"""Flask Blueprint for bot-telegram — webhook (no JWT) + admin bot management.

Single url prefix ``/api/v1/plugins/bot-telegram`` (set via the plugin's
``get_url_prefix``), so routes use relative paths.

  * ``POST /webhook/<bot>`` — **no JWT**; authenticated instead by the
    ``X-Telegram-Bot-Api-Secret-Token`` header matching that bot's
    ``webhook_secret``. A valid update is handed to the provider and dispatched
    through bot-base; an invalid secret is rejected ``401`` with no dispatch.
  * admin (``require_admin`` + ``bot_telegram.manage``): bot CRUD, set-webhook,
    test-send. The bot ``token`` is **always masked** in every response (D4).

Services are built per request from ``db.session``; the config knobs come from
the plugin's ``config_store`` entry.
"""
from typing import Optional

from flask import Blueprint, current_app, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.auth import require_admin, require_auth, require_permission

from plugins.bot_telegram.bot_telegram.models.telegram_bot import TelegramBot
from plugins.bot_telegram.bot_telegram.repositories.telegram_bot_repository import (
    TelegramBotRepository,
)
from plugins.bot_telegram.bot_telegram.services.bot_resolver import (
    TelegramBotResolver,
)
from plugins.bot_telegram.bot_telegram.services.inbound_pipeline import (
    TelegramInboundPipeline,
    build_update_dispatcher,
)
from plugins.bot_telegram.bot_telegram.services.telegram_client import (
    HttpTelegramClient,
)
from plugins.bot_telegram.bot_telegram.services.telegram_provider import (
    DEFAULT_PARSE_MODE,
    NoTelegramBotConfiguredError,
    TelegramProvider,
)
from plugins.bot_telegram.bot_telegram.services.webhook_setup import (
    WebhookSetupService,
)

bot_telegram_bp = Blueprint("bot_telegram", __name__)

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _config_value(key: str, default):
    config_store = getattr(current_app, "config_store", None)
    if config_store is None:
        return default
    config = config_store.get_config("bot-telegram") or {}
    return config.get(key, default)


def _repository() -> TelegramBotRepository:
    return TelegramBotRepository(db.session)


def _telegram_client() -> HttpTelegramClient:
    return HttpTelegramClient()


def _provider() -> TelegramProvider:
    """The request-scoped provider used by the webhook (same class as the
    singleton registered on enable — built here so the webhook can run a
    parse/send round-trip from the current ``db.session``)."""
    resolver = TelegramBotResolver(lambda: db.session)
    parse_mode = str(_config_value("default_parse_mode", DEFAULT_PARSE_MODE))
    client = current_app.config.get("BOT_TELEGRAM_CLIENT") or _telegram_client()
    return TelegramProvider(client, resolver.resolve, default_parse_mode=parse_mode)


# ── webhook (no JWT) ─────────────────────────────────────────────────────────
@bot_telegram_bp.route("/webhook/<bot>", methods=["POST"])
def webhook(bot: str):
    """Receive a Telegram update; authenticate by the bot's webhook secret."""
    bot_row = _repository().find_by_name(bot)
    if bot_row is None or not bot_row.enabled:
        return jsonify({"error": "Unknown bot"}), 404

    supplied_secret = request.headers.get(TELEGRAM_SECRET_HEADER)
    if not bot_row.webhook_secret or supplied_secret != bot_row.webhook_secret:
        return jsonify({"error": "Invalid webhook secret"}), 401

    raw_update = request.get_json(silent=True) or {}
    plugin_manager = getattr(current_app, "plugin_manager", None)
    dispatcher = build_update_dispatcher(db.session, plugin_manager)
    pipeline = TelegramInboundPipeline(_provider(), dispatcher)
    pipeline.handle_raw_update(raw_update)
    db.session.commit()
    return jsonify({"ok": True})


# ── admin: bot CRUD ──────────────────────────────────────────────────────────
@bot_telegram_bp.route("/admin/bots", methods=["GET"])
@require_auth
@require_admin
@require_permission("bot_telegram.manage")
def list_bots():
    bots = _repository().list_all()
    return jsonify({"bots": [bot.to_dict() for bot in bots]})


@bot_telegram_bp.route("/admin/bots", methods=["POST"])
@require_auth
@require_admin
@require_permission("bot_telegram.manage")
def create_bot():
    body = request.get_json(silent=True) or {}
    missing = [field for field in ("name", "username", "token") if not body.get(field)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    repository = _repository()
    make_default = bool(body.get("default", False))
    if make_default:
        _clear_default(repository)
    bot = TelegramBot(
        name=body["name"],
        username=body["username"],
        token=body["token"],
        default=make_default,
        webhook_secret=body.get("webhook_secret"),
        enabled=bool(body.get("enabled", True)),
    )
    repository.save(bot)
    db.session.commit()
    return jsonify({"bot": bot.to_dict()}), 201


@bot_telegram_bp.route("/admin/bots/<bot_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("bot_telegram.manage")
def get_bot(bot_id: str):
    bot = _repository().get(bot_id)
    if bot is None:
        return jsonify({"error": "Bot not found"}), 404
    return jsonify({"bot": bot.to_dict()})


@bot_telegram_bp.route("/admin/bots/<bot_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("bot_telegram.manage")
def update_bot(bot_id: str):
    repository = _repository()
    bot = repository.get(bot_id)
    if bot is None:
        return jsonify({"error": "Bot not found"}), 404

    body = request.get_json(silent=True) or {}
    if "name" in body:
        bot.name = body["name"]
    if "username" in body:
        bot.username = body["username"]
    if body.get("token"):
        bot.token = body["token"]
    if "webhook_secret" in body:
        bot.webhook_secret = body["webhook_secret"]
    if "enabled" in body:
        bot.enabled = bool(body["enabled"])
    if body.get("default"):
        _clear_default(repository)
        bot.default = True
    repository.save(bot)
    db.session.commit()
    return jsonify({"bot": bot.to_dict()})


@bot_telegram_bp.route("/admin/bots/<bot_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("bot_telegram.manage")
def delete_bot(bot_id: str):
    repository = _repository()
    bot = repository.get(bot_id)
    if bot is None:
        return jsonify({"error": "Bot not found"}), 404
    repository.delete(bot)
    db.session.commit()
    return jsonify({"deleted": True})


@bot_telegram_bp.route("/admin/bots/<bot_id>/set-webhook", methods=["POST"])
@require_auth
@require_admin
@require_permission("bot_telegram.manage")
def set_webhook(bot_id: str):
    bot = _repository().get(bot_id)
    if bot is None:
        return jsonify({"error": "Bot not found"}), 404
    body = request.get_json(silent=True) or {}
    public_base_url = body.get("public_base_url") or _config_value(
        "public_base_url", ""
    )
    if not public_base_url:
        return jsonify({"error": "public_base_url is required"}), 400
    result = WebhookSetupService(_telegram_client()).set_webhook(public_base_url, bot)
    return jsonify({"ok": True, "telegram": result})


@bot_telegram_bp.route("/admin/bots/<bot_id>/test", methods=["POST"])
@require_auth
@require_admin
@require_permission("bot_telegram.manage")
def test_bot(bot_id: str):
    bot = _repository().get(bot_id)
    if bot is None:
        return jsonify({"error": "Bot not found"}), 404
    body = request.get_json(silent=True) or {}
    chat_id = body.get("chat_id")
    if not chat_id:
        return jsonify({"error": "chat_id is required"}), 400
    text = body.get("text", "Test message from vbwd.")

    from plugins.bot_base.bot_base.types import BotReply, ChatRef

    provider = _named_provider(bot.name)
    provider.send(BotReply(text=text), to=ChatRef("telegram", str(chat_id)))
    return jsonify({"ok": True})


# ── helpers ──────────────────────────────────────────────────────────────────
def _clear_default(repository: TelegramBotRepository) -> None:
    current_default = repository.find_default()
    if current_default is not None:
        current_default.default = False
        repository.save(current_default)


def _named_provider(name: Optional[str]) -> TelegramProvider:
    """Provider bound to a specific bot name (used by the admin test-send)."""
    resolver = TelegramBotResolver(lambda: db.session)
    parse_mode = str(_config_value("default_parse_mode", DEFAULT_PARSE_MODE))
    client = current_app.config.get("BOT_TELEGRAM_CLIENT") or _telegram_client()
    return TelegramProvider(
        client, lambda _name: resolver.resolve(name), default_parse_mode=parse_mode
    )


__all__ = ["bot_telegram_bp", "NoTelegramBotConfiguredError"]

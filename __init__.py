"""bot-telegram plugin — the first ``IMessengerProvider`` (reference adapter, S45.1).

It proves the bot-base SPI end-to-end: on enable it registers its repository as a
DI provider AND self-registers a :class:`TelegramProvider` into bot-base's
``messenger_provider_registry`` (Open/Closed — bot-base is untouched). It also
starts the dev long-poll worker, **guarded out of TESTING** (booking /
subscription scheduler pattern) so CI never spawns it; the webhook stays the
production inbound path.

The plugin class lives **here** (not re-exported); ``dependencies=["bot-base"]``
makes the provider-registry dependency explicit.
"""
from typing import Any, Dict, Optional, TYPE_CHECKING

from flask import current_app

from vbwd.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from flask import Blueprint

    from plugins.bot_telegram.bot_telegram.services.poll_worker import (
        TelegramPollWorker,
    )


DEFAULT_CONFIG: Dict[str, Any] = {
    "debug_mode": False,
    # Telegram ``parse_mode`` applied to every outbound message ("HTML"/"MarkdownV2").
    "default_parse_mode": "HTML",
    # Dev long-poll worker cadence between getUpdates passes, in seconds.
    "poll_interval_seconds": 2,
    # Public base URL used by the set-webhook helper (prod inbound path).
    "public_base_url": "",
}


class BotTelegramPlugin(BasePlugin):
    """Telegram adapter: encrypted-bot model, provider, webhook + dev poll worker."""

    def __init__(self) -> None:
        super().__init__()
        self._poll_worker: Optional["TelegramPollWorker"] = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="bot-telegram",
            version="1.0.0",
            author="VBWD Team",
            description=(
                "Telegram messenger provider for the bot bridge: normalizes "
                "Telegram updates to neutral DTOs, renders inline keyboards, "
                "and self-registers into bot-base's provider registry."
            ),
            dependencies=["bot-base"],
        )

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self) -> Optional["Blueprint"]:
        from plugins.bot_telegram.bot_telegram.routes import bot_telegram_bp

        return bot_telegram_bp

    def get_url_prefix(self) -> Optional[str]:
        return "/api/v1/plugins/bot-telegram"

    @property
    def admin_permissions(self):
        return [
            {
                "key": "bot_telegram.manage",
                "label": "Manage Telegram bots",
                "group": "Bot",
            },
        ]

    def on_enable(self) -> None:
        from vbwd.extensions import db
        from vbwd.plugins.di_helpers import register_repositories
        from plugins.bot_telegram.bot_telegram.repositories.telegram_bot_repository import (  # noqa: E501
            TelegramBotRepository,
        )
        from plugins.bot_telegram.bot_telegram.services.bot_resolver import (
            TelegramBotResolver,
        )
        from plugins.bot_telegram.bot_telegram.services.telegram_client import (
            HttpTelegramClient,
        )
        from plugins.bot_telegram.bot_telegram.services.telegram_provider import (
            DEFAULT_PARSE_MODE,
            TelegramProvider,
        )

        container = getattr(current_app, "container", None)
        if container is None:
            return

        register_repositories(
            container,
            {"bot_telegram_bot_repository": TelegramBotRepository},
        )

        registry = getattr(container, "messenger_provider_registry", None)
        if registry is None:
            return  # bot-base not enabled; nothing to self-register into.

        parse_mode = str(self._config_value("default_parse_mode", DEFAULT_PARSE_MODE))
        client = current_app.config.get("BOT_TELEGRAM_CLIENT") or HttpTelegramClient()
        resolver = TelegramBotResolver(lambda: db.session)
        provider = TelegramProvider(
            client, resolver.resolve, default_parse_mode=parse_mode
        )
        registry().register(provider)

        self._maybe_start_poll_worker(client)

    def on_disable(self) -> None:
        from vbwd.plugins.di_helpers import unregister_repositories

        if self._poll_worker is not None:
            self._poll_worker.stop()
            self._poll_worker = None

        container = getattr(current_app, "container", None)
        if container is None:
            return
        unregister_repositories(container, ["bot_telegram_bot_repository"])
        registry = getattr(container, "messenger_provider_registry", None)
        if registry is not None:
            registry().unregister("telegram")

    # ── helpers ──────────────────────────────────────────────────────────────
    def _config_value(self, key: str, default):
        return self._config.get(key, default) if self._config else default

    def _maybe_start_poll_worker(self, client) -> None:
        """Start the dev long-poll worker unless running under TESTING.

        Mirrors the booking / subscription scheduler guard so the test suite and
        CI never spawn a background poller; the webhook is the production path.
        """
        if current_app.config.get("TESTING"):
            return

        from plugins.bot_telegram.bot_telegram.services.bot_resolver import (
            TelegramBotResolver,
        )
        from plugins.bot_telegram.bot_telegram.services.inbound_pipeline import (
            TelegramInboundPipeline,
            build_update_dispatcher,
        )
        from plugins.bot_telegram.bot_telegram.services.poll_worker import (
            TelegramPollWorker,
        )
        from plugins.bot_telegram.bot_telegram.services.telegram_provider import (
            DEFAULT_PARSE_MODE,
            TelegramProvider,
        )

        app = current_app._get_current_object()
        plugin_manager = getattr(current_app, "plugin_manager", None)
        if plugin_manager is None:
            return
        parse_mode = str(self._config_value("default_parse_mode", DEFAULT_PARSE_MODE))
        poll_interval = int(self._config_value("poll_interval_seconds", 2))

        def build_pipeline() -> TelegramInboundPipeline:
            from vbwd.extensions import db

            resolver = TelegramBotResolver(lambda: db.session)
            provider = TelegramProvider(
                client, resolver.resolve, default_parse_mode=parse_mode
            )
            dispatcher = build_update_dispatcher(db.session, plugin_manager)
            return TelegramInboundPipeline(provider, dispatcher)

        self._poll_worker = TelegramPollWorker(
            app,
            client=client,
            build_pipeline=build_pipeline,
            poll_interval_seconds=poll_interval,
        )
        self._poll_worker.start()

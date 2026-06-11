"""TelegramProvider — the only Telegram-aware class (an ``IMessengerProvider``).

It normalizes a native Telegram ``Update`` (a ``message`` or a ``callback_query``)
into a neutral :class:`BotInbound`, renders a neutral :class:`BotReply` as a
``sendMessage`` payload (choices → an inline keyboard whose ``callback_data`` is
the choice's opaque ``action_data``), and builds the ``t.me/<username>`` deep
link. All transport goes through an injected :class:`ITelegramClient`, so the
provider is substitutable and testable with the in-memory fake (Liskov / DI).

``provider_id`` is the constant ``"telegram"`` — the id consumers and bot-base
route by. The provider is the *single* place Telegram wire shapes are known;
bot-base and consumers never see a ``Telegram*`` field.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from plugins.bot_base.bot_base.types import (
    BotInbound,
    BotReply,
    ChatRef,
)
from plugins.bot_telegram.bot_telegram.models.telegram_bot import TelegramBot
from plugins.bot_telegram.bot_telegram.services.telegram_client import (
    ITelegramClient,
)

PROVIDER_ID = "telegram"
DEEPLINK_TEMPLATE = "t.me/{username}?start={token}"
DEFAULT_PARSE_MODE = "HTML"


class NoTelegramBotConfiguredError(LookupError):
    """Raised when no matching (default or named) enabled bot is configured.

    A clear typed error (never a silent ``None``) so a misconfigured call site
    surfaces loudly instead of dropping the message.
    """


class TelegramProvider:
    """Telegram adapter implementing the ``IMessengerProvider`` SPI.

    ``resolve_bot`` is injected (DI) so the provider stays free of session /
    repository wiring: it is a callable taking an optional bot name and
    returning the :class:`TelegramBot` to act through (or raising
    :class:`NoTelegramBotConfiguredError`).
    """

    provider_id: str = PROVIDER_ID

    def __init__(
        self,
        client: ITelegramClient,
        resolve_bot: Callable[[Optional[str]], TelegramBot],
        *,
        default_parse_mode: str = DEFAULT_PARSE_MODE,
    ) -> None:
        self._client = client
        self._resolve_bot = resolve_bot
        self._default_parse_mode = default_parse_mode

    # ── inbound ───────────────────────────────────────────────────────────────
    def parse_update(self, raw: dict) -> BotInbound:
        """Normalize a Telegram ``Update`` (message or callback_query)."""
        callback_query = raw.get("callback_query")
        if callback_query is not None:
            return self._parse_callback_query(callback_query)
        return self._parse_message(raw.get("message") or {})

    def _parse_message(self, message: Dict[str, Any]) -> BotInbound:
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id", ""))
        sender_ref = str(sender.get("id", ""))
        text = message.get("text")
        command, args = self._split_command(text)
        return BotInbound(
            provider_id=self.provider_id,
            chat_ref=ChatRef(provider_id=self.provider_id, chat_id=chat_id),
            sender_ref=sender_ref,
            text=text,
            command=command,
            args=args,
        )

    def _parse_callback_query(self, callback_query: Dict[str, Any]) -> BotInbound:
        sender = callback_query.get("from") or {}
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        sender_ref = str(sender.get("id", ""))
        return BotInbound(
            provider_id=self.provider_id,
            chat_ref=ChatRef(provider_id=self.provider_id, chat_id=chat_id),
            sender_ref=sender_ref,
            action_data=callback_query.get("data"),
        )

    @staticmethod
    def _split_command(text: Optional[str]):
        """Split ``/draw a b`` into ``("draw", ["a", "b"])``; else ``(None, [])``."""
        if not text or not text.startswith("/"):
            return None, []
        parts = text.strip().split()
        command_token = parts[0][1:]
        # Telegram allows ``/cmd@BotName`` — keep only the bare command.
        command = command_token.split("@", 1)[0]
        return command, parts[1:]

    # ── outbound ──────────────────────────────────────────────────────────────
    def send(self, reply: BotReply, *, to: ChatRef) -> None:
        """Render ``reply`` as a ``sendMessage`` payload and deliver it."""
        bot = self._resolve_bot(None)
        payload: Dict[str, Any] = {
            "chat_id": to.chat_id,
            "text": reply.text,
            "parse_mode": self._default_parse_mode,
        }
        keyboard = self._render_inline_keyboard(reply)
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        self._client.send_message(bot.token, payload)

    @staticmethod
    def _render_inline_keyboard(
        reply: BotReply,
    ) -> Optional[Dict[str, Any]]:
        """Render ``reply.choices`` as a one-button-per-row inline keyboard."""
        if not reply.choices:
            return None
        rows: List[List[Dict[str, str]]] = [
            [{"text": choice.label, "callback_data": choice.action_data}]
            for choice in reply.choices
        ]
        return {"inline_keyboard": rows}

    # ── linking ───────────────────────────────────────────────────────────────
    def build_link_deeplink(self, token: str) -> Optional[str]:
        """Return ``t.me/<username>?start=<token>`` for the default bot."""
        try:
            bot = self._resolve_bot(None)
        except NoTelegramBotConfiguredError:
            return None
        return DEEPLINK_TEMPLATE.format(username=bot.username, token=token)

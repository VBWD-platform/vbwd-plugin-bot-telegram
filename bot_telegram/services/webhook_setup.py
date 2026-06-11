"""Webhook setup helper — register a bot's Telegram webhook (prod inbound path).

Telegram pushes updates to ``<webhook_base>/api/v1/plugins/bot-telegram/webhook/
<bot>`` and echoes the bot's ``webhook_secret`` in the
``X-Telegram-Bot-Api-Secret-Token`` header, which the webhook route validates.
This helper decrypts the bot's token only to make the ``setWebhook`` call.
"""
from __future__ import annotations

from plugins.bot_telegram.bot_telegram.models.telegram_bot import TelegramBot
from plugins.bot_telegram.bot_telegram.services.telegram_client import (
    ITelegramClient,
)

WEBHOOK_PATH_TEMPLATE = "/api/v1/plugins/bot-telegram/webhook/{bot}"


class WebhookSetupService:
    """Register a Telegram webhook for a configured bot."""

    def __init__(self, client: ITelegramClient) -> None:
        self._client = client

    def webhook_url(self, public_base_url: str, bot: TelegramBot) -> str:
        base = public_base_url.rstrip("/")
        return base + WEBHOOK_PATH_TEMPLATE.format(bot=bot.name)

    def set_webhook(self, public_base_url: str, bot: TelegramBot) -> dict:
        url = self.webhook_url(public_base_url, bot)
        return self._client.set_webhook(bot.token, url, bot.webhook_secret)

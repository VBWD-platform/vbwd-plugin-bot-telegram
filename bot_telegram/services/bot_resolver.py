"""Resolve the :class:`TelegramBot` a provider call should act through.

The :class:`TelegramProvider` is a process-wide singleton (registered on enable),
but a bot row is read per call from the request-scoped ``db.session``. This
resolver closes over a session factory so the provider holds a plain
``Callable[[Optional[str]], TelegramBot]`` and stays free of repository wiring
(DI / single responsibility). The encrypted token is decrypted transparently by
the ORM only when the row is loaded here — never earlier, never stored decrypted.
"""
from __future__ import annotations

from typing import Callable, Optional

from plugins.bot_telegram.bot_telegram.models.telegram_bot import TelegramBot
from plugins.bot_telegram.bot_telegram.repositories.telegram_bot_repository import (
    TelegramBotRepository,
)
from plugins.bot_telegram.bot_telegram.services.telegram_provider import (
    NoTelegramBotConfiguredError,
)


class TelegramBotResolver:
    """Resolve the default (or a named) enabled bot via a fresh session."""

    def __init__(self, session_factory: Callable[[], object]) -> None:
        self._session_factory = session_factory

    def resolve(self, name: Optional[str] = None) -> TelegramBot:
        repository = TelegramBotRepository(self._session_factory())
        bot = (
            repository.find_by_name(name)
            if name is not None
            else repository.find_default()
        )
        if bot is None or not bot.enabled:
            raise NoTelegramBotConfiguredError(
                f"No enabled Telegram bot configured for "
                f"{'name ' + name if name else 'the default slot'}."
            )
        return bot

"""Data access for ``bot_telegram_bot`` rows."""
from typing import List, Optional

from plugins.bot_telegram.bot_telegram.models.telegram_bot import TelegramBot


class TelegramBotRepository:
    """Thin wrapper over the SQLAlchemy session for :class:`TelegramBot`."""

    def __init__(self, session) -> None:
        self._session = session

    def get(self, bot_id) -> Optional[TelegramBot]:
        return self._session.get(TelegramBot, bot_id)

    def find_by_name(self, name: str) -> Optional[TelegramBot]:
        return (
            self._session.query(TelegramBot)
            .filter(TelegramBot.name == name)
            .one_or_none()
        )

    def find_default(self) -> Optional[TelegramBot]:
        return (
            self._session.query(TelegramBot)
            .filter(TelegramBot.default.is_(True))
            .first()
        )

    def list_all(self) -> List[TelegramBot]:
        return self._session.query(TelegramBot).order_by(TelegramBot.created_at).all()

    def list_enabled(self) -> List[TelegramBot]:
        return (
            self._session.query(TelegramBot).filter(TelegramBot.enabled.is_(True)).all()
        )

    def save(self, bot: TelegramBot) -> TelegramBot:
        self._session.add(bot)
        self._session.flush()
        return bot

    def delete(self, bot: TelegramBot) -> None:
        self._session.delete(bot)
        self._session.flush()

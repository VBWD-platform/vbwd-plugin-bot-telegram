"""SQLAlchemy models for the bot-telegram adapter.

Importing this package registers ``bot_telegram_bot`` with SQLAlchemy so
``db.create_all()`` / the plugin migration build it alongside core.
"""
from plugins.bot_telegram.bot_telegram.models.telegram_bot import TelegramBot

__all__ = ["TelegramBot"]

"""TelegramBot — one configured Telegram bot (BotFather token, encrypted).

A single deployment may run several Telegram bots; exactly one is marked
``default`` so an outbound ``send`` without a named bot resolves deterministically.

Secrets (D4): the BotFather ``token`` is encrypted at rest via the
:class:`~vbwd.utils.crypto.EncryptedString` ``TypeDecorator`` — it is decrypted
only at call time inside :class:`TelegramProvider` and is **never** placed in any
API response (the admin routes mask it as ``1234****``). ``username`` is the
bot's public ``@handle`` from BotFather and drives the ``t.me/<username>`` deep
link (the ``name`` field is a human label only — Q2 clarification).
"""
from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.utils.crypto import EncryptedString

TOKEN_MASK_VISIBLE_PREFIX = 4
TOKEN_MASK_SUFFIX = "****"


def mask_token(token: str) -> str:
    """Return a masked rendering of a bot token (``1234****``) for responses.

    Never returns the secret tail. An empty token masks to just the suffix so
    callers always get a non-secret, non-empty string.
    """
    if not token:
        return TOKEN_MASK_SUFFIX
    return f"{token[:TOKEN_MASK_VISIBLE_PREFIX]}{TOKEN_MASK_SUFFIX}"


class TelegramBot(BaseModel):
    """A configured Telegram bot: human label, public handle, encrypted token."""

    __tablename__ = "bot_telegram_bot"

    name = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(255), nullable=False)
    token = db.Column(EncryptedString(), nullable=False)
    default = db.Column(db.Boolean, nullable=False, default=False)
    webhook_secret = db.Column(db.String(255), nullable=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self) -> dict:
        """Serialize for API responses — the token is ALWAYS masked (D4)."""
        return {
            "id": str(self.id),
            "name": self.name,
            "username": self.username,
            "token": mask_token(self.token or ""),
            "default": bool(self.default),
            "enabled": bool(self.enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

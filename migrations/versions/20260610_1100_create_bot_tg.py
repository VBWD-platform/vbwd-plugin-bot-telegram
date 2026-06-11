"""S45.1 — create the bot_telegram_bot table.

One table for the Telegram adapter: a configured bot (human label ``name``,
public ``@handle`` ``username``, encrypted BotFather ``token``, ``default``
flag, ``webhook_secret``, ``enabled``).

Anchored on the bot_base root revision — bot-telegram declares
``dependencies=["bot-base"]``, so bot_base's migration is always present, and
anchoring there keeps the chain resolvable for the exact plugin set
([[project_migration_graph_fragmentation]]). Revision id ≤ 32 chars
([[feedback_plugin_migrations_in_plugin]]). Validated up → down → up.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260610_1100_create_bot_tg"
down_revision = "20260610_1000_create_bot_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_telegram_bot",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        # Encrypted at rest (EncryptedString → Text); never stored plaintext.
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("webhook_secret", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("name", name="uq_bot_telegram_bot_name"),
    )


def downgrade() -> None:
    op.drop_table("bot_telegram_bot")

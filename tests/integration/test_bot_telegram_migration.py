"""Migration up/down/up for the bot_telegram_bot table (real PostgreSQL).

Loads the migration module directly and runs it through alembic's Operations
context, isolated in a rolled-back transaction (so the shared test DB the other
specs use is left untouched). The conftest ``create_all`` already built the
table, so it is dropped first to exercise a clean upgrade. Validates the chain
anchors on the bot_base revision (declared dependency) and the id is ≤ 32 chars.
"""
import importlib.util
import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect


# This migration spec opens its OWN connection + transaction and rolls back
# itself, so it must run WITHOUT the autouse rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection). See conftest ``no_db_isolation``.
pytestmark = pytest.mark.no_db_isolation


def _load_migration():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "migrations",
        "versions",
        "20260610_1100_create_bot_tg.py",
    )
    spec = importlib.util.spec_from_file_location("create_bot_tg", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()
TABLE = "bot_telegram_bot"


def _has_table(connection) -> bool:
    return TABLE in set(inspect(connection).get_table_names())


@pytest.fixture
def migration_connection(app):
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    operations = Operations(MigrationContext.configure(connection))
    if inspect(connection).has_table(TABLE):
        operations.drop_table(TABLE)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.mark.integration
def test_revision_anchors_on_bot_base_and_id_is_short():
    assert migration.revision == "20260610_1100_create_bot_tg"
    assert migration.down_revision == "20260610_1000_create_bot_base"
    assert len(migration.revision) <= 32


@pytest.mark.integration
def test_up_down_up(migration_connection):
    assert not _has_table(migration_connection)
    context = MigrationContext.configure(migration_connection)
    with Operations.context(context):
        migration.upgrade()
    assert _has_table(migration_connection)
    with Operations.context(context):
        migration.downgrade()
    assert not _has_table(migration_connection)
    with Operations.context(context):
        migration.upgrade()
    assert _has_table(migration_connection)

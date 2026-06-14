"""Shared fixtures for bot_telegram tests.

Unit specs use the in-memory ``ITelegramClient`` + tiny resolver closures and
need no DB. Integration specs request ``app`` / ``client`` and self-bootstrap a
``<dbname>_test`` database with all core + bot-base + bot-telegram tables created
via ``db.create_all()`` (mirrors the bot_base / meinchat harness).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("TESTING", "true")


def _test_db_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, dbname = base.rpartition("/")
    dbname = dbname.split("?")[0]
    return f"{prefix}/{dbname}_test"


def _ensure_test_db(url: str) -> None:
    from sqlalchemy import create_engine, text

    main_url = url.rsplit("/", 1)[0] + "/postgres"
    dbname = url.rsplit("/", 1)[1].split("?")[0]
    engine = create_engine(main_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def app():
    from vbwd.app import create_app
    from vbwd.extensions import db as _db

    test_url = _test_db_url()
    _ensure_test_db(test_url)
    application = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": test_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "RATELIMIT_STORAGE_URL": "memory://",
        }
    )
    with application.app_context():
        import plugins.bot_base.bot_base.models  # noqa: F401
        import plugins.bot_telegram.bot_telegram.models  # noqa: F401

        # Build the full schema exactly ONCE, resetting the public schema first
        # (clearing any table or ENUM type left by a prior crashed run or a
        # sibling suite sharing this ``*_test`` DB). A per-test create_all/
        # drop_all strands standalone PG ENUM types and races other suites on
        # the shared catalog — see vbwd/testing/integration_db.py.
        from vbwd.testing.integration_db import reset_schema_and_create_all

        reset_schema_and_create_all(_db)

    yield application

    with application.app_context():
        _db.engine.dispose()


@pytest.fixture(autouse=True)
def _isolate_test(app):
    """Clear data before each test (the schema is built once per session).

    Without per-test isolation a sibling suite's mid-session schema reset
    (DROP SCHEMA CASCADE) could leave this suite with leftover or missing rows;
    truncating on SETUP makes each test deterministic regardless of run order.
    """
    from vbwd.extensions import db as _db

    with app.app_context():
        from vbwd.testing.integration_db import truncate_all_tables

        truncate_all_tables(_db)
        yield
        _db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()

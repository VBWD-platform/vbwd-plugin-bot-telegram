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


def _ensure_bot_telegram_enabled(flask_app) -> None:
    """Enable bot_telegram (+ peer plugins it needs) so on_enable registrations
    fire. A fresh per-plugin CI clone has no plugins.json, so the plugin is
    discovered-but-not-enabled; bot_base must be enabled first so its
    messenger_provider_registry exists on the container. Idempotent.
    """
    from vbwd.plugins.base import PluginStatus

    manager = getattr(flask_app, "plugin_manager", None)
    if manager is None:
        return
    with flask_app.app_context():
        for plugin_name in ("bot_base", "bot_telegram"):
            plugin = manager.get_plugin(plugin_name)
            if plugin is None or plugin.status == PluginStatus.ENABLED:
                continue
            try:
                manager.enable_plugin(plugin_name)
            except ValueError:
                if plugin.status == PluginStatus.INITIALIZED:
                    plugin.enable()


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

        # Build the schema once per process (create_all, checkfirst — never
        # drops, so it cannot wipe data) and commit baseline reference rows
        # once. Each test then isolates itself via a rolled-back transaction
        # (no TRUNCATE, no DROP) — see vbwd/testing/integration_db.py.
        from vbwd.testing.integration_db import ensure_schema_and_baseline

        ensure_schema_and_baseline(_db)

    _ensure_bot_telegram_enabled(application)

    yield application

    with application.app_context():
        _db.engine.dispose()


@pytest.fixture(autouse=True)
def _isolate_test(app, request):
    """Isolate every test in a rolled-back transaction (self-cleaning, no wipe).

    Autouse so route specs that request only ``client`` are isolated too; nothing
    a test writes persists past it (the rollback IS the cleanup). The schema +
    baseline reference rows are built once in the ``app`` fixture. See
    vbwd/testing/integration_db.py.

    A test marked ``no_db_isolation`` (e.g. the migration spec that opens its own
    connection and rolls back itself) runs WITHOUT the wrapper, keeping
    ``db.engine`` a real Engine.
    """
    from vbwd.extensions import db as _db

    if request.node.get_closest_marker("no_db_isolation") is not None:
        with app.app_context():
            yield
            _db.session.remove()
        return

    with app.app_context():
        from vbwd.testing.integration_db import rollback_isolation

        with rollback_isolation(_db):
            yield


@pytest.fixture
def client(app):
    return app.test_client()

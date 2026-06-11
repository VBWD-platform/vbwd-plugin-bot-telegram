"""Integration: bot-telegram routes — admin CRUD, masking, webhook, round-trip.

Boots the full app (bot-base + bot-telegram enabled via plugins.json) so the
container has the provider registry and the blueprints are mounted. Outbound +
poll transport uses the in-memory fake client injected via app config — no
network. Test data is created only through the admin route / core auth service.
"""
import uuid

import pytest

from vbwd.models.enums import UserRole


def _register_user(app, email: str):
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository

    auth_service = app.container.auth_service()
    unique_email = email.replace("@", f"+{uuid.uuid4().hex[:8]}@")
    result = auth_service.register(email=unique_email, password="BotTgTest123@")
    db.session.commit()
    user = UserRepository(db.session).find_by_id(result.user_id)
    return str(user.id), result.token


def _promote_to_admin(app, user_id: str) -> None:
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository

    repository = UserRepository(db.session)
    user = repository.find_by_id(user_id)
    user.role = UserRole.ADMIN
    db.session.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin_headers(app):
    with app.app_context():
        user_id, token = _register_user(app, "tgadmin@example.com")
        _promote_to_admin(app, user_id)
    return _auth(token)


def _create_bot(app, client, **overrides):
    headers = overrides.pop("headers", None) or _admin_headers(app)
    body = {
        "name": overrides.get("name", f"bot-{uuid.uuid4().hex[:6]}"),
        "username": overrides.get("username", "vbwd_demo_bot"),
        "token": overrides.get("token", "123456789:SECRET_TOKEN_VALUE"),
        "default": overrides.get("default", True),
        "webhook_secret": overrides.get("webhook_secret", "wh-secret"),
        "enabled": overrides.get("enabled", True),
    }
    return client.post(
        "/api/v1/plugins/bot-telegram/admin/bots", json=body, headers=headers
    )


@pytest.fixture(autouse=True)
def _inject_fake_client(app):
    """Route outbound + poll through an in-memory client (no network)."""
    from plugins.bot_telegram.bot_telegram.services.telegram_client import (
        InMemoryTelegramClient,
    )

    fake = InMemoryTelegramClient()
    app.config["BOT_TELEGRAM_CLIENT"] = fake
    yield fake
    app.config.pop("BOT_TELEGRAM_CLIENT", None)


# ── self-registration into bot-base ──────────────────────────────────────────
@pytest.mark.integration
def test_provider_registered_into_bot_base_registry(app):
    from plugins.bot_base.bot_base.ports import IMessengerProvider

    with app.app_context():
        registry = app.container.messenger_provider_registry()
        assert registry.has("telegram")
        provider = registry.get("telegram")
        assert isinstance(provider, IMessengerProvider)
        assert provider.provider_id == "telegram"


# ── admin CRUD + permission ──────────────────────────────────────────────────
@pytest.mark.integration
def test_list_bots_requires_authentication(client):
    response = client.get("/api/v1/plugins/bot-telegram/admin/bots")
    assert response.status_code == 401


@pytest.mark.integration
def test_list_bots_forbidden_for_regular_user(app, client):
    with app.app_context():
        _user_id, token = _register_user(app, "plaintg@example.com")
    response = client.get(
        "/api/v1/plugins/bot-telegram/admin/bots", headers=_auth(token)
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_create_then_get_bot_masks_token(app, client):
    create = _create_bot(app, client, token="987654321:VERY_SECRET")
    assert create.status_code == 201
    payload = create.get_json()["bot"]
    assert payload["token"] == "9876****"
    assert "987654321:VERY_SECRET" not in create.get_data(as_text=True)

    headers = _admin_headers(app)
    listing = client.get("/api/v1/plugins/bot-telegram/admin/bots", headers=headers)
    assert listing.status_code == 200
    assert "987654321:VERY_SECRET" not in listing.get_data(as_text=True)
    for bot in listing.get_json()["bots"]:
        assert bot["token"].endswith("****")


@pytest.mark.integration
def test_update_and_delete_bot(app, client):
    headers = _admin_headers(app)
    created = _create_bot(app, client, headers=headers).get_json()["bot"]

    update = client.put(
        f"/api/v1/plugins/bot-telegram/admin/bots/{created['id']}",
        json={"name": "renamed-bot", "enabled": False},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.get_json()["bot"]["name"] == "renamed-bot"
    assert update.get_json()["bot"]["enabled"] is False

    deleted = client.delete(
        f"/api/v1/plugins/bot-telegram/admin/bots/{created['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True


# ── webhook secret enforcement ───────────────────────────────────────────────
@pytest.mark.integration
def test_webhook_invalid_secret_rejected(app, client):
    headers = _admin_headers(app)
    _create_bot(
        app, client, headers=headers, name="wh-bad", webhook_secret="right-secret"
    )

    response = client.post(
        "/api/v1/plugins/bot-telegram/webhook/wh-bad",
        json={"message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "/hello"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_webhook_valid_secret_dispatches_hello_round_trip(
    app, client, _inject_fake_client
):
    headers = _admin_headers(app)
    _create_bot(
        app,
        client,
        headers=headers,
        name="wh-good",
        username="vbwd_demo_bot",
        webhook_secret="right-secret",
        token="111:HELLO_TOKEN",
    )

    response = client.post(
        "/api/v1/plugins/bot-telegram/webhook/wh-good",
        json={"message": {"chat": {"id": 4242}, "from": {"id": 7}, "text": "/hello"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "right-secret"},
    )
    assert response.status_code == 200

    # The dispatcher's built-in /hello reply was sent back through the fake.
    assert len(_inject_fake_client.sent_messages) == 1
    sent = _inject_fake_client.sent_messages[0]
    assert sent["payload"]["chat_id"] == "4242"
    assert "Hello" in sent["payload"]["text"]

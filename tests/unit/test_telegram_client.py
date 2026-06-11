"""Unit specs for the Bot-API client: fake round-trip + real-client 429 retry."""
from plugins.bot_telegram.bot_telegram.services.telegram_client import (
    HttpTelegramClient,
    ITelegramClient,
    InMemoryTelegramClient,
)


def test_in_memory_client_satisfies_port():
    assert isinstance(InMemoryTelegramClient(), ITelegramClient)
    assert isinstance(HttpTelegramClient(), ITelegramClient)


def test_in_memory_client_records_send_and_replays_updates():
    client = InMemoryTelegramClient()
    client.send_message("tok", {"chat_id": "1", "text": "hi"})
    client.queue_update({"update_id": 7})

    assert client.sent_messages[0]["payload"]["text"] == "hi"
    first = client.get_updates("tok", offset=None, timeout_seconds=0)
    assert first == [{"update_id": 7}]
    # Drained — a second poll returns nothing.
    assert client.get_updates("tok", offset=None, timeout_seconds=0) == []


class _FakeResponse:
    def __init__(self, status_code, json_body, headers=None):
        self.status_code = status_code
        self._json_body = json_body
        self.headers = headers or {}
        self.raised = False

    def json(self):
        return self._json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            self.raised = True
            raise AssertionError(f"HTTP {self.status_code}")


def test_http_client_honors_429_retry_after(monkeypatch):
    """A 429 with ``retry_after`` is slept-on then retried, succeeding next call."""
    responses = [
        _FakeResponse(429, {"parameters": {"retry_after": 2}}),
        _FakeResponse(200, {"ok": True, "result": {"message_id": 1}}),
    ]
    slept = []

    def fake_post(url, json=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(
        "plugins.bot_telegram.bot_telegram.services.telegram_client.requests.post",
        fake_post,
    )
    client = HttpTelegramClient(sleep=lambda seconds: slept.append(seconds))

    result = client.send_message("tok", {"chat_id": "1", "text": "hi"})

    assert result == {"ok": True, "result": {"message_id": 1}}
    assert slept == [2.0]

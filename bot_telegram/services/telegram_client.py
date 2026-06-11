"""ITelegramClient — the thin Bot-API transport seam (and an in-memory fake).

The real client talks to ``https://api.telegram.org/bot<token>/<method>``; the
fake records calls and returns canned updates so the whole adapter round-trip is
testable with no network (TDD-first). Both honor the same narrow Protocol so
:class:`TelegramProvider` never depends on which one it holds (Liskov / DI).

Only the three methods the adapter actually uses are on the port (ISP / no
overengineering): ``send_message``, ``set_webhook``, ``get_updates``.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
RATE_LIMITED_STATUS = 429
MAX_RATE_LIMIT_RETRIES = 3


@runtime_checkable
class ITelegramClient(Protocol):
    """Narrow Bot-API transport contract used by :class:`TelegramProvider`."""

    def send_message(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call ``sendMessage`` with an already-rendered payload."""
        ...

    def set_webhook(
        self, token: str, url: str, secret_token: Optional[str]
    ) -> Dict[str, Any]:
        """Call ``setWebhook`` for this bot's token."""
        ...

    def get_updates(
        self, token: str, offset: Optional[int], timeout_seconds: int
    ) -> List[Dict[str, Any]]:
        """Long-poll ``getUpdates``; return the raw ``result`` update list."""
        ...


class HttpTelegramClient:
    """Real Bot-API client. Honors ``429`` + ``retry_after`` with bounded retries."""

    def __init__(
        self,
        *,
        api_base: str = TELEGRAM_API_BASE,
        request_timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        sleep=time.sleep,
    ) -> None:
        self._api_base = api_base
        self._request_timeout_seconds = request_timeout_seconds
        self._sleep = sleep

    def _method_url(self, token: str, method: str) -> str:
        return f"{self._api_base}/bot{token}/{method}"

    def _post(self, token: str, method: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = self._method_url(token, method)
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            response = requests.post(
                url, json=body, timeout=self._request_timeout_seconds
            )
            if response.status_code == RATE_LIMITED_STATUS:
                retry_after = self._retry_after_seconds(response)
                if attempt < MAX_RATE_LIMIT_RETRIES:
                    self._sleep(retry_after)
                    continue
            response.raise_for_status()
            return response.json()
        # Exhausted retries on 429 — raise the last response's HTTP error.
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _retry_after_seconds(response) -> float:
        body = {}
        try:
            body = response.json()
        except ValueError:
            body = {}
        parameters = body.get("parameters") or {}
        return float(
            parameters.get("retry_after") or response.headers.get("Retry-After") or 1
        )

    def send_message(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(token, "sendMessage", payload)

    def set_webhook(
        self, token: str, url: str, secret_token: Optional[str]
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"url": url}
        if secret_token:
            body["secret_token"] = secret_token
        return self._post(token, "setWebhook", body)

    def get_updates(
        self, token: str, offset: Optional[int], timeout_seconds: int
    ) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {"timeout": timeout_seconds}
        if offset is not None:
            body["offset"] = offset
        result = self._post(token, "getUpdates", body)
        return list(result.get("result", []))


class InMemoryTelegramClient:
    """A no-network ``ITelegramClient`` for tests.

    Records every ``send_message`` / ``set_webhook`` call and replays queued
    updates from ``get_updates`` so the inbound + outbound seams round-trip
    without touching a wire.
    """

    def __init__(self) -> None:
        self.sent_messages: List[Dict[str, Any]] = []
        self.webhook_calls: List[Dict[str, Any]] = []
        self._queued_updates: List[Dict[str, Any]] = []

    def queue_update(self, update: Dict[str, Any]) -> None:
        self._queued_updates.append(update)

    def send_message(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.sent_messages.append({"token": token, "payload": payload})
        return {"ok": True, "result": {"message_id": len(self.sent_messages)}}

    def set_webhook(
        self, token: str, url: str, secret_token: Optional[str]
    ) -> Dict[str, Any]:
        self.webhook_calls.append(
            {"token": token, "url": url, "secret_token": secret_token}
        )
        return {"ok": True, "result": True}

    def get_updates(
        self, token: str, offset: Optional[int], timeout_seconds: int
    ) -> List[Dict[str, Any]]:
        drained = list(self._queued_updates)
        self._queued_updates.clear()
        return drained

"""Long-poll dev worker — the no-public-HTTPS inbound transport (Q2 REQUIRED).

In development there is no public HTTPS URL for Telegram to push webhooks to, so
this worker long-polls ``getUpdates`` for each enabled bot and feeds raw updates
through the same :class:`TelegramInboundPipeline` the webhook uses (DRY). It is
**started only outside TESTING** by the plugin's ``on_enable`` — exactly the
booking / subscription scheduler pattern — so CI and the test suite never spawn
it. The webhook remains the production path.

The worker runs in a daemon thread; each loop pushes a fresh app context and
builds its dispatcher + provider from the request-scoped ``db.session`` so the
encrypted token is decrypted only at call time.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 2
DEFAULT_LONG_POLL_TIMEOUT_SECONDS = 25


class TelegramPollWorker:
    """Background ``getUpdates`` loop over every enabled bot (dev transport)."""

    def __init__(
        self,
        app,
        *,
        client,
        build_pipeline,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        long_poll_timeout_seconds: int = DEFAULT_LONG_POLL_TIMEOUT_SECONDS,
    ) -> None:
        self._app = app
        self._client = client
        self._build_pipeline = build_pipeline
        self._poll_interval_seconds = poll_interval_seconds
        self._long_poll_timeout_seconds = long_poll_timeout_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offsets: Dict[str, int] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="telegram-poll-worker", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception:
                # Keep the dev loop alive across a transient error; log loudly.
                logger.exception("Telegram poll worker iteration failed")
            self._stop_event.wait(self._poll_interval_seconds)

    def _poll_once(self) -> None:
        from vbwd.extensions import db
        from plugins.bot_telegram.bot_telegram.repositories import (
            telegram_bot_repository,
        )

        with self._app.app_context():
            repository = telegram_bot_repository.TelegramBotRepository(db.session)
            for bot in repository.list_enabled():
                self._poll_bot(bot)

    def _poll_bot(self, bot) -> None:
        offset = self._offsets.get(str(bot.id))
        updates = self._client.get_updates(
            bot.token, offset, self._long_poll_timeout_seconds
        )
        pipeline = self._build_pipeline()
        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                self._offsets[str(bot.id)] = update_id + 1
            pipeline.handle_raw_update(update)

"""Per-(provider_id, chat_ref) inbound rate-limit guard.

A small in-memory sliding-window limiter so a single chat cannot flood the
dispatcher. Keyed on ``(provider_id, chat_ref)`` (the neutral chat identity) so
the same guard would serve any provider. Defaults are deliberately generous —
this is a flood-stop, not a quota.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

DEFAULT_MAX_UPDATES = 20
DEFAULT_WINDOW_SECONDS = 10


class InboundRateLimitGuard:
    """Allow at most ``max_updates`` inbound updates per chat per window."""

    def __init__(
        self,
        *,
        max_updates: int = DEFAULT_MAX_UPDATES,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self._max_updates = max_updates
        self._window_seconds = window_seconds
        self._clock = clock
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def allow(self, provider_id: str, chat_ref: str) -> bool:
        """Record a hit; return ``False`` if the chat is over its window budget."""
        now = self._clock()
        window = self._hits[(provider_id, chat_ref)]
        cutoff = now - self._window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._max_updates:
            return False
        window.append(now)
        return True

"""Inbound pipeline — one home for parse → dispatch → send (DRY).

Both transports (the webhook route and the dev long-poll worker) must do the
same three steps with a raw Telegram update: hand it to the provider's
``parse_update``, route it through bot-base's :class:`UpdateDispatcher`, and send
the resulting :class:`BotReply` back through the provider. Keeping that single
sequence here means the two transports cannot drift (§5 DRY).

The dispatcher is *built from bot-base's own pieces* (CommandRegistry,
ConversationService, LinkService, BotLinkRepository) per call from the active
``db.session`` — bot-base does not register the dispatcher in the container, so
this adapter assembles it without modifying bot-base (Open/Closed).
"""
from __future__ import annotations

from plugins.bot_base.bot_base.repositories.bot_link_repository import (
    BotLinkRepository,
)
from plugins.bot_base.bot_base.repositories.bot_link_token_repository import (
    BotLinkTokenRepository,
)
from plugins.bot_base.bot_base.repositories.bot_session_repository import (
    BotSessionRepository,
)
from plugins.bot_base.bot_base.services.command_registry import CommandRegistry
from plugins.bot_base.bot_base.services.conversation_service import (
    ConversationService,
)
from plugins.bot_base.bot_base.services.link_service import LinkService
from plugins.bot_base.bot_base.services.update_dispatcher import UpdateDispatcher
from plugins.bot_base.bot_base.types import BotInbound, BotReply


def build_update_dispatcher(session, plugin_manager) -> UpdateDispatcher:
    """Assemble bot-base's :class:`UpdateDispatcher` from a session + manager."""
    link_repository = BotLinkRepository(session)
    return UpdateDispatcher(
        command_registry=CommandRegistry(plugin_manager),
        conversation_service=ConversationService(BotSessionRepository(session)),
        link_service=LinkService(link_repository, BotLinkTokenRepository(session)),
        link_repository=link_repository,
    )


class TelegramInboundPipeline:
    """Run a raw Telegram update through parse → dispatch → send."""

    def __init__(self, provider, dispatcher, *, rate_limit_guard=None) -> None:
        self._provider = provider
        self._dispatcher = dispatcher
        self._rate_limit_guard = rate_limit_guard

    def handle_raw_update(self, raw: dict) -> BotReply:
        """Process one raw update; return the reply that was sent.

        The reply is sent back to the originating chat through the provider so
        the caller (route/worker) never re-implements delivery.
        """
        inbound: BotInbound = self._provider.parse_update(raw)
        if self._rate_limit_guard is not None and not self._rate_limit_guard.allow(
            inbound.provider_id, inbound.chat_ref.chat_id
        ):
            return BotReply(text="")
        reply = self._dispatcher.dispatch(inbound)
        self._provider.send(reply, to=inbound.chat_ref)
        return reply

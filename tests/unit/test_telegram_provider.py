"""Unit specs for TelegramProvider — parse_update / send / deeplink (no DB, no net).

The provider is driven by an in-memory ``ITelegramClient`` and a tiny resolver
closure standing in for the repository — proving the provider is substitutable
and Telegram-aware in exactly one place (Liskov / DI).
"""
from plugins.bot_base.bot_base.ports import IMessengerProvider
from plugins.bot_base.bot_base.types import BotChoice, BotReply, ChatRef
from plugins.bot_telegram.bot_telegram.services.telegram_client import (
    InMemoryTelegramClient,
)
from plugins.bot_telegram.bot_telegram.services.telegram_provider import (
    NoTelegramBotConfiguredError,
    TelegramProvider,
)


class _Bot:
    """Minimal stand-in for a resolved TelegramBot (token + username)."""

    def __init__(self, token: str = "123:ABC", username: str = "vbwd_bot") -> None:
        self.token = token
        self.username = username


def _provider(bot=None, client=None) -> TelegramProvider:
    resolved = bot if bot is not None else _Bot()

    def resolve(_name):
        if resolved is None:
            raise NoTelegramBotConfiguredError("no bot")
        return resolved

    return TelegramProvider(client or InMemoryTelegramClient(), resolve)


def test_provider_satisfies_messenger_provider_port():
    assert isinstance(_provider(), IMessengerProvider)
    assert _provider().provider_id == "telegram"


def test_parse_update_text_command_maps_to_command_and_args():
    update = {
        "message": {
            "chat": {"id": 555},
            "from": {"id": 999},
            "text": "/draw past present future",
        }
    }
    inbound = _provider().parse_update(update)

    assert inbound.provider_id == "telegram"
    assert inbound.chat_ref == ChatRef(provider_id="telegram", chat_id="555")
    assert inbound.sender_ref == "999"
    assert inbound.command == "draw"
    assert inbound.args == ["past", "present", "future"]
    assert inbound.action_data is None


def test_parse_update_strips_botname_suffix_from_command():
    update = {
        "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "/help@vbwd_bot"}
    }
    inbound = _provider().parse_update(update)
    assert inbound.command == "help"
    assert inbound.args == []


def test_parse_update_plain_text_has_no_command():
    update = {"message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "hello there"}}
    inbound = _provider().parse_update(update)
    assert inbound.command is None
    assert inbound.text == "hello there"


def test_parse_update_callback_query_maps_to_action_data():
    update = {
        "callback_query": {
            "from": {"id": 999},
            "message": {"chat": {"id": 555}},
            "data": "taro:reveal:3",
        }
    }
    inbound = _provider().parse_update(update)

    assert inbound.action_data == "taro:reveal:3"
    assert inbound.chat_ref == ChatRef(provider_id="telegram", chat_id="555")
    assert inbound.sender_ref == "999"
    assert inbound.command is None


def test_send_builds_send_message_payload_to_the_chat():
    client = InMemoryTelegramClient()
    provider = _provider(bot=_Bot(token="tok:1"), client=client)

    provider.send(BotReply(text="Hello!"), to=ChatRef("telegram", "42"))

    assert len(client.sent_messages) == 1
    call = client.sent_messages[0]
    assert call["token"] == "tok:1"
    assert call["payload"]["chat_id"] == "42"
    assert call["payload"]["text"] == "Hello!"
    assert "reply_markup" not in call["payload"]


def test_send_renders_choices_as_inline_keyboard():
    client = InMemoryTelegramClient()
    provider = _provider(client=client)
    reply = BotReply(
        text="Pick one",
        choices=[
            BotChoice(label="Reveal", action_data="taro:reveal:1"),
            BotChoice(label="Cancel", action_data="bot-base:cancel:0"),
        ],
    )

    provider.send(reply, to=ChatRef("telegram", "42"))

    markup = client.sent_messages[0]["payload"]["reply_markup"]
    assert markup == {
        "inline_keyboard": [
            [{"text": "Reveal", "callback_data": "taro:reveal:1"}],
            [{"text": "Cancel", "callback_data": "bot-base:cancel:0"}],
        ]
    }


def test_build_link_deeplink_uses_bot_username():
    provider = _provider(bot=_Bot(username="vbwd_demo_bot"))
    assert provider.build_link_deeplink("tok-123") == (
        "t.me/vbwd_demo_bot?start=tok-123"
    )


def test_build_link_deeplink_returns_none_when_no_bot_configured():
    def resolve(_name):
        raise NoTelegramBotConfiguredError("no bot")

    provider = TelegramProvider(InMemoryTelegramClient(), resolve)
    assert provider.build_link_deeplink("tok-123") is None

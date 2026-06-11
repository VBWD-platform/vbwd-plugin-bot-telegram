"""Unit specs for token masking — the secret never appears in a serialized form."""
from plugins.bot_telegram.bot_telegram.models.telegram_bot import mask_token


def test_mask_token_keeps_only_the_first_four_characters():
    assert mask_token("1234567890:ABCDEF") == "1234****"


def test_mask_token_empty_is_masked_not_blank():
    assert mask_token("") == "****"


def test_mask_token_short_token_still_masked():
    assert mask_token("12") == "12****"

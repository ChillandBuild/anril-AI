"""Opt-out keyword matching for inbound WhatsApp replies."""
import pytest

from app.routes.webhook import _is_opt_out


@pytest.mark.parametrize("body", [
    "stop", "unsubscribe", "ஆர்வம் இல்லை",
    "stop please", "please stop", "stop sending", "stop messages", "not interested",
    "unsubscribe me", "no more messages", "don't message", "dont message", "remove me",
    "வேண்டாம்", "நிறுத்து", "நிறுத்துங்கள்", "ஆர்வமில்லை", "venam", "vendam", "niruthu",
])
def test_stop_words_opt_out(body):
    assert _is_opt_out(body)


@pytest.mark.parametrize("body", ["STOP", "Stop", "  stop  ", "Unsubscribe", "Not Interested",
                                  "please  stop", "Don’t message", "VENAM"])
def test_matching_is_case_space_and_apostrophe_insensitive(body):
    assert _is_opt_out(body)


@pytest.mark.parametrize("body", ["hi", "vanakkam", "how much", "", "stopped",
                                  "don't stop", "i am not interested in the 2bhk, show 3bhk"])
def test_normal_replies_do_not_opt_out(body):
    assert not _is_opt_out(body)


@pytest.mark.parametrize("body", ["stop.", "stop!!"])
def test_known_gap_exact_match_only(body):
    """Matching is whole-message, so punctuated forms fall through to scoring
    rather than triggering a hard opt-out. Documents current behaviour."""
    assert not _is_opt_out(body)

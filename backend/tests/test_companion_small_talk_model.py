"""Small talk on a cheaper model: a character can answer "வணக்கம்" on 3.5 Flash Lite and real questions on
3.8 Flash (migration 283). The question step's needs_docs decides; unknown is never small talk."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.companion.engine import _model_kw, is_small_talk
from app.companion.models import CompanionSettings, CompanionUpdate

STRONG, CHEAP = "google/gemini-3.8-flash", "google/gemini-3.5-flash-lite"
JOTHIDAR = {"model": STRONG, "small_talk_model": CHEAP}
HELLO = SimpleNamespace(needs_docs=False)      # "வணக்கம்"
QUESTION = SimpleNamespace(needs_docs=True)    # "வெளிநாட்டு வேலை கிடைக்குமா?"


def test_small_talk_goes_to_the_cheap_model_and_questions_to_the_main_one():
    assert _model_kw(JOTHIDAR, None, HELLO) == {"model": CHEAP, "fallback": True}
    assert _model_kw(JOTHIDAR, None, QUESTION) == {"model": STRONG, "fallback": True}


def test_no_question_step_means_the_main_model():
    assert not is_small_talk(None)
    assert _model_kw(JOTHIDAR, None, None) == {"model": STRONG, "fallback": True}


def test_without_a_small_talk_model_everything_uses_the_main_model():
    assert _model_kw({"model": STRONG}, None, HELLO) == {"model": STRONG, "fallback": True}


def test_a_removed_small_talk_model_falls_back_to_the_main_model():
    assert _model_kw({**JOTHIDAR, "small_talk_model": "google/gone"}, None, HELLO)["model"] == STRONG


def test_the_playground_pick_wins_over_both():
    assert _model_kw(JOTHIDAR, CHEAP, QUESTION) == {"model": CHEAP}


def test_the_small_talk_model_must_be_a_listed_model_and_can_be_cleared():
    assert CompanionSettings(name="J", small_talk_model=CHEAP).small_talk_model == CHEAP
    with pytest.raises(ValidationError):
        CompanionSettings(name="J", small_talk_model="openai/gpt-x")
    assert CompanionUpdate(small_talk_model=None).changes() == {"small_talk_model": None}


def test_every_listed_model_gets_a_thinking_level_it_accepts():
    """3.8 Flash answered every call with a 400 on "minimal" (live 2026-11-18)."""
    from app.services import ai_reply, gemini_client
    assert gemini_client.thinking_level("gemini-3.8-flash") == "low"
    assert gemini_client.thinking_level("gemini-3.1-flash-lite") == "minimal"
    assert {gemini_client.thinking_level(m.removeprefix("google/")) for m in ai_reply.REPLY_MODELS} <= {"minimal", "low"}

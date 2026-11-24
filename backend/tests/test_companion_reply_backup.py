"""engine._chat: the backup call when Google sits on a reply (reply speed, 2026-11-24).

ai_reply._llm_chat is faked: each call gets its own delay and answer, so no test talks to a model.
"""
import asyncio

import pytest

from app.companion import engine
from app.services import ai_reply

JOTHIDAR = {"id": "jothidar", "model": None}
PROMPT = [{"role": "user", "content": "குரு தசை எப்போ?"}]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def llm(monkeypatch):
    """plan: one (delay, answer) per call, in order; an Exception answer is raised. seen: each call's kwargs."""
    state = {"plan": [], "seen": [], "cancelled": 0}

    async def fake(messages, **kw):
        n = len(state["seen"])
        state["seen"].append({"messages": messages, **kw})
        delay, answer = state["plan"][n]
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            state["cancelled"] += 1
            raise
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(ai_reply, "_llm_chat", fake)
    monkeypatch.setattr(engine, "HEDGE_AFTER_SECONDS", 0.05)
    monkeypatch.setattr(engine, "_backups_out", 0)
    return state


def chat():
    return run(engine._chat(JOTHIDAR, "t1", PROMPT, None, None))


def test_a_normal_reply_makes_one_call_and_no_backup(llm):
    llm["plan"] = [(0.0, "குரு தசை டிசம்பர் 11 முதல்")]
    assert chat() == "குரு தசை டிசம்பர் 11 முதல்" and len(llm["seen"]) == 1


def test_a_stalled_call_gets_one_identical_backup_and_the_first_text_back_wins(llm):
    llm["plan"] = [(2.0, "slow answer"), (0.0, "backup answer")]
    assert chat() == "backup answer"
    first, second = llm["seen"]
    assert first == second                              # same prompt, model, fallback, temperature, purpose
    assert llm["cancelled"] == 1 and engine._backups_out == 0


def test_the_first_call_still_wins_when_it_answers_before_the_backup(llm):
    llm["plan"] = [(0.08, "first answer"), (1.0, "backup answer")]
    assert chat() == "first answer" and llm["cancelled"] == 1


def test_an_empty_answer_waits_for_the_other_call(llm):
    llm["plan"] = [(0.06, ""), (0.12, "backup answer")]
    assert chat() == "backup answer"


def test_both_calls_failing_raises_like_one_call_did(llm):
    llm["plan"] = [(0.06, RuntimeError("google 500")), (0.07, RuntimeError("google 500"))]
    with pytest.raises(RuntimeError):
        chat()
    assert engine._backups_out == 0


def test_one_failed_call_and_one_empty_answer_give_the_empty_answer(llm):
    llm["plan"] = [(0.06, RuntimeError("google 500")), (0.07, "")]
    assert chat() == ""


def test_a_fast_failure_is_raised_without_a_backup(llm):
    llm["plan"] = [(0.0, RuntimeError("bad key"))]
    with pytest.raises(RuntimeError):
        chat()
    assert len(llm["seen"]) == 1


def test_no_backup_when_the_server_already_has_its_backups_out(llm, monkeypatch):
    monkeypatch.setattr(engine, "_backups_out", engine.MAX_BACKUPS)
    llm["plan"] = [(0.1, "slow answer")]
    assert chat() == "slow answer" and len(llm["seen"]) == 1


def test_a_cancelled_reply_leaves_no_call_running(llm):
    llm["plan"] = [(2.0, "slow"), (2.0, "slow")]

    async def go():
        task = asyncio.create_task(engine._chat(JOTHIDAR, "t1", PROMPT, None, None))
        await asyncio.sleep(0.1)          # past the backup point: both calls are out
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
    run(go())
    assert llm["cancelled"] == 2 and engine._backups_out == 0

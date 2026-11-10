"""Card memory upgrade (migration 255): same-day refresh + "earlier today" recap, nightly diary lines,
trait rule. Example person throughout: Karthik and his Infosys interview."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.companion import memory_card as card
from app.companion import memory_refresh, memory_sweep, store
from tests.fake_supabase import FakeSupabase

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)      # 15:30 IST, 10 Nov
TODAY, YESTERDAY = "2026-11-10", "2026-11-09"
YDAY_NOON = datetime(2026, 11, 9, 6, 30, tzinfo=timezone.utc)  # 12:00 IST, 9 Nov


def at(minutes_ago: float, base: datetime = NOW) -> str:
    return (base - timedelta(minutes=minutes_ago)).isoformat()


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    monkeypatch.setattr(card, "ist_today", lambda now=None: (now or NOW).astimezone(card.IST).date())
    state = {"calls": [], "answers": []}

    async def llm(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4):
        state["calls"].append({"system": messages[0]["content"], "user": messages[1]["content"]})
        nxt = state["answers"].pop(0) if state["answers"] else "[]"
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
    monkeypatch.setattr(card.ai_reply, "_llm_chat", llm)

    companion = fake.add("companions", tenant_id="t1", name="Aira", language="ta-en", memory_level=2,
                         memory_engine="card", history_messages=10)
    conv = fake.add("companion_conversations", tenant_id="t1", companion_id=companion["id"],
                    end_user_id="karthik", last_message_at=at(9000))
    conv = next(c for c in fake.rows("companion_conversations") if c["id"] == conv["id"])

    def chat(*turns, base: datetime = NOW):
        """turns: (role, text, minutes_ago from base)."""
        for role, text, ago in turns:
            fake.add("companion_messages", tenant_id="t1", companion_id=companion["id"], conversation_id=conv["id"],
                     end_user_id="karthik", role=role, content=text, created_at=at(ago, base))
            conv["last_message_at"] = max(conv["last_message_at"], at(ago, base))

    return type("Env", (), {"db": fake, "state": state, "companion": companion, "chat": staticmethod(chat)})


def run(coro):
    return asyncio.run(coro)


def facts(env):
    return [f["text"] for f in env.db.rows("companion_memory_facts")]


def state_row(env):
    return next(iter(env.db.rows("companion_memory_state")), {})


# --- prompt and recap cleaning ----------------------------------------------------------------

def test_trait_rule_is_in_every_extraction_prompt():
    night, _ = card.build_extraction_prompt("ta-en", [], [{"role": "user", "content": "hi"}])
    assert "big Vijay fan" in night[0]["content"]
    assert "TODAY'S RECAP" not in night[1]["content"] and night[1]["content"].endswith("JSON list now.")


def test_day_mode_prompt_carries_the_current_recap_and_asks_for_an_object():
    prompt, _ = card.build_extraction_prompt("ta-en", [], [{"role": "user", "content": "It went okay"}],
                                             recap="- Interview at Infosys 3 pm")
    assert '"recap"' in prompt[0]["content"] and "Tanglish" in prompt[0]["content"]
    assert "TODAY'S RECAP SO FAR" in prompt[1]["content"] and "Interview at Infosys 3 pm" in prompt[1]["content"]
    assert prompt[1]["content"].endswith("JSON object now.")


def test_clean_recap_drops_sensitive_lines_not_the_whole_recap_and_caps_at_whole_lines():
    raw = "- Interview at Infosys 3 pm, Whitefield\n* OTP is 482913\n  mom has fever  \n- my aadhaar is safe"
    assert card.clean_recap(raw) == "- Interview at Infosys 3 pm, Whitefield\n- mom has fever"
    long = "\n".join(f"- line {i} " + "x" * 200 for i in range(20))
    out = card.clean_recap(long)
    assert len(out) <= card.RECAP_CAP and out.count("\n") + 1 == 7
    assert card.clean_recap("") is None and card.clean_recap(None) is None


# --- same-day refresh (day mode) --------------------------------------------------------------

DAY_ANSWER = ('{"ops":[{"op":"add","section":"threads","text":"Infosys interview","valid_from":"2026-11-10"}],'
              '"recap":"- Interview at Infosys 3 pm, Whitefield office; nervous\\n- Mom has fever, doctor at 4"}')


def test_day_run_learns_facts_and_stores_the_recap_for_today(env):
    env.chat(("user", "Interview at Infosys today, 3 pm, Whitefield office", 30), ("assistant", "All the best!", 30))
    env.state["answers"].append(DAY_ANSWER)
    out = run(memory_sweep._sweep_pair(env.companion, "karthik", None, 0, at(30), NOW, mode="day"))
    assert out == "ok" and facts(env) == ["Infosys interview"]
    row = state_row(env)
    assert row["today_recap"].startswith("- Interview at Infosys 3 pm") and row["recap_day"] == TODAY
    assert row["recap_through"] == at(30) and row["last_message_at"] == at(30)


def test_day_run_passes_todays_recap_on_but_not_yesterdays(env):
    run(store.set_recap("t1", env.companion["id"], "karthik", "- old from yesterday", YESTERDAY, at(2000)))
    env.chat(("user", "hi", 5), ("assistant", "hello", 5))
    run(memory_sweep._sweep_pair(env.companion, "karthik", None, 0, at(5), NOW, mode="day"))
    assert "old from yesterday" not in env.state["calls"][0]["user"]
    run(store.set_recap("t1", env.companion["id"], "karthik", "- interview at 3", TODAY, at(5)))
    env.chat(("user", "it went okay", 2), ("assistant", "super", 2))
    run(memory_sweep._sweep_pair(env.companion, "karthik", at(5), 0, at(2), NOW, mode="day"))
    assert "interview at 3" in env.state["calls"][1]["user"]


def test_day_run_failure_counts_no_failed_night_and_keeps_the_watermark(env):
    env.chat(("user", "hi", 5), ("assistant", "hello", 5))
    env.state["answers"].append(RuntimeError("gemini down"))
    out = run(memory_sweep._sweep_pair(env.companion, "karthik", None, 0, at(5), NOW, mode="day"))
    assert out == "failed" and env.db.rows("companion_memory_state") == []


def test_a_plain_list_answer_in_day_mode_keeps_the_old_recap(env):
    run(store.set_recap("t1", env.companion["id"], "karthik", "- interview at 3", TODAY, at(50)))
    env.chat(("user", "lunch done", 5), ("assistant", "nice", 5))
    env.state["answers"].append("[]")
    run(memory_sweep._sweep_pair(env.companion, "karthik", None, 0, at(5), NOW, mode="day"))
    assert state_row(env)["today_recap"] == "- interview at 3"


# --- the trigger after each reply -------------------------------------------------------------

def test_refresh_runs_only_when_unread_messages_outgrow_history(env, monkeypatch):
    monkeypatch.setattr(memory_refresh, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    env.chat(*[("user", f"msg {i}", 60 - i) for i in range(10)])
    assert run(memory_refresh._refresh(env.companion, "karthik")) == "not_needed"
    assert env.state["calls"] == []
    env.chat(("user", "Interview at Infosys 3 pm", 40))
    env.state["answers"].append(DAY_ANSWER)
    assert run(memory_refresh._refresh(env.companion, "karthik")) == "ok"
    assert len(env.state["calls"]) == 1 and state_row(env)["recap_day"] == TODAY


def test_schedule_ignores_level1_and_runs_one_refresh_per_pair(monkeypatch):
    started = []

    async def fake_refresh(companion, end_user_id):
        started.append(end_user_id)
        await asyncio.sleep(0.01)
        return "ok"
    monkeypatch.setattr(memory_refresh, "_refresh", fake_refresh)

    async def main():
        memory_refresh.schedule({"id": "c1", "memory_level": 1}, "karthik")
        memory_refresh.schedule({"id": "c2", "memory_level": 2}, "karthik")
        memory_refresh.schedule({"id": "c2", "memory_level": 2}, "karthik")  # already running
        assert ("c2", "karthik") in memory_refresh._running
        await asyncio.gather(*memory_refresh._tasks)
        assert ("c2", "karthik") not in memory_refresh._running and not memory_refresh._tasks
    run(main())
    assert started == ["karthik"]


def test_the_reply_does_not_wait_for_the_refresh(monkeypatch):
    gate = None

    async def slow_refresh(companion, end_user_id):
        await gate.wait()
        return "ok"
    monkeypatch.setattr(memory_refresh, "_refresh", slow_refresh)

    async def main():
        nonlocal gate
        gate = asyncio.Event()
        memory_refresh.schedule({"id": "c3", "memory_level": 2}, "karthik")  # returns at once
        assert len(memory_refresh._tasks) == 1
        gate.set()
        await asyncio.gather(*memory_refresh._tasks)
    run(main())


# --- prompt context ---------------------------------------------------------------------------

def test_context_shows_recap_only_on_its_day_then_recent_days_newest_first(env):
    cid = env.companion["id"]
    run(store.add_fact("t1", cid, "karthik", "profile", "works at TCS", None))
    for day, text in [("2026-11-07", "talked about Divya's wedding"), ("2026-11-09", "nervous about interview"),
                      ("2026-11-01", "first chat")]:
        run(store.upsert_diary("t1", cid, "karthik", day, text))
    run(store.set_recap("t1", cid, "karthik", "- Interview at Infosys 3 pm", TODAY, at(30)))
    ctx = run(card.MemoryCard().context_for("t1", cid, "karthik", "hi"))
    assert ctx.index("works at TCS") < ctx.index("Earlier today:") < ctx.index("Recent days:")
    assert "- 9 Nov: nervous about interview\n- 7 Nov: talked about Divya's wedding\n- 1 Nov: first chat" in ctx
    run(store.set_recap("t1", cid, "karthik", "- stale", YESTERDAY, at(2000)))
    assert "Earlier today" not in run(card.MemoryCard().context_for("t1", cid, "karthik", "hi"))


def test_recent_days_are_capped_at_whole_lines_and_exclude_today(env):
    cid = env.companion["id"]
    for i in range(1, 9):
        run(store.upsert_diary("t1", cid, "karthik", f"2026-11-{i:02d}", f"day {i} " + "y" * 150))
    run(store.upsert_diary("t1", cid, "karthik", TODAY, "today's line"))
    block = run(card.day_context("t1", cid, "karthik", date(2026, 11, 10)))
    assert "today's line" not in block and len(block) <= card.DIARY_CAP
    assert block.splitlines()[1].startswith("- 8 Nov: day 8")


# --- nightly diary pass ------------------------------------------------------------------------

def test_diary_written_for_yesterday_with_three_user_messages(env):
    env.chat(*[(r, f"{r} {i}", 60 - i) for i in range(3) for r in ("user", "assistant")], base=YDAY_NOON)
    env.state["answers"].append('{"diary": "Infosys interview went okay, waiting for result"}')
    counts = run(memory_sweep._diary_pass(NOW))
    assert counts == {"diary": 1}
    rows = env.db.rows("companion_memory_diary")
    assert [(r["day"], r["text"]) for r in rows] == [(YESTERDAY, "Infosys interview went okay, waiting for result")]
    assert run(memory_sweep._diary_pass(NOW)) == {} and len(env.state["calls"]) == 1  # once per day


def test_a_hi_ok_day_writes_no_diary_and_makes_no_ai_call(env):
    env.chat(("user", "hi", 30), ("assistant", "hello", 30), ("user", "ok", 20), base=YDAY_NOON)
    assert run(memory_sweep._diary_pass(NOW)) == {} and env.state["calls"] == []


def test_diary_uses_the_recap_plus_only_later_messages_and_clears_the_recap(env):
    cid = env.companion["id"]
    env.chat(("user", "covered by recap", 120), base=YDAY_NOON)
    env.chat(("user", "after the recap", 10), base=YDAY_NOON)
    run(store.set_recap("t1", cid, "karthik", "- Interview at Infosys 3 pm", YESTERDAY, at(60, YDAY_NOON)))
    env.state["answers"].append('{"diary": "interview day"}')
    assert run(memory_sweep._diary_pass(NOW)) == {"diary": 1}
    sent = env.state["calls"][0]["user"]
    assert "Interview at Infosys 3 pm" in sent and "after the recap" in sent and "covered by recap" not in sent
    assert state_row(env)["today_recap"] is None


def test_todays_recap_survives_the_diary_pass(env):
    env.chat(("user", "chat at 01:00 IST today", 60))
    run(store.set_recap("t1", env.companion["id"], "karthik", "- today's note", TODAY, at(60)))
    run(memory_sweep._diary_pass(NOW))
    assert state_row(env)["today_recap"] == "- today's note"


def test_sensitive_or_empty_diary_is_not_saved(env):
    env.chat(*[("user", f"u{i}", 60 - i) for i in range(3)], base=YDAY_NOON)
    env.state["answers"].append('{"diary": "his OTP was 482913"}')
    assert run(memory_sweep._diary_pass(NOW)) == {}
    assert env.db.rows("companion_memory_diary") == []


def test_diary_older_than_90_days_is_pruned(env):
    cid = env.companion["id"]
    run(store.upsert_diary("t1", cid, "karthik", "2026-08-01", "too old"))
    run(store.upsert_diary("t1", cid, "karthik", "2026-08-20", "kept"))
    env.chat(*[("user", f"u{i}", 60 - i) for i in range(3)], base=YDAY_NOON)
    env.state["answers"].append('{"diary": "a day"}')
    run(memory_sweep._diary_pass(NOW))
    assert sorted(r["text"] for r in env.db.rows("companion_memory_diary")) == ["a day", "kept"]


def test_a_failed_diary_call_is_counted_and_does_not_stop_the_sweep(env):
    env.chat(*[("user", f"u{i}", 60 - i) for i in range(3)], base=YDAY_NOON)
    env.state["answers"].append(RuntimeError("gemini down"))
    assert run(memory_sweep._diary_pass(NOW)) == {"diary_failed": 1}


def test_forget_me_during_a_recap_only_diary_call_writes_nothing(env, monkeypatch):
    cid = env.companion["id"]
    env.chat(("user", "all covered", 120), base=YDAY_NOON)
    run(store.set_recap("t1", cid, "karthik", "- Interview at Infosys 3 pm", YESTERDAY, at(100, YDAY_NOON)))

    async def forget_mid_call(*args, **kwargs):
        await store.forget_memory("t1", "karthik")
        return "interview day"
    monkeypatch.setattr(card, "write_diary", forget_mid_call)
    assert run(memory_sweep._diary_pass(NOW)) == {"forgotten": 1}
    assert env.db.rows("companion_memory_diary") == []


def test_forget_me_deletes_diary_and_recap(env):
    cid = env.companion["id"]
    run(store.upsert_diary("t1", cid, "karthik", YESTERDAY, "a day"))
    run(store.set_recap("t1", cid, "karthik", "- note", TODAY, at(5)))
    run(store.forget_memory("t1", "karthik"))
    assert env.db.rows("companion_memory_diary") == [] and env.db.rows("companion_memory_state") == []

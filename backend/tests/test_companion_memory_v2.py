"""Card memory v2 (migration 256): the person's own day, diary in parts with catch-up, redaction,
one-trip day context, long-term search, 'forget that' everywhere. Example person: Karthik (Tanglish)."""
import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.companion import memory, memory_card as card, memory_forget, memory_search, memory_sweep, store
from app.routes import companion_public
from tests.conftest import fake_embedding
from tests.test_companion_memory_recap_diary import (  # noqa: F401  (env is a fixture)
    DAY_ANSWER, NOW, TODAY, YDAY_NOON, YESTERDAY, at, env, run, state_row)

EMPTY = '{"ops": []}'
MIDNIGHT_AGO = 930  # 10 Nov 00:00 IST is 930 minutes before NOW (15:30 IST)


# --- A. the day boundary ------------------------------------------------------------------------

def test_yesterdays_tail_goes_to_the_card_only_never_to_todays_recap(env):
    """#1/#7: a same-day run reading 23:50 and 00:10 messages keeps 23:50 out of the 10 Nov recap."""
    env.chat(("user", "late night: exam tension", MIDNIGHT_AGO + 10), ("assistant", "Relax da", MIDNIGHT_AGO + 9),
             ("user", "morning: interview at 3", MIDNIGHT_AGO - 10), ("assistant", "All the best", MIDNIGHT_AGO - 11))
    env.state["answers"] += [EMPTY, DAY_ANSWER]
    out = run(memory_sweep._sweep_pair(env.companion, "karthik", None, 0, at(0), NOW, mode="day"))
    first, second = env.state["calls"]
    assert out == "ok"
    assert "exam tension" in first["user"] and "interview at 3" not in first["user"]
    assert "TODAY'S RECAP" not in first["user"]  # card only
    assert "interview at 3" in second["user"] and "exam tension" not in second["user"]
    assert state_row(env)["recap_day"] == TODAY


def test_a_long_day_is_read_in_parts_then_joined(env):
    """#1/#2: 170 messages → 3 notes of up to 80 messages, then one join call; nothing is left out."""
    env.chat(*[("user", f"m{i}", 200 - i) for i in range(170)], base=YDAY_NOON)
    env.state["answers"] += ['{"diary": "note one"}', '{"diary": "note two"}', '{"diary": "note three"}',
                             '{"diary": "Prepared for Infosys all day"}']
    assert run(memory_sweep.run_diary_job(NOW)) == {"diary": 1}
    calls = env.state["calls"]
    assert len(calls) == 4
    assert "m0" in calls[0]["user"] and "m169" in calls[2]["user"]
    assert all(n in calls[3]["user"] for n in ("note one", "note two", "note three"))
    assert [r["text"] for r in env.db.rows("companion_memory_diary")] == ["Prepared for Infosys all day"]


# --- B. diary catch-up and the timezone ----------------------------------------------------------

def test_a_day_failing_for_three_days_is_skipped_so_later_days_still_close(env):
    """#3: 7 Nov keeps failing; on 10 Nov it is given up and 8–9 Nov still close."""
    env.chat(*[("user", f"u{i}", 60 - i) for i in range(3)], base=YDAY_NOON - timedelta(days=2))
    env.chat(*[("user", f"y{i}", 60 - i) for i in range(3)], base=YDAY_NOON)
    env.state["answers"] += [RuntimeError("gemini down"), '{"diary": "9 Nov line"}']
    assert run(memory_sweep.run_diary_job(NOW)) == {"diary_gave_up": 1, "diary": 1}
    assert state_row(env)["diary_through"] == YESTERDAY
    assert [r["day"] for r in env.db.rows("companion_memory_diary")] == [YESTERDAY]


def test_the_diary_day_is_the_persons_local_day(env):
    """#10: 23:30 in Toronto on 9 Nov is 10:00 IST on 10 Nov. The Toronto person's 9 Nov is closed."""
    env.db.add("companion_end_users", id="karthik", tenant_id="t1", external_user_id="k1",
               timezone="America/Toronto")
    toronto_late = NOW - timedelta(hours=5, minutes=30)  # 04:30 UTC = 23:30 Toronto, 9 Nov
    env.chat(*[("user", f"t{i}", 3 - i) for i in range(3)], base=toronto_late)
    env.state["answers"].append('{"diary": "late chat in Toronto"}')
    assert run(memory_sweep.run_diary_job(NOW)) == {"diary": 1}
    assert [r["day"] for r in env.db.rows("companion_memory_diary")] == [YESTERDAY]


def test_zone_order_is_person_then_character_then_ist():
    assert str(card.zone_for({"timezone": "Asia/Dubai"}, "America/Toronto")) == "America/Toronto"
    assert str(card.zone_for({"timezone": "Asia/Dubai"}, None)) == "Asia/Dubai"
    assert str(card.zone_for({"timezone": "Mars/Base"}, "not a zone")) == "Asia/Kolkata"
    assert card.local_midnight_utc(date(2026, 11, 10), card.zone_for({})) == "2026-11-09T18:30:00+00:00"


def test_the_chat_api_accepts_only_real_zone_names():
    body = {"companion_id": "5bb40716-32d8-42dc-a074-38a9167e42cc", "user_id": "k1", "message": "hi"}
    assert companion_public.ServerChatIn(**body, timezone="America/Toronto").timezone == "America/Toronto"
    assert companion_public.ServerChatIn(**body).timezone is None
    for bad in ("Mars/Base", "x" * 65, "../etc/passwd"):
        with pytest.raises(ValidationError):
            companion_public.ServerChatIn(**body, timezone=bad)


def test_the_zone_the_app_sends_is_saved_and_kept(env):
    run(store.find_or_create_end_user("t1", "k9", timezone_name="Asia/Dubai"))
    run(store.find_or_create_end_user("t1", "k9"))  # a later message without a zone keeps it
    row = next(r for r in env.db.rows("companion_end_users") if r["external_user_id"] == "k9")
    assert row["timezone"] == "Asia/Dubai"
    assert run(store.person_timezone("t1", row["id"])) == "Asia/Dubai"


# --- F. redaction --------------------------------------------------------------------------------

def test_diary_and_recap_redact_numbers_but_keep_the_line_and_dates():
    """#8: the line survives with "[number]"; dates and short amounts stay; secrets still drop."""
    assert card.redact("Paid 4500 rent, ref 99887766 on 2026-11-09") == "Paid 4500 rent, ref [number] on 2026-11-09"
    assert card.redact("call me on 98765 43210") == "call me on [number]"
    assert card.clean_diary("Booked flight, PNR 4455667788") == "Booked flight, PNR [number]"
    assert card.clean_diary("his OTP was 482913") is None
    assert card.clean_recap("- interview at 3\n- account 123456789012") == "- interview at 3\n- account [number]"


# --- G. one-trip day context ---------------------------------------------------------------------

def test_recap_and_recent_days_load_in_one_database_call(env, monkeypatch):
    """#15: one RPC instead of separate reads."""
    cid = env.companion["id"]
    run(store.set_recap("t1", cid, "karthik", "- interview at 3", TODAY, at(5)))
    run(store.upsert_diary("t1", cid, "karthik", YESTERDAY, "prepared all day"))
    calls = []
    real = env.db.rpc_handlers["companion_day_context"]
    env.db.rpc_handlers["companion_day_context"] = lambda p: calls.append(p) or real(p)
    monkeypatch.setattr(store, "get_recap", None)       # the old reads must not be used
    monkeypatch.setattr(store, "recent_diary", None, raising=False)
    block = run(card.day_context("t1", cid, "karthik", date(2026, 11, 10)))
    assert len(calls) == 1
    assert "interview at 3" in block and "prepared all day" in block


# --- Part 2: long-term search --------------------------------------------------------------------

def _msgs(n, start=0):
    return [{"id": f"m{i}", "role": "user" if i % 2 == 0 else "assistant", "content": f"text {i}",
             "created_at": f"2026-03-12T10:{i:02d}:00+00:00"} for i in range(start, start + n)]


def test_windows_overlap_and_only_cover_new_messages():
    wins = memory_search.windows(_msgs(14), [])
    assert [[m["id"] for m in w][0] for w in wins] == ["m0", "m6"] and all(len(w) <= 8 for w in wins)
    old = _msgs(2)
    wins = memory_search.windows(_msgs(3, start=2), old)
    assert [[m["id"] for m in w] for w in wins] == [["m0", "m1", "m2", "m3", "m4"]]


@pytest.fixture
def floors(monkeypatch):
    monkeypatch.setattr(memory_search, "VECTOR_FLOOR", 0.62)
    monkeypatch.setattr(memory_search, "TRIGRAM_FLOOR", 0.45)


def test_fuse_keeps_a_piece_only_when_one_half_is_sure(floors):
    rows = [{"id": "a", "kind": "messages", "day": "2026-03-12", "text": "Bruno", "source": "vector", "score": 0.7},
            {"id": "b", "kind": "messages", "day": "2026-03-12", "text": "weak", "source": "vector", "score": 0.5},
            {"id": "b", "kind": "messages", "day": "2026-03-12", "text": "weak", "source": "trigram", "score": 0.3},
            {"id": "c", "kind": "diary", "day": "2026-04-01", "text": "rombha", "source": "trigram", "score": 0.5}]
    assert [h["id"] for h in memory_search.fuse(rows)] == ["a", "c"]


def _hit(id_, source, score):
    return {"id": id_, "kind": "messages", "day": "2026-03-12", "text": id_, "source": source, "score": score}


def test_gated_fusion_ignores_weak_word_overlap_but_keeps_an_exact_match(floors, monkeypatch):
    # Bake-off 2026-11-11: weak trigram ranks pushed the right piece down. "right" is the best vector
    # piece; "noise" has a slightly lower vector score plus a weak (0.2) trigram rank.
    rows = [_hit("right", "vector", 0.80), _hit("noise", "vector", 0.78), _hit("noise", "trigram", 0.20),
            _hit("exact", "trigram", 0.90)]
    monkeypatch.setattr(memory_search, "FUSION", "hybrid")
    assert [h["id"] for h in memory_search.fuse(rows)][0] == "noise"
    monkeypatch.setattr(memory_search, "FUSION", "gated")
    assert [h["id"] for h in memory_search.fuse(rows)] == ["right", "exact", "noise"]
    monkeypatch.setattr(memory_search, "FUSION", "vector")
    assert [h["id"] for h in memory_search.fuse(rows)] == ["right", "noise"]


def test_render_skips_todays_chat_and_text_already_shown_and_caps_hits():
    hits = [{"id": "t", "kind": "messages", "day": TODAY, "text": "Person: today"},
            {"id": "d", "kind": "diary", "day": "2026-11-09", "text": "prepared all day"},
            {"id": "m", "kind": "messages", "day": "2026-03-12",
             "text": "Person: my dog Bruno got sick\nCharacter: aiyo\nPerson: vet said 2 weeks rest"}]
    hits += [{"id": f"x{i}", "kind": "fact", "day": "2026-02-01", "text": f"old fact {i}"} for i in range(9)]
    block = memory_search.render_hits(hits, shown="- 9 Nov: prepared all day", today=date(2026, 11, 10))
    lines = block.splitlines()
    assert lines[0] == memory_search.HEADER and len(lines) == 1 + memory_search.MAX_HITS
    assert lines[1] == "- 12 Mar 2026: my dog Bruno got sick / vet said 2 weeks rest"  # person's words only
    assert "today" not in block and "prepared all day" not in block and len(block) <= memory_search.BLOCK_CAP
    assert memory_search.render_hits([], today=date(2026, 11, 10)) == ""


def test_the_night_sweep_indexes_what_it_read_and_search_finds_it_months_later(env, monkeypatch):
    """Bruno never made the card; in June the search still finds the March chat."""
    march = datetime(2026, 3, 12, 6, 30, tzinfo=timezone.utc)
    env.chat(("user", "my dog Bruno got sick", 30), ("assistant", "Aiyo, what did the vet say?", 29),
             ("user", "vet said Bruno needs 2 weeks rest", 28), base=march)
    env.state["answers"].append(EMPTY)
    assert run(memory_sweep._sweep_pair(env.companion, "karthik", None, 0, at(0, march), march + timedelta(hours=1)))\
        == "ok"
    chunks = env.db.rows("companion_memory_chunks")
    assert [(c["kind"], c["day"]) for c in chunks] == [("messages", "2026-03-12")] and chunks[0]["embedding"]
    monkeypatch.setattr(memory_search, "VECTOR_FLOOR", 0.2)
    hits = run(memory_search.search("t1", env.companion["id"], "karthik", "Bruno epdi irukan?"))
    assert hits and "Bruno" in hits[0]["text"]


def test_search_scope_follows_the_card_scope(env, monkeypatch):
    other = env.db.add("companions", tenant_id="t1", name="Guru", memory_level=2)
    cid = env.companion["id"]
    assert run(memory_search.scope_companions("t1", cid)) == [cid]
    env.db.add("companion_tenant_settings", tenant_id="t1", memory_scope="business")
    assert sorted(run(memory_search.scope_companions("t1", cid))) == sorted([cid, other["id"]])


def test_a_broken_search_never_breaks_the_reply(env, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(store, "match_chunks", boom)
    assert run(memory_search.search("t1", env.companion["id"], "karthik", "hi")) == []


def test_backfill_indexes_old_history_once(env):
    cid = env.companion["id"]
    env.chat(*[(r, f"{r} {i}", 100 - i) for i in range(10) for r in ("user", "assistant")], base=YDAY_NOON)
    last = max(m["created_at"] for m in env.db.rows("companion_messages"))
    run(store.set_watermark("t1", cid, "karthik", last))
    run(store.upsert_diary("t1", cid, "karthik", YESTERDAY, "prepared all day"))
    counts = run(memory_sweep.run_search_backfill())
    assert counts["pairs"] == 1 and counts["windows"] == 3
    kinds = sorted(c["kind"] for c in env.db.rows("companion_memory_chunks"))
    assert kinds == ["diary"] + ["messages"] * 3
    in_windows = "\n".join(c["text"] for c in env.db.rows("companion_memory_chunks"))
    assert "assistant 9" in in_windows  # the watermark's own message is kept
    assert state_row(env)["search_backfilled_at"]
    assert run(memory_sweep.run_search_backfill())["pairs"] == 0


# --- E. forget that --------------------------------------------------------------------------------

def _smart_llm(env, monkeypatch, word):
    """Confirms/rewrites by looking for `word`, like the real model would."""
    async def llm(messages, max_tokens=300, tenant_id=None, *, purpose="", temperature=0.4, model=None):
        system, user = messages[0]["content"], messages[1]["content"]
        env.state["calls"].append({"system": system, "user": user})
        refs = re.findall(r"^(\w\d+) \[[^\]]*\] (.*)$", user, re.M)
        if system == memory_forget.CONFIRM_RULES:
            return json.dumps({"remove": [r for r, t in refs if word in t]})
        if system == memory_forget.REWRITE_RULES:
            return json.dumps({"lines": [{"id": r, "text": t.replace(f"failed the {word}, upset; ", "")
                                          if t.startswith("failed") else ""} for r, t in refs if word in t]})
        raise AssertionError("unexpected AI call")
    monkeypatch.setattr(card.ai_reply, "_llm_chat", llm)


def test_forget_that_reaches_search_facts_diary_and_recap(env, monkeypatch):
    """#5: "forget that I failed the exam" → the diary line is rewritten, the piece and fact removed."""
    cid = env.companion["id"]
    _smart_llm(env, monkeypatch, "exam")
    run(store.upsert_chunks([
        {"tenant_id": "t1", "companion_id": cid, "end_user_id": "karthik", "kind": "messages", "source_key": "w1",
         "day": "2026-11-09", "text": "Person: I failed the exam", "embedding": None},
        {"tenant_id": "t1", "companion_id": cid, "end_user_id": "karthik", "kind": "messages", "source_key": "w2",
         "day": "2026-11-08", "text": "Person: watched Leo", "embedding": None}]))
    env.db.add("companion_memory_facts", tenant_id="t1", companion_id=cid, end_user_id="karthik",
               section="events", status="closed", text="Failed the maths exam", updated_at=at(5))
    run(store.upsert_diary("t1", cid, "karthik", YESTERDAY, "failed the exam, upset; watched Leo again"))
    run(store.set_recap("t1", cid, "karthik", "- only about the exam", TODAY, at(5)))
    run(store.update_state("t1", cid, "karthik", {"search_backfilled_at": at(1)}))  # backfill: its own test
    out = run(memory_forget.forget_things("t1", "karthik", ["failed the exam"], date(2026, 11, 10)))
    assert out == {"removed": 2, "rewritten": 2}
    assert [c["text"] for c in env.db.rows("companion_memory_chunks") if c["kind"] == "messages"] \
        == ["Person: watched Leo"]
    assert env.db.rows("companion_memory_facts") == []
    assert [r["text"] for r in env.db.rows("companion_memory_diary")] == ["watched Leo again"]
    assert [c["text"] for c in env.db.rows("companion_memory_chunks") if c["kind"] == "diary"] \
        == ["watched Leo again"]  # re-indexed
    assert state_row(env)["today_recap"] is None


def test_a_forget_list_from_the_model_starts_no_cleanup(env, monkeypatch):
    """Even if the model still answers with a "forget" list, a chat message deletes nothing."""
    seen = []

    async def fake_forget(tenant_id, end_user_id, items, today=None):
        seen.append(items)
        return {}
    monkeypatch.setattr(memory_forget, "forget_things", fake_forget)
    env.chat(("user", "forget that I failed the exam", 30))
    env.state["answers"].append('{"ops": [], "forget": ["failed the exam"]}')
    assert run(memory_sweep._sweep_pair(env.companion, "karthik", None, 0, at(0), NOW)) == "ok"
    assert seen == [] and not any(r.get("forget_pending") for r in env.db.rows("companion_memory_state"))


def test_the_owner_deleting_a_fact_cleans_the_other_copies(env, monkeypatch):
    seen = []

    async def fake_forget(tenant_id, end_user_id, items, today=None):
        seen.append((end_user_id, items))
    monkeypatch.setattr(memory_forget, "forget_things", fake_forget)
    person = env.db.add("companion_end_users", tenant_id="t1", external_user_id="k1")
    fact = env.db.add("companion_memory_facts", tenant_id="t1", companion_id=env.companion["id"],
                      end_user_id=person["id"], section="events", status="active", text="Failed the maths exam",
                      updated_at=at(5))

    async def main():
        assert await memory.forget_fact("t1", env.companion["id"], "k1", str(fact["id"]))
        import asyncio
        await asyncio.gather(*memory._cleanups)
    run(main())
    assert seen == [(person["id"], ["Failed the maths exam"])]


def test_forget_me_deletes_search_pieces_too(env):
    run(store.upsert_chunks([{"tenant_id": "t1", "companion_id": env.companion["id"], "end_user_id": "karthik",
                              "kind": "diary", "source_key": YESTERDAY, "day": YESTERDAY, "text": "a day",
                              "embedding": fake_embedding("a day")}]))
    run(store.forget_memory("t1", "karthik"))
    assert env.db.rows("companion_memory_chunks") == []


# --- F. review fixes (2026-11-11) -------------------------------------------------------------------

def _chunk(cid, key, text, day="2026-11-01", kind="messages", tenant="t1"):
    return {"tenant_id": tenant, "companion_id": cid, "end_user_id": "karthik", "kind": kind, "source_key": key,
            "day": day, "text": text, "embedding": None}


def test_a_hanging_embedding_api_costs_the_reply_at_most_the_budget(env, monkeypatch):
    import asyncio
    import time
    from app.companion import memory_embed
    run(store.upsert_chunks([_chunk(env.companion["id"], "w1", "Person: Bruno got sick, vet said rest")]))

    async def hang(*a, **k):
        await asyncio.sleep(30)
    monkeypatch.setattr(memory_embed, "embed", hang)
    monkeypatch.setattr(memory_search, "QUERY_EMBED_SECONDS", 0.05)
    started = time.monotonic()
    hits = run(memory_search.search("t1", env.companion["id"], "karthik", "Bruno vet enna sonnaru"))
    assert time.monotonic() - started < 2
    assert [h["text"] for h in hits] == ["Person: Bruno got sick, vet said rest"]  # the trigram half still ran


def test_a_one_word_message_skips_the_trigram_half(env, monkeypatch):
    from app.companion import memory_embed

    async def no_vector(texts, *a, **k):
        return [None] * len(texts)
    monkeypatch.setattr(memory_embed, "embed", no_vector)
    run(store.upsert_chunks([_chunk(env.companion["id"], "w1", "Person: ok\nCharacter: sari")]))
    assert run(memory_search.search("t1", env.companion["id"], "karthik", "ok")) == []


def test_secrets_and_long_numbers_never_reach_the_search_pieces():
    line = memory_search._line
    assert line({"role": "user", "content": "my aadhaar is 1234 5678 9012"}) == "Person: (private detail left out)"
    assert line({"role": "user", "content": "OTP 482913 vandhuchu"}) == "Person: (private detail left out)"
    assert line({"role": "user", "content": "paid rent, ref 99887766"}) == "Person: paid rent, ref [number]"


def test_the_night_sweep_keeps_a_toronto_persons_today_in_the_recap(env):
    """02:00 IST is 15:30 the day before in Toronto; at NOW (05:00 Toronto, 10 Nov) the person's
    10 Nov messages must reach the recap, not just the card."""
    env.db.add("companion_end_users", id="karthik", tenant_id="t1", external_user_id="k1",
               timezone="America/Toronto")
    env.chat(("user", "interview at 3 today", 120), ("assistant", "All the best", 119))
    env.state["answers"].append(DAY_ANSWER)
    assert run(memory_sweep._sweep_pair(env.companion, "karthik", None, 0, at(0), NOW)) == "ok"
    row = state_row(env)
    assert row["recap_day"] == "2026-11-10" and "Infosys" in row["today_recap"]


def test_the_night_sweep_reads_the_state_again_once_it_holds_the_pair(env):
    """A same-day refresh moved the watermark after the due list was read: nothing is read twice."""
    env.chat(("user", "hello", 30))
    last = max(m["created_at"] for m in env.db.rows("companion_messages"))
    run(store.set_watermark("t1", env.companion["id"], "karthik", last))
    assert run(memory_sweep._sweep_fresh(env.companion, "karthik", last, NOW)) == "skipped"
    assert env.state["calls"] == []


def test_forget_finds_a_topic_spread_over_many_windows(env, monkeypatch):
    cid = env.companion["id"]
    _smart_llm(env, monkeypatch, "exam")
    monkeypatch.setattr(memory_forget, "PER_ITEM", 10)
    run(store.update_state("t1", cid, "karthik", {"search_backfilled_at": at(1)}))
    run(store.upsert_chunks([_chunk(cid, f"w{i}", f"Person: exam day {i}") for i in range(30)]
                            + [_chunk(cid, "keep", "Person: watched Leo")]))
    out = run(memory_forget.forget_things("t1", "karthik", ["failed the exam"], date(2026, 11, 10)))
    assert out["removed"] == 30
    assert [c["text"] for c in env.db.rows("companion_memory_chunks")] == ["Person: watched Leo"]


def test_forget_indexes_an_unindexed_pair_first_so_the_backfill_cannot_bring_it_back(env, monkeypatch):
    cid = env.companion["id"]
    _smart_llm(env, monkeypatch, "exam")
    env.chat(("user", "I failed the exam", 300), ("assistant", "Paravala", 299),
             ("user", "watched Leo", 200), ("assistant", "Nice", 199), base=YDAY_NOON)
    last = max(m["created_at"] for m in env.db.rows("companion_messages"))
    run(store.set_watermark("t1", cid, "karthik", last))
    run(memory_forget.forget_things("t1", "karthik", ["failed the exam"], date(2026, 11, 10)))
    assert state_row(env)["search_backfilled_at"]
    assert not any("exam" in c["text"] for c in env.db.rows("companion_memory_chunks"))
    assert run(memory_sweep.run_search_backfill())["pairs"] == 0


def test_a_failed_forget_is_queued_and_the_hourly_job_retries_it(env, monkeypatch):
    cid = env.companion["id"]
    run(store.update_state("t1", cid, "karthik", {"search_backfilled_at": at(1)}))
    run(store.upsert_chunks([_chunk(cid, "w1", "Person: I failed the exam")]))

    async def cut_off(messages, **k):
        return '{"remo'   # an answer cut off mid-JSON must not pass as "nothing to forget"
    monkeypatch.setattr(card.ai_reply, "_llm_chat", cut_off)
    assert run(memory_forget.forget_or_queue("t1", cid, "karthik", ["failed the exam"])) is None
    assert state_row(env)["forget_pending"] == {"items": ["failed the exam"], "tries": 1}
    _smart_llm(env, monkeypatch, "exam")
    assert run(memory_forget.run_pending())["done"] == 1
    assert state_row(env)["forget_pending"] is None
    assert env.db.rows("companion_memory_chunks") == []


def test_a_line_another_run_rewrote_meanwhile_is_left_alone(env):
    cid = env.companion["id"]
    run(store.upsert_diary("t1", cid, "karthik", YESTERDAY, "newer line from the diary job"))
    assert not run(store.replace_diary_if("t1", cid, "karthik", YESTERDAY, "old line", "rewritten"))
    assert [r["text"] for r in env.db.rows("companion_memory_diary")] == ["newer line from the diary job"]
    run(store.set_recap("t1", cid, "karthik", "- newer recap", TODAY, at(5)))
    assert not run(store.replace_recap_if("t1", cid, "karthik", "- old recap", None))
    assert state_row(env)["today_recap"] == "- newer recap"


def test_the_owner_deleting_a_closed_fact_drops_its_search_piece_even_if_the_ai_fails(env, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(card.ai_reply, "_llm_chat", boom)
    person = env.db.add("companion_end_users", tenant_id="t1", external_user_id="k1")
    fact = env.db.add("companion_memory_facts", tenant_id="t1", companion_id=env.companion["id"],
                      end_user_id=person["id"], section="life", status="closed", text="Lived in Chennai",
                      updated_at=at(5))
    env.db.add("companion_memory_chunks", tenant_id="t1", companion_id=env.companion["id"], end_user_id=person["id"],
               kind="fact", source_key=str(fact["id"]), day="2026-03-01", text="Lived in Chennai (until Mar 2026)",
               embedding=None)

    async def main():
        assert await memory.forget_fact("t1", env.companion["id"], "k1", str(fact["id"]))
        import asyncio
        await asyncio.gather(*memory._cleanups)
    run(main())
    assert env.db.rows("companion_memory_chunks") == []


def test_a_business_with_a_broken_key_cannot_starve_the_others(env, monkeypatch):
    from app.companion import memory_embed
    other = env.db.add("companions", tenant_id="t2", name="Leo", language="en", memory_level=2,
                       memory_engine="card", history_messages=10)
    run(store.upsert_chunks([_chunk(env.companion["id"], f"w{i}", f"Person: hi {i}") for i in range(80)]
                            + [_chunk(other["id"], "x", "Person: hello there", tenant="t2")]))

    async def embed(texts, kind, tenant_id, model=None, retries=True):
        return [None if tenant_id == "t1" else fake_embedding(t) for t in texts]
    monkeypatch.setattr(memory_embed, "embed", embed)
    assert run(memory_sweep._fill_embeddings()) == 1
    assert next(c for c in env.db.rows("companion_memory_chunks") if c["tenant_id"] == "t2")["embedding"]

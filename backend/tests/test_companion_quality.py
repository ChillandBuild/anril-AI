"""Quality loop: the reply trace (what went into a reply, never the words) and thumbs up/down."""
import json
import logging
import time
from datetime import datetime, timezone

from app.companion import store, trace
from tests.test_companion_chat_api import DASH, PUB, SECRET_TEXT, bearer, env, signed  # noqa: F401

REPLY = "Vanakkam Karthik!"


def _chat(env, user="48213", **extra):  # noqa: F811
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                        json={"companion_id": env.live["id"], "user_id": user, "message": SECRET_TEXT, **extra})
    assert r.status_code == 200
    return r.json()


def _traces(env, want=1):  # noqa: F811
    """The trace is written in the background after the reply: give it a moment."""
    for _ in range(50):
        rows = env.db.rows("companion_reply_trace")
        if len(rows) >= want:
            return rows
        time.sleep(0.02)
    return env.db.rows("companion_reply_trace")


def _rate(env, message_id, rating, user="48213", key=None, **extra):  # noqa: F811
    return env.client.post(f"{PUB}/feedback", headers=bearer(key or env.key),
                           json={"user_id": user, "message_id": message_id, "rating": rating, **extra})


# --- trace ------------------------------------------------------------------------------------

def test_clean_keeps_numbers_flags_and_fixed_words_and_drops_text():
    kept = trace._clean({"hits": 3, "small_talk": True, "chart_redo": "ok", "passages": -4,
                         "topic": "job loss", "chart_redo_note": "x", "card_lines": "14", "rounds": True,
                         "message": SECRET_TEXT})
    assert kept == {"hits": 3, "small_talk": True, "chart_redo": "ok", "passages": 0}
    assert trace._clean({"chart_redo": SECRET_TEXT, "hits": 10**12}) == {"hits": trace.MAX_NUMBER}


def test_note_outside_a_reply_does_nothing():
    trace._current.set(None)
    trace.note(hits=3)
    assert trace._current.get() is None


def test_a_live_reply_writes_one_trace_row_without_any_text(env):  # noqa: F811
    reply = _chat(env)
    rows = _traces(env)
    assert len(rows) == 1
    row = rows[0]
    assert (row["tenant_id"], row["companion_id"], row["message_id"]) == ("t1", env.live["id"], reply["message_id"])
    assert isinstance(row["llm_ms"], int) and isinstance(row["total_ms"], int)
    assert row["detail"]["rounds"] == 1 and row["detail"]["tool_calls"] == 0 and row["detail"]["passages"] == 0
    assert set(row["detail"]) <= trace.NUMBERS | trace.FLAGS | set(trace.WORDS)
    dumped = json.dumps(row)
    assert SECRET_TEXT not in dumped and "Vanakkam" not in dumped and "Madurai" not in dumped


def test_a_failing_trace_insert_does_not_fail_the_chat(env, monkeypatch, caplog):  # noqa: F811
    async def boom(row):
        raise RuntimeError(f"relation companion_reply_trace does not exist {SECRET_TEXT}")
    monkeypatch.setattr(store, "save_reply_trace", boom)
    caplog.set_level(logging.DEBUG)
    assert _chat(env)["text"] == REPLY
    for _ in range(50):
        if "trace: insert failed" in caplog.text:
            break
        time.sleep(0.02)
    assert "trace: insert failed (RuntimeError)" in caplog.text and SECRET_TEXT not in caplog.text


# --- thumbs up / down -------------------------------------------------------------------------

def test_thumbs_down_then_up_is_one_row_and_none_removes_it(env):  # noqa: F811
    mid = _chat(env)["message_id"]
    r = _rate(env, mid, "down")
    assert r.status_code == 200 and r.json() == {"message_id": mid, "rating": "down"}
    rows = env.db.rows("companion_reply_feedback")
    assert len(rows) == 1
    assert (rows[0]["tenant_id"], rows[0]["companion_id"], rows[0]["message_id"], rows[0]["rating"]) == \
        ("t1", env.live["id"], mid, -1)
    assert SECRET_TEXT not in json.dumps(rows) and "Vanakkam" not in json.dumps(rows)

    assert _rate(env, mid, "up").status_code == 200
    rows = env.db.rows("companion_reply_feedback")
    assert len(rows) == 1 and rows[0]["rating"] == 1

    assert _rate(env, mid, "none").status_code == 200
    assert env.db.rows("companion_reply_feedback") == []


def test_only_your_own_assistant_reply_can_be_rated(env):  # noqa: F811
    mid = _chat(env)["message_id"]
    user_msg = next(m for m in env.db.rows("companion_messages") if m["role"] == "user")
    _chat(env, user="99999")                                     # a second person exists
    for r in (
        _rate(env, mid, "down", user="99999"),                   # someone else's reply
        _rate(env, mid, "down", user="nobody"),                  # a person who never chatted
        _rate(env, user_msg["id"], "down"),                      # the person's own message, not a reply
        _rate(env, "00000000-0000-0000-0000-000000000000", "down"),
        _rate(env, mid, "down", key=env.t2_key),                 # another business's key
        _rate(env, mid, "down", profile_id="p7"),                # another profile of the same user
    ):
        assert r.status_code == 404 and r.json()["code"] == "reply_not_found"
    assert env.db.rows("companion_reply_feedback") == []


def test_feedback_body_is_validated_and_needs_a_key(env):  # noqa: F811
    mid = _chat(env)["message_id"]
    assert _rate(env, mid, "meh").status_code == 422
    assert _rate(env, "not-a-uuid", "down").status_code == 422
    assert _rate(env, mid, "down", tenant_id="t2").status_code == 422          # extra fields are refused
    assert _rate(env, mid, "down", comment="bad answer").status_code == 422    # no free text, by design
    assert _rate(env, mid, "down", key="acs_live_wrong").status_code == 401
    assert env.db.rows("companion_reply_feedback") == []


def test_widget_feedback_checks_the_signature_and_the_character(env):  # noqa: F811
    r = env.client.post(f"{PUB}/widget/chat", json={**signed(env), "message": "hi"})
    mid = r.json()["message_id"]
    ok = env.client.post(f"{PUB}/widget/feedback", json={**signed(env), "message_id": mid, "rating": "up"})
    assert ok.status_code == 200 and env.db.rows("companion_reply_feedback")[0]["rating"] == 1
    other = env.client.post(f"{PUB}/widget/feedback",
                            json={**signed(env, cid=env.draft["id"]), "message_id": mid, "rating": "down"})
    assert other.status_code == 404
    bad = env.client.post(f"{PUB}/widget/feedback",
                          json={**signed(env), "signature": "0" * 64, "message_id": mid, "rating": "down"})
    assert bad.status_code == 401
    assert env.db.rows("companion_reply_feedback")[0]["rating"] == 1


def test_feedback_is_not_in_the_request_log_and_has_its_own_rate_limit(env):  # noqa: F811
    from app.routes import companion_public
    companion_public._feedback_limiter._hits.clear()
    mid = _chat(env)["message_id"]
    logged = len(env.db.rows("companion_request_log"))
    for _ in range(companion_public.FEEDBACK_PER_MINUTE):
        assert _rate(env, mid, "up").status_code == 200
    assert _rate(env, mid, "up").status_code == 429
    assert len(env.db.rows("companion_request_log")) == logged
    assert _chat(env)["text"] == REPLY                           # chat's own limit was not used up
    companion_public._feedback_limiter._hits.clear()


def test_a_database_error_is_a_503_without_the_message(env, monkeypatch, caplog):  # noqa: F811
    mid = _chat(env)["message_id"]

    async def boom(*a, **k):
        raise RuntimeError(SECRET_TEXT)
    monkeypatch.setattr(store, "set_reply_feedback", boom)
    r = _rate(env, mid, "down")
    assert r.status_code == 503 and r.json()["code"] == "busy" and SECRET_TEXT not in caplog.text


# --- dashboard --------------------------------------------------------------------------------

def test_quality_page_counts_ratings_and_shows_what_went_into_thumbs_down_replies(env):  # noqa: F811
    now = datetime.now(timezone.utc).isoformat()
    first, second = _chat(env)["message_id"], _chat(env)["message_id"]
    for row in _traces(env, want=2):
        row["created_at"] = now
    assert _rate(env, first, "down").status_code == 200 and _rate(env, second, "up").status_code == 200
    env.db.add("companion_reply_feedback", tenant_id="t2", companion_id=env.live["id"], message_id="x",
               end_user_id="e", rating=-1, updated_at=now)      # another business: never counted

    body = env.client.get(f"{DASH}/{env.live['id']}/quality").json()
    assert (body["days"], body["replies"], body["up"], body["down"], body["down_share"]) == (7, 2, 1, 1, 0.5)
    assert [d["message_id"] for d in body["down_replies"]] == [first]
    assert body["down_replies"][0]["detail"]["rounds"] == 1
    assert SECRET_TEXT not in json.dumps(body) and "Vanakkam" not in json.dumps(body)


def test_quality_page_is_empty_before_any_rating_and_404_for_a_foreign_character(env):  # noqa: F811
    body = env.client.get(f"{DASH}/{env.live['id']}/quality?days=30").json()
    assert body == {"days": 30, "replies": 0, "up": 0, "down": 0, "down_share": None, "down_replies": []}
    assert env.client.get(f"{DASH}/{env.other['id']}/quality").status_code == 404
    assert env.client.get(f"{DASH}/{env.live['id']}/quality?days=99").status_code == 422

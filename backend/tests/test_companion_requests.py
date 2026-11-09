"""companion-dashboard T11: the public API request log and the Requests page.
One row per public call once the business is known, written after the response; no message text;
a failing insert never fails the chat; every read is tenant-filtered."""
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.companion import store
from tests.test_companion_chat_api import DASH, PUB, SECRET_TEXT, bearer, env, signed  # noqa: F401


def _chat(env, **extra):  # noqa: F811
    return env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                           json={"companion_id": env.live["id"], "user_id": "48213", "message": SECRET_TEXT, **extra})


def test_a_server_chat_logs_one_row_without_the_message(env):  # noqa: F811
    r = _chat(env)
    assert r.status_code == 200
    rows = env.db.rows("companion_request_log")
    assert len(rows) == 1
    row = rows[0]
    assert (row["tenant_id"], row["companion_id"], row["kind"], row["external_user_id"], row["status"]) == \
        ("t1", env.live["id"], "chat", "48213", 200)
    assert isinstance(row["ms"], int) and row["ms"] >= 0
    assert SECRET_TEXT not in json.dumps(row) and "Vanakkam" not in json.dumps(row)


def test_widget_calls_and_engine_errors_are_logged_with_their_status(env):  # noqa: F811
    assert env.client.post(f"{PUB}/widget/chat", json={**signed(env), "message": "hi"}).status_code == 200
    r = env.client.post(f"{PUB}/widget/chat", json={**signed(env, cid=env.draft["id"]), "message": "hi"})
    assert r.status_code >= 400
    kinds = [(x["kind"], x["status"]) for x in env.db.rows("companion_request_log")]
    assert kinds[0] == ("widget_chat", 200) and kinds[1] == ("widget_chat", r.status_code)


def test_calls_rejected_before_the_business_is_known_are_not_logged(env):  # noqa: F811
    r = env.client.post(f"{PUB}/chat", headers=bearer("acs_live_wrong"),
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "hi"})
    assert r.status_code == 401
    assert env.db.rows("companion_request_log") == []


def test_a_failing_insert_does_not_fail_the_chat(env, monkeypatch, caplog):  # noqa: F811
    async def boom(row):
        raise RuntimeError(f"relation companion_request_log does not exist {SECRET_TEXT}")
    monkeypatch.setattr(store, "log_request", boom)
    caplog.set_level(logging.DEBUG)
    r = _chat(env)
    assert r.status_code == 200 and r.json()["text"] == "Vanakkam Karthik!"
    assert "request log insert failed (RuntimeError)" in caplog.text
    assert SECRET_TEXT not in caplog.text


def test_requests_page_is_tenant_filtered_and_hides_foreign_ids(env):  # noqa: F811
    _chat(env)
    _chat(env, companion_id=env.other["id"])      # another business's character: logged as an error
    env.db.add("companion_request_log", tenant_id="t2", companion_id=env.other["id"], kind="chat",
               external_user_id="x", status=200, ms=5, created_at=datetime.now(timezone.utc).isoformat())
    body = env.client.get(f"{DASH}/requests").json()
    assert body["total"] == 2 and body["errors"] == 1
    names = [(r["companion_name"], r["companion_id"], r["status"]) for r in body["requests"]]
    assert ("Jothidar AI", env.live["id"], 200) in names
    foreign = next(r for r in body["requests"] if r["status"] != 200)
    assert foreign["companion_id"] is None and foreign["companion_name"] is None
    assert all(r["external_user_id"] != "x" for r in body["requests"])


def test_filters_days_and_daily_counts(env):  # noqa: F811
    now = datetime.now(timezone.utc)
    add = lambda kind, status, ago: env.db.add(  # noqa: E731
        "companion_request_log", tenant_id="t1", companion_id=env.live["id"], kind=kind, external_user_id="48213",
        status=status, ms=100 * (status // 100), created_at=(now - timedelta(days=ago)).isoformat())
    add("chat", 200, 0)
    add("widget_chat", 200, 1)
    add("widget_chat", 503, 1)
    add("chat", 200, 10)                           # outside the default 7 days
    body = env.client.get(f"{DASH}/requests").json()
    assert body["total"] == 3 and body["errors"] == 1 and body["median_ms"] == 200
    assert [(d["ok"], d["error"]) for d in body["daily"]] == [(1, 1), (1, 0)]
    assert env.client.get(f"{DASH}/requests?days=30").json()["total"] == 4
    assert env.client.get(f"{DASH}/requests?kind=widget_chat").json()["total"] == 2
    assert env.client.get(f"{DASH}/requests?status=error").json()["total"] == 1
    assert env.client.get(f"{DASH}/requests?status=ok&kind=chat").json()["total"] == 1


@pytest.mark.parametrize("query", ["kind=email", "status=maybe", "days=0", "days=31"])
def test_bad_filters_are_422(env, query):  # noqa: F811
    assert env.client.get(f"{DASH}/requests?{query}").status_code == 422

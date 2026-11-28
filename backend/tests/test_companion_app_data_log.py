"""The app data each live reply was given, kept 7 days, birth details removed (AstroTamil item 8, 28 Nov 2026)."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from app.companion import app_data_log, store
from tests.test_companion_chat_api import PUB, bearer, env  # noqa: F401
from tests.test_companion_tools import CHART, GET_CHART, call

APP_DATA = ("Name: Karthik\nBirth date: 05-06-1994 (Sunday)\nBirth time: 06:10 AM\nBirth place: Coimbatore\n"
            "Lagnam: ரிஷபம்\nCurrent Dasa: செவ்வாய் தசை (10-06-2022 to 10-06-2029)")


def _chat(env, **extra):  # noqa: F811
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "Velai eppo?", **extra})
    assert r.status_code == 200
    return r.json()


def _logged(env, want=1):  # noqa: F811
    """Written in the background after the reply: give it a moment."""
    for _ in range(50):
        rows = env.db.rows("companion_app_data_log")
        if len(rows) >= want:
            return rows
        time.sleep(0.02)
    return env.db.rows("companion_app_data_log")


def test_a_live_reply_keeps_the_app_data_without_birth_details(env):  # noqa: F811
    reply = _chat(env, app_data=APP_DATA)
    rows = _logged(env)
    assert len(rows) == 1
    row = rows[0]
    person = env.db.rows("companion_end_users")[0]
    assert (row["tenant_id"], row["companion_id"], row["end_user_id"], row["message_id"]) == \
        ("t1", env.live["id"], person["id"], reply["message_id"])
    assert "Lagnam: ரிஷபம்" in row["app_data"] and "செவ்வாய் தசை" in row["app_data"]
    for birth in ("05-06-1994", "06:10", "Coimbatore"):     # stripped even without the chart guard
        assert birth not in row["app_data"]


def test_json_app_data_is_kept_as_json_without_birth_keys(env):  # noqa: F811
    _chat(env, app_data={"name": "Karthik", "dob": "1994-06-05", "place_of_birth": "Coimbatore", "lagnam": "ரிஷபம்"})
    assert _logged(env)[0]["app_data"] == '{"name":"Karthik","lagnam":"ரிஷபம்"}'


def test_no_app_data_no_row(env):  # noqa: F811
    _chat(env)
    time.sleep(0.1)
    assert env.db.rows("companion_app_data_log") == []


def test_a_reply_after_a_tool_turn_keeps_the_app_data_too(env):  # noqa: F811
    env.state["script"] = [("", [call()]), ("[mood: warm] Ungal lagnam Kumbham.", [])]
    first = _chat(env, app_data=APP_DATA, tools=[GET_CHART.model_dump()])
    assert first["status"] == "tool_call" and env.db.rows("companion_app_data_log") == []
    done = env.client.post(f"{PUB}/chat/continue", headers=bearer(env.key), json={
        "user_id": "48213", "turn_id": first["turn_id"], "results": [{"id": "call_1", "output": CHART}]}).json()
    rows = _logged(env)
    assert len(rows) == 1 and rows[0]["message_id"] == done["message_id"]
    assert "Lagnam: ரிஷபம்" in rows[0]["app_data"] and "Coimbatore" not in rows[0]["app_data"]


def test_a_failing_insert_does_not_fail_the_chat(env, monkeypatch, caplog):  # noqa: F811
    async def boom(row):
        raise RuntimeError(f"relation companion_app_data_log does not exist {APP_DATA}")
    monkeypatch.setattr(store, "save_app_data_log", boom)
    caplog.set_level(logging.DEBUG)
    assert _chat(env, app_data=APP_DATA)["text"] == "Vanakkam Karthik!"
    for _ in range(50):
        if "app data log: insert failed" in caplog.text:
            break
        time.sleep(0.02)
    assert "app data log: insert failed (RuntimeError)" in caplog.text and "Coimbatore" not in caplog.text


def test_prune_deletes_rows_older_than_seven_days_and_keeps_the_rest(monkeypatch):
    now = datetime(2026, 12, 5, 4, 0, tzinfo=timezone.utc)
    rows = {"8 days": now - timedelta(days=8), "7 days 1 min": now - timedelta(days=7, minutes=1),
            "6 days": now - timedelta(days=6), "today": now}
    seen = []

    async def prune(cutoff_iso):
        seen.append(cutoff_iso)
        for name in [n for n, at in rows.items() if at.isoformat() < cutoff_iso]:
            del rows[name]
    monkeypatch.setattr(store, "prune_app_data_log", prune)
    asyncio.run(app_data_log.prune(now))
    assert seen == [(now - timedelta(days=7)).isoformat()] and set(rows) == {"6 days", "today"}

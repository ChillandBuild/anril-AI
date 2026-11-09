"""companion-dashboard T8: GET /companions/overview, the numbers on the Agents Overview page.
Test chats (person "owner-test:<user>") are not customers, so they are left out of people and
messages. Every count is tenant-filtered."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import store
from app.routes import companions
from app.services import ai_reply
from tests.fake_supabase import FakeSupabase

BASE = "/api/v1/companions"


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    monkeypatch.setattr(ai_reply, "_resolve_reply_model", lambda tenant_id: "gemini/gemini-3.1-flash")
    monkeypatch.setattr(ai_reply, "_resolve_provider", lambda tenant_id: ("gemini", "gemini-3.1-flash"))
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    app.dependency_overrides[companions.require_companions_manage] = lambda: {
        "tenant_id": "t1", "user_id": "u1", "role": "owner"}
    j = fake.add("companions", tenant_id="t1", name="Jothidar AI", status="live")
    fake.add("companions", tenant_id="t1", name="Draft bot", status="draft")
    karthik = fake.add("companion_end_users", tenant_id="t1", external_user_id="48213")
    fake.add("companion_end_users", tenant_id="t1", external_user_id="77001")
    fake.add("companion_end_users", tenant_id="t1", external_user_id="99999", forgotten_at=_ago(3))
    tester = fake.add("companion_end_users", tenant_id="t1", external_user_id="owner-test:u1")
    for days in (1, 2, 6):
        fake.add("companion_messages", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
                 role="user", content="x", created_at=_ago(days))
    fake.add("companion_messages", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
             role="assistant", content="x", created_at=_ago(1))
    fake.add("companion_messages", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
             role="user", content="x", created_at=_ago(9))
    fake.add("companion_messages", tenant_id="t1", companion_id=j["id"], end_user_id=tester["id"],
             role="user", content="x", created_at=_ago(1))
    fake.add("companion_api_keys", tenant_id="t1", key_prefix="acs_live_ab12", status="active",
             created_at=_ago(5), last_used_at=_ago(0.5))
    fake.add("companion_api_keys", tenant_id="t1", key_prefix="acs_live_old1", status="revoked", created_at=_ago(30))
    # Another tenant's rows must not count.
    t2 = fake.add("companions", tenant_id="t2", name="Their bot", status="live")
    p2 = fake.add("companion_end_users", tenant_id="t2", external_user_id="1")
    fake.add("companion_messages", tenant_id="t2", companion_id=t2["id"], end_user_id=p2["id"],
             role="user", content="x", created_at=_ago(1))
    fake.add("companion_api_keys", tenant_id="t2", key_prefix="acs_live_zz", status="active", created_at=_ago(1))
    return type("Env", (), {"client": TestClient(app), "db": fake})


def test_overview_counts(env):
    body = env.client.get(f"{BASE}/overview").json()
    assert body["characters"] == 2 and body["live_characters"] == 1
    assert body["people"] == 2
    assert body["messages_this_week"] == 3
    assert body["active_keys"] == 1
    assert body["key_last_used_at"] is not None
    assert body["model"] == "gemini-3.1-flash" and body["model_ready"] is True


def test_overview_without_model_or_keys(env, monkeypatch):
    def unset(tenant_id):
        raise RuntimeError("ai_reply_model is not set")
    monkeypatch.setattr(ai_reply, "_resolve_reply_model", unset)
    monkeypatch.setattr(ai_reply, "_resolve_provider", unset)
    env.db.tables["companion_api_keys"] = [r for r in env.db.rows("companion_api_keys") if r["tenant_id"] != "t1"]
    body = env.client.get(f"{BASE}/overview").json()
    assert body["model"] is None and body["model_ready"] is False
    assert body["active_keys"] == 0 and body["key_last_used_at"] is None

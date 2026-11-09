"""companion-dashboard T7: the Memories page routes. List the people a character talked to,
and "Delete this person" (forget_person, business-wide). Every query is tenant-filtered."""
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import store
from app.routes import companions
from tests.fake_supabase import FakeSupabase

BASE = "/api/v1/companions"
SECRET = "lagnam Kumbham"


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    audits = []
    monkeypatch.setattr(companions, "record_audit_event", lambda db, **kw: audits.append(kw))
    monkeypatch.setattr(companions, "get_supabase", lambda: fake)
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    app.dependency_overrides[companions.require_companions_manage] = lambda: {
        "tenant_id": "t1", "user_id": "u1", "role": "owner"}
    j = fake.add("companions", tenant_id="t1", name="Jothidar AI", status="live", privacy_mode="A")
    other_char = fake.add("companions", tenant_id="t1", name="Offer bot", status="live", privacy_mode="A")
    karthik = fake.add("companion_end_users", tenant_id="t1", external_user_id="48213", display_name="Karthik",
                       last_seen_at="2026-11-09T10:00:00+00:00")
    priya = fake.add("companion_end_users", tenant_id="t1", external_user_id="77001", display_name="Priya",
                     last_seen_at="2026-11-08T10:00:00+00:00")
    gone = fake.add("companion_end_users", tenant_id="t1", external_user_id="99999", display_name=None,
                    forgotten_at="2026-11-01T00:00:00+00:00")
    # Two conversations for Karthik with Jothidar (46 messages), one for Priya, one with the other character.
    fake.add("companion_conversations", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
             message_count=40, last_message_at="2026-11-09T10:00:00+00:00")
    fake.add("companion_conversations", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
             message_count=6, last_message_at="2026-11-02T10:00:00+00:00")
    fake.add("companion_conversations", tenant_id="t1", companion_id=j["id"], end_user_id=priya["id"],
             message_count=3, last_message_at="2026-11-08T10:00:00+00:00")
    fake.add("companion_conversations", tenant_id="t1", companion_id=other_char["id"], end_user_id=priya["id"],
             message_count=9, last_message_at="2026-11-08T11:00:00+00:00")
    fake.add("companion_conversations", tenant_id="t1", companion_id=j["id"], end_user_id=gone["id"],
             message_count=0, last_message_at="2026-11-01T00:00:00+00:00")
    for text in (SECRET, "works at Infosys", "sister Meena", "likes short answers"):
        fake.add("companion_memory_facts", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
                 section="life", text=text, status="active")
    fake.add("companion_memory_facts", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
             section="life", text="old job", status="closed")
    fake.add("companion_messages", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
             role="user", content=SECRET)
    # Another tenant with the same external id.
    t2_char = fake.add("companions", tenant_id="t2", name="Their bot", status="live", privacy_mode="A")
    t2_person = fake.add("companion_end_users", tenant_id="t2", external_user_id="48213", display_name="Other Karthik")
    fake.add("companion_conversations", tenant_id="t2", companion_id=t2_char["id"], end_user_id=t2_person["id"],
             message_count=5, last_message_at="2026-11-09T12:00:00+00:00")
    return type("Env", (), {"client": TestClient(app), "db": fake, "j": j, "t2_char": t2_char,
                            "karthik": karthik, "t2_person": t2_person, "audits": audits})


def test_lists_people_newest_first_with_counts(env):
    body = env.client.get(f"{BASE}/{env.j['id']}/people").json()
    assert body["total"] == 2
    assert [(p["external_user_id"], p["display_name"], p["fact_count"], p["message_count"]) for p in body["people"]] == [
        ("48213", "Karthik", 4, 46), ("77001", "Priya", 0, 3)]
    assert body["people"][0]["last_seen_at"] == "2026-11-09T10:00:00+00:00"


def test_search_matches_id_or_name_and_pages(env):
    c, url = env.client, f"{BASE}/{env.j['id']}/people"
    assert [p["external_user_id"] for p in c.get(url, params={"q": "482"}).json()["people"]] == ["48213"]
    assert [p["external_user_id"] for p in c.get(url, params={"q": "pri"}).json()["people"]] == ["77001"]
    page = c.get(url, params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and [p["external_user_id"] for p in page["people"]] == ["77001"]
    assert c.get(url, params={"limit": 0}).status_code == 422
    assert c.get(url, params={"limit": 101}).status_code == 422


def test_privacy_mode_b_hides_fact_counts(env):
    row = next(r for r in env.db.rows("companions") if r["id"] == env.j["id"])
    row["privacy_mode"] = "B"
    people = env.client.get(f"{BASE}/{env.j['id']}/people").json()["people"]
    assert [p["fact_count"] for p in people] == [None, None]


def test_other_tenants_character_is_404(env):
    assert env.client.get(f"{BASE}/{env.t2_char['id']}/people").status_code == 404


def test_delete_person_forgets_everything_and_audits_without_text(env, caplog):
    caplog.set_level(logging.DEBUG)
    assert env.client.delete(f"{BASE}/people/48213").status_code == 204
    db = env.db
    assert [m for m in db.rows("companion_messages") if m["end_user_id"] == env.karthik["id"]] == []
    assert [f for f in db.rows("companion_memory_facts") if f["end_user_id"] == env.karthik["id"]] == []
    assert [c for c in db.rows("companion_conversations") if c["end_user_id"] == env.karthik["id"]] == []
    # The other tenant's 48213 is untouched.
    assert [c for c in db.rows("companion_conversations") if c["end_user_id"] == env.t2_person["id"]]
    assert next(p for p in db.rows("companion_end_users") if p["id"] == env.t2_person["id"])["display_name"] == "Other Karthik"
    # Karthik no longer shows on the list.
    assert [p["external_user_id"] for p in env.client.get(f"{BASE}/{env.j['id']}/people").json()["people"]] == ["77001"]
    assert len(env.audits) == 1
    audit = env.audits[0]
    assert audit["action"] == "tenant.companion_person_forgotten" and audit["target_id"] == env.karthik["id"]
    assert "48213" not in str(audit) and SECRET not in caplog.text


def test_delete_unknown_person_is_404(env):
    assert env.client.delete(f"{BASE}/people/nobody").status_code == 404
    assert env.audits == []

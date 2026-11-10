"""companion-memory T5: owner routes for memory scope and one person's remembered facts."""
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import store
from app.routes import companions
from tests.fake_supabase import FakeSupabase

BASE = "/api/v1/companions"
SECRET = "lost job at Infosys"


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    app.dependency_overrides[companions.require_companions_manage] = lambda: {
        "tenant_id": "t1", "user_id": "u1", "role": "owner"}
    j = fake.add("companions", tenant_id="t1", name="Jothidar AI", status="live", privacy_mode="A")
    karthik = fake.add("companion_end_users", tenant_id="t1", external_user_id="astro-123")
    fact = fake.add("companion_memory_facts", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
                    section="life", text=SECRET, status="active", valid_from="2026-10-01")
    return type("Env", (), {"client": TestClient(app), "db": fake, "j": j, "fact": fact})


def test_memory_settings_default_then_switch(env):
    c = env.client
    assert c.get(f"{BASE}/memory-settings").json() == {"memory_scope": "character"}
    assert c.put(f"{BASE}/memory-settings", json={"memory_scope": "business"}).json() == {"memory_scope": "business"}
    assert c.get(f"{BASE}/memory-settings").json() == {"memory_scope": "business"}
    assert c.put(f"{BASE}/memory-settings", json={"memory_scope": "everyone"}).status_code == 422


def test_owner_lists_and_deletes_one_fact_without_logging_it(env, caplog):
    caplog.set_level(logging.DEBUG)
    c, url = env.client, f"{BASE}/{env.j['id']}/people/astro-123/memory"
    body = c.get(url).json()
    assert body["memory_scope"] == "character"
    assert [(f["text"], f["section"], f["learned_by"], f["valid_from"]) for f in body["facts"]] == [
        (SECRET, "life", "Jothidar AI", "2026-10-01")]
    assert c.delete(f"{url}/{env.fact['id']}").status_code == 204
    assert c.get(url).json()["facts"] == []
    assert c.delete(f"{url}/{env.fact['id']}").status_code == 404
    assert SECRET not in caplog.text


def test_unknown_person_gets_empty_list(env):
    assert env.client.get(f"{BASE}/{env.j['id']}/people/nobody/memory").json()["facts"] == []


def test_privacy_mode_b_is_403(env):
    row = next(r for r in env.db.rows("companions") if r["id"] == env.j["id"])
    row["privacy_mode"] = "B"
    url = f"{BASE}/{env.j['id']}/people/astro-123/memory"
    assert env.client.get(url).status_code == 403
    assert env.client.delete(f"{url}/{env.fact['id']}").status_code == 403
    assert len(env.db.rows("companion_memory_facts")) == 1


def test_another_tenants_character_is_404(env):
    other = env.db.add("companions", tenant_id="t2", name="Their bot", status="live", privacy_mode="A")
    url = f"{BASE}/{other['id']}/people/astro-123/memory"
    assert env.client.get(url).status_code == 404
    assert env.client.delete(f"{url}/{env.fact['id']}").status_code == 404
    assert env.client.get(f"{BASE}/{uuid.uuid4()}/people/astro-123/memory").status_code == 404


def test_bad_ids_are_422(env):
    url = f"{BASE}/{env.j['id']}/people/{'x' * 201}/memory"
    assert env.client.get(url).status_code == 422
    assert env.client.delete(f"{BASE}/{env.j['id']}/people/astro-123/memory/not-a-uuid").status_code == 422


# --- T6: switching a character's engine resets its watermarks ------------------------------------

def test_engine_switch_resets_watermarks_only_on_a_real_change(env):
    import asyncio
    karthik = env.db.rows("companion_end_users")[0]
    v = env.db.add("companions", tenant_id="t1", name="Vastu Guru", status="live", privacy_mode="A")

    def mark():
        for cid in (env.j["id"], v["id"]):
            asyncio.run(store.set_watermark("t1", cid, karthik["id"], "2026-11-09T10:00:00+00:00"))

    def marks():
        return sorted(r["companion_id"] for r in env.db.rows("companion_memory_state"))

    mark()
    assert env.client.patch(f"{BASE}/{env.j['id']}", json={"name": "Jothidar"}).status_code == 200
    assert len(marks()) == 2                                         # no engine change: untouched
    assert env.client.patch(f"{BASE}/{env.j['id']}", json={"memory_engine": "card"}).status_code == 200
    assert len(marks()) == 2                                         # same engine: untouched
    assert env.client.patch(f"{BASE}/{env.j['id']}", json={"memory_engine": "mem0"}).status_code == 200
    assert marks() == [v["id"]]                                      # only this character's reset
    mark()
    assert env.client.patch(f"{BASE}/{env.j['id']}", json={"memory_engine": "card"}).status_code == 200
    assert marks() == [v["id"]]
    assert len(env.db.rows("companion_memory_facts")) == 1          # card facts stay until forget-me


# --- review fix (2026-11-09): business scope never shows the owner a mode-B character's facts ---

def test_business_scope_hides_private_characters_facts_from_the_owner(env):
    karthik = env.db.rows("companion_end_users")[0]
    private = env.db.add("companions", tenant_id="t1", name="Manasu Friend", status="live", privacy_mode="B")
    hidden = env.db.add("companion_memory_facts", tenant_id="t1", companion_id=private["id"],
                        end_user_id=karthik["id"], section="life", text="feels low at night", status="active")
    env.client.put(f"{BASE}/memory-settings", json={"memory_scope": "business"})
    url = f"{BASE}/{env.j['id']}/people/astro-123/memory"
    assert [f["text"] for f in env.client.get(url).json()["facts"]] == [SECRET]
    assert env.client.delete(f"{url}/{hidden['id']}").status_code == 404
    assert len(env.db.rows("companion_memory_facts")) == 2
    # The characters still share it: that's the business-scope promise.
    from app.companion.memory_card import visible_facts
    import asyncio
    seen = asyncio.run(visible_facts("t1", env.j["id"], karthik["id"]))
    assert "feels low at night" in [f["text"] for f in seen]


# --- Diary tab (migration 256) -------------------------------------------------------------------

def _karthik(env):
    return next(r for r in env.db.rows("companion_end_users") if r["external_user_id"] == "astro-123")["id"]


def test_owner_sees_and_deletes_diary_lines_and_the_today_note(env, caplog):
    import asyncio
    caplog.set_level(logging.DEBUG)
    cid, eu = env.j["id"], _karthik(env)
    asyncio.run(store.upsert_diary("t1", cid, eu, "2026-11-09", "Interview prep, nervous"))
    asyncio.run(store.upsert_diary("t1", cid, eu, "2026-11-08", "Watched Leo again"))
    asyncio.run(store.upsert_chunks([{"tenant_id": "t1", "companion_id": cid, "end_user_id": eu, "kind": "diary",
                                      "source_key": "2026-11-09", "day": "2026-11-09",
                                      "text": "Interview prep, nervous", "embedding": None}]))
    asyncio.run(store.set_recap("t1", cid, eu, "- interview at 3 pm", "2026-11-10", "2026-11-10T05:00:00+00:00"))
    c, url = env.client, f"{BASE}/{cid}/people/astro-123"
    body = c.get(f"{url}/diary").json()
    assert body["today"] == {"day": "2026-11-10", "text": "- interview at 3 pm"}
    assert [d["day"] for d in body["days"]] == ["2026-11-09", "2026-11-08"]
    assert c.delete(f"{url}/diary/2026-11-09").status_code == 204
    assert env.db.rows("companion_memory_chunks") == []  # its search piece went too
    assert c.delete(f"{url}/diary/2026-11-09").status_code == 404
    assert c.delete(f"{url}/diary/not-a-day").status_code == 422
    assert c.delete(f"{url}/recap").status_code == 204
    assert c.delete(f"{url}/recap").status_code == 404
    body = c.get(f"{url}/diary").json()
    assert body == {"today": None, "days": [{"day": "2026-11-08", "text": "Watched Leo again"}]}
    assert "Interview prep" not in caplog.text and "interview at 3" not in caplog.text


def test_diary_unknown_person_is_empty_and_mode_b_is_403(env):
    cid = env.j["id"]
    assert env.client.get(f"{BASE}/{cid}/people/nobody/diary").json() == {"today": None, "days": []}
    row = next(r for r in env.db.rows("companions") if r["id"] == cid)
    row["privacy_mode"] = "B"
    url = f"{BASE}/{cid}/people/astro-123"
    assert env.client.get(f"{url}/diary").status_code == 403
    assert env.client.delete(f"{url}/diary/2026-11-09").status_code == 403
    assert env.client.delete(f"{url}/recap").status_code == 403


def test_diary_of_another_tenants_character_is_404(env):
    other = env.db.add("companions", tenant_id="t2", name="Other", status="live", privacy_mode="A")
    assert env.client.get(f"{BASE}/{other['id']}/people/astro-123/diary").status_code == 404

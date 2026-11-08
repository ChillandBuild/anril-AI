"""companion-memory T1: facts, watermarks and the tenant memory scope (migration 249)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.companion import store
from app.companion.models import CompanionSettings, CompanionUpdate
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# --- memory_engine on the character ---------------------------------------------------------------

def test_memory_engine_defaults_to_card_and_rejects_unknown():
    assert CompanionSettings(name="Jothidar AI").memory_engine == "card"
    assert CompanionUpdate(memory_engine="mem0").changes() == {"memory_engine": "mem0"}
    with pytest.raises(ValidationError):
        CompanionSettings(name="Jothidar AI", memory_engine="redis")


# --- memory scope ---------------------------------------------------------------------------------

def test_scope_defaults_to_character_and_is_per_tenant(db):
    assert run(store.get_memory_scope("t1")) == "character"
    run(store.set_memory_scope("t1", "business"))
    assert run(store.get_memory_scope("t1")) == "business"
    assert run(store.get_memory_scope("t2")) == "character"
    run(store.set_memory_scope("t1", "character"))
    assert len(db.rows("companion_tenant_settings")) == 1
    with pytest.raises(ValueError):
        run(store.set_memory_scope("t1", "everyone"))


# --- facts ----------------------------------------------------------------------------------------

def test_add_list_close_update_delete(db):
    f = run(store.add_fact("t1", "jothidar", "karthik", "life", "  lost job  ", valid_from="2026-10-01"))
    assert f["status"] == "active" and f["text"] == "lost job"
    run(store.add_fact("t1", "jothidar", "karthik", "people", "son, in 10th standard"))

    assert run(store.close_fact("t1", f["id"], "2026-12-01"))
    assert run(store.update_fact_text("t1", f["id"], "lost job at Infosys"))
    facts = run(store.list_facts("t1", "karthik", "jothidar"))
    assert [x["section"] for x in facts] == ["people", "life"]  # active first, then recently closed
    closed = facts[1]
    assert closed["status"] == "closed" and closed["valid_to"] == "2026-12-01"

    assert run(store.delete_fact("t1", f["id"]))
    assert [x["section"] for x in run(store.list_facts("t1", "karthik", "jothidar"))] == ["people"]


def test_closed_facts_drop_out_after_90_days(db):
    db.add("companion_memory_facts", tenant_id="t1", companion_id="jothidar", end_user_id="karthik",
           section="life", text="old job", status="closed", updated_at=_days_ago(91))
    db.add("companion_memory_facts", tenant_id="t1", companion_id="jothidar", end_user_id="karthik",
           section="life", text="recent change", status="closed", updated_at=_days_ago(10))
    texts = [x["text"] for x in run(store.list_facts("t1", "karthik", "jothidar"))]
    assert texts == ["recent change"]
    assert run(store.list_facts("t1", "karthik", "jothidar", include_closed=False)) == []


def test_list_scopes_by_character_or_whole_business(db):
    run(store.add_fact("t1", "jothidar", "karthik", "profile", "born 12 Mar 1998, Madurai"))
    run(store.add_fact("t1", "vastu", "karthik", "life", "buying a house"))
    assert [x["text"] for x in run(store.list_facts("t1", "karthik", "vastu"))] == ["buying a house"]
    assert len(run(store.list_facts("t1", "karthik"))) == 2


def test_every_fact_query_is_tenant_filtered(db):
    f = run(store.add_fact("t1", "jothidar", "karthik", "life", "lost job"))
    assert run(store.get_fact("t2", f["id"])) is None
    assert run(store.list_facts("t2", "karthik")) == []
    assert not run(store.close_fact("t2", f["id"]))
    assert not run(store.update_fact_text("t2", f["id"], "hacked"))
    assert not run(store.delete_fact("t2", f["id"]))
    assert run(store.get_fact("t1", f["id"]))["text"] == "lost job"


def test_unknown_section_is_refused(db):
    with pytest.raises(ValueError):
        run(store.add_fact("t1", "jothidar", "karthik", "secrets", "x"))


def test_sixty_fact_cap_evicts_closed_then_preferences_then_refuses(db):
    def seed(n, **kw):
        for i in range(n):
            db.add("companion_memory_facts", tenant_id="t1", companion_id="jothidar", end_user_id="karthik",
                   text=f"fact {i}", created_at=f"2026-01-01T00:{i:02d}:00", **kw)

    seed(1, section="life", status="closed")
    seed(1, section="preferences", status="active")
    seed(58, section="people", status="active")
    assert len(db.rows("companion_memory_facts")) == 60

    run(store.add_fact("t1", "jothidar", "karthik", "threads", "Zoho interview"))
    rows = db.rows("companion_memory_facts")
    assert len(rows) == 60 and not any(r["status"] == "closed" for r in rows)

    run(store.add_fact("t1", "jothidar", "karthik", "threads", "son's exam"))
    rows = db.rows("companion_memory_facts")
    assert len(rows) == 60 and not any(r["section"] == "preferences" for r in rows)

    assert run(store.add_fact("t1", "jothidar", "karthik", "threads", "one too many")) is None
    assert len(db.rows("companion_memory_facts")) == 60
    # Another character's pair has its own 60.
    assert run(store.add_fact("t1", "vastu", "karthik", "life", "buying a house")) is not None


# --- watermarks -----------------------------------------------------------------------------------

def test_watermark_upsert_and_reset(db):
    assert run(store.get_watermark("t1", "jothidar", "karthik")) is None
    run(store.set_watermark("t1", "jothidar", "karthik", "2026-11-09T10:02:00+00:00"))
    run(store.set_watermark("t1", "jothidar", "karthik", "2026-11-09T10:05:00+00:00"))
    assert len(db.rows("companion_memory_state")) == 1
    assert run(store.get_watermark("t1", "jothidar", "karthik")) == "2026-11-09T10:05:00+00:00"
    assert run(store.get_watermark("t2", "jothidar", "karthik")) is None

    run(store.set_watermark("t1", "vastu", "karthik", "2026-11-09T10:05:00+00:00"))
    run(store.reset_watermarks("t2", "jothidar"))  # wrong tenant: nothing happens
    assert run(store.get_watermark("t1", "jothidar", "karthik")) is not None
    run(store.reset_watermarks("t1", "jothidar"))
    assert run(store.get_watermark("t1", "jothidar", "karthik")) is None
    assert run(store.get_watermark("t1", "vastu", "karthik")) is not None

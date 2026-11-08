"""companion-memory T5: memory scope is applied on read; switching it moves no data."""
import asyncio

import pytest

from app.companion import memory, store
from app.companion.memory_card import MemoryCard
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def _seed(db):
    j = db.add("companions", tenant_id="t1", name="Jothidar AI", status="live")
    v = db.add("companions", tenant_id="t1", name="Vastu Guru", status="live")
    karthik = db.add("companion_end_users", tenant_id="t1", external_user_id="astro-123")
    db.add("companion_memory_facts", tenant_id="t1", companion_id=j["id"], end_user_id=karthik["id"],
           section="life", text="lost job at Infosys", status="active", created_at="2026-11-01T10:00:00+00:00")
    db.add("companion_memory_facts", tenant_id="t1", companion_id=v["id"], end_user_id=karthik["id"],
           section="life", text="buying a house in Chennai", status="active",
           created_at="2026-11-05T10:00:00+00:00")
    return j, v, karthik


def test_character_scope_hides_other_characters_facts(db):
    j, v, _ = _seed(db)
    facts = run(memory.list_memory("t1", j["id"], "astro-123"))
    assert [f.text for f in facts] == ["lost job at Infosys"]
    assert facts[0].learned_by == "Jothidar AI"


def test_business_scope_shares_facts_own_first_with_who_learned_it(db):
    j, v, karthik = _seed(db)
    run(store.set_memory_scope("t1", "business"))
    facts = run(memory.list_memory("t1", j["id"], "astro-123"))
    assert [(f.text, f.learned_by) for f in facts] == [
        ("lost job at Infosys", "Jothidar AI"), ("buying a house in Chennai", "Vastu Guru")]
    card = run(MemoryCard().context_for("t1", j["id"], karthik["id"], "hi"))
    assert "lost job at Infosys" in card and "buying a house in Chennai" in card


def test_switching_scope_moves_no_data(db):
    j, _, _ = _seed(db)
    before = sorted((r["id"], r["companion_id"]) for r in db.rows("companion_memory_facts"))
    run(store.set_memory_scope("t1", "business"))
    run(store.set_memory_scope("t1", "character"))
    assert sorted((r["id"], r["companion_id"]) for r in db.rows("companion_memory_facts")) == before
    assert [f.text for f in run(memory.list_memory("t1", j["id"], "astro-123"))] == ["lost job at Infosys"]


def test_unknown_person_is_empty_and_other_tenants_character_raises(db):
    j, _, _ = _seed(db)
    assert run(memory.list_memory("t1", j["id"], "nobody")) == []
    with pytest.raises(LookupError):
        run(memory.list_memory("t2", j["id"], "astro-123"))


def test_forget_fact_only_reaches_what_this_character_can_see(db):
    j, v, _ = _seed(db)
    vastu_fact = next(r for r in db.rows("companion_memory_facts") if r["companion_id"] == v["id"])
    assert not run(memory.forget_fact("t1", j["id"], "astro-123", vastu_fact["id"]))  # character scope
    assert not run(memory.forget_fact("t2", v["id"], "astro-123", vastu_fact["id"]))  # other tenant
    assert run(memory.forget_fact("t1", v["id"], "astro-123", vastu_fact["id"]))
    assert len(db.rows("companion_memory_facts")) == 1

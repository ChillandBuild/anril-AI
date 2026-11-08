"""companion-core T1: migration 248 shape, character-card validation, tenant-scoped store."""
import asyncio
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.companion import store
from app.companion.models import CompanionSettings, CompanionUpdate
from tests.fake_supabase import FakeSupabase

MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/248_companion_core.sql"
TABLES = ["companions", "companion_end_users", "companion_conversations",
          "companion_messages", "companion_pending_turns"]


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    return fake


def run(coro):
    return asyncio.run(coro)


# --- migration ---------------------------------------------------------------------------------

def test_migration_follows_house_style_and_locks_tables_to_service_role():
    sql = MIGRATION.read_text()
    assert sql.startswith("-- 248_companion_core.sql")
    assert "SET LOCAL lock_timeout = '5s';" in sql
    assert "CREATE POLICY" not in sql.upper()
    for table in TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in sql
        assert re.search(rf"ALTER TABLE {table}\s+ENABLE ROW LEVEL SECURITY;", sql), table
        body = sql.split(f"CREATE TABLE IF NOT EXISTS {table} (")[1].split(");")[0]
        assert "tenant_id" in body, f"{table} has no tenant_id"
    assert "UNIQUE (tenant_id, name)" in sql
    assert "UNIQUE (tenant_id, external_user_id)" in sql


# --- validation --------------------------------------------------------------------------------

JOTHIDAR = dict(
    name="Jothidar AI", industry="astrology", role="Vedic astrologer for Astrotamil's users",
    backstory="Learned from his grandfather in Kumbakonam.", speaking_style="Warm Tanglish",
    sample_lines=["Kavalaipadaathinga, Guru dasha nalla time thaan."],
    goals=["Help the user feel heard"], temperament="calm, kind", default_mood="warm",
)


def test_a_full_character_card_is_accepted():
    s = CompanionSettings(**JOTHIDAR)
    assert s.default_mood == "warm" and s.memory_level == 1 and s.status == "draft"


@pytest.mark.parametrize("bad", [
    {"memory_level": 3},
    {"default_mood": "angry"},
    {"privacy_mode": "C"},
    {"industry": "finance"},
    {"name": ""},
    {"name": "x" * 81},
    {"role": "x" * 501},
    {"backstory": "x" * 2001},
    {"speaking_style": "x" * 1001},
    {"temperament": "x" * 301},
    {"sample_lines": ["ok"] * 11},
    {"sample_lines": ["x" * 301]},
    {"goals": ["g"] * 6},
    {"goals": ["x" * 201]},
    {"rules": ["r"] * 31},
    {"rules": ["x" * 301]},
    {"knowledge_tag_id": "not-a-uuid"},
    {"tenant_id": "someone-else"},
])
def test_validation_rejects_out_of_spec_values(bad):
    with pytest.raises(ValidationError):
        CompanionSettings(**{**JOTHIDAR, **bad})


def test_update_rejects_memory_level_3_and_drops_nulls_except_the_tag():
    with pytest.raises(ValidationError):
        CompanionUpdate(memory_level=3)
    assert CompanionUpdate(name=None, knowledge_tag_id=None).changes() == {"knowledge_tag_id": None}
    assert CompanionUpdate(role="New role").changes() == {"role": "New role"}


# --- store -------------------------------------------------------------------------------------

def test_store_creates_lists_reads_and_updates_several_characters(db):
    jothidar = run(store.create_companion("t1", CompanionSettings(**JOTHIDAR)))
    vastu = run(store.create_companion("t1", CompanionSettings(name="Vastu Guru")))
    assert jothidar["tenant_id"] == "t1" and jothidar["sample_lines"] == JOTHIDAR["sample_lines"]
    assert [c["name"] for c in run(store.list_companions("t1"))] == ["Jothidar AI", "Vastu Guru"]
    assert run(store.get_companion("t1", vastu["id"]))["name"] == "Vastu Guru"

    updated = run(store.update_companion("t1", vastu["id"], {"status": "live"}))
    assert updated["status"] == "live" and updated["updated_at"]


def test_wrong_tenant_sees_nothing_and_changes_nothing(db):
    mine = run(store.create_companion("t1", CompanionSettings(**JOTHIDAR)))
    assert run(store.get_companion("t2", mine["id"])) is None
    assert run(store.list_companions("t2")) == []
    assert run(store.update_companion("t2", mine["id"], {"status": "paused"})) is None
    assert run(store.get_companion("t1", mine["id"]))["status"] == "draft"


def test_update_cannot_move_a_character_to_another_tenant(db):
    mine = run(store.create_companion("t1", CompanionSettings(**JOTHIDAR)))
    run(store.update_companion("t1", mine["id"], {"tenant_id": "t2", "role": "r"}))
    assert run(store.get_companion("t1", mine["id"]))["tenant_id"] == "t1"


def test_duplicate_name_becomes_a_clear_error(db, monkeypatch):
    class Dup(Exception):
        code = "23505"

    def boom():
        raise Dup("duplicate key value violates unique constraint")

    monkeypatch.setattr(store, "get_supabase", lambda: type("D", (), {
        "table": lambda self, n: type("Q", (), {"insert": lambda s, r: type("E", (), {"execute": lambda e: boom()})()})()
    })())
    with pytest.raises(store.DuplicateCompanionName):
        run(store.create_companion("t1", CompanionSettings(**JOTHIDAR)))


def test_tag_check_is_tenant_scoped(db):
    tag = db.add("broadcast_tags", tenant_id="t1", name="astrology books")
    assert run(store.tag_belongs_to_tenant("t1", tag["id"])) is True
    assert run(store.tag_belongs_to_tenant("t2", tag["id"])) is False

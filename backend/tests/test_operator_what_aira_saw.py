"""Operator "What Aira saw": auth, tenant scoping, read-only, no retrieval unless asked, no model call."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.system_admin import get_system_admin
from app.main import app
from app.services import ai_reply, automation_guards, business_details, deal_turn, intake, knowledge_service
from app.services.brain import lead_context
from brain_helpers import BrainDB, _BrainQuery

T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
LEAD1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LEAD2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TAMIL_ASK = "தமிழ்ல பேசுங்க"


class _GuardedQuery(_BrainQuery):
    """A write is recorded on the db AND raises, so a write that a caller swallows still fails the test."""

    def _blocked(self, op):
        self.db.write_attempts.append((self.name, op))
        raise AssertionError(f"write attempted: {self.name}.{op}")

    def insert(self, payload):
        self._blocked("insert")

    def update(self, payload):
        self._blocked("update")

    def delete(self):
        self._blocked("delete")

    def upsert(self, payload, **_kw):
        self._blocked("upsert")

    def maybe_single(self):
        self._limit = 1
        self._single = True
        return self

    def execute(self):
        res = super().execute()
        if getattr(self, "_single", False):
            return SimpleNamespace(data=res.data[0] if res.data else None, count=res.count)
        return res


class ReadOnlyDB(BrainDB):
    def __init__(self):
        super().__init__()
        self.write_attempts: list[tuple[str, str]] = []

    def table(self, name):
        return _GuardedQuery(self, name)

    def rpc(self, *_a, **_k):
        return MagicMock(execute=lambda: SimpleNamespace(data=[]))

    def seed(self, table, **row):
        # bypass the guard: seeding is test setup, not app behaviour
        return _BrainQuery(self, table).insert(row).execute().data[0]


@pytest.fixture
def db(monkeypatch):
    fake = ReadOnlyDB()
    fake.seed("leads", id=LEAD1, tenant_id=T1, name="Priya", segment="B", score=6, phone="+910000000001",
              ai_enabled=True, blocked_at=None, opted_out=False, needs_human_attention=False, tamil_locked=False)
    fake.seed("leads", id=LEAD2, tenant_id=T2, name="Other", segment="C", score=3, phone="+910000000002",
              ai_enabled=True)
    fake.seed("messages", lead_id=LEAD1, tenant_id=T1, direction="inbound", content="what are your fees?",
              channel="whatsapp", is_ai_generated=False, created_at="2026-01-01T10:00:00")
    fake.seed("messages", lead_id=LEAD1, tenant_id=T1, direction="outbound", content="Rs 500",
              channel="whatsapp", is_ai_generated=True, created_at="2026-01-01T10:01:00")
    fake.seed("lead_conversation_state", lead_id=LEAD1, conversation_summary="Asked about fees.")
    for module in (ai_reply, business_details, knowledge_service):
        monkeypatch.setattr(module, "get_supabase", lambda: fake)
    monkeypatch.setattr("app.db.supabase.get_supabase", lambda: fake)
    monkeypatch.setattr("app.routes.operator_brain.get_supabase", lambda: fake)
    return fake


@pytest.fixture
def no_model_calls(monkeypatch):
    """Any chat-model or embedding call fails the test. Only the no-retrieval paths may use it
    unpatched: retrieval=true legitimately makes one embedding call (see TestRetrieval)."""
    boom = AsyncMock(side_effect=AssertionError("model or embedding call"))
    monkeypatch.setattr(ai_reply, "_llm_chat", boom)
    monkeypatch.setattr(deal_turn, "converse_once", boom)
    monkeypatch.setattr("app.services.embeddings._call_jina", boom)
    return boom


@pytest.fixture
def retrieval(monkeypatch):
    mock = AsyncMock(return_value="FEES: Rs 500 per session.")
    monkeypatch.setattr(lead_context, "get_knowledge_context", mock)
    return mock


@pytest.fixture(autouse=True)
def quiet(monkeypatch, db):
    def stored_setting(key, fallback=None, tenant_id=None):
        row = next((r for r in db.rows("app_settings") if r["key"] == key and r["tenant_id"] == tenant_id), None)
        return row["value"] if row else fallback

    # Settings > Auto-Reply switches are read through automation_guards, from the seeded rows.
    monkeypatch.setattr(automation_guards, "get_setting", stored_setting)
    monkeypatch.setattr(lead_context, "get_setting", lambda key, fallback=None, tenant_id=None: fallback)
    monkeypatch.setattr(ai_reply, "get_setting", lambda key, fallback=None, tenant_id=None: fallback)
    monkeypatch.setattr(intake, "get_intake_config", lambda tenant_id, db=None: {**intake._DEFAULT_CONFIG})
    monkeypatch.setattr(ai_reply, "get_master_prompt", lambda: "MASTER")


@pytest.fixture
def client():
    app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}
    yield TestClient(app)
    app.dependency_overrides.clear()


def url(tenant=T1, lead=LEAD1, query=""):
    return f"/api/v1/operator/clients/{tenant}/leads/{lead}/what-aira-saw{query}"


class TestAuth:
    def test_non_admin_gets_403(self, monkeypatch):
        no_admin = MagicMock()
        no_admin.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
        monkeypatch.setattr("app.dependencies.system_admin.get_supabase", lambda: no_admin)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "tenant-owner"}
        try:
            assert TestClient(app).get(url()).status_code == 403
        finally:
            app.dependency_overrides.clear()


class TestScoping:
    def test_lead_of_another_tenant_is_404(self, db, client):
        assert client.get(url(tenant=T1, lead=LEAD2)).status_code == 404
        assert client.get(url(tenant=T2, lead=LEAD1)).status_code == 404

    def test_unknown_or_malformed_ids_are_404(self, db, client):
        assert client.get(url(lead="33333333-3333-4333-8333-333333333333")).status_code == 404
        assert client.get(url(lead="not-a-uuid")).status_code == 404
        assert client.get(url(tenant="not-a-uuid")).status_code == 404

    def test_messages_of_another_tenant_are_not_shown(self, db, client):
        db.seed("messages", lead_id=LEAD1, tenant_id=T2, direction="inbound", content="LEAK",
                channel="whatsapp", created_at="2026-01-02T10:00:00")
        assert "LEAK" not in client.get(url()).text


class TestContent:
    def test_reconstruction_is_labelled_and_complete(self, db, client, no_model_calls):
        res = client.get(url())
        assert res.status_code == 200
        body = res.json()
        assert body["reconstructed"] is True and body["generated_at"]
        assert [m["text"] for m in body["recent_messages"]] == ["what are your fees?", "Rs 500"]
        assert [m["is_ai"] for m in body["recent_messages"]] == [False, True]
        assert body["conversation_summary"] == "Asked about fees."
        assert body["message_used"]["text"] == "what are your fees?"
        assert "MASTER" in body["system_prompt"] and "Asked about fees." in body["system_prompt"]
        assert body["reply_language_mode"] is not None
        assert body["would_reply"] is True

    def test_recent_messages_are_capped_and_oldest_first(self, db, client):
        for i in range(30):
            db.seed("messages", lead_id=LEAD1, tenant_id=T1, direction="inbound", content=f"m{i:02d}",
                    channel="whatsapp", created_at=f"2026-02-01T10:{i:02d}:00")
        texts = [m["text"] for m in client.get(url()).json()["recent_messages"]]
        assert len(texts) == lead_context.RECENT_MESSAGE_LIMIT
        assert texts == sorted(texts) and texts[-1] == "m29"

    @pytest.mark.parametrize("lead_patch,gate", [
        ({"blocked_at": "2026-01-01T00:00:00"}, "blocked"),
        ({"ai_enabled": False}, "takeover"),
    ])
    def test_lead_gates_stop_the_reply(self, db, client, lead_patch, gate):
        next(r for r in db.rows("leads") if r["id"] == LEAD1).update(lead_patch)
        body = client.get(url()).json()
        assert {g["key"]: g for g in body["gates"]}[gate]["active"] is True
        assert body["would_reply"] is False

    def test_business_wide_auto_reply_off_stops_the_reply(self, db, client):
        db.seed("app_settings", tenant_id=T1, key="ai_auto_reply_enabled", value="false")
        body = client.get(url()).json()
        assert {g["key"]: g for g in body["gates"]}["auto_reply_off"]["active"] is True
        assert body["would_reply"] is False

    def test_source_row_off_is_named_as_the_reason(self, db, client):
        # Ravi-style case: an IndiaMART lead, with IndiaMART's AI replies switched off.
        next(r for r in db.rows("leads") if r["id"] == LEAD1)["source"] = "indiamart"
        db.seed("app_settings", tenant_id=T1, key="auto_reply_sources", value='{"indiamart": {"ai": false}}')
        body = client.get(url()).json()
        gate = {g["key"]: g for g in body["gates"]}["auto_reply_off"]
        assert gate["active"] is True
        assert gate["label"] == "AI replies are switched off for IndiaMART leads"
        assert body["would_reply"] is False

    def test_channel_row_off_is_named_as_the_reason(self, db, client):
        db.seed("app_settings", tenant_id=T1, key="auto_reply_sources", value='{"whatsapp": {"ai": false}}')
        body = client.get(url()).json()
        gate = {g["key"]: g for g in body["gates"]}["auto_reply_off"]
        assert gate["active"] is True and gate["label"] == "AI replies are switched off for WhatsApp"

    def test_opted_out_is_shown_but_does_not_block_a_reply(self, db, client):
        next(r for r in db.rows("leads") if r["id"] == LEAD1)["opted_out"] = True
        body = client.get(url()).json()
        gate = {g["key"]: g for g in body["gates"]}["opted_out"]
        assert gate["active"] is True and gate["blocks_reply"] is False
        assert body["would_reply"] is True

    def test_hard_cap_reached_stops_the_reply(self, db, client):
        db.seed("tenant_usage_counters", tenant_id=T1, period=lead_context.compute_period_key(None, None),
                metric="ai_reply", used=10, hard_cap=10)
        assert client.get(url()).json()["would_reply"] is False

    def test_latest_inbound_message_drives_the_prompt(self, db, client):
        db.seed("messages", lead_id=LEAD1, tenant_id=T1, direction="inbound", content="is it open sunday?",
                channel="whatsapp", created_at="2026-01-03T10:00:00")
        assert client.get(url()).json()["message_used"]["text"] == "is it open sunday?"

    def test_lead_without_messages_still_builds_with_a_note(self, db, client):
        db.tables["messages"] = []
        body = client.get(url()).json()
        assert body["message_used"] == {"text": "", "note": lead_context.NO_MESSAGE_NOTE}
        assert body["recent_messages"] == []


class TestReadOnly:
    def test_no_writes_and_no_model_call(self, db, client, no_model_calls, retrieval):
        assert client.get(url()).status_code == 200
        assert client.get(url(query="?retrieval=true")).status_code == 200
        assert db.write_attempts == []
        no_model_calls.assert_not_called()

    def test_tamil_lock_is_not_persisted_but_shows_in_the_prompt(self, db, client, monkeypatch):
        monkeypatch.setattr(ai_reply, "_resolve_reply_language_mode", lambda tenant_id: "tanglish_escalate_tamil")
        db.seed("messages", lead_id=LEAD1, tenant_id=T1, direction="inbound", content=TAMIL_ASK,
                channel="whatsapp", created_at="2026-01-05T10:00:00")
        body = client.get(url()).json()
        assert body["reply_language_mode"] == "tamil"
        assert db.write_attempts == []
        assert next(r for r in db.rows("leads") if r["id"] == LEAD1)["tamil_locked"] is False


class TestRetrieval:
    def test_no_retrieval_unless_asked(self, db, client, retrieval):
        body = client.get(url()).json()
        retrieval.assert_not_awaited()
        assert body["knowledge"]["text"] is None and body["knowledge"]["note"]
        assert "KNOWLEDGE BASE" not in body["system_prompt"]

    def test_retrieval_runs_once_when_asked_and_joins_the_prompt(self, db, client, retrieval):
        body = client.get(url(query="?retrieval=true")).json()
        retrieval.assert_awaited_once()
        assert retrieval.await_args.kwargs["query"] == "what are your fees?"
        assert body["knowledge"]["text"] == "FEES: Rs 500 per session."
        assert "FEES: Rs 500 per session." in body["system_prompt"]


def test_write_guard_catches_the_tamil_lock_write_when_persist_is_left_on(db, monkeypatch):
    """Proves the guard above would fail if the route ever dropped persist=False."""
    monkeypatch.setattr(ai_reply, "_resolve_reply_language_mode", lambda tenant_id: "tanglish_escalate_tamil")
    lead = {"name": "Priya", "segment": "B", "tamil_locked": False}
    ai_reply.build_reply_system_prompt(db, LEAD1, T1, lead, TAMIL_ASK)
    assert ("leads", "update") in db.write_attempts

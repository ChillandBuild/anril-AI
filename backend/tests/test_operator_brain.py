"""Operator console Aira Brain: auth, read-only, key secrecy, fallback signals, history."""
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.system_admin import get_system_admin
from app.main import app
from app.services import assignment, brain, consistency, intake, operator_brain
from app.services.ai_reply import _TRIGGER_REASONS
from app.services.brain import inputs, status
from brain_helpers import BrainDB

T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
SECRET = "sk-live-SECRET-VALUE-123"


@pytest.fixture
def db(monkeypatch):
    fake = BrainDB()
    fake.add("tenants", id=T1, name="Acme")
    fake.add("tenants", id=T2, name="Other")
    monkeypatch.setattr(operator_brain, "get_supabase", lambda: fake)
    return fake


@pytest.fixture
def quiet_settings(monkeypatch):
    """Per-tenant get_setting store for the shared brain blocks; no live DB, no gather()."""
    store: dict[tuple[str, str], str] = {}

    def fake_get(key, fallback=None, tenant_id=None):
        return store.get((tenant_id, key), fallback)

    for module in (inputs, status, consistency):
        monkeypatch.setattr(module, "get_setting", fake_get)
    monkeypatch.setattr(intake, "get_intake_config", lambda tenant_id, db=None: {**intake._DEFAULT_CONFIG})
    monkeypatch.setattr(assignment, "get_inbox_config", lambda tenant_id: {**assignment._INBOX_CONFIG_DEFAULT})
    return store


@pytest.fixture
def client():
    app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestAuth:
    def test_non_admin_gets_403_on_both_endpoints(self, monkeypatch):
        no_admin = MagicMock()
        no_admin.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
        monkeypatch.setattr("app.dependencies.system_admin.get_supabase", lambda: no_admin)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "tenant-owner"}
        try:
            http = TestClient(app)
            assert http.get(f"/api/v1/operator/clients/{T1}/brain").status_code == 403
            assert http.get("/api/v1/operator/brain/waiting").status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_unknown_or_malformed_tenant_is_404(self, db, quiet_settings, client):
        assert client.get("/api/v1/operator/clients/not-a-uuid/brain").status_code == 404
        assert client.get("/api/v1/operator/clients/33333333-3333-4333-8333-333333333333/brain").status_code == 404
        assert client.get(f"/api/v1/operator/clients/{T1}/brain").status_code == 200


class TestReadOnly:
    def test_every_input_is_read_only_and_connection_is_shown(self, db, quiet_settings, client):
        body = client.get(f"/api/v1/operator/clients/{T1}/brain").json()
        assert body["tenant"] == {"id": T1, "name": "Acme"}
        assert len(body["inputs"]) == 5
        assert all(row["can_edit"] is False and row["reason"] == operator_brain.READ_ONLY_REASON for row in body["inputs"])
        assert "connection" in body["status"]
        assert {"headline", "waiting", "handovers", "operator_rows", "history", "fallback_signals"} <= set(body)

    def test_operator_view_permissions_hold_no_manage_key(self):
        assert not any(p.endswith(".manage") for p in operator_brain.OPERATOR_VIEW_PERMISSIONS)


class TestOperatorRows:
    def _rows(self, db):
        return {r["key"]: r for r in operator_brain.operator_rows(db, T1)}

    def test_provider_key_values_never_leave_the_service(self, db, client, quiet_settings):
        for key in ("gemini_api_key", "jina_api_key", "sarvam_api_key", "openai_api_key", "groq_api_key"):
            db.add("app_settings", tenant_id=T1, key=key, value=SECRET)
        db.add("app_settings", tenant_id=T1, key="ai_reply_model", value="google/gemini-3.5-flash-lite")
        res = client.get(f"/api/v1/operator/clients/{T1}/brain")
        assert SECRET not in res.text
        rows = {r["key"]: r for r in res.json()["operator_rows"]}
        assert rows["key_gemini"]["state"] == "ok" and rows["key_gemini"]["detail"] == "Present"
        # Keys for providers Aira no longer calls may still sit in the DB; they get no row.
        assert not {"key_sarvam", "key_openai", "key_groq"} & set(rows)

    def test_reply_model_defaults_to_flash_lite_when_none_or_a_removed_one_is_stored(self, db):
        assert self._rows(db)["reply_model"]["detail"] == "google/gemini-3.1-flash-lite"
        db.add("app_settings", tenant_id=T1, key="ai_reply_model", value="openai/gpt-5-mini")
        row = self._rows(db)["reply_model"]
        assert row["state"] == "ok" and row["detail"] == "google/gemini-3.1-flash-lite"

    def test_missing_key_the_client_needs_is_flagged(self, db):
        rows = self._rows(db)
        assert rows["key_gemini"]["state"] == "missing"  # needed even when no model was picked
        assert rows["key_jina"]["state"] == "missing"  # semantic retrieval is the default

    def test_settings_of_another_tenant_do_not_leak(self, db):
        db.add("app_settings", tenant_id=T2, key="ai_reply_model", value="google/gemini-3.5-flash-lite")
        db.add("app_settings", tenant_id=T2, key="gemini_api_key", value=SECRET)
        rows = self._rows(db)
        assert "3.5" not in json.dumps(rows["reply_model"])
        assert rows["key_gemini"]["state"] == "missing"

    def test_master_prompt_row_gives_length_and_date_never_the_text(self, db):
        db.add("platform_defaults", key="default_master_prompt", value="You are Aira. " * 10, updated_at="2026-07-19T10:00:00+00:00")
        row = self._rows(db)["master_prompt"]
        assert row["detail"] == "139 characters, updated 2026-07-19"
        assert "You are Aira" not in json.dumps(row)
        assert row["href"] == "/operator/prompt-template"

    def test_every_row_links_to_an_existing_page(self, db):
        assert all(r["href"].startswith("/operator/") for r in operator_brain.operator_rows(db, T1))


class TestFallbackSignals:
    def _handover(self, db, tenant, reason, opened_at="2026-09-20T00:00:00+00:00"):
        db.add("chat_handovers", tenant_id=tenant, lead_id="lead-1", reason=reason, opened_at=opened_at)

    def _signals(self, monkeypatch, db, config):
        monkeypatch.setattr(assignment, "get_inbox_config", lambda tenant_id: config)
        now = operator_brain.datetime(2026, 9, 30, tzinfo=operator_brain.timezone.utc)
        return operator_brain.fallback_signals(db, T1, now=now)

    def test_counts_only_the_two_ai_failure_reasons_for_this_tenant(self, db, monkeypatch):
        self._handover(db, T1, "AI failed to generate a response")
        self._handover(db, T1, "AI gave a generic fallback reply")
        self._handover(db, T1, "User requested a human agent")
        self._handover(db, T2, "AI failed to generate a response")
        self._handover(db, T1, "AI failed to generate a response", opened_at="2026-01-01T00:00:00+00:00")  # outside window
        result = self._signals(monkeypatch, db, {"enabled": True, "triggers": ["A", "B"], "channels": ["whatsapp"]})
        assert result["count"] == 2

    def test_reasons_match_the_ai_reply_source_strings(self):
        assert _TRIGGER_REASONS["B"] == "AI failed to generate a response"
        assert _TRIGGER_REASONS["A"] == "AI gave a generic fallback reply"

    def test_escalation_off_carries_the_note(self, db, monkeypatch):
        result = self._signals(monkeypatch, db, {**assignment._INBOX_CONFIG_DEFAULT})
        assert result["escalation_enabled"] is False
        assert result["note"] == "Counts only when inbox escalation is on"

    def test_escalation_on_for_both_triggers_has_no_note(self, db, monkeypatch):
        result = self._signals(monkeypatch, db, {"enabled": True, "triggers": ["A", "B", "C"], "channels": ["whatsapp"]})
        assert result["escalation_enabled"] is True and result["note"] is None
        assert result["triggers"] == {"A": True, "B": True}

    def test_escalation_on_but_trigger_missing_or_no_channel_is_partial(self, db, monkeypatch):
        missing_b = self._signals(monkeypatch, db, {"enabled": True, "triggers": ["A"], "channels": ["whatsapp"]})
        assert missing_b["triggers"] == {"A": True, "B": False}
        assert missing_b["escalation_enabled"] is False and missing_b["note"]
        no_channel = self._signals(monkeypatch, db, {"enabled": True, "triggers": ["A", "B"], "channels": []})
        assert no_channel["escalation_enabled"] is False


class TestHistory:
    def test_newest_first_with_readable_labels_and_only_this_tenant(self, db, quiet_settings):
        doc = db.add("knowledge_documents", tenant_id=T1, name="Diwali.pdf")["id"]
        db.add("knowledge_versions", tenant_id=T1, kind="description", reason="edit", created_by="u1")
        db.add("knowledge_versions", tenant_id=T1, kind="facts", document_id=doc, reason="upload", created_by="u1")
        db.add("knowledge_versions", tenant_id=T2, kind="description", reason="edit")
        quiet_settings[(T1, "consistency_report")] = json.dumps({"issues": [], "dismissed": ["a", "b"]})
        history = operator_brain.decision_history(db, T1)
        assert [e["label"] for e in history["entries"]] == ["Sorted file approved", "Description edited"]
        assert [e["target"] for e in history["entries"]] == ["Diwali.pdf", "Description"]
        assert history["dismissed_conflicts"] == 2
        assert "content" not in history["entries"][0]

    def test_brain_service_is_untouched_by_the_operator_wrapper(self, db, quiet_settings):
        shared = brain.build_brain(T1, role=None, permissions=operator_brain.OPERATOR_VIEW_PERMISSIONS, db=db)
        wrapped = operator_brain.build_operator_brain(T1, db=db)
        assert wrapped["waiting"] == shared["waiting"] and wrapped["headline"] == shared["headline"]

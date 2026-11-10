"""Replies run on Gemini only (operator decision 2026-11-10): both settings endpoints refuse a
reply model off the two-model list, and the removed providers are gone from the code."""
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.system_admin import get_system_admin
from app.main import app as main_app
from app.routes import app_settings
from app.services import outbound_guard

OFF_LIST = ["groq/llama-3.3-70b-versatile", "openai/gpt-5-mini", "sarvam-30b", "google/gemini-3.5-flash", ""]
ON_LIST = ["google/gemini-3.1-flash-lite", "google/gemini-3.5-flash-lite"]


# ---- operator console: PATCH /operator/clients/{id}/config ----

@pytest.fixture()
def operator_client():
    main_app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}
    yield TestClient(main_app)
    main_app.dependency_overrides.clear()


def _operator_patch(client, settings):
    db = MagicMock()
    table = MagicMock()

    def pick(name):
        if name == "app_settings":
            return table
        other = MagicMock()
        if name == "tenants":
            other.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"id": "tenant-1"}
        return other

    db.table.side_effect = pick
    with patch("app.routes.operator.get_supabase", return_value=db), \
         patch("app.routes.operator.record_audit_event"), \
         patch("app.config_dynamic.invalidate_cache"):
        res = client.patch("/api/v1/operator/clients/tenant-1/config", json={"settings": settings})
    return res, table


@pytest.mark.parametrize("model", OFF_LIST)
def test_operator_patch_refuses_a_model_off_the_list_and_writes_nothing(operator_client, model):
    res, table = _operator_patch(operator_client, {"kb_retrieval_mode": "keyword", "ai_reply_model": model})
    assert res.status_code == 400 and "Unknown reply model" in res.json()["detail"]
    table.upsert.assert_not_called()   # the sibling setting is not half-saved either


@pytest.mark.parametrize("model", ON_LIST)
def test_operator_patch_stores_a_model_on_the_list(operator_client, model):
    res, table = _operator_patch(operator_client, {"ai_reply_model": model})
    assert res.status_code == 200
    stored = table.upsert.call_args.args[0]
    assert (stored["key"], stored["value"]) == ("ai_reply_model", model)


# ---- tenant dashboard: PATCH /settings/ ----

@pytest.fixture
def tenant(monkeypatch):
    db = MagicMock()
    db.table.return_value.upsert.return_value.execute.return_value.data = [{"ok": True}]
    monkeypatch.setattr(app_settings, "get_supabase", lambda: db)
    monkeypatch.setattr(app_settings, "record_audit_event", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(app_settings.router, prefix="/api/v1/settings")
    app.dependency_overrides[app_settings.require_settings_manage] = lambda: {"tenant_id": "t1", "role": "owner"}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    return SimpleNamespace(client=TestClient(app), db=db)


@pytest.mark.parametrize("model", OFF_LIST)
def test_tenant_patch_refuses_a_model_off_the_list_and_writes_nothing(tenant, model):
    res = tenant.client.patch("/api/v1/settings/", json={"updates": {"business_name": "Shop", "ai_reply_model": model}})
    assert res.status_code == 400 and "Unknown reply model" in res.json()["detail"]
    tenant.db.table.assert_not_called()


def test_tenant_patch_accepts_a_model_on_the_list(tenant):
    res = tenant.client.patch("/api/v1/settings/", json={"updates": {"ai_reply_model": ON_LIST[1]}})
    assert res.status_code == 200


# ---- the removed providers are gone ----

@pytest.mark.parametrize("module", ["sarvam_client", "openai_client", "groq_client"])
def test_removed_provider_clients_do_not_exist(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"app.services.{module}")


def test_dev_safe_mode_no_longer_lets_calls_through_to_removed_providers():
    assert not {"api.sarvam.ai", "api.openai.com", "api.groq.com"} & set(outbound_guard._SAFE_HOSTS)
    assert {"generativelanguage.googleapis.com", "api.jina.ai"} <= set(outbound_guard._SAFE_HOSTS)

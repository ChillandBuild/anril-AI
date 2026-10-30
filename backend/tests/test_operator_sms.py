"""Operator SMS key handling: a key Bulk9 rejects is never saved, a good key is saved with a
fresh webhook secret, and neither the key nor the secret comes back in the response or the audit."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routes import operator_sms
from app.services.bulk9_client import Bulk9Error
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"
KEY = "live_key_abcdefghijklmnop"
ADMIN = {"user_id": "prem"}


def _db():
    db = FakeSupabase()
    db.add("tenants", id=T, name="Astro Tamil", enabled_features=["sms"])
    return db


def _settings_from(db):
    def get(key, tenant_id=None):
        for r in db.rows("app_settings"):
            if r["key"] == key and r.get("tenant_id") == tenant_id:
                return r["value"]
        return None
    return get


@pytest.mark.asyncio
async def test_rejected_key_is_not_saved():
    db = _db()
    with patch.object(operator_sms, "get_supabase", return_value=db), \
         patch.object(operator_sms.bulk9_client, "wallet", AsyncMock(side_effect=Bulk9Error("Invalid key"))):
        with pytest.raises(HTTPException) as exc:
            await operator_sms.save_key(T, operator_sms.KeyIn(api_key=KEY), ADMIN)
    assert exc.value.status_code == 400
    assert db.rows("app_settings") == []


@pytest.mark.asyncio
async def test_good_key_saved_with_webhook_secret_and_never_echoed():
    db = _db()
    get = _settings_from(db)
    audit, hook = [], AsyncMock(return_value={})
    with patch.object(operator_sms, "get_supabase", return_value=db), \
         patch.object(operator_sms, "get_setting", side_effect=get), \
         patch.object(operator_sms.sms_billing, "get_setting", side_effect=get), \
         patch.object(operator_sms, "invalidate_cache"), \
         patch.object(operator_sms, "record_audit_event", side_effect=lambda *a, **k: audit.append(k)), \
         patch.object(operator_sms.bulk9_client, "wallet", AsyncMock(return_value={"wallet": "12.5", "sms_count": 50})), \
         patch.object(operator_sms.bulk9_client, "create_sms_webhook", hook):
        out = await operator_sms.save_key(T, operator_sms.KeyIn(api_key=KEY), ADMIN)

    saved = {r["key"]: r for r in db.rows("app_settings")}
    assert saved["bulk9_api_key"]["value"] == KEY and saved["bulk9_api_key"]["is_secret"] is True
    secret = saved["bulk9_webhook_secret"]["value"]
    assert len(secret) >= 32 and saved["bulk9_webhook_secret"]["is_secret"] is True
    assert hook.await_args.kwargs["url"].endswith(f"/webhook/bulk9/{T}")
    assert hook.await_args.kwargs["secret"] == secret
    dumped = json.dumps(out, default=str) + json.dumps(audit, default=str)
    assert KEY not in dumped and secret not in dumped
    assert out["connected"] and out["webhook_registered"] and out["key_masked"] == "live••••••••mnop"
    assert out["balance"] == {"wallet": 12.5, "sms_count": 50}


def _payments_db(**row):
    db = _db()
    db.add("sms_payments", **{"id": "22222222-2222-2222-2222-222222222222", "tenant_id": T,
                              "amount_paise": 50000, "sms_count": 2000, "price_per_sms": "0.25", **row})
    return db


async def _retry(db):
    credit = AsyncMock(return_value=True)
    with patch.object(operator_sms, "get_supabase", return_value=db), \
         patch.object(operator_sms.sms_billing, "credit_payment", credit), \
         patch.object(operator_sms, "record_audit_event"), \
         patch.object(operator_sms, "_state", AsyncMock(return_value={})):
        await operator_sms.retry_credit(T, "22222222-2222-2222-2222-222222222222", ADMIN)
    return credit


@pytest.mark.asyncio
async def test_retry_refuses_an_underpaid_recharge():
    with pytest.raises(HTTPException) as exc:
        await _retry(_payments_db(status="amount_mismatch"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_retry_picks_up_a_recharge_stuck_as_paid():
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    credit = await _retry(_payments_db(status="paid", paid_at=old))
    credit.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_leaves_a_fresh_paid_recharge_alone():
    from datetime import datetime, timezone
    with pytest.raises(HTTPException):
        await _retry(_payments_db(status="paid", paid_at=datetime.now(timezone.utc).isoformat()))

"""Tenants can't read or write the operator-owned SMS keys through /api/v1/settings: writing
sms_price_per_sms would let a client buy SMS at any price it likes."""
import pytest
from fastapi import BackgroundTasks, HTTPException

from app.routes import app_settings
from app.routes.app_settings import SettingsUpdate, _operator_only


@pytest.mark.parametrize("key", ["sms_price_per_sms", "sms_buy_rate", "bulk9_username", "bulk9_api_key",
                                 "bulk9_webhook_secret", "sms_checklist", "sms_support_contact"])
def test_sms_keys_are_operator_only(key):
    assert _operator_only(key)


@pytest.mark.parametrize("key", ["razorpay_key_id", "telegram_bot_token", "business_description"])
def test_other_keys_are_not(key):
    assert not _operator_only(key)


@pytest.mark.asyncio
async def test_patch_rejects_sms_price():
    ctx = {"tenant_id": "t-1", "role": "owner", "user_id": "u", "permissions": ["settings.manage"]}
    with pytest.raises(HTTPException) as exc:
        await app_settings.update_settings(SettingsUpdate(updates={"sms_price_per_sms": "0.0001"}), BackgroundTasks(), ctx)
    assert exc.value.status_code == 403

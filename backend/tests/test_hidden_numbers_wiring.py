"""Call IQ hidden numbers (v9.2 #21): the queue and the lead list show 98•••••210 to a cloud telecaller."""
from unittest.mock import patch

from app.routes import calls, leads


def test_lead_list_masks_for_cloud_caller_only():
    rows = [{"id": "1", "phone": "+919876543210"}]
    with patch("app.services.call_rules.hides_numbers", return_value=True):
        leads._hide_numbers_for_caller(None, "t", {"role": "caller"}, rows)
    assert rows[0]["phone"] == "98•••••210" and rows[0]["phone_hidden"] is True

    rows = [{"id": "1", "phone": "+919876543210"}]
    with patch("app.services.call_rules.hides_numbers", return_value=True):
        leads._hide_numbers_for_caller(None, "t", {"role": "owner"}, rows)
    assert rows[0]["phone"] == "+919876543210"


def test_lead_list_keeps_numbers_when_rules_cannot_be_read():
    rows = [{"id": "1", "phone": "+919876543210"}]
    with patch("app.services.call_rules.hides_numbers", side_effect=RuntimeError("down")):
        leads._hide_numbers_for_caller(None, "t", {"role": "caller"}, rows)
    assert rows[0]["phone"] == "+919876543210"


def test_next_lead_masks_and_keeps_none():
    with patch("app.services.call_rules.hides_numbers", return_value=True), patch.object(calls, "get_supabase"):
        out = calls._mask_lead_phone({"tenant_id": "t", "role": "caller"}, {"id": "1", "phone": "+919876543210"})
        assert out["phone"] == "98•••••210"
        assert calls._mask_lead_phone({"tenant_id": "t"}, {"lead": None}) == {"lead": None}

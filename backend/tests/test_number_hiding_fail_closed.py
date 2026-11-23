"""Every list or file that carries a lead's number hides it for a cloud telecaller, and a broken check
hides it rather than showing it (audit 2026-11-23)."""
from unittest.mock import patch

from app.routes import calls as calls_routes
from app.services import call_rules
from app.services import password_help
from app.services import ai_setup_report

CALLER = {"tenant_id": "t", "role": "caller", "caller_id": "c1"}
OWNER = {"tenant_id": "t", "role": "owner"}


def test_owner_never_masked_even_if_check_breaks():
    with patch.object(call_rules, "hides_numbers", side_effect=RuntimeError("down")):
        assert call_rules.phone_mask_for(None, "t", OWNER) is None


def test_caller_masked_when_check_breaks():
    with patch.object(call_rules, "hides_numbers", side_effect=RuntimeError("down")):
        assert call_rules.phone_mask_for(None, "t", CALLER) is call_rules.mask_phone


def test_mode_lookup_failure_hides():
    with patch.object(call_rules, "get_rules", return_value={"hide_numbers_for_callers": True}), \
            patch.object(call_rules, "effective_calling_mode", side_effect=RuntimeError("down")):
        assert call_rules.hides_numbers(None, "t", CALLER) is True


def test_nested_lead_phone_masked_in_call_rows():
    rows = [{"id": 1, "leads": {"name": "Ravi", "phone": "+919876543210"}}, {"id": 2, "leads": None}]
    with patch.object(call_rules, "hides_numbers", return_value=True):
        out = calls_routes._mask_nested_lead_phones(None, CALLER, rows)
    assert out[0]["leads"]["phone"] == "98•••••210" and out[0]["leads"]["phone_hidden"] is True
    assert out[1]["leads"] is None


def test_nested_lead_phone_untouched_for_owner():
    rows = [{"leads": {"phone": "+919876543210"}}]
    assert calls_routes._mask_nested_lead_phones(None, OWNER, rows)[0]["leads"]["phone"] == "+919876543210"


def test_mask_lead_phone_fails_closed():
    with patch.object(call_rules, "hides_numbers", side_effect=RuntimeError("down")), \
            patch.object(calls_routes, "get_supabase", return_value=None):
        out = calls_routes._mask_lead_phone(CALLER, {"phone": "+919876543210"})
    assert out["phone"] == "98•••••210"


def test_leads_helper_fails_closed():
    from app.routes import leads as leads_routes
    leads = [{"phone": "+919876543210"}]
    with patch.object(call_rules, "hides_numbers", side_effect=RuntimeError("down")):
        leads_routes._hide_numbers_for_caller(None, "t", CALLER, leads)
    assert leads[0]["phone"] == "98•••••210"


def test_telecaller_without_profile_sees_no_questions():
    assert ai_setup_report._gap_handovers(None, "t", "2026-11-01", "") == []


def test_ai_setup_scope_never_empty_for_caller():
    from app.routes.ai_setup import _caller_scope
    assert _caller_scope({"role": "caller"}) == ""
    assert _caller_scope({"role": "caller", "caller_id": "c1"}) == "c1"
    assert _caller_scope(OWNER) is None


def test_ipv6_limited_per_64():
    a = password_help.ip_bucket("2401:4900:1c2a:5d3e::1")
    b = password_help.ip_bucket("2401:4900:1c2a:5d3e:abcd:ef01:2345:6789")
    assert a == b == "2401:4900:1c2a:5d3e::/64"
    assert password_help.ip_bucket("::ffff:1.2.3.4") == "1.2.3.4"
    assert password_help.ip_bucket("1.2.3.4") == "1.2.3.4"
    assert password_help.ip_bucket("") == "unknown"

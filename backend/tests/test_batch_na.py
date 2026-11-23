"""Batch N-A: hidden numbers on the one-lead and customer pages, and the report card counted in the database."""
import asyncio
from unittest.mock import patch

from app.routes import customer_profile, leads
from app.services import ai_setup_report as svc
from app.services.reports_common import Period
from datetime import date
from tests.fake_supabase import FakeSupabase

T = "t-na"
CALLER = {"tenant_id": T, "role": "caller", "caller_id": "c1"}
OWNER = {"tenant_id": T, "role": "owner"}


def _db_with_lead():
    db = FakeSupabase()
    db.add("leads", id="11111111-1111-1111-1111-111111111111", tenant_id=T, name="Asha", phone="+919876543210",
           source="whatsapp", deleted_at=None, assigned_to="c1")
    return db


def _get_lead(db, ctx):
    with patch.object(leads, "get_supabase", return_value=db):
        return asyncio.run(leads.get_lead("11111111-1111-1111-1111-111111111111", ctx))


def test_get_lead_masks_for_cloud_caller():
    with patch("app.services.call_rules.hides_numbers", return_value=True):
        lead = _get_lead(_db_with_lead(), CALLER)
    assert lead["phone"] == "98•••••210" and lead["phone_hidden"] is True


def test_get_lead_keeps_number_for_owner_and_sim_caller():
    lead = _get_lead(_db_with_lead(), OWNER)
    assert lead["phone"] == "+919876543210" and "phone_hidden" not in lead
    with patch("app.services.call_rules.hides_numbers", return_value=False):
        lead = _get_lead(_db_with_lead(), CALLER)
    assert lead["phone"] == "+919876543210"


def test_get_lead_still_scoped_to_the_tenant():
    from fastapi import HTTPException
    try:
        _get_lead(_db_with_lead(), {"tenant_id": "other", "role": "owner"})
    except HTTPException as e:
        assert e.status_code == 404
    else:
        raise AssertionError("another business must not see this lead")


def test_customer_page_phone_helper():
    with patch("app.services.call_rules.hides_numbers", return_value=True):
        assert customer_profile._phone_for(None, T, CALLER, "+919876543210") == ("98•••••210", True)
        assert customer_profile._phone_for(None, T, OWNER, "+919876543210") == ("+919876543210", False)
    assert customer_profile._phone_for(None, T, CALLER, None) == (None, False)
    with patch("app.services.call_rules.hides_numbers", side_effect=RuntimeError("down")):
        assert customer_profile._phone_for(None, T, CALLER, "+919876543210") == ("+919876543210", False)


def test_customer_page_masks_phone_in_response():
    db = FakeSupabase()
    db.add("leads", id="22222222-2222-2222-2222-222222222222", tenant_id=T, name="Ravi", phone="+919123456789",
           deleted_at=None, assigned_to="c1")
    with patch.object(customer_profile, "get_supabase", return_value=db), \
            patch("app.services.call_rules.hides_numbers", return_value=True):
        out = customer_profile.customer_profile("22222222-2222-2222-2222-222222222222", CALLER)
    assert out["lead"]["phone"] == "91•••••789" and out["lead"]["phone_hidden"] is True


# ── the report card counted in the database ─────────────────────────────────

PERIOD = Period(date(2026, 11, 1), date(2026, 11, 30))


def test_report_card_uses_database_counts_when_present():
    db = FakeSupabase()
    seen = {}

    def handler(p):
        seen.update(p)
        return [{"chats": 10, "handled_alone": 7, "handed_over": 3, "knowledge_gaps": 2}]

    db.rpc_handlers["ai_report_card_counts"] = handler
    got = svc._handled(db, T, PERIOD)
    assert got == {"chats": 10, "handled_by_aira": 7, "handed_over": 3, "knowledge_gaps": 2}
    assert seen["p_tenant_id"] == T and seen["p_start"] == PERIOD.start_iso and seen["p_end"] == PERIOD.end_iso


def test_report_card_falls_back_when_function_missing():
    db = FakeSupabase()  # no handler registered: the rpc call fails like a missing function
    db.add("messages", tenant_id=T, lead_id="l1", direction="inbound", is_ai_generated=False,
           created_at="2026-11-10T05:00:00+00:00")
    db.add("messages", tenant_id=T, lead_id="l1", direction="outbound", is_ai_generated=True, reply_source="ai",
           created_at="2026-11-10T05:01:00+00:00")
    got = svc._handled(db, T, PERIOD)
    assert got["chats"] == 1 and got["handled_by_aira"] == 1 and got["handed_over"] == 0


def test_report_card_falls_back_on_odd_answer():
    db = FakeSupabase()
    db.rpc_handlers["ai_report_card_counts"] = lambda p: None
    assert svc._counts_in_database(db, T, PERIOD) is None
    db.rpc_handlers["ai_report_card_counts"] = lambda p: [{"chats": "x"}]
    assert svc._counts_in_database(db, T, PERIOD) is None


def test_migration_326_matches_python_classification():
    """The SQL lists the same handover reasons the Python classifier calls a missing answer."""
    import pathlib
    from app.services.brain import handovers as hv
    sql = (pathlib.Path(__file__).parents[1] / "supabase/migrations/326_ai_report_card_counts.sql").read_text()
    for reason in hv._KNOWLEDGE_GAP:
        assert f"'{reason}'" in sql, reason
    for reason in hv._ASKED_FOR_HUMAN:
        assert f"'{reason}'" in sql
    assert "payment link could not be created" in sql
    assert "service_role" in sql

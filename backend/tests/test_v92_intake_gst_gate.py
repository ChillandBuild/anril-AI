"""v9.2: GST on WhatsApp intake forms follows the business's GST type, like its bills."""
import json
from unittest.mock import patch

from app.services import deal_engine, intake
from fake_supabase import FakeSupabase

T = "t1"


def _db(gst_percent):
    db = FakeSupabase()
    db.add("app_settings", tenant_id=T, key="intake_config", value=json.dumps({"enabled": True, "gst_percent": gst_percent}))
    return db


def test_regular_gst_business_keeps_its_percent():
    with patch("app.services.business_details.charges_gst", return_value=True):
        cfg = intake.get_intake_config(T, db=_db(18))
    assert "gst_blocked" not in cfg and intake.effective_gst_percent(cfg) == 18 and deal_engine.gst_percent(cfg) == 18


def test_composition_or_unregistered_adds_no_gst_but_keeps_the_saved_percent():
    db = _db(18)
    with patch("app.services.business_details.charges_gst", return_value=False):
        cfg = intake.get_intake_config(T, db=db)
    assert cfg["gst_blocked"] is True and cfg["gst_percent"] == 18
    assert intake.effective_gst_percent(cfg) == 0 and deal_engine.gst_percent(cfg) == 0
    assert intake.gst_session_fields(100000, intake.effective_gst_percent(cfg))["amount_paise"] == 100000
    intake.save_intake_config(T, cfg, db=db)  # saving never stores the worked-out flag
    stored = json.loads(next(r for r in db.rows("app_settings") if r["key"] == "intake_config")["value"])
    assert "gst_blocked" not in stored and stored["gst_percent"] == 18


def test_no_gst_set_needs_no_business_lookup():
    with patch("app.services.business_details.charges_gst", side_effect=AssertionError("not needed")):
        cfg = intake.get_intake_config(T, db=_db(0))
    assert intake.effective_gst_percent(cfg) == 0

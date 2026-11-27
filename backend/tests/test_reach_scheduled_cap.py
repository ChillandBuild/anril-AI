"""A scheduled / drip Reach run applies the weekly limit and the blocked skip too (services/broadcast_executor.py)."""
import asyncio
import json
import sys
import uuid
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import broadcast_executor as ex
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"


class _Picker:
    def __init__(self, tenant_id, **_kw): pass
    def next(self): return {"id": "n1", "meta_phone_number_id": "pn1"}
    async def record_sent(self, sender): pass
    def numbers_used_label(self): return "+910000000000"


class ScheduledCapTests(unittest.TestCase):
    def test_scheduled_run_skips_capped_and_blocked_people(self):
        db = FakeSupabase()
        recent = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        for p in ("+919000000001", "+919000000002", "+919000000003", "+919000000004"):
            db.rows("leads").append({"id": "L" + p[-1], "tenant_id": T1, "phone": p, "deleted_at": None,
                                     **({"blocked_at": "2026-11-01"} if p.endswith("2") else {})})
        for b in ("b1", "b2"):   # 0003 already got two this week; so did 0004, but in ANOTHER tenant's data only
            db.rows("broadcast_recipients").append({"id": str(uuid.uuid4()), "tenant_id": T1, "broadcast_id": b,
                                                    "phone": "+919000000003", "send_status": "sent", "created_at": recent})
            db.rows("broadcast_recipients").append({"id": str(uuid.uuid4()), "tenant_id": T2, "broadcast_id": b,
                                                    "phone": "+919000000004", "send_status": "sent", "created_at": recent})
        db.rows("message_templates").append({"tenant_id": T1, "name": "diwali", "status": "APPROVED",
                                             "language": "en", "body_text": "hi", "variations": []})
        db.rows("scheduled_broadcasts").append({
            "id": "sb1", "tenant_id": T1, "status": "pending", "template_name": "diwali",
            "leads_json": [{"phone": p, "name": "x"} for p in ("+919000000001", "+919000000002", "+919000000003", "+919000000004")],
            "variable_mapping": [], "opt_in_source": "website"})
        row = dict(db.rows("scheduled_broadcasts")[0])
        send = AsyncMock(return_value={"messages": [{"id": "w"}]})
        with patch.object(ex, "get_supabase", return_value=db), patch.object(ex, "SenderPicker", _Picker), \
                patch.object(ex, "send_template_message", new=send), patch.object(ex, "meter"), \
                patch.object(ex, "new_lead_score_and_segment", return_value=(10, "C")):
            result = asyncio.run(ex.execute_broadcast(row))
        self.assertEqual(sorted(c.kwargs["to_number"] for c in send.call_args_list), ["+919000000001", "+919000000004"])
        self.assertEqual((result["sent"], result["failed"], result["skipped_weekly_limit"], result["skipped_blocked"]), (2, 0, 1, 1))
        reasons = {r["phone"]: r.get("fail_reason") for r in db.rows("broadcast_recipients") if r["broadcast_id"] == "sb1"}
        self.assertEqual(reasons["+919000000002"], "blocked")
        self.assertEqual(reasons["+919000000003"], "weekly_limit")
        entry = json.loads(next(r for r in db.rows("app_settings") if r["key"] == "broadcast_history")["value"])[0]
        self.assertEqual((entry["skipped_weekly_limit"], entry["skipped_blocked"]), (1, 1))

    def test_scheduled_run_sends_picked_over_limit_people(self):
        db = FakeSupabase()
        recent = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        for p in ("+919000000005", "+919000000006"):
            db.rows("leads").append({"id": "L" + p[-1], "tenant_id": T1, "phone": p, "deleted_at": None})
            for b in ("b1", "b2"):
                db.rows("broadcast_recipients").append({"id": str(uuid.uuid4()), "tenant_id": T1, "broadcast_id": b,
                                                        "phone": p, "send_status": "sent", "created_at": recent})
        db.rows("message_templates").append({"tenant_id": T1, "name": "diwali", "status": "APPROVED",
                                             "language": "en", "body_text": "hi", "variations": []})
        db.rows("scheduled_broadcasts").append({
            "id": "sb2", "tenant_id": T1, "status": "pending", "template_name": "diwali",
            "leads_json": [{"phone": "+919000000005", "name": "x", "send_over_limit": True},
                           {"phone": "+919000000006", "name": "y"}],
            "variable_mapping": [], "opt_in_source": "website"})
        row = dict(db.rows("scheduled_broadcasts")[0])
        send = AsyncMock(return_value={"messages": [{"id": "w"}]})
        with patch.object(ex, "get_supabase", return_value=db), patch.object(ex, "SenderPicker", _Picker), \
                patch.object(ex, "send_template_message", new=send), patch.object(ex, "meter"), \
                patch.object(ex, "new_lead_score_and_segment", return_value=(10, "C")):
            result = asyncio.run(ex.execute_broadcast(row))
        self.assertEqual([c.kwargs["to_number"] for c in send.call_args_list], ["+919000000005"])
        self.assertEqual((result["sent"], result["skipped_weekly_limit"]), (1, 1))
        reasons = {r["phone"]: r.get("fail_reason") for r in db.rows("broadcast_recipients") if r["broadcast_id"] == "sb2"}
        self.assertEqual(reasons["+919000000006"], "weekly_limit")


if __name__ == "__main__":
    unittest.main()

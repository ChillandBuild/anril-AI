"""Regression tests for the 2026-11-23 code security audit.

Each test fails on the code before the fix:
  1. chat "send media" used the default tenant's WhatsApp number (no tenant_id passed)
  2. /templates/webhook-status wrote every tenant's copy of a template, not just the signed one's
  3. a TeleCMI CDR signed with tenant A's secret could rewrite tenant B's call log
  4. a lead note / phone callback could be created on another tenant's lead, and call
     scoring read every tenant's notes on that lead
  5. any team member could rewrite the AI business description through onboarding,
     add/delete voice numbers, or delete call logs
"""
import asyncio
import inspect
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies.tenant import get_owner_tenant_id, require_owner


class _Res:
    def __init__(self, data=None):
        self.data = data
        self.count = 0


class _Q:
    """Chainable fake: records filters, answers selects from `rows(table, filters)`."""

    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload, self.filters = db, table, None, None, {}

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def neq(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        self.db.ops.append((self.table, self.op, dict(self.filters), self.payload))
        if self.op == "select":
            return _Res(self.db.rows(self.table, self.filters))
        if self.op == "insert":
            return _Res([{"id": "new-id", **(self.payload or {})}])
        return _Res([{"id": "x"}])


class _DB:
    def __init__(self, rows):
        self.rows, self.ops = rows, []

    def table(self, name):
        return _Q(self, name)

    def inserts(self, table):
        return [p for t, op, f, p in self.ops if t == table and op == "insert"]


MINE, THEIRS = "tenant-mine", "tenant-theirs"


def _owned_by(tenant):
    """Rows exist only when the query is scoped to `tenant`."""
    return lambda table, f: [{"id": f.get("id", "row")}] if f.get("tenant_id") == tenant else []


class SendMediaUsesOwnNumber(unittest.TestCase):
    def test_upload_and_send_carry_the_tenant(self):
        from app.routes import media

        db = _DB(lambda t, f: {"phone": "+919800000000", "source": "whatsapp"} if f.get("tenant_id") == MINE else None)
        upload = AsyncMock(return_value="media-1")
        send = AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})

        class _File:
            filename, content_type = "a.png", "image/png"

            async def read(self):
                return b"\x89PNG...."

        with patch.object(media, "get_supabase", return_value=db), \
                patch.object(media, "upload_media_to_meta", upload), \
                patch.object(media, "send_media_message", send), \
                patch.object(media, "sender_fields", return_value={}, create=True):
            try:
                asyncio.run(media.send_media_to_lead(
                    lead_id="11111111-1111-1111-1111-111111111111", file=_File(), caption=None,
                    ctx={"tenant_id": MINE, "user_id": "u1", "role": "owner"},
                ))
            except Exception:
                pass  # only the provider calls matter here
        self.assertEqual(upload.await_args.kwargs.get("tenant_id"), MINE)
        self.assertEqual(send.await_args.kwargs.get("tenant_id"), MINE)


class TemplateWebhookScopedToSignedTenant(unittest.TestCase):
    def test_apply_is_scoped(self):
        from app.routes import templates

        body = {"entry": [{"changes": [
            {"field": "message_template_status_update", "value": {"message_template_id": "111", "event": "APPROVED"}},
            {"field": "message_template_status_update", "value": {"message_template_id": "222", "event": "REJECTED"}},
        ]}]}
        seen = []
        with patch.object(templates, "tenant_for_template_payload", return_value=MINE), \
                patch.object(templates, "verify_meta_signature", return_value=True), \
                patch.object(templates, "apply_template_change",
                             side_effect=lambda db, field, value, tenant_id=None: seen.append(tenant_id)), \
                patch.object(templates, "get_supabase", return_value=_DB(lambda t, f: [])):
            res = TestClient(app).post("/api/v1/templates/webhook-status", json=body,
                                       headers={"X-Hub-Signature-256": "sha256=x"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(seen, [MINE, MINE])


class TeleCmiCdrStaysInItsTenant(unittest.TestCase):
    def test_cdr_for_another_tenants_call_log_is_ignored(self):
        from tests.test_telecmi_cdr_legs import CALL_LOG_ID, LEG_B_ANSWERED, WEBHOOK_SECRET, FakeDB, _call_log

        db = FakeDB(_call_log(tenant_id=THEIRS))
        with patch("app.routes.calls.get_setting", return_value=WEBHOOK_SECRET), \
                patch("app.routes.calls.get_supabase", return_value=db), \
                patch("app.routes.calls.queue_call_ai") as queued, \
                patch("app.routes.calls.run_call_ai"), \
                patch("app.routes.calls.finalize_call_score"), \
                patch("app.routes.calls.meter"):
            res = TestClient(app).post(f"/api/v1/calls/telecmi-cdr/{MINE}",
                                       params={"webhook_secret": WEBHOOK_SECRET}, json=LEG_B_ANSWERED)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(db.updates_to("call_logs"), [])
        queued.assert_not_called()
        self.assertTrue(CALL_LOG_ID)

    def test_cdr_for_own_call_log_still_applies(self):
        from tests.test_telecmi_cdr_legs import LEG_B_ANSWERED, WEBHOOK_SECRET, FakeDB, _call_log

        db = FakeDB(_call_log(tenant_id=MINE))
        with patch("app.routes.calls.get_setting", return_value=WEBHOOK_SECRET), \
                patch("app.routes.calls.get_supabase", return_value=db), \
                patch("app.routes.calls.queue_call_ai"), \
                patch("app.routes.calls.run_call_ai"), \
                patch("app.routes.calls.finalize_call_score"), \
                patch("app.routes.calls.get_telecalling_config", return_value={"targets": {}}), \
                patch("app.routes.calls.meter"):
            TestClient(app).post(f"/api/v1/calls/telecmi-cdr/{MINE}",
                                 params={"webhook_secret": WEBHOOK_SECRET}, json=LEG_B_ANSWERED)
        self.assertIn("completed", [u.get("status") for u in db.updates_to("call_logs")])


class NotesAndCallbacksOnlyOnOwnLeads(unittest.TestCase):
    def test_note_on_foreign_lead_is_404(self):
        from app.routes import lead_notes

        db = _DB(_owned_by(THEIRS))
        payload = lead_notes.CreateNote(content="pay to upi x@y")
        with patch.object(lead_notes, "get_supabase", return_value=db):
            with self.assertRaises(HTTPException) as e:
                asyncio.run(lead_notes.create_lead_note(
                    "11111111-1111-1111-1111-111111111111", payload, ctx={"tenant_id": MINE}))
        self.assertEqual(e.exception.status_code, 404)
        self.assertEqual(db.inserts("lead_notes"), [])

    def test_note_with_foreign_call_is_404(self):
        from app.routes import lead_notes

        db = _DB(lambda t, f: [{"id": "r"}] if (t == "leads" and f.get("tenant_id") == MINE) else [])
        payload = lead_notes.CreateNote(content="hi", call_log_id="22222222-2222-2222-2222-222222222222")
        with patch.object(lead_notes, "get_supabase", return_value=db):
            with self.assertRaises(HTTPException):
                asyncio.run(lead_notes.create_lead_note(
                    "11111111-1111-1111-1111-111111111111", payload, ctx={"tenant_id": MINE}))
        self.assertEqual(db.inserts("lead_notes"), [])

    def test_note_on_own_lead_is_saved(self):
        from app.routes import lead_notes

        db = _DB(_owned_by(MINE))
        with patch.object(lead_notes, "get_supabase", return_value=db):
            asyncio.run(lead_notes.create_lead_note(
                "11111111-1111-1111-1111-111111111111", lead_notes.CreateNote(content="ok"),
                ctx={"tenant_id": MINE}))
        self.assertEqual(len(db.inserts("lead_notes")), 1)

    def test_callback_on_foreign_lead_is_404(self):
        from app.routes import follow_ups

        db = _DB(_owned_by(THEIRS))
        body = follow_ups.CallbackCreate(lead_id="11111111-1111-1111-1111-111111111111",
                                         scheduled_for="2026-11-24T10:00:00Z")
        with patch.object(follow_ups, "get_supabase", return_value=db):
            with self.assertRaises(HTTPException) as e:
                asyncio.run(follow_ups.create_callback(body, ctx={"tenant_id": MINE}))
        self.assertEqual(e.exception.status_code, 404)
        self.assertEqual(db.inserts("follow_up_jobs"), [])

    def test_call_scoring_reads_only_own_notes(self):
        from app.services import call_ai_pipeline

        db = _DB(lambda t, f: [{"content": "theirs"}] if f.get("tenant_id") != MINE else [{"content": "mine"}])
        self.assertEqual(call_ai_pipeline._previous_notes(db, "lead-1", "call-1", MINE), "- mine")
        self.assertEqual(call_ai_pipeline._previous_notes(db, "lead-1", "call-1", None), "")


def _deps(fn):
    return {p.default.dependency for p in inspect.signature(fn).parameters.values()
            if hasattr(p.default, "dependency")}


class OwnerOnlyRoutes(unittest.TestCase):
    def test_onboarding_writes_are_owner_only(self):
        from app.routes import onboarding

        for fn in (onboarding.apply_starter, onboarding.interview_draft, onboarding.interview_apply):
            self.assertIn(get_owner_tenant_id, _deps(fn), fn.__name__)

    def test_voice_number_writes_are_owner_only(self):
        from app.routes import voice_numbers

        for fn in (voice_numbers.create_voice_number, voice_numbers.update_voice_number,
                   voice_numbers.delete_voice_number):
            self.assertIn(get_owner_tenant_id, _deps(fn), fn.__name__)

    def test_delete_call_log_is_owner_only(self):
        from app.routes import calls

        self.assertIn(require_owner, _deps(calls.delete_call_log))


if __name__ == "__main__":
    unittest.main()

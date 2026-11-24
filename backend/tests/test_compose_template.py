"""New message form (POST /api/v1/leads/compose): free text, or an approved template.

A number that hasn't written in 24 hours only accepts a template, so the form
can now send one to any number, new or existing.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import leads as leads_route
from app.services import call_details_share as share
from tests.test_call_details_share import _Base
from tests.fake_supabase import FakeSupabase


class SendApprovedTemplateTests(_Base):
    async def test_sends_to_any_phone_and_returns_the_rendered_text(self):
        sid, content = await share.send_approved_template(self.db, "t1", "+919811112222", "tpl-2", ["Ravi", "see you soon"])
        self.assertEqual(self.send_template.await_args.args, ("+919811112222", "promo", "en"))
        self.assertEqual((sid, content), ("wamid.2", "Hi Ravi see you soon"))

    async def test_unapproved_or_media_templates_are_refused(self):
        for template_id in ("tpl-3", "tpl-4", "tpl-5"):
            with self.assertRaises(share.ShareError):
                await share.send_approved_template(self.db, "t1", "+919811112222", template_id, [])
        self.send_template.assert_not_awaited()

    async def test_every_blank_must_be_filled(self):
        with self.assertRaises(share.ShareError) as err:
            await share.send_approved_template(self.db, "t1", "+919811112222", "tpl-2", ["Ravi"])
        self.assertEqual(str(err.exception), "Fill every blank in the template.")

    def test_compose_templates_lists_only_sendable_ones_with_business_prefilled(self):
        rows = share.compose_templates(self.db, "t1")
        self.assertEqual([t["name"] for t in rows], ["call_details_share", "promo"])
        roles = {v["role"]: v["value"] for v in rows[0]["variables"] if v["role"]}
        self.assertEqual(roles.get("business_name"), "Astro Tamil")
        self.assertEqual(roles.get("customer_name"), "")


class ComposeRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "t1", "role": "owner", "user_id": "u1", "permissions": [],
        }
        self.db = FakeSupabase()
        self.db.add("leads", id="lead-1", tenant_id="t1", phone="+919811112222", name=None)
        for target, value in (("get_supabase", lambda: self.db),):
            p = patch.object(leads_route, target, side_effect=value)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_template_is_sent_and_saved_as_the_rendered_text(self):
        sender = AsyncMock(return_value=("wamid.9", "Hi Ravi see you soon"))
        with patch.object(leads_route, "send_approved_template", sender), \
             patch.object(leads_route, "send_whatsapp", AsyncMock()) as free_text:
            res = self.client.post("/api/v1/leads/compose", json={
                "phone": "+91 98111 12222", "template_id": "tpl-2", "variables": ["Ravi", "see you soon"],
            })
        self.assertEqual(res.status_code, 200, res.text)
        sender.assert_awaited_once()
        self.assertEqual(sender.await_args.args[2:], ("+919811112222", "tpl-2", ["Ravi", "see you soon"]))
        free_text.assert_not_awaited()
        saved = self.db.rows("messages")
        self.assertEqual([(m["content"], m["meta_message_id"]) for m in saved], [("Hi Ravi see you soon", "wamid.9")])

    def test_template_problems_come_back_as_400(self):
        sender = AsyncMock(side_effect=share.ShareError("Fill every blank in the template."))
        with patch.object(leads_route, "send_approved_template", sender):
            res = self.client.post("/api/v1/leads/compose", json={"phone": "+919811112222", "template_id": "tpl-2"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"], "Fill every blank in the template.")
        self.assertEqual(self.db.rows("messages"), [])

    def test_text_and_template_together_or_neither_are_refused(self):
        both = self.client.post("/api/v1/leads/compose", json={"phone": "+919811112222", "content": "Hi", "template_id": "tpl-2"})
        neither = self.client.post("/api/v1/leads/compose", json={"phone": "+919811112222"})
        self.assertEqual((both.status_code, neither.status_code), (400, 400))

    def test_free_text_still_works(self):
        with patch.object(leads_route, "send_whatsapp", AsyncMock(return_value="wamid.1")) as free_text:
            res = self.client.post("/api/v1/leads/compose", json={"phone": "+919811112222", "content": "Hello"})
        self.assertEqual(res.status_code, 200, res.text)
        free_text.assert_awaited_once_with("+919811112222", "Hello", tenant_id="t1", phone_number_id=None)

    def test_templates_endpoint_needs_leads_manage(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "t1", "role": "caller", "user_id": "u1", "permissions": ["leads.view"],
        }
        self.assertEqual(self.client.get("/api/v1/leads/compose/templates").status_code, 403)

    def test_templates_endpoint_lists_options(self):
        with patch.object(leads_route, "compose_templates", return_value=[{"id": "tpl-2", "name": "promo"}]):
            res = self.client.get("/api/v1/leads/compose/templates")
        self.assertEqual(res.json(), {"templates": [{"id": "tpl-2", "name": "promo"}]})


if __name__ == "__main__":
    unittest.main()

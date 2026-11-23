"""The admin MCP's gap tools (app/admin_mcp/tools_gaps.py), run against a fake database with the
read-only guard ON: each returns the chosen client's data and never another client's, never
carries a stored secret, and makes no write."""
import copy
import inspect
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver.exceptions import ToolError

from app import config_dynamic
from app.admin_mcp import tools_gaps, wrapper
from app.db import supabase as supabase_db
from app.services import ai_reply
from tests.fake_supabase import FakeSupabase

A, B = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
USER_A, USER_B = "user-a", "user-b"
EMAILS = {USER_A: "owner-a@example.com", USER_B: "owner-b@example.com"}
TODAY = datetime.now(timezone.utc).date().isoformat()

# Seeded where the code under test (not the fake's column list) decides what is returned.
SECRETS = [
    "SECRET-TELECMI-A", "SECRET-NUMBER-TOKEN", "SECRET-KEY-HASH", "SECRET-KEY-PREFIX",
    "SECRET-AUDIT-TOKEN", "SECRET-AUDIT-NESTED", "SECRET-META-TOKEN",
]
CLIENT_TOOLS = [
    "client_team", "client_templates", "client_numbers", "client_knowledge",
    "client_calling_provider", "client_private_send", "client_audit_logs",
]
PLATFORM_TOOLS = ["subscription_plans", "master_prompt", "provider_rates", "clients_waiting"]


def build_db() -> FakeSupabase:
    db = FakeSupabase()
    db.auth = SimpleNamespace(admin=SimpleNamespace(
        get_user_by_id=lambda uid: SimpleNamespace(user=SimpleNamespace(email=EMAILS[uid]))))
    db.add("tenants", id=A, name="Alpha Astro", enabled_features=["telecalling", "private_send"], status="active")
    db.add("tenants", id=B, name="Beta Bakery", enabled_features=[], status="active")
    db.add("tenant_users", tenant_id=A, user_id=USER_A, role="owner", created_at="2026-01-02")
    db.add("tenant_users", tenant_id=B, user_id=USER_B, role="owner", created_at="2026-01-03")
    db.add("callers", id="c-a", tenant_id=A, name="Asha Caller", active=True, user_id=None,
           shift_start_hour=9, shift_end_hour=18)
    db.add("callers", id="c-b", tenant_id=B, name="Bala Caller", active=True, user_id=None,
           shift_start_hour=9, shift_end_hour=18)
    db.add("app_settings", tenant_id=A, key="telecalling_config", value=json.dumps({"calling_provider": "telecmi"}))
    db.add("app_settings", tenant_id=B, key="telecalling_config", value=json.dumps({"calling_provider": "sim_basic"}))
    db.add("app_settings", tenant_id=A, key="telecmi_secret", value="SECRET-TELECMI-A")
    db.add("app_settings", tenant_id=A, key="meta_access_token", value="SECRET-META-TOKEN")
    db.add("app_settings", tenant_id=A, key="private_send_monthly_cap", value="500")
    db.add("app_settings", tenant_id=A, key="private_send_reply_mode", value="aira")
    db.add("message_templates", id="t-a", tenant_id=A, name="alpha_welcome", status="APPROVED",
           category="UTILITY", language="en", submitted_at="2026-02-01")
    db.add("message_templates", id="t-b", tenant_id=B, name="beta_promo", status="PENDING",
           category="MARKETING", language="en", submitted_at="2026-02-02")
    db.add("phone_numbers", tenant_id=A, number="+911111111111", display_name="Alpha Line", status="active",
           quality_rating="green", messaging_tier="TIER_1K", access_token="SECRET-NUMBER-TOKEN")
    db.add("phone_numbers", tenant_id=B, number="+922222222222", display_name="Beta Line", status="active",
           quality_rating="green", messaging_tier="TIER_1K", access_token="SECRET-NUMBER-TOKEN")
    db.add("knowledge_documents", id="doc-a", tenant_id=A, name="alpha-guide.pdf", file_type="pdf")
    db.add("knowledge_documents", id="doc-b", tenant_id=B, name="beta-menu.pdf", file_type="pdf", status="failed")
    db.add("knowledge_chunks", id="ch-a1", tenant_id=A, document_id="doc-a")
    db.add("knowledge_chunks", id="ch-a2", tenant_id=A, document_id="doc-a")
    db.add("knowledge_chunks", id="ch-b1", tenant_id=B, document_id="doc-b")
    db.add("knowledge_reviews", id="rev-a", tenant_id=A, document_id="doc-a", status="pending",
           created_at="2026-01-05T00:00:00Z")
    db.add("private_send_keys", id="key-a", tenant_id=A, key_prefix="SECRET-KEY-PREFIX", key_hash="SECRET-KEY-HASH",
           status="active", created_at="2026-03-01", last_seen_at="2026-03-02", plugin_version="1.0", revoked_at=None)
    db.add("private_send_keys", id="key-b", tenant_id=B, key_prefix="BETA-PREFIX", key_hash="BETA-HASH",
           status="active", created_at="2026-03-01", last_seen_at=None, plugin_version="1.0", revoked_at=None)
    db.add("private_send_usage", tenant_id=A, day=TODAY, event="otp", template_id="t-a", reported_sent=7, reported_failed=0)
    db.add("private_send_usage", tenant_id=B, day=TODAY, event="otp", template_id="t-b", reported_sent=999, reported_failed=0)
    db.add("app_audit_logs", id="log-a", tenant_id=A, actor_user_id=USER_A, actor_role="owner",
           action="alpha.changed", target_type="x", target_id="1", created_at="2026-04-01T10:00:00Z",
           metadata={"token": "SECRET-AUDIT-TOKEN", "nested": {"api_key": "SECRET-AUDIT-NESTED"}, "note": "fine"})
    db.add("app_audit_logs", id="log-b", tenant_id=B, actor_user_id=USER_B, actor_role="owner",
           action="beta.changed", target_type="x", target_id="2", created_at="2026-04-01T11:00:00Z", metadata={})
    db.add("feature_catalog", feature_key="whatsapp", display_name="WhatsApp", category="channels", sort_order=1,
           monthly_price=100, depends_on=[])
    db.add("plans", id="plan-1", name="Starter", monthly_price=500, feature_keys=["whatsapp"], active=True,
           created_at="2026-01-01")
    db.add("plans", id="plan-old", name="Retired", monthly_price=1, feature_keys=[], active=False, created_at="2026-01-01")
    db.add("platform_defaults", key="default_master_prompt", value="MASTER PROMPT TEXT")
    db.add("provider_model_rates", provider="gemini", model="flash", input_rate_per_1k_inr=1,
           output_rate_per_1k_inr=2, updated_at="2026-01-01")
    db.rpc_handlers["distinct_token_usage_pairs"] = lambda p: [
        {"provider": "gemini", "model": "flash"}, {"provider": "sarvam", "model": "m1"}]
    return db


class GapToolsBase(unittest.TestCase):
    def setUp(self):
        self.db = build_db()
        config_dynamic._CACHE.clear()
        ai_reply.invalidate_prompt_cache()
        patcher = patch.object(supabase_db, "_client", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        token = supabase_db.read_only.set(True)  # what the wrapper does around every tool call
        self.addCleanup(supabase_db.read_only.reset, token)
        self.addCleanup(config_dynamic._CACHE.clear)
        self.addCleanup(ai_reply.invalidate_prompt_cache)

    def _rows(self):
        # The fake creates an empty list for any table that is merely read; only rows count.
        return copy.deepcopy({t: rows for t, rows in self.db.tables.items() if rows})

    def run_tool(self, name, *args, **kwargs):
        before = self._rows()
        out = wrapper.REGISTRY[name].fn(*args, **kwargs)
        self.assertEqual(self._rows(), before, f"{name} changed the database")
        text = json.dumps(out, default=str)
        for secret in SECRETS:
            self.assertNotIn(secret, text, f"{name} leaked {secret}")
        return out, text


class RegistrationTests(GapToolsBase):
    def test_every_gap_tool_is_registered(self):
        for name in CLIENT_TOOLS + PLATFORM_TOOLS:
            self.assertIn(name, wrapper.REGISTRY)

    def test_client_tools_take_client_first_and_the_guard_is_on(self):
        for name in CLIENT_TOOLS:
            self.assertEqual(next(iter(inspect.signature(wrapper.REGISTRY[name].fn).parameters)), "client", name)
        with self.assertRaises(supabase_db.ReadOnlyViolation):
            supabase_db.get_supabase().table("tenants").update({"name": "x"})

    def test_an_unknown_client_is_a_clear_error(self):
        for name in CLIENT_TOOLS:
            with self.assertRaises(ToolError):
                wrapper.REGISTRY[name].fn("Nobody Ltd")


class ClientToolTests(GapToolsBase):
    def test_client_team(self):
        out, text = self.run_tool("client_team", "Alpha Astro")
        self.assertEqual(out["owner"]["email"], "owner-a@example.com")
        self.assertEqual([c["name"] for c in out["callers"]], ["Asha Caller"])
        self.assertEqual(out["calling_provider"], "telecmi")
        for other in ("Bala Caller", "owner-b@example.com"):
            self.assertNotIn(other, text)

    def test_client_templates(self):
        out, text = self.run_tool("client_templates", "Alpha Astro")
        self.assertEqual((out["total"], out["approved"]), (1, 1))
        self.assertIn("alpha_welcome", text)
        self.assertNotIn("beta_promo", text)

    def test_client_templates_cut_long_lists(self):
        for i in range(60):
            self.db.add("message_templates", tenant_id=A, name=f"bulk_{i}", status="APPROVED", submitted_at="2026-05-01")
        out, _ = self.run_tool("client_templates", "Alpha Astro")
        self.assertEqual(len(out["templates"]), 50)
        self.assertEqual(out["total"], 61)
        self.assertIn("first 50 of 61", out["note"])

    def test_client_numbers(self):
        out, text = self.run_tool("client_numbers", "Alpha Astro")
        self.assertEqual((out["total"], out["active"]), (1, 1))
        self.assertIn("+911111111111", text)
        self.assertNotIn("+922222222222", text)

    def test_client_knowledge(self):
        out, text = self.run_tool("client_knowledge", "Alpha Astro")
        self.assertEqual((out["total_docs"], out["total_chunks"]), (1, 2))
        self.assertEqual(out["documents"][0]["chunk_count"], 2)
        self.assertIn("alpha-guide.pdf", text)
        self.assertNotIn("beta-menu.pdf", text)

    def test_client_calling_provider(self):
        out, _ = self.run_tool("client_calling_provider", "Alpha Astro")
        self.assertEqual(out, {"tenant_id": A, "calling_provider": "telecmi", "telecalling_enabled": True})
        out, _ = self.run_tool("client_calling_provider", "Beta Bakery")
        self.assertEqual((out["calling_provider"], out["telecalling_enabled"]), ("sim_basic", False))

    def test_client_private_send_shows_keys_as_status_and_dates_only(self):
        out, text = self.run_tool("client_private_send", "Alpha Astro")
        self.assertTrue(out["enabled"])
        self.assertEqual((out["monthly_cap"], out["reply_mode"]), (500, "aira"))
        self.assertTrue(out["has_active_key"])
        self.assertEqual(out["keys"], [{"id": "key-a", "status": "active", "created_at": "2026-03-01",
                                        "last_seen_at": "2026-03-02", "revoked_at": None}])
        self.assertEqual(out["usage"]["reported_sent"], 7)
        for other in ("key-b", "BETA-PREFIX", "BETA-HASH", "999"):
            self.assertNotIn(other, text)

    def test_client_audit_logs(self):
        out, text = self.run_tool("client_audit_logs", "Alpha Astro")
        self.assertEqual(out["total"], 1)
        row = out["data"][0]
        self.assertEqual(row["action"], "alpha.changed")
        self.assertEqual(row["metadata"]["token"], "[hidden]")
        self.assertEqual(row["metadata"]["nested"]["api_key"], "[hidden]")
        self.assertEqual(row["metadata"]["note"], "fine")
        self.assertNotIn("beta.changed", text)

    def test_client_audit_logs_limit_page_and_dates(self):
        for i in range(60):
            self.db.add("app_audit_logs", tenant_id=A, action=f"bulk.{i}", created_at=f"2026-06-01T10:{i:02d}:00Z", metadata={})
        out, _ = self.run_tool("client_audit_logs", "Alpha Astro", limit=500)
        self.assertEqual((len(out["data"]), out["limit"], out["total"]), (50, 50, 61))
        out, _ = self.run_tool("client_audit_logs", "Alpha Astro", limit=50, page=2)
        self.assertEqual(len(out["data"]), 11)
        out, _ = self.run_tool("client_audit_logs", "Alpha Astro", date_from="2026-04-01", date_to="2026-04-30")
        self.assertEqual([r["action"] for r in out["data"]], ["alpha.changed"])
        with self.assertRaises(ToolError):
            wrapper.REGISTRY["client_audit_logs"].fn("Alpha Astro", date_from="not-a-date")


class PlatformToolTests(GapToolsBase):
    def test_subscription_plans_lists_active_plans_only(self):
        out, _ = self.run_tool("subscription_plans")
        self.assertEqual([f["feature_key"] for f in out["features"]], ["whatsapp"])
        self.assertEqual([p["name"] for p in out["plans"]], ["Starter"])

    def test_master_prompt_returns_the_text_and_nothing_else(self):
        out, _ = self.run_tool("master_prompt")
        self.assertEqual(out, {"prompt": "MASTER PROMPT TEXT", "characters": 18})

    def test_master_prompt_cuts_very_long_text(self):
        self.db.rows("platform_defaults")[0]["value"] = "x" * 150_000
        out, _ = self.run_tool("master_prompt")
        self.assertEqual((len(out["prompt"]), out["characters"]), (100_000, 150_000))
        self.assertIn("only the first", out["note"])

    def test_provider_rates_uses_only_the_read_only_rpc(self):
        out, _ = self.run_tool("provider_rates")
        self.assertEqual([r["model"] for r in out["configured"]], ["flash"])
        self.assertEqual(out["missing"], [{"provider": "sarvam", "model": "m1"}])

    def test_clients_waiting_counts_each_client_separately(self):
        out, _ = self.run_tool("clients_waiting")
        by_client = {r["client"]: r for r in out["data"]}
        self.assertEqual(by_client["Alpha Astro"]["pending_reviews"], 1)
        self.assertEqual(by_client["Alpha Astro"]["waiting_count"], 1)
        self.assertEqual(by_client["Beta Bakery"]["waiting_count"], 1)  # its failed file
        self.assertEqual(by_client["Beta Bakery"]["pending_reviews"], 0)
        self.assertEqual(out["clients_waiting"], 2)
        self.assertTrue(any(a["tenant_id"] == A for a in out["alerts"]))  # pending since January


class NoWriteTests(GapToolsBase):
    def test_every_tool_runs_clean_under_the_guard(self):
        calls = [(n, ("Alpha Astro",)) for n in CLIENT_TOOLS] + [(n, ()) for n in PLATFORM_TOOLS]
        for name, args in calls:
            self.run_tool(name, *args)  # raises on a write, a changed table, or a leaked secret


if __name__ == "__main__":
    unittest.main()

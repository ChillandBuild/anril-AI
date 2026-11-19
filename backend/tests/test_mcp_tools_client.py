"""The admin MCP's one-client tools (app/admin_mcp/tools_client.py) call the Operator Console's
own reads with the resolved client id, and never return a stored secret."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver.exceptions import ToolError

from app.admin_mcp import tools_client, wrapper
from app.routes import operator

TENANT = {"id": "tenant-1", "name": "AstroTamil"}
ADMIN = {"user_id": "mcp"}

TOOL_NAMES = [
    "client_overview", "client_health", "client_usage", "client_messages", "client_leads",
    "client_conversations", "client_telecalling", "client_config", "what_anril_saw",
]


class ClientToolsTests(unittest.TestCase):
    def setUp(self):
        p = patch("app.admin_mcp.tools_client.resolve_client", return_value=TENANT)
        self.resolve = p.start()
        self.addCleanup(p.stop)

    def test_every_tool_is_registered(self):
        for name in TOOL_NAMES:
            self.assertIn(name, wrapper.REGISTRY)

    def test_every_tool_takes_client_first(self):
        import inspect
        for name in TOOL_NAMES:
            first = next(iter(inspect.signature(wrapper.REGISTRY[name].fn).parameters))
            self.assertEqual(first, "client", name)

    def test_client_overview(self):
        with patch.object(operator, "client_overview", return_value={"x": 1}) as fn:
            self.assertEqual(tools_client.client_overview("AstroTamil"), {"x": 1})
        self.resolve.assert_called_once_with("AstroTamil")
        fn.assert_called_once_with(tenant_id="tenant-1", _admin=ADMIN)

    def test_client_health(self):
        with patch.object(operator, "client_health", return_value={"h": 1}) as fn:
            self.assertEqual(tools_client.client_health("AstroTamil"), {"h": 1})
        fn.assert_called_once_with(tenant_id="tenant-1", _admin=ADMIN)

    def test_client_usage_defaults(self):
        with patch.object(operator, "get_client_entitlements", return_value={"e": 1}) as ent, \
             patch.object(tools_client, "_usage_counters", return_value={"u": 2}) as use, \
             patch.object(operator, "get_client_token_usage", return_value={"t": 3}) as tok:
            out = tools_client.client_usage("AstroTamil")
        self.assertEqual(out, {"entitlements": {"e": 1}, "usage": {"u": 2}, "token_usage": {"t": 3}})
        ent.assert_called_once_with(tenant_id="tenant-1", _admin=ADMIN)
        use.assert_called_once_with("tenant-1")
        tok.assert_called_once_with(
            tenant_id="tenant-1", range_days=30, all_time=False, from_date=None, to_date=None, _admin=ADMIN,
        )

    def test_usage_counters_never_write_even_when_the_billing_period_rolled_over(self):
        db = MagicMock()

        def table(name):
            tbl = MagicMock()
            if name == "tenant_subscriptions":
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
                    data={"period_start": "2020-01-05", "period_end": "2020-02-05"})
            else:
                tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            for write in ("insert", "upsert", "update", "delete"):
                getattr(tbl, write).side_effect = AssertionError(f"{write} on {name}")
            return tbl

        db.table.side_effect = table
        with patch.object(tools_client, "get_supabase", return_value=db):
            out = tools_client._usage_counters("tenant-1")
        self.assertEqual(out["data"], [])
        self.assertNotEqual(out["period"], "2020-01-05")
        self.assertIn("new billing period", out["note"])

    def test_client_usage_custom_range(self):
        with patch.object(operator, "get_client_entitlements", return_value={}), \
             patch.object(tools_client, "_usage_counters", return_value={}), \
             patch.object(operator, "get_client_token_usage", return_value={}) as tok:
            tools_client.client_usage("AstroTamil", days=7, from_date="2026-11-01", to_date="2026-11-10")
        tok.assert_called_once_with(
            tenant_id="tenant-1", range_days=7, all_time=False,
            from_date="2026-11-01", to_date="2026-11-10", _admin=ADMIN,
        )

    def test_client_usage_rejects_half_a_date_range_and_bad_days(self):
        with self.assertRaises(ToolError):
            tools_client.client_usage("AstroTamil", from_date="2026-11-01")
        with self.assertRaises(ToolError):
            tools_client.client_usage("AstroTamil", days=0)
        with self.assertRaises(ToolError):
            tools_client.client_usage("AstroTamil", days=5000)

    def test_client_messages_defaults(self):
        with patch.object(operator, "client_dashboard_daily_messages", return_value={"d": 1}) as daily, \
             patch.object(operator, "client_dashboard_analytics", return_value={"a": 2}) as ana:
            out = tools_client.client_messages("AstroTamil")
        self.assertEqual(out, {"daily": {"d": 1}, "analytics": {"a": 2}})
        daily.assert_called_once_with(
            tenant_id="tenant-1", range_days=7, all_time=False, from_date=None, to_date=None, _admin=ADMIN,
        )
        ana.assert_called_once_with(tenant_id="tenant-1", _admin=ADMIN)

    def test_client_messages_all_time_and_bad_input(self):
        with patch.object(operator, "client_dashboard_daily_messages", return_value={}) as daily, \
             patch.object(operator, "client_dashboard_analytics", return_value={}):
            tools_client.client_messages("AstroTamil", days=14, all_time=True)
        daily.assert_called_once_with(
            tenant_id="tenant-1", range_days=14, all_time=True, from_date=None, to_date=None, _admin=ADMIN,
        )
        with self.assertRaises(ToolError):
            tools_client.client_messages("AstroTamil", to_date="2026-11-10")
        with self.assertRaises(ToolError):
            tools_client.client_messages("AstroTamil", days=-1)

    def test_client_leads(self):
        for direction in ("all", "inbound", "outbound"):
            with patch.object(operator, "client_dashboard_leads", return_value={"total": 5}) as fn:
                self.assertEqual(tools_client.client_leads("AstroTamil", direction=direction), {"total": 5})
            fn.assert_called_once_with(tenant_id="tenant-1", direction=direction, _admin=ADMIN)

    def test_client_leads_default_is_all(self):
        with patch.object(operator, "client_dashboard_leads", return_value={}) as fn:
            tools_client.client_leads("AstroTamil")
        fn.assert_called_once_with(tenant_id="tenant-1", direction="all", _admin=ADMIN)

    def test_client_leads_rejects_bad_direction(self):
        with patch.object(operator, "client_dashboard_leads") as fn:
            with self.assertRaises(ToolError):
                tools_client.client_leads("AstroTamil", direction="sideways")
        fn.assert_not_called()

    def test_client_conversations(self):
        with patch.object(operator, "client_dashboard_inbox", return_value={"handover_count": 2}) as fn:
            self.assertEqual(tools_client.client_conversations("AstroTamil"), {"handover_count": 2})
        fn.assert_called_once_with(tenant_id="tenant-1", _admin=ADMIN)

    def test_client_telecalling(self):
        for section in ("upload", "dialer", "scheduled", "notes"):
            with patch.object(operator, "client_dashboard_telecalling", return_value={"s": section}) as fn:
                self.assertEqual(tools_client.client_telecalling("AstroTamil", section=section), {"s": section})
            fn.assert_called_once_with(tenant_id="tenant-1", section=section, _admin=ADMIN)

    def test_client_telecalling_default_and_bad_section(self):
        with patch.object(operator, "client_dashboard_telecalling", return_value={}) as fn:
            tools_client.client_telecalling("AstroTamil")
        fn.assert_called_once_with(tenant_id="tenant-1", section="dialer", _admin=ADMIN)
        with patch.object(operator, "client_dashboard_telecalling") as fn:
            with self.assertRaises(ToolError):
                tools_client.client_telecalling("AstroTamil", section="everything")
        fn.assert_not_called()

    def test_client_config_passes_through(self):
        with patch.object(operator, "client_config", return_value={"c": 1}) as fn:
            self.assertEqual(tools_client.client_config("AstroTamil"), {"c": 1})
        fn.assert_called_once_with(tenant_id="tenant-1", _admin=ADMIN)


class ClientConfigNeverLeaksSecretsTests(unittest.TestCase):
    """Real operator.client_config over a fake database whose app_settings hold fake secrets."""

    SECRETS = {
        "meta_phone_number_id": "SECRET-VALUE-PHONE",
        "meta_access_token": "SECRET-VALUE-123",
        "meta_waba_id": "SECRET-VALUE-WABA",
        "meta_webhook_verify_token": "SECRET-VALUE-VERIFY",
        "telecmi_app_id": "SECRET-VALUE-TCAPP",
        "telecmi_secret": "SECRET-VALUE-TCSECRET",
        "telecmi_callerid": "SECRET-VALUE-TCCALLER",
        "gemini_api_key": "SECRET-VALUE-GEMINI",
        "jina_api_key": "SECRET-VALUE-JINA",
        "telegram_bot_token": "SECRET-VALUE-TG",
        "instagram_page_id": "SECRET-VALUE-IGPAGE",
        "instagram_access_token": "SECRET-VALUE-IGTOKEN",
        "facebook_page_id": "SECRET-VALUE-FBPAGE",
        "facebook_access_token": "SECRET-VALUE-FBTOKEN",
        "astro_bridge_url": "SECRET-VALUE-BRIDGEURL",
        "astro_bridge_api_key": "SECRET-VALUE-BRIDGEKEY",
        "astro_bridge_secret": "SECRET-VALUE-BRIDGESECRET",
    }

    def _fake_db(self):
        db = MagicMock()

        def table(name):
            t = MagicMock()
            if name == "tenants":
                t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
                    data={"enabled_features": ["whatsapp", "ai_replies"]}
                )
            elif name == "tenant_usage_counters":
                t.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"metric": "ai_replies", "used": 3, "included": 100, "hard_cap": None}]
                )
            return t

        db.table.side_effect = table
        return db

    def test_no_secret_value_in_result(self):
        rows = [{"key": k, "value": v} for k, v in self.SECRETS.items()]
        rows.append({"key": "business_description", "value": "We sell horoscopes"})
        with patch("app.admin_mcp.tools_client.resolve_client", return_value=TENANT), \
             patch("app.routes.operator.get_supabase", return_value=self._fake_db()), \
             patch("app.routes.operator.execute_with_retry", return_value=MagicMock(data=rows)), \
             patch("app.routes.operator.get_billing_period", return_value="2026-11"), \
             patch("app.routes.operator.source_rows", return_value=[]), \
             patch("app.services.ai_reply.get_master_prompt", return_value="MASTER PROMPT"):
            result = tools_client.client_config("AstroTamil")

        text = json.dumps(result, default=str)
        self.assertNotIn("SECRET-VALUE", text)
        # It still tells the operator which integrations are set up.
        self.assertEqual(result["credentials_status"]["whatsapp"], "configured")
        self.assertEqual(result["credentials_status"]["ai"], "configured")
        self.assertEqual(result["business_description"], "We sell horoscopes")


class WhatAnrilSawTests(unittest.TestCase):
    def test_passes_retrieval_false_and_ids(self):
        with patch("app.admin_mcp.tools_client.resolve_client", return_value=TENANT), \
             patch.object(tools_client.operator_brain, "what_aira_saw", new=AsyncMock(return_value={"ok": True})) as fn:
            out = tools_client.what_anril_saw("AstroTamil", "lead-9")
        self.assertEqual(out, {"ok": True})
        fn.assert_awaited_once_with(tenant_id="tenant-1", lead_id="lead-9", retrieval=False, _admin=ADMIN)

    def test_is_a_plain_function_so_it_runs_in_a_worker_thread(self):
        # Its database reads block; as an async tool they would freeze the whole web server.
        import inspect
        self.assertFalse(inspect.iscoroutinefunction(wrapper.REGISTRY["what_anril_saw"].fn))


if __name__ == "__main__":
    unittest.main()

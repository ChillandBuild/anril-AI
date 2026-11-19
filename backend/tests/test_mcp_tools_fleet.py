"""Fleet-wide admin MCP tools: each returns what its Operator Console read returns, and calls
that read with every parameter spelled out (they are FastAPI handlers, so a left-out parameter
would arrive as a Depends(...) object)."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin_mcp import tools_fleet, wrapper

ADMIN = {"user_id": "mcp"}
ADDED = ["fleet_alerts", "scheduler_health", "system_health", "fleet_ai_spend", "open_requests", "audit_log"]


class RegistrationTests(unittest.TestCase):
    def test_every_tool_is_registered_and_approved(self):
        for name in ADDED + ["list_clients"]:
            self.assertIn(name, wrapper.REGISTRY)
            self.assertIn(name, wrapper.APPROVED_TOOLS)
            self.assertEqual(wrapper.REGISTRY[name].fn, getattr(tools_fleet, name))


class FleetAlertsTests(unittest.TestCase):
    def test_returns_operator_alerts(self):
        with patch.object(tools_fleet.operator, "operator_alerts", new=AsyncMock(return_value={"data": [1]})) as m:
            out = asyncio.run(tools_fleet.fleet_alerts())
        self.assertEqual(out, {"data": [1]})
        m.assert_awaited_once_with(_admin=ADMIN)


class SchedulerHealthTests(unittest.TestCase):
    def test_returns_scheduler_health(self):
        with patch.object(tools_fleet.operator, "scheduler_health", new=AsyncMock(return_value={"jobs": []})) as m:
            out = asyncio.run(tools_fleet.scheduler_health())
        self.assertEqual(out, {"jobs": []})
        m.assert_awaited_once_with(_admin=ADMIN)


class SystemHealthTests(unittest.TestCase):
    def test_returns_system_health(self):
        with patch.object(tools_fleet.operator, "system_health", return_value={"status": "healthy"}) as m:
            out = tools_fleet.system_health()
        self.assertEqual(out, {"status": "healthy"})
        m.assert_called_once_with(_admin=ADMIN)


class FleetAiSpendTests(unittest.TestCase):
    def test_defaults(self):
        with patch.object(tools_fleet.operator, "get_fleet_token_usage", return_value={"data": {}}) as m:
            out = tools_fleet.fleet_ai_spend()
        self.assertEqual(out, {"data": {}})
        m.assert_called_once_with(range_days=90, all_time=False, from_date=None, to_date=None, _admin=ADMIN)

    def test_custom_values_pass_through(self):
        with patch.object(tools_fleet.operator, "get_fleet_token_usage", return_value={"data": {}}) as m:
            tools_fleet.fleet_ai_spend(range_days=7, all_time=True, from_date="2026-11-01", to_date="2026-11-10")
        m.assert_called_once_with(
            range_days=7, all_time=True, from_date="2026-11-01", to_date="2026-11-10", _admin=ADMIN
        )


class OpenRequestsTests(unittest.TestCase):
    def test_combines_subscription_and_sms_requests(self):
        subs = {"data": [{"id": "s1"}]}
        sms = {"items": [{"id": "c1"}]}
        with patch.object(tools_fleet.operator, "list_subscription_requests", return_value=subs) as m_subs, \
                patch.object(tools_fleet.operator_sms, "list_credit_requests", new=AsyncMock(return_value=sms)) as m_sms:
            out = tools_fleet.open_requests()
        self.assertEqual(out, {"subscription_requests": subs, "sms_credit_requests": sms})
        m_subs.assert_called_once_with(status="submitted", _admin=ADMIN)
        m_sms.assert_awaited_once_with(status="open", _admin=ADMIN)


class AuditLogTests(unittest.TestCase):
    def test_defaults(self):
        with patch.object(tools_fleet.operator, "list_audit_logs", return_value={"data": []}) as m:
            out = tools_fleet.audit_log()
        self.assertEqual(out, {"data": []})
        m.assert_called_once_with(
            page=1, limit=50, tenant_id=None, action=None, include_mcp=False, _admin=ADMIN
        )

    def test_client_is_resolved_to_tenant_id(self):
        with patch("app.admin_mcp.tools_fleet.resolve_client", return_value={"id": "t-1", "name": "AstroTamil"}) as rc, \
                patch.object(tools_fleet.operator, "list_audit_logs", return_value={"data": [1]}) as m:
            out = tools_fleet.audit_log(page=2, limit=20, client="AstroTamil", action="sms", include_claude_reads=True)
        self.assertEqual(out, {"data": [1]})
        rc.assert_called_once_with("AstroTamil")
        m.assert_called_once_with(
            page=2, limit=20, tenant_id="t-1", action="sms", include_mcp=True, _admin=ADMIN
        )

    def test_limit_is_capped_and_page_floored(self):
        with patch.object(tools_fleet.operator, "list_audit_logs", return_value={}) as m:
            tools_fleet.audit_log(page=0, limit=5000)
        self.assertEqual(m.call_args.kwargs["limit"], 100)
        self.assertEqual(m.call_args.kwargs["page"], 1)
        with patch.object(tools_fleet.operator, "list_audit_logs", return_value={}) as m:
            tools_fleet.audit_log(limit=0)
        self.assertEqual(m.call_args.kwargs["limit"], 1)

    def test_no_client_means_no_resolve(self):
        with patch("app.admin_mcp.tools_fleet.resolve_client") as rc, \
                patch.object(tools_fleet.operator, "list_audit_logs", return_value={}):
            tools_fleet.audit_log()
        rc.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""The admin MCP's client_broadcasts tool (app/admin_mcp/tools_broadcasts.py) calls the Operator
Console's own read with the resolved client id and every parameter by keyword."""
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin_mcp import tools_broadcasts, wrapper
from app.routes import operator_broadcasts

TENANT = {"id": "tenant-1", "name": "AstroTamil"}
ADMIN = {"user_id": "mcp"}


class ClientBroadcastsToolTests(unittest.TestCase):
    def setUp(self):
        p = patch("app.admin_mcp.tools_broadcasts.resolve_client", return_value=TENANT)
        self.resolve = p.start()
        self.addCleanup(p.stop)

    def test_registered_under_its_own_name(self):
        self.assertIn("client_broadcasts", wrapper.REGISTRY)
        spec = wrapper.REGISTRY["client_broadcasts"]
        self.assertIs(spec.fn, tools_broadcasts.client_broadcasts)
        self.assertEqual(spec.fn.__name__, "client_broadcasts")
        self.assertEqual(next(iter(inspect.signature(spec.fn).parameters)), "client")
        self.assertIn("IST", spec.description)
        self.assertIn("7 days", spec.description)

    def test_passes_everything_by_keyword(self):
        with patch.object(operator_broadcasts, "client_broadcasts", return_value={"count": 0}) as fn:
            out = tools_broadcasts.client_broadcasts("AstroTamil", "2026-11-01", "2026-11-07", 20)
        self.assertEqual(out, {"count": 0})
        self.resolve.assert_called_once_with("AstroTamil")
        fn.assert_called_once_with(tenant_id="tenant-1", date_from="2026-11-01", date_to="2026-11-07",
                                   limit=20, _admin=ADMIN)

    def test_defaults_are_empty_dates_and_50(self):
        with patch.object(operator_broadcasts, "client_broadcasts", return_value={}) as fn:
            tools_broadcasts.client_broadcasts("AstroTamil")
        fn.assert_called_once_with(tenant_id="tenant-1", date_from="", date_to="", limit=50, _admin=ADMIN)

    def test_empty_dates_mean_the_default_range(self):
        """The real handler treats "" like no date: the last 7 IST days."""
        from datetime import datetime, timezone
        from types import SimpleNamespace
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = \
            SimpleNamespace(data={"id": "x", "name": "A"})
        with patch("app.routes.operator_broadcasts.get_supabase", return_value=db), \
             patch("app.routes.operator_broadcasts._now",
                   return_value=datetime(2026, 11, 19, 10, tzinfo=timezone.utc)), \
             patch("app.routes.upload.get_broadcast_history", new=AsyncMock(return_value={"data": []})):
            out = operator_broadcasts.client_broadcasts(
                tenant_id="11111111-1111-4111-8111-111111111111", date_from="", date_to="", limit=50, _admin=ADMIN)
        self.assertEqual((out["date_from"], out["date_to"]), ("2026-11-13", "2026-11-19"))


if __name__ == "__main__":
    unittest.main()

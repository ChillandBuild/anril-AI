"""fleet_summary: the "How is Anril today?" tool (app/admin_mcp/tools_fleet.py)."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from app.admin_mcp import tools_fleet
from app.db import supabase as supabase_db
from app.routes import operator, operator_broadcasts

CLIENTS = {"data": [
    {"id": "t1", "name": "AstroTamil", "status": "active"},
    {"id": "t2", "name": "Healy", "status": "active"},
    {"id": "t3", "name": "Old Co", "status": "suspended"},
]}


def counting_db(count: int) -> MagicMock:
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.is_.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(count=count)
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(count=count)
    return db


class FleetSummaryTests(unittest.TestCase):
    def _run(self, overview, broadcasts, alerts=None, scheduler=None):
        with patch.object(operator, "list_clients", return_value=CLIENTS), \
             patch.object(operator, "client_overview", side_effect=overview), \
             patch.object(operator_broadcasts, "client_broadcasts", side_effect=broadcasts) as sends, \
             patch.object(tools_fleet, "get_supabase", return_value=counting_db(7)), \
             patch.object(operator, "operator_alerts", alerts or AsyncMock(return_value={"alerts": []})), \
             patch.object(operator, "scheduler_health", scheduler or AsyncMock(return_value={"jobs": []})):
            return asyncio.run(tools_fleet.fleet_summary()), sends

    def test_one_row_per_active_client_with_operator_and_today_figures(self):
        out, sends = self._run(
            overview=lambda tenant_id, _admin: {"stats": {"total_leads": 100, "tenant": tenant_id}},
            broadcasts=lambda **kw: {"count": 2, "totals": {"sent": 50, "failed": 3}},
        )
        self.assertEqual([r["client"] for r in out["clients"]], ["AstroTamil", "Healy"])
        self.assertEqual(out["not_active"], [{"client": "Old Co", "status": "suspended"}])
        first = out["clients"][0]
        self.assertEqual(first["operator_overview"], {"total_leads": 100, "tenant": "t1"})
        self.assertEqual(first["today_ist"], {"new_leads": 7, "messages_received": 7, "messages_sent": 7})
        self.assertEqual(first["broadcasts_yesterday_and_today"], {"count": 2, "sent": 50, "failed": 3})
        kw = sends.call_args.kwargs
        self.assertEqual(kw["date_to"], out["day_ist"])
        self.assertLess(kw["date_from"], kw["date_to"])
        self.assertEqual(out["alerts"], {"alerts": []})
        self.assertEqual(out["scheduler"], {"jobs": []})

    def test_one_broken_client_does_not_hide_the_others(self):
        def overview(tenant_id, _admin):
            if tenant_id == "t1":
                raise HTTPException(status_code=500, detail="boom")
            return {"stats": {"total_leads": 5}}

        out, _ = self._run(
            overview=overview,
            broadcasts=lambda **kw: {"count": 0, "totals": {}},
            scheduler=AsyncMock(side_effect=HTTPException(status_code=503, detail="Task queue not connected")),
        )
        self.assertEqual(out["clients"][0]["operator_overview_error"], "boom")
        self.assertIn("today_ist", out["clients"][0])
        self.assertEqual(out["clients"][1]["operator_overview"], {"total_leads": 5})
        self.assertEqual(out["scheduler_error"], "Task queue not connected")

    def test_the_read_only_guard_reaches_the_worker_threads(self):
        seen = []

        def overview(tenant_id, _admin):
            seen.append(supabase_db.read_only.get())
            return {"stats": {}}

        async def go():
            token = supabase_db.read_only.set(True)
            try:
                return await tools_fleet.fleet_summary()
            finally:
                supabase_db.read_only.reset(token)

        with patch.object(operator, "list_clients", return_value=CLIENTS), \
             patch.object(operator, "client_overview", side_effect=overview), \
             patch.object(operator_broadcasts, "client_broadcasts", return_value={"count": 0, "totals": {}}), \
             patch.object(tools_fleet, "get_supabase", return_value=counting_db(0)), \
             patch.object(operator, "operator_alerts", AsyncMock(return_value={})), \
             patch.object(operator, "scheduler_health", AsyncMock(return_value={})):
            asyncio.run(go())
        self.assertEqual(seen, [True, True])


if __name__ == "__main__":
    unittest.main()

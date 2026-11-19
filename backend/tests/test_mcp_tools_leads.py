"""The lead tools pass their arguments straight to the Operator reads."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin_mcp import tools_leads, wrapper  # noqa: E402

CLIENT = {"id": "11111111-1111-1111-1111-111111111111", "name": "AstroTamil"}


class LeadToolTests(unittest.TestCase):
    def test_names_are_registered(self):
        for name in ("find_lead", "lead_thread"):
            self.assertIn(name, wrapper.REGISTRY)
            self.assertIs(wrapper.REGISTRY[name].fn, getattr(tools_leads, name))
        self.assertIn("next_before", wrapper.REGISTRY["lead_thread"].description)

    def test_find_lead_passes_everything_through(self):
        out = {"query": "meena", "count": 0, "leads": []}
        with patch.object(tools_leads, "resolve_client", return_value=CLIENT) as rc, \
                patch.object(tools_leads.operator_leads, "client_lead_search", return_value=out) as h:
            result = tools_leads.find_lead(client="AstroTamil", query="meena", limit=5)
        rc.assert_called_once_with("AstroTamil")
        h.assert_called_once_with(tenant_id=CLIENT["id"], q="meena", limit=5, _admin={"user_id": "mcp"})
        self.assertIs(result, out)

    def test_find_lead_default_limit_is_10(self):
        with patch.object(tools_leads, "resolve_client", return_value=CLIENT), \
                patch.object(tools_leads.operator_leads, "client_lead_search", return_value={}) as h:
            tools_leads.find_lead(client="x", query="meena")
        self.assertEqual(h.call_args.kwargs["limit"], 10)

    def test_lead_thread_passes_everything_through(self):
        out = {"lead": {}, "messages": [], "next_before": None}
        with patch.object(tools_leads, "resolve_client", return_value=CLIENT) as rc, \
                patch.object(tools_leads.operator_leads, "client_lead_thread", return_value=out) as h:
            result = tools_leads.lead_thread(client="AstroTamil", lead_id="L1", limit=20, before="2026-11-01T10:00:00+00:00")
        rc.assert_called_once_with("AstroTamil")
        h.assert_called_once_with(
            tenant_id=CLIENT["id"], lead_id="L1", limit=20, before="2026-11-01T10:00:00+00:00",
            _admin={"user_id": "mcp"},
        )
        self.assertIs(result, out)

    def test_lead_thread_defaults(self):
        with patch.object(tools_leads, "resolve_client", return_value=CLIENT), \
                patch.object(tools_leads.operator_leads, "client_lead_thread", return_value={}) as h:
            tools_leads.lead_thread(client="x", lead_id="L1")
        self.assertEqual((h.call_args.kwargs["limit"], h.call_args.kwargs["before"]), (30, ""))


if __name__ == "__main__":
    unittest.main()

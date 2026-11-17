"""Tests for the `search` term on GET /api/v1/leads/.

The admin telecalling queue loads one page of leads, so its search box has to
ask the API rather than filter what is already on screen. The term lands inside
a PostgREST `or=(...)` filter string, where commas, dots, parentheses and `*`
are syntax — these pin down both the matching and the sanitising.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.routes import leads as leads_route
from app.routes.leads import _sanitize_search
from app.dependencies.auth import get_current_user


class SanitizeSearchTests(unittest.TestCase):
    def test_plain_terms_survive(self):
        self.assertEqual(_sanitize_search("Keerthi"), "Keerthi")
        self.assertEqual(_sanitize_search("6369781582"), "6369781582")
        self.assertEqual(_sanitize_search("+916369781582"), "+916369781582")
        self.assertEqual(_sanitize_search("  Prem Kannan  "), "Prem Kannan")

    def test_real_name_punctuation_survives(self):
        """Names with apostrophes/hyphens must stay searchable."""
        self.assertEqual(_sanitize_search("O'Brien-Rao"), "O'Brien-Rao")
        self.assertEqual(_sanitize_search("R&D team"), "R&D team")
        # '.' is or_() syntax, so an email loses its dots but stays matchable.
        self.assertEqual(_sanitize_search("a@b.com"), "a@bcom")

    def test_filter_syntax_is_stripped(self):
        """Commas, dots, parentheses and wildcards are or_() syntax, not data."""
        for hostile in [
            "a,phone.ilike.*",
            "x)or(true",
            "*",
            "name.ilike.*x*",
        ]:
            cleaned = _sanitize_search(hostile) or ""
            for char in ",.()*":
                self.assertNotIn(char, cleaned, f"{char!r} survived in {cleaned!r}")

    def test_blank_and_symbol_only_terms_become_none(self):
        for empty in [None, "", "   ", ",,,", "***", "()"]:
            self.assertIsNone(_sanitize_search(empty))


class LeadsSearchRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[leads_route.require_leads_view] = lambda: {
            "tenant_id": "tenant-1", "role": "owner", "permissions": [],
        }
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}

    def tearDown(self):
        app.dependency_overrides.clear()

    def _wire(self, db):
        """Return the query object the route holds after its base filters."""
        base = (
            db.table.return_value.select.return_value.eq.return_value
            .is_.return_value.or_.return_value.or_.return_value
        )
        base.or_.return_value.order.return_value.range.return_value.execute.return_value = (
            MagicMock(data=[], count=0)
        )
        base.order.return_value.range.return_value.execute.return_value = MagicMock(data=[], count=0)
        return base

    @patch("app.routes.leads.get_supabase")
    def test_search_matches_name_or_phone_as_a_substring(self, mock_get_db):
        db = MagicMock()
        base = self._wire(db)
        mock_get_db.return_value = db

        res = self.client.get("/api/v1/leads/?search=6369781582")

        self.assertEqual(res.status_code, 200)
        base.or_.assert_called_with("name.ilike.*6369781582*,phone.ilike.*6369781582*,ad_name.ilike.*6369781582*")

    @patch("app.routes.leads.get_supabase")
    def test_no_search_term_adds_no_filter(self, mock_get_db):
        db = MagicMock()
        base = self._wire(db)
        mock_get_db.return_value = db

        self.client.get("/api/v1/leads/")

        base.or_.assert_not_called()

    @patch("app.routes.leads.get_supabase")
    def test_symbol_only_search_adds_no_filter(self, mock_get_db):
        db = MagicMock()
        base = self._wire(db)
        mock_get_db.return_value = db

        self.client.get("/api/v1/leads/?search=***")

        base.or_.assert_not_called()

    @patch("app.routes.leads.get_supabase")
    def test_hostile_term_cannot_inject_filter_syntax(self, mock_get_db):
        db = MagicMock()
        base = self._wire(db)
        mock_get_db.return_value = db

        self.client.get("/api/v1/leads/?search=a,phone.ilike.*")

        sent = base.or_.call_args[0][0]
        self.assertEqual(sent, "name.ilike.*aphoneilike*,phone.ilike.*aphoneilike*,ad_name.ilike.*aphoneilike*")

    @patch("app.routes.leads.get_supabase")
    def test_overlong_search_is_rejected(self, mock_get_db):
        mock_get_db.return_value = MagicMock()
        res = self.client.get("/api/v1/leads/?search=" + "a" * 101)
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()

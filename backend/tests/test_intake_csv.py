import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.intake_csv import build_csv_headers, build_csv_row


class BuildCsvHeadersTests(unittest.TestCase):
    def test_unions_keys_across_rows_with_snapshot_labels(self):
        rows = [
            {"created_at": "2026-08-01T00:00:00Z",
             "field_schema": [{"key": "name", "label": "Full Name"}, {"key": "dob", "label": "Date of Birth"}],
             "collected_data": {"name": "Cheran", "dob": "06.06.2000"}},
            {"created_at": "2026-08-10T00:00:00Z",
             "field_schema": [{"key": "name", "label": "Full Name"}, {"key": "gender", "label": "Gender"}],
             "collected_data": {"name": "Priya", "gender": "Female"}},
        ]

        headers = build_csv_headers(rows)

        self.assertEqual(headers, [("name", "Full Name"), ("dob", "Date of Birth"), ("gender", "Gender")])

    def test_newest_snapshot_wins_when_a_label_was_renamed(self):
        rows = [
            {"created_at": "2026-08-01T00:00:00Z",
             "field_schema": [{"key": "city", "label": "Place of Birth"}],
             "collected_data": {"city": "chidambaram"}},
            {"created_at": "2026-08-10T00:00:00Z",
             "field_schema": [{"key": "city", "label": "City"}],
             "collected_data": {"city": "chennai"}},
        ]

        self.assertEqual(build_csv_headers(rows), [("city", "City")])

    def test_two_keys_sharing_a_label_get_the_key_appended(self):
        rows = [
            {"created_at": "2026-08-01T00:00:00Z",
             "field_schema": [{"key": "city", "label": "Place"}, {"key": "town", "label": "Place"}],
             "collected_data": {"city": "a", "town": "b"}},
        ]

        self.assertEqual(build_csv_headers(rows), [("city", "Place (city)"), ("town", "Place (town)")])

    def test_key_with_no_snapshot_falls_back_to_a_prettified_key(self):
        rows = [{"created_at": "2026-08-01T00:00:00Z", "field_schema": None,
                 "collected_data": {"time_of_birth": "10.45"}}]

        self.assertEqual(build_csv_headers(rows), [("time_of_birth", "Time Of Birth")])


class BuildCsvRowTests(unittest.TestCase):
    def test_fixed_columns_then_fields_in_header_order(self):
        row = {
            "leads": {"name": "Cheran", "phone": "+918056110957"},
            "status": "paid", "package_name": "VIP", "amount_paise": 500000,
            "created_at": "2026-08-01T00:00:00Z", "paid_at": "2026-08-01T01:00:00Z",
            "collected_data": {"name": "Cheran", "dob": "06.06.2000"},
        }

        result = build_csv_row(row, ["dob", "gender"])

        self.assertEqual(result[0], "Cheran")
        self.assertEqual(result[1], "+918056110957")
        self.assertEqual(result[2], "paid")
        self.assertEqual(result[3], "VIP")
        self.assertEqual(result[4], "5000.00")
        self.assertEqual(result[5:7], ["5000.00", "0.00"])
        self.assertEqual(result[-2:], ["06.06.2000", ""])

    def test_gst_session_splits_amount_charged_into_subtotal_and_gst(self):
        row = {
            "leads": {"name": "Cheran", "phone": "+91"}, "status": "paid", "package_name": "Basic",
            "amount_paise": 5782, "gst_percent": 18, "gst_amount_paise": 882,
            "created_at": "", "paid_at": None, "collected_data": {},
        }

        result = build_csv_row(row, [])

        self.assertEqual(result[4:7], ["57.82", "49.00", "8.82"])

    def test_missing_amount_leaves_amount_and_subtotal_blank_and_gst_zero(self):
        row = {"leads": {}, "status": "paid", "amount_paise": None, "created_at": "", "paid_at": None, "collected_data": {}}

        self.assertEqual(build_csv_row(row, [])[4:7], ["", "", "0.00"])

    def test_lead_name_falls_back_to_collected_data(self):
        row = {
            "leads": {"name": None, "phone": "+91"}, "status": "paid",
            "package_name": None, "amount_paise": None,
            "created_at": "", "paid_at": None,
            "collected_data": {"name": "Cheran"},
        }

        self.assertEqual(build_csv_row(row, [])[0], "Cheran")


class IntakeCsvRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.dependencies.auth import get_current_user
        from app.dependencies.tenant import get_tenant_and_role

        self.client = TestClient(app)
        self.app = app
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "t-1", "role": "owner", "permissions": [],
        }

    def tearDown(self):
        self.app.dependency_overrides.clear()

    @patch("app.routes.intake.get_supabase")
    def test_streams_a_csv_with_fixed_and_dynamic_headers(self, mock_get_db):
        db = MagicMock()
        rows = MagicMock()
        rows.data = [{
            "id": "s-1", "status": "paid", "created_at": "2026-08-01T00:00:00Z",
            "paid_at": "2026-08-01T01:00:00Z", "amount_paise": 1000,
            "package_name": "Basic",
            "field_schema": [{"key": "dob", "label": "Date of Birth"}],
            "collected_data": {"dob": "06.06.2000"},
            "leads": {"name": "Cheran", "phone": "+918056110957"},
        }]
        db.table.return_value.select.return_value.eq.return_value.in_.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = rows
        mock_get_db.return_value = db

        res = self.client.get("/api/v1/intake/sessions.csv?status=paid")

        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res.headers["content-type"])
        body = res.text
        self.assertIn("Lead,Phone,Status,Package,Amount charged,Subtotal,GST,Submitted,Paid at,Date of Birth", body)
        self.assertIn('Cheran,"=""+918056110957""",paid,Basic,10.00,10.00,0.00', body)


if __name__ == "__main__":
    unittest.main()


class CsvFormulaInjectionTests(unittest.TestCase):
    def test_leading_equals_in_a_field_value_gets_a_quote_prefix(self):
        row = {
            "leads": {"name": "=SUM(A1:A9)", "phone": "+91"}, "status": "paid",
            "package_name": "Basic", "amount_paise": 1000,
            "created_at": "2026-08-01T00:00:00Z", "paid_at": None,
            "collected_data": {"name": "=SUM(A1:A9)", "note": "+1;calc"},
        }

        result = build_csv_row(row, ["note"])

        self.assertEqual(result[0], "'=SUM(A1:A9)")
        self.assertEqual(result[-1], "'+1;calc")

    def test_ordinary_values_are_untouched(self):
        row = {
            "leads": {"name": "Cheran", "phone": "+918056110957"}, "status": "paid",
            "package_name": "Basic", "amount_paise": 1000,
            "created_at": "2026-08-01T00:00:00Z", "paid_at": None,
            "collected_data": {},
        }

        result = build_csv_row(row, [])

        self.assertEqual(result[0], "Cheran")
        self.assertEqual(result[1], "+918056110957")

    def test_header_label_starting_with_formula_char_is_quoted(self):
        rows = [{"created_at": "2026-08-01T00:00:00Z",
                 "field_schema": [{"key": "x", "label": "=cmd()"}],
                 "collected_data": {"x": "1"}}]

        headers = build_csv_headers(rows)

        self.assertEqual(headers, [("x", "'=cmd()")])

"""strip_evaluation: the one shared helper every call-log-returning endpoint
uses to remove evaluation fields for SIM tenants -- not null them, remove them."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.call_evaluation import EVALUATION_FIELDS, strip_evaluation

_FULL_ROW = {
    "id": "c1", "outcome": "converted", "score": 82.0, "score_status": "scored",
    "score_final": True, "evaluation": {"checks": []}, "call_group": "real_conversation",
    "talk_share": 0.6, "interruption_count": 2, "interruptions_per_5min": 1.1,
    "ai_call_status": "answered", "rules_version": 4,
}


class StripEvaluationTests(unittest.TestCase):
    def test_sim_removes_every_evaluation_field_from_a_list(self):
        rows = [dict(_FULL_ROW), dict(_FULL_ROW, id="c2")]
        result = strip_evaluation(rows, is_sim=True)
        for row in result:
            for field in EVALUATION_FIELDS:
                self.assertNotIn(field, row)
            self.assertIn("id", row)
            self.assertIn("outcome", row)

    def test_sim_removes_every_evaluation_field_from_a_single_dict(self):
        row = strip_evaluation(dict(_FULL_ROW), is_sim=True)
        for field in EVALUATION_FIELDS:
            self.assertNotIn(field, row)

    def test_telecmi_passes_rows_through_unchanged(self):
        rows = [dict(_FULL_ROW)]
        result = strip_evaluation(rows, is_sim=False)
        for field in EVALUATION_FIELDS:
            self.assertIn(field, result[0])

    def test_none_and_empty_are_safe(self):
        self.assertIsNone(strip_evaluation(None, is_sim=True))
        self.assertEqual(strip_evaluation([], is_sim=True), [])

    def test_missing_fields_dont_raise(self):
        row = strip_evaluation({"id": "c1", "outcome": "converted"}, is_sim=True)
        self.assertEqual(row, {"id": "c1", "outcome": "converted"})


if __name__ == "__main__":
    unittest.main()


class ManagerReportTests(unittest.TestCase):
    """The manager's call report is removed everywhere except the manager-only review route."""

    def _row(self):
        return {"id": "c1", "score": 70.0, "evaluation": {"checks": [], "report": {"coach": {"tip": "Smile."}}}}

    def test_report_removed_by_default_for_telecmi(self):
        row = self._row()
        out = strip_evaluation([row], False)
        self.assertNotIn("report", out[0]["evaluation"])
        self.assertEqual(out[0]["evaluation"]["checks"], [])
        self.assertIn("report", row["evaluation"])  # input not mutated

    def test_review_route_keeps_the_report(self):
        out = strip_evaluation([self._row()], False, keep_report=True)
        self.assertEqual(out[0]["evaluation"]["report"], {"coach": {"tip": "Smile."}})

    def test_single_row_and_rows_without_report(self):
        self.assertNotIn("report", strip_evaluation(self._row(), False)["evaluation"])
        plain = {"id": "c2", "evaluation": {"checks": []}}
        self.assertIs(strip_evaluation([plain], False)[0], plain)

    def test_sim_still_removes_everything(self):
        self.assertNotIn("evaluation", strip_evaluation([self._row()], True, keep_report=True)[0])

"""Check 10: marked from the wrap-up (v2 values), Missing after 2 hours, re-marked when the
wrap-up changes; D10: the AI's Hot/Warm/Cold reading corrects the lead status on cloud calls."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import call_marking as cm

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _checks(crm_level=None):
    out = []
    for c in cm.CHECKS:
        level = "good" if c["key"] != "crm_update" else crm_level
        out.append({"key": c["key"], "full": c["full"], "level": level, "marks": cm.check_marks(c["key"], level)})
    return out


def _row(**kw):
    row = {
        "id": "call-1", "tenant_id": "t", "caller_id": "c1", "lead_id": "lead-1", "provider": "telecmi",
        "call_group": "real_conversation", "ai_status": "done",
        "created_at": (NOW - timedelta(minutes=30)).isoformat(), "feedback_at": None,
        "outcome": None, "manual_status": None, "outcome_reason": None, "preferred_language": None,
        "next_action_at": None, "notes": None,
        "transcript": "[00:01] Telecaller: Hello\n[00:03] Customer: I need a demo",
        "evaluation": {"evaluation_version": 4, "group": "real_conversation", "checks": _checks(), "signs": []},
    }
    row.update(kw)
    return row


def _snap(r):
    return {
        "outcome": r.get("outcome"), "manual_status": r.get("manual_status"), "reason": r.get("outcome_reason"),
        "preferred_language": r.get("preferred_language"), "notes": r.get("notes"),
        "next_action_at": r.get("next_action_at"), "do_not_call": False,
    }


WARM = {"feedback_at": NOW.isoformat(), "manual_status": "connected", "outcome": "interested_needs_time"}


class CrmExpectedTests(unittest.TestCase):
    def test_mapping(self):
        self.assertTrue(cm.crm_matches_expected("wrong_number", {"outcome": "wrong_number"}))
        self.assertFalse(cm.crm_matches_expected("wrong_number", {"outcome": "interested_needs_time"}))
        self.assertTrue(cm.crm_matches_expected("not_enquired", {"outcome": "not_interested"}))
        self.assertTrue(cm.crm_matches_expected("not_enquired", {"outcome": "disqualified", "reason": "never_enquired"}))
        self.assertFalse(cm.crm_matches_expected("not_enquired", {"outcome": "disqualified", "reason": "not_a_fit"}))
        self.assertTrue(cm.crm_matches_expected("callback", {"outcome": "call_later", "next_action_at": "2026-09-26T05:00:00+00:00"}))
        self.assertFalse(cm.crm_matches_expected("callback", {"outcome": "call_later", "next_action_at": None}))
        self.assertTrue(cm.crm_matches_expected("language_barrier", {"outcome": "language_barrier"}))
        self.assertFalse(cm.crm_matches_expected("language_barrier", {"outcome": "not_interested"}))
        self.assertIsNone(cm.crm_matches_expected("voicemail", {"outcome": None}))
        self.assertIsNone(cm.crm_matches_expected("other", {"outcome": "maybe_later"}))

    def test_snapshot_reads_the_v2_columns(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data={"do_not_call": True})
        row = _row(**WARM, outcome_reason=None, next_action_at="2026-09-26T05:00:00+00:00", notes="n")
        self.assertEqual(cm.wrapup_snapshot(db, row), {
            "outcome": "interested_needs_time", "manual_status": "connected", "reason": None,
            "preferred_language": None, "notes": "n", "next_action_at": "2026-09-26T05:00:00+00:00", "do_not_call": True,
        })
        self.assertIsNone(cm.wrapup_snapshot(db, _row()))


class MarkCrmUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, row, ai=None, alert_error=None):
        db = MagicMock()
        writes = []
        db.table.return_value.update.side_effect = lambda payload: writes.append(payload) or db.table.return_value.update.return_value
        with patch.object(cm, "_load_row", return_value=row), \
             patch.object(cm, "wrapup_snapshot", side_effect=lambda db, r: None if not r.get("feedback_at") else _snap(r)), \
             patch.object(cm, "gemini_analysis_json", AsyncMock(return_value=ai or {"level": "excellent", "reason": "matches", "customer": "warm"})) as gem, \
             patch.object(cm, "raise_alert", side_effect=alert_error) as alert, \
             patch.object(cm, "finalize_call_score") as fin:
            changed = await cm.mark_crm_update(db, "call-1", now=NOW)
        return changed, writes, gem, alert, fin, db

    async def test_no_wrapup_before_cutoff_does_nothing(self):
        changed, writes, gem, _, _, _ = await self._run(_row())
        self.assertFalse(changed)
        self.assertEqual(writes, [])
        gem.assert_not_called()

    async def test_no_wrapup_after_cutoff_is_missing_without_ai(self):
        changed, writes, gem, _, fin, _ = await self._run(_row(created_at=(NOW - timedelta(hours=2, minutes=1)).isoformat()))
        self.assertTrue(changed)
        gem.assert_not_called()
        crm = writes[0]["evaluation"]["checks"][-1]
        self.assertEqual((crm["level"], crm["marks"]), ("missing", 0.0))
        self.assertNotIn("ai_call_status", writes[0])
        fin.assert_called_once()

    async def test_wrapup_marks_with_ai_and_leaves_other_checks(self):
        changed, writes, gem, _, _, _ = await self._run(_row(**WARM, notes="needs demo friday"), ai={"level": "good", "reason": "notes thin", "customer": "warm"})
        checks = writes[0]["evaluation"]["checks"]
        self.assertEqual(checks[-1]["level"], "good")
        self.assertEqual(checks[-1]["marks"], 5.25)
        self.assertEqual([c["level"] for c in checks[:-1]], ["good"] * 9)
        self.assertEqual(gem.call_args.kwargs["temperature"], 0.0)
        prompt = gem.call_args.kwargs["user_prompt"]
        self.assertIn("what happened: Interested, needs time or more information", prompt)
        self.assertIn("did the call connect: Connected", prompt)

    async def test_crm_check_keeps_the_manager_report(self):
        row = _row(**WARM, notes="needs demo friday")
        row["evaluation"]["report"] = {"report_version": 1, "coach": {"tip": "Smile."}}
        _, writes, _, _, _, _ = await self._run(row, ai={"level": "good", "reason": "ok", "customer": "warm"})
        self.assertEqual(writes[0]["evaluation"]["report"], {"report_version": 1, "coach": {"tip": "Smile."}})

    async def test_changed_wrapup_is_remarked(self):
        row = _row(feedback_at=NOW.isoformat(), manual_status="connected", outcome="call_later", next_action_at=None)
        row["evaluation"]["checks"] = _checks(crm_level="excellent")
        row["evaluation"]["crm_wrapup"] = _snap(_row(**WARM))
        changed, writes, _, _, _, _ = await self._run(row, ai={"level": "poor", "reason": "callback without time", "customer": "none"})
        self.assertTrue(changed)
        self.assertEqual(writes[0]["evaluation"]["checks"][-1]["level"], "poor")

    async def test_same_wrapup_not_remarked(self):
        row = _row(**WARM)
        row["evaluation"]["checks"] = _checks(crm_level="excellent")
        row["evaluation"]["crm_wrapup"] = _snap(row)
        changed, writes, gem, _, fin, _ = await self._run(row)
        self.assertFalse(changed)
        self.assertEqual(writes, [])
        gem.assert_not_called()
        fin.assert_called_once()  # score_final was never set on the row: self-heal

    async def test_same_wrapup_with_score_final_already_true_skips_finalize(self):
        row = _row(**WARM, score_final=True)
        row["evaluation"]["checks"] = _checks(crm_level="excellent")
        row["evaluation"]["crm_wrapup"] = _snap(row)
        changed, _, gem, _, fin, _ = await self._run(row)
        self.assertFalse(changed)
        gem.assert_not_called()
        fin.assert_not_called()

    async def test_same_wrapup_reapplies_a_pending_correction(self):
        """W5: a telecaller re-saving an unchanged wrap-up must not leave the lead on its own
        value while evaluation.crm_correction / ai_call_status still say the AI overrode it."""
        row = _row(**WARM, score_final=True)
        row["evaluation"]["checks"] = _checks(crm_level="excellent")
        row["evaluation"]["crm_wrapup"] = _snap(row)
        row["evaluation"]["crm_correction"] = {"from": "warm", "to": "hot"}
        changed, writes, gem, _, fin, db = await self._run(row)
        self.assertFalse(changed)
        gem.assert_not_called()
        fin.assert_not_called()
        self.assertEqual(writes, [{"call_status": "hot"}])
        db.table.assert_any_call("leads")
        id_eq = db.table.return_value.update.return_value.eq
        tenant_eq = id_eq.return_value.eq
        status_eq = tenant_eq.return_value.eq
        id_eq.assert_called_with("id", "lead-1")
        tenant_eq.assert_called_with("tenant_id", "t")
        status_eq.assert_called_with("call_status", "warm")

    async def test_same_wrapup_without_a_correction_does_not_touch_leads(self):
        row = _row(**WARM, score_final=True)
        row["evaluation"]["checks"] = _checks(crm_level="excellent")
        row["evaluation"]["crm_wrapup"] = _snap(row)
        changed, writes, gem, _, fin, db = await self._run(row)
        self.assertFalse(changed)
        gem.assert_not_called()
        fin.assert_not_called()
        self.assertEqual(writes, [])
        db.table.assert_not_called()

    async def test_early_exit_mismatch_raises_alert_without_ai(self):
        row = _row(call_group="early_exit", **WARM,
                   evaluation={"evaluation_version": 4, "group": "early_exit",
                               "early_exit_check": {"expected_crm": "wrong_number", "crm_matches": None}})
        changed, writes, gem, alert, fin, _ = await self._run(row)
        gem.assert_not_called()
        self.assertFalse(writes[0]["evaluation"]["early_exit_check"]["crm_matches"])
        self.assertEqual(alert.call_args.kwargs["type"], "crm_mismatch")
        self.assertEqual(alert.call_args.kwargs["quote"],
                         "The call sounded like: Wrong number. Wrap-up saved: Interested, needs time or more information.")
        fin.assert_called_once()

    async def test_early_exit_language_barrier_matches(self):
        row = _row(call_group="early_exit", feedback_at=NOW.isoformat(), manual_status="connected", outcome="language_barrier",
                   preferred_language="tamil",
                   evaluation={"evaluation_version": 4, "group": "early_exit",
                               "early_exit_check": {"expected_crm": "language_barrier", "crm_matches": None}})
        _, writes, _, alert, _, _ = await self._run(row)
        self.assertTrue(writes[0]["evaluation"]["early_exit_check"]["crm_matches"])
        alert.assert_not_called()

    async def test_early_exit_no_wrapup_after_cutoff_is_mismatch_with_alert(self):
        row = _row(call_group="early_exit", created_at=(NOW - timedelta(hours=2, minutes=1)).isoformat(),
                   evaluation={"evaluation_version": 4, "group": "early_exit",
                               "early_exit_check": {"expected_crm": "wrong_number", "crm_matches": None}})
        changed, writes, gem, alert, fin, _ = await self._run(row)
        self.assertTrue(changed)
        gem.assert_not_called()
        early = writes[0]["evaluation"]["early_exit_check"]
        self.assertFalse(early["crm_matches"])
        self.assertTrue(early["no_wrapup"])
        self.assertEqual(alert.call_args.kwargs["type"], "crm_mismatch")
        self.assertEqual(alert.call_args.kwargs["quote"], "No wrap-up saved within 2 hours")
        fin.assert_called_once()

    async def test_early_exit_alert_failure_still_saves_and_finalizes(self):
        row = _row(call_group="early_exit", **WARM,
                   evaluation={"evaluation_version": 4, "group": "early_exit",
                               "early_exit_check": {"expected_crm": "wrong_number", "crm_matches": None}})
        changed, writes, _, _, fin, _ = await self._run(row, alert_error=RuntimeError("insert failed"))
        self.assertTrue(changed)
        self.assertFalse(writes[0]["evaluation"]["early_exit_check"]["crm_matches"])
        fin.assert_called_once()

    async def test_real_conversation_alert_failure_still_saves_and_finalizes(self):
        changed, writes, _, _, fin, _ = await self._run(_row(**WARM), ai={"level": "poor", "reason": "status wrong", "customer": "warm"},
                                                        alert_error=RuntimeError("insert failed"))
        self.assertTrue(changed)
        self.assertEqual(writes[0]["evaluation"]["checks"][-1]["level"], "poor")
        fin.assert_called_once()

    async def test_ai_failure_increments_crm_attempts_and_reraises(self):
        row = _row(**WARM)
        db = MagicMock()
        writes = []
        db.table.return_value.update.side_effect = lambda payload: writes.append(payload) or db.table.return_value.update.return_value
        with patch.object(cm, "_load_row", return_value=row), \
             patch.object(cm, "wrapup_snapshot", return_value=_snap(row)), \
             patch.object(cm, "gemini_analysis_json", AsyncMock(side_effect=RuntimeError("timeout"))), \
             patch.object(cm, "finalize_call_score") as fin:
            with self.assertRaises(cm.CallMarkingError):
                await cm.mark_crm_update(db, "call-1", now=NOW)
        self.assertEqual(writes[-1]["evaluation"]["crm_attempts"], 1)
        fin.assert_not_called()

    async def test_third_ai_failure_marks_missing_and_alerts_no_proof(self):
        row = _row(**WARM)
        row["evaluation"]["crm_attempts"] = 3
        changed, writes, gem, alert, fin, _ = await self._run(row)
        self.assertTrue(changed)
        gem.assert_not_called()
        crm = writes[0]["evaluation"]["checks"][-1]
        self.assertEqual((crm["level"], crm["marks"], crm["reason"]), ("missing", 0.0, "The wrap-up couldn't be checked automatically."))
        self.assertEqual(alert.call_args.kwargs["type"], "no_proof")
        self.assertEqual(alert.call_args.kwargs["quote"], "Wrap-up check failed 3 times")
        self.assertIsNone(writes[0]["ai_call_status"])
        fin.assert_called_once()

    async def test_ai_not_done_yet_waits(self):
        changed, writes, _, _, _, _ = await self._run(_row(ai_status="scoring", feedback_at=NOW.isoformat(), evaluation=None))
        self.assertFalse(changed)
        self.assertEqual(writes, [])

    async def test_gemini_called_ai_votes_times(self):
        _, _, gem, _, _, _ = await self._run(_row(**WARM))
        self.assertEqual(gem.await_count, cm.AI_VOTES)


class TemperatureCorrectionTests(unittest.IsolatedAsyncioTestCase):
    """D10: on cloud calls the AI's majority Hot/Warm/Cold reading corrects the telecaller's."""

    async def _run(self, row, votes):
        db = MagicMock()
        writes = []
        db.table.return_value.update.side_effect = lambda payload: writes.append(payload) or db.table.return_value.update.return_value
        with patch.object(cm, "_load_row", return_value=row), \
             patch.object(cm, "wrapup_snapshot", return_value=_snap(row)), \
             patch.object(cm, "gemini_analysis_json", AsyncMock(side_effect=votes)), \
             patch.object(cm, "raise_alert"), \
             patch.object(cm, "finalize_call_score"):
            await cm.mark_crm_update(db, "call-1", now=NOW)
        return writes, db

    async def test_ai_majority_hot_corrects_a_warm_lead(self):
        votes = [{"level": "good", "reason": "r", "customer": c} for c in ("hot", "hot", "warm")]
        writes, db = await self._run(_row(**WARM), votes)
        self.assertEqual(writes[0]["ai_call_status"], "hot")
        self.assertEqual(writes[0]["evaluation"]["crm_correction"], {"from": "warm", "to": "hot"})
        self.assertEqual(writes[1], {"call_status": "hot"})
        db.table.assert_any_call("leads")

    async def test_correction_only_replaces_the_telecallers_value(self):
        votes = [{"level": "good", "reason": "r", "customer": "cold"}] * 3
        _, db = await self._run(_row(**WARM), votes)
        id_eq = db.table.return_value.update.return_value.eq
        tenant_eq = id_eq.return_value.eq
        status_eq = tenant_eq.return_value.eq
        tenant_eq.assert_called_with("tenant_id", "t")
        status_eq.assert_called_with("call_status", "warm")

    async def test_agreement_means_no_correction(self):
        votes = [{"level": "good", "reason": "r", "customer": "warm"}] * 3
        writes, _ = await self._run(_row(**WARM), votes)
        self.assertEqual(len(writes), 1)
        self.assertIsNone(writes[0]["evaluation"]["crm_correction"])
        self.assertEqual(writes[0]["ai_call_status"], "warm")

    async def test_no_majority_reads_none(self):
        votes = [{"level": "good", "reason": "r", "customer": c} for c in ("hot", "warm", "cold")]
        writes, _ = await self._run(_row(**WARM), votes)
        self.assertEqual((writes[0]["ai_call_status"], writes[0]["evaluation"]["crm_correction"]), ("none", None))

    async def test_non_temperature_results_are_never_corrected(self):
        row = _row(feedback_at=NOW.isoformat(), manual_status="connected", outcome="not_interested", outcome_reason="price")
        votes = [{"level": "good", "reason": "r", "customer": "hot"}] * 3
        writes, _ = await self._run(row, votes)
        self.assertEqual(len(writes), 1)
        self.assertIsNone(writes[0]["evaluation"]["crm_correction"])


class MarkCrmUpdateVotingTests(unittest.IsolatedAsyncioTestCase):
    """Check 10 also asks Gemini AI_VOTES times and decides by majority."""

    async def _run_votes(self, row, votes, alert=None):
        db = MagicMock()
        writes = []
        db.table.return_value.update.side_effect = lambda payload: writes.append(payload) or db.table.return_value.update.return_value
        with patch.object(cm, "_load_row", return_value=row), \
             patch.object(cm, "wrapup_snapshot", return_value=_snap(row)), \
             patch.object(cm, "gemini_analysis_json", AsyncMock(side_effect=votes)), \
             patch.object(cm, "raise_alert", alert or MagicMock()), \
             patch.object(cm, "finalize_call_score"):
            changed = await cm.mark_crm_update(db, "call-1", now=NOW)
        return changed, writes

    async def test_majority_level_from_three_runs(self):
        votes = [{"level": "good", "reason": "r1"}, {"level": "good", "reason": "r2"}, {"level": "poor", "reason": "r3"}]
        changed, writes = await self._run_votes(_row(**WARM), votes)
        crm = writes[0]["evaluation"]["checks"][-1]
        self.assertEqual((changed, crm["level"], crm["reason"]), (True, "good", "r1"))

    async def test_all_differ_takes_median(self):
        votes = [{"level": "poor", "reason": "r1"}, {"level": "good", "reason": "r2"}, {"level": "excellent", "reason": "r3"}]
        _, writes = await self._run_votes(_row(**WARM), votes)
        self.assertEqual(writes[0]["evaluation"]["checks"][-1]["level"], "good")

    async def test_fewer_than_two_valid_votes_raises_and_counts_one_attempt(self):
        row = _row(**WARM)
        db = MagicMock()
        writes = []
        db.table.return_value.update.side_effect = lambda payload: writes.append(payload) or db.table.return_value.update.return_value
        votes = [{"level": "good", "reason": "r1"}, {"level": "not_a_real_level"}, {"level": None}]
        with patch.object(cm, "_load_row", return_value=row), \
             patch.object(cm, "wrapup_snapshot", return_value=_snap(row)), \
             patch.object(cm, "gemini_analysis_json", AsyncMock(side_effect=votes)), \
             patch.object(cm, "finalize_call_score") as fin:
            with self.assertRaises(cm.CallMarkingError):
                await cm.mark_crm_update(db, "call-1", now=NOW)
        self.assertEqual(writes[-1]["evaluation"]["crm_attempts"], 1)
        fin.assert_not_called()

    async def test_one_run_fails_two_disagree_raises_no_proof_alert(self):
        alert = MagicMock()
        votes = [RuntimeError("boom"), {"level": "good", "reason": "r1"}, {"level": "poor", "reason": "r2"}]
        changed, writes = await self._run_votes(_row(**WARM), votes, alert=alert)
        self.assertTrue(changed)
        self.assertEqual(writes[0]["evaluation"]["checks"][-1]["level"], "poor")
        pairs = [(c.kwargs["type"], c.kwargs["quote"]) for c in alert.call_args_list]
        self.assertIn(("no_proof", "Wrap-up check: the AI votes disagreed"), pairs)


if __name__ == "__main__":
    unittest.main()

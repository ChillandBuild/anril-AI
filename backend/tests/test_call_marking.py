"""Step 2: the AI picks levels, the system does every mark, cap and total."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import call_marking as cm
from app.services.call_lines import Line

LINES = [
    Line(0, "telecaller", "Good morning sir, this is Priya from Aira Softwares, you enquired about billing software, is this a good time?"),
    Line(9, "customer", "Yes. We have two branches actually."),
    Line(15, "telecaller", "Our plan includes GST billing and stock tracking. It is 12000 per year."),
    Line(30, "customer", "A bit costly, I'll think."),
    Line(40, "telecaller", "Shall I book a demo for Friday at 11 AM?"),
    Line(45, "customer", "Okay, Friday 11 is fine."),
]


def _level_map(levels: dict) -> list[dict]:
    return [{"key": c["key"], "full": c["full"], "level": levels.get(c["key"])} for c in cm.CHECKS]


class MarksMathsTests(unittest.TestCase):
    def test_document_full_example_is_78_5(self):
        levels = {
            "opening": "excellent", "courtesy": "good", "questions": "good", "listening": "partial",
            "product_info": "good", "doubts": "excellent", "clarity": "good", "next_step": "excellent",
            "decision": "partial", "crm_update": "excellent",
        }
        checks = [dict(c, marks=cm.check_marks(c["key"], c["level"])) for c in _level_map(levels)]
        self.assertEqual(cm.total_score(checks), 78.5)
        self.assertEqual(cm.top_improve(checks), ["listening", "decision"])

    def test_marks_per_level(self):
        self.assertEqual(cm.check_marks("questions", "good"), 11.25)
        self.assertEqual(cm.check_marks("decision", "partial"), 4.0)
        self.assertEqual(cm.check_marks("crm_update", None), 0.0)

    def test_top_improve_tie_prefers_bigger_check(self):
        levels = {c["key"]: "excellent" for c in cm.CHECKS}
        levels.update({"opening": "partial", "questions": "partial", "clarity": "partial"})
        checks = [dict(c, marks=cm.check_marks(c["key"], c["level"])) for c in _level_map(levels)]
        self.assertEqual(cm.top_improve(checks), ["questions", "clarity"])

    def test_pending_crm_excluded_from_top_improve(self):
        levels = {c["key"]: "excellent" for c in cm.CHECKS}
        levels["crm_update"] = None
        levels["clarity"] = "good"
        checks = [dict(c, marks=cm.check_marks(c["key"], c["level"])) for c in _level_map(levels)]
        self.assertNotIn("crm_update", cm.top_improve(checks))

    def test_apply_level_caps_and_records_it(self):
        check = {"key": "listening", "full": 10}
        out = cm.apply_level(check, "excellent", "good", "interruptions")
        self.assertEqual((out["level"], out["ai_level"], out["capped_by"], out["marks"]), ("good", "excellent", "interruptions", 7.5))
        out = cm.apply_level(check, "partial", "good", "interruptions")
        self.assertIsNone(out["capped_by"])


def _ai(**overrides):
    checks = {
        "opening": {"level": "excellent", "reason": "all elements", "quote": "this is Priya from Aira Softwares"},
        "courtesy": {"level": "good", "reason": "polite", "quote": "Good morning sir"},
        "questions": {"level": "good", "reason": "asked need", "quote": "is this a good time"},
        "listening": {"level": "excellent", "reason": "confirmed", "quote": "We have two branches actually"},
        "product_info": {"level": "good", "reason": "correct", "quote": "GST billing and stock tracking"},
        "doubts": {"level": "excellent", "reason": "handled", "quote": "A bit costly"},
        "clarity": {"level": "good", "reason": "clear", "quote": "Our plan includes GST billing"},
        "next_step": {"level": "excellent", "reason": "demo fixed", "quote": "Friday 11 is fine"},
        "decision": {"level": "partial", "reason": "hinted", "quote": "Shall I book a demo"},
    }
    data = {"checks": checks, "rude": False, "rude_quote": None, "excused_interruptions": 0,
            "wrong_info": [], "unverified_claims": []}
    data.update(overrides)
    return data


class MarkCallTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, ai, talk_share=50.0, ipm=0.5, count=0):
        with patch.object(cm, "gemini_analysis_json", AsyncMock(return_value=ai)) as gem:
            result = await cm.mark_call(
                LINES, kb_context="Plan: 12000 per year", previous_notes="", talk_share=talk_share,
                interruptions_per_5min=ipm, interruption_count=count, duration_seconds=60, tenant_id="t",
            )
        return result, gem

    async def test_all_ten_checks_present_crm_pending(self):
        result, gem = await self._run(_ai())
        self.assertEqual([c["key"] for c in result.checks], [c["key"] for c in cm.CHECKS])
        crm = result.checks[-1]
        self.assertEqual((crm["key"], crm["level"], crm["marks"]), ("crm_update", None, None))
        self.assertEqual(gem.call_args.kwargs["temperature"], 0.0)

    async def test_quote_time_comes_from_transcript(self):
        result, _ = await self._run(_ai())
        listening = next(c for c in result.checks if c["key"] == "listening")
        self.assertEqual(listening["time"], "00:09")

    async def test_listening_capped_by_talk_share(self):
        result, _ = await self._run(_ai(), talk_share=80.0, ipm=0.5)
        listening = next(c for c in result.checks if c["key"] == "listening")
        self.assertEqual((listening["level"], listening["capped_by"]), ("partial", "talk_share"))
        self.assertTrue(result.tips)

    async def test_excused_interruption_lifts_courtesy_cap(self):
        ai = _ai(excused_interruptions=1)
        # 4 interruptions in 1 minute = 20/5min; excusing 1 still leaves 15 → cap stays
        result, _ = await self._run(ai, ipm=20.0, count=4)
        courtesy = next(c for c in result.checks if c["key"] == "courtesy")
        self.assertEqual(courtesy["level"], "good")

    async def test_excused_interruption_can_lift_courtesy_cap(self):
        ai = _ai(excused_interruptions=1)
        ai["checks"]["courtesy"]["level"] = "excellent"
        # ipm=4.0, count=4 → remaining 3.0/5min → courtesy cap goes from "good" to "excellent"
        result, _ = await self._run(ai, ipm=4.0, count=4)
        courtesy = next(c for c in result.checks if c["key"] == "courtesy")
        self.assertEqual((courtesy["level"], courtesy["capped_by"]), ("excellent", None))

    async def test_made_up_quote_flags_proof_missing(self):
        ai = _ai()
        ai["checks"]["clarity"]["quote"] = "Let me explain our cloud features"
        result, _ = await self._run(ai)
        clarity = next(c for c in result.checks if c["key"] == "clarity")
        self.assertTrue(clarity["proof_missing"])
        self.assertEqual(clarity["level"], "good")  # the mark still counts
        self.assertIn("clarity", result.proof_missing)

    async def test_missing_level_needs_no_quote(self):
        ai = _ai()
        ai["checks"]["decision"] = {"level": "missing", "reason": "never asked", "quote": None}
        result, _ = await self._run(ai)
        decision = next(c for c in result.checks if c["key"] == "decision")
        self.assertFalse(decision["proof_missing"])

    async def test_wrong_info_forces_product_info_missing(self):
        ai = _ai(wrong_info=[{"quote": "It is 12000 per year", "kb_fact": "Plan is 15000 per year"}])
        result, _ = await self._run(ai)
        product = next(c for c in result.checks if c["key"] == "product_info")
        self.assertEqual((product["level"], product["capped_by"], product["marks"]), ("missing", "wrong_info", 0.0))
        self.assertEqual(result.wrong_info[0]["time"], "00:15")

    async def test_wrong_info_needs_a_real_telecaller_quote(self):
        ai = _ai(wrong_info=[{"quote": "Free for life", "kb_fact": "No free plan"}])
        result, _ = await self._run(ai)
        self.assertEqual(result.wrong_info, [])

    async def test_rude_from_ai_creates_rude_quote(self):
        ai = _ai(rude=True, rude_quote="Our plan includes GST billing")
        result, _ = await self._run(ai)
        self.assertTrue(result.rude_quote.startswith("[00:15]"))
        courtesy = next(c for c in result.checks if c["key"] == "courtesy")
        self.assertEqual(courtesy["level"], "missing")

    async def test_missing_check_in_ai_reply_raises(self):
        ai = _ai()
        del ai["checks"]["clarity"]
        with self.assertRaises(cm.CallMarkingError):
            await self._run(ai)

    async def test_null_string_quote_on_missing_is_not_proof_missing(self):
        ai = _ai()
        ai["checks"]["decision"] = {"level": "missing", "reason": "never asked", "quote": "null"}
        result, _ = await self._run(ai)
        decision = next(c for c in result.checks if c["key"] == "decision")
        self.assertFalse(decision["proof_missing"])


class QuoteOkTests(unittest.TestCase):
    def test_null_string_on_missing_is_ok(self):
        ok, line = cm._quote_ok("missing", "null", LINES)
        self.assertTrue(ok)
        self.assertIsNone(line)


class MarkCallVotingTests(unittest.IsolatedAsyncioTestCase):
    """Step 2 now asks Gemini AI_VOTES times with the identical prompt and decides by majority."""

    async def _run_votes(self, ai_list, talk_share=50.0, ipm=0.5, count=0):
        with patch.object(cm, "gemini_analysis_json", AsyncMock(side_effect=ai_list)) as gem:
            result = await cm.mark_call(
                LINES, kb_context="Plan: 12000 per year", previous_notes="", talk_share=talk_share,
                interruptions_per_5min=ipm, interruption_count=count, duration_seconds=60, tenant_id="t",
            )
        return result, gem

    async def test_gemini_called_ai_votes_times(self):
        _, gem = await self._run_votes([_ai(), _ai(), _ai()])
        self.assertEqual(gem.await_count, cm.AI_VOTES)

    async def test_majority_picks_common_level(self):
        a1, a2, a3 = _ai(), _ai(), _ai()
        a3["checks"]["opening"]["level"] = "poor"  # a1/a2 keep the default "excellent"
        result, _ = await self._run_votes([a1, a2, a3])
        opening = next(c for c in result.checks if c["key"] == "opening")
        self.assertEqual(opening["ai_level"], "excellent")

    async def test_all_differ_takes_median(self):
        a1, a2, a3 = _ai(), _ai(), _ai()
        a1["checks"]["opening"]["level"] = "poor"
        a2["checks"]["opening"]["level"] = "good"
        a3["checks"]["opening"]["level"] = "excellent"
        result, _ = await self._run_votes([a1, a2, a3])
        opening = next(c for c in result.checks if c["key"] == "opening")
        self.assertEqual(opening["ai_level"], "good")

    async def test_fewer_than_two_valid_votes_raises(self):
        a1, a2, a3 = _ai(), _ai(), _ai()
        a2["checks"]["clarity"]["level"] = "not_a_real_level"
        a3["checks"]["clarity"] = None
        with self.assertRaises(cm.CallMarkingError):
            await self._run_votes([a1, a2, a3])

    async def test_rude_needs_two_runs(self):
        a1, a2, a3 = _ai(), _ai(), _ai()
        a1.update(rude=True, rude_quote="Our plan includes GST billing")
        result, _ = await self._run_votes([a1, a2, a3])
        self.assertIsNone(result.rude_quote)
        courtesy = next(c for c in result.checks if c["key"] == "courtesy")
        self.assertNotEqual(courtesy["capped_by"], "rude")

    async def test_rude_confirmed_by_two_runs(self):
        a1, a2, a3 = _ai(), _ai(), _ai()
        a1.update(rude=True, rude_quote="Our plan includes GST billing")
        a2.update(rude=True, rude_quote="Our plan includes GST billing")
        result, _ = await self._run_votes([a1, a2, a3])
        self.assertTrue(result.rude_quote.startswith("[00:15]"))
        courtesy = next(c for c in result.checks if c["key"] == "courtesy")
        self.assertEqual(courtesy["level"], "missing")

    async def test_wrong_info_needs_two_runs_on_the_same_line(self):
        a1, a2, a3 = _ai(), _ai(), _ai()
        a1["wrong_info"] = [{"quote": "It is 12000 per year", "kb_fact": "Plan is 15000 per year"}]
        result, _ = await self._run_votes([a1, a2, a3])
        self.assertEqual(result.wrong_info, [])

    async def test_wrong_info_confirmed_by_two_runs_on_the_same_line(self):
        a1, a2, a3 = _ai(), _ai(), _ai()
        a1["wrong_info"] = [{"quote": "It is 12000 per year", "kb_fact": "Plan is 15000 per year"}]
        a2["wrong_info"] = [{"quote": "It is 12000 per year", "kb_fact": "Plan is 15000 per year"}]
        result, _ = await self._run_votes([a1, a2, a3])
        self.assertEqual(len(result.wrong_info), 1)
        self.assertEqual(result.wrong_info[0]["time"], "00:15")
        product = next(c for c in result.checks if c["key"] == "product_info")
        self.assertEqual((product["level"], product["capped_by"]), ("missing", "wrong_info"))

    async def test_one_run_fails_two_agree_no_error(self):
        a1, a2 = _ai(), _ai()
        result, gem = await self._run_votes([RuntimeError("boom"), a1, a2])
        self.assertEqual(gem.await_count, cm.AI_VOTES)
        opening = next(c for c in result.checks if c["key"] == "opening")
        self.assertEqual(opening["ai_level"], "excellent")
        self.assertFalse(opening["proof_missing"])

    async def test_one_run_fails_two_disagree_flags_proof_missing(self):
        a1, a2 = _ai(), _ai()
        a2["checks"]["opening"]["level"] = "poor"
        result, _ = await self._run_votes([RuntimeError("boom"), a1, a2])
        opening = next(c for c in result.checks if c["key"] == "opening")
        self.assertEqual(opening["ai_level"], "poor")  # the lower of excellent/poor
        self.assertTrue(opening["proof_missing"])
        self.assertIn("opening", result.proof_missing)

    async def test_two_runs_fail_raises(self):
        with self.assertRaises(cm.CallMarkingError):
            await self._run_votes([RuntimeError("boom1"), RuntimeError("boom2"), _ai()])


if __name__ == "__main__":
    unittest.main()


class MarkCallReportTests(unittest.IsolatedAsyncioTestCase):
    """The manager's report rides on the same Step 2 request and never touches the marks."""

    async def _run_votes(self, ai_list):
        with patch.object(cm, "gemini_analysis_json", AsyncMock(side_effect=ai_list)) as gem:
            result = await cm.mark_call(
                LINES, kb_context="Plan: 12000 per year", previous_notes="", talk_share=50.0,
                interruptions_per_5min=0.5, interruption_count=0, duration_seconds=60, tenant_id="t",
            )
        return result, gem

    def _report(self):
        return {"mood": [{"quote": "A bit costly, I'll think.", "mood": "negative"}],
                "coach": {"quote": "A bit costly", "tip": "Answer the price with the EMI option."}}

    async def test_prompt_asks_for_the_report_with_a_bigger_budget(self):
        _, gem = await self._run_votes([_ai(report=self._report())] * cm.AI_VOTES)
        kwargs = gem.call_args.kwargs
        self.assertIn('"report"', kwargs["user_prompt"])
        self.assertEqual(kwargs["max_tokens"], cm.MARKING_MAX_TOKENS)
        self.assertGreaterEqual(cm.MARKING_MAX_TOKENS, 6000)

    async def test_report_is_validated_and_timed_from_the_transcript(self):
        result, _ = await self._run_votes([_ai(report=self._report())] * cm.AI_VOTES)
        self.assertEqual(result.report["mood"][0]["time"], "00:30")
        self.assertEqual(result.report["coach"]["tip"], "Answer the price with the EMI option.")

    async def test_first_vote_with_a_usable_report_is_taken(self):
        votes = [_ai(report="junk"), _ai(report=self._report()), _ai()]
        result, _ = await self._run_votes(votes)
        self.assertEqual(result.report["mood"][0]["mood"], "negative")

    async def test_garbage_report_leaves_the_marks_unchanged(self):
        clean, _ = await self._run_votes([_ai()] * cm.AI_VOTES)
        junk, _ = await self._run_votes([_ai(report={"mood": [None, 3, {"quote": "never said"}]})] * cm.AI_VOTES)
        self.assertEqual(junk.report, {})
        self.assertEqual(clean.checks, junk.checks)
        self.assertEqual(clean.proof_missing, junk.proof_missing)

"""The AI's call report is untrusted: only quotes found in the transcript survive."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.call_lines import Line
from app.services.call_report import (
    MAX_MOOD,
    MAX_OBJECTIONS,
    MAX_PROMISES,
    REPORT_RUBRIC,
    build_report,
)

LINES = [
    Line(5.0, "telecaller", "Our course includes placement support and a refund guarantee."),
    Line(12.0, "customer", "The fees are too high for me."),
    Line(20.0, "telecaller", "I can give you a twenty percent discount today."),
    Line(35.0, "customer", "Okay that sounds good, I will think about it."),
    Line(50.0, "customer", "Can you send me the brochure on WhatsApp?"),
]


class RubricTests(unittest.TestCase):
    def test_rubric_names_every_report_part(self):
        for key in ("report", "mood", "turning_point", "objections", "promises", "coach"):
            self.assertIn(key, REPORT_RUBRIC)


class BuildReportShapeTests(unittest.TestCase):
    def test_non_dict_raw_returns_empty(self):
        for raw in (None, "text", 5, 1.5, True, [], [{"mood": []}], ()):
            self.assertEqual(build_report(raw, LINES), {})

    def test_everything_invalid_returns_empty(self):
        raw = {
            "mood": [{"quote": "never said this", "mood": "positive"}],
            "turning_point": {"quote": "nope nothing here", "direction": "warmed", "why": "x"},
            "objections": [{"quote": "fabricated words entirely", "handling": "handled", "why": "x"}],
            "promises": [{"quote": "free iPhone for everyone", "risky": True, "why": "x"}],
            "coach": {"quote": "invented sentence here", "tip": "do better"},
        }
        self.assertEqual(build_report(raw, LINES), {})

    def test_empty_dict_and_empty_lines(self):
        self.assertEqual(build_report({}, LINES), {})
        self.assertEqual(build_report({"mood": [{"quote": "fees", "mood": "negative"}]}, []), {})

    def test_junk_types_do_not_raise(self):
        junk = [None, 1, "str", 2.5, True, [], [None], {}, {"quote": 5}, {"quote": None}]
        raw = {
            "mood": junk,
            "turning_point": junk[1],
            "objections": junk,
            "promises": junk,
            "coach": junk,
        }
        self.assertEqual(build_report(raw, LINES), {})
        for key in ("mood", "turning_point", "objections", "promises", "coach"):
            for value in junk + [{"a": 1}, "x"]:
                self.assertEqual(build_report({key: value}, LINES), {})

    def test_junk_items_do_not_hide_valid_ones(self):
        raw = {"mood": [None, 3, "x", {"quote": "fees are too high", "mood": "negative"}]}
        out = build_report(raw, LINES)
        self.assertEqual(len(out["mood"]), 1)
        self.assertEqual(out["report_version"], 1)


class MoodTests(unittest.TestCase):
    def test_time_and_start_come_from_the_line_not_the_ai(self):
        raw = {"mood": [{"quote": "The fees are too high", "mood": "negative", "time": "09:99", "start": 999}]}
        item = build_report(raw, LINES)["mood"][0]
        self.assertEqual(item["time"], "00:12")
        self.assertEqual(item["start"], 12.0)
        self.assertEqual(item["mood"], "negative")
        self.assertEqual(item["quote"], "The fees are too high")

    def test_quote_not_in_transcript_dropped(self):
        raw = {"mood": [
            {"quote": "I love this so much", "mood": "positive"},
            {"quote": "fees are too high", "mood": "negative"},
        ]}
        self.assertEqual(len(build_report(raw, LINES)["mood"]), 1)

    def test_telecaller_words_rejected_for_mood(self):
        raw = {"mood": [{"quote": "placement support and a refund guarantee", "mood": "positive"}]}
        self.assertEqual(build_report(raw, LINES), {})

    def test_invalid_enum_dropped_and_case_insensitive_valid(self):
        raw = {"mood": [
            {"quote": "fees are too high", "mood": "angry"},
            {"quote": "send me the brochure", "mood": "  Positive "},
            {"quote": "think about it", "mood": 3},
        ]}
        out = build_report(raw, LINES)["mood"]
        self.assertEqual([m["mood"] for m in out], ["positive"])

    def test_sorted_by_start(self):
        raw = {"mood": [
            {"quote": "send me the brochure", "mood": "positive"},
            {"quote": "fees are too high", "mood": "negative"},
            {"quote": "sounds good", "mood": "positive"},
        ]}
        starts = [m["start"] for m in build_report(raw, LINES)["mood"]]
        self.assertEqual(starts, [12.0, 35.0, 50.0])

    def test_cap_enforced(self):
        many = [Line(float(i), "customer", f"unique customer sentence number {i}x") for i in range(10)]
        raw = {"mood": [{"quote": l.text, "mood": "neutral"} for l in many]}
        out = build_report(raw, many)["mood"]
        self.assertEqual(len(out), MAX_MOOD)
        self.assertEqual(MAX_MOOD, 8)


class TurningPointTests(unittest.TestCase):
    def test_valid(self):
        raw = {"turning_point": {"quote": "fees are too high", "direction": "cooled", "why": "  Fee not answered  "}}
        tp = build_report(raw, LINES)["turning_point"]
        self.assertEqual(tp["direction"], "cooled")
        self.assertEqual(tp["why"], "Fee not answered")
        self.assertEqual(tp["start"], 12.0)

    def test_bad_direction_dropped(self):
        raw = {"turning_point": {"quote": "fees are too high", "direction": "exploded", "why": "x"}}
        self.assertEqual(build_report(raw, LINES), {})

    def test_telecaller_quote_rejected(self):
        raw = {"turning_point": {"quote": "twenty percent discount", "direction": "warmed", "why": "x"}}
        self.assertEqual(build_report(raw, LINES), {})


class ObjectionTests(unittest.TestCase):
    def test_valid_and_enum(self):
        raw = {"objections": [
            {"quote": "fees are too high", "handling": "dodged", "why": "no reply"},
            {"quote": "think about it", "handling": "ignored", "why": "x"},
        ]}
        out = build_report(raw, LINES)["objections"]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["handling"], "dodged")
        self.assertEqual(out[0]["time"], "00:12")

    def test_telecaller_quote_rejected(self):
        raw = {"objections": [{"quote": "twenty percent discount", "handling": "handled", "why": "x"}]}
        self.assertEqual(build_report(raw, LINES), {})

    def test_dedupe_same_line_keeps_first(self):
        raw = {"objections": [
            {"quote": "fees are too high", "handling": "dodged", "why": "first"},
            {"quote": "too high for me", "handling": "handled", "why": "second"},
        ]}
        out = build_report(raw, LINES)["objections"]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["why"], "first")

    def test_cap_and_sort(self):
        many = [Line(float(i), "customer", f"objection sentence about thing {i}z") for i in range(10)]
        raw = {"objections": [{"quote": l.text, "handling": "partly", "why": "w"} for l in reversed(many)]}
        out = build_report(raw, many)["objections"]
        self.assertEqual(len(out), MAX_OBJECTIONS)
        self.assertEqual([o["start"] for o in out], sorted(o["start"] for o in out))


class PromiseTests(unittest.TestCase):
    def test_must_be_telecaller(self):
        raw = {"promises": [{"quote": "fees are too high", "risky": True, "why": "x"}]}
        self.assertEqual(build_report(raw, LINES), {})

    def test_valid_promise(self):
        raw = {"promises": [{"quote": "twenty percent discount today", "risky": True, "why": "No discount in KB"}]}
        p = build_report(raw, LINES)["promises"][0]
        self.assertIs(p["risky"], True)
        self.assertEqual(p["time"], "00:20")
        self.assertEqual(p["start"], 20.0)

    def test_risky_non_bool_becomes_false(self):
        for bad in ("true", 1, None, "yes", [True]):
            raw = {"promises": [{"quote": "twenty percent discount today", "risky": bad, "why": "x"}]}
            self.assertIs(build_report(raw, LINES)["promises"][0]["risky"], False)

    def test_missing_risky_is_false(self):
        raw = {"promises": [{"quote": "refund guarantee", "why": "x"}]}
        self.assertIs(build_report(raw, LINES)["promises"][0]["risky"], False)

    def test_dedupe_and_cap(self):
        many = [Line(float(i), "telecaller", f"promise sentence guarantee {i}q") for i in range(10)]
        raw = {"promises": [{"quote": l.text, "risky": False, "why": "w"} for l in many] * 2}
        out = build_report(raw, many)["promises"]
        self.assertEqual(len(out), MAX_PROMISES)
        self.assertEqual(len({p["start"] for p in out}), MAX_PROMISES)


class CoachTests(unittest.TestCase):
    def test_either_speaker_allowed(self):
        for quote, start in (("fees are too high", 12.0), ("twenty percent discount", 20.0)):
            raw = {"coach": {"quote": quote, "tip": "Answer the fee first."}}
            c = build_report(raw, LINES)["coach"]
            self.assertEqual(c["start"], start)
            self.assertEqual(c["tip"], "Answer the fee first.")

    def test_empty_tip_dropped(self):
        for tip in ("", "   ", None, 5):
            raw = {"coach": {"quote": "fees are too high", "tip": tip}}
            self.assertEqual(build_report(raw, LINES), {})

    def test_unmatched_quote_dropped(self):
        self.assertEqual(build_report({"coach": {"quote": "not said", "tip": "x"}}, LINES), {})


class OutputShapeTests(unittest.TestCase):
    def test_only_non_empty_keys_and_version(self):
        raw = {"coach": {"quote": "fees are too high", "tip": "Do X."}, "mood": [], "objections": "bad"}
        out = build_report(raw, LINES)
        self.assertEqual(set(out), {"coach", "report_version"})
        self.assertEqual(out["report_version"], 1)

    def test_long_text_clipped(self):
        raw = {"coach": {"quote": "fees are too high", "tip": "t" * 1000}}
        self.assertLessEqual(len(build_report(raw, LINES)["coach"]["tip"]), 240)

    def test_input_not_mutated(self):
        raw = {"mood": [{"quote": "fees are too high", "mood": "negative"}]}
        before = repr(raw)
        build_report(raw, LINES)
        self.assertEqual(repr(raw), before)


if __name__ == "__main__":
    unittest.main()

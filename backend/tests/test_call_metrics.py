"""Transcript lines, talk share by words, and the level caps from the method document."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.call_lines import Line, clock, format_transcript, parse_transcript
from app.services import call_metrics as cm


def _words(n: int, word: str = "word") -> str:
    return " ".join([word] * n)


class LineFormatTests(unittest.TestCase):
    def test_round_trip(self):
        lines = [Line(72.4, "customer", "We have two branches actually."), Line(75.0, "telecaller", "Okay sir.")]
        text = format_transcript(lines)
        self.assertEqual(text.splitlines()[0], "[01:12] Customer: We have two branches actually.")
        self.assertEqual(parse_transcript(text), [Line(72.0, "customer", "We have two branches actually."), Line(75.0, "telecaller", "Okay sir.")])

    def test_legacy_lines_without_time(self):
        self.assertEqual(parse_transcript("Telecaller: Hello."), [Line(0.0, "telecaller", "Hello.")])

    def test_clock(self):
        self.assertEqual(clock(0), "00:00")
        self.assertEqual(clock(160.9), "02:40")


class TalkShareTests(unittest.TestCase):
    def test_document_example_65(self):
        lines = [Line(0, "telecaller", _words(650)), Line(1, "customer", _words(350))]
        self.assertEqual(cm.talk_share(lines), 65.0)

    def test_fillers_ignored(self):
        lines = [Line(0, "telecaller", _words(30) + " hmm uh aah"), Line(1, "customer", _words(30)), Line(2, "customer", "ok ok")]
        self.assertEqual(cm.talk_share(lines), 50.0)

    def test_tamil_words_count_as_words(self):
        lines = [Line(0, "telecaller", "சரி சார் நான் அனுப்புறேன் " * 10), Line(1, "customer", "ok thanks " * 10)]
        self.assertAlmostEqual(cm.talk_share(lines), 66.67, places=2)

    def test_under_50_words_is_none(self):
        self.assertIsNone(cm.talk_share([Line(0, "telecaller", _words(20)), Line(1, "customer", _words(20))]))


class CapTests(unittest.TestCase):
    def test_listening_caps(self):
        self.assertEqual(cm.listening_cap(64, 0.5), "excellent")
        self.assertEqual(cm.listening_cap(64, 1.25), "good")      # document full example
        self.assertEqual(cm.listening_cap(70, 0.5), "good")
        self.assertEqual(cm.listening_cap(80, 0.5), "partial")
        self.assertEqual(cm.listening_cap(60, 4), "partial")
        self.assertEqual(cm.listening_cap(80, 4), "poor")
        self.assertEqual(cm.listening_cap(None, None), "excellent")

    def test_listening_cap_reason(self):
        self.assertEqual(cm.listening_cap_reason(70, 4), ("partial", "interruptions"))
        self.assertEqual(cm.listening_cap_reason(80, 2), ("partial", "talk_share"))
        self.assertEqual(cm.listening_cap_reason(70, 2), ("good", "talk_share_and_interruptions"))
        self.assertEqual(cm.listening_cap_reason(80, 4), ("poor", "talk_share_and_interruptions"))
        self.assertEqual(cm.listening_cap_reason(60, 0.5), ("excellent", None))
        self.assertEqual(cm.listening_cap_reason(None, None), ("excellent", None))

    def test_courtesy_cap(self):
        self.assertEqual(cm.courtesy_cap(3), "excellent")
        self.assertEqual(cm.courtesy_cap(3.5), "good")
        self.assertEqual(cm.courtesy_cap(None), "excellent")

    def test_lower_level(self):
        self.assertEqual(cm.lower_level("excellent", "good"), "good")
        self.assertEqual(cm.lower_level("poor", "good"), "poor")

    def test_tips(self):
        self.assertEqual(cm.tips(60, 0.5), [])
        self.assertIn("Let the customer speak more. Aim to talk less than 65% of the time.", cm.tips(72, 0.5))
        self.assertIn("Let the customer finish before you reply.", cm.tips(60, 2))
        self.assertIn("Guide the conversation more: ask questions and explain the next step.", cm.tips(25, 0))


class MonologueAndDeadAirTests(unittest.TestCase):
    def test_longest_monologue_empty(self):
        self.assertEqual(cm.longest_monologue([]), 0.0)

    def test_longest_monologue_single_segment(self):
        self.assertEqual(cm.longest_monologue([(2.0, 7.5)]), 5.5)

    def test_longest_monologue_small_gap_merges(self):
        self.assertEqual(cm.longest_monologue([(0, 5), (6, 10)]), 10.0)

    def test_longest_monologue_large_gap_splits(self):
        self.assertEqual(cm.longest_monologue([(0, 5), (7, 8)]), 5.0)

    def test_longest_monologue_unsorted_input(self):
        self.assertEqual(cm.longest_monologue([(6, 10), (0, 5)]), 10.0)

    def test_longest_monologue_picks_longest_run(self):
        self.assertEqual(cm.longest_monologue([(0, 2), (10, 12), (12.5, 20)]), 10.0)

    def test_dead_air_both_empty(self):
        self.assertEqual(cm.dead_air([], []), 0.0)

    def test_dead_air_single_segment(self):
        self.assertEqual(cm.dead_air([(1, 5)], []), 0.0)

    def test_dead_air_ignores_leading_silence(self):
        self.assertEqual(cm.dead_air([(5, 6)], [(10, 11)]), 4.0)

    def test_dead_air_ignores_trailing_silence(self):
        self.assertEqual(cm.dead_air([(0, 1)], [(1.5, 2)]), 0.0)

    def test_dead_air_ignores_gaps_under_minimum(self):
        self.assertEqual(cm.dead_air([(0, 1), (3, 4)], [(6.5, 7)]), 0.0)

    def test_dead_air_counts_gap_at_minimum(self):
        self.assertEqual(cm.dead_air([(0, 1)], [(4, 5)]), 3.0)

    def test_dead_air_sums_multiple_gaps(self):
        self.assertEqual(cm.dead_air([(0, 1), (9, 10)], [(5, 6)]), 7.0)

    def test_dead_air_overlap_between_sides_has_no_gap(self):
        self.assertEqual(cm.dead_air([(0, 4)], [(2, 6)]), 0.0)

    def test_dead_air_one_side_empty(self):
        self.assertEqual(cm.dead_air([], [(0, 1), (6, 7)]), 5.0)

    def test_dead_air_unsorted_input(self):
        self.assertEqual(cm.dead_air([(10, 11)], [(5, 6), (0, 1)]), 8.0)


if __name__ == "__main__":
    unittest.main()

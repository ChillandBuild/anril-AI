"""English transcript on demand: cached, skips the model for English, tenant and team scope enforced."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import call_translation as ct
from tests.fake_supabase import FakeSupabase

CALL = "00000000-0000-0000-0000-0000000000c1"
OTHER_TENANT_CALL = "00000000-0000-0000-0000-0000000000c2"
URL = f"/api/v1/call-translate/{CALL}"
OWNER = {"tenant_id": "t1", "role": "owner", "user_id": "owner-1", "caller_id": None, "permissions": []}

TAMIL = (
    "[00:01] Telecaller: வணக்கம், நான் அனிதா பேசுறேன்\n"
    "[00:05] Customer: சொல்லுங்க\n"
    "[00:09] Telecaller: உங்க ஆர்டர் நாளைக்கு வரும்\n"
    "[00:12] Customer: சரி நன்றி"
)
TAMIL_EN = ["Hello, this is Anitha speaking", "Tell me", "Your order will come tomorrow", "Okay, thank you"]
ENGLISH = (
    "[00:01] Telecaller: Hello, this is Anitha from the shop and I am calling about your order\n"
    "[00:05] Customer: Yes, tell me what is the problem with it"
)


def gemini_says(lines):
    return AsyncMock(return_value={"lines": lines})


class CallTranslateTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.db.rows("call_logs").extend([
            {"id": CALL, "tenant_id": "t1", "caller_id": "c1", "transcript": TAMIL, "transcript_en": None},
            {"id": OTHER_TENANT_CALL, "tenant_id": "t2", "caller_id": "cx", "transcript": TAMIL, "transcript_en": None},
        ])
        self.p = patch("app.routes.call_translate.get_supabase", return_value=self.db)
        self.p.start()
        self.ctx = dict(OWNER)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.p.stop()

    def row(self, cid=CALL):
        return next(r for r in self.db.rows("call_logs") if r["id"] == cid)

    def post(self, url=URL):
        return self.client.post(url)

    # ── translate once, then cached ──────────────────────────────────────────

    def test_translates_stores_and_keeps_the_speaker_labels(self):
        gem = gemini_says(TAMIL_EN)
        with patch.object(ct, "gemini_analysis_json", gem):
            res = self.post()
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertFalse(body["cached"])
        self.assertFalse(body["already_english"])
        self.assertEqual(gem.await_count, 1)
        stored = self.row()["transcript_en"].splitlines()
        self.assertEqual(stored[0], "[00:01] Telecaller: Hello, this is Anitha speaking")
        self.assertEqual(stored[1], "[00:05] Customer: Tell me")
        self.assertEqual(len(stored), 4)
        self.assertIsNotNone(self.row()["transcript_en_at"])

    def test_the_model_sees_only_the_spoken_words_not_the_labels(self):
        gem = gemini_says(TAMIL_EN)
        with patch.object(ct, "gemini_analysis_json", gem):
            self.post()
        sent = json.loads(gem.call_args.kwargs["user_prompt"])
        self.assertEqual(sent[0], "வணக்கம், நான் அனிதா பேசுறேன்")
        self.assertEqual(gem.call_args.kwargs["tenant_id"], "t1")

    def test_the_browser_gets_only_the_first_and_last_line(self):
        with patch.object(ct, "gemini_analysis_json", gemini_says(TAMIL_EN)):
            body = self.post().json()
        self.assertEqual(body["transcript_preview_en"]["hidden_lines"], 2)
        self.assertEqual(body["transcript_en"].splitlines(), [
            "[00:01] Telecaller: Hello, this is Anitha speaking", "[00:12] Customer: Okay, thank you"])
        self.assertNotIn("Tell me", json.dumps(body))
        self.assertNotIn("Your order will come tomorrow", json.dumps(body))

    def test_a_second_request_is_served_from_the_saved_copy(self):
        gem = gemini_says(TAMIL_EN)
        with patch.object(ct, "gemini_analysis_json", gem):
            self.post()
            again = self.post()
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json()["cached"])
        self.assertEqual(gem.await_count, 1)

    def test_a_saved_translation_is_returned_without_touching_the_model(self):
        self.row()["transcript_en"] = "[00:01] Telecaller: Hello\n[00:02] Customer: Hi"
        gem = gemini_says([])
        with patch.object(ct, "gemini_analysis_json", gem):
            body = self.post().json()
        self.assertTrue(body["cached"])
        gem.assert_not_awaited()

    # ── English skips the model ──────────────────────────────────────────────

    def test_an_english_transcript_never_calls_the_model(self):
        self.row()["transcript"] = ENGLISH
        gem = gemini_says([])
        with patch.object(ct, "gemini_analysis_json", gem):
            res = self.post()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["already_english"])
        gem.assert_not_awaited()
        self.assertIsNone(self.row()["transcript_en"])

    def test_looks_english_tells_english_from_tamil_hindi_and_tanglish(self):
        self.assertTrue(ct.looks_english(ENGLISH))
        self.assertFalse(ct.looks_english(TAMIL))
        self.assertFalse(ct.looks_english("[00:01] Customer: नमस्ते मुझे ऑर्डर के बारे में बात करनी है"))
        self.assertFalse(ct.looks_english("[00:01] Customer: naan nalaiku kaalai la vandhu paakuren, order eppo varum"))
        self.assertTrue(ct.looks_english(""))

    # ── who may ask ──────────────────────────────────────────────────────────

    def test_another_clients_call_is_not_found(self):
        gem = gemini_says(TAMIL_EN)
        with patch.object(ct, "gemini_analysis_json", gem):
            res = self.post(f"/api/v1/call-translate/{OTHER_TENANT_CALL}")
        self.assertEqual(res.status_code, 404)
        gem.assert_not_awaited()
        self.assertIsNone(self.row(OTHER_TENANT_CALL)["transcript_en"])

    def test_a_team_leader_cannot_translate_another_teams_call(self):
        self.ctx = {"tenant_id": "t1", "role": "caller", "user_id": "lead-1", "caller_id": "c9", "permissions": ["team.manage"]}
        gem = gemini_says(TAMIL_EN)
        with patch("app.routes.call_translate.scoped_caller_ids", return_value={"c9", "c2"}), \
             patch.object(ct, "gemini_analysis_json", gem):
            res = self.post()  # the call belongs to c1
        self.assertEqual(res.status_code, 404)
        gem.assert_not_awaited()

    def test_a_team_leader_can_translate_their_own_teams_call(self):
        self.ctx = {"tenant_id": "t1", "role": "caller", "user_id": "lead-1", "caller_id": "c9", "permissions": ["team.manage"]}
        with patch("app.routes.call_translate.scoped_caller_ids", return_value={"c1"}), \
             patch.object(ct, "gemini_analysis_json", gemini_says(TAMIL_EN)):
            self.assertEqual(self.post().status_code, 200)

    def test_someone_who_cannot_open_call_review_gets_403(self):
        self.ctx = {"tenant_id": "t1", "role": "caller", "user_id": "u9", "caller_id": "c1", "permissions": []}
        gem = gemini_says(TAMIL_EN)
        with patch.object(ct, "gemini_analysis_json", gem):
            self.assertEqual(self.post().status_code, 403)
        gem.assert_not_awaited()

    # ── failures ─────────────────────────────────────────────────────────────

    def test_a_call_with_no_transcript_is_a_404(self):
        self.row()["transcript"] = None
        self.assertEqual(self.post().status_code, 404)

    def test_a_wrong_line_count_from_the_model_saves_nothing(self):
        gem = gemini_says(["only one line"])
        with patch.object(ct, "gemini_analysis_json", gem):
            res = self.post()
        self.assertEqual(res.status_code, 502)
        self.assertEqual(gem.await_count, 2)  # one retry
        self.assertIsNone(self.row()["transcript_en"])

    def test_a_missing_gemini_key_is_a_plain_503(self):
        with patch.object(ct, "gemini_analysis_json", AsyncMock(side_effect=RuntimeError("no key"))):
            res = self.post()
        self.assertEqual(res.status_code, 503)
        self.assertIsNone(self.row()["transcript_en"])

    def test_a_very_long_call_is_refused_before_the_model(self):
        self.row()["transcript"] = "\n".join(f"[00:{i % 60:02d}] Customer: வணக்கம் {i} " + "அ" * 50 for i in range(600))
        gem = gemini_says([])
        with patch.object(ct, "gemini_analysis_json", gem):
            res = self.post()
        self.assertEqual(res.status_code, 413)
        gem.assert_not_awaited()

    def test_a_long_call_is_translated_in_batches_with_the_lines_kept_in_order(self):
        lines = [f"[00:{i % 60:02d}] Customer: வணக்கம் {i} " + "அ" * 200 for i in range(60)]  # ~14k chars, over one batch
        self.row()["transcript"] = "\n".join(lines)

        async def fake(**kw):
            texts = json.loads(kw["user_prompt"])
            return {"lines": [f"EN{t.split()[1]}" for t in texts]}
        gem = AsyncMock(side_effect=fake)
        with patch.object(ct, "gemini_analysis_json", gem):
            self.assertEqual(self.post().status_code, 200)
        self.assertGreater(gem.await_count, 1)
        out = self.row()["transcript_en"].splitlines()
        self.assertEqual(len(out), 60)
        self.assertEqual(out[0], "[00:00] Customer: EN0")
        self.assertEqual(out[59], "[00:59] Customer: EN59")


if __name__ == "__main__":
    unittest.main()

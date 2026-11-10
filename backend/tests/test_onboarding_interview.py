"""Tests for the AI onboarding interview:
POST /api/v1/onboarding/interview/draft  -- asks the tenant's OWN configured
    AI provider to draft a business description from a few answers, never a
    shared platform key. It does NOT draft a master prompt: that is
    platform-wide and identical for every tenant.
POST /api/v1/onboarding/interview/apply  -- writes an already-reviewed draft,
    reusing the same clobber guard as apply-starter.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_id

ANSWERS_PAYLOAD = {
    "answers": [
        {"question_id": "what_you_sell", "answer": "Physiotherapy sessions for sports injuries."},
        {"question_id": "never_promise", "answer": "Never guarantee a recovery timeline."},
        {"question_id": "hand_over", "answer": "Whenever someone describes pain or wants to book."},
    ]
}

VALID_DRAFT_JSON = (
    '{"business_description": "We offer physiotherapy for sports injuries. '
    'HAND OVER TO A PERSON WHEN: pain is described or a booking is requested. '
    'WHAT YOU MUST NEVER DO: never guarantee a recovery timeline."}'
)


class InterviewDraftRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_id] = lambda: "tenant-1"

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock)
    def test_drafts_from_the_tenants_own_provider(self, mock_llm_chat):
        mock_llm_chat.return_value = VALID_DRAFT_JSON

        res = self.client.post("/api/v1/onboarding/interview/draft", json=ANSWERS_PAYLOAD)

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("physiotherapy", body["business_description"].lower())
        self.assertIn("HAND OVER TO A PERSON WHEN", body["business_description"])
        # tenant_id was threaded through -- the provider resolution inside
        # _llm_chat is what enforces "this tenant's own key, never shared".
        call_kwargs = mock_llm_chat.call_args.kwargs
        self.assertEqual(call_kwargs["tenant_id"], "tenant-1")
        self.assertEqual(call_kwargs["purpose"], "onboarding_interview")

    @patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock)
    def test_draft_never_returns_a_master_prompt(self, mock_llm_chat):
        """Behaviour is platform-wide; the interview must not offer to change it."""
        mock_llm_chat.return_value = VALID_DRAFT_JSON

        res = self.client.post("/api/v1/onboarding/interview/draft", json=ANSWERS_PAYLOAD)

        self.assertEqual(res.status_code, 200)
        self.assertNotIn("master_prompt", res.json())

    @patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock)
    def test_strips_markdown_code_fences_before_parsing(self, mock_llm_chat):
        mock_llm_chat.return_value = "```json\n" + VALID_DRAFT_JSON + "\n```"

        res = self.client.post("/api/v1/onboarding/interview/draft", json=ANSWERS_PAYLOAD)

        self.assertEqual(res.status_code, 200)

    @patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock)
    def test_no_provider_configured_returns_clean_400_not_500(self, mock_llm_chat):
        mock_llm_chat.side_effect = RuntimeError("gemini_api_key not configured for this client")

        res = self.client.post("/api/v1/onboarding/interview/draft", json=ANSWERS_PAYLOAD)

        self.assertEqual(res.status_code, 400)
        self.assertIn("Add a Gemini API key", res.json()["detail"])

    @patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock)
    def test_malformed_json_from_the_model_returns_502_not_500(self, mock_llm_chat):
        mock_llm_chat.return_value = "Sure, here's a great prompt for your business!"

        res = self.client.post("/api/v1/onboarding/interview/draft", json=ANSWERS_PAYLOAD)

        self.assertEqual(res.status_code, 502)

    @patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock)
    def test_missing_key_in_json_returns_502(self, mock_llm_chat):
        mock_llm_chat.return_value = '{"master_prompt": "wrong key"}'

        res = self.client.post("/api/v1/onboarding/interview/draft", json=ANSWERS_PAYLOAD)

        self.assertEqual(res.status_code, 502)

    def test_no_answers_is_400(self):
        res = self.client.post("/api/v1/onboarding/interview/draft", json={"answers": []})
        self.assertEqual(res.status_code, 400)


class InterviewApplyRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_id] = lambda: "tenant-1"

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.routes.onboarding.get_setting", return_value=None)
    @patch("app.routes.onboarding.save_setting")
    @patch("app.routes.onboarding.get_supabase")
    def test_applies_a_reviewed_draft(self, mock_get_db, mock_save, mock_get_setting):
        mock_get_db.return_value = MagicMock()

        res = self.client.post("/api/v1/onboarding/interview/apply", json={
            "business_description": "We offer physiotherapy.",
        })

        self.assertEqual(res.status_code, 200)
        mock_save.assert_called_once_with("business_description", "We offer physiotherapy.", tenant_id="tenant-1")

    @patch("app.routes.onboarding.get_setting", return_value=None)
    @patch("app.routes.onboarding.save_setting")
    @patch("app.routes.onboarding.get_supabase")
    def test_a_submitted_master_prompt_is_ignored(self, mock_get_db, mock_save, mock_get_setting):
        """A stale client sending master_prompt must not write one anywhere."""
        db = MagicMock()
        mock_get_db.return_value = db

        res = self.client.post("/api/v1/onboarding/interview/apply", json={
            "master_prompt": "Be warm and precise.",
            "business_description": "We offer physiotherapy.",
        })

        self.assertEqual(res.status_code, 200)
        touched = {c.args[0] for c in db.table.call_args_list if c.args}
        self.assertNotIn("ai_prompts", touched)

    @patch("app.routes.onboarding.get_setting", return_value="Already written by the client.")
    @patch("app.routes.onboarding.save_setting")
    @patch("app.routes.onboarding.get_supabase")
    def test_refuses_to_clobber_without_force(self, mock_get_db, mock_save, mock_get_setting):
        mock_get_db.return_value = MagicMock()

        res = self.client.post("/api/v1/onboarding/interview/apply", json={
            "business_description": "We offer physiotherapy.",
        })

        self.assertEqual(res.status_code, 409)
        mock_save.assert_not_called()

    def test_blank_description_is_400(self):
        res = self.client.post("/api/v1/onboarding/interview/apply", json={
            "business_description": "   ",
        })
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()

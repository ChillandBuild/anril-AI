"""Tests for POST /api/v1/ask -- plain-English analytics. The model picks
WHICH real analytics function answers the question and phrases the answer
sentence; the numbers must always come from that real function's actual
return value, never from the model. These tests exist specifically to prove
that guarantee, not just that the endpoint returns 200.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role

FUNNEL_DATA = {
    "total_leads": 214, "by_segment": {"A": 42, "B": 60, "C": 90, "D": 22},
    "by_source": {"instagram": 30}, "leads_this_week": 18, "avg_score": 5.4,
    "score_histogram": [], "hot_lead_aging": [],
}


def _tool_call(name, args):
    import json
    return {"function": {"name": name, "arguments": json.dumps(args)}}


class AskRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "tenant-1", "role": "owner", "permissions": [],
        }

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.routes.ask.funnel_analytics", new_callable=AsyncMock)
    @patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock)
    @patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock)
    def test_answer_uses_only_the_real_functions_data(self, mock_classify, mock_answer, mock_funnel):
        mock_classify.return_value = ("", [_tool_call("funnel_analytics", {})])
        mock_funnel.return_value = FUNNEL_DATA
        mock_answer.return_value = "42 hot leads have arrived so far."

        res = self.client.post("/api/v1/ask", json={"question": "How many hot leads do I have?"})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["answer"], "42 hot leads have arrived so far.")
        self.assertEqual(body["data"], FUNNEL_DATA)
        self.assertEqual(body["source"], "funnel_analytics")
        mock_funnel.assert_awaited_once_with(tenant_id="tenant-1")
        # The exact data the model was shown to write the sentence must be
        # the real function's own return value, not something reconstructed.
        answer_call_messages = mock_answer.call_args[0][0]
        user_message = answer_call_messages[-1]["content"]
        self.assertIn("42", user_message)  # by_segment.A, from the real data
        self.assertIn("214", user_message)  # total_leads, from the real data

    @patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock)
    def test_no_matching_tool_returns_a_graceful_unanswerable_message(self, mock_classify):
        mock_classify.return_value = ("", [])

        res = self.client.post("/api/v1/ask", json={"question": "What's the weather like?"})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIsNone(body["data"])
        self.assertIsNone(body["source"])
        self.assertIn("can't answer", body["answer"])

    @patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock)
    def test_no_provider_configured_is_a_clean_400_not_500(self, mock_classify):
        mock_classify.side_effect = RuntimeError("gemini_api_key not configured for this client")

        res = self.client.post("/api/v1/ask", json={"question": "How many leads today?"})

        self.assertEqual(res.status_code, 400)
        self.assertIn("Add a Gemini API key", res.json()["detail"])

    def test_blank_question_is_400(self):
        res = self.client.post("/api/v1/ask", json={"question": "   "})
        self.assertEqual(res.status_code, 400)

    @patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock)
    def test_malformed_tool_arguments_do_not_crash_the_request(self, mock_classify):
        mock_classify.return_value = (
            "", [{"function": {"name": "funnel_analytics", "arguments": "not valid json{{"}}]
        )
        with patch("app.routes.ask.funnel_analytics", new_callable=AsyncMock) as mock_funnel, \
             patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock) as mock_answer:
            mock_funnel.return_value = FUNNEL_DATA
            mock_answer.return_value = "Answer."
            res = self.client.post("/api/v1/ask", json={"question": "How many leads?"})

        self.assertEqual(res.status_code, 200)

    def test_no_analytics_permission_is_403(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "tenant-1", "role": "caller", "permissions": [],
        }
        res = self.client.post("/api/v1/ask", json={"question": "How many leads?"})
        self.assertEqual(res.status_code, 403)

    @patch("app.routes.ask.compare_analytics", new_callable=AsyncMock)
    @patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock)
    @patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock)
    def test_dispatches_to_the_tool_the_model_picked_with_its_arguments(self, mock_classify, mock_answer, mock_compare):
        mock_classify.return_value = ("", [_tool_call("compare_analytics", {"preset": "last_30d"})])
        mock_compare.return_value = {"current": {}, "prior": {}}
        mock_answer.return_value = "Answer."

        res = self.client.post("/api/v1/ask", json={"question": "How does this month compare to last?"})

        self.assertEqual(res.status_code, 200)
        mock_compare.assert_awaited_once_with(tenant_id="tenant-1", preset="last_30d")


if __name__ == "__main__":
    unittest.main()

"""The Playground shows why a reply failed ("problem"); a visitor only ever gets the sorry line.

Real case (2026-11-14): Google answered 402 "Your prepayment credits are depleted" and the owner
saw only "Mannikkavum, ippo konjam technical problem irukku", with no hint that billing was the cause.
"""
import httpx
import pytest

from app.companion import engine
from app.services import ai_reply
from tests.test_companion_chat_api import DASH, PUB, bearer, env  # noqa: F401  (env is a fixture)


def _http_error(code: int, body: str = "") -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/x")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(code, text=body, request=req))


def _llm_fails(monkeypatch, exc):
    async def plain(*a, **kw):
        raise exc
    monkeypatch.setattr(engine.ai_reply, "_llm_chat", plain)


@pytest.mark.parametrize("exc,words", [
    (_http_error(402, '{"error": {"message": "Your prepayment credits are depleted."}}'), "credits are used up"),
    (_http_error(429, '{"error": {"message": "Your prepayment credits are depleted."}}'), "credits are used up"),
    (_http_error(429, '{"error": {"message": "Quota exceeded per minute"}}'), "rate limit"),
    (_http_error(403, '{"error": {"message": "Billing is not enabled"}}'), "billing isn't set up"),
    (_http_error(400, "API key not valid"), "error 400"),
    (_http_error(401), "refused your Gemini key"),
    (_http_error(404), "doesn't offer this AI model"),
    (_http_error(503), "on its side"),
    (httpx.ReadTimeout("slow"), "timeout"),
    (ValueError("odd"), "ValueError"),
])
def test_describe_llm_error_says_what_to_do(exc, words):
    assert words in ai_reply.describe_llm_error(exc)


def test_playground_shows_the_reason(env, monkeypatch):  # noqa: F811
    _llm_fails(monkeypatch, _http_error(402, "Your prepayment credits are depleted."))
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "Hiii"})
    body = r.json()
    assert r.status_code == 200
    assert body["text"] == engine.fallback_line("ta-en")          # what a visitor would get
    assert "ai.studio/projects" in body["problem"]


def test_playground_problem_is_none_when_the_reply_works(env):  # noqa: F811
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "Hiii"})
    assert r.json()["problem"] is None


def test_public_api_never_shows_the_reason(env, monkeypatch):  # noqa: F811
    _llm_fails(monkeypatch, _http_error(402, "Your prepayment credits are depleted."))
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "Hiii"})
    assert r.status_code == 200
    assert "problem" not in r.json() and "credits" not in r.text

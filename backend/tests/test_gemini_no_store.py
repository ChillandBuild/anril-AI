"""Every Gemini call is sent with "store": False.

The /v1beta/interactions endpoint keeps a copy of each call on Google's side unless told not to,
and that save cost ~3.4s per call (measured 2026-11-14: a tiny flash-lite call took 4.8s with it,
1.45s without). Nothing here reads a saved call back (no previous_interaction_id; every call
re-sends the whole chat), so the copy only cost time and kept customers' chats at Google.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import gemini_client

APP = Path(__file__).resolve().parents[1] / "app"


def _client_returning(data: dict):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = data
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_chat_completion_is_not_stored_at_google():
    client = _client_returning({"steps": [{"type": "model_output", "content": [{"type": "text", "text": "hi"}]}]})
    with patch("app.services.gemini_client.require_tenant_setting", return_value="k"), \
         patch("app.services.gemini_client._record"), \
         patch("app.services.gemini_client.httpx.AsyncClient") as cls:
        cls.return_value.__aenter__.return_value = client
        await gemini_client.gemini_chat_completion([{"role": "user", "content": "hi"}], model="m", tenant_id="t")
    assert client.post.call_args.kwargs["json"]["store"] is False


@pytest.mark.asyncio
async def test_chat_with_tools_is_not_stored_at_google():
    client = _client_returning({"steps": [{"type": "model_output", "content": [{"type": "text", "text": "hi"}]}]})
    with patch("app.services.gemini_client.require_tenant_setting", return_value="k"), \
         patch("app.services.gemini_client._record"), \
         patch("app.services.gemini_client.httpx.AsyncClient") as cls:
        cls.return_value.__aenter__.return_value = client
        await gemini_client.gemini_chat_completion_with_tools(
            [{"role": "user", "content": "hi"}], tools=[], model="m", tenant_id="t")
    assert client.post.call_args.kwargs["json"]["store"] is False


def test_every_interactions_call_in_the_app_turns_storing_off():
    """A new call site that forgets the switch fails here: each file posting to the endpoint has
    as many '"store": False' as it has posts."""
    checked = 0
    for path in APP.rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        posts = src.count("GEMINI_INTERACTIONS_URL,")
        if posts:
            checked += posts
            assert src.count('"store": False') >= posts, f"{path.relative_to(APP)}: a Gemini call without store=False"
    assert checked >= 8

"""Tests for outbound_guard module — dry_run mode blocks external HTTP writes."""

import asyncio
import json
import logging
from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.services.outbound_guard import (
    install_outbound_guard,
    uninstall_outbound_guard,
)


@pytest.fixture(autouse=True)
def _always_uninstall_guard():
    """A failing assert must never leave httpx patched for the rest of the suite."""
    yield
    uninstall_outbound_guard()


@pytest.fixture
def capture_logs(caplog):
    """Fixture to capture logs at WARNING level."""
    caplog.set_level(logging.WARNING)
    return caplog


def _create_mock_transport():
    """Create a mock transport that records requests and returns a 200 response."""
    requests_sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_sent.append(request)
        return httpx.Response(
            200, json={"real": True}, request=request
        )

    return handler, requests_sent


class TestDryRunBlocking:
    """Test that dry_run mode blocks external writes."""

    def test_dry_run_blocks_whatsapp_send(self, monkeypatch, capture_logs):
        """dry_run: POST to graph.facebook.com is NOT sent; response has wamid.DRYRUN."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.post(
            "https://graph.facebook.com/v21.0/123/messages",
            json={"to": "919800000001", "type": "text", "text": {"body": "test"}},
        )

        # Request should NOT be sent to the transport
        assert len(requests_sent) == 0

        # Response should be 200 with a dry-run message ID
        assert response.status_code == 200
        data = response.json()
        assert data["messages"][0]["id"].startswith("wamid.DRYRUN")

        # Log should show the block
        assert "DRY-RUN blocked" in capture_logs.text
        assert "graph.facebook.com" in capture_logs.text
        # Phone numbers are PII: only the last 4 digits reach the log
        assert "919800000001" not in capture_logs.text
        assert "to=***0001" in capture_logs.text

        uninstall_outbound_guard()
        client.close()

    def test_dry_run_blocks_telegram_send(self, monkeypatch, capture_logs):
        """dry_run: POST to api.telegram.org is NOT sent; response has result.message_id."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.post(
            "https://api.telegram.org/bot123:ABC/sendMessage",
            json={"chat_id": "555", "text": "test"},
        )

        # Request should NOT be sent to the transport
        assert len(requests_sent) == 0

        # Response should be 200 with a dry-run message_id
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["message_id"] is not None

        # Log should NOT contain the secret token
        log_text = capture_logs.text
        assert "123:ABC" not in log_text
        assert "DRY-RUN blocked" in log_text

        uninstall_outbound_guard()
        client.close()

    def test_dry_run_allows_supabase(self, monkeypatch, capture_logs):
        """dry_run: POST to Supabase host IS sent."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        monkeypatch.setattr(settings, "supabase_url", "https://abc.supabase.co")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.post(
            "https://abc.supabase.co/rest/v1/leads",
            json={"name": "test"},
        )

        # Request SHOULD be sent to the transport
        assert len(requests_sent) == 1
        assert requests_sent[0].url == "https://abc.supabase.co/rest/v1/leads"

        uninstall_outbound_guard()
        client.close()

    def test_dry_run_allows_ai_providers(self, monkeypatch, capture_logs):
        """dry_run: POST to AI provider hosts IS sent."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        # Test all allowed AI providers
        for url in [
            "https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent",
            "https://api.jina.ai/v1/embeddings",
        ]:
            response = client.post(url, json={"text": "test"})
            assert response.status_code == 200
            assert response.json()["real"] is True

        # All requests should be sent to the transport
        assert len(requests_sent) == 2

        uninstall_outbound_guard()
        client.close()

    def test_dry_run_allows_get_requests(self, monkeypatch, capture_logs):
        """dry_run: GET to external hosts IS sent (reads allowed)."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.get("https://graph.facebook.com/v21.0/me")

        # GET request should be sent to the transport
        assert len(requests_sent) == 1
        assert requests_sent[0].method == "GET"

        uninstall_outbound_guard()
        client.close()

    def test_dry_run_allowlist_recipient(self, monkeypatch, capture_logs):
        """dry_run: allowlisted recipient IS sent (digits-only comparison)."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        monkeypatch.setattr(settings, "outbound_allow_to", "919800000001")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        # Test with various formatting of the same number
        response = client.post(
            "https://graph.facebook.com/v21.0/123/messages",
            json={"to": "+91 98000 00001", "type": "text", "text": {"body": "test"}},
        )

        # Request SHOULD be sent because recipient matches allowlist (digits-only)
        assert len(requests_sent) == 1

        uninstall_outbound_guard()
        client.close()

    def test_stray_comma_in_allowlist_does_not_open_the_gate(self, monkeypatch, capture_logs):
        """dry_run: an empty allowlist entry must not let a digit-less recipient through."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        monkeypatch.setattr(settings, "outbound_allow_to", "919800000001,")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        client.post("https://graph.facebook.com/v21.0/123/messages", json={"to": "no-digits"})

        assert len(requests_sent) == 0

        uninstall_outbound_guard()
        client.close()

    def test_dry_run_blocks_telecmi_call(self, monkeypatch, capture_logs):
        """dry_run: POST to rest.telecmi.com is NOT sent."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.post(
            "https://rest.telecmi.com/v2/webrtc/click2call",
            json={"to": "919800000001"},
        )

        # Request should NOT be sent to the transport
        assert len(requests_sent) == 0

        # Response should be 200
        assert response.status_code == 200

        uninstall_outbound_guard()
        client.close()

    def test_live_mode_is_noop(self, monkeypatch):
        """live mode: install_outbound_guard() is a no-op — requests go through."""
        monkeypatch.setattr(settings, "outbound_mode", "live")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.post(
            "https://graph.facebook.com/v21.0/123/messages",
            json={"to": "919800000001"},
        )

        # Request SHOULD be sent in live mode (guard is no-op)
        assert len(requests_sent) == 1

        uninstall_outbound_guard()
        client.close()

    def test_async_client_dry_run_blocks(self, monkeypatch, capture_logs):
        """dry_run with AsyncClient: POST to graph.facebook.com is NOT sent."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()

        async def test():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                response = await client.post(
                    "https://graph.facebook.com/v21.0/123/messages",
                    json={"to": "919800000001"},
                )
                assert response.status_code == 200
                assert response.json()["messages"][0]["id"].startswith("wamid.DRYRUN")

        asyncio.run(test())

        # Request should NOT be sent to the transport
        assert len(requests_sent) == 0

        uninstall_outbound_guard()

    def test_web_push_dry_run(self, monkeypatch, capture_logs):
        """web push in dry_run: send_user_push returns early without calling pywebpush."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        monkeypatch.setattr(settings, "vapid_public_key", "dummy_public")
        monkeypatch.setattr(settings, "vapid_private_key", "dummy_private")

        # Mock pywebpush to fail if called
        mock_webpush = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("pywebpush should not be called in dry_run")
        )
        with patch("app.services.web_push._webpush") as mock_import:
            mock_import.return_value = (mock_webpush, Exception)

            # Import and call the function
            from app.services.web_push import send_user_push

            # Should not raise because it should return early
            send_user_push(
                tenant_id="test",
                user_id="user1",
                title="test",
                body="test body",
            )

            mock_import.assert_not_called()

        # Should see a log entry
        assert "DRY-RUN blocked web push" in capture_logs.text

    def test_razorpay_dry_run_response(self, monkeypatch, capture_logs):
        """dry_run Razorpay: response includes short_url and id."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.post(
            "https://api.razorpay.com/v1/payment_links",
            json={"amount": 10000},
        )

        assert response.status_code == 200
        data = response.json()
        assert "short_url" in data
        assert "id" in data

        uninstall_outbound_guard()
        client.close()

    def test_astro_bridge_dry_run_response(self, monkeypatch, capture_logs):
        """dry_run Astro Bridge: response includes success field."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.post(
            "https://astro.example.com/push_consultation",
            json={"session_id": "123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "success" in data

        uninstall_outbound_guard()
        client.close()

    def test_guard_is_idempotent(self, monkeypatch, capture_logs):
        """install_outbound_guard() is idempotent — can call multiple times."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")

        # Install twice
        install_outbound_guard()
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        response = client.post(
            "https://graph.facebook.com/v21.0/123/messages",
            json={"to": "919800000001"},
        )

        # Should still be blocked
        assert len(requests_sent) == 0
        assert response.status_code == 200

        uninstall_outbound_guard()
        client.close()

    def test_secret_not_logged_in_url(self, monkeypatch, capture_logs):
        """Log redacts bot tokens and secrets in URL paths."""
        monkeypatch.setattr(settings, "outbound_mode", "dry_run")
        install_outbound_guard()

        handler, requests_sent = _create_mock_transport()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        # Telegram with token in URL
        response = client.post(
            "https://api.telegram.org/bot12345:SECRET_TOKEN_ABC/sendMessage",
            json={"chat_id": "555"},
        )

        assert response.status_code == 200

        # Log should NOT contain the secret token
        log_text = capture_logs.text
        assert "12345:SECRET_TOKEN_ABC" not in log_text
        assert "bot***" in log_text or "DRY-RUN blocked" in log_text

        uninstall_outbound_guard()
        client.close()


def test_other_supabase_project_is_blocked(monkeypatch):
    """dry_run: only OUR Supabase host is safe — another project's edge function is not."""
    monkeypatch.setattr(settings, "outbound_mode", "dry_run")
    monkeypatch.setattr(settings, "supabase_url", "https://abc.supabase.co")
    install_outbound_guard()

    handler, requests_sent = _create_mock_transport()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        client.post("https://evil.supabase.co/functions/v1/send-sms", json={"to": "1"})

    assert len(requests_sent) == 0


def test_scheduler_off_with_live_outbound_warns(monkeypatch, caplog):
    """Turning off only the scheduler must shout that real sends still happen."""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(settings, "outbound_mode", "live")
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    install_outbound_guard()

    assert "WILL reach real people" in caplog.text


def test_app_uses_no_http_client_the_guard_cannot_see():
    """The guard patches httpx only. A new requests/aiohttp/urllib/smtplib import would
    send real messages from a laptop in dry_run — fail loudly so the guard gets extended."""
    import pathlib
    import re as _re

    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    pattern = _re.compile(
        r"^\s*(import|from)\s+(requests|aiohttp|urllib3|smtplib|http\.client)\b"
        r"|urllib\.request|urlopen\(",
        _re.MULTILINE,
    )
    offenders = [
        str(path.relative_to(app_dir))
        for path in app_dir.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"Non-httpx HTTP client used (extend outbound_guard): {offenders}"

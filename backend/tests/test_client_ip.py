"""The per-IP rate-limit key (_client_ip) and the in-process limiter (_SlidingWindow).

Production shape (Render, checked 2026-11-23): uvicorn trusts every proxy and replaces
request.client with the leftmost X-Forwarded-For entry, which the caller types. So a
"peer" here can be attacker-chosen; only CF-Connecting-IP (overwritten by Cloudflare on
every request) is a safe key.
"""
import pytest
from starlette.requests import Request

from app.routes import auto_messages as routes


def _req(headers: dict, peer: str | None = "10.0.0.1") -> Request:
    return Request({
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 0) if peer else None,
    })


@pytest.fixture(autouse=True)
def _default_trust(monkeypatch):
    monkeypatch.setattr(routes.env_settings, "trusted_proxy_cidrs", None)
    routes._trusted_proxies.cache_clear()
    yield
    routes._trusted_proxies.cache_clear()


def test_attacker_typed_forwarded_for_does_not_give_a_fresh_bucket():
    # What Render hands the app: uvicorn put the typed XFF value into request.client, and
    # Cloudflare's CF-Connecting-IP holds the attacker's real address.
    limiter = routes._SlidingWindow(3, 60)
    allowed = [
        limiter.allow(routes._client_ip(_req(
            {"x-forwarded-for": f"9.9.9.{i}", "cf-connecting-ip": "49.37.10.20"}, peer=f"9.9.9.{i}")))
        for i in range(10)
    ]
    assert allowed == [True, True, True] + [False] * 7


def test_cloudflare_ip_is_the_key_whatever_the_peer_is():
    spoof = {"cf-connecting-ip": "49.37.10.20", "true-client-ip": "2.2.2.2", "x-forwarded-for": "3.3.3.3, 4.4.4.4"}
    assert routes._client_ip(_req(spoof, peer="3.3.3.3")) == "49.37.10.20"
    assert routes._client_ip(_req(spoof, peer="10.209.23.112")) == "49.37.10.20"


def test_true_client_ip_and_forwarded_for_are_never_read():
    assert routes._client_ip(_req({"true-client-ip": "2.2.2.2"}, peer="10.0.0.9")) == "10.0.0.9"
    assert routes._client_ip(_req({"x-forwarded-for": "3.3.3.3, 4.4.4.4"}, peer="10.0.0.9")) == "10.0.0.9"


def test_garbage_cloudflare_header_falls_back_to_the_peer():
    assert routes._client_ip(_req({"cf-connecting-ip": "not-an-ip"}, peer="10.0.0.9")) == "10.0.0.9"


def test_ipv6_cloudflare_ip_is_normalised():
    assert routes._client_ip(_req({"cf-connecting-ip": "2001:DB8::0007"})) == "2001:db8::7"


def test_trusted_proxy_list_limits_who_may_send_the_cloudflare_header(monkeypatch):
    monkeypatch.setattr(routes.env_settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    routes._trusted_proxies.cache_clear()
    cf = {"cf-connecting-ip": "1.1.1.1"}
    assert routes._client_ip(_req(cf, peer="10.20.30.40")) == "1.1.1.1"
    assert routes._client_ip(_req(cf, peer="198.51.100.20")) == "198.51.100.20"


def test_empty_trusted_proxy_list_means_never_believe_the_header(monkeypatch):
    monkeypatch.setattr(routes.env_settings, "trusted_proxy_cidrs", "")
    routes._trusted_proxies.cache_clear()
    assert routes._client_ip(_req({"cf-connecting-ip": "1.1.1.1"}, peer="10.0.0.1")) == "10.0.0.1"


def test_no_client_at_all():
    assert routes._client_ip(_req({}, peer=None)) == "unknown"


def test_sliding_window_drops_keys_whose_hits_have_expired(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(routes.time, "monotonic", lambda: clock[0])
    limiter = routes._SlidingWindow(5, 60)
    for i in range(500):
        limiter.allow(f"ip-{i}")
    assert len(limiter) == 500
    clock[0] += 61
    limiter.allow("fresh")
    assert len(limiter) == 1


def test_sliding_window_keeps_keys_still_inside_the_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(routes.time, "monotonic", lambda: clock[0])
    limiter = routes._SlidingWindow(1, 60)
    assert limiter.allow("a") is True
    clock[0] += 30
    limiter.allow("b")
    clock[0] += 31  # "a" is 61s old, "b" 31s
    limiter.allow("c")
    assert len(limiter) == 2
    assert limiter.allow("b") is False  # b's hit still counts

"""The per-IP rate-limit key (_client_ip) and the in-process limiter (_SlidingWindow).

Forwarded headers are only believed when the TCP peer is a trusted proxy (Render's load
balancer, on its private network). A caller that reaches the app directly can type any
header it likes, so from it only the real socket address counts.
"""
from starlette.requests import Request

from app.routes import auto_messages as routes


def _req(headers: dict, peer: str = "10.0.0.1") -> Request:
    return Request({
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 443),
    })


SPOOF = {"cf-connecting-ip": "1.1.1.1", "true-client-ip": "2.2.2.2", "x-forwarded-for": "3.3.3.3, 4.4.4.4"}


def test_spoofed_headers_from_a_public_peer_are_ignored():
    assert routes._client_ip(_req(SPOOF, peer="198.51.100.20")) == "198.51.100.20"


def test_spoofed_headers_from_a_public_ipv6_peer_are_ignored():
    assert routes._client_ip(_req(SPOOF, peer="2001:db8::7")) == "2001:db8::7"


def test_each_new_spoofed_value_from_one_attacker_lands_in_one_bucket():
    limiter = routes._SlidingWindow(3, 60)
    allowed = [limiter.allow(routes._client_ip(_req({"cf-connecting-ip": f"9.9.9.{i}"}, peer="198.51.100.20")))
               for i in range(10)]
    assert allowed == [True, True, True] + [False] * 7


def test_cloudflare_client_ip_is_used_when_the_peer_is_render_internal():
    assert routes._client_ip(_req(SPOOF, peer="10.20.30.40")) == "1.1.1.1"


def test_true_client_ip_alone_is_not_believed_even_from_a_trusted_peer():
    # Cloudflare always sets CF-Connecting-IP; True-Client-IP is only set on some plans, so a
    # client-typed one can pass through untouched.
    assert routes._client_ip(_req({"true-client-ip": "2.2.2.2"}, peer="10.0.0.9")) == "10.0.0.9"


def test_forwarded_for_from_a_trusted_peer_uses_the_rightmost_entry():
    assert routes._client_ip(_req({"x-forwarded-for": "3.3.3.3, 4.4.4.4"}, peer="10.0.0.9")) == "4.4.4.4"


def test_trusted_proxy_list_can_be_set_by_env(monkeypatch):
    monkeypatch.setattr(routes.env_settings, "trusted_proxy_cidrs", "203.0.113.0/24")
    routes._trusted_proxies.cache_clear()
    try:
        assert routes._client_ip(_req(SPOOF, peer="203.0.113.5")) == "1.1.1.1"
        assert routes._client_ip(_req(SPOOF, peer="10.0.0.1")) == "10.0.0.1"
    finally:
        routes._trusted_proxies.cache_clear()


def test_garbage_header_values_fall_back_to_the_peer():
    assert routes._client_ip(_req({"cf-connecting-ip": "not-an-ip"}, peer="10.0.0.9")) == "10.0.0.9"


def test_no_client_at_all():
    req = Request({"type": "http", "headers": [], "client": None})
    assert routes._client_ip(req) == "unknown"


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

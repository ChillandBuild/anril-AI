"""The app-wide slowapi limit (200/minute).

Key: a logged-in user whose token is already proven (in the verified-token cache, or passing
the local HS256 signature check) gets their own bucket, "user:<id>". Anything else keys on
_client_ip (CF-Connecting-IP). Why: the dashboard's SSR calls all leave Vercel from a few
addresses, so keyed on IP every user shared one 200/minute. A made-up token must never buy
a fresh bucket, so the token is never trusted without that proof, and no network call is made.

On Render, uvicorn replaces request.client with the caller-typed X-Forwarded-For entry, so
the tests hand each request a different rewritten client and the Cloudflare-set header.
"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.main as main
from app.dependencies import auth

SECRET = "test-jwt-secret-for-rate-limit-key-0123456789"
VERCEL_IP = "76.76.21.21"


def _token(sub: str, *, secret: str = SECRET, exp_in: int = 3600, **extra) -> str:
    claims = {"sub": sub, "aud": "authenticated", "exp": int(time.time()) + exp_in, **extra}
    return jwt.encode(claims, secret, algorithm="HS256")


def _req(headers: dict) -> Request:
    return Request({
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("9.9.9.9", 0),
    })


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(auth.settings, "supabase_jwt_secret", SECRET)
    auth._TOKEN_CACHE.clear()
    main.limiter.reset()
    main._user_keyed_per_ip.reset()
    yield
    main._user_keyed_per_ip.reset()
    auth._TOKEN_CACHE.clear()
    main.limiter.reset()


def _key(token: str | None = None, ip: str = VERCEL_IP) -> str:
    headers = {"cf-connecting-ip": ip}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return main._rate_limit_key(_req(headers))


def test_a_signed_token_gets_its_own_user_bucket():
    assert _key(_token("user-priya")) == "user:user-priya"


def test_two_users_from_one_vercel_ip_get_two_buckets():
    assert _key(_token("user-priya")) != _key(_token("user-ravi"))


def test_no_token_keys_on_the_cloudflare_ip():
    assert _key() == f"ip:{VERCEL_IP}"


@pytest.mark.parametrize("token", [
    "not-a-jwt",
    "",
    _token("user-anyone", secret="attacker-made-this-up-0123456789abcdef"),  # wrong signature
    _token("user-priya", exp_in=-60),  # expired
    _token("user-claude", client_id="claude-app"),  # OAuth client token, refused by get_current_user
    jwt.encode({"sub": "user-x", "aud": "authenticated"}, None, algorithm="none"),  # unsigned
])
def test_tokens_without_proof_fall_back_to_the_ip(token):
    assert _key(token) == f"ip:{VERCEL_IP}"


def test_wrong_audience_falls_back_to_the_ip():
    assert _key(_token("user-priya", aud="something-else")) == f"ip:{VERCEL_IP}"


def test_non_bearer_scheme_is_ignored():
    headers = {"cf-connecting-ip": VERCEL_IP, "authorization": f"Basic {_token('user-priya')}"}
    assert main._rate_limit_key(_req(headers)) == f"ip:{VERCEL_IP}"


def test_without_the_local_secret_only_cached_tokens_count(monkeypatch):
    monkeypatch.setattr(auth.settings, "supabase_jwt_secret", None)
    token = _token("user-priya")
    assert _key(token) == f"ip:{VERCEL_IP}"  # not proven yet: IP bucket
    auth._set_cached_user(token, {"user_id": "user-priya", "email": ""})  # what get_current_user does after a remote check
    assert _key(token) == "user:user-priya"


def test_dashboard_ssr_for_two_users_from_one_vercel_ip_is_not_throttled():
    # 150 SSR calls each for two users, all from one Vercel address: keyed on IP this
    # was 300 against one 200/minute bucket.
    priya, ravi = _token("user-priya"), _token("user-ravi")
    codes = []
    for i in range(150):
        for token in (priya, ravi):
            codes.append(
                TestClient(main.app, client=(VERCEL_IP, 0)).get(
                    "/health", headers={"cf-connecting-ip": VERCEL_IP, "authorization": f"Bearer {token}"}
                ).status_code
            )
    assert codes == [200] * 300


def test_made_up_tokens_do_not_buy_fresh_buckets():
    codes = [
        TestClient(main.app, client=(f"9.9.{i // 250}.{i % 250}", 0)).get(
            "/health",
            headers={"cf-connecting-ip": "49.37.10.20",
                     "authorization": f"Bearer {_token(f'fake-{i}', secret='attacker-secret-0123456789abcdef')}"},
        ).status_code
        for i in range(201)
    ]
    assert codes[:200] == [200] * 200 and codes[200] == 429


def test_many_accounts_from_one_ip_fall_back_to_the_ip_bucket(monkeypatch):
    monkeypatch.setattr(main, "_user_keyed_per_ip", main._SlidingWindow(3, 60))
    keys = [_key(_token(f"account-{i}"), ip="49.37.10.20") for i in range(5)]
    assert keys[:3] == ["user:account-0", "user:account-1", "user:account-2"]
    assert keys[3:] == ["ip:49.37.10.20", "ip:49.37.10.20"]
    assert _key(_token("user-priya"), ip="1.2.3.4") == "user:user-priya"  # other addresses unaffected


def test_oversized_or_non_jwt_tokens_skip_the_signature_check():
    big = _token("user-priya", pad="x" * 5000)
    assert _key(big) == f"ip:{VERCEL_IP}"
    assert auth.rate_limit_user_id("a.b") is None


def test_global_limit_uses_the_rate_limit_key():
    assert main.limiter._key_func is main._rate_limit_key

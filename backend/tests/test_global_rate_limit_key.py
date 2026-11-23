"""The app-wide slowapi limit (200/minute) must key on the same client IP as the per-route
limits. On Render, uvicorn replaces request.client with the caller-typed leftmost
X-Forwarded-For entry, so keying on request.client.host (slowapi's get_remote_address)
gave every spoofed value a fresh 200. Here each request "arrives" with a different
rewritten client, as uvicorn hands it over, and the same Cloudflare-set CF-Connecting-IP."""
from fastapi.testclient import TestClient

import app.main as main
from app.routes.auto_messages import _client_ip


def test_global_limit_keys_on_the_cloudflare_ip_not_the_rewritten_client():
    main.limiter.reset()
    try:
        codes = [
            TestClient(main.app, client=(f"9.9.{i // 250}.{i % 250}", 0))
            .get("/health", headers={"cf-connecting-ip": "49.37.10.20"}).status_code
            for i in range(201)
        ]
        assert codes[:200] == [200] * 200
        assert codes[200] == 429
    finally:
        main.limiter.reset()


def test_global_limit_uses_the_shared_client_ip_function():
    assert main.limiter._key_func is _client_ip

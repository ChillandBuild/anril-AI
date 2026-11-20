"""Anril AI (client connector): its own address, and the dashboard routes behind the consent
screen and Settings → Anril AI. Spec: docs/specs/anril-client-mcp.md."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from mcp.server.auth.provider import AccessToken
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient as StarletteClient

from app.admin_mcp.server import McpGateway
from app.client_mcp import auth as client_auth
from app.client_mcp import server as client_server
from app.client_mcp import wrapper
from app.config import settings
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import require_owner
from app.main import app
from app.routes import claude_connector
from app.services import client_claude
from tests.test_client_mcp_core import A, ADMIN_APP, APP, B, two_clients

BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _settings():
    with patch.object(settings, "supabase_url", "https://proj.supabase.co"), \
         patch.object(settings, "mcp_oauth_client_id", ADMIN_APP), \
         patch.object(settings, "mcp_client_oauth_client_ids", APP), \
         patch.object(settings, "mcp_client_enabled", True):
        yield
    app.dependency_overrides.clear()


# ── the connector's own address ───────────────────────────────────────────────

def _site():
    """The API (one route) with the client gateway in front, as main.py builds it."""
    api = Starlette(routes=[Route("/api/ping", lambda r: PlainTextResponse("api")), Route("/mcp", lambda r: PlainTextResponse("admin door"))])
    return McpGateway(
        api, mcp_app=client_server.build_app(client_server.build_server()),
        mcp_path=client_server.MCP_PATH, well_known_path=client_server.WELL_KNOWN_PATH,
    )


def test_client_address_asks_for_sign_in_and_lists_tools_only_to_a_verified_owner():
    # The MCP app on its own: its lifespan runs the session manager (main.py's lifespan does it live).
    mcp_app = client_server.build_app(client_server.build_server())
    with StarletteClient(mcp_app, base_url="http://localhost:8000") as client:
        r = client.post("/client/mcp", json=BODY, headers=HEADERS)
        assert r.status_code == 401 and "resource_metadata=" in r.headers["www-authenticate"]
        meta = client.get("/.well-known/oauth-protected-resource/client/mcp").json()
        assert meta["resource"].endswith("/client/mcp")
        owner = AccessToken(token="t", client_id=APP, scopes=[], subject="owner-a", claims={"tenant_id": A, "connection_id": "c"})
        with patch.object(client_auth, "verify", return_value=owner):
            ok = client.post("/client/mcp", json=BODY, headers={**HEADERS, "Authorization": "Bearer t"})
        assert ok.status_code == 200
        assert {t["name"] for t in ok.json()["result"]["tools"]} == set(wrapper.APPROVED_TOOLS)


def test_the_client_gateway_leaves_every_other_address_alone():
    with StarletteClient(_site(), base_url="http://localhost:8000") as client:
        assert client.get("/api/ping").text == "api"
        assert client.get("/mcp").text == "admin door"  # the admin address is not this gateway's


# ── dashboard routes ──────────────────────────────────────────────────────────

def _api(db, user_id="owner-a"):
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "email": "x@example.com"}
    app.dependency_overrides[require_owner] = lambda: {"tenant_id": A, "role": "owner", "user_id": user_id}
    return patch.object(claude_connector, "get_supabase", return_value=db), TestClient(app)


def test_consent_screen_is_told_which_connector_an_app_is():
    patcher, client = _api(two_clients())
    with patcher:
        assert client.get("/api/v1/claude/consent", params={"client_id": ADMIN_APP}).json() == {"kind": "admin"}
        assert client.get("/api/v1/claude/consent", params={"client_id": "look-alike"}).json() == {"kind": "unknown"}
        mine = client.get("/api/v1/claude/consent", params={"client_id": APP}).json()
    assert mine == {"kind": "client", "can_allow": True, "business": "AstroTamil", "daily_cap": 500, "connected": True}


def test_staff_and_switched_off_clients_are_told_why_they_cannot_allow():
    patcher, client = _api(two_clients(), user_id="staff-a")
    with patcher:
        out = client.get("/api/v1/claude/consent", params={"client_id": APP}).json()
        refused = client.post("/api/v1/claude/allow", json={"client_id": APP})
    assert out == {"kind": "client", "can_allow": False, "why": client_claude.REFUSALS["not_owner"]}
    assert refused.status_code == 403


def test_allow_creates_the_owners_connection_for_an_approved_app_only():
    db = two_clients()
    db.tables["tenant_mcp_connections"].clear()
    patcher, client = _api(db)
    with patcher:
        assert client.post("/api/v1/claude/allow", json={"client_id": "look-alike"}).status_code == 400
        assert client.post("/api/v1/claude/allow", json={"client_id": ADMIN_APP}).status_code == 400
        assert db.rows("tenant_mcp_connections") == []
        ok = client.post("/api/v1/claude/allow", json={"client_id": APP, "label": "Claude"})
    assert ok.status_code == 200
    row = db.rows("tenant_mcp_connections")[0]
    assert (row["tenant_id"], row["user_id"], row["client_id"], row["status"]) == (A, "owner-a", APP, "active")
    assert db.rows("app_audit_logs")[0]["action"] == "claude.connection.allow"


def test_settings_page_shows_only_this_clients_connector_and_actions():
    db = two_clients()
    db.add("tenant_mcp_connections", id="conn-b", tenant_id=B, user_id="owner-b", client_id=APP, status="active")
    db.add("app_audit_logs", tenant_id=A, action="claude.send", target_id="send_reply", metadata={"stage": "started"})
    db.add("app_audit_logs", tenant_id=A, action="claude.send", target_id="send_reply", metadata={"stage": "done", "ok": True, "arguments": {"lead_id": "L1"}})
    db.add("app_audit_logs", tenant_id=B, action="claude.send", target_id="send_broadcast", metadata={"stage": "done", "ok": True})
    db.add("app_audit_logs", tenant_id=A, action="team.invite", target_id="x", metadata={})
    client_claude.reserve_sends(db, A, 3)
    patcher, client = _api(db)
    with patcher:
        out = client.get("/api/v1/claude").json()
    assert out["available"] is True and out["mcp_url"].endswith("/client/mcp") and out["oauth_client_id"] == APP
    assert [c["id"] for c in out["connections"]] == ["conn-a"]
    assert (out["daily_cap"], out["sent_today"]) == (500, 3)
    assert [(r["tool"], r["ok"]) for r in out["recent"]] == [("send_reply", True)]


def test_the_owner_can_switch_it_off_and_change_the_cap_within_bounds():
    db = two_clients()
    patcher, client = _api(db)
    with patcher:
        assert client.put("/api/v1/claude/cap", json={"daily_cap": 50}).json() == {"daily_cap": 50}
        assert client.put("/api/v1/claude/cap", json={"daily_cap": -1}).status_code == 422
        assert client.put("/api/v1/claude/cap", json={"daily_cap": client_claude.MAX_DAILY_CAP + 1}).status_code == 422
        assert client.post("/api/v1/claude/revoke").json()["revoked"] == 1
    assert client_claude.daily_cap(db, A) == 50
    assert client_claude.find_active(db, A, "owner-a", APP) is None
    assert [r["action"] for r in db.rows("app_audit_logs")] == ["claude.cap.change", "claude.connection.revoke"]


def test_these_routes_need_a_login():
    client = TestClient(app)
    for method, path in (("get", "/api/v1/claude"), ("get", "/api/v1/claude/consent?client_id=x"),
                         ("post", "/api/v1/claude/allow"), ("post", "/api/v1/claude/revoke"), ("put", "/api/v1/claude/cap")):
        assert getattr(client, method)(path).status_code in (401, 403), path

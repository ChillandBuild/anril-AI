"""Anril AI (client connector): who gets in, the owner's off switch, the daily sending cap, and
the wrapper's guards. Spec: docs/specs/anril-client-mcp.md."""
import asyncio
import time
from unittest.mock import patch

import jwt
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.client_mcp import auth, wrapper
from app.config import settings
from app.db import supabase as supabase_db
from app.services import client_claude
from tests.fake_supabase import FakeSupabase

SECRET = "test-secret-test-secret-test-secret-123"
ISS = "https://proj.supabase.co/auth/v1"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
APP = "claude-client-app"
ADMIN_APP = "claude-admin-app"


def make_token(**overrides) -> str:
    claims = {
        "sub": "owner-a", "aud": "authenticated", "iss": ISS, "email": "owner@a.example",
        "exp": int(time.time()) + 600, "client_id": APP,
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, SECRET, algorithm="HS256")


def reserve_rpcs(db: FakeSupabase) -> None:
    """Python stand-ins for the two SQL functions in migration 303."""
    days = db.tables.setdefault("claude_send_days", [])

    def _day(p):
        return next((r for r in days if r["tenant_id"] == p["p_tenant_id"] and r["day"] == p["p_day"]), None)

    def reserve(p):
        row = _day(p)
        if row is None:
            row = {"tenant_id": p["p_tenant_id"], "day": p["p_day"], "sent": 0}
            days.append(row)
        if row["sent"] + p["p_count"] > p["p_cap"]:
            return None
        row["sent"] += p["p_count"]
        return row["sent"]

    def release(p):
        row = _day(p)
        if row is None:
            return None
        row["sent"] = max(row["sent"] - max(p["p_count"], 0), 0)
        return row["sent"]

    db.rpc_handlers["claude_reserve_sends"] = reserve
    db.rpc_handlers["claude_release_sends"] = release


def two_clients() -> FakeSupabase:
    """Client A (connector on, owner-a connected) and client B (another business)."""
    db = FakeSupabase()
    db.add("tenants", id=A, name="AstroTamil", status="active", enabled_features=["whatsapp", "claude"])
    db.add("tenants", id=B, name="Other Shop", status="active", enabled_features=["whatsapp", "claude"])
    db.add("tenant_users", tenant_id=A, user_id="owner-a", role="owner")
    db.add("tenant_users", tenant_id=B, user_id="owner-b", role="owner")
    db.add("tenant_users", tenant_id=A, user_id="staff-a", role="caller")
    db.add("tenant_mcp_connections", id="conn-a", tenant_id=A, user_id="owner-a", client_id=APP, status="active")
    reserve_rpcs(db)
    return db


@pytest.fixture(autouse=True)
def _settings():
    with patch.object(settings, "supabase_jwt_secret", SECRET), \
         patch.object(settings, "supabase_url", "https://proj.supabase.co"), \
         patch.object(settings, "mcp_oauth_client_id", ADMIN_APP), \
         patch.object(settings, "mcp_client_oauth_client_ids", f"{APP}, {ADMIN_APP}"):
        wrapper._calls.clear()
        yield


def _verify(db, **claims):
    with patch.object(auth, "get_supabase", return_value=db):
        return auth.verify(make_token(**claims))


# ── who gets in ───────────────────────────────────────────────────────────────

def test_owner_with_an_active_connection_gets_in_as_their_own_client():
    token = _verify(two_clients())
    assert token.subject == "owner-a"
    assert token.claims["tenant_id"] == A and token.claims["connection_id"] == "conn-a"


def test_the_admin_app_is_never_a_client_app_even_if_listed():
    assert client_claude.approved_client_ids() == frozenset({APP})
    assert _verify(two_clients(), client_id=ADMIN_APP) is None


@pytest.mark.parametrize("claims", [
    {"client_id": None},              # a normal dashboard login
    {"client_id": "look-alike-app"},  # an app nobody approved
    {"sub": "staff-a"},               # staff, not the owner
    {"sub": "owner-b"},               # another client's owner has no connection here
    {"sub": "stranger"},              # belongs to no client
    {"exp": int(time.time()) - 5},    # expired
])
def test_everyone_else_is_refused(claims):
    assert _verify(two_clients(), **claims) is None


def test_refused_when_the_operator_has_not_switched_it_on():
    db = two_clients()
    db.rows("tenants")[0]["enabled_features"] = ["whatsapp"]
    assert _verify(db) is None
    assert client_claude.owner_seat(db, "owner-a") == (None, "not_enabled")


def test_refused_when_suspended_or_in_two_clients_or_switched_off_by_the_owner():
    db = two_clients()
    db.rows("tenants")[0]["status"] = "suspended"
    assert _verify(db) is None

    db = two_clients()
    db.add("tenant_users", tenant_id=B, user_id="owner-a", role="owner")
    assert client_claude.owner_seat(db, "owner-a") == (None, "many_clients")
    assert _verify(db) is None

    db = two_clients()
    assert client_claude.revoke_all(db, A) == 1
    assert _verify(db) is None


def test_revoking_one_client_leaves_the_other_connected():
    db = two_clients()
    db.add("tenant_mcp_connections", id="conn-b", tenant_id=B, user_id="owner-b", client_id=APP, status="active")
    client_claude.revoke_all(db, A)
    assert client_claude.find_active(db, B, "owner-b", APP)["id"] == "conn-b"


# ── the daily cap ─────────────────────────────────────────────────────────────

def test_cap_defaults_to_500_and_the_owner_can_change_it_within_bounds():
    db = two_clients()
    assert client_claude.daily_cap(db, A) == 500
    assert client_claude.set_daily_cap(db, A, 50) == 50 and client_claude.daily_cap(db, A) == 50
    assert client_claude.set_daily_cap(db, A, 10**9) == client_claude.MAX_DAILY_CAP
    assert client_claude.daily_cap(db, B) == 500  # one client's cap is not another's


def test_sends_are_booked_until_the_cap_and_then_refused_with_nothing_booked():
    db = two_clients()
    client_claude.set_daily_cap(db, A, 10)
    assert client_claude.reserve_sends(db, A, 7) == 7
    with pytest.raises(client_claude.CapReached) as caught:
        client_claude.reserve_sends(db, A, 4)
    assert (caught.value.cap, caught.value.sent, caught.value.wanted) == (10, 7, 4)
    assert client_claude.sent_today(db, A) == 7
    assert client_claude.reserve_sends(db, A, 3) == 10
    client_claude.release_sends(db, A, 2)
    assert client_claude.sent_today(db, A) == 8
    assert client_claude.sent_today(db, B) == 0


# ── the wrapper ───────────────────────────────────────────────────────────────

WHO = {"user_id": "owner-a", "email": "o@a", "client_id": APP, "connection_id": "conn-a", "tenant_id": A, "tenant_name": "AstroTamil"}


def _spec(name: str, fn):
    """Register `fn` under an approved name for one test, then put the real tool back."""
    real = wrapper.REGISTRY.pop(name, None)
    fn.__name__ = name
    wrapper.client_tool(title="t")(fn)
    spec = wrapper.REGISTRY.pop(name)
    if real is not None:
        wrapper.REGISTRY[name] = real
    return spec


def _run(spec, db, **kwargs):
    with patch.object(auth, "current_seat", return_value=WHO), patch.object(wrapper, "get_supabase", return_value=db):
        return asyncio.run(spec.run(**kwargs))


def test_a_tool_must_be_on_the_approved_list_and_plain():
    def not_listed():
        return 1

    with pytest.raises(RuntimeError, match="APPROVED_TOOLS"):
        wrapper.client_tool(title="x")(not_listed)

    async def my_business():
        return 1

    real = wrapper.REGISTRY.pop("my_business", None)
    try:
        with pytest.raises(RuntimeError, match="plain function"):
            wrapper.client_tool(title="x")(my_business)
    finally:
        if real is not None:
            wrapper.REGISTRY["my_business"] = real


def test_a_read_runs_locked_as_the_signed_in_client_and_leaves_one_audit_row():
    db = two_clients()
    seen = {}

    def tool():
        seen["tenant"], seen["locked"] = wrapper.tenant_id(), supabase_db.read_only.get()
        return {"n": 1}

    out = _run(_spec("my_business", tool), db)
    assert out["data"] == {"n": 1} and "Anril" in out["source"]
    assert seen == {"tenant": A, "locked": True}
    rows = db.rows("app_audit_logs")
    assert [(r["tenant_id"], r["action"], r["metadata"]["stage"]) for r in rows] == [(A, "claude.read", "done")]
    assert supabase_db.read_only.get() is False


def test_a_send_writes_its_audit_row_before_acting_and_is_not_locked():
    db = two_clients()
    seen = {}

    def tool(lead_id: str = ""):
        seen["rows_before"] = [r["metadata"]["stage"] for r in db.rows("app_audit_logs")]
        seen["locked"] = supabase_db.read_only.get()
        return {"sent": True}

    _run(_spec("send_reply", tool), db, lead_id="L1")
    assert seen == {"rows_before": ["started"], "locked": False}
    assert [(r["action"], r["metadata"]["stage"], r["metadata"]["ok"]) for r in db.rows("app_audit_logs")] == [
        ("claude.send", "started", None), ("claude.send", "done", True),
    ]


def test_no_audit_row_means_no_action_and_no_answer():
    class Broken(FakeSupabase):
        def table(self, name):
            if name == "app_audit_logs":
                raise RuntimeError("audit table down")
            return super().table(name)

    ran = []
    with pytest.raises(ToolError, match="nothing was done"):
        _run(_spec("send_reply", lambda: ran.append(1)), Broken())
    assert ran == []
    with pytest.raises(ToolError, match="withheld"):
        _run(_spec("my_business", lambda: {"secret": 1}), Broken())


def test_a_failed_action_is_recorded_as_failed():
    db = two_clients()

    def tool():
        raise ToolError("Not sent: nope")

    with pytest.raises(ToolError, match="nope"):
        _run(_spec("send_reply", tool), db)
    assert [r["metadata"]["stage"] for r in db.rows("app_audit_logs")] == ["started", "failed"]


def test_a_crash_inside_a_tool_never_shows_the_raw_error_to_claude():
    db = two_clients()

    def tool():
        raise RuntimeError('relation "leads" at db.internal:5432 password=hunter2')

    for name, hint in (("my_business", "Try again"), ("send_reply", "may or may not have gone through")):
        with pytest.raises(ToolError, match=hint) as caught:
            _run(_spec(name, tool), db)
        assert "hunter2" not in str(caught.value) and "leads" not in str(caught.value)


def test_the_audit_row_keeps_a_cut_down_copy_of_what_was_asked():
    kept = wrapper._audit_arguments({
        "search": "+91 90000 04471", "text": "x" * 500, "lead_ids": [str(n) for n in range(40)], "segment": "A",
    })
    assert kept["search"] == "phone ending 4471" and kept["segment"] == "A"
    assert len(kept["text"]) == wrapper.MAX_AUDIT_TEXT + 1
    assert len(kept["lead_ids"]) == wrapper.MAX_AUDIT_LIST + 1 and kept["lead_ids"][-1] == "… 30 more"


def test_one_client_is_slowed_down_after_60_calls_a_minute_and_others_are_not():
    db = two_clients()
    spec = _spec("my_business", lambda: 1)
    with patch.object(wrapper, "CALLS_PER_MINUTE", 3):
        for _ in range(3):
            _run(spec, db)
        with pytest.raises(ToolError, match="Too many requests"):
            _run(spec, db)
        other = {**WHO, "tenant_id": B}
        with patch.object(auth, "current_seat", return_value=other), patch.object(wrapper, "get_supabase", return_value=db):
            assert asyncio.run(spec.run())["data"] == 1


def test_outside_a_call_there_is_no_client():
    with pytest.raises(ToolError, match="Not signed in"):
        wrapper.tenant_id()


# ── every refusal says why in the logs ────────────────────────────────────────

def test_a_token_without_client_id_logs_why(caplog):
    with caplog.at_level("INFO", logger="app.client_mcp.auth"):
        assert _verify(two_clients(), client_id=None) is None
    assert "no client_id" in caplog.text


def test_no_active_connection_logs_why_and_never_the_token(caplog):
    db = two_clients()
    db.rows("tenant_mcp_connections")[0]["status"] = "revoked"
    token = make_token()
    with patch.object(auth, "get_supabase", return_value=db), caplog.at_level("INFO", logger="app.client_mcp.auth"):
        assert auth.verify(token) is None
    assert "no active connection" in caplog.text
    assert token not in caplog.text

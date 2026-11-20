"""Claude Access (read-only admin MCP): who gets in, the off switch, the read-only guard, the
audit row, and the Operator endpoints behind the Claude Access page.
Spec: docs/specs/anril-admin-mcp.md sections 2 and 4."""
import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient as StarletteClient

from app.admin_mcp import auth, wrapper
from app.admin_mcp.server import build_app, build_server
from app.config import settings
from app.db import supabase as supabase_db
from app.dependencies import auth as api_auth
from app.dependencies.system_admin import get_system_admin
from app.main import app
from app.services import mcp_connections

SECRET = "test-secret-test-secret-test-secret-123"
ISS = "https://proj.supabase.co/auth/v1"


def make_token(**overrides) -> str:
    claims = {
        "sub": "user-1", "aud": "authenticated", "iss": ISS, "email": "p@example.com",
        "exp": int(time.time()) + 600, "client_id": "claude-client",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def admin_db(is_admin: bool = True) -> MagicMock:
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"user_id": "user-1"}] if is_admin else []
    )
    return db


class VerifyTokenTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(settings, "supabase_jwt_secret", SECRET),
            patch.object(settings, "supabase_url", "https://proj.supabase.co"),
            patch.object(settings, "mcp_oauth_client_id", "claude-client"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _verify(self, token, *, is_admin=True, connection={"id": "conn-1"}):
        with patch.object(auth, "get_supabase", return_value=admin_db(is_admin)), \
             patch.object(mcp_connections, "find_active", return_value=connection) as find:
            return auth.verify(token), find

    def test_admin_with_active_connection_gets_in(self):
        result, find = self._verify(make_token())
        self.assertEqual(result.subject, "user-1")
        self.assertEqual(result.client_id, "claude-client")
        self.assertEqual(result.claims["connection_id"], "conn-1")
        self.assertEqual(find.call_args.args[1:], ("user-1", "claude-client"))

    def test_normal_dashboard_login_is_refused(self):
        result, _ = self._verify(make_token(client_id=None))
        self.assertIsNone(result)

    def test_non_admin_is_refused(self):
        result, _ = self._verify(make_token(), is_admin=False)
        self.assertIsNone(result)

    def test_switched_off_connection_is_refused(self):
        result, _ = self._verify(make_token(), connection=None)
        self.assertIsNone(result)

    def test_any_other_oauth_client_is_refused(self):
        ok, _ = self._verify(make_token())
        other, find = self._verify(make_token(client_id="someone-else"))
        self.assertIsNotNone(ok)
        self.assertIsNone(other)
        find.assert_not_called()

    def test_nobody_gets_in_when_the_claude_client_id_is_not_configured(self):
        # Without it, any app an admin was tricked into approving would be let in.
        for unset in (None, ""):
            with patch.object(settings, "mcp_oauth_client_id", unset):
                result, find = self._verify(make_token())
            self.assertIsNone(result)
            find.assert_not_called()

    def test_expired_wrong_issuer_wrong_audience_and_bad_signature_are_refused(self):
        bad = [
            make_token(exp=int(time.time()) - 5),
            make_token(iss="https://evil.example/auth/v1"),
            make_token(aud="something-else"),
            jwt.encode({"sub": "user-1", "aud": "authenticated", "iss": ISS, "client_id": "claude-client",
                        "exp": int(time.time()) + 600}, "another-secret-another-secret-12345", algorithm="HS256"),
            "not-a-token",
        ]
        for token in bad:
            result, find = self._verify(token)
            self.assertIsNone(result)
            find.assert_not_called()

    def test_unknown_algorithm_never_reaches_the_remote_fallback_as_valid(self):
        # alg "none" tokens: PyJWT cannot produce a header we accept, and Supabase says no.
        token = jwt.encode({"sub": "user-1", "client_id": "c"}, key="", algorithm="none")
        db = admin_db()
        db.auth.get_user.side_effect = Exception("invalid")
        with patch.object(auth, "get_supabase", return_value=db):
            self.assertIsNone(auth.verify(token))


class NormalApiRefusesClaudeTokenTests(unittest.TestCase):
    """The token Claude holds must not double as a full login for the rest of the API."""

    def _creds(self, token):
        return MagicMock(credentials=token)

    def test_refused_when_mcp_is_on(self):
        with patch.object(settings, "mcp_enabled", True), patch.object(settings, "supabase_jwt_secret", SECRET):
            with self.assertRaises(HTTPException) as ctx:
                api_auth.get_current_user(self._creds(make_token()))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_normal_login_still_works_when_mcp_is_on(self):
        with patch.object(settings, "mcp_enabled", True), patch.object(settings, "supabase_jwt_secret", SECRET):
            user = api_auth.get_current_user(self._creds(make_token(client_id=None)))
        self.assertEqual(user["user_id"], "user-1")

    def test_still_refused_when_mcp_is_off(self):
        # Turning the MCP off must not turn Claude's token into a full Operator login.
        with patch.object(settings, "mcp_enabled", False), patch.object(settings, "supabase_jwt_secret", SECRET):
            with self.assertRaises(HTTPException) as ctx:
                api_auth.get_current_user(self._creds(make_token()))
            user = api_auth.get_current_user(self._creds(make_token(client_id=None)))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(user["user_id"], "user-1")


class ReadOnlyGuardTests(unittest.TestCase):
    def setUp(self):
        self.raw = MagicMock()
        self.p = patch.object(supabase_db, "_client", self.raw)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_writes_are_refused_and_reads_pass_in_read_only_mode(self):
        token = supabase_db.read_only.set(True)
        try:
            db = supabase_db.get_supabase()
            db.table("leads").select("id").eq("id", "1").execute()
            for method in ("insert", "upsert", "update", "delete"):
                with self.assertRaises(supabase_db.ReadOnlyViolation):
                    getattr(db.table("leads"), method)
                with self.assertRaises(supabase_db.ReadOnlyViolation):
                    getattr(db.from_("leads"), method)
            with self.assertRaises(supabase_db.ReadOnlyViolation):
                db.rpc("anything_else", {})
            db.rpc("distinct_token_usage_pairs", {})
        finally:
            supabase_db.read_only.reset(token)
        self.raw.table.return_value.select.assert_called()
        self.raw.table.return_value.insert.assert_not_called()

    def test_every_other_door_on_the_client_is_shut_in_read_only_mode(self):
        token = supabase_db.read_only.set(True)
        try:
            db = supabase_db.get_supabase()
            for door in ("postgrest", "schema", "storage", "functions", "realtime", "anything_new"):
                with self.assertRaises(supabase_db.ReadOnlyViolation, msg=door):
                    getattr(db, door)
            for write in ("create_user", "update_user_by_id", "delete_user", "invite_user_by_email"):
                with self.assertRaises(supabase_db.ReadOnlyViolation, msg=write):
                    getattr(db.auth.admin, write)
            with self.assertRaises(supabase_db.ReadOnlyViolation):
                db.auth.sign_out
            db.auth.admin.get_user_by_id("user-1")  # the lookup read handlers use
        finally:
            supabase_db.read_only.reset(token)
        self.raw.auth.admin.get_user_by_id.assert_called_once_with("user-1")
        self.raw.auth.admin.create_user.assert_not_called()

    def test_outside_read_only_mode_the_real_client_is_returned(self):
        self.assertIs(supabase_db.get_supabase(), self.raw)


CALLER = {"user_id": "user-1", "email": "p@example.com", "client_id": "claude-client", "connection_id": "conn-1"}


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(wrapper.REGISTRY)
        self.audit = patch.object(wrapper, "write_audit_event")
        self.touch = patch.object(mcp_connections, "touch")
        self.caller = patch.object(wrapper, "current_caller", return_value=CALLER)
        self.db = patch.object(wrapper, "get_supabase", return_value=MagicMock())
        self.audit_mock, self.touch_mock = self.audit.start(), self.touch.start()
        self.caller.start()
        self.db.start()

    def tearDown(self):
        for p in (self.audit, self.touch, self.caller, self.db):
            p.stop()
        wrapper.REGISTRY.clear()
        wrapper.REGISTRY.update(self.saved)

    def _register(self, name, fn):
        wrapper.REGISTRY.pop(name, None)
        fn.__name__ = name
        wrapper.admin_tool(title="T")(fn)
        return wrapper.REGISTRY[name].run

    def test_a_tool_that_is_not_approved_cannot_be_registered(self):
        def sneaky_delete_everything():
            return {}
        with self.assertRaises(RuntimeError):
            wrapper.admin_tool(title="x")(sneaky_delete_everything)

    def test_call_runs_read_only_writes_one_audit_row_and_names_the_source(self):
        seen = {}

        def tool(client: str = ""):
            seen["read_only"] = supabase_db.read_only.get()
            wrapper.note_client("tenant-9")  # runs in a worker thread, like resolve_client
            return {"n": 1}

        run = self._register("client_overview", tool)
        result = asyncio.run(run(client="AstroTamil"))
        self.assertTrue(seen["read_only"])
        self.assertFalse(supabase_db.read_only.get())
        self.assertEqual(result, {"source": wrapper.APPROVED_TOOLS["client_overview"], "data": {"n": 1}})
        self.audit_mock.assert_called_once()
        kw = self.audit_mock.call_args.kwargs
        self.assertEqual((kw["action"], kw["target_type"], kw["target_id"]), ("mcp.tool_call", "mcp_tool", "client_overview"))
        self.assertEqual((kw["actor_user_id"], kw["actor_role"]), ("user-1", "system_admin"))
        self.assertEqual(kw["tenant_id"], "tenant-9")  # the client survives the worker thread
        self.assertEqual(kw["metadata"], {"connection_id": "conn-1", "arguments": {"client": "AstroTamil"}, "ok": True})
        self.touch_mock.assert_called_once()

    def test_a_tool_that_tries_to_write_is_stopped_and_logged_as_failed(self):
        raw = MagicMock()

        def tool():
            supabase_db.get_supabase().table("leads").delete()

        run = self._register("client_leads", tool)
        with patch.object(supabase_db, "_client", raw):
            with self.assertRaises(ToolError):
                asyncio.run(run())
        raw.table.return_value.delete.assert_not_called()
        self.assertFalse(self.audit_mock.call_args.kwargs["metadata"]["ok"])
        self.assertFalse(supabase_db.read_only.get())

    def test_no_audit_row_means_no_answer(self):
        self.audit_mock.side_effect = Exception("app_audit_logs is down")
        run = self._register("client_health", lambda: {"secret": "data"})
        with self.assertRaises(ToolError) as ctx:
            asyncio.run(run())
        self.assertIn("audit log", str(ctx.exception))

    def test_a_tool_that_runs_too_long_is_stopped_and_still_audited(self):
        async def tool():
            await asyncio.sleep(5)

        run = self._register("client_health", tool)
        with patch.object(wrapper, "TOOL_TIMEOUT_SECONDS", 0.05), self.assertRaises(ToolError) as ctx:
            asyncio.run(run())
        self.assertIn("too long", str(ctx.exception))
        self.assertFalse(self.audit_mock.call_args.kwargs["metadata"]["ok"])

    def test_the_audit_row_keeps_a_phone_search_as_its_last_4_digits_and_cuts_long_text(self):
        kept = wrapper._audit_arguments({"client": "AstroTamil", "query": "+91 98765 43210", "limit": 10})
        self.assertEqual(kept, {"client": "AstroTamil", "query": "phone ending 3210", "limit": 10})
        self.assertEqual(wrapper._audit_arguments({"query": "Karthik"}), {"query": "Karthik"})
        self.assertEqual(len(wrapper._audit_arguments({"client": "x" * 5000})["client"]), wrapper.MAX_AUDIT_ARG_CHARS + 1)

    def test_operator_404_becomes_a_tool_error(self):
        def tool():
            raise HTTPException(status_code=404, detail="Tenant not found")

        run = self._register("client_health", tool)
        with self.assertRaises(ToolError) as ctx:
            asyncio.run(run())
        self.assertIn("Tenant not found", str(ctx.exception))

    def test_an_answer_over_the_size_cap_is_refused(self):
        run = self._register("client_config", lambda: {"big": "x" * (wrapper.MAX_RESULT_CHARS + 1)})
        with self.assertRaises(ToolError):
            asyncio.run(run())

    def test_resolve_client_by_name_id_and_unknown(self):
        db = MagicMock()
        db.table.return_value.select.return_value.execute.return_value = MagicMock(data=[
            {"id": "11111111-1111-1111-1111-111111111111", "name": "AstroTamil"},
            {"id": "22222222-2222-2222-2222-222222222222", "name": "Astro Books"},
            {"id": "33333333-3333-3333-3333-333333333333", "name": "Healy"},
        ])
        with patch.object(wrapper, "get_supabase", return_value=db):
            self.assertEqual(wrapper.resolve_client("astrotamil")["name"], "AstroTamil")
            self.assertEqual(wrapper.resolve_client("33333333-3333-3333-3333-333333333333")["name"], "Healy")
            self.assertEqual(wrapper.resolve_client("heal")["name"], "Healy")
            for bad in ("astro", "nobody", "", "44444444-4444-4444-4444-444444444444"):
                with self.assertRaises(ToolError):
                    wrapper.resolve_client(bad)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = build_server()
        cls.app = build_app(cls.server)

    def test_every_approved_tool_is_registered_and_nothing_else(self):
        self.assertEqual(set(wrapper.REGISTRY), set(wrapper.APPROVED_TOOLS))

    def test_every_tool_is_marked_read_only(self):
        tools = asyncio.run(self.server.list_tools())
        self.assertEqual({t.name for t in tools}, set(wrapper.APPROVED_TOOLS))
        for tool in tools:
            self.assertTrue(tool.annotations.read_only_hint, tool.name)
            self.assertFalse(tool.annotations.destructive_hint, tool.name)
            self.assertTrue(tool.description, tool.name)

    def test_http_no_token_is_401_and_points_at_the_sign_in_document(self):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        with StarletteClient(self.app, base_url="http://localhost:8000") as client:
            r = client.post("/mcp", json=body, headers=headers)
            self.assertEqual(r.status_code, 401)
            self.assertIn("resource_metadata=", r.headers["www-authenticate"])
            bad = client.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer nope"})
            self.assertEqual(bad.status_code, 401)
            meta = client.get("/.well-known/oauth-protected-resource/mcp").json()
            self.assertTrue(meta["resource"].endswith("/mcp"))
            self.assertEqual(meta["authorization_servers"], [auth.issuer()])
            good = AccessToken(token="t", client_id="c", scopes=[], subject="user-1", claims={"connection_id": "conn-1"})
            with patch.object(auth, "verify", return_value=good):
                ok = client.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer t"})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(len(ok.json()["result"]["tools"]), len(wrapper.APPROVED_TOOLS))

    def test_the_gateway_takes_only_the_mcp_paths_and_leaves_the_api_alone(self):
        # Regression: a root mount turned the API's slash redirects and 405s into 404s.
        from fastapi import FastAPI
        from app.admin_mcp.server import McpGateway

        api = FastAPI()

        @api.get("/api/v1/numbers/")
        def numbers():
            return []

        @api.post("/only-post")
        def only_post():
            return {}

        seen = []

        async def fake_mcp(scope, receive, send):
            seen.append(scope["path"])
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        api.add_middleware(McpGateway, mcp_app=fake_mcp, limit_per_minute=3)
        client = TestClient(api, follow_redirects=False)
        self.assertEqual(client.get("/api/v1/numbers").status_code, 307)
        self.assertEqual(client.get("/only-post").status_code, 405)
        self.assertEqual(client.get("/nope").headers["content-type"], "application/json")
        self.assertEqual(client.get("/mcpx").status_code, 404)
        codes = [client.post(path).status_code for path in ("/mcp", "/mcp/", "/.well-known/oauth-protected-resource/mcp", "/mcp")]
        self.assertEqual(codes, [204, 204, 204, 429])  # the 4th call in a minute is over the limit of 3
        self.assertEqual(seen, ["/mcp", "/mcp", "/.well-known/oauth-protected-resource/mcp"])

    def test_the_server_announces_the_anril_icon_and_the_backend_serves_it(self):
        from app.admin_mcp import server as mcp_server

        # What Claude actually receives when it connects (the "initialize" answer).
        body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                   "Authorization": "Bearer t"}
        good = AccessToken(token="t", client_id="c", scopes=[], subject="user-1", claims={"connection_id": "conn-1"})
        fresh_app = build_app(build_server())  # its own app: a session manager runs only once
        with StarletteClient(fresh_app, base_url="http://localhost:8000") as mcp_client, \
             patch.object(auth, "verify", return_value=good):
            info = mcp_client.post("/mcp", json=body, headers=headers).json()["result"]["serverInfo"]
        self.assertEqual(info["websiteUrl"], mcp_server.WEBSITE_URL)
        self.assertEqual(info["icons"][0]["src"], mcp_server.base_url() + "/brand/anril-icon.png")

        icon = self.server.icons[0]
        self.assertEqual(self.server.website_url, mcp_server.WEBSITE_URL)
        self.assertEqual(icon.src, mcp_server.base_url() + "/brand/anril-icon.png")
        self.assertEqual((icon.mime_type, icon.sizes), ("image/png", ["192x192"]))
        client = TestClient(app)
        png = client.get("/brand/anril-icon.png")
        self.assertEqual((png.status_code, png.headers["content-type"]), (200, "image/png"))
        self.assertTrue(png.content.startswith(b"\x89PNG"))
        ico = client.get("/favicon.ico")
        self.assertEqual((ico.status_code, ico.headers["content-type"]), (200, "image/x-icon"))

    def test_mcp_is_not_mounted_when_the_switch_is_off(self):
        self.assertFalse(settings.mcp_enabled)
        r = TestClient(app).post("/mcp", json={})
        self.assertEqual(r.status_code, 404)


class ConnectionServiceTests(unittest.TestCase):
    def test_activate_switches_every_other_connection_off_first(self):
        db = MagicMock()
        table = db.table.return_value
        table.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "conn-2", "status": "active"}])
        row = mcp_connections.activate(db, "user-1", "claude-client", None)
        self.assertEqual(row["id"], "conn-2")
        self.assertEqual(table.update.call_args.args[0]["status"], "revoked")
        payload = table.upsert.call_args.args[0]
        self.assertEqual((payload["user_id"], payload["client_id"], payload["status"], payload["label"]),
                         ("user-1", "claude-client", "active", "Claude app"))
        self.assertEqual(table.upsert.call_args.kwargs["on_conflict"], "user_id,client_id")


class ClaudeAccessEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_endpoints_need_a_system_admin(self):
        for method, path in (("get", "/claude-access"), ("post", "/claude-access/allow"), ("post", "/claude-access/revoke")):
            r = getattr(self.client, method)(f"/api/v1/operator{path}")
            self.assertIn(r.status_code, (401, 403), path)

    def test_allow_then_revoke(self):
        app.dependency_overrides[get_system_admin] = lambda: {"user_id": "user-1"}
        with patch("app.routes.operator_mcp.get_supabase", return_value=MagicMock()), \
             patch.object(settings, "mcp_oauth_client_id", "claude-client"), \
             patch("app.routes.operator_mcp.record_audit_event") as audit, \
             patch.object(mcp_connections, "activate", return_value={"id": "conn-1", "label": "Claude"}) as activate, \
             patch.object(mcp_connections, "revoke_all", return_value=1) as revoke, \
             patch.object(mcp_connections, "current", return_value={"id": "conn-1", "status": "revoked"}):
            r = self.client.post("/api/v1/operator/claude-access/allow", json={"client_id": "claude-client", "label": "Claude"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(activate.call_args.args[1:], ("user-1", "claude-client", "Claude"))
            self.assertEqual(self.client.post("/api/v1/operator/claude-access/allow", json={}).status_code, 422)
            r = self.client.post("/api/v1/operator/claude-access/revoke")
            self.assertEqual(r.json()["revoked"], 1)
            revoke.assert_called_once()
        self.assertEqual([c.kwargs["action"] for c in audit.call_args_list], ["mcp.connection.allow", "mcp.connection.revoke"])

    def test_allow_refuses_any_app_that_is_not_the_registered_claude_client(self):
        app.dependency_overrides[get_system_admin] = lambda: {"user_id": "user-1"}
        with patch("app.routes.operator_mcp.get_supabase", return_value=MagicMock()), \
             patch.object(mcp_connections, "activate") as activate:
            for configured in ("claude-client", None):
                with patch.object(settings, "mcp_oauth_client_id", configured):
                    r = self.client.post("/api/v1/operator/claude-access/allow", json={"client_id": "look-alike", "label": "Claude"})
                self.assertEqual(r.status_code, 400)
        activate.assert_not_called()  # the real connection is not kicked out either

    def test_page_data_counts_today_and_names_the_top_tool_and_client(self):
        app.dependency_overrides[get_system_admin] = lambda: {"user_id": "user-1"}
        now = "2999-01-01T10:00:00+00:00"  # later than any "today", so every row counts as today
        rows = [
            {"id": "1", "tenant_id": "t1", "target_id": "lead_thread", "metadata": {"arguments": {"client": "AstroTamil"}}, "created_at": now},
            {"id": "2", "tenant_id": "t1", "target_id": "lead_thread", "metadata": {}, "created_at": now},
            {"id": "3", "tenant_id": None, "target_id": "fleet_summary", "metadata": {}, "created_at": now},
            {"id": "4", "tenant_id": "t1", "target_id": "find_lead", "metadata": {}, "created_at": now},
        ]
        db = MagicMock()

        def table(name):
            t = MagicMock()
            if name == "app_audit_logs":
                t.select.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=rows)
            if name == "tenants":
                t.select.return_value.in_.return_value.execute.return_value = MagicMock(data=[{"id": "t1", "name": "AstroTamil"}])
            return t

        db.table.side_effect = table
        with patch("app.routes.operator_mcp.get_supabase", return_value=db), \
             patch.object(mcp_connections, "current", return_value=None):
            body = self.client.get("/api/v1/operator/claude-access").json()
        self.assertEqual(body["calls_today"], 4)
        self.assertEqual((body["top_tool_week"], body["top_client_week"]), ("lead_thread", "AstroTamil"))
        self.assertEqual([c["tool"] for c in body["recent_calls"]], ["lead_thread", "lead_thread", "fleet_summary"])
        self.assertTrue(body["mcp_url"].endswith("/mcp"))
        self.assertIsNone(body["connection"])


if __name__ == "__main__":
    unittest.main()

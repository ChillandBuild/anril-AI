"""Call IQ teams: the built-in Team leader role, the /api/v1/call-teams API, and what happens
before migration 307 is applied."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fake_supabase import FakeSupabase
from team_fixture import (
    A1, A2, A1_U, B1, B1_U, CUSTOM_U, LC, LEADER_CTX, LEADER_U, MANAGER_CTX, OWNER_CTX, OWNER_U, RID_CU, RID_TC, RID_TL,
    T1, T2, TA, TB, TC_U, TX, U1, X1, X1_U, Harness, build_db, ctx_for, uid,
)
from app.services import call_teams as svc
from app.services.rbac import (
    DEFAULT_TEAM_LEADER_PERMISSIONS, DEFAULT_TELECALLER_PERMISSIONS, PERMISSION_CATALOG, ensure_team_leader_role,
)


class TeamLeaderRoleTests(unittest.TestCase):
    def test_permissions_are_telecaller_plus_team_and_upload(self):
        self.assertEqual(
            set(DEFAULT_TEAM_LEADER_PERMISSIONS),
            set(DEFAULT_TELECALLER_PERMISSIONS) | {"team.view", "team.manage", "telecalling.upload"},
        )

    def test_leader_cannot_download_refund_or_open_settings(self):
        for forbidden in ("leads.download", "deals.manage", "deals.refund", "settings.view", "settings.manage",
                          "roles.view", "roles.manage", "subscription.view", "subscription.manage", "analytics.view"):
            self.assertNotIn(forbidden, DEFAULT_TEAM_LEADER_PERMISSIONS)

    def test_telecaller_defaults_unchanged(self):
        self.assertEqual(DEFAULT_TELECALLER_PERMISSIONS, [
            "dashboard.view", "conversations.view", "leads.view", "deals.view",
            "telecalling.dialer", "telecalling.scheduled", "telecalling.notes",
        ])

    def test_download_permission_is_in_the_catalog(self):
        self.assertIn({"key": "leads.download", "label": "Download lists", "group": "Leads"}, PERMISSION_CATALOG)

    def test_role_is_created_once_per_client(self):
        db = FakeSupabase()
        first = ensure_team_leader_role(db, T1)
        again = ensure_team_leader_role(db, T1)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(first["slug"], "team_leader")
        self.assertEqual(first["name"], "Team leader")
        self.assertTrue(first["is_system_template"])
        self.assertEqual(set(first["permissions"]), set(DEFAULT_TEAM_LEADER_PERMISSIONS))
        self.assertEqual(len([r for r in db.rows("tenant_roles") if r["slug"] == "team_leader"]), 1)
        other = ensure_team_leader_role(db, T2)
        self.assertNotEqual(other["id"], first["id"])

    def test_role_name_clash_with_a_custom_role_falls_back(self):
        db = FakeSupabase()
        db.add("tenant_roles", tenant_id=T1, name="Team leader", slug=None, permissions=["dashboard.view"])
        real_insert = FakeSupabase.table

        class Clash(FakeSupabase):
            def table(self, name):
                q = real_insert(self, name)
                if name == "tenant_roles":
                    inner = q.insert

                    def insert(payload):
                        if payload.get("name") == "Team leader":
                            raise Exception("23505 duplicate key value violates unique constraint (tenant_id, name)")
                        return inner(payload)
                    q.insert = insert
                return q
        clash = Clash()
        clash.tables = db.tables
        role = ensure_team_leader_role(clash, T1)
        self.assertEqual(role["slug"], "team_leader")
        self.assertEqual(role["name"], "Team leader (built-in)")

    def test_roles_list_shows_it_and_it_cannot_be_deleted(self):
        db = FakeSupabase()
        with Harness(db) as h:
            client = h.as_(ctx_for(OWNER_U, "owner", "owner", ["roles.manage"]))
            roles = client.get("/api/v1/rbac/roles").json()["data"]
            leader = next(r for r in roles if r["slug"] == "team_leader")
            self.assertTrue(leader["is_telecaller"])
            self.assertEqual(client.delete(f"/api/v1/rbac/roles/{leader['id']}").status_code, 400)


class TeamsApiTests(unittest.TestCase):
    def test_owner_sees_every_team_with_members_leaders_and_unassigned(self):
        with Harness() as h:
            body = h.as_(OWNER_CTX).get("/api/v1/call-teams").json()
        self.assertTrue(body["teams_ready"])
        self.assertTrue(body["can_manage"])
        teams = {t["name"]: t for t in body["data"]}
        self.assertEqual(set(teams), {"Team A", "Team B"})          # never the other client's team
        self.assertEqual({m["caller_id"] for m in teams["Team A"]["members"]}, {LC, A1, A2})
        self.assertEqual([l["user_id"] for l in teams["Team A"]["leaders"]], [LEADER_U])
        self.assertEqual({m["caller_id"] for m in body["unteamed"]}, {U1})   # owner's own caller is not listed

    def test_create_rename_delete(self):
        with Harness() as h:
            c = h.as_(OWNER_CTX)
            made = c.post("/api/v1/call-teams", json={"name": "  Team   C "})
            self.assertEqual(made.status_code, 201)
            tid = made.json()["data"]["id"]
            self.assertEqual(made.json()["data"]["name"], "Team C")
            self.assertEqual(c.patch(f"/api/v1/call-teams/{tid}", json={"name": "Night team"}).json()["data"]["name"], "Night team")
            self.assertEqual(c.post("/api/v1/call-teams", json={"name": "team a"}).status_code, 409)   # same name as Team A
            self.assertEqual(c.post("/api/v1/call-teams", json={"name": "   "}).status_code, 400)
            self.assertEqual(c.post("/api/v1/call-teams", json={"name": "x" * 61}).status_code, 400)
            self.assertEqual(c.delete(f"/api/v1/call-teams/{tid}").status_code, 200)
            self.assertFalse([t for t in h.db.rows("call_teams") if t["id"] == tid])

    def test_delete_sends_members_back_to_no_team(self):
        with Harness() as h:
            self.assertEqual(h.as_(OWNER_CTX).delete(f"/api/v1/call-teams/{TA}").status_code, 200)
            callers = {c["id"]: c for c in h.db.rows("callers")}
            self.assertIsNone(callers[A1]["team_id"])
            self.assertIsNone(callers[LC]["team_id"])
            self.assertEqual(callers[B1]["team_id"], TB)                    # other team untouched
            self.assertFalse([r for r in h.db.rows("call_team_leaders") if r["team_id"] == TA])

    def test_members_replaces_the_list_and_moves_people_between_teams(self):
        with Harness() as h:
            r = h.as_(OWNER_CTX).put(f"/api/v1/call-teams/{TA}/members", json={"caller_ids": [A1, B1]})
            self.assertEqual(r.status_code, 200)
            callers = {c["id"]: c["team_id"] for c in h.db.rows("callers")}
            self.assertEqual(callers[A1], TA)
            self.assertEqual(callers[B1], TA)       # moved from Team B
            self.assertIsNone(callers[A2])          # ticked off
            self.assertIsNone(callers[LC])

    def test_other_clients_ids_are_404(self):
        with Harness() as h:
            c = h.as_(OWNER_CTX)
            self.assertEqual(c.patch(f"/api/v1/call-teams/{TX}", json={"name": "hijack"}).status_code, 404)
            self.assertEqual(c.delete(f"/api/v1/call-teams/{TX}").status_code, 404)
            self.assertEqual(c.put(f"/api/v1/call-teams/{TX}/members", json={"caller_ids": [A1]}).status_code, 404)
            self.assertEqual(c.put(f"/api/v1/call-teams/{TA}/members", json={"caller_ids": [X1]}).status_code, 404)
            self.assertEqual(c.put(f"/api/v1/call-teams/{TA}/leaders", json={"user_ids": [X1_U]}).status_code, 404)
            self.assertEqual(c.patch("/api/v1/call-teams/not-a-uuid", json={"name": "x"}).status_code, 404)
            self.assertEqual([t["name"] for t in h.db.rows("call_teams") if t["id"] == TX], ["Other client team"])
            callers = {c_["id"]: c_["team_id"] for c_ in h.db.rows("callers")}
            self.assertEqual(callers[X1], TX)

    def test_owner_cannot_be_member_or_leader(self):
        with Harness() as h:
            c = h.as_(OWNER_CTX)
            owner_caller = next(r["id"] for r in h.db.rows("callers") if r["user_id"] == OWNER_U)
            self.assertEqual(c.put(f"/api/v1/call-teams/{TA}/members", json={"caller_ids": [owner_caller]}).status_code, 400)
            self.assertEqual(c.put(f"/api/v1/call-teams/{TA}/leaders", json={"user_ids": [OWNER_U]}).status_code, 400)

    def test_a_team_leader_cannot_change_teams(self):
        with Harness() as h:
            c = h.as_(LEADER_CTX)
            self.assertEqual(c.post("/api/v1/call-teams", json={"name": "Mine"}).status_code, 403)
            self.assertEqual(c.patch(f"/api/v1/call-teams/{TA}", json={"name": "Renamed"}).status_code, 403)
            self.assertEqual(c.delete(f"/api/v1/call-teams/{TA}").status_code, 403)
            self.assertEqual(c.put(f"/api/v1/call-teams/{TA}/members", json={"caller_ids": [B1]}).status_code, 403)
            self.assertEqual(c.put(f"/api/v1/call-teams/{TA}/leaders", json={"user_ids": [A1_U]}).status_code, 403)
            self.assertEqual({t["name"] for t in h.db.rows("call_teams") if t["tenant_id"] == T1}, {"Team A", "Team B"})

    def test_a_team_leader_sees_only_the_team_they_lead(self):
        with Harness() as h:
            body = h.as_(LEADER_CTX).get("/api/v1/call-teams").json()
        self.assertEqual([t["name"] for t in body["data"]], ["Team A"])
        self.assertFalse(body["can_manage"])
        self.assertEqual(body["unteamed"], [])

    def test_a_manager_with_team_manage_but_not_a_leader_can_change_teams(self):
        with Harness() as h:
            self.assertEqual(h.as_(MANAGER_CTX).post("/api/v1/call-teams", json={"name": "Day shift"}).status_code, 201)

    def test_a_role_without_team_view_is_refused(self):
        with Harness() as h:
            r = h.as_(ctx_for(A1_U, "caller", "telecaller", DEFAULT_TELECALLER_PERMISSIONS, caller_id=A1)).get("/api/v1/call-teams")
            self.assertEqual(r.status_code, 403)

    def test_roles_manage_can_change_teams(self):
        with Harness() as h:
            ctx = ctx_for(CUSTOM_U, "caller", "admin", ["team.view", "roles.manage"])
            self.assertEqual(h.as_(ctx).post("/api/v1/call-teams", json={"name": "Admins team"}).status_code, 201)

    def test_audit_events_are_written(self):
        with Harness() as h:
            with patch("app.routes.call_teams.record_audit_event") as audit:
                c = h.as_(OWNER_CTX)
                tid = c.post("/api/v1/call-teams", json={"name": "Audit"}).json()["data"]["id"]
                c.patch(f"/api/v1/call-teams/{tid}", json={"name": "Audit 2"})
                c.put(f"/api/v1/call-teams/{tid}/members", json={"caller_ids": [A1]})
                c.put(f"/api/v1/call-teams/{tid}/leaders", json={"user_ids": [A1_U]})
                c.delete(f"/api/v1/call-teams/{tid}")
            self.assertEqual(
                [call.kwargs["action"] for call in audit.call_args_list],
                ["team.call_team_created", "team.call_team_renamed", "team.call_team_members",
                 "team.call_team_leaders", "team.call_team_deleted"],
            )


class LeaderRoleOnAssignTests(unittest.TestCase):
    def test_telecaller_made_leader_gets_the_team_leader_role(self):
        with Harness() as h:
            r = h.as_(OWNER_CTX).put(f"/api/v1/call-teams/{TB}/leaders", json={"user_ids": [B1_U]})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["promoted"], [B1_U])
            self.assertIsNone(r.json()["note"])
            row = next(u for u in h.db.rows("tenant_users") if u["user_id"] == B1_U)
            self.assertEqual(row["role_id"], RID_TL)
            self.assertEqual([l["user_id"] for l in h.db.rows("call_team_leaders") if l["team_id"] == TB], [B1_U])

    def test_role_is_created_on_demand_when_the_client_has_none(self):
        db = build_db()
        db.tables["tenant_roles"] = [r for r in db.rows("tenant_roles") if r["slug"] != "team_leader"]
        for u in db.rows("tenant_users"):
            if u["role_id"] == RID_TL:
                u["role_id"] = RID_TC
        with Harness(db) as h:
            h.as_(OWNER_CTX).put(f"/api/v1/call-teams/{TB}/leaders", json={"user_ids": [B1_U]})
            made = next(r for r in db.rows("tenant_roles") if r["slug"] == "team_leader")
            row = next(u for u in db.rows("tenant_users") if u["user_id"] == B1_U)
            self.assertEqual(row["role_id"], made["id"])

    def test_custom_role_is_kept_and_a_note_is_returned(self):
        with Harness() as h:
            r = h.as_(OWNER_CTX).put(f"/api/v1/call-teams/{TB}/leaders", json={"user_ids": [CUSTOM_U]})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["promoted"], [])
            self.assertIn("Team leader role", r.json()["note"])
            self.assertIn("keep their role", r.json()["note"])
            row = next(u for u in h.db.rows("tenant_users") if u["user_id"] == CUSTOM_U)
            self.assertEqual(row["role_id"], RID_CU)

    def test_removing_a_leader_does_not_touch_roles(self):
        with Harness() as h:
            h.as_(OWNER_CTX).put(f"/api/v1/call-teams/{TA}/leaders", json={"user_ids": []})
            row = next(u for u in h.db.rows("tenant_users") if u["user_id"] == LEADER_U)
            self.assertEqual(row["role_id"], RID_TL)         # still Team leader: sees only themself (fail closed)
            self.assertFalse([l for l in h.db.rows("call_team_leaders") if l["team_id"] == TA])


class RolesPageTeamInfoTests(unittest.TestCase):
    def test_users_list_carries_each_persons_team_read_only(self):
        with Harness() as h:
            c = h.as_(ctx_for(OWNER_U, "owner", "owner", ["roles.view"]))
            with patch("app.routes.rbac._telecaller_seat_limit", return_value=50), \
                 patch("app.routes.rbac._active_telecaller_count", return_value=1):
                users = {u["user_id"]: u for u in c.get("/api/v1/rbac/users").json()["data"]}
        self.assertEqual(users[LEADER_U]["team_name"], "Team A")
        self.assertEqual(users[LEADER_U]["leads_teams"], ["Team A"])
        self.assertEqual(users[B1_U]["team_name"], "Team B")
        self.assertEqual(users[B1_U]["leads_teams"], [])
        self.assertIsNone(users[OWNER_U]["team_name"])

    def test_removing_a_person_clears_their_leader_rows(self):
        with Harness() as h:
            c = h.as_(ctx_for(OWNER_U, "owner", "owner", ["roles.manage"]))
            with patch("app.routes.rbac.db_auth_delete", create=True):
                h.db.auth = type("A", (), {"admin": type("Ad", (), {"delete_user": staticmethod(lambda u: None)})()})()
                r = c.delete(f"/api/v1/rbac/users/{LEADER_U}")
            self.assertEqual(r.status_code, 200)
            self.assertFalse([l for l in h.db.rows("call_team_leaders") if l["user_id"] == LEADER_U])


class MissingTablesTests(unittest.TestCase):
    """Migration 307 is not applied yet: nothing crashes, nobody is limited, teams are just empty."""

    def _db(self):
        db = build_db()

        class NoTeams(FakeSupabase):
            def table(self, name):
                if name in ("call_teams", "call_team_leaders"):
                    raise Exception('relation "public.%s" does not exist (PGRST205: could not find the table in the schema cache)' % name)
                return super().table(name)
        old = NoTeams()
        old.tables = db.tables
        for c in old.rows("callers"):
            c.pop("team_id", None)
        return old

    def test_schema_error_detection(self):
        self.assertTrue(svc.teams_schema_missing(Exception("column callers.team_id does not exist")))
        self.assertTrue(svc.teams_schema_missing(Exception("PGRST205 could not find the table 'public.call_teams' in the schema cache")))
        self.assertFalse(svc.teams_schema_missing(Exception("connection reset")))

    def test_list_is_empty_and_not_ready(self):
        with Harness(self._db()) as h:
            body = h.as_(OWNER_CTX).get("/api/v1/call-teams").json()
        self.assertEqual(body["data"], [])
        self.assertFalse(body["teams_ready"])

    def test_changing_teams_says_not_switched_on(self):
        with Harness(self._db()) as h:
            r = h.as_(OWNER_CTX).post("/api/v1/call-teams", json={"name": "Team Z"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("not switched on", r.json()["detail"])

    def test_owner_and_other_roles_are_not_limited(self):
        db = self._db()
        self.assertIsNone(svc.caller_scope(db, OWNER_CTX))
        self.assertIsNone(svc.caller_scope(db, MANAGER_CTX))

    def test_owner_still_lists_callers(self):
        with Harness(self._db()) as h:
            body = h.as_(OWNER_CTX).get("/api/v1/callers/").json()
        self.assertEqual({c["id"] for c in body["data"]}, {LC, A1, A2, B1, U1})
        self.assertTrue(all(c["team_id"] is None and c["team_name"] is None for c in body["data"]))

    def test_a_leader_fails_closed_to_nothing(self):
        db = self._db()
        self.assertEqual(svc.caller_scope(db, LEADER_CTX), set())


if __name__ == "__main__":
    unittest.main()

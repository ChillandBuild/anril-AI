"""Private Send: license keys, signed bundles, usage counting, operator + tenant APIs.

A tiny in-memory Supabase stand-in (FakeDB) is patched in for get_supabase so the real
service code (incl. entitlements metering) runs against stateful tables."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.system_admin import get_system_admin
from app.routes import auto_messages, operator
from app.routes import private_send as ps_routes
from app.services import private_send as ps

TENANT = "0f897915-2d34-4b67-8d69-f83f52e4fb6c"
OTHER_TENANT = "11111111-2222-4333-8444-555555555555"
TPL_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TPL_PENDING = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TPL_OTHER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
OPERATOR_BASE = f"/api/v1/operator/clients/{TENANT}/private-send"
PUBLIC_BASE = "/api/v1/private-send"


# ------------------------------------------------------------------ fake database

class Query:
    def __init__(self, store: dict, table: str, failing: set | None = None):
        self._rows = store.setdefault(table, [])
        self._table = table
        self._failing = failing or set()
        self._op, self._payload, self._conflict = "select", None, None
        self._preds, self._order, self._limit, self._count, self._single = [], None, None, False, False
        self._cols = None

    def select(self, cols="*", count=None):
        self._count = count == "exact"
        self._cols = None if cols.strip() == "*" else [c.strip() for c in cols.split(",")]
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op, self._payload = "upsert", payload
        self._conflict = (on_conflict or "").split(",")
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._preds.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        self._preds.append(lambda r: r.get(col) in vals)
        return self

    def gte(self, col, val):
        self._preds.append(lambda r: r.get(col) is not None and r[col] >= val)
        return self

    def lt(self, col, val):
        self._preds.append(lambda r: r.get(col) is not None and r[col] < val)
        return self

    def contains(self, col, vals):
        self._preds.append(lambda r: all(v in (r.get(col) or []) for v in vals))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def maybe_single(self):
        self._single = True
        return self

    def _match(self):
        return [r for r in self._rows if all(p(r) for p in self._preds)]

    def _write(self):
        incoming = self._payload if isinstance(self._payload, list) else [self._payload]
        out = []
        for item in incoming:
            row = dict(item)
            if self._op == "insert":
                row.setdefault("id", str(uuid.uuid4()))
                if self._table == "private_send_keys":
                    row.setdefault("status", "active")
                self._rows.append(row)
                out.append(dict(row))
                continue
            same = [r for r in self._rows if all(r.get(c) == row.get(c) for c in self._conflict)]
            if same:
                same[0].update(row)
                out.append(dict(same[0]))
            else:
                self._rows.append(row)
                out.append(dict(row))
        return out

    def execute(self):
        if self._op != "select" and self._table in self._failing:
            raise RuntimeError(f"simulated write failure on {self._table}")
        if self._op in ("insert", "upsert"):
            return SimpleNamespace(data=self._write(), count=None)
        matched = self._match()
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
            return SimpleNamespace(data=[dict(r) for r in matched], count=None)
        if self._op == "delete":
            for r in matched:
                self._rows.remove(r)
            return SimpleNamespace(data=[dict(r) for r in matched], count=None)
        if self._order:
            matched = sorted(matched, key=lambda r: r.get(self._order[0]) or "", reverse=self._order[1])
        total = len(matched)
        matched = matched[: self._limit] if self._limit else matched
        if self._cols:  # like PostgREST, return only the selected columns
            matched = [{c: r.get(c) for c in self._cols} for r in matched]
        if self._single:  # postgrest returns None outright on zero rows
            return SimpleNamespace(data=dict(matched[0]), count=None) if matched else None
        return SimpleNamespace(data=[dict(r) for r in matched], count=total if self._count else None)


def _fake_record_private_send_usage(db: "FakeDB", tenant: str, rows: list[dict]) -> int:
    """Python mirror of the SQL function record_private_send_usage in 218_private_send.sql:
    per-row GREATEST upsert, returns the sum of the positive growth in reported_sent."""
    table = db.rows("private_send_usage")
    delta = 0
    for r in sorted(rows, key=lambda r: (r["day"], r["event"], r["template_id"])):
        existing = next((u for u in table if (u["tenant_id"], u["day"], u["event"], u["template_id"])
                         == (tenant, r["day"], r["event"], r["template_id"])), None)
        if existing is None:
            table.append({"tenant_id": tenant, "day": r["day"], "event": r["event"],
                          "template_id": r["template_id"], "reported_sent": r["sent"], "reported_failed": r["failed"]})
            delta += r["sent"]
            continue
        old = existing.get("reported_sent") or 0
        existing["reported_sent"] = max(old, r["sent"])
        existing["reported_failed"] = max(existing.get("reported_failed") or 0, r["failed"])
        delta += max(0, r["sent"] - old)
    return delta


class FakeDB:
    def __init__(self):
        self.store: dict[str, list[dict]] = {}
        self.failing_tables: set[str] = set()
        self.lookups: list[str] = []  # tables read through table(), for "no DB hit" assertions

    def table(self, name: str) -> Query:
        self.lookups.append(name)
        return Query(self.store, name, self.failing_tables)

    def rpc(self, name: str, params: dict):
        assert name == "record_private_send_usage", name
        run = lambda: SimpleNamespace(data=_fake_record_private_send_usage(self, params["p_tenant"], params["p_rows"]))
        return SimpleNamespace(execute=run)

    def rows(self, name: str) -> list[dict]:
        return self.store.setdefault(name, [])


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def signing(monkeypatch):
    private = Ed25519PrivateKey.generate()
    seed = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    monkeypatch.setenv(ps.SIGNING_ENV, base64.b64encode(seed).decode())
    return private.public_key()


@pytest.fixture
def env(monkeypatch):
    """FakeDB + in-memory app_settings + the three routers mounted on a throwaway app."""
    db, settings = FakeDB(), {}
    db.rows("tenants").append({"id": TENANT, "enabled_features": ["private_send"]})
    db.rows("tenants").append({"id": OTHER_TENANT, "enabled_features": []})
    db.rows("message_templates").append({"id": TPL_A, "tenant_id": TENANT, "name": "loan_ready"})

    def get_setting(key, fallback=None, tenant_id=None):
        if (tenant_id, key) in settings:
            return settings[(tenant_id, key)] or fallback
        saved = [r["value"] for r in db.rows("app_settings") if (r["tenant_id"], r["key"]) == (tenant_id, key)]
        return (saved[0] if saved else None) or fallback
    monkeypatch.setattr(ps, "get_setting", get_setting)
    for mod in (ps_routes, operator, auto_messages):
        monkeypatch.setattr(mod, "get_supabase", lambda: db)
    monkeypatch.setattr(ps_routes, "_bundle_limiter", ps_routes._SlidingWindow(60, 60))
    monkeypatch.setattr(ps_routes, "_usage_limiter", ps_routes._SlidingWindow(30, 60))
    monkeypatch.setattr(ps_routes, "_ip_limiter", ps_routes._SlidingWindow(120, 60))
    ps.reset_unknown_key_cache()
    audit = []
    monkeypatch.setattr(operator, "record_audit_event", lambda _db, **kw: audit.append(kw))

    app = FastAPI()
    app.include_router(ps_routes.public_router, prefix=PUBLIC_BASE)
    app.include_router(operator.router, prefix="/api/v1/operator")
    app.include_router(auto_messages.router, prefix="/api/v1/auto-messages")
    app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}
    app.dependency_overrides[auto_messages.require_auto_messages_view] = lambda: {"tenant_id": TENANT}
    return SimpleNamespace(db=db, settings=settings, audit=audit, client=TestClient(app))


def _saved(env, key, tenant=TENANT):
    """The value persisted to app_settings (what a reload would read), or None."""
    rows = [r["value"] for r in env.db.rows("app_settings") if (r["tenant_id"], r["key"]) == (tenant, key)]
    return rows[-1] if rows else None


def _add_key(env, tenant=TENANT, status="active"):
    full, prefix, key_hash = ps.generate_key()
    env.db.rows("private_send_keys").append({
        "id": str(uuid.uuid4()), "tenant_id": tenant, "key_prefix": prefix, "key_hash": key_hash, "status": status,
    })
    return full


def _auth(key, version="python/1.0.0"):
    return {"Authorization": f"Bearer {key}", "X-Aira-Plugin": version}


def _today(offset=0):
    return (datetime.now(timezone.utc).date() - timedelta(days=offset)).isoformat()


def _usage_row(**over):
    row = {"day": _today(), "event": "purchased", "template_id": TPL_A, "sent": 5, "failed": 1}
    row.update(over)
    return row


def _seed_rules(env):
    t = env.db.rows("message_templates")
    t += [
        {"id": TPL_A, "tenant_id": TENANT, "name": "loan_ready", "language": "en", "category": "UTILITY",
         "status": "APPROVED", "body_text": "Hi {{1}}", "header_text": None, "header_media_type": None,
         "header_media_url": None, "buttons": []},
        {"id": TPL_PENDING, "tenant_id": TENANT, "name": "draft", "language": "en", "category": "UTILITY",
         "status": "PENDING", "body_text": "x", "buttons": []},
        {"id": TPL_OTHER, "tenant_id": OTHER_TENANT, "name": "theirs", "language": "en", "category": "UTILITY",
         "status": "APPROVED", "body_text": "y", "buttons": []},
    ]
    var = [{"source": "first_name", "key": None, "value": None, "fallback": "there"}]
    env.db.rows("auto_message_rules").extend([
        {"id": "r-purchased", "tenant_id": TENANT, "event": "purchased", "template_id": TPL_A, "delay_minutes": 0,
         "variables": var, "button_param": None, "enabled": True},
        {"id": "r-interested", "tenant_id": TENANT, "event": "interested", "template_id": TPL_A, "delay_minutes": 5,
         "variables": [], "button_param": None, "enabled": False},
        {"id": "r-signed", "tenant_id": TENANT, "event": "signed_up", "template_id": TPL_PENDING, "delay_minutes": 0,
         "variables": [], "button_param": None, "enabled": True},
        {"id": "r-other", "tenant_id": OTHER_TENANT, "event": "purchased", "template_id": TPL_OTHER,
         "delay_minutes": 0, "variables": [], "button_param": None, "enabled": True},
    ])


def _get_bundle(env, key):
    return env.client.get(f"{PUBLIC_BASE}/bundle", headers=_auth(key))


def _decode(body: dict) -> dict:
    return json.loads(base64.b64decode(body["payload"]))


# ------------------------------------------------------------------ keys + auth

def test_generate_key_shape_and_hash():
    full, prefix, key_hash = ps.generate_key()
    assert full.startswith("aps_live_") and len(full) == len("aps_live_") + 32
    assert prefix == full[:13]
    assert key_hash == ps.hash_key(full) and len(key_hash) == 64


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": "Bearer aps_live_" + "x" * 32},
                                     {"Authorization": "Basic abc"}])
def test_bad_key_is_401_invalid_key(env, signing, headers):
    res = env.client.get(f"{PUBLIC_BASE}/bundle", headers=headers)
    assert res.status_code == 401
    assert res.json()["code"] == "invalid_key"


def test_revoked_key_is_401_revoked_key(env, signing):
    key = _add_key(env, status="revoked")
    res = _get_bundle(env, key)
    assert res.status_code == 401
    assert res.json()["code"] == "revoked_key"


def test_feature_off_is_403(env, signing):
    key = _add_key(env, tenant=OTHER_TENANT)
    res = _get_bundle(env, key)
    assert res.status_code == 403
    assert res.json()["code"] == "feature_disabled"


def test_feature_bought_via_subscription_item_counts(env, signing):
    key = _add_key(env, tenant=OTHER_TENANT)
    env.db.rows("tenant_subscription_items").append(
        {"tenant_id": OTHER_TENANT, "feature_key": "private_send", "quantity": 1})
    assert _get_bundle(env, key).status_code == 200


def test_valid_call_records_heartbeat_and_plugin_version(env, signing):
    key = _add_key(env)
    assert _get_bundle(env, key).status_code == 200
    row = env.db.rows("private_send_keys")[0]
    assert row["plugin_version"] == "python/1.0.0"
    assert row["last_seen_at"]


def test_new_anril_plugin_header_records_the_version(env, signing):
    key = _add_key(env)
    res = env.client.get(f"{PUBLIC_BASE}/bundle",
                         headers={"Authorization": f"Bearer {key}", "X-Anril-Plugin": "python/2.0.0"})
    assert res.status_code == 200
    assert env.db.rows("private_send_keys")[0]["plugin_version"] == "python/2.0.0"


def test_old_aira_plugin_header_still_records_the_version(env, signing):
    key = _add_key(env)
    res = env.client.get(f"{PUBLIC_BASE}/bundle",
                         headers={"Authorization": f"Bearer {key}", "X-Aira-Plugin": "python/1.0.0"})
    assert res.status_code == 200
    assert env.db.rows("private_send_keys")[0]["plugin_version"] == "python/1.0.0"


def test_new_plugin_header_wins_when_both_are_sent(env, signing):
    key = _add_key(env)
    res = env.client.get(f"{PUBLIC_BASE}/bundle", headers={
        "Authorization": f"Bearer {key}", "X-Anril-Plugin": "python/2.0.0", "X-Aira-Plugin": "python/1.0.0"})
    assert res.status_code == 200
    assert env.db.rows("private_send_keys")[0]["plugin_version"] == "python/2.0.0"


# ------------------------------------------------------------------ bundle

def test_bundle_signature_verifies_and_expires_in_15_minutes(env, signing):
    _seed_rules(env)
    res = _get_bundle(env, _add_key(env))
    assert res.status_code == 200
    body = res.json()
    assert body["key_id"] == "v1"
    raw = base64.b64decode(body["payload"])
    signing.verify(base64.b64decode(body["sig"]), raw)  # raises InvalidSignature on mismatch
    payload = json.loads(raw)
    issued = datetime.strptime(payload["issued_at"], "%Y-%m-%dT%H:%M:%SZ")
    expires = datetime.strptime(payload["expires_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert expires - issued == timedelta(minutes=15)
    assert payload["version"] == 1 and payload["tenant_id"] == TENANT
    assert payload["offline_grace_hours"] == 6


def test_tampered_payload_fails_verification(env, signing):
    from cryptography.exceptions import InvalidSignature
    body = _get_bundle(env, _add_key(env)).json()
    raw = base64.b64decode(body["payload"]).replace(b'"version":1', b'"version":2')
    with pytest.raises(InvalidSignature):
        signing.verify(base64.b64decode(body["sig"]), raw)


def test_bundle_has_only_enabled_rules_and_approved_templates(env, signing):
    _seed_rules(env)
    payload = _decode(_get_bundle(env, _add_key(env)).json())
    assert [r["id"] for r in payload["rules"]] == ["r-purchased"]
    assert [t["id"] for t in payload["templates"]] == [TPL_A]
    rule = payload["rules"][0]
    assert rule["variables"][0]["fallback"] == "there" and rule["enabled"] is True
    assert payload["templates"][0]["body_text"] == "Hi {{1}}"
    assert "status" not in payload["templates"][0]


@pytest.mark.parametrize("reported,meta,aira,blocked", [
    (110, None, 0, True),   # exactly cap * 1.1, day not reconciled yet
    (109, None, 0, False),
    (10, 130, 10, True),    # Meta saw 120 from the plug-in, more than it reported
    (0, 0, 0, False),
])
def test_blocked_when_used_reaches_cap_plus_ten_percent(env, signing, reported, meta, aira, blocked):
    env.settings[(TENANT, ps.CAP_KEY)] = "100"
    today = _today()
    env.db.rows("private_send_usage").append({"tenant_id": TENANT, "day": today, "event": "purchased",
                                              "template_id": TPL_A, "reported_sent": reported})
    if meta is not None:  # no Meta row yet for the day: the plug-in's own report is all there is
        env.db.rows("private_send_meta_daily").append({"tenant_id": TENANT, "day": today, "volume": meta, "aira_sent": aira})
    limits = _decode(_get_bundle(env, _add_key(env)).json())["limits"]
    assert limits["monthly_cap"] == 100
    assert limits["blocked"] is blocked


def test_no_cap_never_blocks(env, signing):
    env.db.rows("private_send_usage").append({"tenant_id": TENANT, "day": _today(), "event": "purchased",
                                              "template_id": TPL_A, "reported_sent": 10**6})
    limits = _decode(_get_bundle(env, _add_key(env)).json())["limits"]
    assert limits == {"monthly_cap": None, "used": 10**6, "blocked": False}


def test_missing_signing_key_is_503(env, monkeypatch):
    monkeypatch.delenv(ps.SIGNING_ENV, raising=False)
    res = _get_bundle(env, _add_key(env))
    assert res.status_code == 503
    assert res.json()["code"] == "signing_not_configured"


def test_malformed_signing_key_is_503(env, monkeypatch):
    monkeypatch.setenv(ps.SIGNING_ENV, base64.b64encode(b"too-short").decode())
    assert _get_bundle(env, _add_key(env)).json()["code"] == "signing_not_configured"


def test_bundle_rate_limit_is_per_key(env, signing, monkeypatch):
    monkeypatch.setattr(ps_routes, "_bundle_limiter", ps_routes._SlidingWindow(2, 60))
    key, other = _add_key(env), _add_key(env)
    assert [_get_bundle(env, key).status_code for _ in range(3)] == [200, 200, 429]
    assert _get_bundle(env, other).status_code == 200


# ------------------------------------------------------------------ usage

def _post_usage(env, key, body):
    return env.client.post(f"{PUBLIC_BASE}/usage", json=body, headers=_auth(key))


def _metered(env) -> float:
    rows = [r for r in env.db.rows("tenant_usage_counters") if r["metric"] == "private_send_message"]
    return sum(r["used"] for r in rows)


def test_usage_requires_a_valid_key(env, signing):
    res = env.client.post(f"{PUBLIC_BASE}/usage", json={"rows": [_usage_row()]})
    assert res.status_code == 401 and res.json()["code"] == "invalid_key"


def test_usage_with_phone_in_a_row_is_422(env, signing):
    res = _post_usage(env, _add_key(env), {"rows": [_usage_row(phone="919876543210")]})
    assert res.status_code == 422
    assert env.db.rows("private_send_usage") == []


def test_usage_with_phone_at_top_level_is_422(env, signing):
    res = _post_usage(env, _add_key(env), {"rows": [_usage_row()], "phone": "919876543210"})
    assert res.status_code == 422
    assert env.db.rows("private_send_usage") == []


@pytest.mark.parametrize("rows", [
    [],
    [_usage_row()] * 501,
    [_usage_row(day=_today(8))],
    [_usage_row(day=(datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat())],
    [_usage_row(sent=-1)],
    [_usage_row(template_id="not-a-uuid")],
])
def test_usage_validation_rejects_bad_rows(env, signing, rows):
    assert _post_usage(env, _add_key(env), {"rows": rows}).status_code == 422


def test_usage_accepts_the_last_7_days_and_today(env, signing):
    rows = [_usage_row(day=_today(7)), _usage_row(day=_today(0), event="signed_up")]
    res = _post_usage(env, _add_key(env), {"rows": rows})
    assert res.status_code == 200
    assert res.json() == {"ok": True, "accepted": 2}


def test_usage_upsert_is_cumulative_and_idempotent(env, signing):
    key = _add_key(env)
    _post_usage(env, key, {"rows": [_usage_row(sent=5, failed=1)]})
    _post_usage(env, key, {"rows": [_usage_row(sent=8, failed=2)]})
    _post_usage(env, key, {"rows": [_usage_row(sent=8, failed=2)]})  # resend: no change
    rows = env.db.rows("private_send_usage")
    assert len(rows) == 1
    assert (rows[0]["reported_sent"], rows[0]["reported_failed"]) == (8, 2)
    assert rows[0]["tenant_id"] == TENANT
    assert _metered(env) == 8  # 5, then +3, then +0


def test_usage_lower_report_never_lowers_the_stored_total(env, signing):
    key = _add_key(env)
    _post_usage(env, key, {"rows": [_usage_row(sent=8, failed=2)]})
    _post_usage(env, key, {"rows": [_usage_row(sent=3, failed=0)]})  # plug-in lost its store
    row = env.db.rows("private_send_usage")[0]
    assert (row["reported_sent"], row["reported_failed"]) == (8, 2)
    assert _metered(env) == 8


def test_usage_meters_each_row_and_keeps_tenants_apart(env, signing):
    key = _add_key(env)
    rows = [_usage_row(sent=4), _usage_row(event="signed_up", sent=6), _usage_row(day=_today(1), sent=2)]
    assert _post_usage(env, key, {"rows": rows}).status_code == 200
    assert _metered(env) == 12
    assert {r["tenant_id"] for r in env.db.rows("tenant_usage_counters")} == {TENANT}


def test_duplicate_rows_in_one_request_use_the_last(env, signing):
    _post_usage(env, _add_key(env), {"rows": [_usage_row(sent=2), _usage_row(sent=9)]})
    assert env.db.rows("private_send_usage")[0]["reported_sent"] == 9
    assert _metered(env) == 9


# ------------------------------------------------------------------ operator API

def test_operator_create_key_returns_full_key_once_and_stores_only_the_hash(env):
    res = env.client.post(f"{OPERATOR_BASE}/keys")
    assert res.status_code == 200
    body = res.json()
    full = body["key"]
    assert full.startswith("aps_live_") and body["key_prefix"] == full[:13]
    stored = env.db.rows("private_send_keys")[0]
    assert stored["key_hash"] == ps.hash_key(full)
    assert full not in json.dumps(stored)
    assert stored["tenant_id"] == TENANT
    # later reads and the audit log never carry the key
    listing = env.client.get(OPERATOR_BASE)
    assert full not in listing.text and "key_hash" not in listing.text
    assert listing.json()["keys"][0]["key_prefix"] == body["key_prefix"]
    assert full not in json.dumps(env.audit)
    assert env.audit[0]["action"] == "operator.private_send_key_created"


def test_operator_created_key_works_then_revoke_stops_it(env, signing):
    created = env.client.post(f"{OPERATOR_BASE}/keys").json()
    assert _get_bundle(env, created["key"]).status_code == 200
    res = env.client.delete(f"{OPERATOR_BASE}/keys/{created['id']}")
    assert res.json() == {"ok": True}
    row = env.db.rows("private_send_keys")[0]
    assert row["status"] == "revoked" and row["revoked_at"]
    assert _get_bundle(env, created["key"]).json()["code"] == "revoked_key"
    assert env.audit[-1]["action"] == "operator.private_send_key_revoked"


def test_operator_cannot_revoke_another_tenants_key(env):
    key_id = str(uuid.uuid4())
    env.db.rows("private_send_keys").append({"id": key_id, "tenant_id": OTHER_TENANT, "status": "active"})
    assert env.client.delete(f"{OPERATOR_BASE}/keys/{key_id}").status_code == 404
    assert env.db.rows("private_send_keys")[0]["status"] == "active"


def test_operator_unknown_tenant_is_404(env):
    assert env.client.get(f"/api/v1/operator/clients/{uuid.uuid4()}/private-send").status_code == 404


def test_operator_overview_shape_and_usage(env):
    _add_key(env)
    env.settings[(TENANT, ps.CAP_KEY)] = "50000"
    day = _today()
    env.db.rows("private_send_usage").append({"tenant_id": TENANT, "day": day, "event": "purchased",
                                              "template_id": TPL_A, "reported_sent": 100})
    env.db.rows("private_send_meta_daily").append({"tenant_id": TENANT, "day": day, "volume": 400, "aira_sent": 100})
    data = env.client.get(OPERATOR_BASE).json()
    assert data["enabled"] is True and data["monthly_cap"] == 50000
    assert data["reply_mode"] == "aira" and data["offline_grace_hours"] == 6
    assert data["usage"]["days"] == [{"day": day, "reported_sent": 100, "meta_volume": 300}]
    assert data["usage"]["mismatch"] is True  # Meta saw 300, the plug-in reported 100
    assert data["usage"]["period"] == day[:7]
    assert set(data["keys"][0]) == {"id", "key_prefix", "status", "created_at", "last_seen_at",
                                    "plugin_version", "revoked_at"}


def test_operator_overview_no_mismatch_within_tolerance(env):
    day = _today()
    env.db.rows("private_send_usage").append({"tenant_id": TENANT, "day": day, "event": "purchased",
                                              "template_id": TPL_A, "reported_sent": 1000})
    env.db.rows("private_send_meta_daily").append({"tenant_id": TENANT, "day": day, "volume": 1050, "aira_sent": 0})
    assert env.client.get(OPERATOR_BASE).json()["usage"]["mismatch"] is False


def test_settings_patch_saves_grace_and_cap_and_clears_cap(env):
    res = env.client.patch(f"{OPERATOR_BASE}/settings", json={"offline_grace_hours": 12, "monthly_cap": 900})
    assert res.status_code == 200
    assert (res.json()["offline_grace_hours"], res.json()["monthly_cap"]) == (12, 900)
    cleared = env.client.patch(f"{OPERATOR_BASE}/settings", json={"monthly_cap": None})
    assert cleared.json()["monthly_cap"] is None
    assert cleared.json()["offline_grace_hours"] == 12
    assert env.audit[-1]["action"] == "operator.private_send_settings_updated"


@pytest.mark.parametrize("body", [{}, {"offline_grace_hours": 0}, {"offline_grace_hours": 73},
                                  {"reply_mode": "both"}, {"monthly_cap": -1}, {"surprise": 1}])
def test_settings_patch_validation(env, body):
    assert env.client.patch(f"{OPERATOR_BASE}/settings", json=body).status_code in (400, 422)


# ------------------------------------------------------------------ reply mode

def _meta_transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(ps.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def _connect_meta(env):
    env.settings[(TENANT, "meta_access_token")] = "EAAB-secret-token"
    env.settings[(TENANT, "meta_waba_id")] = "waba-1"


def test_reply_mode_meta_failure_is_502_and_setting_unchanged(env, monkeypatch):
    _connect_meta(env)
    env.db.rows("app_settings").append({"tenant_id": TENANT, "key": ps.REPLY_MODE_KEY, "value": "aira"})
    _meta_transport(monkeypatch, lambda req: httpx.Response(400, json={"error": {"message": "Invalid OAuth token"}}))
    res = env.client.patch(f"{OPERATOR_BASE}/settings", json={"reply_mode": "client", "monthly_cap": 5})
    assert res.status_code == 502
    assert _saved(env, ps.REPLY_MODE_KEY) == "aira"
    assert _saved(env, ps.CAP_KEY) is None  # nothing else saved either
    assert "EAAB-secret-token" not in res.text
    assert env.audit == []


def test_reply_mode_network_error_is_502(env, monkeypatch):
    _connect_meta(env)

    def boom(req):
        raise httpx.ConnectError("down")
    _meta_transport(monkeypatch, boom)
    res = env.client.patch(f"{OPERATOR_BASE}/settings", json={"reply_mode": "client"})
    assert res.status_code == 502
    assert _saved(env, ps.REPLY_MODE_KEY) is None


def test_reply_mode_without_meta_connection_is_400(env):
    assert env.client.patch(f"{OPERATOR_BASE}/settings", json={"reply_mode": "client"}).status_code == 400


@pytest.mark.parametrize("mode,method", [("client", "DELETE"), ("aira", "POST")])
def test_reply_mode_calls_subscribed_apps_and_saves(env, monkeypatch, mode, method):
    _connect_meta(env)
    seen = []

    def handler(req):
        seen.append((req.method, str(req.url.path), req.headers.get("authorization"), dict(req.url.params)))
        return httpx.Response(200, json={"success": True})
    _meta_transport(monkeypatch, handler)
    res = env.client.patch(f"{OPERATOR_BASE}/settings", json={"reply_mode": mode})
    assert res.status_code == 200 and res.json()["reply_mode"] == mode
    assert seen == [(method, "/v21.0/waba-1/subscribed_apps", "Bearer EAAB-secret-token", {})]
    assert _saved(env, ps.REPLY_MODE_KEY) == mode


# ------------------------------------------------------------------ Meta reconcile

def test_reconcile_stores_meta_volume_and_aira_sent(env, monkeypatch):
    _connect_meta(env)
    day = datetime.now(timezone.utc).date() - timedelta(days=1)
    seen = []

    def handler(req):
        seen.append(req)
        points = [{"start": 1, "end": 2, "volume": 300}, {"start": 3, "end": 4, "volume": 15}]
        return httpx.Response(200, json={"pricing_analytics": {"data": [{"data_points": points}]}})
    _meta_transport(monkeypatch, handler)
    stamp = day.isoformat()
    env.db.rows("messages").extend([
        {"tenant_id": TENANT, "direction": "outbound", "channel": "whatsapp", "created_at": f"{stamp}T10:00:00Z"},
        {"tenant_id": TENANT, "direction": "outbound", "channel": "whatsapp", "created_at": f"{stamp}T11:00:00Z"},
        {"tenant_id": TENANT, "direction": "inbound", "channel": "whatsapp", "created_at": f"{stamp}T11:00:00Z"},
        {"tenant_id": OTHER_TENANT, "direction": "outbound", "channel": "whatsapp", "created_at": f"{stamp}T11:00:00Z"},
        {"tenant_id": TENANT, "direction": "outbound", "channel": "whatsapp", "created_at": f"{_today()}T01:00:00Z"},
    ])
    import asyncio
    row = asyncio.run(ps.reconcile_meta_volume(env.db, TENANT, day))
    assert row["volume"] == 315 and row["aira_sent"] == 2
    assert env.db.rows("private_send_meta_daily") == [row]
    req = seen[0]
    assert req.headers["authorization"] == "Bearer EAAB-secret-token"
    assert "access_token" not in req.url.params and "EAAB" not in str(req.url)
    assert 'metric_types(["VOLUME"])' in req.url.params["fields"]


def test_process_meta_reconcile_covers_enabled_tenants_and_survives_a_failure(env, monkeypatch):
    _connect_meta(env)
    env.db.rows("tenants").append({"id": "t-broken", "enabled_features": ["private_send"]})
    env.settings[("t-broken", "meta_access_token")] = "tok"
    env.settings[("t-broken", "meta_waba_id")] = "waba-x"

    def handler(req):
        if "waba-x" in req.url.path:
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return httpx.Response(200, json={"pricing_analytics": {"data": [{"data_points": [{"volume": 7}]}]}})
    _meta_transport(monkeypatch, handler)
    import asyncio
    assert asyncio.run(ps.process_meta_reconcile(env.db)) == 1
    assert [r["tenant_id"] for r in env.db.rows("private_send_meta_daily")] == [TENANT]


def test_reconcile_skips_tenant_without_meta_credentials(env):
    import asyncio
    assert asyncio.run(ps.reconcile_meta_volume(env.db, TENANT, datetime.now(timezone.utc).date())) is None


# ------------------------------------------------------------------ tenant dashboard

def test_tenant_overview_enabled(env):
    _add_key(env)
    env.db.rows("message_templates").append({"id": TPL_A, "tenant_id": TENANT, "name": "loan_ready"})
    env.db.rows("private_send_usage").extend([
        {"tenant_id": TENANT, "day": _today(), "event": "purchased", "template_id": TPL_A,
         "reported_sent": 312, "reported_failed": 3},
        {"tenant_id": TENANT, "day": _today(40), "event": "purchased", "template_id": TPL_A,
         "reported_sent": 9, "reported_failed": 0},  # older than 30 days
        {"tenant_id": OTHER_TENANT, "day": _today(), "event": "purchased", "template_id": TPL_A,
         "reported_sent": 99, "reported_failed": 0},
    ])
    data = env.client.get("/api/v1/auto-messages/private-send").json()
    assert data["enabled"] is True and data["reply_mode"] == "aira"
    assert data["key_prefix"].startswith("aps_live_") and len(data["key_prefix"]) == 13
    assert data["days"] == [{"day": _today(), "event": "purchased", "template_id": TPL_A,
                             "template_name": "loan_ready", "sent": 312, "failed": 3}]


def test_tenant_overview_disabled(env):
    env.db.rows("tenants")[0]["enabled_features"] = []
    assert env.client.get("/api/v1/auto-messages/private-send").json() == {
        "enabled": False, "key_prefix": None, "reply_mode": None, "days": []}


# ================================================================== security hardening

import logging

MIGRATION = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "218_private_send.sql"


def _sql() -> str:
    return " ".join(MIGRATION.read_text().split())


# ------------------------------------------------------------------ 1. billing double-count

def test_plugin_reinstall_does_not_meter_the_same_messages_twice(env, signing):
    key = _add_key(env)
    _post_usage(env, key, {"rows": [_usage_row(sent=8)]})
    _post_usage(env, key, {"rows": [_usage_row(sent=0, failed=0)]})  # reinstall: counters reset
    _post_usage(env, key, {"rows": [_usage_row(sent=8)]})            # same 8 messages reported again
    assert env.db.rows("private_send_usage")[0]["reported_sent"] == 8
    assert _metered(env) == 8


def test_record_usage_meters_exactly_the_delta_the_database_function_returns(env, signing, monkeypatch):
    """Two concurrent /usage calls are serialised inside Postgres; Python only trusts its answer."""
    calls = []

    def fake_rpc(name, params):
        calls.append((name, params["p_tenant"], params["p_rows"]))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=7))
    monkeypatch.setattr(env.db, "rpc", fake_rpc)
    res = _post_usage(env, _add_key(env), {"rows": [_usage_row(sent=100)]})
    assert res.status_code == 200
    assert _metered(env) == 7
    assert calls[0][0] == "record_private_send_usage" and calls[0][1] == TENANT
    assert calls[0][2] == [{"day": _today(), "event": "purchased", "template_id": TPL_A, "sent": 100, "failed": 1}]
    assert env.db.rows("private_send_usage") == []  # Python never writes the table itself


def test_usage_rpc_failure_is_a_clean_500_and_meters_nothing(env, signing, monkeypatch):
    def boom(name, params):
        raise RuntimeError("db down")
    monkeypatch.setattr(env.db, "rpc", boom)
    res = _post_usage(env, _add_key(env), {"rows": [_usage_row(sent=5)]})
    assert res.status_code == 500 and res.json()["code"] == "usage_not_saved"
    assert _metered(env) == 0


def test_migration_defines_the_atomic_usage_function_with_locked_down_grants():
    sql = _sql()
    assert "CREATE OR REPLACE FUNCTION record_private_send_usage(p_tenant uuid, p_rows jsonb) RETURNS integer" in sql
    assert "SET search_path = public" in sql
    assert "SECURITY DEFINER" not in sql
    assert "GREATEST" in sql
    assert "REVOKE EXECUTE ON FUNCTION record_private_send_usage(uuid, jsonb) FROM public, anon, authenticated" in sql
    assert "GRANT EXECUTE ON FUNCTION record_private_send_usage(uuid, jsonb) TO service_role" in sql


# ------------------------------------------------------------------ 2. leaked key cannot inflate usage

@pytest.mark.parametrize("field", ["sent", "failed"])
def test_usage_row_above_the_daily_plausibility_cap_is_422(env, signing, field):
    key = _add_key(env)
    too_big = ps.MAX_DAILY_PER_TEMPLATE + 1
    assert ps.MAX_DAILY_PER_TEMPLATE == 100_000
    assert _post_usage(env, key, {"rows": [_usage_row(**{field: too_big})]}).status_code == 422
    assert env.db.rows("private_send_usage") == []
    assert _post_usage(env, key, {"rows": [_usage_row(**{field: ps.MAX_DAILY_PER_TEMPLATE})]}).status_code == 200


class _Oct15(datetime):
    """The service's clock pinned mid-month: a real "yesterday" falls in last month on the 1st."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 15, 12, tzinfo=tz)


def test_reconciled_day_uses_meta_volume_not_the_inflated_report(env, signing, monkeypatch):
    monkeypatch.setattr(ps, "datetime", _Oct15)
    env.settings[(TENANT, ps.CAP_KEY)] = "100"
    y = "2026-10-14"
    env.db.rows("private_send_usage").append({"tenant_id": TENANT, "day": y, "event": "purchased",
                                              "template_id": TPL_A, "reported_sent": 99_000})
    env.db.rows("private_send_meta_daily").append({"tenant_id": TENANT, "day": y, "volume": 40, "aira_sent": 10})
    limits = _decode(_get_bundle(env, _add_key(env)).json())["limits"]
    assert limits["used"] == 30 and limits["blocked"] is False


def test_unreconciled_day_still_uses_the_report_and_days_add_up(env, signing):
    env.settings[(TENANT, ps.CAP_KEY)] = "1000"
    first_of_month = datetime.now(timezone.utc).date().replace(day=1)
    day_a, day_b = first_of_month.isoformat(), (first_of_month + timedelta(days=1)).isoformat()
    for day, sent in ((day_a, 500), (day_b, 20)):
        env.db.rows("private_send_usage").append({"tenant_id": TENANT, "day": day, "event": "purchased",
                                                  "template_id": TPL_A, "reported_sent": sent})
    env.db.rows("private_send_meta_daily").append({"tenant_id": TENANT, "day": day_a, "volume": 70, "aira_sent": 0})
    totals = ps.month_totals(env.db, TENANT, datetime.now(timezone.utc).date())
    assert totals["used"] == 70 + 20  # day_a: Meta is truth; day_b: no Meta row yet, report counts


# ------------------------------------------------------------------ 3. /usage rate limit + template check

def test_usage_rate_limit_is_per_key(env, signing, monkeypatch):
    monkeypatch.setattr(ps_routes, "_usage_limiter", ps_routes._SlidingWindow(2, 60))
    key, other = _add_key(env), _add_key(env)
    body = {"rows": [_usage_row()]}
    assert [_post_usage(env, key, body).status_code for _ in range(3)] == [200, 200, 429]
    res = _post_usage(env, key, body)
    assert res.json()["code"] == "rate_limited" and res.headers["retry-after"] == "60"
    assert _post_usage(env, other, body).status_code == 200


def test_usage_default_limit_is_30_per_minute():
    assert ps_routes.USAGE_LIMIT_PER_MINUTE == 30


def test_usage_with_template_of_another_tenant_is_422_and_stores_nothing(env, signing):
    _seed_rules(env)  # TPL_OTHER belongs to OTHER_TENANT
    res = _post_usage(env, _add_key(env), {"rows": [_usage_row(), _usage_row(template_id=TPL_OTHER)]})
    assert res.status_code == 422 and res.json()["code"] == "unknown_template"
    assert env.db.rows("private_send_usage") == []
    assert _metered(env) == 0


def test_usage_with_random_template_id_is_422(env, signing):
    res = _post_usage(env, _add_key(env), {"rows": [_usage_row(template_id=str(uuid.uuid4()))]})
    assert res.status_code == 422 and res.json()["code"] == "unknown_template"


def test_usage_checks_templates_with_one_query_per_request(env, signing):
    rows = [_usage_row(event="purchased"), _usage_row(event="signed_up"), _usage_row(day=_today(1))]
    key = _add_key(env)
    env.db.lookups.clear()
    assert _post_usage(env, key, {"rows": rows}).status_code == 200
    assert env.db.lookups.count("message_templates") == 1


# ------------------------------------------------------------------ 4. unauthenticated lookups

def test_per_ip_limit_stops_key_guessing_before_any_database_lookup(env, signing, monkeypatch):
    monkeypatch.setattr(ps_routes, "_ip_limiter", ps_routes._SlidingWindow(2, 60))
    guess = "aps_live_" + "g" * 32
    env.db.lookups.clear()
    codes = [env.client.get(f"{PUBLIC_BASE}/bundle", headers={"Authorization": f"Bearer {guess}"}) for _ in range(3)]
    assert [c.status_code for c in codes] == [401, 401, 429]
    assert codes[2].json()["code"] == "rate_limited" and codes[2].headers["retry-after"] == "60"
    assert env.db.lookups.count("private_send_keys") == 1  # 2nd was negative-cached, 3rd never reached the DB


def test_per_ip_limit_also_guards_usage_and_uses_the_edge_client_ip(env, signing, monkeypatch):
    monkeypatch.setattr(ps_routes, "_ip_limiter", ps_routes._SlidingWindow(1, 60))
    body = {"rows": [_usage_row()]}
    bad = {"Authorization": "Bearer nope"}
    one = {**bad, "cf-connecting-ip": "1.1.1.1"}
    two = {**bad, "cf-connecting-ip": "2.2.2.2"}
    post = lambda h: env.client.post(f"{PUBLIC_BASE}/usage", json=body, headers=h).status_code
    assert [post(one), post(one), post(two)] == [401, 429, 401]


def test_ip_key_is_the_rightmost_forwarded_for_entry(env, signing, monkeypatch):
    monkeypatch.setattr(ps_routes, "_ip_limiter", ps_routes._SlidingWindow(1, 60))
    get = lambda xff: env.client.get(f"{PUBLIC_BASE}/bundle", headers={"Authorization": "Bearer nope", "X-Forwarded-For": xff}).status_code
    # a spoofed leftmost entry must not dodge the limit
    assert [get("9.9.9.1, 5.5.5.5"), get("9.9.9.2, 5.5.5.5"), get("9.9.9.3, 6.6.6.6")] == [401, 429, 401]


def test_per_ip_limit_applies_before_the_key_is_known_to_be_valid(env, signing, monkeypatch):
    monkeypatch.setattr(ps_routes, "_ip_limiter", ps_routes._SlidingWindow(1, 60))
    key = _add_key(env)
    assert [_get_bundle(env, key).status_code, _get_bundle(env, key).status_code] == [200, 429]


def test_unknown_key_lookups_are_cached_for_60_seconds(env, monkeypatch):
    guess = "aps_live_" + "u" * 32
    clock = [1000.0]
    monkeypatch.setattr(ps.time, "monotonic", lambda: clock[0])
    lookups = lambda: env.db.lookups.count("private_send_keys")
    for _ in range(3):
        with pytest.raises(ps.PrivateSendError) as e:
            ps.find_key(env.db, guess)
        assert e.value.code == "invalid_key"
    assert lookups() == 1
    clock[0] += ps.UNKNOWN_KEY_TTL_SECONDS + 1
    with pytest.raises(ps.PrivateSendError):
        ps.find_key(env.db, guess)
    assert lookups() == 2
    assert ps.UNKNOWN_KEY_TTL_SECONDS == 60


def test_unknown_key_cache_is_bounded(env):
    for i in range(ps.UNKNOWN_KEY_CACHE_SIZE + 50):
        with pytest.raises(ps.PrivateSendError):
            ps.find_key(env.db, f"aps_live_{i:032d}")
    assert ps.UNKNOWN_KEY_CACHE_SIZE == 1024
    assert ps.unknown_key_cache_len() <= ps.UNKNOWN_KEY_CACHE_SIZE


def test_revoked_and_valid_keys_are_never_negative_cached(env, signing):
    revoked = _add_key(env, status="revoked")
    for _ in range(2):
        assert _get_bundle(env, revoked).json()["code"] == "revoked_key"
    assert ps.unknown_key_cache_len() == 0


# ------------------------------------------------------------------ 5. settings drift

def test_cap_write_failure_is_a_500_not_a_silent_success(env):
    env.db.failing_tables.add("app_settings")
    res = env.client.patch(f"{OPERATOR_BASE}/settings", json={"monthly_cap": 900})
    assert res.status_code == 500
    assert "could not save" in res.json()["detail"].lower()
    assert env.audit == []


def test_grace_write_failure_is_a_500(env):
    env.db.failing_tables.add("app_settings")
    assert env.client.patch(f"{OPERATOR_BASE}/settings", json={"offline_grace_hours": 12}).status_code == 500


def test_settings_are_written_to_app_settings_with_the_save_setting_shape(env):
    assert env.client.patch(f"{OPERATOR_BASE}/settings", json={"monthly_cap": 900}).status_code == 200
    assert env.db.rows("app_settings") == [
        {"key": ps.CAP_KEY, "value": "900", "tenant_id": TENANT, "is_secret": False}
    ]


def test_reply_mode_db_failure_reverts_the_meta_subscription_and_logs(env, monkeypatch, caplog):
    _connect_meta(env)
    seen = []

    def handler(req):
        seen.append(req.method)
        return httpx.Response(200, json={"success": True})
    _meta_transport(monkeypatch, handler)
    env.db.failing_tables.add("app_settings")
    with caplog.at_level(logging.ERROR, logger=ps.logger.name):
        res = env.client.patch(f"{OPERATOR_BASE}/settings", json={"reply_mode": "client"})
    assert res.status_code == 500
    assert seen == ["DELETE", "POST"]  # unsubscribed, DB write failed, reverted to the default "aira"
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert "EAAB-secret-token" not in res.text


def test_reply_mode_revert_failure_is_still_a_500_and_logged(env, monkeypatch, caplog):
    _connect_meta(env)

    def handler(req):
        if req.method == "POST":  # the revert back to the default "aira" fails
            return httpx.Response(400, json={"error": {"message": "nope"}})
        return httpx.Response(200, json={"success": True})
    _meta_transport(monkeypatch, handler)
    env.db.failing_tables.add("app_settings")
    with caplog.at_level(logging.ERROR, logger=ps.logger.name):
        res = env.client.patch(f"{OPERATOR_BASE}/settings", json={"reply_mode": "client"})
    assert res.status_code == 500
    assert any("revert" in r.getMessage().lower() for r in caplog.records)


# ------------------------------------------------------------------ 6. revoke validates the key id

def test_operator_revoke_with_a_non_uuid_key_id_is_422(env):
    res = env.client.delete(f"{OPERATOR_BASE}/keys/not-a-uuid")
    assert res.status_code == 422
    assert env.audit == []


def test_operator_revoke_with_a_uuid_still_works(env):
    key_id = str(uuid.uuid4())
    env.db.rows("private_send_keys").append({"id": key_id, "tenant_id": TENANT, "key_prefix": "aps_live_xxxx",
                                             "key_hash": "h", "status": "active"})
    assert env.client.delete(f"{OPERATOR_BASE}/keys/{key_id}").status_code == 200
    assert env.db.rows("private_send_keys")[0]["status"] == "revoked"


# ------------------------------------------------------------------ 7. migration grants / RLS

@pytest.mark.parametrize("table", ["private_send_keys", "private_send_usage", "private_send_meta_daily"])
def test_migration_revokes_anon_and_authenticated_on_every_private_send_table(table):
    assert f"REVOKE ALL ON {table} FROM anon, authenticated" in _sql()


def test_migration_has_no_tenant_member_select_policies_left():
    sql = _sql()
    assert "CREATE POLICY" not in sql
    assert "DROP POLICY IF EXISTS private_send_usage_tenant_member_select ON private_send_usage" in sql
    assert "DROP POLICY IF EXISTS private_send_meta_daily_tenant_member_select ON private_send_meta_daily" in sql


# ------------------------------------------------------------------ Auto Messages v2: custom events, no quiet hours

def _add_custom_event(env, key="kundli_ready", tenant=TENANT):
    env.db.rows("auto_message_events").append({"id": str(uuid.uuid4()), "tenant_id": tenant, "key": key, "label": key})


def test_usage_accepts_a_custom_event_key_the_tenant_has(env, signing):
    _add_custom_event(env)
    res = _post_usage(env, _add_key(env), {"rows": [_usage_row(event="kundli_ready", sent=3)]})
    assert res.status_code == 200
    assert env.db.rows("private_send_usage")[0]["event"] == "kundli_ready"


def test_usage_for_a_deleted_or_unknown_custom_event_is_accepted_and_billed(env, signing):
    """The owner deleted the event (or it never existed here): the plug-in already sent those
    messages, so the row is stored and billed. Rejecting it would drop the whole batch."""
    _add_custom_event(env, tenant=OTHER_TENANT)  # someone else's event must not matter either
    res = _post_usage(env, _add_key(env), {"rows": [_usage_row(), _usage_row(event="kundli_ready", sent=4)]})
    assert res.status_code == 200 and res.json() == {"ok": True, "accepted": 2}
    assert sorted(r["event"] for r in env.db.rows("private_send_usage")) == ["kundli_ready", "purchased"]
    assert _metered(env) == 9  # 5 + 4


@pytest.mark.parametrize("event", ["Kundli Ready", "1abc", "a", "has-dash", "x" * 41, ""])
def test_usage_event_must_be_a_slug(env, signing, event):
    assert _post_usage(env, _add_key(env), {"rows": [_usage_row(event=event)]}).status_code == 422


def test_usage_never_looks_up_events(env, signing):
    _add_custom_event(env)
    rows = [_usage_row(event="kundli_ready"), _usage_row(event="purchased"), _usage_row(day=_today(1), event="gone_event")]
    key = _add_key(env)
    env.db.lookups.clear()
    assert _post_usage(env, key, {"rows": rows}).status_code == 200
    assert env.db.lookups.count("auto_message_events") == 0
    assert env.db.lookups.count("message_templates") == 1  # the ownership check stays


def test_bundle_has_no_quiet_hours_no_rule_delay_and_still_carries_each_template_category(env, signing):
    _seed_rules(env)
    env.db.rows("auto_message_rules")[1]["enabled"] = True  # r-interested carries delay_minutes=5 in the table
    payload = _decode(_get_bundle(env, _add_key(env)).json())
    assert "quiet_hours" not in payload
    assert {r["event"] for r in payload["rules"]} == {"interested", "purchased"}
    for rule in payload["rules"]:
        assert "delay_minutes" not in rule
        assert set(rule) == {"id", "event", "template_id", "variables", "button_param", "enabled"}
    assert payload["templates"][0]["category"] == "UTILITY"


def test_reply_mode_defaults_to_aira_everywhere_when_unset(env):
    """'client' unsubscribes Anril from the whole WhatsApp number, so it must be an explicit choice."""
    assert ps.get_reply_mode(TENANT) == "aira"
    _add_key(env)
    assert env.client.get(OPERATOR_BASE).json()["reply_mode"] == "aira"
    assert env.client.get("/api/v1/auto-messages/private-send").json()["reply_mode"] == "aira"


def test_reply_mode_unrecognised_stored_value_falls_back_to_aira(env):
    env.settings[(TENANT, ps.REPLY_MODE_KEY)] = "both"
    assert ps.get_reply_mode(TENANT) == "aira"


def test_reply_mode_explicit_client_is_still_honoured(env):
    _add_key(env)
    env.settings[(TENANT, ps.REPLY_MODE_KEY)] = "client"
    assert env.client.get(OPERATOR_BASE).json()["reply_mode"] == "client"
    assert env.client.get("/api/v1/auto-messages/private-send").json()["reply_mode"] == "client"


def test_bundle_includes_a_rule_for_a_custom_event(env, signing):
    _seed_rules(env)
    _add_custom_event(env)
    env.db.rows("auto_message_rules").append(
        {"id": "r-kundli", "tenant_id": TENANT, "event": "kundli_ready", "template_id": TPL_A, "delay_minutes": 0,
         "variables": [], "button_param": None, "enabled": True})
    payload = _decode(_get_bundle(env, _add_key(env)).json())
    assert sorted(r["event"] for r in payload["rules"]) == ["kundli_ready", "purchased"]

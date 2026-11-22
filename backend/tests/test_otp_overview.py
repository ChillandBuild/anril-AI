"""OTP Overview (services/otp_overview.py + routes/otp_overview.py) against the in-memory
FakeSupabase. Timestamps are written with the +05:30 offset (like the app's IST maths) because the
fake compares timestamps as strings."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role
from app.routes import otp_overview as routes
from app.services import otp_overview as svc
from fake_supabase import FakeSupabase

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 15, 0, tzinfo=IST)
KEY_A = "aaaaaaaa-0000-0000-0000-000000000001"


def ts(day: int, month: int = 11, hour: int = 10) -> str:
    return datetime(2026, month, day, hour, 0, tzinfo=IST).isoformat()


_n = [0]


def code(db, tenant=TENANT, day=10, month=11, **kw):
    _n[0] += 1
    row = {"id": f"{_n[0]:08d}", "tenant_id": tenant, "source": "anril", "origin": "api", "status": "pending",
           "sms_status": "none", "whatsapp_status": "none", "fallback_sent_at": None, "api_key_id": None,
           "expires_at": ts(day, month, 11), "created_at": ts(day, month), **kw}
    db.rows("otp_requests").append(row)
    return row


@pytest.fixture(autouse=True)
def _fresh_cache():
    svc._cache.clear()
    yield
    svc._cache.clear()


@pytest.fixture
def db():
    d = FakeSupabase()
    d.rows("otp_api_keys").append({"id": KEY_A, "tenant_id": TENANT, "key_prefix": "anr_otp_live_ab12"})
    d.rows("otp_settings").append({"tenant_id": TENANT, "wa_template_name": "login_code", "wa_template_language": "en",
                                   "sms_message_id": "14892", "status_webhook_url": None})
    return d


def run(db, tenant=TENANT):
    return svc.overview(db, tenant, now=NOW)


def health(result, key):
    return next((h for h in result["health"] if h["key"] == key), None)


# ---------------------------------------------------------------- month numbers

def test_month_counts_and_change_pct(db):
    for _ in range(6):
        code(db, status="verified", sms_status="delivered")
    code(db, status="locked", whatsapp_status="sent", fallback_sent_at=ts(10))
    code(db, status="not_requested", whatsapp_status="sent")
    code(db, status="failed", sms_status="failed")
    for _ in range(5):
        code(db, month=10, day=15, status="verified")        # last month
    code(db, month=9, day=28)                                # older: ignored
    code(db, month=12, day=1)                                # next month: ignored
    r = run(db)
    m = r["month"]
    assert m["sent"] == 9 and m["prev_month_sent"] == 5
    assert m["change_pct"] == 80                             # (9-5)/5
    assert m["verified"] == 6 and m["used_pct"] == 67        # 6 of 9 Anril-made
    assert m["by_sms"] == 7 and m["by_whatsapp"] == 2 and m["backups"] == 1
    assert (m["locked"], m["not_requested"], m["failed"]) == (1, 1, 1)
    assert r["available"] is True


def test_change_pct_null_when_last_month_empty_and_down_is_negative(db):
    code(db)
    assert run(db)["month"]["change_pct"] is None
    for _ in range(4):
        code(db, month=10, day=3)
    assert run(db)["month"]["change_pct"] == -75             # 1 vs 4


def test_used_pct_counts_only_anril_made_codes(db):
    code(db, status="verified")
    code(db, status="pending", expires_at=ts(30))
    for _ in range(8):
        code(db, source="client", status="pending")          # Anril can't see these being used
    m = run(db)["month"]
    assert m["sent"] == 10 and m["used_pct"] == 50
    only_client = FakeSupabase()
    code(only_client, source="client")
    assert run(only_client)["month"]["used_pct"] is None


def test_month_starts_at_indian_midnight(db):
    code(db, day=1, created_at=datetime(2026, 11, 1, 0, 10, tzinfo=IST).isoformat())
    code(db, month=10, day=31, created_at=datetime(2026, 10, 31, 23, 50, tzinfo=IST).isoformat())
    m = run(db)["month"]
    assert m["sent"] == 1 and m["prev_month_sent"] == 1


def test_daily_7_covers_last_seven_indian_days(db):
    code(db, day=20, status="verified")
    code(db, day=20)
    code(db, day=14)
    code(db, day=13)                                         # 8th day back: not in the bars
    code(db, month=10, day=31)                               # inside the 7 days? no: 20 Nov - 6 = 14 Nov
    d = run(db)["daily_7"]
    assert [x["day"] for x in d] == [f"2026-11-{n}" for n in range(14, 21)]
    assert d[-1] == {"day": "2026-11-20", "sent": 2, "verified": 1}
    assert d[0]["sent"] == 1 and sum(x["sent"] for x in d) == 3


def test_daily_7_across_a_month_start(db):
    now = datetime(2026, 11, 3, 9, 0, tzinfo=IST)
    code(db, month=10, day=29)
    code(db, day=3)
    r = svc.overview(db, TENANT, now=now)
    assert r["daily_7"][0]["day"] == "2026-10-28"
    assert sum(x["sent"] for x in r["daily_7"]) == 2
    assert r["month"]["sent"] == 1 and r["month"]["prev_month_sent"] == 1


# ---------------------------------------------------------------- sources

def test_sources_group_by_key_and_origin(db):
    for _ in range(3):
        code(db, api_key_id=KEY_A, status="verified")
    code(db, api_key_id=KEY_A)
    code(db, origin="dashboard", status="verified")
    code(db, origin="dashboard", status="expired")
    code(db, origin="bot")
    s = run(db)["sources"]
    assert [x["sent"] for x in s] == [4, 2, 1]
    assert s[0]["label"] == "Website or app, key anr_otp_live_ab12…" and s[0]["used_pct"] == 75
    assert [x["key"] for x in s] == [f"key:{KEY_A}", "origin:dashboard", "origin:bot"]
    assert s[1] == {"key": "origin:dashboard", "label": "Test codes from the dashboard", "sent": 2, "used_pct": 50}
    assert s[2]["label"] == "The WhatsApp bot" and s[2]["used_pct"] == 0


def test_sources_have_unique_keys_and_distinct_labels_when_key_lookup_fails(db):
    other = "aaaaaaaa-0000-0000-0000-000000000002"
    code(db, api_key_id=KEY_A)
    code(db, api_key_id=KEY_A)
    code(db, api_key_id=other)
    code(db, origin="api")
    real = db.table

    def table(name):
        if name == "otp_api_keys":
            raise RuntimeError("boom")
        return real(name)
    db.table = table
    s = run(db)["sources"]
    assert len({x["key"] for x in s}) == len(s) == 3
    assert len({x["label"] for x in s}) == 3
    assert {x["label"] for x in s} == {"Website or app 1", "Website or app 2", "Your website or app"}


def test_sources_used_pct_null_for_client_made_only(db):
    code(db, source="client", api_key_id=KEY_A)
    assert run(db)["sources"][0]["used_pct"] is None


# ---------------------------------------------------------------- last month by count, cache, columns

def test_last_month_is_counted_not_paged(db):
    for _ in range(5):
        code(db, month=10, day=15)
    code(db)
    seen = {"selects": [], "ranges": 0}
    real = db.table

    def table(name):
        q = real(name)
        if name != "otp_requests":
            return q
        real_select, real_range = q.select, q.range

        def select(cols="*", count=None):
            seen["selects"].append(count)
            return real_select(cols, count=count)

        def rng(a, b):
            seen["ranges"] += 1
            return real_range(a, b)
        q.select, q.range = select, rng
        return q
    db.table = table
    r = run(db)
    assert r["month"]["prev_month_sent"] == 5 and r["month"]["sent"] == 1
    assert seen["selects"].count("exact") == 1       # the one count query
    assert seen["ranges"] == 1                       # one page of the current month only


def test_overview_is_cached_per_tenant_for_a_minute(db, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(svc.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    code(db)
    first = svc.overview(db, TENANT)
    code(db)
    assert svc.overview(db, TENANT) is first                     # cached
    assert svc.overview(db, OTHER)["month"]["sent"] == 0         # other tenant has its own entry
    clock["t"] += svc.CACHE_SECONDS + 1
    assert svc.overview(db, TENANT)["month"]["sent"] == 2


def test_failed_reads_are_not_cached(db, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    real = db.table
    db.table = lambda name: (_ for _ in ()).throw(RuntimeError("down")) if name == "otp_requests" else real(name)
    assert svc.overview(db, TENANT)["available"] is False
    db.table = real
    assert svc.overview(db, TENANT)["available"] is True


def test_settings_read_leaves_out_the_signing_secret(db):
    db.rows("otp_settings")[0]["status_webhook_secret"] = "whsec_secret"
    asked = []
    real = db.table

    def table(name):
        q = real(name)
        if name == "otp_settings":
            real_select = q.select
            q.select = lambda cols="*", count=None: (asked.append(cols), real_select(cols, count=count))[1]
        return q
    db.table = table
    run(db)
    assert asked and all("secret" not in c and c != "*" for c in asked)


# ---------------------------------------------------------------- balance

def test_balance_from_wallet_or_null(db):
    assert run(db)["balance"] == {"sms_left": None, "checked_at": None, "low_below": 500}
    db.rows("sms_wallet").append({"tenant_id": TENANT, "sms_count": 1240, "checked_at": "2026-11-20T09:00:00+00:00"})
    db.rows("sms_wallet").append({"tenant_id": OTHER, "sms_count": 7, "checked_at": "2026-11-20T09:00:00+00:00"})
    b = run(db)["balance"]
    assert b["sms_left"] == 1240 and b["checked_at"] == "2026-11-20T09:00:00+00:00"


# ---------------------------------------------------------------- health

def test_whatsapp_template_approved_not_approved_and_not_set(db):
    db.rows("message_templates").append({"tenant_id": TENANT, "name": "login_code", "language": "en", "status": "APPROVED"})
    db.rows("message_templates").append({"tenant_id": OTHER, "name": "login_code", "language": "en", "status": "REJECTED"})
    h = health(run(db), "whatsapp_template")
    assert h["ok"] is True
    db.rows("message_templates")[0]["status"] = "PENDING"
    h = health(run(db), "whatsapp_template")
    assert h["ok"] is False and "pending" in h["detail"]
    db.rows("message_templates").clear()
    assert health(run(db), "whatsapp_template")["ok"] is False          # chosen but missing
    db.rows("otp_settings")[0].update(wa_template_name=None)
    h = health(run(db), "whatsapp_template")
    assert h["ok"] is None and h["detail"] == "Not set up"


def test_sms_template_ready_or_unknown(db):
    assert health(run(db), "sms_template")["ok"] is None
    db.rows("sms_templates").append({"tenant_id": TENANT, "message_id": "14892", "status": "submitted"})
    assert health(run(db), "sms_template")["ok"] is None
    db.rows("sms_templates").append({"tenant_id": TENANT, "message_id": "14892", "status": "ready"})
    assert health(run(db), "sms_template")["ok"] is True
    db.rows("otp_settings")[0].update(sms_message_id=None)
    assert health(run(db), "sms_template")["detail"] == "Not set up"


def test_website_updates_only_when_a_url_is_set(db):
    assert health(run(db), "website_updates") is None
    db.rows("otp_settings")[0]["status_webhook_url"] = "https://client.example.com/otp"
    assert health(run(db), "website_updates")["ok"] is True
    recent = datetime.now(timezone.utc).isoformat()
    for tenant in (TENANT, TENANT, OTHER):
        db.rows("otp_status_events").append({"id": f"e{len(db.rows('otp_status_events'))}", "tenant_id": tenant,
                                             "status": "failed", "created_at": recent})
    h = health(run(db), "website_updates")
    assert h["ok"] is False and h["detail"].startswith("2 updates")


def test_unused_codes_health(db):
    assert health(run(db), "unused_codes")["ok"] is None                 # nothing made by Anril
    for _ in range(8):
        code(db, status="verified")
    code(db, status="expired")
    code(db, status="pending", expires_at=ts(11))                        # pending but past expiry: counts
    code(db, status="pending", expires_at=ts(25))                        # still valid: does not
    h = health(run(db), "unused_codes")
    assert h["ok"] is True and "18%" in h["detail"] and "2 of 11" in h["detail"]
    for _ in range(4):
        code(db, status="expired")
    assert health(run(db), "unused_codes")["ok"] is False


# ---------------------------------------------------------------- in short, numbers

def test_in_short_sentence(db):
    assert run(db)["in_short"] == "No codes were sent this month yet."
    month = {"sent": 2704, "used_pct": 93, "by_sms": 212}
    assert svc.in_short(month) == "This month 2,704 codes were sent and 93% were used. 212 went by SMS."
    assert svc.in_short({"sent": 1, "used_pct": None, "by_sms": 0}) == "This month 1 code was sent."
    assert "aren't available" in svc.in_short(month, available=False)
    code(db, status="verified", sms_status="delivered")
    assert run(db)["in_short"] == "This month 1 code was sent and 100% were used. 1 went by SMS."


def test_indian_grouping():
    assert [svc.indian(n) for n in (0, 999, 1000, 2704, 100000, 1234567, 12345678)] == \
        ["0", "999", "1,000", "2,704", "1,00,000", "12,34,567", "1,23,45,678"]


# ---------------------------------------------------------------- degrade + isolation

def test_missing_tables_degrade_instead_of_crashing(db):
    real = db.table

    def table(name):
        if name in ("otp_requests", "otp_api_keys", "sms_wallet", "message_templates", "sms_templates", "otp_settings"):
            raise RuntimeError(f'relation "{name}" does not exist')
        return real(name)
    db.table = table
    r = run(db)
    assert r["available"] is False
    assert r["month"]["sent"] == 0 and r["sources"] == [] and r["balance"]["sms_left"] is None
    assert len(r["daily_7"]) == 7 and "aren't available" in r["in_short"]
    assert all(h["ok"] is None for h in r["health"])


def test_one_broken_table_only_blanks_its_own_part(db):
    code(db, status="verified")
    real = db.table

    def table(name):
        if name == "sms_wallet":
            raise RuntimeError("boom")
        return real(name)
    db.table = table
    r = run(db)
    assert r["available"] is True and r["month"]["sent"] == 1 and r["balance"]["sms_left"] is None


def test_other_tenants_codes_never_counted(db):
    code(db, tenant=OTHER, status="verified")
    code(db, tenant=OTHER, month=10, day=4)
    db.rows("otp_api_keys").append({"id": "bbbbbbbb-0000-0000-0000-000000000002", "tenant_id": OTHER, "key_prefix": "anr_otp_live_zz99"})
    r = run(db)
    assert r["month"]["sent"] == 0 and r["month"]["prev_month_sent"] == 0 and r["sources"] == []
    assert run(db, OTHER)["month"]["sent"] == 1


def test_pages_past_1000_rows(db):
    for _ in range(1005):
        code(db)
    assert run(db)["month"]["sent"] == 1005


# ---------------------------------------------------------------- route + permission

def _client(db, monkeypatch, ctx):
    monkeypatch.setattr(routes, "get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/otp-overview")
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    return TestClient(app)


@pytest.mark.parametrize("ctx,status", [
    ({"tenant_id": TENANT, "role": "owner", "permissions": []}, 200),
    ({"tenant_id": TENANT, "role": "staff", "permissions": ["sms.view"]}, 200),
    ({"tenant_id": TENANT, "role": "staff", "permissions": ["settings.manage"]}, 200),   # manage implies view
    ({"tenant_id": TENANT, "role": "staff", "permissions": ["leads.view", "deals.view"]}, 403),
    ({"tenant_id": TENANT, "role": "staff", "permissions": []}, 403),
])
def test_route_permission(db, monkeypatch, ctx, status):
    r = _client(db, monkeypatch, ctx).get("/api/v1/otp-overview")
    assert r.status_code == status
    if status == 200:
        assert set(r.json()) == {"available", "month", "daily_7", "sources", "balance", "health", "in_short"}


def test_route_reads_the_callers_tenant(db, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    code(db, tenant=OTHER)
    code(db)
    code(db)
    ctx = {"tenant_id": TENANT, "role": "owner", "permissions": []}
    body = _client(db, monkeypatch, ctx).get("/api/v1/otp-overview").json()
    assert body["month"]["sent"] == 2

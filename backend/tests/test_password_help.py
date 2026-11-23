"""v9.2 #27 Forgot password = a request to the Anril team (public form)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import password_help as svc
from app.routes.auto_messages import _SlidingWindow
from tests.fake_supabase import FakeSupabase


@pytest.fixture()
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(svc, "get_supabase", lambda: fake)
    monkeypatch.setattr(svc, "_identifier_limiter", _SlidingWindow(svc.PER_IDENTIFIER_PER_HOUR, 3600))
    monkeypatch.setattr(svc, "_ip_limiter", _SlidingWindow(svc.PER_IP_PER_HOUR, 3600))
    return fake


def post(body):
    # No Authorization header at all: the route is public.
    return TestClient(app).post("/api/v1/password-help/request", json=body)


def test_public_request_is_stored_and_reply_is_fixed(db):
    res = post({"identifier": " Owner@Shop.com ", "business_name": "Sri Stores", "note": "call me after 5"})
    assert res.status_code == 200
    assert res.json() == {"message": svc.REPLY}
    rows = db.rows("password_help_requests")
    assert len(rows) == 1
    assert rows[0]["identifier"] == "Owner@Shop.com"
    assert rows[0]["status"] == "open" and rows[0].get("tenant_id") is None
    assert rows[0]["ip_hash"] and "testclient" not in rows[0]["ip_hash"]


def test_same_reply_whether_or_not_it_was_stored(db, monkeypatch):
    stored = post({"identifier": "a@b.com"}).json()
    monkeypatch.setattr(svc, "get_supabase", lambda: (_ for _ in ()).throw(RuntimeError("table missing")))
    failed = post({"identifier": "c@d.com"}).json()
    assert stored == failed == {"message": svc.REPLY}


def test_empty_identifier_is_rejected(db):
    assert post({"identifier": "   "}).status_code == 422
    assert db.rows("password_help_requests") == []


def test_too_long_values_are_rejected(db):
    assert post({"identifier": "x" * 121}).status_code == 422
    assert post({"identifier": "a@b.com", "business_name": "x" * 121}).status_code == 422
    assert post({"identifier": "a@b.com", "note": "x" * 301}).status_code == 422


def test_three_per_identifier_per_hour_same_reply_no_extra_rows(db):
    for _ in range(5):
        res = post({"identifier": "owner@shop.com"})
        assert res.status_code == 200 and res.json()["message"] == svc.REPLY
    assert len(db.rows("password_help_requests")) == 3


def test_phone_typed_two_ways_counts_as_one_identifier(db):
    for ident in ("+91 98765 43210", "98765-43210", "9876543210", "098765 43210"):
        post({"identifier": ident})
    assert len(db.rows("password_help_requests")) == 3


def test_ten_per_ip_per_hour(db):
    for i in range(14):
        post({"identifier": f"person{i}@shop.com"})
    assert len(db.rows("password_help_requests")) == svc.PER_IP_PER_HOUR


def test_control_characters_are_cleaned(db):
    post({"identifier": "a@b.com", "note": "line1\nline2\x00x"})
    assert db.rows("password_help_requests")[0]["note"] == "line1 line2 x"


def test_operator_list_needs_a_system_admin(db):
    client = TestClient(app)
    assert client.get("/api/v1/password-help/requests").status_code in (401, 403)
    assert client.post("/api/v1/password-help/requests/abc/done").status_code in (401, 403)


def test_list_and_mark_done(db):
    post({"identifier": "a@b.com"})
    row = db.rows("password_help_requests")[0]
    assert [r["id"] for r in svc.list_requests("open")] == [row["id"]]
    assert svc.open_count() == 1
    assert svc.mark_done(row["id"]) is True
    assert svc.open_count() == 0
    assert svc.mark_done("nope") is False


def test_hourly_cap_across_everyone_drops_quietly(db, monkeypatch):
    monkeypatch.setattr(svc, "MAX_OPEN_PER_HOUR", 2)
    for i in range(3):
        assert post({"identifier": f"user{i}@shop.com"}).json() == {"message": svc.REPLY}
    assert len(db.rows("password_help_requests")) == 2


def test_ip_hash_is_keyed_not_a_plain_sha(db):
    import hashlib
    assert svc._hash("1.2.3.4") != hashlib.sha256(b"anril-password-help:1.2.3.4").hexdigest()[:32]


def test_mark_done_with_a_bad_id_is_404_not_500(db, monkeypatch):
    from app.dependencies.system_admin import get_system_admin
    app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin"}
    try:
        res = TestClient(app).post("/api/v1/password-help/requests/not-a-uuid/done")
    finally:
        app.dependency_overrides.pop(get_system_admin, None)
    assert res.status_code == 404

"""v9.2 #27 first sign-in: the server checks the given password, saves the new one and clears the flag."""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.password_change as pc
from app.dependencies.auth import get_current_user
from app.routes import first_setup


@pytest.fixture(autouse=True)
def fresh_limit(monkeypatch):
    monkeypatch.setattr(pc, "_tries", pc._SlidingWindow(pc.TRIES_PER_15_MIN, 900))


def _client(monkeypatch, *, right=True):
    db = MagicMock()
    monkeypatch.setattr(pc, "get_supabase", lambda: db)
    monkeypatch.setattr(pc, "_given_password_is_right", lambda email, pw: right)
    app = FastAPI()
    app.include_router(first_setup.router, prefix="/api/v1/first-setup")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "email": "o@x.in"}
    return TestClient(app), db


def test_right_password_saves_and_clears_the_server_flag(monkeypatch):
    client, db = _client(monkeypatch)
    r = client.post("/api/v1/first-setup/new-password", json={"current_password": "Temp-1234", "new_password": "MyOwn-5678"})
    assert r.status_code == 200 and r.json() == {"changed": True}
    uid, attrs = db.auth.admin.update_user_by_id.call_args.args
    assert uid == "u1" and attrs["password"] == "MyOwn-5678"
    assert attrs["app_metadata"] == {"must_change_password": False}
    assert attrs["user_metadata"] == {"must_change_password": False}


def test_wrong_given_password_changes_nothing(monkeypatch):
    client, db = _client(monkeypatch, right=False)
    r = client.post("/api/v1/first-setup/new-password", json={"current_password": "nope", "new_password": "MyOwn-5678"})
    assert r.status_code == 400 and "not right" in r.json()["detail"]
    db.auth.admin.update_user_by_id.assert_not_called()


@pytest.mark.parametrize("current,new,word", [
    ("Temp-1234", "short", "at least"),
    ("Temp-1234", "x" * 73, "at most"),
    ("Same-1234", "Same-1234", "different"),
    ("", "MyOwn-5678", "given"),
])
def test_bad_new_password_is_refused_before_any_check(monkeypatch, current, new, word):
    client, db = _client(monkeypatch)
    r = client.post("/api/v1/first-setup/new-password", json={"current_password": current, "new_password": new})
    assert r.status_code == 400 and word in r.json()["detail"]
    db.auth.admin.update_user_by_id.assert_not_called()


def test_sixth_try_in_15_minutes_is_blocked(monkeypatch):
    client, _ = _client(monkeypatch, right=False)
    body = {"current_password": "nope", "new_password": "MyOwn-5678"}
    codes = [client.post("/api/v1/first-setup/new-password", json=body).status_code for _ in range(6)]
    assert codes == [400] * 5 + [429]


def test_operator_sets_the_flag_the_person_cannot_clear():
    import inspect

    from app.routes import operator
    src = inspect.getsource(operator)
    assert src.count('"app_metadata": {"must_change_password": True}') == 2


def test_prune_deletes_requests_older_than_90_days():
    from app.services import password_help
    db = MagicMock()
    db.table.return_value.delete.return_value.lt.return_value.execute.return_value = MagicMock(data=[{"id": 1}, {"id": 2}])
    assert password_help.prune_old(db) == 2
    db.table.assert_called_with("password_help_requests")


def test_prune_errors_are_swallowed():
    from app.services import password_help
    db = MagicMock()
    db.table.side_effect = RuntimeError("down")
    assert password_help.prune_old(db) == 0

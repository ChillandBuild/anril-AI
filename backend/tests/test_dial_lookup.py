"""Dial a number > matching customers (v9.2 #231): tenant and telecaller scope, number hiding, short terms."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from tests.fake_supabase import FakeSupabase

T1, T2 = "t1", "t2"
URL = "/api/v1/dial/lookup"
OWNER = {"tenant_id": T1, "role": "owner", "user_id": "u-owner", "caller_id": None, "permissions": []}
ANITHA = {"tenant_id": T1, "role": "caller", "user_id": "u-a", "caller_id": "c-anitha", "permissions": ["telecalling.dialer"]}
NOBODY = {"tenant_id": T1, "role": "caller", "user_id": "u-x", "caller_id": "c-x", "permissions": ["conversations.view"]}


@pytest.fixture
def env():
    db = FakeSupabase()
    def lead(i, name, phone, assigned, tenant=T1, **kw):
        db.add("leads", id=i, tenant_id=tenant, name=name, phone=phone, segment="B", assigned_to=assigned,
               created_at=f"2026-11-{10 + int(i[-1]):02d}T00:00:00+00:00", **kw)
    lead("l1", "Priya Nair", "+919876543210", "c-anitha")
    lead("l2", "Priyanka Das", "+919876500000", "c-bala")
    lead("l3", "Suresh", "+919123456789", "c-anitha", opted_out=True)
    lead("l4", "Priya Other", "+919876511111", "c-anitha", tenant=T2)
    lead("l5", "Meena", "+919000011111", None, is_buyer=True)
    with patch("app.routes.dial_lookup.get_supabase", return_value=db):
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        try:
            yield type("Env", (), {"db": db, "client": TestClient(app)})
        finally:
            app.dependency_overrides.clear()


def find(env, ctx, q):
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    return env.client.get(URL, params={"q": q})


def names(res):
    return sorted(m["name"] for m in res.json()["matches"])


def test_owner_finds_by_name_or_digits_in_this_business_only(env):
    assert names(find(env, OWNER, "priya")) == ["Priya Nair", "Priyanka Das"]
    assert names(find(env, OWNER, "98765432")) == ["Priya Nair"]
    assert names(find(env, OWNER, "+91 98765")) == ["Priya Nair", "Priyanka Das"]
    got = find(env, OWNER, "meena").json()["matches"][0]
    assert got == {"id": "l5", "name": "Meena", "phone": "+919000011111", "segment": "B", "is_buyer": True, "phone_hidden": False}


def test_a_telecaller_only_finds_leads_assigned_to_them(env):
    assert names(find(env, ANITHA, "priya")) == ["Priya Nair"]
    assert names(find(env, ANITHA, "meena")) == []
    assert names(find(env, ANITHA, "9876500000")) == []           # Bala's lead


def test_short_or_empty_terms_return_nothing(env):
    for q in ("", "  ", "p", "98", "%%"):
        assert find(env, OWNER, q).json() == {"matches": []}


def test_numbers_are_masked_for_a_telecaller_and_cannot_be_guessed_by_digits(env):
    with patch("app.services.call_rules.get_rules", return_value={"hide_numbers_for_callers": True}), \
         patch("app.services.call_rules.effective_calling_mode", return_value="telecmi"):
        got = find(env, ANITHA, "priya").json()["matches"]
        assert [(m["phone"], m["phone_hidden"]) for m in got] == [("98•••••210", True)]
        assert find(env, ANITHA, "98765").json() == {"matches": []}      # digit search would leak the number
        assert find(env, OWNER, "priya").json()["matches"][0]["phone"].startswith("+91")


def test_masking_off_lets_a_telecaller_search_by_digits(env):
    with patch("app.services.call_rules.get_rules", return_value={"hide_numbers_for_callers": False}):
        assert names(find(env, ANITHA, "98765")) == ["Priya Nair"]


def test_the_matches_are_capped_at_five(env):
    for i in range(9):
        env.db.add("leads", id=f"n{i}", tenant_id=T1, name=f"Ravi {i}", phone=f"+9190000000{i}", segment="C", assigned_to=None,
                   created_at="2026-11-01T00:00:00+00:00")
    assert len(find(env, OWNER, "ravi").json()["matches"]) == 5


def test_people_without_a_dial_or_leads_permission_are_refused(env):
    assert find(env, NOBODY, "priya").status_code == 403

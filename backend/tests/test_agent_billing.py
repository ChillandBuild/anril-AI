"""Agents billing (migration 342): the operator's Agent replies plan, the atomic reply counter and the
client's Agents -> Usage numbers. Example client: Astro Tamil, 10,000 replies for Rs 3,000 a month."""
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.system_admin import get_system_admin
from app.routes import operator, subscriptions
from app.services import agent_billing, entitlements
from tests.fake_supabase import FakeSupabase

ASTRO, OTHER = "t-astro", "t-other"


def _add_usage_sql(db):
    """Stand-in for public.add_usage: insert with `included`, else used += delta (included kept)."""
    def handler(p):
        rows = db.rows("tenant_usage_counters")
        row = next((r for r in rows if (r["tenant_id"], r["period"], r["metric"]) ==
                    (p["p_tenant"], p["p_period"], p["p_metric"])), None)
        if row is None:
            db.add("tenant_usage_counters", tenant_id=p["p_tenant"], period=p["p_period"], metric=p["p_metric"],
                   used=max(p["p_delta"], 0), included=max(p["p_included"], 0), hard_cap=None)
            return max(p["p_delta"], 0)
        row["used"] = row.get("used", 0) + max(p["p_delta"], 0)   # the real column defaults to 0
        return row["used"]
    return handler


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    fake.rpc_handlers["add_usage"] = _add_usage_sql(fake)
    today = date.today()
    for t in (ASTRO, OTHER):
        fake.add("tenants", id=t, name=t)
        fake.add("tenant_subscriptions", tenant_id=t, status="active", mrr=1500,
                 period_start=(today - timedelta(days=5)).isoformat(),
                 period_end=(today + timedelta(days=25)).isoformat())
    fake.add("feature_catalog", feature_key="agent_replies", display_name="Agent replies", usage_metric="agent_reply",
             included_qty=1, monthly_price=0, unit_price=0, depends_on=[], is_metered=True, sort_order=109)
    fake.add("feature_catalog", feature_key="ai_tier.premium", display_name="AI Premium", usage_metric="ai_reply",
             included_qty=12000, monthly_price=1500, unit_price=None, depends_on=[], is_metered=True, sort_order=23)
    fake.add("tenant_subscription_items", tenant_id=ASTRO, feature_key="ai_tier.premium", quantity=1,
             unit_price_snapshot=1500)
    entitlements._COUNTER_SEEN.clear()
    return fake


def _counter(db, tenant=ASTRO):
    return next((r for r in db.rows("tenant_usage_counters")
                 if r["tenant_id"] == tenant and r["metric"] == "agent_reply"), None)


# --- the counter -------------------------------------------------------------------------------

def test_add_usage_counts_and_takes_included_from_the_plan_once(db, monkeypatch):
    agent_billing.set_plan(db, ASTRO, 10000, 3000)
    entitlements._COUNTER_SEEN.clear()
    db.rows("tenant_usage_counters").clear()
    resolves = []
    real = entitlements.resolve_entitlements
    monkeypatch.setattr(entitlements, "resolve_entitlements", lambda d, t: resolves.append(t) or real(d, t))
    for _ in range(3):
        entitlements.add_usage(db, ASTRO, "agent_reply")
    row = _counter(db)
    assert (row["used"], row["included"]) == (3, 10000)
    assert resolves == [ASTRO]   # only the first reply of the cycle looks the plan up


def test_add_usage_never_raises_and_ignores_empty_input(db):
    del db.rpc_handlers["add_usage"]   # the RPC is missing (migration not applied yet)
    entitlements.add_usage(db, ASTRO, "agent_reply")
    entitlements.add_usage(db, "", "agent_reply")
    entitlements.add_usage(db, ASTRO, "agent_reply", 0)
    assert _counter(db) is None


# --- the operator's plan -----------------------------------------------------------------------

def test_set_plan_saves_the_item_the_counter_and_the_mrr(db):
    entitlements.add_usage(db, ASTRO, "agent_reply")   # a reply before the plan: used 1, included 0
    plan = agent_billing.set_plan(db, ASTRO, 10000, 3000)
    assert plan == {"included": 10000, "monthly_price": 3000.0}
    item = next(r for r in db.rows("tenant_subscription_items") if r["feature_key"] == "agent_replies")
    assert (item["quantity"], item["unit_price_snapshot"]) == (10000, 0.3)
    assert (_counter(db)["used"], _counter(db)["included"]) == (1, 10000)   # used kept
    sub = next(r for r in db.rows("tenant_subscriptions") if r["tenant_id"] == ASTRO)
    assert sub["mrr"] == pytest.approx(4500)   # AI Premium 1,500 + Agent replies 3,000


def test_set_plan_zero_removes_the_item(db):
    agent_billing.set_plan(db, ASTRO, 10000, 3000)
    assert agent_billing.set_plan(db, ASTRO, 0, 0) is None
    assert not [r for r in db.rows("tenant_subscription_items") if r["feature_key"] == "agent_replies"]
    assert _counter(db)["included"] == 0


@pytest.mark.parametrize("included, price", [(-1, 100), (10, -5), (agent_billing.MAX_INCLUDED + 1, 1)])
def test_set_plan_refuses_bad_numbers(db, included, price):
    with pytest.raises(agent_billing.PlanError):
        agent_billing.set_plan(db, ASTRO, included, price)


# --- what the client sees -----------------------------------------------------------------------

def test_usage_shows_overage_and_never_another_business(db):
    agent_billing.set_plan(db, ASTRO, 3, 30)
    for _ in range(5):
        entitlements.add_usage(db, ASTRO, "agent_reply")
    entitlements.add_usage(db, OTHER, "agent_reply")
    u = agent_billing.usage(db, ASTRO)
    assert (u["used"], u["included"], u["over"], u["plan"]) == (5, 3, 2, {"included": 3, "monthly_price": 30.0})
    assert u["period_start"] == (date.today() - timedelta(days=5)).isoformat()
    assert u["period_end"] == (date.today() + timedelta(days=25)).isoformat()
    other = agent_billing.usage(db, OTHER)
    assert (other["used"], other["included"], other["over"], other["plan"]) == (1, 0, 0, None)


def test_the_item_is_hidden_from_the_clients_plan_cart():
    assert "agent_replies" in subscriptions.OPERATOR_ONLY_FEATURES


# --- operator routes ---------------------------------------------------------------------------

@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(operator, "get_supabase", lambda: db)
    audits = []
    monkeypatch.setattr(operator, "record_audit_event", lambda d, **kw: audits.append(kw))
    app = FastAPI()
    app.include_router(operator.router, prefix="/op")
    app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}
    c = TestClient(app)
    c.audits = audits
    return c


def test_operator_sets_and_reads_the_plan(client):
    r = client.put(f"/op/clients/{ASTRO}/agent-replies", json={"included": 10000, "monthly_price": 3000})
    assert r.status_code == 200 and r.json()["plan"] == {"included": 10000, "monthly_price": 3000.0}
    assert client.get(f"/op/clients/{ASTRO}/agent-replies").json()["included"] == 10000
    assert client.audits[-1]["action"] == "operator.agent_replies_plan_set"
    assert client.audits[-1]["metadata"] == {"included": 10000, "monthly_price": 3000.0}


@pytest.mark.parametrize("body", [{"included": -1, "monthly_price": 1}, {"included": 5, "monthly_price": -1},
                                  {"included": 5}, {"included": "lots", "monthly_price": 1}])
def test_operator_route_refuses_bad_input(client, body):
    assert client.put(f"/op/clients/{ASTRO}/agent-replies", json=body).status_code == 422


def test_operator_route_404s_an_unknown_client(client):
    assert client.put("/op/clients/nope/agent-replies", json={"included": 1, "monthly_price": 1}).status_code == 404


def test_operator_route_needs_a_system_admin(db, monkeypatch):
    monkeypatch.setattr(operator, "get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(operator.router, prefix="/op")
    r = TestClient(app).put(f"/op/clients/{ASTRO}/agent-replies", json={"included": 1, "monthly_price": 1})
    assert r.status_code in (401, 403)
    assert not [x for x in db.rows("tenant_subscription_items") if x["feature_key"] == "agent_replies"]


def test_a_request_written_straight_into_the_table_cannot_buy_agent_replies(db, monkeypatch):
    """A tenant owner can insert a subscription_requests row directly (RLS). Approving it must not hand out
    the operator-only item at catalog price 0, nor wipe the price the operator set."""
    from app.services import subscription_requests
    monkeypatch.setattr(subscription_requests, "sync_client_toggles", lambda d, t: None)
    agent_billing.set_plan(db, ASTRO, 10000, 3000)
    req = db.add("subscription_requests", tenant_id=ASTRO, status="submitted", is_initial=False,
                 requested_items=[{"feature_key": "agent_replies", "quantity": 1000000},
                                  {"feature_key": "ai_tier.premium", "quantity": 1}], total_amount=0)
    subscription_requests.approve_request(db, req["id"], "admin-1")
    item = next(r for r in db.rows("tenant_subscription_items") if r["feature_key"] == "agent_replies")
    assert (item["quantity"], item["unit_price_snapshot"]) == (10000, 0.3)
    premium = next(r for r in db.rows("tenant_subscription_items") if r["feature_key"] == "ai_tier.premium")
    assert premium["quantity"] == 2   # the ordinary item in the same request still goes through

"""Ask (Reports #16): replies in the question's language, money tools only for people who may see money,
items tools, a chart and links drawn by code, and nothing that writes."""
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient

from fake_supabase import FakeSupabase
from reports_seed import T1, seed, seed_money
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.routes import ask


def _call(name, args=None):
    return {"function": {"name": name, "arguments": json.dumps(args or {})}}


def names(tools):
    return {t["function"]["name"] for t in tools}


def ctx(role="owner", permissions=()):
    return {"tenant_id": T1, "user_id": "u1", "role": role, "caller_id": None, "permissions": list(permissions)}


@pytest.fixture
def client(monkeypatch):
    db = seed_money(seed(FakeSupabase()))
    monkeypatch.setattr("app.db.supabase.get_supabase", lambda: db)
    monkeypatch.setattr("app.services.deals_reports.held_quantities", lambda *a, **k: {})
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    holder = {"ctx": ctx()}
    app.dependency_overrides[get_tenant_and_role] = lambda: holder["ctx"]
    c = TestClient(app)
    c.holder = holder
    yield c
    app.dependency_overrides.clear()


# ── which tools a person is offered ─────────────────────────────────────────

def test_owner_gets_money_and_items_tools():
    offered = names(ask._tools_for(ctx()))
    assert {"money_summary", "items_summary", "sales_summary", "ad_performance_summary", "funnel_analytics"} <= offered


def test_analytics_only_person_gets_no_rupee_tools():
    offered = names(ask._tools_for(ctx("staff", ["analytics.view"])))
    assert offered.isdisjoint({"money_summary", "items_summary", "sales_summary", "ad_performance_summary"})
    assert {"funnel_analytics", "overview_analytics", "telecalling_analytics"} <= offered


def test_orders_viewer_gets_money_tools():
    assert "money_summary" in names(ask._tools_for(ctx("staff", ["analytics.view", "deals.view"])))


def test_model_is_given_only_the_tools_for_this_person(client):
    client.holder["ctx"] = ctx("staff", ["analytics.view"])
    with patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock) as classify:
        classify.return_value = ("", [])
        client.post("/api/v1/ask", json={"question": "profit?"})
    assert "money_summary" not in names(classify.call_args.kwargs["tools"])


def test_a_tool_the_person_was_never_offered_is_refused(client):
    client.holder["ctx"] = ctx("staff", ["analytics.view"])
    with patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock) as classify, \
         patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock) as answer:
        classify.return_value = ("", [_call("money_summary", {"period": "this_month"})])
        body = client.post("/api/v1/ask", json={"question": "profit?"}).json()
    assert body["data"] is None and "can't answer" in body["answer"]
    answer.assert_not_awaited()


# ── language ────────────────────────────────────────────────────────────────

def test_answer_prompt_asks_for_the_question_language(client):
    with patch("app.routes.ask.funnel_analytics", new_callable=AsyncMock) as funnel, \
         patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock) as answer, \
         patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock) as classify:
        classify.return_value = ("", [_call("funnel_analytics")])
        funnel.return_value = {"by_segment": {"A": 4}}
        answer.return_value = "நான்கு hot leads."
        body = client.post("/api/v1/ask", json={"question": "எத்தனை hot leads?"}).json()
    system = answer.call_args[0][0][0]["content"]
    assert "same language and script" in system and "Tamil script" in system and "Tanglish" in system
    assert body["answer"] == "நான்கு hot leads."
    assert "Tanglish" in classify.call_args[0][0][0]["content"]


# ── money and items answers ─────────────────────────────────────────────────

def test_money_question_uses_the_real_report_and_gives_chart_and_links(client):
    with patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock) as answer, \
         patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock) as classify:
        classify.return_value = ("", [_call("money_summary", {"period": "last_30_days"})])
        answer.return_value = "Profit is 480 rupees."
        with patch("app.routes.ask._period_for", lambda _n: __import__("reports_seed").PERIOD):
            body = client.post("/api/v1/ask", json={"question": "What was my profit?"}).json()
    assert body["source"] == "money_summary" and body["data"]["period"]["profit_paise"] == 48_000
    shown = answer.call_args[0][0][-1]["content"]
    assert "profit_rupees" in shown and "480.0" in shown and "_paise" not in shown  # the model reads rupees, not paise
    assert body["chart"]["kind"] == "bar" and "Profit" in body["chart"]["labels"] and 480.0 in body["chart"]["values"]
    assert {"label": "See these orders", "href": "/dashboard/deals"} in body["links"]


def test_orders_viewer_asking_money_gets_no_profit(client):
    client.holder["ctx"] = ctx("staff", ["analytics.view", "deals.view"])
    with patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock) as answer, \
         patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock) as classify, \
         patch("app.routes.ask._period_for", lambda _n: __import__("reports_seed").PERIOD):
        classify.return_value = ("", [_call("money_summary")])
        answer.return_value = "Sales were 1500 rupees."
        body = client.post("/api/v1/ask", json={"question": "sales?"}).json()
    assert "profit_paise" not in body["data"]["period"] and body["data"]["profit_hidden"] is True
    assert "profit" not in answer.call_args[0][0][-1]["content"].replace("profit_hidden", "")


def test_items_question(client):
    with patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock) as answer, \
         patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock) as classify, \
         patch("app.routes.ask._period_for", lambda _n: __import__("reports_seed").PERIOD):
        classify.return_value = ("", [_call("items_summary", {"period": "this_month"})])
        answer.return_value = "Rice sold most."
        body = client.post("/api/v1/ask", json={"question": "What sold most?"}).json()
    assert body["data"]["top_items"][0]["name"] == "Rice 5kg"
    assert body["chart"] == {"kind": "bar", "labels": ["Rice 5kg", "Oil"], "values": [2, 1]}
    assert {"label": "See items running low", "href": "/dashboard/catalog"} in body["links"]


def test_answer_without_chart_has_null_chart_and_links_stay_inside_the_app(client):
    with patch("app.routes.ask.telecalling_analytics", new_callable=AsyncMock) as calls, \
         patch("app.services.ai_reply._llm_chat", new_callable=AsyncMock) as answer, \
         patch("app.services.ai_reply._llm_chat_with_tools", new_callable=AsyncMock) as classify:
        classify.return_value = ("", [_call("telecalling_analytics")])
        calls.return_value = {"calls": 3}
        answer.return_value = "3 calls."
        body = client.post("/api/v1/ask", json={"question": "calls?"}).json()
    assert body["chart"] is None and body["links"] == [{"label": "Open Calls", "href": "/dashboard/telecalling"}]
    for tool, links in ask._LINKS.items():
        assert all(href.startswith("/") and not href.startswith("//") for _l, href in links)


# ── helpers ─────────────────────────────────────────────────────────────────

def test_chart_for_each_source():
    line = ask._chart_for("overview_analytics", {"daily_leads": [{"day": "2026-10-10", "count": 3}, {"day": "2026-10-11", "count": 5}]})
    assert line == {"kind": "line", "labels": ["10-10", "10-11"], "values": [3, 5]}
    funnel = ask._chart_for("funnel_analytics", {"by_segment": {"A": 4, "B": 2, "C": 9, "D": 1}})
    assert funnel["labels"] == ["Hot", "Warm", "Cold", "Not interested"] and funnel["values"] == [4, 2, 9, 1]
    assert ask._chart_for("funnel_analytics", {"by_segment": {"A": 4}}) is None  # one bar is not a chart
    assert ask._chart_for("overview_analytics", {"daily_leads": [{"day": "2026-10-10", "count": 0}, {"day": "2026-10-11", "count": 0}]}) is None
    assert ask._chart_for("compare_analytics", {}) is None and ask._chart_for("funnel_analytics", None) is None
    assert ask._chart_for(None, {}) is None


def test_for_model_turns_paise_into_rupees_and_leaves_the_rest():
    data = {"period": {"sales_paise": 150_000, "orders": 2}, "rows": [{"spend_paise": 50, "name": "x"}], "profit_hidden": True}
    assert ask._for_model(data) == {"period": {"sales_rupees": 1500.0, "orders": 2}, "rows": [{"spend_rupees": 0.5, "name": "x"}], "profit_hidden": True}


def test_period_for_names():
    today = ask._period_for("today")
    assert today.start == today.end
    assert ask._period_for("last_30_days").days == 30 and ask._period_for("last_7_days").days == 7
    assert ask._period_for("this_week").start.weekday() == 0
    last = ask._period_for("last_month")
    assert last.start.day == 1 and (last.end - last.start).days >= 27 and last.end < date.today().replace(day=1)
    assert ask._period_for("yesterday").start < today.start
    assert ask._period_for("whatever").start.day == 1  # unknown = this month


def test_links_for_unknown_tool_is_empty():
    assert ask._links_for("nope") == [] and ask._links_for(None) == []


def test_ask_does_not_write(client):
    import inspect
    src = inspect.getsource(ask)
    assert ".insert(" not in src and ".update(" not in src and ".upsert(" not in src and ".delete(" not in src

import asyncio
import json
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies.tenant import _has_permission, get_tenant_and_role
from app.routes.analytics import (
    _tenant_id_for_permission,
    ad_performance_summary,
    compare_analytics,
    funnel_analytics,
    messaging_analytics,
    overview_analytics,
    telecalling_analytics,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def require_analytics_view(ctx: dict = Depends(get_tenant_and_role)) -> dict:
    _tenant_id_for_permission(ctx, {"analytics.view"})
    return ctx


# One tool per real analytics function. The model picks WHICH one answers the
# question and what parameters to call it with -- the actual numbers always
# come from calling that real function normally, never from the model. Six of
# analytics.py's endpoints, chosen for being the ones a plain-English question
# is actually likely to map to; caller-timeline/qa-queue/template-performance
# and the CSV export variants are deliberately not included -- they're
# drill-down/operational views, not the shape of a one-sentence answer.
_ANALYTICS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "funnel_analytics",
            "description": "Lead counts by segment (hot/warm/cold/disqualified) and by source (whatsapp/instagram/facebook/telegram/upload/manual), average score, and how many leads arrived this week. No parameters -- covers all-time totals.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "overview_analytics",
            "description": "Dashboard KPIs and daily trend over a date range: messages, leads, conversions.",
            "parameters": {
                "type": "object",
                "properties": {"range": {"type": "string", "description": "e.g. '7d', '30d', '90d'. Default 7d."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "messaging_analytics",
            "description": "Message volume and reply stats over a date range, optionally filtered to one channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "range": {"type": "string", "description": "e.g. '7d', '30d'. Default 7d."},
                    "channel": {"type": "string", "description": "whatsapp, instagram, facebook, telegram, or 'all'. Default all."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "telecalling_analytics",
            "description": "Call volume, connect rate, and caller performance for the telecalling team.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ad_performance_summary",
            "description": "Ad spend, cost per lead, and campaign performance from connected ad accounts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_analytics",
            "description": "Compares two time periods against each other (e.g. this week vs last week).",
            "parameters": {
                "type": "object",
                "properties": {"preset": {"type": "string", "description": "e.g. 'last_7d', 'last_30d'. Default last_7d."}},
                "required": [],
            },
        },
    },
]

_ANALYTICS_TOOLS.append({
    "type": "function",
    "function": {
        "name": "sales_summary",
        "description": "Sales from the Deals board: number and rupee total of completed sales, top items sold, unpaid payment links (who hasn't paid), and products low on stock.",
        "parameters": {
            "type": "object",
            "properties": {"period": {"type": "string", "description": "'today', 'this_week' or 'this_month'. Default today."}},
            "required": [],
        },
    },
})

# Money and items tools (Reports #16). Money tools are only offered to a person who may see rupees
# (owner or deals.view); profit, expenses and GST paid also need purchases.view, which the report itself
# enforces by leaving those figures out. Everything here only reads.
_PERIOD_PARAM = {
    "type": "object",
    "properties": {"period": {"type": "string", "description": "'today', 'yesterday', 'this_week', 'this_month', 'last_month', 'last_7_days' or 'last_30_days'. Default this_month."}},
    "required": [],
}
_MONEY_TOOL = {
    "type": "function",
    "function": {
        "name": "money_summary",
        "description": "Sales before GST, refunds, cost of items, expenses, profit, GST collected and GST paid, plus what is still to collect from customers and what is owed to suppliers (right now).",
        "parameters": _PERIOD_PARAM,
    },
}
_ITEMS_TOOL = {
    "type": "function",
    "function": {
        "name": "items_summary",
        "description": "Top selling items, items running low on stock, and orders by stage (quote sent, waiting for payment, paid, lost).",
        "parameters": _PERIOD_PARAM,
    },
}
_MONEY_TOOL_NAMES = {"money_summary", "sales_summary", "ad_performance_summary"}  # these answer in rupees


def _tools_for(ctx: dict) -> list[dict]:
    """The tools this person may use: money tools only with the money permission."""
    sees_money = _has_permission(ctx, "deals.view")
    tools = [t for t in _ANALYTICS_TOOLS if sees_money or t["function"]["name"] not in _MONEY_TOOL_NAMES]
    if sees_money:
        tools.append(_MONEY_TOOL)
        tools.append(_ITEMS_TOOL)
    return tools


def _period_for(name: str | None):
    from app.services.reports_common import Period, today_ist
    today = today_ist()
    if name == "yesterday":
        return Period(today - timedelta(days=1), today - timedelta(days=1))
    if name == "today":
        return Period(today, today)
    if name == "this_week":
        return Period(today - timedelta(days=today.weekday()), today)
    if name == "last_7_days":
        return Period(today - timedelta(days=6), today)
    if name == "last_30_days":
        return Period(today - timedelta(days=29), today)
    if name == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        return Period(last.replace(day=1), last)
    return Period(today.replace(day=1), today)  # this_month, and anything unknown


def _money_or_items(name: str, tenant_id: str, args: dict, ctx: dict):
    from app.db.supabase import get_supabase
    from app.services import reports_items, reports_money
    from app.services.reports_common import flags_for, run_report
    flags = flags_for(ctx)
    period = _period_for(args.get("period"))
    db = get_supabase()
    if name == "money_summary":
        return reports_money.report(db, tenant_id, period, False, flags)
    return run_report(reports_items, db, tenant_id, period, False, flags)


def _for_model(data):
    """The copy of the data the model reads: rupee figures in rupees, so it never has to convert paise."""
    if isinstance(data, dict):
        return {(k[:-6] + "_rupees" if isinstance(k, str) and k.endswith("_paise") and isinstance(v, (int, float)) else k):
                (v / 100 if isinstance(k, str) and k.endswith("_paise") and isinstance(v, (int, float)) else _for_model(v))
                for k, v in data.items()}
    if isinstance(data, list):
        return [_for_model(v) for v in data]
    return data


_LANGUAGE_RULE = (
    " Reply in the same language and script as the question: Tamil script gets Tamil script, Tamil written "
    "in English letters (Tanglish) gets Tanglish, English gets English. Keep numbers exactly as in the data."
)

# Where each answer can send the person to see the real thing (links stay inside the app).
_LINKS = {
    "funnel_analytics": [("See these customers", "/dashboard/leads")],
    "telecalling_analytics": [("Open Calls", "/dashboard/telecalling")],
    "ad_performance_summary": [("Open Ads report", "/dashboard/analytics?tab=ads")],
    "sales_summary": [("See these orders", "/dashboard/deals")],
    "money_summary": [("See these orders", "/dashboard/deals"), ("Open Money report", "/dashboard/analytics?tab=money")],
    "items_summary": [("See these orders", "/dashboard/deals"), ("See items running low", "/dashboard/catalog")],
}


def _links_for(name: str | None) -> list[dict]:
    return [{"label": label, "href": href} for label, href in _LINKS.get(name or "", [])]


def _chart_for(name: str | None, data) -> dict | None:
    """A small bar or line drawn from the real data by code (never by the model); None when there is nothing worth drawing."""
    try:
        labels: list[str] = []
        values: list[float] = []
        kind = "bar"
        if name == "overview_analytics":
            kind = "line"
            for row in data.get("daily_leads") or []:
                labels.append(str(row["day"])[5:])
                values.append(row["count"])
        elif name == "funnel_analytics":
            for key, word in (("A", "Hot"), ("B", "Warm"), ("C", "Cold"), ("D", "Not interested")):
                if key in (data.get("by_segment") or {}):
                    labels.append(word)
                    values.append(data["by_segment"][key])
        elif name == "items_summary":
            for row in data.get("top_items") or []:
                labels.append(row["name"])
                values.append(row["qty"])
        elif name == "money_summary":
            period = data.get("period") or {}
            for key, word in (("sales_paise", "Sales"), ("refunds_paise", "Refunds"), ("cost_paise", "Cost of items"),
                              ("expenses_paise", "Expenses"), ("profit_paise", "Profit")):
                if period.get(key) is not None:
                    labels.append(word)
                    values.append(period[key] / 100)
        if len(labels) < 2 or not any(values):
            return None
        return {"kind": kind, "labels": labels[:31], "values": values[:31]}
    except (AttributeError, KeyError, TypeError):
        return None


_UNANSWERABLE = (
    "I can't answer that from the reports I have. Try asking about leads, messages, calls, sales, or ad spend."
)


async def _dispatch(name: str, tenant_id: str, args: dict, ctx: dict | None = None):
    if name in ("money_summary", "items_summary"):
        if not ctx or not _has_permission(ctx, "deals.view"):
            return None
        return await asyncio.to_thread(_money_or_items, name, tenant_id, args, ctx)
    if name == "funnel_analytics":
        return await funnel_analytics(tenant_id=tenant_id)
    if name == "overview_analytics":
        return await overview_analytics(tenant_id=tenant_id, range=args.get("range", "7d"))
    if name == "messaging_analytics":
        return await messaging_analytics(
            tenant_id=tenant_id, channel=args.get("channel", "all"), range=args.get("range", "7d")
        )
    if name == "telecalling_analytics":
        return await telecalling_analytics(tenant_id=tenant_id)
    if name == "ad_performance_summary":
        return await ad_performance_summary(tenant_id=tenant_id)
    if name == "sales_summary":
        from app.services.deals_reports import sales_summary
        return sales_summary(tenant_id, args.get("period", "today"))
    if name == "compare_analytics":
        result = await compare_analytics(tenant_id=tenant_id, preset=args.get("preset", "last_7d"))
        if not (ctx and _has_permission(ctx, "deals.view")):
            result = _without_money(result)  # ad spend and cost per lead are rupees
        return result
    return None


def _without_money(result):
    """compare_analytics minus its rupee parts, for people who may not see money."""
    if not isinstance(result, dict):
        return result
    out = {k: v for k, v in result.items() if k != "money_metrics"}
    for side in ("current", "previous"):
        if isinstance(out.get(side), dict):
            out[side] = {k: v for k, v in out[side].items() if k != "money"}
    return out


_ANSWER_SYSTEM_PROMPT = (
    "Answer the user's question in exactly one short sentence, using ONLY the numbers present "
    "in the JSON data below. Never state a number that is not literally in that data, and never "
    "guess or round in a way that changes the meaning. If the data doesn't actually answer the "
    "question, say so plainly instead of answering something close. Rupee figures in the data are in rupees." + _LANGUAGE_RULE
)


class AskPayload(BaseModel):
    question: str = Field(..., max_length=1000)


@router.post("/ask")
async def ask_question(payload: AskPayload, ctx: dict = Depends(require_analytics_view)):
    """The model picks which report answers the question and phrases the
    sentence; the numbers always come from calling that real analytics
    function with the caller's own tenant_id, the same way the dashboard
    itself does -- never from the model. See _ANALYTICS_TOOLS above for
    what "which report" can mean."""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    tenant_id = ctx["tenant_id"]
    from app.services.ai_reply import _llm_chat, _llm_chat_with_tools

    try:
        _, tool_calls = await _llm_chat_with_tools(
            [
                {
                    "role": "system",
                    "content": "Pick exactly one tool that answers the question and call it with sensible parameters. If none of the tools can answer it, don't call any tool. The question may be in English, Tamil script or Tanglish (Tamil in English letters).",
                },
                {"role": "user", "content": question},
            ],
            tools=_tools_for(ctx),
            max_tokens=200,
            tenant_id=tenant_id,
        )
    except RuntimeError:
        raise HTTPException(
            status_code=400,
            detail="Add a Gemini API key in Settings before asking a question.",
        )

    if not tool_calls:
        return {"answer": _UNANSWERABLE, "data": None, "source": None, "chart": None, "links": []}

    func = (tool_calls[0].get("function") or {})
    name = func.get("name")
    try:
        args = json.loads(func.get("arguments") or "{}")
    except (ValueError, TypeError):
        args = {}

    if name not in {t["function"]["name"] for t in _tools_for(ctx)}:  # a tool this person was never offered
        return {"answer": _UNANSWERABLE, "data": None, "source": None, "chart": None, "links": []}
    data = await _dispatch(name, tenant_id, args, ctx)
    if data is None:
        return {"answer": _UNANSWERABLE, "data": None, "source": None, "chart": None, "links": []}

    answer = await _llm_chat(
        [
            {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nData: {json.dumps(_for_model(data), default=str)}"},
        ],
        max_tokens=150,
        tenant_id=tenant_id,
        purpose="ask_analytics",
        temperature=0.1,
    )

    return {"answer": answer.strip(), "data": data, "source": name, "chart": _chart_for(name, data), "links": _links_for(name)}

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.tenant import get_tenant_and_role
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

_UNANSWERABLE = (
    "I can't answer that from the reports I have. Try asking about leads, messages, calls, sales, or ad spend."
)


async def _dispatch(name: str, tenant_id: str, args: dict):
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
        return await compare_analytics(tenant_id=tenant_id, preset=args.get("preset", "last_7d"))
    return None


_ANSWER_SYSTEM_PROMPT = (
    "Answer the user's question in exactly one short sentence, using ONLY the numbers present "
    "in the JSON data below. Never state a number that is not literally in that data, and never "
    "guess or round in a way that changes the meaning. If the data doesn't actually answer the "
    "question, say so plainly instead of answering something close."
)


class AskPayload(BaseModel):
    question: str


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
                    "content": "Pick exactly one tool that answers the question and call it with sensible parameters. If none of the tools can answer it, don't call any tool.",
                },
                {"role": "user", "content": question},
            ],
            tools=_ANALYTICS_TOOLS,
            max_tokens=200,
            tenant_id=tenant_id,
        )
    except RuntimeError:
        raise HTTPException(
            status_code=400,
            detail="Add a Gemini API key in Settings before asking a question.",
        )

    if not tool_calls:
        return {"answer": _UNANSWERABLE, "data": None, "source": None}

    func = (tool_calls[0].get("function") or {})
    name = func.get("name")
    try:
        args = json.loads(func.get("arguments") or "{}")
    except (ValueError, TypeError):
        args = {}

    data = await _dispatch(name, tenant_id, args)
    if data is None:
        return {"answer": _UNANSWERABLE, "data": None, "source": None}

    answer = await _llm_chat(
        [
            {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nData: {json.dumps(data, default=str)}"},
        ],
        max_tokens=150,
        tenant_id=tenant_id,
        purpose="ask_analytics",
        temperature=0.1,
    )

    return {"answer": answer.strip(), "data": data, "source": name}

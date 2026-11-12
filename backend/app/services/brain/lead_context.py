"""Operator "What Anril saw": a read-only RECONSTRUCTION of what Anril would see if this lead
messaged now. Nothing here is a record of a past reply (Anril does not store the prompt it used).

Guarantees, each pinned by tests/test_operator_what_aira_saw.py:
- No writes. The prompt is built with persist=False (skips the tamil_locked write), and the
  quota gate reads the counter without check_quota(), whose get_billing_period() can roll the
  billing period forward and write.
- No model call, ever.
- Knowledge retrieval (one embedding call in semantic mode) runs only when retrieval=True."""
import logging
from datetime import datetime, timezone

from app.config_dynamic import get_setting
from app.services import ai_reply, deal_actions, deal_engine, intake
from app.services.entitlements import compute_period_key
from app.services.knowledge_service import get_knowledge_context

logger = logging.getLogger(__name__)

RECENT_MESSAGE_LIMIT = 20
MESSAGE_TEXT_CAP = 2000
DEFAULT_CHANNEL = "whatsapp"
AI_REPLY_METRIC = "ai_reply"
LEAD_COLUMNS = (
    "id,tenant_id,name,segment,score,phone,ai_enabled,blocked_at,opted_out,"
    "needs_human_attention,tamil_locked,assigned_to,source"
)
RETRIEVAL_OFF_NOTE = (
    "Not retrieved. Retrieving knowledge costs one embedding call, so it only runs when you ask."
)
NO_MESSAGE_NOTE = "This lead has no inbound message yet, so the prompt was built with an empty message."


class LeadNotFound(Exception):
    """The lead does not exist, or belongs to another tenant."""


def _fetch_lead(db, tenant_id: str, lead_id: str) -> dict:
    rows = (
        db.table("leads").select(LEAD_COLUMNS)
        .eq("id", lead_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not rows:
        raise LeadNotFound(lead_id)
    return rows[0]


def _recent_messages(db, tenant_id: str, lead_id: str) -> list[dict]:
    rows = (
        db.table("messages").select("direction,content,created_at,is_ai_generated,channel")
        .eq("lead_id", lead_id).eq("tenant_id", tenant_id)
        .order("created_at", desc=True).limit(RECENT_MESSAGE_LIMIT).execute()
    ).data or []
    return [
        {
            "direction": r.get("direction"),
            "text": (r.get("content") or "")[:MESSAGE_TEXT_CAP],
            "at": r.get("created_at"),
            "is_ai": bool(r.get("is_ai_generated")),
        }
        for r in reversed(rows)  # oldest first, like the chat
    ]


def _latest_inbound(db, tenant_id: str, lead_id: str) -> dict | None:
    rows = (
        db.table("messages").select("content,channel")
        .eq("lead_id", lead_id).eq("tenant_id", tenant_id).eq("direction", "inbound")
        .order("created_at", desc=True).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def _auto_reply_block(tenant_id: str, channel: str, lead: dict) -> str | None:
    """The Settings > Auto-Reply check generate_reply makes: the AI master, the channel's
    row and the lead's source row. Returns the plain reason, or None when nothing blocks."""
    from app.services.automation_guards import ai_reply_block_reason
    return ai_reply_block_reason(tenant_id, channel, lead.get("source"))


def _quota_exhausted(db, tenant_id: str) -> bool:
    """check_quota's rule (only an explicit hard_cap blocks), read without its write path."""
    sub = (
        db.table("tenant_subscriptions").select("period_start,period_end")
        .eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    anchor = sub[0] if sub else {}
    period = compute_period_key(anchor.get("period_start"), anchor.get("period_end"))
    counter = (
        db.table("tenant_usage_counters").select("used,hard_cap")
        .eq("tenant_id", tenant_id).eq("period", period).eq("metric", AI_REPLY_METRIC).limit(1).execute()
    ).data or []
    if not counter or counter[0].get("hard_cap") is None:
        return False
    return (counter[0].get("used") or 0) + 1 > counter[0]["hard_cap"]


def _gate(key: str, label: str, active: bool, blocks_reply: bool, detail: str) -> dict:
    return {"key": key, "label": label, "active": active, "blocks_reply": blocks_reply, "detail": detail}


def build_gates(db, tenant_id: str, lead: dict, channel: str = DEFAULT_CHANNEL) -> list[dict]:
    """Every check that can stop or change a reply, in the order generate_reply applies them."""
    auto_reply_block = _auto_reply_block(tenant_id, channel, lead)
    return [
        _gate("blocked", "Lead is blocked", bool(lead.get("blocked_at")), True,
              "A blocked lead gets no auto-reply."),
        _gate("auto_reply_off", auto_reply_block or "Auto-reply is off", bool(auto_reply_block), True,
              "Settings > Auto-Reply: the AI Replies switch, this chat channel's row and the lead's "
              "source row (e.g. IndiaMART) must all be on."),
        _gate("takeover", "AI is off for this lead (a person took over)", lead.get("ai_enabled") is False, True,
              "Anril only rescores this lead. A person answers."),
        _gate("quota_exhausted", "AI reply quota is used up", _quota_exhausted(db, tenant_id), True,
              "Only an explicit hard cap blocks replies."),
        _gate("opted_out", "Lead opted out", bool(lead.get("opted_out")), False,
              "Blocks broadcasts and automated follow-ups. It does not stop a reply to their own message."),
        _gate("needs_human_attention", "Escalated to a person", bool(lead.get("needs_human_attention")), False,
              "Anril still replies, but as a holding presence."),
    ]


def _deal_state(db, tenant_id: str, lead_id: str) -> dict:
    config = intake.get_intake_config(tenant_id, db=db)
    session = intake._get_active_session(lead_id, tenant_id, db)
    return {
        "selling_enabled": deal_engine.is_enabled(config),
        "session": None if not session else {
            "status": session.get("status"),
            "collected_data": session.get("collected_data") or {},
            "created_at": session.get("created_at"),
        },
    }


def _call_summaries(db, tenant_id: str, lead_id: str) -> list[dict]:
    calls = ai_reply._fetch_call_context(db, lead_id, tenant_id)
    return [
        {"at": c.get("created_at"), "outcome": c.get("outcome"),
         "manual_status": c.get("manual_status"), "summary": c.get("ai_summary")}
        for c in calls
    ]


def _orders(db, tenant_id: str, lead_id: str) -> list[dict]:
    return [
        {"deal_number": d.get("deal_number"), "stage": d.get("stage"),
         "total_paise": d.get("total_paise"), "items": d.get("items") or []}
        for d in deal_actions.lead_orders(db, tenant_id, lead_id)
    ]


def _knowledge(context_text: str, retrieval: bool) -> dict:
    if not retrieval:
        return {"text": None, "note": RETRIEVAL_OFF_NOTE}
    return {"text": context_text, "note": None if context_text else "Retrieval ran and found nothing."}


def _build_prompt(db, tenant_id: str, lead_id: str, lead: dict, message: str, channel: str,
                  campaign_name: str | None, context_text: str) -> dict:
    try:
        prompt, mode, intake_active = ai_reply.build_reply_system_prompt(
            db, lead_id, tenant_id, lead, message, channel,
            campaign_name=campaign_name, context_text=context_text, persist=False,
        )
    except Exception:
        logger.exception("What-Anril-saw prompt build failed for lead %s", lead_id)
        return {"system_prompt": None, "reply_language_mode": None, "intake_active": None,
                "prompt_error": "The prompt could not be built. See the server log."}
    return {"system_prompt": prompt, "reply_language_mode": mode, "intake_active": intake_active,
            "prompt_error": None}


async def build_what_aira_saw(db, tenant_id: str, lead_id: str, *, retrieval: bool = False) -> dict:
    lead = _fetch_lead(db, tenant_id, lead_id)
    inbound = _latest_inbound(db, tenant_id, lead_id)
    message = (inbound or {}).get("content") or ""
    channel = (inbound or {}).get("channel") or DEFAULT_CHANNEL
    campaign_tag_id, campaign_name = ai_reply._resolve_campaign(db, lead_id)

    context_text = ""
    if retrieval:
        context_text = await get_knowledge_context(tenant_id, query=message, campaign_tag_id=campaign_tag_id)

    gates = build_gates(db, tenant_id, lead, channel)
    return {
        "reconstructed": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lead": {"id": lead["id"], "name": lead.get("name"), "segment": lead.get("segment"),
                 "score": lead.get("score"), "channel": channel},
        "message_used": {"text": message, "note": None if inbound else NO_MESSAGE_NOTE},
        "recent_messages": _recent_messages(db, tenant_id, lead_id),
        "conversation_summary": ai_reply._fetch_conversation_summary(db, lead_id),
        "campaign": {"id": campaign_tag_id, "name": campaign_name} if campaign_name else None,
        "deal_state": _deal_state(db, tenant_id, lead_id),
        "orders": _orders(db, tenant_id, lead_id),
        "call_summaries": _call_summaries(db, tenant_id, lead_id),
        "gates": gates,
        "would_reply": not any(g["active"] and g["blocks_reply"] for g in gates),
        "knowledge": _knowledge(context_text, retrieval),
        **_build_prompt(db, tenant_id, lead_id, lead, message, channel, campaign_name, context_text),
    }

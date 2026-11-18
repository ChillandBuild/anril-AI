"""Customers > Said stop: one list for every module (leads.opted_out).

What it stops, and what still goes, is decided where each sender checks `opted_out`
(broadcast_executor, reengagement_service, silence_nudge, automation_guards,
scheduled_templates, sms_campaigns, share_product, call_details_share, meta_lead_forms)
and, since 2026-11-18, the telecalling queue and dialler (see `blocks_calls`). The AI
agent still answers a person's own message, payment messages still go, and a team
member can still type in the chat.

How people get on it is recorded in opted_out_source (migration 281):
  stop_reply  replied STOP / unsubscribe / ஆர்வம் இல்லை   (routes/webhook.py)
  chat_ai     the AI read a clear no in chat               (services/scoring_engine.py)
  call        a telecaller ticked "stop messages"          (services/wrapup_apply.py)
  staff       a team member added them by hand             (add_by_hand below)
Only a team member removes someone (remove_by_hand); nothing automatic ever does.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SOURCES = ("stop_reply", "chat_ai", "call", "staff")
_DETAIL_MAX = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text: str | None) -> str | None:
    text = " ".join((text or "").split())
    if not text:
        return None
    return text if len(text) <= _DETAIL_MAX else text[: _DETAIL_MAX - 1] + "…"


def record_source(db, tenant_id: str, lead_id: str, source: str, detail: str | None = None,
                  by: str | None = None) -> None:
    """Say how a person got on Said stop. The first reason wins: a later "not interested"
    in chat does not overwrite an earlier STOP reply (removal clears it, so a new stop
    after a removal is recorded afresh). Best effort, never raises: the stop itself has
    already been saved by the caller, and a missing column (migration 281 not applied yet)
    must not undo it."""
    if source not in SOURCES:
        return
    try:
        db.table("leads").update({
            "opted_out_source": source,
            "opted_out_detail": _clip(detail),
            "opted_out_by": by,
        }).eq("id", str(lead_id)).eq("tenant_id", tenant_id).is_("opted_out_source", "null").execute()
    except Exception as e:
        logger.warning(f"Said stop: could not record how lead {lead_id} stopped: {e}")


def blocks_calls(lead: dict) -> bool:
    """A telecaller must not call this person: Said stop, or the call-only Do not call flag."""
    return bool(lead.get("opted_out") or lead.get("do_not_call"))


def add_by_hand(db, tenant_id: str, lead_ids: list[str], user_id: str | None, staff_name: str | None) -> int:
    """Put people on Said stop because they asked a team member. People already on it keep
    their original reason and date. Returns how many were added."""
    if not lead_ids:
        return 0
    rows = (db.table("leads").update({"opted_out": True, "opted_out_at": _now_iso()})
            .eq("tenant_id", tenant_id).in_("id", lead_ids).is_("deleted_at", "null")
            .or_("opted_out.is.null,opted_out.eq.false").execute()).data or []
    for row in rows:
        record_source(db, tenant_id, str(row["id"]), "staff", staff_name, by=user_id)
    return len(rows)


def remove_by_hand(db, tenant_id: str, lead_ids: list[str]) -> int:
    """Take people off Said stop (only when the customer asked). Clears the per-product
    stops too, so broadcasts of every tag can reach them again. Returns how many."""
    if not lead_ids:
        return 0
    rows = (db.table("leads").update({"opted_out": False, "opted_out_at": None})
            .eq("tenant_id", tenant_id).in_("id", lead_ids).eq("opted_out", True).execute()).data or []
    removed = [str(r["id"]) for r in rows]
    if removed:
        try:
            db.table("leads").update({"opted_out_source": None, "opted_out_detail": None, "opted_out_by": None}) \
                .eq("tenant_id", tenant_id).in_("id", removed).execute()
        except Exception as e:
            logger.warning(f"Said stop: could not clear how-they-stopped for {len(removed)} leads: {e}")
        try:
            db.table("lead_tag_opt_outs").delete().eq("tenant_id", tenant_id).in_("lead_id", removed).execute()
        except Exception as e:
            logger.warning(f"Said stop: could not clear per-product stops: {e}")
    return len(removed)

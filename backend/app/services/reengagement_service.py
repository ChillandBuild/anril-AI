import logging
import re
from datetime import datetime, timezone, timedelta
from app.db.supabase import get_supabase
from app.services.ai_reply import send_whatsapp
from app.services.automation_guards import lead_blocks_automated_outbound, master_switch_on
from app.services.meta_cloud import send_template_message
from app.services.outbound_router import SenderPicker
from app.services.template_params import template_status

logger = logging.getLogger(__name__)


class NoSenderAvailable(Exception):
    """The template can't go out right now: no number may send (all
    Red/resting/unverified or the limit is used up), or the template isn't
    APPROVED on Meta (e.g. under review after an edit). The step is retried
    later, so no log row."""


# Tenants with no sender left: skip their re-engagement templates until this
# time instead of re-checking every due lead every minute.
_NO_SENDER_UNTIL: dict[str, datetime] = {}
_NO_SENDER_RECHECK = timedelta(minutes=10)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _classify_source(lead: dict) -> str:
    """Map a lead to an acquisition-source bucket (ad referral wins over channel)."""
    if lead.get("ad_campaign_id"):
        return "meta_ads"
    src = (lead.get("source") or "").lower()
    if src == "upload":
        return "csv"
    if src in ("telegram", "instagram", "facebook"):
        return src
    return "organic"


def _lead_matches_sources(lead: dict, target_sources) -> bool:
    """NULL/empty target_sources = all sources."""
    if not target_sources:
        return True
    return _classify_source(lead) in target_sources


_HEADER_VAR = re.compile(r"\{\{\s*\d+\s*\}\}")
_MEDIA_HEADERS = ("IMAGE", "VIDEO", "DOCUMENT")


def _header_component(db, tenant_id: str, template_name: str, lead: dict) -> dict | None:
    """The header Meta needs for this template on every send. Meta keeps no
    media for a template: an IMAGE/VIDEO/DOCUMENT header must carry its link
    each time, or Meta refuses it (#132012 "expected IMAGE, received UNKNOWN").
    A text header with {{1}} gets the lead's name."""
    rows = (
        db.table("message_templates").select("header_media_type, header_media_url, header_text")
        .eq("tenant_id", tenant_id).eq("name", template_name).limit(1).execute().data or []
    )
    if not rows:
        return None
    t = rows[0]
    media = (t.get("header_media_type") or "").upper()
    if media in _MEDIA_HEADERS:
        link = t.get("header_media_url")
        if not link:
            raise ValueError(f"Template {template_name} has a {media} header but no saved media link")
        kind = media.lower()
        return {"type": "header", "parameters": [{"type": kind, kind: {"link": link}}]}
    if _HEADER_VAR.search(t.get("header_text") or ""):
        return {"type": "header", "parameters": [{"type": "text", "text": lead.get("name") or "there"}]}
    return None


_IN_CLAUSE_BATCH_SIZE = 200


def _already_processed_lead_ids(db, step_id: str, lead_ids: list[str]) -> set[str]:
    """Batched replacement for a per-lead reengagement_logs existence check."""
    processed: set[str] = set()
    for i in range(0, len(lead_ids), _IN_CLAUSE_BATCH_SIZE):
        batch = lead_ids[i:i + _IN_CLAUSE_BATCH_SIZE]
        res = (
            db.table("reengagement_logs")
            .select("lead_id")
            .eq("step_id", step_id)
            .in_("lead_id", batch)
            .execute()
        )
        processed.update(row["lead_id"] for row in (res.data or []))
    return processed


def _lead_already_logged(db, step_id: str, lead_id: str) -> bool:
    """Fresh check just before a send. The run's batch check can be minutes old by the
    time a lead's turn comes, and another run may have messaged the lead since."""
    res = (
        db.table("reengagement_logs")
        .select("id")
        .eq("step_id", step_id)
        .eq("lead_id", lead_id)
        .limit(1)
        .execute()
    )
    return bool(res.data)


def _fetch_leads_by_id(db, tenant_id: str, lead_ids: list[str]) -> dict[str, dict]:
    """Batched replacement for a per-lead `leads` fetch, keyed by lead id."""
    leads_by_id: dict[str, dict] = {}
    for i in range(0, len(lead_ids), _IN_CLAUSE_BATCH_SIZE):
        batch = lead_ids[i:i + _IN_CLAUSE_BATCH_SIZE]
        res = (
            db.table("leads")
            .select("id, name, phone, last_inbound_phone_number_id, segment, last_inbound_at, source, ad_campaign_id, whatsapp_undeliverable, opted_out")
            .eq("tenant_id", tenant_id)
            .in_("id", batch)
            .execute()
        )
        for row in (res.data or []):
            leads_by_id[row["id"]] = row
    return leads_by_id


async def process_due_reengagements() -> int:
    """Query and process all pending re-engagement steps for all tenants."""
    db = get_supabase()
    
    # 1. Fetch all re-engagement steps
    steps_res = db.table("reengagement_steps").select("*").execute()
    steps = steps_res.data or []
    if not steps:
        return 0

    sent_count = 0
    now = utcnow()

    for step in steps:
        step_id = step["id"]
        tenant_id = step["tenant_id"]
        delay_hours = step["delay_hours"]
        target_segments = step["target_segments"] or []
        target_sources = step.get("target_sources") or []
        message_type = step["message_type"]
        
        if step["type"] == "broadcast":
            # A. Broadcast-specific re-engagement
            broadcast_id = step["broadcast_id"]
            if not broadcast_id:
                continue

            # Fetch recipients who received this broadcast
            recipients_res = (
                db.table("broadcast_recipients")
                .select("lead_id, created_at, phone, name")
                .eq("broadcast_id", broadcast_id)
                .eq("tenant_id", tenant_id)
                .eq("send_status", "sent")
                .execute()
            )
            recipients = recipients_res.data or []
            if not recipients:
                continue

            # Filter by elapsed delay in-memory first — no DB round-trip yet.
            due_recipients = []
            for rec in recipients:
                try:
                    sent_at = datetime.fromisoformat(rec["created_at"].replace("Z", "+00:00"))
                except Exception:
                    continue
                if now - sent_at >= timedelta(hours=delay_hours):
                    due_recipients.append(rec)
            if not due_recipients:
                continue

            # Dedup lead_ids: broadcast_recipients has no unique(broadcast_id, lead_id)
            # constraint, so a duplicate row must not produce a duplicate send.
            due_lead_ids = list(dict.fromkeys(rec["lead_id"] for rec in due_recipients))
            processed_ids = _already_processed_lead_ids(db, step_id, due_lead_ids)
            pending_lead_ids = [lid for lid in due_lead_ids if lid not in processed_ids]
            if not pending_lead_ids:
                continue

            leads_by_id = _fetch_leads_by_id(db, tenant_id, pending_lead_ids)

            for lead_id in pending_lead_ids:
                lead = leads_by_id.get(lead_id)
                if not lead or lead.get("segment") not in target_segments:
                    continue
                if not _lead_matches_sources(lead, target_sources):
                    continue

                # Process sending
                success = await _send_reengagement(db, tenant_id, lead, step)
                if success:
                    sent_count += 1

        elif step["type"] == "inbound":
            # B. Inbound lead-specific re-engagement (relative to last_inbound_at)
            # Find leads with last_inbound_at
            leads_res = (
                db.table("leads")
                .select("id, name, phone, last_inbound_phone_number_id, segment, last_inbound_at, source, ad_campaign_id, whatsapp_undeliverable, opted_out")
                .eq("tenant_id", tenant_id)
                .not_.is_("last_inbound_at", "null")
                .execute()
            )
            leads = leads_res.data or []

            # Filter by elapsed delay + segment/source in-memory first — no DB round-trip yet.
            due_leads = []
            for lead in leads:
                try:
                    last_inbound = datetime.fromisoformat(lead["last_inbound_at"].replace("Z", "+00:00"))
                except Exception:
                    continue
                if now - last_inbound < timedelta(hours=delay_hours):
                    continue
                if lead.get("segment") not in target_segments:
                    continue
                if not _lead_matches_sources(lead, target_sources):
                    continue
                due_leads.append(lead)
            if not due_leads:
                continue

            processed_ids = _already_processed_lead_ids(db, step_id, [lead["id"] for lead in due_leads])

            for lead in due_leads:
                if lead["id"] in processed_ids:
                    continue

                # Process sending
                success = await _send_reengagement(db, tenant_id, lead, step)
                if success:
                    sent_count += 1

    return sent_count


async def _send_step_template(
    db,
    tenant_id: str,
    lead: dict,
    step: dict,
    *,
    template_name: str,
    template_variables: list[str] | None,
    log_status: str,
) -> bool:
    """Send a template message for a step and write message + reengagement logs."""
    lead_id = lead["id"]
    phone = lead["phone"]
    step_id = step["id"]
    if not template_name:
        raise ValueError("Template name not configured")
    if template_status(db, tenant_id, template_name) != "APPROVED":
        logger.info(f"Re-engagement step {step_id}: template {template_name} isn't approved right now; retrying later")
        raise NoSenderAvailable()

    parameters = []
    for var_name in (template_variables or []):
        if var_name == "name":
            val = lead.get("name") or "there"
        elif var_name == "phone":
            val = lead.get("phone") or ""
        else:
            val = ""
        parameters.append({"type": "text", "text": str(val)})

    components = []
    header = _header_component(db, tenant_id, template_name, lead)
    if header:
        components.append(header)
    if parameters:
        components.append({"type": "body", "parameters": parameters})

    # A re-engagement template is marketing Anril starts, so it follows the
    # broadcast rules: never from a Red/resting/unverified number, within the
    # warm-up and daily limits. The lead's own number is preferred so it lands
    # in their existing chat.
    until = _NO_SENDER_UNTIL.get(tenant_id)
    if until and utcnow() < until:
        raise NoSenderAvailable()
    sender = SenderPicker(tenant_id).next(prefer_meta_id=lead.get("last_inbound_phone_number_id"))
    if sender is None:
        _NO_SENDER_UNTIL[tenant_id] = utcnow() + _NO_SENDER_RECHECK
        logger.info(f"Re-engagement: no number can send for tenant {tenant_id}; retrying later")
        raise NoSenderAvailable()

    res = await send_template_message(
        to_number=phone,
        template_name=template_name,
        components=components,
        tenant_id=tenant_id,
        phone_number_id=sender.get("meta_phone_number_id"),
    )
    sid = res.get("messages", [{}])[0].get("id") if res else None

    db.table("messages").insert({
        "lead_id": lead_id,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "channel": "whatsapp",
        "content": f"[Template Broadcast: {template_name}]",
        "is_ai_generated": True,
        "meta_message_id": sid or "",
        "reply_source": "reengagement",
    }).execute()

    db.table("reengagement_logs").insert({
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "step_id": step_id,
        "status": log_status,
    }).execute()
    logger.info(f"Re-engagement step {step_id} ({log_status}) sent to lead {lead_id}")
    return True


async def _send_reengagement(db, tenant_id: str, lead: dict, step: dict) -> bool:
    """Send the re-engagement message to a single lead and write a log entry.

    ai_auto_reply_enabled is the single master switch for every automated AI-authored
    outbound message, not just inbound replies -- when a client turns it off, re-engagement
    must stop too (no separate reengagement_enabled flag; that key existed but was never
    actually wired to any send path, so it was deleted rather than kept as dead config).
    No log row is written on this skip, matching the opted_out/undeliverable checks below --
    re-engagement should resume for this lead+step once the tenant re-enables, not be
    permanently marked processed."""
    lead_id = lead["id"]
    phone = lead["phone"]
    step_id = step["id"]
    if not master_switch_on(tenant_id):
        logger.info(f"Re-engagement step {step_id} skipped for lead {lead_id} (ai_auto_reply disabled for tenant {tenant_id})")
        return False
    message_type = step["message_type"]

    # Shared with silence_nudge via automation_guards: no phone (can't send),
    # whatsapp_undeliverable (Meta marked the number unreachable via the delivery
    # webhook — the original template never landed, so a follow-up can't either),
    # and opted_out (a compliance risk regardless of channel).
    #
    # No log row on any of these skips, matching the master-switch skip above --
    # re-engagement should resume for this lead+step once the blocker clears, not
    # be permanently marked processed.
    block_reason = lead_blocks_automated_outbound(lead)
    if block_reason:
        logger.info(f"Re-engagement step {step_id} skipped for lead {lead_id} ({block_reason})")
        return False

    if _lead_already_logged(db, step_id, lead_id):
        logger.info(f"Re-engagement step {step_id} skipped for lead {lead_id} (already handled by another run)")
        return False

    # Check 24-hour WhatsApp session window for freeform messages
    is_window_active = False
    last_inbound_str = lead.get("last_inbound_at")
    if last_inbound_str:
        try:
            last_inbound = datetime.fromisoformat(last_inbound_str.replace("Z", "+00:00"))
            is_window_active = (utcnow() - last_inbound) <= timedelta(hours=24)
        except Exception:
            pass

    # Exception for non-whatsapp channels (e.g. Telegram where no 24h window applies)
    if lead.get("source") in ("telegram", "instagram", "facebook"):
        is_window_active = True

    if message_type == "freeform":
        if not is_window_active:
            fallback_name = step.get("fallback_template_name")
            if fallback_name:
                try:
                    return await _send_step_template(
                        db, tenant_id, lead, step,
                        template_name=fallback_name,
                        template_variables=step.get("fallback_template_variables"),
                        log_status="sent_fallback",
                    )
                except NoSenderAvailable:
                    return False
                except Exception as e:
                    logger.error(f"Re-engagement fallback template {step_id} failed for lead {lead_id}: {e}")
                    db.table("reengagement_logs").insert({
                        "tenant_id": tenant_id,
                        "lead_id": lead_id,
                        "step_id": step_id,
                        "status": "failed",
                    }).execute()
                    return False

            db.table("reengagement_logs").insert({
                "tenant_id": tenant_id,
                "lead_id": lead_id,
                "step_id": step_id,
                "status": "skipped_window",
            }).execute()
            logger.info(f"Re-engagement step {step_id} skipped for lead {lead_id} (outside 24h window, no fallback)")
            return False

        try:
            content = step["message_content"] or ""
            sid = await send_whatsapp(phone, content, tenant_id=tenant_id)
            if not sid:
                raise RuntimeError("Channel send returned empty SID")

            db.table("messages").insert({
                "lead_id": lead_id,
                "tenant_id": tenant_id,
                "direction": "outbound",
                "channel": "whatsapp",
                "content": content,
                "is_ai_generated": True,
                "meta_message_id": sid,
                "reply_source": "reengagement",
            }).execute()

            db.table("reengagement_logs").insert({
                "tenant_id": tenant_id,
                "lead_id": lead_id,
                "step_id": step_id,
                "status": "sent",
            }).execute()
            logger.info(f"Re-engagement step {step_id} (freeform) sent to lead {lead_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send re-engagement freeform step {step_id} to lead {lead_id}: {e}")
            db.table("reengagement_logs").insert({
                "tenant_id": tenant_id,
                "lead_id": lead_id,
                "step_id": step_id,
                "status": "failed",
            }).execute()
            return False

    elif message_type == "template":
        try:
            return await _send_step_template(
                db, tenant_id, lead, step,
                template_name=step.get("template_name"),
                template_variables=step.get("template_variables"),
                log_status="sent",
            )
        except NoSenderAvailable:
            return False
        except Exception as e:
            logger.error(f"Failed to send re-engagement template step {step_id} to lead {lead_id}: {e}")
            db.table("reengagement_logs").insert({
                "tenant_id": tenant_id,
                "lead_id": lead_id,
                "step_id": step_id,
                "status": "failed",
            }).execute()
            return False

    return False

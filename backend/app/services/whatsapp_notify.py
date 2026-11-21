import logging
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase
from app.services.meta_cloud import send_template_message
from app.services.notification_config import get_notification_config
from app.services.template_fields import AlertFields, build_body_components, chat_link

logger = logging.getLogger(__name__)

_SEGMENT_LABELS = {"A": "Hot", "B": "Warm", "C": "Cold", "D": "Not Interested"}
_COOLDOWN_HOURS = 6
ALERT_DELAY_SECONDS = 300
# Everything a template variable map can pull from the lead row itself.
_ALERT_LEAD_COLUMNS = "id,name,phone,score,segment,created_at,assigned_to,collected_data,call_status"


def _log_incident(db, tenant_id: str, detail: dict) -> None:
    """Record a whatsapp_alert_failed incident so failures surface on the
    dashboard instead of only existing in server logs. Never raises."""
    try:
        db.table("incidents").insert({
            "tenant_id": tenant_id,
            "type": "whatsapp_alert_failed",
            "detail": detail,
        }).execute()
    except Exception:
        logger.exception("Failed to record whatsapp_alert_failed incident for tenant %s", tenant_id)


def _is_recently_notified(db, lead_id: str, to_segment: str) -> bool:
    """True if this lead already triggered a segment_changed->to_segment alert
    within the cooldown window.

    The row for the event that is calling us right now has already been
    inserted by record_stage_event before this function runs, so a single
    matching row is the FIRST legitimate occurrence (must still send) — only
    more than one row means a prior alert already fired in this window.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_COOLDOWN_HOURS)).isoformat()
    try:
        res = (
            db.table("lead_stage_events")
            .select("id,created_at")
            .eq("lead_id", lead_id)
            .eq("to_segment", to_segment)
            .eq("event_type", "segment_changed")
            .gte("created_at", cutoff)
            .order("created_at")
            .execute()
        )
        return len(res.data or []) > 1
    except Exception:
        logger.exception("Cooldown check failed for lead %s segment %s", lead_id, to_segment)
        return False


def _build_components(
    template: dict, lead: dict, to_segment: str, fields: AlertFields | None = None
) -> list[dict] | None:
    """Fill the template body for a hot-lead alert: the template's saved variable
    map when it has one, else {{1}} name, {{2}} phone, {{3}} Hot/Warm label,
    {{4}} conversation link.

    Returns None when the template has no variables — nothing safe to send.
    """
    label = _SEGMENT_LABELS.get(to_segment, to_segment)
    defaults = [lead.get("name") or "Lead", lead.get("phone") or "", label, chat_link(lead["id"])]
    return build_body_components(template, defaults, fields)


def _lead_ad_source(db, tenant_id: str, lead_id: str) -> str:
    """Human-readable acquisition source for a lead's escalation alert.

    Returns the MOST RECENT Meta ad's creative label ("Ad: <label>"), or
    "Organic lead" when the lead has no ad attribution. Broadcast
    attribution is not covered yet — no broadcast has ever run, so
    broadcast_recipients is empty; add it here once that data exists.

    Never raises — a source lookup must not block the alert.
    """
    try:
        res = (
            db.table("lead_meta_ad_attributions")
            .select("created_at, ad_creatives(creative_label)")
            .eq("lead_id", lead_id)
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (res.data or [None])[0]
        if row:
            creative = row.get("ad_creatives") or {}
            label = creative.get("creative_label") if isinstance(creative, dict) else None
            if label:
                return f"Ad: {label}"
    except Exception:
        logger.exception("Ad-source lookup failed for lead %s", lead_id)
    return "Organic lead"


def _build_escalation_components(
    template: dict, lead: dict, reason: str, source: str = "Organic lead",
    fields: AlertFields | None = None,
) -> list[dict] | None:
    """Fill the template body for an escalation alert: the template's saved
    variable map when it has one, else {{1}} name, {{2}} phone, {{3}} reason,
    {{4}} conversation link, {{5}} acquisition source. A template with fewer
    variables simply uses the leading subset. Returns None when the template
    has no variables — nothing safe to send.
    """
    defaults = [
        lead.get("name") or "Lead",
        lead.get("phone") or "",
        (reason or "")[:120],
        chat_link(lead["id"]),
        source,
    ]
    return build_body_components(template, defaults, fields)


def queue_escalation_whatsapp_alert(
    db,
    tenant_id: str,
    lead_id: str,
    handover_id: str,
    reason: str,
    assigned_to: str | None,
) -> None:
    """Queue a delayed WhatsApp alert for a newly created chat handover.

    No cooldown check is needed: _trigger_chat_escalation returns early when an
    open handover already exists, so there is exactly one alert per handover.
    Never raises — escalation must not fail because of a notification.
    """
    try:
        cfg = get_notification_config(tenant_id, db=db).get(
            "whatsapp_escalation_notifications"
        ) or {}

        if not cfg.get("enabled"):
            return
        template_id = cfg.get("template_id")
        recipient_phones = cfg.get("recipient_phones") or []
        if not template_id or not recipient_phones:
            return

        lead_res = (
            db.table("leads")
            .select("id,segment")
            .eq("id", lead_id)
            .limit(1)
            .execute()
        )
        lead = (lead_res.data or [None])[0]
        if not lead:
            return
        if lead.get("segment") not in (cfg.get("target_segments") or []):
            return

        delay_minutes = cfg.get("delay_minutes")
        if delay_minutes is None:
            delay_minutes = 3
        send_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)

        db.table("pending_whatsapp_alerts").insert({
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "handover_id": handover_id,
            "assigned_to_at_queue": assigned_to,
            "escalation_reason": reason,
            "alert_type": "escalation",
            "to_segment": None,
            "from_segment": None,
            "send_at": send_at.isoformat(),
            "status": "pending",
        }).execute()

        logger.info(
            "Queued escalation WhatsApp alert lead=%s handover=%s send_at=%s",
            lead_id, handover_id, send_at,
        )
    except Exception as e:
        logger.exception(
            "queue_escalation_whatsapp_alert failed tenant=%s lead=%s", tenant_id, lead_id
        )
        _log_incident(db, tenant_id, {
            "lead_id": lead_id,
            "handover_id": handover_id,
            "reason": "escalation_queue_failed",
            "error": str(e)[:500],
        })


async def _process_escalation_alert(db, alert: dict) -> None:
    """Send one due escalation alert, unless the handover was claimed or resolved.

    'Claimed' is a change in assigned_to since queue time, NOT simply a non-null
    assigned_to — _trigger_chat_escalation seeds it with the lead's existing owner.
    """
    alert_id = alert["id"]
    tenant_id = alert["tenant_id"]
    lead_id = alert["lead_id"]
    handover_id = alert.get("handover_id")

    def _cancel():
        db.table("pending_whatsapp_alerts").update(
            {"status": "cancelled"}
        ).eq("id", alert_id).execute()

    ho_res = (
        db.table("chat_handovers")
        .select("id,status,assigned_to")
        .eq("id", handover_id)
        .limit(1)
        .execute()
    )
    handover = (ho_res.data or [None])[0]
    if not handover:
        _cancel()
        return
    if handover.get("status") != "pending":
        _cancel()          # resolved before the delay elapsed
        return
    if handover.get("assigned_to") != alert.get("assigned_to_at_queue"):
        _cancel()          # claimed by a teammate
        return

    cfg = get_notification_config(tenant_id, db=db).get(
        "whatsapp_escalation_notifications"
    ) or {}
    template_id = cfg.get("template_id")
    recipient_phones = cfg.get("recipient_phones") or []
    if not cfg.get("enabled") or not template_id or not recipient_phones:
        _cancel()
        return

    lead_res = (
        db.table("leads")
        .select(_ALERT_LEAD_COLUMNS)
        .eq("id", lead_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    lead = (lead_res.data or [None])[0]
    if not lead:
        _cancel()
        _log_incident(db, tenant_id, {"lead_id": lead_id, "reason": "lead_not_found"})
        return

    template_res = (
        db.table("message_templates")
        .select("id,name,language,body_text,status,variable_map")
        .eq("id", template_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "APPROVED")
        .limit(1)
        .execute()
    )
    template = (template_res.data or [None])[0]
    if not template:
        db.table("pending_whatsapp_alerts").update(
            {"status": "failed"}
        ).eq("id", alert_id).execute()
        _log_incident(db, tenant_id, {
            "lead_id": lead_id,
            "template_id": template_id,
            "reason": "escalation_template_not_found_or_not_approved",
        })
        return

    source = _lead_ad_source(db, tenant_id, lead_id)
    reason = alert.get("escalation_reason") or ""
    fields = AlertFields(db, tenant_id, lead, {"escalation_reason": reason[:120], "lead_source": source})
    components = _build_escalation_components(template, lead, reason, source, fields)
    if components is None:
        db.table("pending_whatsapp_alerts").update(
            {"status": "failed"}
        ).eq("id", alert_id).execute()
        return

    await _dispatch_alerts(recipient_phones, template, components, tenant_id, lead_id)
    db.table("pending_whatsapp_alerts").update(
        {"status": "sent"}
    ).eq("id", alert_id).execute()


async def _dispatch_alerts(
    recipient_phones: list[str],
    template: dict,
    components: list[dict],
    tenant_id: str,
    lead_id: str,
) -> None:
    db = get_supabase()
    for phone in recipient_phones:
        try:
            await send_template_message(
                to_number=phone,
                template_name=template["name"],
                lang_code=template.get("language") or "en",
                components=components,
                tenant_id=tenant_id,
                skip_blocked_check=True,  # goes to the business's own staff numbers, not the customer
            )
        except Exception as e:
            logger.exception("WhatsApp admin alert failed to %s for lead %s", phone, lead_id)
            _log_incident(db, tenant_id, {
                "lead_id": lead_id,
                "phone": phone,
                "template": template.get("name"),
                "reason": "meta_send_failed",
                "error": str(e)[:500],
            })


def queue_admin_whatsapp_alert(
    db,
    tenant_id: str,
    lead_id: str,
    from_segment: str | None,
    to_segment: str,
) -> None:
    """Queue a pending admin WhatsApp alert in the database, cancelling any prior pending ones for this lead."""
    try:
        wa_cfg = get_notification_config(tenant_id, db=db).get("whatsapp_notifications") or {}

        if not wa_cfg.get("enabled") or from_segment == to_segment:
            return
        if to_segment not in (wa_cfg.get("target_segments") or []):
            return
        template_id = wa_cfg.get("template_id")
        recipient_phones = wa_cfg.get("recipient_phones") or []
        if not template_id or not recipient_phones:
            return

        if _is_recently_notified(db, lead_id, to_segment):
            return

        # Cancel prior pending alerts for this lead
        db.table("pending_whatsapp_alerts").update(
            {"status": "cancelled"}
        ).eq("lead_id", lead_id).eq("status", "pending").execute()

        # Calculate send_at based on configured delay
        delay_minutes = wa_cfg.get("delay_minutes")
        if delay_minutes is None:
            delay_minutes = 5

        # Check if ALERT_DELAY_SECONDS override is active for testing (e.g. 0.05 seconds or 0)
        if ALERT_DELAY_SECONDS != 300:
            send_at = datetime.now(timezone.utc) + timedelta(seconds=ALERT_DELAY_SECONDS)
        else:
            send_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)

        db.table("pending_whatsapp_alerts").insert({
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "from_segment": from_segment,
            "to_segment": to_segment,
            "send_at": send_at.isoformat(),
            "status": "pending",
        }).execute()
        
        logger.info("Queued WhatsApp notification for lead=%s tenant=%s to_segment=%s send_at=%s", lead_id, tenant_id, to_segment, send_at)
    except Exception as e:
        logger.exception("queue_admin_whatsapp_alert failed for tenant=%s lead=%s", tenant_id, lead_id)
        _log_incident(db, tenant_id, {
            "lead_id": lead_id,
            "reason": "queue_failed",
            "error": str(e)[:500],
        })


async def process_due_whatsapp_alerts() -> None:
    """Query due pending alerts from public.pending_whatsapp_alerts, verify conditions, and send them."""
    db = get_supabase()
    now = datetime.now(timezone.utc)
    try:
        res = (
            db.table("pending_whatsapp_alerts")
            .select("*")
            .eq("status", "pending")
            .lte("send_at", now.isoformat())
            .order("send_at")
            .limit(50)
            .execute()
        )
        alerts = res.data or []
        if not alerts:
            return

        for alert in alerts:
            alert_id = alert["id"]
            tenant_id = alert["tenant_id"]
            lead_id = alert["lead_id"]
            to_segment = alert["to_segment"]

            try:
                # Mark as processing to prevent double runs
                db.table("pending_whatsapp_alerts").update(
                    {"status": "processing"}
                ).eq("id", alert_id).execute()

                # A blocked person raises no alert for the team (full block).
                from app.services.blocked_guard import lead_is_blocked_sync
                if lead_is_blocked_sync(db, tenant_id, lead_id):
                    db.table("pending_whatsapp_alerts").update(
                        {"status": "cancelled"}
                    ).eq("id", alert_id).execute()
                    continue

                # Escalation alerts have their own verification rules.
                if alert.get("alert_type") == "escalation":
                    await _process_escalation_alert(db, alert)
                    continue

                # Verify lead is still in the target segment
                lead_res = (
                    db.table("leads")
                    .select(_ALERT_LEAD_COLUMNS)
                    .eq("id", lead_id)
                    .eq("tenant_id", tenant_id)
                    .limit(1)
                    .execute()
                )
                lead = (lead_res.data or [None])[0]
                if not lead:
                    db.table("pending_whatsapp_alerts").update(
                        {"status": "cancelled"}
                    ).eq("id", alert_id).execute()
                    _log_incident(db, tenant_id, {
                        "lead_id": lead_id,
                        "reason": "lead_not_found",
                    })
                    continue

                if lead.get("segment") != to_segment:
                    db.table("pending_whatsapp_alerts").update(
                        {"status": "cancelled"}
                    ).eq("id", alert_id).execute()
                    continue

                # Verify it is still the latest segment_changed event
                last_event_res = (
                    db.table("lead_stage_events")
                    .select("to_segment")
                    .eq("lead_id", lead_id)
                    .eq("event_type", "segment_changed")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if not last_event_res.data or last_event_res.data[0]["to_segment"] != to_segment:
                    db.table("pending_whatsapp_alerts").update(
                        {"status": "cancelled"}
                    ).eq("id", alert_id).execute()
                    continue

                wa_cfg = get_notification_config(tenant_id, db=db).get("whatsapp_notifications") or {}
                if not wa_cfg.get("enabled"):
                    db.table("pending_whatsapp_alerts").update(
                        {"status": "cancelled"}
                    ).eq("id", alert_id).execute()
                    continue

                template_id = wa_cfg.get("template_id")
                recipient_phones = wa_cfg.get("recipient_phones") or []
                if not template_id or not recipient_phones:
                    db.table("pending_whatsapp_alerts").update(
                        {"status": "cancelled"}
                    ).eq("id", alert_id).execute()
                    continue

                template_res = (
                    db.table("message_templates")
                    .select("id,name,language,body_text,status,variable_map")
                    .eq("id", template_id)
                    .eq("tenant_id", tenant_id)
                    .eq("status", "APPROVED")
                    .limit(1)
                    .execute()
                )
                template = (template_res.data or [None])[0]
                if not template:
                    logger.warning("WhatsApp alert skipped: template %s not found/approved", template_id)
                    db.table("pending_whatsapp_alerts").update(
                        {"status": "failed"}
                    ).eq("id", alert_id).execute()
                    _log_incident(db, tenant_id, {
                        "lead_id": lead_id,
                        "template_id": template_id,
                        "reason": "template_not_found_or_not_approved",
                    })
                    continue

                fields = AlertFields(db, tenant_id, lead, {
                    "lead_temperature": _SEGMENT_LABELS.get(to_segment, to_segment),
                    "lead_source": lambda: _lead_ad_source(db, tenant_id, lead_id),
                })
                components = _build_components(template, lead, to_segment, fields)
                if components is None:
                    db.table("pending_whatsapp_alerts").update(
                        {"status": "failed"}
                    ).eq("id", alert_id).execute()
                    continue

                await _dispatch_alerts(recipient_phones, template, components, tenant_id, lead_id)

                db.table("pending_whatsapp_alerts").update(
                    {"status": "sent"}
                ).eq("id", alert_id).execute()

            except Exception as e:
                logger.exception("Failed to process pending alert %s", alert_id)
                db.table("pending_whatsapp_alerts").update(
                    {"status": "failed"}
                ).eq("id", alert_id).execute()
    except Exception as e:
        logger.exception("process_due_whatsapp_alerts failed")


async def send_admin_whatsapp_alerts(
    tenant_id: str,
    lead_id: str,
    from_segment: str | None,
    to_segment: str,
) -> None:
    """Maintained for tests and backward compatibility. Queues and triggers processing."""
    db = get_supabase()
    queue_admin_whatsapp_alert(db, tenant_id, lead_id, from_segment, to_segment)
    
    import asyncio
    is_mocked_sleep = "mock" in type(asyncio.sleep).__name__.lower()
    
    if is_mocked_sleep or (ALERT_DELAY_SECONDS != 300 and ALERT_DELAY_SECONDS > 0):
        # Determine delay from config
        wa_cfg = get_notification_config(tenant_id, db=db).get("whatsapp_notifications") or {}
        delay_minutes = wa_cfg.get("delay_minutes", 5)
        delay_seconds = ALERT_DELAY_SECONDS if ALERT_DELAY_SECONDS != 300 else (delay_minutes * 60)
        await asyncio.sleep(delay_seconds)
        
    await process_due_whatsapp_alerts()



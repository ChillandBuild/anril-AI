"""Execute a scheduled broadcast row from the scheduled_broadcasts table."""
import csv
import io
import json
import logging
import random as _random
import re as _re
from datetime import datetime, timedelta, timezone

import httpx

from app.db.supabase import get_supabase
from app.services import reach_audience
from app.services.entitlements import meter
from app.services.meta_cloud import send_template_message
from app.services.outbound_router import SenderPicker
from app.services.segmentation import new_lead_score_and_segment
from app.services.template_params import HEADER_COLS, body_parameters, header_components

logger = logging.getLogger(__name__)


def _normalize_phone(raw: str) -> str:
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return ""
    if not digits.startswith("91") and len(digits) == 10:
        digits = "91" + digits
    return "+" + digits


def _clean_text(val: str | None) -> str:
    return (val or "").strip()


def _meta_error_detail(error_msg: str) -> str:
    """Human-readable Meta error for the failed CSV — '(#code) message', else trimmed raw."""
    if not error_msg:
        return ""
    m = _re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', error_msg)
    msg = m.group(1).encode().decode("unicode_escape") if m else error_msg.strip()
    msg = _re.sub(r"^\d{3}:\s*", "", msg)
    return msg[:300]


async def execute_broadcast(row: dict) -> dict:
    """Run a single scheduled_broadcasts row and return a result dict."""
    row_id = row["id"]
    tenant_id = row["tenant_id"]
    template_name = row["template_name"]
    variable_mapping: list[str] = row.get("variable_mapping") or []
    opt_in_source = row.get("opt_in_source") or ""
    tag_id: str | None = row.get("tag_id")

    db = get_supabase()

    # Mark running using a Compare-And-Swap (CAS) lock
    res = (
        db.table("scheduled_broadcasts")
        .update({"status": "running"})
        .eq("id", row_id)
        .eq("status", "pending")
        .execute()
    )
    if not res.data:
        logger.info(f"Broadcast {row_id} already acquired by another worker or not pending.")
        return {"sent": 0, "failed": 0}

    try:
        leads_raw: list[dict] = row.get("leads_json") or []
        if not leads_raw:
            _finish(db, row_id, "done", {"sent": 0, "failed": 0, "note": "empty_leads"})
            return {"sent": 0, "failed": 0}

        # The sender is re-picked as the run goes (see SenderPicker): a
        # failover mid-broadcast moves the rest to the new primary, and once
        # every number is at today's cap -- or none may broadcast (Red with no
        # standby) -- the remainder waits for tomorrow instead of failing.
        picker = SenderPicker(tenant_id)
        if picker.next() is None:
            _defer_send(db, row_id, tenant_id, "no_sender_available")
            return {"sent": 0, "failed": 0, "deferred": True}

        # Fetch template metadata (including variations for rotation)
        tpl_lang = "en"
        tpl_body = ""
        tpl_variations: list[str] = []
        tpl_row = (
            db.table("message_templates")
            .select(f"language,body_text,variations,status,{HEADER_COLS}")
            .eq("name", template_name)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        # Only a template Meta has APPROVED right now is sent. Under review
        # (e.g. after an edit): wait and retry. Rejected/paused/gone: stop.
        tpl_status = ((tpl_row.data or [{}])[0].get("status") or "").upper()
        if tpl_status == "PENDING":
            db.table("scheduled_broadcasts").update({
                "status": "pending",
                "fire_at": in_daytime(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "result": json.dumps({"note": "template_in_review"}),
            }).eq("id", row_id).execute()
            logger.info(f"Broadcast {row_id}: template {template_name} is in Meta review; retrying in an hour")
            return {"sent": 0, "failed": 0, "deferred": True}
        if tpl_status != "APPROVED":
            _finish(db, row_id, "failed", None,
                    error=f"Template {template_name} is {tpl_status or 'missing'} on Meta, so it can't be sent")
            return {"sent": 0, "failed": 0, "error": "template_not_approved"}
        if tpl_row.data:
            tpl_lang = tpl_row.data[0].get("language") or "en"
            tpl_body = tpl_row.data[0].get("body_text") or ""
            raw_variations = tpl_row.data[0].get("variations") or []
            if isinstance(raw_variations, list):
                tpl_variations = [v for v in raw_variations if isinstance(v, str) and v.strip()]

        # Build pool: primary template + approved sibling variants
        # (name, language, body, row) -- row carries the header Meta needs on each send.
        template_pool: list[tuple[str, str, str, dict]] = [
            (template_name, tpl_lang, tpl_body, (tpl_row.data or [{}])[0])
        ]
        for sibling_name in tpl_variations:
            sib_row = (
                db.table("message_templates")
                .select(f"language,body_text,status,{HEADER_COLS}")
                .eq("name", sibling_name)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            if sib_row.data and (sib_row.data[0].get("status") or "").upper() == "APPROVED":
                sib_lang = sib_row.data[0].get("language") or "en"
                sib_body = sib_row.data[0].get("body_text") or ""
                template_pool.append((sibling_name, sib_lang, sib_body, sib_row.data[0]))

        # Opted-out phones
        all_phones = [_normalize_phone(l.get("phone", "")) for l in leads_raw if _normalize_phone(l.get("phone", ""))]
        opted_out_phones: set[str] = set()
        if all_phones:
            rows = db.table("leads").select("phone").in_("phone", all_phones).eq("tenant_id", tenant_id).eq("opted_out", True).execute()
            opted_out_phones = {r["phone"] for r in (rows.data or [])}

        # Suppress leads with 3+ consecutive unreplied outbound messages
        suppressed_phones: set[str] = set()
        if all_phones:
            supp_rows = db.table("leads").select("phone").in_("phone", all_phones).eq("tenant_id", tenant_id).gte("outbound_no_reply_count", 3).execute()
            suppressed_phones = {r["phone"] for r in (supp_rows.data or [])}

        # Suppress leads who previously replied negatively to any broadcast
        negative_reply_phones: set[str] = set()
        if all_phones:
            neg_rows = (
                db.table("leads")
                .select("phone")
                .in_("phone", all_phones)
                .eq("tenant_id", tenant_id)
                .not_.is_("broadcast_negative_reply_at", "null")
                .execute()
            )
            negative_reply_phones = {r["phone"] for r in (neg_rows.data or [])}

        lead_rows = db.table("leads").select("id,phone,name").in_("phone", all_phones).eq("tenant_id", tenant_id).execute()
        phone_to_lead_id = {r["phone"]: r["id"] for r in (lead_rows.data or [])}

        sent = 0
        failed = 0
        broadcast_id = row_id  # reuse scheduled_broadcast id as broadcast_id
        recipient_rows = []
        aborted = False
        deferred = False

        # AUDIT-2026-09.md finding C4: recipient rows used to be written ONLY
        # after the whole loop finished, so a crash/restart mid-send (e.g. a
        # Render deploy) lost every already-sent message's record with no
        # trace, and re-running the same row would re-send to everyone since
        # nothing marked what had already gone out. Both are fixed here:
        # each row is now written right after it's decided (see
        # _record_recipient below), and a phone already recorded for THIS
        # broadcast_id is skipped so a resume never double-sends.
        already_recorded = (
            db.table("broadcast_recipients")
            .select("phone")
            .eq("broadcast_id", broadcast_id)
            .eq("tenant_id", tenant_id)
            .execute()
            .data
            or []
        )
        already_recorded_phones = {r["phone"] for r in already_recorded if r.get("phone")}

        # Blocked people and the 2-offers-a-month limit, read once for this run (services/reach_audience.py).
        blocked_keys, monthly_limit_keys = reach_audience.send_time_skips(
            db, tenant_id, all_phones, exclude_broadcast_id=broadcast_id)
        skipped_monthly = 0
        skipped_blocked = 0

        def _record_recipient(row: dict) -> None:
            recipient_rows.append(row)
            try:
                db.table("broadcast_recipients").insert(row).execute()
            except Exception as rec_err:
                logger.error(f"broadcast_recipients insert failed for {row.get('phone')}: {rec_err}")

        for idx, lead in enumerate(leads_raw):
            if idx % 3 == 0:
                try:
                    abort_row = (
                        db.table("scheduled_broadcasts")
                        .select("abort_requested")
                        .eq("id", row_id)
                        .maybe_single()
                        .execute()
                    )
                    if abort_row and abort_row.data and abort_row.data.get("abort_requested"):
                        aborted = True
                        break
                except Exception:
                    pass

            phone = _normalize_phone(lead.get("phone", ""))
            if phone and phone in already_recorded_phones:
                # Resuming a previously-interrupted run of this same broadcast:
                # this phone already has a recipient row from before the crash.
                continue

            if not phone or phone in opted_out_phones or phone in suppressed_phones or phone in negative_reply_phones:
                failed += 1
                _record_recipient({
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": phone_to_lead_id.get(phone) if phone else None,
                    "phone": phone,
                    "name": _clean_text(lead.get("name")),
                    "send_status": "failed",
                    "tag_id": tag_id,
                })
                continue

            lead_id = phone_to_lead_id.get(phone)
            lead_name = _clean_text(lead.get("name"))
            extra_cols: dict = lead.get("extra_cols") or {}

            skip_key = reach_audience.phone_key(phone)
            skip_reason = (reach_audience.SKIP_BLOCKED if skip_key in blocked_keys
                           else reach_audience.SKIP_MONTHLY if skip_key in monthly_limit_keys else None)
            if skip_reason:
                # Not failed: skipped on purpose. Stored as opted_out_skip + fail_reason (the send_status
                # CHECK has no "skipped"); the History tab reads the reason (routes/upload.py classifier).
                if skip_reason == reach_audience.SKIP_BLOCKED:
                    skipped_blocked += 1
                else:
                    skipped_monthly += 1
                _record_recipient({
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": lead_id,
                    "phone": phone,
                    "name": lead_name,
                    "send_status": "opted_out_skip",
                    "fail_reason": skip_reason,
                    "tag_id": tag_id,
                })
                continue

            sender = picker.next()
            if sender is None:
                deferred = True
                break

            # Pick a random template from pool for this lead
            chosen_name, chosen_lang, chosen_body, chosen_tpl = _random.choice(template_pool)

            try:
                components = header_components(chosen_tpl, lead_name)
                params = body_parameters(chosen_body, variable_mapping, extra_cols, lead_name)
                if params:
                    components.append({"type": "body", "parameters": params})

                _send_resp = await send_template_message(
                    to_number=phone,
                    template_name=chosen_name,
                    lang_code=chosen_lang,
                    components=components,
                    phone_number_id=sender.get("meta_phone_number_id"),
                    tenant_id=tenant_id,
                )
                await picker.record_sent(sender)
                _meta_msg_id: str | None = None
                try:
                    _meta_msg_id = ((_send_resp or {}).get("messages") or [{}])[0].get("id")
                except Exception:
                    pass

                sent += 1
                _record_recipient({
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": lead_id,
                    "phone": phone,
                    "name": lead_name,
                    "send_status": "sent",
                    "meta_message_id": _meta_msg_id,
                    "tag_id": tag_id,
                    "extra_cols": extra_cols or None,
                })
                # Track-only usage metering: one billable send per successfully
                # delivered recipient. Never blocks/caps — best-effort only.
                meter(db, tenant_id, "message_sent")

                if lead_id:
                    try:
                        db.table("messages").insert({
                            "lead_id": lead_id,
                            "tenant_id": tenant_id,
                            "direction": "outbound",
                            "channel": "whatsapp",
                            "content": f"[Template: {chosen_name}]",
                            "is_ai_generated": False,
                            "meta_message_id": _meta_msg_id,
                        }).execute()
                    except Exception:
                        pass
                    try:
                        db.rpc("increment_lead_no_reply_count", {"p_lead_id": lead_id}).execute()
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Scheduled broadcast send failed for {phone}: {e}")
                failed += 1
                _record_recipient({
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": lead_id,
                    "phone": phone,
                    "name": lead_name,
                    "send_status": "failed",
                    "tag_id": tag_id,
                    "fail_detail": _meta_error_detail(str(e)),
                })

        if aborted:
            for lead in leads_raw[idx:]:
                phone = _normalize_phone(lead.get("phone", ""))
                if phone and phone in already_recorded_phones:
                    continue
                _record_recipient({
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": phone_to_lead_id.get(phone),
                    "phone": phone,
                    "name": _clean_text(lead.get("name")),
                    "send_status": "aborted_skip",
                    "tag_id": tag_id,
                })

        # Recipient rows are written incrementally by _record_recipient() as
        # each one is decided (see the C4 note above) -- no batch persist
        # step here any more. broadcast_recipients has no unique constraint
        # beyond its own `id`, so re-inserting the same rows here would
        # silently duplicate every recipient instead of erroring.

        # Freeze previous un-finalized broadcast_lead_scores rows (per-lead freeze).
        # Each broadcast starts its own scoring slate at the tenant's Cold floor;
        # this intentionally does not modify the lead's global score or segment.
        sent_at = datetime.now(timezone.utc).isoformat()
        sent_lead_ids_for_bls = [
            r["lead_id"] for r in recipient_rows
            if r.get("send_status") == "sent" and r.get("lead_id")
        ]

        # Freeze previous un-finalized rows for these leads
        if sent_lead_ids_for_bls:
            try:
                for i in range(0, len(sent_lead_ids_for_bls), 100):
                    batch_ids = sent_lead_ids_for_bls[i:i+100]
                    db.table("broadcast_lead_scores").update(
                        {"finalized_at": sent_at}
                    ).in_("lead_id", batch_ids).is_("finalized_at", "null").neq("broadcast_id", str(broadcast_id)).execute()
            except Exception as frz_err:
                logger.warning(f"broadcast_lead_scores freeze failed: {frz_err}")

        initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
        bls_rows = [
            {
                "tenant_id": tenant_id,
                "broadcast_id": broadcast_id,
                "lead_id": r["lead_id"],
                "tag_id": tag_id,
                "score": initial_score,
                "segment": initial_segment,
                "arc_score": initial_score,
                "arc_message_count": 0,
                "broadcast_sent_at": sent_at,
            }
            for r in recipient_rows
            if r.get("send_status") == "sent" and r.get("lead_id")
        ]
        if bls_rows:
            for i in range(0, len(bls_rows), 100):
                try:
                    db.table("broadcast_lead_scores").upsert(
                        bls_rows[i:i+100],
                        on_conflict="broadcast_id,lead_id",
                    ).execute()
                except Exception as bls_err:
                    logger.error(f"broadcast_lead_scores seed failed: {bls_err}")

        # Increment broadcast_count in lead_tag_interest for each successfully sent lead
        if tag_id and bls_rows:
            sent_lead_ids = [r["lead_id"] for r in bls_rows]
            try:
                existing_lti = (
                    db.table("lead_tag_interest")
                    .select("lead_id,broadcast_count")
                    .eq("tenant_id", tenant_id)
                    .eq("tag_id", tag_id)
                    .in_("lead_id", sent_lead_ids)
                    .execute().data or []
                )
                existing_counts = {r["lead_id"]: r.get("broadcast_count") or 0 for r in existing_lti}
                lti_rows = [
                    {
                        "tenant_id": tenant_id,
                        "lead_id": lid,
                        "tag_id": tag_id,
                        "broadcast_count": existing_counts.get(lid, 0) + 1,
                    }
                    for lid in sent_lead_ids
                ]
                for i in range(0, len(lti_rows), 100):
                    db.table("lead_tag_interest").upsert(
                        lti_rows[i:i+100],
                        on_conflict="tenant_id,lead_id,tag_id",
                    ).execute()
            except Exception as lti_err:
                logger.warning(f"lead_tag_interest broadcast_count update failed: {lti_err}")

        result = {"sent": sent, "failed": failed, "broadcast_id": broadcast_id,
                  "skipped_monthly_limit": skipped_monthly, "skipped_blocked": skipped_blocked}
        if deferred:
            # Unsent leads have no recipient row yet, so tomorrow's run sends
            # exactly those (already-recorded phones are skipped on resume).
            _defer_send(db, row_id, tenant_id, "daily_limit_reached", result)
            logger.info(f"Scheduled broadcast {row_id}: sent={sent} so far, rest deferred to tomorrow")
            return {**result, "deferred": True}
        final_status = "aborted" if aborted else "done"
        _finish(db, row_id, final_status, result)
        _write_broadcast_history(
            db, tenant_id, broadcast_id, template_name, opt_in_source,
            sent, failed, len(leads_raw), picker.numbers_used_label(),
            row.get("csv_file_url"), row.get("csv_file_path"), row.get("csv_file_name"), tag_id,
            skipped_monthly_limit=skipped_monthly, skipped_blocked=skipped_blocked,
        )
        logger.info(f"Scheduled broadcast {row_id}: sent={sent} failed={failed} aborted={aborted}")
        return result

    except Exception as exc:
        logger.error(f"Scheduled broadcast {row_id} failed: {exc}")
        _finish(db, row_id, "failed", None, error=str(exc))
        _write_broadcast_history(
            db, tenant_id, row_id, template_name, opt_in_source,
            0, len(row.get("leads_json") or []), len(row.get("leads_json") or []), None,
            row.get("csv_file_url"), row.get("csv_file_path"), row.get("csv_file_name"), tag_id,
        )
        return {"sent": 0, "failed": 0, "error": str(exc)}


def _write_broadcast_history(
    db, tenant_id: str, broadcast_id: str, template_name: str, opt_in_source: str,
    sent: int, failed: int, total_leads: int, number_used: str | None,
    csv_file_url: str | None, csv_file_path: str | None, csv_file_name: str | None,
    tag_id: str | None, skipped_monthly_limit: int = 0, skipped_blocked: int = 0,
) -> None:
    """Append a broadcast_history entry so fired scheduled/drip/retry broadcasts show
    up in the History tab, the same as immediate 'Send Now' broadcasts already do."""
    try:
        lead_ids: list[str] = []
        try:
            recip = (
                db.table("broadcast_recipients")
                .select("lead_id")
                .eq("tenant_id", tenant_id)
                .eq("broadcast_id", broadcast_id)
                .eq("send_status", "sent")
                .execute()
            )
            lead_ids = [r["lead_id"] for r in (recip.data or []) if r.get("lead_id")]
        except Exception:
            pass

        delivered_count = 0
        opened_count = 0
        if lead_ids:
            now = datetime.now(timezone.utc)
            window_start = (now - timedelta(minutes=2)).isoformat()
            window_end = (now + timedelta(minutes=10)).isoformat()
            try:
                delivered_rows = db.table("messages").select("id") \
                    .in_("lead_id", lead_ids).eq("direction", "outbound") \
                    .eq("delivery_status", "delivered") \
                    .gte("created_at", window_start).lte("created_at", window_end).execute()
                delivered_count = len(delivered_rows.data or [])
                opened_rows = db.table("messages").select("id") \
                    .in_("lead_id", lead_ids).eq("direction", "outbound") \
                    .eq("delivery_status", "read") \
                    .gte("created_at", window_start).lte("created_at", window_end).execute()
                opened_count = len(opened_rows.data or [])
            except Exception:
                pass

        existing = (
            db.table("app_settings")
            .select("value")
            .eq("tenant_id", tenant_id)
            .eq("key", "broadcast_history")
            .maybe_single()
            .execute()
        )
        history: list[dict] = []
        if existing and existing.data and existing.data.get("value"):
            try:
                history = json.loads(existing.data["value"])
            except Exception:
                history = []

        history.insert(0, {
            "broadcast_id": broadcast_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "template_name": template_name,
            "opt_in_source": opt_in_source or "unknown",
            "sent": sent,
            "delivered": delivered_count,
            "opened": opened_count,
            "failed": failed,
            "total_leads": total_leads,
            "number_used": number_used,
            "csv_file_url": csv_file_url,
            "csv_file_path": csv_file_path,
            "csv_file_name": csv_file_name,
            "tag_id": tag_id,
            "skipped_monthly_limit": skipped_monthly_limit,
            "skipped_blocked": skipped_blocked,
        })
        history = history[:50]

        db.table("app_settings").upsert({
            "tenant_id": tenant_id,
            "key": "broadcast_history",
            "value": json.dumps(history),
        }, on_conflict="tenant_id,key").execute()
    except Exception as hist_err:
        logger.exception(f"broadcast_history save failed for {broadcast_id}: {hist_err}")


_IST = timedelta(hours=5, minutes=30)


# The carried-over rest of a capped broadcast only goes out in the daytime --
# marketing at night gets blocked.
SEND_FROM_HOUR_IST = 10
SEND_UNTIL_HOUR_IST = 21


def _ist_at(day, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc) - _IST


def in_daytime(t: datetime) -> datetime:
    """t, or the next 10:00 IST if t falls outside 10:00-21:00 IST."""
    t_ist = t + _IST
    if t_ist.hour < SEND_FROM_HOUR_IST:
        return _ist_at(t_ist.date(), SEND_FROM_HOUR_IST)
    if t_ist.hour >= SEND_UNTIL_HOUR_IST:
        return _ist_at(t_ist.date() + timedelta(days=1), SEND_FROM_HOUR_IST)
    return t


def carry_over_time(first_sent_at: datetime | None, now: datetime | None = None) -> datetime:
    """When the rest of a capped broadcast should try again. Meta's limit is a
    moving 24 hours, so a slot frees 24h after the oldest counted send; with no
    counted send (the block is Red/unverified, not the limit) try again in an hour.
    Always in the daytime."""
    now = now or datetime.now(timezone.utc)
    t = first_sent_at + timedelta(hours=24, minutes=1) if first_sent_at else now + timedelta(hours=1)
    return in_daytime(max(t, now + timedelta(minutes=5)))


def next_send_time(tenant_id: str) -> datetime:
    from app.services.outbound_router import load_usage
    try:
        first = load_usage(get_supabase(), tenant_id).first_sent_at
    except Exception:
        first = None
    return carry_over_time(first)


def _defer_send(db, row_id: str, tenant_id: str, reason: str, result: dict | None = None) -> None:
    update: dict = {"status": "pending", "fire_at": next_send_time(tenant_id).isoformat()}
    if result is not None:
        update["result"] = json.dumps({**result, "note": reason})
    db.table("scheduled_broadcasts").update(update).eq("id", row_id).execute()


def _finish(db, row_id: str, status: str, result: dict | None, error: str | None = None) -> None:
    update: dict = {
        "status": status,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
    if result is not None:
        update["result"] = json.dumps(result)
    if error:
        update["error"] = error
    db.table("scheduled_broadcasts").update(update).eq("id", row_id).execute()

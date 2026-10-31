import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Request, Response
from app.db.supabase import get_supabase
from app.config import settings
from app.services.growth import record_stage_event
from app.services.google_ads_attribution import parse_google_ref
from app.services.failover import update_number_quality, handle_quality_red, handle_quality_yellow, set_portfolio_limit
from app.services.meta_cloud import tier_from_capability_update
from app.services.meta_webhook_verify import verify_meta_signature
from app.services.entitlements import meter
from app.services.segmentation import new_lead_score_and_segment

logger = logging.getLogger(__name__)
router = APIRouter()

# Exact-match opt-out phrases. Checked on every inbound message, not just the first
# reply after a template send -- until 2026-09-09 this only fired inside a broadcast
# window, so "stop" typed mid-conversation (including mid-paid-intake) fell through
# to intake.py's _CANCEL_WORDS instead, which cancels a session but records no
# opted_out flag. The list stays deliberately tiny and exact-match (see
# test_opt_out_keywords.py's documented gap on decorated forms) so a false positive
# here -- silently killing re-engagement for a lead who typed something else -- stays
# effectively impossible.
_STOP_WORDS = frozenset({"stop", "unsubscribe", "ஆர்வம் இல்லை"})

# Sent for an image/document/video/sticker with no caption -- there is nothing
# to read (unlike audio, which is transcribed) and total silence was the prior
# behaviour. Deduped per lead so a burst of uncaptioned photos gets one reply.
_MEDIA_ACK_TEXT = (
    "We can't read files or photos on this chat — please type your reply as a message.\n"
    "இந்த சாட்டில் படங்கள்/கோப்புகளை படிக்க முடியாது — தயவுசெய்து உங்கள் பதிலை தட்டச்சு செய்யவும்."
)
_MEDIA_ACK_DEDUPE_HOURS = 6
# Phones per leads lookup when a coexistence contact sync arrives (keeps the URL short).
_CONTACT_SYNC_CHUNK = 200


def _is_opt_out(body: str) -> bool:
    normalized = body.lower().strip()
    return normalized in _STOP_WORDS


# Meta delivery error codes that mean the RECIPIENT's number itself is the problem
# (invalid number / not on WhatsApp / blocked the business) — safe to permanently
# exclude that one lead. 131026 matches upload.py's own "undeliverable" mapping.
# Every other failure code (transient throttles like 131049/131048/131056/130472,
# and account-level failures like 131031 "Business Account locked") is NOT
# evidence this specific number is bad — flagging the lead for those would
# wrongly blacklist a healthy contact every time the account itself gets
# rate-limited or restricted.
PERMANENT_UNDELIVERABLE_ERROR_CODES = frozenset({131026})


def _is_recipient_undeliverable_error(code) -> bool:
    try:
        return int(code) in PERMANENT_UNDELIVERABLE_ERROR_CODES
    except (TypeError, ValueError):
        return False


def _delivery_fail_detail(err: dict) -> str:
    """Human-readable detail from a Meta status-webhook error object.

    Mirrors _meta_error_detail() on the send path so broadcast_recipients.fail_detail
    reads the same whether Meta rejected the send synchronously or reported the
    failure later via webhook. error_data.details carries Meta's richest text
    ("Failed to send message because there were one or more errors related to your
    payment method."); title/message are the terse fallbacks.
    """
    if not err:
        return ""
    error_data = err.get("error_data")
    detail = (error_data or {}).get("details") if isinstance(error_data, dict) else None
    detail = (detail or err.get("message") or err.get("title") or "").strip()
    if not detail:
        return ""
    code = err.get("code")
    if code is not None and f"#{code}" not in detail:
        detail = f"(#{code}) {detail}"
    return detail[:300]


def _get_tenant_id_for_meta_number(phone_number_id: str, db) -> str | None:
    try:
        result = db.table("phone_numbers").select("tenant_id").eq("meta_phone_number_id", phone_number_id).maybe_single().execute()
        return (result.data or {}).get("tenant_id") if result else None
    except Exception:
        return None


def _get_tenant_id_for_waba(waba_id: str, db) -> str | None:
    """The one tenant whose connected WABA this is. A WABA shared by several
    tenants is ambiguous, so None -- never guess whose payload it is."""
    try:
        rows = db.table("app_settings").select("tenant_id").eq("key", "meta_waba_id").eq("value", waba_id).execute().data or []
        tenants = {r["tenant_id"] for r in rows if r.get("tenant_id")}
        return tenants.pop() if len(tenants) == 1 else None
    except Exception:
        return None


async def _handle_opt_out(phone: str, tenant_id: str, db) -> bool:
    try:
        lead = db.table("leads").select("id").eq("phone", phone).eq("tenant_id", tenant_id).maybe_single().execute()
        if not lead or not lead.data:
            return False
        lead_id = lead.data["id"]
        await _record_per_broadcast_opt_out(lead_id, phone, tenant_id, db)
        logger.info(f"Lead {lead_id} hard-opted out from {phone}")
        try:
            # A text opt-out is a marketing opt-out, not a refund -- exclude 'paid'
            # (and 'resolved', already outside intake.py's _ACTIVE_STATUSES) so
            # someone who already paid still receives the consultation they bought.
            cancelled_sessions = db.table("intake_sessions").update({"status": "cancelled"}).eq(
                "lead_id", lead_id
            ).eq("tenant_id", tenant_id).in_(
                "status",
                [
                    "offer_pending", "awaiting_package_choice", "awaiting_addon_choice",
                    "collecting", "awaiting_confirmation", "awaiting_payment",
                ],
            ).execute()
            from app.services.deals import sync_intake_session
            for session in cancelled_sessions.data or []:
                sync_intake_session(session, db=db)
        except Exception as e:
            logger.warning(f"Cancelling in-progress intake session on opt-out failed for lead {lead_id}: {e}")
        try:
            from app.services.meta_cloud import send_text_message
            await send_text_message(
                to_number=phone,
                text="நன்றி! உங்கள் விருப்பத்தை மதிக்கிறோம். இனிமேல் நாங்கள் உங்களை தொடர்பு கொள்ள மாட்டோம். 🙏\n\n(Thank you! We respect your preference and will not contact you further.)",
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning(f"Opt-out reply failed for {phone}: {e}")
        return True
    except Exception as e:
        logger.error(f"opt-out DB update failed for {phone}: {e}")
        return False


async def _record_per_broadcast_opt_out(lead_id: str, phone: str, tenant_id: str, db) -> None:
    recipient_row: dict | None = None
    tag_id: str | None = None
    try:
        recent = (
            db.table("broadcast_recipients")
            .select("id, broadcast_id, tag_id, created_at")
            .eq("tenant_id", tenant_id)
            .eq("lead_id", lead_id)
            .eq("send_status", "sent")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        recipient_row = (recent.data or [None])[0] if recent.data else None
        tag_id = recipient_row.get("tag_id") if recipient_row else None
    except Exception as e:
        logger.error(f"Per-broadcast opt-out: recipient lookup failed for {phone}: {e}")

    if recipient_row:
        try:
            db.table("broadcast_recipients").update({
                "send_status": "opted_out_skip",
                "opted_out_at": datetime.now(timezone.utc).isoformat(),
                "fail_reason": "opted_out",
            }).eq("id", recipient_row["id"]).eq("tenant_id", tenant_id).execute()
        except Exception as e:
            logger.warning(f"Per-broadcast opt-out: opted_out_at update failed (migration 085?): {e}")
            try:
                db.table("broadcast_recipients").update({
                    "send_status": "opted_out_skip",
                    "fail_reason": "opted_out",
                }).eq("id", recipient_row["id"]).eq("tenant_id", tenant_id).execute()
                logger.info(f"Per-broadcast opt-out: fell back to send_status-only update for {phone}")
            except Exception as e2:
                logger.error(f"Per-broadcast opt-out: send_status update also failed for {phone}: {e2}")

    try:
        if tag_id:
            db.table("lead_tag_opt_outs").upsert({
                "tenant_id": tenant_id,
                "lead_id": lead_id,
                "tag_id": tag_id,
                "opted_out_at": datetime.now(timezone.utc).isoformat(),
                "source": "inbound",
            }, on_conflict="tenant_id,lead_id,tag_id").execute()
        else:
            tags = db.table("broadcast_tags").select("id").eq("tenant_id", tenant_id).execute()
            for t in (tags.data or []):
                db.table("lead_tag_opt_outs").upsert({
                    "tenant_id": tenant_id,
                    "lead_id": lead_id,
                    "tag_id": t["id"],
                    "opted_out_at": datetime.now(timezone.utc).isoformat(),
                    "source": "inbound",
                }, on_conflict="tenant_id,lead_id,tag_id").execute()
            try:
                db.table("lead_tag_opt_outs").insert({
                    "tenant_id": tenant_id,
                    "lead_id": lead_id,
                    "tag_id": None,
                    "opted_out_at": datetime.now(timezone.utc).isoformat(),
                    "source": "inbound",
                }).execute()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Per-broadcast opt-out: lead_tag_opt_outs insert failed (table missing?): {e}")

    try:
        db.table("leads").update({
            "opted_out": True,
            "opted_out_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.error(f"Per-broadcast opt-out: leads.opted_out update failed for {phone}: {e}")

    logger.info(f"Per-broadcast opt-out recorded for {phone} (broadcast_recipient={recipient_row is not None}, tag_id={tag_id})")


def _has_prior_inbound_in_broadcast(lead_id: str, broadcast_sent_at: str | None, tenant_id: str, db, exclude_msg_id: str) -> bool:
    if not broadcast_sent_at:
        return False
    try:
        prior = (
            db.table("messages")
            .select("id")
            .eq("lead_id", lead_id)
            .eq("tenant_id", tenant_id)
            .eq("direction", "inbound")
            .gte("created_at", broadcast_sent_at)
            .neq("meta_message_id", exclude_msg_id)
            .limit(1)
            .execute()
        )
        return bool(prior.data)
    except Exception:
        return False


@router.get("")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    from app.config_dynamic import get_setting
    from app.db.supabase import get_supabase as _get_db

    # Check the incoming token against every tenant's configured verify token,
    # then fall back to the global env var. This supports multiple tenants all
    # sharing the single /webhook/whatsapp endpoint.
    if mode == "subscribe" and token:
        # Try each tenant's stored verify token
        try:
            _db = _get_db()
            rows = (
                _db.table("app_settings")
                .select("value")
                .eq("key", "meta_webhook_verify_token")
                .execute()
            )
            for row in (rows.data or []):
                if row.get("value") and row["value"] == token:
                    logger.info("WhatsApp webhook verified (tenant token match)")
                    return Response(content=challenge, media_type="text/plain")
        except Exception as _e:
            logger.warning(f"WhatsApp verify: tenant token lookup failed: {_e}")

        # Fall back to global env var
        global_token = settings.meta_verify_token or get_setting("meta_webhook_verify_token")
        if global_token and token == global_token:
            logger.info("WhatsApp webhook verified (global token)")
            return Response(content=challenge, media_type="text/plain")

    logger.warning(f"Webhook verification failed — token mismatch. received={token}")
    return Response(content="Forbidden", status_code=403)


def _resolve_tenant_from_payload(payload: dict, db) -> str | None:
    """Extract first phone_number_id from payload and look up its tenant."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_id = (
                value.get("metadata", {}).get("phone_number_id")
                or value.get("phone_number_id", "")
            )
            if phone_id:
                tenant = _get_tenant_id_for_meta_number(phone_id, db)
                if tenant:
                    return tenant
    # Account-level events (business_capability_update) carry no phone number,
    # only the WABA id as entry.id. The signature is still verified against
    # the tenant found here.
    for entry in payload.get("entry", []):
        if entry.get("id") and any(c.get("field") == "business_capability_update" for c in entry.get("changes", [])):
            tenant = _get_tenant_id_for_waba(str(entry["id"]), db)
            if tenant:
                return tenant
    # Template events (status, edits) carry the template id, not a phone number.
    from app.routes.templates import tenant_for_template_payload
    return tenant_for_template_payload(db, payload)


async def _transcribe_whatsapp_audio(media_id: str, tenant_id: str) -> tuple[str, str]:
    from app.services.meta_cloud import download_media_from_meta
    from app.services.gemini_client import gemini_speech_to_text

    audio_bytes, mime_type, _media_url = await download_media_from_meta(media_id, tenant_id=tenant_id)
    transcript = await gemini_speech_to_text(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        tenant_id=tenant_id,
    )
    return transcript, mime_type


async def _process_inbound_message_background(
    lead_id: str,
    tenant_id: str,
    phone: str,
    body: str,
    msg_type: str,
    meta_phone_number_id: str = "",
    meta_message_id: str = "",
    meta_media_id: str = "",
    interactive_id: str = "",
) -> None:
    from app.db.supabase import get_supabase
    db = get_supabase()
    try:
        if msg_type == "audio" and not body and meta_media_id:
            try:
                body, media_mime_type = await _transcribe_whatsapp_audio(meta_media_id, tenant_id)
                meter(db, tenant_id, "ai_speech_to_text")
            except Exception as audio_err:
                logger.error(f"Audio transcription failed for lead {lead_id} media {meta_media_id}: {audio_err}")
                return
            if not body:
                logger.info(f"Audio message {meta_media_id} produced empty transcript for lead {lead_id}")
                return
            db.table("messages").insert({
                "lead_id": lead_id,
                "direction": "inbound",
                "channel": "whatsapp",
                "content": body,
                "is_ai_generated": False,
                "meta_message_id": meta_message_id or meta_media_id,
                "tenant_id": tenant_id,
                "media_url": f"meta:{meta_media_id}",
                "media_type": "audio",
                "media_mime_type": media_mime_type,
            }).execute()
            # The thread has moved on — drop any pending silence nudge. This is
            # an optimisation only; _thread_unchanged() at fire time is what
            # actually prevents a nudge landing on top of a reply.
            try:
                from app.services.silence_nudge import cancel_pending
                cancel_pending(db, lead_id)
            except Exception:
                logger.exception("Silence nudge cancel failed for lead %s", lead_id)
            try:
                from app.services.notify import notify_assigned_caller_of_reply
                notify_assigned_caller_of_reply(lead_id, tenant_id, db=db)
            except Exception:
                pass
            try:
                db.table("leads").update({"outbound_no_reply_count": 0}).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
            except Exception:
                pass

        # Update conversation state counters
        from app.services.conversation_state import get_or_create_state
        from datetime import datetime, timedelta, timezone
        conv_state = get_or_create_state(lead_id, tenant_id, db)
        new_count = (conv_state.get("message_count") or 0) + 1

        db.table("lead_conversation_state").update({
            "message_count": new_count,
            "last_activity_at": datetime.now(timezone.utc).isoformat(),
        }).eq("lead_id", lead_id).eq("tenant_id", tenant_id).execute()

        # Check if compaction needed (threshold: 10)
        if new_count >= 10:
            try:
                from app.services.conversation_compactor import compact_conversation
                await compact_conversation(lead_id, tenant_id, db, mode="rolling")
            except Exception as compact_err:
                logger.error(f"Compaction failed for lead {lead_id}: {compact_err}")

        # Route text-like inbound content, including transcribed audio, a
        # captioned image/document/video (caption as body), and a location pin
        # (synthesized to text in the webhook loop above) into the reply engine.
        # Uncaptioned media and every sticker fall through to the ack branch below
        # instead -- `body` is empty for those, so this condition already excludes them.
        if msg_type in ("text", "button", "interactive", "audio", "image", "document", "video", "location") and body:
            if meta_message_id and meta_phone_number_id:
                try:
                    from app.services.meta_cloud import send_typing_indicator
                    await send_typing_indicator(
                        message_id=meta_message_id,
                        phone_number_id=meta_phone_number_id,
                        tenant_id=tenant_id,
                    )
                except Exception as typing_err:
                    logger.warning(f"Typing indicator failed for lead {lead_id}: {typing_err}")
            # Must run BEFORE route_intake: a consumed turn never reaches
            # generate_reply, so a lead who asks for Tamil mid-intake would
            # otherwise never get the lock set.
            try:
                from app.services.ai_reply import record_tamil_lock_request
                record_tamil_lock_request(db, lead_id, tenant_id, body)
            except Exception as e:
                logger.error(f"Tamil lock check failed for lead {lead_id}: {e}")
            # No pre-AI interception any more: selling packages, collecting the client's
            # required details and sending the payment link are tools the reply brain
            # calls itself (services/deal_turn.py). route_intake stays in intake.py,
            # unused, until the legacy state machine is removed.
            try:
                from app.services.context_builder import build_scorer_context
                context_block = build_scorer_context(lead_id, db)
                from app.services.ai_reply import generate_reply
                await generate_reply(
                    lead_id=lead_id,
                    message=body,
                    phone=phone,
                    context_block=context_block,
                    phone_number_id=meta_phone_number_id or None,
                    inbound_media_type=msg_type,
                    meta_message_id=meta_message_id or meta_media_id or None,
                    interactive_id=interactive_id or None,
                )
            except Exception as e:
                logger.error(f"Reply routing failed for lead {lead_id}: {e}")
        elif msg_type in ("image", "document", "video", "sticker"):
            # No caption to route as text and no transcript to produce (unlike
            # audio) -- we genuinely cannot read this. One canned line beats the
            # total silence this used to be. Deduped to once per lead per window
            # so a lead sending ten photos in a row gets one reply, not ten.
            # Still a lead message: it restarts their open deal's idle clock (D3). Text-like
            # messages do the same inside generate_reply.
            from app.services.intake import note_lead_message
            note_lead_message(db, tenant_id, lead_id)
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=_MEDIA_ACK_DEDUPE_HOURS)).isoformat()
                recent = (
                    db.table("messages")
                    .select("id")
                    .eq("lead_id", lead_id)
                    .eq("direction", "outbound")
                    .eq("content", _MEDIA_ACK_TEXT)
                    .gte("created_at", cutoff)
                    .limit(1)
                    .execute()
                )
                if not (recent and recent.data):
                    from app.services.ai_reply import send_whatsapp
                    mid = await send_whatsapp(phone, _MEDIA_ACK_TEXT, tenant_id=tenant_id, phone_number_id=meta_phone_number_id or None)
                    db.table("messages").insert({
                        "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound",
                        "channel": "whatsapp", "content": _MEDIA_ACK_TEXT, "is_ai_generated": False,
                        "meta_message_id": mid, "reply_source": "automation",
                    }).execute()
            except Exception as e:
                logger.error(f"Media ack failed for lead {lead_id}: {e}")
    except Exception as err:
        logger.error(f"Background inbound message processing failed for lead {lead_id}: {err}")


def _apply_status_updates(db, tenant_id: str, statuses: list) -> None:
    """Meta delivery receipts (delivered, read, failed). Sync Supabase calls, run in
    a worker thread: every campaign send comes back as several of these, and one
    stalled query on the event loop froze the whole server for 35-45 s (24 and 26
    Oct 2026)."""
    for status_update in statuses:
        message_id = status_update.get("id")
        status = status_update.get("status")

        if message_id and status == "failed":
            # Meta's limit counts delivered messages only, so a template
            # that failed no longer counts against it.
            try:
                db.table("template_send_log").delete()                                 .eq("meta_message_id", message_id).eq("tenant_id", tenant_id).execute()
            except Exception as e:
                logger.warning(f"Un-counting failed template {message_id} failed: {e}")

        if message_id and status in ("delivered", "read", "failed"):
            try:
                update_payload: dict = {"delivery_status": status}
                err_code = None
                err_detail = ""
                # Capture Meta error code + title on failed status — surfaced in failed CSV
                if status == "failed":
                    errs = status_update.get("errors") or []
                    if errs:
                        first = errs[0] or {}
                        err_code = first.get("code")
                        err_title = first.get("title") or first.get("message")
                        err_detail = _delivery_fail_detail(first)
                        if err_code is not None:
                            update_payload["delivery_error_code"] = err_code
                        if err_title:
                            update_payload["delivery_error_title"] = err_title[:200]
                        logger.warning(
                            f"Meta delivery failure msg={message_id} code={err_code} "
                            f"title={err_title!r} detail={err_detail!r}"
                        )
                try:
                    updated = db.table("messages") \
                        .update(update_payload) \
                        .eq("meta_message_id", message_id) \
                        .eq("tenant_id", tenant_id) \
                        .execute()
                except Exception as col_err:
                    # Migration 061 may not be applied yet — retry without error columns
                    if "delivery_error_code" in str(col_err) or "delivery_error_title" in str(col_err):
                        logger.warning(f"Migration 061 not applied — saving status only: {col_err}")
                        updated = db.table("messages") \
                            .update({"delivery_status": status}) \
                            .eq("meta_message_id", message_id) \
                            .eq("tenant_id", tenant_id) \
                            .execute()
                    else:
                        raise
                logger.info(f"Message {message_id} status updated to {status}")
                # Mark lead as undeliverable so it's hidden from active views.
                # Only flag the LEAD for error codes that specifically mean this
                # recipient's number is the problem (e.g. 131026 wrong number).
                # Everything else — transient throttles AND account-level failures
                # like 131031 "Business Account locked" — is not evidence this
                # number is bad, and must not permanently blacklist the lead.
                #
                # broadcast_recipients.send_status is deliberately NOT changed here.
                # The row stays 'sent'; delivery failures are derived from
                # messages.delivery_status (failed CSV, tag counts, segment CSV).
                # Many readers treat send_status='sent' as "this lead was messaged"
                # (leads list, re-engagement, template_performance), so relabelling
                # a row would silently drop healthy leads over account-level
                # failures like 131042 payment issues.
                if status == "failed" and updated.data:
                    failed_lead_id = updated.data[0].get("lead_id")
                    if failed_lead_id:
                        if _is_recipient_undeliverable_error(err_code):
                            db.table("leads").update({"whatsapp_undeliverable": True}) \
                                .eq("id", failed_lead_id).eq("tenant_id", tenant_id).execute()
                        else:
                            logger.info(f"Delivery error {err_code} for lead {failed_lead_id} is not recipient-specific — not flagging undeliverable")
                    # Stamp Meta's own explanation so the failed CSV's fail_detail
                    # column is populated for webhook failures too, not just
                    # synchronous send rejections.
                    if err_detail:
                        try:
                            db.table("broadcast_recipients") \
                                .update({"fail_detail": err_detail}) \
                                .eq("meta_message_id", message_id) \
                                .eq("tenant_id", tenant_id) \
                                .execute()
                        except Exception as _fd_err:
                            logger.warning(f"broadcast_recipients fail_detail update failed: {_fd_err}")
                # Lead proved reachable again — clear any stale undeliverable flag.
                if status in ("delivered", "read") and updated.data:
                    reachable_lead_id = updated.data[0].get("lead_id")
                    if reachable_lead_id:
                        try:
                            db.table("leads").update({"whatsapp_undeliverable": False}) \
                                .eq("id", reachable_lead_id).eq("tenant_id", tenant_id) \
                                .eq("whatsapp_undeliverable", True).execute()
                        except Exception as _wu_err:
                            logger.warning(f"Failed to clear whatsapp_undeliverable for lead {reachable_lead_id}: {_wu_err}")
                # Bot Flow Builder per-node analytics: bump node delivered_count once
                if status == "delivered" and updated.data:
                    step_id = updated.data[0].get("automation_step_id")
                    if step_id:
                        try:
                            db.rpc("bump_automation_step_counter", {
                                "p_step_id": step_id,
                                "p_field": "delivered_count",
                                "p_delta": 1,
                            }).execute()
                        except Exception as e:
                            logger.warning(f"Failed to bump delivered_count for step {step_id}: {e}")
            except Exception as e:
                logger.error(f"Failed to update message {message_id} status to {status}: {e}")


@router.post("")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except Exception:
        payload = {}

    # Verify Meta X-Hub-Signature-256 (fail-closed: missing or invalid signatures are ignored)
    signature = request.headers.get("x-hub-signature-256")
    if not signature:
        logger.warning("WhatsApp webhook: missing signature — dropping")
        return Response(content="OK", status_code=200)
    db_sig = get_supabase()
    # Sync Supabase reads, off the event loop (see _apply_status_updates).
    tenant_for_sig = await asyncio.to_thread(_resolve_tenant_from_payload, payload, db_sig)
    if not tenant_for_sig:
        logger.warning("WhatsApp webhook: no tenant for signed payload — dropping")
        return Response(content="OK", status_code=200)
    if not await asyncio.to_thread(verify_meta_signature, raw_body, signature, tenant_for_sig):
        logger.warning(f"WhatsApp webhook: invalid signature for tenant={tenant_for_sig} — dropping")
        return Response(content="OK", status_code=200)
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field = change.get("field")
            value = change.get("value", {})

            if field == "phone_number_quality_update":
                meta_phone_number_id = value.get("phone_number_id")
                db_qual = get_supabase()
                owner_tenant = _get_tenant_id_for_meta_number(meta_phone_number_id, db_qual) if meta_phone_number_id else None
                if owner_tenant != tenant_for_sig:
                    logger.warning(
                        f"phone_number_quality_update: meta_id={meta_phone_number_id} belongs to "
                        f"tenant {owner_tenant}, not the signed tenant {tenant_for_sig} — skipping"
                    )
                    continue
                quality_rating = value.get("quality_rating", "")
                # The business-wide limit (shared by every number), not the
                # deprecated per-number current_limit.
                portfolio_tier = tier_from_capability_update(value)
                logger.info(f"phone_number_quality_update: meta_id={meta_phone_number_id} quality={quality_rating} limit={portfolio_tier}")
                row_id = await update_number_quality(meta_phone_number_id, quality_rating)
                if portfolio_tier:
                    set_portfolio_limit(owner_tenant, portfolio_tier)
                if row_id:
                    if quality_rating == "RED":
                        await handle_quality_red(row_id)
                    elif quality_rating == "YELLOW":
                        await handle_quality_yellow(row_id)

            elif field in ("message_template_status_update", "message_template_components_update"):
                # Status changes and edits for a template. Only the signed
                # tenant's own copy is written.
                from app.routes.templates import apply_template_change
                apply_template_change(get_supabase(), field, value, tenant_id=tenant_for_sig)

            elif field == "business_capability_update":
                # Meta raised (or set) the business's messaging limit. entry.id is
                # the WABA; it must be the signed tenant's own WABA.
                waba_id = str(entry.get("id") or "")
                if not waba_id or _get_tenant_id_for_waba(waba_id, get_supabase()) != tenant_for_sig:
                    logger.warning(f"business_capability_update: WABA {waba_id} is not tenant {tenant_for_sig}'s -- skipping")
                    continue
                portfolio_tier = tier_from_capability_update(value)
                logger.info(f"business_capability_update: tenant={tenant_for_sig} limit={portfolio_tier}")
                if portfolio_tier:
                    set_portfolio_limit(tenant_for_sig, portfolio_tier)

            elif field == "history":
                meta_phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                db = get_supabase()
                tenant_id = _get_tenant_id_for_meta_number(meta_phone_number_id, db) if meta_phone_number_id else None
                if not tenant_id:
                    logger.warning(f"No tenant for meta phone_number_id={meta_phone_number_id}, dropping history payload")
                    continue
                if tenant_id != tenant_for_sig:
                    logger.warning(
                        f"history: meta_phone_number_id={meta_phone_number_id} belongs to tenant "
                        f"{tenant_id}, not the signed tenant {tenant_for_sig} — dropping"
                    )
                    continue
                for chunk in value.get("history", []):
                    for thread in chunk.get("threads", []):
                        wa_id = thread.get("id", "")
                        phone = f"+{wa_id}" if wa_id and not wa_id.startswith("+") else wa_id
                        if not phone:
                            continue

                        lead = db.table("leads").select("id").eq("phone", phone).eq("tenant_id", tenant_id).limit(1).execute()
                        if not lead.data:
                            logger.info(f"history: no lead for phone={phone} tenant={tenant_id}, skipping thread")
                            continue
                        lead_id = lead.data[0]["id"]

                        for msg in thread.get("messages", []):
                            msg_type = msg.get("type")
                            msg_id = msg.get("id", "")
                            if msg_type != "text":
                                logger.info(f"history: skipping unsupported type={msg_type}")
                                continue
                            body = (msg.get("text") or {}).get("body", "").strip()
                            timestamp = msg.get("timestamp")
                            if not body or not msg_id or not timestamp:
                                continue

                            already = db.table("messages").select("id").eq("meta_message_id", msg_id).eq("tenant_id", tenant_id).limit(1).execute()
                            if already.data:
                                continue

                            direction = "outbound" if msg.get("to") else "inbound"
                            created_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()

                            db.table("messages").insert({
                                "lead_id": lead_id,
                                "tenant_id": tenant_id,
                                "direction": direction,
                                "channel": "whatsapp",
                                "content": body,
                                "is_ai_generated": False,
                                "meta_message_id": msg_id,
                                "created_at": created_at,
                            }).execute()
                            logger.info(f"history: backfilled {direction} message for lead {lead_id}")

            elif field == "smb_app_state_sync":
                meta_phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                db = get_supabase()
                tenant_id = _get_tenant_id_for_meta_number(meta_phone_number_id, db) if meta_phone_number_id else None
                if not tenant_id:
                    logger.warning(f"No tenant for meta phone_number_id={meta_phone_number_id}, dropping smb_app_state_sync payload")
                    continue
                if tenant_id != tenant_for_sig:
                    logger.warning(
                        f"smb_app_state_sync: meta_phone_number_id={meta_phone_number_id} belongs to "
                        f"tenant {tenant_id}, not the signed tenant {tenant_for_sig} — dropping"
                    )
                    continue
                names_by_phone: dict[str, str] = {}
                for entry_row in value.get("state_sync", []):
                    if entry_row.get("type") != "contact" or entry_row.get("action") == "remove":
                        continue
                    contact = entry_row.get("contact", {})
                    wa_id = contact.get("phone_number", "")
                    full_name = (contact.get("full_name") or "").strip()
                    phone = f"+{wa_id}" if wa_id and not wa_id.startswith("+") else wa_id
                    if phone and full_name:
                        names_by_phone.setdefault(phone, full_name)

                # Meta re-sends the whole contact list every ~27 min: one lookup per contact
                # was ~16k leads requests a day (2026-10-31), so look them up in chunks.
                phones = list(names_by_phone)
                enriched: set[str] = set()
                for i in range(0, len(phones), _CONTACT_SYNC_CHUNK):
                    leads = (
                        db.table("leads").select("id,name,phone")
                        .in_("phone", phones[i:i + _CONTACT_SYNC_CHUNK])
                        .eq("tenant_id", tenant_id).execute()
                    )
                    for lead_row in leads.data or []:
                        phone = lead_row.get("phone")
                        if lead_row.get("name") or phone in enriched or phone not in names_by_phone:
                            continue
                        enriched.add(phone)
                        db.table("leads").update({"name": names_by_phone[phone]}).eq("id", lead_row["id"]).eq("tenant_id", tenant_id).execute()
                        logger.info(f"smb_app_state_sync: enriched name for lead {lead_row['id']}")

            elif field == "smb_message_echoes":
                meta_phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                db = get_supabase()
                tenant_id = _get_tenant_id_for_meta_number(meta_phone_number_id, db) if meta_phone_number_id else None
                if not tenant_id:
                    logger.warning(f"No tenant for meta phone_number_id={meta_phone_number_id}, dropping smb_message_echoes payload")
                    continue
                if tenant_id != tenant_for_sig:
                    logger.warning(
                        f"smb_message_echoes: meta_phone_number_id={meta_phone_number_id} belongs to "
                        f"tenant {tenant_id}, not the signed tenant {tenant_for_sig} — dropping"
                    )
                    continue
                for echo in value.get("message_echoes", []):
                    echo_type = echo.get("type")
                    echo_id = echo.get("id", "")
                    if echo_type != "text":
                        logger.info(f"smb_message_echoes: skipping unsupported type={echo_type}")
                        continue
                    body = (echo.get("text") or {}).get("body", "").strip()
                    wa_id = echo.get("to", "")
                    phone = f"+{wa_id}" if wa_id and not wa_id.startswith("+") else wa_id
                    if not phone or not body or not echo_id:
                        continue

                    already = db.table("messages").select("id").eq("meta_message_id", echo_id).eq("tenant_id", tenant_id).limit(1).execute()
                    if already.data:
                        continue

                    lead = db.table("leads").select("id").eq("phone", phone).eq("tenant_id", tenant_id).limit(1).execute()
                    if not lead.data:
                        logger.warning(f"smb_message_echoes: no lead for phone={phone} tenant={tenant_id}, dropping")
                        continue
                    lead_id = lead.data[0]["id"]

                    db.table("messages").insert({
                        "lead_id": lead_id,
                        "tenant_id": tenant_id,
                        "direction": "outbound",
                        "channel": "whatsapp",
                        "content": body,
                        "is_ai_generated": False,
                        "meta_message_id": echo_id,
                    }).execute()
                    logger.info(f"smb_message_echoes: recorded phone-app message for lead {lead_id}")

            elif field == "messages":
                meta_phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                db = get_supabase()
                tenant_id = (
                    await asyncio.to_thread(_get_tenant_id_for_meta_number, meta_phone_number_id, db)
                    if meta_phone_number_id else None
                )
                if not tenant_id:
                    logger.warning(f"No tenant for meta phone_number_id={meta_phone_number_id}, dropping WhatsApp payload")
                    continue
                if tenant_id != tenant_for_sig:
                    logger.warning(
                        f"messages: meta_phone_number_id={meta_phone_number_id} belongs to tenant "
                        f"{tenant_id}, not the signed tenant {tenant_for_sig} — dropping"
                    )
                    continue
                for msg in value.get("messages", []):
                    msg_type = msg.get("type")
                    msg_id = msg.get("id", "")
                    # image/document/video/sticker: persisted and, if captioned,
                    # routed through the normal text pipeline using the caption;
                    # uncaptioned (every sticker included) gets one canned ack
                    # instead of silence (see the media-ack block below).
                    # location: converted to text on the spot, same shape as a
                    # transcribed voice note, so it flows through unchanged --
                    # including mid-intake, where it can answer a field like
                    # "which area" with no field-name special-casing needed.
                    if msg_type not in (
                        "text", "button", "interactive", "audio",
                        "image", "document", "video", "sticker", "location",
                    ):
                        continue
                    wa_id = msg.get("from", "")
                    phone = f"+{wa_id}" if wa_id and not wa_id.startswith("+") else wa_id
                    media_id = ""
                    media_mime_type = ""
                    interactive_id = ""
                    is_media_type = msg_type in ("audio", "image", "document", "video", "sticker")
                    if msg_type == "text":
                        body = msg.get("text", {}).get("body", "").strip()
                    elif msg_type == "button":
                        body = msg.get("button", {}).get("text", "").strip()
                    elif msg_type == "interactive":
                        inter = msg.get("interactive", {})
                        reply = inter.get("button_reply") or inter.get("list_reply") or {}
                        body = (reply.get("title") or "").strip()
                        # The id intake.py's menu-builders set to the package/addon's own
                        # key -- the one value that still matches after a button_label
                        # shortened the title, or a list row got truncated to WhatsApp's
                        # 24-char cap. See match_package's docstring in intake.py.
                        interactive_id = (reply.get("id") or "").strip()
                    elif msg_type == "audio":
                        media_id = (msg.get("audio") or {}).get("id", "").strip()
                        body = ""
                    elif msg_type in ("image", "video", "document"):
                        media_obj = msg.get(msg_type) or {}
                        media_id = (media_obj.get("id") or "").strip()
                        media_mime_type = media_obj.get("mime_type", "")
                        body = (media_obj.get("caption") or "").strip()
                    elif msg_type == "sticker":
                        media_obj = msg.get("sticker") or {}
                        media_id = (media_obj.get("id") or "").strip()
                        media_mime_type = media_obj.get("mime_type", "")
                        body = ""  # WhatsApp stickers never carry a caption
                    elif msg_type == "location":
                        loc = msg.get("location") or {}
                        lat, lng = loc.get("latitude"), loc.get("longitude")
                        label = ", ".join(p for p in (loc.get("name"), loc.get("address")) if p)
                        body = f"Location: {label}" if label else (f"Location: {lat}, {lng}" if lat and lng else "")
                    else:
                        body = ""

                    if not phone or (is_media_type and not media_id) or (not is_media_type and not body):
                        continue

                    logger.info(f"Inbound Meta WhatsApp from {phone}: type={msg_type} body={body!r}")

                    existing = db.table("leads").select("id,score,segment,deleted_at,ai_enabled,whatsapp_undeliverable").eq("phone", phone).eq("tenant_id", tenant_id).limit(1).execute()
                    if existing.data:
                        lead_id = existing.data[0]["id"]
                        if meta_phone_number_id:
                            # Which of the tenant's numbers this lead talks to, so
                            # out-of-band replies (astrologer) stay in this thread
                            # even after a failover moves the primary.
                            try:
                                db.table("leads").update({"last_inbound_phone_number_id": meta_phone_number_id})                                     .eq("id", lead_id).eq("tenant_id", tenant_id).execute()
                            except Exception as e:
                                logger.warning(f"Failed to record inbound number for lead {lead_id}: {e}")
                        if existing.data[0].get("deleted_at"):
                            db.table("leads").update({
                                "deleted_at": None,
                                "ai_enabled": True,
                                "needs_human_intervention": False,
                            }).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
                            logger.info(f"Restored soft-deleted lead {lead_id} on inbound message")
                        if existing.data[0].get("whatsapp_undeliverable"):
                            try:
                                db.table("leads").update({"whatsapp_undeliverable": False}) \
                                    .eq("id", lead_id).eq("tenant_id", tenant_id).execute()
                                logger.info(f"Cleared whatsapp_undeliverable for lead {lead_id} — inbound message proves reachable")
                            except Exception as e:
                                logger.warning(f"Failed to clear whatsapp_undeliverable for lead {lead_id}: {e}")
                    else:
                        initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
                        new_lead = db.table("leads").insert({
                            "phone": phone,
                            "source": "whatsapp",
                            "score": initial_score,
                            "segment": initial_segment,
                            "tenant_id": tenant_id,
                            "opt_in_source": "whatsapp",
                            "last_inbound_phone_number_id": meta_phone_number_id or None,
                        }).execute()
                        lead_id = new_lead.data[0]["id"]
                        record_stage_event(lead_id, to_segment=initial_segment, event_type="created", metadata={"source": "whatsapp"}, tenant_id=tenant_id, db=db)
                        try:
                            from app.services.assignment import maybe_assign_lead
                            maybe_assign_lead(lead_id, tenant_id, initial_segment, "whatsapp", reason="created")
                        except Exception as e:
                            logger.warning(f"Auto-assign failed for lead {lead_id}: {e}")

                    # Meta CTWA: count one lead once per ad. Meta's referral ad
                    # id is primary; the pre-filled [ANRIL:...] (or old [AIRA:...]) code is fallback.
                    ad_attributed = False
                    # Which creative produced THIS message -- distinct from
                    # leads.attributed_ad_creative_id, which is intentionally not
                    # overwritten on repeat contacts and could point to a stale,
                    # different ad. scoring_engine.py needs the creative tied to
                    # this exact message to compare against its real pre-fill text.
                    attributed_creative_id_for_message = None
                    referral = msg.get("referral")
                    referral_ad_id = (
                        (referral or {}).get("source_id", "")
                        if (referral or {}).get("source_type") == "ad"
                        else ""
                    )
                    try:
                        from app.services.meta_ads_insights_sync import get_current_ads_account_id
                        from app.services.meta_ctwa_attribution import (
                            find_creative_for_message,
                            record_lead_ad_attribution,
                        )

                        account_id = get_current_ads_account_id(db, tenant_id)
                        creative_row = None
                        attribution_method = None
                        if account_id:
                            creative_row, attribution_method = find_creative_for_message(
                                db,
                                tenant_id=tenant_id,
                                meta_ad_account_id=account_id,
                                referral_ad_id=referral_ad_id or None,
                                body=body,
                            )

                        resolved_ad_id = (
                            referral_ad_id
                            if attribution_method == "meta_ad_id"
                            else (creative_row or {}).get("meta_ad_id")
                        )
                        if account_id and attribution_method and resolved_ad_id:
                            creative_id = (creative_row or {}).get("id")
                            attributed_creative_id_for_message = creative_id
                            is_new_ad_lead = record_lead_ad_attribution(
                                db,
                                tenant_id=tenant_id,
                                lead_id=lead_id,
                                meta_ad_account_id=account_id,
                                meta_ad_id=resolved_ad_id,
                                ad_creative_id=creative_id,
                                attribution_method=attribution_method,
                            )
                            ad_attributed = True

                            lead_updates: dict = {}
                            if creative_row and creative_row.get("campaign_id"):
                                lead_updates["ad_campaign_id"] = creative_row["campaign_id"]
                            elif referral_ad_id:
                                # Keep the existing campaign-level fallback for
                                # a brand-new ad that has not synced yet.
                                from app.services.growth import get_or_create_campaign

                                ads_ctx = (referral or {}).get("ads_context_data", {})
                                ad_title = (
                                    ads_ctx.get("ad_title")
                                    or (referral or {}).get("headline", "")
                                    or referral_ad_id
                                )
                                campaign = get_or_create_campaign(
                                    db=db,
                                    tenant_id=tenant_id,
                                    platform="whatsapp",
                                    campaign_name=ad_title,
                                    external_campaign_id=referral_ad_id,
                                )
                                if campaign:
                                    lead_updates["ad_campaign_id"] = campaign["id"]

                            if creative_id:
                                current = (
                                    db.table("leads")
                                    .select("attributed_ad_creative_id")
                                    .eq("id", lead_id)
                                    .eq("tenant_id", tenant_id)
                                    .limit(1)
                                    .execute()
                                )
                                if current.data and not current.data[0].get("attributed_ad_creative_id"):
                                    lead_updates["attributed_ad_creative_id"] = creative_id

                            if lead_updates:
                                (
                                    db.table("leads")
                                    .update(lead_updates)
                                    .eq("id", lead_id)
                                    .eq("tenant_id", tenant_id)
                                    .execute()
                                )
                            logger.info(
                                "CTWA attribution: lead %s -> ad %s via %s (%s)",
                                lead_id,
                                resolved_ad_id,
                                attribution_method,
                                "new" if is_new_ad_lead else "repeat",
                            )
                    except Exception as ctwa_err:
                        logger.warning(f"CTWA attribution failed for lead {lead_id}: {ctwa_err}")

                    # Google Ads: attribute via a [GADS:...] tag in the pre-filled
                    # click-to-chat message. Google can't inject Meta's referral
                    # object, so the tag in the first inbound message is our signal.
                    # Only runs when Meta CTWA didn't already claim this lead.
                    if body and not ad_attributed:
                        google_ref = parse_google_ref(body)
                        if google_ref:
                            # The message carries a Google ad tag, so flag it
                            # regardless of what happens to the campaign link
                            # below -- that link is skipped on repeat contacts
                            # (it must not clobber an earlier attribution),
                            # which previously left every returning Google
                            # lead unflagged and uncounted.
                            ad_attributed = True
                            try:
                                from app.services.growth import get_or_create_campaign
                                campaign = get_or_create_campaign(
                                    db=db,
                                    tenant_id=tenant_id,
                                    platform="google",
                                    campaign_name=google_ref.campaign,
                                    external_campaign_id=google_ref.external_campaign_id,
                                )
                                if campaign:
                                    # Don't clobber a prior attribution (e.g. repeat
                                    # contact) — only set when currently unattributed.
                                    current = (
                                        db.table("leads").select("ad_campaign_id")
                                        .eq("id", lead_id).eq("tenant_id", tenant_id)
                                        .limit(1).execute()
                                    )
                                    if current.data and not current.data[0].get("ad_campaign_id"):
                                        db.table("leads").update(
                                            {"ad_campaign_id": campaign["id"]}
                                        ).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
                                        logger.info(
                                            f"Google Ads referral: lead {lead_id} linked to "
                                            f"campaign {campaign['id']} (tag={google_ref.campaign}, "
                                            f"gclid={google_ref.gclid})"
                                        )
                            except Exception as gads_err:
                                logger.warning(f"Google Ads attribution failed for lead {lead_id}: {gads_err}")

                    already = db.table("messages").select("id").eq("meta_message_id", msg_id).eq("tenant_id", tenant_id).limit(1).execute()
                    if already.data:
                        continue

                    _is_first = (
                        db.table("messages")
                        .select("id")
                        .eq("lead_id", lead_id)
                        .eq("direction", "inbound")
                        .limit(1)
                        .execute()
                    )
                    is_first_message = not bool(_is_first.data)

                    if body and _is_opt_out(body):
                        # Checked on every inbound turn now, not gated to the first
                        # reply after a broadcast -- see _STOP_WORDS docstring. The
                        # "stop" itself is still worth a compliance record even though
                        # it never reaches route_intake/generate_reply below.
                        try:
                            db.table("messages").insert({
                                "lead_id": lead_id, "direction": "inbound", "channel": "whatsapp",
                                "content": body, "is_ai_generated": False, "meta_message_id": msg_id,
                                "tenant_id": tenant_id,
                            }).execute()
                        except Exception as e:
                            logger.warning(f"Failed to log opt-out message for lead {lead_id}: {e}")
                        # Same as every other inbound insert site: the thread moved
                        # on, so a pending "you've gone quiet" nudge no longer applies.
                        try:
                            from app.services.silence_nudge import cancel_pending
                            if lead_id:
                                cancel_pending(db, lead_id)
                        except Exception:
                            logger.exception("Silence nudge cancel failed for lead %s", lead_id)
                        await _handle_opt_out(phone, tenant_id, db)
                        continue

                    if msg_type != "audio":
                        # A caption becomes the content (text-pipeline-eligible); an
                        # uncaptioned image/document/video/sticker still needs a
                        # readable row in the inbox rather than an empty string.
                        display_content = body or (f"[{msg_type}]" if msg_type in ("image", "video", "document", "sticker") else body)
                        insert_row: dict = {
                            "lead_id": lead_id,
                            "direction": "inbound",
                            "channel": "whatsapp",
                            "content": display_content,
                            "is_ai_generated": False,
                            "meta_message_id": msg_id,
                            "tenant_id": tenant_id,
                            "via_ad_referral": ad_attributed,
                            "attributed_ad_creative_id": attributed_creative_id_for_message,
                        }
                        if media_id:
                            insert_row["media_url"] = f"meta:{media_id}"
                            insert_row["media_type"] = msg_type
                            insert_row["media_mime_type"] = media_mime_type
                        if interactive_id:
                            insert_row["interactive_id"] = interactive_id
                        db.table("messages").insert(insert_row).execute()

                        # The thread has moved on — drop any pending silence
                        # nudge. Optimisation only; _thread_unchanged() at fire
                        # time is the real guard against a nudge landing on top
                        # of a reply.
                        try:
                            from app.services.silence_nudge import cancel_pending
                            if lead_id:
                                cancel_pending(db, lead_id)
                        except Exception:
                            logger.exception("Silence nudge cancel failed for lead %s", lead_id)

                        try:
                            from app.services.notify import notify_assigned_caller_of_reply
                            if lead_id:
                                notify_assigned_caller_of_reply(lead_id, tenant_id, db=db)
                        except Exception:
                            pass

                        # Reset engagement suppression counter on inbound reply
                        if lead_id:
                            try:
                                db.table("leads").update({"outbound_no_reply_count": 0}).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
                            except Exception:
                                pass

                    # Delegate state tracking, compaction, and reply to background task to avoid Meta timeout
                    background_tasks.add_task(
                        _process_inbound_message_background,
                        lead_id=lead_id,
                        tenant_id=tenant_id,
                        phone=phone,
                        body=body,
                        msg_type=msg_type,
                        meta_phone_number_id=meta_phone_number_id,
                        meta_message_id=msg_id,
                        meta_media_id=media_id,
                        interactive_id=interactive_id,
                    )

                # Handle message status updates (delivered, read, failed)
                statuses = value.get("statuses") or []
                if statuses:
                    await asyncio.to_thread(_apply_status_updates, db, tenant_id, statuses)

    return {"status": "ok"}

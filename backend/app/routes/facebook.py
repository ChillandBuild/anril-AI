import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, BackgroundTasks, Response
from app.db.supabase import get_supabase
from app.config_dynamic import get_setting
from app.services.growth import record_stage_event
from app.services.meta_ctwa_attribution import attribute_chat_to_ad, parse_ad_referral
from app.services.ai_reply import generate_reply
from app.services.meta_webhook_verify import (
    verify_meta_signature,
    resolve_tenant_for_page,
    resolve_tenants_from_payload,
    matches_any_tenant_verify_token,
)
from app.services.segmentation import new_lead_score_and_segment

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_or_create_facebook_lead(db, tenant_id: str, sender_id: str, page_id: str) -> str | None:
    """The tenant's lead for this Messenger user, created (and auto-assigned) on first
    contact; a soft-deleted lead is restored. None only if the insert failed."""
    existing = (
        db.table("leads")
        .select("id,score,segment,deleted_at,ai_enabled")
        .eq("fb_user_id", sender_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        lead_id = existing.data[0]["id"]
        if existing.data[0].get("deleted_at"):
            db.table("leads").update({
                "deleted_at": None,
                "ai_enabled": True,
                "needs_human_intervention": False,
            }).eq("id", lead_id).execute()
            logger.info(f"Restored soft-deleted Facebook lead {lead_id}")
        return lead_id

    name = f"Facebook User {sender_id[:6]}"
    initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
    new_lead = db.table("leads").insert({
        "name": name,
        "fb_user_id": sender_id,
        "fb_page_id": page_id,
        "source": "facebook",
        "score": initial_score,
        "segment": initial_segment,
        "tenant_id": tenant_id,
        "opt_in_source": "facebook",
    }).execute()
    if not new_lead.data:
        logger.error(f"Failed to create new Facebook lead for sender {sender_id}")
        return None

    lead_id = new_lead.data[0]["id"]
    record_stage_event(
        lead_id,
        to_segment=initial_segment,
        event_type="created",
        metadata={"source": "facebook"},
        tenant_id=tenant_id,
        db=db,
    )
    try:
        from app.services.assignment import maybe_assign_lead
        maybe_assign_lead(lead_id, tenant_id, initial_segment, "facebook", reason="created")
    except Exception as e:
        logger.warning(f"Auto-assign failed for Facebook lead {lead_id}: {e}")
    return lead_id


@router.get("/{tenant_id}")
async def verify_facebook_webhook(tenant_id: str, request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    verify_token = get_setting("meta_webhook_verify_token", tenant_id=tenant_id)

    if mode == "subscribe" and token == verify_token:
        logger.info(f"Facebook webhook verified successfully for tenant {tenant_id}")
        return Response(content=challenge, media_type="text/plain")

    logger.warning(f"Facebook webhook verification failed for tenant {tenant_id} — token mismatch. received={token}")
    return Response(content="Forbidden", status_code=403)


@router.post("/{tenant_id}")
async def facebook_webhook(tenant_id: str, request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_meta_signature(raw_body, signature, tenant_id):
        # Return 200 for echo messages (our own sent messages bounced back by Meta)
        # so Meta stops retrying them.
        try:
            import json as _json
            _payload = _json.loads(raw_body.decode("utf-8")) if raw_body else {}
            _is_echo = any(
                event.get("message", {}).get("is_echo")
                for entry in _payload.get("entry", [])
                for event in entry.get("messaging", [])
            )
            if _is_echo:
                return {"status": "ok", "detail": "echo_ignored"}
        except Exception:
            pass
        logger.warning(f"Facebook webhook signature invalid for tenant {tenant_id}")
        return Response(content="Forbidden", status_code=403)

    try:
        import json as _json
        payload = _json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        logger.error("Failed to parse Facebook webhook request JSON")
        return {"status": "ok", "detail": "invalid_json"}

    # Meta Messenger payloads have "object": "page"
    if payload.get("object") != "page":
        return {"status": "ok", "detail": "not_page_object"}

    entries = payload.get("entry", [])
    db = get_supabase()

    for entry in entries:
        page_id = entry.get("id", "")
        # Validate that this page_id belongs to the tenant in the URL
        owner_tenant = resolve_tenant_for_page(page_id, "facebook")
        if owner_tenant and owner_tenant != tenant_id:
            logger.warning(
                f"Facebook page_id {page_id} belongs to tenant {owner_tenant}, "
                f"not {tenant_id} (URL) — skipping entry"
            )
            continue
        # Instant form (lead ad) submissions arrive as `changes`, carrying ids
        # only. Unlike messages, they need the Page to be this tenant's own
        # connected Page: the lead is then read with that Page's token.
        for change in entry.get("changes", []) or []:
            if change.get("field") != "leadgen":
                continue
            if owner_tenant != tenant_id:
                logger.warning(f"Facebook leadgen for unregistered page {page_id} on tenant {tenant_id} — skipping")
                continue
            from app.services.meta_lead_forms import process_leadgen_event
            background_tasks.add_task(process_leadgen_event, tenant_id, page_id, change.get("value") or {})
        messaging = entry.get("messaging", [])
        for event in messaging:
            # Ignore echo messages (sent by our page)
            message = event.get("message") or {}
            if message.get("is_echo"):
                continue

            sender_id = event.get("sender", {}).get("id")
            # Meta Ad referral: {source: "ADS", type: "OPEN_THREAD", ad_id, ...}
            # on the message when a Click-to-Messenger ad opens a new chat.
            referral = event.get("referral") or message.get("referral") or {}
            ad_id = parse_ad_referral(referral)

            if not message:
                # Standalone messaging_referrals event: someone with an existing
                # thread came back through an ad. No message to store or reply to,
                # but the ad still gets credit.
                if ad_id and sender_id:
                    lead_id = _get_or_create_facebook_lead(db, tenant_id, sender_id, page_id)
                    if lead_id:
                        attribute_chat_to_ad(
                            db, tenant_id=tenant_id, lead_id=lead_id, referral=referral,
                            channel="messenger", platform="facebook",
                        )
                continue

            message_id = message.get("mid")
            text = (message.get("text") or "").strip()

            # Skip non-text messages (images, stickers, etc.)
            if not sender_id or not text or not message_id:
                continue

            # Step 1: Look up or create lead by fb_user_id
            lead_id = _get_or_create_facebook_lead(db, tenant_id, sender_id, page_id)
            if not lead_id:
                continue

            # Meta Ad attribution (Click-to-Messenger)
            if ad_id:
                attribute_chat_to_ad(
                    db, tenant_id=tenant_id, lead_id=lead_id, referral=referral,
                    channel="messenger", platform="facebook",
                )

            # Step 2: Prevent duplicate message insertion
            already = (
                db.table("messages")
                .select("id")
                .eq("fb_message_id", str(message_id))
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            if already.data:
                continue

            # Step 3: Insert inbound message
            db.table("messages").insert({
                "lead_id": lead_id,
                "direction": "inbound",
                "channel": "facebook",
                "content": text,
                "is_ai_generated": False,
                "fb_message_id": str(message_id),
                "tenant_id": tenant_id,
                # See instagram.py: the flag belongs on the message because
                # the lead-level ad link is not refreshed on repeat contacts.
                "via_ad_referral": bool(ad_id),
            }).execute()

            try:
                from app.services.notify import notify_assigned_caller_of_reply
                if lead_id:
                    notify_assigned_caller_of_reply(lead_id, tenant_id, db=db)
            except Exception:
                pass

            # Step 4: Update conversation activity state
            try:
                from app.services.conversation_state import get_or_create_state
                conv_state = get_or_create_state(lead_id, tenant_id, db)
                new_count = (conv_state.get("message_count") or 0) + 1
                db.table("lead_conversation_state").update({
                    "message_count": new_count,
                    "last_activity_at": datetime.now(timezone.utc).isoformat(),
                }).eq("lead_id", lead_id).execute()
            except Exception as state_err:
                logger.warning(f"Failed to update Facebook lead conversation state: {state_err}")

            # Step 5: Queue AI Auto-Reply
            try:
                from app.services.context_builder import build_scorer_context
                context_block = build_scorer_context(lead_id, db)
                background_tasks.add_task(
                    generate_reply,
                    lead_id=lead_id,
                    message=text,
                    channel="facebook",
                    context_block=context_block,
                    fb_user_id=sender_id,
                )
            except Exception as reply_err:
                logger.error(f"Failed to queue generate_reply for Facebook lead {lead_id}: {reply_err}")

    return {"status": "ok"}


# ── Shared, tenant-agnostic endpoint ────────────────────────────────────────
# Meta allows exactly one callback URL per app per webhook object, so the
# /{tenant_id} routes above can only ever serve a single tenant per Meta app.
# These routes take no tenant and derive it from entry[].id instead — the same
# approach /webhook/whatsapp has always used. The per-tenant routes stay for the
# URLs already configured in Meta.

@router.get("")
async def verify_facebook_webhook_shared(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and matches_any_tenant_verify_token(token):
        logger.info("Facebook webhook verified on the shared endpoint")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("Facebook shared webhook verification failed — token matched no tenant")
    return Response(content="Forbidden", status_code=403)


@router.post("")
async def facebook_webhook_shared(request: Request, background_tasks: BackgroundTasks):
    """Route each entry to its owning tenant, then reuse the per-tenant handler.

    The signature is checked inside that handler, against the resolved tenant's
    secret — resolving from an unverified body only picks which secret to verify
    against, it never grants trust. Entries owned by another tenant are skipped by
    the handler's own ownership check, so calling it once per distinct tenant
    processes every entry exactly once.
    """
    raw_body = await request.body()
    try:
        import json as _json
        payload = _json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        logger.error("Failed to parse Facebook shared webhook request JSON")
        return {"status": "ok", "detail": "invalid_json"}

    tenants = resolve_tenants_from_payload(payload, "facebook")
    if not tenants:
        entry_ids = [e.get("id") for e in payload.get("entry", []) or []]
        logger.warning(
            f"Facebook shared webhook: no tenant owns entries {entry_ids} — "
            f"is facebook_page_id set for this Page?"
        )
        return {"status": "ok", "detail": "no_tenant_for_entries"}

    for tenant_id in tenants:
        await facebook_webhook(tenant_id, request, background_tasks)
    return {"status": "ok", "tenants": len(tenants)}

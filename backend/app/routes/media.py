import logging
import mimetypes
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from app.db.supabase import get_supabase
from app.services.actor import sender_fields
from app.services.outbound_router import reply_number_for
from app.dependencies.tenant import require_permission
from app.services.meta_cloud import (
    download_media_from_meta,
    upload_media_to_meta,
    send_media_message,
    get_wa_type_for_mime,
)

logger = logging.getLogger(__name__)
router = APIRouter()
require_conversations_reply = require_permission("conversations.reply")
require_conversations_view = require_permission("conversations.view")

# Max file sizes in bytes
_MAX_IMAGE_BYTES = 5 * 1024 * 1024       # 5 MB
_MAX_AUDIO_BYTES = 16 * 1024 * 1024      # 16 MB
_MAX_VIDEO_BYTES = 16 * 1024 * 1024      # 16 MB
_MAX_DOCUMENT_BYTES = 100 * 1024 * 1024  # 100 MB

_TYPE_LIMITS = {
    "image": _MAX_IMAGE_BYTES,
    "audio": _MAX_AUDIO_BYTES,
    "video": _MAX_VIDEO_BYTES,
    "document": _MAX_DOCUMENT_BYTES,
}

_ALLOWED_MIME_TYPES = {
    # Images
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    # Documents
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/csv",
    # Audio
    "audio/ogg", "audio/mpeg", "audio/mp3", "audio/aac",
    "audio/amr", "audio/wav", "audio/webm",
    # Video
    "video/mp4", "video/3gpp",
}


@router.post("/{lead_id}/send-media")
async def send_media_to_lead(
    lead_id: UUID,
    file: UploadFile = File(...),
    caption: str = Form(""),
    ctx: dict = Depends(require_conversations_reply),
):
    """
    Upload a file and send it as a WhatsApp media message to a lead.
    Supports: images (JPG, PNG, WEBP), documents (PDF, DOCX, XLSX, PPTX, CSV, TXT),
              audio (MP3, OGG, AAC, WAV, AMR), video (MP4).
    """
    tenant_id = ctx["tenant_id"]
    db = get_supabase()

    # --- Fetch lead ---
    lead = (
        db.table("leads")
        .select("phone,source,last_inbound_phone_number_id")
        .eq("id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not lead or not lead.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.data.get("source") == "instagram":
        raise HTTPException(status_code=400, detail="Media sending is only supported for WhatsApp leads")

    phone = lead.data.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Lead has no phone number")

    # --- Validate file ---
    filename = file.filename or "upload"
    mime_type = file.content_type or ""
    if not mime_type:
        guessed, _ = mimetypes.guess_type(filename)
        mime_type = guessed or "application/octet-stream"

    # Normalise mime type (strip charset etc.)
    mime_type = mime_type.lower().split(";")[0].strip()

    if mime_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{mime_type}'. Allowed: images (PNG/JPG/WEBP), "
                   "documents (PDF/DOCX/XLSX/PPTX/CSV/TXT), audio (MP3/OGG/WAV/AAC), video (MP4).",
        )

    wa_type = get_wa_type_for_mime(mime_type)

    # Read file bytes
    file_bytes = await file.read()
    file_size = len(file_bytes)
    size_limit = _TYPE_LIMITS.get(wa_type, _MAX_DOCUMENT_BYTES)
    if file_size > size_limit:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {round(file_size / 1024 / 1024, 1)} MB. "
                   f"Limit for {wa_type} is {round(size_limit / 1024 / 1024)} MB.",
        )
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # This business's own credentials, from the number the customer wrote to (else the primary).
    # The upload goes to the same number that sends it.
    from_number = reply_number_for(db, tenant_id, lead.data.get("last_inbound_phone_number_id"))

    # --- Upload to Meta ---
    try:
        media_id = await upload_media_to_meta(
            file_bytes=file_bytes,
            mime_type=mime_type,
            filename=filename,
            phone_number_id=from_number,
            tenant_id=tenant_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Media upload to Meta failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Media upload failed: {e}")

    # --- Send via WhatsApp ---
    try:
        result = await send_media_message(
            to_number=phone,
            media_id=media_id,
            wa_type=wa_type,
            filename=filename if wa_type == "document" else None,
            caption=caption.strip() if caption else None,
            phone_number_id=from_number,
            tenant_id=tenant_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Media send failed: %s", e)
        raise HTTPException(status_code=502, detail=f"WhatsApp send failed: {e}")

    meta_msg_id = (result.get("messages") or [{}])[0].get("id")

    # --- Store in DB ---
    content_text = caption.strip() if caption else f"[{wa_type}: {filename}]"
    row = db.table("messages").insert({
        "lead_id": str(lead_id),
        "tenant_id": tenant_id,
        "direction": "outbound",
        "channel": "whatsapp",
        "content": content_text,
        "is_ai_generated": False,
        "meta_message_id": meta_msg_id,
        "media_url": f"meta:{media_id}",   # Reference to Meta-hosted media
        "media_type": wa_type,
        "media_filename": filename,
        "media_mime_type": mime_type,
        **sender_fields(db, ctx),
    }).execute()

    return row.data[0] if row.data else {"sent": True, "media_id": media_id, "wa_type": wa_type}


@router.get("/{lead_id}/messages/{message_id}/audio")
async def voice_note_audio(lead_id: UUID, message_id: UUID, ctx: dict = Depends(require_conversations_view)):
    """Play a WhatsApp voice note in the chat. The file stays on WhatsApp (media_url "meta:<id>"),
    so it is fetched from Meta on each play; WhatsApp keeps it about 30 days, after that 410."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    lead = (db.table("leads").select("id,assigned_to").eq("id", str(lead_id)).eq("tenant_id", tenant_id)
            .is_("deleted_at", "null").limit(1).execute()).data or []
    if not lead or (ctx.get("role") == "caller" and ctx.get("caller_id") and lead[0].get("assigned_to") != ctx["caller_id"]):
        raise HTTPException(status_code=404, detail="Voice note not found")
    rows = (db.table("messages").select("media_url,media_type").eq("id", str(message_id)).eq("lead_id", str(lead_id))
            .eq("tenant_id", tenant_id).limit(1).execute()).data or []
    media_url = (rows[0].get("media_url") or "") if rows else ""
    if not rows or rows[0].get("media_type") != "audio" or not media_url.startswith("meta:"):
        raise HTTPException(status_code=404, detail="Voice note not found")
    try:
        data, mime, _ = await download_media_from_meta(media_url[5:], tenant_id=tenant_id)
    except HTTPException:
        raise HTTPException(status_code=410, detail="WhatsApp no longer has this voice note. It keeps them for about 30 days.")
    except Exception:
        logger.exception("Voice note download failed for message %s", message_id)
        raise HTTPException(status_code=502, detail="Couldn't get the voice note from WhatsApp. Try again.")
    return Response(content=data, media_type=mime or "audio/ogg", headers={"Cache-Control": "private, max-age=3600"})

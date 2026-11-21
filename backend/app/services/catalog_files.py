"""Shop files the AI sends in chat (plan: docs/plans/commerce-stock-plan.md, part 2; migration 306).

Price list PDFs, size charts, shop map photos, short videos. Each has the business's own
"send it when" words; the AI gets a send_file tool listing them and the file goes out right after
its reply (like item photos). Item photos stay in catalog_media."""
from __future__ import annotations

import logging
import re
import uuid

logger = logging.getLogger(__name__)

BUCKET = "catalog-media"
TOOL_SEND_FILE = "send_file"
MAX_PER_REPLY = 2
# What WhatsApp accepts (Meta Cloud API media limits); documents are capped lower by our storage.
KINDS = {
    "image": {"mimes": {"image/jpeg", "image/png"}, "max_bytes": 5 * 1024 * 1024, "label": "Photo"},
    "video": {"mimes": {"video/mp4", "video/3gpp"}, "max_bytes": 16 * 1024 * 1024, "label": "Video"},
    "document": {"mimes": {"application/pdf"}, "max_bytes": 50 * 1024 * 1024, "label": "PDF"},
}


class FileError(ValueError):
    """Something the user can fix; routes turn it into a 400."""


def sniff(content: bytes) -> tuple[str, str] | None:
    """(kind, mime) from the file's first bytes -- never trust the name or the browser's type."""
    head = content[:16]
    if head.startswith(b"%PDF-"):
        return "document", "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand.startswith(b"3g"):
            return "video", "video/3gpp"
        if brand in (b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash"):
            return "video", "video/mp4"
        return None  # HEIC / AVIF / MOV: not something WhatsApp plays as mp4
    return None


def pdf_pages(content: bytes) -> int | None:
    count = len(re.findall(rb"/Type\s*/Page[^s]", content))
    return count or None


def check_upload(content: bytes) -> tuple[str, str]:
    found = sniff(content)
    if not found:
        raise FileError("Add a PDF, a JPG or PNG photo, or an MP4 video.")
    kind, mime = found
    limit = KINDS[kind]["max_bytes"]
    if len(content) > limit:
        raise FileError(f"WhatsApp sends a {KINDS[kind]['label'].lower()} up to {limit // (1024 * 1024)} MB. "
                        "Make it smaller and add it again.")
    return kind, mime


def clean_title(title: str | None, filename: str | None) -> str:
    text = " ".join(str(title or "").split())[:80]
    if not text:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", str(filename or ""))
        text = " ".join(re.sub(r"[_\-]+", " ", stem).split())[:80]
    return text or "File"


def clean_send_when(text) -> str | None:
    text = " ".join(str(text or "").split())[:200]
    return text or None


def upload(db, tenant_id: str, content: bytes, *, filename: str | None, title: str | None,
           send_when: str | None, item_id: str | None, user_id: str | None) -> dict:
    kind, mime = check_upload(content)
    if item_id:
        found = db.table("catalog_items").select("id").eq("id", item_id).eq("tenant_id", tenant_id).limit(1).execute().data
        if not found:
            raise FileError("Product not found")
    ext = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "video/mp4": "mp4", "video/3gpp": "3gp"}[mime]
    path = f"{tenant_id}/files/{uuid.uuid4().hex}.{ext}"
    db.storage.from_(BUCKET).upload(path, content, {"content-type": mime})
    row = db.table("catalog_files").insert({
        "tenant_id": tenant_id, "catalog_item_id": item_id, "title": clean_title(title, filename), "kind": kind,
        "mime_type": mime, "size_bytes": len(content), "storage_path": path,
        "pages": pdf_pages(content) if kind == "document" else None,
        "send_when": clean_send_when(send_when), "created_by": user_id,
    }).execute().data
    return view(db, (row or [{}])[0])


def view(db, row: dict) -> dict:
    return {**row, "url": db.storage.from_(BUCKET).get_public_url(row["storage_path"]) if row.get("storage_path") else None}


def summary(db, tenant_id: str, *, month_start_iso: str) -> dict:
    files = (
        db.table("catalog_files").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True).limit(500).execute()
    ).data or []
    sends = (
        db.table("catalog_file_sends").select("file_id").eq("tenant_id", tenant_id).gte("sent_at", month_start_iso)
        .limit(20000).execute()
    ).data or []
    month: dict[str, int] = {}
    for s in sends:
        month[s["file_id"]] = month.get(s["file_id"], 0) + 1
    items = (
        db.table("catalog_items").select("id, name").eq("tenant_id", tenant_id).eq("item_type", "product")
        .limit(5000).execute()
    ).data or []
    with_photo = {m["catalog_item_id"] for m in (
        db.table("catalog_media").select("catalog_item_id").eq("tenant_id", tenant_id).limit(20000).execute()
    ).data or []}
    names = {i["id"]: i["name"] for i in items}
    no_photo = [i for i in items if i["id"] not in with_photo]
    out = [{**view(db, f), "item_name": names.get(f.get("catalog_item_id")), "sent_this_month": month.get(f["id"], 0)}
           for f in files]
    top = sorted((f for f in out if f["sent_this_month"]), key=lambda f: -f["sent_this_month"])[:3]
    return {
        "files": out,
        "no_photo": {"count": len(no_photo), "items": [{"id": i["id"], "name": i["name"]} for i in no_photo[:20]]},
        "most_sent": [{"id": f["id"], "title": f["title"], "count": f["sent_this_month"]} for f in top],
        "limits": {k: v["max_bytes"] for k, v in KINDS.items()},
    }


def update(db, tenant_id: str, file_id: str, payload: dict) -> dict:
    patch: dict = {}
    if "title" in payload:
        title = " ".join(str(payload.get("title") or "").split())[:80]
        if not title:
            raise FileError("Give the file a name.")
        patch["title"] = title
    if "send_when" in payload:
        patch["send_when"] = clean_send_when(payload.get("send_when"))
    if "ai_enabled" in payload:
        patch["ai_enabled"] = bool(payload.get("ai_enabled"))
    if "catalog_item_id" in payload:
        item_id = payload.get("catalog_item_id") or None
        if item_id:
            found = db.table("catalog_items").select("id").eq("id", item_id).eq("tenant_id", tenant_id).limit(1).execute().data
            if not found:
                raise FileError("Product not found")
        patch["catalog_item_id"] = item_id
    if not patch:
        raise FileError("Nothing to change.")
    rows = db.table("catalog_files").update(patch).eq("id", file_id).eq("tenant_id", tenant_id).execute().data
    if not rows:
        raise FileError("File not found")
    return view(db, rows[0])


def delete(db, tenant_id: str, file_id: str) -> None:
    rows = db.table("catalog_files").select("storage_path").eq("id", file_id).eq("tenant_id", tenant_id).limit(1).execute().data
    if not rows:
        raise FileError("File not found")
    db.table("catalog_files").delete().eq("id", file_id).eq("tenant_id", tenant_id).execute()
    try:
        db.storage.from_(BUCKET).remove([rows[0]["storage_path"]])
    except Exception:
        logger.warning("Couldn't remove stored file %s", rows[0]["storage_path"])


# ── the AI ────────────────────────────────────────────────────────────────────


def ai_files(db, tenant_id: str) -> list[dict]:
    """Files the AI may send: switched on, with the business's 'send it when' words."""
    rows = (
        db.table("catalog_files").select("id, title, kind, send_when").eq("tenant_id", tenant_id)
        .eq("ai_enabled", True).limit(50).execute()
    ).data or []
    return [r for r in rows if (r.get("send_when") or "").strip()]


def ai_tool(files: list[dict]) -> dict | None:
    if not files:
        return None
    lines = "\n".join(f"- {f['id']}: {KINDS[f['kind']]['label']} \"{f['title']}\" -- send when: {f['send_when']}"
                      for f in files)
    return {
        "type": "function",
        "function": {
            "name": TOOL_SEND_FILE,
            "description": (
                "Send the customer one of the business's files (it arrives right after your reply). Call it only "
                f"when the conversation matches that file's 'send when' words, at most {MAX_PER_REPLY} files per reply, "
                "and not again if you already sent it in this chat today. Mention it in one short line, in the "
                f"customer's language.\nFiles:\n{lines}"
            ),
            "parameters": {
                "type": "object",
                "properties": {"file_id": {"type": "string", "enum": [f["id"] for f in files]}},
                "required": ["file_id"],
            },
        },
    }


async def send_after_reply(db, tenant_id: str, lead_id: str, phone: str, file_ids, *,
                           channel: str = "whatsapp", phone_number_id: str | None = None) -> int:
    """Send the files the AI picked, after its words. A failed file costs that file, never the reply.
    Only called from generate_reply, after its Auto-Reply check."""
    from app.services.meta_cloud import send_media_message

    ids = list(dict.fromkeys(file_ids or []))[:MAX_PER_REPLY]
    if not ids:
        return 0
    rows = {r["id"]: r for r in (
        db.table("catalog_files").select("*").eq("tenant_id", tenant_id).in_("id", ids).execute()
    ).data or []}
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = {r["file_id"] for r in (
        db.table("catalog_file_sends").select("file_id").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
        .in_("file_id", ids).gte("sent_at", since).execute()
    ).data or []}
    sent = 0
    for file_id in ids:
        row = rows.get(file_id)
        # Only what the business lets the AI send, and never the same file twice a day to one customer.
        if not row or not row.get("ai_enabled") or not (row.get("send_when") or "").strip() or file_id in recent:
            continue
        url = db.storage.from_(BUCKET).get_public_url(row["storage_path"])
        try:
            resp = await send_media_message(
                to_number=phone, wa_type=row["kind"], media_link=url, caption=row["title"],
                filename=f"{row['title']}.pdf" if row["kind"] == "document" else None,
                tenant_id=tenant_id, phone_number_id=phone_number_id,
            )
            sid = ((resp or {}).get("messages") or [{}])[0].get("id")
            db.table("messages").insert({
                "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound", "channel": channel,
                "content": f"[{KINDS[row['kind']]['label']}: {row['title']}]", "is_ai_generated": True,
                "reply_source": "ai", "meta_message_id": sid, "media_type": row["kind"],
                "media_mime_type": row["mime_type"], "media_url": url,
                **({"media_filename": f"{row['title']}.pdf"} if row["kind"] == "document" else {}),
            }).execute()
            db.rpc("record_catalog_file_send", {"p_tenant_id": tenant_id, "p_file_id": file_id,
                                                "p_lead_id": lead_id}).execute()
            sent += 1
        except Exception as exc:
            logger.warning("Shop file %s to lead %s failed: %s", file_id, lead_id, exc)
    return sent

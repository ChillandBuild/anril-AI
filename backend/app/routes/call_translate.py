"""English transcript on demand for a call review (v9.2 Batch C).

POST /api/v1/call-translate/{call_log_id}

Same permission as opening Call review (team.manage; the owner always passes). A Team leader can only
translate calls made by their own team. The translation is made once, stored on the call
(call_logs.transcript_en) and reused. English calls are returned as they are, without calling the model.

The full transcript never leaves the backend (services/call_transcript.py): the browser gets only the
first and last line, with the middle hidden. The English answer follows the same rule, so
"transcript_en" holds the visible lines only, and "transcript_preview_en" is the same shape as the
transcript_preview the call card already shows.
"""
import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services.call_team_scope import scoped_caller_ids
from app.services.call_translation import TranscriptTooLong, TranslationFailed, looks_english, translate_transcript
from app.services.call_transcript import transcript_preview

logger = logging.getLogger(__name__)
router = APIRouter()

# Opening Call review needs team.manage; reading its transcript in English needs the same.
require_reviewer = require_permission("team.manage")

_locks: dict[str, asyncio.Lock] = {}


def _answer(transcript_en: str, *, cached: bool, already_english: bool) -> dict:
    preview = transcript_preview(transcript_en)
    visible = [x for x in ((preview or {}).get("first"), (preview or {}).get("last")) if x]
    return {
        "transcript_en": "\n".join(visible),
        "transcript_preview_en": preview,
        "cached": cached,
        "already_english": already_english,
    }


def _read_call(db, tenant_id: str, call_log_id: str) -> dict | None:
    """The call's id, caller, transcript and any saved English. Falls back to a read without the
    English columns when migration 307 is not applied (then nothing can be saved)."""
    try:
        res = (
            db.table("call_logs").select("id,caller_id,transcript,transcript_en")
            .eq("id", call_log_id).eq("tenant_id", tenant_id).maybe_single().execute()
        )
    except Exception as e:
        logger.warning("call translate: reading transcript_en failed (%s); trying without it", e)
        res = (
            db.table("call_logs").select("id,caller_id,transcript")
            .eq("id", call_log_id).eq("tenant_id", tenant_id).maybe_single().execute()
        )
    return (res.data or None) if res else None


@router.post("/{call_log_id}")
async def translate_call(call_log_id: UUID, ctx: dict = Depends(require_reviewer)):
    tenant_id = ctx["tenant_id"]
    key = str(call_log_id)
    db = get_supabase()

    row = _read_call(db, tenant_id, key)
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    scoped = scoped_caller_ids(db, ctx)
    if scoped is not None and (not row.get("caller_id") or str(row["caller_id"]) not in scoped):
        raise HTTPException(status_code=404, detail="Call not found")  # not their team: same answer as "no such call"

    if row.get("transcript_en"):
        return _answer(row["transcript_en"], cached=True, already_english=False)
    transcript = (row.get("transcript") or "").strip()
    if not transcript:
        raise HTTPException(status_code=404, detail="This call has no transcript yet.")
    if looks_english(transcript):
        return _answer(transcript, cached=False, already_english=True)

    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            # A second click while the first is translating waits here, then reads what the first saved.
            again = _read_call(db, tenant_id, key) or {}
            if again.get("transcript_en"):
                return _answer(again["transcript_en"], cached=True, already_english=False)
            try:
                english = await translate_transcript(transcript, tenant_id)
            except TranscriptTooLong:
                raise HTTPException(status_code=413, detail="This call is too long to translate.")
            except TranslationFailed:
                raise HTTPException(status_code=502, detail="Couldn't translate this call right now. Try again in a minute.")
            except RuntimeError:
                raise HTTPException(status_code=503, detail="English translation isn't set up for this account yet.")
            try:
                db.table("call_logs").update(
                    {"transcript_en": english, "transcript_en_at": datetime.now(timezone.utc).isoformat()}
                ).eq("id", key).eq("tenant_id", tenant_id).execute()
            except Exception as e:  # migration 307 not applied: still show it, just can't keep it
                logger.warning("call translate: could not save the English transcript (%s)", e)
            return _answer(english, cached=False, already_english=False)
    finally:
        if not lock.locked():
            _locks.pop(key, None)

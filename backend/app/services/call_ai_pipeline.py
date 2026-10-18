"""Recording -> transcript -> summary + evaluation -> score, surviving restarts.

Each recorded call carries its own progress in call_logs.ai_status
(pending -> transcribing -> scoring -> done | failed). The webhook starts the work
straight away as a background task; a scheduler sweep picks up anything a restart
or deploy interrupted, and retries failures up to MAX_ATTEMPTS before showing
"failed" with a manual retry. A conditional update on ai_attempts claims each run,
so the webhook task and the sweep can't both process the same call.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.services.audio_format import detect_audio_format, detect_gemini_audio_mime
from app.services.call_alerts import raise_alert
from app.services.call_lines import format_transcript
from app.services.call_marking import mark_call, mark_crm_update, top_improve
from app.services.call_metrics import dead_air, longest_monologue
from app.services.call_metrics import talk_share as compute_talk_share
from app.services.call_scorer import finalize_call_score
from app.services.call_sorting import sort_call
from app.services.call_tracks import count_interruptions, per_5_min
from app.services.call_transcribe import transcribe_tracks, tracks_look_swapped
from app.services.scoring_rules import MIN_SCORED_SECONDS, RULES_VERSION, WRAPUP_CUTOFF_HOURS

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
RETRY_AFTER = timedelta(minutes=2)
STUCK_AFTER = timedelta(minutes=15)
SWEEP_BATCH = 20
ACTIVE_STATUSES = ("pending", "transcribing", "scoring")

# Max concurrent call-AI runs, so a whole shift hanging up together doesn't trip the
# provider's rate limit. Extra calls wait their turn.
_CALL_AI_SEMAPHORE = asyncio.Semaphore(5)

_MIN_AUDIO_BYTES = 1024
_DOWNLOAD_DELAYS = (10, 20, 30)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_audio_payload(resp: httpx.Response, body: bytes) -> bool:
    """True when a /v2/play response body is plausibly an audio file.

    TeleCMI returns HTTP 200 with a JSON error body on auth/lookup failure, so the
    response has to be inspected rather than trusted.
    """
    content_type = (resp.headers.get("content-type") or "").lower()
    if "json" in content_type or "html" in content_type or "text/" in content_type:
        return False
    if body.lstrip()[:1] in (b"{", b"["):
        return False
    return len(body) >= _MIN_AUDIO_BYTES


def queue_call_ai(db, call_log_id: str, recording_filename: str) -> None:
    db.table("call_logs").update({
        "recording_filename": recording_filename,
        "ai_status": "pending",
        "ai_attempts": 0,
        "ai_error": None,
        "ai_updated_at": _now(),
    }).eq("id", call_log_id).execute()


def retry_call_ai(db, call_log_id: str, tenant_id: str) -> bool:
    res = (
        db.table("call_logs")
        .update({"ai_status": "pending", "ai_attempts": 0, "ai_error": None, "ai_updated_at": _now()})
        .eq("id", call_log_id)
        .eq("tenant_id", tenant_id)
        .eq("ai_status", "failed")
        .execute()
    )
    return bool(res.data)


def _set_stage(db, call_log_id: str, stage: str) -> None:
    db.table("call_logs").update({"ai_status": stage, "ai_updated_at": _now()}).eq("id", call_log_id).execute()


async def _download_from_telecmi(row: dict, appid_override: str | None) -> bytes:
    from app.services.telecmi_client import build_recording_url

    tenant_id = row.get("tenant_id")
    appid = appid_override or get_setting("telecmi_app_id", tenant_id=tenant_id)
    secret = get_setting("telecmi_secret", tenant_id=tenant_id)
    if not appid or not secret:
        raise RuntimeError("TeleCMI app id/secret not configured, cannot download the recording")
    url = build_recording_url(
        appid=str(appid),
        secret=secret,
        filename=row["recording_filename"],
        base_url=get_setting("telecmi_recording_base_url", tenant_id=tenant_id),
    )
    for attempt, delay in enumerate(_DOWNLOAD_DELAYS, start=1):
        await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(url)
            if resp.status_code == 404:
                logger.info(f"Recording not ready yet (attempt {attempt}) for call {row['id']}")
                continue
            resp.raise_for_status()
            if not is_audio_payload(resp, resp.content):
                logger.warning(
                    f"Recording download returned non-audio (attempt {attempt}) for call {row['id']}: "
                    f"content_type={resp.headers.get('content-type')!r} body={resp.content[:200]!r}"
                )
                continue
            return resp.content
        except httpx.HTTPError as e:
            logger.warning(f"Recording download attempt {attempt} failed for call {row['id']}: {type(e).__name__}")
    raise RuntimeError("recording could not be downloaded from TeleCMI")


async def _load_audio(db, row: dict, appid_override: str | None) -> tuple[bytes, str]:
    """The call's audio and its Gemini mime type; downloads + stores it on first run."""
    if row.get("recording_url"):
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(row["recording_url"])
            resp.raise_for_status()
        audio = resp.content
        return audio, detect_gemini_audio_mime(audio, row["recording_url"])

    if not row.get("recording_filename"):
        raise RuntimeError("no recording is attached to this call")
    audio = await _download_from_telecmi(row, appid_override)
    extension, content_type = detect_audio_format(audio, row["recording_filename"])
    storage_path = f"{row['id']}.{extension}"
    db.storage.from_("call-recordings").upload(storage_path, audio, {"content-type": content_type, "upsert": "true"})
    public_url = db.storage.from_("call-recordings").get_public_url(storage_path)
    db.table("call_logs").update({"recording_url": public_url}).eq("id", row["id"]).execute()
    logger.info(f"Recording saved for {row['id']}")
    return audio, detect_gemini_audio_mime(audio, row["recording_filename"])


def _claim(db, call_log_id: str) -> dict | None:
    res = (
        db.table("call_logs")
        .select("id,tenant_id,caller_id,lead_id,status,duration_seconds,recording_url,recording_filename,ai_status,ai_attempts")
        .eq("id", call_log_id)
        .maybe_single()
        .execute()
    )
    row = res.data if res else None
    if not row or row.get("ai_status") not in ACTIVE_STATUSES:
        return None
    attempts = row.get("ai_attempts") or 0
    if attempts >= MAX_ATTEMPTS:
        return None
    claimed = (
        db.table("call_logs")
        .update({"ai_status": "transcribing", "ai_attempts": attempts + 1, "ai_updated_at": _now()})
        .eq("id", call_log_id)
        .eq("ai_attempts", attempts)
        .in_("ai_status", list(ACTIVE_STATUSES))
        .execute()
    )
    if not claimed.data:
        return None
    row["ai_attempts"] = attempts + 1
    return row


def _company_name(db, tenant_id: str | None) -> str | None:
    if not tenant_id:
        return None
    res = db.table("tenants").select("name").eq("id", tenant_id).maybe_single().execute()
    name = ((res.data if res else None) or {}).get("name")
    return name if isinstance(name, str) else None


def _previous_notes(db, lead_id: str | None, call_log_id: str) -> str:
    if not lead_id:
        return ""
    rows = (
        db.table("lead_notes").select("content,created_at").eq("lead_id", lead_id)
        .neq("call_log_id", call_log_id).order("created_at", desc=True).limit(5).execute()
    ).data or []
    return "\n".join(f"- {r['content']}" for r in rows if r.get("content"))


def _speech_report(tracks) -> dict:
    """Speech bars and talk numbers for the manager's player (stereo only: they come from the two tracks)."""
    tele, cust = tracks.telecaller_segments, tracks.customer_segments
    return {
        "talk": {"longest_monologue_s": longest_monologue(tele), "dead_air_s": dead_air(tele, cust)},
        "segments": {
            "telecaller": [[round(s, 1), round(e, 1)] for s, e in tele],
            "customer": [[round(s, 1), round(e, 1)] for s, e in cust],
        },
    }


async def _process(db, row: dict, appid_override: str | None) -> None:
    from app.services.knowledge_service import get_knowledge_context

    call_log_id = row["id"]
    tenant_id = row.get("tenant_id")
    duration = row.get("duration_seconds") or 0
    if duration < MIN_SCORED_SECONDS:
        # Very short calls get no AI at all — not even a transcript.
        db.table("call_logs").update({"ai_status": "done", "ai_error": None, "ai_updated_at": _now()}).eq("id", call_log_id).execute()
        return

    audio, mime_type = await _load_audio(db, row, appid_override)
    tracks = await transcribe_tracks(audio, mime_type, tenant_id=tenant_id)
    if not tracks.lines:
        raise RuntimeError("the transcript came back empty")
    transcript = format_transcript(tracks.lines)
    share = compute_talk_share(tracks.lines)
    count = count_interruptions(tracks.telecaller_segments, tracks.customer_segments) if tracks.stereo else None
    ipm = per_5_min(count, duration)
    db.table("call_logs").update({
        "transcript": transcript, "talk_share": share,
        "interruption_count": count, "interruptions_per_5min": ipm,
    }).eq("id", call_log_id).execute()

    _set_stage(db, call_log_id, "scoring")
    caller_id = row.get("caller_id")
    if tracks.stereo and tracks_look_swapped(tracks.lines, _company_name(db, tenant_id)):
        raise_alert(db, tenant_id=tenant_id, type="tracks_swapped", call_log_id=call_log_id, caller_id=caller_id,
                    quote="The 'calling from…' words were heard on the customer's track.")

    kb_context = await get_knowledge_context(tenant_id, query=transcript[:1500]) if tenant_id else ""
    sorting = await sort_call(tracks.lines, tenant_id=tenant_id, kb_context=kb_context)
    evaluation: dict = {
        "evaluation_version": 4, "rules_version": RULES_VERSION, "group": sorting.group,
        "signs": sorting.signs, "valid_sign_count": len(sorting.signs),
        "language_barrier": sorting.language_barrier,
    }
    rude_quote = sorting.rude_quote
    report = _speech_report(tracks) if tracks.stereo else {}
    if sorting.group == "real_conversation":
        marking = await mark_call(
            tracks.lines, kb_context=kb_context, previous_notes=_previous_notes(db, row.get("lead_id"), call_log_id),
            talk_share=share, interruptions_per_5min=ipm, interruption_count=count,
            duration_seconds=duration, tenant_id=tenant_id,
        )
        evaluation.update({
            "checks": marking.checks, "top_improve": top_improve(marking.checks), "tips": marking.tips,
            "wrong_info": marking.wrong_info, "unverified_claims": marking.unverified_claims,
        })
        report = {**marking.report, **report}
        rude_quote = rude_quote or marking.rude_quote
        for item in marking.wrong_info:
            raise_alert(db, tenant_id=tenant_id, type="wrong_info", call_log_id=call_log_id, caller_id=caller_id,
                        quote=f"[{item['time']}] {item['quote']}", detail={"kb_fact": item.get("kb_fact")})
        if marking.proof_missing:
            raise_alert(db, tenant_id=tenant_id, type="no_proof", call_log_id=call_log_id, caller_id=caller_id,
                        quote=f"No proof for: {', '.join(marking.proof_missing)}", detail={"checks": marking.proof_missing})
    else:
        evaluation["early_exit_check"] = sorting.early_exit_check
    if report:
        evaluation["report"] = report
    if rude_quote:
        raise_alert(db, tenant_id=tenant_id, type="rude", call_log_id=call_log_id, caller_id=caller_id, quote=rude_quote)
    if sorting.language_barrier:
        raise_alert(db, tenant_id=tenant_id, type="language_barrier", call_log_id=call_log_id, caller_id=caller_id,
                    quote=sorting.language_barrier_quote)

    db.table("call_logs").update({
        "ai_summary": sorting.summary, "evaluation": evaluation, "ai_status": "done",
        "ai_error": None, "ai_updated_at": _now(),
    }).eq("id", call_log_id).execute()
    logger.info(f"Call {call_log_id} sorted as {sorting.group} ({len(sorting.signs)} signs)")


async def run_call_ai(call_log_id: str, appid_override: str | None = None) -> None:
    async with _CALL_AI_SEMAPHORE:
        db = get_supabase()
        row = _claim(db, call_log_id)
        if not row:
            return
        try:
            await _process(db, row, appid_override)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:500]
            final = row["ai_attempts"] >= MAX_ATTEMPTS
            logger.error(f"Call AI attempt {row['ai_attempts']}/{MAX_ATTEMPTS} failed for {call_log_id}: {error}")
            db.table("call_logs").update({
                "ai_status": "failed" if final else "pending",
                "ai_error": error,
                "ai_updated_at": _now(),
            }).eq("id", call_log_id).execute()
            if final:
                try:
                    raise_alert(db, tenant_id=row.get("tenant_id"), type="transcript_failed", call_log_id=call_log_id,
                                caller_id=row.get("caller_id"), quote=error[:240])
                except Exception as alert_err:
                    logger.error(f"transcript_failed alert failed for call {call_log_id}: {alert_err}")
        try:
            finalize_call_score(db, call_log_id)
        except Exception as e:
            logger.error(f"Scoring failed for call {call_log_id}: {e}")
        try:
            await mark_crm_update(db, call_log_id)
        except Exception as e:
            logger.error(f"CRM check failed for call {call_log_id}: {e}")


async def sweep_call_ai() -> int:
    """Resume calls a restart interrupted and retry earlier failures. Returns how many ran."""
    db = get_supabase()
    now = datetime.now(timezone.utc)
    due_pending = (
        db.table("call_logs")
        .select("id,ai_attempts,tenant_id,caller_id")
        .eq("ai_status", "pending")
        .lt("ai_updated_at", (now - RETRY_AFTER).isoformat())
        .order("ai_updated_at")
        .limit(SWEEP_BATCH)
        .execute()
    ).data or []
    stuck = (
        db.table("call_logs")
        .select("id,ai_attempts,tenant_id,caller_id")
        .in_("ai_status", ["transcribing", "scoring"])
        .lt("ai_updated_at", (now - STUCK_AFTER).isoformat())
        .order("ai_updated_at")
        .limit(SWEEP_BATCH)
        .execute()
    ).data or []

    runnable = []
    for row in due_pending + stuck:
        if (row.get("ai_attempts") or 0) >= MAX_ATTEMPTS:
            db.table("call_logs").update({
                "ai_status": "failed",
                "ai_error": "stopped after the maximum number of attempts",
                "ai_updated_at": _now(),
            }).eq("id", row["id"]).execute()
            finalize_call_score(db, row["id"])
            try:
                raise_alert(db, tenant_id=row.get("tenant_id"), type="transcript_failed", call_log_id=row["id"],
                            caller_id=row.get("caller_id"), quote="stopped after the maximum number of attempts")
            except Exception as alert_err:
                logger.error(f"transcript_failed alert failed for call {row['id']}: {alert_err}")
        else:
            runnable.append(row["id"])
    if runnable:
        logger.info(f"Call AI sweep: resuming {len(runnable)} call(s)")
        await asyncio.gather(*(run_call_ai(cid) for cid in runnable))
    return len(runnable)


async def sweep_crm_cutoff() -> int:
    """Check 10 for real conversations whose wrap-up never came (Missing after the cut-off)
    or arrived while the AI was still running, plus early-exit calls whose wrap-up check is
    still pending after the cut-off. Early-exit rows are always score_final=True (see
    call_scorer.compute_call_score), so they need their own query keyed on crm_matches
    instead of score_final."""
    db = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=WRAPUP_CUTOFF_HOURS)).isoformat()
    real_conversation_rows = (
        db.table("call_logs").select("id")
        .eq("provider", "telecmi").eq("ai_status", "done").eq("score_final", False)
        .eq("call_group", "real_conversation")
        .lt("created_at", cutoff).order("created_at").limit(SWEEP_BATCH).execute()
    ).data or []
    early_exit_rows = (
        db.table("call_logs").select("id")
        .eq("provider", "telecmi").eq("ai_status", "done").eq("call_group", "early_exit")
        .is_("feedback_at", "null").is_("evaluation->early_exit_check->>crm_matches", "null")
        .lt("created_at", cutoff).order("created_at").limit(SWEEP_BATCH).execute()
    ).data or []
    changed = 0
    for r in real_conversation_rows + early_exit_rows:
        try:
            changed += int(await mark_crm_update(db, r["id"]))
        except Exception as e:
            logger.error(f"CRM cut-off sweep failed for {r['id']}: {e}")
    return changed

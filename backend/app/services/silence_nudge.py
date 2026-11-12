"""Silence nudge — a short contextual follow-up sent minutes after a live AI
reply that went unanswered.

Separate from reengagement_service by design: that engine dedups per
(lead, step) with no time bound, which cannot express "fire again on the next
lull". See docs/superpowers/specs/2026-08-23-silence-nudge-design.md.
"""
import logging
from datetime import datetime, time, timedelta, timezone

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.services.ai_reply import generate_silence_nudge, send_whatsapp
from app.services.automation_guards import ai_replies_allowed, lead_blocks_automated_outbound
from app.services.entitlements import check_quota, meter
from app.services.growth import IST_OFFSET

logger = logging.getLogger(__name__)

DEFAULT_DELAYS = "5"
DEFAULT_CAP = 1
MAX_RUNGS = 3
MIN_DELAY_MINUTES = 1
MAX_DELAY_MINUTES = 1440
MAX_CAP = 10
DEFAULT_QUIET_START = time(21, 0)
DEFAULT_QUIET_END = time(9, 0)
SILENCE_NUDGE_FALLBACK = "Hey, can I help you with anything further?"


def _now() -> datetime:
    """Single clock for the whole module. Indirection so tests can pin it."""
    return datetime.now(timezone.utc)


def _parse_delays(raw: str | None) -> list[int]:
    """Comma-separated minutes, e.g. "5" or "5,60".

    Each rung waits from the previous message sent (the AI reply for rung 0,
    the prior nudge after that — see the re-arm in _process_job), so rungs are
    independent gaps and need not increase: "60,30" is valid.

    The settings UI rejects bad input on save; this is the runtime backstop for
    values edited straight into the DB. Any malformed config falls back to the
    single safe default rather than guessing.
    """
    fallback = [int(DEFAULT_DELAYS)]
    if not raw or not raw.strip():
        return fallback
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = int(part)
        except ValueError:
            logger.warning("silence_nudge: unparseable delay %r — using default", part)
            return fallback
        if not MIN_DELAY_MINUTES <= val <= MAX_DELAY_MINUTES:
            logger.warning("silence_nudge: delay %s out of range — using default", val)
            return fallback
        out.append(val)
    if not out:
        return fallback
    return out[:MAX_RUNGS]


def _parse_cap(raw: str | None) -> int:
    try:
        val = int((raw or "").strip())
    except ValueError:
        return DEFAULT_CAP
    return val if 1 <= val <= MAX_CAP else DEFAULT_CAP


def _parse_time(raw: str | None, fallback: time) -> time:
    try:
        hh, mm = (raw or "").strip().split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return fallback


def _in_quiet_window(now_ist: time, start: time, end: time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= now_ist < end
    return now_ist >= start or now_ist < end  # wraps midnight


def _next_window_end(now_utc: datetime, end: time) -> datetime:
    """The next moment the quiet window closes, in UTC."""
    now_ist = now_utc + IST_OFFSET
    candidate = now_ist.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidate <= now_ist:
        candidate += timedelta(days=1)
    return candidate - IST_OFFSET


def _quiet_window(tenant_id: str) -> tuple[time, time]:
    return (
        _parse_time(get_setting("silence_nudge_quiet_start", tenant_id=tenant_id), DEFAULT_QUIET_START),
        _parse_time(get_setting("silence_nudge_quiet_end", tenant_id=tenant_id), DEFAULT_QUIET_END),
    )


def _delays_for(tenant_id: str) -> list[int]:
    return _parse_delays(get_setting("silence_nudge_delays", fallback=DEFAULT_DELAYS, tenant_id=tenant_id))


def _enabled_for(tenant_id: str) -> bool:
    return get_setting("silence_nudge_enabled", fallback="false", tenant_id=tenant_id) == "true"


SEND = "send"
HOLD = "hold"
SKIP = "skip"

# Only these reply sources represent a live AI reply in an open thread.
# generate_reply() emits exactly these two (ai_reply.py L1568, L1620); every
# other source belongs to a different subsystem and must not arm a timer.
_LIVE_AI_SOURCES = ("ai", "knowledge")

# Every non-terminal status from intake_sessions_status_check (migration 176).
# Terminal statuses are 'resolved' and 'cancelled'.
_ACTIVE_INTAKE_STATUSES = (
    "offer_pending",
    "awaiting_package_choice",
    "collecting",
    "awaiting_confirmation",
    "awaiting_payment",
    "paid",
)

# An OPEN handover carries status='pending' — chat_handovers defaults to
# 'pending' (migration 043) and resolve_handover() flips it to 'resolved'.
# There is no 'open' value; querying for one would silently disable this gate.
_OPEN_HANDOVER_STATUS = "pending"


def arm(db, tenant_id: str, lead_id: str, anchor_message_id: str, step_index: int = 0) -> bool:
    """Insert one pending timer. Returns False when the ladder has no such rung."""
    delays = _delays_for(tenant_id)
    if step_index >= len(delays):
        return False
    fire_at = _now() + timedelta(minutes=delays[step_index])
    db.table("silence_nudge_jobs").insert({
        "tenant_id": tenant_id,
        "lead_id": str(lead_id),
        "anchor_message_id": str(anchor_message_id),
        "step_index": step_index,
        "fire_at": fire_at.isoformat(),
        "status": "pending",
    }).execute()
    return True


def cancel_pending(db, lead_id: str, reason: str = "thread advanced") -> None:
    """Drop every pending timer for a lead. Called whenever the thread moves.

    This is an optimisation, not the correctness mechanism — _thread_unchanged()
    at fire time is what actually prevents a wrong send.
    """
    db.table("silence_nudge_jobs").update(
        {"status": "cancelled", "skip_reason": reason}
    ).eq("lead_id", str(lead_id)).eq("status", "pending").execute()


def maybe_arm_after_ai_reply(db, *, tenant_id, lead_id, channel, is_ai,
                             sid, reply_source, inserted) -> bool:
    """Called straight after generate_reply() stores its outbound message."""
    if channel != "whatsapp" or not is_ai or sid is None:
        return False
    if reply_source not in _LIVE_AI_SOURCES:
        return False
    if not inserted or not inserted.get("id"):
        return False
    if not _enabled_for(tenant_id):
        return False
    cancel_pending(db, lead_id)
    return arm(db, tenant_id, lead_id, inserted["id"], step_index=0)


def _has_open_handover(db, tenant_id: str, lead_id: str) -> bool:
    rows = (
        db.table("chat_handovers")
        .select("id")
        .eq("lead_id", str(lead_id))
        .eq("status", _OPEN_HANDOVER_STATUS)
        .limit(1)
        .execute()
        .data
    ) or []
    return bool(rows)


def _has_active_intake(db, tenant_id: str, lead_id: str) -> bool:
    rows = (
        db.table("intake_sessions")
        .select("id")
        .eq("lead_id", str(lead_id))
        .in_("status", list(_ACTIVE_INTAKE_STATUSES))
        .limit(1)
        .execute()
        .data
    ) or []
    return bool(rows)


def _sent_in_last_24h(db, lead_id: str) -> int:
    since = (_now() - timedelta(hours=24)).isoformat()
    rows = (
        db.table("silence_nudge_jobs")
        .select("id")
        .eq("lead_id", str(lead_id))
        .eq("status", "sent")
        .gte("sent_at", since)
        .execute()
        .data
    ) or []
    return len(rows)


def _evaluate_gates(db, job: dict, lead: dict) -> tuple[str, str | None]:
    """Gates 1-7 of the spec. HOLD leaves the job pending; SKIP consumes it."""
    tenant_id = job["tenant_id"]
    lead_id = job["lead_id"]

    # Gates 1-2: master switches leave the job queued, so automation resumes
    # cleanly when the tenant flips them back on rather than losing the work.
    if not _enabled_for(tenant_id):
        return HOLD, "silence nudge disabled"
    if not ai_replies_allowed(tenant_id, "whatsapp", lead.get("source")):
        return HOLD, "ai auto reply disabled"

    # Gates 3-4: shared lead-level gates, plus the three silence-only checks
    # that reengagement deliberately does not perform.
    block = lead_blocks_automated_outbound(lead)
    if block:
        return SKIP, block
    if not lead.get("ai_enabled", True):
        return SKIP, "ai disabled for lead"
    if lead.get("converted_at"):
        return SKIP, "lead converted"
    if lead.get("blocked_at"):
        return SKIP, "lead blocked"

    # Gate 5: a lead waiting on a promised human callback must not get an
    # automated "anything else?" from the same business.
    if lead.get("needs_human_attention"):
        return SKIP, "escalated to human"
    if _has_open_handover(db, tenant_id, lead_id):
        return SKIP, "open handover"

    # Gate 6: intake sends its own holding messages; two uncoordinated
    # automated messages to a paying customer read as broken.
    if _has_active_intake(db, tenant_id, lead_id):
        return SKIP, "active intake session"

    # Gate 7
    cap = _parse_cap(get_setting("silence_nudge_daily_cap", fallback=str(DEFAULT_CAP), tenant_id=tenant_id))
    if _sent_in_last_24h(db, lead_id) >= cap:
        return SKIP, "daily cap reached"

    return SEND, None


_LEAD_COLUMNS = (
    "id,name,phone,ai_enabled,converted_at,blocked_at,opted_out,"
    "whatsapp_undeliverable,needs_human_attention,last_inbound_at,source"
)


def _mark(db, job: dict, status: str, reason: str | None, preview: str | None = None) -> None:
    patch_row: dict = {"status": status, "skip_reason": reason}
    if status == "sent":
        patch_row["sent_at"] = _now().isoformat()
        patch_row["message_preview"] = preview
    db.table("silence_nudge_jobs").update(patch_row).eq("id", job["id"]).execute()


def _fetch_lead(db, job: dict) -> dict | None:
    rows = (
        db.table("leads").select(_LEAD_COLUMNS)
        .eq("id", job["lead_id"]).limit(1).execute().data
    ) or []
    return rows[0] if rows else None


def _thread_unchanged(db, job: dict) -> bool:
    """True only if our anchor is still the newest message in the thread."""
    rows = (
        db.table("messages").select("id")
        .eq("lead_id", job["lead_id"])
        .order("created_at", desc=True).limit(1).execute().data
    ) or []
    return bool(rows) and rows[0]["id"] == job["anchor_message_id"]


def _window_open(lead: dict) -> bool:
    raw = lead.get("last_inbound_at")
    if not raw:
        return False
    try:
        last_inbound = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (_now() - last_inbound) <= timedelta(hours=24)


async def _process_job(db, job: dict) -> bool:
    tenant_id = job["tenant_id"]
    lead = _fetch_lead(db, job)
    if not lead:
        _mark(db, job, "skipped", "lead missing")
        return False

    action, reason = _evaluate_gates(db, job, lead)
    if action == HOLD:
        return False  # stays pending; resumes when the switch flips back
    if action == SKIP:
        _mark(db, job, "skipped", reason)
        return False

    # Gate 8: the first rung always fires — the lead messaged minutes ago and
    # is demonstrably awake. Later rungs defer out of the quiet window.
    now = _now()
    if job["step_index"] > 0:
        quiet_start, quiet_end = _quiet_window(tenant_id)
        if _in_quiet_window((now + IST_OFFSET).time(), quiet_start, quiet_end):
            db.table("silence_nudge_jobs").update(
                {"fire_at": _next_window_end(now, quiet_end).isoformat()}
            ).eq("id", job["id"]).execute()
            return False

    # Gate 9: the race. Second line of defence behind cancel_pending().
    if not _thread_unchanged(db, job):
        _mark(db, job, "cancelled", "lead replied")
        return False

    # Gate 10
    if not _window_open(lead):
        _mark(db, job, "skipped", "24h window closed")
        return False

    if not check_quota(db, tenant_id, "ai_reply"):
        _mark(db, job, "skipped", "ai_reply quota exhausted")
        return False

    text = await generate_silence_nudge(job["lead_id"], db=db)
    sid = await send_whatsapp(lead["phone"], text, tenant_id=tenant_id)
    if not sid:
        _mark(db, job, "failed", "channel send returned no id")
        return False

    res = db.table("messages").insert({
        "lead_id": job["lead_id"],
        "tenant_id": tenant_id,
        "direction": "outbound",
        "channel": "whatsapp",
        "content": text,
        "is_ai_generated": True,
        "meta_message_id": sid,
        "reply_source": "silence_nudge",
    }).execute()
    meter(db, tenant_id, "ai_reply")
    _mark(db, job, "sent", None, preview=text)

    # The next rung anchors on the nudge we just sent — it is now the newest
    # message, so anchoring on the original reply would self-cancel instantly.
    new_anchor = ((res.data or [{}])[0] or {}).get("id") or job["anchor_message_id"]
    arm(db, tenant_id, job["lead_id"], new_anchor, step_index=job["step_index"] + 1)
    return True


async def drain_due_nudges(limit: int = 100) -> int:
    """Send every due silence nudge. Returns the number actually sent."""
    db = get_supabase()
    jobs = (
        db.table("silence_nudge_jobs").select("*")
        .eq("status", "pending")
        .lte("fire_at", _now().isoformat())
        .order("fire_at").limit(limit).execute().data
    ) or []

    sent = 0
    for job in jobs:
        try:
            if await _process_job(db, job):
                sent += 1
        except Exception:
            logger.exception("Silence nudge job %s failed", job.get("id"))
            try:
                _mark(db, job, "failed", "unhandled error")
            except Exception:
                logger.exception("Could not mark silence nudge job %s failed", job.get("id"))
    return sent

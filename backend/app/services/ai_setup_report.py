"""Anril Setup (v9.2 #23): Couldn't answer, the AI report card, thumbs-down on AI replies, and the
read-only Questions & scoring view.

Every query filters tenant_id. A missing table or column (migration 322 not applied yet) gives an
empty or neutral answer, never a crash. No AI call is made anywhere in here.
"""
import logging
import uuid
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from app.services import ai_teach
from app.services.brain import handovers as handover_kinds
from app.services.brain import headline
from app.services.brain.paging import fetch_bounded
from app.services.reports_common import Period, chunks, today_ist

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 30
MAX_DAYS = 90
ANSWER_LOOKBACK_DAYS = 365
HANDOVER_CAP = 1000
GROUP_CAP = 100
SAMPLE_LEADS = 3
LEAD_CHUNK = 50
FEEDBACK_REASONS = ("wrong", "rude", "too_long", "other")
NOTE_MAX = 300
FIX_CAP = 5
QUESTION_PREVIEW = 80


class SetupError(Exception):
    """A plain-words problem the owner can fix. `status` is the HTTP code the route answers with."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ── the picked period ─────────────────────────────────────────────────────────

def parse_days(period: str | None) -> int:
    """'30d' -> 30. Nothing picked = 30 days. 1 to 90 days."""
    text = (period or "").strip().lower()
    if not text:
        return DEFAULT_DAYS
    found = re.fullmatch(r"(\d{1,3})d", text)
    if not found or not 1 <= int(found.group(1)) <= MAX_DAYS:
        raise SetupError(f"Pick a period like 7d, 30d or {MAX_DAYS}d.", 400)
    return int(found.group(1))


def period_for(days: int) -> Period:
    end = today_ist()
    return Period(end - timedelta(days=days - 1), end)


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _preview(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= QUESTION_PREVIEW else text[:QUESTION_PREVIEW - 3].rstrip() + "..."


# ── Couldn't answer ───────────────────────────────────────────────────────────

def _gap_handovers(db, tenant_id: str, since_iso: str, caller_id: str | None) -> list[dict]:
    """Knowledge-gap handovers since since_iso, newest first, that nobody has answered yet.
    caller_id None = everyone's; "" = a telecaller with no profile, who sees none."""
    if caller_id == "":
        return []

    def read(columns: str):
        q = (db.table("chat_handovers").select(columns).eq("tenant_id", tenant_id)
             .gte("opened_at", since_iso).order("opened_at", desc=True).limit(HANDOVER_CAP * 2))
        if caller_id:
            q = q.eq("assigned_to", caller_id)
        return q.execute().data or []
    try:
        rows = read("id,lead_id,reason,opened_at,answered_at")
    except Exception:
        try:
            rows = read("id,lead_id,reason,opened_at")  # migration 322 not applied yet
        except Exception as exc:
            logger.warning("couldn't answer: handovers unavailable: %s", exc)
            return []
    gaps = [r for r in rows if handover_kinds.classify_reason(r.get("reason")) == handover_kinds.KIND_KNOWLEDGE_GAP
            and not r.get("answered_at") and r.get("lead_id")]
    return gaps[:HANDOVER_CAP]


def _question_per_handover(db, tenant_id: str, rows: list[dict]) -> dict[str, str]:
    """handover id -> the customer's likely message: their latest inbound message at or before the
    handover opened. Read in batches per customer (no query per handover)."""
    by_lead: dict[str, list[dict]] = {}
    for r in rows:
        by_lead.setdefault(r["lead_id"], []).append(r)
    opened = [t for t in (_ts(r["opened_at"]) for r in rows) if t]
    if not opened:
        return {}
    floor = (min(opened).replace(microsecond=0)).isoformat()
    ceiling = max(opened).isoformat()
    out: dict[str, str] = {}
    for lead_ids in chunks(list(by_lead), LEAD_CHUNK):
        try:
            messages = fetch_bounded(
                lambda ids=lead_ids: db.table("messages").select("id,lead_id,content,created_at")
                .eq("tenant_id", tenant_id).eq("direction", "inbound").in_("lead_id", ids)
                .gte("created_at", _day_before(floor)).lte("created_at", ceiling)
                .order("created_at").order("id"),
                "couldn't answer messages")
        except Exception as exc:
            logger.warning("couldn't answer: messages unavailable: %s", exc)
            continue
        per_lead: dict[str, list[tuple[datetime, str]]] = {}
        for m in messages:
            when, text = _ts(m.get("created_at")), (m.get("content") or "").strip()
            if when and text:
                per_lead.setdefault(m["lead_id"], []).append((when, text))
        for lead_id in lead_ids:
            sent = per_lead.get(lead_id, [])
            for handover in by_lead[lead_id]:
                at = _ts(handover["opened_at"])
                before = [text for when, text in sent if at and when <= at]
                if before:
                    out[handover["id"]] = before[-1][:handover_kinds.QUESTION_MAX_CHARS]
    return out


def _day_before(iso: str) -> str:
    when = _ts(iso)
    return (when - timedelta(days=1)).isoformat() if when else iso


def group_questions(rows: list[dict], questions: dict[str, str], *, show_leads: bool = True) -> list[dict]:
    """Pure. Same question once case, spaces and punctuation are ignored = one group.
    -> [{question, count, last_at, sample_lead_ids, key, handover_ids}], most asked first."""
    groups: dict[str, dict] = {}
    for r in rows:
        text = questions.get(r["id"])
        key = ai_teach.match_key(text or "")
        if not key:
            continue
        g = groups.setdefault(key, {"key": key, "question": text, "count": 0, "last_at": r["opened_at"],
                                    "_leads": [], "handover_ids": []})
        g["count"] += 1
        g["handover_ids"].append(r["id"])
        if (_ts(r["opened_at"]) or datetime.min.replace(tzinfo=timezone.utc)) >= (
                _ts(g["last_at"]) or datetime.min.replace(tzinfo=timezone.utc)):
            g["last_at"], g["question"] = r["opened_at"], text
        if r["lead_id"] not in g["_leads"]:
            g["_leads"].append(r["lead_id"])
    out = []
    for g in groups.values():
        leads = g.pop("_leads")
        g["sample_lead_ids"] = leads[:SAMPLE_LEADS] if show_leads else []
        out.append(g)
    out.sort(key=lambda g: (-g["count"], -(_ts(g["last_at"]) or datetime.min.replace(tzinfo=timezone.utc)).timestamp()))
    return out


def _already_taught(db, tenant_id: str) -> dict[str, datetime | None]:
    """match_key -> when that answer was last taught (Teach & offers shares this one list)."""
    return {i.get("match_key"): _ts(i.get("updated_at")) for i in ai_teach.list_items(db, tenant_id, "answer")
            if i.get("match_key")}


def couldnt_answer(db, tenant_id: str, days: int, *, show_leads: bool = True, caller_id: str | None = None,
                   now: datetime | None = None) -> list[dict]:
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
    rows = _gap_handovers(db, tenant_id, since, caller_id)
    if not rows:
        return []
    groups = group_questions(rows, _question_per_handover(db, tenant_id, rows), show_leads=show_leads)
    taught = _already_taught(db, tenant_id)
    shown = []
    for g in groups:
        taught_at = taught.get(g["key"])
        last = _ts(g["last_at"])
        if taught_at and last and taught_at >= last:
            continue  # answered in Teach & offers after the last time it was asked
        shown.append({"question": g["question"], "count": g["count"], "last_at": g["last_at"],
                      "sample_lead_ids": g["sample_lead_ids"]})
    return shown[:GROUP_CAP]


def answer_question(db, tenant_id: str, question: str, answer: str, user_id: str | None) -> dict:
    """Saves the answer to the shared Teach list and marks the matching handovers answered."""
    question, answer = (question or "").strip(), (answer or "").strip()
    if not question or not answer:
        raise SetupError("Type the answer the AI agent should give.")
    try:
        item = ai_teach.save_item(db, tenant_id, "answer", question, answer, source="couldnt_answer", user_id=user_id)
    except ai_teach.TableMissing:
        raise SetupError(ai_teach.NOT_READY, 503) from None
    except ai_teach.TeachError as exc:
        raise SetupError(str(exc), exc.status) from None
    key = ai_teach.match_key(question)
    marked = 0
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=ANSWER_LOOKBACK_DAYS)).isoformat()
        rows = _gap_handovers(db, tenant_id, since, None)
        questions = _question_per_handover(db, tenant_id, rows)
        ids = [r["id"] for r in rows if ai_teach.match_key(questions.get(r["id"]) or "") == key]
        for batch in chunks(ids, 100):
            db.table("chat_handovers").update({"answered_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("tenant_id", tenant_id).in_("id", batch).execute()
            marked += len(batch)
    except Exception as exc:  # the column may not exist yet; the answer is saved anyway
        logger.warning("couldn't answer: could not mark handovers answered: %s", exc)
    return {"saved": item, "marked_answered": marked}


# ── thumbs-down on an AI reply ────────────────────────────────────────────────

def save_feedback(db, ctx: dict, message_id: str, reason: str, note: str | None) -> dict:
    if reason not in FEEDBACK_REASONS:
        raise SetupError("Pick why: wrong answer, rude, too long or other.")
    note = (note or "").strip()
    if len(note) > NOTE_MAX:
        raise SetupError(f"Keep the note under {NOTE_MAX} letters.")
    tenant_id = ctx["tenant_id"]
    try:
        found = db.table("messages").select("id,lead_id,direction,is_ai_generated").eq("id", message_id) \
            .eq("tenant_id", tenant_id).limit(1).execute().data or []
    except Exception:  # noqa: BLE001 - a malformed id is just "not found", never a 500
        found = []
    if not found:
        raise SetupError("That message was not found.", 404)
    message = found[0]
    if message.get("direction") != "outbound" or not message.get("is_ai_generated"):
        raise SetupError("Only replies sent by the AI agent can get a thumbs-down.")
    if ctx.get("role") == "caller":
        lead = db.table("leads").select("assigned_to").eq("id", message["lead_id"]).eq("tenant_id", tenant_id) \
            .limit(1).execute().data or []
        if not lead or lead[0].get("assigned_to") != ctx.get("caller_id"):
            raise SetupError("That message was not found.", 404)
    row = {"tenant_id": tenant_id, "message_id": message_id, "lead_id": message["lead_id"], "reason": reason,
           "note": note or None, "created_by": ctx["user_id"]}
    try:
        existing = db.table("ai_reply_feedback").select("id").eq("tenant_id", tenant_id) \
            .eq("message_id", message_id).eq("created_by", ctx["user_id"]).limit(1).execute().data or []
        if existing:
            db.table("ai_reply_feedback").update({"reason": reason, "note": note or None}) \
                .eq("id", existing[0]["id"]).eq("tenant_id", tenant_id).execute()
            return {**row, "id": existing[0]["id"]}
        res = db.table("ai_reply_feedback").insert(row).execute()
        return (res.data or [row])[0]
    except Exception as exc:
        if ai_teach._is_missing(exc):
            raise SetupError("Thumbs-down is not ready yet. Try again in a little while.", 503) from None
        raise


def delete_feedback(db, ctx: dict, message_id: str) -> None:
    """Undo: removes only the caller's own thumbs-down on that reply."""
    try:
        db.table("ai_reply_feedback").delete().eq("tenant_id", ctx["tenant_id"]) \
            .eq("message_id", message_id).eq("created_by", ctx["user_id"]).execute()
    except Exception as exc:
        if not ai_teach._is_missing(exc):
            raise


MINE_MAX_IDS = 200


def _is_uuid(value: str) -> bool:
    """One bad id would make the whole lookup fail, hiding every mark on screen: drop it instead."""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def my_feedback(db, ctx: dict, message_ids: list[str]) -> dict[str, dict]:
    """The caller's own thumbs-down marks on the given replies: {message_id: {reason, note}}.

    Only marks this person made, in this business. Anything unreadable (table not ready yet) is just "no marks".
    """
    ids = [m for m in dict.fromkeys(i.strip() for i in message_ids if i and i.strip()) if _is_uuid(m)][:MINE_MAX_IDS]
    if not ids:
        return {}
    try:
        rows = db.table("ai_reply_feedback").select("message_id,reason,note").eq("tenant_id", ctx["tenant_id"]) \
            .eq("created_by", ctx["user_id"]).in_("message_id", ids).execute().data or []
    except Exception as exc:  # noqa: BLE001 - a missing table or a malformed id means "no marks", never a 500
        logger.warning("reply feedback: could not read own marks: %s", exc)
        return {}
    return {r["message_id"]: {"reason": r.get("reason"), "note": r.get("note")} for r in rows if r.get("message_id")}


def _feedback_rows(db, tenant_id: str, period: Period) -> list[dict]:
    try:
        return fetch_bounded(
            lambda: db.table("ai_reply_feedback").select("id,reason").eq("tenant_id", tenant_id)
            .gte("created_at", period.start_iso).lt("created_at", period.end_iso).order("created_at").order("id"),
            "reply feedback")
    except Exception as exc:
        logger.warning("report card: feedback unavailable: %s", exc)
        return []


# ── the AI report card ────────────────────────────────────────────────────────

def _counts_in_database(db, tenant_id: str, period: Period) -> dict | None:
    """The four report-card numbers counted by migration 326 in one round trip.
    None when the function is not there yet (or answers oddly): the caller counts on the server instead."""
    try:
        res = db.rpc("ai_report_card_counts", {"p_tenant_id": tenant_id, "p_start": period.start_iso,
                                               "p_end": period.end_iso}).execute()
        data = res.data
        row = data[0] if isinstance(data, list) and data else data
        if not isinstance(row, dict):
            return None
        return {"chats": int(row["chats"]), "handled_by_aira": int(row["handled_alone"]),
                "handed_over": int(row["handed_over"]), "knowledge_gaps": int(row["knowledge_gaps"])}
    except Exception as exc:
        logger.info("report card: counting on the server (database counts unavailable): %s", exc)
        return None


def _handled(db, tenant_id: str, period: Period) -> dict:
    counted = _counts_in_database(db, tenant_id, period)
    if counted is not None:
        return counted
    try:
        messages = fetch_bounded(
            lambda: db.table("messages").select("lead_id,direction,is_ai_generated,reply_source")
            .eq("tenant_id", tenant_id).gte("created_at", period.start_iso).lt("created_at", period.end_iso)
            .order("created_at").order("id"), "report card messages")
        opened = fetch_bounded(
            lambda: db.table("chat_handovers").select("lead_id,reason").eq("tenant_id", tenant_id)
            .gte("opened_at", period.start_iso).lt("opened_at", period.end_iso).order("opened_at").order("id"),
            "report card handovers")
        return headline.aggregate(messages, opened)
    except Exception as exc:
        logger.warning("report card: chats unavailable: %s", exc)
        return {"chats": 0, "handled_by_aira": 0, "handed_over": 0}


def _ai_revenue(db, tenant_id: str, period: Period) -> int:
    from app.services.reports_data import sales_before_gst, won_deals
    try:
        return sum(sales_before_gst(d) for d in won_deals(db, tenant_id, period) if d.get("sold_by_ai"))
    except Exception as exc:
        logger.warning("report card: AI sales unavailable: %s", exc)
        return 0


def fix_these(top_questions: list[dict], feedback_counts: dict[str, int], gap_chats: int) -> list[dict]:
    """Plain next steps; each one links to the page where it gets fixed."""
    fixes: list[dict] = []
    if top_questions:
        top = top_questions[0]
        more = len(top_questions) - 1
        text = f"The AI agent could not answer \"{_preview(top['question'])}\" ({top['count']} times)."
        if more:
            text += f" {more} more question{'s' if more != 1 else ''} also waiting."
        fixes.append({"kind": "couldnt_answer", "text": text,
                      "href": "/dashboard/brain/couldnt-answer?question=" + _quote(top["question"])})
    if feedback_counts.get("wrong"):
        n = feedback_counts["wrong"]
        fixes.append({"kind": "wrong_answers", "href": "/dashboard/teach",
                      "text": f"{n} {'reply was' if n == 1 else 'replies were'} marked wrong. Teach the right answer."})
    if gap_chats and not top_questions:
        fixes.append({"kind": "knowledge", "href": "/dashboard/knowledge",
                      "text": f"{gap_chats} {'chat' if gap_chats == 1 else 'chats'} went to a person because the answer "
                              "was missing. Add it to your Knowledge Base."})
    elif feedback_counts.get("wrong") and top_questions:
        fixes.append({"kind": "knowledge", "href": "/dashboard/knowledge",
                      "text": "Check your Knowledge Base for facts that are out of date."})
    tone = feedback_counts.get("rude", 0) + feedback_counts.get("too_long", 0)
    if tone:
        fixes.append({"kind": "tone", "href": "/dashboard/brain",
                      "text": f"{tone} {'reply was' if tone == 1 else 'replies were'} marked rude or too long. "
                              "Change how the AI agent talks."})
    return fixes[:FIX_CAP]


def _quote(text: str) -> str:
    return quote((text or "")[:300], safe="")


def report_card(db, tenant_id: str, days: int, *, sees_money: bool, caller_id: str | None = None) -> dict:
    period = period_for(days)
    counts = _handled(db, tenant_id, period)
    chats = int(counts.get("chats") or 0)
    alone = int(counts.get("handled_by_aira") or 0)
    feedback = _feedback_rows(db, tenant_id, period)
    reasons: dict[str, int] = {}
    for f in feedback:
        reasons[f.get("reason") or "other"] = reasons.get(f.get("reason") or "other", 0) + 1
    questions = couldnt_answer(db, tenant_id, days, show_leads=False, caller_id=caller_id)
    card = {
        "period": {"days": days, "from": period.start.isoformat(), "to": period.end.isoformat()},
        "chats": chats,
        "handled_alone_pct": round(alone * 100 / chats) if chats else None,
        "passed_to_person": int(counts.get("handed_over") or 0),
        "wrong_answers": reasons.get("wrong", 0),
        "fix_these": fix_these(questions, reasons, int(counts.get("knowledge_gaps") or 0)),
    }
    if sees_money:
        card["revenue_from_ai_paise"] = _ai_revenue(db, tenant_id, period)
    else:
        card["money_hidden"] = True
    return card


# ── Questions & scoring (read-only) ───────────────────────────────────────────

LEVELS = (
    ("hot", "Hot", "8 to 10", "The customer took a buying step: asked the price, how to pay, to book or visit, "
                              "or sent what is needed to start."),
    ("warm", "Warm", "4 to 7", "Real interest but no buying step yet: asks about what you sell, describes a need "
                              "you can meet, compares options, or says they will decide later."),
    ("cold", "Cold", "1 to 3", "No real interest shown: only a greeting, one word, an emoji, a wrong number, or "
                              "something you do not sell."),
    ("not_interested", "Not interested", "0", "The customer said no themselves (for example \"not interested\" "
                                             "or \"please stop\")."),
)
_LEVEL_WORD = {"hot": "hot", "warm": "warm", "cold": "cold"}
_RUBRIC_LINE = re.compile(r"^[\s\-*•]*(hot|warm|cold)\s*[:\-]\s*(.+)$", re.IGNORECASE)
_PLAIN_PATTERN = re.compile(r"^\\b([a-z' ?]+)\\b$")


def _tenant_rubric(tenant_id: str) -> str:
    from app.services import scoring_engine
    try:
        from app.config_dynamic import get_setting
        custom = get_setting("scoring_rubric", tenant_id=tenant_id)
    except Exception:
        custom = None
    if custom and scoring_engine._is_old_5band_rubric(custom):
        return scoring_engine.convert_5band_rubric(custom) or scoring_engine._ARC_RUBRIC_DEFAULT.strip()
    return (custom or scoring_engine._ARC_RUBRIC_DEFAULT).strip()


def _own_examples(rubric: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"hot": [], "warm": [], "cold": []}
    for line in rubric.splitlines():
        found = _RUBRIC_LINE.match(line)
        if found:
            out[_LEVEL_WORD[found.group(1).lower()]].extend(
                p.strip() for p in re.split(r"[;]", found.group(2)) if p.strip())
    return out


def not_interested_phrases() -> list[str]:
    """The plain English phrases that mark a customer Not interested straight away (from the real list)."""
    from app.services import scoring_engine
    out = []
    for pattern in scoring_engine._REJECTION_PATTERNS:
        found = _PLAIN_PATTERN.match(pattern)
        if found:
            out.append(found.group(1).replace("'?", "'").replace("?", ""))
    return out


def scoring_view(tenant_id: str) -> dict:
    own = _own_examples(_tenant_rubric(tenant_id))
    return {
        "read_only": True,
        "note": "Editing comes later.",
        "questions": [],
        "questions_note": "The AI agent asks what it needs from your instructions and Knowledge Base. "
                          "A fixed list of questions to ask every customer comes later.",
        "levels": [{"key": key, "label": label, "points": points, "meaning": meaning,
                    "your_examples": own.get(key, [])} for key, label, points, meaning in LEVELS],
        "not_interested_words": not_interested_phrases(),
    }

"""Step 2 — mark a real conversation out of 100 on 10 fixed checks.

The AI chooses only a level (+ reason + quote) per check. The system validates
every quote, applies the talk-share/interruption caps, forces product info to
Missing on a proven wrong statement, and computes every mark and the total.
Check 10 (CRM update) is left pending here and marked from the wrap-up.
"""
import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.services.call_alerts import raise_alert
from app.services.call_lines import Line, clock, format_transcript, parse_transcript
from app.services.call_metrics import courtesy_cap, listening_cap_reason, lower_level, plurality, tips
from app.services.call_quotes import clean_quote, clip, find_quote
from app.services.call_report import REPORT_RUBRIC, build_report
from app.services.call_scorer import finalize_call_score
from app.services.call_wrapup import (
    AI_CALL_STATUSES, CONNECT_LABEL, LANGUAGE_LABEL, OUTCOME_LABEL, TEMPERATURE_FOR_OUTCOME, TEMPERATURES,
)
from app.services.gemini_client import gemini_analysis_json
from app.services.scoring_rules import AI_VOTES, CHECK_MARKS, LEVEL_ORDER, LEVEL_SHARE, WRAPUP_CUTOFF_HOURS

logger = logging.getLogger(__name__)

CRM_AI_ATTEMPT_CAP = 3
# The 9 checks plus the manager's report; a cut-off reply fails the whole vote, so leave headroom.
MARKING_MAX_TOKENS = 6000

CHECKS: list[dict] = [
    {"key": "opening", "label": "Opening", "stage": "connect"},
    {"key": "courtesy", "label": "Courtesy & empathy", "stage": "connect"},
    {"key": "questions", "label": "Asking questions", "stage": "understand"},
    {"key": "listening", "label": "Listening", "stage": "understand"},
    {"key": "product_info", "label": "Correct product information", "stage": "explain"},
    {"key": "doubts", "label": "Clearing doubts", "stage": "explain"},
    {"key": "clarity", "label": "Clarity", "stage": "explain"},
    {"key": "next_step", "label": "Next step", "stage": "close"},
    {"key": "decision", "label": "Asking for the decision", "stage": "close"},
    {"key": "crm_update", "label": "CRM update", "stage": "close"},
]
for _c in CHECKS:
    _c["full"] = CHECK_MARKS[_c["key"]]
AI_CHECKS = [c["key"] for c in CHECKS if c["key"] != "crm_update"]


class CallMarkingError(Exception):
    """The AI reply didn't give a valid level for every check."""


@dataclass
class MarkResult:
    checks: list[dict]
    rude_quote: str | None = None
    wrong_info: list[dict] = field(default_factory=list)
    unverified_claims: list[str] = field(default_factory=list)
    proof_missing: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    report: dict = field(default_factory=dict)


def check_marks(key: str, level: str | None) -> float:
    return CHECK_MARKS[key] * LEVEL_SHARE[level] if level else 0.0


def total_score(checks: list[dict]) -> float:
    return round(sum(check_marks(c["key"], c.get("level")) for c in checks), 1)


def top_improve(checks: list[dict]) -> list[str]:
    marked = [c for c in checks if c.get("level")]
    marked.sort(key=lambda c: (check_marks(c["key"], c["level"]) / CHECK_MARKS[c["key"]], -CHECK_MARKS[c["key"]]))
    return [c["key"] for c in marked[:2]]


def apply_level(check: dict, ai_level: str, cap: str, cap_name: str | None) -> dict:
    level = lower_level(ai_level, cap)
    out = dict(check)
    out.update({
        "ai_level": ai_level,
        "level": level,
        "capped_by": cap_name if level != ai_level else None,
        "marks": round(check_marks(check["key"], level), 2),
    })
    return out


_SYSTEM = (
    "You are a strict, consistent quality reviewer for a telecalling team. You mark ONE real sales "
    "conversation using a fixed rubric. The transcript lines carry exact times and certain speaker "
    "labels. Judge only what the telecaller did, never whether the customer bought. Use only the "
    "transcript, the knowledge base, the previous notes and the two numbers given. No guessing. "
    "Write reasons in English; copy quotes exactly as they appear in the transcript."
)

_RUBRIC = """Mark checks 1-9. For each give level ("excellent"|"good"|"partial"|"poor"|"missing"), a one-line reason, and a short exact quote from the transcript that supports it (for "missing", quote the line showing the gap, or null and say in the reason what was not said).
1 opening: greeting, telecaller's name, company name, reminder of the enquiry/reason for the call, asking if it's a good time. excellent = all within ~30s; good = one missing; partial = two+ missing or rushed/unclear reason; poor = straight into selling without introducing; missing = no introduction or rude start.
2 courtesy: polite words, acknowledging feelings, patience, no pressure (no "decide now", no false urgency, no pushing after a no), respectful ending. excellent = all; good = misses one; partial = dry/scripted or slightly pushy once; poor = impatient or pushy several times (also: still pushing after the customer's 2nd "not interested" is poor at most); missing = rude, sarcastic, dismissive or abusive.
3 questions: open questions on need, budget, timing, decision-maker. excellent = need + at least 2 of the others; good = need + 1; partial = only 1-2 basic or yes/no questions; poor = assumed the need; missing = none. On a follow-up call where the need is already known (see previous notes), confirming the need counts as asking.
4 listening: repeating back/summarising, using the customer's answers, balanced talk. excellent = summarised/confirmed, built on answers; good = one missed chance to confirm; partial = some points ignored or talked too much; poor = mostly ignored answers or interrupted often; missing = talked over the customer or ignored everything.
5 product_info: compare with the knowledge base. excellent = all correct and linked to the customer's need; good = correct but general; partial = mostly correct but vague/missing details; poor = several gaps or couldn't answer basics; missing = gave wrong information. Something the knowledge base doesn't cover is NOT wrong: list it under unverified_claims. Only statements that clearly contradict the knowledge base are wrong: list each under wrong_info with the telecaller's exact quote and the knowledge-base fact.
6 doubts: excellent = answered every question/concern clearly and checked the customer was satisfied, or (if none were raised) explained common doubts upfront; good = answered but didn't check; partial = vague answers; poor = avoided or brushed off, or confusing; missing = ignored or argued.
7 clarity: excellent = simple, organised, customer never asked "what?"; good = a little repetition; partial = some confusing parts or overly long; poor = frequently confusing; missing = customer clearly couldn't follow.
8 next_step: excellent = specific next step agreed by the customer with date and time; good = agreed, no exact time; partial = vague ("I'll call you sometime"); poor = mentioned but not agreed; missing = none. A correctly disqualified customer ended politely counts as excellent.
9 decision: excellent = asked clearly at a suitable moment without pressure; good = asked weakly/indirectly; partial = only hinted; poor = asked too early or pushed; missing = never asked. For a correctly disqualified customer, politely keeping the door open counts as excellent.
Also: rude (true only if the telecaller was rude/abusive; rude_quote = their exact line); excused_interruptions = how many of the interruptions were the telecaller politely bringing a long off-topic customer back ("Sorry to cut in, sir…"), with the reason in the courtesy reason.

Return JSON only:
{"checks": {"opening": {"level": "...", "reason": "...", "quote": "..."}, ... all 9 keys ...}, "rude": false, "rude_quote": null, "excused_interruptions": 0, "wrong_info": [{"quote": "...", "kb_fact": "..."}], "unverified_claims": ["..."]}"""


def _numbers_block(share, ipm, count) -> str:
    share_txt = f"{share:.0f}% of the words were the telecaller's" if share is not None else "not measured (too few words)"
    int_txt = f"{count} times ({ipm:.2f} per 5 minutes)" if ipm is not None else "not measured"
    return (
        f"Talk share: {share_txt}. Interruptions (telecaller cut in while the customer was speaking): {int_txt}.\n"
        "These numbers guide listening and courtesy, but you must still read what was said.\n"
    )


def _quote_ok(level: str, quote, lines: list[Line]) -> tuple[bool, Line | None]:
    line = find_quote(quote, lines)
    if line:
        return True, line
    return level == "missing" and clean_quote(quote) is None, None


def _majority_level(votes: list[str]) -> str:
    """The most common level; on a tie (including exactly 2 votes that disagree) the median
    by LEVEL_ORDER — the lower of the two when there are only two votes."""
    return plurality(votes, lambda _winners: sorted(votes, key=LEVEL_ORDER.index)[(len(votes) - 1) // 2])


def _median_int(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


async def _gather_votes(coros, *, label: str) -> list[dict]:
    """Run the AI votes concurrently; a failing run counts as an invalid vote instead of
    sinking every other run (asyncio.gather with return_exceptions=True)."""
    results = await asyncio.gather(*coros, return_exceptions=True)
    valid = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"{label} vote failed: {type(r).__name__}: {r}")
        elif isinstance(r, dict):
            valid.append(r)
        else:
            logger.warning(f"{label} vote returned an unexpected type: {type(r).__name__}")
    return valid


async def mark_call(
    lines: list[Line], *, kb_context: str | None, previous_notes: str | None, talk_share: float | None,
    interruptions_per_5min: float | None, interruption_count: int | None, duration_seconds: int | None,
    tenant_id: str | None,
) -> MarkResult:
    kb = kb_context or "none available (treat product claims you can't check as unverified, not wrong)"
    prompt = (
        f"Transcript:\n{format_transcript(lines)}\n\n"
        f"Knowledge base:\n{kb}\n\n"
        f"Previous notes on this lead:\n{previous_notes or 'none'}\n\n"
        f"{_numbers_block(talk_share, interruptions_per_5min, interruption_count)}\n{_RUBRIC}\n\n{REPORT_RUBRIC}"
    )
    runs = await _gather_votes((
        gemini_analysis_json(
            system_prompt=_SYSTEM, user_prompt=prompt, tenant_id=tenant_id, temperature=0.0, purpose="call_marking",
            max_tokens=MARKING_MAX_TOKENS,
        )
        for _ in range(AI_VOTES)
    ), label="mark_call")
    raw_list = [d.get("checks") if isinstance(d.get("checks"), dict) else {} for d in runs]

    excused_values = []
    for d in runs:
        v = d.get("excused_interruptions")
        excused_values.append(v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0)
    excused = _median_int(excused_values)
    ipm_for_caps = interruptions_per_5min
    if ipm_for_caps is not None and interruption_count and excused:
        remaining = max(0, interruption_count - excused)
        ipm_for_caps = round(ipm_for_caps * remaining / interruption_count, 2)

    rude_votes = []
    for d in runs:
        if d.get("rude") is True:
            line = find_quote(d.get("rude_quote"), lines, ("telecaller",))
            if line:
                rude_votes.append((d.get("rude_quote"), line))
    rude_line = rude_votes[0][1] if len(rude_votes) >= 2 else None
    rude_quote_raw = rude_votes[0][0] if len(rude_votes) >= 2 else None

    wrong_seen: dict[int, dict] = {}  # id(line) -> {"count", "quote", "kb_fact", "line"}
    for d in runs:
        matched_this_run: set[int] = set()
        for item in d.get("wrong_info") or []:
            if not isinstance(item, dict):
                continue
            line = find_quote(item.get("quote"), lines, ("telecaller",))
            if not line or id(line) in matched_this_run:
                continue
            matched_this_run.add(id(line))
            entry = wrong_seen.setdefault(id(line), {"count": 0, "quote": item.get("quote"), "kb_fact": item.get("kb_fact"), "line": line})
            entry["count"] += 1
    wrong = [
        {"quote": clip(e["quote"]), "time": clock(e["line"].start), "kb_fact": clip(e["kb_fact"])}
        for e in sorted(wrong_seen.values(), key=lambda e: e["line"].start) if e["count"] >= 2
    ]

    lcap, lcap_name = listening_cap_reason(talk_share, ipm_for_caps)

    checks, proof_missing = [], []
    chosen_levels: dict[str, str] = {}
    for base in CHECKS:
        key = base["key"]
        slim = {"key": key, "full": base["full"]}
        if key == "crm_update":
            checks.append({**slim, "level": None, "ai_level": None, "capped_by": None, "marks": None,
                           "reason": None, "quote": None, "time": None, "proof_missing": False})
            continue
        votes = []
        for raw in raw_list:
            item = raw.get(key)
            lv = item.get("level") if isinstance(item, dict) else None
            if lv in LEVEL_ORDER:
                votes.append(lv)
        if len(votes) < 2:
            raise CallMarkingError(f"fewer than 2 valid votes for check {key}")
        level = _majority_level(votes)
        disagreement = len(votes) == 2 and votes[0] != votes[1]
        chosen_levels[key] = level
        source = next(raw[key] for raw in raw_list if isinstance(raw.get(key), dict) and raw[key].get("level") == level)
        cap, cap_name = "excellent", None
        if key == "listening":
            cap, cap_name = lcap, lcap_name
        elif key == "courtesy":
            if rude_line:
                cap, cap_name = "missing", "rude"
            else:
                cap = courtesy_cap(ipm_for_caps)
                cap_name = "interruptions" if cap != "excellent" else None
        elif key == "product_info" and wrong:
            cap, cap_name = "missing", "wrong_info"
        check = apply_level(slim, level, cap, cap_name)
        ok, line = _quote_ok(level, source.get("quote"), lines)
        needs_review = not ok or disagreement
        check.update({
            "reason": clip(source.get("reason")),
            "quote": clip(source.get("quote")) if line else None,
            "time": clock(line.start) if line else None,
            "proof_missing": needs_review,
        })
        if needs_review:
            proof_missing.append(key)
        checks.append(check)

    unverified: list[str] = []
    for raw, d in zip(raw_list, runs):
        item = raw.get("product_info")
        level = item.get("level") if isinstance(item, dict) else None
        if level != chosen_levels.get("product_info"):
            continue
        for c in d.get("unverified_claims") or []:
            if isinstance(c, str):
                cc = clip(c)
                if cc not in unverified:
                    unverified.append(cc)
    unverified = unverified[:10]

    return MarkResult(
        checks=checks,
        rude_quote=f"[{clock(rude_line.start)}] {clip(rude_quote_raw)}" if rude_line else None,
        wrong_info=wrong,
        unverified_claims=unverified,
        proof_missing=proof_missing,
        tips=tips(talk_share, interruptions_per_5min),
        # Display-only, so no vote: the first run whose report survives quote checks.
        report=next((r for r in (build_report(d.get("report"), lines) for d in runs) if r), {}),
    )


# ── Check 10: CRM update, from the telecaller's wrap-up ─────────────────

_CRM_ROW_FIELDS = (
    "id,tenant_id,caller_id,lead_id,provider,call_group,ai_status,created_at,feedback_at,"
    "outcome,manual_status,outcome_reason,preferred_language,next_action_at,notes,transcript,evaluation,score_final"
)

_CRM_PROMPT = """A telecaller just finished this sales call and saved a wrap-up. Mark check 10 (CRM update) and give your own reading of how interested the customer is.

Transcript:
{transcript}

Wrap-up saved:
- did the call connect: {manual_status}
- what happened: {outcome}
- reason: {reason}
- preferred language: {preferred_language}
- next step / follow-up / callback time: {next_action_at}
- do not call: {do_not_call}
- notes: {notes}

Correct status guide:
- Interested, next step booked (hot): interested and a specific next step with a date and time was agreed.
- Interested, needs time or more information (warm): interested but wants time, information or to think it over.
- Maybe later (cold): low interest now, maybe in future.
- Call later (customer asked): the customer asked to be called later; a date and time must be set.
- Converted: the customer bought or booked.
- Not interested: clearly not interested (reason: price, already bought, no need, other).
- Disqualified: never enquired, not a fit, or not the decision maker.
- Wrong number: the person is not the lead.
- Language barrier: they could not understand each other; the customer's language must be set.
- Do not call: the customer asked not to be contacted again.

Levels: "excellent" = status matches the call, the notes cover the key points (need, budget, next step) and the time is set if one was agreed; "good" = status correct, notes thin; "partial" = status slightly off; "poor" = status wrong; "missing" = nothing useful saved.
customer = your own reading of the customer by the guide: "hot", "warm" or "cold"; "none" if they were not a buying prospect on this call (converted, not interested, disqualified, wrong number, language barrier, do not call).
Return JSON only: {{"level": "...", "reason": "one line", "customer": "hot|warm|cold|none"}}"""


EXPECTED_CRM_LABEL = {
    "wrong_number": "Wrong number", "not_enquired": "Never enquired", "callback": "Callback with a date and time",
    "language_barrier": "Language barrier", "voicemail": "Voicemail / IVR", "other": "Other",
}


def _wrapup_label(snap: dict) -> str:
    if snap.get("outcome") in OUTCOME_LABEL:
        return OUTCOME_LABEL[snap["outcome"]]
    if snap.get("manual_status") in CONNECT_LABEL:
        return CONNECT_LABEL[snap["manual_status"]]
    if snap.get("do_not_call"):
        return "Do not call"
    return "Nothing"


def crm_matches_expected(expected: str, wrapup: dict) -> bool | None:
    """Early-exit check 3. None when no wrap-up status fits that situation (voicemail, other)."""
    outcome = wrapup.get("outcome")
    if expected == "wrong_number":
        return outcome == "wrong_number"
    if expected == "not_enquired":
        return outcome == "not_interested" or (outcome == "disqualified" and wrapup.get("reason") == "never_enquired")
    if expected == "callback":
        return outcome == "call_later" and bool(wrapup.get("next_action_at"))
    if expected == "language_barrier":
        return outcome == "language_barrier"
    return None


def _load_row(db, call_log_id: str) -> dict | None:
    res = db.table("call_logs").select(_CRM_ROW_FIELDS).eq("id", call_log_id).maybe_single().execute()
    return res.data if res else None


def wrapup_snapshot(db, row: dict) -> dict | None:
    if not row.get("feedback_at"):
        return None
    dnc = False
    if row.get("lead_id"):
        lead = db.table("leads").select("do_not_call").eq("id", row["lead_id"]).maybe_single().execute()
        dnc = bool(((lead.data if lead else None) or {}).get("do_not_call"))
    return {
        "outcome": row.get("outcome"), "manual_status": row.get("manual_status"), "reason": row.get("outcome_reason"),
        "preferred_language": row.get("preferred_language"), "notes": row.get("notes"),
        "next_action_at": row.get("next_action_at"), "do_not_call": dnc,
    }


def _prompt_values(snap: dict) -> dict:
    return {
        "manual_status": CONNECT_LABEL.get(snap.get("manual_status"), "—"),
        "outcome": OUTCOME_LABEL.get(snap.get("outcome"), "—"),
        "reason": (snap.get("reason") or "—").replace("_", " "),
        "preferred_language": LANGUAGE_LABEL.get(snap.get("preferred_language"), "—"),
        "next_action_at": snap.get("next_action_at") or "—",
        "do_not_call": "yes" if snap.get("do_not_call") else "no",
        "notes": snap.get("notes") or "—",
    }


def _majority_customer(results: list[dict]) -> str:
    votes = [d.get("customer") for d in results if d.get("customer") in AI_CALL_STATUSES]
    if not votes:
        return "none"
    top, count = Counter(votes).most_common(1)[0]
    return top if count >= 2 else "none"


def _temperature_correction(snap: dict | None, customer: str | None) -> dict | None:
    """D10: only the telecaller's Hot/Warm/Cold is corrected, and only by a clear AI majority."""
    chosen = TEMPERATURE_FOR_OUTCOME.get((snap or {}).get("outcome"))
    if chosen and customer in TEMPERATURES and customer != chosen:
        return {"from": chosen, "to": customer}
    return None


def _apply_correction(db, row: dict, correction: dict | None, call_log_id: str) -> None:
    """Guarded, idempotent: a newer wrap-up or a conversion since this call must not be
    overwritten, so the write only lands while the lead still shows the telecaller's value."""
    if not (correction and row.get("lead_id")):
        return
    try:
        (
            db.table("leads").update({"call_status": correction["to"]})
            .eq("id", row["lead_id"]).eq("tenant_id", row["tenant_id"]).eq("call_status", correction["from"])
            .execute()
        )
    except Exception as e:
        logger.error(f"AI status correction failed for call {call_log_id}: {e}")


def _past_cutoff(row: dict, now: datetime) -> bool:
    created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
    return now - created >= timedelta(hours=WRAPUP_CUTOFF_HOURS)


async def mark_crm_update(db, call_log_id: str, *, now: datetime | None = None) -> bool:
    """Mark (or re-mark) check 10 / the early-exit CRM check. Safe to call any time."""
    now = now or datetime.now(timezone.utc)
    row = _load_row(db, call_log_id)
    evaluation = (row or {}).get("evaluation") or {}
    if not row or row.get("ai_status") != "done" or evaluation.get("evaluation_version") != 4:
        return False
    snap = wrapup_snapshot(db, row)
    group = evaluation.get("group")

    if group == "early_exit":
        early = dict(evaluation.get("early_exit_check") or {})
        alert_quote = None
        if snap is None:
            if early.get("crm_matches") is not None or not _past_cutoff(row, now):
                return False
            early["crm_matches"] = False
            early["no_wrapup"] = True
            alert_quote = "No wrap-up saved within 2 hours"
        else:
            if evaluation.get("crm_wrapup") == snap:
                return False
            matches = crm_matches_expected(early.get("expected_crm", "other"), snap)
            early["crm_matches"] = matches
            if matches is False:
                alert_quote = clip(f"The call sounded like: {EXPECTED_CRM_LABEL.get(early.get('expected_crm'), 'Other')}. Wrap-up saved: {_wrapup_label(snap)}.")
        new_eval = {**evaluation, "early_exit_check": early, "crm_wrapup": snap}
        db.table("call_logs").update({"evaluation": new_eval}).eq("id", call_log_id).execute()
        finalize_call_score(db, call_log_id)
        if alert_quote:
            try:
                raise_alert(db, tenant_id=row["tenant_id"], type="crm_mismatch", call_log_id=call_log_id,
                            caller_id=row.get("caller_id"), quote=alert_quote)
            except Exception as e:
                logger.error(f"crm_mismatch alert failed for call {call_log_id}: {e}")
        return True

    checks = [dict(c) for c in evaluation.get("checks") or []]
    if not checks:
        return False
    crm = checks[-1]
    alerts: list[tuple[str, str]] = []  # (type, quote), fired only after the mark is saved and the score finalized
    customer: str | None = None  # the AI's Hot/Warm/Cold reading; None when the AI didn't run
    clear_ai_status = False  # attempt-cap path: the AI reading can no longer be trusted, so wipe it
    if snap is None:
        if crm.get("level") is not None or not _past_cutoff(row, now):
            return False
        crm.update({"level": "missing", "ai_level": None, "marks": 0.0,
                    "reason": f"No wrap-up saved within {WRAPUP_CUTOFF_HOURS} hours of the call."})
    else:
        if evaluation.get("crm_wrapup") == snap and crm.get("level") is not None:
            if not row.get("score_final"):
                finalize_call_score(db, call_log_id)
            # The lead may have drifted back to the telecaller's value since the correction was
            # applied (e.g. a later manual edit); re-apply it so it doesn't silently go stale.
            _apply_correction(db, row, evaluation.get("crm_correction"), call_log_id)
            return False
        attempts = evaluation.get("crm_attempts") or 0
        if attempts >= CRM_AI_ATTEMPT_CAP:
            crm.update({"level": "missing", "ai_level": None, "marks": 0.0,
                        "reason": "The wrap-up couldn't be checked automatically."})
            alerts.append(("no_proof", "Wrap-up check failed 3 times"))
            clear_ai_status = True
        else:
            try:
                prompt = _CRM_PROMPT.format(
                    transcript=format_transcript(parse_transcript(row.get("transcript"))), **_prompt_values(snap),
                )
                results = await _gather_votes((
                    gemini_analysis_json(
                        system_prompt=_SYSTEM, user_prompt=prompt,
                        tenant_id=row.get("tenant_id"), temperature=0.0, purpose="call_crm_check", max_tokens=400,
                    )
                    for _ in range(AI_VOTES)
                ), label="mark_crm_update")
                votes = [d.get("level") for d in results if d.get("level") in LEVEL_ORDER]
                if len(votes) < 2:
                    raise CallMarkingError("no valid level for check crm_update")
                level = _majority_level(votes)
                disagreement = len(votes) == 2 and votes[0] != votes[1]
                source = next(d for d in results if d.get("level") == level)
                customer = _majority_customer(results)
            except Exception:
                db.table("call_logs").update({"evaluation": {**evaluation, "crm_attempts": attempts + 1}}).eq("id", call_log_id).execute()
                raise
            crm.update({"level": level, "ai_level": level, "marks": round(check_marks("crm_update", level), 2),
                        "reason": clip(source.get("reason"))})
            if disagreement:
                alerts.append(("no_proof", "Wrap-up check: the AI votes disagreed"))
            if level in ("poor", "missing"):
                alerts.append(("crm_mismatch", clip(source.get("reason"))))
    correction = _temperature_correction(snap, customer)
    checks[-1] = crm
    new_eval = {**evaluation, "checks": checks, "top_improve": top_improve(checks), "crm_wrapup": snap,
                "crm_correction": correction}
    updates: dict = {"evaluation": new_eval}
    if customer is not None:
        updates["ai_call_status"] = customer
    elif clear_ai_status:
        updates["ai_call_status"] = None
    db.table("call_logs").update(updates).eq("id", call_log_id).execute()
    finalize_call_score(db, call_log_id)
    _apply_correction(db, row, correction, call_log_id)
    for alert_type, quote in alerts:
        try:
            raise_alert(db, tenant_id=row["tenant_id"], type=alert_type, call_log_id=call_log_id,
                        caller_id=row.get("caller_id"), quote=quote)
        except Exception as e:
            logger.error(f"{alert_type} alert failed for call {call_log_id}: {e}")
    return True

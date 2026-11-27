"""Reach audiences: who a campaign will really reach, and what it costs.

Used by three places, so they always agree:
  - POST /upload/reach-preview (the confirm step's numbers),
  - routes/upload.py bulk_send + _execute_immediate_send (Send now),
  - services/broadcast_executor.py (scheduled and drip runs).

Two kinds of audience feed the SAME template pipeline (routes/upload.py bulk_send):
  - an uploaded list (the CSV people the page already sends),
  - a Customers group (resolve_group below: a picked group's members, or a rule group's filters).

Two send-time rules apply to both:
  - blocked people (leads.blocked_at) are skipped and shown as "blocked";
  - the weekly limit: a person who already got the client's number of Reach campaigns (setting
    reach_weekly_limit, default 2, 1-50) in the current IST week (Sunday 00:00 to Saturday 23:59)
    is skipped and shown as "skipped: weekly limit", unless the sender chose "send anyway" for them.
    ONLY Reach campaign sends count: broadcast_recipients rows with send_status 'sent'. Bills,
    order updates, reminders, Auto-Messages, replies and OTP never write those rows.

A skipped person is stored as a broadcast_recipients row with send_status 'opted_out_skip'
(the send_status CHECK has no "skipped" value) and fail_reason 'weekly_limit' or 'blocked'.
The classifier in routes/upload.py reads that fail_reason and counts them as skipped, not
as failed and not as opt-outs.

Phones are compared as digits with the country code (a bare 10-digit number is Indian), so
"+91 98765 43210", "919876543210" and "09876543210" are the same person.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from app.config import settings

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_WEEKLY_LIMIT = 2
MIN_WEEKLY_LIMIT = 1
MAX_WEEKLY_LIMIT = 50
LIMIT_SETTING_KEY = "reach_weekly_limit"   # app_settings row, per tenant
SKIP_WEEKLY = "weekly_limit"
SKIP_MONTHLY = "monthly_limit"             # only READ: older recipient rows carry it
SKIP_BLOCKED = "blocked"
SKIP_REASONS = frozenset({SKIP_WEEKLY, SKIP_MONTHLY, SKIP_BLOCKED})
# A group send is labelled with this in the history's file-name slot (no schema change needed).
GROUP_LABEL_PREFIX = "Group: "

_PAGE = 1000   # PostgREST caps one response at 1000 rows
_CHUNK = 100   # phones per `in.(...)` lookup (each is looked up in two spellings)
# leads.source values that have no WhatsApp number to send a template to.
_NON_WHATSAPP_SOURCES = ("instagram", "facebook", "telegram")
_PHONE_SHAPE = re.compile(r"\+?[\d\s\-().]+")


# ── phones ────────────────────────────────────────────────────────────────────

def phone_key(raw) -> str | None:
    """One form per person: digits with the country code, or None when it is not a phone."""
    text = str(raw or "").strip()
    if not text or not _PHONE_SHAPE.fullmatch(text):
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return digits if 8 <= len(digits) <= 15 else None


def _spellings(keys) -> list[str]:
    """Both ways a phone can be stored ("+9198..." is what Reach writes, bare digits are rarer)."""
    out: list[str] = []
    for k in keys:
        out.extend((f"+{k}", k))
    return out


def _chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _paged(build) -> list[dict]:
    """Every row of a query, paged through PostgREST's 1000-row cap. `build` returns a fresh query."""
    rows: list[dict] = []
    while True:
        page = build().order("id").range(len(rows), len(rows) + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows


# ── the week ─────────────────────────────────────────────────────────────────

def _week_start_ist(now: datetime | None = None) -> datetime:
    ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    sunday = ist - timedelta(days=(ist.weekday() + 1) % 7)
    return sunday.replace(hour=0, minute=0, second=0, microsecond=0)


def week_start_utc(now: datetime | None = None) -> datetime:
    """Midnight at the start of the current IST week (Sunday), as a UTC time."""
    return _week_start_ist(now).astimezone(timezone.utc)


def week_range_ist(now: datetime | None = None) -> tuple[str, str]:
    """("YYYY-MM-DD" Sunday, "YYYY-MM-DD" Saturday) of the current IST week."""
    start = _week_start_ist(now)
    return start.date().isoformat(), (start + timedelta(days=6)).date().isoformat()


def weekly_counts(db, tenant_id: str, keys, *, now: datetime | None = None,
                  exclude_broadcast_id: str | None = None) -> dict[str, int]:
    """phone key -> how many DIFFERENT Reach campaigns sent to that person this IST week.
    `exclude_broadcast_id` leaves out the campaign being run right now (a resumed run must not
    count its own earlier sends against its own people)."""
    since = week_start_utc(now).isoformat()
    seen: dict[str, set[str]] = {}
    for chunk in _chunks(sorted(set(keys))):
        forms = _spellings(chunk)

        def build(forms=forms):
            return (db.table("broadcast_recipients").select("id,phone,broadcast_id")
                    .eq("tenant_id", tenant_id).eq("send_status", "sent")
                    .gte("created_at", since).in_("phone", forms))

        for row in _paged(build):
            key = phone_key(row.get("phone"))
            bid = str(row.get("broadcast_id") or "")
            if key and bid and bid != str(exclude_broadcast_id or ""):
                seen.setdefault(key, set()).add(bid)
    return {k: len(v) for k, v in seen.items()}


def weekly_limit(db, tenant_id: str) -> int:
    """The client's saved weekly number; anything missing, broken or out of range is the default."""
    try:
        rows = (db.table("app_settings").select("value").eq("tenant_id", tenant_id)
                .eq("key", LIMIT_SETTING_KEY).limit(1).execute().data or [])
    except Exception as exc:
        logger.warning("Reach: weekly-limit lookup failed, using %s: %s", DEFAULT_WEEKLY_LIMIT, exc)
        return DEFAULT_WEEKLY_LIMIT
    try:
        value = int(str(rows[0].get("value")).strip()) if rows else DEFAULT_WEEKLY_LIMIT
    except (TypeError, ValueError):
        return DEFAULT_WEEKLY_LIMIT
    return value if MIN_WEEKLY_LIMIT <= value <= MAX_WEEKLY_LIMIT else DEFAULT_WEEKLY_LIMIT


def save_weekly_limit(db, tenant_id: str, value: int) -> int:
    """Save the client's weekly number (1-50). Raises ValueError outside that range."""
    if not isinstance(value, int) or isinstance(value, bool) or not MIN_WEEKLY_LIMIT <= value <= MAX_WEEKLY_LIMIT:
        raise ValueError(f"The weekly limit must be a whole number from {MIN_WEEKLY_LIMIT} to {MAX_WEEKLY_LIMIT}.")
    db.table("app_settings").upsert(
        {"tenant_id": tenant_id, "key": LIMIT_SETTING_KEY, "value": str(value), "is_secret": False},
        on_conflict="tenant_id,key").execute()
    return value


# ── who is blocked, who said stop, who is on a tag opt-out ───────────────────

def _lead_flags(db, tenant_id: str, keys) -> dict[str, dict]:
    """phone key -> the lead's name / blocked_at / opted_out / negative-reply flags (tenant's own, not deleted)."""
    flags: dict[str, dict] = {}
    for chunk in _chunks(sorted(set(keys))):
        forms = _spellings(chunk)

        def build(forms=forms):
            return (db.table("leads").select("id,phone,name,opted_out,blocked_at,broadcast_negative_reply_at")
                    .eq("tenant_id", tenant_id).is_("deleted_at", "null").in_("phone", forms))

        for row in _paged(build):
            key = phone_key(row.get("phone"))
            if key:
                flags[key] = row
    return flags


def _tag_opted_out_keys(db, tenant_id: str, keys, tag_id: str | None) -> set[str]:
    """People who opted out of this broadcast tag (or of every tag). Best effort, like the sender."""
    out: set[str] = set()
    for chunk in _chunks(sorted(set(keys))):
        forms = _spellings(chunk)
        try:
            if tag_id:
                rows = (db.table("lead_tag_opt_outs").select("leads!inner(phone)")
                        .eq("tenant_id", tenant_id).eq("tag_id", tag_id).in_("leads.phone", forms).execute().data or [])
                out.update(k for r in rows if r.get("leads") and (k := phone_key(r["leads"].get("phone"))))
            rows = (db.table("lead_tag_opt_outs").select("leads!inner(phone)")
                    .eq("tenant_id", tenant_id).is_("tag_id", "null").in_("leads.phone", forms).execute().data or [])
            out.update(k for r in rows if r.get("leads") and (k := phone_key(r["leads"].get("phone"))))
        except Exception as exc:
            logger.warning("Reach: tag opt-out lookup failed: %s", exc)
    return out


def send_time_skips(db, tenant_id: str, phones, *, now: datetime | None = None,
                    exclude_broadcast_id: str | None = None,
                    send_anyway=frozenset()) -> tuple[set[str], set[str]]:
    """(blocked keys, over-the-weekly-limit keys) among `phones`. Read ONCE when a campaign starts.
    People in `send_anyway` (phone keys) are never reported as over the limit.

    Fails OPEN: if a lookup errors, a warning is logged and that rule is not applied, so a
    database blip never stops a whole campaign. (A blocked person is still stopped by the central
    guard in services/blocked_guard.py; only the "skipped: blocked" label would be missing.)
    Two campaigns that start at the same moment can each see the old count, so a person could
    end the week with 3; that is accepted."""
    keys = {k for k in (phone_key(p) for p in phones) if k}
    if not keys:
        return set(), set()
    blocked: set[str] = set()
    over: set[str] = set()
    try:
        blocked = {k for k, row in _lead_flags(db, tenant_id, keys).items() if row.get("blocked_at")}
    except Exception as exc:
        logger.warning("Reach: blocked lookup failed, sending without the blocked label: %s", exc)
    try:
        limit = weekly_limit(db, tenant_id)
        counts = weekly_counts(db, tenant_id, keys - blocked, now=now, exclude_broadcast_id=exclude_broadcast_id)
        over = {k for k, n in counts.items() if n >= limit and k not in send_anyway}
    except Exception as exc:
        logger.warning("Reach: weekly-limit lookup failed, sending without the limit: %s", exc)
    return blocked, over


# ── the confirm step ─────────────────────────────────────────────────────────

def cost_for(count: int) -> dict:
    """What Meta charges for `count` marketing messages, before GST. The rate is ONE setting
    (META_MARKETING_RATE_INR in app/config.py); the frontend never hard-codes it."""
    rate = float(settings.meta_marketing_rate_inr)
    return {"rate_inr": rate, "cost_inr": round(max(0, count) * rate, 2)}


def classify_people(db, tenant_id: str, people: list[dict], *, tag_id: str | None = None,
                    include_opted_out: bool = False, exclude_negative_replies: bool = False,
                    now: datetime | None = None) -> dict:
    """Sort people into who will get the campaign and why the rest will not.

    people: [{"phone": raw, "opted_in": bool, "name": optional}]. Each person lands in ONE bucket, checked in this
    order: no_opt_in, said_stop, negative_reply, blocked, over_cap, else will_get. Numbers that are
    not phones are `invalid`; repeated phones count once.
    """
    seen: dict[str, bool] = {}
    names: dict[str, str | None] = {}
    invalid = 0
    for p in people:
        key = phone_key(p.get("phone"))
        if not key:
            invalid += 1
        elif key not in seen:
            seen[key] = bool(p.get("opted_in"))
            names[key] = p.get("name")
    keys = set(seen)
    flags = _lead_flags(db, tenant_id, keys) if keys else {}
    tag_stop = _tag_opted_out_keys(db, tenant_id, keys, tag_id) if keys else set()
    blocked = {k for k in keys if (flags.get(k) or {}).get("blocked_at")}
    limit = weekly_limit(db, tenant_id)
    counts = weekly_counts(db, tenant_id, keys - blocked, now=now) if keys else {}

    out = {"total": len(keys), "invalid": invalid, "no_opt_in": 0, "said_stop": 0,
           "negative_reply": 0, "blocked": 0, "over_cap": 0, "will_get": 0,
           "over_limit_people": [], "weekly_limit": limit}
    for key, opted_in in seen.items():
        lead = flags.get(key) or {}
        if not opted_in:
            out["no_opt_in"] += 1
        elif not include_opted_out and (lead.get("opted_out") or key in tag_stop):
            out["said_stop"] += 1
        elif exclude_negative_replies and lead.get("broadcast_negative_reply_at"):
            out["negative_reply"] += 1
        elif key in blocked:
            out["blocked"] += 1
        elif counts.get(key, 0) >= limit:
            out["over_cap"] += 1
            out["over_limit_people"].append({"phone": key, "name": lead.get("name") or names.get(key) or None,
                                             "this_week": counts[key]})
        else:
            out["will_get"] += 1
    out["over_limit_people"].sort(key=lambda p: (-p["this_week"], p["phone"]))
    return out


def preview_numbers(db, tenant_id: str, people: list[dict], **kwargs) -> dict:
    """classify_people plus the weekly limit, the week, and the Meta cost line for the "will get it" people."""
    out = classify_people(db, tenant_id, people, **kwargs)
    out["week_start"], out["week_end"] = week_range_ist(kwargs.get("now"))
    out.update(cost_for(out["will_get"]))
    return out


# ── a Customers group as an audience ─────────────────────────────────────────

class GroupNotFound(Exception):
    """The group does not exist for this tenant (another tenant's group reads as missing)."""


def resolve_group(db, ctx: dict, group_id: str) -> dict:
    """The people of one Customers group, ready for the Reach pipeline.

    Members come from the SAME code the Customers page uses (routes/leads.py _filtered_leads_query):
    a picked group's members, or a rule group's saved filters (services/group_rules.py).
    Already left out there: deleted leads and WhatsApp-undeliverable numbers.
    Said-stop people (leads.opted_out) are counted but not returned.

    Returns {"group": {id, name, kind}, "members": N, "stopped": N, "no_whatsapp": N,
             "people": [{lead_id, phone, name, source, opt_in_source, opted_in}]}.
    "members" = everyone the Groups table counts (the people plus said-stop plus those with no number).
    """
    from app.routes.leads import LeadFilters, _fetch_all, _filtered_leads_query  # local: routes import services

    tenant_id = ctx["tenant_id"]
    rows = (db.table("customer_groups").select("id,name,kind").eq("id", group_id)
            .eq("tenant_id", tenant_id).limit(1).execute().data or [])
    if not rows:
        raise GroupNotFound(group_id)
    group = rows[0]
    filters = LeadFilters(group_id=str(group["id"]))
    columns = "id,name,phone,source,opt_in_source"
    memo: dict = {}
    live_query = _filtered_leads_query(db, ctx, filters, columns=columns, memo=memo)
    live = _fetch_all(lambda: _filtered_leads_query(db, ctx, filters, columns=columns, memo=memo),
                      order_by=("created_at", "id")) if live_query is not None else []
    stop_query = _filtered_leads_query(db, ctx, filters, columns="id", count="exact", memo=memo, opted_out_only=True)
    stopped = (stop_query.limit(1).execute().count or 0) if stop_query is not None else 0

    people: list[dict] = []
    no_whatsapp = 0
    for lead in live:
        key = phone_key(lead.get("phone"))
        if not key or (lead.get("source") or "") in _NON_WHATSAPP_SOURCES:
            no_whatsapp += 1
            continue
        source = (lead.get("opt_in_source") or "").strip()
        people.append({
            "lead_id": lead["id"], "phone": f"+{key}", "name": lead.get("name"),
            "source": lead.get("source"), "opt_in_source": source,
            "opted_in": bool(source) and source.lower() != "manual",
        })
    return {
        "group": {"id": str(group["id"]), "name": group.get("name") or "", "kind": group.get("kind") or "picked"},
        "members": len(live) + stopped, "stopped": stopped, "no_whatsapp": no_whatsapp, "people": people,
    }

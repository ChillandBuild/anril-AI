"""SMS campaigns through Bulk9: eligibility, preview, create, and the sending worker (migration 237).

One `sms_messages` row per recipient. Status: queued -> sending -> submitted -> delivered | failed,
or queued -> skipped | cancelled. `sending` is the claim (a conditional queued -> sending update, so
two scheduler runs never double-send). A timeout may mean Bulk9 did accept the SMS, so it becomes
`unknown` and is never re-sent; a row stuck in `sending` for 15 minutes becomes `unknown` too.
"""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.config_dynamic import get_setting
from app.services import bulk9_client
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=15)
BATCH_SIZE = 50
MAX_LEADS = 5000
INSERT_CHUNK = 500

# Exact exclusion strings from the API contract.
R_OPTED_OUT = "Opted out"
R_NO_CONSENT = "No SMS consent (promotional template)"
R_NOT_INDIAN = "Not an Indian mobile number"
R_DUPLICATE = "Duplicate number"


def R_MISSING(field: str) -> str:
    return f"Missing value for {field}"


# Lead fields usable as {#var#} values. first_name is derived from name.
FIELDS = [
    {"key": "name", "label": "Name"},
    {"key": "first_name", "label": "First name"},
    {"key": "phone", "label": "Phone"},
]
_FIELD_KEYS = {f["key"] for f in FIELDS}


class SmsError(Exception):
    """A problem the person can act on. `status` is the HTTP code the route should use."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- pure helpers

def normalize_indian_mobile(phone: Any) -> str | None:
    """10-digit mobile starting 6-9, from +91 / 91 / 0 / 0091 prefixed or spaced input; else None."""
    if phone is None:
        return None
    digits = re.sub(r"\D", "", str(phone))
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None


_VAR = re.compile(r"\{#var#\}", re.IGNORECASE)


def var_count(template_text: str) -> int:
    return len(_VAR.findall(template_text or ""))


def render(template_text: str, values: list[str]) -> str:
    """Replace each {#var#} in order. A placeholder with no value left is kept as is."""
    it = iter(values)

    def sub(m: re.Match) -> str:
        return next(it, m.group(0))

    return _VAR.sub(sub, template_text or "")


_GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXT = set("^{}\\[~]|€\f")


def segments(text: str) -> tuple[int, bool]:
    """(SMS parts, is_unicode). GSM-7: 160 single / 153 per part; UCS-2: 70 / 67."""
    text = text or ""
    if all(c in _GSM_BASIC or c in _GSM_EXT for c in text):
        length = sum(2 if c in _GSM_EXT else 1 for c in text)
        if length <= 160:
            return 1, False
        return -(-length // 153), False
    length = len(text.encode("utf-16-le")) // 2  # characters outside the BMP count twice
    if length <= 70:
        return 1, True
    return -(-length // 67), True


def _clean_value(v: Any) -> str:
    # A '|' would shift every later variable (Bulk9 joins them with '|'), so it is dropped.
    return re.sub(r"\s+", " ", str(v or "").replace("|", "")).strip()


def _field_value(lead: dict, key: str) -> str:
    name = _clean_value(lead.get("name"))
    if key == "first_name":
        return name.split(" ")[0] if name else ""
    if key == "name":
        return name
    if key == "phone":
        return normalize_indian_mobile(lead.get("phone")) or _clean_value(lead.get("phone"))
    return ""


def validate_variable_map(variable_map: list[dict], template_text: str) -> list[dict]:
    """One VarSource per {#var#}, in order; field sources must be known lead fields."""
    n = var_count(template_text)
    if len(variable_map or []) != n:
        raise SmsError(f"This template has {n} variable(s); {len(variable_map or [])} given.")
    clean = []
    for v in variable_map:
        source, value = v.get("source"), v.get("value")
        if source == "field":
            if value not in _FIELD_KEYS:
                raise SmsError(f"Unknown lead field: {value}")
        elif source == "text":
            value = _clean_value(value)
            if not value:
                raise SmsError("A fixed-text variable cannot be empty.")
        else:
            raise SmsError("Each variable must be a lead field or fixed text.")
        clean.append({"source": source, "value": value})
    return clean


def eligibility(leads: list[dict], template_type: str, variable_map: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split leads into (eligible, excluded). eligible items: {lead, phone, values}.
    excluded items: {lead_id, name, phone, reason}. Order of checks follows the contract list."""
    eligible: list[dict] = []
    excluded: list[dict] = []
    seen: set[str] = set()

    def out(lead: dict, reason: str) -> None:
        excluded.append({"lead_id": lead.get("id"), "name": lead.get("name"), "phone": lead.get("phone"),
                         "reason": reason})

    for lead in leads:
        if lead.get("opted_out"):
            out(lead, R_OPTED_OUT)
            continue
        if template_type == "promotional" and not (lead.get("sms_consent_at") and str(lead.get("sms_consent_source") or "").strip()):
            out(lead, R_NO_CONSENT)
            continue
        phone = normalize_indian_mobile(lead.get("phone"))
        if not phone:
            out(lead, R_NOT_INDIAN)
            continue
        values, missing = [], None
        for src in variable_map:
            val = _field_value(lead, src["value"]) if src["source"] == "field" else _clean_value(src["value"])
            if not val:
                missing = src["value"]
                break
            values.append(val)
        if missing:
            out(lead, R_MISSING(missing))
            continue
        if phone in seen:
            out(lead, R_DUPLICATE)
            continue
        seen.add(phone)
        eligible.append({"lead": lead, "phone": phone, "values": values})
    return eligible, excluded


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- lead loading

def load_leads(db, tenant_id: str, lead_ids: list[str]) -> list[dict]:
    """The tenant's own, not-deleted leads among `lead_ids`, in the order given."""
    ids = list(dict.fromkeys(str(i) for i in lead_ids))
    if len(ids) > MAX_LEADS:
        raise SmsError(f"Pick at most {MAX_LEADS} leads at a time.")
    found: dict[str, dict] = {}
    for i in range(0, len(ids), 200):
        rows = (
            db.table("leads").select("id,name,phone,opted_out,sms_consent_at,sms_consent_source")
            .eq("tenant_id", tenant_id).is_("deleted_at", "null").in_("id", ids[i:i + 200]).execute()
        ).data or []
        for r in rows:
            found[r["id"]] = r
    return [found[i] for i in ids if i in found]


def get_template(db, tenant_id: str, template_id: str) -> dict:
    rows = (
        db.table("sms_templates").select("*").eq("tenant_id", tenant_id).eq("id", template_id)
        .limit(1).execute()
    ).data or []
    if not rows:
        raise SmsError("Template not found.", 404)
    t = rows[0]
    if t.get("status") != "ready" or not t.get("message_id"):
        raise SmsError("This template is not approved yet, so it can't be sent.", 409)
    if t.get("template_type") not in ("service", "promotional"):
        raise SmsError("Choose a service or promotional classification before sending this template.", 409)
    return t


# ---------------------------------------------------------------- preview + create

def preview(db, tenant_id: str, template: dict, variable_map: list[dict], lead_ids: list[str]) -> dict:
    vmap = validate_variable_map(variable_map, template["message"])
    leads = load_leads(db, tenant_id, lead_ids)
    eligible, excluded = eligibility(leads, template["template_type"], vmap)
    total_parts = 0
    samples = []
    for item in eligible:
        content = render(template["message"], item["values"])
        parts, uni = segments(content)
        total_parts += parts
        if len(samples) < 3:
            samples.append({"lead_id": item["lead"]["id"], "name": item["lead"].get("name"),
                            "content": content, "segments": parts, "unicode": uni})
    rate = rate_per_sms(db, tenant_id)
    return {
        "eligible_count": len(eligible), "excluded": excluded, "samples": samples,
        "total_segments": total_parts,
        "estimated": True,
        # ≈ ₹ from what this client was actually charged lately; None until a charge has been reported.
        "rate_per_sms": float(round(rate, 4)) if rate is not None else None,
        "estimated_amount": float(round(rate * total_parts, 2)) if rate is not None else None,
    }


RATE_SAMPLE = 500  # recent charged messages the ₹ estimate averages over


def rate_per_sms(db, tenant_id: str) -> Decimal | None:
    """The client's own recent charge per SMS part (Bulk9's amount_debited ÷ parts)."""
    rows = (
        db.table("sms_messages").select("sms_count,amount_debited").eq("tenant_id", tenant_id)
        .not_.is_("amount_debited", "null").order("updated_at", desc=True).limit(RATE_SAMPLE).execute()
    ).data or []
    parts = sum(int(r.get("sms_count") or 1) for r in rows)
    amount = sum((Decimal(str(r["amount_debited"])) for r in rows), Decimal(0))
    return amount / parts if parts and amount > 0 else None


def _existing_campaign(db, tenant_id: str, key: str) -> dict | None:
    rows = (
        db.table("sms_campaigns").select("*").eq("tenant_id", tenant_id).eq("idempotency_key", key)
        .limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def create_campaign(db, tenant_id: str, user_id: str | None, *, name: str, template: dict,
                    variable_map: list[dict], lead_ids: list[str], send_at: datetime | None,
                    idempotency_key: str, now: datetime | None = None) -> tuple[dict, bool]:
    """(campaign row, created). The same idempotency_key again returns the first campaign untouched."""
    existing = _existing_campaign(db, tenant_id, idempotency_key)
    if existing:
        return existing, False
    now = now or utcnow()
    if send_at is not None:
        if send_at.tzinfo is None:
            raise SmsError("Pick a date and time.")
        send_at = send_at.astimezone(timezone.utc)
        if send_at <= now:
            raise SmsError("Pick a future date and time.")
    send_at = send_at or now
    vmap = validate_variable_map(variable_map, template["message"])
    leads = load_leads(db, tenant_id, lead_ids)
    eligible, _excluded = eligibility(leads, template["template_type"], vmap)
    if not eligible:
        raise SmsError("None of the selected leads can receive this SMS.")
    try:
        campaign = db.table("sms_campaigns").insert({
            "tenant_id": tenant_id, "name": name.strip()[:120], "template_id": template["id"],
            "sender_id": template["sender_id"], "message_id": str(template["message_id"]),
            "template_type": template["template_type"], "template_text": template["message"],
            "variable_map": vmap, "status": "scheduled", "send_at": send_at.isoformat(),
            "idempotency_key": idempotency_key, "created_by": user_id,
        }).execute().data[0]
    except Exception:
        # A double click can lose the race on the unique (tenant, key) index: hand back the winner.
        existing = _existing_campaign(db, tenant_id, idempotency_key)
        if existing:
            return existing, False
        raise
    rows = []
    for item in eligible:
        content = render(template["message"], item["values"])
        rows.append({
            "tenant_id": tenant_id, "campaign_id": campaign["id"], "lead_id": item["lead"]["id"],
            "phone": item["phone"], "variables": item["values"], "content": content,
            "send_at": send_at.isoformat(), "status": "queued",
        })
    try:
        for i in range(0, len(rows), INSERT_CHUNK):
            db.table("sms_messages").insert(rows[i:i + INSERT_CHUNK]).execute()
    except Exception:
        # Half a campaign must not go out: cancel what was inserted and let the caller retry.
        logger.exception("sms_campaigns: inserting messages for campaign %s failed", campaign["id"])
        db.table("sms_campaigns").update({"status": "cancelled", "cancelled_at": now.isoformat()}) \
            .eq("id", campaign["id"]).execute()
        db.table("sms_messages").update({"status": "cancelled"}) \
            .eq("campaign_id", campaign["id"]).eq("status", "queued").execute()
        raise SmsError("Could not save the campaign. Nothing was sent; please try again.", 500)
    return campaign, True


def cancel_campaign(db, tenant_id: str, campaign_id: str, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rows = (
        db.table("sms_campaigns").update({"status": "cancelled", "cancelled_at": now.isoformat()})
        .eq("id", campaign_id).eq("tenant_id", tenant_id).eq("status", "scheduled").execute()
    ).data or []
    if not rows:
        found = get_campaign_row(db, tenant_id, campaign_id)
        if not found:
            raise SmsError("Campaign not found.", 404)
        raise SmsError("Only a campaign that has not started can be cancelled.", 409)
    db.table("sms_messages").update({"status": "cancelled", "updated_at": now.isoformat()}) \
        .eq("campaign_id", campaign_id).eq("tenant_id", tenant_id).eq("status", "queued").execute()
    return rows[0]


RESCHEDULE_CUTOFF = timedelta(minutes=1)  # closer than this, the scheduler may already be claiming it


def reschedule_campaign(db, tenant_id: str, campaign_id: str, send_at: datetime,
                        now: datetime | None = None) -> dict:
    now = now or utcnow()
    if send_at.tzinfo is None:
        raise SmsError("Pick a date and time.")
    send_at = send_at.astimezone(timezone.utc)
    if send_at <= now:
        raise SmsError("Pick a future date and time.")
    rows = (
        db.table("sms_campaigns").update({"send_at": send_at.isoformat()})
        .eq("id", campaign_id).eq("tenant_id", tenant_id).eq("status", "scheduled").is_("deleted_at", "null")
        .gt("send_at", (now + RESCHEDULE_CUTOFF).isoformat()).execute()
    ).data or []
    if not rows:
        if not get_campaign_row(db, tenant_id, campaign_id):
            raise SmsError("Campaign not found.", 404)
        raise SmsError("Only a scheduled campaign that starts more than a minute from now can be moved.", 409)
    db.table("sms_messages").update({"send_at": send_at.isoformat(), "updated_at": now.isoformat()}) \
        .eq("campaign_id", campaign_id).eq("tenant_id", tenant_id).eq("status", "queued").execute()
    return rows[0]


def delete_campaign(db, tenant_id: str, campaign_id: str, now: datetime | None = None) -> None:
    """Hide a finished or cancelled campaign. Its messages stay: they are what was sent and charged
    (balance history, Reports), and the balance sync would read vanished sends as outside usage."""
    now = now or utcnow()
    rows = (
        db.table("sms_campaigns").update({"deleted_at": now.isoformat()})
        .eq("id", campaign_id).eq("tenant_id", tenant_id).in_("status", ["completed", "cancelled"])
        .is_("deleted_at", "null").execute()
    ).data or []
    if not rows:
        if not get_campaign_row(db, tenant_id, campaign_id):
            raise SmsError("Campaign not found.", 404)
        raise SmsError("Cancel the campaign first. A campaign that is sending can't be deleted.", 409)


# ---------------------------------------------------------------- reading campaigns / messages

STATUSES = ["queued", "sending", "submitted", "delivered", "failed", "unknown", "skipped", "cancelled"]


def get_campaign_row(db, tenant_id: str, campaign_id: str) -> dict | None:
    rows = (
        db.table("sms_campaigns").select("*").eq("tenant_id", tenant_id).eq("id", campaign_id)
        .is_("deleted_at", "null").limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def _counts_for(db, tenant_id: str, campaign_ids: list[str]) -> dict[str, dict]:
    """Per-campaign status counts, SMS parts used and the client's debit. Pages of 1000 (the API's row cap)."""
    out = {cid: {"counts": {s: 0 for s in STATUSES}, "total": 0, "sms_used": 0, "amount": None}
           for cid in campaign_ids}
    if not campaign_ids:
        return out
    start = 0
    while True:
        rows = (
            db.table("sms_messages").select("campaign_id,status,sms_count,amount_debited")
            .eq("tenant_id", tenant_id).in_("campaign_id", campaign_ids).order("id")
            .range(start, start + 999).execute()
        ).data or []
        for r in rows:
            c = out.get(r["campaign_id"])
            if c is None:
                continue
            if r["status"] in c["counts"]:
                c["counts"][r["status"]] += 1
            c["total"] += 1
            c["sms_used"] += int(r.get("sms_count") or 0)
            if r.get("amount_debited") is not None:
                c["amount"] = (c["amount"] or Decimal(0)) + Decimal(str(r["amount_debited"]))
        if len(rows) < 1000:
            return out
        start += 1000


def public_campaigns(db, tenant_id: str, rows: list[dict]) -> list[dict]:
    stats = _counts_for(db, tenant_id, [r["id"] for r in rows])
    result = []
    for r in rows:
        s = stats[r["id"]]
        result.append({
            "id": r["id"], "name": r["name"], "template_text": r["template_text"],
            "sender_id": r["sender_id"], "template_type": r["template_type"], "status": r["status"],
            "send_at": r.get("send_at"), "created_at": r.get("created_at"),
            "completed_at": r.get("completed_at"), "counts": s["counts"], "total": s["total"],
            "sms_used": s["sms_used"],
            # What Bulk9 debited from the client's own wallet so far; None until a charge is reported.
            "amount_debited": float(round(s["amount"], 2)) if s["amount"] is not None else None,
        })
    return result


def public_messages(db, tenant_id: str, rows: list[dict]) -> list[dict]:
    """Client message shape."""
    lead_ids = list({r["lead_id"] for r in rows if r.get("lead_id")})
    names: dict[str, str | None] = {}
    for i in range(0, len(lead_ids), 200):
        for l in (db.table("leads").select("id,name").eq("tenant_id", tenant_id)
                  .in_("id", lead_ids[i:i + 200]).execute()).data or []:
            names[l["id"]] = l.get("name")
    return [{
        "id": r["id"], "campaign_id": r.get("campaign_id"), "lead_id": r.get("lead_id"),
        "lead_name": names.get(r.get("lead_id")), "phone": r["phone"], "content": r["content"],
        "status": r["status"], "failure_reason": r.get("failure_reason"), "sms_count": r.get("sms_count"),
        "submitted_at": r.get("submitted_at"),
        "delivered_at": r.get("delivered_at"), "updated_at": r.get("updated_at"),
    } for r in rows]


# ---------------------------------------------------------------- the sending worker

def _find_number(obj: Any, names: tuple[str, ...]) -> float | None:
    """First numeric value stored under any of `names`, searched through nested dicts / lists.
    The sms_details response shape is undocumented, so this is deliberately forgiving."""
    if isinstance(obj, dict):
        for n in names:
            if n in obj and _num(obj[n]) is not None:
                return _num(obj[n])
        for v in obj.values():
            found = _find_number(v, names)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_number(v, names)
            if found is not None:
                return found
    return None


def parse_send_result(body: dict, row_id: str) -> dict:
    """Request ID and SMS count from a send response."""
    request_id = body.get("request_id")
    if not request_id and body.get("dry_run"):
        # The local outbound guard answers with a fake body: record a visibly fake id.
        request_id = f"dry-run-{row_id}"
    count = _find_number(body, ("sms_count", "sms_used", "total_sms"))
    return {"request_id": str(request_id) if request_id else None,
            "sms_count": int(count) if count is not None else None}


def _tenant_ctx(db, tenant_id: str, cache: dict) -> dict:
    if tenant_id not in cache:
        t = (db.table("tenants").select("enabled_features").eq("id", tenant_id).limit(1).execute()).data or []
        features = (t[0].get("enabled_features") if t else None) or []
        cache[tenant_id] = {
            "enabled": "sms" in features,
            "key": get_setting("bulk9_api_key", tenant_id=tenant_id),
        }
    return cache[tenant_id]


def _finish(db, row_id: str, patch: dict) -> None:
    """Record the outcome. Conditional on status=sending so a recovery sweep is never overwritten."""
    patch = {**patch, "updated_at": utcnow().isoformat()}
    try:
        db.table("sms_messages").update(patch).eq("id", row_id).eq("status", "sending").execute()
    except Exception:
        # The row stays `sending` and becomes `unknown` after 15 minutes: never re-sent.
        logger.exception("sms_campaigns: could not record outcome for message %s", row_id)


def _complete_if_done(db, campaign_id: str, now: datetime) -> None:
    left = (
        db.table("sms_messages").select("id").eq("campaign_id", campaign_id)
        .in_("status", ["queued", "sending"]).limit(1).execute()
    ).data or []
    if not left:
        db.table("sms_campaigns").update({"status": "completed", "completed_at": now.isoformat()}) \
            .eq("id", campaign_id).eq("status", "sending").execute()


async def _send_one(db, row: dict, campaign: dict | None, tctx: dict) -> None:
    rid = row["id"]
    skip = None
    if campaign is None or campaign.get("status") == "cancelled":
        skip, status = "The campaign was cancelled.", "cancelled"
    else:
        status = "skipped"
        if not tctx["enabled"]:
            skip = "SMS is not enabled for this account."
        elif not tctx["key"]:
            skip = "SMS is not connected."
        else:
            lead = None
            if row.get("lead_id"):
                lead = ((db.table("leads").select("id,opted_out,deleted_at,sms_consent_at,sms_consent_source").eq("tenant_id", row["tenant_id"])
                         .eq("id", row["lead_id"]).limit(1).execute()).data or [None])[0]
            if not lead or lead.get("deleted_at"):
                skip = "The lead was removed."
            elif lead.get("opted_out"):
                skip = "The customer opted out."
            elif campaign.get("template_type") == "promotional" and not (lead.get("sms_consent_at") and str(lead.get("sms_consent_source") or "").strip()):
                skip = R_NO_CONSENT
    if skip:
        _finish(db, rid, {"status": status, "failure_reason": skip})
        return
    try:
        body = await bulk9_client.send_dlt(
            tctx["key"], sender_id=campaign["sender_id"], message_id=campaign["message_id"],
            numbers=[row["phone"]], variables=list(row.get("variables") or []), udf1=rid,
        )
    except Bulk9Timeout:
        _finish(db, rid, {"status": "unknown",
                          "failure_reason": "No answer from the SMS provider; checking the delivery report."})
        return
    except Bulk9Error as e:
        _finish(db, rid, {"status": "unknown" if e.http_status and e.http_status >= 500 else "failed",
                          "failure_reason": str(e)[:300]})
        return
    except ValueError as e:  # refused before anything was sent
        _finish(db, rid, {"status": "failed", "failure_reason": str(e)[:300]})
        return
    except Exception:
        # Anything else after the request left is ambiguous: never re-send.
        logger.exception("sms_campaigns: send crashed for message %s", rid)
        _finish(db, rid, {"status": "unknown", "failure_reason": "Something went wrong while sending."})
        return
    res = parse_send_result(body if isinstance(body, dict) else {}, rid)
    if not res["request_id"]:
        _finish(db, rid, {"status": "unknown", "failure_reason": "No request ID from the SMS provider; checking delivery logs."})
        return
    patch: dict = {"status": "submitted", "request_id": res["request_id"],
                   "submitted_at": utcnow().isoformat()}
    if res["sms_count"] is not None:
        patch["sms_count"] = res["sms_count"]
    _finish(db, rid, patch)


async def process_due_sms(db=None, now: datetime | None = None, batch_size: int = BATCH_SIZE) -> dict:
    """Scheduler job: send every queued SMS whose time has come. Returns {"claimed": n}.
    Safe to run concurrently: rows are claimed with a conditional queued -> sending update."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    now = now or utcnow()
    touched: set[str] = set()

    stuck = (
        db.table("sms_messages")
        .update({"status": "unknown", "failure_reason": "Sending was interrupted; checking the delivery report.",
                 "updated_at": now.isoformat()})
        .eq("status", "sending").lt("claimed_at", (now - STUCK_AFTER).isoformat()).execute()
    ).data or []
    touched.update(r["campaign_id"] for r in stuck if r.get("campaign_id"))

    claimed_total = 0
    cache: dict = {}
    while True:
        due = (
            db.table("sms_messages").select("id").eq("status", "queued").lte("send_at", now.isoformat())
            .order("send_at").limit(batch_size).execute()
        ).data or []
        if not due:
            break
        claimed = (
            db.table("sms_messages").update({"status": "sending", "claimed_at": now.isoformat()})
            .in_("id", [r["id"] for r in due]).eq("status", "queued").execute()
        ).data or []
        if not claimed:
            break  # another run took them all
        claimed_total += len(claimed)
        cids = list({r["campaign_id"] for r in claimed if r.get("campaign_id")})
        if cids:
            db.table("sms_campaigns").update({"status": "sending", "completed_at": None}) \
                .in_("id", cids).in_("status", ["scheduled", "completed"]).execute()
        camps = {c["id"]: c for c in ((db.table("sms_campaigns").select("*").in_("id", cids).execute()).data or [])} \
            if cids else {}
        for row in claimed:
            touched.add(row.get("campaign_id"))
            await _send_one(db, row, camps.get(row.get("campaign_id")), _tenant_ctx(db, row["tenant_id"], cache))
        if len(due) < batch_size:
            break

    for cid in touched:
        if cid:
            _complete_if_done(db, cid, now)
    return {"claimed": claimed_total}

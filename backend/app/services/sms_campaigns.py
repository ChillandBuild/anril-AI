"""SMS campaigns through Bulk9: eligibility, preview, create, and the sending worker (migration 237).

One `sms_messages` row per recipient. Status: queued -> sending -> submitted -> delivered | failed,
or queued -> skipped | cancelled. `sending` is the claim (a conditional queued -> sending update, so
two scheduler runs never double-send). A timeout may mean Bulk9 did accept the SMS, so it becomes
`unknown` and is never re-sent; a row stuck in `sending` for 15 minutes becomes `unknown` too.
"""
import logging
import re
import uuid
from dataclasses import dataclass, field
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
MAX_CONTACTS = 50_000
MAX_NUMBERS = 5000
MAX_GROUPS = 50
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


COL_PREFIX = "col:"  # a variable filled from an extra upload column of an SMS contact


def _field_value(person: dict, key: str) -> str:
    name = _clean_value(person.get("name"))
    if key == "first_name":
        return name.split(" ")[0] if name else ""
    if key == "name":
        return name
    if key == "phone":
        return normalize_indian_mobile(person.get("phone")) or _clean_value(person.get("phone"))
    if key.startswith(COL_PREFIX):
        return _clean_value((person.get("fields") or {}).get(key[len(COL_PREFIX):]))
    return ""


def validate_variable_map(variable_map: list[dict], template_text: str, allow_cols: bool = False) -> list[dict]:
    """One VarSource per {#var#}, in order; field sources must be known fields (extra contact
    columns only when the recipients are SMS contacts)."""
    n = var_count(template_text)
    if len(variable_map or []) != n:
        raise SmsError(f"This template has {n} variable(s); {len(variable_map or [])} given.")
    clean = []
    for v in variable_map:
        source, value = v.get("source"), v.get("value")
        if source == "field":
            is_col = allow_cols and isinstance(value, str) and value.startswith(COL_PREFIX) \
                and len(value) > len(COL_PREFIX)
            if value not in _FIELD_KEYS and not is_col:
                raise SmsError(f"Unknown field: {value}")
        elif source == "text":
            value = _clean_value(value)
            if not value:
                raise SmsError("A fixed-text variable cannot be empty.")
        else:
            raise SmsError("Each variable must be a field or fixed text.")
        clean.append({"source": source, "value": value})
    return clean


# A recipient ("person") whatever the source: {lead_id?, contact_id?, name, phone, fields,
# opted_out, consent}. consent = may get promotional SMS.

def _lead_person(lead: dict) -> dict:
    return {"lead_id": lead.get("id"), "name": lead.get("name"), "phone": lead.get("phone"),
            "opted_out": bool(lead.get("opted_out")),
            "consent": bool(lead.get("sms_consent_at") and str(lead.get("sms_consent_source") or "").strip())}


def _contact_person(c: dict) -> dict:
    return {"contact_id": c.get("id"), "name": c.get("name"), "phone": c.get("phone"),
            "fields": c.get("fields") or {}, "opted_out": False, "consent": bool(c.get("promo_consent_at"))}


def split_people(people: list[dict], template_type: str, variable_map: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split recipients into (eligible, excluded). eligible items: {person, phone, values}.
    excluded items: {lead_id, contact_id, name, phone, reason}. Order of checks follows the contract list."""
    eligible: list[dict] = []
    excluded: list[dict] = []
    seen: set[str] = set()

    def out(p: dict, reason: str) -> None:
        excluded.append({"lead_id": p.get("lead_id"), "contact_id": p.get("contact_id"), "name": p.get("name"),
                         "phone": p.get("phone"), "reason": reason})

    for p in people:
        if p.get("opted_out"):
            out(p, R_OPTED_OUT)
            continue
        if template_type == "promotional" and not p.get("consent"):
            out(p, R_NO_CONSENT)
            continue
        phone = normalize_indian_mobile(p.get("phone"))
        if not phone:
            out(p, R_NOT_INDIAN)
            continue
        values, missing = [], None
        for src in variable_map:
            val = _field_value(p, src["value"]) if src["source"] == "field" else _clean_value(src["value"])
            if not val:
                missing = src["value"]
                break
            values.append(val)
        if missing:
            out(p, R_MISSING(missing))
            continue
        if phone in seen:
            out(p, R_DUPLICATE)
            continue
        seen.add(phone)
        eligible.append({"person": p, "phone": phone, "values": values})
    return eligible, excluded


def eligibility(leads: list[dict], template_type: str, variable_map: list[dict]) -> tuple[list[dict], list[dict]]:
    return split_people([_lead_person(l) for l in leads], template_type, variable_map)


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- recipients

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


def load_contacts(db, tenant_id: str, group_ids: list[str]) -> list[dict]:
    """The tenant's SMS contacts in any of `group_ids` (each contact once). Pages of 1000."""
    gids = list(dict.fromkeys(str(g) for g in group_ids))
    if not gids:
        raise SmsError("Pick at least one group.")
    if len(gids) > MAX_GROUPS:
        raise SmsError(f"Pick at most {MAX_GROUPS} groups.")
    known = (db.table("sms_contact_groups").select("id").eq("tenant_id", tenant_id).in_("id", gids)
             .execute()).data or []
    if len(known) != len(gids):
        raise SmsError("Group not found.", 404)
    out: list[dict] = []
    start = 0
    while True:
        rows = (
            db.table("sms_contacts").select("id,name,phone,fields,promo_consent_at")
            .eq("tenant_id", tenant_id).ov("group_ids", gids).order("id").range(start, start + 999).execute()
        ).data or []
        out.extend(rows)
        if len(out) > MAX_CONTACTS:
            raise SmsError(f"These groups have more than {MAX_CONTACTS:,} numbers. Pick fewer groups.")
        if len(rows) < 1000:
            return out
        start += 1000


def load_people(db, tenant_id: str, audience: "Audience") -> list[dict]:
    if audience.source == "contacts":
        return [_contact_person(c) for c in load_contacts(db, tenant_id, audience.group_ids)]
    if audience.source == "numbers":
        nums = [str(n).strip() for n in audience.numbers if str(n).strip()]
        if not nums:
            raise SmsError("Paste at least one number.")
        if len(nums) > MAX_NUMBERS:
            raise SmsError(f"Paste at most {MAX_NUMBERS:,} numbers at a time.")
        return [{"name": None, "phone": n, "opted_out": False, "consent": audience.consent_confirmed}
                for n in nums]
    return [_lead_person(l) for l in load_leads(db, tenant_id, audience.lead_ids)]


@dataclass
class Audience:
    """Who a campaign goes to. source: leads (lead_ids) | contacts (group_ids) | numbers (pasted)."""
    source: str = "leads"
    lead_ids: list[str] = field(default_factory=list)
    group_ids: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    consent_confirmed: bool = False


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


def manual_template(*, sender_id: str, entity_id: str, dlt_template_id: str, template_type: str,
                    message: str) -> dict:
    """A template-shaped dict for a raw-DLT-ID send (kind=manual). The message is the exact text."""
    if template_type not in ("service", "promotional"):
        raise SmsError("Choose service or promotional.")
    if var_count(message):
        raise SmsError("Replace each {#var#} with the exact text to send.")
    if not message.strip():
        raise SmsError("Type the message.")
    return {"id": None, "kind": "manual", "sender_id": sender_id.upper(), "message": message,
            "template_type": template_type, "message_id": None, "entity_id": entity_id,
            "dlt_template_id": dlt_template_id}
# ---------------------------------------------------------------- preview + create

EXCLUDED_SHOWN = 1000


def _plan(db, tenant_id: str, template: dict, variable_map: list[dict], audience: "Audience"):
    """(clean variable map, eligible, excluded) for this template + audience."""
    if template.get("kind") == "manual" and variable_map:
        raise SmsError("A message sent with DLT IDs has no variables.")
    vmap = validate_variable_map(variable_map, template["message"], allow_cols=audience.source == "contacts")
    eligible, excluded = split_people(load_people(db, tenant_id, audience), template["template_type"], vmap)
    return vmap, eligible, excluded


def preview(db, tenant_id: str, template: dict, variable_map: list[dict], lead_ids: list[str] | None = None,
            *, audience: "Audience | None" = None) -> dict:
    audience = audience or Audience(lead_ids=list(lead_ids or []))
    _vmap, eligible, excluded = _plan(db, tenant_id, template, variable_map, audience)
    total_parts = 0
    samples = []
    for item in eligible:
        content = render(template["message"], item["values"])
        parts, uni = segments(content)
        total_parts += parts
        if len(samples) < 3:
            p = item["person"]
            samples.append({"lead_id": p.get("lead_id"), "contact_id": p.get("contact_id"), "name": p.get("name"),
                            "content": content, "segments": parts, "unicode": uni})
    rate = rate_per_sms(db, tenant_id)
    return {
        "eligible_count": len(eligible), "excluded": excluded[:EXCLUDED_SHOWN], "excluded_total": len(excluded),
        "samples": samples, "total_segments": total_parts,
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


def _message_rows(tenant_id: str, campaign_id: str, template_text: str, eligible: list[dict], send_at: str) -> list[dict]:
    return [{
        "tenant_id": tenant_id, "campaign_id": campaign_id, "lead_id": item["person"].get("lead_id"),
        "contact_id": item["person"].get("contact_id"), "phone": item["phone"], "variables": item["values"],
        "content": render(template_text, item["values"]), "send_at": send_at, "status": "queued",
    } for item in eligible]


def create_campaign(db, tenant_id: str, user_id: str | None, *, name: str, template: dict,
                    variable_map: list[dict], lead_ids: list[str] | None = None, send_at: datetime | None,
                    idempotency_key: str, now: datetime | None = None,
                    audience: "Audience | None" = None) -> tuple[dict, bool]:
    """(campaign row, created). The same idempotency_key again returns the first campaign untouched.
    Leads and pasted numbers (≤5,000) get their messages now; a contacts campaign (≤50,000) is saved
    as `preparing` and the sms-send job builds its messages (build_preparing)."""
    existing = _existing_campaign(db, tenant_id, idempotency_key)
    if existing:
        return existing, False
    audience = audience or Audience(lead_ids=list(lead_ids or []))
    now = now or utcnow()
    if send_at is not None:
        if send_at.tzinfo is None:
            raise SmsError("Pick a date and time.")
        send_at = send_at.astimezone(timezone.utc)
        if send_at <= now:
            raise SmsError("Pick a future date and time.")
    send_at = send_at or now
    if audience.source == "numbers" and template["template_type"] == "promotional" and not audience.consent_confirmed:
        raise SmsError("Confirm that everyone on this list agreed to get promotional SMS.")
    vmap, eligible, _excluded = _plan(db, tenant_id, template, variable_map, audience)
    if not eligible:
        raise SmsError("None of the selected recipients can receive this SMS.")
    manual = template.get("kind") == "manual"
    background = audience.source == "contacts"
    try:
        campaign = db.table("sms_campaigns").insert({
            "tenant_id": tenant_id, "name": name.strip()[:120], "template_id": template.get("id"),
            "sender_id": template["sender_id"],
            "message_id": None if manual else str(template["message_id"]),
            "kind": "manual" if manual else "template",
            "manual_entity_id": template.get("entity_id") if manual else None,
            "manual_template_id": template.get("dlt_template_id") if manual else None,
            "template_type": template["template_type"], "template_text": template["message"],
            "variable_map": vmap, "status": "preparing" if background else "scheduled",
            "source": audience.source, "group_ids": audience.group_ids or None,
            "consent_source": f"confirmed by {user_id or 'unknown'} at {now.isoformat()}"
            if audience.source == "numbers" and audience.consent_confirmed else None,
            "send_at": send_at.isoformat(), "idempotency_key": idempotency_key, "created_by": user_id,
        }).execute().data[0]
    except Exception:
        # A double click can lose the race on the unique (tenant, key) index: hand back the winner.
        existing = _existing_campaign(db, tenant_id, idempotency_key)
        if existing:
            return existing, False
        raise
    if background:
        return campaign, True
    rows = _message_rows(tenant_id, campaign["id"], template["message"], eligible, send_at.isoformat())
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


# ---------------------------------------------------------------- building a contacts campaign

# Messages of a campaign still being built wait at this send_at, so the sender never picks them up.
HOLD = "9999-12-31T00:00:00+00:00"
BUILD_STALE = timedelta(minutes=10)  # a build claimed this long ago crashed: rebuild it
BUILD_GIVE_UP = timedelta(hours=1)   # still failing an hour after creation: stop and say so


def _campaign_template(c: dict) -> dict:
    return {"kind": c.get("kind") or "template", "message": c["template_text"], "template_type": c["template_type"]}


def _drop_unsent(db, campaign_id: str) -> None:
    db.table("sms_messages").delete().eq("campaign_id", campaign_id).in_("status", ["queued", "sending"]).execute()


def build_one(db, campaign: dict, now: datetime) -> str:
    """Insert a preparing campaign's messages, then release them. Returns what happened."""
    cid, tid = campaign["id"], campaign["tenant_id"]
    # A rebuild after a crash: drop the half-built messages. None was sent: the sender never sends
    # for a preparing campaign.
    _drop_unsent(db, cid)
    try:
        _vmap, eligible, _ = _plan(db, tid, _campaign_template(campaign), campaign.get("variable_map") or [],
                                   Audience(source="contacts", group_ids=list(campaign.get("group_ids") or [])))
    except SmsError as e:
        eligible, reason = [], str(e)
    else:
        reason = "None of the contacts in these groups can receive this SMS."
    if not eligible:
        db.table("sms_campaigns").update({"status": "cancelled", "cancelled_at": now.isoformat(),
                                          "build_error": reason}).eq("id", cid).eq("status", "preparing").execute()
        return "empty"
    rows = _message_rows(tid, cid, campaign["template_text"], eligible, HOLD)
    for i in range(0, len(rows), INSERT_CHUNK):
        db.table("sms_messages").insert(rows[i:i + INSERT_CHUNK]).execute()
    # Release the messages first, then the campaign: if this dies in between, the sender puts any
    # message it claims back on hold (the campaign still says preparing) and the build reruns.
    db.table("sms_messages").update({"send_at": campaign["send_at"]}) \
        .eq("campaign_id", cid).eq("status", "queued").eq("send_at", HOLD).execute()
    done = (db.table("sms_campaigns").update({"status": "scheduled", "build_error": None})
            .eq("id", cid).eq("status", "preparing").execute()).data or []
    if not done:  # cancelled while building
        db.table("sms_messages").update({"status": "cancelled", "updated_at": now.isoformat()}) \
            .eq("campaign_id", cid).eq("status", "queued").execute()
        return "cancelled"
    return "built"


def build_preparing(db, now: datetime) -> int:
    """Build every preparing campaign this run can claim. Returns how many were built."""
    built = 0
    waiting = (db.table("sms_campaigns").select("*").eq("status", "preparing").is_("deleted_at", "null")
               .order("created_at").limit(5).execute()).data or []
    for c in waiting:
        created = _parse_ts(c.get("created_at"))
        if created and now - created > BUILD_GIVE_UP:
            db.table("sms_campaigns").update({
                "status": "cancelled", "cancelled_at": now.isoformat(),
                "build_error": "This campaign couldn't be prepared. Nothing was sent; please create it again.",
            }).eq("id", c["id"]).eq("status", "preparing").execute()
            _drop_unsent(db, c["id"])
            continue
        claim = (db.table("sms_campaigns").update({"build_started_at": now.isoformat()})
                 .eq("id", c["id"]).eq("status", "preparing")
                 .or_(f"build_started_at.is.null,build_started_at.lt.{(now - BUILD_STALE).isoformat()}")
                 .execute()).data or []
        if not claim:
            continue  # another run is building it
        try:
            if build_one(db, claim[0], now) == "built":
                built += 1
        except Exception:
            logger.exception("sms_campaigns: building campaign %s failed", c["id"])
            # Let the next run try again from scratch.
            db.table("sms_campaigns").update({"build_started_at": None,
                                              "build_error": "Still preparing: retrying."}) \
                .eq("id", c["id"]).eq("status", "preparing").execute()
    return built


def _parse_ts(v: Any) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def cancel_campaign(db, tenant_id: str, campaign_id: str, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rows = (
        db.table("sms_campaigns").update({"status": "cancelled", "cancelled_at": now.isoformat()})
        .eq("id", campaign_id).eq("tenant_id", tenant_id).in_("status", ["scheduled", "preparing"]).execute()
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
            "sms_used": s["sms_used"], "kind": r.get("kind") or "template", "source": r.get("source") or "leads",
            "build_error": r.get("build_error"),
            # What Bulk9 debited from the client's own wallet so far; None until a charge is reported.
            "amount_debited": float(round(s["amount"], 2)) if s["amount"] is not None else None,
        })
    return result


def public_messages(db, tenant_id: str, rows: list[dict]) -> list[dict]:
    """Client message shape."""
    names: dict[str, str | None] = {}
    for table, col in (("leads", "lead_id"), ("sms_contacts", "contact_id")):
        ids = list({r[col] for r in rows if r.get(col)})
        for i in range(0, len(ids), 200):
            for x in (db.table(table).select("id,name").eq("tenant_id", tenant_id)
                      .in_("id", ids[i:i + 200]).execute()).data or []:
                names[x["id"]] = x.get("name")
    return [{
        "id": r["id"], "campaign_id": r.get("campaign_id"), "lead_id": r.get("lead_id"),
        "contact_id": r.get("contact_id"),
        # The recipient's name, from the lead or the SMS contact.
        "lead_name": names.get(r.get("lead_id") or r.get("contact_id")), "phone": r["phone"], "content": r["content"],
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


def _recipient_skip(db, row: dict, campaign: dict) -> str | None:
    """Why this recipient must not get the SMS any more, or None. Checked at send time because a
    lead or contact can change after the campaign was created."""
    source = campaign.get("source") or "leads"
    promotional = campaign.get("template_type") == "promotional"
    if source == "numbers":
        return None  # consent was confirmed for the whole pasted list
    if source == "contacts":
        contact = None
        if row.get("contact_id"):
            contact = ((db.table("sms_contacts").select("id,promo_consent_at").eq("tenant_id", row["tenant_id"])
                        .eq("id", row["contact_id"]).limit(1).execute()).data or [None])[0]
        if not contact:
            return "The contact was removed."
        if promotional and not contact.get("promo_consent_at"):
            return R_NO_CONSENT
        return None
    lead = None
    if row.get("lead_id"):
        lead = ((db.table("leads").select("id,opted_out,deleted_at,sms_consent_at,sms_consent_source").eq("tenant_id", row["tenant_id"])
                 .eq("id", row["lead_id"]).limit(1).execute()).data or [None])[0]
    if not lead or lead.get("deleted_at"):
        return "The lead was removed."
    if lead.get("opted_out"):
        return "The customer opted out."
    if promotional and not _lead_person(lead)["consent"]:
        return R_NO_CONSENT
    return None


async def _send_one(db, row: dict, campaign: dict | None, tctx: dict) -> None:
    rid = row["id"]
    skip = None
    if campaign is not None and campaign.get("status") == "preparing":
        # Still being built (a crashed build, or a race with another run): back on hold, unsent.
        db.table("sms_messages").update({"status": "queued", "claimed_at": None, "send_at": HOLD}) \
            .eq("id", rid).eq("status", "sending").execute()
        return
    if campaign is None or campaign.get("status") == "cancelled":
        skip, status = "The campaign was cancelled.", "cancelled"
    else:
        status = "skipped"
        if not tctx["enabled"]:
            skip = "SMS is not enabled for this account."
        elif not tctx["key"]:
            skip = "SMS is not connected."
        else:
            skip = _recipient_skip(db, row, campaign)
    if skip:
        _finish(db, rid, {"status": status, "failure_reason": skip})
        return
    try:
        if campaign.get("kind") == "manual":
            body = await bulk9_client.send_dlt_manual(
                tctx["key"], sender_id=campaign["sender_id"], entity_id=campaign["manual_entity_id"],
                template_id=campaign["manual_template_id"], message=row["content"], numbers=[row["phone"]],
                udf1=rid,
            )
        else:
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

    try:
        build_preparing(db, now)
    except Exception:
        # Building must never stop sending.
        logger.exception("sms_campaigns: building preparing campaigns failed")

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

"""v9.2 #26 Come-back offer: a WhatsApp offer to customers who bought before and have not bought for 60 days.

OFF by default. Who gets it: has a won order, last one 60+ days ago, not on Said stop (or blocked, "don't call",
undeliverable), not an unhappy customer (3 stars or fewer), and nobody gets more than 1 offer in 30 days
(comeback_offer_sends is the record). The owner picks an approved template and sets the offer, code and end
date. Goes out 10 AM to 8 PM IST only, at most MAX_PER_BUSINESS_PER_RUN a run.

The planner schedules send_comeback_offers(db) (once a day, late morning IST)."""
import logging
import re
from datetime import date, datetime, timedelta, timezone

import httpx

from app.services.automation_store import (
    read_setting, settings_rows, template_status_of, write_setting,
)
from app.services.evening_summary import _paged, _run

logger = logging.getLogger(__name__)

SETTING_KEY = "comeback_offer"
QUIET_AFTER_PURCHASE = timedelta(days=60)
ONE_OFFER_PER = timedelta(days=30)
RETRY_AFTER_FAILED = timedelta(days=7)      # a failed attempt blocks the lead this long, so bad numbers cannot starve the cap
SEND_HOURS_IST = (10, 20)
MAX_PER_BUSINESS_PER_RUN = 100
UNHAPPY_MAX_STARS = 3
COST_NOTE = "about ₹0.86 a message"
OFFER_MAX = 200
IST = timezone(timedelta(hours=5, minutes=30))
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,30}$")


def _today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(IST).date()


def get_settings(db, tenant_id: str) -> dict:
    s = read_setting(db, tenant_id, SETTING_KEY)
    name = s.get("template_name") or None
    status = template_status_of(db, tenant_id, name) if name else None
    return {
        "on": bool(s.get("on")),
        "template_name": name,
        "template_status": status,
        "offer": s.get("offer") or "",
        "code": s.get("code") or "",
        "ends_on": s.get("ends_on") or None,
        "cost_note": COST_NOTE,
        "rules": "Customers who bought before, 60 days with no purchase, not unhappy, not on Said stop. "
                 "At most 1 offer a month per person.",
        "waiting_for_approval": bool(name) and status != "APPROVED",
    }


def approved_templates(db, tenant_id: str) -> list[dict]:
    """Templates the owner can pick: approved, text only. [{name, body_text, language}]"""
    from app.services.call_details_share import _approved_templates
    try:
        rows = _approved_templates(db, tenant_id)
    except Exception as e:
        logger.warning(f"comeback: templates not read for {tenant_id}: {e}")
        return []
    return [{"name": t["name"], "body_text": t.get("body_text") or "", "language": t.get("language") or "en"} for t in rows]


def save_settings(db, tenant_id: str, *, on: bool, template_name: str | None, offer: str, code: str,
                  ends_on: str | None, now: datetime | None = None) -> dict:
    """Save the owner's choices. Raises ValueError with a plain sentence when something is not right."""
    offer = " ".join((offer or "").split())
    if len(offer) > OFFER_MAX:
        raise ValueError(f"Keep the offer under {OFFER_MAX} letters.")
    code = (code or "").strip()
    if code and not _CODE_RE.match(code):
        raise ValueError("The code can use letters, numbers, - and _ only (30 at most).")
    ends = None
    if ends_on:
        try:
            ends = date.fromisoformat(ends_on)
        except ValueError:
            raise ValueError("Pick the end date again.")
    name = (template_name or "").strip() or None
    if on:
        if not name:
            raise ValueError("Pick an approved message first.")
        if template_status_of(db, tenant_id, name) != "APPROVED":
            raise ValueError("That message is not approved by WhatsApp yet. Pick an approved one.")
        if not offer:
            raise ValueError("Write the offer first, for example: 10% off your next order.")
        if ends and ends < _today_ist(now):
            raise ValueError("The end date has already passed.")
    s = read_setting(db, tenant_id, SETTING_KEY)
    s.update({"on": bool(on), "template_name": name, "offer": offer, "code": code,
              "ends_on": ends.isoformat() if ends else None})
    write_setting(db, tenant_id, SETTING_KEY, s)
    return get_settings(db, tenant_id)


def set_on(db, tenant_id: str, on: bool) -> dict:
    s = read_setting(db, tenant_id, SETTING_KEY)
    return save_settings(db, tenant_id, on=on, template_name=s.get("template_name"), offer=s.get("offer") or "",
                         code=s.get("code") or "", ends_on=s.get("ends_on"))


# ───────────────────────────────────────────────────────────── who gets it

def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_candidates(db, tenant_id: str, now: datetime) -> list[dict]:
    """Leads that should get an offer right now, oldest purchase first."""
    won = _paged(lambda: db.table("deals").select("lead_id, won_at").eq("tenant_id", tenant_id).eq("stage", "won"))
    last_bought: dict[str, datetime] = {}
    for d in won:
        at = _parse(d.get("won_at"))
        if d.get("lead_id") and at and (d["lead_id"] not in last_bought or at > last_bought[d["lead_id"]]):
            last_bought[d["lead_id"]] = at
    cutoff = now - QUIET_AFTER_PURCHASE
    ids = [lid for lid, at in last_bought.items() if at <= cutoff]
    if not ids:
        return []

    recent = {
        r["lead_id"] for r in _paged(lambda: (
            db.table("comeback_offer_sends").select("lead_id").eq("tenant_id", tenant_id)
            .in_("status", ["sending", "sent"]).gte("created_at", (now - ONE_OFFER_PER).isoformat())
        ))
    }
    # A failed attempt (bad number, Meta said no) is not retried for a week, or the same oldest customers
    # would be picked and fail every day while everyone behind them in the queue never gets an offer.
    recent |= {
        r["lead_id"] for r in _paged(lambda: (
            db.table("comeback_offer_sends").select("lead_id").eq("tenant_id", tenant_id)
            .eq("status", "failed").gte("created_at", (now - RETRY_AFTER_FAILED).isoformat())
        ))
    }
    unhappy: set[str] = set()
    try:
        unhappy = {
            r["lead_id"] for r in _paged(lambda: (
                db.table("customer_feedback").select("lead_id").eq("tenant_id", tenant_id)
                .lte("stars", UNHAPPY_MAX_STARS)
            )) if r.get("lead_id")
        }
    except Exception as e:
        logger.warning(f"comeback: unhappy list not read for {tenant_id}: {e}")

    from app.services.automation_guards import lead_blocks_automated_outbound
    out = []
    ids = [i for i in ids if i not in recent and i not in unhappy]
    ids.sort(key=lambda i: last_bought[i])
    for start in range(0, len(ids), 200):
        rows = (
            db.table("leads").select("id, name, phone, opt_in_source, opted_out, blocked_at, do_not_call, whatsapp_undeliverable, archived_at")
            .eq("tenant_id", tenant_id).in_("id", ids[start:start + 200]).execute().data or []
        )
        for lead in rows:
            if lead_blocks_automated_outbound(lead) or lead.get("do_not_call") or lead.get("archived_at"):
                continue
            if not (lead.get("opt_in_source") or "").strip():
                continue                      # no record of how they opted in: no marketing message
            out.append(lead)
    out.sort(key=lambda l: last_bought[l["id"]])
    return out


# ───────────────────────────────────────────────────────────── sending

def _first_name(name: str | None) -> str:
    parts = (name or "").split()
    return parts[0][:30] if parts else "there"


def _business_name(db, tenant_id: str) -> str:
    try:
        rows = db.table("tenants").select("name").eq("id", tenant_id).limit(1).execute().data or []
        return (rows[0].get("name") if rows else "") or "us"
    except Exception:
        return "us"


def _values(template: dict, lead: dict, setting: dict, business: str) -> list[dict] | None:
    from app.services.template_fields import build_body_components, placeholder_count
    ends = setting.get("ends_on") or "soon"
    defaults = [_first_name(lead.get("name")), setting.get("offer") or "-", setting.get("code") or "-", ends, business]
    count = placeholder_count(template.get("body_text"))
    defaults += ["-"] * max(0, count - len(defaults))
    return build_body_components(template, defaults)


async def _send_all(db, tenant_id: str, template: dict, setting: dict, leads: list[dict], now: datetime) -> int:
    from app.services.call_details_share import render_template
    from app.services.meta_cloud import send_template_message

    business = _business_name(db, tenant_id)
    sent = 0
    for lead in leads:
        claim = None
        try:
            # Claim first (counts toward the 30-day rule at once), then send.
            claim = db.table("comeback_offer_sends").insert({
                "tenant_id": tenant_id, "lead_id": lead["id"], "phone": lead["phone"],
                "template_name": template["name"], "status": "sending", "created_at": now.isoformat(),
            }).execute().data[0]
            components = _values(template, lead, setting, business)
            resp = await send_template_message(
                lead["phone"], template["name"], template.get("language") or "en",
                components=components, tenant_id=tenant_id,
            )
            sid = ((resp or {}).get("messages") or [{}])[0].get("id")
            if not sid:
                raise RuntimeError("WhatsApp did not accept the message")
            db.table("comeback_offer_sends").update(
                {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", claim["id"]).execute()
            sent += 1
            values = [p["text"] for p in ((components or [{}])[0].get("parameters") or [])]
            try:
                db.table("messages").insert({
                    "lead_id": lead["id"], "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
                    "content": render_template(template.get("body_text"), values), "is_ai_generated": False,
                    "meta_message_id": sid,
                }).execute()
            except Exception as e:
                logger.warning(f"comeback: sent but not saved to the chat ({lead['id']}): {e}")
        except (httpx.ReadTimeout, httpx.WriteTimeout) as e:
            # Meta may have taken it before the call timed out. Leave the claim as "sending" (it counts for the
            # full 30 days) so the customer is not sent a second offer tomorrow.
            logger.warning(f"comeback: outcome unknown for {lead.get('id')} for {tenant_id}: {e!r}")
            if claim:
                try:
                    db.table("comeback_offer_sends").update(
                        {"error": "timed out, delivery unknown"}
                    ).eq("id", claim["id"]).execute()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"comeback: not sent to {lead.get('id')} for {tenant_id}: {e}")
            if claim:
                try:
                    db.table("comeback_offer_sends").update(
                        {"status": "failed", "error": (str(e) or "failed")[:300]}
                    ).eq("id", claim["id"]).execute()
                except Exception:
                    pass
    return sent


def send_for_tenant(db, tenant_id: str, setting: dict, now: datetime) -> int:
    name = setting.get("template_name")
    if not name:
        return 0
    # Settings > Auto-Reply: when the business switched automatic messages off, no come-back offers either.
    from app.services.automation_guards import master_switch_on
    if not master_switch_on(tenant_id):
        return 0
    ends = setting.get("ends_on")
    if ends:
        try:
            if date.fromisoformat(ends) < _today_ist(now):
                return 0                      # the offer has ended
        except ValueError:
            return 0
    from app.services.call_details_share import _approved_templates
    template = next((t for t in _approved_templates(db, tenant_id) if t.get("name") == name), None)
    if not template:
        return 0
    leads = find_candidates(db, tenant_id, now)[:MAX_PER_BUSINESS_PER_RUN]
    if not leads:
        return 0
    return _run(_send_all(db, tenant_id, template, setting, leads, now))


def send_comeback_offers(db, now: datetime | None = None) -> int:
    """Send the Come-back offer for every business that has it on. Returns how many messages were sent."""
    now = now or datetime.now(timezone.utc)
    start, end = SEND_HOURS_IST
    if not start <= now.astimezone(IST).hour < end:
        return 0
    total = 0
    for row in settings_rows(db, SETTING_KEY):
        if not row["value"].get("on"):
            continue
        try:
            total += send_for_tenant(db, row["tenant_id"], row["value"], now)
        except Exception as e:
            logger.error(f"comeback offer failed for {row['tenant_id']}: {e}")
    return total

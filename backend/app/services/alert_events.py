"""v9.2 #29 Four more alerts, raised from the code paths where the thing happens.

  refund_done        a refund was given on an order        -> owner + people who can see money (deals.view)
  stock_low          an item's stock went below 3          -> owner + admins, once per item per day
  hot_lead_waiting   a Hot chat unanswered for 30 minutes  -> the lead's own person + owner, once per lead per day

("Many said stop" is not here: services/reach_quality.py already stops such a campaign and sends campaign_paused.)

Every one goes through notify_user, so each alert's on/off switch, "who gets it" and push settings
(Settings > Alerts) are respected. "Once per ... per day" is a row in alert_fired (migration 335) claimed before
the bell is sent: two workers racing, or a re-run of the sweep, can never send it twice. When that table does not
exist yet nothing is sent (never a flood).
Everything here is best-effort and never raises: an alert must not break the refund or the sale it follows.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
STOCK_LOW_BELOW = 3
HOT_WAIT = timedelta(minutes=30)
HOT_STALE = timedelta(hours=24)  # a chat that has waited longer than a day is not "just now": stay quiet


def _today(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(IST).date().isoformat()


def claim_once(db, tenant_id: str, alert_key: str, subject: str, now: datetime | None = None) -> bool:
    """True the first time this (alert, thing) is claimed today (IST), False after that or when it cannot be recorded."""
    try:
        res = db.table("alert_fired").upsert(
            {"tenant_id": tenant_id, "alert_key": alert_key, "subject": str(subject), "day": _today(now)},
            on_conflict="tenant_id,alert_key,subject,day", ignore_duplicates=True,
        ).execute()
        return bool(res.data)
    except Exception as e:  # migration 335 not applied, or the database blinked: send nothing rather than repeat
        logger.warning("alerts: could not record %s/%s for %s, not sent: %s", alert_key, subject, tenant_id, e)
        return False


def _members(db, tenant_id: str) -> tuple[list[dict], dict[str, list]]:
    users = db.table("tenant_users").select("user_id, role, role_id").eq("tenant_id", tenant_id).execute().data or []
    roles = db.table("tenant_roles").select("id, permissions").eq("tenant_id", tenant_id).execute().data or []
    return users, {r["id"]: (r.get("permissions") or []) for r in roles}


def user_ids_with(db, tenant_id: str, *permissions: str) -> list[str]:
    """The owner(s) plus every member whose role holds one of these permissions."""
    try:
        users, perms = _members(db, tenant_id)
    except Exception as e:
        logger.warning("alerts: could not list who to tell for %s: %s", tenant_id, e)
        return []
    wanted = set(permissions)
    return [str(u["user_id"]) for u in users
            if u.get("user_id") and (u.get("role") == "owner" or wanted & set(perms.get(u.get("role_id")) or []))]


def money_viewers(db, tenant_id: str) -> list[str]:
    """Who may see rupees: the owner and anyone with Orders view (deals.manage includes it)."""
    return user_ids_with(db, tenant_id, "deals.view", "deals.manage")


def owners_and_admins(db, tenant_id: str) -> list[str]:
    try:
        rows = (db.table("tenant_users").select("user_id, role").eq("tenant_id", tenant_id)
                .in_("role", ["owner", "admin"]).execute().data or [])
    except Exception as e:
        logger.warning("alerts: owners not read for %s: %s", tenant_id, e)
        return []
    return [str(r["user_id"]) for r in rows if r.get("user_id")]


# ── refund done ───────────────────────────────────────────────────────────────

METHOD_WORDS = {"razorpay": "back to their card or UPI (Razorpay)", "cash": "in cash", "upi": "by UPI", "bank_transfer": "by bank transfer"}


def refund_done(db, tenant_id: str, *, deal_id: str, deal_label: str, amount_paise: int, method: str | None,
                reason: str | None, by_user_id: str | None = None) -> int:
    """One bell to every money viewer except the person who gave the refund. Returns how many were told."""
    try:
        from app.services.deals import _rupees
        from app.services.notify import notify_user
        text = f"{_rupees(int(amount_paise))} was refunded on {deal_label} {METHOD_WORDS.get(method or '', '')}".strip() + "."
        if reason:
            text += f" Reason: {reason}."
        told = 0
        for uid in money_viewers(db, tenant_id):
            if uid == str(by_user_id or ""):
                continue
            notify_user(tenant_id, uid, "refund_done", "A refund was given", text, db=db,
                        push_url=f"/dashboard/deals/orders/{deal_id}")
            told += 1
        return told
    except Exception as e:
        logger.warning("alerts: refund_done for %s failed: %s", deal_id, e)
        return 0


# ── stock running low ─────────────────────────────────────────────────────────

def stock_low(db, tenant_id: str, *, subject_id: str, name: str, quantity_after: int, now: datetime | None = None) -> int:
    """Once per item (or size) per day, when a sale or movement takes its stock below 3."""
    try:
        if quantity_after is None or int(quantity_after) >= STOCK_LOW_BELOW:
            return 0
        if not claim_once(db, tenant_id, "stock_low", subject_id, now):
            return 0
        from app.services.notify import notify_user
        left = max(int(quantity_after), 0)
        title = f"Running low: {name}" if left else f"Out of stock: {name}"
        message = f"Only {left} left. Add stock or order more in Catalogue."
        told = 0
        for uid in owners_and_admins(db, tenant_id):
            notify_user(tenant_id, uid, "stock_low", title, message, db=db, push_url="/dashboard/catalog")
            told += 1
        return told
    except Exception as e:
        logger.warning("alerts: stock_low for %s failed: %s", subject_id, e)
        return 0


def stock_moved(db, tenant_id: str, *, item_id: str, variant_id: str | None, delta: int, quantity_after) -> None:
    """Called after a stock movement. Only a sale or removal (delta below 0) can raise it."""
    try:
        if delta >= 0 or quantity_after is None or int(quantity_after) >= STOCK_LOW_BELOW:
            return
        item = (db.table("catalog_items").select("name").eq("id", item_id).eq("tenant_id", tenant_id)
                .limit(1).execute().data or [{}])[0]
        name = item.get("name") or "An item"
        if variant_id:
            v = (db.table("catalog_item_variants").select("size, colour").eq("id", variant_id).eq("tenant_id", tenant_id)
                 .limit(1).execute().data or [{}])[0]
            label = " · ".join(x for x in (v.get("size"), v.get("colour")) if x)
            name = f"{name} ({label})" if label else name
        stock_low(db, tenant_id, subject_id=variant_id or item_id, name=name, quantity_after=int(quantity_after))
    except Exception as e:
        logger.warning("alerts: stock check after a movement failed: %s", e)


# ── hot chat waiting ──────────────────────────────────────────────────────────

def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _waiting_hot_chats(db, tenant_id: str, now: datetime) -> dict[str, datetime]:
    """{lead id: waiting since} for the Hot chats on the Chats page's own "Needs you" list."""
    from app.services.home_today import _needs_you_rows
    rows = _needs_you_rows(db, {"tenant_id": tenant_id, "role": "owner"}, 200, "A")
    out: dict[str, datetime] = {}
    for r in rows:
        since = _parse(r.get("waiting_since"))
        if since and now - HOT_STALE <= since <= now - HOT_WAIT:
            out[str(r["lead_id"])] = since
    return out


def sweep_hot_leads(db=None, now: datetime | None = None) -> int:
    """Every few minutes: a Hot lead whose message has had no answer for 30 minutes rings once per lead per day.
    Returns how many bells went out (people told)."""
    from app.db.supabase import get_supabase
    from app.services.reports_common import paged
    db = db or get_supabase()
    now = now or datetime.now(timezone.utc)
    lo, hi = (now - HOT_STALE).isoformat(), (now - HOT_WAIT).isoformat()
    try:
        leads = paged(lambda: db.table("leads").select("id, tenant_id, name, assigned_to, last_inbound_at")
                      .eq("segment", "A").is_("deleted_at", "null").is_("converted_at", "null").is_("lost_at", "null")
                      .gte("last_inbound_at", lo).lte("last_inbound_at", hi))
    except Exception as e:
        logger.warning("alerts: hot lead sweep could not read leads: %s", e)
        return 0
    by_tenant: dict[str, list[dict]] = {}
    for lead in leads:
        by_tenant.setdefault(str(lead["tenant_id"]), []).append(lead)
    rung = _rung_today(db, list(by_tenant), now)
    told = 0
    for tenant_id, rows in by_tenant.items():
        rows = [lead for lead in rows if (tenant_id, str(lead["id"])) not in rung]
        if not rows:
            continue  # everyone here was already rung today: no inbox lookup at all
        try:
            waiting = _waiting_hot_chats(db, tenant_id, now)
        except Exception as e:  # one business failing must not stop the others
            logger.warning("alerts: hot lead sweep failed for %s: %s", tenant_id, e)
            continue
        for lead in rows:
            try:
                since = waiting.get(str(lead["id"]))
                if since is None or not claim_once(db, tenant_id, "hot_lead_waiting", str(lead["id"]), now):
                    continue
                told += _ring_hot(db, tenant_id, lead, int((now - since).total_seconds() // 60))
            except Exception as e:  # one bad lead must not stop the rest
                logger.warning("alerts: hot lead %s not rung for %s: %s", lead.get("id"), tenant_id, e)
    return told


def _rung_today(db, tenant_ids: list[str], now: datetime) -> set[tuple[str, str]]:
    """{(tenant, lead)} already rung today, so they cost no inbox lookup. Empty when the table cannot be read."""
    if not tenant_ids:
        return set()
    try:
        from app.services.reports_common import chunks, paged
        out: set[tuple[str, str]] = set()
        for part in chunks(tenant_ids):
            rows = paged(lambda part=part: db.table("alert_fired").select("tenant_id, subject")
                         .in_("tenant_id", part).eq("alert_key", "hot_lead_waiting").eq("day", _today(now)),
                         order_by=("tenant_id", "subject"))
            out |= {(str(r["tenant_id"]), str(r["subject"])) for r in rows}
        return out
    except Exception as e:
        logger.warning("alerts: today's hot lead rings not read: %s", e)
        return set()


def _ring_hot(db, tenant_id: str, lead: dict, minutes: int) -> int:
    from app.services.notify import notify_user
    people = set(user_ids_with(db, tenant_id))  # the owner(s)
    if lead.get("assigned_to"):
        row = (db.table("callers").select("user_id").eq("id", lead["assigned_to"]).eq("tenant_id", tenant_id)
               .limit(1).execute().data or [])
        if row and row[0].get("user_id"):
            people.add(str(row[0]["user_id"]))
    name = lead.get("name") or "A hot customer"
    for uid in people:
        notify_user(tenant_id, uid, "hot_lead_waiting", "A hot customer is waiting",
                    f"{name} wrote {minutes} minutes ago and has no reply yet.", db=db,
                    push_url=f"/dashboard/conversations?lead={lead['id']}")
    return len(people)

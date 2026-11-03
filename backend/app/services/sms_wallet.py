# backend/app/services/sms_wallet.py
"""SMS balance history and the low-balance alert (Bulk9 has an API for neither).

Every 15 minutes the sms-balance-sync job reads each connected client's balance and compares it
with the last one, minus the SMS Anril itself sent in between:

    last 500, Anril sent 40, now 1,460  →  1,460 − 500 + 40 = +1,000  → a top-up
    last 500, Anril sent 40, now 400    →  400 − 500 + 40  = −60      → used outside Anril

A tenant with an SMS mid-send is skipped that tick: Bulk9 may already have debited it while our
row has no sms_count yet, which would read as a fake change. Campaign spends come from
sms_messages, so they are never stored twice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services import bulk9_client
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout

logger = logging.getLogger(__name__)

LOW_BALANCE_SMS = 500  # matches the amber chip on the SMS page


def _connected_tenants(db) -> list[tuple[str, str]]:
    rows = (db.table("app_settings").select("tenant_id,value").eq("key", "bulk9_api_key")
            .execute()).data or []
    return [(r["tenant_id"], r["value"]) for r in rows if r.get("tenant_id") and r.get("value")]


def _sent_since(db, tenant_id: str, since: str, until: str) -> int:
    """SMS parts Anril submitted for this tenant in (since, until]. Dry-run sends never reached
    Bulk9, so they cost nothing."""
    total, start = 0, 0
    while True:
        rows = (db.table("sms_messages").select("id,sms_count,submitted_at,request_id").eq("tenant_id", tenant_id)
                .gte("submitted_at", since).lte("submitted_at", until).order("id")
                .range(start, start + 999).execute()).data or []
        total += sum(int(r.get("sms_count") or 1) for r in rows
                     if r.get("submitted_at") != since and not str(r.get("request_id") or "").startswith("dry-run"))
        if len(rows) < 1000:
            return total
        start += 1000


def _alert_low(db, tenant_id: str, sms_count: int) -> None:
    from app.services.call_alerts import admin_user_ids
    from app.services.notify import notify_user
    for uid in admin_user_ids(db, tenant_id):
        notify_user(tenant_id, uid, "sms_low_balance", "SMS balance is low",
                    f"Only {sms_count:,} SMS left. Contact your Anril account manager to top up.",
                    db=db, push_url="/dashboard/sms")


async def sync_tenant(db, tenant_id: str, api_key: str, *, now: datetime | None = None) -> str:
    """One tenant's tick. Returns what happened (for tests and the job log)."""
    now = now or datetime.now(timezone.utc)
    busy = (db.table("sms_messages").select("id").eq("tenant_id", tenant_id).eq("status", "sending")
            .limit(1).execute()).data
    if busy:
        return "busy"
    try:
        count = (await bulk9_client.wallet(api_key))["sms_count"]
    except (Bulk9Error, Bulk9Timeout) as exc:
        logger.info("SMS balance sync: %s for tenant %s", type(exc).__name__, tenant_id)
        return "error"

    prev = ((db.table("sms_wallet").select("*").eq("tenant_id", tenant_id).limit(1).execute()).data
            or [None])[0]
    result = "first"
    low_alerted_at = prev.get("low_alerted_at") if prev else None
    if prev:
        delta = count - int(prev["sms_count"]) + _sent_since(db, tenant_id, prev["checked_at"], now.isoformat())
        result = "same"
        if delta:
            db.table("sms_wallet_events").insert({
                "tenant_id": tenant_id, "kind": "topup" if delta > 0 else "outside_usage",
                "sms_delta": delta, "balance_after": count, "created_at": now.isoformat(),
            }).execute()
            result = "topup" if delta > 0 else "outside_usage"

    # One alert per dip: fires when the balance first falls below the line, re-arms once it's back above.
    if count < LOW_BALANCE_SMS and not low_alerted_at:
        _alert_low(db, tenant_id, count)
        low_alerted_at = now.isoformat()
    elif count >= LOW_BALANCE_SMS:
        low_alerted_at = None

    db.table("sms_wallet").upsert({"tenant_id": tenant_id, "sms_count": count, "checked_at": now.isoformat(),
                                   "low_alerted_at": low_alerted_at}, on_conflict="tenant_id").execute()
    return result


async def sync_balances(db, *, now: datetime | None = None) -> dict[str, int]:
    stats: dict[str, int] = {}
    for tenant_id, key in _connected_tenants(db):
        outcome = await sync_tenant(db, tenant_id, key, now=now)
        stats[outcome] = stats.get(outcome, 0) + 1
    return stats


def history(db, tenant_id: str, limit: int = 100) -> dict[str, Any]:
    """Top-ups, outside usage and per-campaign spends, newest first."""
    items: list[dict[str, Any]] = []
    for e in (db.table("sms_wallet_events").select("*").eq("tenant_id", tenant_id)
              .order("created_at", desc=True).limit(limit).execute()).data or []:
        items.append({
            "kind": e["kind"], "sms": int(e["sms_delta"]), "amount": None,
            "label": "Top-up" if e["kind"] == "topup" else "Used outside Anril (API key)",
            "campaign_id": None, "at": e["created_at"], "balance_after": e.get("balance_after"),
        })

    from app.services.sms_campaigns import public_campaigns
    campaigns = (db.table("sms_campaigns").select("*").eq("tenant_id", tenant_id)
                 .order("created_at", desc=True).limit(limit).execute()).data or []
    by_id = {c["id"]: c for c in campaigns}
    for c in public_campaigns(db, tenant_id, campaigns):
        if not c["sms_used"]:
            continue
        deleted = bool(by_id[c["id"]].get("deleted_at"))  # spend stays; the link goes
        items.append({
            "kind": "campaign", "sms": -c["sms_used"], "amount": c["amount_debited"],
            "label": f'{c["name"]} (deleted)' if deleted else c["name"],
            "campaign_id": None if deleted else c["id"],
            "at": c.get("send_at") or c.get("created_at"), "balance_after": None,
        })

    items.sort(key=lambda i: str(i["at"] or ""), reverse=True)
    wallet = (db.table("sms_wallet").select("checked_at").eq("tenant_id", tenant_id).limit(1)
              .execute()).data or []
    return {"items": items[:limit], "checked_at": wallet[0]["checked_at"] if wallet else None}

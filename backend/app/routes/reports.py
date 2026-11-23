"""Reports (v9.2 Batch H #16): one screen, seven tabs, all read-only.

Every report takes ?from=YYYY-MM-DD&to=YYYY-MM-DD (India days, `to` included; no days = last 30) and
?compare=previous|off, and answers {"period": {...}, "before": {...}|null, "in_short": "...", ...}.
Seeing it needs analytics.view. Rupee figures need the owner or deals.view; profit, expenses, GST paid
and supplier dues also need purchases.view. A person without the permission gets those keys left out
and "money_hidden": true (see services/reports_common.py).
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_permission
from app.services import (
    reports_ads, reports_campaigns, reports_csv, reports_customers, reports_items, reports_money,
    reports_overview, reports_people, reports_team,
)
from app.services.download_gate import log_download, require_download
from app.services.reports_common import flags_for, resolve_period, run_report, want_before

router = APIRouter()
require_view = require_permission("analytics.view")
require_books = require_permission("purchases.view")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# tab -> how to build it (overview and money have their own steps)
SIMPLE = {"customers": reports_customers, "ads": reports_ads, "team": reports_team, "items": reports_items,
          "campaigns": reports_campaigns}


def _build(tab: str, tenant_id: str, ctx: dict, from_day, to_day, compare) -> dict:
    period = resolve_period(from_day, to_day)
    cmp_ = want_before(compare)
    flags = flags_for(ctx)
    db = get_supabase()
    if tab == "overview":
        return reports_overview.report(db, tenant_id, period, cmp_, flags)
    if tab == "money":
        return reports_money.report(db, tenant_id, period, cmp_, flags)
    return run_report(SIMPLE[tab], db, tenant_id, period, cmp_, flags)


async def _tab(tab: str, ctx: dict, from_day, to_day, compare) -> dict:
    return await asyncio.to_thread(_build, tab, ctx["tenant_id"], ctx, from_day, to_day, compare)


def _define(tab: str):
    async def endpoint(ctx: dict = Depends(require_view), from_day: str | None = Query(None, alias="from"),
                       to_day: str | None = Query(None, alias="to"), compare: str = "previous"):
        return await _tab(tab, ctx, from_day, to_day, compare)
    endpoint.__name__ = f"report_{tab}"
    router.add_api_route(f"/{tab}", endpoint, methods=["GET"])

    if tab in reports_csv.TABS:
        async def csv_endpoint(ctx: dict = Depends(require_view), from_day: str | None = Query(None, alias="from"),
                               to_day: str | None = Query(None, alias="to"), compare: str = "previous"):
            require_download(ctx)  # "Download lists": owner or leads.download
            report = await _tab(tab, ctx, from_day, to_day, compare)
            body = await asyncio.to_thread(reports_csv.to_csv, tab, report)
            log_download(get_supabase(), ctx, list_name=f"Report: {tab}", row_count=body.count("\n"),
                         filters={"from": from_day, "to": to_day})
            return Response(body, media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="report-{tab}.csv"'})
        csv_endpoint.__name__ = f"report_{tab}_csv"
        router.add_api_route(f"/{tab}.csv", csv_endpoint, methods=["GET"])


for _name in ("overview", "money", "customers", "ads", "team", "items", "campaigns"):
    _define(_name)


@router.get("/money/accountant.xlsx")
async def accountant_file(month: str | None = None, ctx: dict = Depends(require_books)):
    """One Excel for the accountant: Summary, Sales B2B, Sales B2C, Credit notes, Purchases, Expenses, Payment split.
    It holds sales rupees too, so it also needs "See orders" (deals.view), like every rupee on Reports."""
    if not _has_permission(ctx, "deals.view"):
        raise HTTPException(status_code=403, detail="Permission required: deals.view")
    content, name = await asyncio.to_thread(reports_money.accountant_excel, get_supabase(), ctx["tenant_id"], month)
    log_download(get_supabase(), ctx, list_name="Report: accountant file", row_count=0, filters={"month": month})
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/people")
async def people_behind(metric: str, id: str | None = None, ctx: dict = Depends(require_view),
                        from_day: str | None = Query(None, alias="from"), to_day: str | None = Query(None, alias="to"),
                        compare: str = "previous"):
    """The people behind a number: [{lead_id, name, phone, detail}], 500 at most.
    Names and phones are customer details, so this also needs "See leads" (leads.view), and a telecaller
    sees only the people given to them, the same as on the Customers list."""
    if not _has_permission(ctx, "leads.view"):
        raise HTTPException(status_code=403, detail="Permission required: leads.view")
    period = resolve_period(from_day, to_day)
    flags = flags_for(ctx)
    db = get_supabase()
    rows = await asyncio.to_thread(reports_people.people, db, ctx["tenant_id"], metric, period, id, flags.sees_money)
    if ctx.get("role") == "caller":
        rows = await asyncio.to_thread(_only_assigned, db, ctx, rows)
    return {"people": rows, "count": len(rows), "capped": len(rows) >= reports_people.MAX_PEOPLE}


def _only_assigned(db, ctx: dict, rows: list[dict]) -> list[dict]:
    """A telecaller's people sheet: only leads assigned to them (nobody when they have no caller id)."""
    caller_id = ctx.get("caller_id")
    ids = [r["lead_id"] for r in rows if r.get("lead_id")]
    if not caller_id or not ids:
        return []
    mine: set[str] = set()
    for i in range(0, len(ids), 200):
        part = ids[i:i + 200]
        got = (db.table("leads").select("id").eq("tenant_id", ctx["tenant_id"]).eq("assigned_to", caller_id)
               .in_("id", part).execute().data or [])
        mine |= {str(r["id"]) for r in got}
    return [r for r in rows if str(r.get("lead_id")) in mine]

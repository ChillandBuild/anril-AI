"""v9.2 Courses: the five tiles on Courses & batches, and Fee instalments (every student with a fee plan,
who paid, what is next and when, with Due this week / Late filters).

Read in bulk (plans, their payments, orders, students, batches, courses) and worked out with the same
rule as the course page (fee_plans.covered_parts): money put on the order elsewhere covers unpaid parts,
earliest first. Money is only returned to people who may see it (the routes decide).
"""
import logging
from datetime import date, datetime, timedelta, timezone

from app.services import fee_plans as fees

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
DUE_SOON_DAYS = 7


def _in(db, table: str, tenant_id: str, column: str, values: list, select: str = "*") -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(values), 200):
        out += (db.table(table).select(select).eq("tenant_id", tenant_id).in_(column, values[i:i + 200])
                .execute().data or [])
    return out


def status_for(next_due: date | None, today: date) -> tuple[str, int]:
    """("paid" | "late" | "due_soon" | "on_track", days late)."""
    if next_due is None:
        return "paid", 0
    if next_due < today:
        return "late", (today - next_due).days
    if next_due <= today + timedelta(days=DUE_SOON_DAYS):
        return "due_soon", 0
    return "on_track", 0


def instalments(db, tenant_id: str, *, today: date | None = None) -> list[dict]:
    today = today or datetime.now(IST).date()
    plans = fees.fetch_all(lambda: db.table("fee_plans").select("id,deal_id,parts").eq("tenant_id", tenant_id))
    if not plans:
        return []
    deal_ids = [p["deal_id"] for p in plans]
    deals = {d["id"]: d for d in _in(db, "deals", tenant_id, "id", deal_ids, "id,paid_paise,stage")}
    payments: dict[str, dict[int, int]] = {}
    for pay in _in(db, "fee_plan_payments", tenant_id, "fee_plan_id", [p["id"] for p in plans],
                   "fee_plan_id,part_index,paid_paise"):
        payments.setdefault(pay["fee_plan_id"], {})[int(pay["part_index"])] = int(pay["paid_paise"])
    enrols = {e["deal_id"]: e for e in _in(db, "batch_enrolments", tenant_id, "deal_id", deal_ids,
                                            "id,deal_id,batch_id,lead_id,student_name,phone,status")}
    batches = {b["id"]: b for b in _in(db, "course_batches", tenant_id, "id",
                                       list({e["batch_id"] for e in enrols.values()}), "id,name,course_item_id")}
    courses = {c["id"]: c for c in _in(db, "catalog_items", tenant_id, "id",
                                       list({b["course_item_id"] for b in batches.values()}), "id,name")}
    rows = []
    for plan in plans:
        enrol = enrols.get(plan["deal_id"])
        deal = deals.get(plan["deal_id"]) or {}
        if not enrol or enrol.get("status") != "active" or deal.get("stage") == "lost":
            continue
        parts = plan.get("parts") or []
        done = fees.covered_parts(parts, payments.get(plan["id"], {}), int(deal.get("paid_paise") or 0))
        total = sum(int(p.get("amount_paise") or 0) for p in parts)
        paid = sum(int(p.get("amount_paise") or 0) for i, p in enumerate(parts) if i in done)
        nxt = next(((i, p) for i, p in enumerate(parts) if i not in done), None)
        next_due = date.fromisoformat(str(nxt[1]["due_on"])[:10]) if nxt else None
        status, late_days = status_for(next_due, today)
        batch = batches.get(enrol["batch_id"]) or {}
        rows.append({
            "plan_id": plan["id"], "deal_id": plan["deal_id"], "enrolment_id": enrol["id"],
            "lead_id": enrol.get("lead_id"), "student_name": enrol.get("student_name"), "phone": enrol.get("phone"),
            "course_name": (courses.get(batch.get("course_item_id")) or {}).get("name"), "batch_name": batch.get("name"),
            "parts": len(parts), "total_paise": total, "paid_paise": paid,
            "next_index": nxt[0] if nxt else None, "next_due": next_due.isoformat() if next_due else None,
            "next_paise": int(nxt[1].get("amount_paise") or 0) if nxt else 0,
            "status": status, "days_late": late_days,
        })
    order = {"late": 0, "due_soon": 1, "on_track": 2, "paid": 3}
    rows.sort(key=lambda r: (order[r["status"]], r["next_due"] or "9999"))
    return rows


def hide_money(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if not k.endswith("_paise")} for r in rows]


def tiles(db, tenant_id: str, courses: list[dict], *, show_money: bool, today: date | None = None) -> dict:
    """Students now, seats left in batches starting this month, demo classes this week (and how many
    joined after), fees due this week, and the waitlist with the full batches."""
    today = today or datetime.now(IST).date()
    live = [b for c in courses for b in c["batches"] if b["status"] != "closed"]
    month = today.strftime("%Y-%m")
    out = {
        "students": sum(b["seats_filled"] + b["seats_waiting"] for b in live),
        "batches": len(live),
        "seats_left_this_month": sum(b["seats_left"] for b in live if (b.get("starts_on") or "")[:7] == month),
        "waitlist": sum(b["waitlist_count"] for b in live),
        "full_batches": [b["name"] for b in live if b["status"] == "full"][:3],
        "demo_week": 0, "demo_joined": 0, "fees_due_students": 0,
    }
    try:
        from app.services.courses import find_demo_service
        demo = find_demo_service(db, tenant_id)
        if demo:
            monday = today - timedelta(days=today.weekday())
            start = datetime(monday.year, monday.month, monday.day, tzinfo=IST).astimezone(timezone.utc).isoformat()
            end = (datetime(monday.year, monday.month, monday.day, tzinfo=IST) + timedelta(days=7)).astimezone(timezone.utc).isoformat()
            rows = (db.table("bookings").select("lead_id,status").eq("tenant_id", tenant_id).eq("service_id", demo["id"])
                    .gte("start_at", start).lt("start_at", end).limit(2000).execute().data or [])
            rows = [r for r in rows if r.get("status") != "cancelled"]
            out["demo_week"] = len(rows)
            leads = list({r["lead_id"] for r in rows if r.get("lead_id")})
            joined = {e["lead_id"] for e in _in(db, "batch_enrolments", tenant_id, "lead_id", leads, "lead_id,status")
                      if e.get("status") == "active"} if leads else set()
            out["demo_joined"] = len(joined)
    except Exception as e:
        logger.info("course tiles: demo classes unavailable: %s", e)
    try:
        week_end = (today + timedelta(days=DUE_SOON_DAYS)).isoformat()
        due = [r for r in instalments(db, tenant_id, today=today) if r["next_due"] and r["next_due"] <= week_end]
        out["fees_due_students"] = len(due)
        if show_money:
            out["fees_due_paise"] = sum(r["next_paise"] for r in due)
    except Exception as e:
        logger.info("course tiles: fees unavailable: %s", e)
    return out

"""Reports > Service & team: how fast the AI agent and your people answer, who sold, stars, calls.

Reply times come from the database function analytics_response_times_split (first answer to a customer
message, split by who gave it). If that function is not there yet the answer is None, not an error.
"Handled by the AI agent alone" = new chats of the days minus the people a chat was passed to
(chat_handovers opened in the days). Calls follow the Calls page: calls by the team, owner's own
calls left out, "connected" = the caller marked it connected.
"""
from app.services.reports_common import Flags, Period, chunks, paged, plural, safe, sentence
from app.services.reports_data import call_numbers, new_chats, won_deals

AI_NAME = "AI agent"


def reply_times(db, tenant_id: str, period: Period) -> dict | None:
    def read():
        rows = db.rpc("analytics_response_times_split", {
            "p_tenant_id": tenant_id, "p_start": period.start_iso, "p_end": period.end_iso}).execute().data or []
        out: dict = {"ai": None, "staff": None}
        for r in rows:
            who = r.get("who")
            if who in out:
                out[who] = {"answered": r.get("answered"), "p50_seconds": r.get("p50_seconds"),
                            "p90_seconds": r.get("p90_seconds")}
        return out
    return safe(read, None, "reply times")


def sales_by_person(db, tenant_id: str, deals: list[dict]) -> list[dict]:
    callers = {r["id"]: r.get("name") for r in safe(lambda: paged(
        lambda: db.table("callers").select("id,name").eq("tenant_id", tenant_id)), [], "callers")}
    users = {r["user_id"]: r.get("full_name") for r in safe(lambda: paged(
        lambda: db.table("tenant_users").select("user_id,full_name").eq("tenant_id", tenant_id), order_by="user_id"),
        [], "team names")}
    totals: dict[str, dict] = {}
    for d in deals:
        if d.get("sold_by_ai"):
            name = AI_NAME
        elif d.get("sold_by") and callers.get(d["sold_by"]):
            name = callers[d["sold_by"]]
        elif d.get("created_by") and users.get(d["created_by"]):
            name = users[d["created_by"]]
        else:
            name = "Not recorded"
        row = totals.setdefault(name, {"name": name, "count": 0, "sales_paise": 0})
        row["count"] += 1
        row["sales_paise"] += int(d.get("total_paise") or 0) - int(d.get("gst_paise") or 0)
    return sorted(totals.values(), key=lambda r: (-r["count"], r["name"]))


def stars_by_person(db, tenant_id: str, period: Period) -> list[dict]:
    rows = safe(lambda: paged(lambda: db.table("customer_feedback").select("id,staff_name,stars")
                              .eq("tenant_id", tenant_id).not_.is_("stars", "null")
                              .gte("answered_at", period.start_iso).lt("answered_at", period.end_iso)), [], "feedback")
    groups: dict[str, list[int]] = {}
    for r in rows:
        groups.setdefault(r.get("staff_name") or "Not recorded", []).append(int(r["stars"]))
    out = [{"name": n, "avg": round(sum(v) / len(v), 1), "count": len(v)} for n, v in groups.items()]
    return sorted(out, key=lambda r: (-r["avg"], -r["count"], r["name"]))


def passed_on_lead_ids(db, tenant_id: str, period: Period) -> list[str]:
    rows = safe(lambda: paged(lambda: db.table("chat_handovers").select("id,lead_id").eq("tenant_id", tenant_id)
                              .gte("opened_at", period.start_iso).lt("opened_at", period.end_iso)), [], "handovers")
    return sorted({r["lead_id"] for r in rows if r.get("lead_id")})


def compute(db, tenant_id: str, period: Period, flags: Flags) -> tuple[dict, dict]:
    chat_ids = {str(c["id"]) for c in new_chats(db, tenant_id, period) if c.get("id")}
    chats = len(chat_ids)
    passed_ids = set(passed_on_lead_ids(db, tenant_id, period))
    passed = len(passed_ids)
    # "AI alone" is about the period's new chats only: a handover for an older customer must not lower it.
    alone = chats - len(chat_ids & {str(i) for i in passed_ids})
    times = reply_times(db, tenant_id, period)
    deals = won_deals(db, tenant_id, period)
    stars = stars_by_person(db, tenant_id, period)
    exact = safe(lambda: paged(lambda: db.table("customer_feedback").select("id,stars").eq("tenant_id", tenant_id)
                               .not_.is_("stars", "null").gte("answered_at", period.start_iso)
                               .lt("answered_at", period.end_iso)), [], "feedback")
    calls = safe(lambda: call_numbers(db, tenant_id, period), None, "calls")
    total_stars = sum(int(r["stars"]) for r in exact)  # exact, not built from the rounded per-person averages
    n_stars = len(exact)

    numbers: dict = {
        "chats": chats, "handled_by_ai_alone": alone, "passed_to_person": passed,
        "ai_reply_p50_seconds": ((times or {}).get("ai") or {}).get("p50_seconds"),
        "staff_reply_p50_seconds": ((times or {}).get("staff") or {}).get("p50_seconds"),
        "orders": len(deals),
        "average_stars": round(total_stars / n_stars, 1) if n_stars else None,
        "stars_given": n_stars,
    }
    if calls:
        numbers.update({"calls": calls["calls"], "connected_calls": calls["connected_calls"]})
    extras = {
        "reply_times": times,
        "handled": {"by_ai_alone": alone, "passed_to_person": passed},
        "sales_by_person": sales_by_person(db, tenant_id, deals),
        "stars_by_person": stars,
        "calls": calls,
    }
    return numbers, extras


def _secs(s) -> str:
    s = int(s)
    return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def in_short(numbers: dict, before: dict | None) -> str:
    parts = []
    if numbers.get("chats"):
        parts.append(f"The AI agent handled {numbers.get('handled_by_ai_alone', 0)} of {plural(numbers['chats'], 'new chat')} alone")
    if numbers.get("ai_reply_p50_seconds") is not None:
        parts.append(f"it usually answers in {_secs(numbers['ai_reply_p50_seconds'])}")
    if numbers.get("staff_reply_p50_seconds") is not None:
        parts.append(f"your team in {_secs(numbers['staff_reply_p50_seconds'])}")
    if numbers.get("calls"):
        parts.append(f"{numbers['calls']} calls made")
    return sentence(parts, "No chats or calls in these days.")

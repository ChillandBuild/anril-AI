"""Telecalling uploads: which rows of a file were taken out, and why (v9.2 item 234).

A row is "taken out" when the upload did not hand that person to a telecaller or into the pool:
  bad_number          the phone cell is empty or not a phone number (never became a lead)
  duplicate           the same number appears again in the same file (only the last copy is used)
  said_stop           already on Do Not Call or Said stop
  already_customer    already converted or bought
  closed              closed earlier (wrong number, unreachable, disqualified, ...)
  already_with_caller already in the leads with a telecaller, so the upload left them there
Saved on the batch (telecalling_upload_batches.taken_out / taken_out_counts, migration 334). Uploads made
before that migration have neither and show a dash.
"""
import csv
import io
from datetime import datetime, timezone

from app.services.call_wrapup import CLOSED_LEAD_STATUSES
from app.services.reports_common import safe_cell

REASON_LABEL = {
    "bad_number": "Bad number",
    "duplicate": "Repeated in the file",
    "said_stop": "Said stop",
    "already_customer": "Already a customer",
    "closed": "Closed earlier",
    "already_with_caller": "Already with a telecaller",
}
# Rows kept in full on the batch; the per-reason counts are always complete.
MAX_STORED_ROWS = 5000


def reason_for_existing(lead: dict, *, is_new: bool) -> str | None:
    """Why an upload left this (already-known) lead out, or None when it was used."""
    if lead.get("do_not_call") or lead.get("opted_out"):
        return "said_stop"
    if lead.get("converted_at") or lead.get("call_status") == "converted":
        return "already_customer"
    if lead.get("call_status") in CLOSED_LEAD_STATUSES:
        return "closed"
    if not is_new and lead.get("assigned_to"):
        return "already_with_caller"
    return None


def summarize(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """(rows to store, {reason: count}). The stored list is capped; the counts are not."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["reason"]] = counts.get(r["reason"], 0) + 1
    return rows[:MAX_STORED_ROWS], counts


def csv_text(rows: list[dict], mask=None) -> str:
    """The taken-out rows as a spreadsheet file. mask: the phone masker for people who may not see numbers."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row", "phone", "name", "why"])
    for r in rows:
        phone = r.get("phone") or ""
        if mask and phone:
            phone = mask(phone)
        writer.writerow([r.get("row", ""), safe_cell(phone), safe_cell(r.get("name") or ""),
                         REASON_LABEL.get(r.get("reason"), r.get("reason") or "")])
    return out.getvalue()


def _when(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_CALL_NO_ANSWER = ("no_answer", "missed", "failed")


def reached(call: dict) -> bool:
    """Same rule as the telecaller report: tapped Connected, or (no tap) real talk time."""
    status = call.get("manual_status")
    if status:
        return status == "connected"
    return bool(call.get("duration_seconds")) and call.get("status") not in _CALL_NO_ANSWER


def results_for(snapshot_lead_ids: set[str], calls: list[dict], uploaded_at: str) -> dict:
    """{called, reached, converted}: people of this upload with a call after it (counted once each)."""
    called: set[str] = set()
    got: set[str] = set()
    won: set[str] = set()
    start = _when(uploaded_at)
    for c in calls:
        lead = str(c.get("lead_id") or "")
        at = _when(c.get("created_at"))
        if lead not in snapshot_lead_ids or at is None or start is None or at < start:
            continue
        called.add(lead)
        if reached(c):
            got.add(lead)
        if c.get("outcome") == "converted":
            won.add(lead)
    return {"called": len(called), "reached": len(got), "converted": len(won)}

"""Google Ads page: month window, report-CSV parsing, per-campaign numbers, "came from" labels.

Pure helpers (month window, money / number parsing, CSV parsing, matching) are separate from
the database readers so they are cheap to test. Money (spend, paid, per chat) is only put in
the answer when the caller may see deals money (deals.view); the route passes show_money.

Months are IST months (the business runs on Indian time): "2026-11" is 1 Nov 00:00 IST up to
1 Dec 00:00 IST, converted to UTC for the database.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MAX_UPLOAD_BYTES = 1_048_576
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_CHUNK = 100          # ids per in_() filter, so the request URL stays short
_PAGE = 1000          # PostgREST returns at most 1000 rows per request
HOT_SEGMENT = "A"     # segments: A = Hot, B = Warm, C = Cold, D = Disqualified


class ReportError(ValueError):
    """A problem with what the user sent (bad month, unreadable file); the message is shown as-is."""


# ── Month window ────────────────────────────────────────────────────────────

def current_month_ist(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(IST).strftime("%Y-%m")


def parse_month(value: str | None, now: datetime | None = None) -> str:
    """'YYYY-MM' (default: this month in IST). Raises ReportError for anything else."""
    if value is None or not str(value).strip():
        return current_month_ist(now)
    text = str(value).strip()
    if not _MONTH_RE.match(text):
        raise ReportError("Month must look like 2026-11.")
    return text


def month_first_day(month: str) -> str:
    """The date stored in google_ads_spend.month: 'YYYY-MM-01'."""
    return f"{parse_month(month)}-01"


def month_window_utc(month: str) -> tuple[str, str]:
    """[start, end) of an IST month as UTC ISO strings."""
    year, mon = (int(x) for x in parse_month(month).split("-"))
    start = datetime(year, mon, 1, tzinfo=IST)
    end = datetime(year + (mon == 12), 1 if mon == 12 else mon + 1, 1, tzinfo=IST)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


# ── Number parsing ──────────────────────────────────────────────────────────

def parse_money_paise(value: Any) -> int | None:
    """'₹1,23,456.50' / 'Rs. 1,200' / '1200.5' / '"1,200"' -> paise. None when there is no number
    ('--', '', 'n/a'). Negative amounts are not spend, so they raise nothing and return None."""
    if value is None:
        return None
    text = str(value).strip().replace(" ", " ")
    if not text or text in {"--", "-", "—", "n/a", "N/A"}:
        return None
    text = re.sub(r"(?i)\b(?:rs|inr)\b\.?", "", text)
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    if cleaned in {"", ".", "-"} or cleaned.startswith("-"):
        return None
    try:
        rupees = Decimal(cleaned)
    except InvalidOperation:
        return None
    return int((rupees * 100).to_integral_value(rounding="ROUND_HALF_UP"))


def parse_count(value: Any) -> int | None:
    """'1,234' -> 1234; '--' / '' -> None. Decimals are cut ('12.0' -> 12)."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-", "—"}:
        return None
    try:
        number = int(Decimal(re.sub(r"[^0-9.]", "", text) or "x"))
    except (InvalidOperation, ValueError):
        return None
    return max(number, 0)


# ── Report CSV ──────────────────────────────────────────────────────────────

_MONTH_NAMES = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _cell_month(value: str) -> str | None:
    """The 'YYYY-MM' a Day / Month cell belongs to, or None when it is not a date we know."""
    text = (value or "").strip().strip('"')
    text = re.sub(r"(?i)^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+", "", text)   # "Sunday, 1 November 2026"
    if not text:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$", text)                       # 2026-11 / 2026-11-05
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", text)                    # 05/11/2026 (day first, as in India)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(3)}-{int(m.group(2)):02d}"
    m = re.match(r"^(?:[A-Za-z]+,?\s+)?([A-Za-z]{3,9})\.?\s+(?:\d{1,2},?\s+)?(\d{4})$", text)  # Nov 5, 2026 / November 2026
    if m and m.group(1)[:3].lower() in _MONTH_NAMES:
        return f"{m.group(2)}-{_MONTH_NAMES[m.group(1)[:3].lower()]:02d}"
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$", text)           # 5 Nov 2026
    if m and m.group(2)[:3].lower() in _MONTH_NAMES:
        return f"{m.group(3)}-{_MONTH_NAMES[m.group(2)[:3].lower()]:02d}"
    return None


def decode_report(raw: bytes) -> str:
    """Google exports UTF-8 (sometimes with a BOM) or UTF-16 tab-separated; take either."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


_FOREIGN_MONEY_RE = re.compile(r"[$£€¥]|\b(?:usd|eur|gbp|aud|cad|sgd|aed|jpy|nzd|chf)\b", re.IGNORECASE)
_NOT_RUPEES = "This report is not in rupees. Switch your Google Ads account view to INR and download it again."


def _norm_header(cell: str) -> str:
    return re.sub(r"\s+", " ", (cell or "").strip().strip('"').lower())


def _find_columns(row: list[str]) -> dict[str, int] | None:
    """Column positions when `row` is the table header: needs Campaign plus Cost and/or Clicks."""
    cols: dict[str, int] = {}
    for i, cell in enumerate(row):
        h = _norm_header(cell)
        if h == "campaign" and "campaign" not in cols:
            cols["campaign"] = i
        elif (h == "cost" or h.startswith("cost (") or h == "spend") and "cost" not in cols:
            cols["cost"] = i
        elif h == "clicks" and "clicks" not in cols:
            cols["clicks"] = i
        elif h in {"day", "date", "month", "month of year"} and "when" not in cols:
            cols["when"] = i
    if "campaign" in cols and ("cost" in cols or "clicks" in cols):
        if "cost" in cols and _FOREIGN_MONEY_RE.search(row[cols["cost"]]):
            raise ReportError(_NOT_RUPEES)
        return cols
    return None


def parse_report_csv(raw: bytes | str, month: str) -> dict[str, Any]:
    """Read a Google Ads "Campaign report" CSV.

    Header junk above the table (title, date range) is skipped; the header row is the first one
    with a Campaign column and Cost and/or Clicks. Cost may carry ₹, Rs and thousands commas.
    If the file has a Day / Month column, only rows inside `month` are used (a campaign's days
    are added up); without one, every row is taken as that month's. Total rows are ignored.

    Returns {"rows": [{google_campaign_name, spend_paise, clicks}], "skipped_other_months": n}.
    spend_paise / clicks are None when the file has no Cost / Clicks column. A foreign currency
    ($, USD, EUR...) in the Cost column raises ReportError.
    Raises ReportError when there is no usable table.
    """
    parse_month(month)
    if isinstance(raw, bytes):
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ReportError("That file is too big (limit 1 MB). Download just the campaign report.")
        text = decode_report(raw)
    else:
        text = raw
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sample = "\n".join(text.split("\n")[:40])
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error:
        raise ReportError("We couldn't read that file as a CSV.")

    cols: dict[str, int] | None = None
    start = 0
    for idx, row in enumerate(rows):
        cols = _find_columns(row)
        if cols:
            start = idx + 1
            break
    if not cols:
        raise ReportError(
            "We couldn't find the table. The file needs a Campaign column and a Cost and/or Clicks column."
        )

    totals: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    skipped = 0
    for row in rows[start:]:
        if not row or all(not c.strip() for c in row):
            continue

        def cell(key: str) -> str:
            i = cols.get(key)
            return row[i] if i is not None and i < len(row) else ""

        name = cell("campaign").strip()
        if not name or name in {"--", "-"} or re.match(r"^total\s*(?::|$)", name, re.IGNORECASE):
            continue
        if "when" in cols:
            row_month = _cell_month(cell("when"))
            if row_month != month:
                skipped += 1
                continue
        if "cost" in cols and _FOREIGN_MONEY_RE.search(cell("cost")):
            raise ReportError(_NOT_RUPEES)
        spend = parse_money_paise(cell("cost")) if "cost" in cols else None
        clicks = parse_count(cell("clicks")) if "clicks" in cols else None
        key = name.casefold()
        if key not in totals:
            # None = the file has no such column: the saved value is left alone (see save_spend).
            totals[key] = {"google_campaign_name": name,
                           "spend_paise": 0 if "cost" in cols else None,
                           "clicks": 0 if "clicks" in cols else None}
            order.append(key)
        if "cost" in cols:
            totals[key]["spend_paise"] += spend or 0
        if "clicks" in cols:
            totals[key]["clicks"] += clicks or 0
    if not totals:
        raise ReportError(
            "No campaign rows for this month were found in the file." if skipped
            else "The file has a table but no campaign rows."
        )
    return {"rows": [totals[k] for k in order], "skipped_other_months": skipped}


def match_rows(rows: list[dict], campaigns: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pair report rows with our campaigns by google_campaign_name (case-insensitive, trimmed).

    Returns (matched, unmatched). matched items: the row plus campaign_id and name.
    """
    by_name: dict[str, dict] = {}
    for c in campaigns:
        key = (c.get("google_campaign_name") or "").strip().casefold()
        if key and key not in by_name:
            by_name[key] = c
    matched: list[dict] = []
    unmatched: list[dict] = []
    for row in rows:
        campaign = by_name.get(row["google_campaign_name"].strip().casefold())
        if campaign:
            matched.append({**row, "campaign_id": campaign["id"], "name": campaign.get("campaign_name")})
        else:
            unmatched.append(dict(row))
    return matched, unmatched


# ── Database readers ────────────────────────────────────────────────────────

def _chunks(items: list[str], size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fetch_all(make_query) -> list[dict]:
    """Every row of a query, page by page. make_query() must return a fresh query each call."""
    out: list[dict] = []
    while True:
        page = make_query().order("id").range(len(out), len(out) + _PAGE - 1).execute().data or []
        out.extend(page)
        if len(page) < _PAGE:
            return out


def google_campaigns(db, tenant_id: str) -> list[dict]:
    return (
        db.table("ad_campaigns").select("*")
        .eq("tenant_id", tenant_id).eq("platform", "google")
        .order("created_at", desc=True).execute().data or []
    )


def campaign_rows(db, tenant_id: str, month: str, *, show_money: bool) -> dict[str, Any]:
    """The Google Ads table for one month. Chats = leads from the campaign created in the month;
    calls, hot and paid are about those same leads (calls placed or got in the month; paid is
    what they have paid us, minus refunds, so a late payment still shows against the month the
    chat started)."""
    month = parse_month(month)
    start, end = month_window_utc(month)
    campaigns = google_campaigns(db, tenant_id)
    ids = [str(c["id"]) for c in campaigns]

    leads: list[dict] = []
    spend: dict[str, dict] = {}
    for chunk in _chunks(ids):
        leads += _fetch_all(lambda chunk=chunk: (
            db.table("leads").select("id,ad_campaign_id,segment")
            .eq("tenant_id", tenant_id).in_("ad_campaign_id", chunk)
            .is_("deleted_at", "null").gte("created_at", start).lt("created_at", end)
            .order("created_at")))
        for r in (db.table("google_ads_spend").select("*").eq("tenant_id", tenant_id)
                  .eq("month", month_first_day(month)).in_("campaign_id", chunk).execute().data or []):
            spend[str(r["campaign_id"])] = r

    lead_campaign = {str(l["id"]): str(l["ad_campaign_id"]) for l in leads}
    calls: dict[str, int] = {}
    paid_count: dict[str, int] = {}
    paid_paise: dict[str, int] = {}
    for chunk in _chunks(list(lead_campaign)):
        for call in _fetch_all(lambda chunk=chunk: (
                db.table("call_logs").select("id,lead_id").eq("tenant_id", tenant_id)
                .in_("lead_id", chunk).gte("created_at", start).lt("created_at", end).order("created_at"))):
            cid = lead_campaign.get(str(call["lead_id"]))
            if cid:
                calls[cid] = calls.get(cid, 0) + 1
        for deal in _fetch_all(lambda chunk=chunk: (
                db.table("deals").select("id,lead_id,paid_paise,refunded_paise").eq("tenant_id", tenant_id)
                .in_("lead_id", chunk).gt("paid_paise", 0).order("created_at"))):
            net = int(deal.get("paid_paise") or 0) - int(deal.get("refunded_paise") or 0)
            cid = lead_campaign.get(str(deal["lead_id"]))
            if cid and net > 0:
                paid_count[cid] = paid_count.get(cid, 0) + 1
                paid_paise[cid] = paid_paise.get(cid, 0) + net

    rows: list[dict] = []
    for c in campaigns:
        cid = str(c["id"])
        mine = [l for l in leads if str(l["ad_campaign_id"]) == cid]
        sp = spend.get(cid)
        chats = len(mine)
        row: dict[str, Any] = {
            "campaign_id": cid,
            "name": c.get("campaign_name"),
            "google_campaign_name": c.get("google_campaign_name"),
            "clicks": int(sp["clicks"]) if sp else None,
            "spend_source": sp.get("source") if sp else None,
            "chats": chats,
            "calls": calls.get(cid, 0),
            "hot": sum(1 for l in mine if (l.get("segment") or "").upper() == HOT_SEGMENT),
            "paid_orders": paid_count.get(cid, 0),
        }
        if show_money:
            spent = int(sp["spend_paise"]) if sp else None
            row["spent_paise"] = spent
            row["paid_paise"] = paid_paise.get(cid, 0)
            row["per_chat_paise"] = round(spent / chats) if spent is not None and chats else None
        rows.append(row)
    rows.sort(key=lambda r: (-r["chats"], (r["name"] or "").lower()))
    return {"month": month, "rows": rows, "totals": _totals(rows, show_money=show_money)}


def _totals(rows: list[dict], *, show_money: bool) -> dict[str, Any]:
    clicks = [r["clicks"] for r in rows if r["clicks"] is not None]
    chats = sum(r["chats"] for r in rows)
    totals: dict[str, Any] = {
        "clicks": sum(clicks) if clicks else None,
        "chats": chats,
        "calls": sum(r["calls"] for r in rows),
        "hot": sum(r["hot"] for r in rows),
        "paid_orders": sum(r["paid_orders"] for r in rows),
    }
    if show_money:
        spends = [r["spent_paise"] for r in rows if r.get("spent_paise") is not None]
        spent = sum(spends) if spends else None
        # Per chat over the campaigns that have a spend figure, so a missing month isn't a free chat.
        chats_with_spend = sum(r["chats"] for r in rows if r.get("spent_paise") is not None)
        totals["spent_paise"] = spent
        totals["paid_paise"] = sum(r["paid_paise"] for r in rows)
        totals["per_chat_paise"] = round(spent / chats_with_spend) if spent is not None and chats_with_spend else None
    return totals


def save_spend(db, tenant_id: str, campaign_id: str, month: str, spend_paise: int | None, clicks: int | None,
               *, source: str, user_id: str | None = None) -> dict:
    """Write one campaign-month. None for spend or clicks means "not in the file": the saved value
    stays (both columns are NOT NULL, so a first save of a missing one is 0)."""
    first_day = month_first_day(month)
    if spend_paise is None or clicks is None:
        existing = (
            db.table("google_ads_spend").select("spend_paise,clicks")
            .eq("tenant_id", tenant_id).eq("campaign_id", campaign_id).eq("month", first_day)
            .limit(1).execute().data or []
        )
        old = existing[0] if existing else {}
        if spend_paise is None:
            spend_paise = int(old.get("spend_paise") or 0)
        if clicks is None:
            clicks = int(old.get("clicks") or 0)
    row = {
        "tenant_id": tenant_id,
        "campaign_id": campaign_id,
        "month": first_day,
        "spend_paise": int(spend_paise),
        "clicks": int(clicks),
        "source": source,
        "updated_by": user_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = db.table("google_ads_spend").upsert(row, on_conflict="campaign_id,month").execute().data or [row]
    return saved[0]


# ── "Came from" label for the chat header ───────────────────────────────────

def came_from_labels(db, tenant_id: str, leads: list[dict]) -> dict[str, str]:
    """lead id -> "from Google Ads · <campaign>" / "from Meta ad · <name>" / "from QR · <qr name>".

    An ad campaign wins over a QR code (the ad was the first touch the system recorded as an ad;
    qr_link_id is only set while no ad is). Leads with neither get no entry. Never raises: a
    missing table (migration 317 not applied yet) just means no QR labels.
    """
    out: dict[str, str] = {}
    campaign_ids = sorted({str(l["ad_campaign_id"]) for l in leads if l.get("ad_campaign_id")})
    qr_ids = sorted({str(l["qr_link_id"]) for l in leads if l.get("qr_link_id")})
    campaigns: dict[str, dict] = {}
    qrs: dict[str, str] = {}
    try:
        for chunk in _chunks(campaign_ids):
            for c in (db.table("ad_campaigns").select("id,campaign_name,platform")
                      .eq("tenant_id", tenant_id).in_("id", chunk).execute().data or []):
                campaigns[str(c["id"])] = c
    except Exception:
        campaigns = {}
    try:
        for chunk in _chunks(qr_ids):
            for q in (db.table("qr_links").select("id,name").eq("tenant_id", tenant_id)
                      .in_("id", chunk).execute().data or []):
                qrs[str(q["id"])] = q.get("name") or ""
    except Exception:
        qrs = {}
    for lead in leads:
        lid = str(lead.get("id"))
        if lead.get("ad_campaign_id"):
            c = campaigns.get(str(lead["ad_campaign_id"]))
            label = _ad_label(c)
            if label:
                out[lid] = label
                continue
            out[lid] = "from an ad"
            continue
        if lead.get("qr_link_id") and qrs.get(str(lead["qr_link_id"])):
            out[lid] = f"from QR · {qrs[str(lead['qr_link_id'])]}"
    _add_dialled_labels(db, tenant_id, leads, out)
    return out


_DIAL_WINDOW_SECONDS = 120


def _parse_ts(value: Any) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def dialled_label(lead: dict, first_call: dict | None) -> str | None:
    """"dialled by <caller>" for a lead the dial pad created: source manual, and its first call
    was logged within 120 s of the lead (a lead added by hand and called later gets no label)."""
    if lead.get("source") != "manual" or not first_call:
        return None
    name = ((first_call.get("callers") or {}).get("name") or "").strip()
    lead_at, call_at = _parse_ts(lead.get("created_at")), _parse_ts(first_call.get("created_at"))
    if not name or not lead_at or not call_at:
        return None
    if not 0 <= (call_at - lead_at).total_seconds() <= _DIAL_WINDOW_SECONDS:
        return None
    return f"dialled by {name}"


def _add_dialled_labels(db, tenant_id: str, leads: list[dict], out: dict[str, str]) -> None:
    """Fill `out` for unlabelled manual leads from their first call. Never raises."""
    todo = [l for l in leads if l.get("source") == "manual" and str(l.get("id")) not in out]
    if not todo:
        return
    first: dict[str, dict] = {}
    # Only calls within the dial window of the newest lead can matter: skip the rest of the history.
    created = [t for t in (_parse_ts(l.get("created_at")) for l in todo) if t]
    upper = (max(created) + timedelta(seconds=_DIAL_WINDOW_SECONDS)).isoformat() if created else None
    try:
        for chunk in _chunks(sorted({str(l["id"]) for l in todo})):
            q = (db.table("call_logs").select("lead_id,created_at,callers(name)")
                 .eq("tenant_id", tenant_id).in_("lead_id", chunk))
            if upper:
                q = q.lte("created_at", upper)
            for c in q.order("created_at").execute().data or []:
                first.setdefault(str(c.get("lead_id")), c)  # ascending: first seen is earliest
    except Exception as e:
        logger.warning("dialled-by labels read failed for tenant %s: %s", tenant_id, e)
        return
    for lead in todo:
        label = dialled_label(lead, first.get(str(lead["id"])))
        if label:
            out[str(lead["id"])] = label


def _ad_label(campaign: dict | None) -> str | None:
    if not campaign:
        return None
    name = (campaign.get("campaign_name") or "").strip()
    platform = (campaign.get("platform") or "").lower()
    if platform == "google":
        return f"from Google Ads · {name}" if name else "from Google Ads"
    return f"from Meta ad · {name}" if name else "from Meta ad"

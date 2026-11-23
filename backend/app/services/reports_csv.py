"""Reports: the CSV download of a tab = the same numbers as the screen, as rows.

Built from the finished report (money the person may not see is already left out, so it can't leak
into the file). Rupee figures (keys ending _paise) are written in rupees. Text that a spreadsheet
could run as a formula (a customer or ad name starting with =, +, -, @) is defused.
"""
import csv
import io

from app.services.reports_common import safe_cell

TABS = ("overview", "customers", "ads", "team", "items", "campaigns")

# extras of a report that are lists of rows: (key, title)
TABLES = (("cards", "Cards"), ("todo", "To do"), ("funnel", "Funnel"), ("came_from", "Where people came from"),
          ("rows", "Rows"), ("sales_by_person", "Sales by person"), ("stars_by_person", "Stars by person"),
          ("top_items", "Top items"), ("low_stock", "Running low"), ("orders_by_stage", "Orders by stage"))
SKIP_COLUMNS = {"people", "href", "kind"}


def label(key: str) -> str:
    text = key.replace("_paise", " (rupees)").replace("_seconds", " (seconds)").replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _cell(key: str, value):
    if isinstance(value, bool) or value is None:
        return "" if value is None else value
    if key.endswith("_paise") and isinstance(value, (int, float)):
        return round(value / 100, 2)
    if isinstance(value, (dict, list)):
        return ""
    return safe_cell(value)


def to_csv(tab: str, report: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["In short", safe_cell(report.get("in_short") or "")])
    w.writerow([])
    before = report.get("before")
    w.writerow(["Number", "These days"] + (["Days before"] if before is not None else []))
    for key, value in (report.get("period") or {}).items():
        w.writerow([label(key), _cell(key, value)] + ([_cell(key, before.get(key))] if before is not None else []))
    for key, title in TABLES:
        rows = report.get(key)
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        columns = [c for c in rows[0] if c not in SKIP_COLUMNS and not isinstance(rows[0][c], (dict, list))]
        w.writerow([])
        w.writerow([title])
        w.writerow([label(c) for c in columns])
        for r in rows:
            w.writerow([_cell(c, r.get(c)) for c in columns])
    return out.getvalue()

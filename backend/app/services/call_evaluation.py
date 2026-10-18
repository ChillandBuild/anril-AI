"""SIM clients get no telecaller evaluation anywhere (2026-09-28 decision): no
scores, no winners, no QA review -- and "no evidence" means not even a null
score field on a call-log row. Every endpoint that returns call_logs rows
(recent calls, a caller's own log, a lead's call history, the CSV export)
strips these fields for a SIM tenant with this one helper instead of each
duplicating the field list and the provider check."""

EVALUATION_FIELDS = (
    "score", "score_status", "score_final", "evaluation", "call_group",
    "talk_share", "interruption_count", "interruptions_per_5min",
    "ai_call_status", "rules_version",
)


def _without_evaluation(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in EVALUATION_FIELDS}


def _without_report(row: dict) -> dict:
    evaluation = row.get("evaluation")
    if not isinstance(evaluation, dict) or "report" not in evaluation:
        return row
    return {**row, "evaluation": {k: v for k, v in evaluation.items() if k != "report"}}


def strip_evaluation(
    rows: list[dict] | dict | None, is_sim: bool, *, keep_report: bool = False,
) -> list[dict] | dict | None:
    """Return call-log row(s) with every evaluation field removed when `is_sim`
    is True. Returns new dict(s) -- the row(s) passed in are never mutated, so
    this is safe to call on rows a caller still holds a reference to. For
    TeleCMI tenants the manager's call report (`evaluation.report`) is also
    removed unless `keep_report` -- only the manager-only review route sets it;
    rows without a report come back as the same object.
    Callers do the `calling_provider` lookup once per request and pass the
    result in, rather than this helper looking it up itself on every row."""
    if rows is None:
        return rows
    strip = _without_evaluation if is_sim else (None if keep_report else _without_report)
    if strip is None:
        return rows
    if isinstance(rows, dict):
        return strip(rows)
    return [strip(row) if isinstance(row, dict) else row for row in rows]

# backend/app/services/assignment_rules.py
"""Per-channel telecaller assignment rules. Pure functions, no DB access.

Settings -> Telecalling Assignment has one rule per "row". The rows are:

    whatsapp, instagram, facebook, telegram, meta_form, other, upload

A lead's row comes from the lead's ORIGIN source (``leads.source``), never from
the message channel it arrived on. See ``SOURCE_TO_ROW``. The ``upload`` row is
the exception: it governs only leads that come in through the Telecalling
upload, and the upload flow passes ``row_override="upload"`` explicitly.

Each rule is ``{"enabled": bool, "mode": "auto"|"pull"|"available", "segments": [...]}``
(the ``upload`` rule has no ``segments`` key, because every uploaded row counts).
"""
import logging

logger = logging.getLogger(__name__)

ROWS: tuple[str, ...] = ("whatsapp", "instagram", "facebook", "telegram", "meta_form", "other", "upload")
SEGMENT_ROWS: tuple[str, ...] = tuple(r for r in ROWS if r != "upload")
MODES: tuple[str, ...] = ("auto", "pull", "available")
VALID_SEGMENTS: tuple[str, ...] = ("A", "B", "C")

# Origin source -> row. Every value the leads_source_check constraint allows must
# have an entry here (enforced by tests/test_assignment_rules.py).
SOURCE_TO_ROW: dict[str, str] = {
    "whatsapp": "whatsapp",
    "upload": "whatsapp",  # Leads-page CSV/broadcast imports
    "manual": "whatsapp",
    "instagram": "instagram",
    "facebook": "facebook",
    "telegram": "telegram",
    "meta_form": "meta_form",
    "indiamart": "other",
    "justdial": "other",
    "website": "other",
    "api": "other",
    "store": "other",
}

_OTHER_DEFAULT_SEGMENTS: list[str] = ["A", "B", "C"]


def resolve_row(source: str | None) -> str | None:
    """Return the assignment row for a lead's origin source.

    NULL or empty source counts as whatsapp. An unknown source returns None
    (the lead is never auto-assigned) and logs a warning.
    """
    if not source:
        return "whatsapp"
    row = SOURCE_TO_ROW.get(source)
    if row is None:
        logger.warning("Unknown lead source %r has no assignment row; not auto-assigning", source)
    return row


def _normalize_segments(value: object) -> list[str] | None:
    """Sorted, de-duplicated segments, or None if value is not a list of valid segments."""
    if not isinstance(value, list):
        return None
    if not all(isinstance(s, str) and s in VALID_SEGMENTS for s in value):
        return None
    return sorted(set(value))


def _legacy_default_rule(cfg: dict, row: str) -> dict:
    """Rule derived from the pre-per-channel telecalling config (keeps old tenants working)."""
    mode = "pull" if cfg.get("assignment_mode") == "pull" else "auto"
    if row == "upload":
        return {"enabled": True, "mode": mode}
    if row == "other":
        # Marketplace enquiries were always assigned, even when Cold.
        return {"enabled": True, "mode": mode, "segments": list(_OTHER_DEFAULT_SEGMENTS)}
    raw = cfg.get("segments")
    valid = raw if isinstance(raw, list) else []
    segments = sorted({s for s in valid if isinstance(s, str) and s in VALID_SEGMENTS})
    return {"enabled": True, "mode": mode, "segments": segments or ["A"]}


def get_channel_rules(cfg: dict) -> dict[str, dict]:
    """Return all 7 row rules for a telecalling config.

    Starts from the legacy default for each row, then overlays a stored
    cfg["channel_rules"][row] when it is a dict. Invalid stored fields are
    replaced by the default for that field.
    """
    stored_all = cfg.get("channel_rules")
    if not isinstance(stored_all, dict):
        stored_all = {}

    result: dict[str, dict] = {}
    for row in ROWS:
        default = _legacy_default_rule(cfg, row)
        rule = dict(default)
        stored = stored_all.get(row)
        if isinstance(stored, dict):
            if isinstance(stored.get("enabled"), bool):
                rule["enabled"] = stored["enabled"]
            if stored.get("mode") in MODES:
                rule["mode"] = stored["mode"]
            if row != "upload":
                segments = _normalize_segments(stored.get("segments"))
                if segments is not None:
                    rule["segments"] = segments
        result[row] = rule
    return result


def validate_channel_rules(raw: object) -> dict[str, dict]:
    """Validate a PATCH payload for channel_rules and return the normalized dict.

    Only the rows present in ``raw`` are returned. Raises ValueError with a
    human-readable message on anything invalid. For the ``upload`` row, any
    ``segments`` key is ignored, since that row has no segments.
    """
    if not isinstance(raw, dict):
        raise ValueError("channel_rules must be an object keyed by row")

    unknown = [k for k in raw if k not in ROWS]
    if unknown:
        raise ValueError(f"Unknown channel rule row(s): {', '.join(sorted(map(str, unknown)))}")

    out: dict[str, dict] = {}
    for row, rule in raw.items():
        if not isinstance(rule, dict):
            raise ValueError(f"Rule for '{row}' must be an object")
        enabled = rule.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError(f"Rule for '{row}' needs enabled as true or false")
        mode = rule.get("mode")
        if mode not in MODES:
            raise ValueError(f"Rule for '{row}' has invalid mode {mode!r}; use one of {', '.join(MODES)}")
        normalized: dict = {"enabled": enabled, "mode": mode}
        if row != "upload":
            segments = rule.get("segments")
            if not isinstance(segments, list):
                raise ValueError(f"Rule for '{row}' needs segments as a list")
            bad = [s for s in segments if s not in VALID_SEGMENTS]
            if bad:
                raise ValueError(f"Rule for '{row}' has invalid segment(s): {bad}; use A, B or C")
            normalized["segments"] = sorted(set(segments))
        out[row] = normalized
    return out


def rule_allows(rule: dict, row: str, segment: str | None) -> bool:
    """True if the rule is enabled and the lead's segment is allowed.

    The upload row ignores segments: every uploaded lead counts.
    """
    if not rule.get("enabled"):
        return False
    if row == "upload":
        return True
    return (segment or "") in rule.get("segments", [])


def legacy_fields(rules: dict[str, dict]) -> dict:
    """Derive the old telecalling_config fields ("segments", "assignment_mode") from the rules.

    segments: sorted union of the segments of enabled segment rows, or ["A"] if empty.
    assignment_mode: "pull" when at least one row is enabled and every enabled row is "pull", else "push".
    """
    union: set[str] = set()
    for row in SEGMENT_ROWS:
        rule = rules.get(row)
        if rule and rule.get("enabled"):
            union.update(rule.get("segments", []))
    enabled_modes = [r.get("mode") for r in rules.values() if r.get("enabled")]
    all_pull = bool(enabled_modes) and all(m == "pull" for m in enabled_modes)
    return {
        "segments": sorted(union) or ["A"],
        "assignment_mode": "pull" if all_pull else "push",
    }


def any_mode(rules: dict[str, dict], mode: str) -> bool:
    """True if some enabled row uses this mode."""
    return any(r.get("enabled") and r.get("mode") == mode for r in rules.values())

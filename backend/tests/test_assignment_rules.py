"""Pure-function tests for app/services/assignment_rules.py (no DB).

Run with:
    cd backend && PYTHONUTF8=1 python -m pytest tests/test_assignment_rules.py -q
"""
import logging
import re
from pathlib import Path

import pytest

from app.services import assignment_rules as ar


# ---------------------------------------------------------------- constants

def test_rows_and_modes_constants():
    assert ar.ROWS == ("whatsapp", "instagram", "facebook", "telegram", "meta_form", "other", "upload")
    assert ar.SEGMENT_ROWS == ("whatsapp", "instagram", "facebook", "telegram", "meta_form", "other")
    assert ar.MODES == ("auto", "pull", "available")
    assert ar.VALID_SEGMENTS == ("A", "B", "C")


def test_source_to_row_maps_every_source_to_a_known_row():
    assert set(ar.SOURCE_TO_ROW.values()) <= set(ar.SEGMENT_ROWS)


# ---------------------------------------------------------------- resolve_row

@pytest.mark.parametrize(
    "source, row",
    [
        ("whatsapp", "whatsapp"),
        ("upload", "whatsapp"),
        ("manual", "whatsapp"),
        ("instagram", "instagram"),
        ("facebook", "facebook"),
        ("telegram", "telegram"),
        ("meta_form", "meta_form"),
        ("indiamart", "other"),
        ("justdial", "other"),
        ("website", "other"),
        ("api", "other"),
        ("store", "other"),
    ],
)
def test_resolve_row_maps_each_source(source, row):
    assert ar.resolve_row(source) == row


@pytest.mark.parametrize("source", [None, ""])
def test_resolve_row_null_or_empty_is_whatsapp(source):
    assert ar.resolve_row(source) == "whatsapp"


def test_resolve_row_unknown_source_returns_none_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.assignment_rules"):
        assert ar.resolve_row("carrier_pigeon") is None
    assert any("carrier_pigeon" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------- get_channel_rules

def test_get_channel_rules_empty_cfg_returns_all_seven_rows_with_defaults():
    rules = ar.get_channel_rules({})
    assert list(rules) == list(ar.ROWS)
    for row in ar.SEGMENT_ROWS:
        if row == "other":
            assert rules[row] == {"enabled": True, "mode": "auto", "segments": ["A", "B", "C"]}
        else:
            assert rules[row] == {"enabled": True, "mode": "auto", "segments": ["A"]}
    assert rules["upload"] == {"enabled": True, "mode": "auto"}
    assert "segments" not in rules["upload"]


def test_get_channel_rules_legacy_pull_mode_and_segments():
    cfg = {"assignment_mode": "pull", "segments": ["B", "C", "Z"]}
    rules = ar.get_channel_rules(cfg)
    assert rules["whatsapp"] == {"enabled": True, "mode": "pull", "segments": ["B", "C"]}
    assert rules["upload"] == {"enabled": True, "mode": "pull"}
    # "other" keeps its always-assign default regardless of legacy segments
    assert rules["other"]["segments"] == ["A", "B", "C"]


def test_get_channel_rules_legacy_segments_all_invalid_falls_back_to_a():
    rules = ar.get_channel_rules({"segments": ["Q", "x"]})
    assert rules["whatsapp"]["segments"] == ["A"]


def test_get_channel_rules_overlays_valid_stored_rule():
    cfg = {"channel_rules": {"instagram": {"enabled": False, "mode": "available", "segments": ["C", "A", "A"]}}}
    rules = ar.get_channel_rules(cfg)
    assert rules["instagram"] == {"enabled": False, "mode": "available", "segments": ["A", "C"]}
    # untouched rows keep their defaults
    assert rules["whatsapp"]["mode"] == "auto"


def test_get_channel_rules_invalid_stored_fields_fall_back_to_defaults():
    cfg = {
        "assignment_mode": "pull",
        "channel_rules": {
            "telegram": {"enabled": "yes", "mode": "round-robin", "segments": ["A", "nope"]},
        },
    }
    rules = ar.get_channel_rules(cfg)
    assert rules["telegram"] == {"enabled": True, "mode": "pull", "segments": ["A"]}


def test_get_channel_rules_ignores_non_dict_stored_rule_and_non_dict_channel_rules():
    rules = ar.get_channel_rules({"channel_rules": {"facebook": "off"}})
    assert rules["facebook"] == {"enabled": True, "mode": "auto", "segments": ["A"]}
    rules = ar.get_channel_rules({"channel_rules": ["nope"]})
    assert rules["facebook"] == {"enabled": True, "mode": "auto", "segments": ["A"]}


def test_get_channel_rules_upload_ignores_stored_segments():
    cfg = {"channel_rules": {"upload": {"enabled": False, "mode": "pull", "segments": ["A"]}}}
    rules = ar.get_channel_rules(cfg)
    assert rules["upload"] == {"enabled": False, "mode": "pull"}


def test_get_channel_rules_does_not_mutate_input():
    cfg = {"channel_rules": {"whatsapp": {"enabled": False, "mode": "pull", "segments": ["A"]}}}
    before = repr(cfg)
    ar.get_channel_rules(cfg)
    assert repr(cfg) == before


# ---------------------------------------------------------------- validate_channel_rules

def test_validate_returns_only_given_rows_normalized():
    out = ar.validate_channel_rules({
        "whatsapp": {"enabled": True, "mode": "auto", "segments": ["C", "A", "A"]},
        "upload": {"enabled": False, "mode": "pull"},
    })
    assert out == {
        "whatsapp": {"enabled": True, "mode": "auto", "segments": ["A", "C"]},
        "upload": {"enabled": False, "mode": "pull"},
    }


def test_validate_allows_empty_segments_for_segment_row():
    out = ar.validate_channel_rules({"meta_form": {"enabled": True, "mode": "pull", "segments": []}})
    assert out["meta_form"]["segments"] == []


def test_validate_upload_drops_segments_key():
    out = ar.validate_channel_rules({"upload": {"enabled": True, "mode": "auto", "segments": ["A"]}})
    assert out == {"upload": {"enabled": True, "mode": "auto"}}


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("nope", "object"),
        (["whatsapp"], "object"),
        ({"fax": {"enabled": True, "mode": "auto", "segments": ["A"]}}, "Unknown"),
        ({"whatsapp": "on"}, "object"),
        ({"whatsapp": {"mode": "auto", "segments": ["A"]}}, "enabled"),
        ({"whatsapp": {"enabled": 1, "mode": "auto", "segments": ["A"]}}, "enabled"),
        ({"whatsapp": {"enabled": True, "segments": ["A"]}}, "mode"),
        ({"whatsapp": {"enabled": True, "mode": "round-robin", "segments": ["A"]}}, "mode"),
        ({"whatsapp": {"enabled": True, "mode": "auto"}}, "segments"),
        ({"whatsapp": {"enabled": True, "mode": "auto", "segments": "A"}}, "segments"),
        ({"whatsapp": {"enabled": True, "mode": "auto", "segments": ["D"]}}, "invalid segment"),
    ],
)
def test_validate_rejects_invalid_input(raw, fragment):
    with pytest.raises(ValueError) as exc:
        ar.validate_channel_rules(raw)
    assert fragment.lower() in str(exc.value).lower()


# ---------------------------------------------------------------- rule_allows

def test_rule_allows_segment_rows_need_enabled_and_segment():
    rule = {"enabled": True, "mode": "auto", "segments": ["A", "B"]}
    assert ar.rule_allows(rule, "whatsapp", "A") is True
    assert ar.rule_allows(rule, "whatsapp", "C") is False
    assert ar.rule_allows(rule, "whatsapp", None) is False


def test_rule_allows_disabled_rule_never_allows():
    rule = {"enabled": False, "mode": "auto", "segments": ["A"]}
    assert ar.rule_allows(rule, "whatsapp", "A") is False
    assert ar.rule_allows({"enabled": False, "mode": "auto"}, "upload", None) is False


def test_rule_allows_upload_ignores_segment():
    rule = {"enabled": True, "mode": "auto"}
    assert ar.rule_allows(rule, "upload", None) is True
    assert ar.rule_allows(rule, "upload", "C") is True


# ---------------------------------------------------------------- legacy_fields

def test_legacy_fields_union_of_enabled_segment_rows():
    rules = {
        "whatsapp": {"enabled": True, "mode": "auto", "segments": ["A"]},
        "instagram": {"enabled": True, "mode": "auto", "segments": ["C"]},
        "facebook": {"enabled": False, "mode": "auto", "segments": ["B"]},
        "upload": {"enabled": True, "mode": "auto"},
    }
    assert ar.legacy_fields(rules) == {"segments": ["A", "C"], "assignment_mode": "push"}


def test_legacy_fields_segments_fall_back_to_a_when_empty():
    rules = {"whatsapp": {"enabled": True, "mode": "pull", "segments": []}}
    assert ar.legacy_fields(rules)["segments"] == ["A"]
    rules = {"whatsapp": {"enabled": False, "mode": "pull", "segments": ["B"]}}
    assert ar.legacy_fields(rules)["segments"] == ["A"]


def test_legacy_fields_pull_only_when_every_enabled_row_is_pull():
    rules = {
        "whatsapp": {"enabled": True, "mode": "pull", "segments": ["A"]},
        "other": {"enabled": True, "mode": "pull", "segments": ["A"]},
        "instagram": {"enabled": False, "mode": "auto", "segments": ["A"]},
        "upload": {"enabled": True, "mode": "pull"},
    }
    assert ar.legacy_fields(rules)["assignment_mode"] == "pull"


def test_legacy_fields_push_when_any_enabled_row_is_not_pull():
    rules = {
        "whatsapp": {"enabled": True, "mode": "pull", "segments": ["A"]},
        "other": {"enabled": True, "mode": "available", "segments": ["A"]},
    }
    assert ar.legacy_fields(rules)["assignment_mode"] == "push"


def test_legacy_fields_push_when_no_row_enabled():
    rules = {"whatsapp": {"enabled": False, "mode": "pull", "segments": ["A"]}}
    assert ar.legacy_fields(rules)["assignment_mode"] == "push"


# ---------------------------------------------------------------- any_mode

def test_any_mode_true_only_for_enabled_rows():
    rules = {
        "whatsapp": {"enabled": False, "mode": "available", "segments": ["A"]},
        "upload": {"enabled": True, "mode": "pull"},
    }
    assert ar.any_mode(rules, "pull") is True
    assert ar.any_mode(rules, "available") is False
    assert ar.any_mode(rules, "auto") is False


# ---------------------------------------------------------------- migration guard

def _latest_source_check_values() -> list[str]:
    """Quoted source values from the last leads_source_check definition in the migrations."""
    migrations = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    last_text = None
    last_pos = None
    for path in sorted(migrations.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        pos = text.rfind("leads_source_check")
        if pos != -1:
            last_text, last_pos = text, pos
    assert last_text is not None, "no migration defines leads_source_check"
    tail = last_text[last_pos:]
    block = tail[tail.index("[") : tail.index("]") + 1]
    return re.findall(r"'([^']+)'", block)


def test_every_lead_source_in_latest_constraint_has_a_row():
    """GUARD: a new leads.source value must be decided in SOURCE_TO_ROW before it ships."""
    values = _latest_source_check_values()
    assert values, "could not parse leads_source_check values"
    missing = sorted(set(values) - set(ar.SOURCE_TO_ROW))
    assert not missing, (
        f"New lead source(s) {missing}: decide which assignment row they belong to "
        "in app/services/assignment_rules.py SOURCE_TO_ROW"
    )

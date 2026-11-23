"""v9.2 #21 Call IQ rules: hours, daily limit, mask_phone, SIM/cloud per person, break limit, and /initiate."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import call_rules as cr

UTC = timezone.utc


class _Res:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _Q:
    def __init__(self, db, table):
        self.db, self.table_name, self.op, self.payload, self.filters = db, table, "select", None, {}

    def select(self, *a, **k):
        self.op = "select"
        return self

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def upsert(self, p, **k):
        self.op, self.payload = "upsert", p
        return self

    def __getattr__(self, name):  # eq / gte / in_ / maybe_single / limit ...
        def f(*a, **k):
            if name == "eq":
                self.filters[a[0]] = a[1]
            return self
        return f

    def execute(self):
        self.db.ops.append((self.table_name, self.op, self.payload, dict(self.filters)))
        data = self.db.rows.get(self.table_name)
        if self.table_name == "call_logs":
            return _Res(data or [], count=self.db.call_count)
        return _Res(data)


class FakeDB:
    def __init__(self, rows=None, call_count=0):
        self.rows, self.ops, self.call_count = rows or {}, [], call_count

    def table(self, name):
        return _Q(self, name)


def _ist(h, m=0):
    """A UTC instant that is h:m on 2026-11-23 in India."""
    return datetime(2026, 11, 23, h, m, tzinfo=cr.IST).astimezone(UTC)


def _rules_row(**kw):
    import json
    return {"app_settings": {"value": json.dumps(kw)}}


class MaskPhoneTests(unittest.TestCase):
    def test_masks_first_two_last_three(self):
        self.assertEqual(cr.mask_phone("9876543210"), "98•••••210")
        self.assertEqual(cr.mask_phone("+919876543210"), "98•••••210")

    def test_short_or_empty(self):
        self.assertEqual(cr.mask_phone(""), "")
        self.assertEqual(cr.mask_phone(None), "")
        self.assertEqual(cr.mask_phone("12345"), "•••••")


class RulesTests(unittest.TestCase):
    def test_defaults_when_nothing_saved(self):
        self.assertEqual(cr.get_rules(FakeDB(), "t"), cr.DEFAULT_RULES)

    def test_bad_values_fall_back(self):
        out = cr.clean_rules({"calling_start": "25:00", "daily_limit": -3, "break_limit_minutes": "x"})
        self.assertEqual(out, cr.DEFAULT_RULES)

    def test_end_before_start_resets_hours(self):
        out = cr.clean_rules({"calling_start": "20:00", "calling_end": "08:00"})
        self.assertEqual((out["calling_start"], out["calling_end"]), ("09:00", "21:00"))

    def test_validate_messages(self):
        good = dict(cr.DEFAULT_RULES)
        self.assertIsNone(cr.validate_rules(good))
        self.assertIn("end after", cr.validate_rules({**good, "calling_end": "08:00"}))
        self.assertIn("daily limit", cr.validate_rules({**good, "daily_limit": 0}))
        self.assertIn("break limit", cr.validate_rules({**good, "break_limit_minutes": 999}))

    def test_clock_words_and_message(self):
        self.assertEqual(cr.hours_message(cr.DEFAULT_RULES), "Calling hours are 9 AM to 9 PM")
        self.assertEqual(cr.clock_words("21:30"), "9:30 PM")

    def test_hides_numbers_only_for_callers(self):
        db = FakeDB(_rules_row(hide_numbers_for_callers=True))
        with patch.object(cr, "effective_calling_mode", return_value="telecmi"):
            self.assertTrue(cr.hides_numbers(db, "t", {"role": "caller"}))
        with patch.object(cr, "effective_calling_mode", return_value="sim_basic"):
            self.assertFalse(cr.hides_numbers(db, "t", {"role": "caller"}))  # a SIM phone needs the real number
        self.assertFalse(cr.hides_numbers(db, "t", {"role": "owner"}))
        self.assertFalse(cr.hides_numbers(FakeDB(), "t", {"role": "caller"}))


class PreDialTests(unittest.TestCase):
    def test_owner_never_blocked(self):
        self.assertIsNone(cr.pre_dial_block(FakeDB(), "t", role="owner", caller_id="c", now=_ist(23)))

    def test_caller_blocked_outside_hours(self):
        msg = cr.pre_dial_block(FakeDB(), "t", role="caller", caller_id="c", now=_ist(22))
        self.assertEqual(msg, "Calling hours are 9 AM to 9 PM")
        self.assertIsNotNone(cr.pre_dial_block(FakeDB(), "t", role="caller", caller_id="c", now=_ist(8, 59)))

    def test_caller_allowed_inside_hours_and_at_start(self):
        self.assertIsNone(cr.pre_dial_block(FakeDB(), "t", role="caller", caller_id="c", now=_ist(9)))
        self.assertIsNone(cr.pre_dial_block(FakeDB(), "t", role="caller", caller_id="c", now=_ist(20, 59)))
        self.assertIsNotNone(cr.pre_dial_block(FakeDB(), "t", role="caller", caller_id="c", now=_ist(21)))

    def test_hours_off_allows_any_time(self):
        db = FakeDB(_rules_row(calling_hours_on=False))
        self.assertIsNone(cr.pre_dial_block(db, "t", role="caller", caller_id="c", now=_ist(23)))

    def test_daily_limit(self):
        rows = _rules_row(daily_limit_on=True, daily_limit=5)
        self.assertIsNone(cr.pre_dial_block(FakeDB(rows, call_count=4), "t", role="caller", caller_id="c", now=_ist(12)))
        self.assertEqual(
            cr.pre_dial_block(FakeDB(rows, call_count=5), "t", role="caller", caller_id="c", now=_ist(12)),
            "Daily call limit reached",
        )

    def test_limit_off_by_default(self):
        self.assertIsNone(cr.pre_dial_block(FakeDB(call_count=9999), "t", role="caller", caller_id="c", now=_ist(12)))

    def test_failed_read_never_blocks(self):
        db = FakeDB(_rules_row(daily_limit_on=True, daily_limit=5))
        with patch.object(cr, "calls_made_today", side_effect=RuntimeError("down")):
            self.assertIsNone(cr.pre_dial_block(db, "t", role="caller", caller_id="c", now=_ist(12)))

    def test_rules_read_failure_uses_defaults(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("down")
        self.assertIsNotNone(cr.pre_dial_block(db, "t", role="caller", caller_id="c", now=_ist(23)))
        self.assertIsNone(cr.pre_dial_block(db, "t", role="caller", caller_id="c", now=_ist(12)))

    def test_ist_day_start(self):
        self.assertEqual(cr.ist_day_start_utc(_ist(1)), datetime(2026, 11, 22, 18, 30, tzinfo=UTC))


class EffectiveModeTests(unittest.TestCase):
    def test_own_choice_wins(self):
        sim = FakeDB({"callers": {"calling_mode": "sim"}})
        cloud = FakeDB({"callers": {"calling_mode": "cloud"}})
        self.assertEqual(cr.effective_calling_mode(sim, "t", "c", business_provider="telecmi"), "sim_basic")
        self.assertEqual(cr.effective_calling_mode(cloud, "t", "c", business_provider="sim_basic"), "telecmi")

    def test_default_follows_business(self):
        db = FakeDB({"callers": {"calling_mode": "business_default"}})
        self.assertEqual(cr.effective_calling_mode(db, "t", "c", business_provider="sim_basic"), "sim_basic")
        self.assertEqual(cr.effective_calling_mode(db, "t", "c", business_provider="telecmi"), "telecmi")
        self.assertEqual(cr.effective_calling_mode(db, "t", None, business_provider="sim_basic"), "sim_basic")

    def test_missing_column_follows_business(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("column calling_mode does not exist")
        self.assertEqual(cr.effective_calling_mode(db, "t", "c", business_provider="telecmi"), "telecmi")


class BreakLimitTests(unittest.TestCase):
    NOW = datetime(2026, 11, 23, 6, 0, tzinfo=UTC)

    def _db(self, started_min_ago, sent=None, **rules):
        c = {"id": "c1", "tenant_id": "t", "name": "Priya",
             "status_changed_at": (self.NOW - timedelta(minutes=started_min_ago)).isoformat(),
             "break_alert_sent_at": sent}
        rows = {"callers": [c]}
        rows.update(_rules_row(**rules) if rules else {})
        return FakeDB(rows)

    def _run(self, db):
        with patch("app.services.call_alerts.admin_user_ids", return_value=["owner-1"]), \
             patch("app.services.notify.notify_user") as notify, \
             patch("app.services.caller_leave.start_due_leaves", return_value=0):
            return cr.check_break_limits(db, self.NOW), notify

    def test_alert_after_limit(self):
        n, notify = self._run(self._db(31))
        self.assertEqual(n, 1)
        self.assertEqual(notify.call_args.args[1], "owner-1")
        self.assertIn("31 minutes", notify.call_args.args[4])

    def test_no_alert_before_limit(self):
        n, notify = self._run(self._db(10))
        self.assertEqual(n, 0)
        notify.assert_not_called()

    def test_once_per_break(self):
        sent = (self.NOW - timedelta(minutes=2)).isoformat()
        n, _ = self._run(self._db(40, sent=sent))
        self.assertEqual(n, 0)

    def test_new_break_alerts_again(self):
        old = (self.NOW - timedelta(hours=3)).isoformat()
        n, _ = self._run(self._db(40, sent=old))
        self.assertEqual(n, 1)

    def test_zero_switches_it_off(self):
        n, _ = self._run(self._db(500, break_limit_minutes=0))
        self.assertEqual(n, 0)

    def test_tenant_limit_is_used(self):
        n, _ = self._run(self._db(50, break_limit_minutes=60))
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()

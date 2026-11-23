"""Reports (Batch H #16): the shared pieces. Days, who may see money, the plain sentence helpers."""
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase
from app.services import reports_common as rc


def test_period_bounds_are_india_midnights_in_utc():
    p = rc.Period(date(2026, 10, 1), date(2026, 10, 31))
    assert p.days == 31
    assert p.start_iso == "2026-09-30T18:30:00+00:00"
    assert p.end_iso == "2026-10-31T18:30:00+00:00"  # exclusive: midnight after the last picked day
    assert p.end_excl_day == date(2026, 11, 1)


def test_previous_period_is_same_length_right_before():
    p = rc.Period(date(2026, 10, 8), date(2026, 10, 14))
    assert p.previous() == rc.Period(date(2026, 10, 1), date(2026, 10, 7))


def test_whole_months_only_for_exact_months():
    assert rc.Period(date(2026, 10, 1), date(2026, 10, 31)).whole_months() == ["2026-10"]
    assert rc.Period(date(2026, 9, 1), date(2026, 10, 31)).whole_months() == ["2026-09", "2026-10"]
    assert rc.Period(date(2026, 10, 2), date(2026, 10, 31)).whole_months() is None
    assert rc.Period(date(2026, 10, 1), date(2026, 10, 30)).whole_months() is None


def test_resolve_period_defaults_to_last_30_days():
    p = rc.resolve_period(None, None, now=date(2026, 11, 23))
    assert (p.start, p.end) == (date(2026, 10, 25), date(2026, 11, 23))


def test_resolve_period_rejects_bad_input_in_plain_words():
    for args in [("nope", "2026-10-02"), ("2026-10-05", "2026-10-02"), ("2024-01-01", "2026-10-02")]:
        with pytest.raises(HTTPException) as e:
            rc.resolve_period(*args)
        assert e.value.status_code == 400
        assert e.value.detail


def test_want_before():
    assert rc.want_before(None) and rc.want_before("previous") and not rc.want_before("off")
    with pytest.raises(HTTPException):
        rc.want_before("sideways")


def test_flags_follow_permissions():
    owner = rc.flags_for({"role": "owner", "permissions": []})
    assert (owner.sees_money, owner.sees_profit) == (True, True)
    orders = rc.flags_for({"role": "staff", "permissions": ["deals.view"]})
    assert (orders.sees_money, orders.sees_profit) == (True, False)
    plain = rc.flags_for({"role": "staff", "permissions": ["analytics.view"]})
    assert (plain.sees_money, plain.sees_profit) == (False, False)
    books_only = rc.flags_for({"role": "staff", "permissions": ["purchases.view"]})
    assert books_only.sees_money is False and books_only.sees_profit is False


def test_strip_money_leaves_keys_out_not_zero():
    payload = {"period": {"orders": 3, "sales_paise": 500, "profit_paise": 100, "money_back": 2.0},
               "rows": [{"name": "x", "spend_paise": 9, "chats": 4}]}
    none = rc.strip_money(payload, rc.Flags(False, False))
    assert none == {"period": {"orders": 3}, "rows": [{"name": "x", "chats": 4}]}
    some = rc.strip_money(payload, rc.Flags(True, False))
    assert "sales_paise" in some["period"] and "profit_paise" not in some["period"]
    assert some["rows"][0]["spend_paise"] == 9
    assert rc.strip_money(payload, rc.Flags(True, True)) == payload


def test_finish_marks_hidden_and_keeps_listed_keys():
    out = rc.finish({"period": {"sales_paise": 1}, "cost_coverage": {"with_cost_paise": 1}}, rc.Flags(False, False), keep=("cost_coverage",))
    assert out["money_hidden"] is True and out["period"] == {} and out["cost_coverage"] == {"with_cost_paise": 1}
    assert rc.finish({"period": {}}, rc.Flags(True, False))["profit_hidden"] is True
    full = rc.finish({"period": {}}, rc.Flags(True, True))
    assert "money_hidden" not in full and "profit_hidden" not in full


def test_safe_cell_defuses_formulas():
    assert rc.safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert rc.safe_cell("+91") == "'+91" and rc.safe_cell("Asha") == "Asha" and rc.safe_cell(5) == 5


def test_chunks_and_text_helpers():
    assert [len(c) for c in rc.chunks(list(range(5)), 2)] == [2, 2, 1]
    assert rc.plural(1, "chat") == "1 chat" and rc.plural(2, "chat") == "2 chats"
    assert rc.plural(2, "person", "people") == "2 people"
    assert rc.vs_before(10, 4) == "up 6 from before" and rc.vs_before(3, 4) == "down 1 from before"
    assert rc.vs_before(4, 4) == "same as before" and rc.vs_before(4, None) == ""
    assert rc.vs_before(150000, 100000, "paise") == "up ₹500 from before"
    assert rc.count_phrase(42, 34, "new chat") == "42 new chats, up 8 from before"
    assert rc.count_phrase(1, None, "new chat") == "1 new chat"
    assert rc.sentence(["a b", "", "c"], "none") == "A b; c." and rc.sentence([], "none") == "none"
    assert rc.money(1840000) == "₹18,400"


def test_paged_reads_past_the_1000_row_cap():
    db = FakeSupabase()
    for i in range(2350):
        db.add("things", tenant_id="t", n=i)
    rows = rc.paged(lambda: db.table("things").select("id,n").eq("tenant_id", "t"))
    assert len(rows) == 2350


def test_safe_returns_default_on_error():
    def boom():
        raise RuntimeError("relation does not exist")
    assert rc.safe(boom, [], "thing") == []
    assert rc.safe(lambda: 5, 0, "thing") == 5


def test_build_and_run_report_use_the_module_and_strip():
    class Mod:
        @staticmethod
        def compute(db, t, period, flags):
            return {"orders": 2, "sales_paise": 900}, {"rows": [{"id": "a", "spend_paise": 4}]}

        @staticmethod
        def in_short(now, before):
            return f"{now.get('orders')} orders; before {before.get('orders') if before else None}"
    p = rc.Period(date(2026, 10, 1), date(2026, 10, 7))
    out = rc.run_report(Mod, None, "t", p, True, rc.Flags(False, False))
    assert out["period"] == {"orders": 2} and out["before"] == {"orders": 2} and out["rows"] == [{"id": "a"}]
    assert out["money_hidden"] is True and out["in_short"] == "2 orders; before 2"
    off = rc.run_report(Mod, None, "t", p, False, rc.Flags(True, True))
    assert off["before"] is None and off["period"]["sales_paise"] == 900


def test_today_ist_is_a_date():
    assert isinstance(rc.today_ist(), date)

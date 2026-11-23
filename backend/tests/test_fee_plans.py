"""Fee instalments (services/fee_plans.py): the split, the plan, marking a part paid once with a receipt,
and the daily reminder run (claim before send, never to people who said stop, calling after the late one)."""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import fee_plans as fp
from tests.fake_supabase import _UNIQUE, FakeSupabase

T = "tenant-1"
_UNIQUE["fee_plan_reminders"] = [("fee_plan_id", "part_index", "kind")]
_UNIQUE["fee_plan_payments"] = [("fee_plan_id", "part_index")]
TODAY = datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)  # 10:30 IST on 1 Dec
TEMPLATE = {"name": "fee_reminder", "language": "en", "body_text": "Hi {{1}} {{2}} {{3}} {{4}} {{5}}"}


def world(parts, *, total=900000, lead=None, parent=None):
    db = FakeSupabase()
    db.add("tenants", id=T, name="Bright Academy")
    db.add("leads", id="L1", tenant_id=T, name="Ravi Kumar", phone="+919876543210", **(lead or {}))
    db.add("catalog_items", id="C1", tenant_id=T, name="Python", item_type="course")
    db.add("course_batches", id="B1", tenant_id=T, course_item_id="C1", name="Weekend batch")
    db.add("deals", id="D1", tenant_id=T, lead_id="L1", deal_number=7, stage="quoted", total_paise=total, paid_paise=0)
    db.add("batch_enrolments", id="E1", tenant_id=T, batch_id="B1", lead_id="L1", deal_id="D1", status="active",
           student_name="Ravi Kumar", phone="+919876543210", parent_phone=parent)
    plan = db.add("fee_plans", id="P1", tenant_id=T, deal_id="D1", parts=parts)
    return db, plan


THREE = [{"due_on": "2026-12-01", "amount_paise": 300000}, {"due_on": "2027-01-01", "amount_paise": 300000},
         {"due_on": "2027-02-01", "amount_paise": 300000}]


# ── the parts ────────────────────────────────────────────────────────────────────

def test_split_puts_the_leftover_paise_on_the_first_part():
    parts = fp.split_parts(1000001, 3, date(2026, 12, 1))
    assert sum(p["amount_paise"] for p in parts) == 1000001
    assert [p["due_on"] for p in parts] == ["2026-12-01", "2026-12-31", "2027-01-30"]
    assert parts[0]["amount_paise"] == 333335 and parts[1]["amount_paise"] == 333333


def test_parts_must_add_up_to_the_fee_and_are_sorted():
    ok = fp.clean_parts([{"due_on": "2027-01-01", "amount_paise": 400}, {"due_on": "2026-12-01", "amount_paise": 600}], 1000)
    assert [p["amount_paise"] for p in ok] == [600, 400]
    with pytest.raises(fp.FeeError, match="add up"):
        fp.clean_parts([{"due_on": "2026-12-01", "amount_paise": 999}], 1000)
    with pytest.raises(fp.FeeError):
        fp.clean_parts([{"due_on": "not a date", "amount_paise": 1000}], 1000)
    with pytest.raises(fp.FeeError):
        fp.clean_parts([], 1000)


def test_plan_can_be_replaced_until_a_part_is_paid():
    db, _ = world(THREE)
    new = fp.create_plan(db, T, "D1", [{"due_on": "2026-12-05", "amount_paise": 900000}])
    assert len(db.rows("fee_plans")) == 1 and db.rows("fee_plans")[0]["parts"] == new["parts"]
    db.add("fee_plan_payments", tenant_id=T, fee_plan_id="P1", part_index=0, paid_paise=900000, method="cash", receipt_no="x")
    with pytest.raises(fp.FeeError, match="already paid"):
        fp.create_plan(db, T, "D1", THREE)


# ── mark a part paid ─────────────────────────────────────────────────────────────

def test_mark_part_paid_records_the_money_once_and_gives_a_receipt():
    db, _ = world(THREE)
    with patch("app.services.deals.record_payment", return_value={"status": "recorded", "won": False}) as rec:
        out = fp.mark_part_paid(db, T, "P1", 0, method="upi", by_user_id="u-1")
        with pytest.raises(fp.FeeError) as again:
            fp.mark_part_paid(db, T, "P1", 0, method="upi")
    assert again.value.status_code == 409
    rec.assert_called_once()
    assert rec.call_args.args[:4] == (T, "D1", 300000, "upi")
    assert out["receipt_no"] == "FEE-0007-1" and out["part_number"] == 1 and out["parts_total"] == 3
    assert out["student_name"] == "Ravi Kumar" and out["course_name"] == "Python" and out["batch_name"] == "Weekend batch"
    assert out["balance_paise"] == 600000
    assert len(db.rows("fee_plan_payments")) == 1


def test_refused_payment_leaves_the_part_unpaid():
    db, _ = world(THREE)
    with patch("app.services.deals.record_payment", return_value={"status": "over"}):
        with pytest.raises(fp.FeeError, match="less left to pay"):
            fp.mark_part_paid(db, T, "P1", 1, method="cash")
    assert db.rows("fee_plan_payments") == []
    with patch("app.services.deals.record_payment", side_effect=RuntimeError("boom")):
        with pytest.raises(fp.FeeError, match="try again"):
            fp.mark_part_paid(db, T, "P1", 1, method="cash")
    assert db.rows("fee_plan_payments") == []


def test_mark_part_paid_checks_method_part_and_tenant():
    db, _ = world(THREE)
    with pytest.raises(fp.FeeError):
        fp.mark_part_paid(db, T, "P1", 0, method="razorpay")
    with pytest.raises(fp.FeeError) as e:
        fp.mark_part_paid(db, T, "P1", 9, method="cash")
    assert e.value.status_code == 404
    with pytest.raises(fp.FeeError) as e:
        fp.mark_part_paid(db, "other-tenant", "P1", 0, method="cash")
    assert e.value.status_code == 404


def test_plan_view_shows_paid_and_late_parts():
    db, plan = world([{"due_on": "2020-01-01", "amount_paise": 500000}, {"due_on": "2020-02-01", "amount_paise": 400000}])
    db.add("fee_plan_payments", id="PAY1", tenant_id=T, fee_plan_id="P1", part_index=0, paid_paise=500000,
           method="cash", receipt_no="FEE-0007-1", paid_at="2020-01-02")
    view = fp.plan_view(db, T, plan)
    assert [p["paid"] for p in view["parts"]] == [True, False]
    assert [p["late"] for p in view["parts"]] == [False, True]
    assert view["paid_paise"] == 500000 and view["total_paise"] == 900000


# ── the reminder switch ──────────────────────────────────────────────────────────

def test_switching_reminders_on_needs_an_approved_template():
    db, _ = world(THREE)
    with patch("app.config_dynamic.get_setting", return_value=None), patch("app.config_dynamic.save_setting") as save:
        with pytest.raises(fp.FeeError, match="approved"):
            fp.set_reminders(db, T, True)
        save.assert_not_called()
        db.add("message_templates", tenant_id=T, name="fee_reminder", status="APPROVED")
        fp.set_reminders(db, T, True)
        save.assert_called_once_with("fee_reminders_enabled", "true", tenant_id=T)


def test_kind_for_has_one_day_of_catch_up():
    assert [fp.kind_for(d) for d in (-4, -3, -2, -1, 0, 1, 2, 3, 4, 5)] == \
        [None, "before", "before", None, "due", "due", None, "late", "late", None]


# ── the daily run ────────────────────────────────────────────────────────────────

def run(db, **kw):
    import asyncio
    send = kw.pop("send", AsyncMock(return_value=("wamid-1", "Hi Ravi")))
    calling = kw.pop("calling", patch("app.services.customer_calling.send_to_calling", return_value={}))
    with patch.object(fp, "_tenant_ready", AsyncMock(return_value=kw.pop("template", TEMPLATE))), \
            patch.object(fp, "_send_one", send), calling as call:
        sent = asyncio.run(fp.send_fee_reminders(db, now=kw.pop("now", TODAY)))
    return sent, send, call


def test_reminder_goes_out_once_on_the_due_day_and_a_rerun_does_nothing():
    db, _ = world(THREE)
    sent, send, _ = run(db)
    assert sent == 1
    phone, values = send.call_args.args[3:]
    assert phone == "+919876543210" and values == ["Ravi", "Bright Academy", "₹3,000", "Weekend batch", "1 Dec"]
    assert [(r["part_index"], r["kind"], r["wamid"]) for r in db.rows("fee_plan_reminders")] == [(0, "due", "wamid-1")]
    assert db.rows("messages")[0]["lead_id"] == "L1"
    again, send2, _ = run(db)
    assert again == 0 and send2.await_count == 0


def test_a_claimed_reminder_is_never_sent_again_even_by_an_overlapping_run():
    db, _ = world(THREE)
    db.add("fee_plan_reminders", tenant_id=T, fee_plan_id="P1", part_index=0, kind="due")
    sent, send, _ = run(db)
    assert sent == 0 and send.await_count == 0


def test_a_send_that_raised_releases_the_claim_but_one_with_no_message_id_keeps_it():
    db, _ = world(THREE)
    sent, _, _ = run(db, send=AsyncMock(side_effect=RuntimeError("meta down")))
    assert sent == 0 and db.rows("fee_plan_reminders") == []
    # No message id: we cannot tell if it left, so the claim stays and the next run does not send again.
    sent, _, _ = run(db, send=AsyncMock(return_value=None))
    assert sent == 0 and len(db.rows("fee_plan_reminders")) == 1
    again, send, _ = run(db)
    assert again == 0 and send.await_count == 0


def test_three_days_before_goes_to_the_parents_number():
    db, _ = world(THREE, parent="+919811111111")
    sent, send, _ = run(db, now=datetime(2026, 11, 28, 5, 0, tzinfo=timezone.utc))
    assert sent == 1 and send.call_args.args[3] == "+919811111111"
    assert db.rows("fee_plan_reminders")[0]["kind"] == "before"


@pytest.mark.parametrize("lead", [{"opted_out": True}, {"do_not_call": True}, {"blocked_at": "2026-01-01"}])
def test_nothing_goes_to_someone_who_said_stop_or_is_blocked(lead):
    db, _ = world(THREE, lead=lead)
    sent, send, call = run(db)
    assert sent == 0 and send.await_count == 0 and db.rows("fee_plan_reminders") == []
    call.assert_not_called()


def test_a_parent_who_opted_out_is_not_messaged():
    db, _ = world(THREE, parent="+919811111111")
    db.add("leads", id="L2", tenant_id=T, phone="+919811111111", opted_out=True)
    sent, send, _ = run(db)
    assert sent == 0 and send.await_count == 0


def test_the_late_reminder_sends_the_student_to_calling():
    db, _ = world(THREE)
    sent, _, call = run(db, now=datetime(2026, 12, 4, 5, 0, tzinfo=timezone.utc))
    assert sent == 1 and db.rows("fee_plan_reminders")[0]["kind"] == "late"
    call.assert_called_once()
    assert call.call_args.args[2] == ["L1"] and call.call_args.kwargs == {"reason": "fee_late"}


def test_paid_parts_cancelled_orders_and_other_days_get_nothing():
    db, _ = world(THREE)
    db.add("fee_plan_payments", tenant_id=T, fee_plan_id="P1", part_index=0, paid_paise=300000, method="cash", receipt_no="r")
    assert run(db)[0] == 0
    db2, _ = world(THREE)
    db2.rows("deals")[0]["stage"] = "lost"
    assert run(db2)[0] == 0
    db3, _ = world(THREE)
    assert run(db3, now=datetime(2026, 12, 10, 5, 0, tzinfo=timezone.utc))[0] == 0


def test_switched_off_business_gets_nothing():
    db, _ = world(THREE)
    sent, send, _ = run(db, template=None)
    assert sent == 0 and send.await_count == 0 and db.rows("fee_plan_reminders") == []


# ── review fixes ─────────────────────────────────────────────────────────────────

def test_money_put_on_the_order_elsewhere_stops_the_reminders_and_counts_in_the_plan():
    # 1. Orders page / Razorpay money never reaches fee_plan_payments, but the part is paid.
    db, plan = world(THREE)
    db.rows("deals")[0]["paid_paise"] = 300000
    sent, send, call = run(db)
    assert sent == 0 and send.await_count == 0 and db.rows("fee_plan_reminders") == []
    view = fp.plan_view(db, T, plan)
    assert [p["paid"] for p in view["parts"]] == [True, False, False]
    assert view["parts"][0]["on_order"] is True and view["parts"][0]["payment_id"] is None
    with pytest.raises(fp.FeeError, match="already paid on the order"):
        fp.mark_part_paid(db, T, "P1", 0, method="cash")
    # a late part that was paid elsewhere does not push the student to the call list
    db2, _ = world(THREE)
    db2.rows("deals")[0]["paid_paise"] = 300000
    sent, _, call = run(db2, now=datetime(2026, 12, 4, 5, 0, tzinfo=timezone.utc))
    assert sent == 0 and call.call_count == 0
    # a fully paid (won) order gets nothing at all
    db3, _ = world(THREE)
    db3.rows("deals")[0].update(stage="won", paid_paise=900000)
    assert run(db3)[0] == 0


def test_plan_paid_money_is_not_counted_twice_when_covering_parts():
    parts = [{"amount_paise": 300000}, {"amount_paise": 300000}, {"amount_paise": 300000}]
    # part 3 was marked in the plan (300000); the order shows 600000 paid, so 300000 came from elsewhere
    assert fp.covered_parts(parts, {2: 300000}, 600000) == {0, 2}
    assert fp.covered_parts(parts, {}, 0) == set()


def test_receipt_balance_counts_money_paid_on_the_order():
    db, _ = world(THREE)
    with patch("app.services.deals.record_payment", return_value={"status": "recorded", "won": False}):
        db.rows("deals")[0]["paid_paise"] = 500000  # 200000 more arrived on the Orders page
        out = fp.mark_part_paid(db, T, "P1", 1, method="cash")
    assert out["balance_paise"] == 400000


def test_error_after_the_money_was_written_keeps_the_claim_and_succeeds():
    # 2. deals._insert_payment wrote deal_payments, then ensure_invoice raised: a retry must not charge again.
    db, _ = world(THREE)
    note = "Fee part 1 of 3 (FEE-0007-1)"

    def boom(*a, **k):
        db.add("deal_payments", tenant_id=T, deal_id="D1", amount_paise=300000, method="cash", note=note)
        raise RuntimeError("invoice number failed")

    with patch("app.services.deals.record_payment", side_effect=boom) as rec:
        out = fp.mark_part_paid(db, T, "P1", 0, method="cash")
        assert out["receipt_no"] == "FEE-0007-1" and len(db.rows("fee_plan_payments")) == 1
        with pytest.raises(fp.FeeError) as again:
            fp.mark_part_paid(db, T, "P1", 0, method="cash")
    assert again.value.status_code == 409 and rec.call_count == 1
    # also when only the order's paid total moved
    db2, _ = world(THREE)

    def boom2(*a, **k):
        db2.rows("deals")[0]["paid_paise"] = 300000
        raise RuntimeError("x")

    with patch("app.services.deals.record_payment", side_effect=boom2):
        assert fp.mark_part_paid(db2, T, "P1", 0, method="cash")["receipt_no"] == "FEE-0007-1"
    assert len(db2.rows("fee_plan_payments")) == 1


def test_async_pay_cancels_the_stale_pay_link():
    import asyncio
    db, _ = world(THREE)
    link = {"id": "D1", "razorpay_payment_link_id": "plink_1"}
    with patch("app.services.deals.record_payment", return_value={"status": "recorded", "stale_link": link}), \
            patch("app.services.deals.cancel_stale_link", new=AsyncMock()) as cancel:
        out = asyncio.run(fp.mark_part_paid_async(db, T, "P1", 0, method="upi"))
    assert out["receipt_no"] == "FEE-0007-1"
    cancel.assert_awaited_once_with(link)


def test_one_bad_part_or_calling_error_does_not_stop_the_other_reminders():
    # 9. a malformed part in plan P1; plan P2 (another student) is still reminded.
    db, _ = world([{"due_on": "garbage", "amount_paise": 1}, *THREE[:1]])
    db.add("leads", id="L2", tenant_id=T, name="Meena", phone="+919800000002")
    db.add("deals", id="D2", tenant_id=T, lead_id="L2", deal_number=8, stage="quoted", total_paise=900000, paid_paise=0)
    db.add("batch_enrolments", id="E2", tenant_id=T, batch_id="B1", lead_id="L2", deal_id="D2", status="active",
           student_name="Meena", phone="+919800000002")
    db.add("fee_plans", id="P2", tenant_id=T, deal_id="D2", parts=THREE)
    sent, send, _ = run(db)
    assert sent == 2 and send.await_count == 2
    # a failing send_to_calling after a late reminder does not undo or stop anything
    db2, _ = world(THREE)
    sent, _, _ = run(db2, now=datetime(2026, 12, 4, 5, 0, tzinfo=timezone.utc),
                     calling=patch("app.services.customer_calling.send_to_calling", side_effect=RuntimeError("x")))
    assert sent == 1


def test_editing_a_plan_lets_a_part_with_a_new_due_date_be_reminded_again():
    db, _ = world(THREE)
    db.add("fee_plan_reminders", tenant_id=T, fee_plan_id="P1", part_index=0, kind="due")
    db.add("fee_plan_reminders", tenant_id=T, fee_plan_id="P1", part_index=1, kind="before")
    fp.create_plan(db, T, "D1", [{"due_on": "2026-12-20", "amount_paise": 300000}, THREE[1], THREE[2]])
    assert [(r["part_index"]) for r in db.rows("fee_plan_reminders")] == [1]  # part 0 moved; part 1 did not


def test_fetch_all_reads_past_the_1000_row_cap():
    db = FakeSupabase()
    for i in range(2300):
        db.add("fee_plans", id=f"{i:05d}", tenant_id=T, deal_id=f"d{i}", parts=[])
    rows = fp.fetch_all(lambda: db.table("fee_plans").select("*").eq("tenant_id", T))
    assert len(rows) == 2300 and len({r["id"] for r in rows}) == 2300


# ── v9.2 #217: the pay-link reminder ─────────────────────────────────────────────

LINK_TEMPLATE = {"name": "fee_reminder_link", "language": "en", "body_text": "Hi {{1}} {{2}} {{3}} {{4}} {{5}} {{6}}"}


def test_the_link_reminder_carries_a_pay_link_for_this_part():
    db, _ = world(THREE)
    with patch.object(fp, "_part_link", AsyncMock(return_value="https://rzp.io/l/x1")) as mk:
        sent, send, _ = run(db, template={**LINK_TEMPLATE, "_plain": TEMPLATE})
    assert sent == 1
    tpl, phone, values = send.call_args.args[2:]
    assert tpl["name"] == "fee_reminder_link" and values[-1] == "https://rzp.io/l/x1" and len(values) == 6
    assert mk.await_args.args[3:6] == (0, "due", "+919876543210")


def test_no_pay_link_falls_back_to_the_plain_reminder():
    db, _ = world(THREE)
    with patch.object(fp, "_part_link", AsyncMock(return_value=None)):
        sent, send, _ = run(db, template={**LINK_TEMPLATE, "_plain": TEMPLATE})
    tpl, _, values = send.call_args.args[2:]
    assert sent == 1 and tpl["name"] == "fee_reminder" and len(values) == 5


def test_only_the_link_reminder_approved_and_no_link_sends_nothing_and_frees_the_claim():
    db, _ = world(THREE)
    with patch.object(fp, "_part_link", AsyncMock(return_value=None)):
        sent, send, _ = run(db, template={**LINK_TEMPLATE, "_plain": None})
    assert sent == 0 and send.await_count == 0 and db.rows("fee_plan_reminders") == []


def test_reminders_can_be_switched_on_with_only_the_link_message_approved():
    db, _ = world(THREE)
    with patch("app.config_dynamic.get_setting", return_value=None), \
            patch("app.config_dynamic.save_setting") as save:
        db.add("message_templates", tenant_id=T, name="fee_reminder_link", status="APPROVED")
        fp.set_reminders(db, T, True)
        save.assert_called_once_with("fee_reminders_enabled", "true", tenant_id=T)


def test_owed_on_part_takes_partial_credit_off_the_first_part_it_cant_cover():
    parts = [{"amount_paise": 10000}, {"amount_paise": 10000}, {"amount_paise": 10000}]
    assert [fp.owed_on_part(parts, {}, 4000, i) for i in range(3)] == [6000, 10000, 10000]
    assert [fp.owed_on_part(parts, {}, 14000, i) for i in range(3)] == [0, 6000, 10000]
    # A part marked paid on the plan is owed nothing and its money isn't counted twice.
    assert [fp.owed_on_part(parts, {0: 10000}, 13000, i) for i in range(3)] == [0, 7000, 10000]


def test_part_link_is_made_on_its_own_for_what_is_owed_and_never_touches_the_order_link():
    import asyncio
    db, plan = world(THREE)
    db.rows("deals")[0].update(total_paise=900000, paid_paise=100000)
    made = AsyncMock(return_value={"payment_link_url": "https://rzp.io/l/f1"})
    with patch("app.services.payment_razorpay.create_payment_link", made), \
            patch("app.services.deals.send_payment_link", AsyncMock()) as order_link:
        assert asyncio.run(fp._part_link(db, T, plan, 0, "due", "+919876543210", "Ravi")) == "https://rzp.io/l/f1"
    order_link.assert_not_awaited()
    kw = made.await_args.kwargs
    assert kw["amount_paise"] == 200000 and kw["notes"]["fee_plan_id"] == "P1" and kw["notes"]["deal_id"] == "D1"
    assert kw["idempotency_key"] == "fee:P1:0:due:200000"
    db.rows("deals")[0].update(paid_paise=900000)
    assert asyncio.run(fp._part_link(db, T, plan, 2, "due", "+919876543210", "Ravi")) is None

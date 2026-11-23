"""Property site visits: the reminder with the executive's phone, the gated templates, and the
"liked it, thinking" loan-help follow-up 2 days later."""
from datetime import timedelta

import pytest

from app.services import booking_messages as bm
from app.services import property_visit_messages as pvm
from tests.test_booking_messages import NOW, PHONE, T1, T2, World, iso, ist, run, w  # noqa: F401


def visit_world(w, window=False, approve_visit=False, approve_booking=True, phone="9876500011"):
    w.db.rows("booking_services")[0]["name"] = "Site visit"
    w.db.add("callers", tenant_id=T1, user_id="u-ravi", name="Ravi", phone=phone)
    w.db.add("catalog_items", id="item-1", tenant_id=T1, name="Green Meadows Villa 12")
    w.window(window)
    if approve_booking:
        w.approve("reminder")
    if approve_visit:
        spec = pvm.SITE_VISIT_TEMPLATES["site_visit_reminder"]
        w.db.add("message_templates", tenant_id=T1, name=spec["name"], status="APPROVED", meta_waba_id="waba-1",
                 body_text=spec["body"], language="en", header_media_type=None)
    s = NOW + timedelta(hours=26)
    w.booking(start_at=iso(s), end_at=iso(s + timedelta(hours=1)), block_end_at=iso(s + timedelta(hours=1)))
    w.db.add("property_visits", booking_id="bk-1", property_item_id="item-1", tenant_id=T1)


def test_template_bodies_pass_metas_rules():
    from app.services.template_rules import body_problems, variable_indices
    for spec in pvm.SITE_VISIT_TEMPLATES.values():
        assert body_problems(spec["body"]) == []
        assert len(spec["examples"]) == len(variable_indices(spec["body"]))


def test_reminder_uses_the_site_visit_template_when_approved_with_the_phone(w):
    visit_world(w, approve_visit=True)
    assert run(bm.send_reminders(w.db, NOW)) == 1
    kind, _, name, comps = w.sent[0]
    assert (kind, name) == ("template", "site_visit_reminder")
    assert [p["text"] for p in comps[0]["parameters"]] == [
        "Priya", "Glow Salon", "Green Meadows Villa 12", "tomorrow, Tue 24 Nov, 12:00 PM", "Call Ravi on +919876500011"]
    assert [c["parameters"][0]["payload"] for c in comps[1:]] == ["bk_yes:bk-1", "bk_cancel:bk-1"]


def test_reminder_falls_back_to_the_booking_template_until_approved(w):
    visit_world(w, approve_visit=False)
    assert run(bm.send_reminders(w.db, NOW)) == 1
    kind, _, name, comps = w.sent[0]
    assert (kind, name) == ("template", "anril_booking_reminder")
    assert [p["text"] for p in comps[0]["parameters"]] == ["Priya", "Site visit", "tomorrow, Tue 24 Nov, 12:00 PM", "Ravi"]


def test_free_text_reminder_in_the_window_carries_the_phone(w):
    visit_world(w, window=True)
    assert run(bm.send_reminders(w.db, NOW)) == 1
    kind, _, text, _buttons = w.sent[0]
    assert kind == "buttons" and "Call Ravi on +919876500011 if you need directions. Will you be there?" in text and "Will you be there?" in text


def test_no_staff_phone_uses_the_business_number(w):
    visit_world(w, window=True, phone=None)
    w.db.add("phone_numbers", tenant_id=T1, number="+914440001111", role="primary", status="active")
    run(bm.send_reminders(w.db, NOW))
    assert "Call us on +914440001111" in w.sent[0][2] and "Call Ravi" not in w.sent[0][2]


def test_no_phone_anywhere_keeps_the_old_reminder_even_when_approved(w):
    visit_world(w, approve_visit=True, phone=None)
    assert run(bm.send_reminders(w.db, NOW)) == 1
    assert w.sent[0][2] == "anril_booking_reminder"


def test_other_services_are_untouched(w):
    visit_world(w, approve_visit=True)
    w.db.rows("booking_services")[0]["name"] = "Haircut"
    run(bm.send_reminders(w.db, NOW))
    assert w.sent[0][2] == "anril_booking_reminder"


@pytest.mark.parametrize("flag", ["blocked", "opted_out", "lead_blocked"])
def test_visit_reminder_never_goes_to_blocked_or_opted_out(w, flag):
    visit_world(w, window=True, approve_visit=True)
    lead = w.db.rows("leads")[0]
    if flag == "blocked":
        w.blocked = True
    elif flag == "opted_out":
        lead["opted_out"] = True
    else:
        lead["blocked_at"] = iso(NOW)
    assert run(bm.send_reminders(w.db, NOW)) == 0
    assert w.sent == []


def test_property_name_falls_back_to_the_site(w):
    visit_world(w, approve_visit=True)
    w.db.rows("property_visits").clear()
    run(bm.send_reminders(w.db, NOW))
    assert w.sent[0][3][0]["parameters"][2]["text"] == "the site"


# ── template submission ─────────────────────────────────────────────────────

def _capture(w, monkeypatch):
    made = []

    async def create_template(body, tenant_id=None, _ctx=None):
        made.append(body)
        w.db.add("message_templates", tenant_id=T1, name=body.name, status="PENDING", meta_waba_id="waba-1")

    monkeypatch.setattr("app.routes.templates.create_template", create_template)
    return made


def test_property_business_also_submits_the_site_visit_templates(w, monkeypatch):
    w.db.rows("tenants")[0]["business_type"] = "Real Estate"
    made = _capture(w, monkeypatch)
    run(bm.submit_templates(w.db, T1, {}))
    by = {m.name: m for m in made}
    assert set(by) == {"anril_booking_update", "anril_booking_reminder", "site_visit_reminder", "loan_help_followup"}
    assert by["site_visit_reminder"].category == "UTILITY" and by["loan_help_followup"].category == "MARKETING"
    assert [b.text for b in by["site_visit_reminder"].buttons] == ["Yes, coming", "Cancel"]


def test_other_businesses_do_not_get_them(w, monkeypatch):
    made = _capture(w, monkeypatch)
    run(bm.submit_templates(w.db, T1, {}))
    assert {m.name for m in made} == {"anril_booking_update", "anril_booking_reminder"}


# ── the outcome and the 2-day follow-up ─────────────────────────────────────

@pytest.fixture
def uuids(monkeypatch):
    monkeypatch.setattr("app.services.booking_setup.is_uuid", lambda v: True)


def came(w, **kw):
    visit_world(w, approve_booking=False)
    w.db.rows("bookings")[0].update(status="came", **kw)


def test_liked_thinking_schedules_the_loan_followup_two_days_later(w, uuids):
    came(w)
    out = pvm.record_outcome(w.db, T1, "bk-1", "liked_thinking", NOW)
    row = w.row()
    assert row["visit_outcome"] == "liked_thinking"
    assert row["loan_followup_due_at"] == iso(NOW + timedelta(days=2)) or row["loan_followup_due_at"] == (NOW + timedelta(days=2)).isoformat()
    assert out["loan_followup_due_at"]
    again = pvm.record_outcome(w.db, T1, "bk-1", "liked_thinking", NOW + timedelta(hours=5))
    assert again["loan_followup_due_at"] == row["loan_followup_due_at"]  # not pushed back


def test_outcome_rules(w, uuids):
    came(w)
    with pytest.raises(pvm.OutcomeError):
        pvm.record_outcome(w.db, T1, "bk-1", "nonsense", NOW)
    w.row()["status"] = "booked"
    with pytest.raises(pvm.OutcomeError):
        pvm.record_outcome(w.db, T1, "bk-1", "liked_thinking", NOW)
    w.row()["status"] = "came"
    w.db.rows("booking_services")[0]["name"] = "Haircut"
    with pytest.raises(pvm.OutcomeError) as e:
        pvm.record_outcome(w.db, T1, "bk-1", "liked_thinking", NOW)
    assert e.value.status_code == 404


def test_another_tenants_booking_is_not_found(w, uuids):
    came(w)
    from app.services.bookings import BookingError
    with pytest.raises(BookingError):
        pvm.record_outcome(w.db, T2, "bk-1", "liked_thinking", NOW)


def test_changing_the_answer_cancels_an_unsent_followup(w, uuids):
    came(w)
    pvm.record_outcome(w.db, T1, "bk-1", "liked_thinking", NOW)
    pvm.record_outcome(w.db, T1, "bk-1", "not_interested", NOW)
    assert w.row()["loan_followup_due_at"] is None


def due(w, window, approve=False, **kw):
    came(w, visit_outcome="liked_thinking", loan_followup_due_at=iso(NOW - timedelta(minutes=5)),
         loan_followup_sent_at=None, **kw)
    w.db.rows("leads")[0]["opt_in_source"] = "website"
    w.window(window)
    if approve:
        spec = pvm.SITE_VISIT_TEMPLATES["loan_help_followup"]
        w.db.add("message_templates", tenant_id=T1, name=spec["name"], status="APPROVED", meta_waba_id="waba-1",
                 body_text=spec["body"], language="en", header_media_type=None)


def test_nothing_goes_before_it_is_due(w):
    due(w, True)
    w.row()["loan_followup_due_at"] = iso(NOW + timedelta(hours=1))
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0 and w.sent == []


def test_followup_in_the_window_is_free_text_and_goes_once(w):
    due(w, True)
    assert run(pvm.send_loan_followups(w.db, NOW)) == 1
    kind, phone, text = w.sent[0]
    assert (kind, phone) == ("text", PHONE) and "home loan" in text and "Green Meadows Villa 12" in text
    assert w.row()["loan_followup_sent_at"]
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0 and len(w.sent) == 1


def test_followup_outside_the_window_needs_the_approved_template(w):
    due(w, False, approve=False)
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0
    assert w.sent == [] and w.row()["loan_followup_sent_at"] is None  # tries again once it is approved
    spec = pvm.SITE_VISIT_TEMPLATES["loan_help_followup"]
    w.db.add("message_templates", tenant_id=T1, name=spec["name"], status="APPROVED", meta_waba_id="waba-1",
             body_text=spec["body"], language="en", header_media_type=None)
    assert run(pvm.send_loan_followups(w.db, NOW)) == 1
    kind, _, name, comps = w.sent[0]
    assert (kind, name) == ("template", "loan_help_followup")
    assert [p["text"] for p in comps[0]["parameters"]] == ["Priya", "Green Meadows Villa 12", "Glow Salon"]


def test_followup_waits_for_daytime(w):
    due(w, True)
    night = ist(23, 22)
    assert run(pvm.send_loan_followups(w.db, night)) == 0 and w.sent == []


@pytest.mark.parametrize("flag", ["blocked", "opted_out"])
def test_followup_never_goes_to_blocked_or_opted_out(w, flag):
    due(w, True)
    if flag == "blocked":
        w.blocked = True
    else:
        w.db.rows("leads")[0]["opted_out"] = True
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0
    assert w.sent == [] and w.row()["loan_followup_due_at"] is None  # dropped for good


def test_a_stale_followup_is_dropped(w):
    due(w, True)
    w.row()["loan_followup_due_at"] = iso(NOW - timedelta(days=6))
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0 and w.sent == []


def test_followup_ignores_other_outcomes_and_not_came(w):
    due(w, True, )
    w.row()["visit_outcome"] = "not_interested"
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0
    w.row().update(visit_outcome="liked_thinking", status="no_show")
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0 and w.sent == []


# ── the marketing template needs a real opt-in ──────────────────────────────

def approve_loan(w):
    spec = pvm.SITE_VISIT_TEMPLATES["loan_help_followup"]
    w.db.add("message_templates", tenant_id=T1, name=spec["name"], status="APPROVED", meta_waba_id="waba-1",
             body_text=spec["body"], language="en", header_media_type=None)


@pytest.mark.parametrize("source", [None, "", "manual"])
def test_template_needs_a_recorded_opt_in_and_the_followup_is_closed(w, source):
    due(w, False)
    approve_loan(w)
    w.db.rows("leads")[0]["opt_in_source"] = source
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0
    assert w.sent == [] and w.row()["loan_followup_due_at"] is None and w.row()["loan_followup_sent_at"] is None


def test_no_lead_means_no_template_and_closed(w):
    due(w, False)
    approve_loan(w)
    w.db.rows("leads").clear()
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0
    assert w.sent == [] and w.row()["loan_followup_due_at"] is None


def test_tag_opt_out_blocks_the_template(w):
    due(w, False)
    approve_loan(w)
    w.db.add("lead_tag_opt_outs", tenant_id=T1, lead_id="lead-1", tag_id=None)
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0
    assert w.sent == [] and w.row()["loan_followup_due_at"] is None


def test_template_goes_with_an_opt_in(w):
    due(w, False)
    approve_loan(w)
    assert run(pvm.send_loan_followups(w.db, NOW)) == 1 and w.sent[0][2] == "loan_help_followup"


def test_free_text_in_the_window_needs_no_opt_in_and_never_falls_back_to_the_template(w):
    due(w, True)
    approve_loan(w)
    w.db.rows("leads")[0]["opt_in_source"] = None
    assert run(pvm.send_loan_followups(w.db, NOW)) == 1 and w.sent[0][0] == "text"
    # a free-text send that fails does not turn into a template to someone with no opt-in
    w2 = w
    w2.row().update(loan_followup_sent_at=None)
    w2.sent.clear()
    w2.text_fails = True
    assert run(pvm.send_loan_followups(w2.db, NOW)) == 0 and w2.sent == []
    assert w2.row()["loan_followup_sent_at"] is None


def test_unsendable_booking_is_not_claimed_each_tick(w, monkeypatch):
    due(w, False)  # window closed, template not approved
    writes = []
    real = w.db.table

    def spy(name):
        t = real(name)
        if name == "bookings":
            orig = t.update

            def update(values, *a, **k):
                writes.append(values)
                return orig(values, *a, **k)
            t.update = update
        return t

    monkeypatch.setattr(w.db, "table", spy)
    assert run(pvm.send_loan_followups(w.db, NOW)) == 0
    assert writes == []

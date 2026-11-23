"""Webhook wiring for v9.2 Batch H: star taps / unhappy replies (Customers › Feedback) and form-lead receipts (#18)."""
import asyncio
from unittest.mock import MagicMock

import app.services.customer_feedback as cf
from app.routes import webhook


def _fake_feedback(monkeypatch, *, button=True, text=False):
    calls = {}

    async def handle_feedback_button(db, tenant_id, lead_id, phone, payload):
        calls["button"] = (tenant_id, lead_id, phone, payload)
        return button

    async def handle_feedback_text(db, tenant_id, lead_id, phone, body):
        calls["text"] = (tenant_id, lead_id, phone, body)
        return text

    monkeypatch.setattr(cf, "handle_feedback_button", handle_feedback_button)
    monkeypatch.setattr(cf, "handle_feedback_text", handle_feedback_text)
    return calls


def _run(*args):
    return asyncio.run(webhook._handle_feedback_message(MagicMock(), "t1", "L1", "9198", *args))


def test_template_star_tap_goes_to_feedback(monkeypatch):
    calls = _fake_feedback(monkeypatch)
    assert _run("button", {"button": {"payload": "fb:2:abc", "text": "⭐⭐ 2"}}, "⭐⭐ 2") is True
    assert calls["button"] == ("t1", "L1", "9198", "fb:2:abc")


def test_in_window_star_tap_goes_to_feedback(monkeypatch):
    calls = _fake_feedback(monkeypatch)
    msg = {"interactive": {"button_reply": {"id": "fb:5:abc", "title": "⭐⭐⭐⭐⭐ 5"}}}
    assert _run("interactive", msg, "") is True
    assert calls["button"][3] == "fb:5:abc"


def test_other_buttons_are_not_feedback(monkeypatch):
    calls = _fake_feedback(monkeypatch)
    assert _run("button", {"button": {"payload": "bk_yes:1"}}, "Yes") is False
    assert "button" not in calls and "text" not in calls


def test_text_is_offered_to_feedback_and_falls_through_when_not_theirs(monkeypatch):
    calls = _fake_feedback(monkeypatch, text=False)
    assert _run("text", {}, "what is the price") is False
    assert calls["text"][3] == "what is the price"


def test_unhappy_reason_is_handled(monkeypatch):
    _fake_feedback(monkeypatch, text=True)
    assert _run("text", {}, "waited 40 min") is True


def test_feedback_errors_never_break_the_chat(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(cf, "handle_feedback_button", boom)
    monkeypatch.setattr(cf, "handle_feedback_text", boom)
    assert _run("button", {"button": {"payload": "fb:1:x"}}, "") is False


def test_receipts_reach_form_leads_with_the_error_code(monkeypatch):
    seen = []
    import app.services.meta_lead_forms as mlf
    monkeypatch.setattr(mlf, "apply_delivery_status", lambda db, t, mid, st, code: seen.append((t, mid, st, code)),
                        raising=False)
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    db.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    webhook._apply_status_updates(db, "t1", [
        {"id": "wamid.1", "status": "delivered"},
        {"id": "wamid.2", "status": "failed", "errors": [{"code": 131026, "title": "Undeliverable"}]},
    ])
    assert seen == [("t1", "wamid.1", "delivered", None), ("t1", "wamid.2", "failed", 131026)]


def test_template_status_reaches_automation_pauses(monkeypatch):
    import app.services.template_pauses as tp
    seen = []
    monkeypatch.setattr(tp, "on_template_status_change", lambda db, t, name, status: seen.append((t, name, status)) or 1)
    monkeypatch.setattr(webhook, "get_supabase", lambda: MagicMock())
    webhook._pause_or_resume_automations("t1", {"event": "REJECTED", "message_template_name": "offer_v2"})
    webhook._pause_or_resume_automations(None, {"event": "REJECTED", "message_template_name": "offer_v2"})
    webhook._pause_or_resume_automations("t1", {"event": "APPROVED"})
    assert seen == [("t1", "offer_v2", "REJECTED")]


def test_template_pause_errors_never_break_the_webhook(monkeypatch):
    import app.services.template_pauses as tp

    def boom(*a):
        raise RuntimeError("db down")

    monkeypatch.setattr(tp, "on_template_status_change", boom)
    monkeypatch.setattr(webhook, "get_supabase", lambda: MagicMock())
    webhook._pause_or_resume_automations("t1", {"event": "PAUSED", "message_template_name": "x"})

"""Webhook → Bookings: reminder buttons and booking codes are handled and kept away from the AI."""
import asyncio
import sys
import types

from app.routes import webhook


def _fake_module(monkeypatch, *, button=True, code=True, boom=False):
    mod = types.ModuleType("app.services.booking_messages")
    seen = {}

    async def handle_booking_button(db, tenant_id, phone, payload):
        if boom:
            raise RuntimeError("db down")
        seen["button"] = (tenant_id, phone, payload)
        return button

    async def handle_booking_code(db, tenant_id, lead_id, phone, text):
        seen["code"] = (tenant_id, lead_id, phone, text)
        return code

    mod.handle_booking_button = handle_booking_button
    mod.handle_booking_code = handle_booking_code
    monkeypatch.setitem(sys.modules, "app.services.booking_messages", mod)
    import app.services as pkg
    monkeypatch.setattr(pkg, "booking_messages", mod, raising=False)
    return seen


def _run(*args):
    return asyncio.run(webhook._handle_booking_message(None, *args))


def test_booking_button_is_handled(monkeypatch):
    seen = _fake_module(monkeypatch)
    msg = {"button": {"payload": "bk_yes:abc", "text": "Yes, coming"}}
    assert _run("t1", "L1", "+9198", "button", msg, "Yes, coming") is True
    assert seen["button"] == ("t1", "+9198", "bk_yes:abc")


def test_other_buttons_pass_through(monkeypatch):
    seen = _fake_module(monkeypatch)
    msg = {"button": {"payload": "quote_accept:D1", "text": "Accept"}}
    assert _run("t1", "L1", "+9198", "button", msg, "Accept") is False
    assert "button" not in seen


def test_booking_code_text(monkeypatch):
    seen = _fake_module(monkeypatch)
    assert _run("t1", "L1", "+9198", "text", {}, "Hi, my booking code is BK-0012") is True
    assert seen["code"][3] == "Hi, my booking code is BK-0012"


def test_plain_text_never_calls_bookings(monkeypatch):
    seen = _fake_module(monkeypatch)
    assert _run("t1", "L1", "+9198", "text", {}, "What is the price?") is False
    assert seen == {}


def test_unmatched_code_goes_on_to_the_ai(monkeypatch):
    _fake_module(monkeypatch, code=False)
    assert _run("t1", "L1", "+9198", "text", {}, "bk 99") is False


def test_errors_never_raise(monkeypatch):
    _fake_module(monkeypatch, boom=True)
    assert _run("t1", "L1", "+9198", "button", {"button": {"payload": "bk_cancel:x"}}, "Cancel") is False


def test_in_window_reply_button_is_handled(monkeypatch):
    """Inside the 24h window the reminder uses reply buttons: type "interactive", button_reply.id."""
    seen = _fake_module(monkeypatch)
    msg = {"interactive": {"type": "button_reply", "button_reply": {"id": "bk_cancel:abc", "title": "Cancel"}}}
    assert _run("t1", "L1", "+9198", "interactive", msg, "Cancel") is True
    assert seen["button"] == ("t1", "+9198", "bk_cancel:abc")


def test_other_interactive_taps_pass_through(monkeypatch):
    seen = _fake_module(monkeypatch)
    msg = {"interactive": {"type": "list_reply", "list_reply": {"id": "pkg_gold", "title": "Gold"}}}
    assert _run("t1", "L1", "+9198", "interactive", msg, "Gold") is False
    assert seen == {}

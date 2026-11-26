"""The chat shows the template's words, not "[Template: name]" (2026-11-26).

New sends store the filled-in wording in messages.template_text. Older rows only have the
marker, so the chat fills it from the template, {{1}} = the customer's name.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes import leads
from app.services.template_params import body_parameters, render_body


def test_render_body_fills_each_variable_in_place():
    params = body_parameters("Hi {{1}}! Your {{2}} is ready.", ["", "course"], {"course": "Tally"}, "Dinaharan")
    assert render_body("Hi {{1}}! Your {{2}} is ready.", params) == "Hi Dinaharan! Your Tally is ready."
    assert render_body("No variables", []) == "No variables"
    assert render_body(None, []) == ""


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, table, calls):
        self.table, self.calls = table, calls

    def __getattr__(self, _name):  # select / eq / in_ / order / limit are no-ops
        return lambda *a, **k: self

    def execute(self):
        self.calls.append(self.table)
        if self.table == "messages":
            return _Res([
                {"id": "m1", "content": "[Template: kelir_invite]", "template_text": None},
                {"id": "m2", "content": "[Template: kelir_invite]", "template_text": "Hi Dina, sent exactly"},
                {"id": "m3", "content": "STOP", "template_text": None},
                {"id": "m4", "content": "[Template: gone_template]", "template_text": None},
            ])
        if self.table == "leads":
            return _Res([{"name": "Dinaharan P"}])
        if self.table == "message_templates":
            return _Res([{"name": "kelir_invite", "body_text": "Hi {{1}}! 👋 Welcome."}])
        return _Res([])


class _DB:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return _Q(name, self.calls)


def test_chat_messages_show_the_template_words(monkeypatch):
    db = _DB()
    monkeypatch.setattr(leads, "get_supabase", lambda: db)
    rows = {m["id"]: m for m in asyncio.run(leads.get_lead_messages(lead_id="00000000-0000-0000-0000-000000000001", tenant_id="t1"))}
    assert rows["m1"]["template_text"] == "Hi Dinaharan P! 👋 Welcome."  # filled from the template
    assert rows["m2"]["template_text"] == "Hi Dina, sent exactly"  # what was stored at send time wins
    assert rows["m3"]["template_text"] is None  # a normal message is left alone
    assert rows["m4"]["template_text"] is None  # template deleted since: keep the marker


def test_no_template_lookup_when_there_is_nothing_to_fill(monkeypatch):
    class _Plain(_DB):
        def table(self, name):
            q = _Q(name, self.calls)
            if name == "messages":
                q.execute = lambda: _Res([{"id": "m1", "content": "hello", "template_text": None}])
            return q

    db = _Plain()
    monkeypatch.setattr(leads, "get_supabase", lambda: db)
    asyncio.run(leads.get_lead_messages(lead_id="00000000-0000-0000-0000-000000000001", tenant_id="t1"))
    assert "message_templates" not in db.calls and "leads" not in db.calls

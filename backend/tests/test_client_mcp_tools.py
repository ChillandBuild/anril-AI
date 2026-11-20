"""Anril AI (client connector) tools: the wall between clients, the edit tools, and the two
sending tools with the daily cap. Spec: docs/specs/anril-client-mcp.md."""
import inspect
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.client_mcp import server, tools_edit, tools_read, tools_send, wrapper
from app.config import settings
from app.routes import lead_notes as lead_notes_routes
from app.routes import leads as leads_routes
from app.routes import upload
from app.services import call_details_share as share
from app.services import client_claude
from tests.test_client_mcp_core import A, ADMIN_APP, APP, B, two_clients

LEAD_A = "11111111-1111-1111-1111-111111111111"
LEAD_A2 = "11111111-1111-1111-1111-222222222222"
LEAD_B = "22222222-2222-2222-2222-222222222222"
TEMPLATE = "33333333-3333-3333-3333-333333333333"
NOON_IST = datetime(2026, 11, 21, 6, 30, tzinfo=timezone.utc)  # 12:00 Indian time


def shop():
    """Two clients with leads. A's leads say 'Priya' and 'Karthik'; B's lead says 'SECRET-B'."""
    db = two_clients()
    recent = (NOON_IST - timedelta(hours=1)).isoformat()
    db.add("leads", id=LEAD_A, tenant_id=A, name="Priya", phone="919000000001", segment="B", source="whatsapp",
           opt_in_source="whatsapp", opted_out=False, last_inbound_at=recent, deleted_at=None, created_at="2026-10-05T05:00:00+00:00")
    db.add("leads", id=LEAD_A2, tenant_id=A, name="Karthik", phone="919000000002", segment="A", source="whatsapp",
           opt_in_source="whatsapp", opted_out=False, last_inbound_at=None, deleted_at=None, created_at="2026-10-06T05:00:00+00:00")
    db.add("leads", id=LEAD_B, tenant_id=B, name="SECRET-B", phone="919999999999", segment="A", source="whatsapp",
           opt_in_source="whatsapp", opted_out=False, last_inbound_at=recent, deleted_at=None, created_at="2026-10-05T05:00:00+00:00")
    db.add("message_templates", id=TEMPLATE, tenant_id=A, name="diwali_offer", status="APPROVED", language="en",
           body_text="Hi {{1}}, our Diwali offer is on.", meta_waba_id="waba-a", header_media_type=None)
    db.add("callers", id="caller-1", tenant_id=A, name="Karthik R")
    db.add("callers", id="caller-b", tenant_id=B, name="Other Caller")
    return db


def call(fn, db, tenant=A, now=NOON_IST, **kwargs):
    """Run a tool's plain function as `tenant`'s owner against the fake database."""
    with ExitStack() as stack:
        for module in (tools_read, tools_edit, tools_send, upload):
            stack.enter_context(patch.object(module, "get_supabase", return_value=db))
        stack.enter_context(patch.object(share, "get_setting", side_effect=lambda key, **_: "waba-a" if key == "meta_waba_id" else "set"))
        stack.enter_context(patch.object(tools_send, "_now", return_value=now))
        stack.enter_context(wrapper.acting_as(tenant, user_id="owner-a" if tenant == A else "owner-b"))
        return fn(**kwargs)


# ── the wall ──────────────────────────────────────────────────────────────────

def test_every_approved_tool_is_registered_and_none_can_be_told_which_client():
    server._load_tools()
    assert set(wrapper.REGISTRY) == set(wrapper.APPROVED_TOOLS)
    forbidden = {"tenant", "tenant_id", "client", "client_id", "user_id", "owner_id"}
    for name, spec in wrapper.REGISTRY.items():
        assert not forbidden & set(inspect.signature(spec.fn).parameters), name
        assert (spec.kind, spec.permission, spec.source) == wrapper.APPROVED_TOOLS[name]


def test_only_sends_are_marked_destructive_and_only_reads_as_read_only():
    with patch.object(settings, "supabase_url", "https://proj.supabase.co"):
        tools = {t.name: t.annotations for t in server.build_server()._tool_manager.list_tools()}
    assert len(tools) == len(wrapper.APPROVED_TOOLS)
    for name, (kind, _, _) in wrapper.APPROVED_TOOLS.items():
        assert tools[name].read_only_hint is (kind == wrapper.READ), name
        assert tools[name].destructive_hint is (kind == wrapper.SEND), name
    assert {n for n, (k, _, _) in wrapper.APPROVED_TOOLS.items() if k == wrapper.SEND} == {"send_reply", "send_broadcast"}


def test_find_leads_never_shows_another_clients_lead():
    db = shop()
    everything = call(tools_read.find_leads, db)
    assert {lead["name"] for lead in everything["leads"]} == {"Priya", "Karthik"}
    assert "SECRET-B" not in str(call(tools_read.find_leads, db, search="SECRET"))
    assert "SECRET-B" not in str(call(tools_read.find_leads, db, search="9999999999"))
    assert [lead["name"] for lead in call(tools_read.find_leads, db, segment="A")["leads"]] == ["Karthik"]
    assert [lead["name"] for lead in call(tools_read.find_leads, db, created_to="2026-10-05")["leads"]] == ["Priya"]


@pytest.mark.parametrize("tool, kwargs", [
    (tools_edit.assign_lead, {"team_member": "Karthik R"}),
    (tools_edit.add_lead_note, {"note": "call after 6 pm"}),
    (tools_send.reply_options, {}),
    (tools_send.send_reply, {"text": "hello"}),
])
def test_another_clients_lead_is_not_found_and_nothing_runs(tool, kwargs):
    db = shop()
    with patch.object(leads_routes, "assign_lead", AsyncMock()) as assign, \
         patch.object(lead_notes_routes, "create_lead_note", AsyncMock()) as note, \
         patch.object(share, "send_whatsapp", AsyncMock(return_value="wamid.1")) as send:
        with pytest.raises(ToolError, match="No lead with that id in your account"):
            call(tool, db, lead_id=LEAD_B, **kwargs)
    assert not (assign.called or note.called or send.called)
    assert db.rows("messages") == [] and client_claude.sent_today(db, A) == 0


def test_the_operator_reads_are_always_given_the_signed_in_client():
    reads = {
        "dashboard_summary": ("client_dashboard_analytics", {}),
        "leads_overview": ("client_dashboard_leads", {}),
        "conversations": ("client_dashboard_inbox", {}),
        "calling_stats": ("client_dashboard_telecalling", {}),
        "messaging_stats": ("client_dashboard_daily_messages", {}),
    }
    for tool, (handler, kwargs) in reads.items():
        with patch.object(tools_read.operator, handler, return_value={}) as h:
            call(getattr(tools_read, tool), shop(), **kwargs)
        assert h.call_args.kwargs["tenant_id"] == A, tool
    with patch.object(tools_read.operator_leads, "client_lead_thread", return_value={}) as h:
        call(tools_read.lead_details, shop(), lead_id=LEAD_A)
    assert h.call_args.kwargs["tenant_id"] == A
    with patch.object(tools_read.operator_broadcasts, "client_broadcasts", return_value={}) as h:
        call(tools_read.broadcasts, shop())
    assert h.call_args.kwargs["tenant_id"] == A


def test_templates_and_team_are_the_clients_own():
    db = shop()
    db.add("message_templates", id="t-b", tenant_id=B, name="SECRET-B-template", status="APPROVED", body_text="x")
    assert [t["name"] for t in call(tools_read.templates, db)["templates"]] == ["diwali_offer"]
    with pytest.raises(ToolError, match="You can assign to: Karthik R"):
        call(tools_edit.assign_lead, db, lead_id=LEAD_A, team_member="Other Caller")


# ── edits ─────────────────────────────────────────────────────────────────────

def test_edits_call_the_apps_own_handlers_as_the_owner():
    db = shop()
    with patch.object(leads_routes, "assign_lead", AsyncMock()) as assign:
        out = call(tools_edit.assign_lead, db, lead_id=LEAD_A, team_member="karthik")
    lead_id, payload, ctx = assign.call_args.args
    assert (lead_id, payload.caller_id, ctx["tenant_id"], ctx["role"]) == (LEAD_A, "caller-1", A, "owner")
    assert out == {"lead": "Priya", "assigned_to": "Karthik R"}

    with patch.object(lead_notes_routes, "create_lead_note", AsyncMock(return_value={"id": "n1"})) as note:
        call(tools_edit.add_lead_note, db, lead_id=LEAD_A, note="  call after 6 pm ")
    assert note.call_args.args[1].content == "call after 6 pm" and note.call_args.args[2]["tenant_id"] == A


def test_changing_a_leads_segment_is_not_a_tool():
    # In the app a segment change re-plans the lead's automatic WhatsApp follow-ups, which
    # would be customer messages outside the daily cap.
    assert "set_lead_stage" not in wrapper.APPROVED_TOOLS and not hasattr(tools_edit, "set_lead_stage")


# ── one-to-one send ───────────────────────────────────────────────────────────

def _send(db, **kwargs):
    with patch.object(share, "send_whatsapp", AsyncMock(return_value="wamid.1")) as text, \
         patch.object(share, "send_template_message", AsyncMock(return_value={"messages": [{"id": "wamid.2"}]})) as tpl:
        return call(tools_send.send_reply, db, **kwargs), text, tpl


def test_a_reply_is_sent_once_booked_against_the_cap_and_a_repeat_is_refused():
    db = shop()
    out, text, _ = _send(db, lead_id=LEAD_A, text="Your chart is ready")
    assert out["sent"] and out["left_today"] == 499 and text.await_args.args[:2] == ("919000000001", "Your chart is ready")
    row = db.rows("messages")[0]
    assert (row["tenant_id"], row["lead_id"], row["sent_by_user_id"]) == (A, LEAD_A, "owner-a")
    db.rows("messages")[0]["created_at"] = NOON_IST.isoformat()
    with pytest.raises(ToolError, match="already went to this lead"):
        _send(db, lead_id=LEAD_A, text="Your chart is ready")
    assert len(db.rows("messages")) == 1 and client_claude.sent_today(db, A) == 1


def test_free_text_outside_24_hours_is_refused_and_gives_the_cap_back():
    db = shop()
    with pytest.raises(ToolError, match="send a template instead"):
        _send(db, lead_id=LEAD_A2, text="hello")
    assert db.rows("messages") == [] and client_claude.sent_today(db, A) == 0
    out, _, tpl = _send(db, lead_id=LEAD_A2, template_id=TEMPLATE, variables=["Karthik"])
    assert out["message"] == "Hi Karthik, our Diwali offer is on." and tpl.await_count == 1
    assert client_claude.sent_today(db, A) == 1


def test_at_the_cap_nothing_is_sent():
    db = shop()
    client_claude.set_daily_cap(db, A, 0)
    with patch.object(share, "send_whatsapp", AsyncMock(return_value="wamid.1")) as text:
        with pytest.raises(ToolError, match="today's limit for Anril AI is 0"):
            call(tools_send.send_reply, db, lead_id=LEAD_A, text="hello")
    assert not text.called and db.rows("messages") == []


def test_a_blocked_or_undeliverable_lead_is_not_messaged():
    for flag in ({"blocked_at": NOON_IST.isoformat()}, {"whatsapp_undeliverable": True}):
        db = shop()
        db.rows("leads")[0].update(flag)
        assert call(tools_send.reply_options, db, lead_id=LEAD_A)["can_send"] is False
        with patch.object(share, "send_whatsapp", AsyncMock(return_value="wamid.1")) as text:
            with pytest.raises(ToolError, match="blocked, or WhatsApp cannot deliver"):
                call(tools_send.send_reply, db, lead_id=LEAD_A, text="hello")
        assert not text.called and client_claude.sent_today(db, A) == 0


def test_reply_needs_exactly_one_of_text_or_template():
    for kwargs in ({}, {"text": "hi", "template_id": TEMPLATE}):
        with pytest.raises(ToolError, match="either text or a template_id"):
            call(tools_send.send_reply, shop(), lead_id=LEAD_A, **kwargs)


# ── broadcast ─────────────────────────────────────────────────────────────────

BROADCAST = {"template_name": "diwali_offer", "variables": ["{name}"], "created_from": "2026-10-01", "created_to": "2026-10-31"}
OLD_LEAD = "66666666-6666-6666-6666-666666666666"


def october_shop():
    """shop() plus one lead of A's from September, so "October" is not "everyone"."""
    db = shop()
    db.add("leads", id=OLD_LEAD, tenant_id=A, name="Meena", phone="919000000009", segment="C", source="website_form",
           opt_in_source="website_form", opted_out=False, deleted_at=None, created_at="2026-09-01T05:00:00+00:00")
    return db


def _token(db, **kwargs):
    return call(tools_send.preview_broadcast, db, **{**BROADCAST, **kwargs})["preview_token"]


def test_preview_shows_who_would_get_it_and_sends_nothing():
    db = october_shop()
    db.add("leads", id="44444444-4444-4444-4444-444444444444", tenant_id=A, name="Opted", phone="919000000003",
           opt_in_source="whatsapp", opted_out=True, deleted_at=None, created_at="2026-10-07T05:00:00+00:00")
    db.add("leads", id="55555555-5555-5555-5555-555555555555", tenant_id=A, name="Typed in", phone="919000000004",
           opt_in_source="manual", opted_out=False, deleted_at=None, created_at="2026-10-07T05:00:00+00:00")
    out = call(tools_send.preview_broadcast, db, **BROADCAST)
    assert out["recipients"] == 2 and out["matched_leads"] == 4 and out["preview_token"]
    assert out["left_out"] == {"opted_out_or_blocked": 1, "no_recorded_opt_in": 1}
    assert {s["message"] for s in out["samples"]} == {"Hi Priya, our Diwali offer is on.", "Hi Karthik, our Diwali offer is on."}
    assert "SECRET-B" not in str(out) and out["sending_limit"]["fits"] is True
    assert db.rows("scheduled_broadcasts") == [] and client_claude.sent_today(db, A) == 0


def test_a_previewed_broadcast_is_scheduled_once_for_own_leads():
    db = october_shop()
    out = call(tools_send.send_broadcast, db, preview_token=_token(db), **BROADCAST)
    assert out["scheduled"] and out["recipients"] == 2 and out["left_today"] == 498
    row = db.rows("scheduled_broadcasts")[0]
    assert (row["tenant_id"], row["schedule_type"], row["template_name"], row["created_by"]) == (A, "scheduled", "diwali_offer", "owner-a")
    assert sorted(l["phone"] for l in row["leads_json"]) == ["919000000001", "919000000002"]
    assert {l["extra_cols"]["v1"] for l in row["leads_json"]} == {"Priya", "Karthik"} and row["variable_mapping"] == ["v1"]
    assert datetime.fromisoformat(row["fire_at"]) == NOON_IST + timedelta(minutes=2)
    assert client_claude.sent_today(db, A) == 2

    row["created_at"] = NOON_IST.isoformat()
    with pytest.raises(ToolError, match="already scheduled for 2 people"):
        call(tools_send.send_broadcast, db, preview_token=_token(db), **BROADCAST)
    assert len(db.rows("scheduled_broadcasts")) == 1 and client_claude.sent_today(db, A) == 2


def test_send_broadcast_cannot_skip_the_preview():
    db = october_shop()
    token = _token(db)
    refused = "not the broadcast that was previewed"
    # no token, a made-up one, and a guess at the number of people (the old way in)
    for bad in ("", "2", f"{int(NOON_IST.timestamp()) + 60}.{'0' * 64}"):
        with pytest.raises(ToolError, match=refused) as caught:
            call(tools_send.send_broadcast, db, preview_token=bad, **BROADCAST)
        assert "2 people" not in str(caught.value)  # the refusal does not give the number away
    # a real token, but for other wording, another audience of the same size, or too old
    with pytest.raises(ToolError, match=refused):
        call(tools_send.send_broadcast, db, preview_token=token, **{**BROADCAST, "variables": ["friend"]})
    db.rows("leads")[1]["created_at"] = "2026-09-02T05:00:00+00:00"   # Karthik leaves October
    db.rows("leads")[3]["created_at"] = "2026-10-09T05:00:00+00:00"   # Meena joins it
    db.rows("leads")[3]["opt_in_source"] = "whatsapp"
    with pytest.raises(ToolError, match=refused):
        call(tools_send.send_broadcast, db, preview_token=token, **BROADCAST)
    db = october_shop()
    with pytest.raises(ToolError, match=refused):
        call(tools_send.send_broadcast, db, preview_token=_token(db), now=NOON_IST + timedelta(minutes=11), **BROADCAST)
    # another client's owner cannot use it either
    with pytest.raises(ToolError):
        call(tools_send.send_broadcast, db, tenant=B, preview_token=_token(db), **BROADCAST)
    assert db.rows("scheduled_broadcasts") == [] and client_claude.sent_today(db, A) == 0


def test_a_broadcast_over_the_cap_or_at_night_is_refused():
    db = october_shop()
    client_claude.set_daily_cap(db, A, 1)
    with pytest.raises(ToolError, match="1 are left and this needs 2"):
        call(tools_send.send_broadcast, db, preview_token=_token(db), **BROADCAST)
    assert db.rows("scheduled_broadcasts") == [] and client_claude.sent_today(db, A) == 0

    db = october_shop()
    with pytest.raises(ToolError, match="between 9 am and 9 pm"):
        call(tools_send.send_broadcast, db, preview_token=_token(db), send_at="2026-11-22T02:00:00+05:30", **BROADCAST)
    with pytest.raises(ToolError, match="1 blank"):
        call(tools_send.preview_broadcast, october_shop(), template_name="diwali_offer", segment="A")


@pytest.mark.parametrize("who, refusal", [
    ({}, "Say who should get it"),
    ({"search": "   "}, "Say who should get it"),
    ({"search": "%%"}, "at least 3 letters"),
    ({"search": "a"}, "at least 3 letters"),
    ({"created_from": "2000-01-01"}, "every lead you have"),
    ({"source": "whatsapp", "created_from": "2026-10-01"}, "every lead you have"),
])
def test_a_broadcast_to_everyone_is_refused_however_it_is_asked(who, refusal):
    with pytest.raises(ToolError, match=refusal):
        call(tools_send.preview_broadcast, shop(), template_name="diwali_offer", variables=["{name}"], **who)


def test_listing_the_leads_by_id_is_allowed_even_when_that_is_all_of_them():
    out = call(tools_send.preview_broadcast, shop(), template_name="diwali_offer", variables=["{name}"], lead_ids=[LEAD_A, LEAD_A2, LEAD_B])
    assert out["recipients"] == 2 and "SECRET-B" not in str(out)  # B's lead is simply not found


def test_a_refused_schedule_gives_the_cap_back_but_an_unknown_failure_does_not():
    from fastapi import HTTPException
    db = october_shop()
    with patch.object(upload, "bulk_send", AsyncMock(side_effect=HTTPException(status_code=400, detail="No eligible leads"))):
        with pytest.raises(HTTPException):
            call(tools_send.send_broadcast, db, preview_token=_token(db), **BROADCAST)
    assert client_claude.sent_today(db, A) == 0
    with patch.object(upload, "bulk_send", AsyncMock(side_effect=RuntimeError("connection lost after the insert"))):
        with pytest.raises(RuntimeError):
            call(tools_send.send_broadcast, db, preview_token=_token(db), **BROADCAST)
    assert client_claude.sent_today(db, A) == 2  # it may have been saved, so it still counts


def test_an_unapproved_or_foreign_or_media_template_cannot_be_broadcast():
    db = october_shop()
    db.rows("message_templates")[0]["status"] = "PENDING"
    with pytest.raises(ToolError, match="not approved by Meta"):
        call(tools_send.preview_broadcast, db, **BROADCAST)
    db.rows("message_templates")[0].update(status="APPROVED", header_media_type="IMAGE")
    with pytest.raises(ToolError, match="image, video or document header"):
        call(tools_send.preview_broadcast, db, **BROADCAST)
    db.add("message_templates", id="t-b", tenant_id=B, name="b_only", status="APPROVED", body_text="x")
    with pytest.raises(ToolError, match='No template called "b_only"'):
        call(tools_send.preview_broadcast, db, template_name="b_only", segment="A")

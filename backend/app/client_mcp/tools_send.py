"""Tools that send WhatsApp messages to customers. These leave Anril and cannot be taken back,
so every one of them:
  - goes through the app's own send path (the same approval, opt-out and 24-hour rules),
  - books its messages against the client's daily cap BEFORE sending (services.client_claude),
  - refuses an exact repeat made moments later (Claude retrying after a slow answer),
  - a broadcast needs the preview_token of a preview of exactly that broadcast, made in the
    last 10 minutes (so "send" cannot skip "show the owner who gets it"),
  - is marked as an action in the server, so the Claude app asks the owner to allow it.
A broadcast is never sent in-process: it is saved as a scheduled broadcast and the app's
scheduler sends it, so it shows under Anril → Broadcasts and can be cancelled there until it starts.
"""
import asyncio
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError

from app.client_mcp import leads as lead_lookup
from app.client_mcp.wrapper import client_tool, seat, tenant_id
from app.config import settings
from app.db.supabase import get_supabase
from app.routes import upload
from app.services import call_details_share as share
from app.services import client_claude
from app.services.actor import sender_fields

_IST = timezone(timedelta(hours=5, minutes=30))
_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
REPEAT_SECONDS = 120            # one-to-one: the same text to the same lead
BROADCAST_REPEAT_MINUTES = 10   # the same template to the same number of people
BROADCAST_DELAY_MINUTES = 2     # a broadcast starts this long after it is asked for
SEND_HOURS_IST = (9, 21)        # broadcasts go out between 9 am and 9 pm Indian time
PREVIEW_MINUTES = 10            # a broadcast must be sent within this long of its preview
MIN_SEARCH_CHARS = 3            # a broadcast's search must be at least this specific
MAX_TEXT_CHARS = 4096
SAMPLE = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cap_message(exc: client_claude.CapReached) -> str:
    left = max(exc.cap - exc.sent, 0)
    return (
        f"Not sent: today's limit for Anril AI is {exc.cap} messages and {exc.sent} are used, so "
        f"{left} are left and this needs {exc.wanted}. The owner can raise the limit in Anril → "
        "Settings, or send tomorrow."
    )


# ── one lead ──────────────────────────────────────────────────────────────────

@client_tool(title="What can be sent to this lead")
def reply_options(lead_id: str) -> dict:
    """Before send_reply: whether this lead can get a free-text WhatsApp message right now (only
    within 24 hours of their last message) and which approved templates can be sent instead,
    with the blanks each one needs."""
    db, tenant = get_supabase(), tenant_id()
    mine = lead_lookup.own_lead(db, tenant, lead_id)
    lead = share._lead(db, tenant, mine["id"])
    if not lead:
        raise ToolError("No lead with that id in your account.")
    if _unreachable(mine):
        return {"can_send": False, "why": _UNREACHABLE}
    if not share._whatsapp_ready(tenant, lead):
        return {"can_send": False, "why": "WhatsApp is not connected, or this lead has no phone number or has opted out."}
    facts = {"customer_name": (lead.get("name") or "").strip(), "business_name": share._business_name(db, tenant)}
    return {
        "can_send": True,
        "lead": lead.get("name") or lead.get("phone"),
        "free_text_allowed": share.window_open(lead.get("last_inbound_at"), _now()),
        "last_customer_message_at": lead.get("last_inbound_at"),
        "templates": [
            {
                "template_id": t["id"], "name": t["name"], "text": t.get("body_text") or "",
                "blanks": share.template_variables(t["name"], t.get("body_text"), facts),
            }
            for t in share._approved_templates(db, tenant)
        ],
    }


_UNREACHABLE = "This lead is blocked, or WhatsApp cannot deliver to this number."


def _unreachable(lead: dict) -> bool:
    return bool(lead.get("blocked_at") or lead.get("whatsapp_undeliverable"))


def _refuse_repeat(db, tenant: str, lead_id: str, content: str, now: datetime) -> None:
    recent = (
        db.table("messages").select("content, created_at")
        .eq("tenant_id", tenant).eq("lead_id", lead_id).eq("direction", "outbound")
        .gte("created_at", (now - timedelta(seconds=REPEAT_SECONDS)).isoformat()).limit(20).execute()
    ).data or []
    if any((m.get("content") or "") == content for m in recent):
        raise ToolError(
            "Not sent: this exact message already went to this lead in the last 2 minutes. "
            "If it really should go twice, wait 2 minutes and send again."
        )


@client_tool(title="Send a WhatsApp message to one lead")
def send_reply(lead_id: str, text: str = "", template_id: str = "", variables: list[str] | None = None) -> dict:
    """Send ONE WhatsApp message to ONE lead, now. The customer receives it and it cannot be
    taken back. Give either `text` (allowed only within 24 hours of the customer's last message)
    or a `template_id` from reply_options with `variables` filling its blanks in order. Counts as
    1 against today's sending limit."""
    body, template = (text or "").strip(), (template_id or "").strip()
    if bool(body) == bool(template):
        raise ToolError("Give either text or a template_id, not both and not neither.")
    if len(body) > MAX_TEXT_CHARS:
        raise ToolError(f"The message is too long ({len(body)} characters, the limit is {MAX_TEXT_CHARS}).")
    db, tenant, who = get_supabase(), tenant_id(), seat()
    lead = lead_lookup.own_lead(db, tenant, lead_id)
    if _unreachable(lead):
        raise ToolError(f"Not sent: {_UNREACHABLE}")
    values = [str(v) for v in (variables or [])]
    now = _now()
    try:
        content = share.prepare_template(db, tenant, template, values)[2] if template else body
    except share.ShareError as exc:
        raise ToolError(str(exc)) from exc
    _refuse_repeat(db, tenant, lead["id"], content, now)
    try:
        used = client_claude.reserve_sends(db, tenant, 1)
    except client_claude.CapReached as exc:
        raise ToolError(_cap_message(exc)) from exc
    try:
        asyncio.run(share.send_details(
            db, tenant, lead["id"], text=body if not template else None, template_id=template or None,
            variables=values, now=now, sender=sender_fields(db, {"user_id": who["user_id"], "tenant_id": tenant}),
        ))
    except share.ShareError as exc:
        client_claude.release_sends(db, tenant, 1)  # it did not leave, so it does not count
        raise ToolError(str(exc)) from exc
    cap = client_claude.daily_cap(db, tenant)
    return {"sent": True, "to": lead.get("name") or lead.get("phone"), "message": content, "left_today": max(cap - used, 0)}


# ── many leads ────────────────────────────────────────────────────────────────

def _template_for_broadcast(db, tenant: str, name: str) -> dict:
    wanted = (name or "").strip()
    usable = [t for t in share._approved_templates(db, tenant) if t.get("name") == wanted]
    if usable:
        return usable[0]
    rows = db.table("message_templates").select("name, status").eq("tenant_id", tenant).eq("name", wanted).limit(1).execute().data or []
    if not rows:
        raise ToolError(f'No template called "{wanted}". Call templates to see the names.')
    if (rows[0].get("status") or "").upper() != "APPROVED":
        raise ToolError(f'"{wanted}" is not approved by Meta ({(rows[0].get("status") or "unknown").lower()}), so it cannot be sent.')
    raise ToolError(
        f'"{wanted}" cannot be sent through Anril AI: it has an image, video or document header, or it '
        "belongs to a WhatsApp account that is no longer connected. Send it from Anril itself."
    )


def _blank_count(template: dict) -> int:
    return max((int(n) for n in _VAR_RE.findall(template.get("body_text") or "")), default=0)


def _fill(value: str, lead: dict, name_fallback: str) -> str | None:
    """One blank for one lead. "{name}" becomes the lead's name; None when there is no name
    and no fallback (that lead is skipped rather than greeted with an empty name)."""
    if "{name}" not in value:
        return value
    name = (lead.get("name") or "").strip() or name_fallback.strip()
    return value.replace("{name}", name) if name else None


def _audience(db, tenant: str, template: dict, variables: list[str], name_fallback: str, filters: dict) -> dict:
    """Who would get the broadcast, by the app's own rules, and who is left out and why."""
    if not any(filters.values()):
        raise ToolError(
            "Say who should get it: at least one of search, segment, source, created_from, "
            "created_to or lead_ids. A broadcast to every lead must be sent from Anril itself."
        )
    if filters["search"]:
        term = lead_lookup.search_term(filters["search"])
        if not term or len(term[1]) < (MIN_SEARCH_CHARS if term[0] == "name" else 4):
            raise ToolError("search needs at least 3 letters of a name or 4 digits of a phone number.")
    if len(variables) != _blank_count(template):
        raise ToolError(
            f'"{template["name"]}" has {_blank_count(template)} blank(s) and {len(variables)} value(s) were given. '
            'Give one value per blank, in order. Use {name} for the customer\'s own name.'
        )
    if any(not (v or "").strip() for v in variables):
        raise ToolError("A value for a blank is empty.")
    limit = client_claude.MAX_DAILY_CAP
    found: list[dict] = []
    start = 0
    while len(found) <= limit:
        page = (
            lead_lookup.filtered(db, tenant, **filters).order("created_at", desc=True)
            .range(start, start + lead_lookup.PAGE - 1).execute()
        ).data or []
        found.extend(page)
        if len(page) < lead_lookup.PAGE:
            break
        start += lead_lookup.PAGE
    if len(found) > limit:
        raise ToolError(f"That matches more than {limit:,} leads. Narrow it down, or send it from Anril itself.")
    if found and not filters["lead_ids"]:
        # A filter that happens to match everybody (created since 2000, a one-source business) is
        # still "every lead". Naming the leads one by one is the only way to mean all of them.
        everyone = (
            db.table("leads").select("id", count="exact").eq("tenant_id", tenant).is_("deleted_at", "null").limit(1).execute()
        ).count or 0
        if len(found) >= everyone:
            raise ToolError(
                "That is every lead you have. A broadcast to everyone must be sent from Anril itself. "
                "Narrow it down (segment, source, dates), or list the leads with lead_ids."
            )
    skipped = {"opted_out_or_blocked": 0, "no_phone_or_undeliverable": 0, "no_recorded_opt_in": 0, "no_name_for_blank": 0, "same_phone_twice": 0}
    seen: set[str] = set()
    people: list[dict] = []
    for lead in found:
        phone = upload._normalize_phone(lead.get("phone") or "")
        source = (lead.get("opt_in_source") or "").strip().lower()
        if lead.get("opted_out") or lead.get("blocked_at"):
            skipped["opted_out_or_blocked"] += 1
        elif not phone or lead.get("whatsapp_undeliverable"):
            skipped["no_phone_or_undeliverable"] += 1
        elif not source or source == "manual":
            skipped["no_recorded_opt_in"] += 1
        elif phone in seen:
            skipped["same_phone_twice"] += 1
        else:
            values = [_fill(v, lead, name_fallback) for v in variables]
            if any(v is None for v in values):
                skipped["no_name_for_blank"] += 1
                continue
            seen.add(phone)
            people.append({"lead": lead, "values": values})
    return {"people": people, "matched": len(found), "skipped": {k: v for k, v in skipped.items() if v}}


def _render(template: dict, values: list[str]) -> str:
    return share.render_template(template.get("body_text"), values)


def _filters(search, segment, source, created_from, created_to, lead_ids) -> dict:
    """The audience filters, trimmed: a blank typed into one of them is not a filter."""
    return {
        "search": (search or "").strip(), "segment": (segment or "").strip(), "source": (source or "").strip(),
        "created_from": (created_from or "").strip(), "created_to": (created_to or "").strip(),
        "lead_ids": [i for i in (lead_ids or []) if str(i).strip()] or None,
    }


def _preview_token(tenant: str, user_id: str, template: dict, name_fallback: str, people: list[dict], expires: int) -> str:
    """Proof that exactly this broadcast (this owner, template, wording and these recipients) was
    previewed. Signed with a key only the server has, so it cannot be made up or reused for a
    different audience, and it stops working at `expires`."""
    what = json.dumps([
        tenant, user_id, template.get("id"), template.get("name"), template.get("body_text"), name_fallback,
        sorted([str(p["lead"]["id"]), p["values"]] for p in people), expires,
    ], separators=(",", ":"), default=str)
    key = hashlib.sha256(b"anril-ai-broadcast-preview:" + settings.supabase_service_key.encode()).digest()
    return f"{expires}.{hmac.new(key, what.encode(), hashlib.sha256).hexdigest()}"


def _check_preview(token: str, tenant: str, user_id: str, template: dict, name_fallback: str, people: list[dict], now: datetime) -> None:
    refusal = ToolError(
        "Not sent: this is not the broadcast that was previewed, or the preview is more than "
        f"{PREVIEW_MINUTES} minutes old. Run preview_broadcast again with the same arguments, tell "
        "the owner who will get it, then send with the new preview_token."
    )
    given = (token or "").strip()
    expires = given.partition(".")[0]
    if not (expires.isascii() and expires.isdigit()) or not now.timestamp() <= int(expires) <= now.timestamp() + PREVIEW_MINUTES * 60:
        raise refusal
    expected = _preview_token(tenant, user_id, template, name_fallback, people, int(expires))
    if not hmac.compare_digest(expected.encode(), given.encode()):
        raise refusal


def _send_time(send_at: str, now: datetime) -> datetime:
    """When the broadcast starts: the time asked for, else 2 minutes from now. Always inside
    sending hours (Indian time), and never more than 30 days ahead."""
    if (send_at or "").strip():
        try:
            when = datetime.fromisoformat(send_at.strip().replace("Z", "+00:00"))
        except ValueError:
            raise ToolError("send_at must look like 2026-11-22T10:00:00+05:30.")
        if when.tzinfo is None:
            when = when.replace(tzinfo=_IST)
        if when < now + timedelta(minutes=1):
            raise ToolError("send_at is in the past.")
        if when > now + timedelta(days=30):
            raise ToolError("send_at can be at most 30 days ahead.")
    else:
        when = now + timedelta(minutes=BROADCAST_DELAY_MINUTES)
    hour = when.astimezone(_IST).hour
    if not SEND_HOURS_IST[0] <= hour < SEND_HOURS_IST[1]:
        raise ToolError(
            "Broadcasts through Anril AI go out between 9 am and 9 pm Indian time. "
            "Pass send_at with a time inside those hours, for example tomorrow 10 am."
        )
    return when


@client_tool(title="Preview a broadcast")
def preview_broadcast(template_name: str, variables: list[str] | None = None, name_fallback: str = "",
                      search: str = "", segment: str = "", source: str = "", created_from: str = "",
                      created_to: str = "", lead_ids: list[str] | None = None) -> dict:
    """ALWAYS call this before send_broadcast. Nothing is sent. Shows exactly who would get an
    approved template, who is left out and why, the message as the first few customers would
    see it, and whether it fits in today's sending limit. `variables` fills the template's
    blanks in order; write {name} where the customer's own name should go (name_fallback is
    used when a lead has no name). The audience filters are the same as find_leads."""
    db, tenant, who = get_supabase(), tenant_id(), seat()
    template = _template_for_broadcast(db, tenant, template_name)
    values = [str(v) for v in (variables or [])]
    audience = _audience(db, tenant, template, values, name_fallback,
                         _filters(search, segment, source, created_from, created_to, lead_ids))
    cap, sent = client_claude.daily_cap(db, tenant), client_claude.sent_today(db, tenant)
    count = len(audience["people"])
    expires = int(_now().timestamp()) + PREVIEW_MINUTES * 60
    return {
        "template": template["name"],
        "recipients": count,
        "matched_leads": audience["matched"],
        "left_out": audience["skipped"],
        "samples": [
            {"to": p["lead"].get("name") or p["lead"].get("phone"), "message": _render(template, p["values"])}
            for p in audience["people"][:SAMPLE]
        ],
        "sending_limit": {"daily_cap": cap, "sent_today": sent, "left_today": max(cap - sent, 0), "fits": count <= max(cap - sent, 0)},
        "preview_token": _preview_token(tenant, who["user_id"], template, name_fallback, audience["people"], expires) if count else None,
        "next": (
            f"Tell the owner who will get this. To send, call send_broadcast with the same arguments "
            f"and this preview_token within {PREVIEW_MINUTES} minutes."
        ) if count else "Nobody would receive this.",
    }


@client_tool(title="Send a broadcast")
def send_broadcast(template_name: str, preview_token: str, variables: list[str] | None = None,
                   name_fallback: str = "", search: str = "", segment: str = "", source: str = "",
                   created_from: str = "", created_to: str = "", lead_ids: list[str] | None = None,
                   send_at: str = "") -> dict:
    """Send an approved WhatsApp template to MANY customers. Real customers receive it and each
    message is billed. Call preview_broadcast first, tell the owner who will get it, then pass
    its `preview_token` here with the same arguments: without a preview of exactly this
    broadcast from the last 10 minutes, or if the audience has changed since, nothing is sent.
    It starts 2 minutes after this call (or at send_at, like 2026-11-22T10:00:00+05:30),
    only between 9 am and 9 pm Indian time, and until it starts it can be cancelled in Anril →
    Broadcasts. Every recipient counts against today's sending limit."""
    db, tenant, who = get_supabase(), tenant_id(), seat()
    template = _template_for_broadcast(db, tenant, template_name)
    values = [str(v) for v in (variables or [])]
    audience = _audience(db, tenant, template, values, name_fallback,
                         _filters(search, segment, source, created_from, created_to, lead_ids))
    people = audience["people"]
    if not people:
        raise ToolError("Nobody would receive this, so nothing was sent.")
    now = _now()
    _check_preview(preview_token, tenant, who["user_id"], template, name_fallback, people, now)
    when = _send_time(send_at, now)
    repeat = (
        db.table("scheduled_broadcasts").select("id, recipient_count, created_at")
        .eq("tenant_id", tenant).eq("template_name", template["name"])
        .gte("created_at", (now - timedelta(minutes=BROADCAST_REPEAT_MINUTES)).isoformat()).limit(20).execute()
    ).data or []
    if any(int(r.get("recipient_count") or 0) == len(people) for r in repeat):
        raise ToolError(
            f"Not sent: the same template was already scheduled for {len(people)} people in the last "
            f"{BROADCAST_REPEAT_MINUTES} minutes. Check Anril → Broadcasts before sending it again."
        )
    try:
        used = client_claude.reserve_sends(db, tenant, len(people))
    except client_claude.CapReached as exc:
        raise ToolError(_cap_message(exc)) from exc
    columns = [f"v{i + 1}" for i in range(len(values))]
    body = upload.BulkSendRequest(
        leads=[
            upload.BulkLeadItem(
                phone=p["lead"]["phone"], name=p["lead"].get("name"), opt_in_source=p["lead"].get("opt_in_source"),
                extra_cols=dict(zip(columns, p["values"])),
            )
            for p in people
        ],
        template_name=template["name"],
        schedule_type="scheduled",  # never "immediate": that path sends from a background task of the web request
        schedule_at=when.isoformat(),
        variable_mapping=columns,
    )
    try:
        result = asyncio.run(upload.bulk_send(body, tenant_id=tenant, _ctx={"user_id": who["user_id"]}))
    except HTTPException as exc:
        if exc.status_code < 500:  # the app refused it before saving anything
            client_claude.release_sends(db, tenant, len(people))
        raise
    # Any other failure: it may have been saved, so the booking stays (the cap errs on the low side).
    total = int((result or {}).get("total") or 0)
    if result.get("status") != "scheduled" or total <= 0:
        client_claude.release_sends(db, tenant, len(people))
        raise ToolError("Anril did not schedule the broadcast, so nothing will be sent.")
    if total < len(people):
        client_claude.release_sends(db, tenant, len(people) - total)
    cap = client_claude.daily_cap(db, tenant)
    return {
        "scheduled": True, "template": template["name"], "recipients": total,
        "starts_at": when.astimezone(_IST).isoformat(),
        "cancel": "Until it starts: Anril → Broadcasts → Scheduled.",
        "left_today": max(cap - used + (len(people) - total), 0),
    }

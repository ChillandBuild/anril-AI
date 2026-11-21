"""WhatsApp Forms, Phase 3: when a form goes out by itself, and its numbers.

Every rule is the client's own, per form (whatsapp_form_designs.triggers):
  * ai          -- the AI may send it when the chat matches the client's "when" text
  * ads         -- a customer arriving from a Click-to-WhatsApp ad (every ad, or chosen ads)
  * broadcasts  -- a customer replying to a broadcast that used one of the chosen templates
For ads and broadcasts the client also chooses whether the form goes INSTEAD of Anril's first
reply or AFTER it. And a template can carry an "Open form" button (Meta FLOW button): its
signed token is added to every send by meta_cloud.send_template_message, whoever sends it.

All automatic sends respect Settings > Auto-Reply (the caller checks before sending).
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from app.services import whatsapp_forms as wf

logger = logging.getLogger(__name__)

TIMINGS = ("instead", "after")
WHEN_MAX = 300
MAX_ADS = 200
MAX_TEMPLATES = 50
RESEND_AFTER = timedelta(days=7)  # the same rule won't send the same form to one person again sooner
_TEMPLATE_RE = re.compile(r"^\[Template: (.+?)\]")


# ── rules ────────────────────────────────────────────────────────────────────


def clean_triggers(raw) -> dict:
    """Stored shape, with anything unknown dropped."""
    raw = raw if isinstance(raw, dict) else {}
    ai = raw.get("ai") if isinstance(raw.get("ai"), dict) else {}
    ads = raw.get("ads") if isinstance(raw.get("ads"), dict) else {}
    casts = raw.get("broadcasts") if isinstance(raw.get("broadcasts"), dict) else {}
    return {
        "ai": {"enabled": bool(ai.get("enabled")), "when": " ".join(str(ai.get("when") or "").split())},
        "ads": {
            "enabled": bool(ads.get("enabled")),
            "ad_ids": [str(a).strip() for a in ads.get("ad_ids") or [] if str(a).strip()],
            "timing": ads.get("timing") if ads.get("timing") in TIMINGS else "instead",
        },
        "broadcasts": {
            "enabled": bool(casts.get("enabled")),
            "templates": [str(t).strip() for t in casts.get("templates") or [] if str(t).strip()],
            "timing": casts.get("timing") if casts.get("timing") in TIMINGS else "instead",
        },
    }


def trigger_problems(raw) -> list[str]:
    t = clean_triggers(raw)
    out: list[str] = []
    if t["ai"]["enabled"] and not t["ai"]["when"]:
        out.append("Tell Anril when to send this form, e.g. “when someone wants to visit the site”.")
    if len(t["ai"]["when"]) > WHEN_MAX:
        out.append(f"The “when to send” line can be at most {WHEN_MAX} characters.")
    if len(t["ads"]["ad_ids"]) > MAX_ADS or not all(a.isdigit() for a in t["ads"]["ad_ids"]):
        out.append("Pick the ads again: one of them isn't a Meta ad.")
    if t["broadcasts"]["enabled"] and not t["broadcasts"]["templates"]:
        out.append("Pick at least one broadcast template, or switch broadcast replies off.")
    if len(t["broadcasts"]["templates"]) > MAX_TEMPLATES:
        out.append(f"Pick at most {MAX_TEMPLATES} templates.")
    return out


# ── incoming chats: the ad they came from, the broadcast they answered ──────


def _designs_with(db, tenant_id: str, key: str) -> list[dict]:
    rows = (
        db.table("whatsapp_form_designs").select("*").eq("tenant_id", tenant_id).eq("archived", False)
        .order("created_at", desc=True).execute()
    ).data or []
    return [d for d in rows if clean_triggers(d.get("triggers"))[key]["enabled"]]


def _replied_template(db, tenant_id: str, lead_id: str, context_wamid: str | None) -> str | None:
    """The template of the broadcast this message answers (WhatsApp quotes it in context)."""
    if not context_wamid:
        return None
    rows = (
        db.table("messages").select("content").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
        .eq("meta_message_id", context_wamid).eq("direction", "outbound").limit(1).execute()
    ).data or []
    match = _TEMPLATE_RE.match((rows[0].get("content") or "") if rows else "")
    return match.group(1).strip() if match else None


def _recently_sent(db, tenant_id: str, lead_id: str, design_id: str) -> bool:
    since = (datetime.now(timezone.utc) - RESEND_AFTER).isoformat()
    rows = (
        db.table("whatsapp_form_sends").select("id").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
        .eq("design_id", design_id).gte("created_at", since).limit(1).execute()
    ).data or []
    return bool(rows)


def inbound_match(db, tenant_id: str, lead_id: str, *, ad_id: str | None, context_wamid: str | None) -> dict | None:
    """The form this incoming message should get, or None. An ad rule naming this exact ad wins
    over an every-ad rule; ads win over broadcast replies (they're the reason the chat began)."""
    if not wf.is_enabled(db, tenant_id):
        return None
    candidates: list[tuple[int, dict, str, str]] = []  # (rank, design, timing, via)
    if ad_id:
        for d in _designs_with(db, tenant_id, "ads"):
            rule = clean_triggers(d["triggers"])["ads"]
            if not rule["ad_ids"] or ad_id in rule["ad_ids"]:
                candidates.append((0 if rule["ad_ids"] else 1, d, rule["timing"], "ad"))
    template = _replied_template(db, tenant_id, lead_id, context_wamid) if not candidates else None
    if template:
        for d in _designs_with(db, tenant_id, "broadcasts"):
            rule = clean_triggers(d["triggers"])["broadcasts"]
            if template in rule["templates"]:
                candidates.append((2, d, rule["timing"], "broadcast"))
    for _, design, timing, via in sorted(candidates, key=lambda c: c[0]):
        if _recently_sent(db, tenant_id, lead_id, design["id"]):
            continue
        form = wf.live_custom_form(db, tenant_id, design)
        if form:
            return {"design": design, "form": form, "timing": timing, "via": via}
    return None


async def send_match(db, tenant_id: str, lead_id: str, phone: str, match: dict, phone_number_id: str | None = None) -> str | None:
    """Send the matched form (caller already checked Auto-Reply) and log it in the chat."""
    form = match["form"]
    sid = await wf.send_form(phone, form["intro"], form, cta=form["cta"], tenant_id=tenant_id,
                             phone_number_id=phone_number_id, via=match["via"], lead_id=lead_id, db=db)
    db.table("messages").insert({
        "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
        "content": wf.form_record(form["intro"], form["cta"]), "is_ai_generated": False, "meta_message_id": sid,
    }).execute()
    return sid


# ── the AI's send_form tool ──────────────────────────────────────────────────

TOOL_SEND_FORM = "send_form"


def ai_forms(db, tenant_id: str) -> list[dict]:
    """Forms the AI may send now: rule on, published with their latest changes."""
    if not wf.is_enabled(db, tenant_id):
        return []
    out = []
    for d in _designs_with(db, tenant_id, "ai"):
        if wf.live_custom_form(db, tenant_id, d):
            out.append({"id": d["id"], "name": d["name"], "when": clean_triggers(d["triggers"])["ai"]["when"]})
    return out


def ai_tool(forms: list[dict]) -> dict | None:
    if not forms:
        return None
    lines = "\n".join(f"- {f['id']}: \"{f['name']}\" -- send when: {f['when']}" for f in forms)
    return {
        "type": "function",
        "function": {
            "name": TOOL_SEND_FORM,
            "description": (
                "Send the customer one of the business's WhatsApp Forms (it opens inside WhatsApp). "
                "Call it only when the conversation matches that form's 'send when' rule, at most once "
                "per reply, and never for a form they just filled. Your reply text goes above the form's "
                "button, so write one short line inviting them to fill it, in the customer's language.\n"
                f"Forms:\n{lines}"
            ),
            "parameters": {
                "type": "object",
                "properties": {"form_id": {"type": "string", "enum": [f["id"] for f in forms]}},
                "required": ["form_id"],
            },
        },
    }


# ── template "Open form" button ──────────────────────────────────────────────


def resolve_form_button(db, tenant_id: str, form_ref: str) -> dict:
    """For a new template: the form version its button opens. form_ref = a design id, or
    "services" for the Services form. Raises FormBuildError when nothing publishable is live."""
    if form_ref == "services":
        published = wf._latest(db, tenant_id, status="published")
        if not published or not published.get("meta_flow_id"):
            raise wf.FormBuildError("Publish the Services form first (Services → How Anril collects → WhatsApp Form).")
        return {"flow_id": published["meta_flow_id"], "navigate_screen": wf.SCREEN_PACKAGE, "form_ref": "services"}
    design = wf.get_design(db, tenant_id, form_ref)
    if not design or design.get("archived"):
        raise wf.FormBuildError("That form doesn't exist any more.")
    form = wf.live_custom_form(db, tenant_id, design)
    if not form:
        raise wf.FormBuildError(f"Publish “{design['name']}” with its latest changes first.")
    return {"flow_id": form["meta_flow_id"], "navigate_screen": form["first_screen"] or "", "form_ref": design["id"]}


def template_flow_component(db, tenant_id: str, template_name: str, phone: str, components: list) -> dict | None:
    """The FLOW button parameter a template send needs: a token signed for THIS customer.
    Called by meta_cloud.send_template_message for every template send. None when the template
    has no form button or the caller already supplied one."""
    if any(isinstance(c, dict) and c.get("sub_type") == "flow" for c in components or []):
        return None
    rows = (
        db.table("message_templates").select("buttons").eq("tenant_id", tenant_id).eq("name", template_name)
        .limit(5).execute()
    ).data or []
    for row in rows:
        buttons = [b for b in (row.get("buttons") or []) if isinstance(b, dict)]
        for index, button in enumerate(buttons):
            if str(button.get("type") or "").upper() != "FLOW" or not button.get("flow_id"):
                continue
            versions = (
                db.table("whatsapp_forms").select("id, design_id").eq("tenant_id", tenant_id)
                .eq("meta_flow_id", str(button["flow_id"])).limit(1).execute()
            ).data or []
            if not versions:
                return None  # a form made outside Anril: Meta's default token, answers continue in chat
            send_id = secrets.token_hex(6)
            wf.record_send(tenant_id, versions[0], send_id=send_id, via="template", phone=phone, db=db)
            return {
                "type": "button", "sub_type": "flow", "index": str(index),
                "parameters": [{"type": "action", "action": {
                    "flow_token": wf.make_token(tenant_id, phone, versions[0]["id"], send_id)}}],
            }
    return None


def group_buttons(buttons: list[dict]) -> list[dict]:
    """The order Meta keeps a template's buttons in (call-to-actions first, then quick replies),
    so a stored button's position is its send index."""
    ctas = [b for b in buttons if str(b.get("type") or "").upper() in ("URL", "PHONE_NUMBER", "COPY_CODE", "FLOW")]
    return ctas + [b for b in buttons if b not in ctas]


# ── numbers ──────────────────────────────────────────────────────────────────


def stats(db, tenant_id: str, design_id: str | None) -> dict:
    """Sent / submitted / paid for one custom form (design_id) or the Services form (None)."""
    sends = db.table("whatsapp_form_sends").select("id", count="exact").eq("tenant_id", tenant_id)
    sends = sends.eq("design_id", design_id) if design_id else sends.is_("design_id", "null")
    sent = sends.limit(1).execute().count or 0
    query = db.table("whatsapp_forms").select("id").eq("tenant_id", tenant_id)
    query = query.eq("kind", "custom").eq("design_id", design_id) if design_id else query.eq("kind", "intake")
    ids = [r["id"] for r in query.execute().data or []]
    submitted = paid = 0
    if ids:
        responses = (
            db.table("whatsapp_form_responses").select("intake_session_id").eq("tenant_id", tenant_id)
            .in_("form_id", ids).neq("outcome", "rejected").execute()
        ).data or []
        submitted = len(responses)
        sessions = [r["intake_session_id"] for r in responses if r.get("intake_session_id")]
        if sessions and not design_id:
            paid = (
                db.table("intake_sessions").select("id", count="exact").eq("tenant_id", tenant_id)
                .in_("id", sessions).in_("status", ["paid", "resolved"]).limit(1).execute()
            ).count or 0
    return {"sent": sent, "submitted": submitted, "paid": paid if not design_id else None}

"""'Send details on WhatsApp' on the lead page (call wrap-up v2 spec §5).

Free message when the customer wrote in the last 24 h (pre-filled from the Services
page), otherwise an approved template with its blanks pre-filled. Nothing is sent
without a tap; the message is logged in `messages`, so it shows in Conversations."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import HTTPException

from app.config_dynamic import get_setting
from app.services.ai_reply import get_last_send_error, send_whatsapp
from app.services.call_wrapup import REMINDER_OUTCOMES, next_step_phrase
from app.services.intake import get_intake_config, normalize_packages
from app.services.meta_cloud import send_template_message

VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
FREE_WINDOW = timedelta(hours=24)
# The two templates the owner submits for approval (spec §1); any other template's blanks start empty.
KNOWN_TEMPLATE_ROLES = {
    "call_details_share": ("customer_name", "business_name", "details"),
    "call_details_next_step": ("customer_name", "details", "next_step"),
}


class ShareError(ValueError):
    """Something the telecaller can fix or needs to know; the route turns it into a 400."""


def _rupees(paise: int) -> str:
    return f"₹{paise // 100}" if paise % 100 == 0 else f"₹{paise / 100:.2f}"


def _active(nodes: list[dict] | None) -> list[dict]:
    return [n for n in nodes or [] if n.get("active", True) and (n.get("name") or "").strip()]


def services_text(packages: list[dict], depth: int = 0) -> str:
    indent = "  " * depth
    lines = []
    for p in _active(packages):
        name = p["name"].strip()
        if p.get("options"):
            lines.append(f"{indent}• {name}")
            inner = services_text(p["options"], depth + 1)
            if inner:
                lines.append(inner)
        else:
            lines.append(f"{indent}• {name} — {_rupees(p.get('amount_paise') or 0)}")
        description = (p.get("description") or "").strip()
        if description:
            lines.append(f"{indent}  {description}")
    return "\n".join(lines)


def services_one_line(packages: list[dict]) -> str:
    """WhatsApp template parameters can't hold new lines, so templates get this form."""
    parts = []
    for p in _active(packages):
        name = p["name"].strip()
        if p.get("options"):
            inner = services_one_line(p["options"])
            parts.append(f"{name} ({inner})" if inner else name)
        else:
            parts.append(f"{name} {_rupees(p.get('amount_paise') or 0)}")
    return "; ".join(parts)


def one_line(text: str | None) -> str:
    return " ".join((text or "").split())


def free_message(customer_name: str | None, business_name: str, details: str, next_step: str) -> str:
    first = (customer_name or "").strip().split(" ")[0] or "there"
    parts = [f"Hi {first}, thank you for your time on the call today."]
    if details:
        parts.append(f"Here are the details from {business_name or 'us'}:\n\n{details}")
    if next_step:
        parts.append(f"{next_step}.")
    return "\n\n".join(parts)


def template_variables(name: str, body: str | None, facts: dict) -> list[dict]:
    count = max((int(m) for m in VAR_RE.findall(body or "")), default=0)
    roles = KNOWN_TEMPLATE_ROLES.get(name, ())
    out = []
    for i in range(1, count + 1):
        role = roles[i - 1] if i - 1 < len(roles) else None
        out.append({"key": str(i), "role": role, "value": facts.get(role, "") if role else ""})
    return out


def render_template(body: str | None, values: list[str]) -> str:
    def sub(match: re.Match) -> str:
        i = int(match.group(1))
        return values[i - 1] if 0 < i <= len(values) and values[i - 1] else match.group(0)
    return VAR_RE.sub(sub, body or "")


def window_open(last_inbound_at: str | None, now: datetime) -> bool:
    if not last_inbound_at:
        return False
    at = datetime.fromisoformat(str(last_inbound_at).replace("Z", "+00:00"))
    return now - at < FREE_WINDOW


def _lead(db, tenant_id: str, lead_id: str) -> dict | None:
    rows = (
        db.table("leads").select("id,name,phone,opted_out,last_inbound_at")
        .eq("id", lead_id).eq("tenant_id", tenant_id).is_("deleted_at", "null").limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def _whatsapp_ready(tenant_id: str, lead: dict) -> bool:
    connected = get_setting("meta_phone_number_id", tenant_id=tenant_id) and get_setting("meta_access_token", tenant_id=tenant_id)
    return bool(connected and lead.get("phone") and not lead.get("opted_out"))


def _business_name(db, tenant_id: str) -> str:
    rows = db.table("tenants").select("name").eq("id", tenant_id).limit(1).execute().data or []
    return ((rows[0].get("name") if rows else None) or "").strip()


def _next_step(db, tenant_id: str, lead_id: str, now: datetime) -> str:
    rows = (
        db.table("call_logs").select("outcome,next_action_at,created_at")
        .eq("lead_id", lead_id).eq("tenant_id", tenant_id).in_("outcome", list(REMINDER_OUTCOMES))
        .order("created_at", desc=True).limit(1).execute()
    ).data or []
    if not rows or not rows[0].get("next_action_at"):
        return ""
    at = datetime.fromisoformat(str(rows[0]["next_action_at"]).replace("Z", "+00:00"))
    return next_step_phrase(rows[0]["outcome"], at, now) if at > now else ""


def _approved_templates(db, tenant_id: str) -> list[dict]:
    """Approved, text-only templates on the tenant's current WhatsApp account."""
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    if not waba_id:
        return []
    rows = db.table("message_templates").select("*").eq("tenant_id", tenant_id).execute().data or []
    return [
        r for r in rows
        if (r.get("status") or "").upper() == "APPROVED" and r.get("meta_waba_id") == waba_id and not r.get("header_media_type")
    ]


def compose_templates(db, tenant_id: str) -> list[dict]:
    """Approved templates for a message to a number that may not be a lead yet.

    Blanks tied to the business are pre-filled; the customer's name is left for
    the caller to fill from what was typed."""
    business = _business_name(db, tenant_id)
    return [
        {
            "id": t["id"], "name": t["name"], "language": t.get("language") or "en",
            "body_text": t.get("body_text") or "",
            "variables": template_variables(t["name"], t.get("body_text"), {"business_name": business}),
        }
        for t in _approved_templates(db, tenant_id)
    ]


def prepare_template(db, tenant_id: str, template_id: str, variables: list[str]) -> tuple[dict, list[str], str]:
    """Checks a template is approved on the current WhatsApp account and every blank is filled.
    Returns (template, values, the text as the customer sees it); nothing is sent."""
    template = next((t for t in _approved_templates(db, tenant_id) if t["id"] == template_id), None)
    if not template:
        raise ShareError("That template isn't approved for this WhatsApp number.")
    values = [one_line(v) for v in variables]
    count = len(template_variables(template["name"], template.get("body_text"), {}))
    if len(values) != count or any(not v for v in values):
        raise ShareError("Fill every blank in the template.")
    return template, values, render_template(template.get("body_text"), values)


async def send_approved_template(db, tenant_id: str, phone: str, template_id: str, variables: list[str]) -> tuple[str | None, str]:
    """Send one approved template; returns (Meta message id, the text as the customer sees it)."""
    template, values, content = prepare_template(db, tenant_id, template_id, variables)
    components = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in values]}] if values else None
    try:
        resp = await send_template_message(
            phone, template["name"], template.get("language") or "en", components=components, tenant_id=tenant_id,
        )
    except HTTPException as e:
        raise ShareError(f"WhatsApp didn't send it: {str(e.detail)[:300]}")
    sid = ((resp or {}).get("messages") or [{}])[0].get("id")
    return sid, content


def share_context(db, tenant_id: str, lead_id: str, *, now: datetime) -> dict | None:
    lead = _lead(db, tenant_id, lead_id)
    if not lead:
        return None
    if not _whatsapp_ready(tenant_id, lead):
        return {"available": False}
    # Four independent Supabase round trips; run together so the card isn't 4x one trip late.
    with ThreadPoolExecutor(max_workers=4) as pool:
        intake = pool.submit(get_intake_config, tenant_id, db)
        business_f = pool.submit(_business_name, db, tenant_id)
        next_step_f = pool.submit(_next_step, db, tenant_id, lead_id, now)
        templates_f = pool.submit(_approved_templates, db, tenant_id)
        packages = normalize_packages(intake.result())
        business, next_step, templates = business_f.result(), next_step_f.result(), templates_f.result()
    facts = {
        "customer_name": (lead.get("name") or "").strip(), "business_name": business,
        "details": services_one_line(packages), "next_step": next_step,
    }
    return {
        "available": True,
        "window_open": window_open(lead.get("last_inbound_at"), now),
        "last_inbound_at": lead.get("last_inbound_at"),
        "free_text": free_message(lead.get("name"), business, services_text(packages), next_step),
        "templates": [
            {
                "id": t["id"], "name": t["name"], "language": t.get("language") or "en",
                "body_text": t.get("body_text") or "",
                "variables": template_variables(t["name"], t.get("body_text"), facts),
            }
            for t in templates
        ],
    }


async def send_details(db, tenant_id: str, lead_id: str, *, text: str | None, template_id: str | None,
                       variables: list[str], now: datetime) -> dict:
    lead = _lead(db, tenant_id, lead_id)
    if not lead:
        raise ShareError("Lead not found.")
    if not _whatsapp_ready(tenant_id, lead):
        raise ShareError("WhatsApp isn't available for this lead.")
    if text is not None:
        body = text.strip()
        if not body:
            raise ShareError("The message is empty.")
        if not window_open(lead.get("last_inbound_at"), now):
            raise ShareError("The customer hasn't messaged in the last 24 hours, so send a template instead.")
        sid = await send_whatsapp(lead["phone"], body, tenant_id=tenant_id)
        if not sid:
            raise ShareError(f"WhatsApp didn't send it: {get_last_send_error() or 'unknown error'}")
        content = body
    else:
        sid, content = await send_approved_template(db, tenant_id, lead["phone"], template_id or "", variables)
    rows = db.table("messages").insert({
        "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
        "content": content, "is_ai_generated": False, "meta_message_id": sid,
    }).execute().data or []
    return rows[0] if rows else {"sent": True}

"""v9.2: details about a customer, saved by the AI agent from the chat or typed by the team.

Values live in leads.collected_data (shared with form answers: Instant forms, WhatsApp forms,
IndiaMART, JustDial). leads.detail_sources (migration 340) records who set each one:
  {"budget": {"by": "ai", "at": "..."}}  or  {"budget": {"by": "staff", "name": "Karthik", "at": "..."}}
A key with no entry came from a form.

Rules (see docs/research/v92-last-items-preview.html):
- The AI saves only what the customer said: one small model call (read_and_save) that runs alongside each
  AI reply, never in its way. Not a reply tool: this provider writes no text on a turn where it calls a
  tool, so a tool would cost a second full reply round on every message with a detail in it.
- The AI updates its own values when the customer changes their mind.
- The AI never writes over a value the team set, or a form answer.
"""
import logging
from datetime import datetime, timezone

from app.services.properties import business_kind

logger = logging.getLogger(__name__)

MAX_VALUE = 120

COMMON: dict[str, tuple[str, str]] = {
    "wants": ("What they want", "What the customer wants to buy or book, in a few words (e.g. 'Bridal saree, red silk')."),
    "budget": ("Budget", "The budget the customer said, with the currency (e.g. '₹15,000', 'up to ₹50 lakh')."),
    "needed_by": ("Needed by", "When they need it or plan to buy (e.g. 'January, for a wedding', 'this month')."),
    "city": ("City / area", "The city or area the customer said they are in or want."),
}
REAL_ESTATE: dict[str, tuple[str, str]] = {
    "bhk": ("BHK", "Flat size they want (e.g. '2BHK')."),
    "needs_loan": ("Needs a loan", "'Yes' or 'No', only when they said whether they need a home loan."),
    "site_visit": ("Site visit", "The site-visit day and time they agreed to (e.g. 'Sun 15 Nov, 11 AM')."),
}
EDUCATION: dict[str, tuple[str, str]] = {
    "course": ("Course", "The course they asked about."),
    "preferred_batch": ("Preferred batch", "The batch timing or start they prefer (e.g. 'Morning, December')."),
}


def fields_for(kind: str | None) -> dict[str, tuple[str, str]]:
    extra = REAL_ESTATE if kind == "real_estate" else EDUCATION if kind == "education" else {}
    return {**COMMON, **extra}


def _kind(db, tenant_id: str) -> str | None:
    try:
        rows = db.table("tenants").select("business_type").eq("id", tenant_id).limit(1).execute().data or []
        return business_kind((rows[0] or {}).get("business_type")) if rows else None
    except Exception as e:  # noqa: BLE001
        logger.info("lead details: business type unavailable for %s: %s", tenant_id, type(e).__name__)
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return " ".join(str(value).split())[:MAX_VALUE]


def _label(key: str, fields: dict[str, tuple[str, str]]) -> str:
    if key in fields:
        return fields[key][0]
    s = key.replace("_", " ").replace("-", " ").strip()
    return s[:1].upper() + s[1:]


def _load(db, tenant_id: str, lead_id: str) -> dict | None:
    rows = (db.table("leads").select("id, collected_data, detail_sources").eq("id", lead_id)
            .eq("tenant_id", tenant_id).limit(1).execute()).data or []
    return rows[0] if rows else None


# ---------------------------------------------------------------- the AI read

_EXTRACT = """You read a WhatsApp chat between a customer and a business and pick out facts the CUSTOMER
stated about what they want. Fields:
{fields}

Rules:
- Use only what the customer said, or clearly agreed to (e.g. "11 AM ok" to a visit time the business offered).
- Never guess. Never use what the business offered but the customer did not take.
- Write each value short, in English, keeping amounts and dates as the customer gave them.
- Leave out any field the customer did not mention.
Reply with ONLY a JSON object of the fields you found, e.g. {{"budget": "₹15,000"}}, or {{}} when none.

Chat (oldest first):
{chat}"""

_tasks: set = set()  # strong references: a bare create_task can be garbage-collected mid-run


def _chat_lines(thread: list[dict], message: str) -> str:
    rows = [r for r in reversed(thread or []) if (r.get("content") or "").strip()]  # thread is newest first
    lines = [f"{'Customer' if r.get('direction') == 'inbound' else 'Business'}: {' '.join(r['content'].split())[:400]}"
             for r in rows]
    last = f"Customer: {' '.join((message or '').split())[:400]}"
    if not lines or lines[-1] != last:
        lines.append(last)
    return "\n".join(lines[-8:])


def parse_values(text: str, fields: dict) -> dict[str, str]:
    """The model's JSON object -> {field: value}, known fields only. {} for anything unreadable."""
    import json
    import re
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in ((k, _clean(v)) for k, v in data.items() if k in fields) if v}


async def read_and_save(db, tenant_id: str, lead_id: str, thread: list[dict], message: str, *, llm=None) -> dict:
    """One small model call over the last few chat lines; saves what it finds. Never raises."""
    try:
        import asyncio
        fields = fields_for(await asyncio.to_thread(_kind, db, tenant_id))
        prompt = _EXTRACT.format(fields="\n".join(f"- {k}: {d}" for k, (_, d) in fields.items()),
                                 chat=_chat_lines(thread, message))
        if llm is None:
            from app.services.ai_reply import _llm_chat
            text = await _llm_chat([{"role": "user", "content": prompt}], max_tokens=200, tenant_id=tenant_id,
                                   purpose="lead_details", temperature=0.0)
        else:
            text = await llm(prompt)
        values = parse_values(text, fields)
        if values:
            await asyncio.to_thread(ai_save, db, tenant_id, lead_id, values)
        return values
    except Exception:
        logger.warning("Customer details read failed for lead %s", lead_id, exc_info=True)
        return {}


def save_in_background(db, tenant_id: str, lead_id: str, thread: list[dict], message: str) -> None:
    """Starts read_and_save without waiting for it, so the customer's reply is never slowed down.
    A message with no letters or digits (a lone emoji, a sticker) is skipped."""
    import asyncio
    import re
    if not re.search(r"\w", message or ""):
        return
    task = asyncio.get_running_loop().create_task(read_and_save(db, tenant_id, lead_id, thread, message))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def ai_save(db, tenant_id: str, lead_id: str, values: dict) -> bool:
    """Saves the AI's values under the rules at the top of this file. True when something changed.
    Never raises."""
    try:
        fields = fields_for(_kind(db, tenant_id))
        wanted = {k: _clean(v) for k, v in (values or {}).items() if k in fields}
        wanted = {k: v for k, v in wanted.items() if v}
        if not wanted:
            return False
        lead = _load(db, tenant_id, lead_id)
        if not lead:
            return False
        collected = dict(lead.get("collected_data") or {})
        sources = dict(lead.get("detail_sources") or {})
        changed = False
        now = _now()
        for key, value in wanted.items():
            src = sources.get(key) if isinstance(sources.get(key), dict) else None
            if src and src.get("by") != "ai":
                continue  # the team set it: never overwrite
            if not src and collected.get(key) not in (None, "", [], {}):
                continue  # a form answer (any shape): kept as the customer gave it
            if _clean(collected.get(key)) == value:
                continue
            collected[key] = value
            sources[key] = {"by": "ai", "at": now}
            changed = True
        if changed:
            db.table("leads").update({"collected_data": collected, "detail_sources": sources}) \
                .eq("id", lead_id).eq("tenant_id", tenant_id).execute()
        return changed
    except Exception:
        logger.warning("Saving customer details failed for lead %s", lead_id, exc_info=True)
        return False


# ---------------------------------------------------------------- the About panel

class DetailError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def view(db, tenant_id: str, lead_id: str) -> dict:
    """{fields: [{key, label, value, by: ai|staff|form, name, at}], addable: [{key, label}]}"""
    lead = _load(db, tenant_id, lead_id)
    if not lead:
        raise DetailError("Customer not found.", 404)
    fields = fields_for(_kind(db, tenant_id))
    collected = lead.get("collected_data") or {}
    sources = lead.get("detail_sources") or {}
    out = []
    for key, value in collected.items():
        text = _clean(value)
        if not text:
            continue
        src = sources.get(key) if isinstance(sources.get(key), dict) else {}
        out.append({"key": key, "label": _label(key, fields), "value": text,
                    "by": src.get("by") or "form", "name": src.get("name"), "at": src.get("at")})
    order = list(fields)
    out.sort(key=lambda f: (order.index(f["key"]) if f["key"] in order else len(order), f["label"]))
    shown = {f["key"] for f in out}
    return {"fields": out, "addable": [{"key": k, "label": lbl} for k, (lbl, _) in fields.items() if k not in shown]}


def staff_set(db, tenant_id: str, lead_id: str, key: str, value: str, *, name: str | None) -> dict:
    """A team member sets (or, with an empty value, clears) one detail. Returns the new view."""
    key = (key or "").strip()
    lead = _load(db, tenant_id, lead_id)
    if not lead:
        raise DetailError("Customer not found.", 404)
    fields = fields_for(_kind(db, tenant_id))
    collected = dict(lead.get("collected_data") or {})
    if key not in fields and key not in collected:
        raise DetailError("Pick one of the details shown.")
    raw = " ".join(str(value or "").split())
    if len(raw) > MAX_VALUE:
        raise DetailError(f"Keep it under {MAX_VALUE} characters.")
    sources = dict(lead.get("detail_sources") or {})
    if raw:
        collected[key] = raw
        sources[key] = {"by": "staff", "name": name, "at": _now()}
    else:  # cleared: the source stays as the team's, so the AI does not fill it back in
        collected.pop(key, None)
        sources[key] = {"by": "staff", "name": name, "at": _now(), "cleared": True}
    db.table("leads").update({"collected_data": collected, "detail_sources": sources}) \
        .eq("id", lead_id).eq("tenant_id", tenant_id).execute()
    return view(db, tenant_id, lead_id)

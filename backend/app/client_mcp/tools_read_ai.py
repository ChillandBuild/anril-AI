"""Ask tools: knowledge, teaching, business profile, Anril Brain, automation, handover, AI-reply
settings and the catalogue. Read-only: the wrapper runs each with the database locked against writes.

Where an Anril page's read is a plain route handler, the tool calls that handler for ONE client (the
client comes from the sign-in via wrapper.tenant_id, never from an argument; every handler argument is
passed by keyword). Where the handler would write, call an RPC or touch storage, the tool reads the
tables itself, filtered by the same client.
"""
import asyncio
from uuid import UUID

from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError

from app.client_mcp.wrapper import client_tool, seat, tenant_id
from app.db.supabase import get_supabase
from app.routes import ai_teach as teach_routes
from app.routes import auto_messages as auto_routes
from app.routes import auto_messages_sent as sent_routes
from app.routes import brain as brain_routes
from app.routes import business_details as business_routes
from app.routes import catalog as catalog_routes
from app.routes import chat_handovers as handover_routes
from app.routes import knowledge as knowledge_routes
from app.services import auto_messages as auto_svc
from app.services import automation_guards, meta_catalog, private_send
from app.services.assignment import get_inbox_config
from app.services.deals import held_quantities

MAX_PAGE = 50
MAX_DOC_TEXT = 30_000
_DOC_FIELDS = (
    "id", "name", "file_type", "size_bytes", "status", "error_message", "created_at", "sorted_at",
    "sort_state", "has_pending_review", "searchable", "search_issue",
)
_ITEM_FIELDS = (
    "id", "name", "item_type", "description", "status", "attributes", "variant_group_id", "price_paise",
    "price_note", "stock_quantity", "gst_rate", "cost_price_paise", "hsn_code", "low_stock_at",
    "created_at", "updated_at",
)
_RULE_FIELDS = ("id", "event", "template_id", "delay_minutes", "variables", "button_param", "enabled", "created_at")


def _ctx() -> dict:
    """What a route handler reads from the signed-in caller. Version 1 lets only the owner connect."""
    return {"tenant_id": tenant_id(), "user_id": seat().get("user_id"), "role": "owner", "permissions": []}


def _run(coro):
    """Route handlers that are `async def`: run one to the end inside this worker thread."""
    try:
        return asyncio.run(coro)
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        raise ToolError(str(exc.detail)) from exc


def _uuid(value: str, what: str) -> UUID:
    try:
        return UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        raise ToolError(f"{what} must be an id taken from the matching list tool.") from None


def _limit(limit: int) -> int:
    if not 1 <= limit <= MAX_PAGE:
        raise ToolError(f"limit must be between 1 and {MAX_PAGE}.")
    return limit


def _pick(row: dict, fields) -> dict:
    return {key: row.get(key) for key in fields}


@client_tool(title="Knowledge Base")
def knowledge_base() -> dict:
    """The files in your Knowledge Base (newest first, at most 50) with whether each is ready for Anril
    to search, plus which of the 8 Business Kit headings Anril already has (readiness)."""
    tenant = tenant_id()
    docs = _run(knowledge_routes.list_documents(tenant_id=tenant)).get("data") or []
    readiness = _run(knowledge_routes.get_readiness(tenant_id=tenant)).get("data") or []
    return {
        "total_documents": len(docs),
        "documents": [_pick(d, _DOC_FIELDS) for d in docs[:MAX_PAGE]],
        "readiness": readiness,
    }


@client_tool(title="One Knowledge Base document")
def knowledge_document_text(document_id: str) -> dict:
    """The text Anril looks up for one Knowledge Base file (its facts if it was sorted, else the whole
    extracted text). document_id is the `id` from knowledge_base. Very long text is cut."""
    row = _run(knowledge_routes.document_content(doc_id=_uuid(document_id, "document_id"), tenant_id=tenant_id()))
    text = row.get("full_text") or ""
    out = _pick(row, ("id", "name", "file_type", "size_bytes", "status", "created_at", "sorted", "sort_state"))
    out["text"] = text[:MAX_DOC_TEXT]
    out["total_chars"] = len(text)
    if len(text) > MAX_DOC_TEXT:
        out["note"] = f"Only the first {MAX_DOC_TEXT} characters are shown."
    return out


@client_tool(title="Teach and offers")
def teach_and_offers() -> dict:
    """What you taught Anril (answers to doubts, the words your shop uses and replies you like, by `kind`,
    newest first, at most 50) and the offers that are on now or start later."""
    ctx = _ctx()
    items = teach_routes.list_items(kind=None, ctx=ctx) or []
    offers = [o for o in (teach_routes.list_offers(ctx=ctx) or []) if o.get("status") in ("live", "upcoming")]
    keep = ("id", "kind", "prompt", "reply", "source", "times_taught", "updated_at")
    return {
        "taught": [_pick(i, keep) for i in items[:MAX_PAGE]],
        "taught_total": len(items),
        "offers": [_pick(o, ("id", "title", "details", "starts_on", "ends_on", "status")) for o in offers[:MAX_PAGE]],
    }


@client_tool(title="Business profile")
def business_profile() -> dict:
    """Your business details as printed on exports: legal name, address, city, state, pincode, GSTIN,
    email, phone, and whether your prices include GST."""
    return business_routes.read_profile(ctx=_ctx())


@client_tool(title="Anril Brain")
def anril_brain() -> dict:
    """What Anril has learned and what is waiting on you: the headline numbers, files to review, failed
    files, rejected templates, what you have told Anril, recent handovers, and the connection status.
    `waiting_count` is the number shown on the sidebar badge."""
    ctx = _ctx()
    return {"brain": brain_routes.get_brain(ctx=ctx), "waiting_count": brain_routes.get_count(ctx=ctx)}


@client_tool(title="Auto-Message rules")
def auto_message_rules() -> dict:
    """Your Auto-Message setup, not the sends: the rules (event, template, whether it has ever sent), the
    approved templates a rule can use, your custom events, this month's sent / failed / skipped counts,
    and whether the website intake link exists (the link itself is not shown)."""
    db, tenant = get_supabase(), tenant_id()
    rows = (
        db.table("auto_message_rules").select("*").eq("tenant_id", tenant).order("created_at").limit(100).execute()
    ).data or []
    approved = auto_svc.approved_template_ids(db, tenant, [r["template_id"] for r in rows if r.get("template_id")])
    rules = []
    for r in rows:
        sent = (
            db.table("auto_message_sends").select("id").eq("tenant_id", tenant)
            .eq("event", r.get("event")).eq("status", "sent").limit(1).execute()
        ).data or []
        rules.append({**_pick(r, _RULE_FIELDS), "has_sent": bool(sent), "template_approved": r.get("template_id") in approved})
    token = auto_routes.get_setting(auto_routes.TOKEN_KEY, tenant_id=tenant)
    return {
        "rules": rules,
        "setup": {"intake_link_created": bool(token), "private_send_on": private_send.has_active_key(db, tenant)},
        "month_summary": auto_routes.month_summary(ctx=_ctx()),
        "events": auto_routes.list_events(ctx=_ctx()),
        "templates": auto_routes.list_templates(ctx=_ctx()).get("templates", []),
    }


@client_tool(title="Auto-Messages sent")
def auto_messages_sent(limit: int = 50) -> dict:
    """Messages that went out by themselves (auto-messages, one-time sends, nudges, follow-ups) over the
    last 7 days with their delivery status, and the Auto-Message send log. limit is rows per list (1 to 50)."""
    limit, ctx = _limit(limit), _ctx()
    return {
        "sent_last_7_days": sent_routes.list_sent(days=7, only_not_sent=False, limit=limit, offset=0, ctx=ctx),
        "send_log": auto_routes.list_sends(status=None, event=None, limit=limit, offset=0, ctx=ctx),
    }


@client_tool(title="Handover queue")
def handover_queue() -> dict:
    """Chats Anril handed to your people: those waiting now (pending), how many are waiting, and the
    latest resolved ones with who solved them and the summary numbers."""
    ctx = _ctx()
    return {
        "pending": (handover_routes.list_handovers(ctx=ctx) or {}).get("data", []),
        "pending_count": handover_routes.handover_count(today_only=False, ctx=ctx).get("count", 0),
        "history": handover_routes.handover_history(limit=25, offset=0, q=None, resolver=None, reason=None, ctx=ctx),
    }


@client_tool(title="AI reply settings")
def ai_reply_settings() -> dict:
    """Whether AI replies are on for the business, whether instant templates are on, the switch for each
    channel and lead source, and your inbox rules (which segments, channels and triggers go to people)."""
    tenant = tenant_id()
    return {
        "ai_replies_on": automation_guards.master_switch_on(tenant),
        "instant_templates_on": automation_guards.template_master_on(tenant),
        "sources": automation_guards.source_rows(tenant),
        "inbox_config": get_inbox_config(tenant),
    }


@client_tool(title="Catalogue")
def catalogue(search: str = "", limit: int = 50) -> dict:
    """Your catalogue items, newest first: price, stock, status and how many sizes/colours are out. search is
    part of a name; limit is 1 to 50. Also the Anril rules for sending pictures, the variant groups and the
    Meta catalogue line. For one item's variants and stock history use catalogue_item."""
    db, tenant, limit = get_supabase(), tenant_id(), _limit(limit)
    query = db.table("catalog_items").select("*").eq("tenant_id", tenant)
    term = " ".join(str(search or "").replace("%", " ").replace("*", " ").split())
    if term:
        query = query.ilike("name", f"%{term}%")
    rows = query.order("created_at", desc=True).limit(limit + 1).execute().data or []
    page = rows[:limit]
    ids = [r["id"] for r in page]
    held = held_quantities(tenant, [r["id"] for r in page if r.get("stock_quantity") is not None], db)
    extras = catalog_routes._list_extras(db, tenant, set(ids)) if ids else {}
    items = [
        {
            **_pick(r, _ITEM_FIELDS), "held_quantity": held.get(r["id"], 0),
            **extras.get(r["id"], catalog_routes._EMPTY_EXTRAS),
        }
        for r in page
    ]
    groups = (_run(catalog_routes.list_variant_groups(tenant_id=tenant)).get("data") or [])[:MAX_PAGE]
    return {
        "items": items,
        "more": len(rows) > limit,
        "ai_rules": _run(catalog_routes.get_ai_rules(tenant_id=tenant)),
        "variant_groups": [_pick(g, ("id", "name", "item_type")) for g in groups],
        "meta_catalogue": meta_catalog.status(db, tenant),
    }


@client_tool(title="One catalogue item")
def catalogue_item(item_id: str) -> dict:
    """One catalogue item with its sizes and colours (each with stock and price), how many photos it has,
    and the latest stock movements. item_id is the `id` from catalogue."""
    db, tenant, item_uuid = get_supabase(), tenant_id(), _uuid(item_id, "item_id")
    rows = (
        db.table("catalog_items").select("*").eq("id", str(item_uuid)).eq("tenant_id", tenant).limit(1).execute()
    ).data or []
    if not rows:
        raise ToolError("Catalogue item not found.")
    item = _pick(rows[0], _ITEM_FIELDS)
    photos = (
        db.table("catalog_media").select("id, label").eq("tenant_id", tenant)
        .eq("catalog_item_id", str(item_uuid)).limit(100).execute()
    ).data or []
    variants = _run(catalog_routes.list_variants(item_id=item_uuid, tenant_id=tenant))
    moves = _run(catalog_routes.stock_movements(item_id=item_uuid, tenant_id=tenant)).get("data") or []
    return {
        "item": item,
        "photos": {"count": len(photos), "labels": [p.get("label") for p in photos if p.get("label")]},
        "variants": variants,
        "stock_movements": [
            _pick(m, ("delta", "quantity_after", "reason", "note", "created_at")) for m in moves[:MAX_PAGE]
        ],
    }

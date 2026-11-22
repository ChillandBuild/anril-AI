"""Where each WhatsApp template is used, in one call.

The Templates page shows "Used in: ..." on every card. That needs every place that can
point at a template: the rules and settings tables, plus the few templates the app sends
by a fixed name (order bills, purchase orders, back in stock). Each place is read once
for the whole tenant (never once per template), and each is read on its own: if one
table can't be read, that place is left out and the rest still show.

Result: {template_id: [{"area", "label", "href", "ended"?}]}. Only templates that are
used appear. "ended" marks a place that used it before but doesn't now (a finished
Reach campaign).
"""
import json
import logging

logger = logging.getLogger(__name__)

_ROW_CAP = 2000

AREAS = {
    "auto_messages": ("Auto-Messages", "/dashboard/auto-messages"),
    "instant_forms": ("Instant forms", "/dashboard/meta-ads"),
    "one_time_sends": ("One-time sends", "/dashboard/scheduled-templates"),
    "reach": ("Reach", "/dashboard/outbound-leads"),
    "follow_ups": ("Follow-ups", "/dashboard/settings/follow-ups"),
    "otp": ("OTP & SMS", "/dashboard/otp"),
    "whatsapp_forms": ("WhatsApp Forms", "/dashboard/forms"),
    "staff_alert": ("Alert to staff", "/dashboard/settings"),
    "marketplace": ("Marketplace welcome", "/dashboard/inbound-leads"),
    "commerce": ("Commerce · bills & orders", "/dashboard/deals"),
    "purchases": ("Purchases", "/dashboard/purchases"),
    "back_in_stock": ("Back in stock", "/dashboard/catalog"),
    "reply_ready": ("Reply ready", "/dashboard/intake"),
}

_BROADCAST_ACTIVE = {"pending", "running"}


def _hit(area: str, *, template_id=None, name=None, label: str | None = None, ended: bool = False) -> dict:
    return {"area": area, "id": template_id, "name": name, "label": label or AREAS[area][0], "ended": ended}


def _rows(db, table: str, columns: str, tenant_id: str, **filters) -> list[dict]:
    q = db.table(table).select(columns).eq("tenant_id", tenant_id)
    for col, val in filters.items():
        q = q.eq(col, val)
    return q.limit(_ROW_CAP).execute().data or []


# ── one reader per place ─────────────────────────────────────────────────────


def _auto_messages(db, tenant_id: str) -> list[dict]:
    from app.services import auto_messages as am

    rules = _rows(db, "auto_message_rules", "template_id, event, enabled", tenant_id)
    labels = {e["key"]: e["label"] for e in am.BUILTIN_EVENTS}
    if any(r.get("event") not in labels for r in rules):
        for e in am.list_custom_events(db, tenant_id):
            labels.setdefault(e["key"], e["label"])
    out = []
    for r in rules:
        event = labels.get(r.get("event")) or r.get("event") or ""
        off = "" if r.get("enabled", True) else " (off)"
        out.append(_hit("auto_messages", template_id=r.get("template_id"), label=f"Auto-Messages · {event}{off}"))
    return out


def _instant_forms(db, tenant_id: str) -> list[dict]:
    return [
        _hit("instant_forms", template_id=r["template_id"])
        for r in _rows(db, "meta_lead_forms", "template_id", tenant_id) if r.get("template_id")
    ]


def _one_time_sends(db, tenant_id: str) -> list[dict]:
    rows = (
        db.table("scheduled_template_sends").select("template_id, template_name")
        .eq("tenant_id", tenant_id).in_("status", ["scheduled", "sending"]).limit(_ROW_CAP).execute()
    ).data or []
    return [_hit("one_time_sends", template_id=r.get("template_id"), name=None if r.get("template_id") else r.get("template_name")) for r in rows]


def _reach(db, tenant_id: str) -> list[dict]:
    rows = _rows(db, "scheduled_broadcasts", "template_name, status", tenant_id)
    live: dict[str, int] = {}
    finished: dict[str, int] = {}
    for r in rows:
        name = r.get("template_name")
        if not name:
            continue
        target = live if (r.get("status") or "") in _BROADCAST_ACTIVE else finished
        target[name] = target.get(name, 0) + 1
    out = []
    for name, n in live.items():
        out.append(_hit("reach", name=name, label=f"Reach · {n} campaign{'s' if n != 1 else ''}"))
    for name in finished:
        if name not in live:
            out.append(_hit("reach", name=name, label="was in Reach · ended", ended=True))
    return out


def _follow_ups(db, tenant_id: str) -> list[dict]:
    out = []
    for r in _rows(db, "reengagement_steps", "template_name, fallback_template_name", tenant_id):
        for key in ("template_name", "fallback_template_name"):
            if r.get(key):
                out.append(_hit("follow_ups", name=r[key]))
    return out


def _otp(db, tenant_id: str) -> list[dict]:
    return [
        _hit("otp", name=r["wa_template_name"])
        for r in _rows(db, "otp_settings", "wa_template_name", tenant_id) if r.get("wa_template_name")
    ]


def _whatsapp_forms(db, tenant_id: str) -> list[dict]:
    from app.services.whatsapp_form_reach import clean_triggers

    out = []
    for r in _rows(db, "whatsapp_form_designs", "triggers", tenant_id, archived=False):
        casts = clean_triggers(r.get("triggers"))["broadcasts"]
        if casts["enabled"]:
            out += [_hit("whatsapp_forms", name=n) for n in casts["templates"]]
    return out


def _app_settings(db, tenant_id: str) -> list[dict]:
    rows = (
        db.table("app_settings").select("key, value").eq("tenant_id", tenant_id)
        .in_("key", ["notification_config", "marketplace_welcome_template"]).execute()
    ).data or []
    out = []
    for r in rows:
        if r.get("key") == "marketplace_welcome_template" and r.get("value"):
            out.append(_hit("marketplace", template_id=str(r["value"]).strip()))
        elif r.get("key") == "notification_config":
            try:
                cfg = json.loads(r.get("value") or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(cfg, dict):
                continue
            for part in ("whatsapp_notifications", "whatsapp_escalation_notifications"):
                section = cfg.get(part)
                tid = section.get("template_id") if isinstance(section, dict) else None
                if tid:
                    off = "" if section.get("enabled") else " (off)"
                    out.append(_hit("staff_alert", template_id=tid, label=f"Alert to staff{off}"))
    return out


def _fixed_names(db, tenant_id: str) -> list[dict]:
    """Templates the app sends by a fixed name, so they are in use whenever they exist."""
    from app.config_dynamic import get_setting
    from app.services import intake, orders, purchases, stock_asks

    out = [_hit("commerce", name=t["name"]) for t in orders.ORDER_TEMPLATES.values()]
    out.append(_hit("purchases", name=purchases.TEMPLATE["name"]))
    out.append(_hit("back_in_stock", name=stock_asks.TEMPLATE_NAME))
    reply = get_setting("astro_reply_template_name", fallback=intake._REPLY_READY_TEMPLATE_DEFAULT, tenant_id=tenant_id)
    out.append(_hit("reply_ready", name=reply or intake._REPLY_READY_TEMPLATE_DEFAULT))
    return out


_SOURCES = (
    _auto_messages, _instant_forms, _one_time_sends, _reach, _follow_ups, _otp,
    _whatsapp_forms, _app_settings, _fixed_names,
)


def build_usage(db, tenant_id: str, templates: list[dict]) -> dict[str, list[dict]]:
    """`templates` = the rows this tenant can see (already limited to the connected WhatsApp account)."""
    ids = {t["id"] for t in templates}
    by_name: dict[str, list[str]] = {}
    for t in templates:
        by_name.setdefault(t.get("name") or "", []).append(t["id"])

    usage: dict[str, list[dict]] = {}
    seen: set[tuple[str, str, str]] = set()
    for source in _SOURCES:
        try:
            hits = source(db, tenant_id)
        except Exception as e:  # one place that can't be read must not hide the others
            logger.warning(f"template usage: {source.__name__} skipped for tenant {tenant_id}: {e}")
            continue
        for h in hits:
            targets = []
            if h["id"] and h["id"] in ids:
                targets.append(h["id"])
            if h["name"]:
                targets += by_name.get(h["name"], [])
            for tid in targets:
                key = (tid, h["area"], h["label"])
                if key in seen:
                    continue
                seen.add(key)
                entry = {"area": h["area"], "label": h["label"], "href": AREAS[h["area"]][1]}
                if h["ended"]:
                    entry["ended"] = True
                usage.setdefault(tid, []).append(entry)
    return usage

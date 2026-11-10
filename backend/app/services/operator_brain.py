"""Anril Brain for the operator console: one client's brain, read-only, plus the operator-only
rows (master prompt, reply model, language, retrieval, provider keys), the decision history
and the fallback-signals count.

Reuses services/brain for every shared block. Nothing here writes, and no secret value ever
leaves this module: provider keys are reduced to present / missing before they are returned."""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.services import assignment, brain
from app.services.ai_reply import _TRIGGER_REASONS, _provider_and_native_model, reply_model_or_default

logger = logging.getLogger(__name__)

# The operator sees everything a client with view access sees. No manage keys: every input
# comes back can_edit false.
OPERATOR_VIEW_PERMISSIONS = ("knowledge.view", "settings.view", "catalog.view", "conversations.view")
READ_ONLY_REASON = "Read-only in the operator console"

FALLBACK_WINDOW_DAYS = 30
FALLBACK_TRIGGERS = ("A", "B")
ESCALATION_OFF_NOTE = "Counts only when inbox escalation is on"
ESCALATION_PARTIAL_NOTE = "Counts only when inbox escalation covers the A and B triggers"

HISTORY_LIMIT = 20

DEFAULT_RETRIEVAL_MODE = "semantic"
DEFAULT_LANGUAGE_MODE = "mirror"
MASTER_PROMPT_KEY = "default_master_prompt"

# provider (as returned by ai_reply._provider_and_native_model) -> (label, stored key)
PROVIDER_KEYS = {
    "gemini": ("Gemini", "gemini_api_key"),
    "jina": ("Jina (embeddings)", "jina_api_key"),
}
_SETTING_KEYS = (
    "ai_reply_model", "reply_language_mode", "kb_retrieval_mode",
    *(key for _, key in PROVIDER_KEYS.values()),
)

VERSION_REASON_LABELS = {
    "baseline": "Starting version saved",
    "edit": "Description edited",
    "upload": "Sorted file approved",
    "resort": "Re-sorted file approved",
    "delete_document": "File removed",
    "restore": "Earlier version restored",
}


class TenantNotFound(Exception):
    """The id is not a UUID, or no tenant has it."""


def load_tenant(db, tenant_id: str) -> dict:
    """404 source: a malformed id never reaches the database."""
    try:
        uuid.UUID(tenant_id)
    except (ValueError, AttributeError, TypeError):
        raise TenantNotFound(tenant_id) from None
    rows = db.table("tenants").select("id,name").eq("id", tenant_id).limit(1).execute().data or []
    if not rows:
        raise TenantNotFound(tenant_id)
    return rows[0]


def _as_read_only(inputs: list[dict]) -> list[dict]:
    return [{**row, "can_edit": False, "reason": READ_ONLY_REASON} for row in inputs]


def _row(key: str, label: str, state: str, detail: str, *, href: str, section: str | None) -> dict:
    """href is the existing page that edits it; section names the client-console view to open
    when that page is the Config tab (the console switches views in place)."""
    return {"key": key, "label": label, "state": state, "detail": detail, "href": href, "section": section}


def _tenant_settings(db, tenant_id: str) -> dict[str, str]:
    rows = (
        db.table("app_settings").select("key,value").eq("tenant_id", tenant_id).in_("key", list(_SETTING_KEYS)).execute()
    ).data or []
    return {r["key"]: r.get("value") or "" for r in rows}


def _master_prompt_row(db) -> dict:
    """Length and last-updated only: the text itself is edited (and readable) at the
    prompt-template page."""
    rows = (
        db.table("platform_defaults").select("value,updated_at").eq("key", MASTER_PROMPT_KEY).limit(1).execute()
    ).data or []
    text = ((rows[0].get("value") if rows else None) or "").strip()
    if not text:
        return _row(
            "master_prompt", "Master prompt (platform-wide)", "attention", "Empty: Anril is using the built-in fallback prompt",
            href="/operator/prompt-template", section=None,
        )
    updated = rows[0].get("updated_at")
    detail = f"{len(text):,} characters" + (f", updated {updated[:10]}" if updated else "")
    return _row("master_prompt", "Master prompt (platform-wide)", "ok", detail, href="/operator/prompt-template", section=None)


def _needed_providers(model: str, retrieval_mode: str) -> set[str]:
    needed: set[str] = set()
    try:
        needed.add(_provider_and_native_model(model)[0])
    except RuntimeError:
        logger.warning("operator brain: unrecognised reply model %r", model)
    if retrieval_mode in ("semantic", "hybrid"):
        needed.add("jina")
    return needed


def _provider_key_rows(settings: dict[str, str], needed: set[str], tenant_id: str) -> list[dict]:
    rows = []
    for provider, (label, setting_key) in PROVIDER_KEYS.items():
        present = bool(settings.get(setting_key))
        if present:
            state, detail = "ok", "Present"
        elif provider in needed:
            state, detail = "missing", "Missing, and this client needs it"
        else:
            state, detail = "off", "Missing (not needed by the current settings)"
        rows.append(_row(f"key_{provider}", f"{label} key", state, detail, href=f"/operator/client/{tenant_id}", section="config"))
    return rows


def operator_rows(db, tenant_id: str) -> list[dict]:
    """Master prompt, reply model, language mode, retrieval mode, provider keys. Each is
    {key, label, state, detail, href, section}; key values are never included."""
    settings = _tenant_settings(db, tenant_id)
    model = reply_model_or_default(settings.get("ai_reply_model"))
    language = settings.get("reply_language_mode") or DEFAULT_LANGUAGE_MODE
    retrieval = (settings.get("kb_retrieval_mode") or DEFAULT_RETRIEVAL_MODE).lower()
    link = {"href": f"/operator/client/{tenant_id}", "section": "config"}
    return [
        _master_prompt_row(db),
        _row("reply_model", "Reply model", "ok", model, **link),
        _row("language_mode", "Language mode", "ok", language, **link),
        _row("retrieval_mode", "Knowledge retrieval mode", "ok", retrieval, **link),
        *_provider_key_rows(settings, _needed_providers(model, retrieval), tenant_id),
    ]


def fallback_signals(db, tenant_id: str, *, now: datetime | None = None) -> dict:
    """Handovers whose reason is an AI failure (trigger B) or a generic fallback (trigger A).
    A chat_handovers row is only written when the tenant's inbox escalation is on, the
    trigger is listed and the channel is enabled, so the count says nothing when it is off."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=FALLBACK_WINDOW_DAYS)).isoformat()
    reasons = [_TRIGGER_REASONS[t] for t in FALLBACK_TRIGGERS]
    count = (
        db.table("chat_handovers").select("id", count="exact").eq("tenant_id", tenant_id)
        .in_("reason", reasons).gte("opened_at", since).limit(1).execute()
    ).count or 0
    config = assignment.get_inbox_config(tenant_id)
    triggers = config.get("triggers") or []
    routed = {t: bool(config.get("enabled")) and t in triggers and bool(config.get("channels")) for t in FALLBACK_TRIGGERS}
    if not config.get("enabled"):
        note = ESCALATION_OFF_NOTE
    elif not all(routed.values()):
        note = ESCALATION_PARTIAL_NOTE
    else:
        note = None
    return {
        "count": count,
        "window_days": FALLBACK_WINDOW_DAYS,
        "escalation_enabled": all(routed.values()),
        "triggers": routed,
        "note": note,
    }


def _document_names(db, tenant_id: str, document_ids: list[str]) -> dict[str, str]:
    if not document_ids:
        return {}
    rows = db.table("knowledge_documents").select("id,name").eq("tenant_id", tenant_id).in_("id", document_ids).execute().data or []
    return {r["id"]: r.get("name") or "" for r in rows}


def decision_history(db, tenant_id: str) -> dict:
    """What the client (or a fix) actually changed, newest first.

    No audit event is written for review decisions or conflict fixes today (app_audit_logs
    only holds settings, team, role and operator actions), so this reads knowledge_versions:
    applying a review and applying a conflict fix each write one version row. Dismissals and
    discards leave no timestamped trace; the dismissed count is shown instead."""
    rows = (
        db.table("knowledge_versions").select("id,kind,document_id,reason,created_at,created_by")
        .eq("tenant_id", tenant_id).order("created_at", desc=True).limit(HISTORY_LIMIT).execute()
    ).data or []
    names = _document_names(db, tenant_id, sorted({r["document_id"] for r in rows if r.get("document_id")}))
    entries = [
        {
            "id": r["id"],
            "at": r["created_at"],
            "label": VERSION_REASON_LABELS.get(r["reason"], r["reason"]),
            "target": names.get(r.get("document_id")) if r.get("document_id") else "Description",
            "kind": r["kind"],
            "by_user_id": r.get("created_by"),
        }
        for r in rows
    ]
    return {"entries": entries, "dismissed_conflicts": _dismissed_count(tenant_id)}


def _dismissed_count(tenant_id: str) -> int:
    from app.services import consistency

    dismissed = consistency.load_report(tenant_id).get("dismissed")
    return len(dismissed) if isinstance(dismissed, list) else 0


def build_operator_brain(tenant_id: str, *, db=None) -> dict:
    """GET /operator/clients/{id}/brain. Raises TenantNotFound."""
    db = db or get_supabase()
    tenant = load_tenant(db, tenant_id)
    shared = brain.build_brain(tenant_id, role=None, permissions=OPERATOR_VIEW_PERMISSIONS, db=db)
    return {
        "tenant": {"id": tenant["id"], "name": tenant.get("name")},
        **shared,
        "inputs": _as_read_only(shared["inputs"]),
        "operator_rows": operator_rows(db, tenant_id),
        "history": decision_history(db, tenant_id),
        "fallback_signals": fallback_signals(db, tenant_id),
    }

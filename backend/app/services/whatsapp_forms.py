"""WhatsApp Forms (Meta Flows) for Services intake.

One form replaces the package -> sub-package -> add-ons -> details back-and-forth:

  PACKAGE -> (OPTION, if the package has sub-packages) -> (ADDONS, if the choice has add-ons)
          -> (DETAILS, if Services collects details) -> CONFIRM (offers opt-in + Submit)

Every Continue jumps straight to the next screen that has something to pick (an If around the
Footer), so a one-level package goes straight to the details.

Rules that keep money safe (same as the chat flow):
  * Prices live ONLY in Services. The form shows them; a submission is applied through the same
    deal_actions executors the AI uses (select_offering, save_details, the auto payment link),
    so the live config decides the price and an old/stale form can never charge an old price.
  * Each sent form carries a signed flow_token (tenant + phone + form version). A submission
    whose token does not verify is never applied; it continues in chat like a typed message.
  * A submission is applied once (deduped on Meta's message id).

Phase 0 traps (see .agents/context/subsystem-notes.md "WhatsApp Forms"):
  * A Footer inside an If needs an explicit routing_model; validation passes without it but the
    phone shows "Unexpected screen". build_intake_flow always writes one.
  * Meta only sends/publishes Flows for a VERIFIED business (error 139000 otherwise).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.services import deal_engine, intake

logger = logging.getLogger(__name__)

FEATURE_KEY = "whatsapp_forms"
COLLECT_CHAT, COLLECT_FORM = "chat", "form"
FLOW_JSON_VERSION = "7.3"
FLOW_MESSAGE_VERSION = "3"
GRAPH = "https://graph.facebook.com/v21.0"
FORM_CTA = "Choose & book"  # flow_cta: Meta advises <= 30 chars, no emoji
TOKEN_PREFIX = "wf1"
CONSENT_WORDING = "Send me updates and offers on WhatsApp"
PUBLISHING_GRACE = timedelta(minutes=5)

# Meta Flow JSON limits (components reference, Flow JSON 7.x).
_RADIO_MAX = 20
_TITLE_MAX = 30
_DESC_MAX = 300
_INPUT_LABEL_MAX = 20
_DATE_LABEL_MAX = 40
_DROPDOWN_MAX = 200
_NAME_MAX = 60

SCREEN_PACKAGE, SCREEN_OPTION, SCREEN_ADDONS, SCREEN_DETAILS, SCREEN_CONFIRM = (
    "PACKAGE", "OPTION", "ADDONS", "DETAILS", "CONFIRM",
)
NONE_VALUE = "none"  # p2 when the package has no sub-packages (blank values are rejected by Meta)


class FormBuildError(ValueError):
    """The Services setup cannot be shown as a WhatsApp Form. The message is shown to the client."""


class FormPublishError(RuntimeError):
    """Meta refused to publish. The message is shown to the client."""


# ── building the form ─────────────────────────────────────────────────────────


def _active(nodes) -> list[dict]:
    return [n for n in (nodes or []) if n.get("active", True)]


def _cut(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _rupees(paise: int) -> str:
    return deal_engine._rupees(paise) if paise else ""


def _option(node: dict, *, addon: bool = False) -> dict:
    price = _rupees(node.get("amount_paise") or 0)
    if price and addon:
        price = "+" + price
    item = {"id": node["key"], "title": _cut(node.get("name") or node["key"], _TITLE_MAX)}
    description = node.get("description") or ""
    text = f"{price} · {description}" if price and description else (price or description)
    if text:
        item["description"] = _cut(text, _DESC_MAX)
    return item


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(text or "").lower()).strip("_")[:_NAME_MAX] or "x"


def _unique(base: str, used: set[str]) -> str:
    name, n = base, 2
    while name in used:
        name = f"{base[: _NAME_MAX - 4]}_{n}"
        n += 1
    used.add(name)
    return name


def _check_level(nodes: list[dict], where: str) -> None:
    if len(nodes) > _RADIO_MAX:
        raise FormBuildError(f"{where} has {len(nodes)} choices; a WhatsApp Form shows at most {_RADIO_MAX}.")
    keys = [n.get("key") for n in nodes]
    if any(not k for k in keys):
        raise FormBuildError(f"{where} has a choice without a key. Save Services again.")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(k)) for k in keys):
        raise FormBuildError(f"{where} has a choice whose key has spaces or symbols. Rename it and save again.")


def _navigate_targets(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        action = node.get("on-click-action")
        if isinstance(action, dict) and action.get("name") == "navigate":
            found.add(action["next"]["name"])
        for value in node.values():
            found |= _navigate_targets(value)
    elif isinstance(node, list):
        for value in node:
            found |= _navigate_targets(value)
    return found


def build_intake_flow(config: dict) -> tuple[dict, dict]:
    """(Flow JSON, answer map) for the tenant's Services packages and details. Pure.

    The answer map turns the submitted form names back into Services keys:
      {"addons": {"a_<leaf>": "<leaf key>"},
       "fields": {"f_<key>": {"key", "label", "type", "options": {option id: option text}}}}"""
    roots = _active(intake.normalize_packages(config))
    if not roots:
        raise FormBuildError("Add at least one active package in Services first.")
    _check_level(roots, "Packages")

    leaves: list[tuple[dict, dict | None]] = []
    for root in roots:
        subs = _active(root.get("options"))
        if subs:
            _check_level(subs, f"'{root.get('name')}'")
            if any(_active(s.get("options")) for s in subs):
                raise FormBuildError(
                    f"'{root.get('name')}' has more than two levels of choices; a WhatsApp Form supports two."
                )
            leaves += [(s, root) for s in subs]
        else:
            leaves.append((root, None))
    all_keys = [r["key"] for r in roots] + [leaf["key"] for leaf, parent in leaves if parent]
    if len(all_keys) != len(set(all_keys)):
        raise FormBuildError("Two packages share the same key. Rename one in Services and save again.")
    for leaf, _ in leaves:
        _check_level(_active(leaf.get("addons")), f"Add-ons of '{leaf.get('name')}'")

    used: set[str] = {"p1", "p2", "consent_offers"}
    addon_names = {leaf["key"]: _unique("a_" + _slug(leaf["key"]), used)
                   for leaf, _ in leaves if _active(leaf.get("addons"))}
    fields_cfg = [f for f in (config.get("fields") or []) if f.get("key")]
    field_map: dict[str, dict] = {}
    for f in fields_cfg:
        name = _unique("f_" + _slug(f["key"]), used)
        options = {}
        for text in f.get("options") or []:
            options[_unique(_slug(text), set(options))] = text
        if f.get("type") == "choice" and len(options) > _DROPDOWN_MAX:
            raise FormBuildError(f"'{f.get('label')}' has more than {_DROPDOWN_MAX} options.")
        field_map[name] = {"key": f["key"], "label": f.get("label") or f["key"],
                           "type": f.get("type") or "text", "options": options}

    has_option = any(parent for _, parent in leaves)
    after_leaf_default = SCREEN_DETAILS if field_map else SCREEN_CONFIRM

    def after_leaf(leaf: dict) -> str:
        return SCREEN_ADDONS if leaf["key"] in addon_names else after_leaf_default

    state: dict = {"p1": {"type": "string", "__example__": "x"}, "p2": {"type": "string", "__example__": "x"}}
    for name in addon_names.values():
        state[name] = {"type": "array", "items": {"type": "string"}, "__example__": []}
    empty_addons = {name: [] for name in addon_names.values()}

    def carry(**overrides) -> dict:
        base = {"p1": "${data.p1}", "p2": "${data.p2}", **{n: f"${{data.{n}}}" for n in addon_names.values()}}
        base.update(overrides)
        return base

    def footer(expr: str, targets: dict[str, list[str]], payload: dict, label: str = "Continue") -> dict:
        def button(screen: str) -> dict:
            return {"type": "Footer", "label": label, "on-click-action": {
                "name": "navigate", "next": {"type": "screen", "name": screen}, "payload": payload}}

        items = [(screen, keys) for screen, keys in targets.items() if keys]
        if len(items) == 1:
            return button(items[0][0])
        screen, keys = items[0]
        condition = " || ".join(f"({expr} == '{k}')" for k in keys)
        return {"type": "If", "condition": condition, "then": [button(screen)],
                "else": [footer(expr, dict(items[1:]), payload, label)]}

    screens: list[dict] = []

    first_targets: dict[str, list[str]] = {}
    for root in roots:
        target = SCREEN_OPTION if _active(root.get("options")) else after_leaf(root)
        first_targets.setdefault(target, []).append(root["key"])
    screens.append({
        "id": SCREEN_PACKAGE, "title": "Choose", "terminal": False,
        "layout": {"type": "SingleColumnLayout", "children": [
            {"type": "RadioButtonsGroup", "name": "p1", "label": "Choose one", "required": True,
             "data-source": [_option(r) for r in roots]},
            footer("${form.p1}", first_targets, {"p1": "${form.p1}", "p2": NONE_VALUE, **empty_addons}),
        ]},
    })

    if has_option:
        cases = {
            r["key"]: [{"type": "RadioButtonsGroup", "name": "p2", "label": _cut(r.get("name") or "Option", _TITLE_MAX),
                        "required": True, "data-source": [_option(s) for s in _active(r.get("options"))]}]
            for r in roots if _active(r.get("options"))
        }
        option_targets: dict[str, list[str]] = {}
        for leaf, parent in leaves:
            if parent:
                option_targets.setdefault(after_leaf(leaf), []).append(leaf["key"])
        screens.append({
            "id": SCREEN_OPTION, "title": "Choose option", "terminal": False, "data": state,
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "Switch", "value": "${data.p1}", "cases": cases},
                footer("${form.p2}", option_targets, carry(p2="${form.p2}", **empty_addons)),
            ]},
        })

    if addon_names:
        root_cases, sub_cases = {}, {}
        for leaf, parent in leaves:
            if leaf["key"] in addon_names:
                block = [{"type": "CheckboxGroup", "name": addon_names[leaf["key"]], "label": "Add-ons (optional)",
                          "required": False,
                          "data-source": [_option(a, addon=True) for a in _active(leaf.get("addons"))]}]
                (sub_cases if parent else root_cases)[leaf["key"]] = block
        children = []
        if root_cases:
            children.append({"type": "Switch", "value": "${data.p1}", "cases": root_cases})
        if sub_cases:
            children.append({"type": "Switch", "value": "${data.p2}", "cases": sub_cases})
        payload = carry(**{n: f"${{form.{n}}}" for n in addon_names.values()})
        children.append(footer("", {after_leaf_default: ["x"]}, payload))
        screens.append({"id": SCREEN_ADDONS, "title": "Add-ons", "terminal": False, "data": state,
                        "layout": {"type": "SingleColumnLayout", "children": children}})

    confirm_data = dict(state)
    if field_map:
        inputs = []
        for name, f in field_map.items():
            if f["type"] == "date":
                inputs.append({"type": "DatePicker", "name": name, "label": _cut(f["label"], _DATE_LABEL_MAX),
                               "required": True})
            elif f["type"] == "choice" and f["options"]:
                inputs.append({"type": "Dropdown", "name": name, "label": _cut(f["label"], _INPUT_LABEL_MAX),
                               "required": True,
                               "data-source": [{"id": oid, "title": _cut(text, _TITLE_MAX)}
                                               for oid, text in f["options"].items()]})
            else:
                inputs.append({"type": "TextInput", "name": name, "label": _cut(f["label"], _INPUT_LABEL_MAX),
                               "required": True, "input-type": "text"})
            confirm_data[name] = {"type": "string", "__example__": "x"}
        payload = carry(**{n: f"${{form.{n}}}" for n in field_map})
        screens.append({"id": SCREEN_DETAILS, "title": "Your details", "terminal": False, "data": state,
                        "layout": {"type": "SingleColumnLayout",
                                   "children": inputs + [footer("", {SCREEN_CONFIRM: ["x"]}, payload)]}})

    complete = {k: f"${{data.{k}}}" for k in confirm_data}
    complete["consent_offers"] = "${form.consent_offers}"
    screens.append({
        "id": SCREEN_CONFIRM, "title": "Confirm", "terminal": True, "success": True, "data": confirm_data,
        "layout": {"type": "SingleColumnLayout", "children": [
            {"type": "TextBody", "text": "Tap Submit. We'll reply in this chat with your total and payment link."},
            {"type": "OptIn", "name": "consent_offers", "label": CONSENT_WORDING, "required": False},
            {"type": "Footer", "label": "Submit", "on-click-action": {"name": "complete", "payload": complete}},
        ]},
    })

    flow = {
        "version": FLOW_JSON_VERSION,
        # Required: Meta's auto-generated model ignores navigates inside If (Phase 0 trap).
        "routing_model": {s["id"]: sorted(_navigate_targets(s["layout"])) for s in screens},
        "screens": screens,
    }
    shown = {r["key"]: r.get("amount_paise") or 0 for r in roots}
    for leaf, _ in leaves:
        shown[leaf["key"]] = leaf.get("amount_paise") or 0
        for addon in _active(leaf.get("addons")):
            shown[f"{leaf['key']}/{addon['key']}"] = addon.get("amount_paise") or 0
    return flow, {"addons": {name: key for key, name in addon_names.items()}, "fields": field_map, "prices": shown}


def source_hash(flow: dict) -> str:
    return hashlib.sha256(json.dumps(flow, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ── flow_token: binds ONE sent form to one tenant, one phone and one form version ──
# A random send id makes every sent form's token unique, so the same form message submitted
# twice (reopened after paying, or a retried delivery) is applied once: whatsapp_form_responses
# has UNIQUE (tenant_id, flow_token).


def _token_key() -> bytes:
    import os

    from app.config import settings as app_config

    base = (os.getenv("FLOW_TOKEN_SECRET") or app_config.supabase_service_key or "").encode()
    if not base:
        raise RuntimeError("No server secret for WhatsApp Form tokens")
    return hmac.new(base, b"anril-flow-token-v1", hashlib.sha256).digest()


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _signature(tenant_id: str, phone: str, form_id: str, send_id: str) -> str:
    message = f"{tenant_id}|{_digits(phone)}|{form_id}|{send_id}".encode()
    return hmac.new(_token_key(), message, hashlib.sha256).hexdigest()[:32]


def make_token(tenant_id: str, phone: str, form_id: str, send_id: str | None = None) -> str:
    import secrets

    send_id = send_id or secrets.token_hex(6)
    return f"{TOKEN_PREFIX}.{form_id}.{send_id}.{_signature(tenant_id, phone, form_id, send_id)}"


def verify_token(token: str, tenant_id: str, phone: str) -> str | None:
    """The form id the token was issued for, or None when it is not ours / not this customer's."""
    parts = str(token or "").split(".")
    if (len(parts) != 4 or parts[0] != TOKEN_PREFIX or not re.fullmatch(r"[0-9a-f-]{36}", parts[1])
            or not re.fullmatch(r"[0-9a-f]{12}", parts[2])):
        return None
    if not hmac.compare_digest(parts[3], _signature(tenant_id, phone, parts[1], parts[2])):
        return None
    return parts[1]


# ── switches and lookups ─────────────────────────────────────────────────────


def is_enabled(db, tenant_id: str) -> bool:
    """On when the operator switched the feature on for the tenant (Operator Console → features)."""
    try:
        rows = db.table("tenants").select("enabled_features").eq("id", tenant_id).limit(1).execute().data or []
    except Exception:
        logger.warning("WhatsApp Forms switch read failed for tenant %s", tenant_id)
        return False
    return FEATURE_KEY in ((rows[0].get("enabled_features") if rows else None) or [])


def collects_with_form(config: dict) -> bool:
    return bool(config.get("enabled")) and config.get("collect_with") == COLLECT_FORM


def _latest(db, tenant_id: str, *, status: str | None = None) -> dict | None:
    query = db.table("whatsapp_forms").select("*").eq("tenant_id", tenant_id).eq("kind", "intake")
    if status:
        query = query.eq("status", status)
    rows = query.order("created_at", desc=True).limit(1).execute().data or []
    return rows[0] if rows else None


def _form(db, tenant_id: str, form_id: str) -> dict | None:
    rows = (
        db.table("whatsapp_forms").select("*").eq("id", form_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def _is_package_menu(config: dict, menu: dict) -> bool:
    """A menu of packages / sub-packages (not add-ons, not detail options, not yes/no)."""
    keys = menu.get("offering_keys") or []
    if not keys or menu.get("field_key"):
        return False
    from app.services.deal_actions import _find_node

    packages = intake.normalize_packages(config)
    return all(_find_node(packages, k) for k in keys)


def form_for_menu(tenant_id: str, menu: dict, db=None) -> dict | None:
    """The published intake form to send instead of this package menu, or None (send the menu)."""
    try:
        if db is None:
            from app.db.supabase import get_supabase
            db = get_supabase()
        config = intake.get_intake_config(tenant_id, db=db)
        if not collects_with_form(config) or not _is_package_menu(config, menu) or not is_enabled(db, tenant_id):
            return None
        published = _latest(db, tenant_id, status="published")
        if not published:
            return None
        # Only a form showing exactly today's packages and prices. While a new version is still
        # publishing (or failed), the customer gets the normal menu, never an old price.
        try:
            current = source_hash(build_intake_flow(config)[0])
        except FormBuildError:
            return None
        return published if published.get("source_hash") == current else None
    except Exception:
        logger.exception("WhatsApp Form lookup failed for tenant %s -- sending the menu", tenant_id)
        return None


# ── Meta: publish / retire ───────────────────────────────────────────────────


def _meta_creds(tenant_id: str) -> tuple[str, str]:
    from app.config_dynamic import get_setting

    token = get_setting("meta_access_token", tenant_id=tenant_id)
    waba = get_setting("meta_waba_id", tenant_id=tenant_id)
    if not token or not waba:
        raise FormPublishError("Connect WhatsApp in Settings first.")
    return str(token), str(waba)


def _meta_error(payload) -> str | None:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not error:
        return None
    if error.get("code") == 139000:
        return "Meta needs your business to be verified before it allows WhatsApp Forms."
    return str(error.get("error_user_msg") or error.get("message") or "Meta returned an error")


async def _business_verified(client: httpx.AsyncClient, token: str, waba: str) -> bool | None:
    try:
        payload = (await client.get(f"{GRAPH}/{waba}", params={"fields": "business_verification_status"},
                                    headers={"Authorization": f"Bearer {token}"})).json()
    except (httpx.HTTPError, ValueError):
        return None
    status = payload.get("business_verification_status") if isinstance(payload, dict) else None
    return None if status is None else status == "verified"


async def _publish(tenant_id: str, name: str, flow: dict) -> tuple[str, str]:
    """Create + publish on Meta in one call. Returns (flow id, waba id)."""
    token, waba = _meta_creds(tenant_id)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        verified = await _business_verified(client, token, waba)
        if verified is False:
            raise FormPublishError(
                "Meta needs your business to be verified before it allows WhatsApp Forms. "
                "Verify it in Meta Business Settings → Security Center, then save Services again."
            )
        try:
            response = await client.post(f"{GRAPH}/{waba}/flows", headers=headers, data={
                "name": name, "categories": json.dumps(["OTHER"]),
                "flow_json": json.dumps(flow, ensure_ascii=False), "publish": "true",
            })
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FormPublishError("Could not reach Meta. Try saving again in a minute.") from exc
        message = _meta_error(payload)
        if message:
            raise FormPublishError(message)
        flow_id = str(payload.get("id") or "")
        problems = payload.get("validation_errors") or []
        if not flow_id or problems:
            if flow_id:
                await _delete_draft(client, headers, flow_id)
            detail = "; ".join(str(p.get("message") or p.get("error")) for p in problems[:3]) or "no form id returned"
            raise FormPublishError(f"Meta did not accept the form: {detail}")
        try:
            status = (await client.get(f"{GRAPH}/{flow_id}", params={"fields": "status"}, headers=headers)).json()
        except (httpx.HTTPError, ValueError):
            status = {}
        if status.get("status") != "PUBLISHED":
            await _delete_draft(client, headers, flow_id)
            raise FormPublishError(
                _meta_error(status) or f"Meta did not publish the form (status {status.get('status') or 'unknown'})."
            )
    return flow_id, waba


async def _delete_draft(client: httpx.AsyncClient, headers: dict, flow_id: str) -> None:
    try:
        await client.delete(f"{GRAPH}/{flow_id}", headers=headers)
    except httpx.HTTPError:
        logger.warning("Could not delete draft WhatsApp Form %s", flow_id)


async def _deprecate(tenant_id: str, flow_id: str) -> None:
    try:
        token, _ = _meta_creds(tenant_id)
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(f"{GRAPH}/{flow_id}/deprecate", headers={"Authorization": f"Bearer {token}"})
    except Exception:
        logger.warning("Could not retire WhatsApp Form %s on Meta", flow_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def sync_intake_form(tenant_id: str, db=None) -> dict | None:
    """Publish a new form version when Services changed. Returns the form row it settled on.

    Never sends anything to a customer. A failure is stored on the row (shown on Services)."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    config = intake.get_intake_config(tenant_id, db=db)
    if not collects_with_form(config) or not is_enabled(db, tenant_id):
        return None
    try:
        flow, answer_map = build_intake_flow(config)
    except FormBuildError as exc:
        row = db.table("whatsapp_forms").insert({
            "tenant_id": tenant_id, "kind": "intake", "name": "Services form", "status": "failed",
            "source_hash": "invalid", "definition": {}, "answer_map": {}, "last_error": str(exc),
        }).execute().data
        return row[0] if row else None
    digest = source_hash(flow)
    latest = _latest(db, tenant_id)
    if latest and latest.get("source_hash") == digest:
        if latest["status"] == "published":
            return latest
        started = deal_engine.parse_time(latest.get("created_at"))
        if latest["status"] == "publishing" and started and datetime.now(timezone.utc) - started < PUBLISHING_GRACE:
            return latest
    row = (db.table("whatsapp_forms").insert({
        "tenant_id": tenant_id, "kind": "intake", "name": "Services form", "status": "publishing",
        "source_hash": digest, "definition": flow, "answer_map": answer_map,
    }).execute().data or [None])[0]
    if not row:
        return None
    name = f"anril_services_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{row['id'][:6]}"
    try:
        flow_id, waba = await _publish(tenant_id, name, flow)
    except Exception as exc:
        message = str(exc) if isinstance(exc, FormPublishError) else "Publishing didn't finish. Try again."
        if not isinstance(exc, FormPublishError):
            logger.exception("WhatsApp Form publish crashed for tenant %s", tenant_id)
        db.table("whatsapp_forms").update({"status": "failed", "last_error": message, "updated_at": _now()}) \
            .eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
        return {**row, "status": "failed", "last_error": message}
    newest = _latest(db, tenant_id)
    if newest and newest["id"] != row["id"]:
        # A later save started its own publish while this one ran: this version is already old.
        db.table("whatsapp_forms").update({
            "status": "retired", "meta_flow_id": flow_id, "meta_waba_id": waba, "updated_at": _now(),
        }).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
        await _deprecate(tenant_id, flow_id)
        return newest
    previous = (
        db.table("whatsapp_forms").select("id, meta_flow_id").eq("tenant_id", tenant_id).eq("kind", "intake")
        .eq("status", "published").execute()
    ).data or []
    db.table("whatsapp_forms").update({
        "status": "published", "meta_flow_id": flow_id, "meta_waba_id": waba, "published_at": _now(),
        "last_error": None, "updated_at": _now(),
    }).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
    for old in previous:
        db.table("whatsapp_forms").update({"status": "retired", "updated_at": _now()}) \
            .eq("id", old["id"]).eq("tenant_id", tenant_id).execute()
        if old.get("meta_flow_id"):
            await _deprecate(tenant_id, old["meta_flow_id"])
    return {**row, "status": "published", "meta_flow_id": flow_id}


async def sync_intake_form_safely(tenant_id: str) -> None:
    """Background-task entry point: never raises."""
    try:
        await sync_intake_form(tenant_id)
    except Exception:
        logger.exception("WhatsApp Form sync failed for tenant %s", tenant_id)


def intake_status(db, tenant_id: str) -> dict:
    """What the Services page shows under "Send a WhatsApp Form"."""
    enabled = is_enabled(db, tenant_id)
    if not enabled:
        return {"available": False}
    latest = _latest(db, tenant_id)
    live = latest if latest and latest["status"] == "published" else _latest(db, tenant_id, status="published")
    state = (latest or {}).get("status") or "none"
    error = (latest or {}).get("last_error") if state == "failed" else None
    started = deal_engine.parse_time((latest or {}).get("created_at"))
    if state == "publishing" and started and datetime.now(timezone.utc) - started > PUBLISHING_GRACE:
        state, error = "failed", "Publishing didn't finish. Try again."  # e.g. a restart mid-publish
    return {
        "available": True,
        "state": state,
        "error": error,
        "live": bool(live),
        "published_at": (live or {}).get("published_at"),
    }


# ── sending ──────────────────────────────────────────────────────────────────


async def send_form(phone: str, body: str, form: dict, *, tenant_id: str, phone_number_id: str | None = None) -> str | None:
    from app.services import meta_cloud

    data = await meta_cloud.send_flow_message(
        to_number=phone, body_text=body, flow_id=form["meta_flow_id"], flow_cta=FORM_CTA,
        flow_token=make_token(tenant_id, phone, form["id"]), first_screen=SCREEN_PACKAGE,
        tenant_id=tenant_id, phone_number_id=phone_number_id,
    )
    return (data.get("messages") or [{}])[0].get("id")


def form_record(body: str) -> str:
    """What the conversation history saves for a sent form."""
    return f"{body}\n\n[📝 {FORM_CTA}]"


# ── receiving ────────────────────────────────────────────────────────────────


def parse_response(raw: str) -> dict:
    try:
        answers = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return answers if isinstance(answers, dict) else {}


def _choice_path(config: dict, answers: dict) -> tuple[str | None, list[str]]:
    """(leaf key, path names) from p1/p2."""
    from app.services.deal_actions import _find_node

    packages = intake.normalize_packages(config)
    p1, p2 = str(answers.get("p1") or ""), str(answers.get("p2") or "")
    leaf = p2 if p2 and p2 != NONE_VALUE else p1
    names = []
    for key in (p1, p2):
        if key and key != NONE_VALUE:
            node = _find_node(packages, key)
            names.append(node.get("name") if node else key)
    return (leaf or None), names


def _details(answer_map: dict, answers: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, field in (answer_map.get("fields") or {}).items():
        value = answers.get(name)
        if value in (None, "", []):
            continue
        text = str(value).strip()
        if field.get("options"):
            text = field["options"].get(text, text)
        out[field["key"]] = text[:500]
    return out


def _addon_keys(answer_map: dict, answers: dict, leaf: str | None) -> list[str]:
    for name, leaf_key in (answer_map.get("addons") or {}).items():
        if leaf_key == leaf:
            picked = answers.get(name)
            return [str(k) for k in picked] if isinstance(picked, list) else []
    return []


def _price_went_up(config: dict, answer_map: dict, leaf: str, addon_keys: list[str]) -> bool:
    """True when today's Services price for this choice is higher than the form showed. The chat
    flow asks before charging more (customer_agreed_new_price); a form can't, so it goes to chat."""
    shown = answer_map.get("prices")
    found = intake._find_leaf(intake.normalize_packages(config), leaf)
    if not isinstance(shown, dict) or not found or leaf not in shown:
        return False
    node = found[0]
    live_addons = {a["key"]: a.get("amount_paise") or 0 for a in node.get("addons") or []}
    live = (node.get("amount_paise") or 0) + sum(live_addons.get(k, 0) for k in addon_keys)
    seen = shown[leaf] + sum(shown.get(f"{leaf}/{k}", 0) for k in addon_keys)
    return live > seen


def _wants_offers(answers: dict) -> bool:
    value = answers.get("consent_offers")
    return value is True or str(value).lower() == "true"


def summary_text(db, tenant_id: str, phone: str, raw: str) -> str:
    """The readable inbound line saved in the chat for a submitted form (and what the AI reads if
    the submission continues in chat). Never raises."""
    try:
        answers = parse_response(raw)
        form_id = verify_token(answers.get("flow_token"), tenant_id, phone)
        form = _form(db, tenant_id, form_id) if form_id else None
        if not form:
            return "📝 Form submitted"
        config = intake.get_intake_config(tenant_id, db=db)
        leaf, path = _choice_path(config, answers)
        lines = ["📝 Form submitted"]
        if path:
            lines.append("Choice: " + " › ".join(path))
        addons = _addon_keys(form.get("answer_map") or {}, answers, leaf)
        if addons:
            found = intake._find_leaf(intake.normalize_packages(config), leaf) if leaf else None
            names = {a["key"]: a.get("name") for a in ((found[0].get("addons") if found else None) or [])}
            lines.append("Add-ons: " + ", ".join(names.get(k, k) for k in addons))
        fields = (form.get("answer_map") or {}).get("fields") or {}
        labels = {f["key"]: f.get("label") or f["key"] for f in fields.values()}
        for key, value in _details(form.get("answer_map") or {}, answers).items():
            lines.append(f"{labels.get(key, key)}: {value}")
        lines.append("Offers on WhatsApp: " + ("yes" if _wants_offers(answers) else "no"))
        return "\n".join(lines)[:1500]
    except Exception:
        logger.exception("WhatsApp Form summary failed for tenant %s", tenant_id)
        return "📝 Form submitted"


def _record_response(db, tenant_id: str, form_id: str | None, lead_id: str, meta_message_id: str,
                     answers: dict, outcome: str) -> dict | None:
    """Insert the response row; None when this Meta message or this sent form (its token) was
    already handled. The token is stored only once verified, so a forged one never blocks a real one."""
    stored = {k: v for k, v in answers.items() if k != "flow_token"}
    try:
        rows = db.table("whatsapp_form_responses").insert({
            "tenant_id": tenant_id, "form_id": form_id, "lead_id": lead_id,
            "meta_message_id": meta_message_id, "answers": stored, "outcome": outcome,
            "flow_token": str(answers.get("flow_token")) if form_id else None,
        }).execute().data or []
    except Exception as exc:
        if "23505" in str(exc) or "duplicate key" in str(exc).lower():
            return None
        raise
    return rows[0] if rows else None


def _repeat_outcome(db, tenant_id: str, meta_message_id: str, token: str) -> str:
    """A repeat: the same Meta message again (a retried delivery) is ignored. The same sent form
    submitted again is ignored only if the first one already sent the link; otherwise (a detail
    was refused) the AI answers it, so a corrected resubmission never meets silence."""
    same_message = (
        db.table("whatsapp_form_responses").select("id").eq("tenant_id", tenant_id)
        .eq("meta_message_id", meta_message_id).limit(1).execute()
    ).data or []
    if same_message:
        return "ignored"
    earlier = (
        db.table("whatsapp_form_responses").select("outcome").eq("tenant_id", tenant_id)
        .eq("flow_token", token).limit(1).execute()
    ).data or []
    return "ignored" if earlier and earlier[0].get("outcome") == "link_sent" else "continue"


def _set_outcome(db, tenant_id: str, response_id: str, outcome: str, session_id: str | None = None) -> None:
    patch: dict = {"outcome": outcome}
    if session_id:
        patch["intake_session_id"] = session_id
    db.table("whatsapp_form_responses").update(patch).eq("id", response_id).eq("tenant_id", tenant_id).execute()


def _record_consent(db, tenant_id: str, lead_id: str, form_id: str, offers: bool) -> None:
    source = f"whatsapp_form:{form_id}"
    try:
        db.table("lead_consents").insert([
            {"tenant_id": tenant_id, "lead_id": lead_id, "scope": "replies", "granted": True, "source": source,
             "wording": "Submitted a WhatsApp Form asking to book"},
            {"tenant_id": tenant_id, "lead_id": lead_id, "scope": "offers", "granted": offers, "source": source,
             "wording": CONSENT_WORDING},
        ]).execute()
    except Exception:
        logger.exception("Consent record failed for lead %s", lead_id)


def _confirmation(session: dict) -> tuple[str, str]:
    """(message, button label) for the payment link. Amounts come from the session the
    executors just priced, never from the form."""
    path = [step.get("name") for step in (session.get("package_path") or []) if step.get("name")]
    lines = ["✅ " + (" › ".join(path) or session.get("package_name") or "Your booking")]
    for addon in session.get("selected_addons") or []:
        lines.append(f"+ {addon.get('name')} ({deal_engine._rupees(addon.get('amount_paise') or 0)})")
    total = session.get("amount_paise") or session.get("total_amount_paise") or 0
    line = f"Total: {deal_engine._rupees(total)}"
    if session.get("gst_amount_paise"):
        line += f" (incl. GST {deal_engine._rupees(session['gst_amount_paise'])})"
    lines += [line, "", "Tap below to pay."]
    label = f"Pay {deal_engine._rupees(total)}"
    return "\n".join(lines), (label if len(label) <= 20 else "Pay now")


async def handle_submission(
    db, *, tenant_id: str, lead_id: str, phone: str, raw: str, meta_message_id: str,
    phone_number_id: str | None = None,
) -> str:
    """Apply a submitted intake form. Returns:
      "handled"  -- choice + details saved and the payment link sent; skip the AI this turn
      "ignored"  -- a repeat of a submission already handled; do nothing
      "continue" -- not applied (unverified token; Services switched back to chat or the
                    feature off; the price went up since the form was shown; a refused
                    detail); the AI replies to the summary line as if the customer typed it"""
    from app.services import choices, deal_actions, deal_turn

    answers = parse_response(raw)
    form_id = verify_token(answers.get("flow_token"), tenant_id, phone)
    form = _form(db, tenant_id, form_id) if form_id else None
    if not form:
        logger.warning("WhatsApp Form reply with an unverified token for tenant %s lead %s", tenant_id, lead_id)
        _record_response(db, tenant_id, None, lead_id, meta_message_id, answers, "rejected")
        return "continue"
    response = _record_response(db, tenant_id, form["id"], lead_id, meta_message_id, answers, "received")
    if response is None:
        return _repeat_outcome(db, tenant_id, meta_message_id, str(answers.get("flow_token")))

    ctx = deal_turn.build_context(db, tenant_id, lead_id, phone)
    if not ctx.offerings_enabled or not collects_with_form(ctx.config) or not is_enabled(db, tenant_id):
        # Switched back to chat (or off) after the form went out: the AI answers the summary.
        _set_outcome(db, tenant_id, response["id"], "continued_in_chat")
        return "continue"
    answer_map = form.get("answer_map") or {}
    leaf, _ = _choice_path(ctx.config, answers)
    _record_consent(db, tenant_id, lead_id, form["id"], _wants_offers(answers))
    if not leaf:
        _set_outcome(db, tenant_id, response["id"], "continued_in_chat")
        return "continue"

    addon_keys = _addon_keys(answer_map, answers, leaf)
    if _price_went_up(ctx.config, answer_map, leaf, addon_keys):
        logger.info("WhatsApp Form for lead %s: price went up since the form was shown -- continuing in chat", lead_id)
        _set_outcome(db, tenant_id, response["id"], "continued_in_chat")
        return "continue"
    session = deal_actions._session(ctx)
    select_args: dict = {"key": leaf, "addon_keys": addon_keys}
    if session and session.get("status") == deal_engine.PAID_STATUS:
        select_args["new_booking"] = True  # a fresh form after a paid booking is a new booking
    calls = [{"function": {"name": deal_engine.TOOL_SELECT_OFFERING, "arguments": json.dumps(select_args)}}]
    details = _details(answer_map, answers)
    if details:
        calls.append({"function": {"name": deal_engine.TOOL_SAVE_DETAILS, "arguments": json.dumps({"fields": details})}})
    intake.note_lead_message(db, tenant_id, lead_id)
    outcome = await deal_actions.apply_tool_calls(calls, ctx, auto_link=True)
    session = deal_actions._session(ctx)
    if outcome.refusals:
        logger.info("WhatsApp Form for lead %s continues in chat: %s", lead_id, "; ".join(outcome.refusals))
    if not outcome.payment_link or not session:
        _set_outcome(db, tenant_id, response["id"], "continued_in_chat", (session or {}).get("id"))
        return "continue"

    text, label = _confirmation(session)
    sid, _ = await deal_turn.send_link(
        phone, choices.Link(text, outcome.payment_link, label), tenant_id=tenant_id,
        phone_number_id=phone_number_id, original=f"{text}\n{outcome.payment_link}",
    )
    db.table("messages").insert({
        "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
        "content": f"{text}\n{outcome.payment_link}", "is_ai_generated": False, "meta_message_id": sid,
    }).execute()
    _set_outcome(db, tenant_id, response["id"], "link_sent", session.get("id"))
    return "handled"

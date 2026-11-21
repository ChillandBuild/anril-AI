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

from app.services import deal_engine, form_texts, intake

logger = logging.getLogger(__name__)

FEATURE_KEY = "whatsapp_forms"
COLLECT_CHAT, COLLECT_FORM = "chat", "form"
FLOW_JSON_VERSION = "7.3"
FLOW_MESSAGE_VERSION = "3"
GRAPH = "https://graph.facebook.com/v21.0"
TOKEN_PREFIX = "wf1"
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
    texts = form_texts.resolve(config.get("form_texts"))
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

    def footer(expr: str, targets: dict[str, list[str]], payload: dict, label: str = texts["continue"]) -> dict:
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
        "id": SCREEN_PACKAGE, "title": texts["title_choose"], "terminal": False,
        "layout": {"type": "SingleColumnLayout", "children": [
            {"type": "RadioButtonsGroup", "name": "p1", "label": texts["choose_label"], "required": True,
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
            "id": SCREEN_OPTION, "title": texts["title_option"], "terminal": False, "data": state,
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "Switch", "value": "${data.p1}", "cases": cases},
                footer("${form.p2}", option_targets, carry(p2="${form.p2}", **empty_addons)),
            ]},
        })

    if addon_names:
        root_cases, sub_cases = {}, {}
        for leaf, parent in leaves:
            if leaf["key"] in addon_names:
                block = [{"type": "CheckboxGroup", "name": addon_names[leaf["key"]], "label": texts["addons_label"],
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
        screens.append({"id": SCREEN_ADDONS, "title": texts["title_addons"], "terminal": False, "data": state,
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
        screens.append({"id": SCREEN_DETAILS, "title": texts["title_details"], "terminal": False, "data": state,
                        "layout": {"type": "SingleColumnLayout",
                                   "children": inputs + [footer("", {SCREEN_CONFIRM: ["x"]}, payload)]}})

    complete = {k: f"${{data.{k}}}" for k in confirm_data}
    complete["consent_offers"] = "${form.consent_offers}"
    screens.append({
        "id": SCREEN_CONFIRM, "title": texts["title_confirm"], "terminal": True, "success": True, "data": confirm_data,
        "layout": {"type": "SingleColumnLayout", "children": [
            {"type": "TextBody", "text": texts["confirm_note"]},
            {"type": "OptIn", "name": "consent_offers", "label": texts["consent"], "required": False},
            {"type": "Footer", "label": texts["submit"], "on-click-action": {"name": "complete", "payload": complete}},
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
    names = {r["key"]: r.get("name") or r["key"] for r in roots}
    for leaf, _ in leaves:
        names[leaf["key"]] = leaf.get("name") or leaf["key"]
        for addon in _active(leaf.get("addons")):
            names[addon["key"]] = addon.get("name") or addon["key"]
    return flow, {
        "kind": "intake", "addons": {name: key for key, name in addon_names.items()}, "fields": field_map,
        "prices": shown, "names": names, "consent_wording": texts["consent"],
    }


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


def _latest(db, tenant_id: str, *, status: str | None = None, design_id: str | None = None) -> dict | None:
    """Newest version of the Services form (design_id None) or of one custom form."""
    query = db.table("whatsapp_forms").select("*").eq("tenant_id", tenant_id)
    query = query.eq("kind", "custom").eq("design_id", design_id) if design_id else query.eq("kind", "intake")
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
        if published.get("source_hash") != current:
            return None
        return {**published, "cta": form_texts.resolve(config.get("form_texts"))["cta"]}
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


def endpoint_uri(tenant_id: str) -> str:
    """Where Meta sends a live form's encrypted requests (routes/whatsapp_form_designs.public_router)."""
    from app.config import settings as app_config

    base = (app_config.public_base_url or "").rstrip("/")
    if not base:
        raise FormPublishError("Live forms need the server's public address (PUBLIC_BASE_URL).")
    return f"{base}/api/v1/whatsapp-forms/data/{tenant_id}"


async def _publish(tenant_id: str, name: str, flow: dict) -> tuple[str, str]:
    """Create + publish on Meta in one call. Returns (flow id, waba id)."""
    token, waba = _meta_creds(tenant_id)
    live = "data_api_version" in flow
    if live:
        from app.config_dynamic import get_setting
        from app.db.supabase import get_supabase
        from app.services import whatsapp_live_forms

        await whatsapp_live_forms.ensure_keys(get_supabase(), tenant_id)
        from app.config import settings as env_settings

        # The Meta app that signs the live form's requests (same lookup as templates._meta_app_id).
        app_id = get_setting("meta_app_id", tenant_id=tenant_id) or env_settings.meta_app_id
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        verified = await _business_verified(client, token, waba)
        if verified is False:
            raise FormPublishError(
                "Meta needs your business to be verified before it allows WhatsApp Forms. "
                "Verify it in Meta Business Settings → Security Center, then save Services again."
            )
        try:
            body = {
                "name": name, "categories": json.dumps(["OTHER"]),
                "flow_json": json.dumps(flow, ensure_ascii=False), "publish": "true",
            }
            if live:
                # Meta pings this address before publishing: the server must already be live.
                body["endpoint_uri"] = endpoint_uri(tenant_id)
                if app_id:
                    body["application_id"] = str(app_id)
            response = await client.post(f"{GRAPH}/{waba}/flows", headers=headers, data=body)
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
    return await _publish_version(db, tenant_id, flow, answer_map, name="Services form")


async def _publish_version(
    db, tenant_id: str, flow: dict, answer_map: dict, *, name: str, design_id: str | None = None,
) -> dict | None:
    """Publish this form version unless the same one is already live (or still publishing), then
    retire the older versions of the same form. Shared by the Services form and custom forms."""
    digest = source_hash(flow)
    latest = _latest(db, tenant_id, design_id=design_id)
    if latest and latest.get("source_hash") == digest:
        if latest["status"] == "published":
            return latest
        started = deal_engine.parse_time(latest.get("created_at"))
        if latest["status"] == "publishing" and started and datetime.now(timezone.utc) - started < PUBLISHING_GRACE:
            return latest
    row = (db.table("whatsapp_forms").insert({
        "tenant_id": tenant_id, "kind": "custom" if design_id else "intake", "design_id": design_id,
        "name": name[:120] or "Form", "status": "publishing",
        "source_hash": digest, "definition": flow, "answer_map": answer_map,
    }).execute().data or [None])[0]
    if not row:
        return None
    meta_name = f"anril_{'form' if design_id else 'services'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{row['id'][:6]}"
    try:
        flow_id, waba = await _publish(tenant_id, meta_name, flow)
    except Exception as exc:
        message = str(exc) if isinstance(exc, FormPublishError) else "Publishing didn't finish. Try again."
        if not isinstance(exc, FormPublishError):
            logger.exception("WhatsApp Form publish crashed for tenant %s", tenant_id)
        db.table("whatsapp_forms").update({"status": "failed", "last_error": message, "updated_at": _now()}) \
            .eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
        return {**row, "status": "failed", "last_error": message}
    newest = _latest(db, tenant_id, design_id=design_id)
    if newest and newest["id"] != row["id"]:
        # A later save started its own publish while this one ran: this version is already old.
        db.table("whatsapp_forms").update({
            "status": "retired", "meta_flow_id": flow_id, "meta_waba_id": waba, "updated_at": _now(),
        }).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
        await _deprecate(tenant_id, flow_id)
        return newest
    previous_query = db.table("whatsapp_forms").select("id, meta_flow_id").eq("tenant_id", tenant_id)
    previous_query = (previous_query.eq("kind", "custom").eq("design_id", design_id) if design_id
                      else previous_query.eq("kind", "intake"))
    previous = previous_query.eq("status", "published").execute().data or []
    db.table("whatsapp_forms").update({
        "status": "published", "meta_flow_id": flow_id, "meta_waba_id": waba, "published_at": _now(),
        "last_error": None, "updated_at": _now(),
    }).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
    for old in previous:
        if old["id"] == row["id"]:
            continue
        db.table("whatsapp_forms").update({"status": "retired", "updated_at": _now()}) \
            .eq("id", old["id"]).eq("tenant_id", tenant_id).execute()
        if old.get("meta_flow_id") and not used_by_templates(db, tenant_id, old["meta_flow_id"]):
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
    if not is_enabled(db, tenant_id):
        return {"available": False}
    return {"available": True, **version_status(db, tenant_id)}


def version_status(db, tenant_id: str, design_id: str | None = None) -> dict:
    """Live / updating / failed for the Services form or one custom form."""
    latest = _latest(db, tenant_id, design_id=design_id)
    live = latest if latest and latest["status"] == "published" else _latest(
        db, tenant_id, status="published", design_id=design_id)
    state = (latest or {}).get("status") or "none"
    error = (latest or {}).get("last_error") if state == "failed" else None
    started = deal_engine.parse_time((latest or {}).get("created_at"))
    if state == "publishing" and started and datetime.now(timezone.utc) - started > PUBLISHING_GRACE:
        state, error = "failed", "Publishing didn't finish. Try again."  # e.g. a restart mid-publish
    return {
        "state": state,
        "error": error,
        "live": bool(live),
        "published_at": (live or {}).get("published_at"),
    }


# ── custom forms (Catalogue → Forms) ─────────────────────────────────────────
#
# A design (whatsapp_form_designs) is the client's editable form: name, language, questions,
# texts. Publishing turns it into a whatsapp_forms version (kind 'custom'), like the Services form.

FIELDS_PER_SCREEN = 5
_STRING = {"type": "string", "__example__": "x"}
_ARRAY = {"type": "array", "items": {"type": "string"}, "__example__": []}


def _design_settings(design: dict) -> dict:
    return {"language": design.get("language"), "texts": design.get("texts") or {}}


KINDS = ("standard", "order", "booking")


def design_problems(design: dict) -> list[str]:
    name = str(design.get("name") or "").strip()
    out = [] if name else ["Give the form a name."]
    if len(name) > 120:
        out.append("The form name can be at most 120 characters.")
    kind = design.get("kind") or "standard"
    if kind not in KINDS:
        return out + ["Unknown form type."]
    fields = design.get("fields") or []
    # An order form asks nothing extra; a booking's own questions are optional.
    field_problems = [] if kind == "order" or (kind == "booking" and not fields) else form_texts.field_problems(fields)
    from app.services import whatsapp_live_forms
    return (out + field_problems + form_texts.problems(_design_settings(design))
            + whatsapp_live_forms.settings_problems(kind, design.get("settings")))


def build_design_flow(design: dict) -> tuple[dict, dict]:
    """The Flow for any client form: standard questions, a live order form or a live booking."""
    kind = design.get("kind") or "standard"
    if kind == "standard":
        return build_custom_flow(design)
    problems = design_problems(design)
    if problems:
        raise FormBuildError(problems[0])
    from app.services import whatsapp_live_forms
    return (whatsapp_live_forms.build_order_flow(design) if kind == "order"
            else whatsapp_live_forms.build_booking_flow(design))


def build_custom_flow(design: dict) -> tuple[dict, dict]:
    """(Flow JSON, answer map) for a client's own form. Up to FIELDS_PER_SCREEN questions a
    screen, then a last screen with the form note, the offers opt-in and Submit. Pure."""
    problems = design_problems(design)
    if problems:
        raise FormBuildError(problems[0])
    texts = form_texts.resolve(_design_settings(design))
    used: set[str] = {"consent_offers"}
    fields: list[dict] = []
    field_map: dict[str, dict] = {}
    for f in design["fields"]:
        name = _unique("f_" + _slug(f["key"]), used)
        options: dict[str, str] = {}
        for text in [str(o).strip() for o in f.get("options") or [] if str(o).strip()]:
            options[_unique(_slug(text), set(options))] = text
        fields.append({**f, "name": name, "option_ids": options})
        field_map[name] = {"key": f["key"], "label": str(f["label"]).strip(), "type": f["type"], "options": options}

    def component(f: dict) -> dict:
        label, required, kind = str(f["label"]).strip(), bool(f.get("required", True)), f["type"]
        if kind == "long_text":
            return {"type": "TextArea", "name": f["name"], "label": label, "required": required}
        if kind in ("text", "email", "phone", "number"):
            return {"type": "TextInput", "name": f["name"], "label": label, "required": required, "input-type": kind}
        if kind == "date":
            return {"type": "DatePicker", "name": f["name"], "label": label, "required": required}
        source = [{"id": oid, "title": text} for oid, text in f["option_ids"].items()]
        if kind == "dropdown":
            return {"type": "Dropdown", "name": f["name"], "label": label, "required": required, "data-source": source}
        if kind == "single":
            return {"type": "RadioButtonsGroup", "name": f["name"], "label": label, "required": required,
                    "data-source": source}
        return {"type": "CheckboxGroup", "name": f["name"], "label": label, "required": required, "data-source": source}

    chunks = [fields[i:i + FIELDS_PER_SCREEN] for i in range(0, len(fields), FIELDS_PER_SCREEN)]
    # Meta: screen ids are letters and underscores only (no digits).
    ids = [f"QUESTIONS_{chr(65 + n)}" for n in range(len(chunks))] + [SCREEN_CONFIRM]
    screens: list[dict] = []
    carried: list[dict] = []  # fields answered on earlier screens
    for n, chunk in enumerate(chunks):
        payload = {f["name"]: f"${{data.{f['name']}}}" for f in carried}
        payload.update({f["name"]: f"${{form.{f['name']}}}" for f in chunk})
        screen = {
            "id": ids[n], "title": texts["title_details"], "terminal": False,
            "layout": {"type": "SingleColumnLayout", "children": [component(f) for f in chunk] + [
                {"type": "Footer", "label": texts["continue"], "on-click-action": {
                    "name": "navigate", "next": {"type": "screen", "name": ids[n + 1]}, "payload": payload}},
            ]},
        }
        if carried:
            screen["data"] = {f["name"]: (_ARRAY if f["type"] == "multi" else _STRING) for f in carried}
        screens.append(screen)
        carried = carried + chunk
    complete = {f["name"]: f"${{data.{f['name']}}}" for f in carried}
    complete["consent_offers"] = "${form.consent_offers}"
    screens.append({
        "id": SCREEN_CONFIRM, "title": texts["title_confirm"], "terminal": True, "success": True,
        "data": {f["name"]: (_ARRAY if f["type"] == "multi" else _STRING) for f in carried},
        "layout": {"type": "SingleColumnLayout", "children": [
            {"type": "TextBody", "text": texts["form_note"]},
            {"type": "OptIn", "name": "consent_offers", "label": texts["consent"], "required": False},
            {"type": "Footer", "label": texts["submit"], "on-click-action": {"name": "complete", "payload": complete}},
        ]},
    })
    flow = {"version": FLOW_JSON_VERSION,
            "routing_model": {s["id"]: sorted(_navigate_targets(s["layout"])) for s in screens},
            "screens": screens}
    return flow, {"kind": "custom", "fields": field_map, "consent_wording": texts["consent"],
                  "form_name": str(design.get("name") or "").strip()}


def get_design(db, tenant_id: str, design_id: str) -> dict | None:
    rows = (
        db.table("whatsapp_form_designs").select("*").eq("id", design_id).eq("tenant_id", tenant_id)
        .limit(1).execute()
    ).data or []
    return rows[0] if rows else None


async def publish_design(db, tenant_id: str, design_id: str) -> dict:
    """Publish the saved design as a new form version. Returns its status (version_status shape)."""
    design = get_design(db, tenant_id, design_id)
    if not design or design.get("archived"):
        raise FormBuildError("Form not found.")
    flow, answer_map = build_design_flow(design)
    await _publish_version(db, tenant_id, flow, answer_map, name=design["name"], design_id=design_id)
    return version_status(db, tenant_id, design_id)


def live_custom_form(db, tenant_id: str, design: dict) -> dict | None:
    """The published version to send, only when it shows exactly the saved design."""
    published = _latest(db, tenant_id, status="published", design_id=design["id"])
    if not published:
        return None
    try:
        current = source_hash(build_design_flow(design)[0])
    except FormBuildError:
        return None
    if published.get("source_hash") != current:
        return None
    texts = form_texts.resolve(_design_settings(design))
    # A live form opens by asking Anril for its first screen (data_exchange), not a fixed one.
    first = "QUESTIONS_A" if (design.get("kind") or "standard") == "standard" else None
    return {**published, "cta": texts["form_cta"], "intro": texts["intro"], "first_screen": first}


async def retire_design(db, tenant_id: str, design_id: str) -> None:
    """Archive a form: it disappears from the list and its live version stops on Meta."""
    db.table("whatsapp_form_designs").update({"archived": True, "updated_at": _now()}) \
        .eq("id", design_id).eq("tenant_id", tenant_id).execute()
    live = (
        db.table("whatsapp_forms").select("id, meta_flow_id").eq("tenant_id", tenant_id).eq("kind", "custom")
        .eq("design_id", design_id).eq("status", "published").execute()
    ).data or []
    for row in live:
        db.table("whatsapp_forms").update({"status": "retired", "updated_at": _now()}) \
            .eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
        if row.get("meta_flow_id") and not used_by_templates(db, tenant_id, row["meta_flow_id"]):
            await _deprecate(tenant_id, row["meta_flow_id"])


def used_by_templates(db, tenant_id: str, flow_id: str) -> bool:
    """An approved template's "Open form" button points at this exact form version (Meta pins
    the flow id at approval). Such a version stays open on Meta after it is replaced, so the
    template keeps working without re-approval; its answers still map, and prices are still
    checked against today's Services."""
    try:
        rows = (
            db.table("message_templates").select("buttons").eq("tenant_id", tenant_id).execute()
        ).data or []
    except Exception:
        return True  # unsure: keep it open rather than break a template
    return any(
        isinstance(b, dict) and str(b.get("flow_id") or "") == str(flow_id)
        for r in rows for b in (r.get("buttons") or [])
    )


CHAT_WINDOW = timedelta(hours=24)


def last_inbound_at(db, tenant_id: str, lead_id: str) -> datetime | None:
    rows = (
        db.table("messages").select("created_at").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
        .eq("direction", "inbound").order("created_at", desc=True).limit(1).execute()
    ).data or []
    return deal_engine.parse_time(rows[0]["created_at"]) if rows else None


async def send_design_to_lead(db, tenant_id: str, design_id: str, lead_id: str) -> str | None:
    """Conversations → Send form. Only inside WhatsApp's 24-hour window (outside it a form needs
    a template with a form button). Raises FormBuildError with a reason the agent can act on."""
    design = get_design(db, tenant_id, design_id)
    if not design or design.get("archived"):
        raise FormBuildError("Form not found.")
    form = live_custom_form(db, tenant_id, design)
    if not form:
        raise FormBuildError("Publish this form (with its latest changes) before sending it.")
    lead = (
        db.table("leads").select("phone, opted_out").eq("id", lead_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not lead or not lead[0].get("phone"):
        raise FormBuildError("This customer has no WhatsApp number.")
    if lead[0].get("opted_out"):
        raise FormBuildError("This customer opted out of WhatsApp messages.")
    last = last_inbound_at(db, tenant_id, lead_id)
    if not last or datetime.now(timezone.utc) - last > CHAT_WINDOW:
        raise FormBuildError(
            "WhatsApp lets you send a form only within 24 hours of the customer's last message. "
            "Ask them to reply first."
        )
    sid = await send_form(lead[0]["phone"], form["intro"], form, cta=form["cta"], tenant_id=tenant_id,
                          via="chat", lead_id=lead_id, db=db)
    db.table("messages").insert({
        "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
        "content": form_record(form["intro"], form["cta"]), "is_ai_generated": False, "meta_message_id": sid,
    }).execute()
    return sid


def _custom_answers(answer_map: dict, answers: dict) -> list[tuple[str, str, str]]:
    """[(key, label, readable value)] in the form's order; empty answers left out."""
    out = []
    for name, field in (answer_map.get("fields") or {}).items():
        value = answers.get(name)
        if value in (None, "", []):
            continue
        options = field.get("options") or {}
        if isinstance(value, list):
            text = ", ".join(options.get(str(v), str(v)) for v in value)
        else:
            text = options.get(str(value), str(value))
        out.append((field["key"], field.get("label") or field["key"], " ".join(text.split())[:500]))
    return out


def _custom_summary(form: dict, answers: dict) -> str:
    answer_map = form.get("answer_map") or {}
    lines = [f"📝 {answer_map.get('form_name') or form.get('name') or 'Form'}"]
    lines += [f"{label}: {value}" for _, label, value in _custom_answers(answer_map, answers)]
    lines.append("Offers on WhatsApp: " + ("yes" if _wants_offers(answers) else "no"))
    return "\n".join(lines)[:1500]


_NAME_KEYS = {"name", "full_name", "student_name", "customer_name"}


async def _handle_custom(db, *, tenant_id: str, lead_id: str, phone: str, form: dict, answers: dict,
                         response: dict, phone_number_id: str | None, send_thanks: bool = True,
                         extra: dict | None = None) -> str:
    """Save a custom form's answers on the lead, record consent, send the thank-you message."""
    if not is_enabled(db, tenant_id):
        # Switched off after the form went out: like the Services form, not applied; the AI answers.
        _set_outcome(db, tenant_id, response["id"], "continued_in_chat")
        return "continue"
    answer_map = form.get("answer_map") or {}
    pairs = [("", label, value) for label, value in (extra or {}).items()] + _custom_answers(answer_map, answers)
    rows = db.table("leads").select("name, collected_data").eq("id", lead_id).eq("tenant_id", tenant_id) \
        .limit(1).execute().data or [{}]
    collected = dict(rows[0].get("collected_data") or {})
    history = list(collected.get("whatsapp_forms") or [])
    history.append({"form_id": form["id"], "form_name": answer_map.get("form_name") or form.get("name"),
                    "submitted_at": _now(), "answers": {label: value for _, label, value in pairs}})
    collected["whatsapp_forms"] = history[-20:]
    patch: dict = {"collected_data": collected}
    name = next((value for key, _, value in pairs if key in _NAME_KEYS), None)
    if name and not rows[0].get("name"):
        patch["name"] = name[:120]
    db.table("leads").update(patch).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
    try:
        db.table("lead_notes").insert({
            "lead_id": lead_id, "tenant_id": tenant_id, "content": _custom_summary(form, answers),
            "is_pinned": False, "structured": False,
        }).execute()
    except Exception:
        logger.exception("WhatsApp Form note failed for lead %s", lead_id)
    _record_consent(db, tenant_id, lead_id, form, _wants_offers(answers))
    intake.note_lead_message(db, tenant_id, lead_id)

    _set_outcome(db, tenant_id, response["id"], "saved")
    if not send_thanks:
        return "handled"
    # The thank-you is an automatic message: Settings > Auto-Reply off means nothing automatic
    # reaches the customer, so the answers are saved and the team sees them, but no thank-you.
    # (A Services form's payment link is different: it is the customer's own payment step, sent
    # like every other payment message regardless of Auto-Reply -- owner's rule for payments.)
    from app.services.automation_guards import ai_replies_allowed_for_lead
    if not ai_replies_allowed_for_lead(db, tenant_id, "whatsapp", lead_id):
        return "handled"
    design = get_design(db, tenant_id, form.get("design_id")) if form.get("design_id") else None
    thanks = form_texts.resolve(_design_settings(design or {}))["thank_you"]
    from app.services.ai_reply import send_whatsapp

    sid = await send_whatsapp(phone, thanks, tenant_id=tenant_id, phone_number_id=phone_number_id)
    db.table("messages").insert({
        "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
        "content": thanks, "is_ai_generated": False, "meta_message_id": sid,
    }).execute()
    return "handled"


def lead_answers(db, tenant_id: str, lead_id: str, limit: int = 20) -> list[dict]:
    """Every form this lead submitted, newest first, with readable answers (lead profile card)."""
    responses = (
        db.table("whatsapp_form_responses").select("id, form_id, answers, outcome, created_at")
        .eq("tenant_id", tenant_id).eq("lead_id", lead_id).order("created_at", desc=True).limit(limit).execute()
    ).data or []
    form_ids = list({r["form_id"] for r in responses if r.get("form_id")})
    forms = {
        f["id"]: f for f in (
            db.table("whatsapp_forms").select("id, name, kind, answer_map").eq("tenant_id", tenant_id)
            .in_("id", form_ids).execute().data or []
        )
    } if form_ids else {}
    out = []
    for r in responses:
        form = forms.get(r.get("form_id")) or {}
        answer_map = form.get("answer_map") or {}
        if answer_map.get("kind") in ("order", "booking"):
            from app.services import whatsapp_live_forms
            pairs = [{"label": label, "value": value}
                     for label, value in whatsapp_live_forms.live_pairs(db, tenant_id, answer_map, r["answers"])]
        elif answer_map.get("kind") == "custom":
            pairs = [{"label": label, "value": value} for _, label, value in _custom_answers(answer_map, r["answers"])]
        else:
            labels = {f["key"]: f.get("label") or f["key"] for f in (answer_map.get("fields") or {}).values()}
            pairs = [{"label": labels.get(key, key), "value": value}
                     for key, value in _details(answer_map, r["answers"]).items()]
            _, path = _choice_path({}, r["answers"], answer_map.get("names"))
            if path:
                pairs.insert(0, {"label": "Choice", "value": " › ".join(path)})
        out.append({"id": r["id"], "form_name": answer_map.get("form_name") or form.get("name") or "Form",
                    "kind": answer_map.get("kind") or form.get("kind"), "submitted_at": r["created_at"],
                    "outcome": r["outcome"], "answers": pairs,
                    "offers": _wants_offers(r["answers"])})
    return out


# ── sending ──────────────────────────────────────────────────────────────────


async def send_form(
    phone: str, body: str, form: dict, *, cta: str, tenant_id: str, phone_number_id: str | None = None,
    via: str = "chat", lead_id: str | None = None, db=None,
) -> str | None:
    """Send one form inside the chat. `via` says why it went (chat, ai, ad, broadcast, services)
    and is saved with the send for the form's numbers."""
    import secrets

    from app.services import meta_cloud

    send_id = secrets.token_hex(6)
    data = await meta_cloud.send_flow_message(
        to_number=phone, body_text=body, flow_id=form["meta_flow_id"], flow_cta=cta,
        flow_token=make_token(tenant_id, phone, form["id"], send_id),
        first_screen=form.get("first_screen", SCREEN_PACKAGE),
        tenant_id=tenant_id, phone_number_id=phone_number_id,
    )
    sid = (data.get("messages") or [{}])[0].get("id")
    record_send(tenant_id, form, send_id=send_id, via=via, lead_id=lead_id, phone=phone, meta_message_id=sid, db=db)
    return sid


SEND_VIAS = ("chat", "ai", "ad", "broadcast", "template", "services")


def record_send(tenant_id: str, form: dict, *, send_id: str, via: str, lead_id: str | None = None,
                phone: str | None = None, meta_message_id: str | None = None, db=None) -> None:
    """Best effort: a failed write never blocks a send. Finds the lead by phone when not given."""
    try:
        if db is None:
            from app.db.supabase import get_supabase
            db = get_supabase()
        if not lead_id and phone:
            digits = _digits(phone)
            rows = (
                db.table("leads").select("id").eq("tenant_id", tenant_id).in_("phone", [f"+{digits}", digits])
                .limit(1).execute()
            ).data or []
            lead_id = rows[0]["id"] if rows else None
        db.table("whatsapp_form_sends").insert({
            "tenant_id": tenant_id, "design_id": form.get("design_id"), "form_id": form["id"], "lead_id": lead_id,
            "via": via if via in SEND_VIAS else "chat", "send_id": send_id, "meta_message_id": meta_message_id,
        }).execute()
    except Exception:
        logger.warning("WhatsApp Form send record failed for tenant %s", tenant_id)


def form_record(body: str, cta: str) -> str:
    """What the conversation history saves for a sent form."""
    return f"{body}\n\n[📝 {cta}]"


# ── receiving ────────────────────────────────────────────────────────────────


def parse_response(raw: str) -> dict:
    try:
        answers = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return answers if isinstance(answers, dict) else {}


def _choice_path(config: dict, answers: dict, saved_names: dict | None = None) -> tuple[str | None, list[str]]:
    """(leaf key, path names) from p1/p2. Names come from today's Services, else from the names
    saved with the form version, else the key."""
    from app.services.deal_actions import _find_node

    packages = intake.normalize_packages(config)
    p1, p2 = str(answers.get("p1") or ""), str(answers.get("p2") or "")
    leaf = p2 if p2 and p2 != NONE_VALUE else p1
    names = []
    for key in (p1, p2):
        if key and key != NONE_VALUE:
            node = _find_node(packages, key)
            names.append(node.get("name") if node else (saved_names or {}).get(key, key))
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
        answer_map = form.get("answer_map") or {}
        if answer_map.get("kind") == "custom":
            return _custom_summary(form, answers)
        if answer_map.get("kind") in ("order", "booking"):
            from app.services import whatsapp_live_forms
            lines = [f"📝 {answer_map.get('form_name') or form.get('name') or 'Form'}"]
            lines += [f"{label}: {value}" for label, value in whatsapp_live_forms.live_pairs(db, tenant_id, answer_map, answers)]
            lines.append("Offers on WhatsApp: " + ("yes" if _wants_offers(answers) else "no"))
            return "\n".join(lines)[:1500]
        config = intake.get_intake_config(tenant_id, db=db)
        leaf, path = _choice_path(config, answers, answer_map.get("names"))
        lines = ["📝 Form submitted"]
        if path:
            lines.append("Choice: " + " › ".join(path))
        addons = _addon_keys(form.get("answer_map") or {}, answers, leaf)
        if addons:
            found = intake._find_leaf(intake.normalize_packages(config), leaf) if leaf else None
            names = {**(answer_map.get("names") or {}),
                     **{a["key"]: a.get("name") for a in ((found[0].get("addons") if found else None) or [])}}
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
    return "ignored" if earlier and earlier[0].get("outcome") in ("link_sent", "saved") else "continue"


def _set_outcome(db, tenant_id: str, response_id: str, outcome: str, session_id: str | None = None) -> None:
    patch: dict = {"outcome": outcome}
    if session_id:
        patch["intake_session_id"] = session_id
    db.table("whatsapp_form_responses").update(patch).eq("id", response_id).eq("tenant_id", tenant_id).execute()


def _record_consent(db, tenant_id: str, lead_id: str, form: dict, offers: bool) -> None:
    source = f"whatsapp_form:{form['id']}"
    wording = (form.get("answer_map") or {}).get("consent_wording") or "Offers opt-in on the WhatsApp Form"
    try:
        db.table("lead_consents").insert([
            {"tenant_id": tenant_id, "lead_id": lead_id, "scope": "replies", "granted": True, "source": source,
             "wording": "Submitted a WhatsApp Form"},
            {"tenant_id": tenant_id, "lead_id": lead_id, "scope": "offers", "granted": offers, "source": source,
             "wording": wording},
        ]).execute()
    except Exception:
        logger.exception("Consent record failed for lead %s", lead_id)


def _confirmation(session: dict, texts: dict) -> tuple[str, str]:
    """(message, button label) for the payment link, in the client's words. Amounts come from
    the session the executors just priced, never from the form."""
    path = [step.get("name") for step in (session.get("package_path") or []) if step.get("name")]
    lines = ["✅ " + (" › ".join(path) or session.get("package_name") or "")]
    for addon in session.get("selected_addons") or []:
        lines.append(f"+ {addon.get('name')} ({deal_engine._rupees(addon.get('amount_paise') or 0)})")
    total = session.get("amount_paise") or session.get("total_amount_paise") or 0
    amount = deal_engine._rupees(total)
    line = f"{texts['total']}: {amount}"
    if session.get("gst_amount_paise"):
        line += f" ({texts['incl_gst']} {deal_engine._rupees(session['gst_amount_paise'])})"
    lines += [line, "", texts["pay_note"]]
    label = texts["pay_button"].replace("{amount}", amount)
    return "\n".join(lines), (label if len(label) <= 20 else amount)


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
    kind = (form.get("answer_map") or {}).get("kind")
    if kind in ("order", "booking"):
        if not is_enabled(db, tenant_id):
            _set_outcome(db, tenant_id, response["id"], "continued_in_chat")
            return "continue"
        from app.services import whatsapp_live_forms
        handler = whatsapp_live_forms.handle_order if kind == "order" else whatsapp_live_forms.handle_booking
        return await handler(db, tenant_id=tenant_id, lead_id=lead_id, phone=phone, form=form, answers=answers,
                             response=response, phone_number_id=phone_number_id)
    if kind == "custom":
        return await _handle_custom(db, tenant_id=tenant_id, lead_id=lead_id, phone=phone, form=form,
                                    answers=answers, response=response, phone_number_id=phone_number_id)

    ctx = deal_turn.build_context(db, tenant_id, lead_id, phone)
    if not ctx.offerings_enabled or not collects_with_form(ctx.config) or not is_enabled(db, tenant_id):
        # Switched back to chat (or off) after the form went out: the AI answers the summary.
        _set_outcome(db, tenant_id, response["id"], "continued_in_chat")
        return "continue"
    answer_map = form.get("answer_map") or {}
    leaf, _ = _choice_path(ctx.config, answers)
    _record_consent(db, tenant_id, lead_id, form, _wants_offers(answers))
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

    text, label = _confirmation(session, form_texts.resolve(ctx.config.get("form_texts")))
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

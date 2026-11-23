"""WhatsApp Forms, Phase 4: live forms that read the business's data while the customer fills them.

Two kinds (whatsapp_form_designs.kind):
  * order   -- search / pick Catalogue items with today's price and stock, quantities, delivery
               details, a live summary; on Submit the order goes through deal_actions._send_quote
               (the same price and stock rules as the AI's quotes) and the payment link is sent.
  * booking -- only free dates and times from the business's weekly hours, slot length and
               capacity; on Submit a seat is reserved atomically (UNIQUE(design, slot, seat)).

How a live form talks to Anril (Meta "Flows endpoint", data_api_version 3.0):
  Meta POSTs {encrypted_flow_data, encrypted_aes_key, initial_vector} to
  /api/v1/whatsapp-forms/data/{tenant_id}. The AES key is RSA-OAEP(SHA-256)-encrypted with
  the business's public key (uploaded per WhatsApp number, whatsapp_flow_keys); the payload is
  AES-128-GCM. The reply is AES-GCM with the same key and the bit-flipped IV, base64.
  The endpoint only returns lists (items, free slots, a summary); nothing is saved until the
  normal nfm_reply submission, which is verified with the per-customer signed token.

Every customer-facing word comes from form_texts (English / Tamil / Tanglish, editable).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services import form_texts
from app.services import whatsapp_forms as wf

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
DATA_API_VERSION = "3.0"
MAX_LINES = 5
LIST_MAX = 20  # radio/checkbox options per screen (Meta)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

S_SEARCH, S_PRODUCTS, S_QUANTITY, S_DELIVERY, S_SUMMARY = "SEARCH", "PRODUCTS", "QUANTITY", "DELIVERY", "SUMMARY"
S_DATE, S_SLOT, S_FULL = "DATE", "SLOT", "FULL"

ORDER_DEFAULTS = {"max_items": 3, "ask_address": True}
BOOKING_DEFAULTS = {
    "days_ahead": 14, "slot_minutes": 30, "capacity": 1, "min_notice_minutes": 60,
    "hours": {d: ([["10:00", "18:00"]] if d != "sun" else []) for d in DAYS},
}


# ── settings ─────────────────────────────────────────────────────────────────


def _int(value, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


def _hhmm(text) -> time | None:
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(text or "").strip())
    return time(int(match.group(1)), int(match.group(2))) if match else None


def clean_settings(kind: str, raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    if kind == "order":
        return {"max_items": _int(raw.get("max_items"), 1, MAX_LINES, ORDER_DEFAULTS["max_items"]),
                "ask_address": bool(raw.get("ask_address", True))}
    if kind == "booking":
        hours_in = raw.get("hours") if isinstance(raw.get("hours"), dict) else BOOKING_DEFAULTS["hours"]
        hours = {}
        for day in DAYS:
            ranges = []
            for pair in hours_in.get(day) or []:
                if isinstance(pair, (list, tuple)) and len(pair) == 2 and _hhmm(pair[0]) and _hhmm(pair[1]):
                    ranges.append([str(pair[0]).strip(), str(pair[1]).strip()])
            hours[day] = ranges[:4]
        return {
            "days_ahead": _int(raw.get("days_ahead"), 1, 60, BOOKING_DEFAULTS["days_ahead"]),
            "slot_minutes": _int(raw.get("slot_minutes"), 10, 480, BOOKING_DEFAULTS["slot_minutes"]),
            "capacity": _int(raw.get("capacity"), 1, 50, BOOKING_DEFAULTS["capacity"]),
            "min_notice_minutes": _int(raw.get("min_notice_minutes"), 0, 7 * 24 * 60, BOOKING_DEFAULTS["min_notice_minutes"]),
            "hours": hours,
        }
    return {}


def settings_problems(kind: str, raw) -> list[str]:
    if kind != "booking":
        return []
    settings = clean_settings(kind, raw)
    out = []
    if not any(settings["hours"].values()):
        out.append("Add the hours you take bookings on at least one day.")
    for day, ranges in settings["hours"].items():
        for start, end in ranges:
            if _hhmm(start) >= _hhmm(end):
                out.append(f"{day.capitalize()}: the closing time must be after the opening time.")
    return out


# ── keys: per WhatsApp number, private key encrypted at rest ────────────────


def _vault_key() -> bytes:
    from app.config import settings as app_config

    base = (os.getenv("FLOW_KEY_SECRET") or app_config.supabase_service_key or "").encode()
    if not base:
        raise RuntimeError("No server secret for WhatsApp Form keys")
    return hashlib.sha256(base + b"|anril-flow-private-key-v1").digest()


def _seal(plain: bytes, bound_to: str = "") -> str:
    """Encrypt a private key. `bound_to` ("tenant|phone number id") ties it to its own row."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(_vault_key()).encrypt(nonce, plain, bound_to.encode())).decode()


def _open(sealed: str, bound_to: str = "") -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = base64.b64decode(sealed)
    return AESGCM(_vault_key()).decrypt(raw[:12], raw[12:], bound_to.encode())


def _bound(tenant_id: str, phone_number_id: str) -> str:
    return f"{tenant_id}|{phone_number_id}"


def _new_key_pair() -> tuple[str, bytes]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return public, private


def _phone_number_id(tenant_id: str) -> str:
    from app.config_dynamic import get_setting

    pid = get_setting("meta_phone_number_id", tenant_id=tenant_id)
    if not pid:
        raise wf.FormPublishError("Connect WhatsApp in Settings first.")
    return str(pid)


async def ensure_keys(db, tenant_id: str) -> None:
    """Make sure this WhatsApp number has a key pair and Meta has its public key. Idempotent."""
    import httpx

    pid = _phone_number_id(tenant_id)
    rows = (
        db.table("whatsapp_flow_keys").select("*").eq("tenant_id", tenant_id).eq("phone_number_id", pid)
        .limit(1).execute()
    ).data or []
    if rows and not _readable(rows[0], tenant_id, pid):
        # The server secret changed (or the row was tampered with): start over with a new pair.
        logger.warning("WhatsApp Form key for tenant %s can't be read; making a new one", tenant_id)
        db.table("whatsapp_flow_keys").delete().eq("tenant_id", tenant_id).eq("phone_number_id", pid).execute()
        rows = []
    if rows and rows[0].get("uploaded_at"):
        return
    if rows:
        public = rows[0]["public_key"]
    else:
        public, private = _new_key_pair()
        db.table("whatsapp_flow_keys").insert({
            "tenant_id": tenant_id, "phone_number_id": pid, "public_key": public,
            "private_key_enc": _seal(private, _bound(tenant_id, pid)),
        }).execute()
    token, _ = wf._meta_creds(tenant_id)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = (await client.post(f"{wf.GRAPH}/{pid}/whatsapp_business_encryption",
                                         headers={"Authorization": f"Bearer {token}"},
                                         data={"business_public_key": public})).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise wf.FormPublishError("Could not reach Meta to set up live forms. Try again in a minute.") from exc
    message = wf._meta_error(payload)
    if message or not payload.get("success"):
        raise wf.FormPublishError(message or "Meta didn't accept the live-form key. Try again.")
    db.table("whatsapp_flow_keys").update({"uploaded_at": wf._now()}) \
        .eq("tenant_id", tenant_id).eq("phone_number_id", pid).execute()
    _KEY_CACHE.pop(tenant_id, None)


def _readable(row: dict, tenant_id: str, phone_number_id: str) -> bool:
    try:
        _open(row["private_key_enc"], _bound(tenant_id, phone_number_id))
        return True
    except Exception:
        return False


_KEY_CACHE: dict[str, tuple[float, list]] = {}
_KEY_TTL = 300.0


def private_keys(db, tenant_id: str) -> list:
    """This business's private keys (newest first), cached a few minutes: loading an RSA key is slow."""
    import time as _time

    from cryptography.hazmat.primitives import serialization

    cached = _KEY_CACHE.get(tenant_id)
    if cached and _time.monotonic() - cached[0] < _KEY_TTL:
        return cached[1]
    rows = (
        db.table("whatsapp_flow_keys").select("phone_number_id, private_key_enc").eq("tenant_id", tenant_id)
        .order("created_at", desc=True).limit(3).execute()
    ).data or []
    keys = []
    for r in rows:
        try:
            keys.append(serialization.load_pem_private_key(
                _open(r["private_key_enc"], _bound(tenant_id, r["phone_number_id"])), password=None))
        except Exception:
            logger.warning("Unreadable WhatsApp Form key for tenant %s (republish a live form to renew it)", tenant_id)
    if keys:
        _KEY_CACHE[tenant_id] = (_time.monotonic(), keys)
    return keys


# ── Meta's encryption ────────────────────────────────────────────────────────


class EndpointError(Exception):
    """Meta gets HTTP 421 (cannot decrypt -> Meta re-fetches the key) or 4xx."""

    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


def decrypt_request(body: dict, private_keys: list) -> tuple[dict, bytes, bytes]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        encrypted_key = base64.b64decode(body["encrypted_aes_key"])
        data = base64.b64decode(body["encrypted_flow_data"])
        iv = base64.b64decode(body["initial_vector"])
    except (KeyError, ValueError, TypeError) as exc:
        raise EndpointError(400) from exc
    for key in private_keys:
        try:
            aes_key = key.decrypt(encrypted_key, padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            plain = AESGCM(aes_key).decrypt(iv, data, None)
            return json.loads(plain.decode("utf-8")), aes_key, iv
        except Exception:
            continue
    raise EndpointError(421)


def encrypt_response(response: dict, aes_key: bytes, iv: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    flipped = bytes(b ^ 0xFF for b in iv)
    sealed = AESGCM(aes_key).encrypt(flipped, json.dumps(response, ensure_ascii=False).encode("utf-8"), None)
    return base64.b64encode(sealed).decode()


# ── Flow JSON ────────────────────────────────────────────────────────────────

_STR = {"type": "string", "__example__": "x"}
_BOOL = {"type": "boolean", "__example__": True}
_OPTIONS = {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"}}},
    "__example__": [{"id": "x", "title": "x", "description": "x"}]}
_PLAIN_OPTIONS = {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "title": {"type": "string"}}}, "__example__": [{"id": "x", "title": "x"}]}


def _exchange(payload: dict, label: str) -> dict:
    return {"type": "Footer", "label": label, "on-click-action": {"name": "data_exchange", "payload": payload}}


def build_order_flow(design: dict) -> tuple[dict, dict]:
    texts = form_texts.resolve(wf._design_settings(design))
    settings = clean_settings("order", design.get("settings"))
    lines = settings["max_items"]
    quantity_children = []
    for n in range(1, lines + 1):
        quantity_children.append({
            "type": "Dropdown", "name": f"q{n}", "label": f"${{data.q{n}_label}}", "required": False,
            "visible": f"${{data.q{n}_visible}}", "data-source": f"${{data.q{n}_options}}",
        })
    quantity_data = {}
    for n in range(1, lines + 1):
        quantity_data |= {f"q{n}_label": _STR, f"q{n}_visible": _BOOL, f"q{n}_options": _PLAIN_OPTIONS}
    screens = [
        {"id": S_SEARCH, "title": texts["title_search"], "data": {},
         "layout": {"type": "SingleColumnLayout", "children": [
             {"type": "TextInput", "name": "q", "label": texts["search_label"], "required": True, "input-type": "text"},
             _exchange({"q": "${form.q}"}, texts["continue"])]}},
        {"id": S_PRODUCTS, "title": texts["title_products"], "data": {"items": _OPTIONS},
         "layout": {"type": "SingleColumnLayout", "children": [
             {"type": "CheckboxGroup", "name": "items", "label": texts["products_label"], "required": True,
              "min-selected-items": 1, "max-selected-items": lines, "data-source": "${data.items}"},
             _exchange({"items": "${form.items}"}, texts["continue"])]}},
        {"id": S_QUANTITY, "title": texts["title_quantity"], "data": {**quantity_data, "chosen": _STR},
         "layout": {"type": "SingleColumnLayout", "children": quantity_children + [
             _exchange({"chosen": "${data.chosen}", **{f"q{n}": f"${{form.q{n}}}" for n in range(1, lines + 1)}},
                       texts["continue"])]}},
    ]
    if settings["ask_address"]:
        screens.append({"id": S_DELIVERY, "title": texts["title_delivery"], "data": {"lines": _STR},
                        "layout": {"type": "SingleColumnLayout", "children": [
                            {"type": "TextInput", "name": "name", "label": texts["name_label"], "required": True,
                             "input-type": "text"},
                            {"type": "TextArea", "name": "address", "label": texts["address_label"], "required": True},
                            _exchange({"lines": "${data.lines}", "name": "${form.name}", "address": "${form.address}"},
                                      texts["continue"])]}})
    screens.append({
        "id": S_SUMMARY, "title": texts["title_summary"], "terminal": True, "success": True,
        "data": {"summary": _STR, "lines": _STR, "name": _STR, "address": _STR},
        "layout": {"type": "SingleColumnLayout", "children": [
            {"type": "TextBody", "text": "${data.summary}"},
            {"type": "TextBody", "text": texts["summary_note"]},
            {"type": "OptIn", "name": "consent_offers", "label": texts["consent"], "required": False},
            {"type": "Footer", "label": texts["submit"], "on-click-action": {"name": "complete", "payload": {
                "lines": "${data.lines}", "name": "${data.name}", "address": "${data.address}",
                "consent_offers": "${form.consent_offers}"}}}]},
    })
    for screen in screens:
        screen.setdefault("terminal", False)
    after_quantity = [S_DELIVERY] if settings["ask_address"] else [S_SUMMARY]
    routing = {S_SEARCH: [S_PRODUCTS], S_PRODUCTS: [S_QUANTITY], S_QUANTITY: after_quantity, S_SUMMARY: []}
    if settings["ask_address"]:
        routing[S_DELIVERY] = [S_SUMMARY]
    flow = {"version": wf.FLOW_JSON_VERSION, "data_api_version": DATA_API_VERSION, "routing_model": routing,
            "screens": screens}
    return flow, {"kind": "order", "form_name": str(design.get("name") or "").strip(),
                  "consent_wording": texts["consent"], "fields": {}}


def build_booking_flow(design: dict) -> tuple[dict, dict]:
    """DATE -> SLOT (both from the endpoint) -> the form's own questions -> CONFIRM."""
    texts = form_texts.resolve(wf._design_settings(design))
    custom_flow, answer_map = wf.build_custom_flow(design) if design.get("fields") else (
        {"screens": [{"id": wf.SCREEN_CONFIRM, "data": {}, "layout": {"children": []}}]}, {"fields": {}})
    question_screens = [s for s in custom_flow["screens"] if s["id"] != wf.SCREEN_CONFIRM]
    slot_data = {"slot": _STR, "slot_label": _STR}
    # The booked slot travels through every question screen to the end.
    for s in question_screens:
        s["data"] = {**slot_data, **(s.get("data") or {})}
        for child in s["layout"]["children"]:
            action = child.get("on-click-action") if isinstance(child, dict) else None
            if action and action.get("name") == "navigate":
                action["payload"] = {"slot": "${data.slot}", "slot_label": "${data.slot_label}", **action["payload"]}
    confirm_src = next(s for s in custom_flow["screens"] if s["id"] == wf.SCREEN_CONFIRM)
    carried = {k: v for k, v in (confirm_src.get("data") or {}).items()}
    complete = {k: f"${{data.{k}}}" for k in carried}
    complete |= {"slot": "${data.slot}", "consent_offers": "${form.consent_offers}"}
    confirm = {
        "id": wf.SCREEN_CONFIRM, "title": texts["title_confirm"], "terminal": True, "success": True,
        "data": {**carried, **slot_data},
        "layout": {"type": "SingleColumnLayout", "children": [
            {"type": "TextBody", "text": "${data.slot_label}"},
            {"type": "TextBody", "text": texts["form_note"]},
            {"type": "OptIn", "name": "consent_offers", "label": texts["consent"], "required": False},
            {"type": "Footer", "label": texts["submit"], "on-click-action": {"name": "complete", "payload": complete}}]},
    }
    first_after_slot = question_screens[0]["id"] if question_screens else wf.SCREEN_CONFIRM
    screens = [
        {"id": S_DATE, "title": texts["title_date"], "terminal": False, "data": {"dates": _PLAIN_OPTIONS},
         "layout": {"type": "SingleColumnLayout", "children": [
             {"type": "Dropdown", "name": "date", "label": texts["date_label"], "required": True,
              "data-source": "${data.dates}"},
             _exchange({"date": "${form.date}"}, texts["continue"])]}},
        {"id": S_SLOT, "title": texts["title_slot"], "terminal": False, "data": {"slots": _PLAIN_OPTIONS, "date": _STR},
         "layout": {"type": "SingleColumnLayout", "children": [
             {"type": "RadioButtonsGroup", "name": "slot", "label": texts["slot_label"], "required": True,
              "data-source": "${data.slots}"},
             _exchange({"date": "${data.date}", "slot": "${form.slot}"}, texts["continue"])]}},
        *question_screens,
        confirm,
        {"id": S_FULL, "title": texts["title_full"], "terminal": True, "success": True, "data": {},
         "layout": {"type": "SingleColumnLayout", "children": [
             {"type": "TextBody", "text": texts["full_note"]},
             {"type": "Footer", "label": texts["submit"], "on-click-action": {"name": "complete",
                                                                              "payload": {"full": "yes"}}}]}},
    ]
    routing = {S_DATE: [S_FULL, S_SLOT], S_SLOT: [first_after_slot], wf.SCREEN_CONFIRM: [], S_FULL: []}
    for s in question_screens:
        routing[s["id"]] = sorted(wf._navigate_targets(s["layout"]))
    flow = {"version": wf.FLOW_JSON_VERSION, "data_api_version": DATA_API_VERSION, "routing_model": routing,
            "screens": screens}
    return flow, {"kind": "booking", "form_name": str(design.get("name") or "").strip(),
                  "consent_wording": texts["consent"], "fields": answer_map.get("fields") or {},
                  "first_question": first_after_slot}


# ── live data: Catalogue items ───────────────────────────────────────────────


def _items(db, tenant_id: str, query: str | None = None, ids: list[str] | None = None) -> list[dict]:
    q = (db.table("catalog_items").select("id, name, price_paise, stock_quantity, gst_rate")
         .eq("tenant_id", tenant_id).eq("status", "ready"))
    if ids is not None:
        ids = [i for i in ids if isinstance(i, str) and _UUID.fullmatch(i)]
        q = q.in_("id", ids or ["00000000-0000-0000-0000-000000000000"])
    if query:
        safe = "".join(ch for ch in query if ch.isalnum() or ch in " -").strip()[:60]
        if safe:
            q = q.ilike("name", f"%{safe}%")
    rows = q.order("name").limit(200).execute().data or []
    return [r for r in rows if r.get("price_paise") is not None and (r.get("stock_quantity") is None or r["stock_quantity"] > 0)]


def _item_option(item: dict) -> dict:
    from app.services.deal_engine import _rupees

    note = _rupees(item["price_paise"])
    if item.get("stock_quantity") is not None:
        note += f" · {item['stock_quantity']}"
    return {"id": item["id"], "title": wf._cut(item["name"], 30), "description": note}


def _product_screen(texts: dict, items: list[dict]) -> dict:
    options = [_item_option(i) for i in items[:LIST_MAX]] or [
        {"id": "none", "title": wf._cut(texts["no_results"], 30), "description": ""}]
    return {"screen": S_PRODUCTS, "data": {"items": options}}


def _summary_text(texts: dict, resolved: list[dict], total: int) -> str:
    from app.services.deal_engine import _rupees

    rows = [f"{li['qty']} × {li['name']} — {_rupees(li['line_total_paise'])}" for li in resolved]
    return "\n".join(rows + [f"{texts['total']}: {_rupees(total)}"])


def _parse_lines(raw) -> list[dict]:
    try:
        lines = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    merged: dict[str, int] = {}  # the same product twice is one line (stock is checked per line)
    for li in lines if isinstance(lines, list) else []:
        if isinstance(li, dict) and isinstance(li.get("id"), str) and str(li.get("qty", "")).isdigit():
            if li["id"] in merged or len(merged) < MAX_LINES:
                merged[li["id"]] = merged.get(li["id"], 0) + max(1, int(li["qty"]))
    return [{"id": item_id, "qty": min(qty, 999)} for item_id, qty in merged.items()]


# ── live data: free booking slots ────────────────────────────────────────────

_TA_DAYS = ("திங்கள்", "செவ்வாய்", "புதன்", "வியாழன்", "வெள்ளி", "சனி", "ஞாயிறு")
_TA_MONTHS = ("ஜன", "பிப்", "மார்", "ஏப்", "மே", "ஜூன்", "ஜூலை", "ஆக", "செப்", "அக்", "நவ", "டிச")


def _day_title(day: date, language: str) -> str:
    if language == "ta":
        return f"{_TA_DAYS[day.weekday()]}, {day.day} {_TA_MONTHS[day.month - 1]}"
    return day.strftime("%a, %d %b").replace(" 0", " ")


def _time_title(moment: datetime, language: str) -> str:
    hour12 = moment.hour % 12 or 12
    clock = f"{hour12}:{moment.minute:02d}"
    if language == "ta":
        part = "காலை" if moment.hour < 12 else "மதியம்" if moment.hour < 16 else "மாலை" if moment.hour < 19 else "இரவு"
        return f"{part} {clock}"
    return f"{clock} {'AM' if moment.hour < 12 else 'PM'}"


def slot_label(slot_start: datetime, language: str) -> str:
    local = slot_start.astimezone(IST)
    return f"{_day_title(local.date(), language)}, {_time_title(local, language)}"


def _slot_id(moment: datetime) -> str:
    return moment.astimezone(IST).strftime("%Y%m%d%H%M")


def parse_slot_id(slot_id: str) -> datetime | None:
    try:
        return datetime.strptime(str(slot_id), "%Y%m%d%H%M").replace(tzinfo=IST)
    except ValueError:
        return None


def _taken(db, tenant_id: str, design_id: str, start: datetime, end: datetime) -> dict[str, int]:
    rows = (
        db.table("whatsapp_form_bookings").select("slot_start").eq("tenant_id", tenant_id).eq("design_id", design_id)
        .eq("cancelled", False).gte("slot_start", start.isoformat()).lt("slot_start", end.isoformat()).execute()
    ).data or []
    counts: dict[str, int] = {}
    for r in rows:
        moment = datetime.fromisoformat(str(r["slot_start"]).replace("Z", "+00:00"))
        counts[_slot_id(moment)] = counts.get(_slot_id(moment), 0) + 1
    return counts


def offered_starts(design: dict, day: date, now: datetime | None = None) -> list[datetime]:
    """Every slot the business's hours offer on that day, from the minimum notice on."""
    settings = clean_settings("booking", design.get("settings"))
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    earliest = now + timedelta(minutes=settings["min_notice_minutes"])
    step = timedelta(minutes=settings["slot_minutes"])
    starts: list[datetime] = []
    for open_at, close_at in settings["hours"][DAYS[day.weekday()]]:
        moment = datetime.combine(day, _hhmm(open_at), IST)
        close = datetime.combine(day, _hhmm(close_at), IST)
        while moment + step <= close:
            if moment >= earliest:
                starts.append(moment)
            moment += step
    return starts


def _inside_shop_hours(starts: list[datetime], step: timedelta, shop: dict, day: date) -> list[datetime]:
    """v9.2 #59: only slots inside the shop's open hours (nothing on a closed day). Hours not set -> unchanged."""
    from app.services import booking_setup as bsetup
    from app.services import open_hours
    if not shop.get("set"):
        return starts
    if open_hours.closed_on(shop, day):
        return []
    blocks = bsetup.hours_minutes(shop.get("hours")).get(day.weekday(), [])
    mins = int(step.total_seconds() // 60)
    return [s for s in starts if any(a <= s.hour * 60 + s.minute and s.hour * 60 + s.minute + mins <= b for a, b in blocks)]


def free_slots(db, tenant_id: str, design: dict, day: date, now: datetime | None = None,
               shop: dict | None = None) -> list[datetime]:
    settings = clean_settings("booking", design.get("settings"))
    step = timedelta(minutes=settings["slot_minutes"])
    if shop is None:
        from app.services import open_hours
        shop = open_hours.read(db, tenant_id)
    starts = _inside_shop_hours(offered_starts(design, day, now), step, shop, day)
    if not starts:
        return []
    taken = _taken(db, tenant_id, design["id"], starts[0], starts[-1] + step)
    return [s for s in starts if taken.get(_slot_id(s), 0) < settings["capacity"]]


def free_dates(db, tenant_id: str, design: dict, now: datetime | None = None) -> list[date]:
    settings = clean_settings("booking", design.get("settings"))
    today = (now or datetime.now(timezone.utc)).astimezone(IST).date()
    from app.services import open_hours
    shop = open_hours.read(db, tenant_id)
    out = []
    for offset in range(settings["days_ahead"]):
        day = today + timedelta(days=offset)
        if settings["hours"][DAYS[day.weekday()]] and free_slots(db, tenant_id, design, day, now, shop):
            out.append(day)
        if len(out) >= LIST_MAX * 10:
            break
    return out


# ── the endpoint ─────────────────────────────────────────────────────────────


def _design_for_token(db, tenant_id: str, token: str) -> tuple[dict, dict] | None:
    parts = str(token or "").split(".")
    if (len(parts) != 4 or parts[0] != wf.TOKEN_PREFIX or not re.fullmatch(r"[0-9a-f-]{36}", parts[1])
            or not re.fullmatch(r"[0-9a-f]{12}", parts[2]) or not re.fullmatch(r"[0-9a-f]{32}", parts[3])):
        return None
    form = wf._form(db, tenant_id, parts[1])
    if not form or not form.get("design_id"):
        return None
    design = wf.get_design(db, tenant_id, form["design_id"])
    return (form, design) if design else None


def handle_request(db, tenant_id: str, payload: dict, now: datetime | None = None) -> dict:
    """One decrypted request from Meta -> the reply (before encryption). Never writes data."""
    action = payload.get("action")
    if action == "ping":
        return {"data": {"status": "active"}}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if data.get("error"):
        logger.warning("WhatsApp Form client error for tenant %s: %s", tenant_id, str(data.get("error"))[:200])
        return {"data": {"acknowledged": True}}
    found = _design_for_token(db, tenant_id, payload.get("flow_token"))
    if not found:
        raise EndpointError(427)  # Meta shows the form as no longer available
    _, design = found
    texts = form_texts.resolve(wf._design_settings(design))
    language = form_texts.language_of(wf._design_settings(design))
    screen = payload.get("screen")

    if design.get("kind") == "order":
        settings = clean_settings("order", design.get("settings"))
        if action == "INIT":
            items = _items(db, tenant_id)
            return _product_screen(texts, items) if len(items) <= LIST_MAX else {"screen": S_SEARCH, "data": {}}
        if screen == S_SEARCH:
            return _product_screen(texts, _items(db, tenant_id, query=str(data.get("q") or "")))
        if screen == S_PRODUCTS:
            chosen = [i for i in (data.get("items") or []) if isinstance(i, str) and i != "none"][:settings["max_items"]]
            items = {i["id"]: i for i in _items(db, tenant_id, ids=chosen)}
            if not items:
                return _product_screen(texts, _items(db, tenant_id))
            out = {"chosen": json.dumps([i for i in chosen if i in items])}
            for n in range(1, settings["max_items"] + 1):
                item = items.get(chosen[n - 1]) if n <= len(chosen) else None
                most = min(item["stock_quantity"], 20) if item and item.get("stock_quantity") is not None else 20
                out |= {f"q{n}_visible": bool(item), f"q{n}_label": wf._cut(item["name"] if item else "-", 20),
                        f"q{n}_options": [{"id": str(k), "title": str(k)} for k in range(1, max(most, 1) + 1)]}
            return {"screen": S_QUANTITY, "data": out}
        if screen == S_QUANTITY:
            try:
                chosen = json.loads(data.get("chosen") or "[]")
            except ValueError:
                chosen = []
            lines = [{"id": cid, "qty": int(data.get(f"q{n}") or 1) if str(data.get(f"q{n}") or "1").isdigit() else 1}
                     for n, cid in enumerate(chosen[:settings["max_items"]], 1) if isinstance(cid, str)]
            if settings["ask_address"]:
                return {"screen": S_DELIVERY, "data": {"lines": json.dumps(lines)}}
            return _summary_reply(db, tenant_id, texts, lines, "", "")
        if screen == S_DELIVERY:
            return _summary_reply(db, tenant_id, texts, _parse_lines(data.get("lines")),
                                  str(data.get("name") or "")[:120], str(data.get("address") or "")[:500])

    if design.get("kind") == "booking":
        if action == "INIT":
            days = free_dates(db, tenant_id, design, now)[:LIST_MAX * 10]
            options = [{"id": d.isoformat(), "title": _day_title(d, language)} for d in days]
            return {"screen": S_DATE, "data": {"dates": options or [{"id": "none", "title": wf._cut(texts["no_slots"], 30)}]}}
        if screen == S_DATE:
            try:
                day = date.fromisoformat(str(data.get("date") or ""))
            except ValueError:
                return {"screen": S_FULL, "data": {}}
            slots = free_slots(db, tenant_id, design, day, now)
            if not slots:
                return {"screen": S_FULL, "data": {}}
            return {"screen": S_SLOT, "data": {"date": day.isoformat(), "slots": [
                {"id": _slot_id(s), "title": _time_title(s, language)} for s in slots[:LIST_MAX]]}}
        if screen == S_SLOT:
            moment = parse_slot_id(str(data.get("slot") or ""))
            if not moment or not bookable(design, moment, now):
                return {"screen": S_FULL, "data": {}}
            first = wf.build_custom_flow({**design, "fields": design["fields"]})[0]["screens"][0]["id"] \
                if design.get("fields") else wf.SCREEN_CONFIRM
            reply = {"slot": _slot_id(moment), "slot_label": slot_label(moment, language)}
            if first == wf.SCREEN_CONFIRM:
                return {"screen": wf.SCREEN_CONFIRM, "data": reply}
            return {"screen": first, "data": reply}
    raise EndpointError(400)


def _summary_reply(db, tenant_id: str, texts: dict, lines: list[dict], name: str, address: str) -> dict:
    from app.services import deals

    items = {i["id"]: i for i in _items(db, tenant_id, ids=[li["id"] for li in lines])}
    deal_lines = [{"catalog_item_id": li["id"], "name": items[li["id"]]["name"], "qty": li["qty"]}
                  for li in lines if li["id"] in items]
    if not deal_lines:
        return _product_screen(texts, _items(db, tenant_id))
    resolved = deals._resolve_lines(tenant_id, deal_lines, db)
    total = deals._deal_total(tenant_id, resolved, db)
    return {"screen": S_SUMMARY, "data": {
        "summary": _summary_text(texts, resolved, total),
        "lines": json.dumps([{"id": li["catalog_item_id"], "qty": li["qty"]} for li in resolved]),
        "name": name or "-", "address": address or "-"}}


# ── submissions ──────────────────────────────────────────────────────────────


async def handle_order(db, *, tenant_id: str, lead_id: str, phone: str, form: dict, answers: dict,
                       response: dict, phone_number_id: str | None) -> str:
    """Order form submitted: the quote goes through the AI's own guarded executor (price from
    the Catalogue, stock checked now), then its payment link is sent."""
    from app.services import choices, deal_actions, deal_turn

    lines = _parse_lines(answers.get("lines"))
    items = {i["id"]: i for i in _items(db, tenant_id, ids=[li["id"] for li in lines])}
    lines = [li for li in lines if li["id"] in items]
    wf._record_consent(db, tenant_id, lead_id, form, wf._wants_offers(answers))
    if not lines:
        wf._set_outcome(db, tenant_id, response["id"], "continued_in_chat")
        return "continue"
    name = str(answers.get("name") or "").strip()
    address = str(answers.get("address") or "").strip()
    if address and address != "-":
        rows = db.table("leads").select("name, collected_data").eq("id", lead_id).eq("tenant_id", tenant_id) \
            .limit(1).execute().data or [{}]
        collected = {**(rows[0].get("collected_data") or {}), "delivery_address": address[:500]}
        patch: dict = {"collected_data": collected}
        if name and name != "-" and not rows[0].get("name"):
            patch["name"] = name[:120]
        db.table("leads").update(patch).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
    ctx = deal_actions.DealContext(config={}, db=db, lead_id=lead_id, tenant_id=tenant_id, phone=phone,
                                   catalog=items, buttons_enabled=True)
    turn = deal_actions._Turn()
    refusal = await deal_actions._send_quote(
        ctx, {"item_ids": [li["id"] for li in lines], "quantities": [li["qty"] for li in lines]}, turn)
    if refusal or not turn.quote_text:
        logger.info("Order form for lead %s continues in chat: %s", lead_id, refusal)
        wf._set_outcome(db, tenant_id, response["id"], "continued_in_chat")
        return "continue"
    text = turn.quote_text
    link = choices.split_link(text)
    sid, _ = (await deal_turn.send_link(phone, link, tenant_id=tenant_id, phone_number_id=phone_number_id,
                                        original=text)) if link else (None, False)
    if not link:
        from app.services.ai_reply import send_whatsapp
        sid = await send_whatsapp(phone, text, tenant_id=tenant_id, phone_number_id=phone_number_id)
    db.table("messages").insert({"lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound",
                                 "channel": "whatsapp", "content": text, "is_ai_generated": False,
                                 "meta_message_id": sid}).execute()
    wf._set_outcome(db, tenant_id, response["id"], "link_sent")
    return "handled"


def bookable(design: dict, moment: datetime, now: datetime | None = None) -> bool:
    """Still a time the business offers: open hours, enough notice, inside the days ahead."""
    now = (now or datetime.now(IST)).astimezone(IST)
    day = moment.astimezone(IST).date()
    days_ahead = clean_settings("booking", design.get("settings"))["days_ahead"]
    if not (now.date() <= day < now.date() + timedelta(days=days_ahead)):
        return False
    return moment in offered_starts(design, day, now)


def _already_booked(db, tenant_id: str, design_id: str, moment: datetime, lead_id: str) -> bool:
    """One seat per customer per time: a second form from the same customer can't fill a slot."""
    rows = (
        db.table("whatsapp_form_bookings").select("id").eq("tenant_id", tenant_id).eq("design_id", design_id)
        .eq("slot_start", moment.isoformat()).eq("lead_id", lead_id).eq("cancelled", False).limit(1).execute()
    ).data or []
    return bool(rows)


def reserve(db, tenant_id: str, design: dict, slot_start: datetime, lead_id: str, response_id: str) -> bool:
    """Take a free seat in this slot. UNIQUE(design, slot, seat) makes two customers racing for
    the last seat impossible to both win."""
    capacity = clean_settings("booking", design.get("settings"))["capacity"]
    for seat in range(1, capacity + 1):
        try:
            db.table("whatsapp_form_bookings").insert({
                "tenant_id": tenant_id, "design_id": design["id"], "slot_start": slot_start.isoformat(),
                "seat": seat, "lead_id": lead_id, "response_id": response_id, "cancelled": False,
            }).execute()
            return True
        except Exception as exc:
            if "23505" in str(exc) or "duplicate key" in str(exc).lower():
                continue
            raise
    return False


async def handle_booking(db, *, tenant_id: str, lead_id: str, phone: str, form: dict, answers: dict,
                         response: dict, phone_number_id: str | None) -> str:
    from app.services.ai_reply import send_whatsapp

    design = wf.get_design(db, tenant_id, form.get("design_id")) if form.get("design_id") else None
    if not design:
        return "continue"
    texts = form_texts.resolve(wf._design_settings(design))
    language = form_texts.language_of(wf._design_settings(design))
    moment = parse_slot_id(str(answers.get("slot") or ""))
    if not moment:  # the fully-booked screen
        wf._record_consent(db, tenant_id, lead_id, form, wf._wants_offers(answers))
        wf._set_outcome(db, tenant_id, response["id"], "continued_in_chat")
        return "continue"
    # The slot must still be one the business offers (hours may have changed since the form
    # opened); capacity is enforced by reserve().
    if not bookable(design, moment) or _already_booked(db, tenant_id, design["id"], moment, lead_id) \
            or not reserve(db, tenant_id, design, moment, lead_id, response["id"]):
        wf._record_consent(db, tenant_id, lead_id, form, wf._wants_offers(answers))
        text = texts["slot_taken"]
        outcome = "continued_in_chat"
    else:
        await wf._handle_custom(db, tenant_id=tenant_id, lead_id=lead_id, phone=phone, form=form,
                                answers=answers, response=response, phone_number_id=None, send_thanks=False,
                                extra={"Booked for": slot_label(moment, language)})
        text = texts["booked_message"].replace("{slot}", slot_label(moment, language))
        outcome = "saved"
    # The confirmation is an automatic message: Settings → Auto-Reply off keeps the booking
    # (the team sees it on the lead) but sends nothing. (An order's payment link is the
    # customer's own payment step and goes out regardless, like the Services form's.)
    from app.services.automation_guards import ai_replies_allowed_for_lead
    if not ai_replies_allowed_for_lead(db, tenant_id, "whatsapp", lead_id):
        wf._set_outcome(db, tenant_id, response["id"], outcome)
        return "handled"
    sid = await send_whatsapp(phone, text, tenant_id=tenant_id, phone_number_id=phone_number_id)
    db.table("messages").insert({"lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound",
                                 "channel": "whatsapp", "content": text, "is_ai_generated": False,
                                 "meta_message_id": sid}).execute()
    wf._set_outcome(db, tenant_id, response["id"], outcome)
    return "handled"


def live_pairs(db, tenant_id: str, answer_map: dict, answers: dict) -> list[tuple[str, str]]:
    """Readable answers of an order / booking form (summary line, lead card, answers table)."""
    pairs: list[tuple[str, str]] = []
    if answer_map.get("kind") == "order":
        lines = _parse_lines(answers.get("lines"))
        items = {i["id"]: i for i in _items(db, tenant_id, ids=[li["id"] for li in lines])} if lines else {}
        if lines:
            pairs.append(("Items", ", ".join(f"{li['qty']} × {(items.get(li['id']) or {}).get('name', 'item')}"
                                            for li in lines)))
        for key, label in (("name", "Name"), ("address", "Address")):
            value = str(answers.get(key) or "").strip()
            if value and value != "-":
                pairs.append((label, value[:500]))
    else:
        moment = parse_slot_id(str(answers.get("slot") or ""))
        pairs.append(("Booked for", slot_label(moment, "en") if moment else "Fully booked"))
        pairs += [(label, value) for _, label, value in wf._custom_answers(answer_map, answers)]
    return pairs

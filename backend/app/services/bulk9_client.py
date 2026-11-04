# backend/app/services/bulk9_client.py
"""Bulk9 (Fast2SMS white-label) user API, called with ONE client's own sending key.

Docs: https://docs.bulk9.com (review: docs/bulk9-api-review.md). Rules that apply to every call:
- the key travels in the Authorization header, never in the URL (the docs' GET examples put it
  in ?authorization=, which ends up in proxy logs);
- TLS verification stays on (the docs' sample code turns it off);
- sends are POST only. The outbound dry-run guard (services/outbound_guard.py) blocks write
  methods to bulk9.com on a laptop, so a GET send would slip past it.

Bulk9 answers HTTP 200 with {"return": false, ...} for many failures, so every response goes
through _parse, which distinguishes explicit refusal from an unconfirmed response.
"""
from __future__ import annotations

import json as _json
import logging
from decimal import Decimal, InvalidOperation
import re
from typing import Any

import httpx

from app.config_dynamic import get_setting

logger = logging.getLogger(__name__)

BULK9_BASE = "https://bulk9.com"
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class Bulk9Error(RuntimeError):
    """Bulk9 refused the request. `status_code` is Bulk9's own code when it sent one."""

    def __init__(self, message: str, status_code: int | None = None, http_status: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.http_status = http_status


class Bulk9Timeout(RuntimeError):
    """No answer from Bulk9. For a send this means 'may or may not have been accepted'."""


class Bulk9NotConfigured(RuntimeError):
    """This tenant has no Bulk9 key saved."""


def get_api_key(tenant_id: str) -> str:
    key = get_setting("bulk9_api_key", tenant_id=tenant_id)
    if not key:
        raise Bulk9NotConfigured("SMS is not connected for this account")
    return key


def _parse(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code >= 500:
        raise Bulk9Timeout(f"Bulk9 returned HTTP {resp.status_code}; acceptance is unconfirmed")
    try:
        body = resp.json()
    except ValueError:
        raise Bulk9Timeout(f"Bulk9 returned a non-JSON response (HTTP {resp.status_code})")
    if not isinstance(body, dict):
        raise Bulk9Timeout("Bulk9 returned an unexpected response")
    refused = any(value is False or isinstance(value, str) and value.strip().lower() == "false"
                  for value in (body.get("return"), body.get("success")))
    if resp.status_code >= 400 or refused:
        msg = body.get("message")
        if isinstance(msg, list):
            msg = "; ".join(str(m) for m in msg)
        raise Bulk9Error(str(msg or f"Bulk9 error (HTTP {resp.status_code})"),
                         status_code=body.get("status_code"), http_status=resp.status_code)
    return body


async def _request(api_key: str, method: str, path: str, *, json: dict | None = None,
                   params: dict | None = None) -> dict[str, Any]:
    headers = {"Authorization": api_key, "accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(method, f"{BULK9_BASE}{path}", json=json, params=params,
                                        headers=headers)
    except httpx.TimeoutException as exc:
        raise Bulk9Timeout(f"Bulk9 did not answer: {type(exc).__name__}") from exc
    except httpx.TransportError as exc:
        # A connection that failed before anything was sent is still reported as a timeout
        # for sends: we can't prove which side of the request it broke on.
        raise Bulk9Timeout(f"Could not reach Bulk9: {type(exc).__name__}") from exc
    return _parse(resp)


# ---------------------------------------------------------------- SMS credits

async def wallet(api_key: str) -> dict[str, Any]:
    """Remaining SMS count, plus the client's own ₹ wallet (at the rate Anril set for them, never
    Anril's cost); wallet is None when Bulk9 leaves it out or sends junk."""
    body = await _request(api_key, "POST", "/dev/wallet")
    try:
        count = Decimal(str(body.get("sms_count")))
    except InvalidOperation:
        raise Bulk9Error("Bulk9 returned an invalid SMS count")
    if not count.is_finite() or count < 0 or count != count.to_integral_value():
        raise Bulk9Error("Bulk9 returned an invalid SMS count")
    try:
        rupees = Decimal(str(body.get("wallet")))
    except InvalidOperation:
        rupees = None
    if rupees is not None and (not rupees.is_finite() or rupees < 0):
        rupees = None
    return {"sms_count": int(count), "wallet": float(round(rupees, 2)) if rupees is not None else None}


# ---------------------------------------------------------------- sending

async def send_dlt(api_key: str, *, sender_id: str, message_id: str, numbers: list[str],
                   variables: list[str], schedule_time: str | None = None,
                   udf1: str | None = None) -> dict[str, Any]:
    """One request with an approved Bulk9 template (route=dlt). Variables are joined with '|'
    as the docs require; a '|' inside a value would shift every later variable, so it's refused.
    Returns the provider request ID and SMS details."""
    for v in variables:
        if "|" in v:
            raise ValueError("A variable value cannot contain '|'")
    payload: dict[str, Any] = {
        "route": "dlt",
        "sender_id": sender_id,
        "message": int(message_id) if str(message_id).isdigit() else message_id,
        "variables_values": "|".join(variables),
        "numbers": ",".join(numbers),
        "flash": 0,
        "sms_details": 1,
    }
    if schedule_time:
        payload["schedule_time"] = schedule_time
    if udf1:
        payload["udf1"] = udf1
    return scrub_financial(await _request(api_key, "POST", "/dev/bulkV2", json=payload))


async def send_dlt_manual(api_key: str, *, sender_id: str, entity_id: str, template_id: str,
                          message: str, numbers: list[str], udf1: str | None = None) -> dict[str, Any]:
    """Send the full approved wording with DLT IDs (route=dlt_manual). The text must match the
    DLT-approved template exactly, or the operator rejects it."""
    payload: dict[str, Any] = {
        "route": "dlt_manual", "sender_id": sender_id, "entity_id": entity_id,
        "template_id": template_id, "message": message, "numbers": ",".join(numbers),
        "flash": 0, "sms_details": 1,
    }
    if udf1:
        payload["udf1"] = udf1
    return scrub_financial(await _request(api_key, "POST", "/dev/bulkV2", json=payload))


# ---------------------------------------------------------------- DLT manager

async def list_dlt(api_key: str, kind: str = "template") -> dict[str, Any]:
    """kind='sender' or 'template'. Templates come back grouped by sender with message_id,
    message and var_count. Only usable (approved) templates are listed."""
    if kind not in ("sender", "template"):
        raise ValueError("kind must be 'sender' or 'template'")
    return await _request(api_key, "GET", "/dev/dlt_manager", params={"type": kind})


async def add_entity(api_key: str, *, entity_name: str, entity_id: str) -> dict:
    # No screenshot_links: Bulk9's own Add Entity form has no proof upload. If the API ever insists,
    # its refusal message reaches the client as-is.
    return await _request(api_key, "POST", "/dev/dlt_manager/add_entity",
                          json={"entity_name": entity_name, "entity_id": entity_id})


async def add_sender(api_key: str, *, entity_id: str, sender_id: str, proof_urls: list[str] | None = None) -> dict:
    body: dict[str, Any] = {"entity_id": entity_id, "sender_id": sender_id}
    if proof_urls:
        body["screenshot_links"] = proof_urls
    return await _request(api_key, "POST", "/dev/dlt_manager/add_sender", json=body)


async def add_sender_excel(api_key: str, *, entity_id: str, file_url: str) -> dict:
    return await _request(api_key, "POST", "/dev/dlt_manager/add_sender_excel",
                          json={"entity_id": entity_id, "sender_excel": file_url})


async def add_template(api_key: str, *, entity_id: str, sender_ids: list[str], template_id: str,
                       message_text: str, promotional: bool) -> dict:
    return await _request(api_key, "POST", "/dev/dlt_manager/add_template", json={
        "entity_id": entity_id, "sender_id": sender_ids, "template_id": template_id,
        "message_text": message_text, "template_type": "y" if promotional else "n",
    })


async def add_template_excel(api_key: str, *, entity_id: str, file_url: str) -> dict:
    """The DLT portal export already carries each template's category, so none is sent
    (template_type is optional in Bulk9's docs, and its own panel doesn't ask either)."""
    return await _request(api_key, "POST", "/dev/dlt_manager/add_template_excel", json={
        "entity_id": entity_id, "content_excel": file_url,
    })


# Where Bulk9 might report a template's DLT category, and how its values read. The docs list only
# message_id/message/var_count, but its panel shows "Service Implicit" / "Service Explicit / Promo".
_CATEGORY_KEYS = ("template_type", "category", "template_category", "content_type", "type", "msg_type")


def template_category(item: dict) -> str | None:
    """'service' (Service Implicit), 'promotional' (Service Explicit / Promo) or None if Bulk9 didn't say."""
    for key in _CATEGORY_KEYS:
        raw = item.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        v = raw.strip().lower()
        if v == "y" or "explicit" in v or "promo" in v:
            return "promotional"
        if v == "n" or "implicit" in v or v in ("service", "transactional"):
            return "service"
    return None


# ---------------------------------------------------------------- reports

async def delivery_report(api_key: str, request_id: str) -> dict[str, Any]:
    """Per-request report, last 7 days. A 404 means 'no report' — not a failed delivery."""
    return scrub_financial(await _request(api_key, "GET", f"/dev/dlr/{request_id}"), CLIENT_DEBIT_KEYS)


async def sms_logs(api_key: str, *, date_from: str, date_to: str, page: int = 1, limit: int = 100) -> dict:
    """At most a 3-day window (YYYY-MM-DD). Keeps amount_debited; client-facing routes scrub it."""
    return scrub_financial(await _request(api_key, "GET", "/dev/sms_logs",
                          params={"from": date_from, "to": date_to, "page": page, "limit": limit}),
                          CLIENT_DEBIT_KEYS)


async def sms_summary(api_key: str, *, date_from: str, date_to: str) -> dict:
    """At most a 30-day window (YYYY-MM-DD)."""
    return scrub_financial(await _request(api_key, "GET", "/dev/sms_summary", params={"from": date_from, "to": date_to}))


# ---------------------------------------------------------------- OTP

async def otp_send(api_key: str, *, mobile: str, otp_id: str, otp_length: int = 6,
                   otp_expiry: int = 15, variables_values: str | None = None) -> dict:
    if not 4 <= otp_length <= 10:
        raise ValueError("OTP length must be 4 to 10")
    if not 1 <= otp_expiry <= 10080:
        raise ValueError("OTP expiry must be 1 to 10080 minutes")
    body: dict[str, Any] = {"mobile": mobile, "otp_id": otp_id, "otp_length": otp_length,
                            "otp_expiry": otp_expiry}
    if variables_values:
        body["variables_values"] = variables_values
    return await _request(api_key, "POST", "/dev/otp/send", json=body)


async def otp_verify(api_key: str, *, mobile: str, otp: str) -> dict:
    return await _request(api_key, "POST", "/dev/otp/verify", json={"mobile": mobile, "otp": otp})


async def otp_resend(api_key: str, *, mobile: str) -> dict:
    return await _request(api_key, "POST", "/dev/otp/resend", json={"mobile": mobile})


# ---------------------------------------------------------------- delivery webhook config

# service: "sms" (campaign delivery reports) or "otp" (OTP delivery reports). Both send the same
# standard payload (request_id, mobile, status, amount_debited...).
WEBHOOK_SERVICES = ("sms", "otp")
_WEBHOOK_NAMES = {"sms": "Anril delivery updates", "otp": "Anril OTP updates"}


def _webhook_path(service: str) -> str:
    if service not in WEBHOOK_SERVICES:
        raise ValueError(f"unknown webhook service {service!r}")
    return f"/dev/webhook/v2/{service}"


# Body Bulk9 fills per callback (placeholder syntax from its Create SMS Webhook docs). Without a
# template Bulk9 posts an empty body. The secret is repeated here because Bulk9 did not forward
# the custom header on live callbacks; /webhook/bulk9 accepts either and strips it.
_WEBHOOK_FIELDS = ("request_id", "mobile", "status", "status_description", "failure_reason", "description",
                   "sms_count", "amount_debited", "udf1", "sent_timestamp", "delivery_timestamp", "webhook_type")


def _webhook_payload(secret: str) -> str:
    body = {"anril_secret": secret, **{f: f"@{{{{{f}}}}}" for f in _WEBHOOK_FIELDS}}
    return _json.dumps(body, indent=2)


def _webhook_body(service: str, url: str, secret: str) -> dict:
    return {
        "payload": _webhook_payload(secret),
        "name": _WEBHOOK_NAMES[service],
        "url": url,
        "method": "POST",
        "content_type": "application/json",
        "status": "active",
        "event": "all",
        "payload_type": "SIMPLIFIED",
        "template": "custom",
        "payload_transform": "standard",
        "headers": {"X-Anril-Webhook-Secret": secret},
    }


async def list_sms_webhooks(api_key: str, *, service: str = "sms") -> dict:
    return await _request(api_key, "GET", _webhook_path(service))


async def create_sms_webhook(api_key: str, *, url: str, secret: str, service: str = "sms") -> dict:
    """Point this client's delivery updates at Anril. The secret rides in a custom header
    that /webhook/bulk9/{tenant_id} checks; Bulk9 documents no signing of its own."""
    return await _request(api_key, "POST", _webhook_path(service), json=_webhook_body(service, url, secret))


_FINANCIAL_KEY = re.compile(r"(?:^|_)(?:amount|price|cost|charg\w*|debit\w*|credit\w*|wallet|balance|profit|payment|recharge|stock|rate)(?:_|$)", re.I)


# What Bulk9 debited from the client's own wallet for one SMS. Kept for campaign cost and balance
# history; it is the client's price, never Anril's cost.
CLIENT_DEBIT_KEYS = frozenset({"amount_debited"})


def scrub_financial(value: Any, keep: frozenset[str] = frozenset()) -> Any:
    """Remove financial fields recursively before returning or storing provider data.
    Keys in `keep` survive (only CLIENT_DEBIT_KEYS is ever passed)."""
    if isinstance(value, dict):
        return {key: scrub_financial(item, keep) for key, item in value.items()
                if key in keep or not _FINANCIAL_KEY.search(re.sub(r"([a-z])([A-Z])", r"\1_\2", str(key)))}
    if isinstance(value, list):
        return [scrub_financial(item, keep) for item in value]
    return value


def report_groups(body: dict) -> list[dict]:
    data = next((body[key] for key in ("data", "logs", "sms_logs", "reports") if isinstance(body.get(key), (list, dict))), [])
    if isinstance(data, dict):
        data = data.get("data") or data.get("reports") or [data]
    return [row for row in data if isinstance(row, dict)]


def report_rows(body: dict) -> list[dict]:
    """Flatten documented data[].delivery_status[] while preserving parent correlation."""
    rows = []
    for group in report_groups(body):
        children = group.get("delivery_status")
        if isinstance(children, list):
            parent = {key: value for key, value in group.items() if key != "delivery_status"}
            rows.extend({**parent, **child} for child in children if isinstance(child, dict))
        else:
            rows.append(group)
    return rows


def has_more_logs(body: dict, page: int, limit: int) -> bool:
    pagination = body.get("pagination") or {}
    if isinstance(pagination, dict):
        total = pagination.get("total_pages") or pagination.get("last_page")
        if total is not None:
            try:
                return page < int(total)
            except (ValueError, TypeError):
                pass
        if isinstance(pagination.get("has_more"), bool):
            return pagination["has_more"]
    return len(report_groups(body)) >= limit


async def update_sms_webhook(api_key: str, webhook_id: str, *, url: str, secret: str, service: str = "sms") -> dict:
    return await _request(api_key, "PUT", f"{_webhook_path(service)}/{webhook_id}",
                          json=_webhook_body(service, url, secret))


async def delete_sms_webhook(api_key: str, webhook_id: str, *, service: str = "sms") -> dict:
    return await _request(api_key, "DELETE", f"{_webhook_path(service)}/{webhook_id}")

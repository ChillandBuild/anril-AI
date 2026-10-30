# backend/app/services/bulk9_client.py
"""Bulk9 (Fast2SMS white-label) user API, called with ONE client's own sending key.

Docs: https://docs.bulk9.com (review: docs/bulk9-api-review.md). Rules that apply to every call:
- the key travels in the Authorization header, never in the URL (the docs' GET examples put it
  in ?authorization=, which ends up in proxy logs);
- TLS verification stays on (the docs' sample code turns it off);
- sends are POST only. The outbound dry-run guard (services/outbound_guard.py) blocks write
  methods to bulk9.com on a laptop, so a GET send would slip past it.

Bulk9 answers HTTP 200 with {"return": false, ...} for many failures, so every response goes
through _parse, which raises Bulk9Error unless return is true.
"""
from __future__ import annotations

import logging
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
    try:
        body = resp.json()
    except ValueError:
        raise Bulk9Error(f"Bulk9 returned a non-JSON response (HTTP {resp.status_code})",
                         http_status=resp.status_code)
    if not isinstance(body, dict):
        raise Bulk9Error("Bulk9 returned an unexpected response", http_status=resp.status_code)
    if resp.status_code >= 400 or body.get("return") is False:
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


# ---------------------------------------------------------------- wallet

async def wallet(api_key: str) -> dict[str, Any]:
    """{"wallet": "123.45", "sms_count": 600} — the client's balance."""
    return await _request(api_key, "POST", "/dev/wallet")


# ---------------------------------------------------------------- sending

async def send_dlt(api_key: str, *, sender_id: str, message_id: str, numbers: list[str],
                   variables: list[str], schedule_time: str | None = None,
                   udf1: str | None = None) -> dict[str, Any]:
    """One request with an approved Bulk9 template (route=dlt). Variables are joined with '|'
    as the docs require; a '|' inside a value would shift every later variable, so it's refused.
    Returns the body, including request_id and (sms_details=1) charge details."""
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
    return await _request(api_key, "POST", "/dev/bulkV2", json=payload)


async def send_dlt_manual(api_key: str, *, sender_id: str, entity_id: str, template_id: str,
                          message: str, numbers: list[str], udf1: str | None = None) -> dict[str, Any]:
    """Send full approved wording with DLT ids (route=dlt_manual). Bulk9 does not check the text
    against DLT before charging: wrong wording fails at the operator and is not refunded."""
    payload: dict[str, Any] = {
        "route": "dlt_manual", "sender_id": sender_id, "entity_id": entity_id,
        "template_id": template_id, "message": message, "numbers": ",".join(numbers),
        "flash": 0, "sms_details": 1,
    }
    if udf1:
        payload["udf1"] = udf1
    return await _request(api_key, "POST", "/dev/bulkV2", json=payload)


# ---------------------------------------------------------------- DLT manager

async def list_dlt(api_key: str, kind: str = "template") -> dict[str, Any]:
    """kind='sender' or 'template'. Templates come back grouped by sender with message_id,
    message and var_count. Only usable (approved) templates are listed."""
    if kind not in ("sender", "template"):
        raise ValueError("kind must be 'sender' or 'template'")
    return await _request(api_key, "GET", "/dev/dlt_manager", params={"type": kind})


async def add_entity(api_key: str, *, entity_name: str, entity_id: str, proof_urls: list[str]) -> dict:
    return await _request(api_key, "POST", "/dev/dlt_manager/add_entity", json={
        "entity_name": entity_name, "entity_id": entity_id, "screenshot_links": proof_urls,
    })


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


async def add_template_excel(api_key: str, *, entity_id: str, file_url: str, promotional: bool) -> dict:
    return await _request(api_key, "POST", "/dev/dlt_manager/add_template_excel", json={
        "entity_id": entity_id, "content_excel": file_url, "template_type": "y" if promotional else "n",
    })


# ---------------------------------------------------------------- reports

async def delivery_report(api_key: str, request_id: str) -> dict[str, Any]:
    """Per-request report, last 7 days. A 404 means 'no report' — not a failed delivery."""
    return await _request(api_key, "GET", f"/dev/dlr/{request_id}")


async def sms_logs(api_key: str, *, date_from: str, date_to: str, page: int = 1, limit: int = 100) -> dict:
    """At most a 3-day window (YYYY-MM-DD)."""
    return await _request(api_key, "GET", "/dev/sms_logs",
                          params={"from": date_from, "to": date_to, "page": page, "limit": limit})


async def sms_summary(api_key: str, *, date_from: str, date_to: str) -> dict:
    """At most a 30-day window (YYYY-MM-DD)."""
    return await _request(api_key, "GET", "/dev/sms_summary", params={"from": date_from, "to": date_to})


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

async def list_sms_webhooks(api_key: str) -> dict:
    return await _request(api_key, "GET", "/dev/webhook/v2/sms")


async def create_sms_webhook(api_key: str, *, url: str, secret: str) -> dict:
    """Point this client's SMS delivery updates at Anril. The secret rides in a custom header
    that /webhook/bulk9/{tenant_id} checks; Bulk9 documents no signing of its own."""
    return await _request(api_key, "POST", "/dev/webhook/v2/sms", json={
        "name": "Anril delivery updates",
        "url": url,
        "method": "POST",
        "content_type": "application/json",
        "status": "active",
        "event": "all",
        "payload_type": "SIMPLIFIED",
        "template": "custom",
        "payload_transform": "standard",
        "headers": {"X-Anril-Webhook-Secret": secret},
    })

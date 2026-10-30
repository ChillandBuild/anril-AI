# backend/app/services/bulk9_reseller.py
"""Bulk9 reseller API: Prem's own account, used only from the operator console and the
recharge webhook. The reseller key manages client accounts and moves SMS credit; it cannot
send SMS. It lives in the Render env (BULK9_RESELLER_KEY), never in the database.

Docs: https://bulk9.com/reseller/docs (review: docs/bulk9-api-review.md § reseller). POST
bodies are form-encoded (the docs show no JSON support). Key in the Authorization header.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import string
from decimal import Decimal
from typing import Any

import httpx

from app.services.bulk9_client import Bulk9Error, Bulk9Timeout

logger = logging.getLogger(__name__)

RESELLER_BASE = "https://bulk9.com/api/reseller"
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


class ResellerNotConfigured(RuntimeError):
    pass


class InsufficientResellerStock(Bulk9Error):
    """Prem's own SMS stock is lower than the credit being added."""


def _key() -> str:
    key = os.environ.get("BULK9_RESELLER_KEY", "").strip()
    if not key:
        raise ResellerNotConfigured("BULK9_RESELLER_KEY is not set")
    return key


def _check_username(username: str) -> str:
    if not _USERNAME_RE.fullmatch(username or ""):
        raise ValueError("Invalid Bulk9 username")
    return username


async def _call(method: str, path: str, data: dict | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(method, f"{RESELLER_BASE}{path}", data=data,
                                        headers={"Authorization": _key(), "accept": "application/json"})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise Bulk9Timeout(f"Bulk9 reseller API did not answer: {type(exc).__name__}") from exc
    try:
        body = resp.json()
    except ValueError:
        raise Bulk9Error(f"Bulk9 reseller API returned non-JSON (HTTP {resp.status_code})",
                         http_status=resp.status_code)
    if resp.status_code >= 400 or not isinstance(body, dict) or body.get("return") is False:
        msg = body.get("message") if isinstance(body, dict) else None
        code = body.get("status_code") if isinstance(body, dict) else None
        if code == 429:  # Bulk9's own code for "you don't have enough SMS", not a rate limit
            raise InsufficientResellerStock(str(msg or "Not enough SMS in reseller stock"), status_code=429,
                                            http_status=resp.status_code)
        raise Bulk9Error(str(msg or f"Bulk9 reseller error (HTTP {resp.status_code})"),
                         status_code=code, http_status=resp.status_code)
    return body


def strong_password(length: int = 20) -> str:
    """For create-user. Nobody needs it afterwards (Prem uses 'Login as User'), so it's not stored."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length - 2)) + secrets.choice("!@#$%") + secrets.choice(string.digits)
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw):
            return pw


async def reseller_balance() -> dict[str, Any]:
    """{"sms_balance": "500.0000", "sms_count": 48000, ...}"""
    return await _call("POST", "/balance-check")


async def user_balance(username: str) -> dict[str, Any]:
    return await _call("POST", f"/balance-check/{_check_username(username)}")


async def list_users() -> dict[str, Any]:
    return await _call("GET", "/list-user")


async def create_user(*, name: str, username: str, email: str | None = None,
                      mobile: str | None = None) -> dict[str, Any]:
    data = {"name": name, "username": _check_username(username), "password": strong_password()}
    if email:
        data["email"] = email
    if mobile:
        data["mobile"] = mobile
    return await _call("POST", "/create-user", data)


async def enable_user(username: str) -> dict[str, Any]:
    return await _call("POST", f"/enable/{_check_username(username)}")


async def disable_user(username: str) -> dict[str, Any]:
    return await _call("POST", f"/disable/{_check_username(username)}")


async def add_sms_credit(username: str, *, sms_count: int, price_per_sms: Decimal,
                         expiry_date: str | None = None, check_stock: bool = True) -> dict[str, Any]:
    """Give a client `sms_count` SMS at their selling price. Checks Prem's stock first so a
    shortfall is a clear error, not Bulk9's bare 429."""
    if sms_count <= 0:
        raise ValueError("sms_count must be positive")
    if price_per_sms <= 0:
        raise ValueError("price_per_sms must be positive")
    if check_stock:
        bal = await reseller_balance()
        try:
            stock = int(float(bal.get("sms_count") or 0))
        except (TypeError, ValueError):
            stock = 0
        if stock < sms_count:
            raise InsufficientResellerStock(
                f"Reseller stock is {stock} SMS, need {sms_count}", status_code=429)
    data = {"channel": "sms", "no_of_sms": str(sms_count), "per_sms_cost": str(price_per_sms),
            "type_of_invoice": "prepaid"}
    if expiry_date:
        data["expiry_date"] = expiry_date
    return await _call("POST", f"/add-credit/{_check_username(username)}", data)


async def debit_sms_credit(username: str, *, sms_count: int) -> dict[str, Any]:
    if sms_count <= 0:
        raise ValueError("sms_count must be positive")
    return await _call("POST", f"/debit-credit/{_check_username(username)}",
                       {"channel": "sms", "credit_sms": str(sms_count)})

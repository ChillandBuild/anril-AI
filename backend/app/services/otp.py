"""Anril OTP: one-time codes by SMS (Bulk9 DLT template), WhatsApp (Meta authentication
template), both, or SMS first with WhatsApp as the backup. Spec: docs/specs/anril-otp.md.

Who makes the code:
  * Anril ("anril"): generated here, only an HMAC hash is kept, checked by verify().
  * The client's server ("client"): passed in, delivered, only a masked copy is kept.
Either way the plain code lives in memory for the send, plus an AES-GCM copy in
`pending_code_enc` ONLY while an SMS-then-WhatsApp backup may still be due. It is wiped
once the backup is sent or no longer needed (delivered, verified, locked, expired).

Messages always go out from the tenant's OWN Bulk9 balance and WhatsApp number.
Status changes are pushed to the tenant's status URL via the otp_status_events outbox,
signed with HMAC-SHA256 (see sign_payload)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings as app_config
from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.services import bulk9_client

logger = logging.getLogger(__name__)

MODES = ("sms", "whatsapp", "both", "sms_then_whatsapp")
MAX_ATTEMPTS = 5  # default; each client sets its own (otp_settings.max_attempts, 1-10)
KEY_PREFIX = "anr_otp_live_"
KEY_DISPLAY_LEN = 17
MAX_KEY_LEN = 100
CLIENT_CODE_RE = re.compile(r"[0-9A-Za-z]{4,10}")
REF_MAX = 100
VERIFY_BY_PHONE_WINDOW = timedelta(hours=24)
NOT_REQUESTED_PAYLOAD = "DID_NOT_REQUEST_CODE"

DEFAULTS: dict[str, Any] = {
    "default_mode": "sms_then_whatsapp",
    "fallback_wait_seconds": 30,
    "max_per_hour": 5,
    "expiry_minutes": 10,
    "code_length": 6,
    "max_attempts": MAX_ATTEMPTS,
    "sms_sender_id": None,
    "sms_message_id": None,
    "wa_template_name": None,
    "wa_template_language": None,
    "status_webhook_url": None,
}
LIMITS = {
    "fallback_wait_seconds": (10, 300),
    "max_per_hour": (1, 50),
    "expiry_minutes": (1, 30),
    "code_length": (4, 8),
    "max_attempts": (1, 10),
}

# Status-update delivery: try now, then after 1, 5, 15 and 30 minutes (5 tries, ~50 min).
WEBHOOK_BACKOFF_SECONDS = (60, 300, 900, 1800)
WEBHOOK_MAX_ATTEMPTS = len(WEBHOOK_BACKOFF_SECONDS) + 1
WEBHOOK_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_SMS_RANK = {"none": 0, "sent": 1, "failed": 2, "delivered": 3}
_WA_RANK = {"none": 0, "sent": 1, "failed": 2, "delivered": 3, "read": 4}

# Background tasks must be referenced or the loop may garbage-collect them mid-run.
_tasks: set[asyncio.Task] = set()


class OtpError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


# ---------------------------------------------------------------- small helpers

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


_main_loop: asyncio.AbstractEventLoop | None = None


def _spawn(coro) -> None:
    """Run in the background. Webhook handlers call us from worker threads (asyncio.to_thread),
    so hand the job to the server's loop; with no loop at all the otp-sweep job catches up."""
    global _main_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        _main_loop = loop
        task = loop.create_task(coro)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
        return
    coro.close()


def normalize_phone(raw: Any) -> str:
    """'+91 98765 43210' / '9876543210' / '919876543210' -> '919876543210'.
    A bare 10-digit number is taken as Indian. Anything else needs its country code."""
    text = str(raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10 and not text.startswith("+"):
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise OtpError(400, "invalid_phone", "Enter the phone number with its country code, e.g. +919876543210")
    return digits


def india_10(phone: str) -> str | None:
    """Bulk9 sends to Indian numbers only, as 10 digits."""
    if len(phone) == 12 and phone.startswith("91") and phone[2] in "6789":
        return phone[2:]
    return None


def mask_code(code: str) -> str:
    if len(code) >= 6:
        return code[:2] + "•" * (len(code) - 4) + code[-2:]
    return code[0] + "•" * (len(code) - 2) + code[-1]


def generate_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def _secret_material(label: bytes) -> bytes:
    """Server-side key material. OTP_SECRET wins if set; otherwise derived from the
    Supabase service key, which every deployment has and never leaves the backend."""
    base = (os.getenv("OTP_SECRET") or app_config.supabase_service_key or "").encode()
    if not base:
        raise OtpError(503, "not_configured", "OTP is not configured on this server")
    return hmac.new(base, label, hashlib.sha256).digest()


def hash_code(otp_id: str, code: str) -> str:
    return hmac.new(_secret_material(b"anril-otp-hash-v1"), f"{otp_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _encrypt_code(otp_id: str, code: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_secret_material(b"anril-otp-pending-v1")).encrypt(nonce, code.encode(), otp_id.encode())
    return base64.b64encode(nonce + ct).decode()


def _decrypt_code(otp_id: str, blob: str | None) -> str | None:
    if not blob:
        return None
    try:
        raw = base64.b64decode(blob)
        return AESGCM(_secret_material(b"anril-otp-pending-v1")).decrypt(raw[:12], raw[12:], otp_id.encode()).decode()
    except Exception:
        logger.warning("otp pending code could not be decrypted otp=%s", otp_id)
        return None


# ---------------------------------------------------------------- settings

def get_settings(db, tenant_id: str) -> dict:
    rows = (db.table("otp_settings").select("*").eq("tenant_id", tenant_id).limit(1).execute()).data or []
    out = dict(DEFAULTS)
    if rows:
        for key in DEFAULTS:
            if rows[0].get(key) is not None:
                out[key] = rows[0][key]
        out["has_webhook_secret"] = bool(rows[0].get("status_webhook_secret"))
    else:
        out["has_webhook_secret"] = False
    return out


def _webhook_secret(db, tenant_id: str) -> str | None:
    rows = (db.table("otp_settings").select("status_webhook_secret").eq("tenant_id", tenant_id)
            .limit(1).execute()).data or []
    return rows[0].get("status_webhook_secret") if rows else None


def validate_settings(patch: dict) -> dict:
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise OtpError(400, "unknown_setting", f"Unknown setting: {key}")
        if key in LIMITS:
            low, high = LIMITS[key]
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise OtpError(400, "invalid_setting", f"{key} must be a whole number from {low} to {high}")
        elif key == "default_mode":
            if value not in MODES:
                raise OtpError(400, "invalid_setting", "Unknown delivery mode")
        elif key == "status_webhook_url":
            value = (value or "").strip() or None
            if value:
                check_webhook_url(value)
        elif value is not None:
            value = str(value).strip()[:200] or None
        clean[key] = value
    return clean


def save_settings(db, tenant_id: str, patch: dict) -> dict:
    clean = validate_settings(patch)
    merged = {**get_settings(db, tenant_id), **clean}
    merged.pop("has_webhook_secret", None)
    # Only when the mode itself changes: a new account (default sms_then_whatsapp) must be able
    # to save its SMS template before WhatsApp is connected. Sends check readiness anyway.
    problems = mode_problems(db, tenant_id, merged["default_mode"], merged) if "default_mode" in clean else []
    if problems:
        raise OtpError(409, "mode_not_ready", problems[0])
    row = {"tenant_id": tenant_id, **clean, "updated_at": _iso(_now())}
    db.table("otp_settings").upsert(row, on_conflict="tenant_id").execute()
    return get_settings(db, tenant_id)


def rotate_webhook_secret(db, tenant_id: str) -> str:
    secret = "whsec_" + secrets.token_urlsafe(32)
    db.table("otp_settings").upsert(
        {"tenant_id": tenant_id, "status_webhook_secret": secret, "updated_at": _iso(_now())},
        on_conflict="tenant_id",
    ).execute()
    return secret


# ---------------------------------------------------------------- channel readiness

def _sms_enabled(db, tenant_id: str) -> bool:
    rows = (db.table("tenants").select("enabled_features").eq("id", tenant_id).limit(1).execute()).data or []
    return "sms" in ((rows[0].get("enabled_features") if rows else None) or [])


def sms_problem(db, tenant_id: str, cfg: dict) -> str | None:
    if not _sms_enabled(db, tenant_id):
        return "Anril SMS isn't switched on for this account."
    if not get_setting("bulk9_api_key", tenant_id=tenant_id):
        return "Connect your SMS account first."
    if not cfg.get("sms_sender_id") or not cfg.get("sms_message_id"):
        return "Pick the SMS template the code goes in (OTP settings)."
    return None


def whatsapp_problem(tenant_id: str, cfg: dict) -> str | None:
    if not get_setting("meta_phone_number_id", tenant_id=tenant_id) or not get_setting("meta_access_token", tenant_id=tenant_id):
        return "Connect your WhatsApp number first."
    if not cfg.get("wa_template_name") or not cfg.get("wa_template_language"):
        return "Pick an approved WhatsApp authentication template (OTP settings)."
    return None


def mode_problems(db, tenant_id: str, mode: str, cfg: dict) -> list[str]:
    problems = []
    if mode in ("sms", "both", "sms_then_whatsapp"):
        p = sms_problem(db, tenant_id, cfg)
        if p:
            problems.append(p)
    if mode in ("whatsapp", "both", "sms_then_whatsapp"):
        p = whatsapp_problem(tenant_id, cfg)
        if p:
            problems.append(p)
    return problems


# ---------------------------------------------------------------- API keys

def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def create_key(db, tenant_id: str, created_by: str | None) -> dict:
    """Stores only the hash. The full key is returned here once and never again."""
    full = KEY_PREFIX + secrets.token_urlsafe(32)
    row = (db.table("otp_api_keys").insert({
        "tenant_id": tenant_id, "key_prefix": full[:KEY_DISPLAY_LEN], "key_hash": hash_key(full),
        "created_by": created_by, "status": "active",
    }).execute()).data[0]
    return {"id": row["id"], "key": full, "key_prefix": row["key_prefix"], "created_at": row.get("created_at")}


_KEY_PUBLIC_COLUMNS = ("id", "key_prefix", "status", "created_at", "revoked_at", "last_used_at")


def list_keys(db, tenant_id: str) -> list[dict]:
    rows = (db.table("otp_api_keys").select(", ".join(_KEY_PUBLIC_COLUMNS))
            .eq("tenant_id", tenant_id).order("created_at", desc=True).execute()).data or []
    return [{c: r.get(c) for c in _KEY_PUBLIC_COLUMNS} for r in rows]  # never the hash


def revoke_key(db, tenant_id: str, key_id: str) -> bool:
    rows = (db.table("otp_api_keys").update({"status": "revoked", "revoked_at": _iso(_now())})
            .eq("id", key_id).eq("tenant_id", tenant_id).eq("status", "active").execute()).data or []
    return bool(rows)


def find_key(db, raw_key: str | None) -> dict:
    if not raw_key or not raw_key.startswith(KEY_PREFIX) or len(raw_key) > MAX_KEY_LEN:
        raise OtpError(401, "invalid_key", "The API key is missing or wrong")
    rows = (db.table("otp_api_keys").select("id, tenant_id, status, last_used_at")
            .eq("key_hash", hash_key(raw_key)).limit(1).execute()).data or []
    if not rows:
        raise OtpError(401, "invalid_key", "The API key is missing or wrong")
    if rows[0]["status"] != "active":
        raise OtpError(401, "revoked_key", "This API key was revoked")
    key = rows[0]
    last = _parse_ts(key.get("last_used_at"))
    if not last or _now() - last > timedelta(minutes=5):  # don't write on every call
        try:
            db.table("otp_api_keys").update({"last_used_at": _iso(_now())}).eq("id", key["id"]).execute()
        except Exception:
            pass
    return key


# ---------------------------------------------------------------- public view

def public_view(row: dict) -> dict:
    return {
        "otp_id": row["id"],
        "phone": "+" + row["phone"],
        "mode": row["mode"],
        "source": row["source"],
        "status": row["status"],
        "ref": row.get("ref"),
        "expires_at": row.get("expires_at"),
        "verified_at": row.get("verified_at"),
        "sms": {"status": row.get("sms_status", "none"), "error": row.get("sms_error")},
        "whatsapp": {"status": row.get("whatsapp_status", "none"), "error": row.get("whatsapp_error")},
        "whatsapp_backup_sent": bool(row.get("fallback_sent_at")) and row.get("mode") == "sms_then_whatsapp",
        "not_requested": bool(row.get("not_requested_at")),
        "created_at": row.get("created_at"),
    }


def history_view(row: dict) -> dict:
    """Dashboard row: public view plus who sent it and the masked code."""
    return {**public_view(row), "origin": row.get("origin"), "code": row.get("code_masked"),
            "attempts": row.get("attempts", 0)}


def get_request(db, tenant_id: str, otp_id: str) -> dict | None:
    try:
        uuid.UUID(str(otp_id))
    except ValueError:
        return None
    rows = (db.table("otp_requests").select("*").eq("tenant_id", tenant_id).eq("id", str(otp_id))
            .limit(1).execute()).data or []
    return rows[0] if rows else None


def _update(db, otp_id: str, patch: dict, **conditions) -> dict | None:
    q = db.table("otp_requests").update(patch).eq("id", otp_id)
    for column, value in conditions.items():
        q = q.is_(column, "null") if value is None else q.eq(column, value)
    rows = q.execute().data or []
    return rows[0] if rows else None


# ---------------------------------------------------------------- sending

async def send_code(db, tenant_id: str, *, phone: Any, mode: str | None = None, code: str | None = None,
                    ref: str | None = None, origin: str = "api", api_key_id: str | None = None,
                    created_by: str | None = None) -> dict:
    """Create one OTP request and send it. Returns public_view()."""
    cfg = get_settings(db, tenant_id)
    phone = normalize_phone(phone)
    mode = mode or cfg["default_mode"]
    if mode not in MODES:
        raise OtpError(400, "invalid_mode", "mode must be one of: " + ", ".join(MODES))
    if ref is not None:
        ref = str(ref).strip()[:REF_MAX] or None
    source = "client" if code is not None else "anril"
    if source == "client":
        code = str(code).strip()
        if not CLIENT_CODE_RE.fullmatch(code):
            raise OtpError(400, "invalid_code", "code must be 4 to 10 letters or digits")
    else:
        code = generate_code(int(cfg["code_length"]))

    problems = mode_problems(db, tenant_id, mode, cfg)
    if problems:
        raise OtpError(409, "channel_not_ready", problems[0])
    if mode == "sms" and not india_10(phone):
        raise OtpError(400, "sms_india_only", "SMS goes to Indian mobile numbers only. Use WhatsApp for this number.")

    since = _iso(_now() - timedelta(hours=1))
    recent = (db.table("otp_requests").select("id").eq("tenant_id", tenant_id).eq("phone", phone)
              .gte("created_at", since).execute()).data or []
    if len(recent) >= int(cfg["max_per_hour"]):
        raise OtpError(429, "too_many_codes", "Too many codes sent to this number in the last hour. Try again later.")

    now = _now()
    otp_id = str(uuid.uuid4())
    # A new Anril-made code for a number replaces any earlier one that is still open.
    if source == "anril":
        (db.table("otp_requests").update({"status": "expired", "fallback_due_at": None, "pending_code_enc": None})
         .eq("tenant_id", tenant_id).eq("phone", phone).eq("status", "pending").eq("source", "anril").execute())
    row = (db.table("otp_requests").insert({
        "id": otp_id, "tenant_id": tenant_id, "phone": phone, "mode": mode, "source": source,
        "origin": origin, "code_hash": hash_code(otp_id, code) if source == "anril" else None,
        "code_masked": mask_code(code), "ref": ref, "api_key_id": api_key_id, "created_by": created_by,
        "expires_at": _iso(now + timedelta(minutes=int(cfg["expiry_minutes"]))), "created_at": _iso(now),
        "pending_code_enc": _encrypt_code(otp_id, code) if mode == "sms_then_whatsapp" else None,
    }).execute()).data[0]

    if mode == "sms":
        row = await _send_sms(db, tenant_id, row, code, cfg)
    elif mode == "whatsapp":
        row = await _send_whatsapp(db, tenant_id, row, code, cfg)
    elif mode == "both":
        await asyncio.gather(_send_sms(db, tenant_id, row, code, cfg), _send_whatsapp(db, tenant_id, row, code, cfg))
    else:  # sms_then_whatsapp
        if india_10(phone):
            row = await _send_sms(db, tenant_id, row, code, cfg)
        else:
            row = _update(db, otp_id, {"sms_status": "failed", "sms_error": "Not an Indian mobile number"}) or row
        if row.get("sms_status") == "failed":
            await _fallback_now(db, tenant_id, otp_id)
        else:
            wait = int(cfg["fallback_wait_seconds"])
            _update(db, otp_id, {"fallback_due_at": _iso(_now() + timedelta(seconds=wait))})
            _spawn(_fallback_after(tenant_id, otp_id, wait))
    fresh = get_request(db, tenant_id, otp_id) or row
    _maybe_mark_failed(db, tenant_id, fresh)
    return public_view(get_request(db, tenant_id, otp_id) or fresh)


async def _send_sms(db, tenant_id: str, row: dict, code: str, cfg: dict) -> dict:
    mobile = india_10(row["phone"])
    if not mobile:
        patch = {"sms_status": "failed", "sms_error": "Not an Indian mobile number"}
    else:
        try:
            res = await bulk9_client.send_dlt(
                get_setting("bulk9_api_key", tenant_id=tenant_id), sender_id=cfg["sms_sender_id"],
                message_id=str(cfg["sms_message_id"]), numbers=[mobile], variables=[code],
                udf1=f"otp:{row['id']}",
            )
            patch = {"sms_status": "sent", "sms_request_id": str(res.get("request_id") or "")[:64] or None}
        except bulk9_client.Bulk9Error as e:
            patch = {"sms_status": "failed", "sms_error": str(e)[:300]}
        except Exception as e:  # timeout / transport: we can't prove it went
            logger.warning("otp sms send error otp=%s err=%s", row["id"], type(e).__name__)
            patch = {"sms_status": "failed", "sms_error": "SMS service did not answer"}
    # Only from 'none': Bulk9's delivery report can land before this write (seen: 1 s), and
    # must not be overwritten back to 'sent' (that would fire a needless WhatsApp backup).
    updated = _update(db, row["id"], patch, sms_status="none")
    if not updated:
        return get_request(db, tenant_id, row["id"]) or {**row, **patch}
    emit(db, tenant_id, updated, "sms_sent" if patch["sms_status"] == "sent" else "sms_failed")
    return updated


def _wa_components(code: str) -> list[dict]:
    return [
        {"type": "body", "parameters": [{"type": "text", "text": code}]},
        {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]},
    ]


async def _send_whatsapp(db, tenant_id: str, row: dict, code: str, cfg: dict, *, backup: bool = False) -> dict:
    from app.services import meta_cloud
    try:
        res = await meta_cloud.send_template_message(
            row["phone"], cfg["wa_template_name"], cfg["wa_template_language"],
            components=_wa_components(code), tenant_id=tenant_id,
        )
        wamid = ((res.get("messages") or [{}])[0] or {}).get("id")
        patch = {"whatsapp_status": "sent", "whatsapp_message_id": wamid}
    except Exception as e:
        detail = getattr(e, "detail", None) or str(e)
        logger.warning("otp whatsapp send failed otp=%s err=%s", row["id"], str(detail)[:200])
        patch = {"whatsapp_status": "failed", "whatsapp_error": _meta_error_text(detail)}
    updated = _update(db, row["id"], patch, whatsapp_status="none")  # same race as _send_sms
    if not updated:
        return get_request(db, tenant_id, row["id"]) or {**row, **patch}
    if patch["whatsapp_status"] == "sent":
        emit(db, tenant_id, updated, "whatsapp_backup_sent" if backup else "whatsapp_sent")
    else:
        emit(db, tenant_id, updated, "whatsapp_failed")
    return updated


def _meta_error_text(detail: Any) -> str:
    try:
        err = json.loads(detail).get("error", {}) if isinstance(detail, str) else {}
        text = err.get("error_user_msg") or err.get("message")
        if text:
            return str(text)[:300]
    except (ValueError, AttributeError):
        pass
    return "WhatsApp did not accept the message"


# ---------------------------------------------------------------- SMS-then-WhatsApp backup

async def _fallback_after(tenant_id: str, otp_id: str, wait: int) -> None:
    await asyncio.sleep(wait)
    try:
        await _fallback_now(get_supabase(), tenant_id, otp_id)
    except Exception as e:
        logger.error("otp fallback timer failed otp=%s err=%s", otp_id, type(e).__name__)


async def _fallback_now(db, tenant_id: str, otp_id: str) -> bool:
    """Sends the WhatsApp backup once. The claim is one conditional UPDATE, so the timer, the
    sweep job and a 'failed' SMS report can race and still only one of them sends."""
    claimed = (db.table("otp_requests").update({"fallback_sent_at": _iso(_now())})
               .eq("id", otp_id).eq("tenant_id", tenant_id).eq("mode", "sms_then_whatsapp")
               .eq("status", "pending").is_("fallback_sent_at", "null").neq("sms_status", "delivered")
               .execute()).data or []
    if not claimed:
        return False
    row = claimed[0]
    code = _decrypt_code(otp_id, row.get("pending_code_enc"))
    _update(db, otp_id, {"pending_code_enc": None, "fallback_due_at": None})
    if not code:
        patch = {"whatsapp_status": "failed", "whatsapp_error": "Backup could not be sent"}
        row = _update(db, otp_id, patch) or {**row, **patch}
        emit(db, tenant_id, row, "whatsapp_failed")
    else:
        cfg = get_settings(db, tenant_id)
        if whatsapp_problem(tenant_id, cfg):
            patch = {"whatsapp_status": "failed", "whatsapp_error": whatsapp_problem(tenant_id, cfg)}
            row = _update(db, otp_id, patch) or {**row, **patch}
            emit(db, tenant_id, row, "whatsapp_failed")
        else:
            row = await _send_whatsapp(db, tenant_id, row, code, cfg, backup=True)
    _maybe_mark_failed(db, tenant_id, get_request(db, tenant_id, otp_id) or row)
    return True


def _maybe_mark_failed(db, tenant_id: str, row: dict) -> None:
    """Every channel that was tried failed, and no backup is still due -> the request failed."""
    if row.get("status") != "pending":
        return
    used = [s for s in (row.get("sms_status"), row.get("whatsapp_status")) if s and s != "none"]
    backup_due = row.get("mode") == "sms_then_whatsapp" and not row.get("fallback_sent_at")
    if used and all(s == "failed" for s in used) and not backup_due:
        updated = _update(db, row["id"], {"status": "failed", "pending_code_enc": None, "fallback_due_at": None},
                          status="pending")
        if updated:
            emit(db, tenant_id, updated, "failed")


# ---------------------------------------------------------------- delivery reports

def apply_sms_report(db, tenant_id: str, otp_id: str, status: str | None, reason: str | None = None) -> bool:
    """Bulk9 SMS callback whose udf1 is 'otp:<id>'. status: delivered | failed | submitted."""
    row = get_request(db, tenant_id, otp_id)
    if not row:
        return False
    if status not in ("delivered", "failed"):
        return True
    if _SMS_RANK[status] <= _SMS_RANK.get(row.get("sms_status") or "none", 0):
        return True
    if status == "delivered":
        patch: dict = {"sms_status": "delivered", "sms_error": None}
        if not row.get("fallback_sent_at"):  # SMS arrived in time: the backup is no longer needed
            patch.update({"fallback_due_at": None, "pending_code_enc": None})
        updated = _update(db, otp_id, patch) or {**row, **patch}
        emit(db, tenant_id, updated, "sms_delivered")
        return True
    patch = {"sms_status": "failed", "sms_error": (reason or "SMS not delivered")[:300]}
    if row["mode"] == "sms_then_whatsapp" and not row.get("fallback_sent_at"):
        patch["fallback_due_at"] = _iso(_now())  # due now: the sweep sends it if the spawn below can't
    updated = _update(db, otp_id, patch) or {**row, **patch}
    emit(db, tenant_id, updated, "sms_failed")
    if row["mode"] == "sms_then_whatsapp" and not row.get("fallback_sent_at"):
        _spawn(_fallback_now(get_supabase(), tenant_id, otp_id))
    else:
        _maybe_mark_failed(db, tenant_id, updated)
    return True


def apply_whatsapp_statuses(db, tenant_id: str, statuses: list) -> None:
    """Meta delivery receipts for OTP messages (the rest are ignored here)."""
    ids = [s.get("id") for s in statuses if s.get("id") and s.get("status") in ("delivered", "read", "failed")]
    if not ids:
        return
    rows = (db.table("otp_requests").select("*").eq("tenant_id", tenant_id)
            .in_("whatsapp_message_id", ids).execute()).data or []
    by_wamid = {r["whatsapp_message_id"]: r for r in rows}
    for s in statuses:
        row = by_wamid.get(s.get("id"))
        status = s.get("status")
        if not row or status not in _WA_RANK:
            continue
        current = row.get("whatsapp_status") or "none"
        if _WA_RANK[status] <= _WA_RANK.get(current, 0):
            continue
        patch: dict = {"whatsapp_status": status}
        if status == "failed":
            err = (s.get("errors") or [{}])[0] or {}
            patch["whatsapp_error"] = str(err.get("title") or err.get("message") or "Not delivered")[:300]
        updated = _update(db, row["id"], patch) or {**row, **patch}
        by_wamid[s.get("id")] = updated
        emit(db, tenant_id, updated, f"whatsapp_{status}")
        if status == "failed":
            _maybe_mark_failed(db, tenant_id, updated)


def handle_not_requested(db, tenant_id: str, *, phone: str, context_wamid: str | None) -> bool:
    """The customer tapped WhatsApp's 'I didn't request a code' button. The code is cancelled
    (verify answers not_requested) and the client's server is told."""
    row = None
    if context_wamid:
        rows = (db.table("otp_requests").select("*").eq("tenant_id", tenant_id)
                .eq("whatsapp_message_id", context_wamid).limit(1).execute()).data or []
        row = rows[0] if rows else None
    if not row:
        try:
            digits = normalize_phone(phone)
        except OtpError:
            return False
        since = _iso(_now() - VERIFY_BY_PHONE_WINDOW)
        rows = (db.table("otp_requests").select("*").eq("tenant_id", tenant_id).eq("phone", digits)
                .neq("whatsapp_status", "none").gte("created_at", since)
                .order("created_at", desc=True).limit(1).execute()).data or []
        row = rows[0] if rows else None
    if not row or row.get("not_requested_at"):
        return bool(row)
    patch: dict = {"not_requested_at": _iso(_now()), "fallback_due_at": None, "pending_code_enc": None}
    if row["status"] == "pending":
        patch["status"] = "not_requested"
    updated = _update(db, row["id"], patch) or {**row, **patch}
    emit(db, tenant_id, updated, "not_requested")
    return True


# ---------------------------------------------------------------- verify

def verify(db, tenant_id: str, *, code: Any, otp_id: str | None = None, phone: Any = None) -> dict:
    code = str(code or "").strip()
    if not CLIENT_CODE_RE.fullmatch(code):
        raise OtpError(400, "invalid_code", "code must be 4 to 10 letters or digits")
    row = None
    if otp_id:
        row = get_request(db, tenant_id, otp_id)
    elif phone:
        digits = normalize_phone(phone)
        since = _iso(_now() - VERIFY_BY_PHONE_WINDOW)
        rows = (db.table("otp_requests").select("*").eq("tenant_id", tenant_id).eq("phone", digits)
                .eq("source", "anril").gte("created_at", since)
                .order("created_at", desc=True).limit(1).execute()).data or []
        row = rows[0] if rows else None
    else:
        raise OtpError(400, "missing_target", "Send otp_id (or phone)")
    if not row:
        raise OtpError(404, "not_found", "No code found for this request")
    if row["source"] != "anril":
        raise OtpError(409, "not_checkable", "This code was made by your server, so your server checks it")
    # Read now, not at send time: a saved change also applies to codes still open.
    max_attempts = int(get_settings(db, tenant_id)["max_attempts"])
    result = (db.rpc("otp_try_code", {
        "p_tenant": tenant_id, "p_id": row["id"], "p_hash": hash_code(row["id"], code),
        "p_max_attempts": max_attempts,
    }).execute()).data
    if isinstance(result, list):
        result = result[0] if result else None
    fresh = get_request(db, tenant_id, row["id"]) or row
    if result in ("verified", "locked", "expired"):
        emit(db, tenant_id, fresh, result)
    reasons = {
        "verified": None, "already_verified": "This code was already used",
        "wrong_code": "Wrong code", "locked": "Too many wrong tries. Send a new code.",
        "expired": "This code has expired. Send a new code.",
        "not_requested": "The customer said they didn't ask for this code",
        "failed": "This code was never delivered", "not_found": "No code found for this request",
    }
    return {
        "verified": result == "verified",
        "reason": result if result != "verified" else None,
        "message": reasons.get(result, "Could not check the code"),
        "attempts_left": max(0, max_attempts - int(fresh.get("attempts") or 0)) if fresh.get("status") == "pending" else 0,
        "otp_id": row["id"],
    }


# ---------------------------------------------------------------- status updates (webhooks)

def _event_payload(row: dict, event: str, event_id: str) -> dict:
    view = public_view(row)
    return {
        "id": event_id, "event": event, "at": _iso(_now()),
        "otp_id": view["otp_id"], "ref": view["ref"], "phone": view["phone"], "mode": view["mode"],
        "source": view["source"], "status": view["status"],
        "sms": view["sms"]["status"], "whatsapp": view["whatsapp"]["status"],
        "whatsapp_backup_sent": view["whatsapp_backup_sent"],
    }


def emit(db, tenant_id: str, row: dict, event: str) -> None:
    """Queue one status update for the tenant's status URL (if they set one). Best-effort:
    a failure here must never break a send or a verify."""
    try:
        cfg = get_settings(db, tenant_id)
        if not cfg.get("status_webhook_url"):
            return
        event_id = "evt_" + secrets.token_hex(12)
        db.table("otp_status_events").insert({
            "tenant_id": tenant_id, "otp_id": row["id"], "event": event,
            "payload": _event_payload(row, event, event_id),
        }).execute()
        _spawn(deliver_due_events(get_supabase(), tenant_id=tenant_id))
    except Exception as e:
        logger.warning("otp status event not queued otp=%s event=%s err=%s", row.get("id"), event, type(e).__name__)


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    """X-Anril-Signature = 'v1=' + hex(HMAC-SHA256(secret, f'{timestamp}.{body}'))."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"v1={mac}"


def _blocked_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
            or addr.is_reserved or addr.is_unspecified or not addr.is_global)


def check_webhook_url(url: str) -> None:
    """Shape check when the URL is saved: https, a real host name, no credentials, and not an
    address inside a private network. Resolved again before every delivery."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or len(url) > 500:
        raise OtpError(400, "invalid_webhook_url", "Status URL must be a full https:// address")
    host = parts.hostname
    try:
        if _blocked_ip(host):
            raise OtpError(400, "invalid_webhook_url", "Status URL can't point to a private address")
    except ValueError:  # not an IP literal: a name
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            raise OtpError(400, "invalid_webhook_url", "Status URL can't point to a private address")


async def _resolves_public(host: str, port: int) -> bool:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(infos) and not any(_blocked_ip(info[4][0]) for info in infos)


async def _post_event(url: str, secret: str, event: dict) -> str | None:
    """Returns None on success, else a short error text."""
    try:
        check_webhook_url(url)
    except OtpError as e:
        return e.message
    parts = urlsplit(url)
    if not await _resolves_public(parts.hostname, parts.port or 443):
        return "Status URL does not resolve to a public address"
    body = json.dumps(event["payload"], separators=(",", ":")).encode()
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json", "User-Agent": "Anril-OTP-Webhooks/1",
        "X-Anril-Event": event["event"], "X-Anril-Delivery": event["payload"].get("id", ""),
        "X-Anril-Timestamp": str(ts), "X-Anril-Signature": sign_payload(secret, ts, body),
    }
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT, follow_redirects=False) as client:
            resp = await client.post(url, content=body, headers=headers)
    except httpx.HTTPError as e:
        return f"Could not reach the status URL ({type(e).__name__})"
    if 200 <= resp.status_code < 300:
        return None
    return f"Status URL answered HTTP {resp.status_code}"


async def deliver_due_events(db, *, tenant_id: str | None = None, limit: int = 50) -> dict:
    stats = {"delivered": 0, "retry": 0, "failed": 0}
    q = (db.table("otp_status_events").select("*").eq("status", "pending")
         .lte("next_attempt_at", _iso(_now())).order("id").limit(limit))
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    events = q.execute().data or []
    for ev in events:
        attempts = int(ev.get("attempts") or 0)
        # Claim: bump attempts only if nobody else did, and push next_attempt_at out as a lease.
        claimed = (db.table("otp_status_events").update({
            "attempts": attempts + 1, "next_attempt_at": _iso(_now() + timedelta(seconds=120)),
        }).eq("id", ev["id"]).eq("attempts", attempts).eq("status", "pending").execute()).data or []
        if not claimed:
            continue
        cfg = get_settings(db, ev["tenant_id"])
        url, secret = cfg.get("status_webhook_url"), _webhook_secret(db, ev["tenant_id"])
        error = "No status URL set" if not url else ("No signing secret set" if not secret else None)
        if not error:
            error = await _post_event(url, secret, ev)
        if error is None:
            db.table("otp_status_events").update({"status": "delivered", "delivered_at": _iso(_now()),
                                                   "last_error": None}).eq("id", ev["id"]).execute()
            stats["delivered"] += 1
        elif attempts + 1 >= WEBHOOK_MAX_ATTEMPTS:
            db.table("otp_status_events").update({"status": "failed", "last_error": error[:300]}).eq("id", ev["id"]).execute()
            stats["failed"] += 1
        else:
            delay = WEBHOOK_BACKOFF_SECONDS[attempts]
            db.table("otp_status_events").update({
                "last_error": error[:300], "next_attempt_at": _iso(_now() + timedelta(seconds=delay)),
            }).eq("id", ev["id"]).execute()
            stats["retry"] += 1
    return stats


# ---------------------------------------------------------------- the once-a-minute sweep

async def sweep(db=None, *, limit: int = 200) -> dict:
    """Safety net for what the in-process timers may have missed (restart, deploy):
    overdue WhatsApp backups, codes that expired unused, and status updates due a retry."""
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    db = db or get_supabase()
    now_iso = _iso(_now())
    stats = {"backups": 0, "expired": 0}
    due = (db.table("otp_requests").select("id, tenant_id").eq("status", "pending")
           .is_("fallback_sent_at", "null").lte("fallback_due_at", now_iso).limit(limit).execute()).data or []
    for r in due:
        if await _fallback_now(db, r["tenant_id"], r["id"]):
            stats["backups"] += 1
    stale = (db.table("otp_requests").select("*").eq("status", "pending").lte("expires_at", now_iso)
             .limit(limit).execute()).data or []
    for r in stale:
        updated = _update(db, r["id"], {"status": "expired", "fallback_due_at": None, "pending_code_enc": None},
                          status="pending")
        if updated:
            stats["expired"] += 1
            emit(db, r["tenant_id"], updated, "expired")
    stats.update(await deliver_due_events(db))
    return stats


# ---------------------------------------------------------------- dashboard summaries

def history(db, tenant_id: str, *, limit: int = 50, before: str | None = None) -> list[dict]:
    q = (db.table("otp_requests").select("*").eq("tenant_id", tenant_id)
         .order("created_at", desc=True).limit(min(max(limit, 1), 200)))
    if before:
        q = q.lt("created_at", before)
    return [history_view(r) for r in (q.execute().data or [])]


def not_requested_count(db, tenant_id: str, days: int = 7) -> int:
    since = _iso(_now() - timedelta(days=days))
    rows = (db.table("otp_requests").select("id").eq("tenant_id", tenant_id)
            .gte("not_requested_at", since).execute()).data or []
    return len(rows)


def failed_webhook_count(db, tenant_id: str, days: int = 7) -> int:
    since = _iso(_now() - timedelta(days=days))
    rows = (db.table("otp_status_events").select("id").eq("tenant_id", tenant_id).eq("status", "failed")
            .gte("created_at", since).execute()).data or []
    return len(rows)

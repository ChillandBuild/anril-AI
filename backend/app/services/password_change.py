"""v9.2 #27 First sign-in: the owner swaps the password the Anril team gave them for their own.

Done on the server so the "must change password" flag (app_metadata, which the person cannot edit) is
cleared only when a new password was really set: the given password is checked first, then the new
one is saved and the flag cleared in one admin update. Nothing here logs a password or an email."""
import logging

import httpx

from app.config import settings
from app.db.supabase import get_supabase
from app.routes.auto_messages import _SlidingWindow

logger = logging.getLogger(__name__)

MIN_LEN, MAX_LEN = 8, 72
TRIES_PER_15_MIN = 5
_tries = _SlidingWindow(TRIES_PER_15_MIN, 900)


class PasswordChangeError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check_new(current: str, new: str) -> None:
    if not current:
        raise PasswordChangeError("Type the password you were given")
    if len(new or "") < MIN_LEN:
        raise PasswordChangeError(f"Use at least {MIN_LEN} characters")
    if len(new) > MAX_LEN:
        raise PasswordChangeError(f"Use at most {MAX_LEN} characters")
    if new == current:
        raise PasswordChangeError("The new password must be different from the old one")


def _given_password_is_right(email: str, password: str) -> bool:
    """Sign in once with the given password (then end that extra session). True when it is correct."""
    base = settings.supabase_url.rstrip("/")
    key = settings.supabase_service_key
    try:
        res = httpx.post(f"{base}/auth/v1/token?grant_type=password", headers={"apikey": key},
                         json={"email": email, "password": password}, timeout=10)
    except httpx.HTTPError as e:
        logger.warning("password_change: sign-in check failed (%s)", type(e).__name__)
        raise PasswordChangeError("Could not check the password just now. Please try again.", 503)
    if res.status_code != 200:
        return False
    token = (res.json() or {}).get("access_token")
    if token:
        try:
            httpx.post(f"{base}/auth/v1/logout?scope=local", headers={"apikey": key, "Authorization": f"Bearer {token}"},
                       timeout=10)
        except httpx.HTTPError:
            pass
    return True


def change_first_password(user_id: str, email: str, current: str, new: str) -> None:
    check_new(current, new)
    if not user_id or not email:
        raise PasswordChangeError("Please sign in again.", 401)
    if not _tries.allow(user_id):
        raise PasswordChangeError("Too many tries. Wait 15 minutes and try again.", 429)
    if not _given_password_is_right(email, current):
        raise PasswordChangeError("The password you were given is not right")
    get_supabase().auth.admin.update_user_by_id(user_id, {
        "password": new,
        "app_metadata": {"must_change_password": False},
        "user_metadata": {"must_change_password": False},
    })

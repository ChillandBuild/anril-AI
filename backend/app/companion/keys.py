"""Secret keys and signed user ids for the companion chat API (migration 250).

Two ways in, one key:
- **Server to server.** The business's server sends "Authorization: Bearer acs_live_...".
  We hash the key and look the hash up; the full key is never stored.
- **Web widget.** The browser never sees the key. The business's server signs the user id:

      signing_key = sha256_hex(secret_key)            # the same value we store
      signature   = hmac_sha256_hex(signing_key, f"{exp}.{user_id}")

  and hands user_id, exp and signature to the page. We recompute the signature with each
  active key's stored hash. Example: Karthik (user 48213) opens Astrotamil; their server
  signs "1767225600.48213"; the widget sends those three values with every message; someone
  who changes the user id to 48214 fails the check.
"""
import hashlib
import hmac
import re
import secrets
import time

KEY_PREFIX = "acs_live_"
KEY_DISPLAY_LEN = len(KEY_PREFIX) + 4        # "acs_live_Ab3x" is what the dashboard shows
MAX_KEY_LEN = 100
MAX_ACTIVE_KEYS = 2                          # rotate with no downtime: new key, swap, revoke old
MAX_SIGNATURE_LIFETIME = 30 * 24 * 3600      # an exp further out than this is refused
OWNER_TEST_PREFIX = "owner-test:"            # the dashboard test chat's people; never a real user

# The client's own user id. Letters, digits and _ . @ : - ; up to 128 characters.
USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:\-]{0,127}$")
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """(full key, display prefix, hash). The full key is returned to the owner once."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:KEY_DISPLAY_LEN], hash_key(raw)


def looks_like_key(raw: str | None) -> bool:
    return bool(raw) and raw.startswith(KEY_PREFIX) and len(raw) <= MAX_KEY_LEN


def valid_user_id(user_id: str) -> bool:
    return bool(USER_ID_RE.fullmatch(user_id)) and not user_id.startswith(OWNER_TEST_PREFIX)


def sign_user(key_hash: str, user_id: str, exp: int) -> str:
    """What the business's server computes (key_hash = sha256 hex of its secret key)."""
    return hmac.new(key_hash.encode(), f"{exp}.{user_id}".encode(), hashlib.sha256).hexdigest()


def check_signature(key_hashes: list[tuple[str, str]], user_id: str, exp: int, signature: str,
                    now: float | None = None) -> str | None:
    """The id of the active key that signed this user id, or None (bad, expired or too long-lived)."""
    now = time.time() if now is None else now
    if not (now < exp <= now + MAX_SIGNATURE_LIFETIME):
        return None
    signature = (signature or "").lower()
    if not _SIGNATURE_RE.fullmatch(signature) or not valid_user_id(user_id):
        return None
    for key_id, key_hash in key_hashes:
        if hmac.compare_digest(sign_user(key_hash, user_id, exp), signature):
            return key_id
    return None

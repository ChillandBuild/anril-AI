"""The tenant's own business identity (legal name, address, GSTIN) and its GST
pricing convention. Printed on the monthly sales export so the auditor's file
belongs to the client, never to Anril.

Stored as one JSON blob in app_settings under key "business_details", same
shape as intake_config (services/intake.py get_intake_config). Not to be confused with services/business_profile.py, which is the AI prompt's description sections."""
import json
import logging
import re

from app.db.supabase import get_supabase
from app.services.bill_number_format import clean_prefix

logger = logging.getLogger(__name__)

SETTING_KEY = "business_details"
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
UPI_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9.-]{1,63}$")
ACCOUNT_NO_RE = re.compile(r"^[0-9]{5,20}$")
STATE_CODE_RE = re.compile(r"^[0-9]{2}$")
TEXT_FIELDS = ("legal_name", "address", "city", "state", "pincode", "gstin", "email", "phone")
GST_TYPES = ("regular", "composition", "none")

# New in v9.2 (Business details & bills). Same JSON blob, so no new table.
BILL_FIELDS = (
    "bill_name", "state_code", "gst_type", "pan", "bill_prefix", "licence_number", "terms", "upi_id",
    "bank_account_name", "bank_name", "bank_ifsc", "bank_account_number",
)
# Set only by the picture upload routes, never by the save form.
IMAGE_FIELDS = ("logo_path", "signature_path")
# What the save form may write.
EDITABLE_FIELDS = TEXT_FIELDS + BILL_FIELDS + ("prices_include_gst",)
MAX_LEN = {
    "legal_name": 200, "address": 400, "city": 100, "state": 100, "pincode": 12, "email": 200, "phone": 32,
    "bill_name": 120, "licence_number": 60, "terms": 1000, "bank_account_name": 120, "bank_name": 120,
}


class BusinessDetailsError(ValueError):
    """A value the owner typed that we can't accept; the message is plain English."""


def _defaults(tenant_id: str, db) -> dict:
    """Seed from what onboarding already collected, so a tenant who never opens
    Business details still gets their own name on the export."""
    profile = {field: "" for field in TEXT_FIELDS + BILL_FIELDS + IMAGE_FIELDS}
    profile["gst_type"] = "regular"
    profile["prices_include_gst"] = True
    try:
        tenant = (
            db.table("tenants").select("name, contact_phone").eq("id", tenant_id).maybe_single().execute()
        )
        if tenant and tenant.data:
            profile["legal_name"] = tenant.data.get("name") or ""
            profile["phone"] = tenant.data.get("contact_phone") or ""
    except Exception as e:
        logger.warning(f"business_details: tenant lookup failed for {tenant_id}: {e}")
    return profile


def get_business_details(tenant_id: str, db=None) -> dict:
    db = db or get_supabase()
    profile = _defaults(tenant_id, db)
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", SETTING_KEY)
        .maybe_single()
        .execute()
    )
    if row and row.data and row.data.get("value"):
        try:
            stored = json.loads(row.data["value"])
            profile.update({k: v for k, v in stored.items() if k in profile and v is not None})
        except (TypeError, ValueError):
            logger.warning(f"business_details: unparseable value for tenant {tenant_id}")
    return profile


def save_business_details(tenant_id: str, profile: dict, db=None) -> dict:
    """Raises on write failure -- unlike config_dynamic.save_setting, which only
    logs, because the owner must know their auditor details weren't saved."""
    db = db or get_supabase()
    db.table("app_settings").upsert(
        {"key": SETTING_KEY, "value": json.dumps(profile), "tenant_id": tenant_id, "is_secret": True},
        on_conflict="tenant_id,key",
    ).execute()
    return profile


def mask_account_number(number: str) -> str:
    number = str(number or "")
    return f"••••{number[-4:]}" if number else ""


def view_for(profile: dict, can_manage: bool) -> dict:
    """The profile as it is sent to the screen: picture paths are internal (the route adds links),
    and the bank account number shows only its last 4 digits unless the viewer can manage settings."""
    out = {k: v for k, v in profile.items() if k not in IMAGE_FIELDS}
    out["has_logo"] = bool(profile.get("logo_path"))
    out["has_signature"] = bool(profile.get("signature_path"))
    if not can_manage:
        out["bank_account_number"] = mask_account_number(out.get("bank_account_number", ""))
    return out


def clean_update(existing: dict, incoming: dict) -> dict:
    """The saved profile after applying what the owner sent. Only fields that were sent change, so
    an older screen that doesn't know the new fields can't blank them. Raises BusinessDetailsError."""
    merged = dict(existing)
    for key in EDITABLE_FIELDS:
        if key not in incoming or incoming[key] is None:
            continue
        value = incoming[key]
        if key == "prices_include_gst":
            merged[key] = bool(value)
            continue
        value = str(value).strip()
        if key in ("gstin", "pan", "bank_ifsc"):
            value = value.upper().replace(" ", "")
        if len(value) > MAX_LEN.get(key, 400):
            raise BusinessDetailsError(f"That is too long (most {MAX_LEN.get(key, 400)} characters)")
        if key == "bank_account_number":
            value = value.replace(" ", "")
            if value.startswith("•"):  # the masked copy the screen was shown: keep what is saved
                continue
        merged[key] = value

    if merged["gstin"] and not GSTIN_RE.match(merged["gstin"]):
        raise BusinessDetailsError("GSTIN doesn't look right — it should be 15 characters like 33ABCDE1234F1Z5")
    if merged["pan"] and not PAN_RE.match(merged["pan"]):
        raise BusinessDetailsError("PAN doesn't look right — it should be like ABCDE1234F")
    if merged["bank_ifsc"] and not IFSC_RE.match(merged["bank_ifsc"]):
        raise BusinessDetailsError("IFSC doesn't look right — it should be like SBIN0001234")
    if merged["upi_id"] and not UPI_RE.match(merged["upi_id"]):
        raise BusinessDetailsError("UPI ID doesn't look right — it should be like shopname@upi")
    if merged["bank_account_number"] and not ACCOUNT_NO_RE.match(merged["bank_account_number"]):
        raise BusinessDetailsError("Account number should be digits only (5 to 20 digits)")
    if merged["state_code"] and not STATE_CODE_RE.match(merged["state_code"]):
        raise BusinessDetailsError("State code is two digits, like 33 for Tamil Nadu")
    if merged["gst_type"] not in GST_TYPES:
        raise BusinessDetailsError("Pick Registered, Composition or Not registered")
    try:
        merged["bill_prefix"] = clean_prefix(merged["bill_prefix"])
    except ValueError as e:
        raise BusinessDetailsError(str(e)) from None
    return merged


# ── logo and signature pictures ──────────────────────────────────────────────

BRAND_BUCKET = "business-brand"  # private; read through a short signed link (migration 325)
MAX_IMAGE_BYTES = 1024 * 1024
IMAGE_KINDS = {"logo": "logo_path", "signature": "signature_path"}
_IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp"}


def _image_ext(content: bytes, mime: str) -> str:
    ext = _IMAGE_TYPES.get((mime or "").lower().split(";")[0].strip())
    if not ext:
        raise BusinessDetailsError("Add a PNG, JPG or WEBP picture.")
    if not content:
        raise BusinessDetailsError("That picture is empty.")
    if len(content) > MAX_IMAGE_BYTES:
        raise BusinessDetailsError("The picture must be under 1 MB.")
    ok = (
        (ext == "png" and content.startswith(b"\x89PNG"))
        or (ext == "jpg" and content.startswith(b"\xff\xd8"))
        or (ext == "webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
    )
    if not ok:
        raise BusinessDetailsError("That file isn't a real picture.")
    return ext


def save_brand_image(tenant_id: str, kind: str, content: bytes, mime: str, db=None) -> dict:
    """Stores the logo or signature and remembers where. Returns the saved profile."""
    if kind not in IMAGE_KINDS:
        raise BusinessDetailsError("Unknown picture.")
    ext = _image_ext(content, mime)
    db = db or get_supabase()
    profile = get_business_details(tenant_id, db)
    old = profile.get(IMAGE_KINDS[kind])
    path = f"{tenant_id}/{kind}.{ext}"
    try:
        db.storage.from_(BRAND_BUCKET).upload(path, content, {"content-type": _mime_for(ext), "upsert": "true"})
    except Exception as e:
        logger.error(f"business_details: {kind} upload failed for {tenant_id}: {e}")
        raise BusinessDetailsError("Couldn't save the picture right now — please try again later.") from None
    if old and old != path:
        _remove_quietly(db, old)
    profile[IMAGE_KINDS[kind]] = path
    return save_business_details(tenant_id, profile, db)


def remove_brand_image(tenant_id: str, kind: str, db=None) -> dict:
    if kind not in IMAGE_KINDS:
        raise BusinessDetailsError("Unknown picture.")
    db = db or get_supabase()
    profile = get_business_details(tenant_id, db)
    old = profile.get(IMAGE_KINDS[kind])
    if old:
        _remove_quietly(db, old)
    profile[IMAGE_KINDS[kind]] = ""
    return save_business_details(tenant_id, profile, db)


def brand_image_url(profile: dict, kind: str, db=None, seconds: int = 3600) -> str | None:
    """A short-lived link to the stored picture, or None when there is none (or it can't be read)."""
    path = profile.get(IMAGE_KINDS[kind])
    if not path:
        return None
    try:
        signed = (db or get_supabase()).storage.from_(BRAND_BUCKET).create_signed_url(path, seconds)
        return signed.get("signedURL") or signed.get("signedUrl") or None
    except Exception as e:
        logger.warning(f"business_details: no link for {kind}: {e}")
        return None


def _mime_for(ext: str) -> str:
    return {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[ext]


def _remove_quietly(db, path: str) -> None:
    try:
        db.storage.from_(BRAND_BUCKET).remove([path])
    except Exception as e:
        logger.warning(f"business_details: couldn't remove old picture {path}: {e}")


def charges_gst(tenant_id: str, db=None) -> bool:
    """False for a composition shop or one not registered for GST: its bills add and show no tax (Bill of supply).
    Anything unreadable keeps the old behaviour (GST)."""
    try:
        return (get_business_details(tenant_id, db).get("gst_type") or "regular") not in ("composition", "none")
    except Exception as e:
        logger.warning(f"business_details: defaulting charges_gst for {tenant_id}: {e}")
        return True


def prices_include_gst(tenant_id: str, db=None) -> bool:
    try:
        return bool(get_business_details(tenant_id, db).get("prices_include_gst", True))
    except Exception as e:
        logger.warning(f"business_details: defaulting prices_include_gst for {tenant_id}: {e}")
        return True

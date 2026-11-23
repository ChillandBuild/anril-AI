"""How a bill number is written. Today: 2026-27/0045. When the owner sets a bill prefix (say DS):
DS/26-27/0045. The counter itself (restarts every April) lives in the next_invoice_number function and
is not touched here. Credit notes (CN/...) are formatted elsewhere and are unchanged."""
import logging
import re

logger = logging.getLogger(__name__)

PREFIX_RE = re.compile(r"^[A-Z0-9]{1,6}$")


def clean_prefix(raw) -> str:
    """The prefix as it will be stored: trimmed, capital letters. '' means no prefix. Raises
    ValueError (plain English) when it isn't A-Z / 0-9, up to 6 characters."""
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if not PREFIX_RE.match(text):
        raise ValueError("Bill prefix can have only letters and numbers, up to 6 characters (for example DS)")
    return text


def format_number(prefix: str, fy: str, n: int) -> str:
    """fy is the financial year as '2026-27'. No prefix -> exactly '2026-27/0045'."""
    if not prefix:
        return f"{fy}/{n:04d}"
    return f"{prefix}/{fy[2:]}/{n:04d}"


def format_bill_number(db, tenant_id: str, fy: str, n: int) -> str:
    """The bill number for counter value n in financial year fy. Never raises: if the shop's
    settings can't be read, the bill still gets the default number rather than losing a sale."""
    prefix = ""
    try:
        from app.services.business_details import get_business_details
        prefix = (get_business_details(tenant_id, db) or {}).get("bill_prefix") or ""
        prefix = prefix if PREFIX_RE.match(prefix) else ""
    except Exception as e:
        logger.warning(f"bill_number_format: using the default number for {tenant_id}: {e}")
    return format_number(prefix, fy, n)

"""What a shop prints on its bill besides the items: logo, signature, PAN, licence number, UPI ID,
bank details, terms, and the "Bill of supply" title of a composition-scheme shop.

orders.public_bill() calls decorate() once, so the customer's page, the WhatsApp picture and the
PDF all read the same data. A shop that set none of these gets a bill that looks exactly as before:
every new key is empty and the files draw nothing for an empty key.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

COMPOSITION_TITLE = "Bill of supply"
COMPOSITION_NOTE = "Composition taxable person, not eligible to collect tax on supplies."


def is_composition(business: dict) -> bool:
    return (business.get("gst_type") or "regular") == "composition"


def brand_block(db, tenant_id: str, business: dict) -> dict:
    """The printable extras, from Settings > Business details & bills. Pictures are short-lived
    signed links (the pictures live in a private bucket). Never raises."""
    from app.services.business_details import brand_image_url

    def text(key: str) -> str:
        return str(business.get(key) or "").strip()

    out = {
        "pan": text("pan"),
        "licence_number": text("licence_number"),
        "upi_id": text("upi_id"),
        "terms": text("terms"),
        "bank": {
            "account_name": text("bank_account_name"),
            "bank_name": text("bank_name"),
            "ifsc": text("bank_ifsc"),
            "account_number": text("bank_account_number"),
        },
        "logo_url": None,
        "signature_url": None,
    }
    try:
        if business.get("logo_path"):
            out["logo_url"] = brand_image_url(business, "logo", db)
        if business.get("signature_path"):
            out["signature_url"] = brand_image_url(business, "signature", db)
    except Exception as e:
        logger.warning("bill brand pictures for %s unavailable: %s", tenant_id, e)
    return out


def has_bank(brand: dict) -> bool:
    bank = brand.get("bank") or {}
    return bool(bank.get("account_number") or bank.get("bank_name") or bank.get("ifsc"))


def bank_lines(brand: dict) -> list[str]:
    """"HDFC Bank · A/c name · A/c no. 1234 · IFSC HDFC0001234", split into short lines."""
    bank = brand.get("bank") or {}
    out = []
    if bank.get("bank_name") or bank.get("account_name"):
        out.append(" · ".join(p for p in (bank.get("bank_name"), bank.get("account_name")) if p))
    detail = " · ".join(p for p in (
        f"A/c no. {bank['account_number']}" if bank.get("account_number") else "",
        f"IFSC {bank['ifsc']}" if bank.get("ifsc") else "",
    ) if p)
    if detail:
        out.append(detail)
    return out


def has_pay_block(brand: dict) -> bool:
    return bool(brand.get("upi_id") or has_bank(brand))


def decorate(bill: dict, db, tenant_id: str, business: dict) -> dict:
    """Adds `brand` (always). The tax handling follows the ORDER's own stored bill_type (set when it was
    made), never the shop's GST setting today: a "gst" order always prints as the tax invoice it was, even
    if the shop has since gone composition. A "simple" order (made while the shop charged no tax) gets the
    "Bill of supply" title when the shop is still a composition shop (an unregistered shop keeps "Bill"),
    with every tax figure zero. A regular shop's deliberate simple bill keeps its old look. Everything else is left alone."""
    bill["brand"] = brand_block(db, tenant_id, business)
    if (bill.get("bill_type") or "gst") != "simple":
        return bill
    gst_type = business.get("gst_type") or "regular"
    if gst_type not in ("composition", "none"):
        return bill
    if gst_type == "composition":
        bill["title"] = COMPOSITION_TITLE  # only a composition shop issues a "Bill of supply"
        bill["composition"] = True  # the PDF/picture add the composition note and show the shop's GSTIN
    # An unregistered shop keeps the plain "Bill" title (no title key), with no tax figures.
    bill["gst_paise"] = bill["cgst_paise"] = bill["sgst_paise"] = bill["igst_paise"] = 0
    for line in bill.get("lines") or []:
        line["gst_rate"] = None
    return bill

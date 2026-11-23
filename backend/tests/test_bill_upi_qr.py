"""The UPI QR on a bill: the link a payment app opens, the QR picture, and when the bill shows one
(only while money is still owed, never on a paid or cancelled bill)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import bill_files


def _bill_with_upi(**extra):
    bill = bill_files.sample_bill()
    bill["brand"] = {"upi_id": "demo.silks@upi"}
    return {**bill, **extra}


def _unpaid(**extra):
    return _bill_with_upi(**{"paid_paise": 0, "balance_paise": 380000, "methods": [], **extra})


# ── the link and the picture ───────────────────────────────────────────────────

def test_a_valid_upi_id_makes_a_png():
    png = bill_files.upi_qr_png("demo.silks@upi", "Demo Silks", 245000)
    assert png is not None and png[:4] == b"\x89PNG"


@pytest.mark.parametrize("upi_id", ["", "   ", None])
def test_no_upi_id_means_no_qr(upi_id):
    assert bill_files.upi_qr_png(upi_id, "Demo Silks", 245000) is None


def test_the_link_carries_the_amount_only_when_something_is_due():
    link = bill_files.upi_link("demo.silks@upi", "Demo Silks", 245000)
    assert link.startswith("upi://pay?pa=demo.silks@upi&pn=Demo%20Silks&cu=INR")
    assert "&am=2450.00" in link
    assert "am=" not in bill_files.upi_link("demo.silks@upi", "Demo Silks", 0)
    assert "am=" not in bill_files.upi_link("demo.silks@upi", "Demo Silks", None)


def test_amount_is_the_balance_still_owed():
    assert bill_files.amount_due_paise(_unpaid()) == 380000
    assert bill_files.amount_due_paise(_unpaid(paid_paise=300000, balance_paise=80000)) == 80000
    assert bill_files.amount_due_paise(_bill_with_upi()) == 0  # paid in full
    assert bill_files.amount_due_paise(_unpaid(cancelled=True)) == 0


def test_a_paid_bill_gets_no_qr_but_keeps_the_upi_text():
    paid = _bill_with_upi()
    assert bill_files._upi_qr_for(paid, paid["brand"], paid["business"]) == (0, None)
    assert bill_files.bill_png(paid)[:4] == b"\x89PNG"


# ── the files ──────────────────────────────────────────────────────────────────

def test_the_picture_with_a_balance_still_renders():
    png = bill_files.bill_png(_unpaid())
    assert png[:4] == b"\x89PNG"


def test_the_picture_with_upi_but_no_balance_renders():
    assert bill_files.bill_png(_bill_with_upi())[:4] == b"\x89PNG"


def test_the_pdf_with_a_balance_and_without_renders():
    pytest.importorskip("fpdf")  # fpdf2 is in requirements.txt; skip only where it is not installed
    assert bill_files.invoice_pdf(_unpaid())[:5] == b"%PDF-"
    assert bill_files.invoice_pdf(_bill_with_upi())[:5] == b"%PDF-"

"""The bill as files a WhatsApp message can carry.

  - bill_png:    a receipt picture for a simple bill (the image header of anril_bill_picture)
  - invoice_pdf: the tax invoice PDF for a GST bill (the document header of anril_bill_pdf)

Both are drawn from orders.public_bill(), the same data the customer's bill page shows,
so the picture, the PDF and the page always agree. Noto Sans is bundled because the
server has no font with the ₹ sign.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.deals import _rupees

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"
REGULAR = FONTS / "NotoSans-Regular.ttf"
BOLD = FONTS / "NotoSans-Bold.ttf"
IST = timezone(timedelta(hours=5, minutes=30))
MAX_LINES = 14  # more than this and the picture says "+ N more items"

INK = (17, 27, 33)
SUB = (102, 119, 129)
RULE = (207, 214, 218)
GREEN = (11, 127, 122)
AMBER = (154, 91, 0)
RED = (180, 35, 24)


def _when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        at = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)[:10]
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    at = at.astimezone(IST)
    return f"{at.day} {at.strftime('%b')}, {at.strftime('%I:%M %p').lstrip('0')}"


def _place(business: dict) -> str:
    return ", ".join(p for p in (business.get("city") or "", business.get("state") or "") if p) or (business.get("address") or "")


def _item_label(line: dict) -> str:
    name = line.get("name") or "Item"
    if line.get("variant"):
        name += f" ({line['variant']})"
    return f"{name} × {line.get('qty') or 1}"


def bill_number(bill: dict) -> str:
    return bill.get("invoice_number") or bill.get("order_label") or ""


def paid_line(bill: dict) -> tuple[str, str, str]:
    """(label, amount, tone) for the line under the total."""
    if bill.get("cancelled"):
        return "Cancelled", "", "red"
    paid, balance = int(bill.get("paid_paise") or 0), int(bill.get("balance_paise") or 0)
    methods = " + ".join(bill.get("methods") or [])
    if paid and not balance:
        return f"Paid{f' · {methods}' if methods else ''}", f"{_rupees(paid)} ✓", "green"
    if paid:
        return f"Paid {_rupees(paid)}{f' · {methods}' if methods else ''}", f"Balance {_rupees(balance)}", "amber"
    return "To pay", _rupees(balance or int(bill.get("total_paise") or 0)), "amber"


# ── the receipt picture ────────────────────────────────────────────────────────

def bill_png(bill: dict) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    width, pad = 900, 56
    f = {
        "shop": ImageFont.truetype(str(BOLD), 44),
        "sub": ImageFont.truetype(str(REGULAR), 26),
        "row": ImageFont.truetype(str(REGULAR), 31),
        "total": ImageFont.truetype(str(BOLD), 36),
        "small": ImageFont.truetype(str(REGULAR), 27),
    }
    img = Image.new("RGB", (width, 3000), "white")
    d = ImageDraw.Draw(img)
    y = pad

    def centre(text: str, font, fill, gap: int) -> None:
        nonlocal y
        text = _fit(d, text, font, width - 2 * pad)
        w = d.textlength(text, font=font)
        d.text(((width - w) / 2, y), text, font=font, fill=fill)
        y += gap

    def row(left: str, right: str, font, fill=INK, right_fill=None, gap: int = 50) -> None:
        nonlocal y
        rw = d.textlength(right, font=font)
        left = _fit(d, left, font, width - 2 * pad - rw - 24)
        d.text((pad, y), left, font=font, fill=fill)
        d.text((width - pad - rw, y), right, font=font, fill=right_fill or fill)
        y += gap

    def dashed() -> None:
        nonlocal y
        y += 10
        x = pad
        while x < width - pad:
            d.line([(x, y), (min(x + 12, width - pad), y)], fill=RULE, width=2)
            x += 22
        y += 28

    business = bill.get("business") or {}
    centre(business.get("legal_name") or "Bill", f["shop"], INK, 64)
    place = " · ".join(p for p in (_place(business), business.get("phone") or "") if p)
    if place:
        centre(place, f["sub"], SUB, 40)
    centre(f"Bill {bill_number(bill)} · {_when(bill.get('invoice_date'))}".strip(" ·"), f["sub"], SUB, 40)
    dashed()

    lines = bill.get("lines") or []
    for line in lines[:MAX_LINES]:
        row(_item_label(line), _rupees(int(line.get("amount_paise") or 0)), f["row"])
    if len(lines) > MAX_LINES:
        rest = sum(int(li.get("amount_paise") or 0) for li in lines[MAX_LINES:])
        row(f"+ {len(lines) - MAX_LINES} more items", _rupees(rest), f["row"], fill=SUB)
    if int(bill.get("discount_paise") or 0):
        row("Discount", f"− {_rupees(int(bill['discount_paise']))}", f["row"])
    if bill.get("bill_type") == "gst" and int(bill.get("gst_paise") or 0):
        label = "Includes GST" if bill.get("prices_include_gst") else "GST"
        row(label, _rupees(int(bill["gst_paise"])), f["small"], fill=SUB, gap=44)
    if int(bill.get("refunded_paise") or 0):
        row("Refunded", f"− {_rupees(int(bill['refunded_paise']))}", f["row"])
    dashed()

    row("Total", _rupees(int(bill.get("total_paise") or 0)), f["total"], gap=58)
    label, amount, tone = paid_line(bill)
    colour = {"green": GREEN, "amber": AMBER, "red": RED}[tone]
    if amount.endswith("✓"):
        # Noto Sans has no ✓; draw the tick.
        amount = amount[:-2]
        rw = d.textlength(amount, font=f["row"])
        _tick(d, width - pad - 26, y + 8, colour)
        d.text((width - pad - 40 - rw, y), amount, font=f["row"], fill=colour)
        d.text((pad, y), label, font=f["row"], fill=colour)
        y += 50
    else:
        row(label, amount, f["row"], fill=colour)
    y += pad - 20

    img = img.crop((0, 0, width, y))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _tick(d, x: float, y: float, colour) -> None:
    d.line([(x, y + 13), (x + 9, y + 22), (x + 26, y)], fill=colour, width=4, joint="curve")


def _fit(d, text: str, font, max_width: float) -> str:
    if d.textlength(text, font=font) <= max_width:
        return text
    while text and d.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


# ── the tax invoice PDF ────────────────────────────────────────────────────────

def invoice_pdf(bill: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("Noto", "", str(REGULAR))
    pdf.add_font("Noto", "B", str(BOLD))
    pdf.set_title(f"Invoice {bill_number(bill)}")
    pdf.add_page()
    left, right = 16, 194
    pdf.set_left_margin(left)
    pdf.set_right_margin(210 - right)
    business = bill.get("business") or {}
    customer = bill.get("customer") or {}
    is_gst = bill.get("bill_type") == "gst"

    # Seller (left) and invoice details (right)
    top = 16
    pdf.set_xy(left, top)
    pdf.set_font("Noto", "B", 16)
    pdf.cell(110, 8, business.get("legal_name") or "Bill", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", "", 9)
    pdf.set_text_color(90, 100, 110)
    address = ", ".join(p for p in (business.get("address"), business.get("city"), business.get("state"), business.get("pincode")) if p)
    if address:
        pdf.multi_cell(105, 4.6, address, new_x="LMARGIN", new_y="NEXT")
    contact = " · ".join(p for p in (business.get("phone"), business.get("email")) if p)
    if contact:
        pdf.cell(105, 4.6, contact, new_x="LMARGIN", new_y="NEXT")
    if is_gst and business.get("gstin"):
        pdf.set_text_color(40, 50, 60)
        pdf.set_font("Noto", "B", 9)
        pdf.cell(105, 5, f"GSTIN {business['gstin']}", new_x="LMARGIN", new_y="NEXT")
    seller_bottom = pdf.get_y()

    pdf.set_text_color(150, 160, 170)
    pdf.set_font("Noto", "B", 8)
    pdf.set_xy(130, top)
    pdf.cell(right - 130, 5, "TAX INVOICE" if is_gst else "BILL", align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(17, 27, 33)
    pdf.set_font("Noto", "B", 13)
    pdf.cell(right - 130, 7, bill_number(bill), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_font("Noto", "", 9)
    pdf.set_text_color(90, 100, 110)
    pdf.cell(right - 130, 5, f"{_when(bill.get('invoice_date'))} · Order {bill.get('order_label') or ''}", align="R",
             new_x="LEFT", new_y="NEXT")
    if bill.get("cancelled"):
        pdf.set_text_color(*RED)
        pdf.set_font("Noto", "B", 9)
        pdf.cell(right - 130, 5, "Cancelled", align="R", new_x="LEFT", new_y="NEXT")

    y = max(seller_bottom, pdf.get_y()) + 4
    pdf.set_draw_color(220, 226, 230)
    pdf.line(left, y, right, y)

    # Billed to
    pdf.set_xy(left, y + 4)
    pdf.set_text_color(150, 160, 170)
    pdf.set_font("Noto", "B", 8)
    pdf.cell(0, 5, "BILLED TO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(17, 27, 33)
    pdf.set_font("Noto", "B", 10.5)
    pdf.cell(0, 5.5, customer.get("business") or customer.get("name") or "Customer", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", "", 9)
    pdf.set_text_color(90, 100, 110)
    if customer.get("business") and customer.get("name"):
        pdf.cell(0, 4.6, customer["name"], new_x="LMARGIN", new_y="NEXT")
    if customer.get("phone"):
        pdf.cell(0, 4.6, customer["phone"], new_x="LMARGIN", new_y="NEXT")
    if customer.get("gstin"):
        pdf.set_font("Noto", "B", 9)
        pdf.set_text_color(40, 50, 60)
        pdf.cell(0, 4.6, f"GSTIN {customer['gstin']}", new_x="LMARGIN", new_y="NEXT")

    # Items
    pdf.ln(4)
    cols = [("Item", 86, "L"), ("Qty", 16, "R"), ("Rate", 28, "R")] + ([("GST", 18, "R")] if is_gst else []) + [("Amount", 0, "R")]
    widths = [w for _, w, _ in cols]
    widths[-1] = (right - left) - sum(widths[:-1])
    pdf.set_draw_color(220, 226, 230)
    pdf.set_font("Noto", "B", 8)
    pdf.set_text_color(150, 160, 170)
    pdf.cell(0, 0, "", border="T", new_x="LMARGIN", new_y="NEXT")
    for (label, _, align), w in zip(cols, widths):
        pdf.cell(w, 8, label.upper(), align=align)
    pdf.ln(8)
    pdf.cell(0, 0, "", border="T", new_x="LMARGIN", new_y="NEXT")
    for line in bill.get("lines") or []:
        name = line.get("name") or "Item"
        if line.get("variant"):
            name += f" · {line['variant']}"
        values = [name, str(line.get("qty") or 1), _rupees(int(line.get("unit_price_paise") or 0))]
        if is_gst:
            values.append(f"{line['gst_rate']:g}%" if line.get("gst_rate") is not None else "-")
        values.append(_rupees(int(line.get("amount_paise") or 0)))
        pdf.set_text_color(17, 27, 33)
        for i, ((_, _, align), w, value) in enumerate(zip(cols, widths, values)):
            pdf.set_font("Noto", "B" if i in (0, len(values) - 1) else "", 9.5)
            text = value
            while i == 0 and pdf.get_string_width(text) > w - 2 and len(text) > 1:
                text = text[:-1]
            if text != value:
                text = text.rstrip() + "…"
            pdf.cell(w, 8, text, align=align)
        pdf.ln(8)
        pdf.set_draw_color(240, 243, 245)
        pdf.cell(0, 0, "", border="T", new_x="LMARGIN", new_y="NEXT")

    # Totals
    pdf.ln(3)
    box_x, box_w = right - 76, 76

    def total_row(label: str, value: str, *, bold: bool = False, colour=(60, 70, 80), size: float = 9.5) -> None:
        pdf.set_x(box_x)
        pdf.set_font("Noto", "B" if bold else "", size)
        pdf.set_text_color(*colour)
        pdf.cell(box_w / 2, 6, label)
        pdf.cell(box_w / 2, 6, value, align="R", new_x="LMARGIN", new_y="NEXT")

    total_row("Items", _rupees(int(bill.get("subtotal_paise") or 0)))
    if int(bill.get("discount_paise") or 0):
        total_row("Discount", f"− {_rupees(int(bill['discount_paise']))}")
    gst = int(bill.get("gst_paise") or 0)
    if is_gst and gst:
        inc = " (included)" if bill.get("prices_include_gst") else ""
        if int(bill.get("igst_paise") or 0):
            total_row(f"IGST{inc}", _rupees(int(bill["igst_paise"])), size=8.5, colour=(110, 120, 130))
        else:
            total_row(f"CGST{inc}", _rupees(int(bill.get("cgst_paise") or 0)), size=8.5, colour=(110, 120, 130))
            total_row(f"SGST{inc}", _rupees(int(bill.get("sgst_paise") or 0)), size=8.5, colour=(110, 120, 130))
    pdf.set_draw_color(220, 226, 230)
    pdf.line(box_x, pdf.get_y() + 1, right, pdf.get_y() + 1)
    pdf.ln(2)
    total_row("Total", _rupees(int(bill.get("total_paise") or 0)), bold=True, colour=INK, size=12)
    paid, balance = int(bill.get("paid_paise") or 0), int(bill.get("balance_paise") or 0)
    if 0 < paid < int(bill.get("total_paise") or 0):
        total_row("Paid", _rupees(paid))
    if int(bill.get("refunded_paise") or 0):
        total_row("Refunded", f"− {_rupees(int(bill['refunded_paise']))}")
    if balance and not bill.get("cancelled"):
        total_row("Balance to pay", _rupees(balance), bold=True, colour=AMBER)
    elif paid and not balance:
        total_row("", "Paid in full · thank you", bold=True, colour=GREEN, size=8.5)

    pdf.ln(12)
    pdf.set_font("Noto", "", 8)
    pdf.set_text_color(150, 160, 170)
    note = "This is a computer-made tax invoice." if is_gst else "Thank you for shopping with us."
    pdf.cell(0, 5, f"{note} Made with Anril.", align="C")
    return bytes(pdf.output())


def pdf_filename(bill: dict) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in bill_number(bill)) or "bill"
    return f"Invoice {safe}.pdf"


# ── a sample, for the template Meta reviews ───────────────────────────────────

def sample_bill(shop: str = "Demo Silks", bill_type: str = "simple") -> dict:
    """Meta needs an example file with every media template. Shop's own name, made-up lines."""
    lines = [
        {"name": "Green silk saree", "variant": None, "qty": 1, "unit_price_paise": 245000, "gst_rate": 5, "amount_paise": 245000},
        {"name": "Cotton kurti", "variant": None, "qty": 2, "unit_price_paise": 65000, "gst_rate": 5, "amount_paise": 130000},
        {"name": "Gift box", "variant": None, "qty": 1, "unit_price_paise": 15000, "gst_rate": 18, "amount_paise": 15000},
    ]
    return {
        "business": {"legal_name": shop, "address": "", "city": "Coimbatore", "state": "Tamil Nadu", "pincode": "",
                     "gstin": "33ABCDE1234F1Z5" if bill_type == "gst" else "", "phone": "", "email": ""},
        "bill_type": bill_type, "invoice_number": "2026-27/0045", "invoice_date": "2026-11-15T05:50:00+00:00",
        "order_label": "D-1045", "customer": {"name": "Kavitha", "phone": "98•• ••210", "business": None, "gstin": None},
        "lines": lines, "subtotal_paise": 390000, "discount_paise": 10000, "gst_paise": 19600 if bill_type == "gst" else 0,
        "cgst_paise": 9800 if bill_type == "gst" else 0, "sgst_paise": 9800 if bill_type == "gst" else 0, "igst_paise": 0,
        "prices_include_gst": True, "total_paise": 380000, "paid_paise": 380000, "balance_paise": 0, "cancelled": False,
        "refunded_paise": 0, "methods": ["UPI"],
    }


def purchase_order_pdf(po: dict, business: dict) -> bytes:
    """The purchase order the supplier gets (PO-0043.pdf): who orders, what, how many, at what cost, by when."""
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("Noto", "", str(REGULAR))
    pdf.add_font("Noto", "B", str(BOLD))
    pdf.set_title(f"Purchase order {po['po_number']}")
    pdf.add_page()
    left, right = 16, 194
    pdf.set_left_margin(left)
    pdf.set_right_margin(210 - right)
    pdf.set_font("Noto", "B", 16)
    pdf.cell(110, 8, business.get("legal_name") or "Purchase order", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", "", 9)
    pdf.set_text_color(90, 100, 110)
    address = ", ".join(p for p in (business.get("address"), business.get("city"), business.get("state"), business.get("pincode")) if p)
    if address:
        pdf.multi_cell(105, 4.6, address, new_x="LMARGIN", new_y="NEXT")
    for extra in (business.get("phone"), f"GSTIN {business['gstin']}" if business.get("gstin") else None):
        if extra:
            pdf.cell(105, 4.6, extra, new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(130, 16)
    pdf.set_text_color(15, 23, 42)
    pdf.set_font("Noto", "B", 13)
    pdf.cell(64, 7, "PURCHASE ORDER", align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_font("Noto", "", 10)
    pdf.cell(64, 5.5, po["po_number"], align="R", new_x="LEFT", new_y="NEXT")
    created = str(po.get("created_at") or "")[:10]
    if created:
        pdf.cell(64, 5.5, f"Date: {datetime.fromisoformat(created).strftime('%d %b %Y')}", align="R", new_x="LEFT", new_y="NEXT")
    if po.get("need_by"):
        pdf.cell(64, 5.5, f"Need by: {datetime.fromisoformat(str(po['need_by'])).strftime('%d %b %Y')}", align="R",
                 new_x="LEFT", new_y="NEXT")
    supplier = po.get("supplier") or {}
    pdf.set_xy(left, max(pdf.get_y(), 44) + 4)
    pdf.set_font("Noto", "B", 10)
    pdf.cell(0, 5.5, "To", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", "", 10)
    pdf.cell(0, 5.5, supplier.get("name") or "", new_x="LMARGIN", new_y="NEXT")
    if supplier.get("gstin"):
        pdf.cell(0, 5.5, f"GSTIN {supplier['gstin']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    widths = (88, 20, 28, 16, 26)
    pdf.set_font("Noto", "B", 9)
    pdf.set_fill_color(241, 245, 249)
    for w, head, align in zip(widths, ("Item", "Qty", "Cost each", "GST", "Amount"), ("L", "R", "R", "R", "R")):
        pdf.cell(w, 7, head, border="B", align=align, fill=True)
    pdf.ln()
    pdf.set_font("Noto", "", 9.5)
    for li in po.get("lines") or []:
        amount = int(li["unit_cost_paise"]) * int(li["qty_ordered"])
        pdf.cell(widths[0], 7, str(li["label"])[:60])
        pdf.cell(widths[1], 7, str(li["qty_ordered"]), align="R")
        pdf.cell(widths[2], 7, _rupees(int(li["unit_cost_paise"])), align="R")
        pdf.cell(widths[3], 7, f"{float(li.get('gst_rate') or 0):g}%", align="R")
        pdf.cell(widths[4], 7, _rupees(amount), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Noto", "", 10)
    for label, paise in (("Items", int(po.get("items_paise") or 0)), ("GST", int(po.get("gst_paise") or 0))):
        pdf.cell(sum(widths[:4]), 6, label, align="R")
        pdf.cell(widths[4], 6, _rupees(paise), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", "B", 11)
    pdf.cell(sum(widths[:4]), 7, "Total", align="R")
    pdf.cell(widths[4], 7, _rupees(int(po.get("total_paise") or 0)), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Noto", "", 9)
    pdf.set_text_color(90, 100, 110)
    pdf.multi_cell(0, 4.6, "Please confirm on WhatsApp, or tell us if the date doesn't work. Quote this PO number on your bill.")
    return bytes(pdf.output())

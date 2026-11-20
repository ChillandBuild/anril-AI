"""The bill on WhatsApp with the file on top: a receipt picture for a simple bill, the tax
invoice PDF for a GST bill (services/bill_files.py + orders._send_bill_file)."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import bill_files, orders
from tests.test_orders import T, _connected, _deal, _lead, db  # noqa: F401  (db is the fixture)

TOKEN = "tok_abcdefghijklmnopqr"


def run(coro):
    return asyncio.run(coro)


def _bill_deal(db, bill_type="simple", **extra):
    _deal(db, **{"lead_id": "L1", "stage": "won", "bill_token": TOKEN, "invoice_number": "2026-27/0045",
                 "total_paise": 380000, "paid_paise": 380000, "discount_paise": 10000, "bill_type": bill_type,
                 "gst_paise": 0, **extra})
    db.add("deal_items", tenant_id=T, deal_id="d1", name="Green silk saree", variant_label=None, qty=1,
           unit_price_paise=245000, gst_rate=5)
    db.add("deal_items", tenant_id=T, deal_id="d1", name="Cotton kurti", variant_label=None, qty=2,
           unit_price_paise=67500, gst_rate=5)
    db.rows("deal_payments").append({"tenant_id": T, "deal_id": "d1", "amount_paise": 380000, "method": "upi"})


# ── the files ───────────────────────────────────────────────────────────────────

def test_the_picture_and_the_pdf_are_real_files():
    png = bill_files.bill_png(bill_files.sample_bill())
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = bill_files.invoice_pdf(bill_files.sample_bill(bill_type="gst"))
    assert pdf[:5] == b"%PDF-" and len(pdf) < 200_000


def test_the_line_under_the_total_says_paid_balance_or_cancelled():
    paid = bill_files.sample_bill()
    assert bill_files.paid_line(paid) == ("Paid · UPI", "₹3,800 ✓", "green")
    part = {**paid, "paid_paise": 300000, "balance_paise": 80000, "methods": ["Cash", "UPI"]}
    assert bill_files.paid_line(part) == ("Paid ₹3,000 · Cash + UPI", "Balance ₹800", "amber")
    assert bill_files.paid_line({**paid, "cancelled": True})[2] == "red"


def test_a_long_bill_still_makes_one_picture():
    bill = bill_files.sample_bill()
    bill["lines"] = bill["lines"] * 10  # 30 lines: the picture shows 14 and "+ 16 more items"
    assert bill_files.bill_png(bill)[:4] == b"\x89PNG"


def test_public_bill_lists_how_it_was_paid(db):
    _lead(db)
    _bill_deal(db)
    assert orders.public_bill(db, TOKEN)["methods"] == ["UPI"]
    data, content_type, name = orders.bill_file(db, TOKEN)
    assert content_type == "image/png" and name == "Bill 2026-27-0045.png"


# ── sending ─────────────────────────────────────────────────────────────────────

def _meta(sid="wamid.9"):
    return {
        "upload": AsyncMock(return_value="media-1"),
        "media": AsyncMock(return_value={"messages": [{"id": sid}]}),
        "template": AsyncMock(return_value={"messages": [{"id": sid}]}),
    }


def _patched(m, approved=None):
    rows = approved or []
    return (
        patch("app.config_dynamic.get_setting", side_effect=_connected),
        patch("app.services.meta_cloud.upload_media_to_meta", m["upload"]),
        patch("app.services.meta_cloud.send_media_message", m["media"]),
        patch("app.services.meta_cloud.send_template_message", m["template"]),
        patch.object(orders, "_approved_media_template", side_effect=lambda db, t, name: next((r for r in rows if r["name"] == name), None)),
        patch("app.services.call_details_share._approved_templates", return_value=[]),
    )


def test_inside_24_hours_the_bill_goes_as_a_picture_with_the_message(db):
    _lead(db, inbound_hours_ago=2)
    _bill_deal(db)
    m = _meta()
    p = _patched(m)
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        out = run(orders.notify(db, T, "d1", "bill"))
    assert (out["sent"], out["via"]) == (True, "text")
    assert m["upload"].await_args.args[1] == "image/png"
    kwargs = m["media"].await_args.kwargs
    assert kwargs["wa_type"] == "image" and "Your bill 2026-27/0045" in kwargs["caption"]
    msg = db.rows("messages")[0]
    assert msg["media_type"] == "image" and msg["media_url"].endswith(f"/public/bills/{TOKEN}/picture.png")


def test_outside_24_hours_a_gst_bill_goes_as_the_pdf_template(db):
    _lead(db, inbound_hours_ago=48)
    _bill_deal(db, bill_type="gst")
    m = _meta()
    p = _patched(m, approved=[{"id": "tp", "name": "anril_bill_pdf", "language": "en"}])
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        out = run(orders.notify(db, T, "d1", "bill"))
    assert (out["sent"], out["via"]) == (True, "template")
    assert m["template"].await_args.args[1] == "anril_bill_pdf"
    header, body, button = m["template"].await_args.kwargs["components"]
    assert header["parameters"][0]["type"] == "document"
    assert header["parameters"][0]["document"] == {"id": "media-1", "filename": "Invoice 2026-27-0045.pdf"}
    assert [v["text"] for v in body["parameters"]] == ["Revathi", "2026-27/0045", "our shop", "₹3,800"]
    assert button["sub_type"] == "url" and button["parameters"][0]["text"] == TOKEN
    assert "Your GST invoice 2026-27/0045" in out["text"] and out["text"].endswith("Again vaanga!")
    m["media"].assert_not_awaited()


def test_a_part_paid_bill_says_the_balance_in_the_template(db):
    _lead(db, inbound_hours_ago=48)
    _bill_deal(db, paid_paise=300000, stage="awaiting_payment")
    m = _meta()
    p = _patched(m, approved=[{"id": "tb", "name": "anril_bill_picture", "language": "en"}])
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        run(orders.notify(db, T, "d1", "bill"))
    body = m["template"].await_args.kwargs["components"][1]
    assert body["parameters"][3]["text"] == "₹3,800 (paid ₹3,000, balance ₹800)"


def test_without_the_picture_template_the_old_text_bill_still_goes(db):
    _lead(db, inbound_hours_ago=48)
    _bill_deal(db)
    m = _meta()
    text_template = {"id": "tt", "name": "anril_order_bill", "body_text": orders.ORDER_TEMPLATES["bill"]["body"]}
    p = _patched(m)
    with p[0], p[1], p[2], p[3], p[4], patch("app.services.call_details_share._approved_templates", return_value=[text_template]):
        out = run(orders.notify(db, T, "d1", "bill"))
    assert (out["sent"], out["via"]) == (True, "template")
    assert m["template"].await_args.args[1] == "anril_order_bill"
    m["upload"].assert_not_awaited()  # no file made when it can't be sent


def test_if_the_upload_fails_the_text_bill_goes_instead(db):
    _lead(db, inbound_hours_ago=2)
    _bill_deal(db)
    m = _meta()
    m["upload"].side_effect = RuntimeError("Meta down")
    p = _patched(m)
    with p[0], p[1], p[2], p[3], p[4], p[5], \
         patch("app.services.ai_reply.send_whatsapp", AsyncMock(return_value="wamid.t")) as text:
        out = run(orders.notify(db, T, "d1", "bill"))
    assert (out["sent"], out["via"]) == (True, "text")
    text.assert_awaited_once()
    assert "media_type" not in db.rows("messages")[0]


# ── the templates the owner submits ─────────────────────────────────────────────

def test_the_bill_templates_carry_a_file_header_footer_and_view_bill_button(db):
    from app.routes import orders as route
    created = []

    async def fake_create(payload, tenant_id, _ctx):
        created.append(payload)

    statuses = [{"key": k, "name": t["name"], "body": t["body"], "status": "MISSING" if k.startswith("bill_") else "APPROVED"}
                for k, t in orders.ORDER_TEMPLATES.items()]
    with patch("app.routes.orders.get_supabase", return_value=db), \
         patch.object(route, "_template_status", return_value=statuses), \
         patch.object(route, "_sample_header_handle", AsyncMock(side_effect=lambda db, t, spec: f"4::{spec['header']}")), \
         patch("app.routes.templates.create_template", fake_create):
        out = run(route.submit_order_templates({"tenant_id": T}))
    assert out["problems"] == []
    by_name = {p.name: p for p in created}
    assert set(by_name) == {"anril_bill_picture", "anril_bill_pdf"}
    pic = by_name["anril_bill_picture"]
    assert (pic.header_media_type, pic.header_media_url, pic.footer_text) == ("IMAGE", "4::IMAGE", "Again vaanga!")
    button = pic.buttons[0]
    assert (button.type, button.text) == ("URL", "View bill") and button.url.endswith("/bill/{{1}}")
    assert by_name["anril_bill_pdf"].header_media_type == "DOCUMENT"

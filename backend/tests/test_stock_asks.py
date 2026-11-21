"""Asked but out of stock (migration 305, services/stock_asks.py): the AI and staff note who asked,
the tab counts people and sales missed, and Mark back in stock tells each person once."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services import ai_reply, deal_actions, stock_asks
from tests.fake_supabase import FakeSupabase

T = "tenant-1"
ITEM, OUT_ITEM = "10000000-0000-0000-0000-000000000001", "10000000-0000-0000-0000-000000000002"
RED_XL, RED_M = "20000000-0000-0000-0000-000000000001", "20000000-0000-0000-0000-000000000002"
NOW = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
LEADS = {
    "near": ("30000000-0000-0000-0000-000000000001", "Meena Kumar", NOW - timedelta(hours=2)),  # inside 24 h
    "far": ("30000000-0000-0000-0000-000000000002", "Ravi", NOW - timedelta(days=5)),
    "quiet": ("30000000-0000-0000-0000-000000000003", None, NOW - timedelta(days=9)),
}


@pytest.fixture
def db(monkeypatch):
    db = FakeSupabase()
    db.table("catalog_items").insert({"id": ITEM, "tenant_id": T, "name": "Kanchi pattu", "price_paise": 1050000,
                                      "stock_quantity": 3, "item_type": "product", "status": "ready"}).execute()
    db.table("catalog_items").insert({"id": OUT_ITEM, "tenant_id": T, "name": "Wedding set", "price_paise": 1550000,
                                      "stock_quantity": 0, "item_type": "product", "status": "ready"}).execute()
    db.table("catalog_item_variants").insert({"id": RED_XL, "tenant_id": T, "catalog_item_id": ITEM, "colour": "Red",
                                              "size": "XL", "stock_quantity": 0, "price_paise": None}).execute()
    db.table("catalog_item_variants").insert({"id": RED_M, "tenant_id": T, "catalog_item_id": ITEM, "colour": "Red",
                                              "size": "M", "stock_quantity": 3, "price_paise": 990000}).execute()
    for lead_id, name, last in LEADS.values():
        db.table("leads").insert({"id": lead_id, "tenant_id": T, "name": name, "phone": "9198" + lead_id[-6:],
                                  "last_inbound_at": last.isoformat(), "opted_out": False}).execute()
    settings = {"meta_phone_number_id": "pn", "meta_access_token": "tok", "meta_waba_id": "waba"}
    import app.config_dynamic as config_dynamic
    monkeypatch.setattr(config_dynamic, "get_setting", lambda key, fallback=None, tenant_id=None: settings.get(key, fallback))
    import app.services.orders as orders
    monkeypatch.setattr(orders, "_shop_name", lambda db, tenant_id: "Demo Silks")
    return db


def _lead(key):
    return LEADS[key][0]


class TestAsks:
    def test_asking_again_keeps_one_open_request_and_a_yes_sticks(self, db):
        stock_asks.record_ask(db, T, lead_id=_lead("near"), item_id=ITEM, variant_id=RED_XL, wants_message=True, source="ai")
        stock_asks.record_ask(db, T, lead_id=_lead("near"), item_id=ITEM, variant_id=RED_XL, wants_message=False, source="ai")
        rows = db.rows("stock_waitlist")
        assert len(rows) == 1 and rows[0]["wants_message"] is True and rows[0]["source"] == "ai"
        assert rows[0]["price_paise"] == 1050000  # the size has no own price: the item's

    def test_a_size_that_is_not_on_the_item_is_refused(self, db):
        with pytest.raises(stock_asks.StockAskError):
            stock_asks.record_ask(db, T, lead_id=_lead("near"), item_id=OUT_ITEM, variant_id=RED_XL)

    def test_the_tab_counts_people_sales_missed_and_who_waits(self, db):
        stock_asks.record_ask(db, T, lead_id=_lead("near"), item_id=OUT_ITEM, wants_message=True)
        stock_asks.record_ask(db, T, lead_id=_lead("far"), item_id=OUT_ITEM, wants_message=False)
        stock_asks.record_ask(db, T, lead_id=_lead("far"), item_id=ITEM, variant_id=RED_XL, wants_message=True)
        data = stock_asks.summary(db, T, now=NOW + timedelta(minutes=1))
        assert data["people_asked"] == 2 and data["waiting"] == 2 and data["missed_paise"] == 3100000 + 1050000
        top = data["rows"][0]
        assert (top["name"], top["asked"], top["waiting"], top["in_stock"]) == ("Wedding set", 2, 1, False)
        xl = data["rows"][1]
        assert xl["variant_label"] == "Red · XL" and xl["missed_paise"] == 1050000


class TestBackInStock:
    def _send(self, db, monkeypatch, *, template=False):
        sent = []

        async def fake_text(phone, text, **kw):
            sent.append(("text", phone, text))
            return "wamid.t"

        async def fake_template(db_, tenant_id, phone, tpl, values, payloads):
            sent.append(("template", phone, values))
            return "wamid.p", "filled"

        import app.services.ai_reply as ai
        import app.services.orders as orders
        monkeypatch.setattr(ai, "send_whatsapp", fake_text)
        monkeypatch.setattr(orders, "_send_order_template", fake_template)
        if template:
            db.table("message_templates").insert({"id": "tpl-1", "tenant_id": T, "name": stock_asks.TEMPLATE_NAME,
                                                  "status": "APPROVED", "meta_waba_id": "waba"}).execute()
        return sent

    def test_still_zero_in_stock_is_refused(self, db):
        stock_asks.record_ask(db, T, lead_id=_lead("near"), item_id=OUT_ITEM)
        with pytest.raises(stock_asks.StockAskError):
            asyncio.run(stock_asks.mark_back(db, T, item_id=OUT_ITEM, now=NOW))

    def test_inside_24_hours_a_message_outside_waits_for_the_template(self, db, monkeypatch):
        sent = self._send(db, monkeypatch)
        db.table("catalog_item_variants").update({"stock_quantity": 2}).eq("id", RED_XL).execute()
        for key in ("near", "far"):
            stock_asks.record_ask(db, T, lead_id=_lead(key), item_id=ITEM, variant_id=RED_XL)
        stock_asks.record_ask(db, T, lead_id=_lead("quiet"), item_id=ITEM, variant_id=RED_XL, wants_message=False)

        out = asyncio.run(stock_asks.mark_back(db, T, item_id=ITEM, variant_id=RED_XL, now=NOW))

        assert out == {"sent": 1, "not_reachable": 1, "skipped": 1}
        assert sent[0][0] == "text" and sent[0][2].startswith("Vanakkam Meena, good news from Demo Silks: "
                                                              "Kanchi pattu (Red · XL) is back in stock at ₹10,500.")
        still = [r for r in db.rows("stock_waitlist") if r.get("closed_at") is None]
        assert [r["lead_id"] for r in still] == [_lead("far")]  # pressed again once the template is approved

    def test_outside_24_hours_the_approved_template_goes_and_nobody_is_told_twice(self, db, monkeypatch):
        sent = self._send(db, monkeypatch, template=True)
        db.table("catalog_items").update({"stock_quantity": 4}).eq("id", OUT_ITEM).execute()
        stock_asks.record_ask(db, T, lead_id=_lead("far"), item_id=OUT_ITEM)
        assert asyncio.run(stock_asks.mark_back(db, T, item_id=OUT_ITEM, now=NOW))["sent"] == 1
        assert sent[0] == ("template", "9198" + _lead("far")[-6:], ["Ravi", "Demo Silks", "Wedding set", "₹15,500"])
        assert asyncio.run(stock_asks.mark_back(db, T, item_id=OUT_ITEM, now=NOW))["sent"] == 0

    def test_opted_out_customers_are_never_messaged(self, db, monkeypatch):
        sent = self._send(db, monkeypatch, template=True)
        db.table("leads").update({"opted_out": True}).eq("id", _lead("near")).execute()
        db.table("catalog_items").update({"stock_quantity": 4}).eq("id", OUT_ITEM).execute()
        stock_asks.record_ask(db, T, lead_id=_lead("near"), item_id=OUT_ITEM)
        assert asyncio.run(stock_asks.mark_back(db, T, item_id=OUT_ITEM, now=NOW))["skipped"] == 1 and sent == []


class TestMessage:
    def test_the_four_boxes_must_stay(self):
        assert stock_asks.body_problems(stock_asks.STARTING_BODY["ta"]) == []
        assert stock_asks.body_problems("Hi {{1}}, {{3}} is back") != []
        assert stock_asks.body_problems("{{1}} {{2}} {{3}} {{4}}") != []  # can't start/end with a box

    def test_every_starting_text_is_valid(self):
        assert all(stock_asks.body_problems(b) == [] for b in stock_asks.STARTING_BODY.values())


class TestAi:
    def _items(self):
        return [
            {"id": ITEM, "name": "Kanchi pattu", "item_type": "product", "price_paise": 1050000, "stock_quantity": 3,
             "variants": [{"id": RED_XL, "colour": "Red", "size": "XL", "stock_quantity": 0},
                          {"id": RED_M, "colour": "Red", "size": "M", "stock_quantity": 3}]},
        ]

    def test_the_ai_sees_which_sizes_are_out_and_gets_the_tool(self):
        text, tools, _, _ = ai_reply.catalog_prompt(self._items(), "", {})
        assert "sizes/colours in stock: Red · M (3); OUT now: Red · XL" in text
        assert "note_out_of_stock_request" in [t["function"]["name"] for t in tools]

    def test_no_tool_when_nothing_is_out(self):
        items = self._items()
        items[0]["variants"] = items[0]["variants"][1:]
        _, tools, _, _ = ai_reply.catalog_prompt(items, "", {})
        assert "note_out_of_stock_request" not in [t["function"]["name"] for t in tools]

    def test_the_tool_saves_the_size_and_refuses_one_in_stock(self, db):
        ctx = deal_actions.DealContext(config={}, db=db, lead_id=_lead("near"), tenant_id=T, phone="x",
                                       catalog={ITEM: self._items()[0]})
        turn = deal_actions._Turn()
        assert asyncio.run(deal_actions._note_stock_request(ctx, {"item_id": ITEM, "variant": "red · xl",
                                                                  "wants_message": True}, turn)) is None
        row = db.rows("stock_waitlist")[0]
        assert row["variant_id"] == RED_XL and row["source"] == "ai" and row["wants_message"] is True
        refusal = asyncio.run(deal_actions._note_stock_request(ctx, {"item_id": ITEM, "variant": "Red · M",
                                                                     "wants_message": False}, turn))
        assert "IS in stock" in refusal

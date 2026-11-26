"""WhatsApp Forms Phase 4: live forms. Meta's encryption round trip, the order form's screens
(live price and stock), free booking slots, and a slot that can't be over-booked."""
import asyncio
import base64
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services import form_texts, intake
from app.services import whatsapp_forms as wf
from app.services import whatsapp_live_forms as live
from tests.fake_supabase import FakeSupabase
from tests.test_whatsapp_forms import PHONE, TENANT

LEAD = "11111111-0000-0000-0000-000000000001"
I1, I2, I3, I4 = (f"55555555-0000-0000-0000-00000000000{n}" for n in range(1, 5))
ORDER_ID, BOOK_ID = "33333333-0000-0000-0000-000000000001", "33333333-0000-0000-0000-000000000002"
FORM_1, FORM_2 = "44444444-0000-0000-0000-000000000001", "44444444-0000-0000-0000-000000000002"
FORM_IDS = {ORDER_ID: FORM_1, BOOK_ID: FORM_2}
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=live.IST)  # a Monday, 9 am


def _order(**over):
    d = {"id": ORDER_ID, "name": "Sweets order", "language": "en", "kind": "order", "fields": [], "texts": {},
         "settings": {"max_items": 3, "ask_address": True}}
    return {**d, **over}


def _booking(**over):
    d = {"id": BOOK_ID, "name": "Consultation", "language": "ta", "kind": "booking", "texts": {},
         "fields": [{"key": "full_name", "type": "text", "label": "முழுப் பெயர்", "required": True, "options": []}],
         "settings": {"days_ahead": 3, "slot_minutes": 60, "capacity": 1, "min_notice_minutes": 60,
                      "hours": {"mon": [["10:00", "13:00"]], "tue": [["10:00", "11:00"]]}}}
    return {**d, **over}


@pytest.fixture
def db():
    db = FakeSupabase()
    db.table("tenants").insert({"id": TENANT, "enabled_features": [wf.FEATURE_KEY]}).execute()
    db.table("leads").insert({"id": LEAD, "tenant_id": TENANT, "phone": PHONE, "collected_data": {}}).execute()
    for item in [(I1, "Kaju katli", 60000, 5), (I2, "Mysore pak", 40000, None), (I3, "Sold out", 100, 0),
                 (I4, "No price", None, 3)]:
        db.table("catalog_items").insert({"id": item[0], "tenant_id": TENANT, "name": item[1], "status": "ready",
                                          "price_paise": item[2], "stock_quantity": item[3], "gst_rate": None}).execute()
    for design in (_order(), _booking()):
        db.table("whatsapp_form_designs").insert({**design, "tenant_id": TENANT, "archived": False}).execute()
        flow, answer_map = wf.build_design_flow(design)
        db.table("whatsapp_forms").insert({"id": FORM_IDS[design["id"]], "tenant_id": TENANT, "kind": "custom",
                                           "design_id": design["id"], "name": design["name"], "status": "published",
                                           "meta_flow_id": "9", "source_hash": wf.source_hash(flow),
                                           "definition": flow, "answer_map": answer_map}).execute()
    return db


def _token(form_id):
    return f"wf1.{form_id}.abcdef123456.{'0' * 32}"


# ── encryption: exactly as Meta does it ──────────────────────────────────────

def test_a_request_encrypted_like_meta_decrypts_and_the_reply_decrypts_back():
    public_pem, private_pem = live._new_key_pair()
    public = serialization.load_pem_public_key(public_pem.encode())
    private = serialization.load_pem_private_key(private_pem, password=None)
    aes_key, iv = os.urandom(16), os.urandom(12)
    request = {"action": "ping", "version": "3.0"}
    body = {
        "encrypted_aes_key": base64.b64encode(public.encrypt(aes_key, padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))).decode(),
        "encrypted_flow_data": base64.b64encode(AESGCM(aes_key).encrypt(iv, json.dumps(request).encode(), None)).decode(),
        "initial_vector": base64.b64encode(iv).decode(),
    }
    payload, key, vector = live.decrypt_request(body, [private])
    assert payload == request
    sealed = live.encrypt_response({"data": {"status": "active"}}, key, vector)
    flipped = bytes(b ^ 0xFF for b in iv)
    assert json.loads(AESGCM(aes_key).decrypt(flipped, base64.b64decode(sealed), None)) == {"data": {"status": "active"}}


def test_a_request_for_another_key_gets_421_so_meta_refetches():
    _, other = live._new_key_pair()
    public_pem, _ = live._new_key_pair()
    public = serialization.load_pem_public_key(public_pem.encode())
    body = {"encrypted_aes_key": base64.b64encode(public.encrypt(os.urandom(16), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))).decode(),
        "encrypted_flow_data": base64.b64encode(b"x" * 32).decode(), "initial_vector": base64.b64encode(b"0" * 12).decode()}
    with pytest.raises(live.EndpointError) as err:
        live.decrypt_request(body, [serialization.load_pem_private_key(other, password=None)])
    assert err.value.status == 421


def test_private_keys_are_sealed_at_rest():
    _, private = live._new_key_pair()
    sealed = live._seal(private)
    assert b"PRIVATE KEY" not in sealed.encode() and live._open(sealed) == private


# ── the order form ────────────────────────────────────────────────────────────

class TestOrderForm:
    def test_flow_is_a_live_form_with_every_jump_routed(self):
        flow, _ = wf.build_design_flow(_order())
        assert flow["data_api_version"] == "3.0"
        assert flow["routing_model"] == {"SEARCH": ["PRODUCTS"], "PRODUCTS": ["QUANTITY"], "QUANTITY": ["DELIVERY"],
                                         "DELIVERY": ["SUMMARY"], "SUMMARY": []}
        assert all(c.get("type") != "Dropdown" or c["visible"].startswith("${data.")
                   for s in flow["screens"] for c in s["layout"]["children"])

    def test_without_address_it_goes_straight_to_the_summary(self):
        flow, _ = wf.build_design_flow(_order(settings={"max_items": 2, "ask_address": False}))
        assert flow["routing_model"]["QUANTITY"] == ["SUMMARY"] and "DELIVERY" not in flow["routing_model"]

    def test_opening_lists_only_priced_in_stock_items(self, db):
        reply = live.handle_request(db, TENANT, {"action": "INIT", "flow_token": _token(FORM_1)})
        assert reply["screen"] == "PRODUCTS"
        assert [i["title"] for i in reply["data"]["items"]] == ["Kaju katli", "Mysore pak"]
        assert reply["data"]["items"][0]["description"].endswith("· 5")

    def test_search_finds_by_name_and_says_when_nothing_matches(self, db):
        found = live.handle_request(db, TENANT, {"action": "data_exchange", "screen": "SEARCH",
                                                 "flow_token": _token(FORM_1), "data": {"q": "mysore"}})
        assert [i["id"] for i in found["data"]["items"]] == [I2]
        none = live.handle_request(db, TENANT, {"action": "data_exchange", "screen": "SEARCH",
                                                "flow_token": _token(FORM_1), "data": {"q": "pizza"}})
        assert none["data"]["items"][0]["id"] == "none"

    def test_quantity_choices_never_exceed_stock(self, db):
        reply = live.handle_request(db, TENANT, {"action": "data_exchange", "screen": "PRODUCTS",
                                                 "flow_token": _token(FORM_1), "data": {"items": [I1, I2]}})
        data = reply["data"]
        assert reply["screen"] == "QUANTITY" and data["q1_visible"] and data["q2_visible"] and not data["q3_visible"]
        assert len(data["q1_options"]) == 5 and len(data["q2_options"]) == 20

    def test_summary_shows_live_prices_and_the_total(self, db):
        reply = live.handle_request(db, TENANT, {"action": "data_exchange", "screen": "DELIVERY",
                                                 "flow_token": _token(FORM_1),
                                                 "data": {"lines": json.dumps([{"id": I1, "qty": 2}]),
                                                          "name": "Meena", "address": "12 Anna Nagar"}})
        assert reply["screen"] == "SUMMARY"
        assert "2 × Kaju katli" in reply["data"]["summary"] and "Total: ₹1,200" in reply["data"]["summary"].replace("₹1200", "₹1,200")

    def test_unknown_token_gets_427(self, db):
        with pytest.raises(live.EndpointError) as err:
            live.handle_request(db, TENANT, {"action": "INIT", "flow_token": "unused"})
        assert err.value.status == 427

    def test_ping_is_answered(self, db):
        assert live.handle_request(db, TENANT, {"action": "ping"}) == {"data": {"status": "active"}}


# ── booking ───────────────────────────────────────────────────────────────────

class TestBooking:
    def test_only_open_hours_after_the_notice_are_offered(self, db):
        slots = live.free_slots(db, TENANT, _booking(), date(2026, 11, 23), NOW)
        assert [s.hour for s in slots] == [10, 11, 12]  # 9 am now + 60 min notice
        assert live.free_slots(db, TENANT, _booking(), date(2026, 11, 25), NOW) == []  # Wednesday closed

    def test_shop_open_hours_cut_the_form_slots(self, db):
        # v9.2 #59: the shop opens at 11 on Monday and is shut on Tuesday.
        from app.services import open_hours
        open_hours.save(db, TENANT, {"hours": {"0": [["11:00", "20:00"]], "2": [["10:00", "20:00"]]}})
        assert [s.hour for s in live.free_slots(db, TENANT, _booking(), date(2026, 11, 23), NOW)] == [11, 12]
        assert live.free_slots(db, TENANT, _booking(), date(2026, 11, 24), NOW) == []
        assert live.free_dates(db, TENANT, _booking(), NOW) == [date(2026, 11, 23)]

    def test_dates_in_tamil_and_full_days_left_out(self, db):
        reply = live.handle_request(db, TENANT, {"action": "INIT", "flow_token": _token(FORM_2)}, now=NOW)
        assert [d["id"] for d in reply["data"]["dates"]] == ["2026-11-23", "2026-11-24"]
        assert reply["data"]["dates"][0]["title"].startswith("திங்கள்")

    def test_a_taken_slot_disappears(self, db):
        db.table("whatsapp_form_bookings").insert({"tenant_id": TENANT, "design_id": BOOK_ID, "seat": 1,
                                                   "slot_start": datetime(2026, 11, 23, 10, 0, tzinfo=live.IST).isoformat(),
                                                   "cancelled": False}).execute()
        assert [s.hour for s in live.free_slots(db, TENANT, _booking(), date(2026, 11, 23), NOW)] == [11, 12]

    def test_two_customers_can_never_both_get_the_last_seat(self, db):
        moment = datetime(2026, 11, 23, 11, 0, tzinfo=live.IST)
        design = _booking()
        assert live.reserve(db, TENANT, design, moment, LEAD, "r1") is True
        assert live.reserve(db, TENANT, design, moment, LEAD, "r2") is False

    def test_a_flow_with_questions_carries_the_slot_to_the_end(self):
        flow, answer_map = wf.build_design_flow(_booking())
        assert flow["routing_model"]["DATE"] == ["FULL", "SLOT"] and flow["routing_model"]["SLOT"] == ["QUESTIONS_A"]
        complete = flow["screens"][-2]["layout"]["children"][-1]["on-click-action"]["payload"]
        assert complete["slot"] == "${data.slot}" and "f_full_name" in complete

    def test_booking_submitted_reserves_and_confirms_in_the_forms_language(self, db, monkeypatch):
        sent = []

        async def fake_send(phone, text, **kw):
            sent.append(text)
            return "wamid.x"

        import app.services.ai_reply as ai_reply
        from app.services import automation_guards
        monkeypatch.setattr(ai_reply, "send_whatsapp", fake_send)
        monkeypatch.setattr(intake, "note_lead_message", lambda *a, **k: None)
        monkeypatch.setattr(automation_guards, "ai_replies_allowed_for_lead", lambda *a, **k: True)
        monkeypatch.setattr(live, "bookable", lambda design, moment, now=None: True)   # the slot check has its own tests, with NOW
        answers = json.dumps({"flow_token": wf.make_token(TENANT, PHONE, FORM_2, "a1b2c3d4e5f6"),
                              "slot": "202611231100", "f_full_name": "மீனா", "consent_offers": False})
        out = asyncio.run(wf.handle_submission(db, tenant_id=TENANT, lead_id=LEAD, phone=PHONE, raw=answers,
                                               meta_message_id="m1"))
        assert out == "handled" and len(db.rows("whatsapp_form_bookings")) == 1
        assert sent == [form_texts.PRESETS["ta"]["booked_message"].replace("{slot}", "திங்கள், 23 நவ, காலை 11:00")]
        saved = db.rows("leads")[0]["collected_data"]["whatsapp_forms"][0]["answers"]
        assert saved["Booked for"].startswith("திங்கள்") and saved["முழுப் பெயர்"] == "மீனா"


def test_order_submitted_goes_through_the_quote_rules(db, monkeypatch):
    from app.services import deal_actions, deal_turn
    captured = {}

    async def fake_quote(ctx, args, turn):
        captured.update(args)
        turn.quote_text = "2 × Kaju katli\nPay here: https://rzp.io/l/9"
        return None

    async def fake_link(phone, link, **kw):
        captured["url"] = link.url
        return "wamid.q", True

    monkeypatch.setattr(deal_actions, "_send_quote", fake_quote)
    monkeypatch.setattr(deal_turn, "send_link", fake_link)
    answers = json.dumps({"flow_token": wf.make_token(TENANT, PHONE, FORM_1, "a1b2c3d4e5f6"),
                          "lines": json.dumps([{"id": I1, "qty": 2}, {"id": I3, "qty": 1}]),
                          "name": "Meena", "address": "12 Anna Nagar", "consent_offers": True})
    out = asyncio.run(wf.handle_submission(db, tenant_id=TENANT, lead_id=LEAD, phone=PHONE, raw=answers,
                                           meta_message_id="m2"))
    assert out == "handled" and captured["item_ids"] == [I1] and captured["quantities"] == [2]  # sold-out dropped
    assert captured["url"] == "https://rzp.io/l/9"
    assert db.rows("leads")[0]["collected_data"]["delivery_address"] == "12 Anna Nagar"


def test_live_send_asks_the_endpoint_for_the_first_screen(db, monkeypatch):
    from app.services import meta_cloud
    sent = {}

    async def fake_flow(**kwargs):
        sent.update(kwargs)
        return {"messages": [{"id": "w"}]}

    monkeypatch.setattr(meta_cloud, "send_flow_message", fake_flow)
    design = db.rows("whatsapp_form_designs")[0]
    form = wf.live_custom_form(db, TENANT, design)
    asyncio.run(wf.send_form(PHONE, "Order here", form, cta="Order", tenant_id=TENANT, db=db))
    assert sent["first_screen"] is None


def test_auto_reply_off_keeps_the_booking_but_sends_nothing(db, monkeypatch):
    sent = []

    async def fake_send(phone, text, **kw):
        sent.append(text)

    import app.services.ai_reply as ai_reply
    from app.services import automation_guards
    monkeypatch.setattr(ai_reply, "send_whatsapp", fake_send)
    monkeypatch.setattr(intake, "note_lead_message", lambda *a, **k: None)
    monkeypatch.setattr(automation_guards, "ai_replies_allowed_for_lead", lambda *a, **k: False)
    monkeypatch.setattr(live, "bookable", lambda design, moment, now=None: True)   # the slot check has its own tests, with NOW
    answers = json.dumps({"flow_token": wf.make_token(TENANT, PHONE, FORM_2, "a1b2c3d4e5f6"),
                          "slot": "202611231100", "f_full_name": "Meena"})
    out = asyncio.run(wf.handle_submission(db, tenant_id=TENANT, lead_id=LEAD, phone=PHONE, raw=answers,
                                           meta_message_id="m3"))
    assert out == "handled" and len(db.rows("whatsapp_form_bookings")) == 1 and sent == []


# ── security review fixes (2026-11-21) ───────────────────────────────────────

def test_the_same_product_twice_is_one_line_so_stock_is_checked_on_the_total():
    lines = live._parse_lines(json.dumps([{"id": "a", "qty": 5}, {"id": "a", "qty": 5}, {"id": "b", "qty": 1}]))
    assert lines == [{"id": "a", "qty": 10}, {"id": "b", "qty": 1}]


def test_made_up_item_ids_are_ignored_not_an_error(db):
    assert live._items(db, TENANT, ids=["'; drop", 42, "not-a-uuid"]) == []


def test_a_badly_shaped_token_is_refused(db):
    with pytest.raises(live.EndpointError) as err:
        live.handle_request(db, TENANT, {"action": "INIT", "flow_token": f"wf1.{FORM_2}.zz.x"})
    assert err.value.status == 427


class TestBookingLimits:
    def test_a_time_beyond_the_days_ahead_is_not_bookable(self):
        design = _booking()  # 3 days ahead, Mondays 10-13
        assert live.bookable(design, datetime(2026, 11, 23, 11, 0, tzinfo=live.IST), NOW)
        assert not live.bookable(design, datetime(2026, 11, 30, 11, 0, tzinfo=live.IST), NOW)
        assert not live.bookable(design, datetime(2026, 11, 23, 9, 30, tzinfo=live.IST), NOW)  # too soon

    def test_the_slot_screen_refuses_a_spoofed_time(self, db):
        reply = live.handle_request(db, TENANT, {"action": "data_exchange", "screen": "SLOT", "flow_token": _token(FORM_2),
                                                 "data": {"slot": "202712311000"}}, now=NOW)
        assert reply["screen"] == "FULL"

    def test_one_customer_cannot_take_two_seats_of_the_same_time(self, db, monkeypatch):
        sent = []

        async def fake_send(phone, text, **kw):
            sent.append(text)

        import app.services.ai_reply as ai_reply
        from app.services import automation_guards
        monkeypatch.setattr(ai_reply, "send_whatsapp", fake_send)
        monkeypatch.setattr(intake, "note_lead_message", lambda *a, **k: None)
        monkeypatch.setattr(automation_guards, "ai_replies_allowed_for_lead", lambda *a, **k: True)
        monkeypatch.setattr(live, "bookable", lambda design, moment, now=None: True)
        db.table("whatsapp_form_designs").update({"settings": {**_booking()["settings"], "capacity": 3}}).eq("id", BOOK_ID).execute()
        for n, send_id in enumerate(("a1b2c3d4e5f6", "a1b2c3d4e5f7")):
            answers = json.dumps({"flow_token": wf.make_token(TENANT, PHONE, FORM_2, send_id),
                                  "slot": "202611231100", "f_full_name": "Meena"})
            asyncio.run(wf.handle_submission(db, tenant_id=TENANT, lead_id=LEAD, phone=PHONE, raw=answers,
                                             meta_message_id=f"m-{n}"))
        assert len(db.rows("whatsapp_form_bookings")) == 1
        assert sent[1] == form_texts.PRESETS["ta"]["slot_taken"]


def test_keys_are_bound_to_their_own_row():
    _, private = live._new_key_pair()
    sealed = live._seal(private, live._bound(TENANT, "111"))
    assert live._open(sealed, live._bound(TENANT, "111")) == private
    with pytest.raises(Exception):
        live._open(sealed, live._bound("other-tenant", "111"))


class TestEndpoint:
    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routes import whatsapp_form_designs as routes
        from app.services import meta_webhook_verify

        app = FastAPI()
        app.include_router(routes.public_router, prefix="/data")
        monkeypatch.setattr(routes, "get_supabase", lambda: FakeSupabase())
        self.signed = True
        monkeypatch.setattr(meta_webhook_verify, "verify_meta_signature", lambda *a, **k: self.signed)
        self.keys = ["k"]
        monkeypatch.setattr(live, "private_keys", lambda db, tenant: self.keys)
        return TestClient(app)

    def test_a_business_without_a_key_has_nothing_here(self, client):
        self.keys = []
        assert client.post(f"/data/{LEAD}", content=b"{}").status_code == 404

    def test_an_unsigned_request_is_refused(self, client):
        self.signed = False
        assert client.post(f"/data/{LEAD}", content=b"{}").status_code == 432

    def test_a_huge_request_is_refused_before_any_work(self, client):
        assert client.post(f"/data/{LEAD}", content=b"x" * (65 * 1024)).status_code == 413

    def test_a_signed_request_that_cant_be_decrypted_gets_421(self, client):
        _, other = live._new_key_pair()
        self.keys = [serialization.load_pem_private_key(other, password=None)]
        body = {"encrypted_aes_key": base64.b64encode(b"x" * 256).decode(),
                "encrypted_flow_data": base64.b64encode(b"x" * 32).decode(),
                "initial_vector": base64.b64encode(b"0" * 12).decode()}
        assert client.post(f"/data/{LEAD}", json=body).status_code == 421

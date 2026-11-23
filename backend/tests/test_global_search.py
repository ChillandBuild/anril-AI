"""Global search (/api/v1/search): each group's permission gate, caller scoping for customers and chats,
order-number forms, bill-number match, phone-by-digits, sanitizing, query length, a failing group
skipped, and tenant isolation."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import global_search as gs
from fake_supabase import FakeSupabase

T1, T2 = "t1", "t2"
ALL = ("leads.view", "deals.view", "catalog.view", "conversations.view")


def _now(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _ctx(role="owner", permissions=ALL, tenant=T1, caller_id=None):
    return {"tenant_id": tenant, "user_id": "u1", "role": role, "caller_id": caller_id, "permissions": list(permissions)}


@pytest.fixture
def db():
    d = FakeSupabase()
    d.add("leads", id="L1", tenant_id=T1, name="Priya Raman", phone="+916369781582", segment="A",
          assigned_to="c1", deleted_at=None, needs_human_attention=False)
    d.add("leads", id="L2", tenant_id=T1, name="Priya Kumar", phone="+919876500000", segment="C",
          assigned_to="c2", deleted_at=None, needs_human_attention=False)
    d.add("leads", id="L3", tenant_id=T1, name="Priya Gone", phone="+919000000000", segment="B",
          assigned_to="c1", deleted_at="2026-01-01T00:00:00+00:00")
    d.add("leads", id="LX", tenant_id=T2, name="Priya Other Shop", phone="+916369781582", segment="A",
          assigned_to="c1", deleted_at=None)
    d.add("deals", id="D1", tenant_id=T1, deal_number=12, invoice_number="B-2231", lead_id="L1",
          total_paise=1050000, stage="won", created_at="2026-11-12T08:00:00+00:00")
    d.add("deals", id="D2", tenant_id=T1, deal_number=13, invoice_number=None, lead_id="L2",
          total_paise=500000, stage="awaiting_payment", created_at="2026-11-13T08:00:00+00:00")
    d.add("deals", id="DX", tenant_id=T2, deal_number=12, invoice_number="B-2231", lead_id="LX",
          total_paise=100, stage="won", created_at="2026-11-12T08:00:00+00:00")
    d.add("catalog_items", id="I1", tenant_id=T1, name="Silk Saree Red", price_paise=1050000, stock_quantity=3)
    d.add("catalog_items", id="I2", tenant_id=T1, name="Silk Scarf", price_paise=None, stock_quantity=0)
    d.add("catalog_items", id="IX", tenant_id=T2, name="Silk Other Shop", price_paise=100, stock_quantity=1)
    d.add("messages", id="M1", tenant_id=T1, lead_id="L1", direction="inbound", channel="whatsapp",
          content="Do you have the silk saree in blue colour please", created_at=_now(1))
    d.add("messages", id="M1b", tenant_id=T1, lead_id="L1", direction="inbound", channel="whatsapp",
          content="Another silk question", created_at=_now(5))
    d.add("messages", id="M2", tenant_id=T1, lead_id="L2", direction="inbound", channel="instagram",
          content="silk price?", created_at=_now(2))
    d.add("messages", id="M3", tenant_id=T1, lead_id="L1", direction="inbound", channel="whatsapp",
          content="very old silk message", created_at=_now(120))
    d.add("messages", id="MX", tenant_id=T2, lead_id="LX", direction="inbound", channel="whatsapp",
          content="silk from another shop", created_at=_now(1))
    return d


def _keys(result):
    return [g["key"] for g in result["groups"]]


def _group(result, key):
    return next(g for g in result["groups"] if g["key"] == key)["items"]


# ---------------------------------------------------------------- pure helpers

def test_order_number_forms():
    for form in ("D-0012", "d-12", "d12", "12", "#12", "0012", "# 12"):
        assert gs.order_number(form) == 12, form
    assert gs.order_number("Priya") is None
    assert gs.order_number("D-") is None
    assert gs.order_number("9876543210") is None  # a phone number, not an order number


def test_sanitizing_drops_filter_syntax_and_wildcards():
    assert gs.sanitize_or_term("a%b_c,d(e)f*g.h") == "abcdefgh"
    assert gs.sanitize_value("B/25-26.12%") == "B/25-26.12"
    assert gs.sanitize_or_term("%%__") == ""


def test_phone_digits_needs_four_digits_and_only_phone_characters():
    assert gs.phone_digits("6369") == "6369"
    assert gs.phone_digits("+91 63697 81582") == "916369781582"
    assert gs.phone_digits("123") is None
    assert gs.phone_digits("Priya 6369") is None


def test_rupees_use_indian_grouping():
    assert gs.format_rupees(1050000) == "₹10,500"
    assert gs.format_rupees(10500000) == "₹1,05,000"
    assert gs.format_rupees(12345) == "₹123.45"
    assert gs.format_rupees(0) == "₹0"


def test_snippet_is_about_sixty_characters_around_the_match():
    text = "x" * 80 + " silk saree " + "y" * 80
    snip = gs.snippet_around(text, "silk")
    assert "silk" in snip and snip.startswith("…") and snip.endswith("…") and len(snip) <= 62
    assert gs.snippet_around("short silk", "silk") == "short silk"


# ---------------------------------------------------------------- permission gates (group omitted, never an error)

@pytest.mark.parametrize("perm,gone", [
    ("leads.view", "customers"), ("deals.view", "orders"), ("catalog.view", "items"), ("conversations.view", "chats"),
])
def test_each_group_is_omitted_without_its_permission(db, perm, gone):
    with_all = gs.search(db, _ctx(role="staff"), "priya silk")
    ctx = _ctx(role="staff", permissions=[p for p in ALL if p != perm])
    result = gs.search(db, ctx, "priya silk")
    assert gone not in _keys(result)
    assert set(_keys(result)) == set(_keys(with_all)) - {gone}


def test_no_permissions_gives_no_groups(db):
    assert gs.search(db, _ctx(role="staff", permissions=()), "priya")["groups"] == []


def test_manage_permission_implies_view(db):
    result = gs.search(db, _ctx(role="staff", permissions=("leads.manage",)), "priya")
    assert _keys(result) == ["customers"]


def test_owner_sees_all_groups_in_order(db):
    result = gs.search(db, _ctx(), "silk")
    assert _keys(result) == ["items", "chats"]
    result = gs.search(db, _ctx(), "priya")
    assert _keys(result) == ["customers", "orders"]


# ---------------------------------------------------------------- customers

def test_customers_match_name_skip_deleted_and_other_tenants(db):
    items = _group(gs.search(db, _ctx(), "priya"), "customers")
    assert {i["id"] for i in items} == {"L1", "L2"}
    first = next(i for i in items if i["id"] == "L1")
    assert first["name"] == "Priya Raman" and first["detail"] == "Hot" and first["href"] == "/dashboard/leads/L1"


def test_customers_buyer_detail(db):
    db.rows("leads")[0]["is_buyer"] = True
    items = _group(gs.search(db, _ctx(), "raman"), "customers")
    assert items[0]["detail"] == "Buyer"


def test_customers_match_by_phone_digits(db):
    items = _group(gs.search(db, _ctx(), "6369781"), "customers")
    assert [i["id"] for i in items] == ["L1"]  # not the other shop's lead with the same phone
    items = _group(gs.search(db, _ctx(), "+91 6369 781582"), "customers")
    assert [i["id"] for i in items] == ["L1"]


def test_short_digit_run_does_not_match_phone(db):
    assert "customers" not in _keys(gs.search(db, _ctx(), "63"))


def test_callers_only_see_their_assigned_customers(db):
    caller = _ctx(role="caller", caller_id="c1", permissions=ALL)
    items = _group(gs.search(db, caller, "priya"), "customers")
    assert [i["id"] for i in items] == ["L1"]


def test_caller_without_caller_profile_sees_no_customers_or_chats(db):
    caller = _ctx(role="caller", caller_id=None, permissions=ALL)
    result = gs.search(db, caller, "silk")
    assert "chats" not in _keys(result) and "customers" not in _keys(gs.search(db, caller, "priya"))


def test_customers_capped_at_five(db):
    for n in range(10):
        db.add("leads", id=f"N{n}", tenant_id=T1, name=f"Meena {n}", phone=f"+9100000000{n}", deleted_at=None)
    assert len(_group(gs.search(db, _ctx(), "meena"), "customers")) == 5


# ---------------------------------------------------------------- orders and bills

@pytest.mark.parametrize("q", ["D-0012", "12", "#12", "d12"])
def test_order_number_forms_find_the_order(db, q):
    items = _group(gs.search(db, _ctx(), q), "orders")
    assert items[0]["id"] == "D1"
    assert items[0]["label"] == "D-0012 · Priya Raman"
    assert items[0]["detail"] == "₹10,500 · paid · 12 Nov"
    assert items[0]["href"] == "/dashboard/deals/orders/D1"
    assert all(i["id"] != "DX" for i in items)  # the other shop's D-0012


def test_bill_number_matches_and_labels_as_a_bill(db):
    items = _group(gs.search(db, _ctx(), "b-2231"), "orders")
    assert [i["id"] for i in items] == ["D1"]
    assert items[0]["label"] == "Bill B-2231 · Priya Raman"


def test_orders_of_a_matching_customer_are_listed(db):
    items = _group(gs.search(db, _ctx(), "priya kumar"), "orders")
    assert [i["id"] for i in items] == ["D2"]
    assert items[0]["detail"].startswith("₹5,000 · unpaid")


def test_orders_have_no_caller_scoping_same_as_orders_page(db):
    caller = _ctx(role="caller", caller_id="c1", permissions=ALL)
    ids = {i["id"] for i in _group(gs.search(db, caller, "priya"), "orders")}
    assert ids == {"D1", "D2"}


def test_a_matched_order_is_not_listed_twice(db):
    items = _group(gs.search(db, _ctx(), "12"), "orders")
    assert [i["id"] for i in items].count("D1") == 1


# ---------------------------------------------------------------- items

def test_items_match_name_with_price_and_stock(db):
    items = _group(gs.search(db, _ctx(), "silk"), "items")
    by_id = {i["id"]: i for i in items}
    assert set(by_id) == {"I1", "I2"}  # not the other shop's
    assert by_id["I1"]["detail"] == "₹10,500 · 3 in stock"
    assert by_id["I2"]["detail"] == "Out of stock"
    assert by_id["I1"]["href"] == "/dashboard/catalog/items/I1"


# ---------------------------------------------------------------- chats

def test_chats_one_hit_per_lead_newest_first_within_90_days(db):
    items = _group(gs.search(db, _ctx(), "silk"), "chats")
    assert [i["lead_id"] for i in items] == ["L1", "L2"]  # L1's newest hit; the 120-day message is out
    assert "silk" in items[0]["snippet"].lower()
    assert items[0]["channel"] == "whatsapp" and items[1]["channel"] == "instagram"
    assert items[0]["href"] == "/dashboard/conversations?lead=L1"
    assert "Another silk question" not in items[0]["snippet"]


def test_chats_old_messages_only_means_no_group(db):
    assert "chats" not in _keys(gs.search(db, _ctx(), "very old"))


def test_callers_chats_only_assigned_or_needing_a_person(db):
    caller = _ctx(role="caller", caller_id="c1", permissions=ALL)
    assert [i["lead_id"] for i in _group(gs.search(db, caller, "silk"), "chats")] == ["L1"]
    db.rows("leads")[1]["needs_human_attention"] = True  # L2 now needs a person
    assert [i["lead_id"] for i in _group(gs.search(db, caller, "silk"), "chats")] == ["L1", "L2"]


def test_chats_skip_deleted_leads(db):
    db.add("messages", id="M9", tenant_id=T1, lead_id="L3", direction="inbound", channel="whatsapp",
           content="silk for me", created_at=_now(1))
    assert "L3" not in [i["lead_id"] for i in _group(gs.search(db, _ctx(), "silk"), "chats")]


# ---------------------------------------------------------------- failures, tenants, sanitizing

def test_a_failing_group_is_skipped_not_fatal(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(gs, "_items", boom)
    result = gs.search(db, _ctx(), "silk")
    assert _keys(result) == ["chats"]


def test_a_slow_group_is_dropped_after_the_budget(db, monkeypatch):
    import time

    def slow(*a, **k):
        time.sleep(0.6)
        return [{"id": "x"}]
    monkeypatch.setattr(gs, "_items", slow)
    result = gs.search(db, _ctx(), "silk", budget=0.1)
    assert _keys(result) == ["chats"]


def test_other_tenant_sees_only_its_own_rows(db):
    ctx = _ctx(tenant=T2)
    result = gs.search(db, ctx, "silk")
    assert [i["id"] for i in _group(result, "items")] == ["IX"]
    assert [i["lead_id"] for i in _group(result, "chats")] == ["LX"]
    assert [i["id"] for i in _group(gs.search(db, ctx, "12"), "orders")] == ["DX"]


def test_wildcards_and_filter_syntax_are_not_taken_literally(db):
    # "%" and "_" would match everything as LIKE wildcards; they are dropped, leaving nothing to search.
    assert gs.search(db, _ctx(), "%%")["groups"] == []
    assert gs.search(db, _ctx(), "__")["groups"] == []
    # A comma or paren cannot add an extra or(...) branch: "x,phone.ilike.*" becomes plain text.
    assert gs.search(db, _ctx(), "zz,phone.ilike.*")["groups"] == []
    assert gs.search(db, _ctx(), "priya),name.ilike.*")["groups"] == []


# ---------------------------------------------------------------- the endpoint

@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr("app.routes.global_search.get_supabase", lambda: db)
    holder = {"ctx": _ctx()}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    app.dependency_overrides[get_tenant_and_role] = lambda: holder["ctx"]
    try:
        c = TestClient(app)
        c.holder = holder
        yield c
    finally:
        app.dependency_overrides.clear()


def test_endpoint_returns_groups(client):
    res = client.get("/api/v1/search", params={"q": "priya"})
    assert res.status_code == 200
    body = res.json()
    assert body["query"] == "priya" and [g["key"] for g in body["groups"]] == ["customers", "orders"]
    assert body["groups"][0]["title"] == "Customers"


def test_endpoint_query_length_is_422(client):
    assert client.get("/api/v1/search", params={"q": "a"}).status_code == 422
    assert client.get("/api/v1/search", params={"q": " a "}).status_code == 422
    assert client.get("/api/v1/search", params={"q": ""}).status_code == 422
    assert client.get("/api/v1/search").status_code == 422
    assert client.get("/api/v1/search", params={"q": "x" * 61}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "ab"}).status_code == 200
    assert client.get("/api/v1/search", params={"q": "x" * 60}).status_code == 200


def test_endpoint_is_open_to_any_signed_in_user_without_403(client):
    client.holder["ctx"] = _ctx(role="staff", permissions=())
    res = client.get("/api/v1/search", params={"q": "priya"})
    assert res.status_code == 200 and res.json()["groups"] == []


# ---------------------------------------------------------------- review fixes: Tamil, template lines, caller cut, budget

def test_sanitizing_keeps_letters_of_every_script_and_strips_filter_syntax():
    tamil = "பிரியா"  # vowel signs are combining marks: they must survive
    assert gs.sanitize_or_term(tamil) == tamil
    assert gs.sanitize_value("साड़ी") == "साड़ी"
    assert gs.sanitize_or_term('a,b(c)d.e"f\\g`h*i%j_k') == "abcdefghijk"
    assert gs.sanitize_value('a,b(c)d.e"f\\g') == "abcd.efg"  # the dot stays only in single-column values


def test_tamil_query_reaches_customers_items_and_chats(db):
    db.add("leads", id="LT", tenant_id=T1, name="பிரியா சுந்தர்", phone="+919111111111", segment="B",
           assigned_to="c1", deleted_at=None)
    db.add("catalog_items", id="IT", tenant_id=T1, name="பட்டு புடவை", price_paise=500000, stock_quantity=2)
    db.add("messages", id="MT", tenant_id=T1, lead_id="LT", direction="inbound", channel="whatsapp",
           content="பட்டு புடவை வேண்டும்", created_at=_now(1))
    assert [i["id"] for i in _group(gs.search(db, _ctx(), "பிரியா"), "customers")] == ["LT"]
    result = gs.search(db, _ctx(), "புடவை")
    assert [i["id"] for i in _group(result, "items")] == ["IT"]
    assert [i["lead_id"] for i in _group(result, "chats")] == ["LT"]


def test_template_lines_never_fill_the_chat_candidates(db):
    for n in range(200):
        db.add("messages", id=f"T{n}", tenant_id=T1, lead_id="L2", direction="outbound", channel="whatsapp",
               content=f"[Template Broadcast: silk sale {n}]", created_at=_now(0))
    db.add("messages", id="TT", tenant_id=T1, lead_id="L2", direction="outbound", channel="whatsapp",
           content="[Template: silk offer]", created_at=_now(0))
    items = _group(gs.search(db, _ctx(), "silk"), "chats")
    assert [i["lead_id"] for i in items] == ["L1", "L2"]
    assert all(not i["snippet"].startswith("[Template") for i in items)


def test_caller_chats_are_cut_to_their_leads_before_the_newest_n_limit(db):
    # 200 newer silk messages on someone else's lead must not push the caller's own chat out.
    for n in range(200):
        db.add("messages", id=f"F{n}", tenant_id=T1, lead_id="L2", direction="inbound", channel="whatsapp",
               content=f"silk flood {n}", created_at=_now(0))
    caller = _ctx(role="caller", caller_id="c1", permissions=ALL)
    assert [i["lead_id"] for i in _group(gs.search(db, caller, "silk"), "chats")] == ["L1"]
    # a person needing attention becomes visible to every caller
    db.rows("leads")[1]["needs_human_attention"] = True
    assert "L2" in [i["lead_id"] for i in _group(gs.search(db, caller, "silk"), "chats")]


def test_caller_with_no_visible_leads_gets_no_chats(db):
    caller = _ctx(role="caller", caller_id="c9", permissions=ALL)
    assert "chats" not in _keys(gs.search(db, caller, "silk"))


def test_a_user_with_searches_in_flight_gets_an_empty_busy_answer(db):
    gs._inflight["u1"] = gs.MAX_INFLIGHT_PER_USER
    try:
        result = gs.search(db, _ctx(), "silk")
        assert result["busy"] is True and result["groups"] == []
        # another user is not affected
        other = {**_ctx(), "user_id": "u2"}
        assert _keys(gs.search(db, other, "silk")) == ["items", "chats"]
    finally:
        gs._inflight.clear()


def test_the_slot_is_released_after_a_normal_search(db):
    gs.search(db, _ctx(), "silk")
    deadline = __import__("time").time() + 2
    while gs._inflight and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)
    assert gs._inflight == {}


def test_a_slow_group_keeps_the_slot_until_its_thread_finishes(db, monkeypatch):
    import time

    def slow(*a, **k):
        time.sleep(0.4)
        return []
    monkeypatch.setattr(gs, "_items", slow)
    monkeypatch.setattr(gs, "MAX_INFLIGHT_PER_USER", 1)
    first = gs.search(db, _ctx(), "silk", budget=0.05)
    assert "busy" not in first
    assert gs.search(db, _ctx(), "silk", budget=0.05).get("busy") is True  # the slow thread still runs
    time.sleep(0.6)
    assert "busy" not in gs.search(db, _ctx(), "silk", budget=0.05)


def test_worker_threads_see_the_request_context_vars(db, monkeypatch):
    import contextvars
    var = contextvars.ContextVar("probe", default="unset")
    seen = []

    def probe(*a, **k):
        seen.append(var.get())
        return []
    monkeypatch.setattr(gs, "_items", probe)
    var.set("request-1")
    gs.search(db, _ctx(), "silk")
    assert seen == ["request-1"]


def test_the_customer_lookup_for_orders_is_newest_activity_first(db):
    for n in range(60):
        db.add("leads", id=f"Z{n}", tenant_id=T1, name=f"Zed {n}", phone=f"+9100000{n:04d}", deleted_at=None,
               last_inbound_at="2026-12-01T00:00:00+00:00" if n == 59 else "2026-11-01T00:00:00+00:00",
               created_at=f"2026-01-01T00:00:{n:02d}")
    db.add("deals", id="DZ", tenant_id=T1, deal_number=99, lead_id="Z59", total_paise=100, stage="won",
           created_at="2026-11-01T00:00:00+00:00")
    ids = [i["id"] for i in _group(gs.search(db, _ctx(), "zed"), "orders")]
    # Z59 is among the newest 50 by last message, so its order is found (it would be cut by an unordered limit)
    assert "DZ" in ids


# ---------------------------------------------------------------- bookings group (v9.2 #19)

def _bk_db(db):
    db.add("booking_resources", id="R1", tenant_id=T1, name="Ravi", kind="person", user_id="u-ravi",
           hours={}, active=True, sort=0)
    db.add("booking_resources", id="R2", tenant_id=T1, name="Chair 2", kind="chair", user_id=None,
           hours={}, active=True, sort=1)
    db.add("booking_services", id="S1", tenant_id=T1, name="Reading", duration_min=30, price_paise=50000,
           advance_paise=0, gap_after_min=0, active=True, sort=0)
    rows = [("B1", 12, "Priya Raman", "+916369781582", "R1", "booked", "2026-11-24T04:30:00+00:00"),
            ("B2", 13, "Priya Kumar", "+919876500000", "R2", "booked", "2026-11-24T05:30:00+00:00"),
            ("B3", 14, "Priya Gone", "+919000000000", "R1", "cancelled", "2026-11-24T06:30:00+00:00")]
    for id_, number, name, phone, res, status, start in rows:
        db.add("bookings", id=id_, tenant_id=T1, number=number, customer_name=name, phone=phone, service_id="S1",
               resource_id=res, start_at=start, end_at=start, block_end_at=start, status=status)
    db.add("bookings", id="BX", tenant_id=T2, number=12, customer_name="Priya Other Shop", phone="+916369781582",
           service_id="S1", resource_id="RX", start_at="2026-11-24T04:30:00+00:00", status="booked")
    return db


def test_booking_number_forms():
    for form in ("BK-0012", "bk12", "#12", "12", "BK-12"):
        assert gs.booking_number(form) == 12, form
    assert gs.booking_number("Priya") is None
    assert gs.booking_number("9876543210") is None


def test_bookings_group_needs_bookings_view_and_comes_after_orders(db):
    _bk_db(db)
    assert "bookings" not in _keys(gs.search(db, _ctx(role="staff"), "priya"))
    ctx = _ctx(role="staff", permissions=ALL + ("bookings.view",))
    result = gs.search(db, ctx, "priya")
    assert _keys(result) == ["customers", "orders", "bookings"]
    items = _group(result, "bookings")
    assert {i["id"] for i in items} == {"B1", "B2"}                 # cancelled one and the other business are out
    one = next(i for i in items if i["id"] == "B1")
    assert one["label"] == "BK-0012 · Priya Raman"
    assert one["detail"] == "Tue 10:00 AM · Reading · Ravi"          # Indian time
    assert one["href"] == "/dashboard/bookings?date=2026-11-24&booking=B1"
    assert set(one) == {"id", "label", "detail", "href"}


def test_bookings_found_by_code_number_and_phone_digits(db):
    _bk_db(db)
    ctx = _ctx(role="staff", permissions=("bookings.view",))
    for q in ("BK-0012", "bk12", "#12"):
        assert [i["id"] for i in _group(gs.search(db, ctx, q), "bookings")] == ["B1"], q
    assert [i["id"] for i in _group(gs.search(db, ctx, "63697 81582"), "bookings")] == ["B1"]


def test_a_linked_staff_member_searches_only_their_own_column(db):
    _bk_db(db)
    ctx = {**_ctx(role="staff", permissions=("bookings.view",)), "user_id": "u-ravi"}
    assert [i["id"] for i in _group(gs.search(db, ctx, "priya"), "bookings")] == ["B1"]
    manager = _ctx(role="staff", permissions=("bookings.manage",))
    assert {i["id"] for i in _group(gs.search(db, manager, "priya"), "bookings")} == {"B1", "B2"}


def test_bookings_search_lists_upcoming_first_then_past_most_recent_first(db, monkeypatch):
    from app.services import bookings as bk
    now = datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(bk, "_now", lambda: now)
    for i, hours in enumerate((-72, -2, 30, 5), start=1):               # two past, two upcoming
        start = bk.iso(now + timedelta(hours=hours))
        db.add("bookings", id=f"O{i}", tenant_id=T1, number=900 + i, customer_name="Zed Order", phone="+910000000000",
               service_id="S1", resource_id="R1", start_at=start, end_at=start, block_end_at=start, status="booked")
    ctx = _ctx(role="staff", permissions=("bookings.view",))
    assert [i["id"] for i in _group(gs.search(db, ctx, "zed order"), "bookings")] == ["O4", "O3", "O2", "O1"]

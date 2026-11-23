"""Deal lifecycle rules (services/deals.py) against a small in-memory fake of
the Supabase client: stock moves on won only and exactly once, a refund puts
it back, prices come from the catalog, the AI keeps one open quote per lead,
and the intake form mirrors onto one deal per session."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import deals

TENANT = "t-1"


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload = db, table, [], "select", None
        self._single, self._limit = False, None

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: r.get(k) == v)
        return self

    def neq(self, k, v):
        self.filters.append(lambda r: r.get(k) != v)
        return self

    def in_(self, k, vs):
        self.filters.append(lambda r: r.get(k) in vs)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            new = [{"id": str(uuid.uuid4()), "created_at": "2026-09-25T00:00:00+00:00", **i} for i in items]
            rows.extend(new)
            return SimpleNamespace(data=new)
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            return SimpleNamespace(data=[dict(r) for r in match])
        if self.op == "delete":
            self.db.tables[self.table] = [r for r in rows if r not in match]
            return SimpleNamespace(data=match)
        if self._limit:
            match = match[: self._limit]
        if self._single:
            return SimpleNamespace(data=dict(match[0]) if match else None)
        return SimpleNamespace(data=[dict(r) for r in match])


class FakeDb:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.counter = itertools.count(1)
        self.movements: list[tuple] = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        if name == "next_deal_number":
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=next(self.counter)))
        assert name == "apply_stock_movement"
        item = next(i for i in self.tables["catalog_items"] if i["id"] == params["p_item_id"])
        current = item.get("stock_quantity")
        if current is None:
            row = {"ok": True, "tracked": False, "quantity_after": None}
        elif current + params["p_delta"] < 0:
            row = {"ok": False, "tracked": True, "quantity_after": current}
        else:
            item["stock_quantity"] = current + params["p_delta"]
            self.movements.append((params["p_item_id"], params["p_delta"], params["p_reason"]))
            row = {"ok": True, "tracked": True, "quantity_after": item["stock_quantity"]}
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[row]))


@pytest.fixture
def db():
    fake = FakeDb()
    fake.tables["catalog_items"] = [
        {"id": "earbuds", "tenant_id": TENANT, "name": "Earbuds", "price_paise": 129900, "gst_rate": 18, "stock_quantity": 3},
        {"id": "service", "tenant_id": TENANT, "name": "Setup", "price_paise": 50000, "gst_rate": None, "stock_quantity": None},
    ]
    fake.tables["leads"] = [{"id": "lead-1", "tenant_id": TENANT, "name": "Ravi", "phone": "+919800000001"}]
    with patch("app.services.business_details.prices_include_gst", return_value=True):
        yield fake


@pytest.mark.asyncio
async def test_walk_in_won_sale_snapshots_catalog_price_and_deducts_stock(db):
    result = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 2}], "walk_in", "won",
                                     payment_method="cash", db=db)
    assert result["deal"]["total_paise"] == 259800
    assert result["deal"]["deal_number"] == 1
    assert result["items"][0]["unit_price_paise"] == 129900
    assert db.tables["catalog_items"][0]["stock_quantity"] == 1
    assert db.movements == [("earbuds", -2, "sale")]
    assert result["stock_warnings"] == []


@pytest.mark.asyncio
async def test_a_deal_for_a_shop_that_charges_no_gst_is_born_a_simple_bill(db):
    """Composition or unregistered shop: the order says so itself ('simple'), so it never prints as a tax invoice."""
    with patch("app.services.business_details.charges_gst", return_value=False):
        result = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 1}], "whatsapp", "quoted", db=db)
    assert result["deal"]["bill_type"] == "simple"
    assert db.tables["deals"][0]["bill_type"] == "simple"


@pytest.mark.asyncio
async def test_a_deal_for_a_gst_shop_is_left_to_the_gst_default(db):
    with patch("app.services.business_details.charges_gst", return_value=True):
        result = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 1}], "whatsapp", "quoted", db=db)
    assert result["deal"].get("bill_type") in (None, "gst")


def test_the_ai_quote_for_a_shop_that_charges_no_gst_is_a_simple_bill(db):
    with patch("app.services.business_details.charges_gst", return_value=False):
        deals.upsert_quoted_deal(TENANT, "lead-1", {"catalog_item_id": "earbuds", "name": "Earbuds", "qty": 1}, db=db)
    assert db.tables["deals"][0]["bill_type"] == "simple"


@pytest.mark.asyncio
async def test_overselling_still_records_the_sale_but_warns(db):
    result = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 5}], "walk_in", "won",
                                     payment_method="upi", db=db)
    assert result["deal"]["stage"] == "won"
    assert result["stock_warnings"] == [{"catalog_item_id": "earbuds", "name": "Earbuds", "available": 3}]
    assert db.tables["catalog_items"][0]["stock_quantity"] == 3


@pytest.mark.asyncio
async def test_quoted_deal_never_touches_stock(db):
    await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 1}], "manual", "quoted", db=db)
    assert db.movements == []


@pytest.mark.asyncio
async def test_line_without_any_price_is_rejected(db):
    with pytest.raises(deals.DealError):
        await deals.create_deal(TENANT, "lead-1", [{"name": "Mystery box", "qty": 1}], "manual", "won", db=db)


@pytest.mark.asyncio
async def test_other_tenants_product_is_not_found(db):
    db.tables["catalog_items"].append({"id": "theirs", "tenant_id": "t-2", "name": "X", "price_paise": 1})
    with pytest.raises(deals.DealError):
        await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "theirs", "qty": 1}], "manual", "won", db=db)


@pytest.mark.asyncio
async def test_mark_won_twice_deducts_stock_once(db):
    created = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 1}], "manual", "quoted", db=db)
    deal_id = created["deal"]["id"]
    first = deals.mark_won(TENANT, deal_id, payment_method="razorpay", razorpay_payment_id="pay_1", db=db)
    second = deals.mark_won(TENANT, deal_id, payment_method="razorpay", razorpay_payment_id="pay_1", db=db)
    assert first is not None and second is None
    assert db.movements == [("earbuds", -1, "sale")]


@pytest.mark.asyncio
async def test_refund_of_a_won_deal_returns_stock(db):
    created = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 2}], "walk_in", "won",
                                      payment_method="cash", db=db)
    lost = deals.mark_lost(TENANT, created["deal"]["id"], "Customer returned it", db=db)
    assert lost["deal"]["stage"] == "lost"
    assert db.tables["catalog_items"][0]["stock_quantity"] == 3
    assert db.movements[-1] == ("earbuds", 2, "return")


@pytest.mark.asyncio
async def test_prices_excluding_gst_add_tax_to_what_the_customer_pays(db):
    with patch("app.services.business_details.prices_include_gst", return_value=False):
        result = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 1}], "manual", "quoted", db=db)
    assert result["deal"]["total_paise"] == 129900 + round(129900 * 18 / 100)
    assert result["items"][0]["line_total_paise"] == 129900


@pytest.mark.asyncio
async def test_awaiting_payment_creates_link_with_deal_id_in_notes(db):
    fake_link = AsyncMock(return_value={"payment_link_url": "https://rzp.io/x", "razorpay_payment_link_id": "plink_1"})
    with patch("app.services.payment_razorpay.create_payment_link", fake_link), \
         patch("app.services.ai_reply.send_whatsapp", AsyncMock(side_effect=RuntimeError("outside 24h window"))):
        result = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 1}], "manual",
                                         "awaiting_payment", send_link=True, db=db)
    assert fake_link.await_args.kwargs["notes"] == {"deal_id": result["deal"]["id"]}
    assert result["payment_link"] == "https://rzp.io/x"
    assert result["message_sent"] is False  # link still returned so staff can share it
    assert db.tables["deals"][0]["stage"] == "awaiting_payment"


def test_ai_recommendations_keep_one_open_quote_per_lead(db):
    deals.upsert_quoted_deal(TENANT, "lead-1", {"catalog_item_id": "earbuds", "name": "Earbuds", "qty": 1}, db=db)
    deals.upsert_quoted_deal(TENANT, "lead-1", {"catalog_item_id": "service", "name": "Setup", "qty": 1}, db=db)
    assert len(db.tables["deals"]) == 1
    assert [i["name"] for i in db.tables["deal_items"]] == ["Setup"]
    assert db.tables["deals"][0]["total_paise"] == 50000


def test_intake_session_mirrors_onto_one_deal_through_its_statuses(db):
    session = {
        "id": "s-1", "tenant_id": TENANT, "lead_id": "lead-1", "status": "awaiting_payment",
        "package_name": "Horoscope", "package_amount_paise": 150000,
        "selected_addons": [{"name": "Remedy", "amount_paise": 50000}], "total_amount_paise": 200000,
        "payment_link": "https://rzp.io/s",
    }
    deals.sync_intake_session(session, db=db)
    deals.sync_intake_session({**session, "status": "paid", "razorpay_payment_id": "pay_9"}, db=db)
    assert len(db.tables["deals"]) == 1
    deal = db.tables["deals"][0]
    assert deal["source"] == "form" and deal["stage"] == "won" and deal["total_paise"] == 200000
    assert sorted(i["name"] for i in db.tables["deal_items"]) == ["Horoscope", "Remedy"]


def test_intake_session_with_gst_charges_total_plus_gst_and_tags_lines_with_the_rate(db):
    session = {
        "id": "s-g", "tenant_id": TENANT, "lead_id": "lead-1", "status": "awaiting_payment",
        "package_name": "Horoscope", "package_amount_paise": 4900, "total_amount_paise": 4900,
        "gst_percent": 18, "gst_amount_paise": 882, "amount_paise": 5782, "payment_link": "https://rzp.io/g",
    }
    deals.sync_intake_session(session, db=db)
    deal = db.tables["deals"][0]
    assert deal["total_paise"] == 5782
    item = db.tables["deal_items"][0]
    assert item["unit_price_paise"] == 4900 and item["gst_rate"] == 18.0 and item["line_total_paise"] == 4900


def test_intake_session_without_gst_is_unchanged(db):
    session = {
        "id": "s-n", "tenant_id": TENANT, "lead_id": "lead-1", "status": "awaiting_payment",
        "package_name": "Horoscope", "package_amount_paise": 4900, "total_amount_paise": 4900,
        "gst_percent": 18, "gst_amount_paise": 0, "amount_paise": 4900,
    }
    deals.sync_intake_session(session, db=db)
    assert db.tables["deals"][0]["total_paise"] == 4900
    assert db.tables["deal_items"][0].get("gst_rate") is None


def test_cancelled_intake_session_marks_its_deal_lost(db):
    session = {"id": "s-2", "tenant_id": TENANT, "lead_id": "lead-1", "status": "awaiting_payment",
               "package_name": "Horoscope", "package_amount_paise": 150000}
    deals.sync_intake_session(session, db=db)
    deals.sync_intake_session({**session, "status": "cancelled"}, db=db)
    assert db.tables["deals"][0]["stage"] == "lost"
    assert db.tables["deals"][0]["lost_reason"] == "Link expired or cancelled"


def test_cancelled_intake_session_carries_the_callers_lost_reason(db):
    session = {"id": "s-3", "tenant_id": TENANT, "lead_id": "lead-1", "status": "awaiting_payment",
               "package_name": "Horoscope", "package_amount_paise": 150000}
    deals.sync_intake_session(session, db=db)
    deals.sync_intake_session({**session, "status": "cancelled"}, db=db, lost_reason="Customer declined")
    assert db.tables["deals"][0]["lost_reason"] == "Customer declined"


def test_sync_never_raises_on_bad_input():
    deals.sync_intake_session({"status": "paid"}, db=FakeDb())


# ---------------------------------------------------------------- R2: one live link per deal

def _in(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _open_deal(db, **over) -> dict:
    deal = {
        "id": "d-1", "tenant_id": TENANT, "lead_id": "lead-1", "deal_number": 7, "stage": "awaiting_payment",
        "source": "manual", "total_paise": 129900, "payment_link": "https://rzp.io/old",
        "razorpay_payment_link_id": "plink_old", "link_expires_at": _in(hours=10), **over,
    }
    db.tables.setdefault("deals", []).append(deal)
    db.tables.setdefault("deal_items", []).append(
        {"deal_id": "d-1", "tenant_id": TENANT, "name": "Earbuds", "qty": 1, "line_total_paise": 129900})
    return deal


class _Razorpay:
    """Fake create/cancel pair patched over the payment_razorpay module."""

    def __init__(self, cancel_ok=True):
        self.created: list[dict] = []
        self.cancelled: list[tuple] = []
        self.events: list[str] = []
        self.cancel_ok = cancel_ok
        self.expiry = _in(hours=24, minutes=-7)  # deliberately not now+24h

    async def create(self, **kw):
        self.created.append(kw)
        self.events.append("create")
        return {"payment_link_url": f"https://rzp.io/new{len(self.created)}",
                "razorpay_payment_link_id": f"plink_new{len(self.created)}",
                "payment_link_expires_at": self.expiry}

    async def cancel(self, plink_id, tenant_id=None):
        self.cancelled.append((plink_id, tenant_id))
        self.events.append("cancel")
        return self.cancel_ok

    def install(self):
        return (patch("app.services.payment_razorpay.create_payment_link", self.create),
                patch("app.services.payment_razorpay.cancel_payment_link", self.cancel),
                patch("app.services.ai_reply.send_whatsapp", AsyncMock()))


@pytest.fixture
def rzp():
    fake = _Razorpay()
    patches = fake.install()
    for p in patches:
        p.start()
    yield fake
    for p in patches:
        p.stop()


@pytest.mark.asyncio
async def test_a_live_link_is_resent_not_recreated(db, rzp):
    _open_deal(db)
    out = await deals.send_payment_link(TENANT, "d-1", db=db)
    assert out["payment_link"] == "https://rzp.io/old" and out["message_sent"] is True
    assert rzp.created == [] and rzp.cancelled == []
    assert db.tables["deals"][0]["razorpay_payment_link_id"] == "plink_old"


@pytest.mark.asyncio
async def test_an_expired_link_is_replaced_and_the_real_expiry_is_stored(db, rzp):
    _open_deal(db, link_expires_at=_in(hours=-1))
    out = await deals.send_payment_link(TENANT, "d-1", db=db)
    deal = db.tables["deals"][0]
    assert out["payment_link"] == "https://rzp.io/new1" and deal["payment_link"] == "https://rzp.io/new1"
    assert deal["razorpay_payment_link_id"] == "plink_new1"
    assert deal["link_expires_at"] == rzp.expiry
    assert rzp.cancelled == []  # already dead on Razorpay's side, nothing to cancel


@pytest.mark.asyncio
async def test_a_link_with_no_recorded_expiry_counts_as_dead(db, rzp):
    _open_deal(db, link_expires_at=None, razorpay_payment_link_id=None)
    await deals.send_payment_link(TENANT, "d-1", db=db)
    assert len(rzp.created) == 1


@pytest.mark.asyncio
async def test_a_link_about_to_expire_is_replaced_and_the_old_plink_cancelled_after_storing(db, rzp):
    _open_deal(db, link_expires_at=_in(seconds=20))
    real_update = db.table

    def spy_table(name):
        q = real_update(name)
        if name == "deals":
            orig = q.execute

            def execute():
                if q.op == "update":
                    rzp.events.append("store")
                return orig()
            q.execute = execute
        return q

    db.table = spy_table
    await deals.send_payment_link(TENANT, "d-1", db=db)
    assert rzp.cancelled == [("plink_old", TENANT)]
    assert rzp.events == ["create", "store", "cancel"]


@pytest.mark.asyncio
async def test_a_failed_cancel_still_leaves_the_new_link_in_place(db, rzp):
    rzp.cancel_ok = False
    _open_deal(db, link_expires_at=_in(seconds=20))
    out = await deals.send_payment_link(TENANT, "d-1", db=db)
    assert out["payment_link"] == "https://rzp.io/new1"
    assert db.tables["deals"][0]["razorpay_payment_link_id"] == "plink_new1"


@pytest.mark.asyncio
async def test_a_raising_cancel_never_breaks_link_creation(db, rzp):
    async def boom(*a, **k):
        raise RuntimeError("network")

    _open_deal(db, link_expires_at=_in(seconds=20))
    with patch("app.services.payment_razorpay.cancel_payment_link", boom):
        out = await deals.send_payment_link(TENANT, "d-1", db=db)
    assert out["payment_link"] == "https://rzp.io/new1"


@pytest.mark.asyncio
async def test_a_regenerated_link_uses_a_new_idempotency_key(db, rzp):
    _open_deal(db, link_expires_at=_in(hours=-1), razorpay_payment_link_id=None)
    await deals.send_payment_link(TENANT, "d-1", db=db)
    db.tables["deals"][0]["link_expires_at"] = _in(hours=-1)
    await deals.send_payment_link(TENANT, "d-1", db=db)
    first, second = (c["idempotency_key"] for c in rzp.created)
    assert first != second and second.endswith(":payment_link") and "d-1" in second


def test_intake_sync_stores_the_sessions_real_expiry_and_plink_id(db):
    session = {
        "id": "s-x", "tenant_id": TENANT, "lead_id": "lead-1", "status": "awaiting_payment",
        "package_name": "Horoscope", "package_amount_paise": 4900, "total_amount_paise": 4900, "amount_paise": 4900,
        "payment_link": "https://rzp.io/s", "razorpay_payment_link_id": "plink_s",
        "payment_link_expires_at": "2026-10-04T12:32:00+00:00",
    }
    deals.sync_intake_session(session, db=db)
    deal = db.tables["deals"][0]
    assert deal["link_expires_at"] == "2026-10-04T12:32:00+00:00"
    assert deal["razorpay_payment_link_id"] == "plink_s"


# ---- R3 / D2: an expired link clears the link, the deal stays open -----------------

def test_expire_deal_link_clears_the_link_and_keeps_the_stage():
    from app.services.deals import expire_deal_link
    from tests.fake_supabase import FakeSupabase

    db = FakeSupabase()
    deal = db.add("deals", tenant_id="t1", stage="awaiting_payment", payment_link="https://rzp.io/x",
                  razorpay_payment_link_id="plink_1", link_expires_at="2026-01-02T00:00:00+00:00")
    assert expire_deal_link("t1", deal["id"], db=db) is True
    saved = db.rows("deals")[0]
    assert saved["stage"] == "awaiting_payment"
    assert saved["payment_link"] is None and saved["link_expires_at"] is None
    assert saved["razorpay_payment_link_id"] == "plink_1"


def test_expire_deal_link_ignores_other_tenants_and_settled_deals():
    from app.services.deals import expire_deal_link
    from tests.fake_supabase import FakeSupabase

    db = FakeSupabase()
    other = db.add("deals", tenant_id="t2", stage="awaiting_payment", payment_link="https://rzp.io/x")
    won = db.add("deals", tenant_id="t1", stage="won", payment_link="https://rzp.io/y")
    assert expire_deal_link("t1", other["id"], db=db) is False
    assert expire_deal_link("t1", won["id"], db=db) is False
    assert all(r["payment_link"] for r in db.rows("deals"))


@pytest.mark.asyncio
async def test_an_order_created_already_paid_takes_its_property_units(db):
    """Record payment 'paid now' creates the order already won: its property units must come off too."""
    seen = []
    with patch("app.services.properties.on_deal_paid", side_effect=lambda _db, t, d: seen.append((t, d)) or 1):
        result = await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 1}], "walk_in", "won",
                                         payment_method="cash", db=db)
    assert seen == [(TENANT, result["deal"]["id"])]


@pytest.mark.asyncio
async def test_a_quoted_order_takes_no_property_units_yet(db):
    seen = []
    with patch("app.services.properties.on_deal_paid", side_effect=lambda *a: seen.append(a) or 0), \
         patch.object(deals, "send_payment_link"):
        await deals.create_deal(TENANT, "lead-1", [{"catalog_item_id": "earbuds", "qty": 1}], "walk_in", "quoted", db=db)
    assert seen == []

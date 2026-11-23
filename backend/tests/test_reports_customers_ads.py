"""Reports: shared reads, Customers and Ads tabs."""
from reports_seed import PERIOD, T1, T2, MissingTables, at, seed
from fake_supabase import FakeSupabase
from app.services import reports_ads, reports_customers, reports_data as rd
from app.services.reports_common import Flags

ALL = Flags(True, True)


def test_won_deals_are_this_shops_paid_orders_in_the_days():
    ids = {d["id"] for d in rd.won_deals(seed(FakeSupabase()), T1, PERIOD)}
    assert ids == {"D1", "D2"}


def test_sales_before_gst():
    assert rd.sales_before_gst({"total_paise": 118_000, "gst_paise": 18_000}) == 100_000
    assert rd.sales_before_gst({"total_paise": 5, "gst_paise": None}) == 5


def test_new_leads_and_new_chats():
    db = seed(FakeSupabase())
    assert {l["id"] for l in rd.new_leads(db, T1, PERIOD)} == {"L1", "L2", "L3", "L4", "L6"}
    assert {l["id"] for l in rd.new_chats(db, T1, PERIOD)} == {"L1", "L2", "L3", "L4"}  # an uploaded list is not a chat


def test_is_hot():
    assert rd.is_hot({"segment": "A"}) and rd.is_hot({"segment": "a"})
    assert not rd.is_hot({"segment": "B"}) and not rd.is_hot({})


def test_buyers_split_repeat_means_paid_before_the_days():
    db = seed(FakeSupabase())
    split = rd.buyers_split(db, T1, PERIOD, rd.won_deals(db, T1, PERIOD))
    assert split == {"buyer_ids": ["L1", "L5"], "repeat_ids": ["L5"], "new_ids": ["L1"]}


def test_money_in_is_payments_less_refunds():
    assert rd.money_in(seed(FakeSupabase()), T1, PERIOD) == 118_000 + 50_000 - 5_000


def test_call_numbers_leave_out_the_owners_own_calls():
    db = FakeSupabase()
    mk = lambda cid, status, outcome, secs: db.add("call_logs", tenant_id=T1, caller_id=cid, manual_status=status,
                                                   outcome=outcome, duration_seconds=secs, created_at=at(12))
    mk("c1", "connected", "converted", 120)
    mk("c1", "not_connected", None, 0)
    mk(None, "connected", None, 600)
    assert rd.call_numbers(db, T1, PERIOD) == {"calls": 2, "connected_calls": 1, "sales_from_calls": 1, "talk_minutes": 2}


def test_booking_count_and_missing_table():
    db = FakeSupabase()
    db.add("bookings", tenant_id=T1, status="booked", booking_date="2026-10-12")
    db.add("bookings", tenant_id=T1, status="cancelled", booking_date="2026-10-12")
    db.add("bookings", tenant_id=T1, status="came", booking_date="2026-10-16")
    db.add("bookings", tenant_id=T1, status="booked", booking_date="2026-10-17")
    assert rd.booking_count(db, T1, PERIOD) == 2
    assert rd.booking_count(MissingTables("bookings"), T1, PERIOD) is None


def test_modules_in_use():
    db = FakeSupabase()
    assert rd.modules_in_use(db, T1) == {"orders": False, "calls": False, "ads": False, "bookings": False}
    seed(db)
    mods = rd.modules_in_use(db, T1)
    assert mods["orders"] and mods["ads"] and not mods["calls"]
    assert rd.modules_in_use(db, T2)["orders"]  # T2 has its own order, T1's rows are not counted for it


# ── Customers ───────────────────────────────────────────────────────────────

def test_came_from_key_first_touch_first():
    plat = {"g": "google", "m": "meta"}
    k = reports_customers.came_from_key
    assert k({"source": "qr"}, plat) == "qr" and k({"qr_link_id": "q", "source": "whatsapp"}, plat) == "qr"
    assert k({"source": "meta_form"}, plat) == "instant_form"
    assert k({"source": "whatsapp", "ad_campaign_id": "g"}, plat) == "google_ads"
    assert k({"source": "whatsapp", "ad_campaign_id": "m"}, plat) == "meta_ad"
    assert k({"source": "instagram"}, plat) == "organic" and k({"source": "upload"}, plat) == "upload"


def test_campaign_platforms_and_cohort_buyers():
    db = seed(FakeSupabase())
    assert reports_customers.campaign_platforms(db, T1) == {"camp-m": "meta", "camp-g": "google"}
    assert reports_customers.cohort_buyer_ids(db, T1, ["L1", "L2", "L5"]) == {"L1", "L5"}


def test_customers_funnel_buyers_and_sources():
    db = seed(FakeSupabase())
    numbers, extras = reports_customers.compute(db, T1, PERIOD, ALL)
    assert numbers == {"first_chats": 4, "hot": 2, "paid": 2, "new_buyers": 1, "repeat_buyers": 1}
    assert [(f["key"], f["count"]) for f in extras["funnel"]] == [("first_chats", 4), ("hot", 2), ("paid", 1)]
    counts = {c["key"]: c["count"] for c in extras["came_from"]}
    assert counts == {"meta_ad": 1, "qr": 1, "instant_form": 1, "organic": 1, "upload": 1}
    assert all("people" in c for c in extras["came_from"])


def test_customers_in_short_says_it_plainly():
    text = reports_customers.in_short({"first_chats": 42, "hot": 6, "paid": 3, "repeat_buyers": 1}, {"first_chats": 34})
    assert text == "42 new chats, up 8 from before; 6 hot; 3 persons paid (1 came back)."
    assert reports_customers.in_short({"first_chats": 0}, None) == "0 new chats."


# ── Ads ─────────────────────────────────────────────────────────────────────

def test_google_spend_is_shared_out_by_day():
    rows = [{"campaign_id": "g", "month": "2026-10-01", "spend_paise": 3_100_000}]
    assert reports_ads.google_spend_for(rows, PERIOD) == {"g": 700_000}
    assert reports_ads.google_spend_for(rows, __import__("reports_seed").Period(PERIOD.start.replace(month=12), PERIOD.end.replace(month=12))) == {}


def test_meta_spend_reads_daily_insights_as_paise():
    assert reports_ads.meta_spend_for(seed(FakeSupabase()), T1, PERIOD) == {"camp-m": 50_000}


def test_ads_rows_costs_and_money_back():
    numbers, extras = reports_ads.compute(seed(FakeSupabase()), T1, PERIOD, ALL)
    rows = {r["id"]: r for r in extras["rows"]}
    meta = rows["camp-m"]
    assert (meta["platform"], meta["chats"], meta["hot"], meta["sales"]) == ("meta", 1, 1, 1)
    assert meta["spend_paise"] == 50_000 and meta["earned_paise"] == 118_000
    assert meta["cost_per_chat_paise"] == 50_000 and meta["cost_per_sale_paise"] == 50_000 and meta["money_back"] == 2.36
    google = rows["camp-g"]
    assert (google["platform"], google["spend_paise"], google["sales"], google["cost_per_sale_paise"]) == ("google", 700_000, 0, None)
    assert numbers["spend_paise"] == 750_000 and numbers["chats"] == 2 and numbers["hot"] == 1


def test_ads_without_money_permission_never_reads_spend():
    numbers, extras = reports_ads.compute(seed(FakeSupabase()), T1, PERIOD, Flags(False, False))
    assert numbers["spend_paise"] == 0 and all(r["spend_paise"] == 0 for r in extras["rows"])


def test_ads_missing_cost_tables_do_not_crash():
    db = seed(MissingTables("ad_insights_daily", "google_ads_spend"))
    numbers, extras = reports_ads.compute(db, T1, PERIOD, ALL)
    assert numbers["chats"] == 2 and numbers["spend_paise"] == 0


def test_ads_in_short():
    text = reports_ads.in_short({"spend_paise": 750_000, "chats": 2, "cost_per_chat_paise": 375_000, "sales": 1}, {"chats": 1})
    assert text == "₹7,500 spent on ads; 2 chats from ads, up 1 from before; ₹3,750 per chat; 1 paid."

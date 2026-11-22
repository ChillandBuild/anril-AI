"""WhatsApp QR & links (#24): codes, staff API, public redirect, webhook tag hook. The DB is the in-memory fake."""
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role
from app.routes import qr_links as routes
from app.services import qr_links as svc
from tests import fake_supabase
from tests.fake_supabase import FakeSupabase

T1 = "11111111-1111-1111-1111-111111111111"
T2 = "22222222-2222-2222-2222-222222222222"
OWNER = {"tenant_id": T1, "role": "owner", "permissions": [], "user_id": "u1"}


@pytest.fixture
def db(monkeypatch):
    d = FakeSupabase()
    monkeypatch.setitem(fake_supabase._UNIQUE, "qr_links", [("code",)])
    monkeypatch.setattr(routes, "get_supabase", lambda: d)
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    routes._public_limiter.reset()
    svc._recent_opens.clear()
    svc._open_log_times.clear()
    d.add("phone_numbers", tenant_id=T1, number="+91 98765 43210", role="primary", status="active")
    return d


def client(ctx):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/qr-links")
    app.include_router(routes.public_router, prefix="/api/v1/public/qr")
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    return TestClient(app)


def link(db, code="ABCDE", tenant=T1, **kw):
    return db.add("qr_links", tenant_id=tenant, code=code, name=kw.pop("name", "Table 4"),
                  first_message=kw.pop("first_message", "Hi, I'm at Table 4"), archived=kw.pop("archived", False), **kw)


# ---------------------------------------------------------------- codes

def test_code_alphabet_has_no_lookalikes():
    for _ in range(200):
        code = svc.generate_code()
        assert 4 <= len(code) <= 6 and svc.CODE_RE.match(code)
        assert not set(code) & set("01OI")


def test_create_retries_when_the_code_is_taken(db, monkeypatch):
    link(db, code="AAAAA")
    codes = iter(["AAAAA", "AAAAA", "BBBBB"])
    monkeypatch.setattr(svc, "generate_code", lambda length=5: next(codes))
    row = svc.create_link(db, T1, name="Wall", first_message="Hi", place_id=None, created_by="u1")
    assert row["code"] == "BBBBB"


def test_create_gives_up_after_many_collisions(db, monkeypatch):
    link(db, code="AAAAA")
    monkeypatch.setattr(svc, "generate_code", lambda length=5: "AAAAA")
    with pytest.raises(svc.QrError) as e:
        svc.create_link(db, T1, name="Wall", first_message="Hi", place_id=None, created_by=None)
    assert e.value.status_code == 503


def test_non_unique_errors_are_not_swallowed(db, monkeypatch):
    class Boom:
        def table(self, _):
            raise RuntimeError("db down")
    with pytest.raises(RuntimeError):
        svc.create_link(Boom(), T1, name="Wall", first_message="Hi", place_id=None, created_by=None)


# ---------------------------------------------------------------- staff API

def test_create_and_list(db):
    c = client(OWNER)
    r = c.post("/api/v1/qr-links", json={"name": "  Table 4 ", "first_message": "Hi, I'm at Table 4"})
    assert r.status_code == 200
    item = r.json()
    assert item["name"] == "Table 4" and item["url"] == f"https://app.example.com/q/{item['code']}"
    assert item["stats"] == {"opens": 0, "chats": 0, "new_customers": 0, "paid_orders": 0, "paid_paise": 0}
    listing = c.get("/api/v1/qr-links").json()
    assert [i["id"] for i in listing["items"]] == [item["id"]] and listing["places"] == []


def test_create_validates_input(db):
    c = client(OWNER)
    assert c.post("/api/v1/qr-links", json={"name": "   ", "first_message": "Hi"}).status_code == 400
    assert c.post("/api/v1/qr-links", json={"name": "x" * 81, "first_message": "Hi"}).status_code == 400
    assert c.post("/api/v1/qr-links", json={"name": "A", "first_message": "x" * 301}).status_code == 400
    assert c.post("/api/v1/qr-links", json={"name": "A", "first_message": "Hi", "tenant_id": T2}).status_code == 422


def test_place_must_belong_to_this_business(db):
    mine = db.add("stock_places", tenant_id=T1, name="Cafe", archived=False, sort_order=1)
    theirs = db.add("stock_places", tenant_id=T2, name="Other", archived=False, sort_order=1)
    db.add("stock_places", tenant_id=T1, name="Old", archived=True, sort_order=2)
    c = client(OWNER)
    assert c.post("/api/v1/qr-links", json={"name": "A", "first_message": "Hi", "place_id": theirs["id"]}).status_code == 400
    ok = c.post("/api/v1/qr-links", json={"name": "A", "first_message": "Hi", "place_id": mine["id"]})
    assert ok.json()["place_name"] == "Cafe"
    assert [p["name"] for p in c.get("/api/v1/qr-links").json()["places"]] == ["Cafe"]


def test_places_empty_when_the_table_read_fails(db, monkeypatch):
    real = FakeSupabase.table

    def table(self, name):
        if name == "stock_places":
            raise RuntimeError("no table")
        return real(self, name)
    monkeypatch.setattr(FakeSupabase, "table", table)
    assert svc.load_places(db, T1) == ([], {})
    assert client(OWNER).get("/api/v1/qr-links").json()["places"] == []


def test_patch_edit_archive_and_clear_place(db):
    place = db.add("stock_places", tenant_id=T1, name="Cafe", archived=False, sort_order=1)
    row = link(db, place_id=place["id"])
    c = client(OWNER)
    r = c.patch(f"/api/v1/qr-links/{row['id']}", json={"name": "Counter", "archived": True, "place_id": None})
    body = r.json()
    assert r.status_code == 200 and body["name"] == "Counter" and body["archived"] is True and body["place_id"] is None
    assert db.rows("qr_links")[0]["first_message"] == "Hi, I'm at Table 4"


def test_patch_other_tenants_qr_is_404(db):
    row = link(db, tenant=T2, code="ZZZZZ")
    assert client(OWNER).patch(f"/api/v1/qr-links/{row['id']}", json={"name": "Hacked"}).status_code == 404
    assert db.rows("qr_links")[0]["name"] == "Table 4"


def test_listing_hides_other_tenants_and_puts_archived_last(db):
    link(db, code="AAAAA", archived=True)
    link(db, code="BBBBB")
    link(db, code="CCCCC", tenant=T2)
    codes = [i["code"] for i in client(OWNER).get("/api/v1/qr-links").json()["items"]]
    assert codes == ["BBBBB", "AAAAA"]


def test_stats_and_money(db):
    row = link(db)
    for _ in range(3):
        db.add("qr_events", tenant_id=T1, qr_link_id=row["id"], kind="open")
    db.add("qr_events", tenant_id=T1, qr_link_id=row["id"], kind="chat")
    a = db.add("leads", tenant_id=T1, qr_link_id=row["id"])
    b = db.add("leads", tenant_id=T1, qr_link_id=row["id"])
    db.add("leads", tenant_id=T1, qr_link_id=None)
    db.add("deals", tenant_id=T1, lead_id=a["id"], paid_paise=50000, refunded_paise=10000)
    db.add("deals", tenant_id=T1, lead_id=a["id"], paid_paise=20000, refunded_paise=20000)  # fully refunded
    db.add("deals", tenant_id=T1, lead_id=b["id"], paid_paise=0, refunded_paise=0)
    stats = client(OWNER).get("/api/v1/qr-links").json()["items"][0]["stats"]
    assert stats == {"opens": 3, "chats": 1, "new_customers": 2, "paid_orders": 1, "paid_paise": 40000}


def test_money_hidden_without_deals_view(db):
    row = link(db)
    lead = db.add("leads", tenant_id=T1, qr_link_id=row["id"])
    db.add("deals", tenant_id=T1, lead_id=lead["id"], paid_paise=50000, refunded_paise=0)
    staff = {"tenant_id": T1, "role": "staff", "permissions": ["numbers.view"], "user_id": "u2"}
    stats = client(staff).get("/api/v1/qr-links").json()["items"][0]["stats"]
    assert "paid_paise" not in stats and stats["paid_orders"] == 1
    with_deals = {**staff, "permissions": ["numbers.view", "deals.view"]}
    assert client(with_deals).get("/api/v1/qr-links").json()["items"][0]["stats"]["paid_paise"] == 50000


@pytest.mark.parametrize("perms,get,write", [
    ([], 403, 403),
    (["numbers.view"], 200, 403),
    (["numbers.manage"], 200, 200),
])
def test_permission_gates(db, perms, get, write):
    c = client({"tenant_id": T1, "role": "staff", "permissions": perms, "user_id": "u2"})
    row = link(db)
    assert c.get("/api/v1/qr-links").status_code == get
    assert c.post("/api/v1/qr-links", json={"name": "A", "first_message": "Hi"}).status_code == write
    assert c.patch(f"/api/v1/qr-links/{row['id']}", json={"name": "B"}).status_code == write


# ---------------------------------------------------------------- public

def test_public_redirect_builds_encoded_wa_url_and_logs_open(db):
    link(db, first_message="Hi, I'm at Table 4 & ready!")
    r = client(OWNER).get("/api/v1/public/qr/abcde")
    assert r.status_code == 200
    url = urlparse(r.json()["wa_url"])
    assert url.netloc == "wa.me" and url.path == "/919876543210"
    assert parse_qs(url.query)["text"] == ["Hi, I'm at Table 4 & ready! (Q-ABCDE)"]
    assert "&" not in url.query.split("text=")[1]
    assert [e["kind"] for e in db.rows("qr_events")] == ["open"]


def test_public_unknown_archived_and_malformed_are_the_same_404(db):
    link(db, code="GONE2", archived=True)
    c = client(OWNER)
    bodies = {c.get(f"/api/v1/public/qr/{code}").text for code in ("GONE2", "NOPE9", "x", "a-b-c-d", "TOOLONGCODE1")}
    assert len(bodies) == 1
    assert c.get("/api/v1/public/qr/GONE2").status_code == 404 and db.rows("qr_events") == []


def test_public_404_when_no_whatsapp_number(db):
    link(db, tenant=T2, code="OTHER")
    assert client(OWNER).get("/api/v1/public/qr/OTHER").status_code == 404


def test_public_open_log_failure_never_breaks_the_redirect(db, monkeypatch):
    link(db)
    real = FakeSupabase.table

    def table(self, name):
        if name == "qr_events":
            raise RuntimeError("events down")
        return real(self, name)
    monkeypatch.setattr(FakeSupabase, "table", table)
    r = client(OWNER).get("/api/v1/public/qr/ABCDE")
    assert r.status_code == 200 and "wa.me" in r.json()["wa_url"]


def test_public_rate_limit(db):
    link(db)
    c = client(OWNER)
    codes = [c.get("/api/v1/public/qr/ABCDE").status_code for _ in range(121)]
    assert codes[:120] == [200] * 120 and codes[120] == 429


def test_public_needs_no_login(db):
    link(db)
    app = FastAPI()
    app.include_router(routes.public_router, prefix="/api/v1/public/qr")
    assert TestClient(app).get("/api/v1/public/qr/ABCDE").status_code == 200


# ---------------------------------------------------------------- webhook hook

@pytest.mark.parametrize("text", [
    "Hi, I'm at Table 4 (Q-ABCDE)", "hi (q-abcde)", "(Q-ABCDE)", "Hello\n(Q-ABCDE) thanks",
])
def test_tag_forms_on_a_new_lead(db, text):
    row = link(db)
    lead = db.add("leads", tenant_id=T1, source="whatsapp", opt_in_source="whatsapp")
    assert svc.handle_inbound_qr(db, T1, lead["id"], text, is_new_lead=True) == row["id"]
    got = db.rows("leads")[0]
    assert (got["qr_link_id"], got["source"], got["opt_in_source"]) == (row["id"], "qr", "qr")
    assert [(e["kind"], e["lead_id"]) for e in db.rows("qr_events")] == [("chat", lead["id"])]


@pytest.mark.parametrize("text", ["no tag", "Q-ABCDE", "(Q-ABC)", "(Q-ABCDEFGHI)", "(Q ABCDE)", "", None])
def test_no_tag_does_nothing(db, text):
    link(db)
    lead = db.add("leads", tenant_id=T1)
    assert svc.handle_inbound_qr(db, T1, lead["id"], text, is_new_lead=True) is None
    assert db.rows("qr_events") == [] and "qr_link_id" not in db.rows("leads")[0]


def test_other_tenants_code_is_ignored(db):
    link(db, tenant=T2)
    lead = db.add("leads", tenant_id=T1)
    assert svc.handle_inbound_qr(db, T1, lead["id"], "(Q-ABCDE)", is_new_lead=True) is None
    assert db.rows("qr_events") == []


def test_archived_qr_is_ignored(db):
    link(db, archived=True)
    lead = db.add("leads", tenant_id=T1)
    assert svc.handle_inbound_qr(db, T1, lead["id"], "(Q-ABCDE)", is_new_lead=True) is None


def test_existing_lead_first_touch_rules(db):
    row = link(db)
    fresh = db.add("leads", tenant_id=T1, source="whatsapp")
    from_ad = db.add("leads", tenant_id=T1, ad_campaign_id="camp-1")
    from_other_qr = db.add("leads", tenant_id=T1, qr_link_id="old-qr")
    for lead in (fresh, from_ad, from_other_qr):
        assert svc.handle_inbound_qr(db, T1, lead["id"], "(Q-ABCDE)", is_new_lead=False) == row["id"]
    by_id = {r["id"]: r for r in db.rows("leads")}
    assert by_id[fresh["id"]]["qr_link_id"] == row["id"]
    assert by_id[fresh["id"]]["source"] == "whatsapp"          # source only changes for a brand-new lead
    assert by_id[from_ad["id"]].get("qr_link_id") is None
    assert by_id[from_other_qr["id"]]["qr_link_id"] == "old-qr"
    assert len(db.rows("qr_events")) == 3                       # every tagged chat still counts


def test_other_tenants_lead_is_never_stamped(db):
    link(db)
    foreign = db.add("leads", tenant_id=T2)
    svc.handle_inbound_qr(db, T1, foreign["id"], "(Q-ABCDE)", is_new_lead=True)
    assert "qr_link_id" not in db.rows("leads")[0]


def test_handle_inbound_qr_never_raises(db):
    class Boom:
        def table(self, _):
            raise RuntimeError("db down")
    assert svc.handle_inbound_qr(Boom(), T1, "lead", "(Q-ABCDE)", is_new_lead=True) is None
    assert svc.handle_inbound_qr(db, T1, "", "(Q-ABCDE)", is_new_lead=True) is None


# ---------------------------------------------------------------- review fixes

def test_second_open_from_the_same_visitor_within_10s_is_not_counted(db, monkeypatch):
    link(db)
    clock = [1000.0]
    monkeypatch.setattr(svc.time, "monotonic", lambda: clock[0])
    c = client(OWNER)
    assert c.get("/api/v1/public/qr/ABCDE").status_code == 200
    clock[0] += 5
    assert c.get("/api/v1/public/qr/ABCDE").status_code == 200       # still redirects
    assert len(db.rows("qr_events")) == 1
    clock[0] += 6
    c.get("/api/v1/public/qr/ABCDE")
    assert len(db.rows("qr_events")) == 2


def test_a_different_visitor_or_qr_is_counted_separately(db):
    link(db)
    link(db, code="FGHJK")
    svc.public_redirect(db, "ABCDE", "1.1.1.1")
    svc.public_redirect(db, "ABCDE", "2.2.2.2")
    svc.public_redirect(db, "FGHJK", "1.1.1.1")
    assert len(db.rows("qr_events")) == 3


def test_number_without_digits_is_no_number(db):
    link(db, tenant=T2, code="NODIG")
    db.add("phone_numbers", tenant_id=T2, number="+ - ()", role="primary", status="active")
    assert client(OWNER).get("/api/v1/public/qr/NODIG").status_code == 404
    assert db.rows("qr_events") == []


def test_patch_with_a_non_uuid_id_is_404(db):
    link(db)
    assert client(OWNER).patch("/api/v1/qr-links/not-a-uuid", json={"name": "B"}).status_code == 404


def test_stats_skip_deleted_leads_and_use_counts_not_rows(db, monkeypatch):
    row = link(db)
    db.add("qr_events", tenant_id=T1, qr_link_id=row["id"], kind="open")
    db.add("qr_events", tenant_id=T1, qr_link_id=row["id"], kind="chat")
    db.add("qr_events", tenant_id=T2, qr_link_id=row["id"], kind="open")        # not this business
    live = db.add("leads", tenant_id=T1, qr_link_id=row["id"], deleted_at=None)
    gone = db.add("leads", tenant_id=T1, qr_link_id=row["id"], deleted_at="2026-11-01T00:00:00Z")
    db.add("deals", tenant_id=T1, lead_id=live["id"], paid_paise=1000, refunded_paise=0)
    db.add("deals", tenant_id=T1, lead_id=gone["id"], paid_paise=9000, refunded_paise=0)
    reads = []
    real = FakeSupabase.table
    monkeypatch.setattr(FakeSupabase, "table", lambda self, n: (reads.append(n), real(self, n))[1])
    stats = svc.link_stats(db, T1, [row["id"]], include_money=True)[row["id"]]
    assert stats == {"opens": 1, "chats": 1, "new_customers": 1, "paid_orders": 1, "paid_paise": 1000}
    assert reads.count("qr_events") == 2        # exact counts: one per kind for this QR, no rows read


def test_a_qr_lead_is_a_known_inbound_source():
    """source='qr' (migration 317) must be accepted everywhere a lead's source is checked."""
    from app.models.schemas import Lead
    from app.routes import calls, leads as leads_routes
    from app.services import assignment_rules, inbound_leads_logic

    Lead.model_validate({"id": "00000000-0000-0000-0000-000000000001", "phone": "+919800000001", "source": "qr",
                         "score": 5, "segment": "C", "created_at": "2026-11-23T00:00:00Z",
                         "updated_at": "2026-11-23T00:00:00Z"})
    assert "qr" in leads_routes.INBOUND_SOURCES
    assert "qr" in inbound_leads_logic.INBOUND_SOURCES
    assert "qr" in calls._MESSAGE_LEAD_SOURCES
    assert assignment_rules.SOURCE_TO_ROW["qr"] == "whatsapp"


def test_opens_are_capped_per_code_per_hour_but_the_redirect_still_works(db, monkeypatch):
    link(db)
    clock = [5000.0]
    monkeypatch.setattr(svc.time, "monotonic", lambda: clock[0])
    for i in range(svc.OPEN_CAP_PER_HOUR):               # 300 different visitors inside the hour
        assert svc.public_redirect(db, "ABCDE", f"ip-{i}")
    assert len(db.rows("qr_events")) == svc.OPEN_CAP_PER_HOUR
    assert svc.public_redirect(db, "ABCDE", "one-more").startswith("https://wa.me/")
    assert len(db.rows("qr_events")) == svc.OPEN_CAP_PER_HOUR      # redirect worked, nothing logged
    clock[0] += 3601                                               # an hour later it counts again
    svc.public_redirect(db, "ABCDE", "later")
    assert len(db.rows("qr_events")) == svc.OPEN_CAP_PER_HOUR + 1


def test_cap_is_per_code(db):
    link(db)
    link(db, code="FGHJK")
    svc._open_log_times["ABCDE"] = svc.deque([svc.time.monotonic()] * svc.OPEN_CAP_PER_HOUR)
    svc.public_redirect(db, "ABCDE", "a")
    svc.public_redirect(db, "FGHJK", "a")
    assert [e["qr_link_id"] for e in db.rows("qr_events")] == [db.rows("qr_links")[1]["id"]]

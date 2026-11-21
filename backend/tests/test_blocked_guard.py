"""Full block: a blocked person (leads.blocked_at) gets nothing sent, on any channel.
Core guard, the WhatsApp senders (meta_cloud), and the Instagram / Telegram / Facebook senders (ai_reply).
Other send paths are in test_blocked_guard_paths.py."""
import logging
from types import SimpleNamespace

import pytest

from app.services import ai_reply, blocked_guard, meta_cloud
from app.services.blocked_guard import BLOCKED_DETAIL, RecipientBlocked
from tests.fake_supabase import FakeSupabase

T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
PHONE = "919876543210"
NOW = "2026-11-20T10:00:00+00:00"


def make_db(*leads) -> FakeSupabase:
    db = FakeSupabase()
    for lead in leads:
        db.add("leads", **lead)
    return db


def use_db(monkeypatch, db) -> FakeSupabase:
    monkeypatch.setattr(blocked_guard, "get_supabase", lambda: db)
    blocked_guard.invalidate()
    return db


class FakeHttp:
    """Stands in for httpx.AsyncClient and records every POST (a recorded POST = a message that went out)."""
    posts: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, params=None, **k):
        FakeHttp.posts.append((url, json))
        body = {"messages": [{"id": "wamid.1"}], "message_id": "m.1", "message_id_": "x", "result": {"message_id": 7}}
        return SimpleNamespace(is_success=True, status_code=200, text="", json=lambda: body,
                               raise_for_status=lambda: None)


@pytest.fixture
def http(monkeypatch):
    FakeHttp.posts = []
    monkeypatch.setattr("httpx.AsyncClient", FakeHttp)
    monkeypatch.setattr(meta_cloud, "_creds", lambda *a, **k: ("pid", "tok"))
    monkeypatch.setattr("app.services.outbound_router.count_template_send", lambda *a, **k: None)
    monkeypatch.setattr("app.config_dynamic.get_setting", lambda key, fallback=None, tenant_id=None: "tok")
    return FakeHttp


# ---------------------------------------------------------------- the central check

@pytest.mark.asyncio
async def test_blocked_person_is_found_only_in_their_own_business(monkeypatch):
    use_db(monkeypatch, make_db(
        {"tenant_id": T1, "phone": PHONE, "blocked_at": NOW},
        {"tenant_id": T2, "phone": PHONE, "blocked_at": None},
    ))
    assert await blocked_guard.is_blocked(T1, PHONE) is True
    assert await blocked_guard.is_blocked(T2, PHONE) is False  # same phone, other business


@pytest.mark.asyncio
async def test_unblocked_deleted_and_unknown_people_are_not_blocked(monkeypatch):
    use_db(monkeypatch, make_db(
        {"tenant_id": T1, "phone": "919000000001", "blocked_at": None},
        {"tenant_id": T1, "phone": "919000000002", "blocked_at": NOW, "deleted_at": NOW},
    ))
    for phone in ("919000000001", "919000000002", "919000000003"):
        assert await blocked_guard.is_blocked(T1, phone) is False
    assert await blocked_guard.is_blocked(None, PHONE) is False
    assert await blocked_guard.is_blocked(T1, "") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("sent_to", ["919876543210", "+91 98765 43210", "9876543210", "09876543210", "+91-98765-43210"])
async def test_phone_spellings_are_one_person(monkeypatch, sent_to):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": "+91 98765 43210", "blocked_at": NOW}))
    assert await blocked_guard.is_blocked(T1, sent_to) is True


@pytest.mark.asyncio
async def test_chat_ids_only_match_their_own_channel(monkeypatch):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": None, "tg_user_id": "555", "ig_user_id": "666",
                                 "fb_user_id": "777", "blocked_at": NOW}))
    assert await blocked_guard.is_blocked(T1, "555", "telegram") is True
    assert await blocked_guard.is_blocked(T1, "666", "instagram") is True
    assert await blocked_guard.is_blocked(T1, "777", "facebook") is True
    assert await blocked_guard.is_blocked(T1, "555", "instagram") is False  # a Telegram id is not an Instagram id
    assert await blocked_guard.is_blocked(T1, "555", "whatsapp") is False


@pytest.mark.asyncio
async def test_one_query_serves_many_checks_and_a_new_block_is_seen_at_once(monkeypatch):
    db = use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    reads = []
    real = db.table
    monkeypatch.setattr(db, "table", lambda name: (reads.append(name), real(name))[1])
    for _ in range(50):
        await blocked_guard.is_blocked(T1, PHONE)
    assert reads.count("leads") == 1  # cached: a 5,000-message broadcast is one query a minute
    db.add("leads", tenant_id=T1, phone="919111111111", blocked_at=NOW)
    assert await blocked_guard.is_blocked(T1, "919111111111") is False  # still the cached list
    blocked_guard.invalidate(T1)  # what the block toggle does
    assert await blocked_guard.is_blocked(T1, "919111111111") is True


@pytest.mark.asyncio
async def test_a_failed_lookup_allows_the_send_and_logs_a_warning(monkeypatch, caplog):
    def broken():
        raise RuntimeError("database down")
    monkeypatch.setattr(blocked_guard, "get_supabase", broken)
    blocked_guard.invalidate()
    with caplog.at_level(logging.WARNING, logger="app.services.blocked_guard"):
        assert await blocked_guard.is_blocked(T1, PHONE) is False
    assert "allowing sends" in caplog.text


@pytest.mark.asyncio
async def test_a_failed_refresh_keeps_the_last_good_list(monkeypatch):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    assert await blocked_guard.is_blocked(T1, PHONE) is True
    blocked_guard._cache[T1] = (0.0, blocked_guard._cache[T1][1])  # expired

    def broken():
        raise RuntimeError("blip")
    monkeypatch.setattr(blocked_guard, "get_supabase", broken)
    assert await blocked_guard.is_blocked(T1, PHONE) is True  # stale list beats no list


# ---------------------------------------------------------------- WhatsApp senders

@pytest.mark.asyncio
async def test_text_to_a_blocked_person_is_refused_before_any_request(monkeypatch, http):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    with pytest.raises(RecipientBlocked) as err:
        await meta_cloud.send_text_message(PHONE, "hi", tenant_id=T1)
    assert err.value.status_code == 409 and err.value.detail == BLOCKED_DETAIL
    assert http.posts == []


@pytest.mark.asyncio
async def test_every_whatsapp_sender_is_guarded(monkeypatch, http):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    calls = [
        lambda: meta_cloud.send_text_message(PHONE, "hi", tenant_id=T1),
        lambda: meta_cloud.send_template_message(PHONE, "offer", "en", tenant_id=T1),
        lambda: meta_cloud.send_media_message(PHONE, wa_type="image", media_link="https://x/y.png", tenant_id=T1),
        lambda: meta_cloud.send_audio_message(PHONE, "https://x/y.ogg", tenant_id=T1),
        lambda: meta_cloud.send_location_message(PHONE, 1.0, 2.0, tenant_id=T1),
        lambda: meta_cloud.send_cta_url_message(PHONE, "pay", "Pay", "https://x/pay", tenant_id=T1),
        lambda: meta_cloud.send_interactive_buttons(PHONE, "pick", [{"id": "a", "title": "A"}], tenant_id=T1),
        lambda: meta_cloud.send_list_message(PHONE, "pick", "Open", [{"title": "S", "rows": [{"id": "1", "title": "One"}]}], tenant_id=T1),
        lambda: meta_cloud.send_catalog_message(PHONE, "see", "cat1", [], tenant_id=T1),
        lambda: meta_cloud.send_flow_message(PHONE, "form", "flow1", "tok", "Open", "SCREEN", tenant_id=T1),
    ]
    for call in calls:
        with pytest.raises(RecipientBlocked):
            await call()
    assert http.posts == []


@pytest.mark.asyncio
async def test_unblocked_and_other_business_still_get_their_message(monkeypatch, http):
    use_db(monkeypatch, make_db(
        {"tenant_id": T1, "phone": "919000000001", "blocked_at": None},
        {"tenant_id": T1, "phone": PHONE, "blocked_at": NOW},
    ))
    await meta_cloud.send_text_message("919000000001", "hi", tenant_id=T1)      # not blocked
    await meta_cloud.send_text_message(PHONE, "hi", tenant_id=T2)               # blocked only in business 1
    await meta_cloud.send_template_message("919000000001", "offer", "en", tenant_id=T1)
    assert len(http.posts) == 3


@pytest.mark.asyncio
async def test_otp_style_and_staff_alert_sends_are_exempt(monkeypatch, http):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    await meta_cloud.send_template_message(PHONE, "otp", "en", tenant_id=T1, skip_blocked_check=True)
    assert len(http.posts) == 1


@pytest.mark.asyncio
async def test_the_otp_service_sends_to_a_blocked_phone(monkeypatch, http):
    from app.services import otp
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    monkeypatch.setattr(otp, "_update", lambda db, rid, patch, **k: {"id": rid, **patch})
    monkeypatch.setattr(otp, "emit", lambda *a, **k: None)
    row = {"id": "o1", "phone": PHONE}
    cfg = {"wa_template_name": "otp", "wa_template_language": "en"}
    out = await otp._send_whatsapp(FakeSupabase(), T1, row, "123456", cfg)
    assert out["whatsapp_status"] == "sent" and len(http.posts) == 1


@pytest.mark.asyncio
async def test_the_sending_number_decides_the_business_when_none_is_given(monkeypatch, http):
    db = use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    db.add("phone_numbers", tenant_id=T1, meta_phone_number_id="pn-1")
    with pytest.raises(RecipientBlocked):
        await meta_cloud.send_text_message(PHONE, "hi", phone_number_id="pn-1")
    assert http.posts == []


# ---------------------------------------------------------------- AI reply / chat-channel senders

@pytest.mark.asyncio
async def test_ai_reply_send_to_a_blocked_person_returns_not_sent(monkeypatch, http):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    assert await ai_reply.send_whatsapp(PHONE, "hello", tenant_id=T1) is None
    assert ai_reply.get_last_send_error() == BLOCKED_DETAIL
    assert http.posts == []


@pytest.mark.asyncio
async def test_ai_reply_send_to_an_unblocked_person_goes_out(monkeypatch, http):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": None}))
    assert await ai_reply.send_whatsapp(PHONE, "hello", tenant_id=T1) == "wamid.1"
    assert len(http.posts) == 1


@pytest.mark.asyncio
async def test_a_blocked_send_raises_no_system_failure_alert(monkeypatch, http):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": PHONE, "blocked_at": NOW}))
    alerts = []
    monkeypatch.setattr("app.services.notify.notify_user", lambda *a, **k: alerts.append(a))
    await ai_reply.send_whatsapp(PHONE, "hello", tenant_id=T1)
    assert alerts == []


@pytest.mark.asyncio
async def test_instagram_telegram_facebook_sends_to_a_blocked_person_return_not_sent(monkeypatch, http):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": None, "ig_user_id": "i1", "tg_user_id": "t1",
                                 "fb_user_id": "f1", "blocked_at": NOW}))
    assert await ai_reply.send_instagram("i1", "hi", tenant_id=T1) is None
    assert await ai_reply.send_telegram("t1", "hi", tenant_id=T1) is None
    assert await ai_reply.send_facebook("f1", "hi", tenant_id=T1) is None
    assert http.posts == []


@pytest.mark.asyncio
async def test_instagram_to_an_unblocked_person_still_goes_out(monkeypatch, http):
    use_db(monkeypatch, make_db({"tenant_id": T1, "phone": None, "ig_user_id": "i1", "blocked_at": None}))
    assert await ai_reply.send_instagram("i1", "hi", tenant_id=T1) == "m.1"

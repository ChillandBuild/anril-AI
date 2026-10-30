"""Expiry bookkeeping around regenerated payment links: a late "old link expired" webhook
must not clear a session that now holds a newer link, and the stored expiry is the one
Razorpay reports, not just the one we computed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import deal_engine
from app.services import payment_razorpay as pr
from app.services.intake import expire_intake_session


class _RecordingDb:
    """Records every chained call on intake_sessions so the filters can be asserted."""

    def __init__(self, rows):
        self.calls = []
        self._rows = rows

    def table(self, name):
        return _Chain(self.calls, self._rows)


class _Chain:
    def __init__(self, calls, rows):
        self._calls = calls
        self._rows = rows

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self._calls.append((name, args))
            return self

        return _record

    def execute(self):
        result = MagicMock()
        result.data = self._rows
        return result


def test_expiry_webhook_only_clears_a_link_that_is_unknown_or_past():
    db = _RecordingDb([{"id": "s1"}])
    with patch("app.services.intake._sync_deal"):
        assert expire_intake_session("s1", db=db) is True
    calls = dict(db.calls)
    assert ("eq", ("status", "awaiting_payment")) in db.calls
    (or_filter,) = calls["or_"]
    assert or_filter.startswith("payment_link_expires_at.is.null,payment_link_expires_at.lte.")
    assert or_filter.endswith("Z")
    update_payload = calls["update"][0]
    # D2: only the link dies; the deal stays open, so no status is written.
    assert update_payload == {"payment_link": None, "payment_link_expires_at": None}


def test_expiry_webhook_for_a_session_that_moved_on_reports_ignored():
    db = _RecordingDb([])
    with patch("app.services.intake._sync_deal"):
        assert expire_intake_session("s1", db=db) is False


@pytest.mark.asyncio
async def test_stored_expiry_is_the_one_razorpay_reports():
    reported = 1_900_000_000
    fake_resp = MagicMock(is_success=True)
    fake_resp.json.return_value = {"short_url": "https://rzp.io/abc", "id": "plink_1", "expire_by": reported}
    client = AsyncMock()
    client.post.return_value = fake_resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    with patch.object(pr, "get_setting", side_effect=["k", "s"]), \
         patch.object(pr.razorpay_oauth, "get_access_token", AsyncMock(return_value=None)), \
         patch("httpx.AsyncClient", return_value=client):
        out = await pr.create_payment_link("key", {}, 100, "A", "+91", "d", tenant_id="t")
    assert datetime.fromisoformat(out["payment_link_expires_at"]) == datetime.fromtimestamp(reported, tz=timezone.utc)


@pytest.mark.parametrize("stored", [
    "2999-01-01 06:57:20.903532+00",   # Supabase's own format
    "2999-01-01T06:57:20+00:00",
    "2999-01-01 06:57:20+00",
])
def test_supabase_style_timestamps_count_as_live(stored):
    session = {"status": "awaiting_payment", "payment_link": "https://rzp.io/x", "amount_paise": 100,
               "payment_link_expires_at": stored}
    assert deal_engine.link_is_live(session, 100) is True


def test_naive_timestamp_is_read_as_utc_and_garbage_counts_as_expired():
    session = {"status": "awaiting_payment", "payment_link": "https://rzp.io/x", "amount_paise": 100}
    assert deal_engine.link_is_live({**session, "payment_link_expires_at": "2999-01-01 00:00:00"}, 100) is True
    assert deal_engine.link_is_live({**session, "payment_link_expires_at": "not a date"}, 100) is False

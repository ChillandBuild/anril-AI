"""The read-only RPC allowlist: only vetted, SELECT-only functions pass; every write RPC stays blocked.

Each allowed name was checked against its function body in pg_proc (2026-11-23). If you add a
name to READ_ONLY_RPCS, check the body the same way and add it here.
"""
from unittest.mock import MagicMock

import pytest

from app.db import supabase as supabase_db

VETTED = {
    "distinct_token_usage_pairs",
    "analytics_daily_leads",
    "analytics_daily_messages",
    "analytics_daily_returning_ad_leads",
    "analytics_lead_arrival_heatmap",
    "analytics_period_money",
    "analytics_period_summary",
    "analytics_reply_sources",
    "analytics_response_times",
    "analytics_segment_movement",
    "get_telecalling_all_time_stats",
    "template_performance_range",
}


def test_the_allowlist_is_exactly_the_vetted_set():
    assert set(supabase_db.READ_ONLY_RPCS) == VETTED


@pytest.mark.parametrize("name", sorted(VETTED))
def test_a_vetted_rpc_passes_in_read_only_mode(name):
    inner = MagicMock()
    guarded = supabase_db._ReadOnlyClient(inner)
    guarded.rpc(name, {"p_tenant_id": "t1"})
    inner.rpc.assert_called_once_with(name, {"p_tenant_id": "t1"})


@pytest.mark.parametrize("name", ["claude_reserve_sends", "claude_release_sends", "increment_usage", "anything_else"])
def test_any_other_rpc_is_refused_in_read_only_mode(name):
    inner = MagicMock()
    guarded = supabase_db._ReadOnlyClient(inner)
    with pytest.raises(supabase_db.ReadOnlyViolation):
        guarded.rpc(name, {})
    inner.rpc.assert_not_called()

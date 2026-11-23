"""Tests for GET /api/v1/analytics/overview -- the tenant home dashboard's
data source. Covers the prior-window trend fields (D6 of the 2026-07-28
dashboard redesign spec): daily_leads_trend_pct, converted_7d_trend_pct,
new_hot_leads_7d / new_hot_leads_7d_trend_pct."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role


class AnalyticsOverviewTrendTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "tenant-1", "role": "owner", "permissions": [],
        }

    def tearDown(self):
        app.dependency_overrides.clear()

    def _mock_db(self, mock_get_db, leads_rows, prior_leads_rows, msgs_rows,
                 handover_count=0):
        db = MagicMock()

        leads_tbl = MagicMock()
        leads_chain = leads_tbl.select.return_value.eq.return_value.is_.return_value
        leads_chain.range.return_value.execute.return_value = MagicMock(data=leads_rows)
        # prior-window leads fetch adds .gte().lt()
        leads_chain.gte.return_value.lt.return_value.range.return_value.execute.return_value = MagicMock(data=prior_leads_rows)

        msgs_tbl = MagicMock()
        msgs_tbl.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(data=msgs_rows)

        def table(name):
            return {"leads": leads_tbl, "messages": msgs_tbl}[name]

        db.table.side_effect = table
        mock_get_db.return_value = db
        return db

    @patch("app.routes.analytics.get_supabase")
    def test_daily_leads_trend_pct_none_when_no_prior_baseline(self, mock_get_db):
        self._mock_db(mock_get_db, leads_rows=[], prior_leads_rows=[], msgs_rows=[])

        res = self.client.get("/api/v1/analytics/overview?range=7d")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIsNone(body["daily_leads_trend_pct"])
        self.assertIsNone(body["converted_7d_trend_pct"])
        self.assertIsNone(body["new_hot_leads_7d_trend_pct"])

    @patch("app.routes.analytics.get_supabase")
    def test_ad_attributed_leads_counts_leads_with_ad_campaign_id(self, mock_get_db):
        current_leads = [
            {"id": "l1", "created_at": "2026-07-20T10:00:00+00:00", "segment": "C",
             "source": "whatsapp", "converted_at": None, "ad_campaign_id": "camp-1"},
            {"id": "l2", "created_at": "2026-07-20T10:00:00+00:00", "segment": "C",
             "source": "whatsapp", "converted_at": None, "ad_campaign_id": None},
        ]
        self._mock_db(mock_get_db, leads_rows=current_leads, prior_leads_rows=[],
                       msgs_rows=[])

        res = self.client.get("/api/v1/analytics/overview?range=7d")
        body = res.json()
        self.assertEqual(body["ad_attributed_leads"], 1)

    @patch("app.routes.analytics.get_supabase")
    def test_daily_leads_trend_pct_computed_against_prior_window(self, mock_get_db):
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone.utc).date().isoformat()
        prior_day = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()

        current_leads = [{"id": f"l{i}", "created_at": f"{today}T10:00:00+00:00", "segment": "C",
                           "source": "whatsapp", "converted_at": None} for i in range(3)]
        prior_leads = [{"id": f"p{i}", "created_at": f"{prior_day}T10:00:00+00:00", "segment": "C",
                         "source": "whatsapp", "converted_at": None} for i in range(2)]

        self._mock_db(mock_get_db, leads_rows=current_leads, prior_leads_rows=prior_leads,
                       msgs_rows=[])

        res = self.client.get("/api/v1/analytics/overview?range=7d")
        body = res.json()
        # 3 current vs 2 prior -> +50%
        self.assertEqual(body["daily_leads_trend_pct"], 50)

    @patch("app.routes.analytics.get_supabase")
    def test_converted_7d_trend_uses_full_lead_population_not_just_prior_created(self, mock_get_db):
        """Regression: prior_converted_7d must scan the full leads_rows
        population bounded to the prior window, not leads *created* in the
        prior window (a lead can be created weeks earlier and convert this
        week) -- and must not double-count conversions that already landed
        in the current window's own converted_7d."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        prior_window_conversion = now - timedelta(days=10)  # inside prior window (7d range -> [-14d, -7d))
        current_window_conversion = now - timedelta(days=2)  # inside current window, must NOT count as prior

        leads_rows = [
            # created 30 days ago (outside both windows) but converted inside
            # the PRIOR window -- must count.
            {"id": "l1", "created_at": (now - timedelta(days=30)).isoformat(),
             "converted_at": prior_window_conversion.isoformat(), "segment": "A", "source": "whatsapp"},
            # created 30 days ago, converted inside the CURRENT window --
            # already counted in converted_7d, must NOT also land in prior_converted_7d.
            {"id": "l2", "created_at": (now - timedelta(days=30)).isoformat(),
             "converted_at": current_window_conversion.isoformat(), "segment": "A", "source": "whatsapp"},
        ]
        self._mock_db(mock_get_db, leads_rows=leads_rows, prior_leads_rows=[], msgs_rows=[])

        res = self.client.get("/api/v1/analytics/overview?range=7d")
        body = res.json()
        self.assertEqual(body["converted_7d"], 1)  # only l2
        # prior=1 (l1), current=1 (l2) -> 0% change
        self.assertEqual(body["converted_7d_trend_pct"], 0)

    @patch("app.routes.analytics.get_supabase")
    def test_new_hot_leads_7d_counts_new_leads_currently_hot_not_rescoring_events(self, mock_get_db):
        """new_hot_leads_7d = leads created in-window whose CURRENT segment is
        A -- not a count of lead_stage_events rows. A lead already Hot that
        gets rescored 5x today (event_type='score_updated' each time, per
        ai_reply.py) must not inflate this past the number of distinct leads."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        leads_rows = [
            {"id": "l1", "created_at": f"{today}T09:00:00+00:00", "segment": "A",
             "source": "whatsapp", "converted_at": None},
            {"id": "l2", "created_at": f"{today}T11:00:00+00:00", "segment": "A",
             "source": "whatsapp", "converted_at": None},
            # Segment B lead created today must not count as hot.
            {"id": "l3", "created_at": f"{today}T12:00:00+00:00", "segment": "B",
             "source": "whatsapp", "converted_at": None},
        ]
        self._mock_db(mock_get_db, leads_rows=leads_rows, prior_leads_rows=[], msgs_rows=[])

        res = self.client.get("/api/v1/analytics/overview?range=7d")
        body = res.json()
        self.assertEqual(body["new_hot_leads_7d"], 2)
        self.assertIsInstance(body["new_hot_leads_daily"], list)
        self.assertIsNone(body["new_hot_leads_7d_trend_pct"])  # empty prior window

    @patch("app.routes.analytics.get_supabase")
    def test_channel_breakdown_today_and_ad_attributed_today_only_count_todays_leads(self, mock_get_db):
        from datetime import datetime, timezone, timedelta
        # Stamp from `now` rather than building "{utc_date}T09:00:00+00:00": the
        # today-scoped fields bucket by IST calendar date, so between 18:30 and 00:00
        # UTC the UTC date is a day behind IST and a "today" fixture built that way
        # lands on the previous IST day.
        now = datetime.now(timezone.utc)
        today_ts = now.isoformat()
        yesterday_ts = (now - timedelta(days=1)).isoformat()

        leads_rows = [
            {"id": "l1", "created_at": today_ts, "segment": "A",
             "source": "whatsapp", "converted_at": None, "ad_campaign_id": "camp-1"},
            {"id": "l2", "created_at": today_ts, "segment": "B",
             "source": "instagram", "converted_at": None, "ad_campaign_id": None},
            {"id": "l3", "created_at": yesterday_ts, "segment": "C",
             "source": "whatsapp", "converted_at": None, "ad_campaign_id": "camp-2"},
        ]
        self._mock_db(mock_get_db, leads_rows=leads_rows, prior_leads_rows=[], msgs_rows=[])

        res = self.client.get("/api/v1/analytics/overview?range=7d")
        body = res.json()
        # All 3 leads count toward the all-time fields.
        self.assertEqual(body["channel_breakdown"]["whatsapp"], 2)
        self.assertEqual(body["ad_attributed_leads"], 2)
        self.assertEqual(body["by_segment"]["A"], 1)
        self.assertEqual(body["by_segment"]["C"], 1)
        # Only l1/l2 (today) count toward the today-scoped fields; yesterday's
        # l3 (whatsapp, ad-attributed, segment C) must not leak in.
        self.assertEqual(body["channel_breakdown_today"]["whatsapp"], 1)
        self.assertEqual(body["channel_breakdown_today"]["instagram"], 1)
        self.assertEqual(body["ad_attributed_leads_today"], 1)
        self.assertEqual(body["by_segment_today"], {"A": 1, "B": 1, "C": 0, "D": 0})

    @patch("app.routes.analytics.get_supabase")
    def test_channel_breakdown_7d_counts_the_last_seven_ist_days_only(self, mock_get_db):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        stamp = lambda days: (now - timedelta(days=days)).isoformat()
        leads_rows = [
            {"id": "l1", "created_at": stamp(0), "segment": "C", "source": "whatsapp",
             "converted_at": None, "ad_campaign_id": None},
            {"id": "l2", "created_at": stamp(6), "segment": "C", "source": "whatsapp",   # oldest day of the 7
             "converted_at": None, "ad_campaign_id": None},
            {"id": "l3", "created_at": stamp(3), "segment": "C", "source": "instagram",
             "converted_at": None, "ad_campaign_id": None},
            {"id": "l4", "created_at": stamp(7), "segment": "C", "source": "whatsapp",   # one day too old
             "converted_at": None, "ad_campaign_id": None},
            {"id": "l5", "created_at": stamp(30), "segment": "C", "source": "meta_form",
             "converted_at": None, "ad_campaign_id": None},
            {"id": "l6", "created_at": stamp(1), "segment": "C", "source": "not_a_channel",
             "converted_at": None, "ad_campaign_id": None},
        ]
        self._mock_db(mock_get_db, leads_rows=leads_rows, prior_leads_rows=[], msgs_rows=[])

        # same answer whichever range the page asked for: it is always the last 7 IST days
        for rng in ("today", "7d", "30d"):
            body = self.client.get(f"/api/v1/analytics/overview?range={rng}").json()
            week = body["channel_breakdown_7d"]
            self.assertEqual(set(week), set(body["channel_breakdown"]))
            self.assertEqual(week["whatsapp"], 2)
            self.assertEqual(week["instagram"], 1)
            self.assertEqual(week["meta_form"], 0)
            # the all-time and today fields are unchanged
            self.assertEqual(body["channel_breakdown"]["whatsapp"], 3)
            self.assertEqual(body["channel_breakdown_today"]["whatsapp"], 1)

    @patch("app.services.ai_setup_report._counts_in_database")
    @patch("app.routes.analytics.get_supabase")
    def test_couldnt_answer_today_is_the_report_cards_gap_count_for_todays_range(self, mock_get_db, mock_counts):
        mock_counts.return_value = {"chats": 9, "handled_by_aira": 5, "handed_over": 3, "knowledge_gaps": 4}
        self._mock_db(mock_get_db, leads_rows=[], prior_leads_rows=[], msgs_rows=[])

        body = self.client.get("/api/v1/analytics/overview?range=7d").json()

        self.assertEqual(body["couldnt_answer_today"], 4)
        _db, tenant_id, period = mock_counts.call_args.args
        self.assertEqual(tenant_id, "tenant-1")
        self.assertEqual(period.days, 1)                 # today alone, in IST
        self.assertEqual(period.start, period.end)

    @patch("app.services.ai_setup_report._counts_in_database", side_effect=RuntimeError("rpc down"))
    @patch("app.routes.analytics.get_supabase")
    def test_couldnt_answer_today_falls_back_to_zero_and_never_breaks_the_overview(self, mock_get_db, _mock_counts):
        self._mock_db(mock_get_db, leads_rows=[], prior_leads_rows=[], msgs_rows=[])

        res = self.client.get("/api/v1/analytics/overview?range=7d")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["couldnt_answer_today"], 0)

    @patch("app.services.ai_setup_report._counts_in_database", return_value=None)
    @patch("app.routes.analytics.get_supabase")
    def test_couldnt_answer_today_is_zero_when_the_database_function_is_missing(self, mock_get_db, _mock_counts):
        self._mock_db(mock_get_db, leads_rows=[], prior_leads_rows=[], msgs_rows=[])
        self.assertEqual(self.client.get("/api/v1/analytics/overview?range=7d").json()["couldnt_answer_today"], 0)


if __name__ == "__main__":
    unittest.main()

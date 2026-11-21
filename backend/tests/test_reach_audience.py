"""Reach audiences: the 2-offers-a-month limit, blocked people, the Meta cost line, and a
Customers group as the audience (services/reach_audience.py), on the in-memory fake database.

tenant-1 is the caller's; tenant-2 has the same phone numbers and must never change a count.
"""
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, settings
from app.services import reach_audience as ra
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
OWNER = {"tenant_id": T1, "role": "owner", "user_id": "user-1", "permissions": []}


def U(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "anril-reach:" + name))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# 2026-11-20 10:00 UTC = 15:30 IST. The IST month started 2026-10-31T18:30:00Z.
NOW = utc(2026, 11, 20, 10, 0)


def sent(db, phone, broadcast, at, tenant=T1, status="sent"):
    db.rows("broadcast_recipients").append({
        "id": str(uuid.uuid4()), "tenant_id": tenant, "broadcast_id": broadcast, "phone": phone,
        "send_status": status, "created_at": at.isoformat()})


class MonthBoundaryTests(unittest.TestCase):
    def test_month_starts_at_midnight_ist_on_the_first(self):
        self.assertEqual(ra.month_start_utc(NOW), utc(2026, 10, 31, 18, 30))

    def test_late_evening_ist_on_the_last_day_is_still_the_old_month(self):
        # 2026-11-30 23:30 IST = 18:00 UTC: still November, which began 2026-10-31T18:30Z.
        self.assertEqual(ra.month_start_utc(utc(2026, 11, 30, 18, 0)), utc(2026, 10, 31, 18, 30))

    def test_just_after_midnight_ist_is_the_new_month(self):
        # 2026-12-01 00:15 IST = 2026-11-30 18:45 UTC.
        self.assertEqual(ra.month_start_utc(utc(2026, 11, 30, 18, 45)), utc(2026, 11, 30, 18, 30))


class MonthlyCountTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()

    def test_counts_distinct_reach_campaigns_this_ist_month_per_person(self):
        sent(self.db, "+919876543210", "b1", utc(2026, 11, 2, 5, 0))
        sent(self.db, "+919876543210", "b2", utc(2026, 11, 10, 5, 0))
        sent(self.db, "+919876543211", "b1", utc(2026, 11, 2, 5, 0))
        counts = ra.monthly_counts(self.db, T1, {"919876543210", "919876543211"}, now=NOW)
        self.assertEqual(counts, {"919876543210": 2, "919876543211": 1})

    def test_boundary_is_ist_not_utc(self):
        # 17:00 UTC on Oct 31 = 22:30 IST Oct 31: October. 19:00 UTC = 00:30 IST Nov 1: November.
        sent(self.db, "+919876543210", "old", utc(2026, 10, 31, 17, 0))
        sent(self.db, "+919876543210", "new", utc(2026, 10, 31, 19, 0))
        counts = ra.monthly_counts(self.db, T1, {"919876543210"}, now=NOW)
        self.assertEqual(counts, {"919876543210": 1})

    def test_only_sent_rows_count_not_failed_or_skipped(self):
        sent(self.db, "+919876543210", "b1", utc(2026, 11, 2), status="failed")
        sent(self.db, "+919876543210", "b2", utc(2026, 11, 3), status="opted_out_skip")
        sent(self.db, "+919876543210", "b3", utc(2026, 11, 4), status="rejected")
        self.assertEqual(ra.monthly_counts(self.db, T1, {"919876543210"}, now=NOW), {})

    def test_other_tenants_rows_never_count(self):
        sent(self.db, "+919876543210", "b1", utc(2026, 11, 2), tenant=T2)
        sent(self.db, "+919876543210", "b2", utc(2026, 11, 3), tenant=T2)
        self.assertEqual(ra.monthly_counts(self.db, T1, {"919876543210"}, now=NOW), {})

    def test_one_campaign_counts_once_even_with_two_rows(self):
        sent(self.db, "+919876543210", "b1", utc(2026, 11, 2))
        sent(self.db, "+919876543210", "b1", utc(2026, 11, 2, 1))
        self.assertEqual(ra.monthly_counts(self.db, T1, {"919876543210"}, now=NOW), {"919876543210": 1})

    def test_the_running_campaign_is_left_out(self):
        sent(self.db, "+919876543210", "b1", utc(2026, 11, 2))
        sent(self.db, "+919876543210", "running", utc(2026, 11, 20, 9, 0))
        counts = ra.monthly_counts(self.db, T1, {"919876543210"}, now=NOW, exclude_broadcast_id="running")
        self.assertEqual(counts, {"919876543210": 1})

    def test_other_spellings_of_the_same_phone_are_one_person(self):
        sent(self.db, "919876543210", "b1", utc(2026, 11, 2))          # no plus
        sent(self.db, "+919876543210", "b2", utc(2026, 11, 3))
        self.assertEqual(ra.monthly_counts(self.db, T1, {ra.phone_key("98765 43210")}, now=NOW), {"919876543210": 2})


class SendTimeSkipTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        for phone, extra in (("+919000000001", {}), ("+919000000002", {}), ("+919000000003", {"blocked_at": "2026-11-01"})):
            self.db.rows("leads").append({"id": phone, "tenant_id": T1, "phone": phone, "deleted_at": None, **extra})
        # The same number as 0003, blocked in ANOTHER tenant only.
        self.db.rows("leads").append({"id": "x", "tenant_id": T2, "phone": "+919000000001", "blocked_at": "2026-11-01"})

    def test_two_campaigns_this_month_is_over_the_cap_and_one_is_not(self):
        sent(self.db, "+919000000001", "b1", utc(2026, 11, 2))
        sent(self.db, "+919000000001", "b2", utc(2026, 11, 3))
        sent(self.db, "+919000000002", "b1", utc(2026, 11, 2))
        blocked, over = ra.send_time_skips(self.db, T1, ["+919000000001", "+919000000002", "+919000000003"], now=NOW)
        self.assertEqual(over, {"919000000001"})
        self.assertEqual(blocked, {"919000000003"})  # tenant-2's block on 0001 does not leak

    def test_the_limit_is_two(self):
        self.assertEqual(ra.MONTHLY_LIMIT, 2)

    def test_a_lookup_error_fails_open_not_closed(self):
        with patch.object(ra, "_lead_flags", side_effect=RuntimeError("db down")), \
                patch.object(ra, "monthly_counts", side_effect=RuntimeError("db down")):
            self.assertEqual(ra.send_time_skips(self.db, T1, ["+919000000001"], now=NOW), (set(), set()))


class CostLineTests(unittest.TestCase):
    def test_default_rate_is_the_meta_india_marketing_rate(self):
        self.assertEqual(Settings.model_fields["meta_marketing_rate_inr"].default, 0.8631)

    def test_cost_is_will_get_times_the_setting(self):
        with patch.object(settings, "meta_marketing_rate_inr", 0.8631):
            self.assertEqual(ra.cost_for(8), {"rate_inr": 0.8631, "cost_inr": 6.9})
            self.assertEqual(ra.cost_for(0)["cost_inr"], 0)
        with patch.object(settings, "meta_marketing_rate_inr", 1.25):
            self.assertEqual(ra.cost_for(8), {"rate_inr": 1.25, "cost_inr": 10.0})

    def test_the_preview_cost_uses_only_the_people_who_will_get_it(self):
        db = FakeSupabase()
        db.rows("leads").append({"id": "s", "tenant_id": T1, "phone": "+919000000001", "opted_out": True, "deleted_at": None})
        people = [{"phone": "+919000000001", "opted_in": True}, {"phone": "+919000000002", "opted_in": True}]
        with patch.object(settings, "meta_marketing_rate_inr", 2.0):
            out = ra.preview_numbers(db, T1, people, now=NOW)
        self.assertEqual((out["said_stop"], out["will_get"], out["cost_inr"], out["rate_inr"]), (1, 1, 2.0, 2.0))


class ClassifyTests(unittest.TestCase):
    def test_every_person_lands_in_one_bucket_in_order(self):
        db = FakeSupabase()
        def lead(phone, **extra):
            db.rows("leads").append({"id": phone, "tenant_id": T1, "phone": phone, "deleted_at": None, **extra})
        lead("+919000000001", opted_out=True)
        lead("+919000000002", blocked_at="2026-11-01")
        lead("+919000000003")
        lead("+919000000004", opted_out=True, blocked_at="2026-11-01")   # stopped AND blocked: counted once, as stop
        for b in ("b1", "b2"):
            sent(db, "+919000000003", b, utc(2026, 11, 5))
        sent(db, "+919000000002", "b1", utc(2026, 11, 5))
        sent(db, "+919000000002", "b2", utc(2026, 11, 5))                # blocked AND over the cap: counted once, as blocked
        people = [{"phone": f"+9190000000{n:02d}", "opted_in": True} for n in (1, 2, 3, 4, 5)]
        people += [{"phone": "+919000000006", "opted_in": False}, {"phone": "not a phone", "opted_in": True}]
        out = ra.classify_people(db, T1, people, now=NOW)
        self.assertEqual(
            {k: out[k] for k in ("total", "invalid", "no_opt_in", "said_stop", "blocked", "over_cap", "will_get")},
            {"total": 6, "invalid": 1, "no_opt_in": 1, "said_stop": 2, "blocked": 1, "over_cap": 1, "will_get": 1})

    def test_cap_applies_to_an_uploaded_contact_who_is_not_a_lead_yet(self):
        db = FakeSupabase()
        sent(db, "+919111111111", "b1", utc(2026, 11, 5))
        sent(db, "+919111111111", "b2", utc(2026, 11, 6))
        out = ra.classify_people(db, T1, [{"phone": "91111 11111", "opted_in": True}], now=NOW)
        self.assertEqual((out["over_cap"], out["will_get"]), (1, 0))

    def test_include_opted_out_lets_stopped_people_through(self):
        db = FakeSupabase()
        db.rows("leads").append({"id": "a", "tenant_id": T1, "phone": "+919000000001", "opted_out": True, "deleted_at": None})
        out = ra.classify_people(db, T1, [{"phone": "+919000000001", "opted_in": True}], include_opted_out=True, now=NOW)
        self.assertEqual((out["said_stop"], out["will_get"]), (0, 1))


class GroupAudienceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.picked = U("picked")
        self.rule = U("rule")
        self.other_group = U("other-group")

        def lead(name, phone, tenant=T1, **extra):
            row = {"id": U(name), "tenant_id": tenant, "name": name, "phone": phone, "source": "whatsapp",
                   "opt_in_source": "website", "created_at": "2026-01-01T00:00:00+00:00", "deleted_at": None,
                   "opted_out": None, "whatsapp_undeliverable": None, **extra}
            self.db.rows("leads").append(row)
            return row

        lead("ann", "+919000000001", segment="A")
        lead("bob", "+919000000002", segment="A", opted_out=True)                  # said stop
        lead("cat", "+919000000003", segment="B")                                  # no opt-in below
        lead("dev", "+919000000004", segment="A", blocked_at="2026-11-01")         # blocked
        lead("eli", "ig_998877", segment="A", source="instagram")                  # no WhatsApp number
        lead("fay", "+919000000006", segment="A", deleted_at="2026-02-01")         # deleted
        lead("gus", "+919000000007", segment="A", whatsapp_undeliverable=True)     # undeliverable
        lead("hal", "+919000000008", segment="A", opt_in_source="manual")          # manual = no opt-in
        self.db.rows("leads")[2]["opt_in_source"] = None
        lead("zed", "+919000000001", tenant=T2, segment="A")                       # same phone, other tenant
        self.db.rows("customer_groups").append({"id": self.picked, "tenant_id": T1, "name": "Insta Hot", "kind": "picked"})
        self.db.rows("customer_groups").append({"id": self.rule, "tenant_id": T1, "name": "Hot people", "kind": "rule",
                                                "rule": {"segment": "A"}})
        self.db.rows("customer_groups").append({"id": self.other_group, "tenant_id": T2, "name": "Theirs", "kind": "picked"})
        for n in ("ann", "bob", "cat", "dev", "eli", "fay", "gus", "hal"):
            self.db.rows("customer_group_members").append({"group_id": self.picked, "lead_id": U(n), "tenant_id": T1})
        self.db.rows("customer_group_members").append({"group_id": self.other_group, "lead_id": U("zed"), "tenant_id": T2})

    def test_a_picked_group_is_its_members_with_the_exclusions_counted(self):
        out = ra.resolve_group(self.db, OWNER, self.picked)
        self.assertEqual(out["group"], {"id": self.picked, "name": "Insta Hot", "kind": "picked"})
        phones = {p["phone"] for p in out["people"]}
        # ann, cat (no opt-in, still returned but flagged), dev (blocked, flagged later), hal (manual).
        self.assertEqual(phones, {"+919000000001", "+919000000003", "+919000000004", "+919000000008"})
        self.assertEqual({p["name"] for p in out["people"] if p["opted_in"]}, {"ann", "dev"})
        self.assertEqual(out["stopped"], 1)           # bob
        self.assertEqual(out["no_whatsapp"], 1)       # eli
        # Members as the Groups table counts them: deleted (fay) and undeliverable (gus) are not in it.
        self.assertEqual(out["members"], 4 + 1 + 1)

    def test_a_rule_group_is_worked_out_from_its_filters(self):
        out = ra.resolve_group(self.db, OWNER, self.rule)
        self.assertEqual({p["name"] for p in out["people"]}, {"ann", "dev", "hal"})
        self.assertEqual(out["stopped"], 1)           # bob: Hot and said stop
        self.assertEqual(out["no_whatsapp"], 1)       # eli

    def test_another_tenants_group_reads_as_missing(self):
        with self.assertRaises(ra.GroupNotFound):
            ra.resolve_group(self.db, OWNER, self.other_group)

    def test_a_missing_group_reads_as_missing(self):
        with self.assertRaises(ra.GroupNotFound):
            ra.resolve_group(self.db, OWNER, U("nope"))

    def test_the_confirm_numbers_for_a_group(self):
        resolved = ra.resolve_group(self.db, OWNER, self.picked)
        people = [{"phone": p["phone"], "opted_in": p["opted_in"]} for p in resolved["people"]]
        for b in ("b1", "b2"):
            sent(self.db, "+919000000001", b, utc(2026, 11, 5))     # ann already got 2 this month
        out = ra.classify_people(self.db, T1, people, now=NOW)
        self.assertEqual((out["no_opt_in"], out["blocked"], out["over_cap"], out["will_get"]), (2, 1, 1, 0))


if __name__ == "__main__":
    unittest.main()

"""Regression: Reach > Opted-Out showed nobody even though a lead had said stop (2026-11-26).

The per-tag query embedded broadcast_tags(name), but lead_tag_opt_outs has no foreign key to
broadcast_tags, so PostgREST failed the whole request and the page fell back to an empty list.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes import upload


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, table):
        self.table, self.cols = table, ""

    def select(self, cols, *_a, **_k):
        self.cols = cols
        return self

    def __getattr__(self, _name):  # eq / order / limit / in_ / not_ / is_ are no-ops
        return lambda *a, **k: self

    @property
    def not_(self):
        return self

    def execute(self):
        if self.table == "lead_tag_opt_outs" and "broadcast_tags(" in self.cols:
            raise Exception("Could not find a relationship between 'lead_tag_opt_outs' and 'broadcast_tags'")
        if self.table == "leads":
            return _Res([{"id": "L1", "phone": "+916382546876", "name": "Dinaharan P", "opted_out_at": "2026-11-24T10:15:02+00:00"}])
        if self.table == "lead_tag_opt_outs":
            return _Res([{"lead_id": "L2", "tag_id": "T1", "opted_out_at": "2026-11-25T10:00:00+00:00",
                          "leads": {"phone": "+919000000000", "name": "Tag Person"}}])
        if self.table == "broadcast_tags":
            return _Res([{"id": "T1", "name": "Hosts"}])
        return _Res([])


class _DB:
    def table(self, name):
        return _Q(name)


def test_opted_out_list_shows_people_who_said_stop(monkeypatch):
    monkeypatch.setattr(upload, "get_supabase", lambda: _DB())
    rows = asyncio.run(upload.list_opted_out_leads(tenant_id="t1"))["data"]
    assert [(r["name"], r["scope"], r["tag_name"]) for r in rows] == [
        ("Dinaharan P", "global", None),
        ("Tag Person", "tag", "Hosts"),
    ]

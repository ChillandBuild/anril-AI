"""Inbound Leads: first-message keyword and campaign name per lead.

Regression for 2026-11-09 (Astro Tamil - ORG): the newest leads showed
"no message yet" because the keyword fetch read every inbound message and
PostgREST returns at most 1000 rows; organic leads showed "Unknown Campaign".
"""
from app.routes.inbound_leads import _enrich, _fetch_first_keywords

PG_CAP = 1000


class _Result:
    def __init__(self, data):
        self.data = data


class _CappedQuery:
    """Any table query: returns at most PG_CAP rows, oldest first, like PostgREST."""

    def __init__(self, messages):
        self._messages = messages

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        rows = sorted(self._messages, key=lambda m: m["created_at"])
        return _Result([dict(r) for r in rows[:PG_CAP]])


class _Rpc:
    def __init__(self, db, name, params):
        self._db, self._name, self._params = db, name, params

    def execute(self):
        self._db.rpc_calls.append((self._name, self._params))
        assert self._name == "first_inbound_messages"
        wanted = set(self._params["p_lead_ids"])
        first: dict[str, dict] = {}
        for m in sorted(self._db.messages, key=lambda m: m["created_at"]):
            if m["lead_id"] in wanted and m["lead_id"] not in first:
                first[m["lead_id"]] = {"lead_id": m["lead_id"], "content": m["content"]}
        rows = list(first.values())
        assert len(rows) <= PG_CAP
        return _Result(rows)


class FakeDb:
    def __init__(self, messages):
        self.messages = messages
        self.rpc_calls = []

    def table(self, _name):
        return _CappedQuery(self.messages)

    def rpc(self, name, params):
        return _Rpc(self, name, params)


def _messages(n_leads: int, per_lead: int):
    """Lead i joins at time i and sends per_lead messages; lead n-1 is the newest."""
    out = []
    for i in range(n_leads):
        for j in range(per_lead):
            out.append({
                "lead_id": f"lead-{i}",
                "content": f"first from {i}" if j == 0 else f"later {j}",
                "created_at": f"2026-11-09T{i:05d}.{j:03d}",
            })
    return out


def test_newest_leads_keep_their_keyword_past_the_1000_row_cap():
    # 200 leads x 6 messages = 1200 rows, more than one capped response.
    db = FakeDb(_messages(200, 6))
    lead_ids = [f"lead-{i}" for i in range(200)]

    keywords = _fetch_first_keywords(db, "tenant-1", lead_ids)

    assert len(keywords) == 200
    assert keywords["lead-199"] == "first from 199"  # the newest lead
    assert keywords["lead-0"] == "first from 0"


def test_big_export_is_split_into_chunks_under_the_cap():
    db = FakeDb(_messages(1200, 1))
    lead_ids = [f"lead-{i}" for i in range(1200)]

    keywords = _fetch_first_keywords(db, "tenant-1", lead_ids)

    assert len(keywords) == 1200
    assert all(len(p["p_lead_ids"]) <= 500 for _, p in db.rpc_calls)
    assert all(p["p_tenant"] == "tenant-1" for _, p in db.rpc_calls)


def test_no_leads_makes_no_call():
    db = FakeDb([])
    assert _fetch_first_keywords(db, "tenant-1", []) == {}
    assert db.rpc_calls == []


def _lead(**over):
    base = {"id": "l1", "phone": "+919000011201", "source": "whatsapp", "segment": "B", "created_at": "2026-11-09"}
    return {**base, **over}


def test_organic_lead_has_no_campaign_name():
    [row] = _enrich([_lead(ad_campaign_id=None)], {}, {})
    assert row["origin"] == "organic"
    assert row["campaign_name"] == "—"


def test_ad_lead_shows_its_campaign_name():
    [row] = _enrich([_lead(ad_campaign_id="c1")], {"c1": "Diwali Jathagam Offer"}, {})
    assert row["origin"] == "ad"
    assert row["campaign_name"] == "Diwali Jathagam Offer"


def test_ad_lead_with_unknown_campaign_id_says_unknown():
    [row] = _enrich([_lead(ad_campaign_id="gone")], {}, {})
    assert row["campaign_name"] == "Unknown Campaign"


def test_instant_form_lead_without_campaign_id_has_no_campaign_name():
    [row] = _enrich([_lead(ad_campaign_id=None, source="meta_form")], {}, {})
    assert row["origin"] == "ad"
    assert row["campaign_name"] == "—"

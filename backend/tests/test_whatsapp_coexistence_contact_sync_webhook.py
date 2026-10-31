import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, Request

from app.routes import webhook


class _Result:
    def __init__(self, data):
        self.data = data


class _RouteTable:
    def __init__(self, name, captured_updates, lead_rows, lead_selects):
        self.name = name
        self.captured_updates = captured_updates
        self.lead_rows = lead_rows
        self.lead_selects = lead_selects
        self.operation = "select"
        self._update_payload = None
        self._eq = {}
        self._in = {}

    def select(self, *_args, **_kwargs):
        self.operation = "select"
        return self

    def update(self, row):
        self.operation = "update"
        self._update_payload = row
        return self

    def eq(self, col, value=None, **_kwargs):
        self._eq[col] = value
        return self

    def in_(self, col, values):
        self._in[col] = list(values)
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self.name == "phone_numbers":
            return _Result({"tenant_id": "tenant-1"})
        if self.name == "leads" and self.operation == "select":
            self.lead_selects.append({"eq": dict(self._eq), "in": dict(self._in)})
            phones = self._in.get("phone") or [self._eq.get("phone")]
            return _Result([r for r in self.lead_rows if r["phone"] in phones])
        if self.name == "leads" and self.operation == "update":
            self.captured_updates.append({"lead_id": self._eq["id"], **self._update_payload})
            return _Result([])
        return _Result([])


def _route_db(captured_updates, lead_row=None, lead_rows=None, lead_selects=None):
    rows = lead_rows if lead_rows is not None else (
        [{"phone": "+919999999999", **lead_row}] if lead_row else []
    )
    selects = lead_selects if lead_selects is not None else []
    db = MagicMock()
    db.table.side_effect = lambda name: _RouteTable(name, captured_updates, rows, selects)
    return db


def _state_sync_payload(phone="919999999999", full_name="Ravi Kumar", action="add", contacts=None):
    contacts = contacts or [(phone, full_name)]
    return {
        "entry": [{
            "changes": [{
                "field": "smb_app_state_sync",
                "value": {
                    "metadata": {"phone_number_id": "phone-number-1"},
                    "state_sync": [{
                        "type": "contact",
                        "contact": {"full_name": name, "first_name": name.split(" ")[0], "phone_number": p},
                        "action": action,
                        "metadata": {"timestamp": "1700000000"},
                    } for p, name in contacts],
                },
            }],
        }],
    }


async def _post_webhook(db, payload):
    request = MagicMock(spec=Request)
    request.body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
    request.headers = {"x-hub-signature-256": "sha256=test"}
    background_tasks = MagicMock(spec=BackgroundTasks)
    with patch("app.routes.webhook.get_supabase", return_value=db), \
         patch("app.routes.webhook.verify_meta_signature", return_value=True):
        return await webhook.whatsapp_webhook(request, background_tasks)


@pytest.mark.asyncio
async def test_matched_contact_with_blank_name_gets_enriched():
    captured: list[dict] = []
    db = _route_db(captured, lead_row={"id": "lead-1", "name": None})

    response = await _post_webhook(db, _state_sync_payload())

    assert response == {"status": "ok"}
    assert captured == [{"lead_id": "lead-1", "name": "Ravi Kumar"}]


@pytest.mark.asyncio
async def test_matched_contact_with_existing_name_is_not_overwritten():
    captured: list[dict] = []
    db = _route_db(captured, lead_row={"id": "lead-1", "name": "Already Named"})

    await _post_webhook(db, _state_sync_payload())

    assert captured == []


@pytest.mark.asyncio
async def test_unmatched_contact_writes_nothing():
    captured: list[dict] = []
    db = _route_db(captured, lead_row=None)

    await _post_webhook(db, _state_sync_payload())

    assert captured == []


@pytest.mark.asyncio
async def test_remove_action_writes_nothing_even_if_matched():
    captured: list[dict] = []
    db = _route_db(captured, lead_row={"id": "lead-1", "name": None})

    await _post_webhook(db, _state_sync_payload(action="remove"))

    assert captured == []


@pytest.mark.asyncio
async def test_a_300_contact_sync_looks_leads_up_in_bulk_not_one_by_one():
    # Regression (2026-10-31): Meta re-sends a coexistence tenant's whole contact list
    # every ~27 min, and one leads lookup per contact was 15,879 requests a day.
    contacts = [(f"9190000{i:05d}", f"Contact {i}") for i in range(300)]
    lead_rows = [
        {"id": "lead-nameless", "phone": "+919000000007", "name": None},
        {"id": "lead-named", "phone": "+919000000099", "name": "Already Named"},
    ]
    captured: list[dict] = []
    selects: list[dict] = []
    db = _route_db(captured, lead_rows=lead_rows, lead_selects=selects)

    await _post_webhook(db, _state_sync_payload(contacts=contacts))

    assert len(selects) <= 2
    assert all(s["eq"].get("tenant_id") == "tenant-1" for s in selects)
    assert sorted(p for s in selects for p in s["in"]["phone"]) == sorted(f"+{p}" for p, _ in contacts)
    assert sorted(captured, key=lambda u: u["lead_id"]) == [
        {"lead_id": "lead-nameless", "name": "Contact 7"},
    ]


@pytest.mark.asyncio
async def test_a_sync_with_no_usable_contacts_makes_no_lookup():
    captured: list[dict] = []
    selects: list[dict] = []
    db = _route_db(captured, lead_rows=[], lead_selects=selects)

    await _post_webhook(db, _state_sync_payload(full_name="  "))

    assert selects == [] and captured == []

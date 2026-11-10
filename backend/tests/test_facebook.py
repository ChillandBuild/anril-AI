# backend/tests/test_facebook.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import Request, BackgroundTasks
from fastapi.responses import Response
from app.routes.facebook import facebook_webhook, verify_facebook_webhook


@pytest.mark.asyncio
async def test_verify_facebook_webhook_success():
    mock_request = MagicMock(spec=Request)
    mock_request.query_params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "my-verify-token",
        "hub.challenge": "challenge-fb-123",
    }

    with patch("app.routes.facebook.get_setting", return_value="my-verify-token"):
        response = await verify_facebook_webhook(
            tenant_id="tenant-123",
            request=mock_request,
        )
        assert isinstance(response, Response)
        assert response.status_code == 200
        assert response.body == b"challenge-fb-123"


@pytest.mark.asyncio
async def test_facebook_webhook_new_lead():
    mock_payload = {
        "object": "page",
        "entry": [
            {
                "id": "fb-page-id-999",
                "time": 1716223400,
                "messaging": [
                    {
                        "sender": {"id": "fb-user-777"},
                        "recipient": {"id": "fb-page-id-999"},
                        "timestamp": 1716223400,
                        "message": {
                            "mid": "mid.facebook.99999",
                            "text": "Hello Facebook",
                        },
                    }
                ],
            }
        ],
    }

    import json
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=mock_payload)
    mock_request.body = AsyncMock(return_value=json.dumps(mock_payload).encode("utf-8"))
    mock_background_tasks = MagicMock(spec=BackgroundTasks)

    mock_db = MagicMock()

    # 1. Lead exists check — empty (new lead)
    mock_execute_leads = MagicMock()
    mock_execute_leads.data = []

    # 2. Insert lead — returns created row
    mock_execute_new_lead = MagicMock()
    mock_execute_new_lead.data = [{"id": "lead-facebook-1"}]

    # 3. Duplicate message check — empty
    mock_execute_messages = MagicMock()
    mock_execute_messages.data = []

    # 4. First inbound check returns empty
    mock_execute_is_first = MagicMock()
    mock_execute_is_first.data = []

    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.side_effect = [
        mock_execute_leads,     # leads look-up
        mock_execute_messages,  # messages dedup check
        mock_execute_is_first,  # first inbound check
    ]
    mock_db.table.return_value.insert.return_value.execute.side_effect = [
        mock_execute_new_lead,  # insert lead
        MagicMock(),            # insert message
    ]

    with patch("app.routes.facebook.get_supabase", return_value=mock_db), \
         patch("app.routes.facebook.verify_meta_signature", return_value=True), \
         patch("app.routes.facebook.resolve_tenant_for_page", return_value="tenant-123"), \
         patch("app.routes.facebook.record_stage_event") as mock_record_event, \
         patch("app.services.assignment.assign_by_rule"), \
         patch("app.services.conversation_state.get_or_create_state", return_value={"message_count": 0}), \
         patch("app.services.context_builder.build_scorer_context", return_value="ctx"):

        response = await facebook_webhook(
            tenant_id="tenant-123",
            request=mock_request,
            background_tasks=mock_background_tasks,
        )

        assert response == {"status": "ok"}
        mock_db.table.assert_any_call("leads")
        mock_db.table.assert_any_call("messages")
        mock_record_event.assert_called_once_with(
            "lead-facebook-1",
            to_segment="C",
            event_type="created",
            metadata={"source": "facebook"},
            tenant_id="tenant-123",
            db=mock_db,
        )
        assert mock_background_tasks.add_task.call_count >= 1


@pytest.mark.asyncio
async def test_facebook_webhook_ignores_echo():
    """Echo messages (is_echo=True) should be silently skipped."""
    mock_payload = {
        "object": "page",
        "entry": [
            {
                "id": "fb-page-id-999",
                "messaging": [
                    {
                        "sender": {"id": "fb-page-id-999"},
                        "recipient": {"id": "fb-user-888"},
                        "message": {"mid": "mid.echo.111", "text": "Echo reply", "is_echo": True},
                    }
                ],
            }
        ],
    }
    import json
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=mock_payload)
    mock_request.body = AsyncMock(return_value=json.dumps(mock_payload).encode("utf-8"))
    mock_background_tasks = MagicMock(spec=BackgroundTasks)

    mock_db = MagicMock()
    with patch("app.routes.facebook.get_supabase", return_value=mock_db), \
         patch("app.routes.facebook.verify_meta_signature", return_value=True), \
         patch("app.routes.facebook.resolve_tenant_for_page", return_value="tenant-123"):
        response = await facebook_webhook(
            tenant_id="tenant-123",
            request=mock_request,
            background_tasks=mock_background_tasks,
        )
        assert response == {"status": "ok"}
        # DB should NOT be touched for lead/message inserts
        mock_background_tasks.add_task.assert_not_called()

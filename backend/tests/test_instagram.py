# backend/tests/test_instagram.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import Request, BackgroundTasks
from fastapi.responses import Response
from app.routes.instagram import instagram_webhook, verify_instagram_webhook

@pytest.mark.asyncio
async def test_verify_instagram_webhook_success():
    mock_request = MagicMock(spec=Request)
    mock_request.query_params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "my-verify-token",
        "hub.challenge": "challenge-code-abc"
    }

    with patch("app.routes.instagram.get_setting", return_value="my-verify-token"):
        response = await verify_instagram_webhook(
            tenant_id="tenant-123",
            request=mock_request
        )
        assert isinstance(response, Response)
        assert response.status_code == 200
        assert response.body == b"challenge-code-abc"


@pytest.mark.asyncio
async def test_instagram_webhook_new_lead():
    mock_payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "ig-page-id",
                "time": 1716223400,
                "messaging": [
                    {
                        "sender": {"id": "ig-user-888"},
                        "recipient": {"id": "ig-page-id"},
                        "timestamp": 1716223400,
                        "message": {
                            "mid": "mid.instagram.12345",
                            "text": "Hello Instagram"
                        }
                    }
                ]
            }
        ]
    }

    import json
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=mock_payload)
    mock_request.body = AsyncMock(return_value=json.dumps(mock_payload).encode("utf-8"))

    mock_background_tasks = MagicMock(spec=BackgroundTasks)

    # Mock DB queries
    mock_db = MagicMock()
    
    # 1. Lead exists check returns empty data (new lead)
    mock_execute_leads = MagicMock()
    mock_execute_leads.data = []
    
    # 2. Insert lead returns created lead
    mock_execute_new_lead = MagicMock()
    mock_execute_new_lead.data = [{"id": "lead-instagram-1"}]
    
    # 3. Duplicate check returns empty
    mock_execute_messages = MagicMock()
    mock_execute_messages.data = []

    # 4. First inbound check returns empty
    mock_execute_is_first = MagicMock()
    mock_execute_is_first.data = []

    # Setup mock chain
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.side_effect = [
        mock_execute_leads,      # first call: select leads
        mock_execute_messages,   # second call: select messages (duplicate check)
        mock_execute_is_first,   # third call: select messages (is first check)
    ]
    mock_db.table.return_value.insert.return_value.execute.side_effect = [
        mock_execute_new_lead,   # insert into leads
        MagicMock()              # insert into messages
    ]

    with patch("app.routes.instagram.get_supabase", return_value=mock_db), \
         patch("app.routes.instagram.verify_meta_signature", return_value=True), \
         patch("app.routes.instagram.resolve_tenant_for_page", return_value="tenant-123"), \
         patch("app.routes.instagram.record_stage_event") as mock_record_event, \
         patch("app.services.assignment.assign_by_rule") as mock_auto_assign, \
         patch("app.services.conversation_state.get_or_create_state", return_value={"message_count": 0}), \
         patch("app.services.context_builder.build_scorer_context", return_value="context block"):

        response = await instagram_webhook(
            tenant_id="tenant-123",
            request=mock_request,
            background_tasks=mock_background_tasks
        )

        assert response == {"status": "ok"}
        
        # Verify lead creation and events recorded
        mock_db.table.assert_any_call("leads")
        mock_db.table.assert_any_call("messages")
        mock_record_event.assert_called_once_with(
            "lead-instagram-1",
            to_segment="C",
            event_type="created",
            metadata={"source": "instagram"},
            tenant_id="tenant-123",
            db=mock_db
        )
        assert mock_background_tasks.add_task.call_count >= 1

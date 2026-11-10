# backend/tests/test_telegram.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import Request, BackgroundTasks
from app.routes.telegram import telegram_webhook

@pytest.mark.asyncio
async def test_telegram_webhook_new_lead():
    # Mock Request JSON
    mock_payload = {
        "update_id": 12345,
        "message": {
            "message_id": 999,
            "from": {
                "id": 8888,
                "first_name": "Test",
                "last_name": "User",
                "username": "testuser",
                "is_bot": False
            },
            "chat": {
                "id": 8888,
                "first_name": "Test",
                "last_name": "User",
                "username": "testuser",
                "type": "private"
            },
            "date": 1716223400,
            "text": "Hello Aira"
        }
    }

    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=mock_payload)
    mock_request.headers = {"X-Telegram-Bot-Api-Secret-Token": "my-telegram-secret"}

    mock_background_tasks = MagicMock(spec=BackgroundTasks)

    # Mock DB queries
    mock_db = MagicMock()
    
    # 1. Lead exists check returns empty data (new lead)
    mock_execute_leads = MagicMock()
    mock_execute_leads.data = []
    
    # 2. Insert lead returns created lead
    mock_execute_new_lead = MagicMock()
    mock_execute_new_lead.data = [{"id": "lead-telegram-1"}]
    
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

    with patch("app.routes.telegram.get_supabase", return_value=mock_db), \
         patch("app.routes.telegram.get_setting", return_value="my-telegram-secret"), \
         patch("app.routes.telegram.record_stage_event") as mock_record_event, \
         patch("app.services.assignment.assign_by_rule") as mock_auto_assign, \
         patch("app.services.conversation_state.get_or_create_state", return_value={"message_count": 0}), \
         patch("app.services.context_builder.build_scorer_context", return_value="context block"):

        response = await telegram_webhook(
            tenant_id="tenant-123",
            request=mock_request,
            background_tasks=mock_background_tasks
        )

        assert response == {"status": "ok"}
        
        # Verify lead creation and events recorded
        mock_db.table.assert_any_call("leads")
        mock_db.table.assert_any_call("messages")
        mock_record_event.assert_called_once_with(
            "lead-telegram-1",
            to_segment="C",
            event_type="created",
            metadata={"source": "telegram"},
            tenant_id="tenant-123",
            db=mock_db
        )
        assert mock_background_tasks.add_task.call_count >= 1

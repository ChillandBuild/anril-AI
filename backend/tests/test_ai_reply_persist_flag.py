"""build_reply_system_prompt(persist=False) is read-only.

Its only write is the tamil_locked flip in _resolve_tamil_lock. The operator
"What Aira saw" reconstruction passes persist=False so viewing a lead can never
change it -- and the prompt must come out identical to a persist=True build.
"""
from unittest.mock import MagicMock, patch

from app.services import ai_reply
from app.services import intake

TAMIL_ASK = "தமிழ்ல பேசுங்க"


def _build(db, **kwargs):
    with patch.object(ai_reply, "_build_base_prompt", return_value="BASE"), \
         patch.object(ai_reply, "_fetch_conversation_summary", return_value=""), \
         patch.object(ai_reply, "_fetch_call_context", return_value=None), \
         patch.object(ai_reply, "_resolve_reply_language_mode", return_value="tanglish_escalate_tamil"), \
         patch("app.config_dynamic.get_setting", return_value=""), \
         patch("app.services.business_details.get_business_details", return_value={}), \
         patch.object(intake, "get_intake_config", return_value={"enabled": False}), \
         patch("app.services.form_answers_ai.prompt_block", return_value=""):  # a read of leads.collected_data
        return ai_reply.build_reply_system_prompt(
            db, "lead-1", "t-1", {"phone": "+910000000000"}, TAMIL_ASK, **kwargs
        )


def _lead_updates(db):
    return [c for c in db.table.call_args_list if c.args == ("leads",)]


def test_persist_false_performs_no_lead_update():
    db = MagicMock()
    _build(db, persist=False)
    assert db.table.return_value.update.call_count == 0
    assert _lead_updates(db) == []


def test_persist_true_default_still_writes_tamil_lock():
    db = MagicMock()
    _build(db)
    db.table.return_value.update.assert_called_once_with({"tamil_locked": True})


def test_persist_false_prompt_and_mode_match_persist_true():
    read_only = _build(MagicMock(), persist=False)
    writing = _build(MagicMock(), persist=True)
    assert read_only == writing
    assert read_only[1] == "tamil"


def test_resolve_tamil_lock_persist_false_returns_tamil_without_write():
    db = MagicMock()
    mode = ai_reply._resolve_tamil_lock(db, "lead-1", {}, TAMIL_ASK, persist=False)
    assert mode == "tamil"
    db.table.assert_not_called()

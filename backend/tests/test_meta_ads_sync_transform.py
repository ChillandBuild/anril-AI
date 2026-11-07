import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.meta_ads_insights_sync import sum_actions


def test_sum_actions_matches_types():
    actions = [
        {"action_type": "onsite_conversion.total_messaging_connection", "value": "12"},
        {"action_type": "link_click", "value": "40"},
        {"action_type": "post_engagement", "value": "99"},
    ]
    assert sum_actions(actions, {"onsite_conversion.total_messaging_connection"}) == 12
    assert sum_actions(actions, {"link_click"}) == 40
    assert sum_actions(actions, {"nonexistent"}) == 0


def test_sum_actions_handles_empty():
    assert sum_actions([], {"link_click"}) == 0
    assert sum_actions(None, {"link_click"}) == 0

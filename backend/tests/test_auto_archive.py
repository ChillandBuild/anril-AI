"""auto-archive-idle (migration 274): one call to the SQL function for every tenant, 30 days,
run off the event loop; a manual archive clears the automatic marker."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import auto_archive
from tests.fake_supabase import FakeSupabase


class AutoArchiveTests(unittest.TestCase):
    def test_calls_the_sql_function_once_with_30_days_and_returns_the_count(self):
        db = FakeSupabase()
        calls = []
        db.rpc_handlers["auto_archive_idle_chats"] = lambda params: calls.append(params) or 951
        with patch.object(auto_archive, "get_supabase", return_value=db):
            archived = asyncio.run(auto_archive.archive_idle_chats())
        self.assertEqual(archived, 951)
        self.assertEqual(calls, [{"p_days": 30}])

    def test_nothing_idle_is_zero_not_none(self):
        db = FakeSupabase()
        db.rpc_handlers["auto_archive_idle_chats"] = lambda params: None
        with patch.object(auto_archive, "get_supabase", return_value=db):
            self.assertEqual(asyncio.run(auto_archive.archive_idle_chats()), 0)


if __name__ == "__main__":
    unittest.main()

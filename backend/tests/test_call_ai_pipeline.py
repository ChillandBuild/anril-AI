"""The durable recording pipeline: claiming, stages, retries, the restart sweep, and the
new v4 flow (per-track transcription -> sorting -> marking -> alerts -> check 10)."""
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import call_ai_pipeline as pipe
from app.services.call_lines import Line
from app.services.call_marking import CHECKS, MarkResult
from app.services.call_sorting import SortResult
from app.services.call_transcribe import TrackTranscript


class _Res:
    def __init__(self, data):
        self.data = data


def _json_path_get(row: dict, path: str):
    """Resolve a postgrest-style 'a->b->>c' column path against a nested dict."""
    value = row
    for part in re.split(r"->>|->", path):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload, self.filters = db, table, "select", None, []

    def select(self, *a, **k):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        self.filters.append(lambda r: r.get(col) in vals)
        return self

    def lt(self, col, val):
        self.filters.append(lambda r: (r.get(col) or "") < val)
        return self

    def is_(self, col, val):
        getter = (lambda r: _json_path_get(r, col)) if "->" in col else (lambda r: r.get(col))
        self.filters.append((lambda r: getter(r) is None) if val == "null" else (lambda r: getter(r) is not None))
        return self

    def order(self, col, desc=False, **k):
        self.order_col, self.order_desc = col, desc
        return self

    def limit(self, *a):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        rows = [r for r in self.db.rows.get(self.table, []) if all(f(r) for f in self.filters)]
        if getattr(self, "order_col", None):
            rows = sorted(rows, key=lambda r: r.get(self.order_col) or "", reverse=self.order_desc)
        if self.op == "update":
            for r in rows:
                r.update(self.payload)
            self.db.updates.append((self.table, dict(self.payload)))
            return _Res([dict(r) for r in rows])
        if self.op == "insert":
            self.db.inserts.append((self.table, self.payload))
            return _Res([self.payload])
        if getattr(self, "single", False):
            return _Res(dict(rows[0]) if rows else None)
        return _Res([dict(r) for r in rows])


class FakeDB:
    def __init__(self, **rows):
        self.rows = rows
        self.updates, self.inserts = [], []
        self.storage = MagicMock()
        self.storage.from_.return_value.get_public_url.return_value = "https://storage.test/c1.mp3"

    def table(self, name):
        return _Q(self, name)

    def row(self):
        return self.rows["call_logs"][0]


def _call(**over):
    row = {"id": "c1", "tenant_id": "t1", "caller_id": "k1", "lead_id": "l1", "duration_seconds": 240,
           "recording_url": "https://storage.test/c1.mp3", "recording_filename": "rec.mp3",
           "ai_status": "pending", "ai_attempts": 0, "ai_updated_at": "2026-09-24T00:00:00+00:00"}
    row.update(over)
    return row


class ClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_finished_or_exhausted_calls_are_not_claimed(self):
        for row in (_call(ai_status="done"), _call(ai_status="failed"), _call(ai_attempts=2)):
            db = FakeDB(call_logs=[row])
            self.assertIsNone(pipe._claim(db, "c1"))

    async def test_claim_is_lost_when_another_worker_gets_there_first(self):
        """The webhook task and the sweep can't both process one call."""
        db = FakeDB(call_logs=[_call()])
        real_table = db.table

        def table(name):
            query = real_table(name)
            real_update = query.update

            def update(payload):
                db.row()["ai_attempts"] = 1  # the other worker claimed between our read and write
                return real_update(payload)

            query.update = update
            return query

        db.table = table
        self.assertIsNone(pipe._claim(db, "c1"))

    async def test_claim_bumps_the_attempt_and_moves_to_transcribing(self):
        db = FakeDB(call_logs=[_call(ai_attempts=1, ai_status="transcribing")])
        self.assertEqual(pipe._claim(db, "c1")["ai_attempts"], 2)
        self.assertEqual(db.row()["ai_status"], "transcribing")


def _tracks():
    return TrackTranscript([Line(1, "telecaller", "Hello"), Line(3, "customer", "I need a demo")], [(1.0, 2.0)], [(3.0, 5.0)], True)


def _sort(group):
    early = None if group == "real_conversation" else {"polite": True, "rude_quote": None, "enquiry_confirmed_early": False, "expected_crm": "other", "crm_matches": None}
    return SortResult(group, [], {"next_action": "Call back"}, early, False, None, None)


class NewFlowTests(unittest.IsolatedAsyncioTestCase):
    async def _process(self, db, row, group):
        marking = MarkResult(checks=[{"key": c["key"], "full": c["full"], "level": "good" if c["key"] != "crm_update" else None} for c in CHECKS])
        with patch.object(pipe, "_load_audio", AsyncMock(return_value=(b"wav", "audio/wav"))), \
             patch.object(pipe, "transcribe_tracks", AsyncMock(return_value=_tracks())), \
             patch.object(pipe, "sort_call", AsyncMock(return_value=_sort(group))), \
             patch.object(pipe, "mark_call", AsyncMock(return_value=marking)) as mark, \
             patch.object(pipe, "raise_alert") as alert, \
             patch("app.services.knowledge_service.get_knowledge_context", AsyncMock(return_value="")):
            await pipe._process(db, row, None)
        return mark, alert

    async def test_very_short_call_is_never_transcribed(self):
        db = MagicMock()
        with patch.object(pipe, "transcribe_tracks", AsyncMock()) as tr:
            await pipe._process(db, {"id": "c", "tenant_id": "t", "duration_seconds": 20}, None)
        tr.assert_not_called()

    async def test_early_exit_skips_marking(self):
        mark, _ = await self._process(MagicMock(), {"id": "c", "tenant_id": "t", "duration_seconds": 90, "lead_id": None}, "early_exit")
        mark.assert_not_called()

    async def test_real_conversation_is_marked(self):
        mark, _ = await self._process(MagicMock(), {"id": "c", "tenant_id": "t", "duration_seconds": 90, "lead_id": None}, "real_conversation")
        mark.assert_called_once()

    async def test_kb_context_is_fetched_once_and_shared_with_sort_and_mark(self):
        marking = MarkResult(checks=[{"key": c["key"], "full": c["full"], "level": "good" if c["key"] != "crm_update" else None} for c in CHECKS])
        kb_mock = AsyncMock(return_value="Sells billing software")
        with patch.object(pipe, "_load_audio", AsyncMock(return_value=(b"wav", "audio/wav"))), \
             patch.object(pipe, "transcribe_tracks", AsyncMock(return_value=_tracks())), \
             patch.object(pipe, "sort_call", AsyncMock(return_value=_sort("real_conversation"))) as sort_mock, \
             patch.object(pipe, "mark_call", AsyncMock(return_value=marking)) as mark_mock, \
             patch.object(pipe, "raise_alert"), \
             patch("app.services.knowledge_service.get_knowledge_context", kb_mock):
            await pipe._process(MagicMock(), {"id": "c", "tenant_id": "t", "duration_seconds": 90, "lead_id": None}, None)
        kb_mock.assert_awaited_once()
        self.assertEqual(sort_mock.call_args.kwargs["kb_context"], "Sells billing software")
        self.assertEqual(mark_mock.call_args.kwargs["kb_context"], "Sells billing software")


class RunCallAiTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_path_finalizes_score_and_checks_crm(self):
        db = FakeDB(call_logs=[_call()])
        with patch.object(pipe, "get_supabase", return_value=db), \
             patch.object(pipe, "_process", AsyncMock()), \
             patch.object(pipe, "finalize_call_score") as finalize, \
             patch.object(pipe, "mark_crm_update", AsyncMock()) as crm:
            await pipe.run_call_ai("c1")
        finalize.assert_called_once_with(db, "c1")
        crm.assert_awaited_once_with(db, "c1")

    async def test_non_final_failure_goes_back_to_pending_without_an_alert(self):
        db = FakeDB(call_logs=[_call()])
        with patch.object(pipe, "get_supabase", return_value=db), \
             patch.object(pipe, "_process", AsyncMock(side_effect=RuntimeError("gemini 503"))), \
             patch.object(pipe, "raise_alert") as alert, \
             patch.object(pipe, "finalize_call_score"), \
             patch.object(pipe, "mark_crm_update", AsyncMock()):
            await pipe.run_call_ai("c1")
        self.assertEqual(db.row()["ai_status"], "pending")
        self.assertIn("gemini 503", db.row()["ai_error"])
        alert.assert_not_called()

    async def test_final_failure_is_marked_failed_and_raises_a_transcript_failed_alert(self):
        db = FakeDB(call_logs=[_call(ai_attempts=1)])  # bumped to MAX_ATTEMPTS(2) on claim
        with patch.object(pipe, "get_supabase", return_value=db), \
             patch.object(pipe, "_process", AsyncMock(side_effect=RuntimeError("still down"))), \
             patch.object(pipe, "raise_alert") as alert, \
             patch.object(pipe, "finalize_call_score"), \
             patch.object(pipe, "mark_crm_update", AsyncMock()):
            await pipe.run_call_ai("c1")
        self.assertEqual(db.row()["ai_status"], "failed")
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["type"], "transcript_failed")

    async def test_a_broken_alert_insert_does_not_stop_scoring_or_the_crm_check(self):
        """A non-duplicate error from raise_alert on the final-failure path must not
        abort finalize_call_score / mark_crm_update."""
        db = FakeDB(call_logs=[_call(ai_attempts=1)])  # bumped to MAX_ATTEMPTS(2) on claim
        with patch.object(pipe, "get_supabase", return_value=db), \
             patch.object(pipe, "_process", AsyncMock(side_effect=RuntimeError("still down"))), \
             patch.object(pipe, "raise_alert", side_effect=RuntimeError("insert failed")), \
             patch.object(pipe, "finalize_call_score") as finalize, \
             patch.object(pipe, "mark_crm_update", AsyncMock()) as crm:
            await pipe.run_call_ai("c1")
        self.assertEqual(db.row()["ai_status"], "failed")
        finalize.assert_called_once_with(db, "c1")
        crm.assert_awaited_once_with(db, "c1")


class LoadAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_run_downloads_from_telecmi_and_stores_the_recording(self):
        db = FakeDB(call_logs=[_call(recording_url=None)])
        with patch.object(pipe, "_download_from_telecmi", AsyncMock(return_value=b"ID3" + bytes(4000))):
            audio, mime = await pipe._load_audio(db, db.row(), "2222223")
        self.assertEqual(db.row()["recording_url"], "https://storage.test/c1.mp3")
        self.assertEqual(mime, "audio/mp3")
        db.storage.from_.assert_called_with("call-recordings")

    async def test_telecmi_download_url_follows_the_play_record_docs(self):
        settings = {"telecmi_app_id": "33337312", "telecmi_secret": "app-secret-xyz", "telecmi_recording_base_url": None}
        response = MagicMock(status_code=200, content=b"ID3" + bytes(4000), headers={"content-type": "audio/mpeg"})
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(return_value=response)
        with patch.object(pipe, "get_setting", side_effect=lambda k, **kw: settings.get(k)), \
             patch.object(pipe.httpx, "AsyncClient", return_value=client), \
             patch.object(pipe.asyncio, "sleep", AsyncMock()):
            audio = await pipe._download_from_telecmi(_call(recording_url=None), "2222223")
        url = client.get.call_args.args[0]
        self.assertIn("rest.telecmi.com/v2/play", url)
        self.assertIn("appid=2222223", url)
        self.assertIn("file=rec.mp3", url)
        self.assertTrue(audio.startswith(b"ID3"))

    async def test_missing_telecmi_credentials_fail_loudly(self):
        with patch.object(pipe, "get_setting", return_value=None):
            with self.assertRaises(RuntimeError):
                await pipe._download_from_telecmi(_call(recording_url=None), None)


class QueueAndSweepTests(unittest.IsolatedAsyncioTestCase):
    def test_queue_resets_progress(self):
        db = FakeDB(call_logs=[_call(ai_status="failed", ai_attempts=3, ai_error="x")])
        pipe.queue_call_ai(db, "c1", "new.mp3")
        row = db.row()
        self.assertEqual((row["ai_status"], row["ai_attempts"], row["ai_error"], row["recording_filename"]), ("pending", 0, None, "new.mp3"))

    def test_retry_only_touches_failed_calls_in_the_tenant(self):
        db = FakeDB(call_logs=[_call(ai_status="failed", ai_attempts=3)])
        self.assertFalse(pipe.retry_call_ai(db, "c1", "other-tenant"))
        self.assertTrue(pipe.retry_call_ai(db, "c1", "t1"))
        self.assertEqual(db.row()["ai_status"], "pending")
        self.assertFalse(pipe.retry_call_ai(db, "c1", "t1"), "a pending call has nothing to retry")

    async def test_sweep_resumes_stale_calls_and_fails_exhausted_ones(self):
        db = FakeDB(call_logs=[
            _call(id="stale"),
            _call(id="stuck", ai_status="transcribing"),
            _call(id="exhausted", ai_attempts=2),
            _call(id="fresh", ai_updated_at="9999-01-01T00:00:00+00:00"),
        ])
        runs = []
        with patch.object(pipe, "get_supabase", return_value=db), \
             patch.object(pipe, "run_call_ai", AsyncMock(side_effect=lambda cid: runs.append(cid))), \
             patch.object(pipe, "finalize_call_score") as finalize, \
             patch.object(pipe, "raise_alert") as alert:
            count = await pipe.sweep_call_ai()
        self.assertEqual(sorted(runs), ["stale", "stuck"])
        self.assertEqual(count, 2)
        exhausted = next(r for r in db.rows["call_logs"] if r["id"] == "exhausted")
        self.assertEqual(exhausted["ai_status"], "failed")
        finalize.assert_called_once_with(db, "exhausted")
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["type"], "transcript_failed")

    async def test_a_broken_alert_insert_does_not_abort_the_rest_of_the_sweep(self):
        db = FakeDB(call_logs=[
            _call(id="exhausted-first", ai_attempts=2),
            _call(id="exhausted-second", ai_attempts=2),
            _call(id="stale"),
        ])
        runs = []
        with patch.object(pipe, "get_supabase", return_value=db), \
             patch.object(pipe, "run_call_ai", AsyncMock(side_effect=lambda cid: runs.append(cid))), \
             patch.object(pipe, "finalize_call_score") as finalize, \
             patch.object(pipe, "raise_alert", side_effect=RuntimeError("insert failed")):
            count = await pipe.sweep_call_ai()
        self.assertEqual(count, 1)
        self.assertEqual(runs, ["stale"])
        self.assertEqual(finalize.call_count, 2)
        for cid in ("exhausted-first", "exhausted-second"):
            row = next(r for r in db.rows["call_logs"] if r["id"] == cid)
            self.assertEqual(row["ai_status"], "failed")


class SweepCrmCutoffTests(unittest.IsolatedAsyncioTestCase):
    _OLDER = "2010-01-01T00:00:00+00:00"
    _PAST = "2020-01-01T00:00:00+00:00"
    _RECENT = "2099-01-01T00:00:00+00:00"

    def _row(self, id, call_group, **over):
        row = {"id": id, "provider": "telecmi", "ai_status": "done", "score_final": False,
               "call_group": call_group, "created_at": self._PAST}
        if call_group == "early_exit":
            row.update(score_final=True, feedback_at=None, evaluation={"early_exit_check": {"crm_matches": None}})
        row.update(over)
        return row

    async def test_real_conversations_and_pending_early_exits_past_cutoff_are_rechecked(self):
        rows = [
            self._row("rc-old", "real_conversation"),
            self._row("rc-older", "real_conversation", created_at=self._OLDER),
            self._row("rc-final", "real_conversation", score_final=True),
            self._row("rc-recent", "real_conversation", created_at=self._RECENT),
            self._row("ee-pending", "early_exit"),
            self._row("ee-has-feedback", "early_exit", feedback_at=self._PAST),
            self._row("ee-marked", "early_exit", evaluation={"early_exit_check": {"crm_matches": False}}),
            self._row("ee-recent", "early_exit", created_at=self._RECENT),
        ]
        db = FakeDB(call_logs=rows)
        results = {"rc-old": True, "rc-older": True, "ee-pending": False}
        with patch.object(pipe, "get_supabase", return_value=db), \
             patch.object(pipe, "mark_crm_update", AsyncMock(side_effect=lambda d, cid: results[cid])) as crm:
            changed = await pipe.sweep_crm_cutoff()
        self.assertEqual(changed, 2)
        called_ids = [c.args[1] for c in crm.await_args_list]
        self.assertEqual(set(called_ids), {"rc-old", "rc-older", "ee-pending"})
        self.assertEqual(called_ids[:2], ["rc-older", "rc-old"],
                          "real-conversation rows must be processed oldest-created_at first")


if __name__ == "__main__":
    unittest.main()


def _saved_evaluation(db):
    for call in db.table.return_value.update.call_args_list:
        payload = call.args[0]
        if "evaluation" in payload:
            return payload["evaluation"]
    raise AssertionError("evaluation was never saved")


class ReportPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def _process(self, tracks, group, report=None):
        db = MagicMock()
        marking = MarkResult(checks=[{"key": c["key"], "full": c["full"], "level": "good" if c["key"] != "crm_update" else None} for c in CHECKS],
                             report=report or {})
        with patch.object(pipe, "_load_audio", AsyncMock(return_value=(b"wav", "audio/wav"))), \
             patch.object(pipe, "transcribe_tracks", AsyncMock(return_value=tracks)), \
             patch.object(pipe, "sort_call", AsyncMock(return_value=_sort(group))), \
             patch.object(pipe, "mark_call", AsyncMock(return_value=marking)), \
             patch.object(pipe, "raise_alert"), \
             patch("app.services.knowledge_service.get_knowledge_context", AsyncMock(return_value="")):
            await pipe._process(db, {"id": "c", "tenant_id": "t", "duration_seconds": 90, "lead_id": None}, None)
        return _saved_evaluation(db)

    async def test_stereo_real_conversation_saves_report_talk_and_segments(self):
        tracks = TrackTranscript([Line(1, "telecaller", "Hello"), Line(3, "customer", "I need a demo")],
                                 [(1.04, 2.0), (9.0, 9.5)], [(3.0, 5.01)], True)
        report = {"report_version": 1, "coach": {"time": "00:01", "start": 1.0, "quote": "Hello", "tip": "Smile."}}
        ev = await self._process(tracks, "real_conversation", report)
        self.assertEqual(ev["report"]["coach"]["tip"], "Smile.")
        self.assertEqual(ev["report"]["segments"], {"telecaller": [[1.0, 2.0], [9.0, 9.5]], "customer": [[3.0, 5.0]]})
        self.assertEqual(ev["report"]["talk"], {"longest_monologue_s": 1.0, "dead_air_s": 4.0})
        self.assertEqual(ev["evaluation_version"], 4)

    async def test_early_exit_stereo_call_still_gets_segments_for_the_player(self):
        ev = await self._process(_tracks(), "early_exit")
        self.assertIn("segments", ev["report"])
        self.assertNotIn("coach", ev["report"])

    async def test_mono_call_has_no_segments_or_talk(self):
        tracks = TrackTranscript([Line(1, "telecaller", "Hello"), Line(3, "customer", "Hi")], [], [], False)
        ev = await self._process(tracks, "real_conversation")
        self.assertNotIn("report", ev)

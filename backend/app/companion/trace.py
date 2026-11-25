"""Reply trace: one row per saved live reply saying what went INTO it, never what was said.

Example: Karthik asks Jothidar AI about his job; the reply's trace row is
  {"card_lines": 14, "hits": 0, "dropped_recent_days": 5, "passages": 3, "chart_wrong": 1, "chart_redo": "ok"}
so a thumbs-down on that reply can be explained ("the old-chat search found nothing"), not guessed.

Privacy: the detail holds only whole numbers, true/false and the fixed words in WORDS. Anything else
(a message, a name, a topic) is dropped by _clean before it can reach the table, so the trace keeps the
same promise as the request log: who and how it went, never the words.

The steps of one reply call note(...) as they go; engine._finish calls schedule(...) once the reply is
saved. Nothing here raises: a broken trace must not break a chat.
"""
import asyncio
import logging
from contextvars import ContextVar

from app.companion import store

logger = logging.getLogger(__name__)

# The only keys a trace may carry. A key missing here is dropped.
NUMBERS = frozenset({
    "card_lines", "facts_left_out", "hits", "dropped_earlier_today", "dropped_old_chats",
    "dropped_recent_days", "passages", "chart_wrong", "rounds", "tool_calls", "prep_ms",
})
FLAGS = frozenset({"small_talk", "memory_cleaning", "kb_failed", "kb_small_talk", "shortcut_hit"})
WORDS = {"chart_redo": frozenset({"ok", "handoff"})}
MAX_NUMBER = 10_000_000
MODEL_MAX = 80

_current: ContextVar[dict | None] = ContextVar("companion_reply_trace", default=None)
_tasks: set[asyncio.Task] = set()


def start() -> None:
    """Called once at the start of a reply. The dict is shared by the reply's parallel steps."""
    _current.set({})


def _clean(values: dict) -> dict:
    """Keeps whole numbers, true/false and the fixed words; drops everything else.
    {"hits": 3, "small_talk": True, "chart_redo": "ok", "topic": "job"} -> the first three only."""
    out: dict = {}
    for key, value in values.items():
        if key in FLAGS and isinstance(value, bool):
            out[key] = value
        elif key in NUMBERS and isinstance(value, int) and not isinstance(value, bool):
            out[key] = max(0, min(value, MAX_NUMBER))
        elif key in WORDS and value in WORDS[key]:
            out[key] = value
    return out


def note(**values) -> None:
    """Adds facts about the reply being built. A no-op outside a reply. Never raises."""
    try:
        current = _current.get()
        if current is not None:
            current.update(_clean(values))
    except Exception as exc:
        logger.warning("companion trace: note failed (%s)", type(exc).__name__)


def schedule(tenant_id: str, companion_id: str, message_id: str, *, basis: str | None, model: str | None,
             llm_ms: int, total_ms: int) -> None:
    """Called after the reply is saved. Starts the trace write in the background. Never raises."""
    try:
        row = {"tenant_id": tenant_id, "companion_id": companion_id, "message_id": message_id,
               "basis": basis, "model": (model or "")[:MODEL_MAX] or None,
               "llm_ms": max(int(llm_ms), 0), "total_ms": max(int(total_ms), 0),
               "detail": dict(_current.get() or {})}
        task = asyncio.get_running_loop().create_task(_save(row))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception as exc:
        logger.warning("companion trace: could not schedule the trace (%s)", type(exc).__name__)


async def _save(row: dict) -> None:
    try:
        await store.save_reply_trace(row)
    except Exception as exc:
        logger.warning("companion trace: insert failed (%s)", type(exc).__name__)

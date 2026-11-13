"""The heavy file work of the knowledge base runs in ONE helper process, not in the web server.

Opening a PDF, reading a page's text, drawing a page for OCR and pulling the text out of a Word
or Excel file used to run in threads of the web server. Python never hands that memory back to
the system, so every big book left the server bigger (book 02, 182 pages: 135 MB -> 270 MB and
it stayed), and the PDF parser (plain Python) held the interpreter lock while WhatsApp requests
waited (1-4.6 s stalls during uploads). In a helper process the main server stays flat (same
book: 135 MB -> 127 MB, same 17 s), and when the helper exits the system takes back everything
it used.

- One helper, one call at a time. Today's work was one-at-a-time anyway (the interpreter lock,
  the PDFium lock). A call's timeout starts when its turn starts, so a call waiting behind a
  slow page does not lose its time.
- A call that runs past its timeout gets its helper killed (a thread could never be stopped).
- close() at the end of every 45-second pass (ingest.run_pending) lets the helper exit. A fresh
  one also starts after RECYCLE_AFTER calls (Python 3.11's own max_tasks_per_child hangs).
- The helper starts as a fresh Python ("spawn"), not a copy of the server: copying a process
  that runs threads can leave the copy stuck on a lock some thread held.

fn and its arguments cross to the helper by pickling, so fn must be a module-level function.
Tests fake these functions with closures, so conftest sets INLINE (run in a thread here).
"""
import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

logger = logging.getLogger(__name__)

RECYCLE_AFTER = 100    # calls one helper serves before a fresh one starts
INLINE = False         # tests only: run in a thread of this process

_pool: ProcessPoolExecutor | None = None
_calls = 0
_turns: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None


def _turn() -> asyncio.Lock:
    """The lock that makes calls take turns, one per event loop (a lock is tied to its loop)."""
    global _turns
    loop = asyncio.get_running_loop()
    if _turns is None or _turns[0] is not loop:
        _turns = (loop, asyncio.Lock())
    return _turns[1]


def _ready() -> ProcessPoolExecutor:
    global _pool, _calls
    if _pool is not None and _calls >= RECYCLE_AFTER:
        close()
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        _calls = 0
    _calls += 1
    return _pool


def _kill(pool: ProcessPoolExecutor) -> None:
    """Stop the helper now, even in the middle of a call. Python 3.11 has no public way to kill a
    pool's process, so this reaches into _processes (present in 3.8-3.14)."""
    global _pool
    if _pool is pool:
        _pool = None
    for process in list((getattr(pool, "_processes", None) or {}).values()):
        try:
            process.kill()
        except Exception:
            pass
    pool.shutdown(wait=False, cancel_futures=True)


def close() -> None:
    """Let the helper exit once its current call (if any) is done; everything it used goes back
    to the system. The next run() starts a fresh one."""
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


async def run(fn, *args, timeout: float):
    """fn(*args) in the helper. Raises asyncio.TimeoutError after `timeout` seconds of its turn
    (the helper is killed), and fn's own exception when fn raises."""
    if INLINE:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout)
    async with _turn():
        pool = _ready()
        try:
            return await asyncio.wait_for(asyncio.wrap_future(pool.submit(fn, *args)), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _kill(pool)          # the call may still be running in there: never leave it behind
            raise
        except BrokenProcessPool:
            logger.warning("companion kb: the helper process died during %s", getattr(fn, "__name__", fn))
            _kill(pool)
            raise

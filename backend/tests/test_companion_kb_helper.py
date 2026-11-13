"""The helper process that does the heavy file work (opening PDFs, reading and drawing pages).

These tests start real processes (conftest runs the helper inline for every other test), so each
one takes about a second."""
import asyncio
import os
import time

import psutil
import pytest
from PIL import Image

from app.companion.kb import filetypes, helper, pages


@pytest.fixture(autouse=True)
def real_helper(monkeypatch):
    monkeypatch.setattr(helper, "INLINE", False)
    helper.close()
    yield
    helper.close()


def run(coro):
    return asyncio.run(coro)


def gone(pid: int, seconds: float = 10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
            return True
        time.sleep(0.1)
    return False


def test_the_work_runs_in_another_process_and_the_result_comes_back():
    assert run(helper.run(os.getpid, timeout=30)) != os.getpid()
    assert run(helper.run(divmod, 17, 5, timeout=30)) == (3, 2)


def test_an_error_in_the_helper_comes_back_as_the_same_error():
    with pytest.raises(ZeroDivisionError):
        run(helper.run(divmod, 1, 0, timeout=30))


def test_closing_lets_the_helper_exit_so_its_memory_goes_back():
    pid = run(helper.run(os.getpid, timeout=30))
    helper.close()
    assert gone(pid)


def test_a_hung_call_is_cut_off_and_its_helper_killed_and_the_next_call_gets_a_fresh_one():
    pid = run(helper.run(os.getpid, timeout=30))
    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        run(helper.run(time.sleep, 30, timeout=0.5))
    assert time.monotonic() - started < 10
    assert gone(pid)
    assert run(helper.run(os.getpid, timeout=30)) not in (pid, os.getpid())


def test_calls_take_turns_so_a_waiting_call_does_not_lose_its_time():
    # Two lanes ask at once. Each call gets its full timeout once it is its turn: the second call
    # (1 s allowed) waits behind a 1.5 s call and still succeeds.
    async def both():
        return await asyncio.gather(helper.run(time.sleep, 1.5, timeout=30), helper.run(os.getpid, timeout=1))
    assert run(both())[1] != os.getpid()


def test_a_fresh_helper_after_recycle_after_calls(monkeypatch):
    monkeypatch.setattr(helper, "RECYCLE_AFTER", 2)
    pids = [run(helper.run(os.getpid, timeout=30)) for _ in range(3)]
    assert pids[0] == pids[1] != pids[2]
    assert gone(pids[0])


def test_inline_mode_runs_here(monkeypatch):
    monkeypatch.setattr(helper, "INLINE", True)
    assert run(helper.run(os.getpid, timeout=30)) == os.getpid()


def test_the_real_book_readers_cross_to_the_helper(tmp_path):
    # The functions ingest and ocr send over must be importable by name from light modules.
    pdf = tmp_path / "two.pdf"
    Image.new("RGB", (200, 300), "white").save(pdf, format="PDF", save_all=True,
                                               append_images=[Image.new("RGB", (300, 200), "white")])
    notes = tmp_path / "notes.txt"
    notes.write_text("Saturn in the seventh house", encoding="utf-8")

    async def read_all():
        return (await helper.run(pages.count_pages, str(pdf), timeout=30),
                await helper.run(pages.read_page, str(pdf), 1, timeout=30),
                await helper.run(pages.render_pdf_page, str(pdf), 2, timeout=30),
                await helper.run(filetypes.text_pages, str(notes), "txt", timeout=30))
    count, layer, png, text = run(read_all())
    assert (count, layer, text) == (2, ("", set()), ["Saturn in the seventh house"])
    assert png.startswith(b"\x89PNG")

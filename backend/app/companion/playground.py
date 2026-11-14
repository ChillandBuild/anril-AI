"""Playground-only search settings, carried through one dashboard request in a context variable.

The live path never sets them: current() is None there, and every reader falls back to the live
constant (memory_search.VECTOR_FLOOR, kb_judge.PASS_MARK, ...). So a setting can only ever change
what the owner sees in the Playground, never what a real person gets.

Worked example. The owner opens Search, picks Maya and Karthik, sets strictness 0.60 and turns the
judge off, then searches "shoe return":
    with use(Overrides(memory_floor=0.60, rerank=False)) as ov:
        await kb_search.search(...); await memory_search.search(...)
    ov.kb_candidates  -> every passage looked at, with its meaning score and kept/dropped
    ov.memory_candidates -> every memory piece, including the ones below 0.60
    ov.trace -> ["Knowledge: 8 candidates from the main files, judge off, kept 5", ...]

Context variables are copied into tasks made by asyncio.gather / wait_for / to_thread, and they all
share the same Overrides object, so what a child task records is visible to the route.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, Literal

Sources = Literal["all", "memories", "knowledge"]
Mode = Literal["auto", "agentic"]


@dataclass
class Overrides:
    sources: Sources = "all"
    results: int | None = None          # None: the live counts (memory 5 hits, knowledge 3 / 4 passages)
    memory_floor: float | None = None   # None: memory_search.VECTOR_FLOOR
    judge_min: int | None = None        # None: kb_judge.PASS_MARK
    rerank: bool = True                 # False: no judge call, the fused order decides
    rewrite: bool = True                # False: search the message as typed
    memory_card: bool = True            # False: the card and today's recap are left out of the prompt
    mode: Mode = "auto"                 # "agentic": the model calls search tools when it wants
    # Filled in while the request runs (read by the route, never by the live path).
    trace: list[str] = field(default_factory=list)
    rewritten: dict | None = None
    kb_candidates: list[dict] = field(default_factory=list)
    kb_scores: dict[str, dict] = field(default_factory=dict)   # passage id -> meaning / rrf, from fuse
    memory_candidates: list[dict] = field(default_factory=list)
    # Why the reply failed, in plain words (ai_reply.describe_llm_error). None when it worked.
    problem: str | None = None
    # What memory reached the reply, for the plain "Used:" line. None: not looked at this turn.
    memory_hits: int | None = None      # past moments found by the memory search
    card_lines: int | None = None       # lines of the memory card (its notes about the person)

    def note(self, line: str) -> None:
        self.trace.append(line)


_current: ContextVar[Overrides | None] = ContextVar("companion_playground", default=None)


def current() -> Overrides | None:
    return _current.get()


@contextmanager
def use(overrides: Overrides) -> Iterator[Overrides]:
    token = _current.set(overrides)
    try:
        yield overrides
    finally:
        _current.reset(token)


def changes_search() -> bool:
    """True inside a Playground request whose settings change what search keeps (so the reply must
    not feed the live question log or shortcut counters). False on the live path."""
    ov = _current.get()
    return ov is not None and (ov.results is not None or ov.memory_floor is not None or ov.judge_min is not None
                               or not ov.rerank or not ov.rewrite or ov.mode != "auto")


def problem(text: str) -> None:
    """Record why the reply failed, for the owner's eyes only; a no-op on the live path.
    The first problem wins (the normal reply runs before Compare's reply without memory)."""
    ov = _current.get()
    if ov is not None and ov.problem is None:
        ov.problem = text


def used_memories(hits: int) -> None:
    """How many past moments the memory search handed the reply; a no-op on the live path."""
    ov = _current.get()
    if ov is not None:
        ov.memory_hits = hits


def note(line: str) -> None:
    """Add a trace line when a Playground request is running; a no-op on the live path."""
    ov = _current.get()
    if ov is not None:
        ov.note(line)


# What the live path uses, shown beside each setting ("Live chat uses 0.70").
def live_defaults() -> dict:
    from app.companion import memory_search
    from app.companion.kb import judge as kb_judge
    return {"sources": "all", "results": memory_search.MAX_HITS, "memory_floor": memory_search.VECTOR_FLOOR,
            "judge_min": kb_judge.PASS_MARK, "rerank": True, "rewrite": True, "memory_card": True,
            "mode": "auto"}

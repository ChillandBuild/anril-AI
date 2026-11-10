"""The eval's stand-ins: a frozen clock and an in-memory database per person, real embeddings (cached),
and a pg_trgm-like word_similarity, so a whole month of chat replays in minutes without touching the
live database. Everything is per asyncio task (contextvars), so people replay in parallel.

Nothing here writes to the live DB: store.get_supabase is the per-person fake, and token metering
is captured in memory instead of being recorded. The tenant's keys and model are read live, read-only.
"""
import contextvars
import itertools
import logging
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.companion import memory_card, memory_embed, memory_refresh, memory_sweep, store
from app.services import ai_reply, gemini_client
from tests.fake_supabase import FakeSupabase, _cosine, _vector

CLOCK: contextvars.ContextVar[datetime] = contextvars.ContextVar("eval_clock")
DB: contextvars.ContextVar["SimDB"] = contextvars.ContextVar("eval_db")
LABEL: contextvars.ContextVar[str] = contextvars.ContextVar("eval_label", default="other")
CALLS: contextvars.ContextVar[list] = contextvars.ContextVar("eval_calls")


class SimDT(datetime):
    """datetime whose now() is the task's simulated clock."""
    @classmethod
    def now(cls, tz=None):
        t = CLOCK.get()
        return t.astimezone(tz) if tz else t.astimezone(timezone.utc).replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return CLOCK.get().astimezone(timezone.utc).replace(tzinfo=None)


# --- pg_trgm word_similarity -------------------------------------------------------------------

def _word_char(ch: str) -> bool:
    # Live check (2026-11-10): Tamil vowel signs count as word characters, so L, M and N categories.
    return unicodedata.category(ch)[0] in "LMN"


def _words(text: str) -> list[str]:
    out, cur = [], []
    for ch in text.casefold():
        if _word_char(ch):
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _word_trigrams(word: str) -> list[str]:
    padded = "  " + word + " "
    return [padded[i:i + 3] for i in range(len(padded) - 2)]


_TRGM_CACHE: dict[str, list[str]] = {}


def trigram_seq(text: str) -> list[str]:
    seq = _TRGM_CACHE.get(text)
    if seq is None:
        seq = [t for w in _words(text) for t in _word_trigrams(w)]
        _TRGM_CACHE[text] = seq
    return seq


_SIM_CACHE: dict[tuple[str, str], float] = {}


def word_similarity(query: str, text: str) -> float:
    """Best shared / (|Tq| + |extent| - shared) over contiguous extents of the text's trigrams
    (|extent| = distinct trigrams in it), the formula that matched live Postgres on sample pairs."""
    key = (query, text)
    if key in _SIM_CACHE:
        return _SIM_CACHE[key]
    tq = set(trigram_seq(query))
    seq = trigram_seq(text)
    best = 0.0
    if tq and seq:
        nq = len(tq)
        starts = [i for i, t in enumerate(seq) if t in tq]
        for i in starts:
            seen: set[str] = set()
            shared = 0
            for j in range(i, len(seq)):
                t = seq[j]
                if t not in seen:
                    seen.add(t)
                    if t in tq:
                        shared += 1
                if t in tq:
                    score = shared / (nq + len(seen) - shared)
                    if score > best:
                        best = score
                # Even matching every remaining query trigram can't beat best: stop this start.
                if nq / (nq + len(seen) - shared) <= best:
                    break
    _SIM_CACHE[key] = best
    return best


# --- the per-person database ---------------------------------------------------------------------

class SimDB(FakeSupabase):
    """FakeSupabase whose timestamps come from the simulated clock and whose search RPC ranks with
    real cosine + word_similarity, like migration 256."""

    def __init__(self, tables: dict | None = None):
        super().__init__()
        if tables is not None:
            self.tables = tables
        self._seq = itertools.count(1)
        self.rpc_handlers["claim_memory_pair"] = self._claim
        self.rpc_handlers["match_memory_chunks"] = self._match

    def _stamp(self) -> str:
        # Unique, ordered, always with microseconds (string comparison stays correct).
        t = CLOCK.get().astimezone(timezone.utc) + timedelta(microseconds=next(self._seq) % 999_999 + 1)
        return t.isoformat(timespec="microseconds")

    def _claim(self, p: dict) -> bool:
        now = CLOCK.get()
        until = (now + timedelta(seconds=p["p_seconds"])).isoformat()
        rows = [r for r in self.rows("companion_memory_state")
                if r["companion_id"] == p["p_companion"] and r["end_user_id"] == p["p_end_user"]]
        if not rows:
            self.add("companion_memory_state", tenant_id=p["p_tenant"], companion_id=p["p_companion"],
                     end_user_id=p["p_end_user"], busy_until=until, failures=0, last_message_at=None)
            return True
        row = rows[0]
        busy = row.get("busy_until")
        if row["tenant_id"] != p["p_tenant"] or (busy and datetime.fromisoformat(busy) >= now):
            return False
        row["busy_until"] = until
        return True

    def _match(self, p: dict) -> list[dict]:
        mine = [r for r in self.rows("companion_memory_chunks")
                if r["tenant_id"] == p["p_tenant"] and r["end_user_id"] == p["p_end_user"]
                and r["companion_id"] in p["p_companions"]]
        keys = ("id", "companion_id", "kind", "day", "text")
        out = []
        q = _vector(p.get("p_embedding"))
        if q is not None:
            scored = [(r, _cosine(q, _vector(r["embedding"]))) for r in mine if r.get("embedding") is not None]
            for r, s in sorted(scored, key=lambda t: -t[1])[:p["p_count"]]:
                out.append({**{k: r[k] for k in keys}, "source": "vector", "score": s})
        if p.get("p_query"):
            scored = [(r, word_similarity(p["p_query"], r["text"])) for r in mine]
            for r, s in sorted(scored, key=lambda t: -t[1])[:p["p_count"]]:
                if s > 0:
                    out.append({**{k: r[k] for k in keys}, "source": "trigram", "score": s})
        return out


# --- embeddings: both models, cached --------------------------------------------------------------

REAL_EMBED = memory_embed.embed
EMB: dict[tuple[str, str, str], list[float]] = {}
EMB_FAILED: Counter = Counter()
STORE_MODEL = "gemini"      # the vector written into chunk rows during replay
QUERY_MODEL: contextvars.ContextVar[str] = contextvars.ContextVar("eval_query_model", default="gemini")


async def ensure(texts: list[str], kind: str, tenant_id: str, model: str) -> None:
    missing = list(dict.fromkeys(t for t in texts if (model, kind, t) not in EMB))
    if not missing:
        return
    vectors = await REAL_EMBED(missing, kind, tenant_id, model=model)
    for t, v in zip(missing, vectors):
        if v is None:
            EMB_FAILED[model] += 1
        else:
            EMB[(model, kind, t)] = v


async def sim_embed(texts: list[str], kind: str, tenant_id: str, model: str | None = None, retries: bool = True):
    """Stored pieces are embedded with both models (for the bake-off); the row keeps STORE_MODEL's.
    Queries use the task's QUERY_MODEL."""
    if kind == "document":
        for m in ("gemini", "jina"):
            await ensure(texts, kind, tenant_id, m)
        use = model or STORE_MODEL
    else:
        use = model or QUERY_MODEL.get()
        await ensure(texts, kind, tenant_id, use)
    return [EMB.get((use, kind, t)) for t in texts]


# --- LLM call capture -------------------------------------------------------------------------------

REAL_LLM = ai_reply._llm_chat


def _label_for(system: str) -> str:
    for mod in (memory_card, __import__("app.companion.memory_forget", fromlist=["x"])):
        for name, value in vars(mod).items():
            if isinstance(value, str) and name.isupper() and len(value) > 80 and system.startswith(value[:200]):
                return f"{mod.__name__.rsplit('.', 1)[-1]}.{name}"
    return LABEL.get()


async def sim_llm(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4, model=None):
    label = _label_for(messages[0]["content"] if messages and messages[0]["role"] == "system" else "")
    token = LABEL.set(label)
    calls = CALLS.get(None)
    entry = {"label": label, "max_tokens": max_tokens, "in": None, "out": None, "ok": False}
    if calls is not None:
        calls.append(entry)
    try:
        raw = await REAL_LLM(messages, max_tokens=max_tokens, tenant_id=tenant_id, purpose=purpose,
                             temperature=temperature, model=model)
        entry["ok"] = bool(raw)
        return raw
    finally:
        LABEL.reset(token)


def sim_record_tokens(tenant_id, purpose, provider, model, input_tokens, output_tokens):
    calls = CALLS.get(None)
    if calls:
        # The newest open entry of this task is the call whose response just arrived.
        for entry in reversed(calls):
            if entry["in"] is None:
                entry["in"], entry["out"], entry["model"] = input_tokens, output_tokens, model
                break


class WarningCounter(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.counts: Counter = Counter()

    def emit(self, record):
        if record.name.startswith(("app.companion", "app.services")):
            self.counts[f"{record.name}: {record.msg}"] += 1


WARNINGS = WarningCounter()


def install() -> None:
    """Patches the app for the eval run (process-wide; per-task state lives in the contextvars)."""
    for mod in (memory_card, store, memory_refresh, memory_sweep):
        mod.datetime = SimDT
    store.get_supabase = lambda: DB.get()
    memory_embed.embed = sim_embed
    ai_reply._llm_chat = sim_llm
    gemini_client.record_tokens = sim_record_tokens
    logging.getLogger().addHandler(WARNINGS)
    logging.getLogger().setLevel(logging.INFO)


def per_label(calls: list[dict]) -> dict:
    out: dict = defaultdict(lambda: {"calls": 0, "failed": 0, "in": [], "out": [], "near_cap": 0})
    for c in calls:
        row = out[c["label"]]
        row["calls"] += 1
        row["failed"] += 0 if c["ok"] else 1
        if c["in"] is not None:
            row["in"].append(c["in"])
            row["out"].append(c["out"] or 0)
            if (c["out"] or 0) >= int(c["max_tokens"] * 0.98):
                row["near_cap"] += 1
    return {k: {"calls": v["calls"], "failed": v["failed"], "near_cap": v["near_cap"],
                "avg_in": round(sum(v["in"]) / len(v["in"])) if v["in"] else None,
                "avg_out": round(sum(v["out"]) / len(v["out"])) if v["out"] else None,
                "max_out": max(v["out"]) if v["out"] else None} for k, v in out.items()}

"""A follow-up chip never repeats a question the person already asked (28 Nov 2026).

Why code and not the prompt: told "never one already asked", the model kept offering "Kalyanam eppo nadakkum?"
back to someone who had asked "kalyanam eppo" (27 of 100 chips repeated). Letting the model label its own
questions did not work either: flash-lite left 26% unlabelled, labelled a child question "marriage when", and
showed the labels themselves as chips (16 of 42). So code compares each chip with the person's real questions.

Prem's line: the same topic AND the same kind of ask is a repeat; a different ask on the topic is fine.
  - The topic comes from embeddings, which match across scripts: "கல்யாணம் எப்போ" ~ "kalyanam eppo" 0.96.
  - Embeddings cannot tell the ask apart ("வெளிநாடு வேலை எப்போ?" ~ "வெளிநாடு போக வாய்ப்பு இருக்கா?" 0.93, but one
    asks when and the other whether), so the kind comes from the question words (kinds()).
A chip is dropped when an asked question (or a chip picked before it) is at least SAME_TOPIC alike and shares
a kind, or at least NEAR_COPY alike whatever its words (that also covers languages kinds() has no words for):
    asked "kalyanam eppo"; ideas "கல்யாணம் எப்போ" (0.96, when) | "Love-a arranged-a?" (0.80, which) | "Veedu eppo?"
    -> chips ["Love-a arranged-a?", "Veedu eppo?"]
Vectors are cached per business and text, so the person's questions are embedded once (prefetch() starts that
while the model writes the reply). A failed or slow embedding costs the meaning check, never the reply: then
only an exact copy is dropped.
"""
import asyncio
import logging
import math
import re
from array import array
from collections import OrderedDict

from app.companion import memory_embed
from app.companion.reply_format import CHIPS, copy_key as _copy_key

logger = logging.getLogger(__name__)

SAME_TOPIC = 0.80    # this alike and the same kind of ask = a repeat (chips eval grid, 28 Nov 2026)
NEAR_COPY = 0.95     # this alike = a repeat, whatever the question words
WAIT_SECONDS = 3.0   # longest the reply waits for vectors
CACHE_MAX = 6000     # (business, text) vectors kept, the newest: ~3 KB each, ~20 MB; a person needs up to 34

# The kinds of ask, from question words in Tamil, Tanglish and English. A question can have several
# ("Kalyanam thaamadham aaguma?" = when + whether); two questions share a kind when the sets meet.
# "Will it be delayed" (தாமதம், thaamadham) is a when (Prem, 27 Nov 2026). No \b next to Tamil letters:
# Tamil vowel signs are not word characters to Python, so a boundary there falls inside a word.
_KINDS = {
    "when": r"எப்ப(?!டி)|எந்த வருஷ|எந்த வருட|எந்த மாச|தாமத|(?<!எதிர்)காலம்|நேரம்|\by?eppo|\by?epo|\beppa\b"
            r"|\bwhen\b|\bsoon\b|which (year|month)|thaamadh|thamadh|\bdelay|\blate\b|\btime\b|\bperiod\b",
    "how": r"எப்படி|\beppadi|\bepdi|\byepadi|\beppdi|\bhow\b",
    "whether": r"ா\s*[?!.]*\s*$|(uma|umaa|lama|laama|kka|kkaa|ruka|rukka)\s*[?!.]*\s*$"
               r"|^\s*(will|would|is|are|am|can|could|should|shall|do|does|did|any)\b",
    "why": r"ஏன்|\byen\b|\bean\b|\bwhy\b",
    "which": r"எந்த|அல்லது|\bendha\b|\bentha\b|\bwhich\b|\bor\b|-a\b.*-a\b",
    "advice": r"பரிகாரம்|என்ன செய்ய|கோவி|கோயி|\bparig?h?aa?ram|\bremed|\bwhat should\b|\bwhat to do\b|\btemple"
              r"|\bkovil|\bkoil\b",
}
_KIND_RES = {kind: re.compile(pattern, re.IGNORECASE) for kind, pattern in _KINDS.items()}

_CACHE: "OrderedDict[tuple[str, str], array]" = OrderedDict()   # (tenant_id, text) -> unit vector
_PENDING: dict[tuple[str, str], asyncio.Task] = {}                # (tenant_id, text) -> the embedding under way


def kinds(question: str) -> set[str]:
    """The kinds of ask in a question: kinds("Kalyanam thaamadham aaguma?") -> {"when", "whether"}."""
    text = " ".join((question or "").split())
    return {kind for kind, pattern in _KIND_RES.items() if pattern.search(text)}


def _cos(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))   # unit vectors


def _repeats(chip: str, vector, other: str, other_vector) -> bool:
    if vector is None or other_vector is None:
        return False
    alike = _cos(vector, other_vector)
    if alike >= NEAR_COPY:
        return True
    mine, theirs = kinds(chip), kinds(other)
    # no question words in either ("what is my lagnam" ~ "my lagnam pathi sollunga"): the same plain ask
    return alike >= SAME_TOPIC and (bool(mine & theirs) or not (mine or theirs))


def pick(ideas: list[str], vectors: list, asked: list[str], asked_vectors: list) -> list[str]:
    """The first CHIPS ideas that repeat neither an asked question nor an idea picked before them; fewer
    than CHIPS -> []. vectors / asked_vectors: one unit vector or None per text (None: copy check only)."""
    picked: list[tuple[str, object]] = []
    seen = list(zip(asked, asked_vectors))
    copies = {_copy_key(q) for q in asked}
    for idea, vector in zip(ideas, vectors):
        key = _copy_key(idea)
        if not key or key in copies or any(_repeats(idea, vector, q, v) for q, v in seen):
            continue
        copies.add(key)
        seen.append((idea, vector))
        picked.append((idea, vector))
    return [idea for idea, _ in picked[:CHIPS]] if len(picked) >= CHIPS else []


def _unit(vector: list[float]) -> array | None:
    norm = math.sqrt(sum(x * x for x in vector))
    return array("f", (x / norm for x in vector)) if norm else None


def _in_flight(task: asyncio.Task | None) -> bool:
    """A task still running on this event loop (one from a loop that has closed is never waited on)."""
    if task is None or task.done():
        return False
    try:
        return task.get_loop() is asyncio.get_running_loop()
    except RuntimeError:
        return False


async def _embed(tenant_id: str, texts: list[str]) -> None:
    try:
        vectors = await memory_embed.embed(texts, "query", tenant_id, retries=False)
    except Exception as exc:
        logger.warning("chip repeats: embedding failed for %d text(s) (%s)", len(texts), type(exc).__name__)
        vectors = [None] * len(texts)
    finally:   # also on a cancel: nothing is left marked under way
        for text in texts:
            _PENDING.pop((tenant_id, text), None)
    for text, vector in zip(texts, vectors):
        unit = _unit(vector) if vector else None
        if unit is not None:
            _CACHE[(tenant_id, text)] = unit
            _CACHE.move_to_end((tenant_id, text))
    while len(_CACHE) > CACHE_MAX:
        _CACHE.popitem(last=False)


def prefetch(tenant_id: str, texts: list[str]) -> None:
    """Start embedding the texts not cached or under way, in one call, and return at once. Call it with the
    person's questions before the model writes, so only the chips are left to embed after."""
    missing = [t for t in dict.fromkeys(texts) if t and (tenant_id, t) not in _CACHE
               and not _in_flight(_PENDING.get((tenant_id, t)))]
    if not missing:
        return
    task = asyncio.ensure_future(_embed(tenant_id, missing))
    for text in missing:
        _PENDING[(tenant_id, text)] = task


async def _vectors(tenant_id: str, texts: list[str]) -> list:
    prefetch(tenant_id, texts)
    tasks = {task for t in texts if _in_flight(task := _PENDING.get((tenant_id, t)))}
    if tasks:
        await asyncio.wait(tasks, timeout=WAIT_SECONDS)   # a slow call keeps going and fills the cache later
    vectors = []
    for text in texts:
        vector = _CACHE.get((tenant_id, text))
        if vector is not None:
            _CACHE.move_to_end((tenant_id, text))
        vectors.append(vector)
    return vectors


async def fresh(tenant_id: str, ideas: list[str], asked: list[str]) -> list[str]:
    """The chips to show out of the model's ideas: pick() with vectors. asked: the person's questions,
    the newest message included. Never raises."""
    if len(ideas) < CHIPS:
        return []
    try:
        vectors = await _vectors(tenant_id, list(asked) + list(ideas))
    except Exception as exc:
        logger.warning("chip repeats: meaning check skipped (%s)", type(exc).__name__)
        vectors = [None] * (len(asked) + len(ideas))
    return pick(ideas, vectors[len(asked):], asked, vectors[:len(asked)])

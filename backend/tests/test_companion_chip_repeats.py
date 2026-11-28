"""chip_repeats: a follow-up chip never repeats a question the person already asked (28 Nov 2026)."""
import asyncio
import math

import pytest

from app.companion import chip_repeats, memory_embed
from app.companion.chip_repeats import kinds, pick


@pytest.fixture(autouse=True)
def _empty_cache():
    chip_repeats._CACHE.clear()
    chip_repeats._PENDING.clear()
    yield
    chip_repeats._CACHE.clear()
    chip_repeats._PENDING.clear()


def _unit(angle: float) -> list[float]:
    """A 2-d unit vector: cos between _unit(a) and _unit(b) is cos(a - b)."""
    return [math.cos(angle), math.sin(angle)]


def _at(similarity: float) -> list[float]:
    """A vector whose cos with _unit(0) is `similarity`."""
    return _unit(math.acos(similarity))


# --- kinds: the kind of ask, read from the question words ------------------------------------------

@pytest.mark.parametrize("question, expected", [
    ("kalyanam eppo", {"when"}),
    ("கல்யாணம் எப்போ", {"when"}),
    ("enaku when job kidaikum?", {"when"}),
    ("Kalyanam thaamadham aaguma?", {"when", "whether"}),     # Prem: "will it be delayed" is a when
    ("Will my loan be cleared soon?", {"when", "whether"}),
    ("வெளிநாடு போக நல்ல காலம் எது?", {"when"}),                  # a good time = a when
    ("Is this a good time to change jobs?", {"when", "whether"}),
    ("வேலை வாய்ப்பு எப்படி இருக்கும்?", {"how"}),
    ("Health condition epdi irkum", {"how"}),
    ("How is my career overall?", {"how"}),
    ("வெளிநாடு போக வாய்ப்பு இருக்கா?", {"whether"}),
    ("அரசு வேலை கிடைக்குமா?", {"whether"}),
    ("overseas job kidaikuma ?", {"whether"}),
    ("Higher studies abroad pannalama?", {"whether"}),
    ("Should I start a business?", {"whether"}),
    ("Love-a arranged-a?", {"which"}),
    ("எந்த கோவிலுக்கு போகணும்?", {"which", "advice"}),
    ("குழந்தை பாக்கியம் தாமதம் ஏன்?", {"when", "why"}),
    ("Parigaaram edaadbu iruka", {"advice", "whether"}),
    ("What is my lagnam and rasi?", set()),
    ("கல்யாணம் எப்ப?", {"when"}),                                 # no space after எப்ப
    ("yeppo kalyanam", {"when"}),
    ("kidaikuma!", {"whether"}),
    ("எதிர்காலம் எப்படி இருக்கும்?", {"how"}),                      # the future: not a when
])
def test_kinds_reads_the_kind_of_ask_in_tamil_tanglish_and_english(question, expected):
    assert kinds(question) == expected


# --- pick: the first two chips that repeat nothing ------------------------------------------------

ASKED = ["kalyanam eppo"]
ASKED_V = [_unit(0)]


def test_a_chip_on_the_same_topic_with_the_same_kind_of_ask_is_dropped():
    # "கல்யாணம் எப்போ" is kalyanam eppo in Tamil letters: same topic (0.90), both a when
    ideas = ["கல்யாணம் எப்போ", "Love-a arranged-a?", "Sontha veedu eppo?"]
    assert pick(ideas, [_at(0.90), _at(0.90), _at(0.40)], ASKED, ASKED_V) == ["Love-a arranged-a?",
                                                                             "Sontha veedu eppo?"]


def test_the_same_topic_with_a_different_kind_of_ask_stays():
    # "will I go abroad" asked; "when will I get an abroad job" is a deeper question, not a repeat
    assert pick(["வெளிநாடு வேலை எப்போ?", "Dasa eppadi?"], [_at(0.93), _at(0.30)],
                ["வெளிநாடு போக வாய்ப்பு இருக்கா?"], ASKED_V) == ["வெளிநாடு வேலை எப்போ?", "Dasa eppadi?"]


def test_a_near_copy_is_dropped_whatever_its_question_words():
    assert pick(["What about my lagnam?", "Dasa eppadi?", "Velai eppadi?"], [_at(0.96), _unit(1.3), _unit(-1.4)],
                ["What is my lagnam and rasi?"], ASKED_V) == ["Dasa eppadi?", "Velai eppadi?"]


def test_below_the_topic_line_a_chip_stays_even_with_the_same_kind_of_ask():
    ideas = ["Sontha veedu eppo?", "Velai eppo?"]
    assert pick(ideas, [_at(chip_repeats.SAME_TOPIC - 0.02), _at(0.2)], ASKED, ASKED_V) == ideas


def test_two_chips_that_repeat_each_other_never_show_together():
    # the 2nd idea repeats the 1st (0.90 alike, both when): the 3rd takes its place
    ideas = ["Kalyanam eppo nadakkum?", "Thirumanam eppo?", "Velai eppadi?"]
    vectors = [_unit(1.5), _unit(1.5 + math.acos(0.90)), _unit(-1.5)]
    assert pick(ideas, vectors, ASKED, ASKED_V) == ["Kalyanam eppo nadakkum?", "Velai eppadi?"]


def test_two_questions_without_question_words_count_as_the_same_ask():
    ideas = ["My lagnam pathi sollunga", "Velai eppadi?", "Dasa eppadi?"]
    assert pick(ideas, [_at(0.88), _unit(-1.2), _unit(1.3)], ["What is my lagnam?"], ASKED_V) == ["Velai eppadi?",
                                                                                              "Dasa eppadi?"]


def test_without_vectors_only_an_exact_copy_is_dropped():
    ideas = ["Kalyanam  EPPO?", "Love-a arranged-a?", "Veedu eppo?"]
    assert pick(ideas, [None, None, None], ASKED, [None]) == ["Love-a arranged-a?", "Veedu eppo?"]
    assert pick(["Velai?", "velai"], [None, None], [], []) == []     # a copy of the chip before it


def test_fewer_than_two_fresh_chips_show_none():
    assert pick(["கல்யாணம் எப்போ", "Veedu eppo?"], [_at(0.95), _at(0.1)], ASKED, ASKED_V) == []
    assert pick([], [], ASKED, ASKED_V) == []


def test_tamil_vowel_signs_keep_two_words_apart_in_the_copy_check():
    # வேலை (job) and வலி (pain) differ only in vowel signs: not a copy
    assert pick(["வலி எப்படி?", "Dasa?"], [None, None], ["வேலை எப்படி?"], [None]) == ["வலி எப்படி?", "Dasa?"]


# --- fresh: embeds through a cache, never fails the reply --------------------------------------------

def _counting_embed(monkeypatch, vectors: dict[str, list[float]] | None = None):
    calls = []

    async def embed(texts, kind, tenant_id, model=None, retries=True):
        calls.append(list(texts))
        return [(vectors or {}).get(t, [1.0, 0.0]) for t in texts]
    monkeypatch.setattr(memory_embed, "embed", embed)
    return calls


def test_fresh_embeds_each_text_once_and_reuses_it_on_the_next_reply(monkeypatch):
    calls = _counting_embed(monkeypatch, {"kalyanam eppo": _unit(0), "கல்யாணம் எப்போ": _at(0.9),
                                          "Love-a arranged-a?": _unit(1.0), "Veedu eppo?": _unit(2.0)})

    async def two_replies():
        chip_repeats.prefetch("t1", ["kalyanam eppo"])
        first = await chip_repeats.fresh("t1", ["கல்யாணம் எப்போ", "Love-a arranged-a?", "Veedu eppo?"],
                                         ["kalyanam eppo"])
        second = await chip_repeats.fresh("t1", ["Love-a arranged-a?", "Veedu eppo?"], ["kalyanam eppo"])
        return first, second
    first, second = asyncio.run(two_replies())
    assert first == ["Love-a arranged-a?", "Veedu eppo?"] and second == first
    assert calls == [["kalyanam eppo"], ["கல்யாணம் எப்போ", "Love-a arranged-a?", "Veedu eppo?"]]


def test_a_cache_entry_belongs_to_one_business(monkeypatch):
    calls = _counting_embed(monkeypatch)
    asyncio.run(chip_repeats.fresh("t1", ["a?", "b?"], ["c"]))
    asyncio.run(chip_repeats.fresh("t2", ["a?", "b?"], ["c"]))
    assert len(calls) == 2


def test_a_failed_embedding_falls_back_to_the_copy_check(monkeypatch):
    async def broken(*a, **kw):
        raise RuntimeError("quota")
    monkeypatch.setattr(memory_embed, "embed", broken)
    chips = asyncio.run(chip_repeats.fresh("t1", ["Kalyanam eppo?", "Love-a arranged-a?", "Veedu eppo?"],
                                           ["kalyanam eppo"]))
    assert chips == ["Love-a arranged-a?", "Veedu eppo?"]
    assert not chip_repeats._CACHE   # nothing cached, so the next reply tries again


def test_a_slow_embedding_costs_the_meaning_check_not_the_reply(monkeypatch):
    monkeypatch.setattr(chip_repeats, "WAIT_SECONDS", 0.05)

    async def slow(texts, *a, **kw):
        await asyncio.sleep(1)
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(memory_embed, "embed", slow)
    chips = asyncio.run(chip_repeats.fresh("t1", ["Kalyanam eppo?", "Velai?", "Veedu?"], ["kalyanam eppo"]))
    assert chips == ["Velai?", "Veedu?"]


def test_the_cache_keeps_only_the_newest_entries(monkeypatch):
    _counting_embed(monkeypatch)
    monkeypatch.setattr(chip_repeats, "CACHE_MAX", 3)
    asyncio.run(chip_repeats.fresh("t1", ["a?", "b?", "c?", "d?"], []))
    assert [text for _, text in chip_repeats._CACHE] == ["b?", "c?", "d?"]

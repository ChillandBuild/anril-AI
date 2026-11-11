"""Tests for the knowledge-base passage cutter (app/companion/kb/chunking.py). Pure logic, no I/O."""
import random
import statistics

from app.companion.kb.chunking import MAX_CHARS, OVERLAP, TARGET_CHARS, chunk_pages

TITLE = "Book 7"


def para(label: str, length: int, filler: str = "lorem ipsum dolor sit amet ") -> str:
    """A paragraph of exactly `length` characters (it starts with its label so it is findable)."""
    text = (label + " " + filler * (length // len(filler) + 2))[:length]
    return text.rstrip() + "x" if text.endswith(" ") else text


def one_page(*blocks: str) -> list[tuple[int, str]]:
    return [(1, "\n\n".join(blocks))]


def test_defaults_are_the_documented_ones():
    assert (TARGET_CHARS, OVERLAP, MAX_CHARS) == (1800, 0.15, 3600)


def test_empty_input_gives_nothing():
    assert chunk_pages([], title=TITLE) == []
    assert chunk_pages([(1, ""), (2, "   \n \n")], title=TITLE) == []


def test_short_page_is_one_passage_with_title_path():
    out = chunk_pages([(5, "Just a line.")], title=TITLE)
    assert out == [{"heading_path": "Book 7", "text": "Just a line.", "page_from": 5, "page_to": 5}]


def test_three_pages_are_covered_with_no_gap():
    pages = [(n, "\n\n".join(para(f"p{n}-{i}", 500) for i in range(4))) for n in (1, 2, 3)]
    out = chunk_pages(pages, title=TITLE)
    assert len(out) > 1
    for p in out:
        assert p["page_from"] <= p["page_to"]
    for n in (1, 2, 3):
        assert any(p["page_from"] <= n <= p["page_to"] for p in out)


def test_text_flows_across_a_page_boundary():
    # one paragraph that starts at the bottom of page 44 and carries on at the top of page 45
    pages = [(44, "First line of a paragraph\nsecond line"), (45, "third line\nfourth line")]
    out = chunk_pages(pages, title=TITLE)
    assert len(out) == 1
    assert out[0]["page_from"] == 44 and out[0]["page_to"] == 45
    assert out[0]["text"] == "First line of a paragraph\nsecond line\nthird line\nfourth line"


def test_missing_pages_are_simply_absent():
    out = chunk_pages([(1, "alpha"), (3, "beta")], title=TITLE)
    assert [(p["page_from"], p["page_to"]) for p in out] == [(1, 3)]


def test_table_row_is_never_cut():
    rows = [f"| row{i:03d} | " + "cell " * 8 + f"| {i} |" for i in range(100)]  # ~100 rows, longer than MAX
    table = "\n".join(["| a | b | c |", "|---|---|---|"] + rows)
    assert len(table) > MAX_CHARS
    pages = [(1, para("intro", 1500) + "\n\n" + table + "\n\n" + para("outro", 400))]
    out = chunk_pages(pages, title=TITLE)
    all_rows = set(rows) | {"| a | b | c |", "|---|---|---|"}
    for r in all_rows:
        assert any(r in p["text"] for p in out), r
    for p in out:
        for line in p["text"].split("\n"):
            if line.startswith("|"):
                assert line in all_rows, f"half a row: {line!r}"
        assert len(p["text"]) <= MAX_CHARS


def test_small_table_across_the_target_stays_whole():
    rows = [f"| r{i:02d} | " + "cell " * 8 + "|" for i in range(30)]
    table = "\n".join(rows)  # ~1700 chars, fits in one block
    out = chunk_pages(one_page(para("lead", 1000), table), title=TITLE)
    holders = [p for p in out if rows[0] in p["text"]]
    assert len(holders) == 1
    assert all(r in holders[0]["text"] for r in rows)


def test_verse_on_the_boundary_stays_in_one_passage():
    stanza = [f"Line {i} of the verse " + "la " * 19 + "la" for i in range(4)]
    verse = "\n".join(stanza)
    first = para("before", 1500)
    assert len(first) + 2 + len(verse) > TARGET_CHARS  # it really sits on the boundary
    out = chunk_pages(one_page(first, verse, para("after", 300)), title=TITLE)
    assert any(verse in p["text"] for p in out)
    for line in stanza:  # and no passage holds only part of it
        for p in out:
            if line in p["text"]:
                assert verse in p["text"]


def test_heading_path_follows_levels():
    text = "\n\n".join([
        "# Chapter 4", "intro to four",
        "## Saturn", "saturn text",
        "## Mars", "mars text",
        "# Chapter 5", "five text",
    ])
    out = chunk_pages([(1, text)], title=TITLE)
    paths = [p["heading_path"] for p in out]
    assert paths == [
        "Book 7 > Chapter 4",
        "Book 7 > Chapter 4 > Saturn",
        "Book 7 > Chapter 4 > Mars",
        "Book 7 > Chapter 5",
    ]
    assert out[1]["text"].startswith("## Saturn")  # the heading line stays in the passage it opens


def test_deeper_heading_replaces_deeper_and_shallower_clears():
    text = "# A\n\na\n\n### C\n\nc\n\n## B\n\nb\n\n# D\n\n#### E\n\ne"
    paths = [p["heading_path"] for p in chunk_pages([(1, text)], title=TITLE)]
    assert paths == ["Book 7 > A", "Book 7 > A > C", "Book 7 > A > B", "Book 7 > D", "Book 7 > D > E"]


def test_text_before_first_heading_gets_the_title_only():
    out = chunk_pages([(1, "preface line\n\n# Chapter 1\n\nbody")], title=TITLE)
    assert [p["heading_path"] for p in out] == ["Book 7", "Book 7 > Chapter 1"]


def test_heading_always_starts_a_new_passage():
    out = chunk_pages([(1, "tiny\n\n# H\n\nalso tiny")], title=TITLE)
    assert len(out) == 2
    assert out[0]["text"] == "tiny"
    assert out[1]["text"] == "# H\nalso tiny"  # the heading stays glued to its first block


def test_hash_without_space_is_not_a_heading():
    out = chunk_pages([(1, "#hashtag line\n\nmore")], title=TITLE)
    assert [p["heading_path"] for p in out] == ["Book 7"]


def test_overlap_repeats_the_last_paragraph():
    paras = [para(f"P{i}", 600) for i in range(6)]
    out = chunk_pages(one_page(*paras), title=TITLE, overlap=0.4)  # budget 720 >= one 600-char paragraph
    assert len(out) >= 3
    last_of_first = out[0]["text"].split("\n\n")[-1]
    assert last_of_first == paras[1]
    assert out[1]["text"].startswith(paras[1])
    assert out[1]["text"].split("\n\n")[0] == last_of_first


def test_overlap_skipped_when_last_block_is_bigger_than_budget():
    paras = [para(f"P{i}", 600) for i in range(6)]
    out = chunk_pages(one_page(*paras), title=TITLE)  # default budget is 270 < 600
    assert len(out) >= 3
    texts = [p["text"] for p in out]
    for a, b in zip(texts, texts[1:]):
        assert a.split("\n\n")[-1] not in b  # nothing repeated, and no block was cut to make overlap
    assert "\n\n".join(texts) == "\n\n".join(paras)


def test_default_overlap_takes_whole_small_blocks():
    paras = [para(f"S{i}", 200) for i in range(30)]
    out = chunk_pages(one_page(*paras), title=TITLE)
    assert len(out) > 2
    for a, b in zip(out, out[1:]):
        assert b["text"].startswith(a["text"].split("\n\n")[-1])
        carried = 0
        for blk in b["text"].split("\n\n"):
            if blk in a["text"]:
                carried += len(blk)
        assert 0 < carried <= OVERLAP * TARGET_CHARS + 2


def test_overlap_never_crosses_a_heading():
    paras = [para(f"S{i}", 200) for i in range(12)]
    text = "\n\n".join(paras) + "\n\n# New\n\n" + para("fresh", 200)
    out = chunk_pages([(1, text)], title=TITLE)
    last = out[-1]
    assert last["heading_path"] == "Book 7 > New"
    assert last["text"] == "# New\n" + para("fresh", 200)


def test_overlap_zero_means_no_repeat():
    paras = [para(f"S{i}", 200) for i in range(30)]
    out = chunk_pages(one_page(*paras), title=TITLE, overlap=0)
    assert "\n\n".join(p["text"] for p in out) == "\n\n".join(paras)


def test_giant_block_is_split_at_line_breaks():
    lines = [f"line {i:03d} " + "w" * 50 for i in range(100)]  # ~6,000 characters, no blank line
    block = "\n".join(lines)
    assert len(block) > 5500
    out = chunk_pages([(1, block)], title=TITLE)
    assert len(out) >= 2
    for p in out:
        assert len(p["text"]) <= MAX_CHARS
        for line in p["text"].split("\n"):
            assert line in lines  # only whole lines
    for ln in lines:
        assert any(ln in p["text"] for p in out)


def test_giant_block_overlap_uses_whole_trailing_lines():
    lines = [f"line {i:03d} " + "w" * 50 for i in range(100)]
    out = chunk_pages([(1, "\n".join(lines))], title=TITLE)
    first, second = out[0]["text"].split("\n"), out[1]["text"].split("\n")
    assert second[0] in first  # begins with lines the previous passage ended with
    assert first[-1] in second


def test_single_giant_line_splits_at_sentences_then_spaces():
    sentence = "This is one sentence of the long line. "
    line = sentence * 200  # ~7,800 chars, one line
    out = chunk_pages([(1, line)], title=TITLE)
    assert len(out) >= 2
    for p in out:
        assert len(p["text"]) <= MAX_CHARS
        assert p["text"].rstrip().endswith(".")  # cut at a sentence end
    no_period = "word " * 1500  # 7,500 chars, no sentence end at all
    out2 = chunk_pages([(1, no_period)], title=TITLE)
    assert len(out2) >= 2
    for p in out2:
        assert len(p["text"]) <= MAX_CHARS
        assert p["text"].split()[0] == "word" and set(p["text"].split()) == {"word"}  # cut at a space, no word cut


def test_no_empty_passages_and_every_line_is_kept():
    rng = random.Random(7)
    blocks = []
    for i in range(80):
        n = rng.randint(1, 5)
        blocks.append("\n".join(f"b{i}l{j} " + "z" * rng.randint(5, 300) for j in range(n)))
        if i % 17 == 0:
            blocks.append(f"## Heading {i}")
    pages = [(k + 1, "\n\n".join(blocks[k * 10:(k + 1) * 10])) for k in range(10)]
    out = chunk_pages(pages, title=TITLE)
    assert all(p["text"].strip() for p in out)
    kept = "\n".join(p["text"] for p in out)
    for _, text in pages:
        for line in text.split("\n"):
            if line.strip():
                assert line in kept


def test_median_passage_is_near_the_target():
    rng = random.Random(3)
    paras = [para(f"R{i}", rng.randint(300, 900)) for i in range(120)]
    out = chunk_pages(one_page(*paras), title=TITLE)
    assert 1000 <= statistics.median(len(p["text"]) for p in out) <= 2600


def test_target_parameter_is_respected():
    paras = [para(f"R{i}", 300) for i in range(40)]
    small = chunk_pages(one_page(*paras), title=TITLE, target=700)
    big = chunk_pages(one_page(*paras), title=TITLE, target=3000)
    assert len(small) > len(big)


def test_tamil_behaves_like_english():
    tamil = "சனி பகவான் ஏழரை சனி "
    ta = [para(f"த{i}", 450, filler=tamil) for i in range(20)]
    en = [para(f"e{i}", 450) for i in range(20)]
    assert all(len(x) == 450 for x in ta)  # length is in characters, not bytes
    out_ta = chunk_pages(one_page(*ta), title=TITLE)
    out_en = chunk_pages(one_page(*en), title=TITLE)
    assert [len(p["text"]) for p in out_ta] == [len(p["text"]) for p in out_en]
    for p in out_ta:
        assert p["text"].startswith("த")
    out_h = chunk_pages([(1, "# அத்தியாயம் 4\n\n## சனி\n\nசனி பகவான்")], title="நூல் 7")
    assert out_h[-1]["heading_path"] == "நூல் 7 > அத்தியாயம் 4 > சனி"

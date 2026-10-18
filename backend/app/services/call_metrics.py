"""Talk share (by words) and the caps the two numbers put on Listening and Courtesy."""
from collections import Counter
from typing import Callable, TypeVar

from app.services.call_lines import Line
from app.services.scoring_rules import (
    DEAD_AIR_MIN_S, INTERRUPTIONS_GOOD_MAX, INTERRUPTIONS_SOMETIMES_MAX, LEVEL_ORDER,
    MONOLOGUE_GAP_S, TALK_SHARE_HEALTHY_MAX, TALK_SHARE_HIGH_MAX, TALK_SHARE_MIN_WORDS,
    TALK_SHARE_PASSIVE,
)

_T = TypeVar("_T")
_Segment = tuple[float, float]


def plurality(votes: list[_T], tie_break: Callable[[list[_T]], _T]) -> _T:
    """The most common vote; tie_break(winners) resolves when more than one value ties for the lead."""
    counts = Counter(votes)
    top = max(counts.values())
    winners = [v for v, n in counts.items() if n == top]
    return winners[0] if len(winners) == 1 else tie_break(winners)

_FILLERS = {
    "hmm", "hm", "hmmm", "mm", "mmm", "uh", "uhh", "um", "umm", "aah", "ah", "aa", "haan",
    "ம்ம்", "ம்", "ஆ", "ஆஆ", "ஹ்ம்",
}
_OK = {"ok", "okay"}
_STRIP = ".,!?…\"'()[]:;-—"


def _count_words(text: str) -> int:
    tokens = [t.strip(_STRIP).lower() for t in text.split()]
    tokens = [t for t in tokens if t and t not in _FILLERS]
    if tokens and all(t in _OK for t in tokens):
        return 0  # "ok ok" on its own is a filler
    return len(tokens)


def talk_share(lines: list[Line]) -> float | None:
    """Telecaller's share of all words spoken, 0-100. None when too few words to mean anything."""
    tele = sum(_count_words(l.text) for l in lines if l.speaker == "telecaller")
    cust = sum(_count_words(l.text) for l in lines if l.speaker == "customer")
    total = tele + cust
    if total < TALK_SHARE_MIN_WORDS:
        return None
    return round(tele / total * 100, 2)


def lower_level(a: str, b: str) -> str:
    return a if LEVEL_ORDER.index(a) <= LEVEL_ORDER.index(b) else b


def listening_cap(share: float | None, ipm: float | None) -> str:
    high_share = share is not None and share > TALK_SHARE_HIGH_MAX
    mid_share = share is not None and share > TALK_SHARE_HEALTHY_MAX
    high_int = ipm is not None and ipm > INTERRUPTIONS_SOMETIMES_MAX
    mid_int = ipm is not None and ipm > INTERRUPTIONS_GOOD_MAX
    if high_share and high_int:
        return "poor"
    if high_share or high_int:
        return "partial"
    if mid_share or mid_int:
        return "good"
    return "excellent"


def listening_cap_reason(share: float | None, ipm: float | None) -> tuple[str, str | None]:
    """Return (cap, reason) for listening — reason identifies which metric(s) caused the cap."""
    cap = listening_cap(share, ipm)
    if cap == "excellent":
        return cap, None
    if cap == "poor":
        return cap, "talk_share_and_interruptions"

    # Compute individual caps
    share_cap = "excellent"
    if share is not None and share > TALK_SHARE_HIGH_MAX:
        share_cap = "partial"
    elif share is not None and share > TALK_SHARE_HEALTHY_MAX:
        share_cap = "good"

    ipm_cap = "excellent"
    if ipm is not None and ipm > INTERRUPTIONS_SOMETIMES_MAX:
        ipm_cap = "partial"
    elif ipm is not None and ipm > INTERRUPTIONS_GOOD_MAX:
        ipm_cap = "good"

    # Determine reason based on which individual caps match the combined cap
    if share_cap == cap and ipm_cap == cap:
        reason = "talk_share_and_interruptions"
    elif share_cap == cap:
        reason = "talk_share"
    else:
        reason = "interruptions"

    return cap, reason


def courtesy_cap(ipm: float | None) -> str:
    return "good" if ipm is not None and ipm > INTERRUPTIONS_SOMETIMES_MAX else "excellent"


def tips(share: float | None, ipm: float | None) -> list[str]:
    out = []
    if share is not None and share > TALK_SHARE_HEALTHY_MAX:
        out.append(f"Let the customer speak more. Aim to talk less than {TALK_SHARE_HEALTHY_MAX}% of the time.")
    if share is not None and share < TALK_SHARE_PASSIVE:
        out.append("Guide the conversation more: ask questions and explain the next step.")
    if ipm is not None and ipm > INTERRUPTIONS_GOOD_MAX:
        out.append("Let the customer finish before you reply.")
    return out


def longest_monologue(segments: list[_Segment]) -> float:
    """Longest unbroken telecaller run in seconds; gaps under MONOLOGUE_GAP_S keep a run going."""
    longest = 0.0
    run_start = run_end = None
    for start, end in sorted(segments):
        if run_end is not None and start - run_end < MONOLOGUE_GAP_S:
            run_end = max(run_end, end)
            continue
        if run_start is not None:
            longest = max(longest, run_end - run_start)
        run_start, run_end = start, end
    if run_start is not None:
        longest = max(longest, run_end - run_start)
    return round(longest, 1)


def dead_air(telecaller_segments: list[_Segment], customer_segments: list[_Segment]) -> float:
    """Seconds of silence between the first and last speech, counting only gaps of DEAD_AIR_MIN_S or more."""
    total = 0.0
    merged_end = None
    for start, end in sorted(telecaller_segments + customer_segments):
        if merged_end is not None and start - merged_end >= DEAD_AIR_MIN_S:
            total += start - merged_end
        merged_end = end if merged_end is None else max(merged_end, end)
    return round(total, 1)

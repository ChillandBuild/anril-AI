"""The opt-in "reply format": a reply as short chat bubbles, plus follow-up chips, an optional button and a tag.

Pure functions, no I/O. Switched on per request (ServerChatIn.reply_format); without it nothing here runs.
Generic on purpose: the button ids and when to show them come from the request, never from code.

Example, with buttons porutham / astrologer (handoff) / helpline. The model writes, after [mood] [used]:
    [tag: counted] [button: porutham]
    Karthik, unga 7th house la Guru irukku.
    ---
    Porutham paartha innum theliva sollalaam.
    [chips: Kalyanam eppo nadakkum? | Velai eppadi irukkum?]
read_format -> bubbles ["Karthik, unga 7th house la Guru irukku.", "Porutham paartha innum theliva sollalaam."],
chips ["Kalyanam eppo nadakkum?", "Velai eppadi irukkum?"], button "porutham", tag "counted".
finalize then applies the code-side rules (a failed call, a Strict hand-off, no chips when nothing is counted).

Chips: the model writes up to CHIP_IDEAS ideas and the engine shows CHIPS of them, the first that repeat no
question the person already asked (chip_repeats.py, by meaning). Those questions ride on ReplyFormat.asked
(set by the engine, never by the request) and are NOT listed in the prompt: listed, flash-lite copied them
back as chips (41% of 196 ideas repeated one, against 24% of 184 unlisted; chips eval, 28 Nov 2026).
"""
import re
from typing import Annotated, NamedTuple

from pydantic import (BaseModel, ConfigDict, Field, PrivateAttr, StringConstraints, field_validator,
                      model_validator)

from app.companion.prompt import fence

GENERIC_TAGS = ("counted", "ask_back", "greeting", "off_topic", "need_details")
RESERVED_IDS = GENERIC_TAGS + ("none", "failed", "handoff")   # tags code sets itself
MAX_BUBBLES = 3
CHIPS = 2
MAX_BUTTONS = 6
MAX_CHIP_CHARS = 80
CHIP_IDEAS = 4      # ideas the model writes, so a repeat dropped by code still leaves a pair
ASKED_DAYS = 7      # a chip never repeats what the person asked in this many days
ASKED_MAX = 30      # the newest of those questions, checked against the chips
ASKED_CHARS = 120   # each cut to this (a long message is no chip anyone would repeat word for word)

ButtonId = Annotated[str, StringConstraints(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")]
When = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ButtonSpec(BaseModel):
    """One button the app can show under a reply. id and its meaning are the business's, e.g.
    {"id": "astrologer", "when": "the question is very personal", "handoff": true}."""
    model_config = ConfigDict(extra="forbid")
    id: ButtonId
    when: When          # business text: fenced in the prompt
    handoff: bool = False   # the button a Strict character's hand-off points to (at most one)

    @field_validator("id")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value in RESERVED_IDS:
            raise ValueError(f"button id '{value}' is reserved; pick another")
        return value


class ReplyFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buttons: list[ButtonSpec] = Field(default_factory=list, max_length=MAX_BUTTONS)
    questions_left: int | None = Field(None, ge=0)   # 0 = no chips (the person can't ask more); None = unknown
    _asked: list[str] = PrivateAttr(default_factory=list)   # set by the engine (with_asked), never by the request

    @model_validator(mode="after")
    def _ids_unique_one_handoff(self) -> "ReplyFormat":
        ids = [b.id for b in self.buttons]
        if len(set(ids)) != len(ids):
            raise ValueError("button ids must be unique")
        if sum(b.handoff for b in self.buttons) > 1:
            raise ValueError("at most one button may have handoff: true")
        return self

    def ids(self) -> set[str]:
        return {b.id for b in self.buttons}

    @property
    def asked(self) -> list[str]:
        """The questions this person asked in the last ASKED_DAYS days, oldest first. [] until set."""
        return self._asked

    def with_asked(self, questions: list[str]) -> "ReplyFormat":
        """A copy carrying the person's questions (oldest first), each once at its newest place, cut to
        ASKED_CHARS, the newest ASKED_MAX: with_asked(["Velai?", "kalyanam eppo", "velai?"]).asked ->
        ["kalyanam eppo", "velai?"]."""
        newest, seen = [], set()
        for question in reversed(questions):
            text = " ".join((question or "").split())[:ASKED_CHARS].strip()
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                newest.append(text)
        copy = self.model_copy()
        copy._asked = list(reversed(newest[:ASKED_MAX]))
        return copy


class Shaped(NamedTuple):
    bubbles: list[str]
    chips: list[str]
    button: str | None
    tag: str | None


def format_block(fmt: ReplyFormat) -> str:
    """The [REPLY FORMAT] prompt section (goes right after [OUTPUT])."""
    tags = ("counted = a real answer to their question; ask_back = you only ask something you need before "
            "answering; greeting = hello, thanks, ok, small talk; off_topic = not your subject, or you decline; "
            "need_details = you need their details or another person's profile first")
    if fmt.buttons:
        tags += "; or a button id when the reply only points them to that button"
        buttons = ("2. [button: ID] or [button: none]. At most one. Buttons (id: when, set by the business):\n"
                   + "\n".join(f"- {b.id}: {' '.join(fence(b.when).split())}" for b in fmt.buttons))
    else:
        buttons = "2. [button: none]"
    return (
        "[REPLY FORMAT]\nAfter [mood] and [used], write:\n"
        f"1. [tag: X]. X: {tags}.\n"
        f"{buttons}\n"
        f"3. The reply: 1 to {MAX_BUBBLES} short chat bubbles, each 1 to 3 short lines, with a line holding only "
        "--- between bubbles. A small question gets 1 bubble. No headings, lists or bold.\n"
        f"4. Last line: [chips: question | question | question | question]: {CHIP_IDEAS} short follow-up "
        "questions they might tap next, as they would type them, in their own language and script, at most 6 "
        "words each. First: deeper on this topic. Then linked new topics. Never one they already asked, in any "
        "wording or script. [chips: none] when the tag is not counted, or they are distressed or frightened.\n"
        "Never show tags, button ids or chips inside a bubble."
    )


def _tag_re(name: str) -> re.Pattern:
    return re.compile(r"[ \t]*\[\s*" + name + r"\s*:([^\]\n]*)\][ \t]*", re.IGNORECASE)


_TAG, _BUTTON, _CHIPS = _tag_re("tag"), _tag_re("button"), _tag_re("chips")
_SEPARATOR = re.compile(r"^[ \t]*-{3,}[ \t]*$", re.MULTILINE)
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def strip_tags(text: str) -> str:
    """'Vanakkam [button: x] Karthik.\\n[chips: a | b]' -> 'Vanakkam Karthik.' Each line stripped."""
    for pattern in (_TAG, _BUTTON, _CHIPS):
        text = pattern.sub(" ", text or "")
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def _values(pattern: re.Pattern, text: str) -> list[str]:
    return [v.strip() for v in pattern.findall(text or "")]


def _bubbles(text: str) -> list[str]:
    parts = _SEPARATOR.split(text) if _SEPARATOR.search(text) else _BLANK_LINE.split(text)
    parts = [_BLANK_LINE.sub("\n", p.strip()) for p in parts if p.strip()]   # a gap inside a bubble closes up
    if len(parts) > MAX_BUBBLES:   # merge the extras into the last bubble: no text is lost
        parts = parts[:MAX_BUBBLES - 1] + ["\n".join(parts[MAX_BUBBLES - 1:])]
    return parts


def _chips(text: str) -> list[str]:
    """The chip ideas: '[chips: Eppo? › | velai? | Velai? | none-too-long...]' -> ['Eppo?', 'velai?'], at most
    CHIP_IDEAS, each once (case aside) and at most MAX_CHIP_CHARS. Which CHIPS of them show is the engine's
    (chip_repeats.fresh); [chips: none] -> []."""
    for value in _values(_CHIPS, text):
        ideas: list[str] = []
        for part in value.split("|"):
            chip = part.strip().rstrip("›>").strip()
            if (chip and chip.casefold() != "none" and len(chip) <= MAX_CHIP_CHARS
                    and chip.casefold() not in {c.casefold() for c in ideas}):
                ideas.append(chip)
        return ideas[:CHIP_IDEAS]
    return []


def read_format(text: str, fmt: ReplyFormat) -> Shaped:
    """The reply (mood/used tags already removed) -> Shaped. Invalid button/tag -> None. chips: the ideas,
    not yet checked for repeats (the engine does that)."""
    ids = fmt.ids()
    button = next((v.lower() for v in _values(_BUTTON, text) if v.lower() in ids), None)
    tag = next((v.lower() for v in _values(_TAG, text) if v.lower() in GENERIC_TAGS or v.lower() in ids), None)
    return Shaped(bubbles=_bubbles(strip_tags(text)), chips=_chips(text), button=button, tag=tag)


def finalize(shaped: Shaped, fmt: ReplyFormat, *, small_talk: bool, handed_off: bool, failed: bool,
             fallback_text: str, text: str = "", own: bool = False) -> Shaped:
    """Code-side rules over what the model wrote. text: the reply read_format was given, used only when
    no bubble came out of it (e.g. a lone '---'). own: the answer came from the model's own reading, not
    the business's files -> it keeps its bubbles and chips and also gets the handoff button ("astrologer"),
    unless the model chose a button itself."""
    if not failed and not shaped.bubbles:
        rest = strip_tags(text)
        if rest:
            shaped = shaped._replace(bubbles=[rest])
        else:
            failed = True
    if failed:
        return Shaped([fallback_text], [], None, "failed")
    if handed_off:
        target = next((b.id for b in fmt.buttons if b.handoff), None)
        return Shaped([fallback_text], [], target, target or "handoff")
    tag = shaped.tag or ("greeting" if small_talk else "counted")
    if shaped.button and tag != "counted":
        tag = shaped.button   # "[tag: ask_back] [button: helpline]" is a helpline reply: the button names its kind
    chips = shaped.chips if tag == "counted" and fmt.questions_left != 0 else []
    button = shaped.button
    if own and button is None and tag == "counted":
        button = next((b.id for b in fmt.buttons if b.handoff), None)
    return Shaped(shaped.bubbles, chips, button, tag)

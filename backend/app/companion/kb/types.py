"""The two shapes kb-search hands to the reply path. No I/O, no imports from the rest of kb.

Example: Priya asks Guru about Saturn in the 7th house. search() returns
    KbResult(needs_docs=True, topic="Saturn in the seventh house and marriage delay",
             passages=(Passage(document_title="Main resource", tier=1, page_from=12, page_to=12, ...),))
The prompt numbers the passages (1), (2), ... in this order; "[used: 1]" in the reply points back at them.
"""
from dataclasses import asdict, dataclass, field, fields


@dataclass(frozen=True)
class Passage:
    id: str
    document_id: str
    document_title: str
    tier: int                 # 1 = main resource, 2 = other books
    heading_path: str
    text: str
    page_from: int
    page_to: int
    score: int = 0            # the judge's mark, 0..3


@dataclass(frozen=True)
class KbResult:
    needs_docs: bool = True               # False: small talk, the books were not searched
    passages: tuple[Passage, ...] = ()    # in prompt order
    topic: str | None = None              # de-personalised English topic, the only text the question log keeps
    shortcut_id: str | None = None        # the learned shortcut tried this turn, if any
    shortcut_hit: bool = False
    failed: bool = False                  # search broke; the reply goes on without passages
    # The topic's embedding, kept only so the question log does not pay for it twice. Not part of
    # equality and never saved with a pending turn (768 numbers; a resumed turn logs without it).
    topic_embedding: tuple[float, ...] | None = field(default=None, compare=False, repr=False)

    def to_json(self) -> dict:
        """Saved on a pending turn, so a reply that paused for an app tool keeps its passage list."""
        data = asdict(self)
        data.pop("topic_embedding", None)
        return data

    @classmethod
    def from_json(cls, data: dict | None) -> "KbResult | None":
        if not isinstance(data, dict):
            return None
        known = {f.name for f in fields(Passage)}
        passages = tuple(Passage(**{k: v for k, v in p.items() if k in known})
                         for p in data.get("passages") or [] if isinstance(p, dict))
        return cls(needs_docs=bool(data.get("needs_docs", True)), passages=passages, topic=data.get("topic"),
                   shortcut_id=data.get("shortcut_id"), shortcut_hit=bool(data.get("shortcut_hit")),
                   failed=bool(data.get("failed")))

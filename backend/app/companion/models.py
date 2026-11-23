"""Pydantic models for companion settings (the character card) and the reply contract."""
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.companion.languages import read_language
from app.companion.platform_rules import MOODS

Mood = Literal["calm", "warm", "happy", "concerned", "encouraging", "serious"]
assert set(Mood.__args__) == set(MOODS)  # keep the Literal and the constant in step

SampleLine = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Goal = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Rule = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Language = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]
MAX_RULES = 40      # = companions_rules_check (migration 275)


DEFAULT_MODEL = "google/gemini-3.1-flash-lite"   # = ai_reply.DEFAULT_REPLY_MODEL (a test keeps them equal)

MAX_APP_DATA_CHARS = 12000   # = companion_end_users_test_app_data_check (migration 316)


def app_data_text(value: str | dict | None) -> str | None:
    """What the client's app knows about this person, as one block of text for the prompt.

    Example: {"lagna": "மீனம்", "dasa": "ராகு"} -> '{"lagna": "மீனம்", "dasa": "ராகு"}' (Tamil kept as is);
    "plan: Gold, ends 30 Nov" stays as typed. None or blank -> None. Over 12,000 characters -> ValueError."""
    if value is None:
        return None
    text = (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).strip()
    if not text:
        return None
    if len(text) > MAX_APP_DATA_CHARS:
        raise ValueError(f"app_data is over {MAX_APP_DATA_CHARS} characters")
    return text


AppData = Annotated[str | dict | None, AfterValidator(app_data_text)]

def reply_language_text(value: str | None) -> str | None:
    """The language the app wants this reply in ("en", "English", "Tamil, written in Tamil script"), checked
    by languages.read_language: an unknown language is a 422. Blank -> None (the character's own)."""
    if value is None or not value.strip():
        return None
    read_language(value)
    return " ".join(value.split())


ReplyLanguage = Annotated[str | None, Field(None, max_length=60), AfterValidator(reply_language_text)]


def _known_model(value: str | None) -> str | None:
    """A character's model must be on ai_reply.REPLY_MODELS. Adding a model there is all it takes."""
    from app.services.ai_reply import REPLY_MODELS   # lazy: ai_reply pulls in the whole services layer
    if value is not None and value not in REPLY_MODELS:
        raise ValueError("Pick one of the listed AI models")
    return value


class _CardFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("model", "small_talk_model", check_fields=False)
    @classmethod
    def _model_is_known(cls, value: str | None) -> str | None:
        return _known_model(value)

    @field_validator("handoff_line", check_fields=False)
    @classmethod
    def _blank_handoff_is_none(cls, value: str | None) -> str | None:
        """"  " -> None, so a cleared box goes back to the generic line."""
        return (value or "").strip() or None


class CompanionSettings(_CardFields):
    """A new character. Example: Jothidar AI, astrology, Tanglish, books tag = 'astrology books'."""
    name: Name
    industry: Literal["astrology", "general"] = "general"
    role: str = Field("", max_length=500)
    backstory: str = Field("", max_length=2000)
    speaking_style: str = Field("", max_length=1000)
    sample_lines: list[SampleLine] = Field(default_factory=list, max_length=10)
    goals: list[Goal] = Field(default_factory=list, max_length=5)
    temperament: str = Field("", max_length=300)
    default_mood: Mood = "calm"
    language: Language = "ta-en"
    model: str = DEFAULT_MODEL                 # the AI model every reply uses, e.g. "google/gemini-3.8-flash"
    small_talk_model: str | None = None        # cheaper model for greetings and chit-chat; None = model
    rules: list[Rule] = Field(default_factory=list, max_length=MAX_RULES)
    knowledge_tag_id: UUID | None = None     # old Anril Sales books tag: still accepted, no longer read
    knowledge_collection_id: UUID | None = None   # the collection of books this character reads
    own_reasoning: bool = True               # False = "Strict": an answer from no file becomes the handoff line
    handoff_line: str | None = Field(None, max_length=300)   # Strict's line; None = the generic one
    full_main_resource: bool = False         # send the main resource whole with every real question (≤40,000 chars)
    working_step: bool = False               # think in a hidden <working> block before replying (not small talk)
    chart_guard: bool = False                # astrology: no birth details to the model, replies checked against the chart
    memory_level: Literal[1, 2] = 1          # 3 (graph memory) is not built
    memory_engine: Literal["card", "mem0"] = "card"   # which Level 2 engine; ignored at Level 1
    history_messages: int = Field(10, ge=2, le=50)   # recent messages every reply reads
    privacy_mode: Literal["A", "B"] = "A"
    status: Literal["draft", "live", "paused"] = "draft"


class CompanionUpdate(_CardFields):
    """A partial update: only the fields sent are changed."""
    name: Name | None = None
    industry: Literal["astrology", "general"] | None = None
    role: str | None = Field(None, max_length=500)
    backstory: str | None = Field(None, max_length=2000)
    speaking_style: str | None = Field(None, max_length=1000)
    sample_lines: list[SampleLine] | None = Field(None, max_length=10)
    goals: list[Goal] | None = Field(None, max_length=5)
    temperament: str | None = Field(None, max_length=300)
    default_mood: Mood | None = None
    language: Language | None = None
    model: str | None = None
    small_talk_model: str | None = None
    rules: list[Rule] | None = Field(None, max_length=MAX_RULES)
    knowledge_tag_id: UUID | None = None
    knowledge_collection_id: UUID | None = None
    own_reasoning: bool | None = None
    handoff_line: str | None = Field(None, max_length=300)
    full_main_resource: bool | None = None
    working_step: bool | None = None
    chart_guard: bool | None = None
    memory_level: Literal[1, 2] | None = None
    memory_engine: Literal["card", "mem0"] | None = None
    history_messages: int | None = Field(None, ge=2, le=50)
    privacy_mode: Literal["A", "B"] | None = None
    status: Literal["draft", "live", "paused"] | None = None

    def changes(self) -> dict:
        """Fields the caller actually sent. Only knowledge_tag_id, knowledge_collection_id, handoff_line and
        small_talk_model may be sent as null (clears them); a null for any other field is ignored, since those
        columns are NOT NULL."""
        sent = self.model_dump(mode="json", exclude_unset=True)
        clearable = ("knowledge_tag_id", "knowledge_collection_id", "handoff_line", "small_talk_model")
        return {k: v for k, v in sent.items() if v is not None or k in clearable}


class AppTool(_CardFields):
    """A tool the client's own app runs (e.g. Astrotamil's get_chart). Sent with each message;
    we never store or call it. Size limits and the LLM format live in tools.py (T6)."""
    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
    description: str = Field(max_length=500)
    parameters: dict = Field(default_factory=dict)


class ToolResult(_CardFields):
    """What the client's app sends back for one tool call (output is capped to 4,000 chars later)."""
    id: str = Field(min_length=1, max_length=100)
    output: dict | str | None = None

    @field_validator("output")
    @classmethod
    def _not_huge(cls, v):
        if v is not None and len(v if isinstance(v, str) else json.dumps(v)) > 64_000:
            raise ValueError("tool output is over 64 KB")
        return v


class ReplySource(BaseModel):
    """One passage a reply relied on, e.g. Book 7, pages 212 to 212."""
    document: str            # the title the owner gave
    page_from: int
    page_to: int


class CompanionReply(BaseModel):
    """What reply() returns. 'done' carries the text; 'tool_call' (T6) carries a turn_id.

    basis says where the answer came from: 'primary' (main resource), 'book', 'own' (the character's
    own reasoning) or 'chat' (small talk). None for a character with no collection, and on tool_call."""
    status: Literal["done", "tool_call"]
    text: str | None = None
    mood: str | None = None
    turn_id: str | None = None
    tool_calls: list[dict] = Field(default_factory=list)
    conversation_id: str | None = None   # None only for the Playground's "without memory" reply
    message_id: str | None = None
    basis: Literal["primary", "book", "own", "chat"] | None = None
    sources: list[ReplySource] = Field(default_factory=list)
    # Only when the request sent a reply_format (reply_format.py); all None otherwise. text is then the
    # bubbles joined by a blank line. tag tells the app whether to count the question: "counted", "ask_back",
    # "greeting", "off_topic", "need_details", a button id, "handoff" or "failed".
    bubbles: list[str] | None = None
    chips: list[str] | None = None
    button: str | None = None
    tag: str | None = None


class MemoryFact(BaseModel):
    """One remembered fact, as shown to the end user or (privacy mode A) the business owner.
    learned_by = the name of the character the person told it to."""
    id: str
    section: Literal["profile", "people", "life", "preferences", "threads"]
    text: str
    valid_from: str | None = None
    valid_to: str | None = None
    status: Literal["active", "closed"]
    learned_by: str


class MemoryScopeIn(_CardFields):
    memory_scope: Literal["character", "business"]

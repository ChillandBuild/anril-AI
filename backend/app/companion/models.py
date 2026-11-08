"""Pydantic models for companion settings (the character card) and the reply contract."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.companion.platform_rules import MOODS

Mood = Literal["calm", "warm", "happy", "concerned", "encouraging", "serious"]
assert set(Mood.__args__) == set(MOODS)  # keep the Literal and the constant in step

SampleLine = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Goal = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Rule = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Language = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]


class _CardFields(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    rules: list[Rule] = Field(default_factory=list, max_length=30)
    knowledge_tag_id: UUID | None = None
    memory_level: Literal[1, 2] = 1          # 3 (graph memory) arrives with companion-memory
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
    rules: list[Rule] | None = Field(None, max_length=30)
    knowledge_tag_id: UUID | None = None
    memory_level: Literal[1, 2] | None = None
    privacy_mode: Literal["A", "B"] | None = None
    status: Literal["draft", "live", "paused"] | None = None

    def changes(self) -> dict:
        """Fields the caller actually sent. Only knowledge_tag_id may be sent as null (clears the tag);
        a null for any other field is ignored, since those columns are NOT NULL."""
        sent = self.model_dump(mode="json", exclude_unset=True)
        return {k: v for k, v in sent.items() if v is not None or k == "knowledge_tag_id"}

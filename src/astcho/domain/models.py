from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PlannerDecision(BaseModel):
    action: Literal["reply", "no_reply"] = "no_reply"
    reason: str = Field(default="", max_length=200)
    target_message_id: str | None = None
    excitement_delta: float = Field(default=0.0, ge=-0.2, le=0.2)
    shyness_delta: float = Field(default=0.0, ge=-0.2, le=0.2)
    affinity_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    should_meme: bool = False
    meme_query: str | None = Field(default=None, max_length=80)


class ReplyPayload(BaseModel):
    reply: str = Field(min_length=1, max_length=1000)

    @field_validator("reply")
    @classmethod
    def clean_reply(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reply cannot be blank")
        return value


class MemoryAtom(BaseModel):
    content: str = Field(min_length=2, max_length=500)
    importance: int = Field(default=5, ge=1, le=10)
    kind: Literal["short", "long"] = "short"


class MemoryExtraction(BaseModel):
    memories: list[MemoryAtom] = Field(default_factory=list, max_length=10)


class VisionResult(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    is_sticker: bool = False
    tags: list[str] = Field(default_factory=list, max_length=10)
    inclination: str = Field(default="neutral", max_length=80)


class MemeSelection(BaseModel):
    selected_index: int | None = Field(default=None, ge=0)


class RetrievedMemory(BaseModel):
    memory_id: str
    content: str
    score: float
    kind: str
    group_id: str
    user_id: str


class ChatMessage(BaseModel):
    message_id: str
    user_id: str
    nickname: str
    text: str
    timestamp: float
    is_bot: bool = False
    mentioned_bot: bool = False
    replied_to_bot: bool = False
    image_description: str = ""


from __future__ import annotations

from astcho.config import Settings
from astcho.domain.models import PlannerDecision, ReplyPayload
from astcho.prompts import planner_prompt, reply_prompt
from astcho.services.llm import LLMResponseError, LLMService


class ChatService:
    def __init__(self, settings: Settings, llm: LLMService):
        self.settings = settings
        self.llm = llm

    async def plan(self, context: str, schedule: str, *, metadata: dict | None = None) -> PlannerDecision:
        metadata = metadata or {}
        try:
            return await self.llm.json_completion(
                model=self.settings.planner_model, schema=PlannerDecision,
                messages=[{"role": "user", "content": planner_prompt(
                    context, bot_name=str(self.settings.profile.get("name", "Astcho")),
                    current_time=str(metadata.get("current_time", "now")),
                    accumulated_count=int(metadata.get("accumulated_count", 1)),
                    time_span_seconds=int(metadata.get("time_span_seconds", 0)),
                    participant_count=int(metadata.get("participant_count", 1)),
                    last_bot_spoke_seconds=metadata.get("last_bot_spoke_seconds"),
                    recent_meme_rate=str(metadata.get("recent_meme_rate", "0/10")),
                )}], temperature=self.settings.planner_temperature,
            )
        except LLMResponseError:
            return PlannerDecision(action="no_reply", reason="invalid planner output")

    async def reply(self, context: str, memories: list[str], schedule: str, *,
                    emotion: dict | None = None, planner_reason: str = "") -> str:
        try:
            payload = await self.llm.json_completion(
                model=self.settings.chat_model, schema=ReplyPayload,
                messages=[{"role": "user", "content": reply_prompt(
                    bot_name=str(self.settings.profile.get("name", "Astcho")),
                    profile=self.settings.profile, context=context, memories=memories,
                    schedule=schedule, emotion=emotion, planner_reason=planner_reason,
                )}], temperature=self.settings.chat_temperature,
            )
            return payload.reply
        except LLMResponseError:
            return "我刚才有点走神了，可以再说一次吗？"

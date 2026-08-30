from __future__ import annotations

from astcho.config import Settings
from astcho.domain.models import PlannerDecision, ReplyPayload
from astcho.services.llm import LLMResponseError, LLMService


class ChatService:
    def __init__(self, settings: Settings, llm: LLMService):
        self.settings = settings
        self.llm = llm

    async def plan(self, context: str, schedule: str) -> PlannerDecision:
        try:
            return await self.llm.json_completion(
                model=self.settings.planner_model, schema=PlannerDecision,
                messages=[
                    {"role": "system", "content": "Decide whether the assistant should reply. Return only the requested JSON. Allowed actions: reply, no_reply. You cannot invoke tools or administrative actions."},
                    {"role": "user", "content": f"Schedule: {schedule}\nConversation:\n{context}"},
                ], temperature=self.settings.planner_temperature,
            )
        except LLMResponseError:
            return PlannerDecision(action="no_reply", reason="invalid planner output")

    async def reply(self, context: str, memories: list[str], schedule: str) -> str:
        profile = self.settings.profile
        try:
            payload = await self.llm.json_completion(
                model=self.settings.chat_model, schema=ReplyPayload,
                messages=[
                    {"role": "system", "content": f"You are {profile.get('name', 'Astcho')}. Personality: {profile.get('personality', '')}. Reply naturally and protect privacy. Return JSON {{\"reply\":\"...\"}}."},
                    {"role": "user", "content": f"Schedule: {schedule}\nRelevant memories: {memories}\nConversation:\n{context}"},
                ], temperature=self.settings.chat_temperature,
            )
            return payload.reply
        except LLMResponseError:
            return "我刚才有点走神了，可以再说一次吗？"


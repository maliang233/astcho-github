from __future__ import annotations

from astcho.config import Settings
from astcho.domain.models import PlannerDecision, ReasoningReplyPayload, ReplyPayload
from astcho.prompts import planner_prompt, reasoning_reply_prompt, reply_prompt
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
                client=self.llm.planner_client,
            )
        except LLMResponseError:
            return PlannerDecision(action="no_reply", reason="invalid planner output")

    async def reply(self, context: str, memories: list[str], schedule: str, *,
                    emotion: dict | None = None, planner_reason: str = "",
                    expression_hint: str = "", user_id: str = "",
                    group_id: str = "") -> str:
        arguments = dict(
            bot_name=str(self.settings.profile.get("name", "Astcho")),
            profile=self.settings.profile, context=context, memories=memories,
            schedule=schedule, emotion=emotion, planner_reason=planner_reason,
            expression_hint=expression_hint, user_id=user_id, group_id=group_id,
        )
        if self.settings.reasoning_enabled:
            try:
                raw = await self.llm.raw_completion(
                    model=self.settings.reasoning_model,
                    messages=[{"role": "user", "content": reasoning_reply_prompt(**arguments)}],
                    temperature=self.settings.reasoning_temperature,
                    client=self.llm.reasoning_client,
                )
                return _parse_reasoning_reply(raw).reply
            except (LLMResponseError, ValueError):
                pass
        try:
            payload = await self.llm.json_completion(
                model=self.settings.chat_model, schema=ReplyPayload,
                messages=[{"role": "user", "content": reply_prompt(**arguments)}],
                temperature=self.settings.chat_temperature,
            )
            return payload.reply
        except LLMResponseError:
            return "我刚才有点走神了，可以再说一次吗？"


def _parse_reasoning_reply(content: str) -> ReasoningReplyPayload:
    """Accept strict JSON and the mildly malformed formats used by reasoning models."""
    import json
    import re

    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.I)
    candidate = fenced.group(1) if fenced else cleaned
    object_match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if object_match:
        try:
            return ReasoningReplyPayload.model_validate(json.loads(object_match.group(0)))
        except (json.JSONDecodeError, ValueError):
            pass
    reply_match = re.search(r'["\']?reply["\']?\s*[:：]\s*["\'](.+?)["\'](?:\s*[,}]|$)', cleaned, re.DOTALL | re.I)
    thinking_match = re.search(r'["\']?thinking["\']?\s*[:：]\s*["\'](.+?)["\'](?:\s*,|$)', cleaned, re.DOTALL | re.I)
    if reply_match:
        return ReasoningReplyPayload(
            thinking=thinking_match.group(1).strip() if thinking_match else "",
            reply=reply_match.group(1).strip(),
        )
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        raise LLMResponseError("Empty reasoning reply")
    return ReasoningReplyPayload(reply=lines[-1].strip('"\''))

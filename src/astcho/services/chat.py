from __future__ import annotations

from astcho.config import Settings
from astcho.domain.models import PlannerDecision, ReasoningReplyPayload, ReplyPayload
from astcho.logging import get_logger, preview
from astcho.prompts import (
    planner_prompt,
    private_reply_prompt,
    reasoning_reply_prompt,
    reply_prompt,
)
from astcho.services.llm import LLMResponseError, LLMService

logger = get_logger(__name__)


class ChatService:
    def __init__(self, settings: Settings, llm: LLMService):
        self.settings = settings
        self.llm = llm

    async def plan(
        self, context: str, schedule: str, *, metadata: dict | None = None
    ) -> PlannerDecision:
        metadata = metadata or {}
        logger.debug(
            "🧠 [Planner] model=%s | 上下文 %d 字 | 累积 %s 条 / %s 人",
            self.settings.planner_model,
            len(context),
            metadata.get("accumulated_count", 1),
            metadata.get("participant_count", 1),
        )
        try:
            return await self.llm.json_completion(
                model=self.settings.planner_model,
                schema=PlannerDecision,
                messages=[
                    {
                        "role": "user",
                        "content": planner_prompt(
                            context,
                            bot_name=str(self.settings.profile.get("name", "Astcho")),
                            current_time=str(metadata.get("current_time", "now")),
                            accumulated_count=int(metadata.get("accumulated_count", 1)),
                            time_span_seconds=int(metadata.get("time_span_seconds", 0)),
                            participant_count=int(metadata.get("participant_count", 1)),
                            last_bot_spoke_seconds=metadata.get("last_bot_spoke_seconds"),
                            recent_meme_rate=str(metadata.get("recent_meme_rate", "0/10")),
                        ),
                    }
                ],
                temperature=self.settings.planner_temperature,
                client=self.llm.planner_client,
            )
        except LLMResponseError as exc:
            logger.warning("Planner 输出校验失败，安全降级为 NO_REPLY: %s", exc)
            return PlannerDecision(action="no_reply", reason="invalid planner output")

    async def reply(
        self,
        context: str,
        memories: list[str],
        schedule: str,
        *,
        emotion: dict | None = None,
        planner_reason: str = "",
        expression_hint: str = "",
        user_id: str = "",
        group_id: str = "",
    ) -> str:
        arguments = dict(
            bot_name=str(self.settings.profile.get("name", "Astcho")),
            profile=self.settings.profile,
            context=context,
            memories=memories,
            schedule=schedule,
            emotion=emotion,
            planner_reason=planner_reason,
            expression_hint=expression_hint,
            user_id=user_id,
            group_id=group_id,
        )
        if self.settings.reasoning_enabled:
            logger.debug(
                "🧮 [推理模式] model=%s | 上下文 %d 字 | 记忆 %d 条 | 表达提示 %s",
                self.settings.reasoning_model,
                len(context),
                len(memories),
                "有" if expression_hint else "无",
            )
            try:
                raw = await self.llm.raw_completion(
                    model=self.settings.reasoning_model,
                    messages=[{"role": "user", "content": reasoning_reply_prompt(**arguments)}],
                    temperature=self.settings.reasoning_temperature,
                    client=self.llm.reasoning_client,
                )
                parsed = _parse_reasoning_reply(raw)
                logger.debug(
                    "🧮 [推理模式] 解析成功 | thinking=%d 字 | reply=%d 字",
                    len(parsed.thinking),
                    len(parsed.reply),
                )
                return parsed.reply
            except (LLMResponseError, ValueError) as exc:
                logger.warning("Reasoning Replyer 解析失败，降级普通 Replyer: %s", exc)
        logger.debug("💬 [Replyer] model=%s | 正在生成回复...", self.settings.chat_model)
        try:
            payload = await self.llm.json_completion(
                model=self.settings.chat_model,
                schema=ReplyPayload,
                messages=[{"role": "user", "content": reply_prompt(**arguments)}],
                temperature=self.settings.chat_temperature,
            )
            return payload.reply
        except LLMResponseError as exc:
            logger.warning("Replyer 输出校验失败，使用安全回复: %s", exc)
            return "我刚才有点走神了，可以再说一次吗？"

    async def private_reply(self, *, nickname: str, history: list[dict], latest: str) -> str:
        logger.debug(
            "🔒 [私聊 Replyer] 用户=%s | 历史=%d 条 | latest=%s",
            nickname,
            len(history),
            preview(latest),
        )
        try:
            result = await self.llm.text_completion(
                model=self.settings.chat_model,
                messages=[
                    {
                        "role": "user",
                        "content": private_reply_prompt(
                            bot_name=str(self.settings.profile.get("name", "Astcho")),
                            profile=self.settings.profile,
                            nickname=nickname,
                            history=history,
                            latest=latest,
                        ),
                    }
                ],
                temperature=self.settings.chat_temperature,
                max_tokens=500,
            )
            return _clean_plain_reply(result)
        except Exception as exc:
            logger.error("[私聊 Replyer] 生成失败: %s", exc)
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
    reply_match = re.search(
        r'["\']?reply["\']?\s*[:：]\s*["\'](.+?)["\'](?:\s*[,}]|$)', cleaned, re.DOTALL | re.I
    )
    thinking_match = re.search(
        r'["\']?thinking["\']?\s*[:：]\s*["\'](.+?)["\'](?:\s*,|$)', cleaned, re.DOTALL | re.I
    )
    if reply_match:
        return ReasoningReplyPayload(
            thinking=thinking_match.group(1).strip() if thinking_match else "",
            reply=reply_match.group(1).strip(),
        )
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        raise LLMResponseError("Empty reasoning reply")
    return ReasoningReplyPayload(reply=lines[-1].strip("\"'"))


def _clean_plain_reply(value: str) -> str:
    import re

    value = re.sub(r"^(?:Astcho|星回|回复)\s*[:：]\s*", "", value.strip(), flags=re.I)
    return value or "……"

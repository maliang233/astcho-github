import asyncio
from types import SimpleNamespace

from astcho.services.chat import ChatService, DegradedReply
from astcho.services.llm import LLMResponseError


def _settings(*, reasoning_enabled: bool = True):
    return SimpleNamespace(
        profile={"name": "星回", "personality": "温暖的少年"},
        planner_model="deepseek-v4-flash",
        planner_temperature=0.2,
        chat_model="deepseek-v4-flash",
        chat_temperature=0.7,
        reasoning_enabled=reasoning_enabled,
        reasoning_model="deepseek-v4-flash",
        reasoning_temperature=0.7,
    )


def test_reasoning_reply_uses_legacy_prompt_reasoning_without_native_thinking():
    calls = []

    class FakeLLM:
        reasoning_client = object()

        async def raw_completion(self, **kwargs):
            calls.append(kwargs)
            return '{"thinking":"判断语境","reply":"在呢 (｡･ω･｡)"}'

    service = ChatService(_settings(), FakeLLM())
    result = asyncio.run(service.reply("最近聊天", [], "日常"))

    assert result == "在呢 (｡･ω･｡)"
    assert calls[0]["max_tokens"] is None
    assert calls[0]["thinking"] is False
    assert "推理步骤（一步一步思考！）" in calls[0]["messages"][0]["content"]


def test_failed_reasoning_uses_non_thinking_replyer_and_marks_local_fallback():
    calls = []

    class FakeLLM:
        reasoning_client = object()

        async def raw_completion(self, **kwargs):
            raise LLMResponseError("empty response")

        async def json_completion(self, **kwargs):
            calls.append(kwargs)
            raise LLMResponseError("empty response")

    service = ChatService(_settings(), FakeLLM())
    result = asyncio.run(service.reply("最近聊天", [], "日常"))

    assert isinstance(result, DegradedReply)
    assert "(´・ω・`)" in result
    assert calls[0]["max_tokens"] == 512
    assert calls[0]["thinking"] is False

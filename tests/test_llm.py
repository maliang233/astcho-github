import asyncio
import json
from types import SimpleNamespace

import pytest

from astcho.domain.models import MemeTasteDecision, PlannerDecision
from astcho.services.chat import _parse_reasoning_reply
from astcho.services.llm import LLMResponseError, LLMService, _extract_json


def test_extract_wrapped_json():
    value = PlannerDecision.model_validate_json(_extract_json('```json\n{"action":"reply"}\n```'))
    assert value.action == "reply"


def test_invalid_json_rejected():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("not json")


def test_error_type_is_runtime_error():
    assert issubclass(LLMResponseError, RuntimeError)


def test_json_completion_retries_empty_content_and_disables_thinking_by_default():
    calls = []

    class Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            content = "" if len(calls) == 1 else '{"heart_throb":false,"reason":"普通图片"}'
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content, reasoning_content="内部判断"),
                        finish_reason="length" if len(calls) == 1 else "stop",
                    )
                ],
                usage=None,
            )

    service = object.__new__(LLMService)
    service.settings = SimpleNamespace(
        input_price_per_million=0,
        output_price_per_million=0,
    )
    service.usage_callback = None
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    result = asyncio.run(
        service.json_completion(
            model="deepseek-v4-flash",
            schema=MemeTasteDecision,
            messages=[{"role": "user", "content": "JSON"}],
            max_tokens=512,
            client=client,
        )
    )

    assert result.heart_throb is False
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == 512
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_non_deepseek_model_does_not_receive_provider_specific_thinking_option():
    calls = []

    class Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"heart_throb":false,"reason":"普通图片"}',
                            reasoning_content=None,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

    service = object.__new__(LLMService)
    service.settings = SimpleNamespace(input_price_per_million=0, output_price_per_million=0)
    service.usage_callback = None
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    asyncio.run(
        service.json_completion(
            model="qwen-vl",
            schema=MemeTasteDecision,
            messages=[{"role": "user", "content": "JSON"}],
            client=client,
            thinking=False,
        )
    )

    assert "extra_body" not in calls[0]


def test_raw_completion_can_use_provider_default_limit_with_native_thinking_disabled():
    calls = []

    class Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"thinking":"判断","reply":"在呢"}', reasoning_content=None
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

    service = object.__new__(LLMService)
    service.settings = SimpleNamespace(input_price_per_million=0, output_price_per_million=0)
    service.usage_callback = None
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    result = asyncio.run(
        service.raw_completion(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "做题"}],
            client=client,
            max_tokens=None,
            thinking=False,
        )
    )

    assert result.endswith('"}')
    assert "max_tokens" not in calls[0]
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_planner_accepts_prompt_emotion_field_names():
    value = PlannerDecision.model_validate({"action": "reply", "excitement": 0.1, "shyness": -0.1})
    assert value.excitement_delta == 0.1
    assert value.shyness_delta == -0.1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"thinking":"x","reply":"你好"}', "你好"),
        ('```json\n{"thinking":"x","reply":"在呢"}\n```', "在呢"),
        ('thinking: "x", reply: "嗯嗯"', "嗯嗯"),
        ("一些内部判断\n最终回复", "最终回复"),
    ],
)
def test_reasoning_reply_compatibility(raw, expected):
    assert _parse_reasoning_reply(raw).reply == expected

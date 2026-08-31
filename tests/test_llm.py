import json

import pytest

from astcho.domain.models import PlannerDecision
from astcho.services.chat import _parse_reasoning_reply
from astcho.services.llm import LLMResponseError, _extract_json


def test_extract_wrapped_json():
    value = PlannerDecision.model_validate_json(_extract_json('```json\n{"action":"reply"}\n```'))
    assert value.action == "reply"


def test_invalid_json_rejected():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("not json")


def test_error_type_is_runtime_error():
    assert issubclass(LLMResponseError, RuntimeError)


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

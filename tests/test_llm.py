import pytest

from astcho.domain.models import PlannerDecision
from astcho.services.llm import LLMResponseError, _extract_json


def test_extract_wrapped_json():
    value = PlannerDecision.model_validate_json(_extract_json("```json\n{\"action\":\"reply\"}\n```"))
    assert value.action == "reply"


def test_invalid_json_rejected():
    with pytest.raises(Exception):
        _extract_json("not json")


def test_error_type_is_runtime_error():
    assert issubclass(LLMResponseError, RuntimeError)


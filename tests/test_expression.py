import asyncio

from astcho.domain.models import ChatMessage, ExpressionExtraction
from astcho.services.expression import ExpressionService
from astcho.storage.sqlite import SQLiteStore


class FakeLLM:
    async def json_completion(self, **kwargs):
        return ExpressionExtraction.model_validate({"expressions": [
            {"situation": "表示惊叹时", "style": "使用我嘞个句式", "source_id": 1}
        ]})


def message(text="我嘞个这么强"):
    return ChatMessage(message_id="1", user_id="u", nickname="user", text=text, timestamp=1)


def test_expression_requires_repetition_before_injection(tmp_path):
    store = SQLiteStore(tmp_path / "test.sqlite3")
    service = ExpressionService(store, FakeLLM(), "test", interval=30, minimum_messages=3)
    for _ in range(3):
        service.observe("g1", message())
    assert asyncio.run(service.learn("g1", "Astcho")) == 1
    assert service.relevant_hint("g1", "惊叹") == ""

    service.last_learn["g1"] = 0
    for _ in range(3):
        service.observe("g1", message())
    assert asyncio.run(service.learn("g1", "Astcho")) == 1
    assert "我嘞个" in service.relevant_hint("g1", "惊叹")


def test_expression_isolated_by_group(tmp_path):
    store = SQLiteStore(tmp_path / "test.sqlite3")
    service = ExpressionService(store, FakeLLM(), "test", interval=30, minimum_messages=3)
    for _ in range(3):
        service.observe("g1", message())
    asyncio.run(service.learn("g1", "Astcho"))
    assert service.relevant_hint("g2", "惊叹") == ""

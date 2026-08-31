import time

from astcho.domain.models import ChatMessage
from astcho.services.attention import AttentionService
from astcho.services.schedule import ScheduleState


def message(**changes):
    values = {
        "message_id": "1",
        "user_id": "user",
        "nickname": "u",
        "text": "hello",
        "timestamp": time.time(),
    }
    values.update(changes)
    return ChatMessage(**values)


def test_real_bot_identity_updates_last_reply():
    service = AttentionService("42")
    service.add(message(user_id="42"))
    assert service.seconds_since_bot_reply() == 0


def test_low_activity_only_allows_mention():
    service = AttentionService("42")
    sleepy = ScheduleState(5, "sleepy", "night")
    assert not service.should_plan(message(), sleepy, random_value=0)
    assert service.last_trace["reason"] == "日程低活跃，仅响应提及/引用"
    assert service.should_plan(message(mentioned_bot=True), sleepy, random_value=1)


def test_probability_trace_exposes_decision_factors():
    service = AttentionService("42", base_talk_probability=0.1)
    active = ScheduleState(50, "calm", "day")

    assert not service.should_plan(message(), active, excitement=0.25, random_value=0.99)
    assert service.last_trace["reason"] == "概率判定"
    assert service.last_trace["talk"] == 50
    assert 0 < service.last_trace["probability"] < 1
    assert service.last_trace["sample"] == 0.99

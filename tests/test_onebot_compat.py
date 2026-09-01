import asyncio
from collections import defaultdict
from types import SimpleNamespace

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment

from astcho.domain.models import ChatMessage, PlannerDecision
from astcho.handlers.common import local_image_source
from astcho.handlers.group import (
    _handle_custom_follow,
    _process_after_window,
    is_bot_mentioned,
    qq_nickname,
)
from astcho.handlers.media import describe_event_media, describe_forward
from astcho.services.attention import AttentionService
from astcho.services.schedule import ScheduleState


def group_event(message: Message, *, to_me: bool = False) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1,
        self_id=10001,
        post_type="message",
        sub_type="normal",
        user_id=10002,
        message_type="group",
        message_id=123,
        message=message,
        original_message=message,
        raw_message=str(message),
        font=0,
        sender={"user_id": 10002, "nickname": "tester", "card": ""},
        group_id=10003,
        to_me=to_me,
    )


def test_real_onebot_at_segment_is_detected():
    event = group_event(Message([MessageSegment.at(10001), MessageSegment.text("说句话")]))
    assert is_bot_mentioned(event, "10001") is True


def test_adapter_to_me_is_authoritative_even_without_at_segment():
    event = group_event(Message("星回，说句话"), to_me=True)
    assert is_bot_mentioned(event, "10001") is True


def test_group_sender_uses_qq_nickname_instead_of_group_card():
    event = group_event(Message("你好"))
    event.sender.nickname = "QQ昵称"
    event.sender.card = "群名片"
    assert qq_nickname(event) == "QQ昵称"


def test_local_meme_is_encoded_for_containerized_napcat(tmp_path):
    image = tmp_path / "meme.gif"
    image.write_bytes(b"GIF89a")
    assert local_image_source(str(image)) == "base64://R0lGODlh"


def test_forward_message_is_expanded():
    class Bot:
        async def get_forward_msg(self, **kwargs):
            return {
                "messages": [
                    {
                        "sender": {"nickname": "甲"},
                        "message": [{"type": "text", "data": {"text": "第一句"}}],
                    },
                    {
                        "sender": {"nickname": "乙"},
                        "message": [{"type": "text", "data": {"text": "第二句"}}],
                    },
                ]
            }

    runtime = SimpleNamespace(
        settings=SimpleNamespace(forward_max_text_segments=30, forward_max_media_segments=10),
        vision=SimpleNamespace(),
        llm=SimpleNamespace(),
    )
    result = asyncio.run(describe_forward(runtime, Bot(), "forward-id"))
    assert result == "[转发自 甲] 甲: 第一句 | 乙: 第二句"


def test_two_distinct_users_trigger_custom_follow():
    sent = []

    class Bot:
        self_id = "10001"

        async def send_group_msg(self, **kwargs):
            sent.append(kwargs)

    def event(user_id, *, reply=True):
        original = Message([MessageSegment.at(99)])
        return SimpleNamespace(
            message_id=user_id,
            reply=(
                SimpleNamespace(message_id=88, sender=SimpleNamespace(user_id=99))
                if reply
                else None
            ),
            original_message=original,
            get_message=lambda: original,
            get_plaintext=lambda: "",
        )

    runtime = SimpleNamespace(
        schedule=SimpleNamespace(current=lambda: SimpleNamespace(talk_value=50)),
        custom_reply_tracker={"1": {}},
        custom_reply_handled={"1": {}},
    )

    async def scenario():
        assert await _handle_custom_follow(runtime, Bot(), event(10), "1", "10") is False
        assert await _handle_custom_follow(runtime, Bot(), event(11), "1", "11") is True

    asyncio.run(scenario())
    assert len(sent) == 1


def test_bare_at_can_continue_an_active_custom_follow_chain():
    sent = []

    class Bot:
        self_id = "10001"

        async def send_group_msg(self, **kwargs):
            sent.append(kwargs)

    def event(user_id, *, reply):
        original = Message([MessageSegment.at(99)])
        return SimpleNamespace(
            message_id=user_id,
            reply=(
                SimpleNamespace(message_id=88, sender=SimpleNamespace(user_id=99))
                if reply
                else None
            ),
            original_message=original,
            get_message=lambda: original,
            get_plaintext=lambda: "",
        )

    runtime = SimpleNamespace(
        schedule=SimpleNamespace(current=lambda: SimpleNamespace(talk_value=50)),
        custom_reply_tracker={"1": {}},
        custom_reply_handled={"1": {}},
    )

    async def scenario():
        first = await _handle_custom_follow(runtime, Bot(), event(10, reply=True), "1", "10")
        second = await _handle_custom_follow(runtime, Bot(), event(11, reply=False), "1", "11")
        assert first is False
        assert second is True

    asyncio.run(scenario())
    assert len(sent) == 1


def test_empty_reply_without_mention_does_not_start_custom_follow():
    class Bot:
        self_id = "10001"

    reply = SimpleNamespace(message_id=88, sender=SimpleNamespace(user_id=99))
    event = SimpleNamespace(
        message_id=10,
        reply=reply,
        original_message=Message([MessageSegment.reply(88)]),
        get_message=lambda: Message(),
        get_plaintext=lambda: "",
    )
    runtime = SimpleNamespace(
        schedule=SimpleNamespace(current=lambda: SimpleNamespace(talk_value=50)),
        custom_reply_tracker={"1": {}},
        custom_reply_handled={"1": {}},
    )

    handled = asyncio.run(_handle_custom_follow(runtime, Bot(), event, "1", "10"))
    assert handled is False
    assert runtime.custom_reply_tracker["1"] == {}


def test_media_failure_degrades_without_stopping_message():
    image = MessageSegment(type="image", data={"url": "https://invalid.example/image.jpg"})
    event = group_event(Message([image]))

    class Vision:
        async def describe(self, url):
            raise RuntimeError("vision unavailable")

    runtime = SimpleNamespace(vision=Vision())
    result = asyncio.run(describe_event_media(runtime, SimpleNamespace(), event))
    assert result.descriptions == ["[图片]"]


def test_group_event_runs_planner_reply_and_send(monkeypatch):
    event = group_event(Message([MessageSegment.at(10001), MessageSegment.text("说句话")]))
    message = ChatMessage(
        message_id="123",
        user_id="10002",
        nickname="tester",
        text="说句话",
        timestamp=1,
        mentioned_bot=True,
    )
    attention = AttentionService("10001", bot_name="星回")
    attention.add(message)
    sent, remembered = [], []

    class Bot:
        self_id = "10001"

        async def send(self, event, message):
            sent.append(message)

    class Chat:
        async def plan(self, *args, **kwargs):
            return PlannerDecision(action="reply", reason="明确@了机器人")

        async def reply(self, *args, **kwargs):
            return "第一句\n第二句"

    class Memory:
        def retrieve(self, *args, **kwargs):
            return []

        def queue_turn(self, *args, **kwargs):
            remembered.append((args, kwargs))

    runtime = SimpleNamespace(
        locks=defaultdict(asyncio.Lock),
        pending_group_messages={"10003": [(event, message)]},
        aggregation_tasks={},
        attention={"10003": attention},
        schedule=SimpleNamespace(current=lambda: ScheduleState(50, "正常", "default")),
        emotion=SimpleNamespace(
            state=lambda *args: {"excitement": 0, "shyness": 0, "affinity": 0.3},
            apply=lambda *args, **kwargs: {"excitement": 0, "shyness": 0, "affinity": 0.3},
        ),
        chat=Chat(),
        memory=Memory(),
        expressions=SimpleNamespace(relevant_hint=lambda *args: ""),
        settings=SimpleNamespace(max_memories=8, profile={"name": "星回"}),
        memes=SimpleNamespace(),
    )

    async def no_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr("astcho.handlers.group.asyncio.sleep", no_sleep)
    asyncio.run(_process_after_window(runtime, Bot(), "10003"))
    assert len(sent) == 2
    assert remembered

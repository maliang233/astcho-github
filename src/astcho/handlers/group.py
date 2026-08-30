from __future__ import annotations

import time
from datetime import datetime

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from astcho.domain.models import ChatMessage
from astcho.handlers.common import image_urls, reply_message, text_of
from astcho.runtime import Runtime
from astcho.services.attention import AttentionService


def register_group(runtime: Runtime) -> None:
    matcher = on_message(priority=20, block=False)

    @matcher.handle()
    async def handle(bot: Bot, event: GroupMessageEvent) -> None:
        group_id, user_id = str(event.group_id), str(event.user_id)
        if runtime.settings.allowed_groups and group_id not in runtime.settings.allowed_groups:
            return
        async with runtime.locks[f"group:{group_id}"]:
            text = text_of(event)
            descriptions = []
            for url in image_urls(event):
                result = await runtime.vision.describe(url)
                descriptions.append(result.description)
                if result.is_sticker:
                    runtime.memes.learn(file_id=url.rsplit("/", 1)[-1][:120], url=url,
                                        description=result.description, tags=result.tags,
                                        inclination=result.inclination)
            nickname = event.sender.card or event.sender.nickname or user_id
            runtime.sqlite.touch_user(group_id, user_id, nickname)
            attention = runtime.attention.setdefault(
                group_id, AttentionService(str(bot.self_id))
            )
            mentioned = any(seg.type == "at" and str(seg.data.get("qq")) == str(bot.self_id)
                            for seg in event.get_message())
            message = ChatMessage(message_id=str(event.message_id), user_id=user_id,
                                  nickname=nickname, text=text, timestamp=time.time(),
                                  mentioned_bot=mentioned,
                                  image_description="; ".join(descriptions))
            attention.add(message)
            if runtime.settings.expression_learning and runtime.expressions.observe(group_id, message):
                runtime.tasks.create(runtime.expressions.learn(
                    group_id, str(runtime.settings.profile.get("name", "Astcho"))
                ))
            schedule = runtime.schedule.current()
            mood = runtime.emotion.state(group_id, user_id)
            if not attention.should_plan(message, schedule, excitement=mood["excitement"]):
                return
            buffered = list(attention.messages)
            span = int(buffered[-1].timestamp - buffered[0].timestamp) if len(buffered) > 1 else 0
            decision = await runtime.chat.plan(
                attention.context(), schedule.mood,
                metadata={
                    "current_time": datetime.now().strftime("%H:%M:%S"),
                    "accumulated_count": len(buffered),
                    "time_span_seconds": span,
                    "participant_count": len({item.user_id for item in buffered if not item.is_bot}),
                    "last_bot_spoke_seconds": attention.seconds_since_bot_reply(),
                },
            )
            runtime.emotion.apply(
                group_id, user_id,
                excitement_delta=decision.excitement_delta,
                shyness_delta=decision.shyness_delta,
                affinity_score=decision.affinity_score,
            )
            if decision.action != "reply":
                return
            memories = runtime.memory.retrieve(text or message.image_description,
                                               group_id=group_id, user_id=user_id,
                                               limit=runtime.settings.max_memories)
            answer = await runtime.chat.reply(
                attention.context(), [item.content for item in memories], schedule.mood,
                emotion=mood, planner_reason=decision.reason,
                expression_hint=runtime.expressions.relevant_hint(group_id, attention.context()),
            )
            meme_url = None
            if decision.should_meme and decision.meme_query:
                selected = await runtime.memes.select(answer, decision.meme_query)
                if selected:
                    meme_url = selected["url"]
                    runtime.memes.mark_used(selected["file_id"])
            await matcher.send(reply_message(answer, meme_url))
            attention.add(ChatMessage(message_id=f"bot-{time.time_ns()}", user_id=str(bot.self_id),
                                      nickname="Astcho", text=answer, timestamp=time.time(), is_bot=True))
            runtime.tasks.create(runtime.memory.extract(text, group_id=group_id, user_id=user_id))

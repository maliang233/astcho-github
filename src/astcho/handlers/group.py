from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import is_type

from astcho.domain.models import ChatMessage
from astcho.handlers.common import local_image_source, reply_message, split_reply, text_of
from astcho.handlers.media import describe_event_media
from astcho.runtime import Runtime
from astcho.services.attention import AttentionService
from astcho.services.emotion import apply_typo

logger = logging.getLogger(__name__)


def register_group(runtime: Runtime) -> None:
    matcher = on_message(rule=is_type(GroupMessageEvent), priority=20, block=False)

    @matcher.handle()
    async def handle(bot: Bot, event: GroupMessageEvent) -> None:
        group_id, user_id = str(event.group_id), str(event.user_id)
        if runtime.settings.allowed_groups and group_id not in runtime.settings.allowed_groups:
            logger.debug("Ignored message from group %s: not in allowlist", group_id)
            return
        text = text_of(event)
        media = await describe_event_media(runtime, bot, event)
        for url, result in media.learned_images:
            runtime.tasks.create(
                runtime.memes.consider_remote(
                    url=url,
                    description=result.description,
                    tags=result.tags,
                    inclination=result.inclination,
                    context=text[-500:],
                )
            )
        nickname = event.sender.card or event.sender.nickname or user_id
        runtime.sqlite.touch_user(group_id, user_id, nickname)
        mentioned = is_bot_mentioned(event, str(bot.self_id))
        replied = bool(event.reply and str(event.reply.sender.user_id) == str(bot.self_id))
        message = ChatMessage(
            message_id=str(event.message_id),
            user_id=user_id,
            nickname=nickname,
            text=text,
            timestamp=time.time(),
            mentioned_bot=mentioned,
            replied_to_bot=replied,
            image_description="; ".join(media.descriptions),
        )
        logger.debug(
            "Received group message group=%s user=%s message=%s mentioned=%s replied=%s",
            group_id,
            user_id,
            message.message_id,
            mentioned,
            replied,
        )
        attention = runtime.attention.setdefault(
            group_id,
            AttentionService(
                str(bot.self_id), bot_name=str(runtime.settings.profile.get("name", "Astcho"))
            ),
        )
        attention.add(message)
        if runtime.settings.expression_learning and runtime.expressions.observe(group_id, message):
            runtime.tasks.create(
                runtime.expressions.learn(
                    group_id, str(runtime.settings.profile.get("name", "Astcho"))
                )
            )
        if await _handle_custom_follow(runtime, bot, event, group_id, user_id):
            return
        # The original behavior learns media but does not wake Planner for media-only messages.
        if not text.strip():
            return
        runtime.pending_group_messages[group_id].append((event, message))
        active = runtime.aggregation_tasks.get(group_id)
        if active and not active.done():
            logger.debug(
                "Aggregated message %s into pending group %s", message.message_id, group_id
            )
            return
        task = runtime.tasks.create(_process_after_window(runtime, bot, group_id))
        runtime.aggregation_tasks[group_id] = task


async def _process_after_window(runtime: Runtime, bot: Bot, group_id: str) -> None:
    await asyncio.sleep(random.uniform(2.0, 5.0))
    async with runtime.locks[f"group:{group_id}"]:
        pending = runtime.pending_group_messages.pop(group_id, [])
        runtime.aggregation_tasks.pop(group_id, None)
        if not pending:
            return
        logger.debug("Processing %d aggregated messages for group %s", len(pending), group_id)
        event, message = pending[-1]
        attention = runtime.attention[group_id]
        schedule = runtime.schedule.current()
        mood = runtime.emotion.state(group_id, message.user_id)
        trigger = next(
            (item for _, item in reversed(pending) if item.mentioned_bot or item.replied_to_bot),
            message,
        )
        if not attention.should_plan(trigger, schedule, excitement=mood["excitement"]):
            logger.debug(
                "Attention skipped planner group=%s trigger=%s", group_id, trigger.message_id
            )
            return
        buffered = list(attention.messages)
        span = int(buffered[-1].timestamp - buffered[0].timestamp) if len(buffered) > 1 else 0
        decision = await runtime.chat.plan(
            attention.context(),
            schedule.mood,
            metadata={
                "current_time": datetime.now().strftime("%H:%M:%S"),
                "accumulated_count": len(pending),
                "time_span_seconds": span,
                "participant_count": len({item.user_id for _, item in pending}),
                "last_bot_spoke_seconds": attention.seconds_since_bot_reply(),
            },
        )
        logger.debug(
            "Planner decision group=%s action=%s target=%s reason=%s",
            group_id,
            decision.action,
            decision.target_message_id,
            decision.reason,
        )
        mood = runtime.emotion.apply(
            group_id,
            message.user_id,
            excitement_delta=decision.excitement_delta,
            shyness_delta=decision.shyness_delta,
            affinity_score=decision.affinity_score,
        )
        attention.update_after_planner(decision.action == "reply")
        if decision.action != "reply":
            return
        query = "\n".join(item.text or item.image_description for _, item in pending)
        memories = runtime.memory.retrieve(
            query, group_id=group_id, user_id=message.user_id, limit=runtime.settings.max_memories
        )
        answer = await runtime.chat.reply(
            attention.context(),
            [item.content for item in memories],
            schedule.mood,
            emotion=mood,
            planner_reason=decision.reason,
            expression_hint=runtime.expressions.relevant_hint(group_id, attention.context()),
            user_id=message.user_id,
            group_id=group_id,
        )
        logger.debug(
            "Reply generated group=%s chars=%d memories=%d", group_id, len(answer), len(memories)
        )
        answer = apply_typo(answer, mood["excitement"])
        parts = split_reply(answer)
        quote_id = trigger.message_id if trigger.mentioned_bot or trigger.replied_to_bot else None
        for index, part in enumerate(parts):
            await bot.send(event, reply_message(part, reply_to=quote_id if index == 0 else None))
            logger.debug("Sent reply part group=%s part=%d/%d", group_id, index + 1, len(parts))
            if index < len(parts) - 1:
                await asyncio.sleep(random.uniform(0.8, 2.0))
        if decision.should_meme and decision.meme_query:
            selected = await runtime.memes.select(answer, decision.meme_query, session_key=group_id)
            if selected:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                local_path = selected.get("local_path")
                try:
                    meme_source = local_image_source(local_path) if local_path else selected["url"]
                    await bot.send(event, reply_message("", meme_source))
                    runtime.memes.mark_used(selected["file_id"], session_key=group_id)
                except Exception:
                    logger.warning("Meme file unavailable, deleting %s", selected["file_id"])
                    runtime.memes.delete(selected["file_id"])
        attention.add(
            ChatMessage(
                message_id=f"bot-{time.time_ns()}",
                user_id=str(bot.self_id),
                nickname=str(runtime.settings.profile.get("name", "Astcho")),
                text=answer,
                timestamp=time.time(),
                is_bot=True,
            )
        )
        for _, item in pending:
            if item.text:
                runtime.memory.queue_turn(
                    item.text,
                    answer,
                    group_id=group_id,
                    user_id=item.user_id,
                    user_name=item.nickname,
                )


async def _handle_custom_follow(
    runtime: Runtime, bot: Bot, event: GroupMessageEvent, group_id: str, user_id: str
) -> bool:
    """Follow the two-user reply+@ custom used in the original group handler."""
    if (
        runtime.schedule.current().talk_value < 10
        or not event.reply
        or event.get_plaintext().strip()
    ):
        return False
    target_id = str(event.reply.message_id)
    target_user = str(event.reply.sender.user_id)
    if target_user == str(bot.self_id):
        return False
    now = time.time()
    tracker = runtime.custom_reply_tracker[group_id]
    handled = runtime.custom_reply_handled[group_id]
    for key in [key for key, value in tracker.items() if now - value["timestamp"] > 60]:
        tracker.pop(key, None)
    for key in [key for key, timestamp in handled.items() if now - timestamp > 600]:
        handled.pop(key, None)
    if target_id in handled:
        return False
    entry = tracker.setdefault(
        target_id, {"uids": set(), "timestamp": now, "target_user": target_user}
    )
    entry["uids"].add(user_id)
    if len(entry["uids"]) < 2:
        return False
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    handled[target_id] = now
    tracker.pop(target_id, None)
    try:
        message = MessageSegment.reply(int(target_id)) + MessageSegment.at(int(target_user))
        await bot.send_group_msg(group_id=int(group_id), message=Message(message))
        logger.info("Custom follow sent group=%s target=%s", group_id, target_id)
        return True
    except Exception:
        handled.pop(target_id, None)
        logger.exception("Custom follow failed group=%s target=%s", group_id, target_id)
        return False


def is_bot_mentioned(event: GroupMessageEvent, bot_id: str) -> bool:
    return bool(event.to_me) or any(
        segment.type == "at" and str(segment.data.get("qq")) == str(bot_id)
        for segment in event.get_message()
    )

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import is_type

from astcho.domain.models import ChatMessage
from astcho.handlers.common import local_image_source, reply_message, split_reply, text_of
from astcho.handlers.media import describe_event_media
from astcho.logging import get_logger, preview
from astcho.runtime import Runtime
from astcho.services.attention import AttentionService
from astcho.services.emotion import apply_typo

logger = get_logger(__name__)


def register_group(runtime: Runtime) -> None:
    matcher = on_message(rule=is_type(GroupMessageEvent), priority=20, block=False)

    @matcher.handle()
    async def handle(bot: Bot, event: GroupMessageEvent) -> None:
        group_id, user_id = str(event.group_id), str(event.user_id)
        if runtime.settings.allowed_groups and group_id not in runtime.settings.allowed_groups:
            logger.debug("🔕 [白名单] 忽略未授权群 %s", group_id)
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
        logger.chat_user(
            "[群:%s] %s(%s): %s",
            group_id,
            nickname,
            user_id,
            preview(text or message.image_description or "[空消息]", 100),
        )
        logger.debug(
            "🔍 [@检测] 消息:%s | is_mention=%s | is_reply=%s | bot_id=%s",
            message.message_id,
            mentioned,
            replied,
            bot.self_id,
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
            logger.debug("🖼️ [媒体消息] 已完成理解/学习，不唤醒 Planner")
            return
        runtime.pending_group_messages[group_id].append((event, message))
        active = runtime.aggregation_tasks.get(group_id)
        if active and not active.done():
            logger.debug(
                "🔄 [合并] 群 %s 的 Planner 等待窗口中，消息 %s 已并入",
                group_id,
                message.message_id,
            )
            return
        logger.debug("⏳ [聚合] 群 %s 开始等待 2~5 秒消息窗口", group_id)
        task = runtime.tasks.create(_process_after_window(runtime, bot, group_id))
        runtime.aggregation_tasks[group_id] = task


async def _process_after_window(runtime: Runtime, bot: Bot, group_id: str) -> None:
    await asyncio.sleep(random.uniform(2.0, 5.0))
    async with runtime.locks[f"group:{group_id}"]:
        pending = runtime.pending_group_messages.pop(group_id, [])
        runtime.aggregation_tasks.pop(group_id, None)
        if not pending:
            return
        logger.debug("📦 [聚合] 群 %s 共处理 %d 条新消息", group_id, len(pending))
        event, message = pending[-1]
        attention = runtime.attention[group_id]
        schedule = runtime.schedule.current()
        mood = runtime.emotion.state(group_id, message.user_id)
        trigger = next(
            (item for _, item in reversed(pending) if item.mentioned_bot or item.replied_to_bot),
            message,
        )
        should_plan = attention.should_plan(trigger, schedule, excitement=mood["excitement"])
        trace = attention.last_trace
        if trace.get("reason") == "概率判定":
            logger.debug(
                "📊 [概率] 日程:%s(%s) 沉默:%d秒 兴奋:%.2f 频率:%.2f → 概率:%.1f%% 抽样:%.3f → %s",
                schedule.routine,
                schedule.talk_value,
                int(float(trace.get("silence", 0))),
                float(trace.get("excitement", 0)),
                float(trace.get("frequency", 1)),
                float(trace.get("probability", 0)) * 100,
                float(trace.get("sample", 0)),
                "进入思考" if should_plan else "保持安静",
            )
        else:
            logger.debug(
                "🎯 [注意力] %s → %s",
                trace.get("reason"),
                "进入思考" if should_plan else "跳过",
            )
        if not should_plan:
            return
        buffered = list(attention.messages)
        span = int(buffered[-1].timestamp - buffered[0].timestamp) if len(buffered) > 1 else 0
        logger.debug("🧠 [思考] 星回正在审视群聊气氛并进行决策...")
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
        if decision.action == "reply":
            logger.system(
                "🧠 [决策] REPLY (回复 %s) | 理由: %s",
                decision.target_message_id or trigger.message_id,
                preview(decision.reason, 120),
            )
        else:
            logger.system("🧠 [决策] NO_REPLY | 理由: %s", preview(decision.reason, 120))
        before_mood = mood.copy()
        mood = runtime.emotion.apply(
            group_id,
            message.user_id,
            excitement_delta=decision.excitement_delta,
            shyness_delta=decision.shyness_delta,
            affinity_score=decision.affinity_score,
        )
        attention.update_after_planner(decision.action == "reply")
        logger.system(
            "💭 [情绪] 兴奋 %.2f→%.2f | 害羞 %.2f→%.2f | 好感 %.2f→%.2f",
            before_mood["excitement"],
            mood["excitement"],
            before_mood["shyness"],
            mood["shyness"],
            before_mood["affinity"],
            mood["affinity"],
        )
        if decision.action != "reply":
            return
        query = "\n".join(item.text or item.image_description for _, item in pending)
        memories = runtime.memory.retrieve(
            query, group_id=group_id, user_id=message.user_id, limit=runtime.settings.max_memories
        )
        logger.debug(
            "🧠 [记忆检索] query=%s | 命中 %d 条%s",
            preview(query, 60),
            len(memories),
            f" | 最高分 {memories[0].score:.3f}" if memories else "",
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
        logger.debug("🧮 [推理模式] 最终回复: [%s]", preview(answer, 160))
        answer = apply_typo(answer, mood["excitement"])
        parts = split_reply(answer)
        quote_id = trigger.message_id if trigger.mentioned_bot or trigger.replied_to_bot else None
        for index, part in enumerate(parts):
            await bot.send(event, reply_message(part, reply_to=quote_id if index == 0 else None))
            logger.chat_ai(str(runtime.settings.profile.get("name", "Astcho")), part)
            logger.debug("📤 [发送] 群 %s 第 %d/%d 段发送完成", group_id, index + 1, len(parts))
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
                    logger.system(
                        "🎨 [自动配图] %s... (for: %s)",
                        selected["file_id"][:8],
                        preview(answer, 30),
                    )
                except Exception:
                    logger.warning("表情包 %s 无可用资源，清理数据库条目", selected["file_id"][:8])
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
        logger.debug("📝 [上下文] 星回消息与 %d 个用户回合已加入记忆队列", len(pending))


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
        logger.system("🎯 [习俗跟风] 群 %s 跟风回复消息 %s", group_id, target_id)
        return True
    except Exception:
        handled.pop(target_id, None)
        logger.exception("习俗跟风失败 group=%s target=%s", group_id, target_id)
        return False


def is_bot_mentioned(event: GroupMessageEvent, bot_id: str) -> bool:
    return bool(event.to_me) or any(
        segment.type == "at" and str(segment.data.get("qq")) == str(bot_id)
        for segment in event.get_message()
    )

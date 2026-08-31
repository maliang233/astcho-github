from __future__ import annotations

import asyncio
import os
import signal

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg

from astcho.runtime import Runtime


def register_commands(runtime: Runtime) -> None:
    status = on_command("astcho_status", priority=5, block=True)
    stats = on_command("stats", priority=5, block=True)
    recent = on_command("recent", aliases={"astcho_memories"}, priority=5, block=True)
    reset_memory = on_command("astcho_reset_memory", priority=5, block=True)
    clean = on_command("clean", priority=5, block=True)
    bill = on_command("bill", priority=5, block=True)
    shutdown = on_command("shutdown", priority=1, block=True)
    what = on_command("what", priority=5, block=True)
    delete_meme = on_command("del_meme", priority=5, block=True)
    learn_meme = on_command("learn", aliases={"learn_meme"}, priority=5, block=True)
    teach_meme = on_command("teach_meme", priority=5, block=True)
    reset_meme = on_command("reset_meme", priority=5, block=True)
    schedule = on_command("schedule", aliases={"astcho_schedule"}, priority=5, block=True)
    gaming_lost = on_command("打游戏输了", priority=5, block=True)
    sick = on_command("生病了", priority=5, block=True)
    normal = on_command("恢复正常", priority=5, block=True)

    async def require_admin(event: MessageEvent, matcher) -> bool:
        if runtime.is_admin(str(event.user_id)):
            return True
        await matcher.finish("权限不足。")
        return False

    def session_key(event: MessageEvent) -> str:
        return (
            str(event.group_id)
            if isinstance(event, GroupMessageEvent)
            else f"private_{event.user_id}"
        )

    @status.handle()
    async def handle_status(event: MessageEvent) -> None:
        if not await require_admin(event, status):
            return
        state = runtime.schedule.current()
        await status.finish(f"Astcho running | schedule={state.routine} | talk={state.talk_value}")

    @stats.handle()
    async def handle_stats(event: MessageEvent) -> None:
        if not await require_admin(event, stats):
            return
        await stats.finish(
            "📊 【星回记忆统计】\n"
            f"🧠 碎片记忆: {runtime.vectors.memory_count()} 条\n"
            f"🎨 策展收藏: {runtime.sqlite.meme_count()} 张\n"
            f"📚 表达方式: {runtime.sqlite.expression_count()} 条"
        )

    @recent.handle()
    async def handle_recent(event: MessageEvent) -> None:
        if not await require_admin(event, recent):
            return
        user_id = str(event.user_id)
        group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else "private"
        items = runtime.vectors.recent_memories(
            group_id=group_id if group_id != "private" else None,
            user_id=user_id if group_id == "private" else None,
            limit=5,
        )
        await recent.finish(
            "🌌 最近记忆：\n"
            + "\n".join(f"{index}. {item.content}" for index, item in enumerate(items, 1))
            if items
            else "脑海里还没这里的记忆..."
        )

    @reset_memory.handle()
    async def handle_reset_memory(event: MessageEvent) -> None:
        if not await require_admin(event, reset_memory):
            return
        group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else "private"
        runtime.vectors.delete_memories(
            group_id=group_id,
            user_id=str(event.user_id) if group_id == "private" else None,
        )
        await reset_memory.finish("记忆已重置。")

    @clean.handle()
    async def handle_clean(event: MessageEvent) -> None:
        if not await require_admin(event, clean):
            return
        await clean.send("好哦，开始整理记忆啦 ( •̀ ω •́ )y")
        count = await asyncio.to_thread(runtime.memory.clean)
        await clean.finish(f"整理完成！合并了 {count} 条重复记忆。")

    @bill.handle()
    async def handle_bill(event: MessageEvent) -> None:
        if not await require_admin(event, bill):
            return
        today, hour = runtime.sqlite.usage_summary(24), runtime.sqlite.usage_summary(1)
        await bill.finish(
            "💰 【星回财务简报】\n"
            f"💵 今日估算：¥{today['cost']:.4f}\n"
            f"时耗：¥{hour['cost']:.4f}/h\n"
            f"流量：{today['input_tokens'] + today['output_tokens']} tokens"
        )

    @shutdown.handle()
    async def handle_shutdown(event: MessageEvent) -> None:
        if not await require_admin(event, shutdown):
            return
        await shutdown.send("系统关闭中...")
        asyncio.get_running_loop().call_later(0.2, os.kill, os.getpid(), signal.SIGINT)

    @what.handle()
    async def handle_what(event: MessageEvent) -> None:
        info = runtime.memes.last_info(session_key(event))
        if not info:
            await what.finish("唔...最近没发过表情包，或者记不太清了 (ovo)")
        await what.finish(
            f"这个表情包的感觉：{info.get('inclination', '未知')}\n"
            f"内容：{info.get('description', '暂无描述')}\n"
            f"使用次数：{info.get('use_count', 0)}"
        )

    @delete_meme.handle()
    async def handle_delete_meme(event: MessageEvent) -> None:
        if not await require_admin(event, delete_meme):
            return
        if runtime.memes.delete_last(session_key(event)):
            await delete_meme.finish("好哦，把那个表情包忘掉啦 ( > < )")
        await delete_meme.finish("最近没发过表情包呀？")

    @learn_meme.handle()
    async def handle_learn_meme(event: MessageEvent) -> None:
        if not await require_admin(event, learn_meme):
            return
        info = runtime.memes.last_info(session_key(event))
        if not info:
            await learn_meme.finish("最近没回复过表情包呀？")
        runtime.memes.learn(
            file_id=info["file_id"],
            url=info["url"],
            description=info["description"],
            tags=info.get("tags", []),
            inclination=info.get("inclination", "neutral"),
        )
        await learn_meme.finish(f"学会啦！这个表情包的感觉是：{info.get('inclination', '未知')}")

    @teach_meme.handle()
    async def handle_teach_meme(event: MessageEvent) -> None:
        if not await require_admin(event, teach_meme):
            return
        if not event.reply:
            await teach_meme.finish("请回复一张图片来教导我表情包~")
        image = next((seg for seg in event.reply.message if seg.type == "image"), None)
        if not image or not image.data.get("url"):
            await teach_meme.finish("唔...回复的消息里没有图片呀？")
        await teach_meme.send("好哦，正在学习这个表情包~")
        result = await runtime.vision.describe(str(image.data["url"]))
        learned = await runtime.memes.learn_remote(
            url=str(image.data["url"]),
            description=result.description,
            tags=result.tags,
            inclination=result.inclination,
        )
        await teach_meme.finish(
            f"学会啦！这个表情包的感觉是：{result.inclination}" if learned else "唔...学习失败了"
        )

    @reset_meme.handle()
    async def handle_reset_meme(event: MessageEvent) -> None:
        if not await require_admin(event, reset_meme):
            return
        count = await asyncio.to_thread(runtime.memes.purge)
        await reset_meme.finish(
            f"表情包库已重置，清除了 {count} 条记录和全部本地文件。从现在开始重新学习！"
        )

    @schedule.handle()
    async def handle_schedule(
        event: MessageEvent,
        args: Message = CommandArg(),  # noqa: B008 - NoneBot dependency injection
    ) -> None:
        tokens = args.extract_plain_text().strip().split() or ["status"]
        action = tokens[0].lower()
        if action != "status" and not await require_admin(event, schedule):
            return
        try:
            if action == "clear":
                runtime.schedule.clear_override()
            elif action == "reload":
                runtime.schedule.reload()
            elif action == "override":
                if len(tokens) < 2:
                    await schedule.finish(
                        "用法：/schedule override <routine> [minutes] [mood_append]"
                    )
                minutes = int(tokens[2]) if len(tokens) > 2 and tokens[2].isdigit() else 60
                runtime.schedule.set_routine_override(
                    tokens[1], minutes=minutes, mood_append=" ".join(tokens[3:])
                )
            elif action != "status":
                await schedule.finish(
                    "用法：/schedule status | override <routine> [minutes] [mood] | clear | reload"
                )
        except ValueError as exc:
            await schedule.finish(f"日程设置失败：{exc}")
        state = runtime.schedule.current()
        await schedule.finish(
            f"📅 星回日程状态\n当前模板: {state.routine}\n说话欲望: {state.talk_value}\n"
            f"心情描述: {state.mood}\n{'⚠️ 临时覆写生效中!' if state.overridden else ''}"
        )

    async def shortcut(
        event: MessageEvent, matcher, routine: str, minutes: int, mood: str, response: str
    ) -> None:
        if not await require_admin(event, matcher):
            return
        runtime.schedule.set_routine_override(routine, minutes=minutes, mood_append=mood)
        await matcher.finish(response)

    @gaming_lost.handle()
    async def handle_gaming_lost(event: MessageEvent) -> None:
        await shortcut(
            event,
            gaming_lost,
            "gaming_lost",
            30,
            "游戏连跪，很生气！",
            "😤 游戏连跪模式已激活 (30分钟)",
        )

    @sick.handle()
    async def handle_sick(event: MessageEvent) -> None:
        await shortcut(event, sick, "sick_day", 120, "", "🤒 生病模式已激活 (2小时)")

    @normal.handle()
    async def handle_normal(event: MessageEvent) -> None:
        if not await require_admin(event, normal):
            return
        runtime.schedule.clear_override()
        await normal.finish("✨ 已恢复正常日程状态")

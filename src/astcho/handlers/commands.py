from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg

from astcho.runtime import Runtime


def register_commands(runtime: Runtime) -> None:
    status = on_command("astcho_status", aliases={"stats", "what"}, priority=5, block=True)
    memories = on_command("astcho_memories", aliases={"recent"}, priority=5, block=True)
    reset = on_command("astcho_reset_memory", aliases={"clean"}, priority=5, block=True)
    schedule = on_command("astcho_schedule", aliases={"schedule"}, priority=5, block=True)

    async def require_admin(event: MessageEvent, matcher) -> bool:
        if runtime.is_admin(str(event.user_id)):
            return True
        await matcher.finish("权限不足。")
        return False

    @status.handle()
    async def handle_status(event: MessageEvent) -> None:
        if not await require_admin(event, status):
            return
        state = runtime.schedule.current()
        await status.finish(
            f"Astcho running | schedule={state.routine} | talk={state.talk_value} | "
            f"memories={runtime.vectors.memory_count()} | memes={runtime.sqlite.meme_count()} | "
            f"expressions={runtime.sqlite.expression_count()}"
        )

    @memories.handle()
    async def handle_memories(event: MessageEvent) -> None:
        if not await require_admin(event, memories):
            return
        user_id = str(event.user_id)
        group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else "private"
        # Private queries are always constrained to the current user, including admins.
        items = runtime.vectors.recent_memories(
            group_id=group_id if group_id != "private" else None,
            user_id=user_id if group_id == "private" else None,
            limit=10,
        )
        await memories.finish("\n".join(f"- {item.content}" for item in items) or "暂无记忆。")

    @reset.handle()
    async def handle_reset(event: MessageEvent) -> None:
        if not await require_admin(event, reset):
            return
        user_id = str(event.user_id)
        group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else "private"
        runtime.vectors.delete_memories(group_id=group_id,
                                        user_id=user_id if group_id == "private" else None)
        await reset.finish("记忆已重置。")

    @schedule.handle()
    async def handle_schedule(event: MessageEvent, args: Message = CommandArg()) -> None:
        if not await require_admin(event, schedule):
            return
        tokens = args.extract_plain_text().strip().split()
        try:
            if tokens and tokens[0] == "clear":
                runtime.schedule.clear_override()
            elif tokens and tokens[0] == "reload":
                runtime.schedule.reload()
            elif tokens and tokens[0] == "override" and len(tokens) >= 2:
                minutes = int(tokens[2]) if len(tokens) >= 3 else None
                runtime.schedule.set_routine_override(tokens[1], minutes=minutes)
            elif tokens and tokens[0] not in {"status"}:
                await schedule.finish("用法：/schedule status | override <routine> [minutes] | clear | reload")
        except (ValueError, IndexError) as exc:
            await schedule.finish(f"日程设置失败：{exc}")
        state = runtime.schedule.current()
        await schedule.finish(f"{state.routine}: talk={state.talk_value}, mood={state.mood}")

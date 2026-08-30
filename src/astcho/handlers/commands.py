from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from astcho.runtime import Runtime


def register_commands(runtime: Runtime) -> None:
    status = on_command("astcho_status", priority=5, block=True)
    memories = on_command("astcho_memories", priority=5, block=True)
    reset = on_command("astcho_reset_memory", priority=5, block=True)
    schedule = on_command("astcho_schedule", priority=5, block=True)

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
            f"memories={runtime.vectors.memory_count()} | memes={runtime.sqlite.meme_count()}"
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
    async def handle_schedule(event: MessageEvent) -> None:
        if not await require_admin(event, schedule):
            return
        state = runtime.schedule.current()
        await schedule.finish(f"{state.routine}: talk={state.talk_value}, mood={state.mood}")


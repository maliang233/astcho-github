from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import PrivateMessageEvent

from astcho.handlers.common import text_of
from astcho.runtime import Runtime


def register_private(runtime: Runtime) -> None:
    matcher = on_message(priority=20, block=False)

    @matcher.handle()
    async def handle(event: PrivateMessageEvent) -> None:
        user_id, text = str(event.user_id), text_of(event)
        if not text:
            return
        key = f"private:{user_id}"
        async with runtime.locks[key]:
            runtime.add_history(key, "user", text)
            context = "\n".join(f"{m['role']}: {m['content']}" for m in runtime.history(key))
            memories = runtime.memory.retrieve(text, group_id="private", user_id=user_id,
                                               limit=runtime.settings.max_memories)
            answer = await runtime.chat.reply(context, [m.content for m in memories],
                                              runtime.schedule.current().name)
            runtime.add_history(key, "assistant", answer)
            runtime.tasks.create(runtime.memory.extract(text, group_id="private", user_id=user_id))
            await matcher.finish(answer)

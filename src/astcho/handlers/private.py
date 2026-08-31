from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import PrivateMessageEvent
from nonebot.rule import is_type

from astcho.handlers.common import text_of
from astcho.runtime import Runtime


def register_private(runtime: Runtime) -> None:
    matcher = on_message(rule=is_type(PrivateMessageEvent), priority=20, block=False)

    @matcher.handle()
    async def handle(event: PrivateMessageEvent) -> None:
        user_id, text = str(event.user_id), text_of(event)
        if not text or text.startswith(("/", ".")):
            return
        key = f"private:{user_id}"
        async with runtime.locks[key]:
            handled, feedback = runtime.expressions.handle_admin_feedback(user_id, text)
            if handled:
                await matcher.finish(feedback)
            history = runtime.private_histories[key]
            history.append({"role": "user", "content": text})
            nickname = event.sender.nickname or "朋友"
            answer = await runtime.chat.private_reply(
                nickname=nickname, history=list(history), latest=text
            )
            history.append({"role": "assistant", "content": answer})
            await matcher.finish(answer)

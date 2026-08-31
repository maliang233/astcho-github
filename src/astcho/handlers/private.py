from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import PrivateMessageEvent
from nonebot.rule import is_type

from astcho.handlers.common import text_of
from astcho.logging import get_logger, preview
from astcho.runtime import Runtime

logger = get_logger(__name__)


def register_private(runtime: Runtime) -> None:
    matcher = on_message(rule=is_type(PrivateMessageEvent), priority=20, block=False)

    @matcher.handle()
    async def handle(event: PrivateMessageEvent) -> None:
        user_id, text = str(event.user_id), text_of(event)
        if not text or text.startswith(("/", ".")):
            return
        key = f"private:{user_id}"
        logger.chat_user("[私聊] %s: %s", event.sender.nickname or user_id, preview(text, 120))
        async with runtime.locks[key]:
            handled, feedback = runtime.expressions.handle_admin_feedback(user_id, text)
            if handled:
                await matcher.finish(feedback)
            history = runtime.private_histories[key]
            was_empty = not history
            history.append({"role": "user", "content": text})
            if was_empty:
                logger.system("🔒 [私聊:%s] 私聊会话启动完成", user_id)
            nickname = event.sender.nickname or "朋友"
            answer = await runtime.chat.private_reply(
                nickname=nickname, history=list(history), latest=text
            )
            history.append({"role": "assistant", "content": answer})
            logger.chat_ai(str(runtime.settings.profile.get("name", "Astcho")), answer)
            logger.debug("🔒 [私聊:%s] 本轮完成，历史共 %d 条", user_id, len(history))
            await matcher.finish(answer)

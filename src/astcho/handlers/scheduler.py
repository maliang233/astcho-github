from __future__ import annotations

import asyncio

from astcho.logging import get_logger
from astcho.runtime import Runtime

logger = get_logger(__name__)


async def maintenance_loop(runtime: Runtime) -> None:
    ticks = 0
    while True:
        await asyncio.sleep(300)
        try:
            logger.debug("⏰ [定时任务] 开始第 %d 次维护", ticks + 1)
            memories = await runtime.memory.flush()
            ticks += 1
            logger.debug("🧠 [定时任务] 记忆持久化新增 %d 条", memories)
            if ticks % 6 == 0 and runtime.settings.expression_learning:
                reviewed = await runtime.expressions.review_quality()
                logger.debug("📚 [定时任务] 表达自省处理 %d 条", reviewed)
            if ticks % 3 == 0 and runtime.settings.expression_learning and runtime.settings.admins:
                try:
                    from nonebot import get_bot

                    await runtime.expressions.ask_human_review(
                        get_bot(), sorted(runtime.settings.admins)[0]
                    )
                except (KeyError, RuntimeError):
                    pass
            if ticks % 12 == 0:
                runtime.memes.enforce_limit()
                runtime.schedule.reload()
                logger.system("📅 日程配置已重新加载")
            runtime.sqlite.set_state("last_maintenance", {"ok": True})
            logger.debug("✅ [定时任务] 第 %d 次维护完成", ticks)
        except Exception:
            logger.exception("定时维护任务出错")

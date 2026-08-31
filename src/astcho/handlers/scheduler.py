from __future__ import annotations

import asyncio
import logging

from astcho.runtime import Runtime

logger = logging.getLogger(__name__)


async def maintenance_loop(runtime: Runtime) -> None:
    ticks = 0
    while True:
        await asyncio.sleep(300)
        try:
            await runtime.memory.flush()
            ticks += 1
            if ticks % 6 == 0 and runtime.settings.expression_learning:
                await runtime.expressions.review_quality()
            if ticks % 12 == 0:
                runtime.memes.enforce_limit()
                runtime.schedule.reload()
            runtime.sqlite.set_state("last_maintenance", {"ok": True})
        except Exception:
            logger.exception("Scheduled maintenance failed")

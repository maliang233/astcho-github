from __future__ import annotations

import asyncio
import logging

from astcho.runtime import Runtime

logger = logging.getLogger(__name__)


async def maintenance_loop(runtime: Runtime) -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            runtime.memes.enforce_limit()
            runtime.schedule.reload()
            runtime.sqlite.set_state("last_maintenance", {"ok": True})
        except Exception:
            logger.exception("Scheduled maintenance failed")


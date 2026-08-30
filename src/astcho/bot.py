from __future__ import annotations

import logging

import nonebot
from nonebot.adapters.onebot.v11 import Adapter

from astcho.config import ConfigurationError, Settings
from astcho.handlers import register_commands, register_group, register_private
from astcho.handlers.scheduler import maintenance_loop
from astcho.runtime import Runtime


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    nonebot.init()
    driver = nonebot.get_driver()
    driver.register_adapter(Adapter)
    runtime = Runtime.build(settings)
    register_commands(runtime)
    register_group(runtime)
    register_private(runtime)

    @driver.on_startup
    async def startup() -> None:
        runtime.tasks.create(maintenance_loop(runtime))

    @driver.on_shutdown
    async def shutdown() -> None:
        await runtime.tasks.close()

    nonebot.run()


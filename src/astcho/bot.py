from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter

from astcho.config import ConfigurationError, Settings
from astcho.handlers import register_commands, register_group, register_private
from astcho.handlers.scheduler import maintenance_loop
from astcho.logging import configure_logging, get_logger
from astcho.runtime import Runtime

logger = get_logger(__name__)


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    configure_logging(debug=settings.debug, data_dir=settings.data_dir)
    logger.system("🌌 星回正在初始化...")
    # NoneBot's DEBUG startup dump contains every environment-backed setting,
    # including API keys. Keep framework logs at INFO and emit safe, targeted
    # application diagnostics through the standard logging module instead.
    nonebot.init(log_level="INFO")
    driver = nonebot.get_driver()
    driver.register_adapter(Adapter)
    runtime = Runtime.build(settings)
    register_commands(runtime)
    register_group(runtime)
    register_private(runtime)

    @driver.on_startup
    async def startup() -> None:
        logger.system("📅 日程系统已加载：%s", runtime.schedule.current().routine)
        logger.system(
            "🧠 记忆系统已就绪 (%d 条) | 🎨 表情包策展人已就绪 (%d 张)",
            runtime.vectors.memory_count(),
            runtime.sqlite.meme_count(),
        )
        logger.system(
            "🧮 Reasoning Replyer: %s | 📚 表达学习: %s",
            "已启用" if settings.reasoning_enabled else "已关闭",
            "已启用" if settings.expression_learning else "已关闭",
        )
        runtime.tasks.create(maintenance_loop(runtime))
        logger.system("✅ 星回启动完成，等待 OneBot 连接")

    @driver.on_bot_connect
    async def bot_connect(bot) -> None:
        logger.system("🔗 OneBot 已连接 | bot_id=%s", bot.self_id)

    @driver.on_bot_disconnect
    async def bot_disconnect(bot) -> None:
        logger.system("🔌 OneBot 已断开 | bot_id=%s", bot.self_id)

    @driver.on_shutdown
    async def shutdown() -> None:
        logger.system("🔌 星回正在关闭，保存运行时状态...")
        await runtime.tasks.close()
        saved = await runtime.memory.flush()
        logger.debug("🧠 [记忆] 关闭前写入 %d 条记忆", saved)
        logger.system("🔌 Bot 已断开，后台任务已清理")

    nonebot.run()

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SYSTEM = 25
CHAT_USER = 24
CHAT_AI = 23
logging.addLevelName(SYSTEM, "SYSTEM")
logging.addLevelName(CHAT_USER, "CHAT_USER")
logging.addLevelName(CHAT_AI, "CHAT_AI")


class _ConsoleFormatter(logging.Formatter):
    COLORS = {
        "SYSTEM": "\033[36m",
        "CHAT_USER": "\033[32m",
        "CHAT_AI": "\033[34m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[31m",
        "DEBUG": "\033[90m",
    }

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.levelno == SYSTEM:
            line = f"[System] {message}"
        elif record.levelno == CHAT_USER:
            line = f"👨 {message}"
        elif record.levelno == CHAT_AI:
            line = f"🌌 {message}"
        elif record.levelno == logging.DEBUG:
            line = f"  {message}"
        elif record.levelno == logging.WARNING:
            line = f"⚠️ Warning: {message}"
        elif record.levelno >= logging.ERROR:
            line = f"❌ Error: {message}"
        else:
            line = message
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        color = self.COLORS.get(record.levelname, "")
        return f"{color}{line}\033[0m" if color and sys.stderr.isatty() else line


class AstchoLogger:
    """Small compatibility facade for the observable stages used by Astcho."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def system(self, message: str, *args: Any) -> None:
        self._logger.log(SYSTEM, message, *args)

    def chat_user(self, message: str, *args: Any) -> None:
        self._logger.log(CHAT_USER, message, *args)

    def chat_ai(self, name: str, message: str) -> None:
        self._logger.log(CHAT_AI, "[%s] %s", name, message.strip())

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(message, *args, **kwargs)

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.exception(message, *args, **kwargs)


def get_logger(name: str) -> AstchoLogger:
    return AstchoLogger(name)


def configure_logging(*, debug: bool, data_dir: Path) -> None:
    """Configure detailed app logs without exposing NoneBot's environment dump."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    root.setLevel(logging.INFO)

    app = logging.getLogger("astcho")
    app.handlers.clear()
    app.propagate = False
    app.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if debug else SYSTEM)
    console.setFormatter(_ConsoleFormatter())
    app.addHandler(console)

    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / f"{datetime.now():%Y-%m-%d}.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    )
    app.addHandler(file_handler)

    for noisy in ("chromadb", "httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def preview(value: str, limit: int = 80) -> str:
    """Single-line preview for local diagnostics; never print complete prompts by default."""
    clean = " ".join(str(value).split())
    return clean if len(clean) <= limit else clean[:limit] + "..."

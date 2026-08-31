from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when a required public configuration value is missing."""


def _csv_set(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    return parsed


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if parsed < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    return parsed


@dataclass(frozen=True, slots=True)
class Settings:
    llm_api_key: str
    llm_base_url: str
    chat_model: str
    planner_model: str
    planner_api_key: str
    planner_base_url: str
    vision_model: str
    vision_api_key: str
    vision_base_url: str
    reasoning_enabled: bool
    reasoning_model: str
    reasoning_api_key: str
    reasoning_base_url: str
    admins: frozenset[str]
    allowed_groups: frozenset[str]
    data_dir: Path
    profile_path: Path
    schedule_path: Path
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    short_history_limit: int = 10
    max_memories: int = 8
    meme_limit: int = 300
    expression_learning: bool = True
    expression_learn_interval: int = 900
    expression_learn_min_messages: int = 10
    forward_max_text_segments: int = 200
    forward_max_media_segments: int = 20
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0
    debug: bool = False
    reply_cooldown_seconds: int = 5
    planner_temperature: float = 0.1
    chat_temperature: float = 0.7
    reasoning_temperature: float = 0.1
    profile: dict = field(default_factory=dict, compare=False)

    @classmethod
    def from_env(cls, *, load_file: bool = True) -> Settings:
        if load_file:
            load_dotenv(override=False)

        required = {
            "ASTCHO_LLM_API_KEY": os.getenv("ASTCHO_LLM_API_KEY", "").strip(),
            "ASTCHO_LLM_BASE_URL": os.getenv("ASTCHO_LLM_BASE_URL", "").strip(),
            "ASTCHO_CHAT_MODEL": os.getenv("ASTCHO_CHAT_MODEL", "").strip(),
            "ASTCHO_PLANNER_MODEL": os.getenv("ASTCHO_PLANNER_MODEL", "").strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ConfigurationError(
                "Missing required settings: " + ", ".join(missing) + ". Copy .env.example to .env."
            )

        admins = _csv_set(os.getenv("ASTCHO_ADMINS"))
        if not admins:
            raise ConfigurationError("ASTCHO_ADMINS must contain at least one QQ user ID")

        data_dir = Path(os.getenv("ASTCHO_DATA_DIR", "var")).expanduser().resolve()
        profile_path = Path(os.getenv("ASTCHO_PROFILE_PATH", "config/profile.json"))
        schedule_path = Path(os.getenv("ASTCHO_SCHEDULE_PATH", "config/schedule.json"))
        vision_api_key = (
            os.getenv("ASTCHO_VISION_API_KEY", "").strip() or required["ASTCHO_LLM_API_KEY"]
        )
        vision_base_url = (
            os.getenv("ASTCHO_VISION_BASE_URL", "").strip() or required["ASTCHO_LLM_BASE_URL"]
        )
        reasoning_api_key = (
            os.getenv("ASTCHO_REASONING_API_KEY", "").strip() or required["ASTCHO_LLM_API_KEY"]
        )
        reasoning_base_url = (
            os.getenv("ASTCHO_REASONING_BASE_URL", "").strip() or required["ASTCHO_LLM_BASE_URL"]
        )

        profile = _load_profile(profile_path)
        return cls(
            llm_api_key=required["ASTCHO_LLM_API_KEY"],
            llm_base_url=required["ASTCHO_LLM_BASE_URL"],
            chat_model=required["ASTCHO_CHAT_MODEL"],
            planner_model=required["ASTCHO_PLANNER_MODEL"],
            planner_api_key=os.getenv("ASTCHO_PLANNER_API_KEY", "").strip()
            or required["ASTCHO_LLM_API_KEY"],
            planner_base_url=os.getenv("ASTCHO_PLANNER_BASE_URL", "").strip()
            or required["ASTCHO_LLM_BASE_URL"],
            vision_model=os.getenv("ASTCHO_VISION_MODEL", "").strip()
            or required["ASTCHO_CHAT_MODEL"],
            vision_api_key=vision_api_key,
            vision_base_url=vision_base_url,
            reasoning_enabled=_bool(os.getenv("ASTCHO_REASONING_ENABLED"), True),
            reasoning_model=os.getenv("ASTCHO_REASONING_MODEL", "").strip()
            or required["ASTCHO_CHAT_MODEL"],
            reasoning_api_key=reasoning_api_key,
            reasoning_base_url=reasoning_base_url,
            admins=admins,
            allowed_groups=_csv_set(os.getenv("ASTCHO_ALLOWED_GROUPS")),
            data_dir=data_dir,
            profile_path=profile_path,
            schedule_path=schedule_path,
            embedding_model=os.getenv("ASTCHO_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip(),
            short_history_limit=_int("ASTCHO_SHORT_HISTORY_LIMIT", 10),
            max_memories=_int("ASTCHO_MAX_MEMORIES", 8, 1),
            meme_limit=_int("ASTCHO_MEME_LIMIT", 300, 1),
            expression_learning=_bool(os.getenv("ASTCHO_EXPRESSION_LEARNING"), True),
            expression_learn_interval=_int("ASTCHO_EXPRESSION_LEARN_INTERVAL", 900, 30),
            expression_learn_min_messages=_int("ASTCHO_EXPRESSION_LEARN_MIN_MESSAGES", 10, 3),
            forward_max_text_segments=_int("ASTCHO_FORWARD_MAX_TEXT_SEGMENTS", 200, 3),
            forward_max_media_segments=_int("ASTCHO_FORWARD_MAX_MEDIA_SEGMENTS", 20, 1),
            input_price_per_million=_float("ASTCHO_INPUT_PRICE_PER_MILLION", 0.0),
            output_price_per_million=_float("ASTCHO_OUTPUT_PRICE_PER_MILLION", 0.0),
            debug=_bool(os.getenv("ASTCHO_DEBUG")),
            reply_cooldown_seconds=_int("ASTCHO_REPLY_COOLDOWN_SECONDS", 5),
            profile=profile,
        )

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "chroma").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "memes").mkdir(parents=True, exist_ok=True)


def _load_profile(path: Path) -> dict:
    if not path.exists():
        return {
            "name": "Astcho",
            "personality": "A warm, thoughtful AI companion.",
            "style": ["Speak naturally and briefly", "Respect privacy"],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load profile from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError("Profile must be a JSON object")
    return data

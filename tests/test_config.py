from pathlib import Path

import pytest

from astcho.config import ConfigurationError, Settings


def test_missing_configuration_fails_early(monkeypatch):
    for name in ("ASTCHO_LLM_API_KEY", "ASTCHO_LLM_BASE_URL", "ASTCHO_CHAT_MODEL",
                 "ASTCHO_PLANNER_MODEL", "ASTCHO_ADMINS"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="Missing required"):
        Settings.from_env(load_file=False)


def test_settings_parse_lists(monkeypatch, tmp_path: Path):
    values = {
        "ASTCHO_LLM_API_KEY": "test", "ASTCHO_LLM_BASE_URL": "https://example.invalid/v1",
        "ASTCHO_CHAT_MODEL": "chat", "ASTCHO_PLANNER_MODEL": "planner",
        "ASTCHO_ADMINS": "1, 2", "ASTCHO_ALLOWED_GROUPS": "9,10",
        "ASTCHO_DATA_DIR": str(tmp_path), "ASTCHO_SHORT_HISTORY_LIMIT": "0",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Settings.from_env(load_file=False)
    assert settings.admins == frozenset({"1", "2"})
    assert settings.allowed_groups == frozenset({"9", "10"})
    assert settings.short_history_limit == 0


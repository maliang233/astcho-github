from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ScheduleState:
    talk_value: int
    mood: str
    routine: str
    overridden: bool = False


class ScheduleService:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._override: ScheduleState | None = None
        self._config = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {
                "default": [
                    {"start": "00:00", "end": "23:59", "talk_value": 50, "mood": "calm"}
                ]
            }
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Schedule configuration must be an object")
        return data

    def reload(self) -> None:
        self._config = self._load()

    def set_override(self, talk_value: int, mood: str) -> None:
        self._override = ScheduleState(
            talk_value=max(0, min(100, talk_value)),
            mood=mood[:200],
            routine="override",
            overridden=True,
        )

    def clear_override(self) -> None:
        self._override = None

    def current(self, now: datetime | None = None) -> ScheduleState:
        if self._override:
            return self._override
        now = now or datetime.now()
        weekday = now.strftime("%A").lower()
        blocks = self._config.get(weekday) or self._config.get("default", [])
        current = now.strftime("%H:%M")
        for block in blocks:
            if _in_range(current, str(block["start"]), str(block["end"])):
                return ScheduleState(
                    talk_value=max(0, min(100, int(block.get("talk_value", 50)))),
                    mood=str(block.get("mood", "calm"))[:200],
                    routine=weekday if weekday in self._config else "default",
                )
        return ScheduleState(50, "calm", "fallback")


def _in_range(current: str, start: str, end: str) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


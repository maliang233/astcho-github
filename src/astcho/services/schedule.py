from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
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
        self._override_until: datetime | None = None
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

    def set_override(self, talk_value: int, mood: str, *, routine: str = "override",
                     minutes: int | None = None) -> None:
        self._override = ScheduleState(
            talk_value=max(0, min(100, talk_value)),
            mood=mood[:200],
            routine=routine,
            overridden=True,
        )
        self._override_until = datetime.now() + timedelta(minutes=minutes) if minutes else None

    def set_routine_override(self, routine: str, *, minutes: int | None = None) -> None:
        blocks = self._config.get("routines", {}).get(routine)
        if not blocks:
            raise ValueError(f"Unknown routine: {routine}")
        current = datetime.now().strftime("%H:%M")
        block = next((item for item in blocks if _in_range(current, str(item["start"]), str(item["end"]))), blocks[0])
        self.set_override(int(block.get("talk_value", 50)),
                          str(block.get("mood", block.get("mood_prompt", "calm"))),
                          routine=routine, minutes=minutes)

    def clear_override(self) -> None:
        self._override = None
        self._override_until = None

    def current(self, now: datetime | None = None) -> ScheduleState:
        if self._override_until and datetime.now() >= self._override_until:
            self.clear_override()
        if self._override:
            return self._override
        now = now or datetime.now()
        weekday = now.strftime("%A").lower()
        blocks, routine_name, mood_append = self._resolve_blocks(now, weekday)
        current = now.strftime("%H:%M")
        for block in blocks:
            if _in_range(current, str(block["start"]), str(block["end"])):
                return ScheduleState(
                    talk_value=max(0, min(100, int(block.get("talk_value", 50)))),
                    mood=(str(block.get("mood", block.get("mood_prompt", "calm"))) + mood_append)[:500],
                    routine=routine_name,
                )
        return ScheduleState(50, "calm", "fallback")

    def _resolve_blocks(self, now: datetime, weekday: str) -> tuple[list, str, str]:
        routines = self._config.get("routines")
        if not isinstance(routines, dict):
            blocks = self._config.get(weekday) or self._config.get("default", [])
            return blocks, weekday if weekday in self._config else "default", ""
        special = self._config.get("yearly_specials", {}).get(now.strftime("%m-%d"), {})
        weekly = self._config.get("weekly_rules", {})
        routine_name = str(
            special.get("routine_id") or weekly.get(now.strftime("%A")) or "default_fallback"
        )
        append = str(special.get("mood_append", ""))
        return list(routines.get(routine_name, routines.get("default_fallback", []))), routine_name, append


def _in_range(current: str, start: str, end: str) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end

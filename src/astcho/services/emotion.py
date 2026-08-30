from __future__ import annotations

import time
from dataclasses import dataclass

from astcho.storage.sqlite import SQLiteStore


@dataclass(slots=True)
class Mood:
    excitement: float = 0.0
    shyness: float = 0.0
    updated_at: float = 0.0


class EmotionService:
    def __init__(self, store: SQLiteStore):
        self.store = store
        self._moods: dict[str, Mood] = {}

    def touch_user(self, group_id: str, user_id: str, nickname: str) -> None:
        self.store.touch_user(group_id, user_id, nickname)

    def state(self, group_id: str, user_id: str) -> dict[str, float]:
        mood = self._moods.setdefault(group_id, Mood(updated_at=time.time()))
        self._decay(mood)
        user = self.store.get_user(group_id, user_id)
        return {
            "excitement": mood.excitement,
            "shyness": mood.shyness,
            "affinity": float(user["affinity"]) if user else 0.3,
        }

    def apply(
        self,
        group_id: str,
        user_id: str,
        *,
        excitement_delta: float,
        shyness_delta: float,
        affinity_score: float,
    ) -> dict[str, float]:
        mood = self._moods.setdefault(group_id, Mood(updated_at=time.time()))
        self._decay(mood)
        mood.excitement = _clamp(mood.excitement + excitement_delta, -1, 1)
        mood.shyness = _clamp(mood.shyness + shyness_delta, 0, 1)
        if affinity_score:
            self.store.update_affinity(group_id, user_id, _clamp(affinity_score, -1, 1) * 0.03)
        return self.state(group_id, user_id)

    @staticmethod
    def _decay(mood: Mood) -> None:
        now = time.time()
        elapsed_hours = max(0.0, now - mood.updated_at) / 3600
        factor = 0.85**elapsed_hours
        mood.excitement *= factor
        mood.shyness *= factor
        mood.updated_at = now


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


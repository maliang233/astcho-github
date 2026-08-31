from __future__ import annotations

import random
import time
from dataclasses import dataclass

from astcho.storage.sqlite import SQLiteStore


@dataclass(slots=True)
class Mood:
    excitement: float = 0.0
    shyness: float = 0.0
    updated_at: float = 0.0


class EmotionService:
    def __init__(self, store: SQLiteStore, admins: frozenset[str] = frozenset()):
        self.store = store
        self.admins = admins
        self._moods: dict[str, Mood] = {}

    def touch_user(self, group_id: str, user_id: str, nickname: str) -> None:
        self.store.touch_user(group_id, user_id, nickname)

    def state(self, group_id: str, user_id: str) -> dict[str, float]:
        mood = self._moods.setdefault(group_id, Mood(updated_at=time.time()))
        self._decay(mood)
        user = self.store.get_user(group_id, user_id)
        if user:
            self._decay_affinity(group_id, user_id, user)
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
        mood.excitement = _clamp(mood.excitement + excitement_delta, 0, 1)
        mood.shyness = _clamp(mood.shyness + shyness_delta, 0, 1)
        if affinity_score:
            self._apply_affinity(group_id, user_id, affinity_score)
        return self.state(group_id, user_id)

    @staticmethod
    def _decay(mood: Mood) -> None:
        now = time.time()
        elapsed_hours = max(0.0, now - mood.updated_at) / 3600
        factor = 0.85**elapsed_hours
        mood.excitement *= factor
        mood.shyness *= factor
        mood.updated_at = now

    def _apply_affinity(self, group_id: str, user_id: str, score: float) -> None:
        user = self.store.get_user(group_id, user_id)
        if not user:
            self.store.touch_user(group_id, user_id, user_id)
            user = self.store.get_user(group_id, user_id)
        now = time.time()
        if now - float(user.get("affinity_changed_at", 0)) < 60:
            return
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        daily = (
            float(user.get("affinity_daily_delta", 0)) if user.get("affinity_day") == day else 0.0
        )
        requested = _clamp(score, -1, 1) * 0.03
        remaining = max(0.0, 0.10 - abs(daily))
        delta = _clamp(requested, -remaining, remaining)
        floor = 0.75 if user_id in self.admins else 0.25
        affinity = _clamp(float(user["affinity"]) + delta, floor, 1.0)
        actual = affinity - float(user["affinity"])
        self.store.set_affinity_state(
            group_id,
            user_id,
            affinity=affinity,
            daily_delta=daily + actual,
            day=day,
            changed_at=now,
            decayed_at=float(user.get("affinity_decayed_at", now) or now),
        )

    def _decay_affinity(self, group_id: str, user_id: str, user: dict) -> None:
        now = time.time()
        last = float(user.get("affinity_decayed_at", 0) or now)
        days = max(0.0, now - last) / 86400
        if days < 1:
            return
        floor = 0.75 if user_id in self.admins else 0.25
        current = float(user["affinity"])
        decayed = _clamp(current - 0.005 * days * (1 - current) ** 2, floor, 1.0)
        self.store.set_affinity_state(
            group_id,
            user_id,
            affinity=decayed,
            daily_delta=float(user.get("affinity_daily_delta", 0)),
            day=str(user.get("affinity_day", "")),
            changed_at=float(user.get("affinity_changed_at", 0)),
            decayed_at=now,
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def apply_typo(text: str, excitement: float, *, random_value: float | None = None) -> str:
    """Occasionally mimic a harmless excited typo used by the chat persona."""
    if not text or excitement < 0.3:
        return text
    sample = random.random() if random_value is None else random_value
    if sample > (excitement - 0.3) * 0.35:
        return text
    substitutions = {
        "好耶": "豪耶",
        "厉害": "利害",
        "支持": "智齿",
        "真的": "震的",
        "开心": "凯心",
        "谢谢": "鞋鞋",
        "嘻嘻": "系系",
    }
    for original, typo in substitutions.items():
        if original in text:
            return text.replace(original, typo, 1)
    return text

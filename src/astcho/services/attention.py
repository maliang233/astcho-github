from __future__ import annotations

import random
import time
from collections import deque

from astcho.domain.models import ChatMessage
from astcho.services.schedule import ScheduleState


class AttentionService:
    """Per-group context and deterministic identity-aware trigger state."""

    def __init__(
        self, bot_id: str, *, bot_name: str = "Astcho", base_talk_probability: float = 0.1
    ):
        self.bot_id = str(bot_id)
        self.bot_name = bot_name
        self.base_talk_probability = base_talk_probability
        self.messages: deque[ChatMessage] = deque(maxlen=30)
        self.last_bot_reply = 0.0
        self.consecutive_no_reply = 0
        self.watching_until = 0.0
        self._recent_meme_flags: deque[bool] = deque(maxlen=10)

    def add(self, message: ChatMessage) -> None:
        self.messages.append(message)
        if message.is_bot or message.user_id == self.bot_id:
            self.last_bot_reply = message.timestamp

    def should_plan(
        self,
        message: ChatMessage,
        schedule: ScheduleState,
        *,
        excitement: float = 0.0,
        random_value: float | None = None,
    ) -> bool:
        direct = (
            message.mentioned_bot
            or message.replied_to_bot
            or self.bot_name.lower() in message.text.lower()
        )
        if schedule.talk_value < 10:
            return message.mentioned_bot or message.replied_to_bot
        if direct:
            return True
        now = time.time()
        if self.last_bot_reply and now - self.last_bot_reply < 5:
            return False
        silence_bonus = (
            min(0.2, max(0, now - self.last_bot_reply) / 600 * 0.05) if self.last_bot_reply else 0
        )
        recent = [m for m in self.messages if not m.is_bot and now - m.timestamp <= 300]
        average_gap = (
            (recent[-1].timestamp - recent[0].timestamp) / (len(recent) - 1)
            if len(recent) > 1
            else 999
        )
        frequency_factor = (
            0.6
            if average_gap < 60
            else 0.75
            if average_gap < 180
            else 0.9
            if average_gap < 300
            else 1.0
        )
        threshold_factor = 1.2 if self.consecutive_no_reply >= 2 else 1.0
        watching_factor = 1.35 if now < self.watching_until else 1.0
        probability = (self.base_talk_probability + silence_bonus) * (schedule.talk_value / 100)
        probability *= frequency_factor * threshold_factor * watching_factor
        probability *= 1 + max(-1, min(1, excitement)) * 0.8
        sample = random.random() if random_value is None else random_value
        return sample < max(0.0, min(1.0, probability))

    def update_after_planner(self, replied: bool) -> None:
        if replied:
            self.consecutive_no_reply = 0
            self.watching_until = 0.0
        else:
            self.consecutive_no_reply += 1
            if self.consecutive_no_reply >= 2:
                self.watching_until = time.time() + 10

    def context(self, limit: int = 20) -> str:
        lines = []
        for message in list(self.messages)[-limit:]:
            role = (
                self.bot_name
                if message.user_id == self.bot_id or message.is_bot
                else message.nickname
            )
            suffix = " [mentioned you]" if message.mentioned_bot else ""
            image = f" [image: {message.image_description}]" if message.image_description else ""
            lines.append(f"[{message.message_id}] {role}: {message.text}{image}{suffix}")
        return "\n".join(lines)

    def seconds_since_bot_reply(self) -> int | None:
        if not self.last_bot_reply:
            return None
        return max(0, int(time.time() - self.last_bot_reply))

from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from difflib import SequenceMatcher

from astcho.domain.models import ChatMessage, ExpressionExtraction, ExpressionReview
from astcho.prompts import expression_learning_prompt
from astcho.services.llm import LLMResponseError, LLMService
from astcho.storage.sqlite import SQLiteStore


class ExpressionService:
    """Learns per-group situation/style rules without retaining full chat logs."""

    def __init__(self, store: SQLiteStore, llm: LLMService, model: str, *,
                 interval: int = 1800, minimum_messages: int = 10):
        self.store, self.llm, self.model = store, llm, model
        self.interval, self.minimum_messages = interval, minimum_messages
        self.buffers: defaultdict[str, deque[ChatMessage]] = defaultdict(lambda: deque(maxlen=50))
        self.last_learn: defaultdict[str, float] = defaultdict(float)
        self.locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def observe(self, group_id: str, message: ChatMessage) -> bool:
        if not message.text or message.is_bot:
            return False
        self.buffers[group_id].append(message)
        return (len(self.buffers[group_id]) >= self.minimum_messages
                and time.time() - self.last_learn[group_id] >= self.interval)

    async def learn(self, group_id: str, bot_name: str) -> int:
        async with self.locks[group_id]:
            messages = list(self.buffers[group_id])
            if len(messages) < self.minimum_messages:
                return 0
            self.buffers[group_id].clear()
            self.last_learn[group_id] = time.time()
            lines = [f"[{index}] [{'SELF' if item.is_bot else item.nickname}] {item.text}"
                     for index, item in enumerate(messages, 1)]
            try:
                result = await self.llm.json_completion(
                    model=self.model, schema=ExpressionExtraction,
                    messages=[{"role": "user", "content": expression_learning_prompt(
                        "\n".join(lines), bot_name
                    )}], temperature=0.3,
                )
            except LLMResponseError:
                return 0
            learned = 0
            for item in result.expressions:
                index = item.source_id - 1
                if index < 0 or index >= len(messages) or messages[index].is_bot:
                    continue
                if _unsafe(item.situation) or _unsafe(item.style):
                    continue
                existing = self._find_similar(group_id, item.situation)
                self.store.add_expression(group_id, item.situation, item.style,
                                          similar_id=existing["id"] if existing else None)
                learned += 1
            return learned

    def relevant_hint(self, group_id: str, context: str, limit: int = 5) -> str:
        expressions = self.store.list_expressions(group_id, include_singletons=False, limit=50)
        expressions.sort(
            key=lambda item: max(
                SequenceMatcher(None, context[-500:], item["situation"]).ratio(),
                min(1.0, item["count"] / 10),
            ), reverse=True,
        )
        selected = expressions[:limit]
        if not selected:
            return ""
        return "\n".join(
            f'- 当“{item["situation"]}”时，可以“{item["style"]}”'
            for item in selected
        )

    def _find_similar(self, group_id: str, situation: str) -> dict | None:
        best, score = None, 0.65
        for item in self.store.list_expressions(group_id, limit=500):
            samples = item["examples"] or [item["situation"]]
            similarity = max(SequenceMatcher(None, situation, sample).ratio() for sample in samples)
            if similarity >= score:
                best, score = item, similarity
        return best

    async def review_quality(self) -> int:
        items = self.store.pending_expression_reviews(5)
        if not items:
            return 0
        listing = "\n".join(f"[{item['id']}] 场景:{item['situation']} | 表达:{item['style']} | 次数:{item['count']}"
                            for item in items)
        prompt = f"""审核以下从群聊中归纳的表达习惯。保留自然、可复用、无私人信息的规则；拒绝过拟合、冒犯、包含身份信息或语义不明的规则。
{listing}
只输出 JSON：{{"accepted_ids":[1],"rejected_ids":[2]}}"""
        try:
            result = await self.llm.json_completion(model=self.model, schema=ExpressionReview,
                                                    messages=[{"role": "user", "content": prompt}],
                                                    temperature=0.1, max_tokens=200)
        except LLMResponseError:
            return 0
        valid = {int(item["id"]) for item in items}
        accepted = [item for item in result.accepted_ids if item in valid]
        rejected = [item for item in result.rejected_ids if item in valid and item not in accepted]
        self.store.review_expressions(accepted, rejected)
        return len(accepted) + len(rejected)


def _unsafe(value: str) -> bool:
    return bool(re.search(r"(?:QQ|UID|账号)\s*[:：]?\s*\d{5,}|@\S+|\[图片", value, re.I))

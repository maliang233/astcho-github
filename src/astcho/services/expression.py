from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from difflib import SequenceMatcher

from astcho.domain.models import ChatMessage, ExpressionExtraction, ExpressionReview
from astcho.logging import get_logger, preview
from astcho.prompts import expression_learning_prompt
from astcho.services.llm import LLMResponseError, LLMService
from astcho.storage.sqlite import SQLiteStore

logger = get_logger(__name__)


class ExpressionService:
    """Learns per-group situation/style rules without retaining full chat logs."""

    def __init__(
        self,
        store: SQLiteStore,
        llm: LLMService,
        model: str,
        *,
        interval: int = 1800,
        minimum_messages: int = 10,
    ):
        self.store, self.llm, self.model = store, llm, model
        self.interval, self.minimum_messages = interval, minimum_messages
        self.buffers: defaultdict[str, deque[ChatMessage]] = defaultdict(lambda: deque(maxlen=50))
        self.last_learn: defaultdict[str, float] = defaultdict(float)
        self.locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.pending_human_review: dict | None = None
        self.last_human_review = 0.0

    def observe(self, group_id: str, message: ChatMessage) -> bool:
        if not message.text or message.is_bot:
            return False
        self.buffers[group_id].append(message)
        logger.debug(
            "📚 [表达学习] 群 %s 已积累 %d/%d 条",
            group_id,
            len(self.buffers[group_id]),
            self.minimum_messages,
        )
        return (
            len(self.buffers[group_id]) >= self.minimum_messages
            and time.time() - self.last_learn[group_id] >= self.interval
        )

    async def learn(self, group_id: str, bot_name: str) -> int:
        async with self.locks[group_id]:
            messages = list(self.buffers[group_id])
            if len(messages) < self.minimum_messages:
                return 0
            self.buffers[group_id].clear()
            self.last_learn[group_id] = time.time()
            logger.debug("📚 [表达学习] 群 %s 开始分析 %d 条消息", group_id, len(messages))
            lines = [
                f"[{index}] [{'SELF' if item.is_bot else item.nickname}] {item.text}"
                for index, item in enumerate(messages, 1)
            ]
            try:
                result = await self.llm.json_completion(
                    model=self.model,
                    schema=ExpressionExtraction,
                    messages=[
                        {
                            "role": "user",
                            "content": expression_learning_prompt("\n".join(lines), bot_name),
                        }
                    ],
                    temperature=0.3,
                )
            except LLMResponseError as exc:
                logger.error("[表达学习] 学习失败: %s", exc)
                return 0
            learned = 0
            for item in result.expressions:
                index = item.source_id - 1
                if index < 0 or index >= len(messages) or messages[index].is_bot:
                    continue
                if _unsafe(item.situation) or _unsafe(item.style):
                    continue
                existing = self._find_similar(group_id, item.situation)
                self.store.add_expression(
                    group_id,
                    item.situation,
                    item.style,
                    similar_id=existing["id"] if existing else None,
                )
                learned += 1
                logger.debug("   - %s -> %s", preview(item.situation, 50), preview(item.style, 50))
            if learned:
                logger.system("📚 [表达学习] 在群 %s 学习到 %d 个表达方式", group_id, learned)
            else:
                logger.debug("📚 [表达学习] 本轮没有获得可用表达")
            return learned

    def relevant_hint(self, group_id: str, context: str, limit: int = 5) -> str:
        # Keep the original runtime behavior: stable, frequently observed group
        # expressions win. ``context`` remains part of the interface for callers,
        # but the legacy implementation intentionally did not use it for ranking.
        selected = self.store.list_expressions(group_id, include_singletons=False, limit=limit)
        if not selected:
            return ""
        logger.debug(
            "📚 [表达选择] 群 %s 按累计次数选出 %d 条",
            group_id,
            len(selected),
        )
        return "\n".join(f"- 当“{item['situation']}”时，可以“{item['style']}”" for item in selected)

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
            logger.debug("📚 [表达自省] 没有待检查表达")
            return 0
        logger.system("📚 [表达自省] 开始检查 %d 条表达", len(items))
        listing = "\n".join(
            f"[{item['id']}] 场景:{item['situation']} | 表达:{item['style']} | 次数:{item['count']}"
            for item in items
        )
        prompt = f"""审核以下从群聊中归纳的表达习惯。
保留自然、可复用、无私人信息的规则；拒绝过拟合、冒犯、包含身份信息或语义不明的规则。
{listing}
只输出 JSON：{{"accepted_ids":[1],"rejected_ids":[2]}}"""
        try:
            result = await self.llm.json_completion(
                model=self.model,
                schema=ExpressionReview,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
            )
        except LLMResponseError as exc:
            logger.error("[表达自省] 检查失败: %s", exc)
            return 0
        valid = {int(item["id"]) for item in items}
        accepted = [item for item in result.accepted_ids if item in valid]
        rejected = [item for item in result.rejected_ids if item in valid and item not in accepted]
        self.store.review_expressions(accepted, rejected)
        logger.system("📚 [表达自省] 通过 %d 条，拒绝 %d 条", len(accepted), len(rejected))
        return len(accepted) + len(rejected)

    async def ask_human_review(self, bot, admin_id: str) -> bool:
        now = time.time()
        if self.pending_human_review:
            if now - float(self.pending_human_review["asked_at"]) <= 3600:
                return False
            self.pending_human_review = None
        if now - self.last_human_review < 15 * 60:
            return False
        item = self.store.expression_for_human_review()
        if not item:
            return False
        self.pending_human_review = {**item, "asked_at": now, "admin_id": str(admin_id)}
        message = (
            "📚 【表达学习审核】\n\n我在群里学到了一个新的表达方式，请帮我看看是否合适：\n\n"
            f"情境：{item['situation']}\n风格：{item['style']}\n\n"
            "回复“通过”表示认可，回复“拒绝”表示不合适。"
        )
        try:
            await bot.send_private_msg(user_id=int(admin_id), message=message)
        except Exception:
            self.pending_human_review = None
            raise
        self.last_human_review = now
        logger.system(
            "📚 [表达反思] 向管理员提问: %s -> %s",
            preview(item["situation"], 50),
            preview(item["style"], 50),
        )
        return True

    def handle_admin_feedback(self, user_id: str, text: str) -> tuple[bool, str]:
        pending = self.pending_human_review
        if not pending or str(user_id) != pending["admin_id"]:
            return False, ""
        normalized = text.strip().lower()
        # Sentence-level feedback is accepted, e.g. “这个不太合适，拒绝吧”.
        # Check explicit negative phrases first so “不好” is not mistaken for “好”.
        reject_phrases = ("不合适", "不太合适", "不行", "不好", "拒绝", "no")
        approve_phrases = ("通过", "可以", "同意", "认可", "ok", "yes", "好", "行")
        reject = any(phrase in normalized for phrase in reject_phrases)
        approve = not reject and any(phrase in normalized for phrase in approve_phrases)
        if not approve and not reject:
            return False, ""
        expression_id = int(pending["id"])
        if approve:
            self.store.review_expressions([expression_id], [])
            logger.system("📚 [表达反思] 管理员通过表达 #%d", expression_id)
        else:
            self.store.delete_expression(expression_id)
            logger.system("📚 [表达反思] 管理员拒绝并删除表达 #%d", expression_id)
        self.pending_human_review = None
        return True, "✅"


def _unsafe(value: str) -> bool:
    return bool(re.search(r"(?:QQ|UID|账号)\s*[:：]?\s*\d{5,}|@\S+|\[图片", value, re.I))

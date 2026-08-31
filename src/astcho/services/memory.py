from __future__ import annotations

from collections import defaultdict

from astcho.domain.models import MemoryExtraction, RetrievedMemory
from astcho.logging import get_logger, preview
from astcho.prompts import memory_extraction_prompt
from astcho.services.llm import LLMResponseError, LLMService
from astcho.storage.chroma import ChromaStore

logger = get_logger(__name__)


class MemoryService:
    def __init__(self, vectors: ChromaStore, llm: LLMService, model: str):
        self.vectors = vectors
        self.llm = llm
        self.model = model
        self._pending: defaultdict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)

    def queue_turn(
        self, user_text: str, bot_text: str, *, group_id: str, user_id: str, user_name: str = "用户"
    ) -> None:
        key = (group_id, user_id)
        self._pending[key].append((user_name, user_text, bot_text))
        logger.debug(
            "📝 [记忆队列] session=%s/%s | %d/5 回合",
            group_id,
            user_id,
            len(self._pending[key]),
        )
        if len(self._pending[key]) >= 5:
            turns = self._pending.pop(key)
            import asyncio

            asyncio.create_task(
                self.extract(
                    _format_turns(turns), group_id=group_id, user_id=user_id, user_name=user_name
                )
            )

    async def flush(self) -> int:
        pending, self._pending = self._pending, defaultdict(list)
        total = 0
        for (group_id, user_id), turns in pending.items():
            total += await self.extract(
                _format_turns(turns), group_id=group_id, user_id=user_id, user_name=turns[-1][0]
            )
        logger.debug("🧠 [记忆持久化] 刷新 %d 个会话，新增 %d 条", len(pending), total)
        return total

    async def extract(
        self, text: str, *, group_id: str, user_id: str, user_name: str = "用户"
    ) -> int:
        if len(text.strip()) < 6:
            logger.debug("🧠 [记忆提取] 文本过短，跳过")
            return 0
        logger.debug("🧠 [记忆提取] session=%s/%s | 输入=%s", group_id, user_id, preview(text, 80))
        try:
            result = await self.llm.json_completion(
                model=self.model,
                schema=MemoryExtraction,
                messages=[
                    *memory_extraction_prompt(
                        text=text[:3000], user_id=user_id, user_name=user_name
                    ),
                ],
            )
        except LLMResponseError as exc:
            logger.warning("记忆提取输出无效，已跳过: %s", exc)
            return 0
        count = 0
        existing = self.vectors.retrieve_memories(
            text,
            group_id=group_id if group_id != "private" else None,
            user_id=user_id if group_id == "private" else None,
            limit=5,
        )
        for atom in result.memories:
            if any(item.score > 0.94 for item in existing if item.content == atom.content):
                continue
            self.vectors.add_memory(
                atom.content,
                group_id=group_id,
                user_id=user_id,
                kind=atom.kind,
                importance=atom.importance,
            )
            count += 1
        logger.system("🧠 [记忆] 提取 %d 条，去重后写入 %d 条", len(result.memories), count)
        return count

    def retrieve(
        self, query: str, *, group_id: str, user_id: str, limit: int
    ) -> list[RetrievedMemory]:
        memories = self.vectors.retrieve_memories(
            query,
            group_id=group_id if group_id != "private" else None,
            user_id=user_id if group_id == "private" else None,
            limit=max(50, limit),
        )
        selected = [item for item in memories if item.score >= 0.35][:limit]
        logger.debug("🔍 [记忆检索] 候选 %d 条，阈值后保留 %d 条", len(memories), len(selected))
        return selected

    def clean(self) -> int:
        return self.vectors.clean_duplicate_memories()


def _format_turns(turns: list[tuple[str, str, str]]) -> str:
    return "\n".join(f"{name}: {user}\nAstcho: {bot}" for name, user, bot in turns)

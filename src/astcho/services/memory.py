from __future__ import annotations

import logging
from collections import defaultdict

from astcho.domain.models import MemoryExtraction, RetrievedMemory
from astcho.prompts import memory_extraction_prompt
from astcho.services.llm import LLMResponseError, LLMService
from astcho.storage.chroma import ChromaStore

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, vectors: ChromaStore, llm: LLMService, model: str):
        self.vectors = vectors
        self.llm = llm
        self.model = model
        self._pending: defaultdict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)

    def queue_turn(self, user_text: str, bot_text: str, *, group_id: str,
                   user_id: str, user_name: str = "用户") -> None:
        key = (group_id, user_id)
        self._pending[key].append((user_name, user_text, bot_text))
        if len(self._pending[key]) >= 5:
            turns = self._pending.pop(key)
            import asyncio
            asyncio.create_task(self.extract(_format_turns(turns), group_id=group_id,
                                             user_id=user_id, user_name=user_name))

    async def flush(self) -> int:
        pending, self._pending = self._pending, defaultdict(list)
        total = 0
        for (group_id, user_id), turns in pending.items():
            total += await self.extract(_format_turns(turns), group_id=group_id,
                                        user_id=user_id, user_name=turns[-1][0])
        return total

    async def extract(self, text: str, *, group_id: str, user_id: str,
                      user_name: str = "用户") -> int:
        if len(text.strip()) < 6:
            return 0
        try:
            result = await self.llm.json_completion(
                model=self.model,
                schema=MemoryExtraction,
                messages=[
                    *memory_extraction_prompt(text=text[:3000], user_id=user_id, user_name=user_name),
                ],
            )
        except LLMResponseError:
            return 0
        count = 0
        existing = self.vectors.retrieve_memories(
            text, group_id=group_id if group_id != "private" else None,
            user_id=user_id if group_id == "private" else None, limit=5
        )
        for atom in result.memories:
            if any(item.score > 0.94 for item in existing if item.content == atom.content):
                continue
            self.vectors.add_memory(atom.content, group_id=group_id, user_id=user_id,
                                    kind=atom.kind, importance=atom.importance)
            count += 1
        return count

    def retrieve(self, query: str, *, group_id: str, user_id: str, limit: int) -> list[RetrievedMemory]:
        memories = self.vectors.retrieve_memories(
            query,
            group_id=group_id if group_id != "private" else None,
            user_id=user_id if group_id == "private" else None,
            limit=max(50, limit),
        )
        return [item for item in memories if item.score >= 0.35][:limit]


def _format_turns(turns: list[tuple[str, str, str]]) -> str:
    return "\n".join(f"{name}: {user}\nAstcho: {bot}" for name, user, bot in turns)

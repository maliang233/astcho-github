from __future__ import annotations

import logging

from astcho.domain.models import MemoryExtraction, RetrievedMemory
from astcho.services.llm import LLMResponseError, LLMService
from astcho.storage.chroma import ChromaStore

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, vectors: ChromaStore, llm: LLMService, model: str):
        self.vectors = vectors
        self.llm = llm
        self.model = model

    async def extract(self, text: str, *, group_id: str, user_id: str) -> int:
        if len(text.strip()) < 6:
            return 0
        try:
            result = await self.llm.json_completion(
                model=self.model,
                schema=MemoryExtraction,
                messages=[
                    {"role": "system", "content": "Extract durable user facts. Return JSON: {memories:[{content,importance,kind}]}. Never infer sensitive facts."},
                    {"role": "user", "content": text[:3000]},
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
        return self.vectors.retrieve_memories(
            query,
            group_id=group_id if group_id != "private" else None,
            user_id=user_id if group_id == "private" else None,
            limit=limit,
        )


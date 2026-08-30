from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import chromadb

from astcho.domain.models import RetrievedMemory


class ChromaStore:
    """Vector storage limited to episodic memories and curated memes."""

    def __init__(
        self,
        path: Path,
        embedding_model: str,
        *,
        embedder: Callable[[str], list[float]] | None = None,
    ):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.path))
        self.memories = self.client.get_or_create_collection(
            "episodic_memory", metadata={"hnsw:space": "cosine"}
        )
        self.memes = self.client.get_or_create_collection(
            "meme_curated_library", metadata={"hnsw:space": "cosine"}
        )
        self._embedder = embedder
        self._embedding_model_name = embedding_model
        self._model: Any = None

    def embed(self, text: str) -> list[float]:
        if self._embedder is not None:
            return self._embedder(text)
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._embedding_model_name)
        return self._model.encode(text).tolist()

    def add_memory(
        self,
        content: str,
        *,
        group_id: str,
        user_id: str,
        kind: str,
        importance: int,
        status: str = "raw",
        memory_id: str | None = None,
    ) -> str:
        memory_id = memory_id or f"mem_{uuid.uuid4().hex}"
        now = time.time()
        self.memories.add(
            ids=[memory_id],
            documents=[content],
            embeddings=[self.embed(content)],
            metadatas=[
                {
                    "group_id": group_id,
                    "user_id": user_id,
                    "kind": kind,
                    "importance": importance,
                    "status": status,
                    "created_at": now,
                }
            ],
        )
        return memory_id

    def retrieve_memories(
        self,
        query: str,
        *,
        group_id: str | None,
        user_id: str | None,
        limit: int,
    ) -> list[RetrievedMemory]:
        if self.memories.count() == 0:
            return []
        if group_id is not None:
            where = {"group_id": group_id}
        elif user_id is not None:
            where = {"$and": [{"group_id": "private"}, {"user_id": user_id}]}
        else:
            raise ValueError("group_id or user_id is required for isolated retrieval")
        result = self.memories.query(
            query_embeddings=[self.embed(query)],
            n_results=min(max(limit * 3, limit), self.memories.count()),
            where=where,
        )
        if not result["ids"] or not result["ids"][0]:
            return []
        output: list[RetrievedMemory] = []
        for index, memory_id in enumerate(result["ids"][0]):
            metadata = result["metadatas"][0][index]
            similarity = 1.0 - float(result["distances"][0][index])
            importance = float(metadata.get("importance", 5)) / 10
            output.append(
                RetrievedMemory(
                    memory_id=memory_id,
                    content=result["documents"][0][index],
                    score=similarity * (1 + importance),
                    kind=str(metadata.get("kind", "short")),
                    group_id=str(metadata.get("group_id", "private")),
                    user_id=str(metadata.get("user_id", "unknown")),
                )
            )
        output.sort(key=lambda item: item.score, reverse=True)
        return output[:limit]

    def recent_memories(
        self, *, group_id: str | None, user_id: str | None, limit: int = 5
    ) -> list[RetrievedMemory]:
        if group_id is not None:
            where = {"group_id": group_id}
        elif user_id is not None:
            where = {"$and": [{"group_id": "private"}, {"user_id": user_id}]}
        else:
            raise ValueError("group_id or user_id is required")
        result = self.memories.get(where=where, include=["documents", "metadatas"])
        items = []
        for index, memory_id in enumerate(result["ids"]):
            meta = result["metadatas"][index]
            items.append((float(meta.get("created_at", 0)), memory_id, result["documents"][index], meta))
        items.sort(reverse=True)
        return [
            RetrievedMemory(
                memory_id=memory_id,
                content=content,
                score=1.0,
                kind=str(meta.get("kind", "short")),
                group_id=str(meta.get("group_id", "private")),
                user_id=str(meta.get("user_id", "unknown")),
            )
            for _, memory_id, content, meta in items[:limit]
        ]

    def memory_count(self) -> int:
        return self.memories.count()

    def delete_memories(self, *, group_id: str, user_id: str | None = None) -> None:
        where: dict[str, Any]
        if user_id is None:
            where = {"group_id": group_id}
        else:
            where = {"$and": [{"group_id": group_id}, {"user_id": user_id}]}
        self.memories.delete(where=where)

    def upsert_meme(self, file_id: str, description: str, metadata: dict[str, str]) -> None:
        self.memes.upsert(
            ids=[file_id],
            documents=[description],
            embeddings=[self.embed(description)],
            metadatas=[metadata],
        )

    def query_memes(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if self.memes.count() == 0:
            return []
        result = self.memes.query(
            query_embeddings=[self.embed(query)], n_results=min(limit, self.memes.count())
        )
        return [
            {
                "file_id": file_id,
                "description": result["documents"][0][index],
                "metadata": result["metadatas"][0][index],
                "score": 1.0 - float(result["distances"][0][index]),
            }
            for index, file_id in enumerate(result["ids"][0])
        ]

    def delete_meme(self, file_id: str) -> None:
        self.memes.delete(ids=[file_id])

    def meme_count(self) -> int:
        return self.memes.count()

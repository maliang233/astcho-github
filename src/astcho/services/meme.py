from __future__ import annotations

from pathlib import Path

from astcho.storage.chroma import ChromaStore
from astcho.storage.sqlite import SQLiteStore
from astcho.domain.models import MemeSelection
from astcho.prompts import meme_selection_prompt
from astcho.services.llm import LLMResponseError, LLMService


class MemeCurator:
    def __init__(self, sqlite: SQLiteStore, vectors: ChromaStore, limit: int,
                 llm: LLMService | None = None, model: str = ""):
        self.sqlite, self.vectors, self.limit = sqlite, vectors, limit
        self.llm, self.model = llm, model

    def learn(self, *, file_id: str, url: str, description: str,
              tags: list[str], inclination: str) -> bool:
        record = {"file_id": file_id, "url": url, "description": description,
                  "tags": tags, "inclination": inclination}
        self.sqlite.upsert_meme(record)
        try:
            self.vectors.upsert_meme(file_id, description, {
                "inclination": inclination, "tags": ",".join(tags)
            })
        except Exception:
            self.sqlite.delete_meme(file_id)
            raise
        self.enforce_limit()
        return True

    def search(self, query: str, limit: int = 6) -> list[dict]:
        output = []
        for candidate in self.vectors.query_memes(query, limit):
            record = self.sqlite.get_meme(candidate["file_id"])
            if record:
                record["score"] = candidate["score"]
                output.append(record)
        return output

    async def select(self, reply_text: str, mood_hint: str = "") -> dict | None:
        candidates = self.search(f"{reply_text} [情绪:{mood_hint}]", 8)
        if not candidates:
            return None
        if len(candidates) == 1 or self.llm is None:
            return candidates[0]
        try:
            selection = await self.llm.json_completion(
                model=self.model, schema=MemeSelection,
                messages=[{"role": "user", "content": meme_selection_prompt(
                    reply_text, candidates, mood_hint
                )}], temperature=0.1, max_tokens=100,
            )
        except LLMResponseError:
            return None
        index = selection.selected_index
        return candidates[index] if index is not None and index < len(candidates) else None

    def mark_used(self, file_id: str) -> None:
        self.sqlite.mark_meme_used(file_id)

    def delete(self, file_id: str) -> bool:
        record = self.sqlite.delete_meme(file_id)
        if not record:
            return False
        try:
            self.vectors.delete_meme(file_id)
        except Exception:
            self.sqlite.upsert_meme(record)
            raise
        path = record.get("local_path")
        if path:
            Path(path).unlink(missing_ok=True)
        return True

    def enforce_limit(self) -> None:
        overflow = self.sqlite.meme_count() - self.limit
        for record in self.sqlite.list_memes(least_used_first=True)[:max(0, overflow)]:
            self.delete(record["file_id"])

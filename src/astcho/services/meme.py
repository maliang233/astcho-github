from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from pathlib import Path

import httpx

from astcho.domain.models import MemeSelection, MemeTasteDecision
from astcho.logging import get_logger, preview
from astcho.prompts import meme_selection_prompt, meme_taste_prompt
from astcho.services.llm import LLMResponseError, LLMService
from astcho.storage.chroma import ChromaStore
from astcho.storage.sqlite import SQLiteStore

logger = get_logger(__name__)


class MemeCurator:
    def __init__(
        self,
        sqlite: SQLiteStore,
        vectors: ChromaStore,
        limit: int,
        llm: LLMService | None = None,
        model: str = "",
    ):
        self.sqlite, self.vectors, self.limit = sqlite, vectors, limit
        self.llm, self.model = llm, model
        self.recent: defaultdict[str, deque[str]] = defaultdict(lambda: deque(maxlen=5))
        self.last_meme_map: dict[str, str] = {}

    def learn(
        self, *, file_id: str, url: str, description: str, tags: list[str], inclination: str
    ) -> bool:
        record = {
            "file_id": file_id,
            "url": url,
            "description": description,
            "tags": tags,
            "inclination": inclination,
        }
        self.sqlite.upsert_meme(record)
        try:
            self.vectors.upsert_meme(
                file_id, description, {"inclination": inclination, "tags": ",".join(tags)}
            )
        except Exception:
            self.sqlite.delete_meme(file_id)
            raise
        self.enforce_limit()
        logger.system("✨ [策展人] 学会了: [%s] %s", inclination, preview(description, 50))
        return True

    async def learn_remote(
        self, *, url: str, description: str, tags: list[str], inclination: str
    ) -> bool:
        """Persist newly learned media locally; remote QQ URLs are short-lived."""
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        media_dir = self.sqlite.path.parent / "memes"
        media_dir.mkdir(parents=True, exist_ok=True)
        destination: Path | None = None
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                if len(response.content) > 20 * 1024 * 1024:
                    return False
                mime = response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
                extension = {
                    "image/gif": ".gif",
                    "image/png": ".png",
                    "image/webp": ".webp",
                    "image/jpeg": ".jpg",
                }.get(mime, ".img")
                destination = media_dir / f"{digest}{extension}"
                destination.write_bytes(response.content)
            record = {
                "file_id": digest,
                "url": url,
                "local_path": str(destination),
                "description": description,
                "tags": tags,
                "inclination": inclination,
            }
            self.sqlite.upsert_meme(record)
            try:
                self.vectors.upsert_meme(
                    digest, description, {"inclination": inclination, "tags": ",".join(tags)}
                )
            except Exception:
                self.sqlite.delete_meme(digest)
                destination.unlink(missing_ok=True)
                raise
            self.enforce_limit()
            return True
        except (httpx.HTTPError, OSError):
            if destination is not None:
                destination.unlink(missing_ok=True)
            return False

    async def consider_remote(
        self,
        *,
        url: str,
        description: str,
        tags: list[str],
        inclination: str,
        context: str = "",
    ) -> bool:
        if self.llm is None:
            return False
        logger.system("🤔 [策展人] 品味判定中... %s", preview(description, 40))
        try:
            decision = await self.llm.json_completion(
                model=self.model,
                schema=MemeTasteDecision,
                messages=[
                    {
                        "role": "user",
                        "content": meme_taste_prompt(description, tags, inclination, context),
                    }
                ],
                temperature=0.1,
                max_tokens=512,
                thinking=False,
            )
        except LLMResponseError as exc:
            logger.warning("品味判定异常，跳过收藏: %s", exc)
            return False
        if not decision.heart_throb:
            logger.system("❌ [策展人] 跳过 | %s", preview(decision.reason, 80))
            return False
        logger.system("✅ [策展人] 收藏 | %s", preview(decision.reason, 80))
        return await self.learn_remote(
            url=url, description=description, tags=tags, inclination=inclination
        )

    def search(self, query: str, limit: int = 6, *, session_key: str = "global") -> list[dict]:
        output = []
        for candidate in self.vectors.query_memes(query, max(limit * 2, 12)):
            if candidate["score"] < 0.35:
                continue
            record = self.sqlite.get_meme(candidate["file_id"])
            if record:
                record["score"] = candidate["score"]
                record["is_recent"] = record["file_id"] in self.recent[session_key]
                output.append(record)
        selected = output[:limit]
        logger.system("🔍 [策展人初筛] query='%s' → %d 条", preview(query, 60), len(selected))
        for candidate in selected:
            logger.debug(
                "   [%s] sim=%.3f | %s | %s",
                candidate["file_id"][:8],
                candidate["score"],
                candidate.get("inclination", ""),
                preview(candidate.get("description", ""), 50),
            )
        return selected

    async def select(
        self, reply_text: str, mood_hint: str = "", *, session_key: str = "global"
    ) -> dict | None:
        candidates = self.search(f"{reply_text} [情绪:{mood_hint}]", 8, session_key=session_key)
        if not candidates:
            logger.debug("🎨 [自动配图] 没有达到阈值的候选")
            return None
        if len(candidates) == 1 or self.llm is None:
            logger.system("🎯 [策展人终审] 单一候选，选择 %s", candidates[0]["file_id"][:8])
            return candidates[0]
        logger.system(
            "🎯 [策展人终审] reply='%s' mood=%s 候选=%d 条",
            preview(reply_text, 60),
            mood_hint,
            len(candidates),
        )
        for _ in range(2):
            try:
                selection = await self.llm.json_completion(
                    model=self.model,
                    schema=MemeSelection,
                    messages=[
                        {
                            "role": "user",
                            "content": meme_selection_prompt(reply_text, candidates, mood_hint),
                        }
                    ],
                    temperature=0.1,
                    max_tokens=100,
                    thinking=False,
                )
            except LLMResponseError:
                logger.warning("[策展人终审] 输出无效，正在重试")
                continue
            index = selection.selected_index
            logger.system("📊 [策展人终审] 结果: idx=%s", index)
            if index is not None and index < len(candidates):
                return candidates[index]
        return None

    def mark_used(self, file_id: str, *, session_key: str = "global") -> None:
        self.sqlite.mark_meme_used(file_id)
        recent = self.recent[session_key]
        if file_id in recent:
            recent.remove(file_id)
        recent.append(file_id)
        self.last_meme_map[session_key] = file_id

    def last_info(self, session_key: str) -> dict | None:
        file_id = self.last_meme_map.get(session_key)
        return self.sqlite.get_meme(file_id) if file_id else None

    def delete_last(self, session_key: str) -> bool:
        file_id = self.last_meme_map.get(session_key)
        if not file_id or not self.delete(file_id):
            return False
        self.last_meme_map.pop(session_key, None)
        recent = self.recent[session_key]
        if file_id in recent:
            recent.remove(file_id)
        return True

    def purge(self) -> int:
        records = self.sqlite.list_memes()
        for record in records:
            self.delete(record["file_id"])
        self.recent.clear()
        self.last_meme_map.clear()
        return len(records)

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
        logger.system("🗑️ [策展人] 已删除: %s...", file_id[:8])
        return True

    def enforce_limit(self) -> None:
        overflow = self.sqlite.meme_count() - self.limit
        if overflow > 0:
            logger.system("🧹 [策展人] 数量超限，淘汰 %d 张最少使用的", overflow)
        for record in self.sqlite.list_memes(least_used_first=True)[: max(0, overflow)]:
            self.delete(record["file_id"])

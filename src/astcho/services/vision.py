from __future__ import annotations

import base64
import hashlib

import httpx

from astcho.config import Settings
from astcho.domain.models import VisionResult
from astcho.logging import get_logger, preview
from astcho.prompts import vision_prompt
from astcho.services.llm import LLMResponseError, LLMService
from astcho.storage.sqlite import SQLiteStore

logger = get_logger(__name__)


class VisionService:
    def __init__(self, settings: Settings, llm: LLMService, store: SQLiteStore):
        self.settings, self.llm, self.store = settings, llm, store

    async def describe(self, url: str) -> VisionResult:
        key = hashlib.sha256(url.encode()).hexdigest()
        cached = self.store.get_vision(key)
        if cached:
            logger.debug("🖼️ [视觉缓存] 命中 %s", key[:8])
            return VisionResult.model_validate(cached)
        logger.debug("🖼️ [视觉缓存] 未命中 %s，下载图片", key[:8])
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("图片下载失败: %s", exc)
            return VisionResult(description="[图片]")
        mime = response.headers.get("content-type", "image/jpeg").split(";")[0]
        encoded = base64.b64encode(response.content).decode()
        try:
            result = await self.llm.json_completion(
                client=self.llm.vision_client,
                model=self.settings.vision_model,
                schema=VisionResult,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": vision_prompt()},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{encoded}"},
                            },
                        ],
                    }
                ],
            )
        except (LLMResponseError, ValueError, httpx.HTTPError) as exc:
            logger.warning("图片识别失败: %s", exc)
            result = VisionResult(description="无法可靠识别的图片")
        self.store.set_vision(key, result.model_dump())
        logger.debug("🖼️ [视觉缓存] 已写入 %s | %s", key[:8], preview(result.description, 80))
        return result

    async def describe_video(self, url: str, *, file_id: str = "") -> str:
        if not url:
            return "[视频]"
        key = "video:" + (file_id or hashlib.sha256(url.encode()).hexdigest())
        cached = self.store.get_vision(key)
        if cached:
            logger.debug("🎬 [视觉缓存] 视频命中 %s", key[-8:])
            return str(cached.get("description", "[视频]"))
        prompt = (
            "描述这个短视频或 GIF 的主要画面、文字、动作以及在群聊中表达的情绪或梗。控制在100字内。"
        )
        try:
            result = await self.llm.raw_completion(
                client=self.llm.vision_client,
                model=self.settings.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "video_url", "video_url": {"url": url}},
                        ],
                    }
                ],
                temperature=0.1,
                max_tokens=300,
            )
            description = result.strip()[:500] or "[视频]"
        except Exception as exc:
            logger.warning("视频识别失败: %s", exc)
            description = "[视频]"
        self.store.set_vision(key, {"description": description})
        logger.debug("🎬 [视觉] 识别完成: %s", preview(description, 100))
        return description

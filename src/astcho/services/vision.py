from __future__ import annotations

import base64
import hashlib

import httpx

from astcho.config import Settings
from astcho.domain.models import VisionResult
from astcho.services.llm import LLMResponseError, LLMService
from astcho.storage.sqlite import SQLiteStore


class VisionService:
    def __init__(self, settings: Settings, llm: LLMService, store: SQLiteStore):
        self.settings, self.llm, self.store = settings, llm, store

    async def describe(self, url: str) -> VisionResult:
        key = hashlib.sha256(url.encode()).hexdigest()
        cached = self.store.get_vision(key)
        if cached:
            return VisionResult.model_validate(cached)
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        mime = response.headers.get("content-type", "image/jpeg").split(";")[0]
        encoded = base64.b64encode(response.content).decode()
        try:
            result = await self.llm.json_completion(
                client=self.llm.vision_client, model=self.settings.vision_model,
                schema=VisionResult,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Describe this image and whether it is a reusable chat sticker. Return JSON with description,is_sticker,tags,inclination."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ]}],
            )
        except LLMResponseError:
            result = VisionResult(description="无法可靠识别的图片")
        self.store.set_vision(key, result.model_dump())
        return result


from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from astcho.config import Settings

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMResponseError(RuntimeError):
    """Raised when an LLM response cannot be safely validated."""


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.text_client = AsyncOpenAI(
            api_key=settings.llm_api_key, base_url=settings.llm_base_url
        )
        self.planner_client = AsyncOpenAI(
            api_key=settings.planner_api_key, base_url=settings.planner_base_url
        )
        self.vision_client = AsyncOpenAI(
            api_key=settings.vision_api_key, base_url=settings.vision_base_url
        )
        self.reasoning_client = AsyncOpenAI(
            api_key=settings.reasoning_api_key, base_url=settings.reasoning_base_url
        )

    async def json_completion(
        self,
        *,
        model: str,
        messages: list[dict],
        schema: type[ModelT],
        temperature: float = 0.1,
        max_tokens: int = 800,
        client: AsyncOpenAI | None = None,
    ) -> ModelT:
        active_client = client or self.text_client
        response = await active_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        try:
            return schema.model_validate_json(_extract_json(content))
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.warning("Rejected invalid %s response: %s", schema.__name__, exc)
            raise LLMResponseError(f"Invalid {schema.__name__} response") from exc

    async def text_completion(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 800,
    ) -> str:
        response = await self.text_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (response.choices[0].message.content or "").strip()

    async def raw_completion(self, *, model: str, messages: list[dict],
                             temperature: float = 0.1, max_tokens: int = 1200,
                             client: AsyncOpenAI | None = None) -> str:
        response = await (client or self.text_client).chat.completions.create(
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
        )
        return (response.choices[0].message.content or "").strip()


def _extract_json(content: str) -> str:
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return content
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object", content, 0)
    return match.group(0)

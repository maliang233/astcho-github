from __future__ import annotations

import json
import re
import time
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from astcho.config import Settings
from astcho.logging import get_logger

logger = get_logger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMResponseError(RuntimeError):
    """Raised when an LLM response cannot be safely validated."""


class LLMService:
    def __init__(self, settings: Settings, usage_callback=None):
        self.settings = settings
        self.usage_callback = usage_callback
        self.text_client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
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
        thinking: bool | None = False,
        empty_retries: int = 1,
    ) -> ModelT:
        active_client = client or self.text_client
        started = time.perf_counter()
        logger.debug(
            "🤖 [LLM] 请求 %s | model=%s | max_tokens=%d",
            schema.__name__,
            model,
            max_tokens,
        )
        request = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if thinking is not None and _supports_thinking_toggle(model):
            request["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
        content = ""
        for attempt in range(empty_retries + 1):
            response = await active_client.chat.completions.create(**request)
            self._record_usage(model, response)
            choice = response.choices[0]
            content = choice.message.content or ""
            reasoning = getattr(choice.message, "reasoning_content", "") or ""
            logger.debug(
                "✅ [LLM] %s 完成 | %.2fs | finish=%s | 输出=%d字 | reasoning=%d字",
                schema.__name__,
                time.perf_counter() - started,
                getattr(choice, "finish_reason", "unknown"),
                len(content),
                len(str(reasoning)),
            )
            if content.strip() or attempt >= empty_retries:
                break
            logger.warning(
                "[LLM] %s 返回空内容，自动重试 %d/%d",
                schema.__name__,
                attempt + 1,
                empty_retries,
            )
        try:
            return schema.model_validate_json(_extract_json(content))
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.warning("[LLM校验] 拒绝非法 %s 输出: %s", schema.__name__, exc)
            raise LLMResponseError(f"Invalid {schema.__name__} response") from exc

    async def text_completion(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 800,
        thinking: bool | None = False,
    ) -> str:
        started = time.perf_counter()
        logger.debug("🤖 [LLM] 文本请求 | model=%s | max_tokens=%d", model, max_tokens)
        request = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if thinking is not None and _supports_thinking_toggle(model):
            request["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
        response = await self.text_client.chat.completions.create(**request)
        self._record_usage(model, response)
        content = (response.choices[0].message.content or "").strip()
        logger.debug(
            "✅ [LLM] 文本完成 | %.2fs | 输出 %d 字",
            time.perf_counter() - started,
            len(content),
        )
        return content

    async def raw_completion(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1200,
        client: AsyncOpenAI | None = None,
        thinking: bool | None = False,
    ) -> str:
        started = time.perf_counter()
        logger.debug("🤖 [LLM] 原始请求 | model=%s | max_tokens=%d", model, max_tokens)
        request = dict(
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
        )
        if thinking is not None and _supports_thinking_toggle(model):
            request["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
        response = await (client or self.text_client).chat.completions.create(**request)
        self._record_usage(model, response)
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        reasoning = getattr(choice.message, "reasoning_content", "") or ""
        logger.debug(
            "✅ [LLM] 原始请求完成 | %.2fs | finish=%s | 输出=%d字 | reasoning=%d字",
            time.perf_counter() - started,
            getattr(choice, "finish_reason", "unknown"),
            len(content),
            len(str(reasoning)),
        )
        return content

    def _record_usage(self, model: str, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = int(getattr(details, "reasoning_tokens", 0) or 0)
        cost = (
            prompt * self.settings.input_price_per_million
            + completion * self.settings.output_price_per_million
        ) / 1_000_000
        logger.debug(
            "💰 [用量] %s | In:%d Out:%d%s%s",
            model,
            prompt,
            completion,
            f" Reasoning:{reasoning_tokens}" if reasoning_tokens else "",
            f" | ¥{cost:.5f}" if cost else "",
        )
        if self.usage_callback is not None:
            self.usage_callback(model, prompt, completion, cost)


def _extract_json(content: str) -> str:
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return content
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object", content, 0)
    return match.group(0)


def _supports_thinking_toggle(model: str) -> bool:
    """Only send provider-specific thinking controls to known compatible models."""
    return "deepseek" in model.lower()

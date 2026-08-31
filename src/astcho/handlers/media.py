from __future__ import annotations

import logging
from dataclasses import dataclass, field

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from astcho.prompts import forward_summary_prompt
from astcho.runtime import Runtime

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MediaContext:
    descriptions: list[str] = field(default_factory=list)
    learned_images: list[tuple[str, object]] = field(default_factory=list)


async def describe_event_media(
    runtime: Runtime, bot: Bot, event: GroupMessageEvent
) -> MediaContext:
    output = MediaContext()
    for segment in event.get_message():
        data = segment.data
        try:
            if segment.type == "image" and data.get("url"):
                result = await runtime.vision.describe(str(data["url"]))
                output.descriptions.append(result.description)
                if result.is_sticker:
                    output.learned_images.append((str(data["url"]), result))
            elif segment.type == "video":
                output.descriptions.append(
                    await runtime.vision.describe_video(
                        str(data.get("url", "")),
                        file_id=str(data.get("file") or data.get("md5") or ""),
                    )
                )
            elif segment.type == "record":
                output.descriptions.append("[语音]")
            elif segment.type == "forward":
                output.descriptions.append(
                    await describe_forward(runtime, bot, str(data.get("id", "")))
                )
        except Exception:
            logger.exception("Media segment processing failed: type=%s", segment.type)
            output.descriptions.append(f"[{_media_name(segment.type)}]")
    return output


async def describe_forward(runtime: Runtime, bot: Bot, forward_id: str) -> str:
    if not forward_id:
        return "[转发消息]"
    try:
        try:
            payload = await bot.get_forward_msg(message_id=forward_id)
        except Exception:
            payload = await bot.call_api("get_forward_msg", id=forward_id)
    except Exception as exc:
        logger.warning("Cannot fetch forwarded message %s: %s", forward_id, exc)
        return "[转发消息：内容已过期或无法访问]"
    messages = payload.get("messages") or payload.get("message") or []
    if not isinstance(messages, list):
        return "[转发消息]"
    text_count = sum(1 for item in messages for seg in _segments(item) if seg.get("type") == "text")
    media_count = sum(
        1 for item in messages for seg in _segments(item) if seg.get("type") in {"image", "video"}
    )
    if text_count > runtime.settings.forward_max_text_segments:
        return "[转发消息：太长了，星回看不完]"
    skip_visual = media_count > runtime.settings.forward_max_media_segments
    lines: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        sender = item.get("sender") or {}
        name = sender.get("nickname") or sender.get("card") or "未知"
        fragments: list[str] = []
        for segment in _segments(item):
            kind, data = segment.get("type"), segment.get("data") or {}
            if kind == "text" and data.get("text"):
                fragments.append(str(data["text"]))
            elif kind == "at":
                fragments.append("@" + str(data.get("name") or data.get("qq") or ""))
            elif kind == "image":
                if skip_visual or not data.get("url"):
                    fragments.append("[图片]")
                else:
                    result = await runtime.vision.describe(str(data["url"]))
                    fragments.append(f"[图片: {result.description}]")
            elif kind == "video":
                if skip_visual:
                    fragments.append("[视频]")
                else:
                    fragments.append(
                        await runtime.vision.describe_video(
                            str(data.get("url", "")), file_id=str(data.get("file", ""))
                        )
                    )
        if fragments:
            lines.append(f"{name}: {' '.join(fragments)}")
    source = ((messages[0].get("sender") or {}).get("nickname") if messages else None) or "未知"
    if len(lines) <= 3:
        return f"[转发自 {source}] " + " | ".join(lines)
    try:
        summary = await runtime.llm.text_completion(
            model=runtime.settings.chat_model,
            messages=[{"role": "user", "content": forward_summary_prompt(lines)}],
            temperature=0.5,
            max_tokens=80,
        )
        return f"[转发 x{len(lines)}条] {summary.strip()[:30]}"
    except Exception:
        return f"[转发 x{len(lines)}条] {source}转发的聊天记录"


def _segments(item: dict) -> list[dict]:
    segments = item.get("message", []) if isinstance(item, dict) else []
    return segments if isinstance(segments, list) else []


def _media_name(kind: str) -> str:
    return {"image": "图片", "video": "视频", "record": "语音", "forward": "转发消息"}.get(
        kind, "媒体"
    )

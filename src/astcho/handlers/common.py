from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment


def text_of(event: MessageEvent) -> str:
    return event.get_plaintext().strip()


def image_urls(event: MessageEvent) -> list[str]:
    return [str(segment.data.get("url", "")) for segment in event.get_message()
            if segment.type == "image" and segment.data.get("url")]


def reply_message(text: str, image_url: str | None = None) -> Message:
    message = Message(text)
    if image_url:
        message += MessageSegment.image(image_url)
    return message

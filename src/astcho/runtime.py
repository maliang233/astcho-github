from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

from astcho.config import Settings
from astcho.services.attention import AttentionService
from astcho.services.chat import ChatService
from astcho.services.emotion import EmotionService
from astcho.services.expression import ExpressionService
from astcho.services.llm import LLMService
from astcho.services.meme import MemeCurator
from astcho.services.memory import MemoryService
from astcho.services.schedule import ScheduleService
from astcho.services.vision import VisionService
from astcho.storage.chroma import ChromaStore
from astcho.storage.sqlite import SQLiteStore

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    def create(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.error(
                "Background task failed", exc_info=(type(error), error, error.__traceback__)
            )

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


@dataclass
class Runtime:
    settings: Settings
    sqlite: SQLiteStore
    vectors: ChromaStore
    llm: LLMService
    chat: ChatService
    memory: MemoryService
    vision: VisionService
    memes: MemeCurator
    schedule: ScheduleService
    emotion: EmotionService
    expressions: ExpressionService
    tasks: TaskManager = field(default_factory=TaskManager)
    locks: defaultdict[str, asyncio.Lock] = field(default_factory=lambda: defaultdict(asyncio.Lock))
    histories: defaultdict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    attention: dict[str, AttentionService] = field(default_factory=dict)
    pending_group_messages: defaultdict[str, list] = field(
        default_factory=lambda: defaultdict(list)
    )
    aggregation_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    private_histories: defaultdict[str, deque] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=50))
    )
    custom_reply_tracker: defaultdict[str, dict] = field(default_factory=lambda: defaultdict(dict))
    custom_reply_handled: defaultdict[str, dict] = field(default_factory=lambda: defaultdict(dict))

    @classmethod
    def build(cls, settings: Settings) -> Runtime:
        settings.prepare_directories()
        sqlite = SQLiteStore(settings.data_dir / "astcho.sqlite3")
        vectors = ChromaStore(settings.data_dir / "chroma", settings.embedding_model)
        llm = LLMService(settings, sqlite.record_usage)
        return cls(
            settings=settings,
            sqlite=sqlite,
            vectors=vectors,
            llm=llm,
            chat=ChatService(settings, llm),
            memory=MemoryService(vectors, llm, settings.chat_model),
            vision=VisionService(settings, llm, sqlite),
            memes=MemeCurator(sqlite, vectors, settings.meme_limit, llm, settings.chat_model),
            schedule=ScheduleService(settings.schedule_path),
            emotion=EmotionService(sqlite, settings.admins),
            expressions=ExpressionService(
                sqlite,
                llm,
                settings.chat_model,
                interval=settings.expression_learn_interval,
                minimum_messages=settings.expression_learn_min_messages,
            ),
        )

    def add_history(self, key: str, role: str, content: str) -> None:
        limit = self.settings.short_history_limit
        if limit == 0:
            self.histories.pop(key, None)
            return
        history = self.histories[key]
        history.append({"role": role, "content": content})
        while len(history) > limit:
            history.popleft()

    def history(self, key: str) -> list[dict]:
        if self.settings.short_history_limit == 0:
            return []
        return list(self.histories[key])

    def is_admin(self, user_id: str) -> bool:
        return str(user_id) in self.settings.admins

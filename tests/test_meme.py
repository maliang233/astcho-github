import asyncio

from astcho.domain.models import MemeTasteDecision
from astcho.services.meme import MemeCurator
from astcho.storage.chroma import ChromaStore
from astcho.storage.sqlite import SQLiteStore


def test_curator_enforces_limit(tmp_path):
    sqlite = SQLiteStore(tmp_path / "test.sqlite3")
    vectors = ChromaStore(tmp_path / "chroma", "unused", embedder=lambda _: [1.0, 0.0])
    curator = MemeCurator(sqlite, vectors, limit=1)
    curator.learn(
        file_id="one",
        url="https://example.invalid/1",
        description="one",
        tags=[],
        inclination="neutral",
    )
    curator.learn(
        file_id="two",
        url="https://example.invalid/2",
        description="two",
        tags=[],
        inclination="neutral",
    )
    assert sqlite.meme_count() == vectors.meme_count() == 1


def test_curator_taste_gate_rejects_ordinary_image(tmp_path):
    calls = []

    class LLM:
        async def json_completion(self, **kwargs):
            calls.append(kwargs)
            return MemeTasteDecision(heart_throb=False, reason="普通截图")

    sqlite = SQLiteStore(tmp_path / "test.sqlite3")
    vectors = ChromaStore(tmp_path / "chroma", "unused", embedder=lambda _: [1.0, 0.0])
    curator = MemeCurator(sqlite, vectors, limit=10, llm=LLM(), model="test")
    accepted = asyncio.run(
        curator.consider_remote(
            url="https://example.invalid/image",
            description="普通风景照",
            tags=["风景"],
            inclination="neutral",
        )
    )
    assert accepted is False
    assert sqlite.meme_count() == 0
    assert calls[0]["max_tokens"] == 512
    assert calls[0]["thinking"] is False

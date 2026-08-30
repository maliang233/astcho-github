from astcho.services.meme import MemeCurator
from astcho.storage.chroma import ChromaStore
from astcho.storage.sqlite import SQLiteStore


def test_curator_enforces_limit(tmp_path):
    sqlite = SQLiteStore(tmp_path / "test.sqlite3")
    vectors = ChromaStore(tmp_path / "chroma", "unused", embedder=lambda _: [1.0, 0.0])
    curator = MemeCurator(sqlite, vectors, limit=1)
    curator.learn(file_id="one", url="https://example.invalid/1", description="one",
                  tags=[], inclination="neutral")
    curator.learn(file_id="two", url="https://example.invalid/2", description="two",
                  tags=[], inclination="neutral")
    assert sqlite.meme_count() == vectors.meme_count() == 1


from astcho.storage.chroma import ChromaStore


def embed(text: str) -> list[float]:
    return [float("private" in text), float("group" in text), 1.0]


def test_private_memory_isolation(tmp_path):
    store = ChromaStore(tmp_path / "chroma", "unused", embedder=embed)
    store.add_memory("private fact", group_id="private", user_id="u1", kind="long", importance=8)
    store.add_memory("private other", group_id="private", user_id="u2", kind="long", importance=8)
    result = store.retrieve_memories("private", group_id=None, user_id="u1", limit=10)
    assert {item.user_id for item in result} == {"u1"}


def test_group_memory_isolation(tmp_path):
    store = ChromaStore(tmp_path / "chroma", "unused", embedder=embed)
    store.add_memory("group one", group_id="g1", user_id="u", kind="short", importance=5)
    store.add_memory("group two", group_id="g2", user_id="u", kind="short", importance=5)
    result = store.retrieve_memories("group", group_id="g1", user_id=None, limit=10)
    assert {item.group_id for item in result} == {"g1"}


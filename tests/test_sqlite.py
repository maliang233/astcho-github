from astcho.storage.sqlite import SQLiteStore


def test_user_isolated_by_group_and_user(tmp_path):
    store = SQLiteStore(tmp_path / "test.sqlite3")
    store.touch_user("g1", "u1", "one")
    store.touch_user("g2", "u1", "two")
    assert store.get_user("g1", "u1")["nickname"] == "one"
    assert store.get_user("g2", "u1")["nickname"] == "two"


def test_meme_lifecycle(tmp_path):
    store = SQLiteStore(tmp_path / "test.sqlite3")
    store.upsert_meme({"file_id": "m1", "url": "https://example.invalid/1.jpg",
                       "description": "smile", "tags": ["happy"]})
    store.mark_meme_used("m1")
    assert store.get_meme("m1")["use_count"] == 1
    assert store.delete_meme("m1")["file_id"] == "m1"


from collections import defaultdict, deque
from types import SimpleNamespace

from astcho.runtime import Runtime


def test_zero_history_means_no_history():
    runtime = object.__new__(Runtime)
    runtime.settings = SimpleNamespace(short_history_limit=0)
    runtime.histories = defaultdict(deque)
    runtime.add_history("private:1", "user", "secret")
    assert runtime.history("private:1") == []


def test_history_has_hard_limit():
    runtime = object.__new__(Runtime)
    runtime.settings = SimpleNamespace(short_history_limit=2)
    runtime.histories = defaultdict(deque)
    for value in "abc":
        runtime.add_history("x", "user", value)
    assert [item["content"] for item in runtime.history("x")] == ["b", "c"]


def test_private_session_keeps_independent_fifty_message_buffer():
    runtime = object.__new__(Runtime)
    factory = Runtime.__dataclass_fields__["private_histories"].default_factory
    runtime.private_histories = factory()
    for index in range(55):
        runtime.private_histories["private:1"].append({"role": "user", "content": str(index)})
    assert len(runtime.private_histories["private:1"]) == 50
    assert runtime.private_histories["private:1"][0]["content"] == "5"

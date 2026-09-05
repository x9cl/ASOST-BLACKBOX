import json
from asost.memory import JSONMemory


def test_missing_corrupt_and_round_trip(tmp_path):
    path = tmp_path / "state.json"
    store = JSONMemory(path)
    assert store.read("missing", 42) == 42
    path.write_text("not-json", encoding="utf-8")
    assert store.read("missing") is None
    store.write("page", {"status": "running"})
    assert store.read("page") == {"status": "running"}
    assert not path.with_suffix(".json.tmp").exists()
    assert json.loads(path.read_text())["page"]["status"] == "running"

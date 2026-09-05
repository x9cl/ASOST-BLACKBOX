import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

from asost.memory import JSONMemory
from asost.providers import FakeCredentialPool, FakeProvider


@pytest.fixture
def synthetic_book():
    return Path(__file__).parent / "fixtures" / "synthetic_book" / "manifest.json"


@pytest.fixture
def fake_pool():
    return FakeCredentialPool(["credential-secret-A", "credential-secret-B"])


@pytest.fixture
def memory(tmp_path):
    return JSONMemory(tmp_path / "memory.json")


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network access is forbidden in ASOST tests")
    monkeypatch.setattr("socket.socket.connect", denied)

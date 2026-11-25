import litellm
import pytest
from fastapi.testclient import TestClient

from app.main import app

KEY_A, KEY_B = "fake-key-a", "fake-key-b"


class FakeLLM:
    """Replaces litellm.completion. It still calls the REAL litellm.completion with
    mock_response, so litellm's real cache code runs, but nothing touches the network."""

    def __init__(self, real):
        self.real = real
        self.calls = []  # one entry per chat call
        self.fail = {}  # api_key -> exception to raise

    def __call__(self, **kw):
        if "mock_response" in kw:  # startup warm-up, already offline
            return self.real(**kw)
        self.calls.append({"api_key": kw["api_key"], "messages": kw["messages"], "cache": kw.get("cache")})
        if kw["api_key"] in self.fail:
            raise self.fail[kw["api_key"]]
        n = len(self.calls)
        return self.real(**kw, mock_response=f"reply {n} to: {kw['messages'][-1]['content']}")


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    fake = FakeLLM(litellm.completion)
    monkeypatch.setattr(litellm, "completion", fake)  # autouse: tests can never hit the real API
    return fake


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "test.db"  # parent dir does not exist yet
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
    monkeypatch.setenv("LLM_API_KEYS", f"{KEY_A},{KEY_B}")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    monkeypatch.setenv("DEFAULT_SYSTEM_PROMPT", "DEFAULT PROMPT")
    return path


@pytest.fixture
def client(db_path):
    with TestClient(app) as c:  # context manager runs startup (lifespan): fresh cache each test
        yield c

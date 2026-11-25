import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


@pytest.mark.parametrize("keys", ["", " , ,", "only-one-key", "only-one-key,"])
def test_health_503_with_fewer_than_2_keys(db_path, monkeypatch, keys):
    monkeypatch.setenv("LLM_API_KEYS", keys)
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert set(body) == {"detail"}
    assert "required keys configured" in body["detail"]
    assert "only-one-key" not in r.text  # never expose key values


@pytest.mark.parametrize("keys,count", [("fake-a,fake-b", 2), ("fake-a,fake-b,fake-c", 3), (" fake-a , fake-b ,", 2)])
def test_health_200_with_2_or_more_keys(db_path, monkeypatch, keys, count):
    monkeypatch.setenv("LLM_API_KEYS", keys)
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": count, "cache_enabled": True}
    assert "fake-" not in r.text


def test_health_503_when_database_unreachable(client, monkeypatch):
    def broken(path):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(db, "check_db", broken)
    r = client.get("/health")  # 2 keys are configured, but the DB is not reachable
    assert r.status_code == 503
    assert r.json() == {"detail": "database unreachable"}


@pytest.mark.parametrize(
    "body",
    [
        {"session_id": "s1"},  # missing message
        {"session_id": "s1", "message": ""},  # empty
        {"session_id": "s1", "message": "   \n\t "},  # whitespace-only
        {"session_id": "s1", "message": "x" * 4001},  # too long
        {"message": "hi"},  # missing session_id
        {"session_id": "", "message": "hi"},  # empty session_id
        {"session_id": "s" * 129, "message": "hi"},  # session_id too long
    ],
)
def test_chat_422(client, body):
    r = client.post("/chat", json=body)
    assert r.status_code == 422
    assert "detail" in r.json()
    assert client.get("/sessions/s1/messages").status_code == 404  # nothing stored


def test_chat_malformed_json_422(client):
    r = client.post("/chat", content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert "detail" in r.json()


def test_message_boundaries_pass_validation(client):
    assert client.post("/chat", json={"session_id": "s", "message": "x" * 4000}).status_code == 200
    assert client.post("/chat", json={"session_id": "s" * 128, "message": " x "}).status_code == 200


def test_422_never_calls_llm_or_saves(client, fake_llm):
    client.post("/chat", json={"session_id": "s1", "message": "   "})
    assert fake_llm.calls == []


def test_unknown_session_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


def test_unexpected_error_is_json_500_without_traceback(client, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("internal detail with fake-key-a inside")

    monkeypatch.setattr(db, "save_exchange", boom)
    r = client.post("/chat", json={"session_id": "s1", "message": "hi"})  # default client: would raise if re-raised
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error"}
    assert "Traceback" not in r.text and "fake-key" not in r.text and "RuntimeError" not in r.text
    assert "fake-key" not in caplog.text and "Traceback" not in caplog.text  # logs: type name only


def test_500_still_has_cors_headers(client, monkeypatch):
    monkeypatch.setattr(db, "save_exchange", lambda *a, **k: 1 / 0)
    r = client.post("/chat", json={"session_id": "s1", "message": "hi"}, headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_wrong_method_is_json_405(client):
    r = client.get("/chat")
    assert r.status_code == 405
    assert "detail" in r.json() and "text/html" not in r.headers["content-type"]


def test_unknown_route_is_json(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_db_created_on_startup(db_path, client):
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert {"messages", "sessions", "idx_messages_session_id"} <= names


def test_history_oldest_first_without_system_prompt(client, db_path):
    meta = {"resolution_source": "LIVE_INFERENCE", "input_tokens": 5, "output_tokens": 2}
    db.save_exchange(str(db_path), "s1", "be brief", "q1", "a1", meta)
    db.save_exchange(str(db_path), "s1", None, "q2", "a2", meta)
    r = client.get("/sessions/s1/messages")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["content"] for m in msgs] == ["q1", "a1", "q2", "a2"]
    assert "metadata" not in msgs[0]
    assert msgs[1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert msgs[1]["metadata"]["input_tokens"] == 5
    assert all(m["role"] in ("user", "assistant") for m in msgs)


def test_cors_allows_simulate_failure_header(client):
    r = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Simulate-Failure",
        },
    )
    assert r.status_code == 200
    assert "x-simulate-failure" in r.headers["access-control-allow-headers"].lower()

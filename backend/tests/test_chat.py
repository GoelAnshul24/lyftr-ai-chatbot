import litellm
from fastapi.testclient import TestClient

from app.main import app

from .conftest import KEY_A, KEY_B


def chat(client, session_id, message, headers=None, **extra):
    return client.post("/chat", json={"session_id": session_id, "message": message, **extra}, headers=headers or {})


def history(client, session_id):
    return client.get(f"/sessions/{session_id}/messages")


# ---------- failover ----------

def test_live_response_shape(client):
    r = chat(client, "s1", "hello")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s1" and body["reply"]
    m = body["metadata"]
    assert m["resolution_source"] == "LIVE_INFERENCE"
    assert m["key_id"] == "key_1" and m["fallback_attempts"] == 0
    assert isinstance(m["latency_ms"], int) and isinstance(m["input_tokens"], int) and isinstance(m["output_tokens"], int)
    assert m["model"]
    assert "fake-key" not in r.text


def test_failover_key_1_429_uses_key_2(client, fake_llm):
    r = chat(client, "s1", "hello", {"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1
    assert m["resolution_source"] == "LIVE_INFERENCE"
    assert r.json()["reply"].startswith("reply ")  # a real answer, not an error wrapped in 200
    assert [c["api_key"] for c in fake_llm.calls] == [KEY_B]  # key_1 failed before any real call
    assert len(history(client, "s1").json()["messages"]) == 2


def test_failover_key_1_500_uses_key_2(client):
    r = chat(client, "s1", "hello", {"X-Simulate-Failure": "key_1=500"})
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"


def test_failover_bad_gateway_and_unavailable(client):
    for status in ("502", "503"):
        r = chat(client, f"s{status}", "hello", {"X-Simulate-Failure": f"key_1={status}"})
        assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"


def test_all_keys_fail_503_and_nothing_saved(client, fake_llm):
    r = chat(client, "s1", "hello", {"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert history(client, "s1").status_code == 404  # nothing added to history
    assert fake_llm.calls == []


def test_specific_key_overrides_star(client):
    r = chat(client, "s1", "hello", {"X-Simulate-Failure": "*=429,key_2=500"})
    assert r.status_code == 503


def test_real_provider_errors_fail_over(client, fake_llm):
    fake_llm.fail[KEY_A] = litellm.RateLimitError(message="quota", llm_provider="gemini", model="m")
    r = chat(client, "s1", "hello")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2" and r.json()["metadata"]["fallback_attempts"] == 1


def test_timeout_and_connection_errors_fail_over(client, fake_llm):
    fake_llm.fail[KEY_A] = litellm.Timeout(message="slow", model="m", llm_provider="gemini")
    assert chat(client, "s1", "hello").json()["metadata"]["key_id"] == "key_2"
    fake_llm.fail[KEY_A] = litellm.APIConnectionError(message="down", llm_provider="gemini", model="m")
    assert chat(client, "s2", "other").json()["metadata"]["key_id"] == "key_2"


def test_real_all_providers_failing_is_503_not_saved(client, fake_llm):
    err = litellm.ServiceUnavailableError(message="x", llm_provider="gemini", model="m")
    fake_llm.fail[KEY_A] = fake_llm.fail[KEY_B] = err
    r = chat(client, "s1", "hello")
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert history(client, "s1").status_code == 404


def test_header_ignored_when_simulation_disabled(db_path, monkeypatch):
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")
    with TestClient(app) as c:
        r = chat(c, "s1", "hello", {"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_1" and r.json()["metadata"]["fallback_attempts"] == 0


def test_invalid_header_values_are_ignored(client):
    for i, bad in enumerate(["garbage", "key_1=999", "=429", "key_1=", ",,,", "key_1=abc", "key_1=4 29"]):
        r = chat(client, f"s{i}", f"hello {i}", {"X-Simulate-Failure": bad})
        assert r.status_code == 200, bad
        assert r.json()["metadata"]["key_id"] == "key_1", bad


def test_parse_failure_header():
    from app.llm import parse_failure_header as p

    assert p("key_1=429,key_2=500") == {"key_1": 429, "key_2": 500}
    assert p("*=429") == {"*": 429}
    assert p(" key_1 = 502 , bogus, key_2=404") == {"key_1": 502}
    assert p("key_1=4²9") == {}  # non-ASCII digits must not crash int()
    assert p(None) == {} and p("") == {}


# ---------- LiteLLM Router (real-key failover) ----------

def test_failover_uses_litellm_router(client):
    from litellm import Router

    router = app.state.router
    assert isinstance(router, Router)
    assert sorted(router.registry().names()) == ["key_1", "key_2"]  # one model group per key


def test_three_keys_chain_in_order_and_count_attempts(db_path, monkeypatch, fake_llm):
    monkeypatch.setenv("LLM_API_KEYS", f"{KEY_A},{KEY_B},fake-key-c")
    err = lambda: litellm.RateLimitError(message="quota", llm_provider="gemini", model="m")
    fake_llm.fail[KEY_A], fake_llm.fail[KEY_B] = err(), err()
    with TestClient(app) as c:
        r = chat(c, "s1", "hello")
    m = r.json()["metadata"]
    assert r.status_code == 200 and m["key_id"] == "key_3" and m["fallback_attempts"] == 2
    assert [x["api_key"] for x in fake_llm.calls] == [KEY_A, KEY_B, "fake-key-c"]  # strictly in order


def test_simulated_and_real_failures_combine(db_path, monkeypatch, fake_llm):
    monkeypatch.setenv("LLM_API_KEYS", f"{KEY_A},{KEY_B},fake-key-c")
    fake_llm.fail[KEY_B] = litellm.InternalServerError(message="x", llm_provider="gemini", model="m")
    with TestClient(app) as c:
        r = chat(c, "s1", "hello", {"X-Simulate-Failure": "key_1=429"})  # key_1 simulated, key_2 really fails
    m = r.json()["metadata"]
    assert r.status_code == 200 and m["key_id"] == "key_3" and m["fallback_attempts"] == 2
    assert [x["api_key"] for x in fake_llm.calls] == [KEY_B, "fake-key-c"]  # key_1 never reached the provider


def test_a_failing_key_is_not_benched_next_request_starts_at_key_1(client, fake_llm):
    fake_llm.fail[KEY_A] = litellm.RateLimitError(message="quota", llm_provider="gemini", model="m")
    assert chat(client, "s1", "first").json()["metadata"]["key_id"] == "key_2"
    fake_llm.fail.clear()  # key_1 recovers
    r = chat(client, "s2", "second")
    assert r.json()["metadata"]["key_id"] == "key_1" and r.json()["metadata"]["fallback_attempts"] == 0


def test_cache_is_shared_across_key_groups(client, fake_llm):
    fake_llm.fail[KEY_A] = litellm.RateLimitError(message="quota", llm_provider="gemini", model="m")
    a = chat(client, "s1", "shared question").json()  # answered by key_2
    fake_llm.fail.clear()
    b = chat(client, "s2", "shared question").json()  # key_1 group asked: must be a cache hit
    assert a["metadata"]["key_id"] == "key_2"
    assert b["metadata"]["resolution_source"] == "LLM_CACHE" and b["reply"] == a["reply"]


def test_provider_error_text_with_a_key_never_reaches_logs(client, fake_llm, caplog, capfd):
    leaky = f"quota exceeded for key {KEY_A}"
    fake_llm.fail[KEY_A] = fake_llm.fail[KEY_B] = litellm.RateLimitError(message=leaky, llm_provider="gemini", model="m")
    with caplog.at_level("DEBUG"):
        r = chat(client, "s1", "hello")
    assert r.status_code == 503 and KEY_A not in r.text
    out = capfd.readouterr()
    assert KEY_A not in caplog.text and KEY_A not in out.out and KEY_A not in out.err


# ---------- cache ----------

def test_same_first_message_in_new_session_hits_cache(client):
    a = chat(client, "s1", "What is the capital of France?").json()
    b = chat(client, "s2", "What is the capital of France?").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["reply"] == a["reply"]
    assert b["metadata"]["key_id"] is None and b["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
    assert b["metadata"]["output_tokens"] == a["metadata"]["output_tokens"]
    assert isinstance(b["metadata"]["latency_ms"], int)
    # a cache hit is stored in history like any other reply
    assert history(client, "s2").json()["messages"][1]["metadata"]["resolution_source"] == "LLM_CACHE"


def test_cache_entries_outlive_litellm_default_ten_minutes(client):
    chat(client, "s1", "ttl check")
    store = litellm.cache.cache  # litellm's InMemoryCache
    remaining = max(store.ttl_dict.values()) - store._clock()
    assert remaining > 3600  # without our setting this would be ~600 s


def test_different_message_is_never_cached(client):
    chat(client, "s1", "hello")
    r = chat(client, "s2", "hello!")
    assert r.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_different_system_prompt_is_not_a_cache_hit(client):
    chat(client, "s1", "hello", system_prompt="Be a pirate")
    r = chat(client, "s2", "hello", system_prompt="Be a poet")
    assert r.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_does_not_depend_on_which_key_answered(client):
    a = chat(client, "s1", "hello", {"X-Simulate-Failure": "key_1=429"}).json()  # answered by key_2
    assert a["metadata"]["key_id"] == "key_2"
    b = chat(client, "s2", "hello").json()  # key_1 would be used live; cache must still hit
    assert b["metadata"]["resolution_source"] == "LLM_CACHE" and b["reply"] == a["reply"]


def test_failure_header_bypasses_cache_read(client):
    chat(client, "s1", "hello")  # now cached
    r = chat(client, "s2", "hello", {"X-Simulate-Failure": "key_1=429"}).json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r["metadata"]["key_id"] == "key_2" and r["metadata"]["fallback_attempts"] == 1


# ---------- multi-turn, sessions, tokens ----------

def test_history_is_passed_to_the_model(client, fake_llm):
    chat(client, "s1", "my name is Ada")
    chat(client, "s1", "what is my name?")
    sent = fake_llm.calls[1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[0]["content"] == "DEFAULT PROMPT"
    assert sent[1]["content"] == "my name is Ada"
    assert sent[2]["content"].startswith("reply 1")
    assert sent[3]["content"] == "what is my name?"
    msgs = history(client, "s1").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert all(m["role"] != "system" for m in msgs)


def test_sessions_are_isolated(client, fake_llm):
    chat(client, "s1", "secret apple")
    chat(client, "s2", "banana")
    assert [m["content"] for m in fake_llm.calls[1]["messages"]] == ["DEFAULT PROMPT", "banana"]
    assert [m["content"] for m in history(client, "s1").json()["messages"]][0] == "secret apple"
    assert len(history(client, "s2").json()["messages"]) == 2


def test_tokens_are_per_request_not_cumulative(client):
    first = chat(client, "s1", "hello").json()["metadata"]
    second = chat(client, "s1", "and again").json()["metadata"]
    # the model reports the same usage for each call; a running total would double it
    assert second["input_tokens"] == first["input_tokens"]
    assert second["output_tokens"] == first["output_tokens"]
    msgs = history(client, "s1").json()["messages"]
    assert msgs[1]["metadata"]["input_tokens"] == first["input_tokens"]
    assert msgs[3]["metadata"]["output_tokens"] == second["output_tokens"]


def test_system_prompt_override_is_stored_and_reused(client, fake_llm):
    chat(client, "s1", "hi", system_prompt="Be a pirate")
    chat(client, "s1", "again")  # no prompt sent: reuse stored one
    chat(client, "s2", "hi there")  # new session: default
    assert fake_llm.calls[0]["messages"][0]["content"] == "Be a pirate"
    assert fake_llm.calls[1]["messages"][0]["content"] == "Be a pirate"
    assert fake_llm.calls[2]["messages"][0]["content"] == "DEFAULT PROMPT"


def test_message_is_stripped_before_use(client, fake_llm):
    chat(client, "s1", "   padded   ")
    assert fake_llm.calls[0]["messages"][-1]["content"] == "padded"
    assert history(client, "s1").json()["messages"][0]["content"] == "padded"

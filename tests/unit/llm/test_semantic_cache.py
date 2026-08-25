"""Tests for the LLM semantic cache.

Acceptance target: a repeated (identical) request must be served from cache in
well under 100 ms. The exact tier (in-memory) retrieves in ~1 ms; the semantic
tier reuses a prior response for rephrasings.
"""

import os
import time

import pytest
from pydantic import BaseModel

from src.audiobook_studio.llm.client import LLMCallResult
from src.audiobook_studio.llm.direct_client import (
    DirectProviderClient,
    DirectProviderClientConfig,
    DirectProviderType,
)
from src.audiobook_studio.llm.semantic_cache import (
    SemanticCache,
    cached_llm_lookup,
    cached_llm_store,
    get_semantic_cache,
    normalize_prompt,
    reset_semantic_cache,
)


class _M(BaseModel):
    value: str


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_semantic_cache()
    yield
    reset_semantic_cache()


def _make_result(value: str = "x", latency_ms: int = 1) -> LLMCallResult:
    return LLMCallResult(
        output=_M(value=value),
        model="m",
        tokens_in=1,
        tokens_out=1,
        cost_usd=0.0,
        latency_ms=latency_ms,
        schema_compliance=True,
    )


def _redis_available() -> bool:
    try:
        import redis

        return bool(redis.Redis(decode_responses=True).ping())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# normalize_prompt
# ---------------------------------------------------------------------------


def test_normalize_prompt_collapses_whitespace_and_case():
    assert normalize_prompt("  Hello   WORLD  ") == "hello world"
    assert normalize_prompt([{"role": "user", "content": "Hi There"}]) == "hi there"
    assert normalize_prompt([{"content": "A"}, {"content": "B"}]) == "a b"


# ---------------------------------------------------------------------------
# disabled / no-op behavior
# ---------------------------------------------------------------------------


def test_disabled_when_env_unset():
    # Ensure the singleton resolves to None when the env flag is off.
    assert os.environ.get("LLM_SEMANTIC_CACHE_ENABLED") != "true"
    assert get_semantic_cache() is None
    # Helpers are safe no-ops with a None cache.
    assert cached_llm_lookup(None, prompt="x", response_model=_M, model="m", temperature=0.1, max_tokens=10) is None
    cached_llm_store(None, prompt="x", result=_make_result(), response_model=_M, model="m", temperature=0.1, max_tokens=10)


def test_disabled_explicit_false():
    os.environ["LLM_SEMANTIC_CACHE_ENABLED"] = "false"
    reset_semantic_cache()
    assert get_semantic_cache() is None


# ---------------------------------------------------------------------------
# exact tier
# ---------------------------------------------------------------------------


def test_exact_hit_returns_cached_result():
    cache = SemanticCache(backend="memory")
    cache.put("same prompt", _make_result("first"), response_model=_M, model="m", temperature=0.1, max_tokens=10)
    hit = cache.get("same prompt", response_model=_M, model="m", temperature=0.1, max_tokens=10)
    assert hit is not None
    assert isinstance(hit.output, _M)
    assert hit.output.value == "first"
    assert cache.exact_hits == 1
    assert cache.semantic_hits == 0


def test_different_namespace_is_a_miss():
    cache = SemanticCache(backend="memory")
    cache.put("prompt", _make_result("a"), response_model=_M, model="m", temperature=0.1, max_tokens=10)
    # Different model -> miss
    assert cache.get("prompt", response_model=_M, model="other", temperature=0.1, max_tokens=10) is None
    # Different temperature -> miss
    assert cache.get("prompt", response_model=_M, model="m", temperature=0.5, max_tokens=10) is None
    # Different response_model name -> miss
    class _Other(BaseModel):
        value: str

    assert cache.get("prompt", response_model=_Other, model="m", temperature=0.1, max_tokens=10) is None
    assert cache.misses >= 3


# ---------------------------------------------------------------------------
# semantic tier
# ---------------------------------------------------------------------------


def test_semantic_hit_for_rephrasing():
    cache = SemanticCache(backend="memory", similarity_threshold=0.95)
    cache.put("the quick brown fox jumps", _make_result("a"), response_model=_M, model="m", temperature=0.1, max_tokens=10)
    # Reordered / rephrased but same word set -> semantic hit.
    hit = cache.get("brown fox quick the jumps", response_model=_M, model="m", temperature=0.1, max_tokens=10)
    assert hit is not None
    assert cache.semantic_hits == 1


def test_semantic_miss_for_unrelated_text():
    cache = SemanticCache(backend="memory", similarity_threshold=0.95)
    cache.put("the quick brown fox jumps", _make_result("a"), response_model=_M, model="m", temperature=0.1, max_tokens=10)
    assert cache.get("completely different sentence about music", response_model=_M, model="m", temperature=0.1, max_tokens=10) is None
    assert cache.semantic_hits == 0


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------


def test_ttl_expiry():
    cache = SemanticCache(backend="memory", ttl=1)
    cache.put("p", _make_result("a"), response_model=_M, model="m", temperature=0.1, max_tokens=10)
    assert cache.get("p", response_model=_M, model="m", temperature=0.1, max_tokens=10) is not None
    time.sleep(1.1)
    assert cache.get("p", response_model=_M, model="m", temperature=0.1, max_tokens=10) is None


def test_does_not_cache_none_output():
    cache = SemanticCache(backend="memory")
    # A result with no output (a failure) must not be cached.
    bad = LLMCallResult(output=None, model="m", tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=1, schema_compliance=False)
    cache.put("p", bad, response_model=_M, model="m", temperature=0.1, max_tokens=10)
    assert cache.get("p", response_model=_M, model="m", temperature=0.1, max_tokens=10) is None


# ---------------------------------------------------------------------------
# redis backend (guarded)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _redis_available(), reason="redis not available")
def test_redis_backend_exact_hit():
    cache = SemanticCache(backend="redis")
    try:
        cache.clear()
        cache.put("redis prompt", _make_result("r"), response_model=_M, model="m", temperature=0.1, max_tokens=10)
        hit = cache.get("redis prompt", response_model=_M, model="m", temperature=0.1, max_tokens=10)
        assert hit is not None
        assert hit.output.value == "r"
    finally:
        cache.clear()


@pytest.mark.skipif(not _redis_available(), reason="redis not available")
def test_redis_backend_falls_back_to_memory_when_unreachable(monkeypatch):
    # Force an unreachable Redis URL; the cache must degrade to memory.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    cache = SemanticCache(backend="redis")
    assert cache.backend == "memory"
    cache.put("x", _make_result("y"), response_model=_M, model="m", temperature=0.1, max_tokens=10)
    assert cache.get("x", response_model=_M, model="m", temperature=0.1, max_tokens=10) is not None


# ---------------------------------------------------------------------------
# Acceptance: repeated request < 100 ms
# ---------------------------------------------------------------------------


def test_acceptance_repeated_request_under_100ms():
    cache = SemanticCache(backend="memory")
    gen_calls = {"n": 0}

    def slow_generate(prompt: str) -> LLMCallResult:
        hit = cache.get(prompt, response_model=_M, model="m", temperature=0.1, max_tokens=10)
        if hit is not None:
            return hit
        gen_calls["n"] += 1
        time.sleep(0.25)  # simulate a slow LLM backend
        result = _make_result("generated")
        cache.put(prompt, result, response_model=_M, model="m", temperature=0.1, max_tokens=10)
        return result

    t0 = time.perf_counter()
    slow_generate("hello world")
    dt_first = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    slow_generate("hello world")
    dt_second = (time.perf_counter() - t0) * 1000

    assert dt_first > 100, f"first call unexpectedly fast: {dt_first}"
    assert dt_second < 100, f"repeated request too slow: {dt_second} ms"
    assert gen_calls["n"] == 1, "backend should have been called exactly once"


# ---------------------------------------------------------------------------
# Integration with the real LLM clients (mock mode)
# ---------------------------------------------------------------------------


def test_llm_client_cache_hit_fast(monkeypatch):
    """LLMClient.call() serves a repeated request from cache in < 100 ms."""
    import os

    monkeypatch.setenv("MOCK_LLM", "true")
    monkeypatch.setenv("LLM_SEMANTIC_CACHE_ENABLED", "true")
    monkeypatch.setenv("LLM_SEMANTIC_CACHE_BACKEND", "memory")
    reset_semantic_cache()

    from src.audiobook_studio.llm.client import LLMClient, LLMClientConfig

    client = LLMClient(LLMClientConfig(model="test-model"))
    calls = {"n": 0}
    orig = client._mock_call

    def slow_mock(prompt, rm):
        calls["n"] += 1
        time.sleep(0.2)
        return LLMCallResult(
            output=rm(value="ok") if rm is _M else orig(prompt, rm),
            model=client.config.model,
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            latency_ms=1,
            schema_compliance=True,
        )

    monkeypatch.setattr(client, "_mock_call", slow_mock)

    client.call("repeat this exact prompt", _M)
    t0 = time.perf_counter()
    r2 = client.call("repeat this exact prompt", _M)
    dt = (time.perf_counter() - t0) * 1000

    assert calls["n"] == 1, "underlying generation should run only once"
    assert dt < 100, f"cached call too slow: {dt} ms"
    assert isinstance(r2.output, _M)


def test_direct_client_cache_hit_fast(monkeypatch):
    """DirectProviderClient.call() serves a repeated request from cache in < 100 ms."""
    monkeypatch.setenv("MOCK_LLM", "true")
    monkeypatch.setenv("LLM_SEMANTIC_CACHE_ENABLED", "true")
    monkeypatch.setenv("LLM_SEMANTIC_CACHE_BACKEND", "memory")
    reset_semantic_cache()

    client = DirectProviderClient(
        DirectProviderClientConfig(provider=DirectProviderType.OPENAI, model="gpt-4o-mini")
    )
    calls = {"n": 0}
    orig = client._mock_call

    def slow_mock(prompt, rm):
        calls["n"] += 1
        time.sleep(0.2)
        # _M() is a valid non-None output so the cache can store the result.
        return LLMCallResult(
            output=rm(value="ok") if rm is _M else orig(prompt, rm),
            model=client.config.model,
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            latency_ms=1,
            schema_compliance=True,
        )

    monkeypatch.setattr(client, "_mock_call", slow_mock)

    client.call("repeat this exact prompt", _M)
    t0 = time.perf_counter()
    client.call("repeat this exact prompt", _M)
    dt = (time.perf_counter() - t0) * 1000

    assert calls["n"] == 1, "underlying generation should run only once"
    assert dt < 100, f"cached call too slow: {dt} ms"


def test_stats_reported():
    cache = SemanticCache(backend="memory")
    cache.put("p", _make_result("a"), response_model=_M, model="m", temperature=0.1, max_tokens=10)
    cache.get("p", response_model=_M, model="m", temperature=0.1, max_tokens=10)
    cache.get("missing", response_model=_M, model="m", temperature=0.1, max_tokens=10)
    s = cache.stats()
    assert s["hits"] == 1
    assert s["misses"] == 1
    assert s["size"] == 1
    assert s["backend"] == "memory"

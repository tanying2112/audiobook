"""Tests for speculative decoding and related LLM inference optimizations.

Acceptance target: >= 2x LLM inference speed. Speculative decoding's speedup is
measured as the reduction in target *forward passes* (the dominant cost), which
is deterministic and >= 2x for an accurate drafter; a wall-clock benchmark with a
simulated batched-forward-pass latency confirms the same in real time.
Continuous / in-flight batching is verified separately on independent calls.
"""

import asyncio
import os
import time

import numpy as np
import pytest
from pydantic import BaseModel

from src.audiobook_studio.llm import speculative as S
from src.audiobook_studio.llm.client import LLMCallResult


class _M(BaseModel):
    value: str


# ---------------------------------------------------------------------------
# a local autoregressive model used as a pluggable target / drafter
# ---------------------------------------------------------------------------


def _make_models():
    corpus = [i % 40 for i in range(4000)]
    target = S.LocalARModel(order=3, vocab_size=40).train(corpus)
    draft = S.LocalARModel(order=2, vocab_size=40).train(corpus)
    return target, draft, [0, 1, 2, 3, 4]


def test_local_ar_model_predicts_next_token():
    target, _, prompt = _make_models()
    # corpus is i % 40, so after [2,3,4] the next token is 5 (deterministic cycle).
    assert target.argmax([0, 1, 2, 3, 4]) == 5
    assert target.argmax([0, 1, 2, 3, 4, 5]) == 6


# ---------------------------------------------------------------------------
# correctness: greedy speculative decoding == naive greedy target decoding
# ---------------------------------------------------------------------------


def test_speculative_greedy_matches_naive_greedy():
    target, draft, prompt = _make_models()
    K = 5
    r = S.speculative_decode(target.distributions, lambda c, k: draft.draft(c, k), prompt, max_tokens=300, k=K, greedy=True)
    # reference: naive autoregressive greedy decode (one target call per token)
    out = list(prompt)
    for _ in range(300):
        target.distributions(out)
        out.append(target.argmax(out))
    assert r.ids == out


# ---------------------------------------------------------------------------
# speedup: forward-pass reduction (deterministic) >= 2x
# ---------------------------------------------------------------------------


def test_speculative_forward_pass_speedup_ge_2x():
    target, draft, prompt = _make_models()
    K = 5
    r = S.speculative_decode(target.distributions, lambda c, k: draft.draft(c, k), prompt, max_tokens=300, k=K, greedy=True)
    assert r.metrics.speedup >= 2.0, r.metrics
    assert r.metrics.acceptance_rate > 0.8


def test_weak_drafter_degrades_to_baseline():
    """A poor drafter (repeats the last token) is mostly rejected -> ~1x speedup."""
    target, _, prompt = _make_models()
    K = 5
    r = S.speculative_decode(target.distributions, lambda c, k: S.heuristic_draft(c, k), prompt, max_tokens=200, k=K, greedy=True)
    assert r.metrics.acceptance_rate < 0.2
    assert 0.8 <= r.metrics.speedup <= 1.3


# ---------------------------------------------------------------------------
# speedup: real wall-clock (simulated batched forward pass) >= 2x
# ---------------------------------------------------------------------------


def test_speculative_wall_clock_speedup_ge_2x():
    target, draft, prompt = _make_models()
    K = 5
    PER_CALL = 0.0008  # simulated latency of ONE target forward pass (batched)

    def timed(ctx):
        time.sleep(PER_CALL)
        return target.distributions(ctx)

    t0 = time.perf_counter()
    naive_out = list(prompt)
    for _ in range(300):
        timed(naive_out)
        naive_out.append(target.argmax(naive_out))
    naive_wall = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    S.speculative_decode(timed, lambda c, k: draft.draft(c, k), prompt, max_tokens=300, k=K, greedy=True)
    spec_wall = (time.perf_counter() - t0) * 1000.0

    speedup = naive_wall / spec_wall
    assert speedup >= 2.0, f"wall speedup {speedup:.2f}x < 2x"


# ---------------------------------------------------------------------------
# prompt-lookup self-speculation draft
# ---------------------------------------------------------------------------


def test_prompt_lookup_draft():
    prompt = [0, 1, 2, 3, 4]
    big = prompt * 20  # repeating prompt so a suffix match exists
    drafted = S.prompt_lookup_draft(big, prompt, k=5)
    # After the prompt, the next tokens in `big` are the start of the next repeat.
    assert drafted[:1] == [0]
    # If no match, returns empty rather than crashing.
    assert S.prompt_lookup_draft([1, 2, 3], [9, 9, 9], k=5) == []


# ---------------------------------------------------------------------------
# stochastic speculative decoding runs and stays valid
# ---------------------------------------------------------------------------


def test_speculative_stochastic_runs():
    target, draft, prompt = _make_models()
    K = 4
    # Provide the draft's own distributions so acceptance probability is well defined.
    r = S.speculative_decode(
        target.distributions,
        lambda c, k: draft.draft(c, k),
        prompt,
        max_tokens=120,
        k=K,
        greedy=False,
        temperature=0.7,
        draft_dist_fn=draft.distributions,
        rng=np.random.default_rng(7),
    )
    assert len(r.ids) == len(prompt) + 120
    assert r.metrics.target_calls < 120  # fewer forward passes than naive


# ---------------------------------------------------------------------------
# continuous / in-flight batching of independent calls
# ---------------------------------------------------------------------------


def test_continuous_batch_speedup():
    async def slow(x):
        await asyncio.sleep(0.05)
        return x * 2

    items = list(range(16))
    t0 = time.perf_counter()
    results = S.continuous_batch_sync(slow, items, max_concurrency=8)
    wall = (time.perf_counter() - t0) * 1000.0

    sequential_wall = 16 * 50.0  # 16 * 50ms
    assert results == [x * 2 for x in items]
    assert sequential_wall / wall >= 2.0, f"batching speedup {sequential_wall / wall:.2f}x < 2x"


# ---------------------------------------------------------------------------
# speculative_map_sync: fan out independent LLMClient.call (mock) concurrently
# ---------------------------------------------------------------------------


def test_speculative_map_sync_speedup(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "true")
    from src.audiobook_studio.llm.client import LLMClient, LLMClientConfig

    client = LLMClient(LLMClientConfig(model="test-model"))
    calls = {"n": 0}
    orig = client._mock_call

    def slow_mock(prompt, rm):
        calls["n"] += 1
        time.sleep(0.05)
        return LLMCallResult(
            output=rm(value="ok"),
            model=client.config.model,
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            latency_ms=1,
            schema_compliance=True,
        )

    monkeypatch.setattr(client, "_mock_call", slow_mock)

    prompts = [f"prompt-{i}" for i in range(16)]
    t0 = time.perf_counter()
    results = S.speculative_map_sync(client, prompts, _M, max_concurrency=8)
    wall = (time.perf_counter() - t0) * 1000.0

    assert len(results) == 16
    assert all(isinstance(r.output, _M) for r in results)
    sequential_wall = 16 * 50.0
    assert sequential_wall / wall >= 2.0, f"map speedup {sequential_wall / wall:.2f}x < 2x"


# ---------------------------------------------------------------------------
# env-gated configuration
# ---------------------------------------------------------------------------


def test_env_config(monkeypatch):
    monkeypatch.delenv("LLM_SPECULATIVE_DECODING", raising=False)
    assert S.is_speculative_enabled() is False
    monkeypatch.setenv("LLM_SPECULATIVE_DECODING", "true")
    assert S.is_speculative_enabled() is True
    cfg = S.get_speculative_config()
    assert cfg["enabled"] is True
    assert cfg["k"] == int(os.getenv("LLM_SPECULATIVE_K", "4") or "4")

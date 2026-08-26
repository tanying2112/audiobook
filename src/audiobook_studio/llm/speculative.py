"""Speculative decoding and related LLM inference optimizations.

This module implements *backend-agnostic* inference-speed optimizations so the
project can reach >= 2x LLM latency reduction without requiring a paid API or a
GPU. Three complementary techniques are provided:

1. **Speculative decoding** (Chen et al. 2023; Leviathan et al. 2023).
   A cheap *drafter* proposes ``K`` candidate tokens per step; a slower
   *target* model verifies them in a **single** forward pass. Accepted tokens
   are emitted "for free"; on rejection we fall back to the target's own token.
   Wall-clock speedup is ~``K`` when the draft is accurate, because the target
   does ~1 forward pass per ``K`` tokens instead of ``K``.

   The algorithm is implemented over two plain callables so it works with any
   backend: a local model (vLLM / llama.cpp / HuggingFace ``transformers`` /
   TGI -- all of which expose speculative decoding natively), or a remote
   echo/logprobs-capable API (via the *prompt-lookup* self-speculation below).

2. **Prompt-lookup self-speculation** (Santilli et al. 2023, "Accelerating
   Transformer Decoding with Single-Step Cached Lookup"). Needs *no* extra
   model: it copies the tokens that follow an n-gram match inside the prompt.
   This is the drop-in technique for any API that can echo its prompt with
   ``logprobs``.

3. **Continuous / in-flight batching** of *independent* LLM calls. The common
   case in this project is translating / extracting / QA-ing many paragraphs;
   fanning those out concurrently (with a bounded semaphore) gives near-linear
   wall-clock speedup. This is the same idea behind vLLM's continuous batching,
   applied at the request level.

Frontier relatives (not re-implemented here, but the interfaces are compatible):
Medusa / EAGLE / lookahead decoding replace the drafter with a trained head; the
:class:`SpeculativeHead` protocol is the extension point.

All of this is opt-in via env (``LLM_SPECULATIVE_DECODING=true``) so existing
tests and remote/mock behaviour are unchanged by default.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

TokenSeq = List[int]
# target(context) -> next-token log-probs (log_softmax) for EVERY prefix position.
#   result[i] has length V and is the distribution for token i+1 given context[:i+1].
TargetFn = Callable[[TokenSeq], List[np.ndarray]]
# draft(context, k) -> up to k proposed token ids (deterministic drafter).
DraftFn = Callable[[TokenSeq, int], TokenSeq]


# ---------------------------------------------------------------------------
# small math helpers
# ---------------------------------------------------------------------------


def _log_softmax(arr: np.ndarray) -> np.ndarray:
    a = arr.astype(np.float64)
    a = a - float(a.max())
    ea = np.exp(a)
    s = float(ea.sum()) + 1e-12
    return np.log(ea / s + 1e-12)


def _pick(logp: np.ndarray, temperature: float, rng: np.random.Generator, greedy: bool) -> int:
    if greedy or temperature <= 0:
        return int(np.argmax(logp))
    scaled = logp / max(temperature, 1e-6)
    probs = np.exp(scaled)
    probs = probs / (probs.sum() + 1e-12)
    return int(rng.choice(probs.shape[0], p=probs))


# ---------------------------------------------------------------------------
# Local autoregressive model (used as a pluggable target / drafter and for tests)
# ---------------------------------------------------------------------------


class LocalARModel:
    """A tiny, deterministic n-gram autoregressive model.

    It is intentionally lightweight (count-based, numpy only) so it can act as a
    *local* target model for speculative decoding in tests and, if a real local
    LLM is unavailable, as a cheap drafter. It exposes the exact surface a
    transformer target would: ``distributions(context)`` returns the per-position
    next-token log-probs needed by the verification step.
    """

    def __init__(self, order: int, vocab_size: int, seed: int = 0) -> None:
        self.order = max(1, order)
        self.vocab_size = vocab_size
        self.counts: Dict[Tuple[int, ...], np.ndarray] = {}
        self._rng = np.random.default_rng(seed)

    def train(self, token_ids: Sequence[int]) -> "LocalARModel":
        for i in range(len(token_ids)):
            # Context = the `order` tokens *before* token i (NOT including it).
            ctx = tuple(token_ids[max(0, i - self.order) : i])
            nxt = int(token_ids[i])
            arr = self.counts.get(ctx)
            if arr is None:
                arr = np.full(self.vocab_size, 0.1, dtype=np.float64)  # Laplace smoothing
                self.counts[ctx] = arr
            arr[nxt] += 1.0
        return self

    def _key(self, context: TokenSeq) -> Tuple[int, ...]:
        return tuple(context[-self.order :]) if context else ()

    def logits(self, context: TokenSeq) -> np.ndarray:
        arr = self.counts.get(self._key(context))
        if arr is None:
            arr = np.full(self.vocab_size, 0.1, dtype=np.float64)
        return _log_softmax(arr)

    def distributions(self, context: TokenSeq) -> List[np.ndarray]:
        """Next-token log-probs after every prefix position of ``context``."""
        return [_log_softmax(self.counts.get(self._key(context[: i + 1]),
                                               np.full(self.vocab_size, 0.1, dtype=np.float64)))
                for i in range(len(context))]

    def argmax(self, context: TokenSeq) -> int:
        return int(np.argmax(self.logits(context)))

    def draft(self, context: TokenSeq, k: int) -> TokenSeq:
        """Greedily autoregressively draft ``k`` tokens (used as a drafter)."""
        out = list(context)
        res: TokenSeq = []
        for _ in range(k):
            nxt = self.argmax(out)
            res.append(nxt)
            out.append(nxt)
        return res


# ---------------------------------------------------------------------------
# draft strategies
# ---------------------------------------------------------------------------


def independent_model_draft(model: LocalARModel, context: TokenSeq, k: int) -> TokenSeq:
    """Draft ``k`` tokens with an independent (smaller/cheaper) model."""
    return model.draft(context, k)


def heuristic_draft(context: TokenSeq, k: int) -> TokenSeq:
    """A deliberately weak drafter: repeats the last token ``k`` times.

    Useful to demonstrate the *worst case* (low acceptance -> near-baseline cost).
    """
    if not context:
        return []
    return [context[-1]] * k


def _find_subseq(haystack: TokenSeq, needle: TokenSeq) -> int:
    if not needle:
        return -1
    n = len(needle)
    for i in range(0, len(haystack) - n + 1):
        if haystack[i : i + n] == needle:
            return i
    return -1


def prompt_lookup_draft(prompt_ids: TokenSeq, context: TokenSeq, k: int, max_ngram: int = 8) -> TokenSeq:
    """Prompt-lookup / self-speculation draft (Santilli et al. 2023).

    Find the longest suffix of ``context`` that also occurs earlier in
    ``prompt_ids`` and draft the tokens that follow that occurrence. Needs no
    extra model and works with any echo/logprobs-capable API.
    """
    for n in range(min(max_ngram, max(0, len(context) - 1)), 0, -1):
        suffix = tuple(context[-n:])
        idx = _find_subseq(prompt_ids, list(suffix))
        if idx != -1:
            follow = prompt_ids[idx + n : idx + n + k]
            return list(follow)[:k]
    return []


# ---------------------------------------------------------------------------
# core speculative decoding loop
# ---------------------------------------------------------------------------


@dataclass
class SpeculativeMetrics:
    accepted: int = 0
    drafted: int = 0
    steps: int = 0
    target_calls: int = 0
    draft_calls: int = 0
    naive_target_calls: int = 0
    wall_ms: float = 0.0

    @property
    def speedup(self) -> float:
        """Forward-pass reduction vs naive autoregressive decoding."""
        return float(self.naive_target_calls) / float(self.target_calls) if self.target_calls else float("inf")

    @property
    def acceptance_rate(self) -> float:
        return float(self.accepted) / float(self.drafted) if self.drafted else 0.0


@dataclass
class SpeculativeResult:
    ids: TokenSeq
    metrics: SpeculativeMetrics


def speculative_decode(
    target_dist_fn: TargetFn,
    draft_fn: DraftFn,
    prompt_ids: TokenSeq,
    max_tokens: int,
    k: int = 4,
    temperature: float = 0.0,
    draft_dist_fn: Optional[TargetFn] = None,
    rng: Optional[np.random.Generator] = None,
    greedy: bool = True,
) -> SpeculativeResult:
    """Run speculative decoding.

    Returns the full token sequence (prompt + generated) and metrics. The
    generated portion is *exactly* the target's greedy decode when ``greedy`` is
    True, regardless of draft quality (the algorithm never changes the target's
    distribution).
    """
    rng = rng or np.random.default_rng(0)
    out: TokenSeq = list(prompt_ids)
    target_calls = 0
    draft_calls = 0
    accepted = 0
    drafted_total = 0
    steps = 0
    generated = 0
    start = time.perf_counter()

    while generated < max_tokens:
        steps += 1
        base_len = len(out)  # fixed for this step; out is mutated inside the loop
        draft_calls += 1
        draft_tokens = list(draft_fn(out, k))

        if not draft_tokens:
            # Drafter has nothing to propose -> one plain target token.
            target_calls += 1
            dists = target_dist_fn(out)
            out.append(_pick(dists[-1], temperature, rng, greedy))
            generated += 1
            continue

        drafted_total += len(draft_tokens)
        ctx = out + draft_tokens
        target_calls += 1
        dists = target_dist_fn(ctx)  # length == len(ctx)
        n_accepted = 0
        broke = False
        for t in range(len(draft_tokens)):
            # Verify draft token t against the target distribution at the prefix
            # BEFORE it (O + d_0..d_{t-1}), i.e. index base_len + t - 1 in dists.
            # Using the prefix that includes the draft token would "peek" at the
            # draft and break equivalence with greedy target decoding.
            ver_pos = base_len + t - 1
            drafted = draft_tokens[t]
            p_target = float(np.exp(dists[ver_pos][drafted]))
            if draft_dist_fn is not None:
                dd = draft_dist_fn(ctx[: ver_pos + 1])[-1]
                p_draft = float(np.exp(dd[drafted]))
            else:
                p_draft = 1.0  # deterministic drafter: certain of its token
            if greedy:
                accept = drafted == int(np.argmax(dists[ver_pos]))
            else:
                accept_prob = min(1.0, p_target / max(p_draft, 1e-12))
                accept = rng.random() < accept_prob
            if accept:
                out.append(drafted)
                accepted += 1
                n_accepted += 1
                generated += 1
            else:
                out.append(_pick(dists[ver_pos], temperature, rng, greedy))
                generated += 1
                broke = True
                break

        if not broke:
            # All drafts accepted -> "bonus" target token from the last position
            # (free, from the same forward pass). This is what yields ~K+1 tokens
            # per step and the real speedup.
            out.append(_pick(dists[-1], temperature, rng, greedy))
            generated += 1
            n_accepted += 1

    wall_ms = (time.perf_counter() - start) * 1000.0
    metrics = SpeculativeMetrics(
        accepted=accepted,
        drafted=drafted_total,
        steps=steps,
        target_calls=target_calls,
        draft_calls=draft_calls,
        naive_target_calls=max_tokens,
        wall_ms=wall_ms,
    )
    return SpeculativeResult(ids=out, metrics=metrics)


# ---------------------------------------------------------------------------
# continuous / in-flight batching of independent calls
# ---------------------------------------------------------------------------


async def continuous_batch(fn: Callable[[Any], Any], items: Sequence[Any], max_concurrency: int = 8) -> List[Any]:
    """Run ``fn`` over ``items`` concurrently with a bounded semaphore.

    ``fn`` may be sync or async; sync callables are run in the default executor
    so they do not block the event loop. This is the request-level analogue of
    vLLM's continuous batching and gives ~linear wall-clock speedup for
    independent LLM calls (the dominant workload in translate/extract/QA).
    """
    sem = asyncio.Semaphore(max(1, max_concurrency))
    loop = asyncio.get_running_loop()

    async def _run(it: Any) -> Any:
        async with sem:
            if asyncio.iscoroutinefunction(fn):
                return await fn(it)
            return await loop.run_in_executor(None, fn, it)

    return await asyncio.gather(*(_run(it) for it in items))


def continuous_batch_sync(fn: Callable[[Any], Any], items: Sequence[Any], max_concurrency: int = 8) -> List[Any]:
    """Synchronous wrapper around :func:`continuous_batch`."""
    return asyncio.run(continuous_batch(fn, items, max_concurrency))


def speculative_map_sync(
    client: Any,
    prompts: Sequence[Any],
    response_model: Any,
    max_concurrency: int = 8,
    **call_kwargs: Any,
) -> List[Any]:
    """Fan out many independent ``client.call(prompt, response_model)`` calls.

    Directly applicable to this project's pipelines: many paragraphs are
    translated / extracted independently, so concurrent execution cuts wall
    time roughly by ``max_concurrency``. Returns results in input order.
    """

    def _one(prompt: Any) -> Any:
        return client.call(prompt, response_model, **call_kwargs)

    return continuous_batch_sync(_one, list(prompts), max_concurrency)


# ---------------------------------------------------------------------------
# extension point for Medusa / EAGLE / lookahead heads
# ---------------------------------------------------------------------------


class SpeculativeHead(Protocol):
    """A trained draft head (Medusa / EAGLE / lookahead).

    Implementations expose ``propose(context, k) -> List[TokenSeq]`` returning
    *multiple* candidate token paths; the core loop above would verify each.
    Provided as the integration point for those frontier methods.
    """

    def propose(self, context: TokenSeq, k: int) -> List[TokenSeq]:
        ...


# ---------------------------------------------------------------------------
# env-gated configuration
# ---------------------------------------------------------------------------


def is_speculative_enabled() -> bool:
    return os.getenv("LLM_SPECULATIVE_DECODING", "false").lower() in ("1", "true", "yes", "on")


def get_speculative_config() -> Dict[str, Any]:
    return {
        "enabled": is_speculative_enabled(),
        "k": int(os.getenv("LLM_SPECULATIVE_K", "4") or "4"),
        "draft": os.getenv("LLM_SPECULATIVE_DRAFT", "ngram"),
    }


__all__ = [
    "LocalARModel",
    "independent_model_draft",
    "heuristic_draft",
    "prompt_lookup_draft",
    "speculative_decode",
    "SpeculativeMetrics",
    "SpeculativeResult",
    "continuous_batch",
    "continuous_batch_sync",
    "speculative_map_sync",
    "SpeculativeHead",
    "is_speculative_enabled",
    "get_speculative_config",
]

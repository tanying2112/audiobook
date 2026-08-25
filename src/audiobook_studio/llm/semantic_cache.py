"""LLM semantic cache.

A two-tier cache for LLM responses so that *repeated* and *semantically
similar* requests can be served without hitting the (slow, possibly paid) LLM
backend.

Tiers
-----
1. **Exact tier** — keyed on a normalized form of the prompt together with the
   model / temperature / max_tokens / response_model that influence the output.
   Identical repeat requests return the cached ``LLMCallResult`` in well under
   1 ms (in-process memory) or a few ms (Redis round-trip). This is what
   guarantees the ``< 100 ms`` acceptance target for repeated requests.
2. **Semantic tier** — the prompt is embedded with a dependency-free
   feature-hash bag-of-words vector; new requests are compared (cosine
   similarity) against cached vectors *within the same output namespace*. When
   similarity exceeds a threshold the previously cached response is reused.
   This catches rephrasings / word re-orderings of the same meaning.

Embedding provider is pluggable: by default a free, offline hash embedding is
used; if ``LLM_SEMANTIC_CACHE_EMBEDDING=sentence_transformers`` and
``sentence_transformers`` is importable a real embedding model is used instead.

Backends
--------
* ``memory`` (default) — in-process LRU + TTL. Fastest, per-process.
* ``redis``  — exact payloads are mirrored to a shared Redis (so they survive
  across workers); the semantic similarity index stays in-process for speed.

Everything is controlled by environment variables and the cache is **disabled
unless** ``LLM_SEMANTIC_CACHE_ENABLED=true``. When disabled, ``get()`` always
returns ``None`` and ``put()`` is a no-op, so callers pay nothing.

This module intentionally avoids importing the heavy LLM client at module load
to prevent circular imports; ``LLMCallResult`` is imported lazily inside
``_to_result``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)

__all__ = [
    "SemanticCache",
    "get_semantic_cache",
    "reset_semantic_cache",
    "normalize_prompt",
    "cached_llm_lookup",
    "cached_llm_store",
]

# ---------------------------------------------------------------------------
# Configuration (read from environment, mirroring the MOCK_LLM pattern)
# ---------------------------------------------------------------------------

EMBED_DIM = 256
_DEFAULT_SIMILARITY = 0.95
_DEFAULT_TTL = 86400  # 24h
_DEFAULT_MAX_SIZE = 1024
_REDIS_PREFIX = "llm_semcache:"


def _cache_enabled() -> bool:
    return os.getenv("LLM_SEMANTIC_CACHE_ENABLED", "false").lower() in ("1", "true", "yes", "on")


def _cache_backend() -> str:
    return os.getenv("LLM_SEMANTIC_CACHE_BACKEND", "memory").lower()


def _cache_similarity() -> float:
    try:
        return float(os.getenv("LLM_SEMANTIC_CACHE_SIMILARITY", str(_DEFAULT_SIMILARITY)))
    except (TypeError, ValueError):
        return _DEFAULT_SIMILARITY


def _cache_ttl() -> int:
    try:
        return int(os.getenv("LLM_SEMANTIC_CACHE_TTL", str(_DEFAULT_TTL)))
    except (TypeError, ValueError):
        return _DEFAULT_TTL


def _cache_max_size() -> int:
    try:
        return int(os.getenv("LLM_SEMANTIC_CACHE_MAX_SIZE", str(_DEFAULT_MAX_SIZE)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_SIZE


def _embedding_provider_name() -> str:
    return os.getenv("LLM_SEMANTIC_CACHE_EMBEDDING", "hash").lower()


# ---------------------------------------------------------------------------
# Prompt normalization + embedding
# ---------------------------------------------------------------------------


def normalize_prompt(prompt: Any) -> str:
    """Normalize a prompt (string or messages list) to a comparable string.

    Lower-cases and collapses whitespace so trivial formatting differences do
    not create distinct cache keys.
    """
    if isinstance(prompt, (list, tuple)):
        parts: List[str] = []
        for m in prompt:
            if isinstance(m, dict):
                parts.append(str(m.get("content", "")))
            else:
                parts.append(str(m))
        text = " ".join(parts)
    else:
        text = str(prompt)
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _hash_embed(text: str, dim: int = EMBED_DIM) -> List[float]:
    """Dependency-free feature-hash bag-of-words embedding.

    Token order is discarded and each token is hashed into a fixed-dimension
    vector (counting occurrences), then L2-normalized. Two prompts that share
    the same words (in any order) get identical vectors (cosine == 1.0);
    rephrasings sharing most words get high cosine similarity.
    """
    vec = [0.0] * dim
    for tok in re.findall(r"\w+", text):
        vec[hash(tok) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _cosine(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Cache entry + payload (de)serialization
# ---------------------------------------------------------------------------


@dataclass
class _Entry:
    exact_key: str
    norm: str
    embedding: List[float]
    namespace: str
    payload: Dict[str, Any]
    expires_at: float


def _serialize_result(result: Any, response_model: Type[Any]) -> Dict[str, Any]:
    """Convert an LLMCallResult into a JSON-serializable payload."""
    output = getattr(result, "output", None)
    if output is None:
        output_json: Optional[str] = None
    elif hasattr(output, "model_dump_json"):
        output_json = output.model_dump_json()
    else:
        output_json = json.dumps(output, default=str)
    return {
        "output_json": output_json,
        "response_model_name": getattr(response_model, "__name__", "Unknown"),
        "tokens_in": getattr(result, "tokens_in", 0),
        "tokens_out": getattr(result, "tokens_out", 0),
        "cost_usd": getattr(result, "cost_usd", 0.0),
        "model": getattr(result, "model", ""),
        "schema_compliance": getattr(result, "schema_compliance", True),
        "contract_version": getattr(result, "contract_version", 1),
    }


def _to_result(payload: Dict[str, Any], response_model: Type[Any], latency_ms: int) -> Any:
    """Rebuild an LLMCallResult from a cached payload (lazy import)."""
    from .client import LLMCallResult

    output_json = payload.get("output_json")
    if output_json is None:
        output = None
    else:
        output = response_model.model_validate_json(output_json)
    return LLMCallResult(
        output=output,
        model=payload.get("model", ""),
        tokens_in=payload.get("tokens_in", 0),
        tokens_out=payload.get("tokens_out", 0),
        cost_usd=payload.get("cost_usd", 0.0),
        latency_ms=latency_ms,
        schema_compliance=payload.get("schema_compliance", True),
        contract_version=payload.get("contract_version", 1),
        raw_response=None,
    )


# ---------------------------------------------------------------------------
# Semantic cache
# ---------------------------------------------------------------------------


class SemanticCache:
    """Two-tier (exact + semantic) LLM response cache.

    Thread-safe. Exact payloads live in ``_mem`` (and optionally mirrored to
    Redis); the semantic similarity index is the in-process ``_mem`` map.
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
        ttl: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> None:
        self.backend = (backend or _cache_backend()).lower()
        self.similarity_threshold = (
            similarity_threshold if similarity_threshold is not None else _cache_similarity()
        )
        self.ttl = ttl if ttl is not None else _cache_ttl()
        self.max_size = max_size if max_size is not None else _cache_max_size()
        self.enabled = True

        self._lock = threading.Lock()
        self._mem: Dict[str, _Entry] = {}

        self._redis: Any = None
        if self.backend == "redis":
            self._redis = self._make_redis_client()

        # Stats
        self.hits = 0
        self.misses = 0
        self.exact_hits = 0
        self.semantic_hits = 0

        # Embedding provider (lazy)
        self._embed_fn = self._build_embed_fn()

    # -- redis plumbing ----------------------------------------------------

    def _make_redis_client(self) -> Any:
        try:
            import redis as _redis_lib  # type: ignore

            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = _redis_lib.Redis.from_url(
                url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
            )
            client.ping()
            return client
        except Exception as e:  # pragma: no cover - depends on environment
            logger.warning("SemanticCache: redis backend unavailable (%s); using memory only", e)
            self.backend = "memory"
            return None

    def _redis_key(self, exact_key: str) -> str:
        return f"{_REDIS_PREFIX}{exact_key}"

    def _redis_get(self, exact_key: str) -> Optional[Dict[str, Any]]:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(self._redis_key(exact_key))
        except Exception as e:  # pragma: no cover - depends on environment
            logger.warning("SemanticCache: redis get failed (%s)", e)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def _redis_set(self, exact_key: str, payload: Dict[str, Any]) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(self._redis_key(exact_key), json.dumps(payload), ex=self.ttl)
        except Exception as e:  # pragma: no cover - depends on environment
            logger.warning("SemanticCache: redis set failed (%s)", e)

    # -- embedding --------------------------------------------------------

    def _build_embed_fn(self):  # type: ignore[no-untyped-def]
        name = _embedding_provider_name()
        if name == "sentence_transformers":
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore

                model = SentenceTransformer("all-MiniLM-L6-v2")

                def _embed(text: str) -> List[float]:
                    vec = model.encode(text, normalize_embeddings=True)
                    return [float(x) for x in vec]

                logger.info("SemanticCache: using sentence_transformers embedding")
                return _embed
            except Exception as e:  # pragma: no cover - heavy optional dep
                logger.warning("SemanticCache: sentence_transformers unavailable (%s); using hash", e)
        return _hash_embed

    # -- keying -----------------------------------------------------------

    @staticmethod
    def _namespace(model: str, temperature: float, max_tokens: int, response_model_name: str) -> str:
        return f"{model}|{temperature}|{max_tokens}|{response_model_name}"

    def _exact_key(self, norm: str, namespace: str) -> str:
        raw = f"{namespace}::{norm}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # -- public API -------------------------------------------------------

    def get(
        self,
        prompt: Any,
        *,
        response_model: Type[Any],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Any:
        """Return a cached ``LLMCallResult`` or ``None``.

        On a hit, ``latency_ms`` reflects the (tiny) time spent retrieving from
        the cache, which is what the ``< 100 ms`` acceptance target measures.
        """
        if not self.enabled:
            self.misses += 1
            return None

        t0 = time.perf_counter()
        norm = normalize_prompt(prompt)
        namespace = self._namespace(model, temperature, max_tokens, response_model.__name__)
        exact_key = self._exact_key(norm, namespace)

        # 1) exact (in-memory)
        with self._lock:
            entry = self._mem.get(exact_key)
            if entry is not None and not self._is_expired(entry):
                self.hits += 1
                self.exact_hits += 1
                latency = int((time.perf_counter() - t0) * 1000)
                return _to_result(entry.payload, response_model, latency)

        # 1b) exact (redis mirror, possibly written by another process)
        if self._redis is not None:
            red = self._redis_get(exact_key)
            if red is not None:
                with self._lock:
                    self._mem[exact_key] = self._make_entry(exact_key, norm, namespace, red)
                self.hits += 1
                self.exact_hits += 1
                latency = int((time.perf_counter() - t0) * 1000)
                return _to_result(red, response_model, latency)

        # 2) semantic (in-memory vector index)
        emb = self._embed_fn(norm)
        best: Optional[_Entry] = None
        best_sim = self.similarity_threshold
        with self._lock:
            for e in self._mem.values():
                if e.namespace != namespace or self._is_expired(e):
                    continue
                sim = _cosine(emb, e.embedding)
                if sim > best_sim:
                    best_sim = sim
                    best = e

        if best is not None:
            payload = best.payload
            if self._redis is not None:
                red = self._redis_get(best.exact_key)
                if red is not None:
                    payload = red
            self.hits += 1
            self.semantic_hits += 1
            latency = int((time.perf_counter() - t0) * 1000)
            return _to_result(payload, response_model, latency)

        self.misses += 1
        return None

    def put(
        self,
        prompt: Any,
        result: Any,
        *,
        response_model: Type[Any],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> None:
        """Store an ``LLMCallResult`` for later retrieval."""
        if not self.enabled:
            return
        # Never cache failure results (None output) — they would poison hits.
        if getattr(result, "output", None) is None:
            return

        norm = normalize_prompt(prompt)
        namespace = self._namespace(model, temperature, max_tokens, response_model.__name__)
        exact_key = self._exact_key(norm, namespace)
        payload = _serialize_result(result, response_model)
        entry = self._make_entry(exact_key, norm, namespace, payload)

        with self._lock:
            self._mem[exact_key] = entry
            self._evict_if_needed()

        if self._redis is not None:
            self._redis_set(exact_key, payload)

    # -- helpers ----------------------------------------------------------

    def _make_entry(self, exact_key: str, norm: str, namespace: str, payload: Dict[str, Any]) -> _Entry:
        return _Entry(
            exact_key=exact_key,
            norm=norm,
            embedding=self._embed_fn(norm),
            namespace=namespace,
            payload=payload,
            expires_at=time.time() + self.ttl,
        )

    def _is_expired(self, entry: _Entry) -> bool:
        return time.time() > entry.expires_at

    def _evict_if_needed(self) -> None:
        # Lazily prune expired entries, then cap total size.
        if len(self._mem) <= self.max_size:
            return
        now = time.time()
        expired = [k for k, v in self._mem.items() if now > v.expires_at]
        for k in expired:
            self._mem.pop(k, None)
        while len(self._mem) > self.max_size:
            # pop the entry that expires soonest (approx LRU by expiry)
            try:
                oldest = min(self._mem.values(), key=lambda e: e.expires_at)
                self._mem.pop(oldest.exact_key, None)
            except (ValueError, KeyError):
                break

    def stats(self) -> Dict[str, int]:
        """Return cache statistics for observability."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "exact_hits": self.exact_hits,
            "semantic_hits": self.semantic_hits,
            "size": len(self._mem),
            "backend": self.backend,
        }

    def clear(self) -> None:
        """Clear all in-memory entries (and Redis keys if applicable)."""
        with self._lock:
            self._mem.clear()
        if self._redis is not None:
            try:
                for k in self._redis.scan_iter(match=f"{_REDIS_PREFIX}*"):
                    self._redis.delete(k)
            except Exception as e:  # pragma: no cover - depends on environment
                logger.warning("SemanticCache: redis clear failed (%s)", e)


# ---------------------------------------------------------------------------
# Singleton accessor (lazy, process-wide)
# ---------------------------------------------------------------------------

_cache_singleton: Optional[SemanticCache] = None
_cache_resolved = False


def get_semantic_cache() -> Optional[SemanticCache]:
    """Return the process-wide ``SemanticCache`` or ``None`` if disabled.

    Resolution happens once per process. Call :func:`reset_semantic_cache` to
    force re-resolution (e.g. after changing env vars in tests).
    """
    global _cache_singleton, _cache_resolved
    if _cache_resolved:
        return _cache_singleton
    _cache_resolved = True
    if not _cache_enabled():
        _cache_singleton = None
        return None
    try:
        _cache_singleton = SemanticCache()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("SemanticCache init failed (%s); cache disabled", e)
        _cache_singleton = None
    return _cache_singleton


def reset_semantic_cache() -> None:
    """Reset the singleton so the next call re-resolves from env vars."""
    global _cache_singleton, _cache_resolved
    _cache_singleton = None
    _cache_resolved = False


# ---------------------------------------------------------------------------
# Thin helpers for the LLM clients (reduce duplication)
# ---------------------------------------------------------------------------


def cached_llm_lookup(
    cache: Optional[SemanticCache],
    *,
    prompt: Any,
    response_model: Type[Any],
    model: str,
    temperature: float,
    max_tokens: int,
) -> Any:
    """Return a cached result or ``None`` (no-op when ``cache`` is ``None``)."""
    if cache is None:
        return None
    return cache.get(
        prompt,
        response_model=response_model,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def cached_llm_store(
    cache: Optional[SemanticCache],
    *,
    prompt: Any,
    result: Any,
    response_model: Type[Any],
    model: str,
    temperature: float,
    max_tokens: int,
) -> None:
    """Store a result in the cache (no-op when ``cache`` is ``None``)."""
    if cache is None:
        return
    cache.put(
        prompt,
        result,
        response_model=response_model,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

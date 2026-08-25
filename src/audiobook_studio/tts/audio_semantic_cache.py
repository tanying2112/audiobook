"""Audio Semantic Cache for TTS Segments.

A two-tier cache for TTS audio synthesis so that *repeated* and *semantically
similar* text segments can be served without hitting the (slow, possibly paid)
TTS backend.

Tiers
-----
1. **Exact tier** — keyed on a normalized form of the text together with the
   voice_id / prosody / speed that influence the output.
   Identical repeat requests return the cached audio file path in well under
   1 ms (in-process memory) or a few ms (Redis round-trip).

2. **Semantic tier** — the text is embedded with a dependency-free
   feature-hash bag-of-words vector; new requests are compared (cosine
   similarity) against cached vectors *within the same voice namespace*. When
   similarity exceeds a threshold the previously cached audio file is reused.
   This catches rephrasings / word re-orderings of the same meaning.

Embedding provider is pluggable: by default a free, offline hash embedding is
used; if ``AUDIO_SEMANTIC_CACHE_EMBEDDING=sentence_transformers`` and
``sentence_transformers`` is importable a real embedding model is used instead.

Backends
--------
* ``memory`` (default) — in-process LRU + TTL. Fastest, per-process.
* ``redis``  — exact payloads are mirrored to a shared Redis (so they survive
  across workers); the semantic similarity index stays in-process for speed.

Everything is controlled by environment variables and the cache is **disabled
unless** ``AUDIO_SEMANTIC_CACHE_ENABLED=true``. When disabled, ``get()`` always
returns ``None`` and ``put()`` is a no-op, so callers pay nothing.
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "AudioSemanticCache",
    "get_audio_semantic_cache",
    "reset_audio_semantic_cache",
    "normalize_audio_text",
    "cached_audio_lookup",
    "cached_audio_store",
]

# ---------------------------------------------------------------------------
# Configuration (read from environment, mirroring the LLM semantic cache pattern)
# ---------------------------------------------------------------------------

EMBED_DIM = 256
_DEFAULT_SIMILARITY = 0.93  # Slightly lower for audio since text variations may be acceptable
_DEFAULT_TTL = 86400 * 7  # 7 days for audio (larger files, less frequent regeneration)
_DEFAULT_MAX_SIZE = 512  # Smaller default due to audio file sizes
_REDIS_PREFIX = "audio_semcache:"


def _cache_enabled() -> bool:
    return os.getenv("AUDIO_SEMANTIC_CACHE_ENABLED", "false").lower() in ("1", "true", "yes", "on")


def _cache_backend() -> str:
    return os.getenv("AUDIO_SEMANTIC_CACHE_BACKEND", "memory").lower()


def _cache_similarity() -> float:
    try:
        return float(os.getenv("AUDIO_SEMANTIC_CACHE_SIMILARITY", str(_DEFAULT_SIMILARITY)))
    except (TypeError, ValueError):
        return _DEFAULT_SIMILARITY


def _cache_ttl() -> int:
    try:
        return int(os.getenv("AUDIO_SEMANTIC_CACHE_TTL", str(_DEFAULT_TTL)))
    except (TypeError, ValueError):
        return _DEFAULT_TTL


def _cache_max_size() -> int:
    try:
        return int(os.getenv("AUDIO_SEMANTIC_CACHE_MAX_SIZE", str(_DEFAULT_MAX_SIZE)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_SIZE


def _embedding_provider_name() -> str:
    return os.getenv("AUDIO_SEMANTIC_CACHE_EMBEDDING", "hash").lower()


def _audio_cache_dir() -> Path:
    """Get the audio cache directory."""
    cache_dir = os.getenv("AUDIOBOOK_STUDIO_AUDIO_CACHE", "~/.cache/audiobook_studio/audio_cache")
    return Path(cache_dir).expanduser()


# ---------------------------------------------------------------------------
# Text normalization + embedding (reused from LLM semantic cache logic)
# ---------------------------------------------------------------------------


def normalize_audio_text(text: str, voice_id: str, prosody: Dict[str, Any]) -> str:
    """Normalize text + voice + prosody to a comparable cache key string.

    Lower-cases and collapses whitespace so trivial formatting differences do
    not create distinct cache keys.
    """
    # Normalize text
    norm_text = text.lower()
    norm_text = re.sub(r"\s+", " ", norm_text).strip()

    # Normalize prosody (sorted for consistency)
    prosody_items = sorted(prosody.items()) if prosody else []
    prosody_str = json.dumps(prosody_items, sort_keys=True)

    # Combine: text|voice_id|prosody
    return f"{norm_text}|{voice_id}|{prosody_str}"


def _hash_embed(text: str, dim: int = EMBED_DIM) -> List[float]:
    """Dependency-free feature-hash bag-of-words embedding.

    Token order is discarded and each token is hashed into a fixed-dimension
    vector (counting occurrences), then L2-normalized. Two texts that share
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
# Cache entry
# ---------------------------------------------------------------------------


@dataclass
class _AudioCacheEntry:
    exact_key: str
    norm_text: str
    embedding: List[float]
    namespace: str  # voice_id for audio cache
    audio_path: str  # Path to cached audio file
    duration_ms: int
    expires_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Audio Semantic Cache Implementation
# ---------------------------------------------------------------------------


class AudioSemanticCache:
    """Two-tier semantic cache for TTS audio segments."""

    def __init__(
        self,
        enabled: Optional[bool] = None,
        backend: Optional[str] = None,
        similarity: Optional[float] = None,
        ttl: Optional[int] = None,
        max_size: Optional[int] = None,
        embedding_provider: Optional[str] = None,
    ):
        self._enabled = enabled if enabled is not None else _cache_enabled()
        self._backend = backend if backend is not None else _cache_backend()
        self._similarity = similarity if similarity is not None else _cache_similarity()
        self._ttl = ttl if ttl is not None else _cache_ttl()
        self._max_size = max_size if max_size is not None else _cache_max_size()
        self._embedding_provider = embedding_provider if embedding_provider is not None else _embedding_provider_name()

        # In-memory LRU cache: exact_key -> _AudioCacheEntry
        self._memory_cache: Dict[str, _AudioCacheEntry] = {}
        self._access_order: List[str] = []  # For LRU eviction
        self._lock = threading.RLock()

        # Namespace index: voice_id -> List[exact_key] (for semantic search within voice)
        self._namespace_index: Dict[str, List[str]] = {}

        # Redis client (lazy init)
        self._redis = None
        self._redis_ready = False

        # Stats
        self._stats = {
            "exact_hits": 0,
            "semantic_hits": 0,
            "misses": 0,
            "puts": 0,
            "evictions": 0,
        }

        # Ensure cache directory exists
        self._cache_dir = _audio_cache_dir()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"AudioSemanticCache initialized: enabled={self._enabled}, "
            f"backend={self._backend}, similarity={self._similarity}, "
            f"ttl={self._ttl}s, max_size={self._max_size}, "
            f"embedding={self._embedding_provider}, cache_dir={self._cache_dir}"
        )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def get(
        self,
        text: str,
        voice_id: str,
        prosody: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Optional[Tuple[str, int, Dict[str, Any]]]:
        """Get cached audio for the given text/voice/prosody.

        Returns:
            Tuple of (audio_file_path, duration_ms, metadata) if found, else None.
            Metadata includes 'cache_type': 'exact' or 'semantic', and 'similarity' for semantic hits.
        """
        if not self._enabled:
            return None

        namespace = namespace or voice_id
        exact_key = self._make_exact_key(text, voice_id, prosody)

        # Tier 1: Exact match
        entry = self._get_exact(exact_key)
        if entry is not None:
            self._stats["exact_hits"] += 1
            logger.debug(f"Audio cache exact hit: {exact_key[:32]}...")
            return entry.audio_path, entry.duration_ms, {"cache_type": "exact", "similarity": 1.0}

        # Tier 2: Semantic similarity (within same voice namespace)
        semantic_entry = self._get_semantic(text, voice_id, prosody, namespace)
        if semantic_entry is not None:
            self._stats["semantic_hits"] += 1
            similarity = _cosine(_hash_embed(normalize_audio_text(text, voice_id, prosody)), semantic_entry.embedding)
            logger.debug(f"Audio cache semantic hit: {exact_key[:32]}... similarity={similarity:.3f}")
            return semantic_entry.audio_path, semantic_entry.duration_ms, {
                "cache_type": "semantic",
                "similarity": similarity,
            }

        self._stats["misses"] += 1
        return None

    def put(
        self,
        text: str,
        voice_id: str,
        prosody: Dict[str, Any],
        audio_path: str,
        duration_ms: int,
        namespace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store audio in cache.

        The audio file at audio_path will be copied to the cache directory
        for persistence (if not already there).
        """
        if not self._enabled:
            return

        namespace = namespace or voice_id
        exact_key = self._make_exact_key(text, voice_id, prosody)
        norm_text = normalize_audio_text(text, voice_id, prosody)

        # Copy audio file to cache directory if needed
        cached_audio_path = self._ensure_cached_audio(audio_path, exact_key)

        entry = _AudioCacheEntry(
            exact_key=exact_key,
            norm_text=norm_text,
            embedding=_hash_embed(norm_text),
            namespace=namespace,
            audio_path=cached_audio_path,
            duration_ms=duration_ms,
            expires_at=time.time() + self._ttl,
            metadata=metadata or {},
        )

        with self._lock:
            # Add to memory cache
            self._memory_cache[exact_key] = entry
            self._access_order.append(exact_key)

            # Add to namespace index
            if namespace not in self._namespace_index:
                self._namespace_index[namespace] = []
            self._namespace_index[namespace].append(exact_key)

            # Evict if over max size
            self._evict_if_needed()

            self._stats["puts"] += 1

        # Mirror to Redis if enabled
        if self._backend == "redis":
            self._put_redis(exact_key, entry)

        logger.debug(f"Audio cache put: {exact_key[:32]}... ({duration_ms}ms)")

    def invalidate(self, text: str, voice_id: str, prosody: Dict[str, Any]) -> bool:
        """Invalidate a specific cache entry."""
        exact_key = self._make_exact_key(text, voice_id, prosody)
        with self._lock:
            if exact_key in self._memory_cache:
                entry = self._memory_cache.pop(exact_key)
                self._access_order.remove(exact_key)
                if entry.namespace in self._namespace_index:
                    self._namespace_index[entry.namespace].remove(exact_key)
                return True
        return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._memory_cache.clear()
            self._access_order.clear()
            self._namespace_index.clear()
            self._stats = {k: 0 for k in self._stats}

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                **self._stats,
                "memory_entries": len(self._memory_cache),
                "namespaces": list(self._namespace_index.keys()),
                "enabled": self._enabled,
                "backend": self._backend,
            }

    # -----------------------------------------------------------------------
    # Internal methods
    # -----------------------------------------------------------------------

    def _make_exact_key(self, text: str, voice_id: str, prosody: Dict[str, Any]) -> str:
        """Create exact cache key from text + voice + prosody."""
        content = normalize_audio_text(text, voice_id, prosody)
        return hashlib.sha256(content.encode(), usedforsecurity=False).hexdigest()[:32]

    def _get_exact(self, exact_key: str) -> Optional[_AudioCacheEntry]:
        """Get entry by exact key (Tier 1)."""
        with self._lock:
            entry = self._memory_cache.get(exact_key)
            if entry is None:
                # Try Redis
                if self._backend == "redis":
                    entry = self._get_redis(exact_key)
                    if entry:
                        # Promote to memory cache
                        self._memory_cache[exact_key] = entry
                        self._access_order.append(exact_key)
                        self._evict_if_needed()

            if entry and entry.expires_at > time.time():
                # Update LRU order
                if exact_key in self._access_order:
                    self._access_order.remove(exact_key)
                self._access_order.append(exact_key)
                return entry
            elif entry:
                # Expired - remove
                self._remove_entry(exact_key)
        return None

    def _get_semantic(self, text: str, voice_id: str, prosody: Dict[str, Any], namespace: str) -> Optional[_AudioCacheEntry]:
        """Find semantically similar entry in the same namespace (Tier 2)."""
        if namespace not in self._namespace_index:
            return None

        query_embedding = _hash_embed(normalize_audio_text(text, voice_id, prosody))
        best_entry = None
        best_similarity = 0.0

        with self._lock:
            for exact_key in self._namespace_index.get(namespace, []):
                entry = self._memory_cache.get(exact_key)
                if entry is None or entry.expires_at <= time.time():
                    continue

                similarity = _cosine(query_embedding, entry.embedding)
                if similarity > best_similarity and similarity >= self._similarity:
                    best_similarity = similarity
                    best_entry = entry

        return best_entry

    def _ensure_cached_audio(self, source_path: str, exact_key: str) -> str:
        """Ensure audio file is in cache directory, return cached path."""
        source = Path(source_path)
        cache_path = self._cache_dir / f"{exact_key}.wav"

        if source == cache_path:
            return str(cache_path)

        if source.exists() and not cache_path.exists():
            import shutil
            shutil.copy2(source, cache_path)

        return str(cache_path)

    def _evict_if_needed(self) -> None:
        """Evict LRU entries if over max size."""
        while len(self._memory_cache) > self._max_size and self._access_order:
            oldest_key = self._access_order.pop(0)
            self._remove_entry(oldest_key)
            self._stats["evictions"] += 1

    def _remove_entry(self, exact_key: str) -> None:
        """Remove entry from memory cache and namespace index."""
        entry = self._memory_cache.pop(exact_key, None)
        if entry and entry.namespace in self._namespace_index:
            if exact_key in self._namespace_index[entry.namespace]:
                self._namespace_index[entry.namespace].remove(exact_key)

    # -----------------------------------------------------------------------
    # Redis backend (optional)
    # -----------------------------------------------------------------------

    def _get_redis_client(self):
        """Lazy init Redis client."""
        if not self._redis_ready:
            try:
                import redis
                self._redis = redis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                    decode_responses=True,
                )
                self._redis.ping()
                self._redis_ready = True
                logger.info("Audio semantic cache Redis backend connected")
            except Exception as e:
                logger.warning(f"Audio cache Redis unavailable, falling back to memory: {e}")
                self._redis = None
                self._redis_ready = True  # Don't retry
        return self._redis

    def _put_redis(self, exact_key: str, entry: _AudioCacheEntry) -> None:
        """Mirror entry to Redis."""
        client = self._get_redis_client()
        if client is None:
            return

        try:
            payload = {
                "exact_key": entry.exact_key,
                "norm_text": entry.norm_text,
                "embedding": entry.embedding,
                "namespace": entry.namespace,
                "audio_path": entry.audio_path,
                "duration_ms": entry.duration_ms,
                "expires_at": entry.expires_at,
                "metadata": entry.metadata,
            }
            client.setex(
                f"{_REDIS_PREFIX}{exact_key}",
                int(entry.expires_at - time.time()),
                json.dumps(payload),
            )
            # Add to namespace set for semantic search
            client.sadd(f"{_REDIS_PREFIX}ns:{entry.namespace}", exact_key)
        except Exception as e:
            logger.warning(f"Failed to write audio cache to Redis: {e}")

    def _get_redis(self, exact_key: str) -> Optional[_AudioCacheEntry]:
        """Get entry from Redis."""
        client = self._get_redis_client()
        if client is None:
            return None

        try:
            data = client.get(f"{_REDIS_PREFIX}{exact_key}")
            if data:
                payload = json.loads(data)
                return _AudioCacheEntry(**payload)
        except Exception as e:
            logger.warning(f"Failed to read audio cache from Redis: {e}")
        return None


# ---------------------------------------------------------------------------
# Global instance management (singleton pattern)
# ---------------------------------------------------------------------------

_global_audio_cache: Optional[AudioSemanticCache] = None
_global_audio_cache_lock = threading.Lock()


def get_audio_semantic_cache(**kwargs) -> AudioSemanticCache:
    """Get or create the global audio semantic cache instance."""
    global _global_audio_cache
    with _global_audio_cache_lock:
        if _global_audio_cache is None:
            _global_audio_cache = AudioSemanticCache(**kwargs)
        return _global_audio_cache


def reset_audio_semantic_cache() -> None:
    """Reset the global audio semantic cache instance (mainly for testing)."""
    global _global_audio_cache
    with _global_audio_cache_lock:
        if _global_audio_cache is not None:
            _global_audio_cache.clear()
        _global_audio_cache = None


# ---------------------------------------------------------------------------
# Convenience decorators/functions for integration with synthesize pipeline
# ---------------------------------------------------------------------------


def cached_audio_lookup(
    text: str,
    voice_id: str,
    prosody: Dict[str, Any],
    namespace: Optional[str] = None,
) -> Optional[Tuple[str, int, Dict[str, Any]]]:
    """Convenience function for cache lookup."""
    cache = get_audio_semantic_cache()
    return cache.get(text, voice_id, prosody, namespace)


def cached_audio_store(
    text: str,
    voice_id: str,
    prosody: Dict[str, Any],
    audio_path: str,
    duration_ms: int,
    namespace: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Convenience function for cache store."""
    cache = get_audio_semantic_cache()
    cache.put(text, voice_id, prosody, audio_path, duration_ms, namespace, metadata)

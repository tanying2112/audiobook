"""Phase B coverage tests for tts/audio_semantic_cache.py.

Covers: config parsing (env + invalid values), normalization/embedding math,
exact tier (hit/miss/expiry/LRU promotion), semantic tier (namespace isolation,
threshold boundary, rephrasing hit), put/copy/invalidate/clear/stats/eviction,
Redis backend paths (mocked client: success / down / write failure), singleton
management and convenience wrappers.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.tts.audio_semantic_cache import (
    EMBED_DIM,
    AudioSemanticCache,
    _audio_cache_dir,
    _cache_backend,
    _cache_enabled,
    _cache_max_size,
    _cache_similarity,
    _cache_ttl,
    _cosine,
    _hash_embed,
    cached_audio_lookup,
    cached_audio_store,
    get_audio_semantic_cache,
    normalize_audio_text,
    reset_audio_semantic_cache,
)

MOD = "src.audiobook_studio.tts.audio_semantic_cache"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_STUDIO_AUDIO_CACHE", str(tmp_path / "acache"))
    return tmp_path / "acache"


def make_audio(cache_dir: Path, name="seg.wav") -> Path:
    f = cache_dir.parent / name
    f.write_bytes(b"RIFFfake-audio")
    return f


def enabled_cache(**kw) -> AudioSemanticCache:
    kw.setdefault("enabled", True)
    kw.setdefault("backend", "memory")
    return AudioSemanticCache(**kw)


# ─────────────────────────────────────────────────────────────────────────────
# Config helpers — env & malformed values
# ─────────────────────────────────────────────────────────────────────────────


class TestConfigHelpers:
    def test_enabled_flag_variants(self, monkeypatch):
        for v in ("1", "true", "YES", "on"):
            monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_ENABLED", v)
            assert _cache_enabled() is True
        for v in ("0", "false", "no", "off", ""):
            monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_ENABLED", v)
            assert _cache_enabled() is False

    def test_backend_default_and_override(self, monkeypatch):
        monkeypatch.delenv("AUDIO_SEMANTIC_CACHE_BACKEND", raising=False)
        assert _cache_backend() == "memory"
        monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_BACKEND", "REDIS")
        assert _cache_backend() == "redis"

    def test_similarity_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_SIMILARITY", "not-a-float")
        assert _cache_similarity() == 0.93

    def test_ttl_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_TTL", "abc")
        assert _cache_ttl() == 86400 * 7

    def test_max_size_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_MAX_SIZE", "xyz")
        assert _cache_max_size() == 512

    def test_cache_dir_expands_user(self, monkeypatch):
        monkeypatch.setenv("AUDIOBOOK_STUDIO_AUDIO_CACHE", "~/myaudio")
        p = _audio_cache_dir()
        assert not str(p).startswith("~")


class TestMathHelpers:
    def test_normalize_lowercases_and_collapses_ws(self):
        a = normalize_audio_text("Hello   WORLD\n", "v1", {"rate": 1.0})
        b = normalize_audio_text("hello world", "v1", {"rate": 1.0})
        assert a == b

    def test_normalize_sorts_prosody(self):
        a = normalize_audio_text("x", "v", {"a": 1, "b": 2})
        b = normalize_audio_text("x", "v", {"b": 2, "a": 1})
        assert a == b

    def test_hash_embed_deterministic_normalized(self):
        v1 = _hash_embed("hello world hello")
        v2 = _hash_embed("world hello hello")
        assert v1 == v2  # bag of words ignores order
        assert len(v1) == EMBED_DIM
        norm = sum(x * x for x in v1) ** 0.5
        assert abs(norm - 1.0) < 1e-9

    def test_cosine_identical_opposite_degenerate(self):
        v = _hash_embed("some tokens here")
        assert _cosine(v, v) == pytest.approx(1.0)
        assert _cosine([1.0], [0.0]) == 0.0  # length mismatch
        assert _cosine([], []) == 0.0  # empty
        assert _cosine([0.0] * 4, [0.0] * 4) == 0.0  # zero vector


# ─────────────────────────────────────────────────────────────────────────────
# Disabled behaviour — zero cost contract
# ─────────────────────────────────────────────────────────────────────────────


class TestDisabledCache:
    def test_get_put_noop_when_disabled(self, tmp_path):
        c = AudioSemanticCache(enabled=False, backend="memory")
        assert c.get("t", "v", {}) is None
        c.put("t", "v", {}, "/nonexistent.wav", 100)  # must not touch fs
        assert c.stats()["puts"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Exact tier
# ─────────────────────────────────────────────────────────────────────────────


class TestExactTier:
    def test_put_then_exact_hit_roundtrip(self, cache_dir):
        c = enabled_cache()
        src = make_audio(cache_dir)
        c.put("你好世界", "voiceA", {"rate": 1.0}, str(src), 1500)
        hit = c.get("你好世界", "voiceA", {"rate": 1.0})
        assert hit is not None
        path, ms, meta = hit
        assert meta["cache_type"] == "exact"
        assert meta["similarity"] == 1.0
        assert ms == 1500
        assert Path(path).exists()  # copied into cache dir

    def test_whitespace_variant_is_same_key(self, cache_dir):
        c = enabled_cache()
        src = make_audio(cache_dir)
        c.put("Hello   World", "v", {}, str(src), 100)
        hit = c.get("hello world", "v", {})
        assert hit and hit[2]["cache_type"] == "exact"

    def test_miss_then_stats(self, cache_dir):
        c = enabled_cache()
        assert c.get("nothing", "v", {}) is None
        s = c.stats()
        assert s["misses"] == 1 and s["exact_hits"] == 0

    def test_expired_entry_removed_on_read(self, cache_dir):
        c = enabled_cache(ttl=1)
        src = make_audio(cache_dir)
        c.put("t", "v", {}, str(src), 100)
        key = c._make_exact_key("t", "v", {})
        c._memory_cache[key].expires_at = time.time() - 1  # force expiry
        assert c.get("t", "v", {}) is None
        assert key not in c._memory_cache

    def test_invalidate_true_false(self, cache_dir):
        c = enabled_cache()
        src = make_audio(cache_dir)
        c.put("k", "v", {}, str(src), 10)
        assert c.invalidate("k", "v", {}) is True
        assert c.get("k", "v", {}) is None
        assert c.invalidate("k", "v", {}) is False

    def test_clear_resets_everything(self, cache_dir):
        c = enabled_cache()
        src = make_audio(cache_dir)
        c.put("a", "v", {}, str(src), 10)
        c.put("b", "v2", {}, str(src), 20)
        c._stats["semantic_hits"] = 5
        c.clear()
        s = c.stats()
        assert s["memory_entries"] == 0
        assert s["namespaces"] == []
        assert s["semantic_hits"] == 0
        assert s["puts"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Semantic tier
# ─────────────────────────────────────────────────────────────────────────────


class TestSemanticTier:
    def test_rephrase_within_namespace_hits_semantically(self, cache_dir):
        c = enabled_cache(similarity=0.90)
        src = make_audio(cache_dir)
        base = "the quick brown fox jumps over the lazy dog"
        c.put(base, "voiceX", {}, str(src), 800)
        rephrased = "the lazy dog jumps over the quick brown fox"  # same tokens, reordered
        hit = c.get(rephrased, "voiceX", {})
        assert hit is not None
        assert hit[2]["cache_type"] in ("semantic", "exact")
        if hit[2]["cache_type"] == "semantic":
            assert hit[2]["similarity"] >= 0.90

    def test_namespace_isolation_prevents_cross_voice_hit(self, cache_dir):
        c = enabled_cache(similarity=0.50)  # low bar on purpose
        src = make_audio(cache_dir)
        c.put("完全相同的句子内容", "male_voice", {}, str(src), 100)
        # Different voice → different namespace → no hit even at low threshold
        assert c.get("完全相同的句子内容", "female_voice", {}) is None

    def test_below_threshold_no_semantic_hit(self, cache_dir):
        c = enabled_cache(similarity=0.99)
        src = make_audio(cache_dir)
        c.put("alpha beta gamma delta epsilon", "v", {}, str(src), 100)
        assert c.get("totally different words zzz qqq", "v", {}) is None

    def test_expired_entries_skipped_in_semantic_scan(self, cache_dir):
        c = enabled_cache(similarity=0.10)
        src = make_audio(cache_dir)
        c.put("matching words here", "v", {}, str(src), 100)
        for e in c._memory_cache.values():
            e.expires_at = time.time() - 1
        assert c.get("matching words here", "v", {}) is None

    def test_empty_namespace_index_short_circuit(self, cache_dir):
        c = enabled_cache()
        assert c._get_semantic("x", "novoice", {}, "novoice") is None


# ─────────────────────────────────────────────────────────────────────────────
# File handling & eviction
# ─────────────────────────────────────────────────────────────────────────────


class TestFileAndEviction:
    def test_source_already_in_cache_dir_not_copied_again(self, cache_dir):
        c = enabled_cache()
        target = cache_dir / f"{c._make_exact_key('dup', 'v', {})}.wav"
        target.write_bytes(b"already-there")
        out = c._ensure_cached_audio(str(target), c._make_exact_key("dup", "v", {}))
        assert out == str(target)

    def test_missing_source_file_returns_expected_cache_path(self, cache_dir):
        c = enabled_cache()
        key = "deadbeef"
        out = c._ensure_cached_audio(str(cache_dir.parent / "ghost.wav"), key)
        assert out == str(cache_dir / f"{key}.wav")

    def test_lru_eviction_over_max_size(self, cache_dir):
        c = enabled_cache(max_size=3)
        src = make_audio(cache_dir)
        keys = []
        for i in range(5):
            t = f"text number {i}"
            c.put(t, "v", {}, str(src), 10)
            keys.append(c._make_exact_key(t, "v", {}))
        s = c.stats()
        assert s["evictions"] >= 2
        assert len(c._memory_cache) <= 3
        # oldest two evicted, newest retained
        assert keys[0] not in c._memory_cache
        assert keys[-1] in c._memory_cache

    def test_access_refreshes_lru_position(self, cache_dir):
        c = enabled_cache(max_size=2)
        src = make_audio(cache_dir)
        c.put("first", "v", {}, str(src), 10)
        c.put("second", "v", {}, str(src), 10)
        # Touch 'first' so it becomes most-recently used
        c.get("first", "v", {})
        c.put("third", "v", {}, str(src), 10)  # should evict 'second', not 'first'
        k_first = c._make_exact_key("first", "v", {})
        k_second = c._make_exact_key("second", "v", {})
        assert k_first in c._memory_cache
        assert k_second not in c._memory_cache


# ─────────────────────────────────────────────────────────────────────────────
# Redis backend (mocked client)
# ─────────────────────────────────────────────────────────────────────────────


class TestRedisBackend:
    def _redis_mock(self):
        client = MagicMock()
        client.ping.return_value = True
        client.get.return_value = None
        return client

    def test_put_mirrors_to_redis_and_sets_namespace(self, cache_dir):
        client = self._redis_mock()
        c = enabled_cache(backend="redis")
        with patch(f"{MOD}._AudioSemanticCache__dict__", create=True):
            pass
        with patch.object(AudioSemanticCache, "_get_redis_client", return_value=client):
            src = make_audio(cache_dir)
            c.put("redis text", "v", {}, str(src), 55)
            assert client.setex.called
            args = client.setex.call_args
            payload = json.loads(args.args[2])
            assert payload["duration_ms"] == 55
            assert client.sadd.called
            ns_key = client.sadd.call_args.args[0]
            assert "ns:v" in ns_key

    def test_get_promotes_redis_entry_to_memory(self, cache_dir):
        client = self._redis_mock()
        entry_payload = {
            "exact_key": "k1",
            "norm_text": "n",
            "embedding": [1.0] * EMBED_DIM,
            "namespace": "v",
            "audio_path": "/tmp/x.wav",
            "duration_ms": 42,
            "expires_at": time.time() + 3600,
            "metadata": {},
        }
        client.get.return_value = json.dumps(entry_payload)
        c = enabled_cache(backend="redis")
        with patch.object(AudioSemanticCache, "_get_redis_client", return_value=client):
            got = c._get_exact("k1")
        assert got is not None
        assert got.duration_ms == 42
        assert "k1" in c._memory_cache  # promoted

    def test_redis_down_falls_back_to_memory_only_once(self, cache_dir):
        failing = MagicMock()
        failing.ping.side_effect = RuntimeError("connection refused")
        c = enabled_cache(backend="redis")
        with patch("redis.from_url", return_value=failing), \
             patch.object(AudioSemanticCache, "_put_redis", return_value=None):
            first = c._get_redis_client()
            second = c._get_redis_client()
        assert first is None
        assert second is None
        assert failing.ping.call_count == 1  # no retry after failure

    def test_redis_write_failure_swallowed(self, cache_dir):
        client = self._redis_mock()
        client.setex.side_effect = RuntimeError("disk full on redis")
        c = enabled_cache(backend="redis")
        with patch.object(AudioSemanticCache, "_get_redis_client", return_value=client):
            src = make_audio(cache_dir)
            c.put("boom", "v", {}, str(src), 5)  # must not raise
        assert c.stats()["puts"] == 1

    def test_redis_get_corrupt_payload_returns_none(self, cache_dir):
        client = self._redis_mock()
        client.get.return_value = "{corrupt json"
        c = enabled_cache(backend="redis")
        with patch.object(AudioSemanticCache, "_get_redis_client", return_value=client):
            assert c._get_redis("anykey") is None


# ─────────────────────────────────────────────────────────────────────────────
# Singleton & convenience wrappers
# ─────────────────────────────────────────────────────────────────────────────


class TestSingletonAndWrappers:
    def setup_method(self):
        reset_audio_semantic_cache()

    def teardown_method(self):
        reset_audio_semantic_cache()

    def test_singleton_identity_and_reset(self):
        a = get_audio_semantic_cache(enabled=False)
        b = get_audio_semantic_cache(enabled=True)  # kwargs ignored on existing
        assert a is b
        reset_audio_semantic_cache()
        c = get_audio_semantic_cache(enabled=False)
        assert c is not a

    def test_reset_clears_before_discard(self):
        c = get_audio_semantic_cache(enabled=False)
        c._stats["puts"] = 7
        reset_audio_semantic_cache()  # calls clear() on live instance
        assert c._stats["puts"] == 0

    def test_convenience_lookup_and_store_disabled_by_default(self, cache_dir):
        # default env has cache disabled → lookup None, store noop
        src = make_audio(cache_dir)
        assert cached_audio_lookup("t", "v", {}) is None
        cached_audio_store("t", "v", {}, str(src), 10)  # no crash

    def test_convenience_wrappers_hit_when_enabled(self, cache_dir, monkeypatch):
        monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_ENABLED", "true")
        reset_audio_semantic_cache()
        src = make_audio(cache_dir)
        cached_audio_store("wrap me", "vx", {}, str(src), 33)
        hit = cached_audio_lookup("wrap me", "vx", {})
        assert hit is not None and hit[2]["cache_type"] == "exact"

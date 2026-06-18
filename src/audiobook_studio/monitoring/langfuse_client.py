"""Langfuse Client for LLM/TTS/Quality Tracing.

Provides observability for Audiobook Studio pipeline operations.
Integrates with Langfuse SDK for tracing, metrics, and debugging.
"""

import os
import logging
import atexit
from contextlib import contextmanager
from functools import wraps
from typing import Any, Dict, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

# Global Langfuse client instance
_langfuse_client: Optional[Any] = None
_enabled: bool = False


def init_langfuse(
    public_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    host: Optional[str] = None,
    enabled: bool = True,
) -> bool:
    """Initialize Langfuse client.

    Args:
        public_key: Langfuse public key (or LANGFUSE_PUBLIC_KEY env)
        secret_key: Langfuse secret key (or LANGFUSE_SECRET_KEY env)
        host: Langfuse host (or LANGFUSE_HOST env, defaults to https://cloud.langfuse.com)
        enabled: Whether to enable tracing

    Returns:
        True if initialization succeeded, False otherwise
    """
    global _langfuse_client, _enabled

    if not enabled:
        logger.info("Langfuse tracing disabled")
        _enabled = False
        return False

    public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
    host = host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.warning("Langfuse keys not configured, tracing disabled")
        _enabled = False
        return False

    try:
        from langfuse import Langfuse
        _langfuse_client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        _enabled = True
        logger.info(f"Langfuse initialized: {host}")

        # Register flush on exit
        atexit.register(flush_langfuse)
        return True
    except ImportError:
        logger.warning("langfuse package not installed, tracing disabled")
        _enabled = False
        return False
    except Exception as e:
        logger.error(f"Failed to initialize Langfuse: {e}")
        _enabled = False
        return False


def get_langfuse_client() -> Optional[Any]:
    """Get the global Langfuse client instance."""
    return _langfuse_client if _enabled else None


def is_enabled() -> bool:
    """Check if Langfuse tracing is enabled."""
    return _enabled and _langfuse_client is not None


def flush_langfuse() -> None:
    """Flush pending traces to Langfuse."""
    if _langfuse_client:
        try:
            _langfuse_client.flush()
            logger.debug("Langfuse traces flushed")
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse: {e}")


@contextmanager
def trace(
    name: str,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[list] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """Context manager for creating a trace.

    Usage:
        with trace("pipeline.run", metadata={"project_id": 1}) as span:
            span.update(output="result")
    """
    if not is_enabled():
        yield None
        return

    trace_obj = _langfuse_client.trace(
        name=name,
        metadata=metadata or {},
        tags=tags or [],
        user_id=user_id,
        session_id=session_id,
    )

    try:
        yield trace_obj
    except Exception as e:
        trace_obj.update(
            level="ERROR",
            status_message=str(e),
        )
        raise
    finally:
        _langfuse_client.flush()


@contextmanager
def span(
    name: str,
    trace_obj: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
    input_data: Optional[Any] = None,
    output_data: Optional[Any] = None,
):
    """Context manager for creating a span within a trace.

    Usage:
        with trace("pipeline") as t:
            with span("llm.call", t, metadata={"model": "gpt-4"}) as s:
                result = llm_call()
                s.update(output=result)
    """
    if not is_enabled() or trace_obj is None:
        yield None
        return

    span_obj = trace_obj.span(
        name=name,
        metadata=metadata or {},
        input=input_data,
    )

    try:
        yield span_obj
    except Exception as e:
        span_obj.update(
            level="ERROR",
            status_message=str(e),
        )
        raise
    finally:
        if output_data is not None:
            span_obj.update(output=output_data)
        span_obj.end()
        _langfuse_client.flush()


def observe_llm_call(
    stage: str,
    model: str,
    provider: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record an LLM call observation.

    Args:
        stage: Pipeline stage (extract, analyze, annotate, edit, synthesize, quality)
        model: Model name
        provider: Provider name
        prompt_tokens: Input tokens
        completion_tokens: Output tokens
        total_tokens: Total tokens
        cost_usd: Estimated cost
        latency_ms: Call latency
        metadata: Additional metadata
    """
    if not is_enabled():
        return

    _langfuse_client.generation(
        name=f"llm.{stage}",
        model=model,
        metadata={
            "stage": stage,
            "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            **(metadata or {}),
        },
    )
    _langfuse_client.flush()


def observe_tts_synthesis(
    voice_id: str,
    text_length: int,
    audio_duration_ms: float,
    latency_ms: float,
    backend: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a TTS synthesis observation.

    Args:
        voice_id: Voice identifier
        text_length: Input text length
        audio_duration_ms: Generated audio duration
        latency_ms: Synthesis latency
        backend: TTS backend (edge-tts, kokoro, gptsovits)
        metadata: Additional metadata
    """
    if not is_enabled():
        return

    _langfuse_client.generation(
        name="tts.synthesis",
        model=backend,
        metadata={
            "voice_id": voice_id,
            "text_length": text_length,
            "audio_duration_ms": audio_duration_ms,
            "latency_ms": latency_ms,
            "backend": backend,
            **(metadata or {}),
        },
    )
    _langfuse_client.flush()


def observe_quality_check(
    stage: str,
    passed: bool,
    score: float,
    issues: list,
    latency_ms: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a quality check observation.

    Args:
        stage: Quality check stage
        passed: Whether check passed
        score: Quality score (0-1)
        issues: List of detected issues
        latency_ms: Check latency
        metadata: Additional metadata
    """
    if not is_enabled():
        return

    _langfuse_client.event(
        name=f"quality.{stage}",
        metadata={
            "passed": passed,
            "score": score,
            "issues_count": len(issues),
            "issues": issues,
            "latency_ms": latency_ms,
            **(metadata or {}),
        },
        level="INFO" if passed else "WARNING",
    )
    _langfuse_client.flush()


def trace_function(
    name: Optional[str] = None,
    stage: Optional[str] = None,
    metadata_extractor: Optional[Callable] = None,
):
    """Decorator to trace a function call.

    Usage:
        @trace_function("llm.analyze", stage="analyze")
        def analyze_chapter(text):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            trace_name = name or f"{func.__module__}.{func.__name__}"
            meta = {}
            if metadata_extractor:
                try:
                    meta = metadata_extractor(*args, **kwargs)
                except Exception:
                    pass

            if stage:
                meta["stage"] = stage

            if not is_enabled():
                return func(*args, **kwargs)

            with trace(trace_name, metadata=meta) as trace_obj:
                with span(f"{trace_name}.exec", trace_obj) as span_obj:
                    start = datetime.now()
                    try:
                        result = func(*args, **kwargs)
                        span_obj.update(output={"success": True})
                        return result
                    except Exception as e:
                        span_obj.update(
                            level="ERROR",
                            status_message=str(e),
                            output={"success": False, "error": str(e)},
                        )
                        raise
                    finally:
                        latency_ms = (datetime.now() - start).total_seconds() * 1000
                        if span_obj:
                            span_obj.metadata = {**span_obj.metadata, "latency_ms": latency_ms}

        return wrapper
    return decorator


def score_trace(trace_obj: Any, score: float, comment: Optional[str] = None) -> None:
    """Add a score to a trace for evaluation.

    Args:
        trace_obj: Trace object from trace() context manager
        score: Score between 0 and 1
        comment: Optional comment
    """
    if not is_enabled() or trace_obj is None:
        return

    trace_obj.score(
        name="quality",
        value=score,
        comment=comment,
    )
    _langfuse_client.flush()


# Convenience functions for common pipeline stages
def trace_extract(func: Callable) -> Callable:
    return trace_function("pipeline.extract", stage="extract")(func)


def trace_analyze(func: Callable) -> Callable:
    return trace_function("pipeline.analyze", stage="analyze")(func)


def trace_annotate(func: Callable) -> Callable:
    return trace_function("pipeline.annotate", stage="annotate")(func)


def trace_edit(func: Callable) -> Callable:
    return trace_function("pipeline.edit", stage="edit")(func)


def trace_synthesize(func: Callable) -> Callable:
    return trace_function("pipeline.synthesize", stage="synthesize")(func)


def trace_quality(func: Callable) -> Callable:
    return trace_function("pipeline.quality", stage="quality")(func)


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(level=logging.INFO)

    # Initialize (will fail without keys, but shows usage)
    init_langfuse(enabled=False)

    # Example traced function
    @trace_function("demo.operation", stage="demo")
    def demo_func(x: int) -> int:
        return x * 2

    # Context manager usage
    with trace("demo.trace", metadata={"test": True}) as t:
        with span("demo.span", t, metadata={"input": 5}) as s:
            result = demo_func(5)
            print(f"Result: {result}")

    flush_langfuse()
    print("Demo complete")
"""
F2 — Langfuse 集成

全 LLM 调用 trace 上报，支持成本追踪、延迟监控、质量评估。
"""

import functools
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import langfuse, make it optional
try:
    from langfuse import Langfuse
    from langfuse.api.resources.commons.types.observation_type import ObservationType

    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    logger.warning("Langfuse not installed. Run 'pip install langfuse' to enable.")


@dataclass
class LLMCallTrace:
    """单次 LLM 调用的 trace 记录."""

    trace_id: str
    name: str
    input_data: Dict[str, Any]
    output_data: Optional[Dict[str, Any]] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    usage: Optional[Dict[str, int]] = (
        None  # prompt_tokens, completion_tokens, total_tokens
    )
    cost_usd: Optional[float] = None
    error: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return None


class LangfuseClient:
    """Langfuse 客户端封装，支持优雅降级."""

    def __init__(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        host: Optional[str] = None,
        enabled: bool = True,
    ):
        self.enabled = enabled and LANGFUSE_AVAILABLE
        self.client: Optional["Langfuse"] = None
        self._local_traces: List[LLMCallTrace] = []

        if self.enabled:
            public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
            secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
            host = host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

            if public_key and secret_key:
                try:
                    self.client = Langfuse(
                        public_key=public_key,
                        secret_key=secret_key,
                        host=host,
                    )
                    logger.info("Langfuse client initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize Langfuse: {e}")
                    self.enabled = False
            else:
                logger.warning("Langfuse credentials not found, disabling")
                self.enabled = False

    @contextmanager
    def trace(
        self,
        name: str,
        input_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ):
        """上下文管理器：自动记录 LLM 调用的开始/结束."""
        trace_id = str(uuid.uuid4())
        trace = LLMCallTrace(
            trace_id=trace_id,
            name=name,
            input_data=input_data,
            metadata=metadata or {},
            tags=tags or [],
        )

        try:
            yield trace
            trace.end_time = time.time()
        except Exception as e:
            trace.error = str(e)
            trace.end_time = time.time()
            raise
        finally:
            self._record_trace(trace)

    def _record_trace(self, trace: LLMCallTrace) -> None:
        """记录 trace 到 Langfuse 或本地存储."""
        self._local_traces.append(trace)

        if not self.enabled or not self.client:
            return

        try:
            # Create observation in Langfuse
            self.client.trace(
                id=trace.trace_id,
                name=trace.name,
                input=trace.input_data,
                output=trace.output_data,
                metadata={
                    **trace.metadata,
                    "duration_ms": trace.duration_ms,
                    "cost_usd": trace.cost_usd,
                    "error": trace.error,
                },
                tags=trace.tags,
                start_time=datetime.fromtimestamp(trace.start_time, tz=timezone.utc),
                end_time=(
                    datetime.fromtimestamp(trace.end_time, tz=timezone.utc)
                    if trace.end_time
                    else None
                ),
            )

            # If usage data available, create generation
            if trace.usage:
                self.client.generation(
                    trace_id=trace.trace_id,
                    name=f"{trace.name}_generation",
                    model=trace.metadata.get("model", "unknown"),
                    input=trace.input_data,
                    output=trace.output_data,
                    usage=trace.usage,
                    cost=trace.cost_usd,
                    metadata=trace.metadata,
                    start_time=datetime.fromtimestamp(
                        trace.start_time, tz=timezone.utc
                    ),
                    end_time=(
                        datetime.fromtimestamp(trace.end_time, tz=timezone.utc)
                        if trace.end_time
                        else None
                    ),
                )

            self.client.flush()
        except Exception as e:
            logger.error(f"Failed to send trace to Langfuse: {e}")

    def get_local_traces(self, limit: int = 100) -> List[LLMCallTrace]:
        """获取本地缓存的 traces（用于离线/降级模式）."""
        return self._local_traces[-limit:]

    def get_cost_summary(
        self,
        since_hours: int = 24,
        group_by: str = "model",
    ) -> Dict[str, Any]:
        """获取成本汇总（基于本地缓存）."""
        from datetime import datetime, timedelta

        cutoff = time.time() - (since_hours * 3600)
        recent = [t for t in self._local_traces if t.start_time >= cutoff]

        summary: Dict[str, Any] = {
            "total_calls": len(recent),
            "total_cost_usd": 0.0,
            "total_tokens": 0,
            "by_group": {},
        }

        for trace in recent:
            if trace.cost_usd:
                summary["total_cost_usd"] += trace.cost_usd
            if trace.usage:
                summary["total_tokens"] += trace.usage.get("total_tokens", 0)

            group_key = trace.metadata.get(group_by, "unknown")
            if group_key not in summary["by_group"]:
                summary["by_group"][group_key] = {
                    "calls": 0,
                    "cost_usd": 0.0,
                    "tokens": 0,
                }
            summary["by_group"][group_key]["calls"] += 1
            if trace.cost_usd:
                summary["by_group"][group_key]["cost_usd"] += trace.cost_usd
            if trace.usage:
                summary["by_group"][group_key]["tokens"] += trace.usage.get(
                    "total_tokens", 0
                )

        return summary


# Global singleton
_langfuse_client: Optional[LangfuseClient] = None


def get_langfuse_client() -> LangfuseClient:
    """获取全局 Langfuse 客户端单例."""
    global _langfuse_client
    if _langfuse_client is None:
        _langfuse_client = LangfuseClient()
    return _langfuse_client


def trace_llm_call(
    name: str,
    input_data: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
):
    """装饰器：自动为 LLM 调用函数添加 trace."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            client = get_langfuse_client()
            with client.trace(name, input_data, metadata, tags) as trace:
                result = func(*args, **kwargs)
                trace.output_data = (
                    result if isinstance(result, dict) else {"result": str(result)}
                )
                return result

        return wrapper

    return decorator

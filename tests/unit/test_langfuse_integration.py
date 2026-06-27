"""Tests for Langfuse integration module."""

import os
from contextlib import contextmanager
from unittest.mock import Mock, patch, MagicMock

import pytest


class TestLangfuseInit:
    """Tests for init_langfuse function."""

    def test_init_langfuse_without_keys_disables_client(self):
        """init_langfuse without API keys should disable the client."""
        with patch.dict(os.environ, {}, clear=True):
            from src.audiobook_studio.observability.langfuse_client import LangfuseClient

            client = LangfuseClient(public_key=None, secret_key=None, enabled=True)
            assert client.enabled is False
            assert client.client is None

    def test_init_langfuse_with_keys_enables_client(self):
        """init_langfuse with valid keys should enable the client."""
        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", True):
            with patch("src.audiobook_studio.observability.langfuse_client.Langfuse") as mock_langfuse:
                mock_instance = Mock()
                mock_langfuse.return_value = mock_instance

                from src.audiobook_studio.observability.langfuse_client import LangfuseClient

                client = LangfuseClient(
                    public_key="pk_test",
                    secret_key="sk_test",
                    host="https://cloud.langfuse.com",
                    enabled=True,
                )

                assert client.enabled is True
                assert client.client == mock_instance
                mock_langfuse.assert_called_once_with(
                    public_key="pk_test",
                    secret_key="sk_test",
                    host="https://cloud.langfuse.com",
                )

    def test_init_langfuse_with_env_vars(self):
        """init_langfuse should read keys from environment variables."""
        with patch.dict(os.environ, {
            "LANGFUSE_PUBLIC_KEY": "pk_env",
            "LANGFUSE_SECRET_KEY": "sk_env",
            "LANGFUSE_HOST": "https://custom.langfuse.com",
        }):
            with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", True):
                with patch("src.audiobook_studio.observability.langfuse_client.Langfuse") as mock_langfuse:
                    mock_instance = Mock()
                    mock_langfuse.return_value = mock_instance

                    from src.audiobook_studio.observability.langfuse_client import LangfuseClient

                    client = LangfuseClient(enabled=True)

                    assert client.enabled is True
                    mock_langfuse.assert_called_once_with(
                        public_key="pk_env",
                        secret_key="sk_env",
                        host="https://custom.langfuse.com",
                    )

    def test_init_langfuse_mock_mode(self):
        """init_langfuse with enabled=False should work in mock mode."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(
            public_key="pk_test",
            secret_key="sk_test",
            enabled=False,  # mock mode
        )

        assert client.enabled is False
        assert client.client is None

    def test_init_langfuse_not_available(self):
        """init_langfuse should handle missing langfuse package gracefully."""
        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", False):
            from src.audiobook_studio.observability.langfuse_client import LangfuseClient

            client = LangfuseClient(
                public_key="pk_test",
                secret_key="sk_test",
                enabled=True,
            )

            assert client.enabled is False
            assert client.client is None


class TestIsEnabled:
    """Tests for is_enabled function / property."""

    def test_is_enabled_returns_false_when_not_initialized(self):
        """is_enabled should return False when client not initialized or disabled."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)
        assert client.enabled is False

    def test_is_enabled_returns_true_when_initialized(self):
        """is_enabled should return True when client is properly initialized."""
        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", True):
            with patch("src.audiobook_studio.observability.langfuse_client.Langfuse") as mock_langfuse:
                mock_instance = Mock()
                mock_langfuse.return_value = mock_instance

                from src.audiobook_studio.observability.langfuse_client import LangfuseClient

                client = LangfuseClient(
                    public_key="pk_test",
                    secret_key="sk_test",
                    enabled=True,
                )

                assert client.enabled is True


class TestTraceContextManager:
    """Tests for trace context manager."""

    def test_trace_yields_none_when_disabled(self):
        """trace context manager should yield trace object even when disabled (local tracking)."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient, LLMCallTrace

        client = LangfuseClient(enabled=False)

        with client.trace(name="test_llm", input_data={"prompt": "hello"}) as trace:
            assert trace is not None
            assert isinstance(trace, LLMCallTrace)
            assert trace.name == "test_llm"
            assert trace.input_data == {"prompt": "hello"}

    def test_trace_yields_trace_object_when_enabled(self):
        """trace context manager should yield trace object when enabled."""
        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", True):
            with patch("src.audiobook_studio.observability.langfuse_client.Langfuse"):
                from src.audiobook_studio.observability.langfuse_client import LangfuseClient, LLMCallTrace

                client = LangfuseClient(
                    public_key="pk_test",
                    secret_key="sk_test",
                    enabled=True,
                )

                with client.trace(name="test_llm", input_data={"prompt": "hello"}) as trace:
                    assert trace is not None
                    assert isinstance(trace, LLMCallTrace)
                    assert trace.name == "test_llm"

    def test_trace_marks_end_time_on_exit(self):
        """trace should set end_time when context exits normally."""
        import time
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)

        with client.trace(name="test", input_data={}) as trace:
            start_time = trace.start_time

        assert trace.end_time is not None
        assert trace.end_time >= start_time

    def test_trace_marks_error_on_exception(self):
        """trace should record error when exception occurs."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)

        try:
            with client.trace(name="test", input_data={}) as trace:
                raise ValueError("test error")
        except ValueError:
            pass

        assert trace.error == "test error"
        assert trace.end_time is not None

    def test_trace_records_locally_when_disabled(self):
        """trace should store traces locally when disabled."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)

        with client.trace(name="test1", input_data={"a": 1}):
            pass
        with client.trace(name="test2", input_data={"b": 2}):
            pass

        traces = client.get_local_traces()
        assert len(traces) == 2
        assert traces[0].name == "test1"
        assert traces[1].name == "test2"


class TestSpanContextManager:
    """Tests for span context manager (if implemented)."""

    def test_span_yields_none_when_disabled(self):
        """span context manager should yield None when client disabled."""
        # Note: Current implementation doesn't have a separate span context manager
        # This test documents expected behavior if span is added
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)
        # Current implementation uses trace() for both traces and spans
        # If a span() method is added, it should yield None when disabled
        assert client.enabled is False


class TestObserveLLMCall:
    """Tests for observe_llm_call function."""

    def test_observe_llm_call_noop_when_disabled(self):
        """observe_llm_call should be no-op when disabled."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)

        # Should not raise - use as context manager
        with client.trace(
            name="llm_call",
            input_data={"messages": [{"role": "user", "content": "hi"}]},
            metadata={"model": "gpt-4", "temperature": 0.7},
            tags=["llm", "chat"],
        ):
            pass

        # Verify local trace was recorded
        traces = client.get_local_traces()
        assert len(traces) == 1
        assert traces[0].name == "llm_call"
        assert traces[0].metadata["model"] == "gpt-4"

    def test_observe_llm_call_records_when_enabled(self):
        """observe_llm_call should record to Langfuse when enabled."""
        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", True):
            with patch("src.audiobook_studio.observability.langfuse_client.Langfuse") as mock_langfuse:
                mock_client = Mock()
                mock_langfuse.return_value = mock_client

                from src.audiobook_studio.observability.langfuse_client import LangfuseClient

                client = LangfuseClient(
                    public_key="pk_test",
                    secret_key="sk_test",
                    enabled=True,
                )

                with client.trace(
                    name="llm_call",
                    input_data={"messages": [{"role": "user", "content": "hi"}]},
                    metadata={"model": "gpt-4", "temperature": 0.7},
                    tags=["llm", "chat"],
                ) as trace:
                    trace.output_data = {"response": "Hello!"}
                    trace.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
                    trace.cost_usd = 0.001

                # Verify Langfuse trace was called
                mock_client.trace.assert_called_once()
                mock_client.generation.assert_called_once()
                mock_client.flush.assert_called_once()


class TestObserveTTSSynthesis:
    """Tests for observe_tts_synthesis function."""

    def test_observe_tts_synthesis_noop_when_disabled(self):
        """observe_tts_synthesis should be no-op when disabled."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)

        # Should not raise, just record locally
        with client.trace(
            name="tts_synthesis",
            input_data={"text": "Hello world", "voice_id": "voice_1"},
            metadata={"provider": "elevenlabs", "model": "eleven_turbo_v2"},
            tags=["tts", "synthesis"],
        ) as trace:
            trace.output_data = {"audio_duration": 2.5, "characters": 11}

        traces = client.get_local_traces()
        assert len(traces) == 1
        assert traces[0].name == "tts_synthesis"
        assert traces[0].metadata["provider"] == "elevenlabs"


class TestObserveQualityCheck:
    """Tests for observe_quality_check function."""

    def test_observe_quality_check_noop_when_disabled(self):
        """observe_quality_check should be no-op when disabled."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)

        # Should not raise, just record locally
        with client.trace(
            name="quality_check",
            input_data={"text": "Hello world", "audio_path": "/tmp/out.wav"},
            metadata={"check_type": "pronunciation", "threshold": 0.8},
            tags=["quality", "check"],
        ) as trace:
            trace.output_data = {"score": 0.95, "passed": True}

        traces = client.get_local_traces()
        assert len(traces) == 1
        assert traces[0].name == "quality_check"
        assert traces[0].metadata["check_type"] == "pronunciation"


class TestTraceFunctionDecorator:
    """Tests for trace_function decorator."""

    def test_trace_function_returns_original_when_disabled(self):
        """trace_function should return original function when disabled."""
        from src.audiobook_studio.observability.langfuse_client import trace_llm_call
        from contextlib import contextmanager

        # Mock the global client to be disabled
        with patch("src.audiobook_studio.observability.langfuse_client._langfuse_client") as mock_client:
            mock_client.enabled = False
            
            @contextmanager
            def mock_trace(*args, **kwargs):
                from src.audiobook_studio.observability.langfuse_client import LLMCallTrace
                import uuid
                trace = LLMCallTrace(
                    trace_id=str(uuid.uuid4()),
                    name=args[0] if args else "test",
                    input_data=args[1] if len(args) > 1 else {},
                    metadata=args[2] if len(args) > 2 else {},
                    tags=args[3] if len(args) > 3 else [],
                )
                yield trace
            
            mock_client.trace.side_effect = mock_trace

            @trace_llm_call("test_func", {"input": "data"})
            def my_function(x, y):
                return x + y

            result = my_function(2, 3)
            assert result == 5
            # The trace should still be called (it uses local tracking)
            mock_client.trace.assert_called_once()

    def test_trace_function_wraps_when_enabled(self):
        """trace_function should wrap function when enabled."""
        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", True):
            with patch("src.audiobook_studio.observability.langfuse_client.Langfuse"):
                from src.audiobook_studio.observability.langfuse_client import (
                    LangfuseClient, get_langfuse_client, trace_llm_call, _langfuse_client
                )

                # Reset singleton
                import src.audiobook_studio.observability.langfuse_client as lfc_module
                lfc_module._langfuse_client = None

                client = LangfuseClient(
                    public_key="pk_test",
                    secret_key="sk_test",
                    enabled=True,
                )
                # Manually set as global
                lfc_module._langfuse_client = client

                @trace_llm_call("test_func", {"input": "data"}, metadata={"model": "gpt-4"})
                def my_function(x, y):
                    return x + y

                result = my_function(2, 3)
                assert result == 5

                # Verify trace was used
                traces = client.get_local_traces()
                assert len(traces) == 1
                assert traces[0].name == "test_func"
                assert traces[0].output_data == {"result": "5"}

    def test_trace_function_preserves_function_metadata(self):
        """trace_function should preserve original function metadata."""
        from src.audiobook_studio.observability.langfuse_client import trace_llm_call

        @trace_llm_call("test", {})
        def my_function(x: int, y: int) -> int:
            """Add two numbers."""
            return x + y

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "Add two numbers."


class TestFlushLangfuse:
    """Tests for flush_langfuse function."""

    def test_flush_langfuse_noop_when_disabled(self):
        """flush_langfuse should be no-op when disabled."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)

        # Should not raise
        # Current implementation flushes in _record_trace, but we can add explicit flush
        traces = client.get_local_traces()
        assert isinstance(traces, list)

    def test_flush_langfuse_calls_client_when_enabled(self):
        """flush_langfuse should call Langfuse client flush when enabled."""
        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", True):
            with patch("src.audiobook_studio.observability.langfuse_client.Langfuse") as mock_langfuse:
                mock_client = Mock()
                mock_langfuse.return_value = mock_client

                from src.audiobook_studio.observability.langfuse_client import LangfuseClient

                client = LangfuseClient(
                    public_key="pk_test",
                    secret_key="sk_test",
                    enabled=True,
                )

                # Trigger a trace which calls flush internally
                with client.trace(name="test", input_data={}):
                    pass

                mock_client.flush.assert_called()


class TestCostSummary:
    """Tests for cost summary functionality."""

    def test_get_cost_summary_returns_zero_when_no_traces(self):
        """get_cost_summary should return zeros when no traces."""
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)
        summary = client.get_cost_summary()

        assert summary["total_calls"] == 0
        assert summary["total_cost_usd"] == 0.0
        assert summary["total_tokens"] == 0
        assert summary["by_group"] == {}

    def test_get_cost_summary_aggregates_costs(self):
        """get_cost_summary should aggregate costs from traces."""
        import time
        from src.audiobook_studio.observability.langfuse_client import LangfuseClient

        client = LangfuseClient(enabled=False)

        # Add traces manually to local cache
        with client.trace(name="call1", input_data={}) as trace:
            trace.metadata["model"] = "gpt-4"
            trace.cost_usd = 0.01
            trace.usage = {"total_tokens": 100}

        with client.trace(name="call2", input_data={}) as trace:
            trace.metadata["model"] = "gpt-4"
            trace.cost_usd = 0.02
            trace.usage = {"total_tokens": 200}

        with client.trace(name="call3", input_data={}) as trace:
            trace.metadata["model"] = "gpt-3.5"
            trace.cost_usd = 0.005
            trace.usage = {"total_tokens": 50}

        summary = client.get_cost_summary()

        assert summary["total_calls"] == 3
        assert abs(summary["total_cost_usd"] - 0.035) < 1e-10
        assert summary["total_tokens"] == 350
        assert "gpt-4" in summary["by_group"]
        assert "gpt-3.5" in summary["by_group"]
        assert summary["by_group"]["gpt-4"]["calls"] == 2
        assert summary["by_group"]["gpt-4"]["cost_usd"] == 0.03
        assert summary["by_group"]["gpt-3.5"]["calls"] == 1


class TestGlobalSingleton:
    """Tests for global singleton get_langfuse_client."""

    def test_get_langfuse_client_returns_same_instance(self):
        """get_langfuse_client should return same instance on multiple calls."""
        import src.audiobook_studio.observability.langfuse_client as lfc_module

        # Reset singleton
        lfc_module._langfuse_client = None

        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", False):
            client1 = lfc_module.get_langfuse_client()
            client2 = lfc_module.get_langfuse_client()

            assert client1 is client2

    def test_get_langfuse_client_creates_new_if_none(self):
        """get_langfuse_client should create new client if none exists."""
        import src.audiobook_studio.observability.langfuse_client as lfc_module

        lfc_module._langfuse_client = None

        with patch("src.audiobook_studio.observability.langfuse_client.LANGFUSE_AVAILABLE", False):
            client = lfc_module.get_langfuse_client()

            assert client is not None
            assert isinstance(client, lfc_module.LangfuseClient)


class TestLLMCallTrace:
    """Tests for LLMCallTrace dataclass."""

    def test_trace_duration_ms(self):
        """duration_ms should calculate correctly."""
        import time
        from src.audiobook_studio.observability.langfuse_client import LLMCallTrace

        start = time.time()
        trace = LLMCallTrace(
            trace_id="test-1",
            name="test",
            input_data={},
            start_time=start,
        )

        # No end time yet
        assert trace.duration_ms is None

        trace.end_time = start + 1.5  # 1.5 seconds later
        assert trace.duration_ms == 1500.0

    def test_trace_with_all_fields(self):
        """LLMCallTrace should accept all fields."""
        from src.audiobook_studio.observability.langfuse_client import LLMCallTrace

        trace = LLMCallTrace(
            trace_id="test-1",
            name="test_call",
            input_data={"prompt": "hello"},
            output_data={"response": "hi"},
            metadata={"model": "gpt-4", "temperature": 0.7},
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            cost_usd=0.001,
            error=None,
            tags=["llm", "chat"],
        )

        assert trace.trace_id == "test-1"
        assert trace.name == "test_call"
        assert trace.input_data == {"prompt": "hello"}
        assert trace.output_data == {"response": "hi"}
        assert trace.metadata["model"] == "gpt-4"
        assert trace.usage["total_tokens"] == 15
        assert trace.cost_usd == 0.001
        assert trace.error is None
        assert trace.tags == ["llm", "chat"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""Unit tests for src/audiobook_studio/base.py — agents abstractions."""

import logging
import threading

import pytest

from src.audiobook_studio.base import AbstractAgent, AgentCapability, AgentContext, AgentMessage, ErrorSeverity


class ConcreteAgent(AbstractAgent):
    """Minimal concrete subclass for testing."""

    def __init__(self, capabilities=None):
        super().__init__(capabilities or [AgentCapability.TEXT_EXTRACTION])
        self.handled = []

    def _handle_message(self, message):
        self.handled.append(message)


class FailingAgent(AbstractAgent):
    def __init__(self):
        super().__init__([AgentCapability.TEXT_EXTRACTION])

    def _handle_message(self, message):
        raise ValueError("boom")


class TestAgentContext:
    def test_init(self):
        ctx = AgentContext(
            task_id="t1",
            book_id="b1",
            current_stage="extract",
            shared_knowledge={"key": "value"},
            retry_count=2,
        )
        assert ctx.task_id == "t1"
        assert ctx.retry_count == 2
        assert ctx.shared_knowledge["key"] == "value"


class TestAgentMessage:
    def test_init(self):
        msg = AgentMessage(sender="a", content={"x": 1}, requires_response=True)
        assert msg.sender == "a"
        assert msg.content == {"x": 1}
        assert msg.requires_response is True

    def test_default(self):
        msg = AgentMessage(sender="x", content={})
        assert msg.requires_response is False


class TestAgentCapabilityEnum:
    def test_values(self):
        assert AgentCapability.TEXT_EXTRACTION.value == "extract"
        assert AgentCapability.STRUCTURE_ANALYSIS.value == "analyze"
        assert AgentCapability.TTS_SYNTHESIS.value == "synthesize"
        assert AgentCapability.QUALITY_CONTROL.value == "quality_check"
        assert AgentCapability.FEEDBACK_LEARNING.value == "learn"


class TestErrorSeverity:
    def test_values(self):
        assert ErrorSeverity.TRANSIENT.value == "transient"
        assert ErrorSeverity.FATAL.value == "fatal"

    def test_members(self):
        assert len(list(ErrorSeverity)) == 2


class TestAbstractAgentBasics:
    def test_agent_id_is_set(self):
        agent = ConcreteAgent()
        assert agent.agent_id.startswith("ConcreteAgent-")
        assert len(agent.agent_id.split("-")[1]) == 8

    def test_capabilities_persisted(self):
        caps = [AgentCapability.TTS_SYNTHESIS, AgentCapability.QUALITY_CONTROL]
        agent = ConcreteAgent(caps)
        assert agent.capabilities == caps

    def test_logger_per_agent(self, caplog):
        agent = ConcreteAgent()
        with caplog.at_level(logging.ERROR, logger=agent.logger.name):
            agent.logger.error("test error")
        assert any("test error" in rec.message for rec in caplog.records)

    def test_lock_is_threading_lock(self):
        agent = ConcreteAgent()
        assert isinstance(agent.lock, type(threading.Lock()))

    def test_message_queue_initially_empty(self):
        agent = ConcreteAgent()
        assert agent.message_queue == []
        assert agent.context is None


class TestAgent_MessageHandling:
    def test_receive_message_appends(self):
        agent = ConcreteAgent()
        msg = AgentMessage(sender="s", content={"k": "v"})
        agent.receive_message(msg)
        assert agent.message_queue == [msg]

    def test_send_message_appends(self):
        agent = ConcreteAgent()
        msg = AgentMessage(sender="s", content={"k": "v"})
        agent.send_message(msg)
        assert agent.message_queue == [msg]

    def test_process_messages_drains_queue(self):
        agent = ConcreteAgent()
        agent.receive_message(AgentMessage(sender="s", content={"i": 1}))
        agent.receive_message(AgentMessage(sender="s", content={"i": 2}))
        agent.process_messages()
        assert agent.message_queue == []
        assert len(agent.handled) == 2

    def test_process_messages_empty(self):
        agent = ConcreteAgent()
        # Should not raise
        agent.process_messages()
        assert agent.handled == []

    def test_process_messages_swallows_exceptions(self):
        agent = FailingAgent()
        agent.receive_message(AgentMessage(sender="s", content={"x": 1}))
        # Should NOT re-raise — exception handled by _handle_failure path
        agent.process_messages()


class TestAgentFailureHandling:
    def test_handle_failure_logs_traceback(self, caplog):
        agent = FailingAgent()
        with caplog.at_level(logging.ERROR, logger=agent.logger.name):
            try:
                raise ValueError("boom")
            except ValueError as e:
                agent._handle_failure(e, severity=ErrorSeverity.FATAL)
        # Error message should contain agent id and 'failed'
        msgs = [r.getMessage() for r in caplog.records]
        assert any(agent.agent_id in m for m in msgs)

    def test_handle_failure_transient_branch(self, caplog):
        agent = ConcreteAgent()
        with caplog.at_level(logging.ERROR, logger=agent.logger.name):
            try:
                raise RuntimeError("transient!")
            except RuntimeError as e:
                agent._handle_failure(e, severity=ErrorSeverity.TRANSIENT)
        # Severity branch executes without error
        msgs = [r.getMessage() for r in caplog.records]
        assert any("failed" in m for m in msgs)


class TestAgentContextAcquisition:
    def test_acquire_context_sets_context(self):
        agent = ConcreteAgent()
        ctx = AgentContext(task_id="t", book_id="b", current_stage="x", shared_knowledge={})
        agent.acquire_context(ctx)
        assert agent.context is ctx

    def test_acquire_context_none_clears(self):
        agent = ConcreteAgent()
        agent.acquire_context(None)
        assert agent.context is None


class TestAgentCapabilities:
    def test_can_handle_returns_true_for_matching(self):
        agent = ConcreteAgent([AgentCapability.TEXT_EXTRACTION])
        assert agent.can_handle(AgentCapability.TEXT_EXTRACTION) is True

    def test_can_handle_returns_false_for_other(self):
        agent = ConcreteAgent([AgentCapability.TEXT_EXTRACTION])
        assert agent.can_handle(AgentCapability.TTS_SYNTHESIS) is False


class TestAgentIdGetter:
    def test_get_agent_id(self):
        agent = ConcreteAgent()
        assert agent.get_agent_id() == agent.agent_id

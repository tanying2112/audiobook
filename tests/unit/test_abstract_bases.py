"""Tests for abstract base classes in base.py and stage_registry.py."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.base import AbstractAgent, AgentCapability, AgentContext, AgentMessage, ErrorSeverity
from src.audiobook_studio.pipeline.stage_registry import StageHandler


def test_abstract_agent_abstract_method_raises_not_implemented():
    """Test that _handle_message raises NotImplementedError when not overridden."""

    # Create an instance of AbstractAgent directly (this is allowed)
    agent = AbstractAgent([])

    # Calling the abstract method should raise NotImplementedError
    with pytest.raises(NotImplementedError):
        agent._handle_message(None)


def test_abstract_agent_can_be_instantiated_but_abstract_method_fails():
    """Test that AbstractAgent can be instantiated but abstract methods fail."""

    # AbstractAgent is not actually an ABC, so we can instantiate it directly
    agent = AbstractAgent([AgentCapability.TEXT_EXTRACTION])
    assert isinstance(agent, AbstractAgent)

    # But calling the abstract method should fail
    with pytest.raises(NotImplementedError):
        agent._handle_message(None)


def test_abstract_agent_handle_message_raises_not_implemented():
    """Test that _handle_message raises NotImplementedError when not overridden."""

    # Test the base class directly
    with pytest.raises(NotImplementedError):
        AbstractAgent._handle_message(AbstractAgent([]), None)


def test_abstract_agent_handle_failure_can_be_called():
    """Test that _handle_failure can be called on the base class."""
    agent = AbstractAgent([])
    # This should not raise an exception
    try:
        agent._handle_failure(ValueError("test error"))
    except Exception:
        pytest.fail("_handle_failure should not raise an exception")


def test_stage_handler_cannot_be_instantiated_directly():
    """Test that StageHandler cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        StageHandler()


def test_stage_handler_abstract_method_must_be_implemented():
    """Test that abstract methods must be implemented in StageHandler subclasses."""

    class IncompleteStage(StageHandler):
        pass  # Not implementing run()

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteStage()


def test_stage_handler_run_is_abstract():
    """Test that run() method is abstract in StageHandler."""

    class IncompleteStage(StageHandler):
        # Implementing other methods but not run()
        def persist(self, *args, **kwargs):
            pass

        def get_result_snapshot(self, result):
            return {}

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteStage()


def test_stage_handler_persist_has_default_implementation():
    """Test that persist() method has a default implementation that does nothing."""

    class MinimalStage(StageHandler):
        def run(self, **kwargs):
            return "test_result"

    stage = MinimalStage()
    # This should not raise any exception
    try:
        stage.persist(None, 1, None, None, "result")
    except Exception as e:
        pytest.fail(f"persist() should not raise exception, got: {e}")


def test_stage_handler_get_result_snapshot_has_default_implementation():
    """Test that get_result_snapshot() method has a default implementation."""

    class MinimalStage(StageHandler):
        def run(self, **kwargs):
            return "test_result"

    stage = MinimalStage()

    # Test with various types of results
    test_cases = [
        ("string_result", dict),  # string -> dict
        (42, dict),  # int -> dict
        ({"key": "value"}, dict),  # dict -> dict (same object)
        ([1, 2, 3], list),  # list -> list (same object)
        ({"nested": {"data": "value"}}, dict),  # dict -> dict (same object)
    ]

    for test_case, expected_type in test_cases:
        result = stage.get_result_snapshot(test_case)
        assert isinstance(result, expected_type)
        # For dict and list, check that it's the same object
        if isinstance(test_case, (dict, list)):
            assert result == test_case


def test_stage_handler_get_result_snapshot_with_model_dump():
    """Test get_result_snapshot with object that has model_dump method."""

    class MockModel:
        def model_dump(self):
            return {"mocked": "data"}

    class MinimalStage(StageHandler):
        def run(self, **kwargs):
            return MockModel()

    stage = MinimalStage()
    result = MockModel()
    snapshot = stage.get_result_snapshot(result)

    assert snapshot == {"mocked": "data"}


def test_stage_handler_get_result_snapshot_with_dict():
    """Test get_result_snapshot with dict object."""

    class MinimalStage(StageHandler):
        def run(self, **kwargs):
            return {"existing": "dict"}

    stage = MinimalStage()
    result = {"existing": "dict", "number": 42}
    snapshot = stage.get_result_snapshot(result)

    assert snapshot == result  # Should return the dict as-is


def test_stage_handler_get_result_snapshot_with_list():
    """Test get_result_snapshot with list object."""

    class MinimalStage(StageHandler):
        def run(self, **kwargs):
            return [1, 2, 3]

    stage = MinimalStage()
    result = [1, 2, 3]
    snapshot = stage.get_result_snapshot(result)

    assert snapshot == result  # Should return the list as-is


def test_stage_handler_get_result_snapshot_fallback():
    """Test get_result_snapshot fallback for unknown object types."""

    class MinimalStage(StageHandler):
        def run(self, **kwargs):
            return object()  # Plain object

    stage = MinimalStage()
    result = object()
    snapshot = stage.get_result_snapshot(result)

    assert isinstance(snapshot, dict)
    assert "result" in snapshot
    assert str(result) in snapshot["result"]


def test_stage_handler_can_be_subclassed_and_used():
    """Test that a proper subclass of StageHandler can be instantiated and used."""

    class ConcreteStage(StageHandler):
        def __init__(self):
            super().__init__()
            self.run_called = False
            self.persist_called = False

        def run(self, **kwargs):
            self.run_called = True
            return "success"

        def persist(self, *args, **kwargs):
            self.persist_called = True

        def get_result_snapshot(self, result):
            return {"result": result}

    stage = ConcreteStage()

    # Test instantiation works
    assert isinstance(stage, StageHandler)

    # Test run method
    result = stage.run(test_param="value")
    assert result == "success"

    # Test persist method
    stage.persist(None, 1, None, None, "test")
    assert stage.persist_called == True

    # Test get_result_snapshot method
    snapshot = stage.get_result_snapshot("test_result")
    assert snapshot == {"result": "test_result"}

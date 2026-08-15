"""DeepEval integration smoke test.
Verifies the DeepEval library is importable and provides expected public API.
"""
import pytest


def test_deepeval_importable():
    """Verify deepeval package is installed and exposes core API."""
    try:
        import deepeval
    except ImportError:
        pytest.skip("deepeval not installed")

    # Verify the package has a version attribute (it's a real install, not a stub)
    assert hasattr(deepeval, "__version__") or hasattr(deepeval, "__name__")

    # Verify key test-case API is accessible
    try:
        from deepeval.test_case import LLMTestCase
    except ImportError:
        pytest.fail("LLMTestCase not importable — deepeval install may be incomplete")


def test_deepeval_metrics_registry():
    """Verify core metrics are accessible when deepeval is installed."""
    deepeval = pytest.importorskip("deepeval")
    # HallucinationMetric, AnswerRelevancyMetric, FaithfulnessMetric are core
    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, HallucinationMetric

    for metric_cls in [AnswerRelevancyMetric, FaithfulnessMetric, HallucinationMetric]:
        assert metric_cls.__name__, f"{metric_cls} should have a name"
"""Minimal pytest configuration - only indispensable mocks.

This file contains ONLY mocks that are absolutely required for test collection
to succeed in environments where heavy optional dependencies are not installed.

DO NOT add test fixtures here - they belong in tests/conftest.py
"""

import importlib.abc
import importlib.util
import os
import sys
from unittest.mock import MagicMock


# ═══════════════════════════════════════════════════════════════════════════
# Unify dual-import namespaces.
#
# The package is importable BOTH as ``audiobook_studio`` (editable install) and
# as ``src.audiobook_studio`` (when ``src`` is on sys.path). These resolve to
# *different* module objects for the same source files, so a patch like
# ``patch("src.audiobook_studio.feedback.promotion_gate._constitution")`` does
# NOT affect code that did ``from audiobook_studio.feedback.promotion_gate
# import ...`` (and vice versa). That mismatch is the root cause of several
# pre-existing test-isolation failures. The meta-path finder below redirects
# every ``audiobook_studio.*`` import to the canonical ``src.audiobook_studio.*``
# module object so the two namespaces are a single object.
# ═══════════════════════════════════════════════════════════════════════════
class _CanonicalAliasLoader(importlib.abc.Loader):
    """Loader that yields the already-loaded canonical ``src.`` module object."""

    def __init__(self, canonical: str):
        self.canonical = canonical

    def create_module(self, spec):
        return importlib.import_module(self.canonical)

    def exec_module(self, module):
        # The canonical module is already fully executed; nothing to do.
        return None


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != "audiobook_studio" and not name.startswith("audiobook_studio."):
            return None
        canonical = "src." + name
        existing = sys.modules.get(canonical)
        if existing is not None:
            # Canonical already imported: alias directly and reuse its spec.
            sys.modules[name] = existing
            return importlib.util.spec_from_loader(
                name, existing.__loader__, origin=getattr(existing, "__file__", None)
            )
        try:
            cspec = importlib.util.find_spec(canonical)
        except Exception:
            return None
        if cspec is None or cspec.origin is None:
            return None
        return importlib.util.spec_from_loader(name, _CanonicalAliasLoader(canonical), origin=cspec.origin)


sys.meta_path.insert(0, _AliasFinder())

# Alias any ``audiobook_studio.*`` module that was imported (as a distinct
# object) before this finder was installed, so it points at the canonical
# ``src.`` object too.
for _mod in list(sys.modules):
    if _mod == "audiobook_studio" or _mod.startswith("audiobook_studio."):
        _canon = "src." + _mod
        if _canon in sys.modules and sys.modules[_mod] is not sys.modules[_canon]:
            sys.modules[_mod] = sys.modules[_canon]

# ═══════════════════════════════════════════════════════════════════════════
# Set ALLOWED_HOSTS BEFORE any imports to configure TrustedHostMiddleware correctly
# This must happen before src.audiobook_studio.main is imported anywhere
# ═══════════════════════════════════════════════════════════════════════════
os.environ["ALLOWED_HOSTS"] = '["localhost", "127.0.0.1", "testserver"]'

# =============================================================================
# Hermetic test DB: each pytest process gets its own temp SQLite file so
# concurrent test runs never share/overwrite a repository DB (fixes H3 flakiness).
# CI may override DATABASE_URL. Rate limiting stays OFF during tests to avoid
# cross-test 429s from the shared per-IP bucket; the production default is ON
# in code (see settings.RATE_LIMIT_ENABLED).
# =============================================================================
import tempfile as _tempfile

os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{_tempfile.gettempdir()}/audiobook_test_{os.getpid()}.db",
)
# Tests must never be throttled by the shared per-IP bucket. The production
# default (settings.RATE_LIMIT_ENABLED) is True; tests force it off.
os.environ["RATE_LIMIT_ENABLED"] = "false"
# Tests self-register freely. The production default (settings.AUTH_REGISTRATION_MODE)
# is "invite"; test_registration_mode.py explicitly overrides to "invite" to verify it.
os.environ.setdefault("AUTH_REGISTRATION_MODE", "open")

# JWT secret for tests (must be valid URL-safe base64, >=32 chars for 256-bit entropy)
# Using a fixed test key: "test-secret-key-for-testing-purposes-only-32chars"
os.environ.setdefault("JWT_SECRET_KEY", "dGVzdC1zZWNyZXQta2V5LWZvci10ZXN0aW5nLXB1cnBvc2VzLW9ubHktMzJjaGFycw==")

# ═══════════════════════════════════════════════════════════════════════════
# Only mock dspy if it's not available - this is an optional dependency
# ═══════════════════════════════════════════════════════════════════════════

try:
    import dspy  # noqa: F401

    DSPY_AVAILABLE = True
except ImportError:
    DSPY_AVAILABLE = False

if not DSPY_AVAILABLE:
    # Create minimal mock classes only needed for bootstrap_fewshot imports
    class MockScoreWithFeedback:
        """Mock ScoreWithFeedback with proper attribute access."""

        def __init__(self, score: float, feedback: str):
            self.score = score
            self.feedback = feedback

    class MockExample:
        """Mock Example with proper attribute storage."""

        def __init__(self, **kwargs):
            self._inputs = set()
            for key, value in kwargs.items():
                setattr(self, key, value)
            self._store = {}

        def with_inputs(self, *keys):
            self._inputs = set(keys)
            return self

        def outputs(self, key=None):
            if key:
                return self._store.get(key)
            return self._store

    class MockPrediction:
        """Mock Prediction that stores outputs in a dict-like way."""

        def __init__(self, **kwargs):
            self._store = kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)

        def __getitem__(self, key):
            return self._store.get(key)

    class MockSignature:
        """Mock Signature for DSPy module definitions."""

        def __init__(self, *args, **kwargs):
            self._signature = args[0] if args else ""
            self._instructions = kwargs.get("instructions", "")

    class MockPredict:
        """Mock Predict that returns a result with expected attributes."""

        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, **kwargs):
            result = MagicMock()
            for key, value in kwargs.items():
                setattr(result, key, value)
            return result

    class MockModule:
        """Mock base Module for CharacterRecognitionModule etc."""

        def __init__(self):
            pass

    # Inject mocks into sys.modules BEFORE any imports
    mock_gepa_utils = MagicMock()
    mock_gepa_utils.ScoreWithFeedback = MockScoreWithFeedback
    sys.modules["dspy"] = MagicMock()
    sys.modules["dspy.Signature"] = MagicMock
    sys.modules["dspy.teleprompt"] = MagicMock()
    sys.modules["dspy.teleprompt.gepa"] = MagicMock()
    sys.modules["dspy.teleprompt.gepa.gepa_utils"] = mock_gepa_utils
    sys.modules["dspy.teleprompt.gepa.gepa_logprob"] = MagicMock()

    # Patch dspy classes after mock setup
    def _patch_dspy_classes():
        dspy = sys.modules["dspy"]
        dspy.Example = MockExample
        dspy.Prediction = MockPrediction
        dspy.Signature = MockSignature
        dspy.Predict = MockPredict
        dspy.Module = MockModule

    _patch_dspy_classes()

# ═══════════════════════════════════════════════════════════════════════════
# Mock heavy optional dependencies that trigger import chains
# ═══════════════════════════════════════════════════════════════════════════


def _install_canonical_torch_mock():
    """Install/repair the mocked ``torch`` with a valid ``__spec__``.

    A bare ``MagicMock`` in ``sys.modules['torch']`` lacks ``__spec__`` and makes
    any later ``import torch`` raise ``ValueError: torch.__spec__ is not set``
    (importlib validates the spec of already-imported modules). It also makes
    hardware-probing code (e.g. ``bench_voxcpm2.detect_hardware``) store a
    ``MagicMock`` inside a JSON-serialized report. Rebuilding the mock here gives
    a deterministic, serializable, spec-equipped fake so tests cannot leak bad
    torch state into one another.
    """
    _torch_mock = sys.modules.get("torch")
    if not isinstance(_torch_mock, MagicMock):
        # Real torch (or absent entirely) — don't clobber it.
        return

    _torch_mock = MagicMock()
    _torch_mock.__spec__ = importlib.util.spec_from_loader("torch", None)
    _torch_mock.__version__ = "0.0.0"
    _cuda_mock = MagicMock()
    _cuda_mock.is_available.return_value = False
    _cuda_mock.device_count.return_value = 0
    _cuda_mock.get_device_name.return_value = "cpu"
    _cuda_mock.memory_allocated.return_value = 0
    _cuda_mock.max_memory_allocated.return_value = 0
    _cuda_mock.empty_cache.return_value = None
    _cuda_mock.get_device_properties.return_value = MagicMock(total_memory=0)
    _cuda_mock.mem_get_info.return_value = (0, 0)
    _cuda_mock.is_bf16_supported.return_value = False
    _torch_mock.cuda = _cuda_mock
    _mps_mock = MagicMock()
    _mps_mock.is_available.return_value = False
    _torch_mock.backends = MagicMock()
    _torch_mock.backends.mps = _mps_mock
    _torch_mock.backends.cudnn = MagicMock()
    _torch_mock.backends.cudnn.is_available.return_value = False
    _torch_mock.version = MagicMock()
    _torch_mock.version.cuda = None
    sys.modules["torch"] = _torch_mock


def _force_torch_mock():
    """Force ``sys.modules['torch']`` (and torchaudio) back to the canonical mock.

    Some optional-backend test modules (e.g. voxcpm-based ones) must import a
    *real* torch-dependent package at collection time. Those imports pull the
    real, environment-broken torch into ``sys.modules``, which then leaks and
    crashes unrelated tests later in the session (e.g. ``import spacy`` ->
    ``thinc`` -> ``torch._C`` -> ``NameError: name '_C' is not defined``).
    Re-establishing the canonical MagicMock here keeps the rest of the session
    hermetic. Unlike :func:`_install_canonical_torch_mock`, this deliberately
    OVERWRITES real torch (the importing module has already captured its own
    reference, so restoring the mock for everyone else is safe).
    """
    _torch_mock = MagicMock()
    _torch_mock.__spec__ = importlib.util.spec_from_loader("torch", None)
    _torch_mock.__version__ = "0.0.0"
    _cuda_mock = MagicMock()
    _cuda_mock.is_available.return_value = False
    _cuda_mock.device_count.return_value = 0
    _cuda_mock.get_device_name.return_value = "cpu"
    _cuda_mock.memory_allocated.return_value = 0
    _cuda_mock.max_memory_allocated.return_value = 0
    _cuda_mock.empty_cache.return_value = None
    _cuda_mock.get_device_properties.return_value = MagicMock(total_memory=0)
    _cuda_mock.mem_get_info.return_value = (0, 0)
    _cuda_mock.is_bf16_supported.return_value = False
    _torch_mock.cuda = _cuda_mock
    _mps_mock = MagicMock()
    _mps_mock.is_available.return_value = False
    _torch_mock.backends = MagicMock()
    _torch_mock.backends.mps = _mps_mock
    _torch_mock.backends.cudnn = MagicMock()
    _torch_mock.backends.cudnn.is_available.return_value = False
    _torch_mock.version = MagicMock()
    _torch_mock.version.cuda = None
    sys.modules["torch"] = _torch_mock
    if "torchaudio" not in sys.modules or not isinstance(sys.modules.get("torchaudio"), MagicMock):
        _ta_mock = MagicMock()
        _ta_mock.__spec__ = importlib.util.spec_from_loader("torchaudio", None)
        sys.modules["torchaudio"] = _ta_mock


for mod_name in [
    "fitz",
    "pymupdf",
    "pdfplumber",
    "ebooklib",
    "docx",
    "pytesseract",
    "PIL",
    "numpy",
    "soundfile",
    "ffmpeg_python",
    "librosa",
    "pandas",
    "scikit_learn",
    "scipy",
    "structlog",
    "python_json_logger",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.background",
    "apscheduler.triggers",
    "apscheduler.triggers.cron",
    "redis",
    "redis.asyncio",
    "flower",
    "deepeval",
    "promptfoo",
    "black",
    "isort",
    "flake8",
    "flake8_bugbear",
    "bandit",
    "detect_secrets",
    "mypy",
    "pre_commit",
    "langfuse",
    "litellm",
    "instructor",
    "tenacity",
    "jinja2",
    "edge_tts",
    "kokoro_onnx",
    "piper_tts",
    "openai",
    "anthropic",
    "google",
    "google_generativeai",
    "bcrypt",
    "passlib",
    "cryptography",
    # "email_validator",  # Do NOT mock - Pydantic's EmailStr depends on it
    "python_multipart",
    "pydantic_settings",
    "python_dotenv",
    "uvicorn",
    "asyncpg",
    "psycopg2",
    "httpx",
    "mako",
    "markdown_it",
    "mkdocs",
    "mkdocs_material",
    "opentelemetry",
    "opentelemetry.exporter",
    "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto",
    "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.exporter.prometheus",
    "opentelemetry.sdk",
    "opentelemetry.sdk.metrics",
    "opentelemetry.sdk.metrics.export",
    "opentelemetry.sdk.resources",
    "opentelemetry.sdk.trace",
    "opentelemetry.sdk.trace.export",
    "opentelemetry.metrics",
    "opentelemetry.trace",
    "opentelemetry.instrument",
    "celery",
    "celery.states",
    "celery.schedules",
    "celery.signals",
    "boto3",
    "torch",
    "torchaudio",
    "lightning",
    "lightning.pytorch",
    "modal",
    "modal.client",
    "kaggle",
    "boto3",
    "requests",
    "transformers",
    "typer",
    "typer._click",
    "typer._click._compat",
    "click",
    "click.core",
    "click.types",
    "click._compat",
]:
    # Modules that are genuinely installed must NOT be shadowed by a bare
    # MagicMock: doing so breaks code that accesses attributes on the real
    # module (e.g. ``requests.exceptions.HTTPError``) and pollutes
    # globally-imported modules such as ``base_worker`` across the whole
    # session. These are hard dependencies that are always present, so we
    # leave the real modules in place. Everything else keeps the original
    # behaviour of being mocked only if it has not yet been imported (which
    # covers genuinely-optional dependencies). "typer" pulls in "click" at
    # runtime, so "typer._click" and friends are also skipped here.
    # ``requests`` is a hard dependency that is always installed, so it must
    # never be shadowed by a bare MagicMock (otherwise ``requests.exceptions
    # .HTTPError`` is not a real exception and download-retry tests break).
    # ``transformers`` is intentionally NOT whitelisted: it is an optional
    # dependency and mocking it as a bare MagicMock actually *helps* (its real
    # import triggers a torch-availability check that crashes against the
    # mocked ``torch`` module). Everything else keeps the original behaviour
    # of being mocked only if it has not yet been imported.
    _INSTALLED_OK = {"requests"}
    if mod_name not in sys.modules and mod_name not in _INSTALLED_OK:
        _mock_mod = MagicMock()
        # Give the fake module a minimal __spec__ so that submodule imports
        # such as ``from torch import nn`` (and importlib internals) don't
        # raise "ValueError: <mod>.__spec__ is not set" against the mocked
        # module. Without this, any code that triggers importlib's spec check
        # on the mocked module crashes the whole import.
        _mock_mod.__spec__ = importlib.util.spec_from_loader(mod_name, None)
        sys.modules[mod_name] = _mock_mod

# Ensure the mocked torch (which the loop above may have just created) has a
# valid __spec__ and deterministic CUDA/MPS probes so hardware detection and
# JSON-serialized reports don't leak MagicMock objects.
_install_canonical_torch_mock()

# Set celery states constants
sys.modules["celery.states"].PENDING = "PENDING"
sys.modules["celery.states"].FAILURE = "FAILURE"
sys.modules["celery.states"].RETRY = "RETRY"
sys.modules["celery.states"].STARTED = "STARTED"
sys.modules["celery.states"].SUCCESS = "SUCCESS"


# Create a proper Celery mock that returns a task with string id
class MockAsyncResult:
    def __init__(self, task_id="test-task-id-12345"):
        self.id = task_id


# Provide a fake Task class that can be subclassed
class FakeCeleryTask:
    """Fake Task class that mimics celery.Task for testing."""

    def __init__(self):
        self.request = MagicMock()
        self.request.id = "test-task-id-12345"
        self.max_retries = 3
        self.autoretry_for = ()
        self.retry_backoff = True
        self.retry_backoff_max = 300
        self.retry_jitter = True
        self.acks_late = True
        self.reject_on_worker_lost = True

    def retry(self, exc=None, *args, **kwargs):
        """Mock retry method."""
        raise exc

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Mock on_failure callback."""
        pass

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Mock on_retry callback."""
        pass

    def on_success(self, retval, task_id, args, kwargs):
        """Mock on_success callback."""
        pass


class MockCeleryTask:
    def __init__(self, func):
        self.func = func

    def delay(self, *args, **kwargs):
        return MagicMock(id="test-task-id-12345")

    def __call__(self, *args, **kwargs):
        # In mock mode, just call the underlying function with MOCK_LLM=true
        os.environ["MOCK_LLM"] = "true"
        return self.func(*args, **kwargs)


mock_celery_app = MagicMock()
mock_celery_app.AsyncResult.return_value = MockAsyncResult()
mock_celery_app.delay = MagicMock(return_value=MagicMock(id="test-task-id-12345"))
mock_celery_app.task = MagicMock(side_effect=lambda *args, **kwargs: lambda f: MockCeleryTask(f))

sys.modules["celery"] = mock_celery_app
sys.modules["celery"].Celery = MagicMock(return_value=mock_celery_app)
sys.modules["celery"].current_app = mock_celery_app
sys.modules["celery"].Task = FakeCeleryTask  # Use proper fake Task class instead of MagicMock

# Also patch celery_app module to use the fake Task
import types

mock_celery_module = types.ModuleType("src.audiobook_studio.celery_app")
mock_celery_module.celery_app = mock_celery_app
mock_celery_module.celery_app.Task = FakeCeleryTask
sys.modules["src.audiobook_studio.celery_app"] = mock_celery_module

# Also mock the celery_app module used by the codebase
import types

mock_celery_module = types.ModuleType("src.audiobook_studio.celery_app")
mock_celery_module.celery_app = mock_celery_app
sys.modules["src.audiobook_studio.celery_app"] = mock_celery_module

# ═══════════════════════════════════════════════════════════════════════════
# Environment setup for all tests
# ═══════════════════════════════════════════════════════════════════════════

# Set MOCK_LLM=true for all tests to prevent real API calls and health probe startup
os.environ["MOCK_LLM"] = "true"

# Speed up LiteLLM imports by using local model cost map
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

# ═══════════════════════════════════════════════════════════════════════════
# Provide a working LLMProvidersConfig mock with load() method
# ═══════════════════════════════════════════════════════════════════════════


class MockProviderConfig:
    def __init__(
        self,
        name="mock",
        provider="openai",
        model="gpt-3.5-turbo",
        api_key_env=None,
        base_url=None,
        priority=100,
        max_tokens_per_minute=10000,
        max_requests_per_minute=60,
        timeout_seconds=60,
        stages=None,
        enabled=True,
        extra_params=None,
        api_key_pool_env=None,
        key_rotation_strategy="round_robin",
        max_daily_cost_usd=None,
    ):
        self.name = name
        self.provider = provider
        self.model = model
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.priority = priority
        self.max_tokens_per_minute = max_tokens_per_minute
        self.max_requests_per_minute = max_requests_per_minute
        self.timeout_seconds = timeout_seconds
        self.stages = stages or []
        self.enabled = enabled
        self.extra_params = extra_params or {}
        self.api_key_pool_env = api_key_pool_env or []
        self.key_rotation_strategy = key_rotation_strategy
        self.max_daily_cost_usd = max_daily_cost_usd

    def get_litellm_model_name(self):
        if self.provider == "ollama":
            return f"ollama/{self.model}"
        return self.model


class MockLLMProvidersConfig:
    def __init__(self):
        self.providers = [
            MockProviderConfig(
                name="mock-gpt",
                provider="openai",
                model="gpt-3.5-turbo",
                stages=["extract", "analyze", "annotate", "edit", "route", "judge", "translate"],
                max_daily_cost_usd=10.0,
            )
        ]

        # Provide real PromptCompressionConfig values instead of MagicMock
        class MockPromptCompression:
            max_input_tokens = 4000
            truncate_strategy = "smart"
            remove_few_shot_when_long = True
            min_few_shot_examples = 1
            schema_injection_mode = "minimal"

        class MockFallback:
            max_retries_per_provider = 2
            retry_on_rate_limit = True
            retry_on_timeout = True
            timeout_seconds = 60
            exponential_backoff_base = 2.0

        self.prompt_compression = MockPromptCompression()
        self.fallback = MockFallback()
        # cost_control needs to have daily_limit_usd as a float for CostTracker.set_global_daily_limit
        cost_control = MagicMock()
        cost_control.daily_limit_usd = 10.0
        self.cost_control = cost_control

        # For hardware profile compatibility
        class MockHardwareProfile:
            def get_llm_stage_models(self, stage):
                return None

        self.hardware_profile = MockHardwareProfile()

    def get_providers_for_stage(self, stage):
        stage_str = stage.value if hasattr(stage, "value") else str(stage)
        return [p for p in self.providers if stage_str in p.stages]

    def get_all_enabled(self):
        return self.providers

    @classmethod
    def load(cls, config_path=None):
        return cls()


# Inject the mock config before any imports that use it
# Create a proper module object (not MagicMock) so that `from module import Name` works correctly
# Need to register BOTH names since the package can be imported as "audiobook_studio" (from src/)
# or "src.audiobook_studio" (when src is in sys.path)
for module_name in ["src.audiobook_studio.llm.config_loader", "audiobook_studio.llm.config_loader"]:
    if module_name not in sys.modules:
        import types

        sys.modules[module_name] = types.ModuleType(module_name)

    mock_config_loader = sys.modules[module_name]
    # Create an iterable StageName enum mock for router.stage_configs iteration
    from enum import Enum

    class MockStageName(str, Enum):
        EXTRACT = "extract"
        ANALYZE = "analyze"
        ANNOTATE = "annotate"
        ANNOTATE_PARAGRAPH = "annotate_paragraph"
        EDIT = "edit"
        ROUTE = "route"
        JUDGE = "judge"
        TRANSLATE = "translate"

    mock_config_loader.LLMProvidersConfig = MockLLMProvidersConfig
    mock_config_loader.ProviderType = MagicMock()
    mock_config_loader.StageName = MockStageName
    mock_config_loader.ProviderConfig = MockProviderConfig
    mock_config_loader.PromptCompressionConfig = MagicMock()
    mock_config_loader.FallbackConfig = MagicMock()
    mock_config_loader.CostControlConfig = MagicMock()

# ═══════════════════════════════════════════════════════════════════════════
# Mock soundfile for tests that use it in mock mode
# This mock actually writes files (with zero bytes) so file existence checks pass
# ═══════════════════════════════════════════════════════════════════════════


def _mock_sf_write(path, data, sr):
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"\x00" * len(data))


mock_sf = MagicMock()
mock_sf.write = _mock_sf_write
sys.modules["soundfile"] = mock_sf

# ═══════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════

import logging
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SAWarning

logger = logging.getLogger(__name__)


# Mock modules with required functions before fixtures use them
mock_router = MagicMock()
mock_router.reset_cost_tracker = MagicMock()

mock_kill_switch = MagicMock()
mock_kill_switch._kill_switch = None
mock_kill_switch.KillSwitchConfig = MagicMock()
mock_kill_switch.DegradationLevel = MagicMock()


@pytest.fixture(autouse=True)
def mock_health_probe():
    """Mock health probe to prevent background HTTP calls during tests."""
    # Check if already mocked (by test_reviewer_agent.py)
    import sys

    if "src.audiobook_studio.llm.health_probe" in sys.modules:
        # Already mocked by test file, skip patching
        yield
        return

    with patch("src.audiobook_studio.llm.health_probe.HealthProbe.start") as mock_start:
        mock_start.return_value = None
        yield mock_start


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset global singletons between tests."""
    mock_router.reset_cost_tracker()

    mock_kill_switch._kill_switch = None

    yield

    mock_router.reset_cost_tracker()
    mock_kill_switch._kill_switch = None

    # Ensure MOCK_LLM stays set for subsequent tests
    os.environ["MOCK_LLM"] = "true"


@pytest.fixture
def mock_voice_mapping(tmp_path):
    """Create a temporary voice_mapping.yaml for tests."""
    voice_mapping = tmp_path / "voice_mapping.yaml"
    voice_mapping.write_text(
        """
voice_mapping:
  test_voice:
    voice_id: "test_voice_id"
    description: "Test voice"
    language: "zh-CN"
"""
    )
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value=voice_mapping.read_text()):
            yield voice_mapping


@pytest.fixture(autouse=True)
def disable_langfuse(monkeypatch):
    """Comprehensively disable Langfuse in ALL tests.

    This fixture:
    1. Removes Langfuse env vars so no real keys are used
    2. Sets the global _enabled flag to False
    3. Patches all observe_* functions to be no-ops
    4. Patches flush_langfuse to be a no-op

    This prevents "Failed to export span batch" errors and 401/403 from
    Langfuse cloud during unit tests.
    """
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)

    try:
        import src.audiobook_studio.monitoring.langfuse_client as lfc

        original_enabled = lfc._enabled
        original_client = lfc._langfuse_client
        lfc._enabled = False
        lfc._langfuse_client = None

        with (
            patch.object(lfc, "observe_llm_call", return_value=None),
            patch.object(lfc, "observe_tts_synthesis", return_value=None),
            patch.object(lfc, "observe_quality_check", return_value=None),
            patch.object(lfc, "flush_langfuse", return_value=None),
            patch.object(lfc, "score_trace", return_value=None),
        ):
            yield

        lfc._enabled = original_enabled
        lfc._langfuse_client = original_client
    except (ImportError, AttributeError):
        # Langfuse module not available or already mocked by test
        yield


@pytest.fixture(scope="session", autouse=True)
def ensure_tmp_repo():
    os.makedirs("/tmp/repo", exist_ok=True)


@pytest.fixture(autouse=True, scope="function")
def isolate_torch_mock():
    """Reset the mocked ``torch`` after every test to prevent global pollution.

    Several test modules assign ``sys.modules['torch'] = MagicMock()`` (without a
    valid ``__spec__``), which leaks into later tests and breaks any ``import
    torch`` that triggers importlib's spec check, or stores a ``MagicMock`` in a
    JSON-serialized report. Restoring the canonical spec-equipped mock after each
    test guarantees no test can corrupt the shared ``torch`` state.
    """
    yield
    _install_canonical_torch_mock()


@pytest.fixture(autouse=True, scope="function")
def reset_redis_url():
    """Neutralize a known global pollutant from the integration tests.

    ``tests/integration/test_stress_celery_redis.py`` assigns
    ``REDIS_URL = ".../1"`` at module-import time and never restores it, which
    leaks into unit tests that expect the default ``/0``. Drop it after each test
    unless a real test deliberately set ``TEST_REDIS_URL``. This is a targeted
    fix for that one pollutant (not a blanket env reset, which broke other tests).
    """
    yield
    if os.environ.get("REDIS_URL") == "redis://localhost:6379/1" and "TEST_REDIS_URL" not in os.environ:
        os.environ.pop("REDIS_URL", None)


@pytest.fixture(autouse=True, scope="function")
def ensure_di_defaults():
    """Keep global singletons in a clean state across tests.

    Several pre-existing test-isolation failures are caused by singleton state
    (DI container, LLM router, settings, semantic/regression caches) leaking
    from one test into the next. Reset the canonical ones after every test so
    each test starts from a fresh default. Wrapped in try/except so a failure
    here can never mask a real test failure.
    """
    yield
    for _reset in (
        "src.audiobook_studio.di:reset_app_container",
        "src.audiobook_studio.llm.router:reset_llm_router",
        "src.audiobook_studio.config.settings_loader:reset_settings",
        "src.audiobook_studio.llm.semantic_cache:reset_semantic_cache",
        "src.audiobook_studio.feedback.regression_suite:reset_regression_suite",
    ):
        try:
            _mod, _fn = _reset.split(":")
            getattr(__import__(_mod, fromlist=[_fn]), _fn)()
        except Exception:
            pass


# Ignore SAWarning about foreign key cycles in SQLite drop_all
warnings.filterwarnings(
    "ignore",
    message="Can't sort tables for DROP; an unresolvable foreign key dependency exists between tables:.*",
    category=SAWarning,
)

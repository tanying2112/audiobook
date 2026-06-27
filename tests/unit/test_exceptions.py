"""Tests for audiobook_studio exceptions module."""

import pytest
from src.audiobook_studio.exceptions import (
    AudiobookError,
    DomainError,
    ValidationError,
    SchemaComplianceError,
    FallbackUsedError,
    ProviderError,
    QuotaExceededError,
    RateLimitError,
    CircuitOpenError,
    ProviderUnavailableError,
    ProviderTimeoutError,
    InfrastructureError,
    DatabaseError,
    FileWriteError,
    ConfigError,
    PipelineError,
    StageExecutionError,
    StageHookError,
    DataLoadError,
    DataPersistError,
    TTSError,
    TTSModelLoadError,
    TTSSynthesisError,
    TTSAudioExportError,
)


class TestAudiobookError:
    """Tests for base AudiobookError."""

    def test_create_minimal(self):
        """Test creating minimal error."""
        err = AudiobookError(message="Test error", error_code="TEST_ERROR")
        assert err.message == "Test error"
        assert err.error_code == "TEST_ERROR"
        assert err.stage is None
        assert err.provider is None
        assert err.context == {}
        assert err.original_error is None

    def test_create_full(self):
        """Test creating error with all fields."""
        original = ValueError("original")
        err = AudiobookError(
            message="Detailed error",
            error_code="DETAILED",
            stage="annotate",
            provider="gemini",
            context={"key": "value"},
            original_error=original,
        )
        assert err.message == "Detailed error"
        assert err.error_code == "DETAILED"
        assert err.stage == "annotate"
        assert err.provider == "gemini"
        assert err.context == {"key": "value"}
        assert err.original_error is original

    def test_to_dict_minimal(self):
        """Test to_dict with minimal error."""
        err = AudiobookError(message="Test", error_code="TEST")
        data = err.to_dict()
        assert data == {
            "error_type": "AudiobookError",
            "error_code": "TEST",
            "message": "Test",
        }

    def test_to_dict_full(self):
        """Test to_dict with full error."""
        original = ValueError("orig")
        err = AudiobookError(
            message="Full error",
            error_code="FULL",
            stage="synthesize",
            provider="kokoro",
            context={"extra": "data"},
            original_error=original,
        )
        data = err.to_dict()
        assert data["error_type"] == "AudiobookError"
        assert data["error_code"] == "FULL"
        assert data["message"] == "Full error"
        assert data["stage"] == "synthesize"
        assert data["provider"] == "kokoro"
        assert data["context"] == {"extra": "data"}
        assert "orig" in data["original_error"]

    def test_string_representation(self):
        """Test error string representation."""
        err = AudiobookError(message="Error message", error_code="ERR")
        assert str(err) == "Error message"


class TestDomainErrors:
    """Tests for domain layer errors."""

    def test_validation_error(self):
        """Test ValidationError."""
        err = ValidationError(
            message="Field required",
            field="title",
            stage="extract",
            context={"input": "test"},
        )
        assert err.error_code == "VALIDATION_ERROR"
        assert err.stage == "extract"
        assert err.context["field"] == "title"
        assert err.context["input"] == "test"

    def test_schema_compliance_error(self):
        """Test SchemaComplianceError."""
        err = SchemaComplianceError(
            message="Missing required field",
            stage="annotate",
            contract_version=2,
            violations=["missing title", "invalid type"],
        )
        assert err.error_code == "SCHEMA_COMPLIANCE_ERROR"
        assert err.stage == "annotate"
        assert err.context["contract_version"] == 2
        assert err.context["violations"] == ["missing title", "invalid type"]

    def test_fallback_used_error(self):
        """Test FallbackUsedError."""
        err = FallbackUsedError(
            message="Using heuristic fallback",
            stage="quality_check",
            fallback_reason="All providers exhausted",
            original_provider="gemini",
        )
        assert err.error_code == "FALLBACK_USED"
        assert err.context["fallback_reason"] == "All providers exhausted"
        assert err.context["original_provider"] == "gemini"


class TestProviderErrors:
    """Tests for provider layer errors."""

    def test_quota_exceeded_error(self):
        """Test QuotaExceededError."""
        err = QuotaExceededError(
            provider="gemini",
            quota_type="daily_tokens",
            limit=1000000,
            remaining=0,
            reset_at="2026-06-24T00:00:00Z",
            stage="annotate",
        )
        assert err.error_code == "QUOTA_EXCEEDED"
        assert err.provider == "gemini"
        assert err.context["quota_type"] == "daily_tokens"
        assert err.context["limit"] == 1000000

    def test_rate_limit_error(self):
        """Test RateLimitError."""
        err = RateLimitError(
            provider="openai",
            retry_after=60,
            stage="extract",
        )
        assert err.error_code == "RATE_LIMITED"
        assert err.provider == "openai"
        assert err.context["retry_after"] == 60

    def test_circuit_open_error(self):
        """Test CircuitOpenError."""
        err = CircuitOpenError(
            provider="gemini",
            stage="synthesize",
            failure_count=5,
            recovery_at="2026-06-23T20:00:00Z",
        )
        assert err.error_code == "CIRCUIT_OPEN"
        assert err.context["failure_count"] == 5

    def test_provider_unavailable_error(self):
        """Test ProviderUnavailableError."""
        original = ConnectionError("DNS failure")
        err = ProviderUnavailableError(
            provider="azure",
            stage="transcribe",
            original_error=original,
        )
        assert err.error_code == "PROVIDER_UNAVAILABLE"
        assert err.original_error is original

    def test_provider_timeout_error(self):
        """Test ProviderTimeoutError."""
        original = TimeoutError("Request timed out")
        err = ProviderTimeoutError(
            provider="gemini",
            timeout_s=30.0,
            stage="analyze",
            original_error=original,
        )
        assert err.error_code == "PROVIDER_TIMEOUT"
        assert "30.0" in err.message
        assert err.original_error is original


class TestInfrastructureErrors:
    """Tests for infrastructure layer errors."""

    def test_database_error(self):
        """Test DatabaseError."""
        err = DatabaseError(
            message="Connection pool exhausted",
            operation="INSERT",
            table="paragraphs",
        )
        assert err.error_code == "DATABASE_ERROR"
        assert err.context["component"] == "database"
        assert err.context["operation"] == "INSERT"
        assert err.context["table"] == "paragraphs"

    def test_file_write_error(self):
        """Test FileWriteError."""
        original = PermissionError("No write access")
        err = FileWriteError(
            path="/output/audio.mp3",
            reason="Disk full",
            original_error=original,
        )
        assert err.error_code == "FILE_WRITE_ERROR"
        assert err.context["path"] == "/output/audio.mp3"
        assert err.context["reason"] == "Disk full"

    def test_config_error(self):
        """Test ConfigError."""
        err = ConfigError(
            message="Invalid YAML syntax",
            config_path="config/llm_providers.yaml",
        )
        assert err.error_code == "CONFIG_ERROR"
        assert err.context["component"] == "config"
        assert err.context["config_path"] == "config/llm_providers.yaml"


class TestPipelineErrors:
    """Tests for pipeline layer errors."""

    def test_stage_execution_error(self):
        """Test StageExecutionError."""
        original = ValueError("Invalid input")
        err = StageExecutionError(
            stage="annotate",
            reason="Invalid paragraph format",
            original_error=original,
        )
        assert err.error_code == "STAGE_EXECUTION_ERROR"
        assert err.stage == "annotate"
        assert err.context["reason"] == "Invalid paragraph format"

    def test_stage_hook_error(self):
        """Test StageHookError."""
        err = StageHookError(
            stage="quality_check",
            hook_name="on_exit",
        )
        assert err.error_code == "STAGE_HOOK_ERROR"
        assert err.context["hook_name"] == "on_exit"

    def test_data_load_error(self):
        """Test DataLoadError."""
        err = DataLoadError(
            stage="extract",
            source="s3://bucket/input.txt",
        )
        assert err.error_code == "DATA_LOAD_ERROR"
        assert err.context["source"] == "s3://bucket/input.txt"

    def test_data_persist_error(self):
        """Test DataPersistError."""
        err = DataPersistError(
            stage="synthesize",
            target="database",
        )
        assert err.error_code == "DATA_PERSIST_ERROR"
        assert err.context["target"] == "database"


class TestTTSErrors:
    """Tests for TTS layer errors."""

    def test_tts_model_load_error(self):
        """Test TTSModelLoadError."""
        err = TTSModelLoadError(
            engine="kokoro",
            model_name="kokoro-v1.0",
        )
        assert err.error_code == "TTS_MODEL_LOAD_ERROR"
        assert err.provider == "kokoro"
        assert err.context["model_name"] == "kokoro-v1.0"

    def test_tts_synthesis_error(self):
        """Test TTSSynthesisError."""
        err = TTSSynthesisError(
            engine="edge",
            text="Hello world",
            reason="Voice not found",
        )
        assert err.error_code == "TTS_SYNTHESIS_ERROR"
        assert err.context["text_length"] == 11
        assert err.context["reason"] == "Voice not found"

    def test_tts_audio_export_error(self):
        """Test TTSAudioExportError."""
        err = TTSAudioExportError(
            engine="azure",
            output_path="/output/test.mp3",
            format="mp3",
        )
        assert err.error_code == "TTS_AUDIO_EXPORT_ERROR"
        assert err.context["output_path"] == "/output/test.mp3"
        assert err.context["format"] == "mp3"


class TestErrorInheritance:
    """Tests for error inheritance chain."""

    def test_domain_error_is_audiobook_error(self):
        """Test DomainError inherits from AudiobookError."""
        err = ValidationError(message="test", field="title")
        assert isinstance(err, DomainError)
        assert isinstance(err, AudiobookError)
        assert isinstance(err, Exception)

    def test_provider_error_is_audiobook_error(self):
        """Test ProviderError inherits from AudiobookError."""
        err = RateLimitError(provider="test")
        assert isinstance(err, ProviderError)
        assert isinstance(err, AudiobookError)

    def test_pipeline_error_is_audiobook_error(self):
        """Test PipelineError inherits from AudiobookError."""
        err = StageExecutionError(stage="test", reason="test")
        assert isinstance(err, PipelineError)
        assert isinstance(err, AudiobookError)

    def test_catch_domain_error_as_audiobook_error(self):
        """Test catching domain error as base AudiobookError."""
        try:
            raise ValidationError(message="test", field="title")
        except AudiobookError as e:
            assert isinstance(e, ValidationError)
            assert e.error_code == "VALIDATION_ERROR"

    def test_exception_hierarchy(self):
        """Test all errors are Exceptions."""
        errors = [
            AudiobookError("msg", "CODE"),
            ValidationError(message="msg", field="title"),
            QuotaExceededError("prov", "quota"),
            StageExecutionError("stage", "reason"),
        ]
        for err in errors:
            assert isinstance(err, Exception)
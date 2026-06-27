"""Audiobook Studio — 统一异常体系.

分层异常设计，便于捕获、分类和结构化日志记录。
"""

from typing import Any, Dict, Optional, List


class AudiobookError(Exception):
    """所有自定义异常的基类."""

    def __init__(
        self,
        message: str,
        error_code: str,
        stage: Optional[str] = None,
        provider: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.stage = stage
        self.provider = provider
        self.context = context or {}
        self.original_error = original_error
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """转换为结构化字典，用于日志记录."""
        data = {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.stage:
            data["stage"] = self.stage
        if self.provider:
            data["provider"] = self.provider
        if self.context:
            data["context"] = self.context  # type: ignore[assignment]
        if self.original_error:
            data["original_error"] = str(self.original_error)
        return data


# ==================== Domain Layer Errors ====================


class DomainError(AudiobookError):
    """业务逻辑错误基类."""

    def __init__(
        self,
        message: str,
        error_code: str,
        stage: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            stage=stage,
            context=context,
            original_error=original_error,
        )


class ValidationError(DomainError):
    """数据验证失败."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        stage: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        ctx = {"field": field, **(context or {})}
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            stage=stage,
            context=ctx,
        )


class SchemaComplianceError(DomainError):
    """LLM 输出不符合契约 Schema."""

    def __init__(
        self,
        message: str,
        stage: Optional[str] = None,
        contract_version: int = 1,
        violations: Optional[List[str]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code="SCHEMA_COMPLIANCE_ERROR",
            stage=stage,
            context={"contract_version": contract_version, "violations": violations or []},
            original_error=original_error,
        )


class FallbackUsedError(DomainError):
    """触发了兜底逻辑."""

    def __init__(
        self,
        message: str,
        stage: Optional[str] = None,
        fallback_reason: Optional[str] = None,
        original_provider: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            error_code="FALLBACK_USED",
            stage=stage,
            context={"fallback_reason": fallback_reason, "original_provider": original_provider},
        )


# ==================== Provider Layer Errors ====================


class ProviderError(AudiobookError):
    """外部提供商相关错误基类."""

    def __init__(
        self,
        message: str,
        provider: str,
        error_code: str,
        stage: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            stage=stage,
            provider=provider,
            context=context,
            original_error=original_error,
        )


class QuotaExceededError(ProviderError):
    """配额耗尽."""

    def __init__(
        self,
        provider: str,
        quota_type: str,
        limit: Optional[int] = None,
        remaining: int = 0,
        reset_at: Optional[str] = None,
        stage: Optional[str] = None,
    ):
        super().__init__(
            message=f"Provider {provider} quota exceeded for {quota_type}",
            provider=provider,
            error_code="QUOTA_EXCEEDED",
            stage=stage,
            context={
                "quota_type": quota_type,
                "limit": limit,
                "remaining": remaining,
                "reset_at": reset_at,
            },
        )


class RateLimitError(ProviderError):
    """请求速率超限."""

    def __init__(
        self,
        provider: str,
        retry_after: Optional[int] = None,
        stage: Optional[str] = None,
    ):
        super().__init__(
            message=f"Provider {provider} rate limited",
            provider=provider,
            error_code="RATE_LIMITED",
            stage=stage,
            context={"retry_after": retry_after},
        )


class CircuitOpenError(ProviderError):
    """熔断器打开，拒绝请求."""

    def __init__(
        self,
        provider: str,
        stage: Optional[str] = None,
        failure_count: int = 0,
        recovery_at: Optional[str] = None,
    ):
        super().__init__(
            message=f"Provider {provider} circuit is open",
            provider=provider,
            error_code="CIRCUIT_OPEN",
            stage=stage,
            context={"failure_count": failure_count, "recovery_at": recovery_at},
        )


class ProviderUnavailableError(ProviderError):
    """提供商服务不可用."""

    def __init__(
        self,
        provider: str,
        stage: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Provider {provider} is unavailable",
            provider=provider,
            error_code="PROVIDER_UNAVAILABLE",
            stage=stage,
            original_error=original_error,
        )


class ProviderTimeoutError(ProviderError):
    """提供商请求超时."""

    def __init__(
        self,
        provider: str,
        timeout_s: float,
        stage: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Provider {provider} timed out after {timeout_s}s",
            provider=provider,
            error_code="PROVIDER_TIMEOUT",
            stage=stage,
            original_error=original_error,
        )


# ==================== Infrastructure Layer Errors ====================


class InfrastructureError(AudiobookError):
    """基础设施层错误基类."""

    def __init__(
        self,
        message: str,
        error_code: str,
        component: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = {"component": component} if component else None
        if context:
            ctx = {**(ctx or {}), **context}
        super().__init__(
            message=message,
            error_code=error_code,
            context=ctx,
            original_error=original_error,
        )


class DatabaseError(InfrastructureError):
    """数据库操作失败."""

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        table: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code="DATABASE_ERROR",
            component="database",
            context={"operation": operation, "table": table},
            original_error=original_error,
        )


class FileNotFoundError(InfrastructureError):
    """文件不存在."""

    def __init__(
        self,
        path: str,
        operation: Optional[str] = None,
    ):
        super().__init__(
            message=f"File not found: {path}",
            error_code="FILE_NOT_FOUND",
            component="storage",
            context={"path": path, "operation": operation},
        )


class FileWriteError(InfrastructureError):
    """文件写入失败."""

    def __init__(
        self,
        path: str,
        reason: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to write file: {path}",
            error_code="FILE_WRITE_ERROR",
            component="storage",
            context={"path": path, "reason": reason},
            original_error=original_error,
        )


class ConfigError(InfrastructureError):
    """配置加载或验证失败."""

    def __init__(
        self,
        message: str,
        config_path: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code="CONFIG_ERROR",
            component="config",
            context={"config_path": config_path},
            original_error=original_error,
        )


# ==================== Pipeline Layer Errors ====================


class PipelineError(AudiobookError):
    """Pipeline 执行错误基类."""

    def __init__(
        self,
        message: str,
        stage: str,
        error_code: str,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            stage=stage,
            context=context,
            original_error=original_error,
        )


class StageExecutionError(PipelineError):
    """阶段执行失败."""

    def __init__(
        self,
        stage: str,
        reason: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Stage {stage} execution failed: {reason}",
            stage=stage,
            error_code="STAGE_EXECUTION_ERROR",
            context={"reason": reason},
            original_error=original_error,
        )


class StageHookError(PipelineError):
    """Hook 执行失败."""

    def __init__(
        self,
        stage: str,
        hook_name: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Hook {hook_name} failed in stage {stage}",
            stage=stage,
            error_code="STAGE_HOOK_ERROR",
            context={"hook_name": hook_name},
            original_error=original_error,
        )


class DataLoadError(PipelineError):
    """数据加载失败."""

    def __init__(
        self,
        stage: str,
        source: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to load data from {source} in stage {stage}",
            stage=stage,
            error_code="DATA_LOAD_ERROR",
            context={"source": source},
            original_error=original_error,
        )


class DataPersistError(PipelineError):
    """数据持久化失败."""

    def __init__(
        self,
        stage: str,
        target: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to persist data to {target} in stage {stage}",
            stage=stage,
            error_code="DATA_PERSIST_ERROR",
            context={"target": target},
            original_error=original_error,
        )


# ==================== TTS Layer Errors ====================


class TTSError(AudiobookError):
    """TTS 合成错误基类."""

    def __init__(
        self,
        message: str,
        engine: str,
        error_code: str,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            provider=engine,
            context=context,
            original_error=original_error,
        )


class TTSModelLoadError(TTSError):
    """TTS 模型加载失败."""

    def __init__(
        self,
        engine: str,
        model_name: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to load TTS model {model_name} for engine {engine}",
            engine=engine,
            error_code="TTS_MODEL_LOAD_ERROR",
            context={"model_name": model_name},
            original_error=original_error,
        )


class TTSSynthesisError(TTSError):
    """TTS 合成失败."""

    def __init__(
        self,
        engine: str,
        text: str,
        reason: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"TTS synthesis failed for engine {engine}: {reason or 'unknown'}",
            engine=engine,
            error_code="TTS_SYNTHESIS_ERROR",
            context={"text_length": len(text), "reason": reason},
            original_error=original_error,
        )


class TTSAudioExportError(TTSError):
    """音频导出失败."""

    def __init__(
        self,
        engine: str,
        output_path: str,
        format: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to export audio to {output_path} for engine {engine}",
            engine=engine,
            error_code="TTS_AUDIO_EXPORT_ERROR",
            context={"output_path": output_path, "format": format},
            original_error=original_error,
        )
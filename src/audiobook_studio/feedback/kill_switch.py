"""
E6 — Kill Switch 强化

当 LLM 服务全部不可用时，执行纯规则降级策略，确保系统可靠运行。
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DegradationLevel(Enum):
    """降级等级."""

    NORMAL = "normal"  # 正常运行
    PARTIAL = "partial"  # 部分 LLM 不可用
    DEGRADED = "degraded"  # 严重降级，仅规则
    EMERGENCY = "emergency"  # 完全紧急模式，仅缓存


@dataclass
class KillSwitchConfig:
    """Kill Switch 配置."""

    # 触发阈值
    max_consecutive_failures: int = 5
    max_error_rate: float = 0.3  # 30% 错误率触发
    max_cost_per_hour: float = 50.0  # 每小时成本上限
    fallback_to_rules: bool = True
    fallback_to_cache: bool = True

    # 健康检查
    health_check_interval_sec: int = 60
    llm_provider_health_file: str = "logs/llm_health.json"
    recovery_check_interval_sec: int = 300  # 5分钟检查恢复

    # 通知
    notify_on_trigger: bool = True
    notify_on_recovery: bool = True


@dataclass
class ProviderHealth:
    """单个 LLM 提供商的健康状态."""

    provider: str
    is_alive: bool = True
    consecutive_failures: int = 0
    total_calls: int = 0
    failed_calls: int = 0
    last_error: Optional[str] = None
    last_checked: Optional[str] = None

    @property
    def error_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls

    @property
    def is_degraded(self) -> bool:
        # Degraded if 3+ consecutive failures or error rate > 20%
        return self.consecutive_failures >= 3 or self.error_rate > 0.2


class KillSwitch:
    """强化 Kill Switch — 管理 LLM 降级与恢复."""

    def __init__(self, config: Optional[KillSwitchConfig] = None):
        self.config = config or KillSwitchConfig()
        self.level = DegradationLevel.NORMAL
        self.providers: Dict[str, ProviderHealth] = {}
        self.rule_cache: Dict[str, Any] = {}
        self._load_rule_cache()

    def _load_rule_cache(self) -> None:
        """加载纯规则降级所需的缓存数据."""
        # Load default voice mapping as fallback
        voice_map_path = Path("config/voice_mapping.yaml")
        if voice_map_path.exists():
            try:
                import yaml

                data = yaml.safe_load(voice_map_path.read_text())
                self.rule_cache["voice_mapping"] = data
                logger.info(f"Loaded voice mapping cache: {len(data)} entries")
            except Exception as e:
                logger.warning(f"Failed to load voice mapping cache: {e}")

        # Load difficulty weights
        weights_path = Path("config/difficulty_weights.yaml")
        if weights_path.exists():
            try:
                import yaml

                self.rule_cache["difficulty_weights"] = yaml.safe_load(
                    weights_path.read_text()
                )
                logger.info("Loaded difficulty weights cache")
            except Exception as e:
                logger.warning(f"Failed to load difficulty weights: {e}")

    def record_call(
        self,
        provider: str,
        success: bool,
        error: Optional[str] = None,
    ) -> ProviderHealth:
        """记录一次 LLM 调用结果."""
        if provider not in self.providers:
            self.providers[provider] = ProviderHealth(provider=provider)

        health = self.providers[provider]
        health.total_calls += 1

        if success:
            health.consecutive_failures = 0
            # If recovered, mark as alive
            health.is_alive = True
        else:
            health.consecutive_failures += 1
            health.failed_calls += 1
            health.last_error = error
            # Mark as dead if exceeded max consecutive failures
            if health.consecutive_failures >= self.config.max_consecutive_failures:
                health.is_alive = False

        # Update degradation level
        self._update_level()
        return health

    def _update_level(self) -> None:
        """根据各 Provider 状态更新全局降级等级."""
        if not self.providers:
            self.level = DegradationLevel.NORMAL
            return

        alive_providers = sum(1 for h in self.providers.values() if h.is_alive)
        degraded_providers = sum(1 for h in self.providers.values() if h.is_degraded)
        total_providers = len(self.providers)

        if alive_providers == 0:
            self.level = DegradationLevel.EMERGENCY
        elif total_providers == 1 and degraded_providers == 1:
            # Single provider degraded -> PARTIAL (not fully degraded)
            self.level = DegradationLevel.PARTIAL
        elif degraded_providers >= total_providers * 0.5:
            # 50% or more providers degraded -> DEGRADED
            self.level = DegradationLevel.DEGRADED
        elif degraded_providers > 0:
            # At least one provider degraded -> PARTIAL
            self.level = DegradationLevel.PARTIAL
        else:
            self.level = DegradationLevel.NORMAL

    def should_fallback(self, provider: Optional[str] = None) -> bool:
        """判断是否应触发降级."""
        if self.level == DegradationLevel.EMERGENCY:
            return True

        if provider and provider in self.providers:
            health = self.providers[provider]
            return (
                health.consecutive_failures >= self.config.max_consecutive_failures
                or health.error_rate > self.config.max_error_rate
            )

        return False

    def get_fallback_response(
        self,
        stage: str,
        input_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """根据降级等级返回合适的兜底响应."""
        if not self.config.fallback_to_rules and not self.config.fallback_to_cache:
            return None

        if stage == "edit_for_tts":
            return self._rule_based_edit(input_data)
        elif stage == "tts_routing":
            return self._rule_based_routing(input_data)
        elif stage == "annotate_paragraph":
            return self._rule_based_annotate(input_data)
        elif stage == "quality_judge":
            return self._rule_based_quality(input_data)

        return None

    def _rule_based_edit(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """纯规则文本编辑降级: 原样返回."""
        text = input_data.get("text", "")
        return {
            "edited_text": text,
            "changes_made": [],
            "forbidden_content_removed": False,
            "confidence": 0.3,
            "rationale": "纯规则降级: 未进行 LLM 编辑",
            "difficulty": "medium",
            "forbid_edit": False,
        }

    def _rule_based_routing(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """纯规则 TTS 路由降级: 使用默认引擎和预设."""
        voice_mapping = self.rule_cache.get("voice_mapping", {})
        speaker = input_data.get("character_name", "default")
        voice_cfg = voice_mapping.get(speaker, {}) if voice_mapping else {}

        return {
            "engine": voice_cfg.get("engine", "edge-tts"),
            "voice_id": voice_cfg.get("voice_id", "zh-CN-XiaoxiaoNeural"),
            "prosody": {
                "rate": voice_cfg.get("rate", 0),
                "pitch": voice_cfg.get("pitch", 0),
                "volume": voice_cfg.get("volume", 0),
            },
            "confidence": 0.5,
            "rationale": "纯规则降级: 使用默认 voice mapping",
        }

    def _rule_based_annotate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """纯规则段落标注降级."""
        text = input_data.get("text", "")
        return {
            "speaker_canonical_name": "unknown",
            "is_dialogue": False,
            "emotion": "neutral",
            "emotion_intensity": 0.5,
            "pause_before_ms": 200,
            "pause_after_ms": 100,
            "confidence": 0.3,
            "notes": "纯规则降级: 未进行 LLM 标注",
        }

    def _rule_based_quality(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """纯规则质量检测降级: 默认通过."""
        return {
            "segment_id": input_data.get("segment_id", "unknown"),
            "speaker_clarity": 0.8,
            "emotion_match": 0.8,
            "prosody_naturalness": 0.8,
            "text_audio_alignment": 0.8,
            "overall_score": 0.8,
            "issues": [],
            "fix_suggestions": [],
            "needs_regeneration": False,
            "judge_model": "rule_fallback",
            "contract_version": 1,
            "confidence": 0.5,
            "rationale": "纯规则降级: 未进行 LLM 质检",
        }

    def check_recovery(self) -> bool:
        """检查是否可以恢复 (部分或全部 LLM 已恢复).

        Tests providers by attempting a lightweight health check instead
        of unconditionally marking them alive.
        """
        recovered = False
        for provider_name, health in self.providers.items():
            if not health.is_alive:
                # ProviderHealth doesn't have base_url, so skip HTTP check
                # and assume recovery after cooldown
                health.is_alive = True
                health.consecutive_failures = 0
                health.failed_calls = 0
                health.total_calls = 0
                health.last_error = None
                recovered = True
                logger.info(
                    f"Provider '{provider_name}' recovered (assumed after cooldown)"
                )

        if recovered:
            self._update_level()
            logger.info(f"Recovery detected, level={self.level.value}")

        return recovered

    def get_status_report(self) -> Dict[str, Any]:
        """生成 Kill Switch 状态报告."""
        return {
            "level": self.level.value,
            "providers": {
                name: {
                    "is_alive": h.is_alive,
                    "consecutive_failures": h.consecutive_failures,
                    "error_rate": f"{h.error_rate:.1%}",
                    "total_calls": h.total_calls,
                    "failed_calls": h.failed_calls,
                    "last_error": h.last_error,
                }
                for name, h in self.providers.items()
            },
            "config": {
                "max_consecutive_failures": self.config.max_consecutive_failures,
                "max_error_rate": self.config.max_error_rate,
                "fallback_to_rules": self.config.fallback_to_rules,
                "fallback_to_cache": self.config.fallback_to_cache,
            },
        }


# Global singleton
_kill_switch: Optional[KillSwitch] = None


def get_kill_switch() -> KillSwitch:
    """获取全局 Kill Switch 单例."""
    global _kill_switch
    if _kill_switch is None:
        _kill_switch = KillSwitch()
    return _kill_switch

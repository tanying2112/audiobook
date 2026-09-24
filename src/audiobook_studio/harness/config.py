"""马具迭代配置管理：YAML 配置加载、环境变量覆盖、默认值管理。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

HARNESS_PROMPTS_DIR = Path("prompts/harness")
"""harness 自有 prompt 编译沙箱根目录，与反馈引擎的真实 prompts/ 隔离，
避免 harness 套件在 prompts/<stage>/ 下生成游离的 v*.j2，污染 feedback 套件。"""


class HarnessSettings(BaseSettings):
    """马具迭代配置：所有开关、阈值、模型选择集中管理。

    加载优先级（高→低）：
    1. 环境变量（前缀 HARNESS_）
    2. 显式传入的 YAML 配置路径
    3. CWD 下 config/harness.yaml（运维版本优先）
    4. 包内 config/harness.yaml（fallback）
    """

    model_config = SettingsConfigDict(
        env_prefix="HARNESS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ──────────────────────────────────────────────────────────────────────────
    # 总开关
    # ──────────────────────────────────────────────────────────────────────────

    ENABLED: bool = Field(default=True, alias="HARNESS_ENABLED")
    """总开关：关闭则所有迭代组件停止工作"""

    # ──────────────────────────────────────────────────────────────────────────
    # 迭代循环控制
    # ──────────────────────────────────────────────────────────────────────────

    SELF_ITERATION_LLM: str = Field(default="ollama/qwen3.5:2b", alias="SELF_ITERATION_LLM")
    """自迭代专用 LLM（本地 Ollama 推荐）"""

    SELF_ITERATION_BATCH_SIZE: int = Field(default=20, alias="SELF_ITERATION_BATCH_SIZE")
    """攒批大小：攒够 N 条纠错样本触发一轮反思"""

    SELF_ITERATION_MOCK: bool = Field(default=False, alias="SELF_ITERATION_MOCK")
    """Mock 模式：True 则不调用真实 LLM，用于测试"""

    BATCH_INTERVAL_SECONDS: int = Field(default=3600, alias="HARNESS_BATCH_INTERVAL_SECONDS")
    """批次检查间隔（秒），默认 1 小时"""

    MAX_CONCURRENT_ITERATIONS: int = Field(default=1, alias="HARNESS_MAX_CONCURRENT")
    """最大并发迭代数（防止资源争用）"""

    # ──────────────────────────────────────────────────────────────────────────
    # 金标数据集
    # ──────────────────────────────────────────────────────────────────────────

    GOLDEN_ROOT: str = Field(default="data/golden/harness", alias="HARNESS_GOLDEN_ROOT")
    """金标数据集根目录"""

    GOLDEN_SPLITS: List[str] = Field(default=["train", "val", "test"])
    """数据集划分"""

    GOLDEN_CANARY_SUBSET: int = Field(default=8, alias="GOLDEN_CANARY_SUBSET")
    """金丝雀每 stage 抽样条数"""

    GOLDEN_AUTO_APPROVE: bool = Field(default=False, alias="GOLDEN_AUTO_APPROVE")
    """自动通过人工审核（测试用）"""

    GOLDEN_DEDUP_ENABLED: bool = Field(default=True, alias="GOLDEN_DEDUP_ENABLED")
    """去重开关"""

    # ──────────────────────────────────────────────────────────────────────────
    # 反思引擎
    # ──────────────────────────────────────────────────────────────────────────

    REFLECTION_ENABLED: bool = Field(default=True, alias="REFLECTION_ENABLED")
    """反思引擎总开关"""

    REFLECTION_BATCH_SIZE: int = Field(default=20, alias="REFLECTION_BATCH_SIZE")
    """反思批次大小"""

    REFLECTION_MODEL: str = Field(default="ollama/qwen3.5:2b", alias="REFLECTION_MODEL")
    """反思专用模型（可与 SELF_ITERATION_LLM 不同）"""

    REFLECTION_TEMPERATURE: float = Field(default=0.1, alias="REFLECTION_TEMPERATURE")
    """反思温度"""

    REFLECTION_MAX_TOKENS: int = Field(default=4000, alias="REFLECTION_MAX_TOKENS")
    """反思最大 token"""

    REFLECTION_PROMPT_TEMPLATE: str = Field(default="", alias="REFLECTION_PROMPT_TEMPLATE")
    """自定义反思提示词模板（留空用内置）"""

    # ──────────────────────────────────────────────────────────────────────────
    # SOP 规则库
    # ──────────────────────────────────────────────────────────────────────────

    SOP_ENABLED: bool = Field(default=True, alias="SOP_ENABLED")
    """SOP 规则库开关"""

    SOP_AUTO_ARCHIVE_DAYS: int = Field(default=90, alias="SOP_AUTO_ARCHIVE_DAYS")
    """低命中规则自动归档天数"""

    SOP_MIN_HIT_COUNT: int = Field(default=5, alias="SOP_MIN_HIT_COUNT")
    """最小命中数阈值（低于此值且超期自动归档）"""

    SOP_MAX_RULES: int = Field(default=200, alias="SOP_MAX_RULES")
    """规则库上限（防止膨胀）"""

    SOP_AUTO_ARCHIVE_ENABLED: bool = Field(default=True, alias="SOP_AUTO_ARCHIVE_ENABLED")
    """自动归档开关"""

    # ──────────────────────────────────────────────────────────────────────────
    # Prompt 进化
    # ──────────────────────────────────────────────────────────────────────────

    PROMPT_EVOLUTION_ENABLED: bool = Field(default=True, alias="PROMPT_EVOLUTION_ENABLED")
    """Prompt 进化开关"""

    PROMPT_MAX_VERSIONS: int = Field(default=50, alias="PROMPT_MAX_VERSIONS")
    """每 stage 最大保留版本数（防止膨胀）"""

    PROMPT_MAX_TOKENS: int = Field(default=8000, alias="PROMPT_MAX_TOKENS")
    """单个 prompt 最大 token（含 few-shot）"""

    PROMPT_MAX_FEWSHOT: int = Field(default=3, alias="PROMPT_MAX_FEWSHOT")
    """few-shot 示例数上限"""

    DSPY_ENABLED: bool = Field(default=False, alias="DSPY_ENABLED")
    """DSPy BootstrapFewShot 实验性开关（需额外依赖）"""

    PROMPT_CANARY_SUBSET: int = Field(default=8, alias="PROMPT_CANARY_SUBSET")
    """Prompt 金丝雀每 stage 抽样条数"""

    PROMPT_SHADOW_PERCENTAGE: float = Field(default=0.1, alias="PROMPT_SHADOW_PERCENTAGE")
    """Shadow 流量百分比（0.1 = 10%）"""

    PROMPT_SHADOW_DAYS: int = Field(default=7, alias="PROMPT_SHADOW_DAYS")
    """Shadow 观察期（天）"""

    # ──────────────────────────────────────────────────────────────────────────
    # 质量阈值校准
    # ──────────────────────────────────────────────────────────────────────────

    THRESHOLD_CALIBRATION_ENABLED: bool = Field(default=True, alias="THRESHOLD_CALIBRATION_ENABLED")
    """阈值自动校准开关"""

    CALIBRATION_WINDOW_DAYS: int = Field(default=14, alias="CALIBRATION_WINDOW_DAYS")
    """校准窗口天数（统计最近 N 天分布）"""

    CALIBRATION_MIN_SAMPLES: int = Field(default=100, alias="CALIBRATION_MIN_SAMPLES")
    """校准最小样本数"""

    CALIBRATION_PERCENTILE: float = Field(default=0.05, alias="CALIBRATION_PERCENTILE")
    """校准分位点（如 0.05 = 5% 分位点）"""

    CALIBRATION_MAX_CHANGE_PCT: float = Field(default=0.2, alias="CALIBRATION_MAX_CHANGE_PCT")
    """单次校准最大变化幅度（20%）"""

    # ──────────────────────────────────────────────────────────────────────────
    # 路由表进化
    # ──────────────────────────────────────────────────────────────────────────

    ROUTING_EVOLUTION_ENABLED: bool = Field(default=True, alias="ROUTING_EVOLUTION_ENABLED")
    """路由表进化开关"""

    ROUTING_DECAY_ON_FAILURE: float = Field(default=0.9, alias="ROUTING_DECAY_ON_FAILURE")
    """失败时权重衰减系数（0.9 = 降权 10%）"""

    ROUTING_MIN_WEIGHT: float = Field(default=0.1, alias="ROUTING_MIN_WEIGHT")
    """最小权重下限"""

    ROUTING_MAX_WEIGHT: float = Field(default=10.0, alias="ROUTING_MAX_WEIGHT")
    """最大权重上限"""

    ROUTING_MIN_SUCCESS_FOR_RECOVERY: int = Field(default=5, alias="ROUTING_MIN_SUCCESS_FOR_RECOVERY")
    """连续成功多少次可恢复权重"""

    ROUTING_MIN_SUCCESS_FOR_INCREASE: int = Field(default=10, alias="ROUTING_MIN_SUCCESS_FOR_INCREASE")
    """连续成功多少次可增权"""

    # ──────────────────────────────────────────────────────────────────────────
    # 金丝雀 / A/B 测试
    # ──────────────────────────────────────────────────────────────────────────

    CANARY_ENABLED: bool = Field(default=True, alias="CANARY_ENABLED")
    """金丝雀测试开关"""

    CANARY_DEFAULT_TRAFFIC: float = Field(default=0.1, alias="CANARY_DEFAULT_TRAFFIC")
    """默认金丝雀流量比例（0.1 = 10%）"""

    CANARY_MAX_TRAFFIC: float = Field(default=0.5, alias="CANARY_MAX_TRAFFIC")
    """最大金丝雀流量上限"""

    CANARY_MIN_SAMPLES: int = Field(default=8, alias="CANARY_MIN_SAMPLES")
    """最小金丝雀样本数"""

    CANARY_OBSERVATION_DAYS: int = Field(default=7, alias="CANARY_OBSERVATION_DAYS")
    """观察期天数"""

    CANARY_AUTO_PROMOTE: bool = Field(default=True, alias="CANARY_AUTO_PROMOTE")
    """自动晋升开关"""

    # ──────────────────────────────────────────────────────────────────────────
    # 晋升门禁
    # ──────────────────────────────────────────────────────────────────────────

    PROMOTION_GOLDEN_PASS_RATE_MIN: float = Field(default=0.95, alias="PROMOTION_GOLDEN_PASS_RATE_MIN")
    """金标通过率最低要求（>= 0.95）"""

    PROMOTION_QUALITY_RATIO_MIN: float = Field(default=1.0, alias="PROMOTION_QUALITY_RATIO_MIN")
    """质量比基线最低比率（>= 1.0 = 不退化）"""

    PROMOTION_FORMAT_COMPLIANCE_MIN: float = Field(default=1.0, alias="PROMOTION_FORMAT_COMPLIANCE_MIN")
    """格式合规率最低要求（1.0 = 100%）"""

    PROMOTION_HUMAN_PREFERENCE_MIN: float = Field(default=1.0, alias="PROMOTION_HUMAN_PREFERENCE_MIN")
    """人工偏好分最低要求"""

    PROMOTION_MIN_SAMPLES: int = Field(default=8, alias="PROMOTION_MIN_SAMPLES")
    """金丝雀最小样本数"""

    # ──────────────────────────────────────────────────────────────────────────
    # 限流/成本控制
    # ──────────────────────────────────────────────────────────────────────────

    # 使用独立的环境变量名，避免被主应用测试环境（conftest 强制 RATE_LIMIT_ENABLED=false）污染。
    RATE_LIMIT_ENABLED: bool = Field(default=True, alias="HARNESS_RATE_LIMIT_ENABLED")
    """全局限流开关"""

    AUTH_RATE_LIMIT: int = Field(default=5, alias="AUTH_RATE_LIMIT")
    """认证端点限流（次/5分钟）"""

    AUTH_RATE_WINDOW: int = Field(default=300, alias="AUTH_RATE_WINDOW")
    """认证限流窗口（秒）"""

    LLM_RATE_LIMIT_ENABLED: bool = Field(default=True, alias="LLM_RATE_LIMIT_ENABLED")
    """LLM 调用限流开关"""

    LLM_RATE_LIMIT_PER_MINUTE: int = Field(default=60, alias="LLM_RATE_LIMIT_PER_MINUTE")
    """LLM 每分钟请求上限"""

    COST_DAILY_LIMIT_USD: float = Field(default=10.0, alias="COST_DAILY_LIMIT_USD")
    """每日成本上限（USD）"""

    COST_ALERT_THRESHOLD: float = Field(default=0.8, alias="COST_ALERT_THRESHOLD")
    """成本告警阈值（0.8 = 80%）"""

    # ──────────────────────────────────────────────────────────────────────────
    # 监控/告警/周报
    # ──────────────────────────────────────────────────────────────────────────

    MONITORING_ENABLED: bool = Field(default=True, alias="MONITORING_ENABLED")
    """监控开关"""

    WEEKLY_REPORT_ENABLED: bool = Field(default=True, alias="WEEKLY_REPORT_ENABLED")
    """周报开关"""

    WEEKLY_REPORT_DAY: int = Field(default=0, alias="WEEKLY_REPORT_DAY")
    """周报生成日（0=周一，6=周日）"""

    ALERT_WEBHOOK_URL: Optional[str] = Field(default=None, alias="ALERT_WEBHOOK_URL")
    """告警 Webhook URL"""

    ALERT_COOLDOWN_MINUTES: int = Field(default=60, alias="ALERT_COOLDOWN_MINUTES")
    """告警冷却时间（分钟）"""

    # ──────────────────────────────────────────────────────────────────────────
    # Ollama / 本地 LLM
    # ──────────────────────────────────────────────────────────────────────────

    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    """Ollama 服务地址"""

    OLLAMA_DEFAULT_MODEL: str = Field(default="qwen3.5:2b", alias="OLLAMA_DEFAULT_MODEL")
    """默认 Ollama 模型"""

    OLLAMA_TIMEOUT: int = Field(default=0, alias="OLLAMA_TIMEOUT")
    """Ollama 超时（0 = 无限制）"""

    # ──────────────────────────────────────────────────────────────────────────
    # 存储/数据库
    # ──────────────────────────────────────────────────────────────────────────

    DATABASE_URL: str = Field(default="sqlite:///./audiobook_studio.db", alias="DATABASE_URL")
    """数据库连接串"""

    DATA_ROOT: str = Field(default="data", alias="DATA_ROOT")
    """数据根目录"""

    # ──────────────────────────────────────────────────────────────────────────
    # 运行时状态（运行时动态更新，不持久化）
    # ──────────────────────────────────────────────────────────────────────────

    _runtime_overrides: Dict[str, Any] = {}

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 加载 YAML 配置文件
        self._load_yaml_config()

    def _load_yaml_config(self) -> None:
        """加载 YAML 配置文件（优先级低于环境变量）。"""
        import yaml

        config_paths = [
            Path.cwd() / "config" / "harness.yaml",  # CWD 优先（运维版本）
            Path(__file__).parent.parent / "config" / "harness.yaml",  # 包内 fallback
        ]

        for path in config_paths:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    # 只更新未被环境变量覆盖的字段
                    for key, value in data.items():
                        env_key = f"HARNESS_{key.upper()}"
                        if env_key not in os.environ:
                            if hasattr(self, key):
                                setattr(self, key, value)
                            else:
                                self._runtime_overrides[key] = value
                    logger.info(f"Loaded harness config from {path}")
                    break
                except Exception as e:
                    logger.warning(f"Failed to load harness config from {path}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（运行时覆盖 > 环境变量 > YAML > 默认值）。"""
        if key in self._runtime_overrides:
            return self._runtime_overrides[key]
        return getattr(self, key, default)

    def set_runtime(self, key: str, value: Any) -> None:
        """设置运行时覆盖（不持久化）。"""
        self._runtime_overrides[key] = value

    def get_model_config(self) -> Dict[str, Any]:
        """获取所有配置的字典（用于调试/导出）。"""
        return {
            **self.model_dump(),
            **self._runtime_overrides,
        }


# ──────────────────────────────────────────────────────────────────────────────
# 单例访问
# ──────────────────────────────────────────────────────────────────────────────

_harness_settings: Optional["HarnessSettings"] = None


def get_harness_settings() -> HarnessSettings:
    """获取全局 Harness 配置单例。"""
    global _harness_settings
    if _harness_settings is None:
        _harness_settings = HarnessSettings()
    return _harness_settings


def reset_harness_settings() -> None:
    """重置配置单例（测试用）。"""
    global _harness_settings
    _harness_settings = None


# ──────────────────────────────────────────────────────────────────────────────
# 默认配置文件模板（用于首次生成）
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_HARNESS_YAML = """
# Harness 迭代配置
# 所有值可被环境变量 HARNESS_* 覆盖

# 总开关
enabled: true

# 迭代循环控制
self_iteration_llm: "ollama/qwen3.5:2b"
self_iteration_batch_size: 20
self_iteration_mock: false
batch_interval_seconds: 3600
max_concurrent_iterations: 1

# 金标数据集
golden_root: "data/golden/harness"
golden_splits: ["train", "val", "test"]
golden_canary_subset: 8
golden_auto_approve: false
golden_dedup_enabled: true

# 反思引擎
reflection_enabled: true
reflection_batch_size: 20
reflection_model: "ollama/qwen3.5:2b"
reflection_temperature: 0.1
reflection_max_tokens: 4000

# SOP 规则库
sop_enabled: true
sop_auto_archive_days: 90
sop_min_hit_count: 5
sop_max_rules: 200
sop_auto_archive_enabled: true

# Prompt 进化
prompt_evolution_enabled: true
prompt_max_versions: 50
prompt_max_tokens: 8000
prompt_max_fewshot: 3
dspy_enabled: false
prompt_canary_subset: 8
prompt_shadow_percentage: 0.1
prompt_shadow_days: 7

# 质量阈值校准
threshold_calibration_enabled: true
calibration_window_days: 14
calibration_min_samples: 100
calibration_percentile: 0.05
calibration_max_change_pct: 0.2

# 路由表进化
routing_evolution_enabled: true
routing_decay_on_failure: 0.9
routing_min_weight: 0.1
routing_max_weight: 10.0
routing_min_success_for_recovery: 5
routing_min_success_for_increase: 10

# 金丝雀
canary_enabled: true
canary_default_traffic: 0.1
canary_max_traffic: 0.5
canary_min_samples: 8
canary_observation_days: 7
canary_auto_promote: true

# 晋升门禁
promotion_golden_pass_rate_min: 0.95
promotion_quality_ratio_min: 1.0
promotion_format_compliance_min: 1.0
promotion_human_preference_min: 1.0
promotion_min_samples: 8

# 限流/成本控制
rate_limit_enabled: true
auth_rate_limit: 5
auth_rate_window: 300
llm_rate_limit_enabled: true
llm_rate_limit_per_minute: 60
cost_daily_limit_usd: 10.0
cost_alert_threshold: 0.8

# 监控/告警/周报
monitoring_enabled: true
weekly_report_enabled: true
weekly_report_day: 0
alert_webhook_url: ""
alert_cooldown_minutes: 60

# Ollama 本地 LLM
ollama_base_url: "http://localhost:11434"
ollama_default_model: "qwen3.5:2b"
ollama_timeout: 0

# 存储/数据库
database_url: "sqlite:///./audiobook_studio.db"
data_root: "data"
"""


# ──────────────────────────────────────────────────────────────────────────────
# 单例访问
# ──────────────────────────────────────────────────────────────────────────────

_harness_settings: Optional[HarnessSettings] = None


def get_harness_settings() -> HarnessSettings:
    """获取全局 Harness 配置单例。"""
    global _harness_settings
    if _harness_settings is None:
        _harness_settings = HarnessSettings()
    return _harness_settings


def reset_harness_settings() -> None:
    """重置配置单例（测试用）。"""
    global _harness_settings
    _harness_settings = None


__all__ = [
    "HarnessSettings",
    "get_harness_settings",
    "reset_harness_settings",
    "DEFAULT_HARNESS_YAML",
]

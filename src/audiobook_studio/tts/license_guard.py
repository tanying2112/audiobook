"""TTS 引擎商用许可守卫 (P2.11 合规).

在 EngineRegistry.register 时校验目标引擎的商用许可状态, 阻止商用路径
(active_profile 非 free 档) 注册被标注 commercial_use=False 的引擎。

红线#1 (主路径真实性) 边界:
    - 不替任何引擎假声明 license (杜绝 P1.9 azure/gcp "True # TODO" 复发)。
    - commercial_use 默认 null = 未核实 → gand 降级 warn, 不假成功也不禁用。
    - 仅当维护者凭已核实的官方 model card/license, 在 config/tts_licenses.yaml
      显式填 commercial_use:false 时, 守卫才在商用路径禁用该引擎注册。
    - active_profile 读取失败/未知 → 不作商用判定, 走最保守的 warn 通道 (不停所有引擎)。

校验结果 (LicenseVerdict):
    ok              许可满足路径要求 (或 null 未核实 + 非商用路径)
    warn_unverified 商用路径下 commercial_use=null (未核实, 降级 warn 不禁)
    blocked         商用路径下 commercial_use=false (终止注册, 诚实噪止而非假装注册成功)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

# Use UnifiedConfig for centralized configuration loading
from ..config.unified import get_unified_config

logger = logging.getLogger(__name__)

# 视为非商用 (免费档) 的 profile 名 → 守卫对 null/false 宽容 (不阻断)。
# 余下 (pro_studio / cloud_hybrid 等生产/商用倾向档) 触发严格商用守门。
_FREE_PROFILES = frozenset({"potato"})


class LicenseVerdict(str, Enum):
    """register 时的许可校验结果。"""

    OK = "ok"
    WARN_UNVERIFIED = "warn_unverified"
    BLOCKED = "blocked"


@dataclass
class EngineLicense:
    """单引擎许可元数据 (来自 config/tts_licenses.yaml)。"""

    commercial_use: Optional[bool]  # True=商用OK | False=仅非商用 | None=未核实
    license_name: Optional[str]
    note: str
    verified_at: Optional[str]


def load_license_registry(config_path: Optional[Path] = None) -> Dict[str, EngineLicense]:
    """加载引擎许可注册表; 缺失/解析失败 → 返回空表 (调用方按 None 处理, 诚实降级)。"""
    try:
        # Use UnifiedConfig for centralized loading with caching
        unified = get_unified_config()
        raw: Dict[str, Any] = unified.load_yaml_config("tts_licenses")
    except Exception as e:  # pragma: no cover - 解析失败诚实降级
        logger.warning("license_guard: 许可配置加载失败 (%s): %s → 全引擎按未核实降级", config_path, e)
        return {}

    registry: Dict[str, EngineLicense] = {}
    engines = raw.get("engines") or {}
    if not isinstance(engines, dict):
        return registry
    for name, meta in engines.items():
        if not isinstance(meta, dict):
            continue
        registry[name] = EngineLicense(
            commercial_use=meta.get("commercial_use"),
            license_name=meta.get("license_name"),
            note=str(meta.get("note", "")),
            verified_at=meta.get("verified_at"),
        )
    return registry


def get_active_profile() -> str:
    """获取当前硬件档位 (复用 hardware_profile 模块, 避免循环导入)."""
    try:
        from ..config.hardware_profile import get_active_profile as _get_active

        return _get_active()
    except ImportError:
        return "unknown"


def is_commercial_profile(profile: str) -> bool:
    """判断是否为商用路径 (非 free 档即视为商用倾向, 触发严格守门)."""
    return profile not in _FREE_PROFILES


def check_engine_license(engine_name: str) -> LicenseVerdict:
    """对单引擎做商用许可校验, 返回三态判定。"""
    registry = load_license_registry()
    license_meta = registry.get(engine_name)

    if license_meta is None or license_meta.commercial_use is None:
        # 未核实 → 商用路径 warn, 非商用 ok
        profile = get_active_profile()
        return LicenseVerdict.WARN_UNVERIFIED if is_commercial_profile(profile) else LicenseVerdict.OK

    if license_meta.commercial_use is False:
        # 显式禁用商用
        profile = get_active_profile()
        return LicenseVerdict.BLOCKED if is_commercial_profile(profile) else LicenseVerdict.OK

    # commercial_use=True → 所有路径 ok
    return LicenseVerdict.OK


def register_guard(engine_name: str, active_profile: str) -> bool:
    """register 时许可守门: 返回 True=允许注册, False=阻断 (诚实噪止).

    P2.11 守门语义 (与 check_engine_license 对齐, 但接受显式传入的 active_profile):
        - active_profile 为商用路径 (非 free 档) 且引擎 commercial_use=False
          → 阻断注册 (False), 由调用方诚实噪止而非假装成功。
        - commercial_use=None (未核实) / 非商用档 / commercial_use=True
          → 放行 (True) (未核实仅降级 warn, 不误杀)。
    """
    registry = load_license_registry()
    license_meta = registry.get(engine_name)
    commercial = is_commercial_profile(active_profile)

    if license_meta is None or license_meta.commercial_use is None:
        # 未核实: 商用路径降级 warn 但放行, 非商用放行 → 一律放行。
        return True
    if license_meta.commercial_use is False:
        # 显式禁用商用: 仅商用路径阻断, 非商用放行。
        return not commercial
    # commercial_use=True → 所有路径放行。
    return True


def log_license_audit(engine_name: str, verdict: LicenseVerdict) -> None:
    """统一日志格式, 便于审计追踪。"""
    profile = get_active_profile()
    if verdict == LicenseVerdict.BLOCKED:
        logger.error(
            "license_guard: BLOCKED engine=%s profile=%s reason=commercial_use=false",
            engine_name,
            profile,
        )
    elif verdict == LicenseVerdict.WARN_UNVERIFIED:
        logger.warning(
            "license_guard: WARN_UNVERIFIED engine=%s profile=%s reason=commercial_use=null (未核实)",
            engine_name,
            profile,
        )
    else:
        logger.debug("license_guard: OK engine=%s profile=%s", engine_name, profile)


if __name__ == "__main__":
    # 手工校验入口: python -m src.audiobook_studio.tts.license_guard
    logging.basicConfig(level=logging.DEBUG)
    for eng in ["kokoro", "edge_tts", "azure_tts", "gcp_tts", "elevenlabs", "voxcpm2"]:
        verdict = check_engine_license(eng)
        log_license_audit(eng, verdict)
        logger.info(f"{eng}: {verdict.value}")

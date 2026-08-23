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

logger = logging.getLogger(__name__)

# 视为非商用 (免费档) 的 profile 名 → 守卫对 null/false 宽容 (不阻断)。
# 余下 (pro_studio / cloud_hybrid 等生产/商用倾向档) 触发严格商用守门。
_FREE_PROFILES = frozenset({"potato"})

# config/tts_licenses.yaml 相对仓库根路径 (license_guard 与硬件配置同目录约定)。
_LICENSES_PATH = Path("config/tts_licenses.yaml")


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
    path = config_path or _LICENSES_PATH
    try:
        import yaml  # 既有依赖 (hardware_profile 等已用), 非新增
    except ImportError:
        logger.warning("license_guard: pyyaml 未安装, 无法加载 TTS 许可表 → 全引擎按未核实降级")
        return {}

    if not Path(path).exists():
        logger.warning("license_guard: 许可配置缺失 (%s) → 全引擎按未核实降级", path)
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            raw: Dict[str, Any] = yaml.safe_load(f) or {}
    except Exception as e:  # pragma: no cover - 解析失败诚实降级
        logger.warning("license_guard: 许可配置解析失败 (%s): %s → 全引擎按未核实降级", path, e)
        return {}

    registry: Dict[str, EngineLicense] = {}
    engines = raw.get("engines") or {}
    if not isinstance(engines, dict):
        return registry
    for name, meta in engines.items():
        if not isinstance(meta, dict):
            continue
        cu = meta.get("commercial_use", None)
        # yaml null → None; 容错非 bool 字面 (只接受 bool/None)
        if cu is not None and not isinstance(cu, bool):
            cu = None
        registry[str(name)] = EngineLicense(
            commercial_use=cu,
            license_name=meta.get("license_name"),
            note=str(meta.get("note") or ""),
            verified_at=meta.get("verified_at"),
        )
    return registry


def is_commercial_profile(active_profile: Optional[str]) -> bool:
    """active_profile 是否商用倾向 (触发严格守门)。

    None/未知 → False (最保守: 不拦, 走 warn 通道, 免误杀可用引擎)。
    """
    if not active_profile:
        return False
    return active_profile.strip() not in _FREE_PROFILES


def check_engine_license(
    engine_name: str,
    active_profile: Optional[str],
    registry: Optional[Dict[str, EngineLicense]] = None,
) -> LicenseVerdict:
    """判定某引擎在给定 profile 下能否注册。

    红线#1 语义:
    - 非商用档 (potato / 未判定): 任何 commercial_use 都 OK (含 null/false)
      —— 免费档非商用场景本就不触发商用限制。
    - 商用档: commercial_use=True → OK; null → WARN_UNVERIFIED (降级不禁);
      false → BLOCKED (诚实噪止, 终止该引擎注册, 避免商用路径误用非商用引擎假装就绪)。
    """
    if registry is None:
        registry = load_license_registry()

    if not is_commercial_profile(active_profile):
        return LicenseVerdict.OK

    lic = registry.get(engine_name)
    if lic is None:
        # 无表项 = 未核实: 商用路径降级 warn, 不假成功也不阻断 (与 null 同语义)
        logger.warning(
            "license_guard: 引擎 %s 无许可声明 (商用档 %s) → 降级 warn (未核实, 不假成功)",
            engine_name,
            active_profile,
        )
        return LicenseVerdict.WARN_UNVERIFIED

    if lic.commercial_use is True:
        return LicenseVerdict.OK
    if lic.commercial_use is False:
        logger.warning(
            "license_guard: 引擎 %s 声明 commercial_use=False (仅非商用), 商用档 %s 禁用注册",
            engine_name,
            active_profile,
        )
        return LicenseVerdict.BLOCKED
    # commercial_use is None → 未核实
    logger.warning(
        "license_guard: 引擎 %s 许可未核实 (commercial_use=null), 商用档 %s 降级 warn",
        engine_name,
        active_profile,
    )
    return LicenseVerdict.WARN_UNVERIFIED


def register_guard(
    engine_name: str,
    active_profile: Optional[str],
    registry: Optional[Dict[str, EngineLicense]] = None,
) -> bool:
    """EngineRegistry.register 钩子: 返回是否允许注册该引擎。

    True = 放行 (ok / warn_unverified: 后者降级但不禁, 因阻断须凭已核实 false)。
    False = 阻断 (blocked: 商用路径明确禁用非商用引擎)。

    调用方应在 BLOCKED 时跳过该引擎注册, 并在日志记清原因 (不假装注册成功)。
    """
    verdict = check_engine_license(engine_name, active_profile, registry)
    return verdict != LicenseVerdict.BLOCKED

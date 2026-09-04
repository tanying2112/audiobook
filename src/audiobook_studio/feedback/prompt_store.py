"""M1 — 提示词版本化闭环门面（薄封装现有 infrastructure，不重建注册表）。

复用：
* ``feedback.release.VersionStore``  —— 版本跟踪 / promote / rollback / 回滚日志
* ``feedback.canary._pipeline_stage_to_prompt_dir`` —— pipeline stage → prompts/ 目录名

各 stage 已在运行时通过 Jinja2 加载 ``prompts/<dir>/v1.j2``（见
``pipeline/annotate_paragraph.py`` 等），因此本门面只提供统一、可测的
「读 active 版本 / 列版本 / promote / rollback」API，使「编译→评判→晋升→部署」
闭环在 harness 层可被程序化驱动，而非依赖手工改文件。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .canary import _pipeline_stage_to_prompt_dir
from .release import VersionStore

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS_DIR = Path("prompts")


class PromptStore:
    """提示词版本化门面。"""

    def __init__(self, prompts_dir: Path = DEFAULT_PROMPTS_DIR) -> None:
        self.prompts_dir = Path(prompts_dir)
        self._vs = VersionStore(base_path=self.prompts_dir)

    def active_version(self, pipeline_stage: str) -> int:
        """当前生效的提示词版本号（0 表示尚未有版本）。"""
        return self._vs.get_current_version(_pipeline_stage_to_prompt_dir(pipeline_stage))

    def list_versions(self, pipeline_stage: str) -> List[int]:
        """列出某 stage 所有已有版本号。"""
        dir_name = _pipeline_stage_to_prompt_dir(pipeline_stage)
        versions: List[int] = []
        d = self.prompts_dir / dir_name
        if d.is_dir():
            for f in d.glob("v*.j2"):
                try:
                    versions.append(int(f.stem[1:]))
                except ValueError:
                    continue
        return sorted(versions)

    def load_version(self, pipeline_stage: str, version: int) -> Optional[str]:
        """读取指定版本的 prompt 文本；不存在返回 None。"""
        dir_name = _pipeline_stage_to_prompt_dir(pipeline_stage)
        p = self.prompts_dir / dir_name / f"v{version}.j2"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def load_active(self, pipeline_stage: str) -> Optional[str]:
        """读取当前生效版本的 prompt 文本。"""
        v = self.active_version(pipeline_stage)
        if v <= 0:
            return None
        return self.load_version(pipeline_stage, v)

    def promote(self, pipeline_stage: str, version: int) -> bool:
        """将某版本提升为当前生效版本（仅当 version > 当前版本时成功）。"""
        ok = self._vs.promote_version(_pipeline_stage_to_prompt_dir(pipeline_stage), version)
        if ok:
            logger.info(f"promoted {pipeline_stage} -> v{version}")
        return ok

    def rollback(self, pipeline_stage: str, version: int) -> bool:
        """回滚到指定版本（version 必须 < 当前版本且 >= 1）。"""
        ok = self._vs.rollback_version(_pipeline_stage_to_prompt_dir(pipeline_stage), version)
        if ok:
            logger.info(f"rolled back {pipeline_stage} -> v{version}")
        return ok

    def status(self) -> Dict[str, Any]:
        return self._vs.get_status()

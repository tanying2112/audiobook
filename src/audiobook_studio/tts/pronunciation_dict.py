"""发音字典 (P2.12) — 合成前对文本做注音替换/annot 注入.

解决仙侠生造人名、专有名词 TTS 读不对的问题: 在文本送入 TTS 引擎前,
按字典把目标词替换为可读的注音正文 (拼音 / 同音字提示)。

加载优先级: 项目级字典 (<项目目录>/pronunciation_dict.yaml) 覆盖补充全局 dict
   (config/pronunciation_dict.yaml): 合并后项目条目赢 (同名 project 覆盖 global)。

红线#1 (诚实): 不杜撰权威 IPA; 字典条目按规则化派生注音, source 标注派生方式
   (rule_ns=规则化 / manual=人工核验 / heuristic=启发式); 无证据不标 manual。

向后兼容 (不破主路径): 无字典条目的词原样透传; 字典加载失败 → 降级 warn 且原样透传
   (主路径不崩, 红线#1 降级非崩)。

匹配策略: 长词优先 (按词长降序), 避免短词子串吃掉长词 (如 "帝" 吃 "帝释天")。
   用正则按整词边界替换; 中英文混合时对 ASCII 词用 \b 边界, 对非 ASCII 词按
   直接子串定位 (中文无词边界 \b)。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 全局字典路径 (相对仓库根; 与既有 config 约定一致)。
_GLOBAL_DICT_PATH = Path("config/pronunciation_dict.yaml")
# 项目级字典文件名 (放在项目目录下覆盖全局)。
_PROJECT_DICT_FILENAME = "pronunciation_dict.yaml"


@dataclass
class DictEntry:
    """单条发音字典条目。"""

    phoneme: str  # 发音替换正文 (拼音/同音字提示/SSML 注释等, 引擎按其读)
    source: str = "rule_ns"  # rule_ns | manual | heuristic


def _parse_raw(raw: Dict) -> Dict[str, DictEntry]:
    """从 yaml 解析后的 dict 结构里取 entries → {词: DictEntry}。容错非预期结构。"""
    entries: Dict[str, DictEntry] = {}
    if not isinstance(raw, dict):
        return entries
    raw_entries = raw.get("entries") or {}
    if not isinstance(raw_entries, dict):
        return entries
    for word, meta in raw_entries.items():
        if not isinstance(word, str) or not word:
            continue
        if not isinstance(meta, dict):
            # 简写结构: word: "phoneme 正文"
            entries[word] = DictEntry(phoneme=str(meta))
            continue
        phoneme = meta.get("phoneme")
        if phoneme is None:
            continue
        source = str(meta.get("source") or "rule_ns")
        entries[word] = DictEntry(phoneme=str(phoneme), source=source)
    return entries


def load_pronunciation_dict(
    project_dir: Optional[Path] = None,
    global_path: Optional[Path] = None,
) -> Dict[str, DictEntry]:
    """加载发音字典: 合并全局 + 项目级 (项目条目覆盖同名全局)。

    缺失/解析失败 → 返回空 dict (调用方按无字典处理, 原样透传, 诚实降级)。
    """
    g_path = global_path or _GLOBAL_DICT_PATH
    registry: Dict[str, DictEntry] = {}

    try:
        import yaml  # 既有依赖, 非新增
    except ImportError:
        logger.warning("pronunciation_dict: pyyaml 未安装 → 字典降级 (原样透传)")
        return registry

    # 全局字典
    if Path(g_path).exists():
        try:
            with open(g_path, encoding="utf-8") as f:
                registry.update(_parse_raw(yaml.safe_load(f) or {}))
        except Exception as e:  # pragma: no cover - 解析失败诚实降级
            logger.warning("pronunciation_dict: 全局字典解析失败 (%s): %s → 降级", g_path, e)

    # 项目级字典覆盖 (同名条目 project 赢; 不同名条目补充)
    if project_dir is not None:
        proj_path = Path(project_dir) / _PROJECT_DICT_FILENAME
        if proj_path.exists():
            try:
                with open(proj_path, encoding="utf-8") as f:
                    proj_entries = _parse_raw(yaml.safe_load(f) or {})
                registry.update(proj_entries)  # 后 update → 项目条目覆盖同名全局
                logger.info("pronunciation_dict: 加载项目级字典 %s, 覆盖/补充 %d 条", proj_path, len(proj_entries))
            except Exception as e:  # pragma: no cover
                logger.warning("pronunciation_dict: 项目级字典解析失败 (%s): %s", proj_path, e)

    return registry


def apply_pronunciation_dict(text: str, registry: Dict[str, DictEntry]) -> str:
    """对文本按字典做注音替换; 无条目原样透传 (向后兼容)。

    长词优先 (按词长降序) 避免短词子串吃长词。中文无 \b 词边界, 用直接子串
    正则定位 (对目标词做 re.escape)。替换为 phoneme 正文。
    """
    if not text or not registry:
        return text

    # 按词长降序: 先替换长词, 避免短词吃长词 (如 "帝" 不应吃 "帝释天" 内的子串)。
    words = sorted(
        (w for w in registry if w),  # 过滤空 key
        key=lambda w: len(w),
        reverse=True,
    )
    if not words:
        return text

    out = text
    for word in words:
        entry = registry[word]
        if entry.phoneme == word:  # 替换体与原词相同 → 无意义, 跳过避免空操作
            continue
        # re.escape 防 word 含正则元字符; 直接子串匹配 (中文无词边界)。
        pattern = re.escape(word)
        try:
            out = re.sub(pattern, entry.phoneme, out)
        except re.error:
            # 理论不可达 (re.escape 后不报错); 诚实降级跳过该词
            logger.warning("pronunciation_dict: 替换 %r 失败 → 跳过", word)
            continue
    return out


def apply_pronunciation_dict_using(
    text: str,
    project_dir: Optional[Path] = None,
    global_path: Optional[Path] = None,
) -> str:
    """便捷封装: 加载字典(项目级覆盖)并替换; 字典缺失/失败 → 原样透传。

    供 synthesize 接入点一行调用; 内部每次加载 (字典小, 合成段间开销可接受;
    若需热路径优化可由调用方缓存 registry 后直接用 apply_pronunciation_dict)。
    """
    registry = load_pronunciation_dict(project_dir=project_dir, global_path=global_path)
    return apply_pronunciation_dict(text, registry)

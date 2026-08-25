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

# Use UnifiedConfig for centralized configuration loading
from ..config.unified import get_unified_config

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

    # Load global dictionary via UnifiedConfig
    try:
        unified = get_unified_config()
        global_raw: Dict = unified.load_yaml_config("pronunciation_dict") or {}
        registry.update(_parse_raw(global_raw))
    except Exception as e:
        logger.warning("发音字典: 全局配置加载失败 (%s): %s", g_path, e)

    # Load project-level dictionary (if project_dir provided)
    if project_dir:
        p_path = Path(project_dir) / _PROJECT_DICT_FILENAME
        if p_path.exists():
            try:
                import yaml
                with open(p_path, encoding="utf-8") as f:
                    project_raw: Dict = yaml.safe_load(f) or {}
                registry.update(_parse_raw(project_raw))
                logger.info("发音字典: 已合并项目级字典 (%s)", p_path)
            except Exception as e:
                logger.warning("发音字典: 项目级配置加载失败 (%s): %s", p_path, e)

    return registry


def apply_pronunciation_dict(text: str, pronunciation_dict: Dict[str, DictEntry]) -> str:
    """对文本应用发音字典替换 (长词优先, 整词边界)。"""
    if not pronunciation_dict:
        return text

    # 按词长降序排序，长词优先匹配
    sorted_words = sorted(pronunciation_dict.keys(), key=len, reverse=True)

    for word in sorted_words:
        entry = pronunciation_dict[word]
        phoneme = entry.phoneme

        # 中英文混合边界处理
        if re.search(r"[\u4e00-\u9fff]", word):
            # 含中文字符: 直接子串替换 (中文无词边界 \b)
            text = text.replace(word, phoneme)
        else:
            # 纯 ASCII: 用单词边界 \b 防止误伤子串
            pattern = r"\b" + re.escape(word) + r"\b"
            text = re.sub(pattern, phoneme, text)

    return text


def get_pronunciation_dict(
    project_dir: Optional[Path] = None,
    global_path: Optional[Path] = None,
) -> Dict[str, DictEntry]:
    """获取发音字典 (模块级缓存, 便于复用)。"""
    # Module-level cache
    if not hasattr(get_pronunciation_dict, "_cache"):
        get_pronunciation_dict._cache = None
        get_pronunciation_dict._cache_key = None

    cache_key = (str(project_dir) if project_dir else None, str(global_path) if global_path else None)
    if get_pronunciation_dict._cache is not None and get_pronunciation_dict._cache_key == cache_key:
        return get_pronunciation_dict._cache

    result = load_pronunciation_dict(project_dir, global_path)
    get_pronunciation_dict._cache = result
    get_pronunciation_dict._cache_key = cache_key
    return result


if __name__ == "__main__":
    # 手工测试入口
    logging.basicConfig(level=logging.INFO)
    dict_data = load_pronunciation_dict()
    print(f"加载条目数: {len(dict_data)}")
    for word, entry in list(dict_data.items())[:10]:
        print(f"  {word} → {entry.phoneme} ({entry.source})")

    # 测试替换
    test_text = "帝释天降临了，帝释天很厉害。"
    result = apply_pronunciation_dict(test_text, dict_data)
    print(f"\n原文: {test_text}")
    print(f"替换后: {result}")

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
from typing import Dict, Optional

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
    # Gap #7 (2026-10-13) 词条音色敏感: 同一注音换音色后回听不再整词命中 —
    # Lenda→"Len da" 10 音色矩阵实证仅 6 音色过, am_liam/am_michael/am_puck
    # 需 "Lenn-dah", am_onyx 7 种拼写全败 (池内不可修)。
    # voice_variants: {voice_id: 该音色专用注音}; 恒等变体 (值=原词拼写)
    # 表示该音色按原词读 (不伤害红线)。未列出的音色一律用默认 phoneme。
    voice_variants: Optional[Dict[str, str]] = None


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
        if phoneme is None or not str(phoneme).strip():
            # Gap F: proposed (空 phoneme) 条目惰性跳过 — 只占位不替换,
            # 防止 apply 把目标词替换成空串。
            continue
        source = str(meta.get("source") or "rule_ns")
        voice_variants: Optional[Dict[str, str]] = None
        voices_raw = meta.get("voices")
        if isinstance(voices_raw, dict):
            # Gap #7: 分音色注音块 {voice_id: 注音}; 空值/非字符串滤除。
            voice_variants = {
                str(v): str(p)
                for v, p in voices_raw.items()
                if isinstance(v, str) and v and isinstance(p, str) and p.strip()
            } or None
        entries[word] = DictEntry(
            phoneme=str(phoneme), source=source, voice_variants=voice_variants
        )
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


def apply_pronunciation_dict(
    text: str,
    pronunciation_dict: Dict[str, DictEntry],
    voice_id: Optional[str] = None,
) -> str:
    """对文本应用发音字典替换 (长词优先, 整词边界)。

    voice_id (可选): 条目带 voice_variants 时优先取该音色专用注音, 未命中
    (含 "default"/blend 合成式) 回落默认 phoneme; 不传 → 一律默认 phoneme
    (旧调用方语义不变)。
    限制: voice_id 是段落级路由音色 — 句级 voice override 在此之后才解析,
    句级换音色的句子仍按段落音色选注音 (gap_report 行动项记后续)。
    """
    if not pronunciation_dict:
        return text

    # 按词长降序排序，长词优先匹配
    sorted_words = sorted(pronunciation_dict.keys(), key=len, reverse=True)

    for word in sorted_words:
        entry = pronunciation_dict[word]
        phoneme = entry.phoneme
        if voice_id and entry.voice_variants:
            # Gap #7: 该音色专用注音优先; 未列出回落默认 phoneme。
            phoneme = entry.voice_variants.get(voice_id, phoneme)

        # 中英文混合边界处理
        if re.search(r"[\u4e00-\u9fff]", word):
            # 含中文字符: 直接子串替换 (中文无词边界 \b)
            text = text.replace(word, phoneme)
        else:
            # 纯 ASCII: 用单词边界 \b 防止误伤子串
            pattern = r"\b" + re.escape(word) + r"\b"
            text = re.sub(pattern, phoneme, text)

    return text


# Gap F (2026-10-13): 启发式专名抽取的排除词表 — 句首大写词多为普通词,
# 书名/章节标题词不作专名提议。英文小写化后命中即排除。
_PROPER_NOUN_STOPWORDS = frozenset({
    "i", "the", "a", "an", "it's", "he's", "she's", "they're", "we're",
    "chapter", "one", "two", "three", "okay", "ok", "yes", "no", "not",
    "stars", "stripes", "cup",  # 本域队名等普通名词 (语料观察)
})


def propose_pronunciation_entries(
    text: str,
    language: Optional[str] = None,
    top_k: int = 40,
) -> Dict[str, Dict[str, str]]:
    """从书文本启发式抽取候选专名 → 词典模板条目 (Gap F: 分析→词典链).

    只提议、不发明发音 (红线#1): 每条 phoneme 留空, 由 LLM 注音或人工
    核对一次后填入 (随后合成回听 SenseVoice 验证 — 见
    scratch/ff_system/f_pron_dict_validate.py 的实证流程), 全书复用。

    启发式 (en): 句中大写词 (排除句首/对白引号内首词与停用词) 按频次排序,
    停用词先滤再切 top_k (防低频噪声按字母序挤掉高频人名); 连续大写词合并
    为短语 (如 "Sao Paulo")。zh 文本无大小写信号 → 返回空 (诚实: 无证据
    不提议, zh 专名仍走人工/LLM 渠道)。

    Returns:
        {词: {"phoneme": "", "source": "proposed"}} — 供生成项目级
        pronunciation_dict.yaml 模板; 空 phoneme 条目在 _parse_raw
        惰性跳过 (只占位不替换), 填入注音并回听验证后才生效。
    """
    if language and language.startswith("zh"):
        return {}
    # 句中大写词: 句首/对白引号内首词多为普通起始词, 用位置+停用词双滤。
    proposals: Dict[str, int] = {}
    tokens = re.split(r"(\s+)", text)  # 保留空白以判断句首
    at_sentence_start = True
    for tok in tokens:
        if not tok:
            continue
        if tok.isspace():
            continue
        # 对白引号内首词 ('We' is Stars / “I'm ready”): 开引号起句 → 句首。
        quote_open = tok[0] in "'\"“‘"
        word = tok.strip(".,!?;:'\"“”‘’()[]—-")
        if word and word[0].isupper() and not (at_sentence_start or quote_open):
            proposals[word] = proposals.get(word, 0) + 1
        at_sentence_start = (
            tok.endswith(("\n", "\r", ".", "!", "?", ":", '"', "”", "'")) or None
        )
    # 停用词/非 ASCII 先滤, 再按频次切 top_k (防 1 次噪声词挤掉高频人名)。
    ranked = sorted(
        (
            (w, c) for w, c in proposals.items()
            if w.lower() not in _PROPER_NOUN_STOPWORDS and w.isascii()
        ),
        key=lambda kv: (-kv[1], kv[0]),
    )[:top_k]
    return {w: {"phoneme": "", "source": "proposed"} for w, _c in ranked}


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
    logger.info(f"加载条目数: {len(dict_data)}")
    for word, entry in list(dict_data.items())[:10]:
        logger.info(f"  {word} → {entry.phoneme} ({entry.source})")

    # 测试替换
    test_text = "帝释天降临了，帝释天很厉害。"
    result = apply_pronunciation_dict(test_text, dict_data)
    logger.info(f"\n原文: {test_text}")
    logger.info(f"替换后: {result}")

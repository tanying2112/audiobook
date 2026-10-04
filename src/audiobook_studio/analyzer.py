"""Analyzer module — 结构分析与场景标签映射.

包含：
- LLM_ANALYSIS_PROMPT: LLM 结构分析提示词 JSON Schema（含 scene_tags 字段）
- SceneTagMapper: 场景标签到本地音效文件的映射器
- validate_scene_tags: 验证并补全 scene_tags 字段
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# LLM_ANALYSIS_PROMPT — 结构分析提示词 JSON Schema（含 scene_tags）
# =============================================================================

LLM_ANALYSIS_PROMPT: Dict[str, Any] = {
    "type": "object",
    "title": "BookAnalysisOutput",
    "description": "有声书结构分析输出 — 上帝视角完整档案",
    "properties": {
        "book_meta": {
            "type": "object",
            "title": "BookMeta",
            "description": "书籍元信息",
            "properties": {
                "title": {"type": "string", "description": "书名"},
                "author": {"type": ["string", "null"], "description": "作者"},
                "genre": {
                    "type": "string",
                    "enum": ["小说", "散文", "诗歌", "历史", "科普", "童话", "其他"],
                    "description": "体裁",
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["A", "B", "C", "D"],
                    "description": "难度等级",
                },
                "language": {"type": "string", "description": "ISO 639-1 语言代码"},
                "era": {"type": ["string", "null"], "description": "时代背景"},
                "total_chapters_estimated": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "预估总章节数",
                },
                "contract_version": {
                    "type": "integer",
                    "default": 1,
                    "description": "契约版本号",
                },
            },
            "required": [
                "title",
                "genre",
                "difficulty",
                "language",
                "total_chapters_estimated",
            ],
        },
        "character_voice_map": {
            "type": "array",
            "title": "CharacterVoiceBinding[]",
            "description": "角色声音绑定表（全本唯一 canonical_name）",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "canonical_name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "规范角色名（全本唯一）",
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "别名列表",
                    },
                    "gender": {
                        "type": "string",
                        "enum": ["male", "female", "neutral", "unknown"],
                        "default": "unknown",
                        "description": "性别",
                    },
                    "age_range": {
                        "type": "string",
                        "enum": ["child", "young", "adult", "elderly", "unknown"],
                        "default": "unknown",
                        "description": "年龄段",
                    },
                    "suggested_voice_id": {
                        "type": ["string", "null"],
                        "default": None,
                        "description": "建议声音 ID（TTS 引擎特定）",
                    },
                    "sample_quote": {
                        "type": "string",
                        "description": "用于声音克隆的样本引用文本",
                    },
                    "contract_version": {
                        "type": "integer",
                        "default": 1,
                        "description": "契约版本号",
                    },
                },
                "required": ["canonical_name", "sample_quote"],
            },
        },
        "emotion_snapshots": {
            "type": "array",
            "title": "EmotionSnapshot[]",
            "description": "每章情感快照",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "chapter": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "章节号",
                    },
                    "dominant_emotion": {
                        "type": "string",
                        "enum": [
                            "neutral",
                            "happy",
                            "sad",
                            "angry",
                            "fearful",
                            "surprised",
                            "disgusted",
                            "tense",
                            "tender",
                            "contemplative",
                        ],
                        "description": "主导情感",
                    },
                    "intensity": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "情感强度 0-1",
                    },
                    "notes": {
                        "type": "string",
                        "default": "",
                        "description": "备注",
                    },
                    "contract_version": {
                        "type": "integer",
                        "default": 1,
                        "description": "契约版本号",
                    },
                },
                "required": ["chapter", "dominant_emotion", "intensity"],
            },
        },
        "story_line_summary": {
            "type": "string",
            "minLength": 100,
            "maxLength": 500,
            "description": "故事主线摘要 100-500 字，包含主要人物、核心冲突、关键转折、结局走向",
        },
        "global_style_notes": {
            "type": "string",
            "description": "全局文风与特殊处理建议",
        },
        "scene_tags": {
            "type": "array",
            "title": "SceneTags",
            "description": "环境音效标签列表（如：[雷雨夜]、[繁华街道]、[酒馆喧闹]），用于后续环境音效匹配与混音",
            "items": {
                "type": "string",
                "description": "场景标签，建议使用中文方括号格式，如：雷雨夜、繁华街道、酒馆喧闹",
            },
            "minItems": 5,
            "maxItems": 15,
            "default": [],
            "examples": [
                ["雷雨夜", "繁华街道", "酒馆喧闹", "静谧书房", "战场硝烟"],
                ["森林鸟鸣", "海浪拍岸", "马车颠簸", "宫廷争斗", "地下室潮湿"],
            ],
        },
        "contract_version": {
            "type": "integer",
            "default": 1,
            "description": "契约版本号，用于追踪 schema 变更",
        },
    },
    "required": [
        "book_meta",
        "character_voice_map",
        "emotion_snapshots",
        "story_line_summary",
        "global_style_notes",
        "scene_tags",
    ],
    "additionalProperties": False,
}


# =============================================================================
# Scene Tag Mapping — 场景标签到本地音效文件的映射
# =============================================================================

# 默认音效库路径
DEFAULT_EFFECTS_LIBRARY_PATH = Path("assets/effects")

# 中文场景标签 -> 音效文件名映射表
SCENE_TAG_TO_FILENAME: Dict[str, str] = {
    "雷雨夜": "thunder_rain.mp3",
    "繁华街道": "busy_street.mp3",
    "酒馆喧闹": "tavern_ambience.mp3",
    "静谧书房": "quiet_study.mp3",
    "战场硝烟": "battlefield.mp3",
    "森林鸟鸣": "forest_birds.mp3",
    "海浪拍岸": "ocean_waves.mp3",
    "马车颠簸": "carriage_ride.mp3",
    "宫廷争斗": "palace_intrigue.mp3",
    "地下室潮湿": "damp_basement.mp3",
    "静谧厨房": "quiet_kitchen.mp3",
    "乡间田野": "countryside.mp3",
    "老屋灯下": "old_house_lamp.mp3",
    "四季更替": "seasons_change.mp3",
    "麦芽糖香": "kitchen_sweet.mp3",
}


class SceneTagMapper:
    """场景标签映射器 — 将 LLM 提取的 scene_tags 映射到本地 assets/effects/ 文件."""

    def __init__(
        self,
        effects_library_path: Optional[Path] = None,
        custom_mapping: Optional[Dict[str, str]] = None,
    ):
        """
        Args:
            effects_library_path: 音效库根目录，默认为 assets/effects/
            custom_mapping: 自定义标签到文件名的映射，会与默认映射合并
        """
        self.effects_library_path = effects_library_path or DEFAULT_EFFECTS_LIBRARY_PATH
        self.mapping = {**SCENE_TAG_TO_FILENAME}
        if custom_mapping:
            self.mapping.update(custom_mapping)

    def resolve(self, scene_tags: List[str]) -> List[Path]:
        """将场景标签列表解析为音效文件路径列表.

        Args:
            scene_tags: 场景标签列表，如 ["雷雨夜", "繁华街道"]

        Returns:
            对应的音效文件路径列表（不存在的文件会记录警告但不中断）
        """
        resolved: List[Path] = []
        for tag in scene_tags:
            # 清理标签：去除方括号、全角括号
            clean_tag = tag.strip("[]【】")
            filename = self.mapping.get(clean_tag, f"{clean_tag}.mp3")
            file_path = self.effects_library_path / filename
            if not file_path.exists():
                logger.warning(f"Scene tag '{tag}' -> 音效文件不存在: {file_path}")
            resolved.append(file_path)
        return resolved

    def resolve_with_validation(self, scene_tags: List[str], require_exists: bool = False) -> List[Path]:
        """解析场景标签并可选择性要求文件必须存在.

        Args:
            scene_tags: 场景标签列表
            require_exists: 为 True 时，缺失文件会抛出 FileNotFoundError

        Returns:
            存在的音效文件路径列表

        Raises:
            FileNotFoundError: require_exists=True 且有文件不存在时
        """
        resolved = self.resolve(scene_tags)
        missing = [p for p in resolved if not p.exists()]
        if missing and require_exists:
            raise FileNotFoundError(f"以下场景音效文件缺失: {missing}")
        # 仅返回存在的文件
        return [p for p in resolved if p.exists()]

    def get_available_tags(self) -> List[str]:
        """获取当前映射表中所有支持的场景标签."""
        return list(self.mapping.keys())

    def add_mapping(self, tag: str, filename: str) -> None:
        """添加或更新自定义标签映射."""
        self.mapping[tag] = filename


# =============================================================================
# Validation & Normalization — 验证与补全 scene_tags
# =============================================================================


def normalize_scene_tag(tag: str) -> str:
    """标准化场景标签：去除方括号、全角括号、首尾空白."""
    return tag.strip(" []【】\t\n\r")


def validate_scene_tags(
    scene_tags: Optional[List[str]],
    min_tags: int = 5,
    max_tags: int = 15,
    default_tags: Optional[List[str]] = None,
) -> List[str]:
    """验证并补全 scene_tags 字段.

    Args:
        scene_tags: 原始场景标签列表（可能为 None、空、或包含脏数据）
        min_tags: 最少标签数，默认 5
        max_tags: 最多标签数，默认 15
        default_tags: 当输入为空或无效时的默认标签列表

    Returns:
        标准化后的场景标签列表，长度在 [min_tags, max_tags] 范围内

    Raises:
        ValueError: 无法生成有效标签列表时
    """
    if default_tags is None:
        default_tags = [
            "雷雨夜",
            "繁华街道",
            "酒馆喧闹",
            "静谧书房",
            "森林鸟鸣",
        ]

    # 处理 None 或空列表
    if not scene_tags:
        logger.warning("scene_tags 为空，使用默认标签")
        return default_tags[:max_tags]

    # 标准化每个标签
    normalized = []
    seen = set()
    for tag in scene_tags:
        if not isinstance(tag, str):
            logger.warning(f"忽略非字符串标签: {tag!r}")
            continue
        clean = normalize_scene_tag(tag)
        if not clean:
            continue
        if clean in seen:
            logger.debug(f"忽略重复标签: {clean}")
            continue
        seen.add(clean)
        normalized.append(clean)

    # 截断或补全
    if len(normalized) > max_tags:
        logger.warning(f"scene_tags 数量 {len(normalized)} 超过上限 {max_tags}，截断")
        normalized = normalized[:max_tags]
    elif len(normalized) < min_tags:
        # 从默认标签中补充
        needed = min_tags - len(normalized)
        for tag in default_tags:
            if tag not in seen:
                normalized.append(tag)
                seen.add(tag)
                needed -= 1
                if needed == 0:
                    break
        logger.info(f"scene_tags 数量不足，已补全至 {len(normalized)} 个")

    return normalized


def ensure_scene_tags_in_output(
    analysis_output: Dict[str, Any],
    min_tags: int = 5,
    max_tags: int = 15,
) -> Dict[str, Any]:
    """确保分析输出 JSON 包含合法的 scene_tags 字段（原地修改并返回）.

    Args:
        analysis_output: LLM 返回的原始分析结果字典
        min_tags: 最少标签数
        max_tags: 最多标签数

    Returns:
        补全后的分析结果字典
    """
    if "scene_tags" not in analysis_output:
        logger.warning("分析输出缺少 scene_tags 字段，自动补全")
        analysis_output["scene_tags"] = []

    validated = validate_scene_tags(analysis_output["scene_tags"], min_tags=min_tags, max_tags=max_tags)
    analysis_output["scene_tags"] = validated
    return analysis_output


# =============================================================================
# Pydantic Models — 用于类型安全的内部数据结构
# =============================================================================


class SceneTagInfo(BaseModel):
    """场景标签信息."""

    tag: str = Field(..., description="原始标签")
    normalized_tag: str = Field(..., description="标准化后的标签")
    file_path: Optional[Path] = Field(None, description="对应的音效文件路径")
    file_exists: bool = Field(False, description="文件是否存在")
    mapped_filename: Optional[str] = Field(None, description="映射的文件名")


class SceneTagAnalysisResult(BaseModel):
    """场景标签分析结果."""

    scene_tags: List[SceneTagInfo] = Field(default_factory=list)
    total_tags: int = Field(0, description="标签总数")
    available_count: int = Field(0, description="可用音效文件数")
    missing_count: int = Field(0, description="缺失音效文件数")
    missing_tags: List[str] = Field(default_factory=list, description="缺失文件的标签列表")

    @classmethod
    def from_tags(cls, scene_tags: List[str], mapper: SceneTagMapper) -> "SceneTagAnalysisResult":
        """从标签列表创建分析结果."""
        infos = []
        missing = []
        available = 0
        for tag in scene_tags:
            clean = normalize_scene_tag(tag)
            filename = mapper.mapping.get(clean, f"{clean}.mp3")
            path = mapper.effects_library_path / filename
            exists = path.exists()
            if exists:
                available += 1
            else:
                missing.append(clean)
            infos.append(
                SceneTagInfo(
                    tag=tag,
                    normalized_tag=clean,
                    file_path=path if exists else None,
                    file_exists=exists,
                    mapped_filename=filename,
                )
            )
        return cls(
            scene_tags=infos,
            total_tags=len(infos),
            available_count=available,
            missing_count=len(missing),
            missing_tags=missing,
        )


# =============================================================================
# Convenience Functions — 便捷函数
# =============================================================================


def create_scene_tag_mapper(
    effects_library_path: Optional[Path] = None,
) -> SceneTagMapper:
    """创建场景标签映射器实例."""
    return SceneTagMapper(effects_library_path=effects_library_path)


def analyze_scene_tags(
    scene_tags: List[str],
    effects_library_path: Optional[Path] = None,
) -> SceneTagAnalysisResult:
    """分析场景标签并返回详细结果."""
    mapper = create_scene_tag_mapper(effects_library_path)
    return SceneTagAnalysisResult.from_tags(scene_tags, mapper)


def resolve_scene_tags_to_files(
    scene_tags: List[str],
    effects_library_path: Optional[Path] = None,
) -> List[Path]:
    """将场景标签解析为音效文件路径（便捷函数）."""
    mapper = create_scene_tag_mapper(effects_library_path)
    return mapper.resolve(scene_tags)

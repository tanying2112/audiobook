"""SOP Reflection Module — Module 4.2: Self-Evolution System.

Background thread that watches frontend user corrections (emotion/speed tags),
triggers LLM reflection to update config/agent_sop.json with genre-specific rules,
auto-applies on next same-genre novel import.

Components:
- SOPConfig: Load/save/merge agent_sop.json
- CorrectionCollector: Queue for frontend user corrections
- ReflectionEngine: LLM-powered rule synthesis from corrections
- SOPBackgroundThread: Daemon thread for continuous reflection
- GenreDetector: Auto-detect genre from book meta
- RuleApplier: Apply learned rules during annotation stage
"""

import json
import logging
import threading
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional

from src.audiobook_studio.schemas import BookMeta

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class UserCorrection:
    """A single user correction captured from frontend."""

    timestamp: str
    project_id: int
    chapter_index: int
    paragraph_index: int
    field: str  # "emotion", "speech_rate", "pitch_shift_semitones", "pause_before_ms", "pause_after_ms", "sfx_tags"
    original_value: Any
    corrected_value: Any
    genre: str
    context: Dict[str, Any] = field(default_factory=dict)
    """Additional context: speaker, is_dialogue, text_preview, etc."""


@dataclass
class CorrectionBatch:
    """Batch of corrections for reflection."""

    corrections: List[UserCorrection]
    genre: str
    project_id: int
    collected_at: str


@dataclass
class ReflectionResult:
    """Result of LLM reflection on corrections."""

    genre: str
    proposed_rules: Dict[str, Any]
    confidence: float
    reasoning: str
    corrections_analyzed: int
    timestamp: str


# ── SOP Configuration Manager ────────────────────────────────────────────────


class SOPConfig:
    """Load, save, and manage agent_sop.json configuration."""

    DEFAULT_CONFIG_PATH = Path("config/agent_sop.json")

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        """Load configuration from file."""
        with self._lock:
            if self.config_path.exists():
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        self._config = json.load(f)
                    logger.info(f"[SOP] Loaded config from {self.config_path}")
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"[SOP] Failed to load config: {e}")
                    self._config = self._default_config()
            else:
                logger.warning(f"[SOP] Config not found at {self.config_path}, creating default")
                self._config = self._default_config()
                self.save()

    def _default_config(self) -> Dict[str, Any]:
        """Return minimal default configuration."""
        return {
            "version": "1.0",
            "genres": {
                "default": {
                    "name": "默认通用",
                    "rules": {
                        "emotion_defaults": {"默认": "neutral"},
                        "speech_rate": {"default": 1.0},
                        "pitch_shifts": {"narrator": 0},
                        "pause_patterns": {"default_pause": 300},
                        "sfx_rules": {"enabled": False},
                        "voice_bindings": {"narrator": "zh-CN-XiaoxiaoNeural"},
                    },
                    "learning_stats": {"corrections_received": 0, "confidence": 0.5},
                }
            },
            "global_settings": {
                "learning_enabled": True,
                "min_corrections_for_update": 3,
                "confidence_threshold": 0.65,
            },
        }

    def save(self, backup: bool = True) -> bool:
        """Save configuration to file with optional backup."""
        with self._lock:
            try:
                # Update timestamp
                self._config["last_updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

                # Backup if enabled
                if backup and self.config_path.exists():
                    backup_path = self.config_path.with_suffix(
                        f".bak.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
                    )
                    self.config_path.rename(backup_path)
                    logger.debug(f"[SOP] Backed up config to {backup_path}")

                # Write new config
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self._config, f, ensure_ascii=False, indent=2)

                logger.info(f"[SOP] Saved config to {self.config_path}")
                return True
            except OSError as e:
                logger.error(f"[SOP] Failed to save config: {e}")
                return False

    def get_genre_rules(self, genre: str) -> Dict[str, Any]:
        """Get rules for a specific genre, with fallback to default."""
        with self._lock:
            genre_key = self._normalize_genre(genre)
            if genre_key in self._config.get("genres", {}):
                return deepcopy(self._config["genres"][genre_key].get("rules", {}))
            return deepcopy(self._config.get("genres", {}).get("default", {}).get("rules", {}))

    def get_genre_config(self, genre: str) -> Dict[str, Any]:
        """Get full genre config including learning_stats."""
        with self._lock:
            genre_key = self._normalize_genre(genre)
            if genre_key in self._config.get("genres", {}):
                return deepcopy(self._config["genres"][genre_key])
            return deepcopy(self._config.get("genres", {}).get("default", {}))

    def _normalize_genre(self, genre: str) -> str:
        """Normalize genre name to config key."""
        genre_lower = genre.strip().lower()
        for key, config in self._config.get("genres", {}).items():
            if key.lower() == genre_lower:
                return key
            if genre_lower in [a.lower() for a in config.get("aliases", [])]:
                return key
        return "default"

    def update_genre_rules(self, genre: str, new_rules: Dict[str, Any], confidence: float, reasoning: str) -> bool:
        """Merge new rules into genre config."""
        with self._lock:
            genre_key = self._normalize_genre(genre)
            if genre_key not in self._config.get("genres", {}):
                # Create new genre entry
                self._config.setdefault("genres", {})[genre_key] = {
                    "name": genre,
                    "aliases": [],
                    "rules": {},
                    "learning_stats": {
                        "corrections_received": 0,
                        "rules_updated": 0,
                        "last_correction": None,
                        "confidence": 0.5,
                    },
                }

            genre_config = self._config["genres"][genre_key]
            rules = genre_config.setdefault("rules", {})
            stats = genre_config.setdefault(
                "learning_stats",
                {"corrections_received": 0, "rules_updated": 0, "last_correction": None, "confidence": 0.5},
            )

            # Deep merge rules
            self._deep_merge(rules, new_rules)

            # Update stats
            stats["rules_updated"] = stats.get("rules_updated", 0) + 1
            stats["last_correction"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            stats["confidence"] = max(stats.get("confidence", 0.5), confidence)
            genre_config["last_learned_from"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            return self.save()

    def _deep_merge(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Deep merge source into target."""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = deepcopy(value)

    def record_correction(self, genre: str) -> None:
        """Increment correction counter for genre."""
        with self._lock:
            genre_key = self._normalize_genre(genre)
            if genre_key in self._config.get("genres", {}):
                stats = self._config["genres"][genre_key].setdefault("learning_stats", {})
                stats["corrections_received"] = stats.get("corrections_received", 0) + 1
                self.save(backup=False)

    def get_global_settings(self) -> Dict[str, Any]:
        """Get global SOP settings."""
        with self._lock:
            return deepcopy(self._config.get("global_settings", {}))

    def is_learning_enabled(self) -> bool:
        """Check if learning is enabled."""
        return self.get_global_settings().get("learning_enabled", True)

    def get_min_corrections_for_update(self) -> int:
        """Get minimum corrections needed before triggering reflection."""
        return self.get_global_settings().get("min_corrections_for_update", 3)

    def get_confidence_threshold(self) -> float:
        """Get confidence threshold for applying learned rules."""
        return self.get_global_settings().get("confidence_threshold", 0.65)

    def get_reflection_model(self) -> str:
        """Get LLM model for reflection."""
        return self.get_global_settings().get("reflection_model", "gpt-4o-mini")

    def get_reflection_temperature(self) -> float:
        """Get LLM temperature for reflection."""
        return self.get_global_settings().get("reflection_temperature", 0.3)

    def list_genres(self) -> List[str]:
        """List all configured genres."""
        with self._lock:
            return list(self._config.get("genres", {}).keys())

    def get_config_snapshot(self) -> Dict[str, Any]:
        """Get full config snapshot for debugging."""
        with self._lock:
            return deepcopy(self._config)


# ── Correction Collector ─────────────────────────────────────────────────────


class CorrectionCollector:
    """Thread-safe queue for collecting user corrections from frontend."""

    def __init__(self, max_size: int = 10000):
        self._queue: Queue[UserCorrection] = Queue(maxsize=max_size)
        self._lock = threading.Lock()
        self._project_genre_cache: Dict[int, str] = {}

    def add_correction(self, correction: UserCorrection) -> bool:
        """Add a user correction to the queue."""
        try:
            self._queue.put_nowait(correction)
            logger.debug(f"[SOP] Queued correction: {correction.field} for project {correction.project_id}")
            return True
        except Exception as e:
            logger.warning(f"[SOP] Correction queue full, dropping correction: {e}")
            return False

    def add_correction_dict(self, data: Dict[str, Any]) -> bool:
        """Add correction from dict (e.g., from WebSocket message)."""
        correction = UserCorrection(
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
            project_id=data["project_id"],
            chapter_index=data["chapter_index"],
            paragraph_index=data["paragraph_index"],
            field=data["field"],
            original_value=data["original_value"],
            corrected_value=data["corrected_value"],
            genre=data.get("genre", "default"),
            context=data.get("context", {}),
        )
        return self.add_correction(correction)

    def get_batch(self, max_size: int = 100, timeout: float = 1.0) -> List[UserCorrection]:
        """Get a batch of corrections from the queue."""
        batch = []
        deadline = time.time() + timeout
        while len(batch) < max_size:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                item = self._queue.get(timeout=min(remaining, 0.1))
                batch.append(item)
            except Empty:
                break
        return batch

    def get_corrections_by_genre(self, genre: str, max_size: int = 100) -> List[UserCorrection]:
        """Get corrections for a specific genre (drains queue)."""
        all_corrections = self.get_batch(max_size * 3)  # Get extra to filter
        genre_corrections = [c for c in all_corrections if c.genre == genre]
        # Put back non-matching corrections
        for c in all_corrections:
            if c.genre != genre:
                try:
                    self._queue.put_nowait(c)
                except Exception:
                    pass
        return genre_corrections[:max_size]

    def cache_project_genre(self, project_id: int, genre: str) -> None:
        """Cache genre for a project to avoid repeated lookups."""
        with self._lock:
            self._project_genre_cache[project_id] = genre

    def get_project_genre(self, project_id: int) -> Optional[str]:
        """Get cached genre for a project."""
        with self._lock:
            return self._project_genre_cache.get(project_id)

    def queue_size(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()


# ── Genre Detector ───────────────────────────────────────────────────────────


class GenreDetector:
    """Detect book genre from BookMeta or text analysis."""

    GENRE_KEYWORDS = {
        "玄幻": [
            "修仙",
            "灵气",
            "丹田",
            "筑基",
            "金丹",
            "元婴",
            "渡劫",
            "飞升",
            "宗门",
            "功法",
            "法宝",
            "御剑",
            "洞府",
            "灵石",
            "秘境",
            "大乘",
            "合体",
            "化神",
            "炼虚",
            "返虚",
        ],
        "仙侠": [
            "修真",
            "长生",
            "道友",
            "师兄",
            "师姐",
            "掌门",
            "长老",
            "峰主",
            "灵根",
            "天灵根",
            "废柴",
            "逆天",
            "机缘",
            "造化",
        ],
        "都市": [
            "公司",
            "总裁",
            "职场",
            "办公室",
            "项目",
            "会议",
            "客户",
            "合同",
            "谈判",
            "股份",
            "上市",
            "创业",
            "投资",
            "白领",
            "写字楼",
        ],
        "历史": [
            "皇帝",
            "朝廷",
            "大臣",
            "皇上",
            "臣",
            "奏折",
            "朝堂",
            "藩王",
            "边关",
            "兵部",
            "户部",
            "礼部",
            "刑部",
            "工部",
            "吏部",
        ],
        "科幻": [
            "星际",
            "飞船",
            "AI",
            "人工智能",
            "虚拟",
            "赛博",
            "机甲",
            "基因",
            "克隆",
            "穿越",
            "平行宇宙",
            "量子",
            "纳米",
            "脑机接口",
        ],
        "悬疑": [
            "凶手",
            "线索",
            "推理",
            "侦探",
            "尸体",
            "现场",
            "作案",
            "动机",
            "不在场证明",
            "指纹",
            "DNA",
            "监控",
            "证人",
            "供词",
        ],
        "言情": [
            "心动",
            "喜欢",
            "爱上",
            "吻",
            "拥抱",
            "表白",
            "告白",
            "男友",
            "女友",
            "结婚",
            "求婚",
            "订婚",
            "恋人",
            "暗恋",
            "单恋",
        ],
    }

    def __init__(self, sop_config: Optional[SOPConfig] = None):
        self.sop_config = sop_config or SOPConfig()

    def detect_from_meta(self, book_meta: BookMeta) -> str:
        """Detect genre from BookMeta."""
        # Map broad BookMeta genre to SOP genre keys
        broad_to_sop = {
            "小说": "default",  # Will be refined by chapter analysis
            "历史": "历史",
            "其他": "default",
        }
        return broad_to_sop.get(book_meta.genre, "default")

    def detect_from_text(self, text: str) -> str:
        """Detect genre from text using keyword matching."""
        text_lower = text.lower()
        scores = {}
        for genre, keywords in self.GENRE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[genre] = score

        if scores:
            return max(scores, key=scores.get)
        return "default"

    def detect_from_chapter_analysis(self, analyzed_json: Dict[str, Any]) -> str:
        """Detect genre from chapter analysis JSON."""
        # Check scene_tags first (most specific)
        scene_tags = analyzed_json.get("scene_tags", [])
        for tag in scene_tags:
            for genre, keywords in self.GENRE_KEYWORDS.items():
                if any(kw in tag for kw in keywords):
                    return genre

        # Check story_line_summary
        story_summary = analyzed_json.get("story_line_summary", "")
        genre_from_text = self.detect_from_text(story_summary)
        if genre_from_text != "default":
            return genre_from_text

        # Fall back to book_meta genre (broad category)
        book_meta = analyzed_json.get("book_meta", {})
        if book_meta.get("genre"):
            # Map broad genre to SOP genre
            broad_to_sop = {"历史": "历史"}
            return broad_to_sop.get(book_meta["genre"], "default")

        return "default"


# ── Reflection Engine ────────────────────────────────────────────────────────


class ReflectionEngine:
    """LLM-powered reflection to synthesize rules from user corrections."""

    def __init__(self, sop_config: SOPConfig, llm_client: Optional[Callable] = None):
        self.sop_config = sop_config
        self.llm_client = llm_client
        self._reflection_prompt = self._build_reflection_prompt()

    def _build_reflection_prompt(self) -> str:
        return """你是一个有声书制作专家，专门分析用户对段落标注的修正，总结出该体裁（genre）的通用规则。

**输入**：
- 体裁：{genre}
- 用户修正列表（每条包含：字段、原值、修正值、上下文）
- 当前该体裁的规则配置

**任务**：
分析这些修正的模式，提炼出该体裁的通用规则更新建议。重点关注：
1. emotion（情感标签）的系统性偏差
2. speech_rate（语速）的体裁特征
3. pitch_shift_semitones（音高）的角色模式
4. pause_before/after_ms（停顿）的结构规律
5. sfx_tags（音效）的使用偏好

**输出格式**（JSON）：
{{
  "proposed_rules": {{
    "emotion_defaults": {{"场景名": "情感标签"}},
    "speech_rate": {{"角色/场景": 语速值}},
    "pitch_shifts": {{"角色类型": 半音数}},
    "pause_patterns": {{"触发条件": 毫秒数}},
    "sfx_rules": {{"enabled": true/false, "default_sfx": [...], "场景": [...]}},
    "voice_bindings": {{"角色类型": "voice_id"}}
  }},
  "confidence": 0.0-1.0,
  "reasoning": "简要说明推理依据，引用具体修正例子"
}}

**原则**：
- 只输出有统计显著性的模式（至少3次相似修正）
- 保守更新：confidence < 0.65 时不建议应用
- 保持现有规则结构，只增量更新
- 推理要具体，引用修正的字段和值
"""

    def reflect(self, genre: str, corrections: List[UserCorrection]) -> ReflectionResult:
        """Run reflection on corrections for a genre."""
        if not corrections:
            return ReflectionResult(
                genre=genre,
                proposed_rules={},
                confidence=0.0,
                reasoning="No corrections to analyze",
                corrections_analyzed=0,
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )

        # Group corrections by field
        by_field: Dict[str, List[UserCorrection]] = {}
        for c in corrections:
            by_field.setdefault(c.field, []).append(c)

        # Get current rules for context
        current_rules = self.sop_config.get_genre_rules(genre)

        # Build correction summary for LLM
        correction_summary = []
        for field, corrs in by_field.items():
            # Find most common correction patterns
            patterns = {}
            for c in corrs:
                key = f"{c.original_value} -> {c.corrected_value}"
                patterns[key] = patterns.get(key, 0) + 1
            top_patterns = sorted(patterns.items(), key=lambda x: -x[1])[:3]
            correction_summary.append(
                {
                    "field": field,
                    "count": len(corrs),
                    "top_patterns": [{"pattern": p, "count": c} for p, c in top_patterns],
                    "contexts": [c.context for c in corrs[:5]],  # Sample contexts
                }
            )

        # If no LLM client, use heuristic rules
        if self.llm_client is None:
            return self._heuristic_reflection(genre, correction_summary, current_rules)

        # Call LLM
        prompt = self._reflection_prompt.format(genre=genre)
        prompt += f"\n\n当前规则：\n{json.dumps(current_rules, ensure_ascii=False, indent=2)}"
        prompt += f"\n\n修正统计：\n{json.dumps(correction_summary, ensure_ascii=False, indent=2)}"

        try:
            response = self.llm_client(prompt)
            result = json.loads(response)
            return ReflectionResult(
                genre=genre,
                proposed_rules=result.get("proposed_rules", {}),
                confidence=result.get("confidence", 0.0),
                reasoning=result.get("reasoning", ""),
                corrections_analyzed=len(corrections),
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
        except Exception as e:
            logger.error(f"[SOP] Reflection LLM call failed: {e}")
            return self._heuristic_reflection(genre, correction_summary, current_rules)

    def _heuristic_reflection(
        self, genre: str, correction_summary: List[Dict], current_rules: Dict[str, Any]
    ) -> ReflectionResult:
        """Heuristic reflection without LLM."""
        proposed = {}
        total_corrections = sum(c["count"] for c in correction_summary)
        significant_patterns = 0

        for cs in correction_summary:
            field = cs["field"]
            count = cs["count"]
            if count < 3:  # Need at least 3 corrections for a pattern
                continue

            for pattern_info in cs["top_patterns"]:
                pattern = pattern_info["pattern"]
                pattern_count = pattern_info["count"]
                if pattern_count < 2:
                    continue

                significant_patterns += 1
                orig, corrected = pattern.split(" -> ")

                # Map field to rule category
                if field == "emotion":
                    proposed.setdefault("emotion_defaults", {})[
                        f"learned_{len(proposed.get('emotion_defaults', {}))}"
                    ] = corrected
                elif field == "speech_rate":
                    proposed.setdefault("speech_rate", {})[f"learned_{len(proposed.get('speech_rate', {}))}"] = float(
                        corrected
                    )
                elif field == "pitch_shift_semitones":
                    proposed.setdefault("pitch_shifts", {})[f"learned_{len(proposed.get('pitch_shifts', {}))}"] = int(
                        corrected
                    )
                elif field in ("pause_before_ms", "pause_after_ms"):
                    proposed.setdefault("pause_patterns", {})[f"learned_{len(proposed.get('pause_patterns', {}))}"] = (
                        int(corrected)
                    )
                elif field == "sfx_tags":
                    sfx_list = corrected if isinstance(corrected, list) else [corrected]
                    proposed.setdefault("sfx_rules", {}).setdefault("default_sfx", []).extend(sfx_list)
                    proposed["sfx_rules"]["enabled"] = True

        confidence = min(0.5 + (significant_patterns * 0.1), 0.85) if significant_patterns > 0 else 0.0

        return ReflectionResult(
            genre=genre,
            proposed_rules=proposed,
            confidence=confidence,
            reasoning=f"Heuristic analysis: {significant_patterns} significant patterns from {total_corrections} corrections",
            corrections_analyzed=total_corrections,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )


# ── Rule Applier ─────────────────────────────────────────────────────────────


class RuleApplier:
    """Apply learned SOP rules during annotation stage."""

    def __init__(self, sop_config: SOPConfig):
        self.sop_config = sop_config

    def apply_to_annotation_input(
        self, input_data: "ParagraphAnnotationInput", genre: str
    ) -> "ParagraphAnnotationInput":
        """Enhance annotation input with learned genre rules."""
        rules = self.sop_config.get_genre_rules(genre)
        if not rules:
            return input_data

        # Create a copy to modify
        from src.audiobook_studio.schemas.paragraph import ParagraphAnnotationInput

        enhanced = input_data.model_copy(deep=True)

        # Apply emotion defaults for context
        emotion_defaults = rules.get("emotion_defaults", {})
        if emotion_defaults and enhanced.emotion_snapshot:
            # Could enhance emotion_snapshot based on scene_tags
            pass

        # Apply speech_rate defaults
        speech_rates = rules.get("speech_rate", {})
        if speech_rates:
            # Could set default speech_rate in global_style_notes or context
            pass

        # Apply voice bindings
        voice_bindings = rules.get("voice_bindings", {})
        if voice_bindings and enhanced.character_voice_map:
            # Merge learned voice bindings
            for binding in enhanced.character_voice_map:
                role_key = self._map_character_to_role(binding.canonical_name)
                if role_key in voice_bindings:
                    binding.suggested_voice_id = voice_bindings[role_key]

        return enhanced

    def apply_to_audio_postprocess(self, segment: Dict[str, Any], genre: str, speaker_role: str) -> Dict[str, Any]:
        """Apply learned rules to audio post-process parameters."""
        rules = self.sop_config.get_genre_rules(genre)
        if not rules:
            return segment

        enhanced = segment.copy()

        # Apply speech rate
        speech_rates = rules.get("speech_rate", {})
        if speaker_role in speech_rates:
            enhanced["speed"] = speech_rates[speaker_role]
        elif "default" in speech_rates and "speed" not in enhanced:
            enhanced["speed"] = speech_rates["default"]

        # Apply pitch shift
        pitch_shifts = rules.get("pitch_shifts", {})
        if speaker_role in pitch_shifts:
            enhanced["pitch_hz"] = pitch_shifts[speaker_role] * 6.0  # semitones to Hz approx

        # Apply pause patterns
        pause_patterns = rules.get("pause_patterns", {})
        # Context-dependent, would need more info

        # Apply SFX rules
        sfx_rules = rules.get("sfx_rules", {})
        if sfx_rules.get("enabled") and not enhanced.get("needs_sfx"):
            # Could enable SFX based on scene tags
            pass

        return enhanced

    def _map_character_to_role(self, canonical_name: str) -> str:
        """Map character name to role type for voice binding lookup."""
        name_lower = canonical_name.lower()
        if "narrator" in name_lower or "旁白" in name_lower:
            return "narrator"
        if any(kw in name_lower for kw in ["主角", "protagonist", "hero"]):
            return "protagonist"
        if any(kw in name_lower for kw in ["反派", "villain", "boss", "大反派"]):
            return "antagonist"
        if any(kw in name_lower for kw in ["长老", "elder", "老祖"]):
            return "elder"
        if any(kw in name_lower for kw in ["师兄", "师姐", "同门"]):
            return "fellow_disciple"
        if any(kw in name_lower for kw in ["女主", "heroine", "夫人", "小姐"]):
            return "female_lead"
        if any(kw in name_lower for kw in ["魔", "demon", "妖", "beast"]):
            return "demon_lord"
        return "narrator"


# ── Background Reflection Thread ─────────────────────────────────────────────


class SOPBackgroundThread:
    """Daemon thread for continuous SOP reflection."""

    def __init__(
        self,
        sop_config: SOPConfig,
        correction_collector: CorrectionCollector,
        reflection_engine: ReflectionEngine,
        check_interval: float = 30.0,
    ):
        self.sop_config = sop_config
        self.collector = correction_collector
        self.engine = reflection_engine
        self.check_interval = check_interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_reflection: Dict[str, float] = {}  # genre -> timestamp

    def start(self) -> None:
        """Start the background reflection thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("[SOP] Background thread already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="SOPReflectionThread", daemon=True)
        self._thread.start()
        logger.info("[SOP] Background reflection thread started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            logger.info("[SOP] Background reflection thread stopped")

    def _run(self) -> None:
        """Main loop for background reflection."""
        while not self._stop_event.is_set():
            try:
                self._check_and_reflect()
            except Exception as e:
                logger.error(f"[SOP] Reflection loop error: {e}")

            # Sleep with interruption check
            self._stop_event.wait(self.check_interval)

    def _check_and_reflect(self) -> None:
        """Check for accumulated corrections and trigger reflection if threshold met."""
        if not self.sop_config.is_learning_enabled():
            return

        min_corrections = self.sop_config.get_min_corrections_for_update()
        confidence_threshold = self.sop_config.get_confidence_threshold()

        # Get all genres that have corrections
        # We drain the queue and group by genre
        all_corrections = self.collector.get_batch(max_size=500)
        if not all_corrections:
            return

        # Group by genre
        by_genre: Dict[str, List[UserCorrection]] = {}
        for c in all_corrections:
            by_genre.setdefault(c.genre, []).append(c)

        # Check each genre
        for genre, corrections in by_genre.items():
            if len(corrections) < min_corrections:
                # Not enough corrections, put them back
                for c in corrections:
                    try:
                        self.collector._queue.put_nowait(c)
                    except Exception:
                        pass
                continue

            # Throttle: don't reflect too frequently for same genre
            now = time.time()
            last = self._last_reflection.get(genre, 0)
            if now - last < 300:  # 5 minutes minimum between reflections
                for c in corrections:
                    try:
                        self.collector._queue.put_nowait(c)
                    except Exception:
                        pass
                continue

            # Run reflection
            logger.info(f"[SOP] Triggering reflection for genre '{genre}' with {len(corrections)} corrections")
            result = self.engine.reflect(genre, corrections)

            if result.confidence >= confidence_threshold and result.proposed_rules:
                # Apply the learned rules
                success = self.sop_config.update_genre_rules(
                    genre, result.proposed_rules, result.confidence, result.reasoning
                )
                if success:
                    logger.info(
                        f"[SOP] ✅ Applied learned rules for '{genre}': "
                        f"confidence={result.confidence:.2f}, "
                        f"rules={list(result.proposed_rules.keys())}"
                    )
                    # Record corrections processed
                    for _ in corrections:
                        self.sop_config.record_correction(genre)
                else:
                    logger.error(f"[SOP] Failed to save learned rules for '{genre}'")
                    # Put corrections back
                    for c in corrections:
                        try:
                            self.collector._queue.put_nowait(c)
                        except Exception:
                            pass
            else:
                logger.info(
                    f"[SOP] Reflection for '{genre}' below threshold "
                    f"(confidence={result.confidence:.2f} < {confidence_threshold}), "
                    f"retaining corrections"
                )
                # Put corrections back for next round
                for c in corrections:
                    try:
                        self.collector._queue.put_nowait(c)
                    except Exception:
                        pass

            self._last_reflection[genre] = now


# ── Global Instance Management ───────────────────────────────────────────────


_sop_config: Optional[SOPConfig] = None
_correction_collector: Optional[CorrectionCollector] = None
_reflection_engine: Optional[ReflectionEngine] = None
_background_thread: Optional[SOPBackgroundThread] = None
_genre_detector: Optional[GenreDetector] = None
_rule_applier: Optional[RuleApplier] = None


def get_sop_config() -> SOPConfig:
    global _sop_config
    if _sop_config is None:
        _sop_config = SOPConfig()
    return _sop_config


def get_correction_collector() -> CorrectionCollector:
    global _correction_collector
    if _correction_collector is None:
        _correction_collector = CorrectionCollector()
    return _correction_collector


def get_reflection_engine(llm_client: Optional[Callable] = None) -> ReflectionEngine:
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = ReflectionEngine(get_sop_config(), llm_client)
    return _reflection_engine


def get_genre_detector() -> GenreDetector:
    global _genre_detector
    if _genre_detector is None:
        _genre_detector = GenreDetector(get_sop_config())
    return _genre_detector


def get_rule_applier() -> RuleApplier:
    global _rule_applier
    if _rule_applier is None:
        _rule_applier = RuleApplier(get_sop_config())
    return _rule_applier


def start_sop_background_thread(
    check_interval: float = 30.0, llm_client: Optional[Callable] = None
) -> SOPBackgroundThread:
    """Start the SOP background reflection thread."""
    global _background_thread
    if _background_thread and _background_thread._thread and _background_thread._thread.is_alive():
        return _background_thread

    _background_thread = SOPBackgroundThread(
        sop_config=get_sop_config(),
        correction_collector=get_correction_collector(),
        reflection_engine=get_reflection_engine(llm_client),
        check_interval=check_interval,
    )
    _background_thread.start()
    return _background_thread


def stop_sop_background_thread() -> None:
    """Stop the SOP background reflection thread."""
    global _background_thread
    if _background_thread:
        _background_thread.stop()
        _background_thread = None


# ── WebSocket Integration Helpers ────────────────────────────────────────────


async def handle_user_correction_websocket(data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle user correction from WebSocket (frontend ParagraphEditor/CharacterManager)."""
    collector = get_correction_collector()
    success = collector.add_correction_dict(data)

    # Cache project genre
    if "genre" in data and "project_id" in data:
        collector.cache_project_genre(data["project_id"], data["genre"])

    return {
        "status": "accepted" if success else "queue_full",
        "queued_count": collector.queue_size(),
    }


def apply_learned_rules_on_import(
    project_id: int, book_meta: BookMeta, analyzed_json: Dict[str, Any]
) -> Dict[str, Any]:
    """Apply learned SOP rules when importing a new novel of same genre."""
    detector = get_genre_detector()
    # First get broad genre from meta
    broad_genre = detector.detect_from_meta(book_meta)
    # Then refine using chapter analysis
    genre = detector.detect_from_chapter_analysis(analyzed_json)
    # If analysis returns default, fall back to broad genre mapping
    if genre == "default":
        genre = broad_genre

    rules = get_sop_config().get_genre_rules(genre)
    confidence = get_sop_config().get_genre_config(genre).get("learning_stats", {}).get("confidence", 0.5)

    return {
        "genre": genre,
        "rules_applied": bool(rules),
        "confidence": confidence,
        "rules": rules,
    }


__all__ = [
    "SOPConfig",
    "CorrectionCollector",
    "UserCorrection",
    "ReflectionEngine",
    "ReflectionResult",
    "GenreDetector",
    "RuleApplier",
    "SOPBackgroundThread",
    "get_sop_config",
    "get_correction_collector",
    "get_reflection_engine",
    "get_genre_detector",
    "get_rule_applier",
    "start_sop_background_thread",
    "stop_sop_background_thread",
    "handle_user_correction_websocket",
    "apply_learned_rules_on_import",
]

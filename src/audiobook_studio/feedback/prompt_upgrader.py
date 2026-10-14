"""
E3 — 提示词自动版本升级引擎

根据差异分析 Agent 提取的 pattern_tags,
自动生成 v{N+1}.j2 版本的 Prompt 模板。
"""

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .processor import AggregateAnalysis

logger = logging.getLogger(__name__)

# ── Pattern → Prompt 修改映射 ─────────────────────────────────────────────

PATTERN_PROMPT_FIXES: Dict[str, str] = {
    "dialogue_attribution": (
        "特别注意：必须准确识别并标注每个段落的对话归属关系。"
        "如果是对话内容，在文本前加上说话人名称用方括号标注，如 '[李明] 你好！'。"
        "不要遗漏任何对话标记。"
    ),
    "emotion_too_mild": (
        "情感表达需要更加鲜明生动。在标注情感时，优先选择强度更明显的描述词。"
        "对于高兴的情感，使用'欣喜'、'激动'而非'平静'；对于悲伤，使用'悲痛'、'感伤'而非'低落'。"
        "情感强度值建议保持在 0.6-1.0 之间。"
    ),
    "emotion_too_strong": (
        "情感表达要适度克制。在标注情感时，避免过度夸张的表达。"
        "对于日常对话，优先使用'平静'、'温和'等中性描述。"
        "情感强度值建议保持在 0.2-0.6 之间。"
    ),
    "emotion_wrong": (
        "请更仔细地分析上下文来推断角色的情感状态。"
        "综合考虑：① 剧情冲突程度 ② 角色间关系 ③ 事件严重性 ④ 角色性格特征。"
        "不要仅凭对话字面意思判断情感。"
    ),
    "speaker_wrong": (
        "说话人识别规则：① 每个段落前先查找对话引导词（'说'、'道'、'问'、'喊'）"
        "② 主语在引导词前，如'张三说'→ 说话人是张三 ③ 如果主语缺失，查看上一段对话的说话人。"
    ),
    "pause_missing": (
        "在需要强调、转折或情感转换的位置添加停顿标记。"
        "① 段落切换时添加 pause_before_ms=500 ② 情感转折处 pause_before_ms=800 "
        "③ 重要陈述前 pause_before_ms=1000。"
    ),
    "pause_too_long": (
        "减少停顿时长，保持叙述流畅。常规段落切换 pause_before_ms=200-300 即可。"
        "仅在章节切换或重大情节转折处使用 pause_before_ms=500+。"
    ),
    "prosody_robotic": (
        "注意语调的抑扬顿挫。在文本编辑时添加适当的语气词、"
        "调整句式结构使其更符合自然口语节奏。避免过于工整的书面句式。"
    ),
    "prosody_flat": (
        "增加语调起伏。使用更丰富的标点符号（问号、感叹号、省略号）来引导语调变化。"
        "对话部分要体现出角色性格特征的语气差异。"
    ),
    "sfx_missing": (
        "场景音效是提升沉浸感的关键。在以下场景必须添加音效标记："
        "① 开门/关门 ② 脚步声 ③ 风雨雷电 ④ 车辆声 ⑤ 电话铃声 ⑥ 背景人群声。"
        "使用 [sfx:类型] 格式标记。"
    ),
    "text_colloquial": (
        "将书面化的表达转换为自然的口语表达。例如："
        "'然而'→'但是'，'因此'→'所以'，'是否'→'是不是'，"
        "'逐一'→'一个一个'。保持语言的自然流畅感。"
    ),
    "text_formal": (
        "适当增加正式感，避免过于随意的表达。例如对话外的叙述部分使用标准书面语，"
        "减少'嘛'、'呗'、'啦'等语气词的过度使用。"
    ),
    "format_issue": (
        "注意输出格式的规范性。必须严格遵守 JSON Schema 定义，"
        "字段名称、类型、嵌套结构完全一致。不要添加额外字段或省略必填字段。"
    ),
    "style_issue": (
        "保持文本风格的统一性。同一作品内用词、语气、格式需前后一致。"
        "避免在同一章节中混用不同风格的表达。"
    ),
    "emotion_mismatch": (
        "情感标注必须与上下文情节匹配。根据剧情冲突、角色关系、事件严重性推断情感。"
        "不要仅凭对话字面意思判断，要结合完整语境。"
    ),
    "pronunciation_fix": (
        "注意生僻字、多音字的正确读音标注。使用拼音或 IPA 标注特殊读音。"
        "人名、地名、专有名词需额外标注读音。"
    ),
    "quality_issue": (
        "合成音频需满足质量基线：无削波、无异常静音、音量适中、时长匹配。"
        "生成前检查文本长度与预估时长是否合理。"
    ),
    "audio_artifact": (
        "避免音频伪影：爆音、电流声、金属音、重影。"
        "如检测到伪影，需在 prompt 中强调清晰度优先。"
    ),
    "speech_rate_issue": (
        "语速需自然适中。叙述部分约 200-240 字/分钟，对话部分根据情感调整。"
        "避免过快导致吞字或过慢显得拖沓。"
    ),
    "low_quality_score": (
        "综合质量评分偏低时，需从韵律、情感、清晰度、完整性多维度排查。"
        "在 prompt 中增加质量自检步骤。"
    ),
    "background_noise": (
        "合成音频不应包含背景噪音。如环境音需添加，请使用显式 [sfx:] 标记。"
        "纯语音合成需保证底噪极低。"
    ),
    "unclear_pronunciation": (
        "发音必须清晰可辨。多音字、歧义词需在文本预处理阶段消歧。"
        "连读、弱读处理要符合自然语流。"
    ),
    "chunk_too_short": (
        "音频片段过短会导致听感破碎。单段合成建议不少于 500 字符。"
        "短文本需合并合成或调整分段策略。"
    ),
    "voice_inconsistency": (
        "同一角色全书音色必须一致。建立角色声纹档案，合成时复用。"
        "不同场景、情感下保持声纹核心特征不变。"
    ),
    "truncated_ending": (
        "合成音频不得截断结尾。需完整播放至句号、问号、感叹号等终止符。"
        "检测到截断时自动重试并延长最大生成长度。"
    ),

}


def _load_current_prompt(stage: str) -> Tuple[Optional[str], int]:
    """加载当前版本的 prompt 模板.

    Returns:
        (content, version_number) or (None, 0) if not found
    """
    prompt_dir = Path("prompts") / stage
    if not prompt_dir.exists():
        logger.warning(f"Prompt directory not found: {prompt_dir}")
        return None, 0

    # Find highest version number
    version = 0
    current_content = None

    for f in prompt_dir.glob("v*.j2"):
        try:
            v = int(f.stem[1:])  # "v1.j2" → 1
            if v > version:
                version = v
                current_content = f.read_text(encoding="utf-8")
        except (ValueError, IndexError):
            continue

    if current_content is None:
        logger.warning(f"No v*.j2 files found in {prompt_dir}")
        return None, 0

    logger.info(f"Loaded prompt v{version} from {stage}/v{version}.j2")
    return current_content, version


def _apply_pattern_fixes(
    content: str,
    pattern_tags: List[str],
    stage: str,
) -> Tuple[str, List[str]]:
    """根据 pattern_tags 在 prompt 中插入修复指令.

    Returns:
        (updated_content, applied_fixes)
    """
    applied: List[str] = []

    for tag in pattern_tags:
        fix_text = PATTERN_PROMPT_FIXES.get(tag)
        if not fix_text:
            continue

        # Check if this fix was already applied
        if fix_text[:40] in content:
            logger.info(f"Pattern '{tag}' fix already in prompt, skipping")
            continue

        applied.append(tag)
        # Actually apply the fix by appending to content
        content = content.rstrip() + f"\n\n# 模式修复 [{tag}]:\n{fix_text}\n"
        logger.info(f"Applying pattern fix '{tag}' to {stage} prompt")

    return content, applied


def _write_new_version(
    stage: str,
    content: str,
    version: int,
    change_log: List[str],
) -> Path:
    """写入新版本的 prompt 模板."""
    prompt_dir = Path("prompts") / stage
    prompt_dir.mkdir(parents=True, exist_ok=True)

    new_version = version + 1
    new_path = prompt_dir / f"v{new_version}.j2"

    # 规范化空白：累积的模式修复块会引入 3+ 连续空行 / 末尾多空行，恰好触发
    # 晋升门 Gate1（格式合规率）的「连续空行」「末尾空行」机械检查 ——
    # 语义无关的排版缺陷，写入前统一收敛为最多一个空行。
    content = re.sub(r"\n{3,}", "\n\n", content.rstrip()) + "\n"

    # Write the new version
    new_path.write_text(content, encoding="utf-8")

    # Write change log
    changelog_path = prompt_dir / "CHANGELOG.md"
    with open(changelog_path, "a", encoding="utf-8") as f:
        from datetime import datetime, timezone

        f.write(f"\n## v{new_version} ({datetime.now(timezone.utc).isoformat()[:10]})\n")
        for change in change_log:
            f.write(f"- {change}\n")

    logger.info(f"New prompt version written: {new_path}")
    return new_path


def upgrade_prompt(
    stage: str,
    pattern_tags: List[str],
    additional_fixes: Optional[List[str]] = None,
) -> Optional[Path]:
    """主入口: 根据 pattern_tags 升级一个 stage 的 prompt.

    Args:
        stage: Pipeline stage name (e.g., "edit_for_tts")
        pattern_tags: List of pattern tags from diff analysis
        additional_fixes: Optional extra instruction text to add

    Returns:
        Path to the new prompt file, or None if no upgrade needed
    """
    content, version = _load_current_prompt(stage)
    if content is None:
        return None

    # Apply pattern-based fixes
    updated_content, applied_fixes = _apply_pattern_fixes(content, pattern_tags, stage)

    # Add additional fixes
    change_log: List[str] = []
    if additional_fixes:
        for fix in additional_fixes:
            if fix[:40] not in updated_content:
                updated_content += f"\n\n# 额外优化指令:\n{fix}\n"
                change_log.append(f"额外优化: {fix[:60]}...")

    if not applied_fixes and not change_log:
        logger.info(f"No upgrades needed for {stage} (no new patterns to apply)")
        return None

    # Log changes
    for tag in applied_fixes:
        desc = PATTERN_PROMPT_FIXES.get(tag, tag)
        change_log.append(f"模式修复 [{tag}]: {desc[:60]}...")

    # Write new version
    new_path = _write_new_version(stage, updated_content, version, change_log)

    logger.info(
        f"Prompt upgrade complete: {stage} v{version} → v{version + 1} " f"({len(applied_fixes)} pattern fixes applied)"
    )
    return new_path


def batch_upgrade(
    analysis_result: "AggregateAnalysis",
    min_pattern_threshold: int = 3,
) -> Dict[str, Path]:
    """根据批量分析结果，自动升级所有需要改进的 Prompt.

    Args:
        analysis_result: 批量差异分析结果
        min_pattern_threshold: 模式出现次数最小值（低于此值不触发升级）

    Returns:
        stage → new_path mapping
    """

    results: Dict[str, Path] = {}

    # Group patterns by stage
    stage_patterns: Dict[str, List[str]] = {}
    for pattern, count in analysis_result.top_patterns:
        if count < min_pattern_threshold:
            continue
        # Map pattern to likely stage
        stage = _map_pattern_to_stage(pattern)
        if stage:
            stage_patterns.setdefault(stage, []).append(pattern)

    # 反馈记录的 stage 是 pipeline 名（edit/annotate/...），stage_instructions 按它归集；
    # stage_patterns 的键是 prompt 目录名（edit_for_tts/...）—— 反查后再取指令。
    _prompt_dir_to_pipeline = {
        "edit_for_tts": "edit",
        "annotate_paragraph": "annotate",
        "quality_judge": "quality",
        "analyze_structure": "analyze",
        "extract": "extract",
        "translate": "translate",
    }

    for stage, patterns in stage_patterns.items():
        instructions = (getattr(analysis_result, "stage_instructions", None) or {}).get(
            _prompt_dir_to_pipeline.get(stage, stage), []
        )
        # 每轮最多 3 条 LLM 指令进入候选：prompt 无界膨胀会稀释注意力，
        # 且 Gate3 会实证检验其净效果（劣化即拒），保持小步快跑。
        extra = [f"{stage}: {instr}" if not instr.startswith(stage) else instr for instr in instructions[:3]]
        new_path = upgrade_prompt(stage, patterns, additional_fixes=extra or None)
        if new_path:
            results[stage] = new_path

    return results


def _map_pattern_to_stage(pattern: str) -> Optional[str]:
    """将 pattern_tag 映射到最可能所属的 pipeline stage."""
    # Edit patterns
    if pattern in (
        "dialogue_attribution",
        "emotion_too_mild",
        "emotion_too_strong",
        "emotion_wrong",
        "speaker_wrong",
        "pause_missing",
        "pause_too_long",
        "sfx_missing",
        "sfx_wrong",
        "text_colloquial",
        "text_formal",
        "style_issue",
        "pronunciation_fix",
        "speech_rate_issue",
        "unclear_pronunciation",
    ):
        return "edit_for_tts"
    # Quality patterns
    if pattern in (
        "clipping",
        "silence",
        "low_volume",
        "duration_mismatch",
        "prosody_robotic",
        "prosody_flat",
        "quality_issue",
        "audio_artifact",
        "low_quality_score",
        "background_noise",
        "chunk_too_short",
        "voice_inconsistency",
        "truncated_ending",
    ):
        return "quality_judge"
    # Structure patterns
    if pattern in ("chapter_split_wrong", "character_missing", "summary_incomplete", "format_issue"):
        return "analyze_structure"
    # Annotation patterns
    if pattern in ("emotion_too_mild", "emotion_too_strong", "emotion_wrong", "emotion_mismatch"):
        return "annotate_paragraph"

    return None


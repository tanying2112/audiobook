"""Reviewer Agent Pipeline — Module 4.1: 质量门禁.

Runs between audio_postprocess and synthesize stages.
Checks annotations for:
1. Missing character voice bindings
2. JSON truncation in annotation fields
3. Tag logic consistency (emotion/speed/sfx vs text)

Auto-rejects and emits fix commands for Developer Agent.
Terminal shows interception/retry logs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from ..schemas.review import (
    ReviewerInput,
    ReviewerJudgment,
    VoiceBindingCheck,
    JsonTruncationCheck,
    TagConsistencyCheck,
    FixCommand,
)

logger = logging.getLogger(__name__)


class ReviewerAgent:
    """Reviewer Agent — independent quality gate before synthesis.

    This agent reviews paragraph annotations from audio_postprocess stage
    and either passes them to synthesize or rejects with fix commands.
    """

    def __init__(
        self,
        mock_mode: Optional[bool] = None,
        strict_mode: bool = True,
    ):
        """Initialize Reviewer Agent.

        Args:
            mock_mode: If True, uses mock review (for testing). Defaults to MOCK_LLM env.
            strict_mode: If True, treats warnings as blocking issues.
        """
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"

        self.strict_mode = strict_mode

        # Valid emotion labels from schema
        self.valid_emotions = {
            "neutral", "happy", "sad", "angry", "fearful", "surprised", "disgusted",
            "tense", "tender", "contemplative", "whisper", "cold_laugh", "sigh", "sarcastic"
        }

        # Valid speed range
        self.speed_min = 0.5
        self.speed_max = 2.0

        logger.info(f"ReviewerAgent initialized (mock_mode={self.mock_mode}, strict={self.strict_mode})")

    def _load_voice_map(self, character_voice_map: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Build lookup map from character_voice_map."""
        voice_map = {}
        for char in character_voice_map:
            canonical = char.get("canonical_name")
            if canonical:
                voice_map[canonical] = char
        return voice_map

    def check_voice_bindings(
        self,
        paragraphs: List[Dict[str, Any]],
        voice_map: Dict[str, Dict[str, Any]],
    ) -> List[VoiceBindingCheck]:
        """Check all speakers have valid voice bindings."""
        checks = []
        seen_speakers = set()

        for para in paragraphs:
            speaker = para.get("speaker_canonical_name") or para.get("speaker")
            if not speaker:
                continue

            if speaker in seen_speakers:
                continue
            seen_speakers.add(speaker)

            if speaker in voice_map:
                char_info = voice_map[speaker]
                checks.append(VoiceBindingCheck(
                    speaker_canonical_name=speaker,
                    found_in_voice_map=True,
                    suggested_voice_id=char_info.get("suggested_voice_id"),
                ))
            else:
                # Check if it's the default narrator
                if speaker == "_narrator_":
                    checks.append(VoiceBindingCheck(
                        speaker_canonical_name=speaker,
                        found_in_voice_map=True,
                        suggested_voice_id="zh-CN-XiaoxiaoNeural",
                    ))
                else:
                    checks.append(VoiceBindingCheck(
                        speaker_canonical_name=speaker,
                        found_in_voice_map=False,
                        issue=f"Speaker '{speaker}' not found in character_voice_map",
                        severity="error",
                    ))

        return checks

    def check_json_truncation(
        self,
        paragraphs: List[Dict[str, Any]],
    ) -> List[JsonTruncationCheck]:
        """Check for JSON truncation in annotation fields.

        Looks for:
        - Fields ending with '...' or '...' (truncation markers)
        - Fields with incomplete JSON structures
        - Missing required fields
        """
        checks = []
        required_fields = {
            "speaker_canonical_name": str,
            "is_dialogue": bool,
            "emotion": str,
            "emotion_intensity": float,
            "speech_rate": float,
            "pitch_shift_semitones": int,
            "needs_sfx": bool,
            "sfx_tags": list,
            "pause_before_ms": int,
            "pause_after_ms": int,
            "confidence": float,
        }

        for i, para in enumerate(paragraphs):
            para_idx = para.get("paragraph_index", i)

            for field_name, expected_type in required_fields.items():
                value = para.get(field_name)

                is_truncated = False
                issue = None

                if value is None:
                    is_truncated = True
                    issue = f"Required field '{field_name}' is missing"
                elif isinstance(value, str):
                    # Check for truncation markers
                    if value.endswith("...") or value.endswith("……") or len(value) > 10000:
                        is_truncated = True
                        issue = f"Field '{field_name}' appears truncated (ends with ... or too long)"
                    # Check for incomplete JSON-like structures
                    elif value.strip().startswith("{") and not value.strip().endswith("}"):
                        is_truncated = True
                        issue = f"Field '{field_name}' has incomplete JSON structure"
                    elif value.strip().startswith("[") and not value.strip().endswith("]"):
                        is_truncated = True
                        issue = f"Field '{field_name}' has incomplete JSON array"
                elif isinstance(value, (list, dict)):
                    # Check if we can serialize/deserialize properly
                    try:
                        json.dumps(value)
                    except (TypeError, ValueError) as e:
                        is_truncated = True
                        issue = f"Field '{field_name}' contains non-serializable data: {e}"

                checks.append(JsonTruncationCheck(
                    paragraph_index=para_idx,
                    field_name=field_name,
                    is_truncated=is_truncated,
                    expected_type=expected_type.__name__,
                    actual_value=str(value)[:100] if value is not None else None,
                    issue=issue,
                    severity="error" if is_truncated else "warning",
                ))

        return checks

    def check_tag_consistency(
        self,
        paragraphs: List[Dict[str, Any]],
        scene_tags: List[str],
    ) -> List[TagConsistencyCheck]:
        """Check tag logic consistency.

        Validates:
        1. emotion matches text content (dialogue vs narration)
        2. speed is in valid range
        3. sfx_tags are from allowed scene_tags
        4. pause timing is logical
        """
        checks = []

        for para in paragraphs:
            para_idx = para.get("paragraph_index", 0)
            text = para.get("text", "")
            emotion = para.get("emotion", "neutral")
            speech_rate = para.get("speech_rate", 1.0)
            pitch_shift = para.get("pitch_shift_semitones", 0)
            needs_sfx = para.get("needs_sfx", False)
            sfx_tags = para.get("sfx_tags", [])
            pause_before = para.get("pause_before_ms", 0)
            pause_after = para.get("pause_after_ms", 0)
            is_dialogue = para.get("is_dialogue", False)

            # 1. Emotion-text consistency
            emotion_passed = emotion in self.valid_emotions
            if not emotion_passed:
                checks.append(TagConsistencyCheck(
                    paragraph_index=para_idx,
                    check_type="emotion_text_match",
                    passed=False,
                    expected=f"one of {sorted(self.valid_emotions)}",
                    actual=emotion,
                    issue=f"Invalid emotion label: '{emotion}'",
                    severity="error",
                ))
            else:
                # Check if emotion fits dialogue/narration context
                if is_dialogue and emotion in ["neutral", "contemplative"] and "？" in text:
                    checks.append(TagConsistencyCheck(
                        paragraph_index=para_idx,
                        check_type="emotion_text_match",
                        passed=False,
                        expected="questioning emotion (surprised, tense)",
                        actual=emotion,
                        issue=f"Dialogue with question mark but emotion is '{emotion}'",
                        severity="warning",
                    ))

            # 2. Speed range check
            if not (self.speed_min <= speech_rate <= self.speed_max):
                checks.append(TagConsistencyCheck(
                    paragraph_index=para_idx,
                    check_type="speed_range",
                    passed=False,
                    expected=f"[{self.speed_min}, {self.speed_max}]",
                    actual=f"{speech_rate}",
                    issue=f"Speech rate {speech_rate} outside valid range",
                    severity="error",
                ))
            else:
                checks.append(TagConsistencyCheck(
                    paragraph_index=para_idx,
                    check_type="speed_range",
                    passed=True,
                ))

            # 3. SFX tag validation
            if needs_sfx:
                for tag in sfx_tags:
                    if tag not in scene_tags:
                        checks.append(TagConsistencyCheck(
                            paragraph_index=para_idx,
                            check_type="sfx_context",
                            passed=False,
                            expected=f"one of {scene_tags}",
                            actual=tag,
                            issue=f"SFX tag '{tag}' not in allowed scene_tags",
                            severity="warning",
                        ))
                    else:
                        checks.append(TagConsistencyCheck(
                            paragraph_index=para_idx,
                            check_type="sfx_context",
                            passed=True,
                        ))

            # 4. Pause logic
            if pause_before < 0 or pause_before > 5000:
                checks.append(TagConsistencyCheck(
                    paragraph_index=para_idx,
                    check_type="pause_logic",
                    passed=False,
                    expected="0-5000ms",
                    actual=f"{pause_before}ms",
                    issue=f"Pause before {pause_before}ms is unrealistic",
                    severity="warning",
                ))
            else:
                checks.append(TagConsistencyCheck(
                    paragraph_index=para_idx,
                    check_type="pause_logic",
                    passed=True,
                ))

            if pause_after < 0 or pause_after > 5000:
                checks.append(TagConsistencyCheck(
                    paragraph_index=para_idx,
                    check_type="pause_logic",
                    passed=False,
                    expected="0-5000ms",
                    actual=f"{pause_after}ms",
                    issue=f"Pause after {pause_after}ms is unrealistic",
                    severity="warning",
                ))
            else:
                checks.append(TagConsistencyCheck(
                    paragraph_index=para_idx,
                    check_type="pause_logic",
                    passed=True,
                ))

            # 5. Pitch shift range (-12 to +12 semitones typical)
            if not (-24 <= pitch_shift <= 24):
                checks.append(TagConsistencyCheck(
                    paragraph_index=para_idx,
                    check_type="speed_range",  # reuse category
                    passed=False,
                    expected="[-24, +24] semitones",
                    actual=f"{pitch_shift}",
                    issue=f"Pitch shift {pitch_shift} semitones is extreme",
                    severity="warning",
                ))

        return checks

    def generate_fix_commands(
        self,
        voice_checks: List[VoiceBindingCheck],
        truncation_checks: List[JsonTruncationCheck],
        tag_checks: List[TagConsistencyCheck],
        paragraphs: List[Dict[str, Any]],
    ) -> List[FixCommand]:
        """Generate auto-fix commands for Developer Agent."""
        commands = []

        # Fix missing voice bindings
        for check in voice_checks:
            if not check.found_in_voice_map and check.severity == "error":
                commands.append(FixCommand(
                    command_type="add_voice_binding",
                    target_paragraph_index=-1,  # Chapter-level fix
                    parameters={
                        "canonical_name": check.speaker_canonical_name,
                        "action": "add_to_voice_map",
                        "suggested_voice_id": self._suggest_voice_id(check.speaker_canonical_name),
                    },
                    priority=10,
                    rationale=f"Speaker '{check.speaker_canonical_name}' missing from character_voice_map",
                ))

        # Fix truncated fields
        for check in truncation_checks:
            if check.is_truncated and check.severity == "error":
                commands.append(FixCommand(
                    command_type="fix_truncated_field",
                    target_paragraph_index=check.paragraph_index,
                    parameters={
                        "field_name": check.field_name,
                        "action": "re_extract_or_default",
                    },
                    priority=9,
                    rationale=f"Field '{check.field_name}' in paragraph {check.paragraph_index} is truncated: {check.issue}",
                ))

        # Fix tag inconsistencies
        for check in tag_checks:
            if not check.passed and (check.severity == "error" or check.check_type == "pause_logic"):
                if check.check_type == "emotion_text_match":
                    # paragraph_index is 1-based in checks, but paragraphs list is 0-based
                    para_idx = check.paragraph_index - 1 if check.paragraph_index > 0 else 0
                    commands.append(FixCommand(
                        command_type="correct_emotion_tag",
                        target_paragraph_index=check.paragraph_index,
                        parameters={
                            "current_emotion": check.actual,
                            "suggested_emotion": self._suggest_emotion_from_text(
                                paragraphs[para_idx].get("text", "") if para_idx < len(paragraphs) else ""
                            ),
                        },
                        priority=7,
                        rationale=f"Emotion tag mismatch: {check.issue}",
                    ))
                elif check.check_type == "speed_range":
                    commands.append(FixCommand(
                        command_type="adjust_speed",
                        target_paragraph_index=check.paragraph_index,
                        parameters={
                            "current_speed": check.actual,
                            "clamped_speed": max(self.speed_min, min(self.speed_max, float(check.actual) if check.actual else 1.0)),
                        },
                        priority=6,
                        rationale=f"Speech rate out of range: {check.issue}",
                    ))
                elif check.check_type == "sfx_context":
                    commands.append(FixCommand(
                        command_type="add_sfx_tag",
                        target_paragraph_index=check.paragraph_index,
                        parameters={
                            "invalid_tag": check.actual,
                            "action": "remove_or_replace",
                            "allowed_tags": check.expected,
                        },
                        priority=5,
                        rationale=f"Invalid SFX tag: {check.issue}",
                    ))
                elif check.check_type == "pause_logic":
                    # pause_logic checks have severity="warning" but we still generate fix commands
                    val = check.actual.replace("ms", "") if "ms" in str(check.actual) else check.actual
                    commands.append(FixCommand(
                        command_type="fix_pause_timing",
                        target_paragraph_index=check.paragraph_index,
                        parameters={
                            "field": "pause_before_ms" if "before" in (check.issue or "") else "pause_after_ms",
                            "current_value": check.actual,
                            "clamped_value": max(0, min(5000, int(val) if val else 300)),
                        },
                        priority=4,
                        rationale=f"Unrealistic pause timing: {check.issue}",
                    ))

        return commands

    def _suggest_voice_id(self, speaker_name: str) -> str:
        """Suggest a voice ID based on speaker name."""
        name_lower = speaker_name.lower()
        if "旁白" in speaker_name or "narrator" in name_lower or "_narrator_" in name_lower:
            return "zh-CN-XiaoxiaoNeural"
        elif any(kw in name_lower for kw in ["女", "female", "小姐", "夫人", "公主", "姑娘"]):
            return "zh-CN-XiaoyiNeural"
        elif any(kw in name_lower for kw in ["男", "male", "先生", "大哥", "老", "爷"]):
            return "zh-CN-YunxiNeural"
        elif any(kw in name_lower for kw in ["童", "child", "小", "孩"]):
            return "zh-CN-XiaoxiaoNeural"
        else:
            return "zh-CN-YunjianNeural"  # Default neutral

    def _suggest_emotion_from_text(self, text: str) -> str:
        """Heuristic emotion suggestion from text content."""
        if not text:
            return "neutral"

        # Question marks -> surprised/tense
        if "？" in text or "?" in text:
            return "surprised"

        # Exclamation marks -> happy/angry/excited
        if "！" in text or "!" in text:
            if any(w in text for w in ["怒", "恨", "气", "恼", "可恶"]):
                return "angry"
            return "happy"

        # Sad keywords
        if any(w in text for w in ["悲", "伤", "泪", "哭", "愁", "痛", "心碎"]):
            return "sad"

        # Fear keywords
        if any(w in text for w in ["怕", "恐", "惧", "惊", "吓", "颤", "抖"]):
            return "fearful"

        # Whisper indicators
        if any(w in text for w in ["悄", "低声", "耳语", "嘘"]):
            return "whisper"

        return "neutral"

    def run(self, input_data: ReviewerInput) -> ReviewerJudgment:
        """Execute the review process.

        Args:
            input_data: ReviewerInput with paragraphs, voice_map, etc.

        Returns:
            ReviewerJudgment with check results and fix commands.
        """
        logger.info(f"ReviewerAgent: Reviewing chapter {input_data.chapter_index} of project {input_data.project_id}")

        if self.mock_mode:
            return self._mock_review(input_data)

        # Build voice map lookup
        voice_map = self._load_voice_map(input_data.character_voice_map)

        # Run all checks
        voice_checks = self.check_voice_bindings(input_data.paragraphs, voice_map)
        truncation_checks = self.check_json_truncation(input_data.paragraphs)
        tag_checks = self.check_tag_consistency(input_data.paragraphs, input_data.scene_tags)

        # Create judgment
        judgment = ReviewerJudgment(
            project_id=input_data.project_id,
            chapter_index=input_data.chapter_index,
        )

        # Add check results
        judgment.voice_binding_checks = voice_checks
        judgment.json_truncation_checks = truncation_checks
        judgment.tag_consistency_checks = tag_checks

        # Evaluate overall
        for check in voice_checks:
            if not check.found_in_voice_map and check.severity == "error":
                judgment.add_blocking_issue(check.issue or f"Missing voice binding for {check.speaker_canonical_name}")
            elif check.severity == "warning":
                judgment.add_warning(check.issue or f"Voice binding warning for {check.speaker_canonical_name}")

        for check in truncation_checks:
            if check.is_truncated:
                if check.severity == "error":
                    judgment.add_blocking_issue(check.issue or f"Truncated field {check.field_name} in para {check.paragraph_index}")
                else:
                    judgment.add_warning(check.issue or f"Truncation warning in {check.field_name}")

        for check in tag_checks:
            if not check.passed:
                if check.severity == "error" or (check.severity == "warning" and self.strict_mode):
                    judgment.add_blocking_issue(check.issue or f"Tag check failed: {check.check_type} para {check.paragraph_index}")
                else:
                    judgment.add_warning(check.issue or f"Tag warning: {check.check_type} para {check.paragraph_index}")

        # Generate fix commands if there are issues
        if not judgment.overall_passed:
            fix_commands = self.generate_fix_commands(
                voice_checks, truncation_checks, tag_checks, input_data.paragraphs
            )
            for cmd in fix_commands:
                judgment.add_fix_command(cmd)

        # Log summary
        logger.info(
            f"ReviewerAgent result: passed={judgment.overall_passed}, "
            f"blocking={judgment.blocking_issues}, warnings={judgment.warning_issues}, "
            f"fix_commands={len(judgment.fix_commands)}"
        )

        if judgment.fix_commands:
            for cmd in judgment.fix_commands:
                logger.warning(
                    f"  [FIX CMD] {cmd.command_type} para={cmd.target_paragraph_index} "
                    f"priority={cmd.priority}: {cmd.rationale}"
                )

        if not judgment.summary and judgment.overall_passed:
            judgment.summary = "All checks passed"

        return judgment

    def _mock_review(self, input_data: ReviewerInput) -> ReviewerJudgment:
        """Mock review for testing."""
        judgment = ReviewerJudgment(
            project_id=input_data.project_id,
            chapter_index=input_data.chapter_index,
            overall_passed=True,
            summary="Mock review passed",
        )
        return judgment


def review_annotations(
    project_id: int,
    chapter_index: int,
    paragraphs: List[Dict[str, Any]],
    character_voice_map: List[Dict[str, Any]],
    scene_tags: List[str],
    book_meta: Optional[Dict[str, Any]] = None,
    mock_mode: bool = True,
) -> ReviewerJudgment:
    """Convenience function to run review."""
    input_data = ReviewerInput(
        project_id=project_id,
        chapter_index=chapter_index,
        paragraphs=paragraphs,
        character_voice_map=character_voice_map,
        scene_tags=scene_tags,
        book_meta=book_meta,
    )
    agent = ReviewerAgent(mock_mode=mock_mode)
    return agent.run(input_data)


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)

    # Quick self-test
    test_paragraphs = [
        {
            "paragraph_index": 1,
            "text": "贾雨村冷笑道：“何必多言？”",
            "speaker_canonical_name": "贾雨村",
            "is_dialogue": True,
            "emotion": "cold_laugh",
            "emotion_intensity": 0.8,
            "speech_rate": 1.1,
            "pitch_shift_semitones": -2,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.95,
        },
        {
            "paragraph_index": 2,
            "text": "这是一段旁白描述，没有对话。",
            "speaker_canonical_name": "_narrator_",
            "is_dialogue": False,
            "emotion": "neutral",
            "emotion_intensity": 0.5,
            "speech_rate": 1.0,
            "pitch_shift_semitones": 0,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.9,
        },
    ]

    test_voice_map = [
        {
            "canonical_name": "_narrator_",
            "suggested_voice_id": "zh-CN-XiaoxiaoNeural",
        },
        # Missing 贾雨村 - should trigger error
    ]

    result = review_annotations(
        project_id=1,
        chapter_index=1,
        paragraphs=test_paragraphs,
        character_voice_map=test_voice_map,
        scene_tags=[],
        mock_mode=False,
    )

    print(f"\n=== Reviewer Judgment ===")
    print(f"Overall Passed: {result.overall_passed}")
    print(f"Blocking Issues: {result.blocking_issues}")
    print(f"Warnings: {result.warning_issues}")
    print(f"Summary: {result.summary}")
    print(f"Fix Commands: {len(result.fix_commands)}")
    for cmd in result.fix_commands:
        print(f"  - {cmd.command_type} para={cmd.target_paragraph_index}: {cmd.rationale}")

    sys.exit(0 if result.overall_passed else 1)
"""Reviewer Agent Schema — 质量门禁契约 (Module 4.1).

Reviewer Agent runs between audio_postprocess and synthesize stages.
Checks:
1. Missing character voice bindings (speaker_canonical_name not in character_voice_map)
2. JSON truncation in annotations (incomplete ParagraphAnnotation fields)
3. Tag logic consistency (emotion/speed/sfx tags vs text content)

Auto-rejects bad annotations and emits fix commands for Developer Agent.
"""

from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class VoiceBindingCheck(BaseModel):
    """Check result for character voice binding."""
    speaker_canonical_name: str
    found_in_voice_map: bool
    suggested_voice_id: Optional[str] = None
    issue: Optional[str] = None
    severity: Literal["error", "warning"] = "error"


class JsonTruncationCheck(BaseModel):
    """Check result for JSON truncation in annotations."""
    paragraph_index: int
    field_name: str
    is_truncated: bool
    expected_type: str
    actual_value: Optional[str] = None
    issue: Optional[str] = None
    severity: Literal["error", "warning"] = "error"


class TagConsistencyCheck(BaseModel):
    """Check result for tag logic consistency."""
    paragraph_index: int
    check_type: Literal["emotion_text_match", "speed_range", "sfx_context", "pause_logic"]
    passed: bool
    expected: Optional[str] = None
    actual: Optional[str] = None
    issue: Optional[str] = None
    severity: Literal["error", "warning"] = "warning"


class FixCommand(BaseModel):
    """Auto-fix command for Developer Agent to execute."""
    command_type: Literal[
        "add_voice_binding",
        "fix_truncated_field",
        "correct_emotion_tag",
        "adjust_speed",
        "add_sfx_tag",
        "fix_pause_timing",
        "re_annotate_paragraph"
    ]
    target_paragraph_index: int
    parameters: Dict[str, Any]
    priority: int = Field(default=1, ge=1, le=10)
    rationale: str


class ReviewerJudgment(BaseModel):
    """Reviewer Agent output — quality gate decision."""

    project_id: int
    chapter_index: int
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)

    # Check results
    voice_binding_checks: List[VoiceBindingCheck] = Field(default_factory=list)
    json_truncation_checks: List[JsonTruncationCheck] = Field(default_factory=list)
    tag_consistency_checks: List[TagConsistencyCheck] = Field(default_factory=list)

    # Auto-fix commands for Developer Agent
    fix_commands: List[FixCommand] = Field(default_factory=list)

    # Overall decision
    overall_passed: bool = True
    blocking_issues: int = 0
    warning_issues: int = 0

    # Summary for logging
    summary: str = ""

    def add_blocking_issue(self, issue: str) -> None:
        """Add a blocking issue and mark overall as failed."""
        self.blocking_issues += 1
        self.overall_passed = False
        if self.summary:
            self.summary += f"; {issue}"
        else:
            self.summary = issue

    def add_warning(self, issue: str) -> None:
        """Add a warning issue."""
        self.warning_issues += 1
        if self.summary:
            self.summary += f"; [WARN] {issue}"
        else:
            self.summary = f"[WARN] {issue}"

    def add_fix_command(self, command: FixCommand) -> None:
        """Add a fix command for Developer Agent."""
        self.fix_commands.append(command)


class ReviewerInput(BaseModel):
    """Input to Reviewer Agent."""

    project_id: int
    chapter_index: int
    paragraphs: List[Dict[str, Any]]  # Paragraph annotations from audio_postprocess
    character_voice_map: List[Dict[str, Any]]  # From BookAnalysisOutput
    scene_tags: List[str] = Field(default_factory=list)  # Available SFX tags
    book_meta: Optional[Dict[str, Any]] = None  # BookMeta for context
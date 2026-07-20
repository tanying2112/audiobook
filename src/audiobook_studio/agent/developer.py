"""Developer Agent — 执行 Reviewer Agent 下发的 FixCommands.

Closes the quality gate loop:
ReviewerAgent -> FixCommands -> DeveloperAgent -> 修正后的段落 -> 重新 Review

This agent applies structured fix commands to paragraph annotations and
re-runs the affected pipeline stages.
"""

from __future__ import annotations

import logging
from typing import Any

from ..schemas.review import FixCommand, ReviewerInput, ReviewerJudgment

logger = logging.getLogger(__name__)


class DeveloperAgent:
    """Developer Agent — applies fix commands to pipeline annotations.

    This agent takes FixCommands from the ReviewerAgent and mutates
    paragraph annotations accordingly, then triggers re-processing
    of affected stages.
    """

    def __init__(self, mock_mode: bool = False):
        """Initialize Developer Agent.

        Args:
            mock_mode: If True, simulates fixes without running pipelines.
        """
        self.mock_mode = mock_mode
        logger.info(f"DeveloperAgent initialized (mock_mode={mock_mode})")

    def apply_fix_commands(
        self,
        paragraphs: list[dict[str, Any]],
        fix_commands: list[FixCommand],
    ) -> list[dict[str, Any]]:
        """Apply fix commands to paragraph annotations.

        Args:
            paragraphs: List of paragraph annotation dicts
            fix_commands: List of FixCommand from ReviewerJudgment

        Returns:
            Updated list of paragraph annotations
        """
        logger.info(f"DeveloperAgent: Applying {len(fix_commands)} fix commands")

        # Deep copy to avoid mutating originals
        fixed = [dict(p) for p in paragraphs]

        # Sort by priority (higher first)
        sorted_commands = sorted(fix_commands, key=lambda c: -c.priority)

        for cmd in sorted_commands:
            try:
                self._apply_single_command(fixed, cmd)
                logger.debug(f"Applied fix: {cmd.command_type} para={cmd.target_paragraph_index}")
            except Exception as e:
                logger.error(f"Failed to apply fix {cmd.command_type}: {e}")

        return fixed

    def _apply_single_command(
        self,
        paragraphs: list[dict[str, Any]],
        cmd: FixCommand,
    ) -> None:
        """Apply a single fix command."""
        para_idx = cmd.target_paragraph_index
        params = cmd.parameters

        if cmd.command_type == "add_voice_binding":
            # Voice binding is chapter-level, handled externally
            # This command just signals the voice map needs update
            logger.info(f"Voice binding fix requested for {params.get('canonical_name')}")
            # We add a marker so the calling code knows to update the voice map
            if "_voice_map_updates" not in paragraphs[0] if paragraphs else {}:
                for p in paragraphs:
                    p["_voice_map_updates"] = []
            # Find or create voice map updates list
            for p in paragraphs:
                if "_voice_map_updates" not in p:
                    p["_voice_map_updates"] = []
            paragraphs[0]["_voice_map_updates"].append(params)

        elif cmd.command_type == "fix_truncated_field":
            field_name = params.get("field_name")
            action = params.get("action", "re_extract_or_default")

            if 0 <= para_idx < len(paragraphs):
                # Apply default based on field type
                default_value = self._get_field_default(field_name)
                paragraphs[para_idx][field_name] = default_value
                logger.info(f"Fixed truncated field '{field_name}' in para {para_idx} with default: {default_value}")

        elif cmd.command_type == "correct_emotion_tag":
            current = params.get("current_emotion")
            suggested = params.get("suggested_emotion")

            if 0 <= para_idx < len(paragraphs):
                paragraphs[para_idx]["emotion"] = suggested
                logger.info(f"Corrected emotion: {current} -> {suggested} (para {para_idx})")

        elif cmd.command_type == "adjust_speed":
            current = params.get("current_speed")
            clamped = params.get("clamped_speed")

            if 0 <= para_idx < len(paragraphs):
                paragraphs[para_idx]["speech_rate"] = clamped
                logger.info(f"Adjusted speed: {current} -> {clamped} (para {para_idx})")

        elif cmd.command_type == "add_sfx_tag":
            invalid = params.get("invalid_tag")
            action = params.get("action", "remove_or_replace")
            allowed = params.get("allowed_tags", [])

            if 0 <= para_idx < len(paragraphs):
                sfx_tags = paragraphs[para_idx].get("sfx_tags", [])
                if invalid in sfx_tags:
                    sfx_tags.remove(invalid)
                    # Optionally add first allowed tag as replacement
                    if allowed and action == "remove_or_replace":
                        sfx_tags.append(allowed[0])
                    paragraphs[para_idx]["sfx_tags"] = sfx_tags
                    paragraphs[para_idx]["needs_sfx"] = len(sfx_tags) > 0
                    logger.info(f"Fixed SFX tags in para {para_idx}: removed '{invalid}'")

        elif cmd.command_type == "fix_pause_timing":
            field = params.get("field")  # "pause_before_ms" or "pause_after_ms"
            current = params.get("current_value")
            clamped = params.get("clamped_value")

            if 0 <= para_idx < len(paragraphs):
                paragraphs[para_idx][field] = clamped
                logger.info(f"Fixed {field}: {current} -> {clamped} (para {para_idx})")

        elif cmd.command_type == "re_annotate_paragraph":
            # Trigger full re-annotation for this paragraph
            if 0 <= para_idx < len(paragraphs):
                paragraphs[para_idx]["_needs_reannotation"] = True
                logger.info(f"Marked paragraph {para_idx} for re-annotation")

        else:
            logger.warning(f"Unknown fix command type: {cmd.command_type}")

    def _get_field_default(self, field_name: str) -> Any:
        """Get sensible default for a paragraph field."""
        defaults = {
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
            "confidence": 0.8,
        }
        return defaults.get(field_name, None)

    async def run_reannotation(
        self,
        project_id: int,
        chapter_index: int,
        paragraph_indices: list[int],
    ) -> dict[str, Any]:
        """Run re-annotation for specific paragraphs.

        Delegates to the annotate pipeline.
        """
        if self.mock_mode:
            return {"status": "mock", "reannotated": paragraph_indices}

        from ..pipeline.annotate import annotate_chapter
        from ..storage import get_db_session

        db = get_db_session()
        try:
            # Run full chapter re-annotation
            result = await annotate_chapter(
                project_id=project_id,
                chapter_index=chapter_index,
                style="detailed",
            )
            return {"status": "ok", "reannotated": paragraph_indices, "result": result}
        finally:
            db.close()

    def create_fixed_reviewer_input(
        self,
        original_input: ReviewerInput,
        fixed_paragraphs: list[dict[str, Any]],
        voice_map_updates: list[dict[str, Any]] | None = None,
    ) -> ReviewerInput:
        """Create updated ReviewerInput with fixes applied.

        Args:
            original_input: Original ReviewerInput
            fixed_paragraphs: Paragraphs with fixes applied
            voice_map_updates: Updates to character_voice_map from add_voice_binding commands

        Returns:
            Updated ReviewerInput ready for re-review
        """
        new_voice_map = list(original_input.character_voice_map)

        if voice_map_updates:
            for update in voice_map_updates:
                canonical = update.get("canonical_name")
                # Check if already exists
                exists = any(c.get("canonical_name") == canonical for c in new_voice_map)
                if not exists:
                    new_voice_map.append(
                        {
                            "canonical_name": canonical,
                            "suggested_voice_id": update.get("suggested_voice_id"),
                            "aliases": update.get("aliases", []),
                            "gender": update.get("gender", "neutral"),
                            "age_range": update.get("age_range", "adult"),
                            "sample_quote": update.get("sample_quote", ""),
                        }
                    )

        return ReviewerInput(
            project_id=original_input.project_id,
            chapter_index=original_input.chapter_index,
            paragraphs=fixed_paragraphs,
            character_voice_map=new_voice_map,
            scene_tags=original_input.scene_tags,
            book_meta=original_input.book_meta,
        )


# Convenience function for orchestrator integration
async def apply_fixes_and_rerun(
    project_id: int,
    chapter_index: int,
    paragraphs: list[dict[str, Any]],
    fix_commands: list[FixCommand],
    character_voice_map: list[dict[str, Any]],
    scene_tags: list[str],
    book_meta: dict[str, Any] | None,
    mock_mode: bool = False,
) -> ReviewerJudgment:
    """Apply fixes and run reviewer again (closed loop).

    This is the main entry point for the review-developer-review cycle.
    """
    developer = DeveloperAgent(mock_mode=mock_mode)

    # Apply fixes
    fixed_paragraphs = developer.apply_fix_commands(paragraphs, fix_commands)

    # Extract voice map updates
    voice_map_updates = []
    for p in fixed_paragraphs:
        if "_voice_map_updates" in p:
            voice_map_updates.extend(p["_voice_map_updates"])

    # Create updated input
    original_input = ReviewerInput(
        project_id=project_id,
        chapter_index=chapter_index,
        paragraphs=paragraphs,
        character_voice_map=character_voice_map,
        scene_tags=scene_tags,
        book_meta=book_meta,
    )
    new_input = developer.create_fixed_reviewer_input(original_input, fixed_paragraphs, voice_map_updates)

    # Re-run review
    from ..pipeline.review import ReviewerAgent

    reviewer = ReviewerAgent(mock_mode=mock_mode)
    new_judgment = reviewer.run(new_input)

    return new_judgment

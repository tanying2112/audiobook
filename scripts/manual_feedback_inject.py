#!/usr/bin/env python3
"""Manual Feedback Injection Script for Self-Iteration Loop Testing.

This script injects 10 feedback records for a specific project and triggers
the self-iteration loop to verify prompt upgrade and A/B testing.

Usage:
    python scripts/manual_feedback_inject.py --project-id 1 --count 10
"""

#!/usr/bin/env python3
"""Manual Feedback Injection Script for Self-Iteration Loop Testing.

This script injects 10 feedback records for a specific project and triggers
the self-iteration loop to verify prompt upgrade and A/B testing.

Usage:
    python scripts/manual_feedback_inject.py --project-id 1 --count 10
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def inject_test_feedback(project_id: int, count: int = 10) -> list[str]:
    """Inject test feedback records for self-iteration testing."""
    from src.audiobook_studio.database import Base
    from src.audiobook_studio.feedback.collector import capture_feedback
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Create session factory with correct database path
    db_path = Path(__file__).parent.parent / "audiobook_studio.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    injected_ids = []

    # Pattern types for testing
    patterns = [
        ("emotion_mismatch", "neutral", "happy", "Fixed emotion from neutral to happy for dialogue"),
        ("speaker_wrong", "narrator", "male_1", "Corrected speaker for dialogue"),
        ("prosody_issues", {"rate": 1.0, "pitch": 1.0}, {"rate": 1.1, "pitch": 2.0}, "Adjusted speech rate and pitch"),
        ("text_truncation", "short", "full text", "LLM truncated output, restored full content"),
        ("emotion_intensity", {"intensity": 0.5}, {"intensity": 0.7}, "Increased emotion intensity"),
    ]

    db = session_factory()
    try:
        for i in range(count):
            pattern_idx = i % len(patterns)
            pattern_name, wrong_output, correct_output, rationale = patterns[pattern_idx]

            # Prepare outputs
            llm_output = {"emotion": wrong_output} if isinstance(wrong_output, str) else wrong_output
            corrected_output = {"emotion": correct_output} if isinstance(correct_output, str) else correct_output

            record = capture_feedback(
                db=db,
                project_id=project_id,
                source="human_edit",
                stage="annotate_paragraph",
                input_snapshot={"text": f"Test paragraph {i}", "type": "dialogue"},
                llm_output=llm_output,
                corrected_output=corrected_output,
                rationale=rationale,
                paragraph_index=(i % 3) + 1,
                chapter_index=(i // 3) + 1,
                paragraph_id=(i % 3) + 1,
                chapter_id=(i // 3) + 1,
                diff_summary=f"{wrong_output} -> {correct_output}",
                pattern_tags=[pattern_name, "test_feedback"],
            )
            injected_ids.append(record.feedback_id)
            print(f"✅ Injected feedback: {record.feedback_id} (pattern: {pattern_name})")
    finally:
        db.close()

    return injected_ids


def trigger_self_iteration(project_id: int) -> dict:
    """Trigger the self-iteration loop manually."""
    from src.audiobook_studio.feedback.integration import create_self_iteration_loop
    from src.audiobook_studio.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Create session factory with correct database path
    db_path = Path(__file__).parent.parent / "audiobook_studio.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    # Create and trigger self iteration loop
    loop = create_self_iteration_loop(
        db_session_factory=session_factory,
        project_id=project_id,
        min_feedback_count=10,  # Already set to match our injected count
        check_interval_seconds=60,
        enable_auto_trigger=False,  # Manual trigger only
        canary_percentage=0.1,
    )

    # Trigger iteration manually
    result = loop.trigger_iteration_now()

    if result:
        print(f"\n🔄 Self-iteration triggered: {result.total_analyzed} records analyzed")
        print(f"Pattern count: {len(result.top_patterns)}")
        for p in result.top_patterns[:3]:
            print(f"  - {p}")

        return loop.get_status()
    else:
        print("❌ No iteration triggered - insufficient feedback or processing error")
        return {}


def main():
    parser = argparse.ArgumentParser(description="Inject test feedback for self-iteration verification")
    parser.add_argument("--project-id", type=int, default=1, help="Project ID")
    parser.add_argument("--count", type=int, default=10, help="Number of feedback records to inject")
    parser.add_argument("--trigger", action="store_true", help="Trigger self-iteration after injection")
    args = parser.parse_args()

    print(f"Injecting {args.count} feedback records for project {args.project_id}")
    print("=" * 60)

    injected = inject_test_feedback(args.project_id, args.count)
    print(f"\n✅ Injected {len(injected)} feedback records")

    if args.trigger:
        print("\nTriggering self-iteration loop...")
        print("=" * 60)
        status = trigger_self_iteration(args.project_id)
        print(f"\n📊 Status: {json.dumps(status, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
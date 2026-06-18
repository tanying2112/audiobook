#!/usr/bin/env python3
"""
E2E Long Novel Verification Script for Audiobook Studio.
Runs the full pipeline on a long novel (e.g., 红楼梦) in mock mode
and generates detailed performance/cost/quality reports.
"""

import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

# Add src to path
sys.path.insert(0, "src")

from audiobook_studio.pipeline import (
    extract_text,
    analyze_structure,
    annotate_paragraph,
    edit_for_tts,
    synthesize_paragraphs,
    quality_check,
)
from audiobook_studio.schemas import (
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
    ParagraphAnnotation,
    TtsEditInput,
    TtsRoutingDecision,
    TtsRoutingInput,
    ExtractionInput,
    BookAnalysisInput,
    QualityJudgment,
)


@dataclass
class StageMetrics:
    """Metrics for a single pipeline stage."""
    stage_name: str
    duration_ms: float
    success: bool
    input_size: int = 0
    output_size: int = 0
    error_message: str = ""
    mock_cost_usd: float = 0.0


@dataclass
class PipelineReport:
    """Complete pipeline execution report."""
    book_id: str
    book_title: str
    total_text_chars: int
    total_paragraphs: int
    stages: List[StageMetrics]
    total_duration_ms: float
    total_mock_cost_usd: float
    quality_summary: Dict[str, Any]
    timestamp: str
    passed: bool


def split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs by double newlines, filtering empty ones."""
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    # If no double newlines, try single newlines
    if len(paragraphs) <= 1:
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    return paragraphs


def run_extraction(novel_path: Path) -> tuple:
    """Stage 1: Text Extraction (use real extraction for text files)."""
    start = time.time()
    # Use mock_mode=False for text extraction to get actual content
    extraction = extract_text(
        file_path=str(novel_path),
        mime_type="text/plain",
        detect_language=True,
        mock_mode=False
    )
    duration = (time.time() - start) * 1000
    metrics = StageMetrics(
        stage_name="extract",
        duration_ms=duration,
        success=True,
        input_size=novel_path.stat().st_size,
        output_size=len(extraction.raw_text),
        mock_cost_usd=0.0
    )
    return extraction, metrics


def run_analyze(text: str, title_hint: str = "Long Novel") -> tuple:
    """Stage 2: Structure Analysis."""
    start = time.time()
    analysis = analyze_structure(text, title_hint=title_hint, mock_mode=True)
    duration = (time.time() - start) * 1000
    metrics = StageMetrics(
        stage_name="analyze_structure",
        duration_ms=duration,
        success=True,
        input_size=len(text),
        output_size=len(analysis.story_line_summary),
        mock_cost_usd=0.0
    )
    return analysis, metrics


def run_annotate_paragraphs(
    paragraphs: List[str],
    analysis,
    max_paragraphs: int = 100  # Limit for verification
) -> tuple:
    """Stage 3: Paragraph Annotation (process up to max_paragraphs)."""
    start = time.time()
    annotations = []
    total_chars = 0

    # Use first emotion snapshot as default
    default_emotion_snapshot = analysis.emotion_snapshots[0] if analysis.emotion_snapshots else EmotionSnapshot(
        emotion="neutral", intensity=0.5, confidence=0.8
    )

    story_line_summary = analysis.story_line_summary
    global_style_notes = getattr(analysis, 'global_style_notes', 'Standard narrative style.')

    for i, para_text in enumerate(paragraphs[:max_paragraphs]):
        try:
            annotation = annotate_paragraph(
                paragraph_text=para_text,
                paragraph_index=i,
                chapter_index=1,
                book_meta=analysis.book_meta,
                character_voice_map=analysis.character_voice_map,
                emotion_snapshot=default_emotion_snapshot,
                story_line_summary=story_line_summary,
                global_style_notes=global_style_notes,
                mock_mode=True
            )
            annotations.append(annotation)
            total_chars += len(para_text)
        except Exception as e:
            print(f"   ⚠️  Paragraph {i} annotation failed: {e}")
            # Continue with other paragraphs

    duration = (time.time() - start) * 1000
    metrics = StageMetrics(
        stage_name="annotate_paragraph",
        duration_ms=duration,
        success=len(annotations) > 0,
        input_size=total_chars,
        output_size=len(annotations),
        mock_cost_usd=0.0
    )
    return annotations, metrics


def run_edit_for_tts(
    paragraphs: List[str],
    annotations: List[ParagraphAnnotation],
    max_paragraphs: int = 100
) -> tuple:
    """Stage 4: TTS Editing."""
    start = time.time()
    edited_results = []
    total_chars = 0

    for i, (para_text, annotation) in enumerate(zip(paragraphs[:max_paragraphs], annotations[:max_paragraphs])):
        try:
            result = edit_for_tts(
                paragraph_text=para_text,
                paragraph_annotation=annotation,
                difficulty="B",
                mock_mode=True
            )
            edited_results.append(result)
            total_chars += len(result.edited_text)
        except Exception as e:
            print(f"   ⚠️  Paragraph {i} edit failed: {e}")

    duration = (time.time() - start) * 1000
    metrics = StageMetrics(
        stage_name="edit_for_tts",
        duration_ms=duration,
        success=len(edited_results) > 0,
        input_size=sum(len(p) for p in paragraphs[:max_paragraphs]),
        output_size=total_chars,
        mock_cost_usd=0.0
    )
    return edited_results, metrics


def run_synth(
    annotations: List[ParagraphAnnotation],
    edited_results,
    analysis,
    max_paragraphs: int = 100
) -> tuple:
    """Stage 5: Audio Synthesis."""
    start = time.time()

    # Prepare TTS inputs
    char_voice_map = analysis.character_voice_map if analysis.character_voice_map else [
        CharacterVoiceBinding(
            canonical_name="旁白", aliases=[], gender="neutral",
            age_range="adult", suggested_voice_id="v1", sample_quote=None
        )
    ]

    tts_inputs = []
    for i, (annotation, edited_result) in enumerate(zip(annotations[:max_paragraphs], edited_results[:max_paragraphs])):
        tts_input = TtsRoutingInput(
            paragraph_annotation=annotation,
            text=edited_result.edited_text if hasattr(edited_result, 'edited_text') else "",
            character_voice_map=char_voice_map,
            book_id="long_novel",
            chapter_index=1,
            paragraph_index=i,
            cumulative_cost_usd=0.0,
            cost_limit_per_book=20.0,
            cost_limit_per_chapter=5.0,
            prefer_local=True
        )
        tts_inputs.append(tts_input)

    synthesis = synthesize_paragraphs(inputs=tts_inputs, mock_mode=True)

    duration = (time.time() - start) * 1000
    total_duration = sum(s.duration_ms for s in synthesis)

    metrics = StageMetrics(
        stage_name="synthesize",
        duration_ms=duration,
        success=len(synthesis) > 0,
        input_size=len(tts_inputs),
        output_size=total_duration,
        mock_cost_usd=0.0
    )
    return synthesis, metrics


def run_quality(
    annotations: List[ParagraphAnnotation],
    edited_results,
    synthesis,
    routing_decisions: List[TtsRoutingDecision],
    max_paragraphs: int = 100
) -> tuple:
    """Stage 6: Quality Check."""
    start = time.time()

    quality_inputs = []
    for i, (annotation, edited_result, segment) in enumerate(
        zip(annotations[:max_paragraphs], edited_results[:max_paragraphs], synthesis[:max_paragraphs])
    ):
        reference_text = edited_result.edited_text if hasattr(edited_result, 'edited_text') else ""
        quality_inputs.append((
            segment.file_path,
            annotation,
            routing_decisions[i] if i < len(routing_decisions) else TtsRoutingDecision(
                segment_id=f"long_novel_ch1_p{i}",
                engine_choice="kokoro", voice_id="v1",
                prosody_overrides={}, fallback_engine="edge",
                reasoning="Mock", estimated_cost_usd=0.0, estimated_duration_ms=3000
            ),
            reference_text
        ))

    quality_results = quality_check(inputs=quality_inputs, mock_mode=True)

    duration = (time.time() - start) * 1000

    # Calculate quality summary
    avg_score = sum(r.overall_score for r in quality_results) / len(quality_results) if quality_results else 0
    total_issues = sum(len(r.issues) for r in quality_results)
    needs_regeneration_count = sum(1 for r in quality_results if r.needs_regeneration)

    quality_summary = {
        "avg_overall_score": round(avg_score, 3),
        "total_issues": total_issues,
        "needs_regeneration_count": needs_regeneration_count,
        "score_distribution": {
            "speaker_clarity": round(sum(r.speaker_clarity for r in quality_results) / len(quality_results), 3) if quality_results else 0,
            "emotion_match": round(sum(r.emotion_match for r in quality_results) / len(quality_results), 3) if quality_results else 0,
            "prosody_naturalness": round(sum(r.prosody_naturalness for r in quality_results) / len(quality_results), 3) if quality_results else 0,
            "text_audio_alignment": round(sum(r.text_audio_alignment for r in quality_results) / len(quality_results), 3) if quality_results else 0,
        }
    }

    metrics = StageMetrics(
        stage_name="quality_check",
        duration_ms=duration,
        success=len(quality_results) > 0,
        input_size=len(quality_inputs),
        output_size=len(quality_results),
        mock_cost_usd=0.0
    )
    return quality_results, metrics, quality_summary


def run_e2e_long_book(
    novel_path: Path,
    book_id: str = "long_novel",
    title_hint: str = "Long Novel",
    max_paragraphs: int = 100
) -> PipelineReport:
    """Run full E2E pipeline on long novel."""

    print(f"🚀 Starting E2E Long Book Verification: {novel_path.name}")
    print(f"   Book ID: {book_id}")
    print(f"   Max paragraphs to process: {max_paragraphs}")
    print("=" * 70)

    stage_metrics = []

    # Stage 1: Extract
    print("\n📤 Stage 1: Text Extraction")
    try:
        extraction, metrics = run_extraction(novel_path)
        stage_metrics.append(metrics)
        print(f"   ✅ {metrics.duration_ms:.1f}ms | Input: {metrics.input_size} bytes | Output: {metrics.output_size} chars | Language: {extraction.language}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        stage_metrics.append(StageMetrics("extract", 0, False, error_message=str(e)))
        return PipelineReport(
            book_id=book_id, book_title=title_hint,
            total_text_chars=0, total_paragraphs=0,
            stages=stage_metrics, total_duration_ms=0,
            total_mock_cost_usd=0, quality_summary={},
            timestamp=datetime.now().isoformat(), passed=False
        )

    # Split into paragraphs
    paragraphs = split_paragraphs(extraction.raw_text)
    print(f"   📄 Found {len(paragraphs)} paragraphs")

    # Stage 2: Analyze
    print("\n🔍 Stage 2: Structure Analysis")
    try:
        analysis, metrics = run_analyze(extraction.raw_text, title_hint)
        stage_metrics.append(metrics)
        print(f"   ✅ {metrics.duration_ms:.1f}ms | Characters: {len(analysis.character_voice_map)} | Emotions: {len(analysis.emotion_snapshots)}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        stage_metrics.append(StageMetrics("analyze_structure", 0, False, error_message=str(e)))
        return PipelineReport(
            book_id=book_id, book_title=title_hint,
            total_text_chars=len(extraction.raw_text), total_paragraphs=len(paragraphs),
            stages=stage_metrics, total_duration_ms=sum(m.duration_ms for m in stage_metrics),
            total_mock_cost_usd=0, quality_summary={},
            timestamp=datetime.now().isoformat(), passed=False
        )

    # Stage 3: Annotate
    print(f"\n🏷️  Stage 3: Paragraph Annotation (first {max_paragraphs} paragraphs)")
    try:
        annotations, metrics = run_annotate_paragraphs(paragraphs, analysis, max_paragraphs)
        stage_metrics.append(metrics)
        print(f"   ✅ {metrics.duration_ms:.1f}ms | Annotated: {len(annotations)} paragraphs")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        stage_metrics.append(StageMetrics("annotate_paragraph", 0, False, error_message=str(e)))
        return PipelineReport(
            book_id=book_id, book_title=title_hint,
            total_text_chars=len(extraction.raw_text), total_paragraphs=len(paragraphs),
            stages=stage_metrics, total_duration_ms=sum(m.duration_ms for m in stage_metrics),
            total_mock_cost_usd=0, quality_summary={},
            timestamp=datetime.now().isoformat(), passed=False
        )

    # Stage 4: Edit for TTS
    print(f"\n🎛️  Stage 4: TTS Editing (first {max_paragraphs} paragraphs)")
    try:
        edited_results, metrics = run_edit_for_tts(paragraphs, annotations, max_paragraphs)
        stage_metrics.append(metrics)
        print(f"   ✅ {metrics.duration_ms:.1f}ms | Edited: {len(edited_results)} paragraphs")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        stage_metrics.append(StageMetrics("edit_for_tts", 0, False, error_message=str(e)))
        return PipelineReport(
            book_id=book_id, book_title=title_hint,
            total_text_chars=len(extraction.raw_text), total_paragraphs=len(paragraphs),
            stages=stage_metrics, total_duration_ms=sum(m.duration_ms for m in stage_metrics),
            total_mock_cost_usd=0, quality_summary={},
            timestamp=datetime.now().isoformat(), passed=False
        )

    # Stage 5: Synthesize
    print(f"\n🔊 Stage 5: Audio Synthesis (first {max_paragraphs} paragraphs)")
    try:
        synthesis, metrics = run_synth(annotations, edited_results, analysis, max_paragraphs)
        stage_metrics.append(metrics)
        total_audio_ms = sum(s.duration_ms for s in synthesis)
        print(f"   ✅ {metrics.duration_ms:.1f}ms | Segments: {len(synthesis)} | Total audio: {total_audio_ms}ms")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        stage_metrics.append(StageMetrics("synthesize", 0, False, error_message=str(e)))
        return PipelineReport(
            book_id=book_id, book_title=title_hint,
            total_text_chars=len(extraction.raw_text), total_paragraphs=len(paragraphs),
            stages=stage_metrics, total_duration_ms=sum(m.duration_ms for m in stage_metrics),
            total_mock_cost_usd=0, quality_summary={},
            timestamp=datetime.now().isoformat(), passed=False
        )

    # Prepare routing decisions for quality check
    routing_decisions = []
    for i, annotation in enumerate(annotations[:max_paragraphs]):
        routing = TtsRoutingDecision(
            segment_id=f"{book_id}_ch1_p{i}",
            engine_choice="kokoro",
            voice_id="v1",
            prosody_overrides={},
            fallback_engine="edge",
            reasoning="Mock routing decision for E2E verification",
            estimated_cost_usd=0.0,
            estimated_duration_ms=synthesis[i].duration_ms if i < len(synthesis) else 3000,
        )
        routing_decisions.append(routing)

    # Stage 6: Quality Check
    print(f"\n🔍 Stage 6: Quality Check (first {max_paragraphs} paragraphs)")
    try:
        quality_results, metrics, quality_summary = run_quality(annotations, edited_results, synthesis, routing_decisions, max_paragraphs)
        stage_metrics.append(metrics)
        print(f"   ✅ {metrics.duration_ms:.1f}ms | Checked: {len(quality_results)} segments")
        print(f"   📊 Avg Score: {quality_summary['avg_overall_score']:.3f} | Issues: {quality_summary['total_issues']} | Regen needed: {quality_summary['needs_regeneration_count']}")
        for k, v in quality_summary['score_distribution'].items():
            print(f"      {k}: {v:.3f}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        stage_metrics.append(StageMetrics("quality_check", 0, False, error_message=str(e)))
        quality_summary = {}

    # Final report
    total_duration = sum(m.duration_ms for m in stage_metrics)
    all_passed = all(m.success for m in stage_metrics)

    report = PipelineReport(
        book_id=book_id,
        book_title=analysis.book_meta.title if 'analysis' in locals() else title_hint,
        total_text_chars=len(extraction.raw_text) if 'extraction' in locals() else 0,
        total_paragraphs=len(paragraphs),
        stages=stage_metrics,
        total_duration_ms=total_duration,
        total_mock_cost_usd=sum(m.mock_cost_usd for m in stage_metrics),
        quality_summary=quality_summary,
        timestamp=datetime.now().isoformat(),
        passed=all_passed
    )

    return report


def save_report(report: PipelineReport, output_path: Path):
    """Save report to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert dataclasses to dict
    report_dict = asdict(report)
    report_dict['stages'] = [asdict(m) for m in report.stages]

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report_dict, f, ensure_ascii=False, indent=2)

    print(f"\n📝 Report saved to: {output_path}")


def print_summary(report: PipelineReport):
    """Print formatted summary."""
    print("\n" + "=" * 70)
    print("📊 E2E LONG NOVEL VERIFICATION REPORT")
    print("=" * 70)
    print(f"📖 Book: {report.book_title} ({report.book_id})")
    print(f"📝 Total text: {report.total_text_chars:,} characters")
    print(f"📄 Total paragraphs: {report.total_paragraphs}")
    print(f"⏱️  Total pipeline time: {report.total_duration_ms:.1f}ms")
    print(f"💰 Mock total cost: ${report.total_mock_cost_usd:.4f}")
    print(f"✅ Overall: {'PASSED' if report.passed else 'FAILED'}")
    print(f"🕐 Timestamp: {report.timestamp}")

    print("\n📈 Stage Breakdown:")
    print("-" * 70)
    for m in report.stages:
        status = "✅" if m.success else "❌"
        print(f"  {status} {m.stage_name:20s} | {m.duration_ms:8.1f}ms | in:{m.input_size:>8} | out:{m.output_size:>8}")

    if report.quality_summary:
        qs = report.quality_summary
        print(f"\n🎯 Quality Summary:")
        print(f"   Overall Score: {qs['avg_overall_score']:.3f}")
        print(f"   Total Issues: {qs['total_issues']}")
        print(f"   Needs Regeneration: {qs['needs_regeneration_count']}")
        for k, v in qs['score_distribution'].items():
            print(f"   {k}: {v:.3f}")

    print("=" * 70)

    # Performance insights
    if report.stages:
        slowest = max(report.stages, key=lambda m: m.duration_ms)
        print(f"\n💡 Insights:")
        print(f"   Slowest stage: {slowest.stage_name} ({slowest.duration_ms:.1f}ms)")

        # Check if any stage took suspiciously long
        for m in report.stages:
            if m.duration_ms > 5000:  # >5 seconds in mock mode is unusual
                print(f"   ⚠️  {m.stage_name} took {m.duration_ms:.1f}ms (unexpectedly slow for mock mode)")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="E2E Long Novel Verification")
    parser.add_argument("--novel", default="data/long_novel/hongloumeng.txt", help="Path to novel text file")
    parser.add_argument("--book-id", default="hongloumeng", help="Book identifier")
    parser.add_argument("--title", default="红楼梦", help="Book title hint")
    parser.add_argument("--max-paragraphs", type=int, default=100, help="Max paragraphs to process (for verification speed)")
    parser.add_argument("--output", default="reports/e2e_long_book_report.json", help="Output report path")

    args = parser.parse_args()

    novel_path = Path(args.novel)
    if not novel_path.exists():
        print(f"❌ Error: Novel file not found: {novel_path}")
        return 1

    # Run E2E verification
    report = run_e2e_long_book(
        novel_path=novel_path,
        book_id=args.book_id,
        title_hint=args.title,
        max_paragraphs=args.max_paragraphs
    )

    # Save report
    save_report(report, Path(args.output))

    # Print summary
    print_summary(report)

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
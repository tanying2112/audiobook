#!/usr/bin/env python3
"""
End-to-end verification script for Audiobook Studio pipeline.
Runs the full pipeline on a test novel in mock mode and validates outputs.
"""

import sys
import os
from pathlib import Path

# Add src to path so we can import the pipeline modules
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
)

def main():
    print("🔍 Starting Audiobook Studio End-to-End Verification")
    print("=" * 60)
    
    # 1. Load test novel
    print("📖 Loading test novel...")
    novel_path = Path("data/test_novel.txt")
    if not novel_path.exists():
        print(f"❌ Error: Test novel not found at {novel_path}")
        return 1
    
    with open(novel_path, 'r', encoding='utf-8') as f:
        novel_text = f.read()
    
    print(f"   Loaded novel with {len(novel_text)} characters ({len(novel_text.split())} words)")
    
    # 2. Extract text (simulate)
    print("\n📤 Stage 1: Text Extraction")
    try:
        extraction = extract_text(
            file_path=str(novel_path),
            mime_type="text/plain",
            detect_language=True,
            mock_mode=True
        )
        print(f"   ✅ Extraction successful: {extraction.language}, {extraction.page_count} pages")
        print(f"   📝 Raw text preview: {extraction.raw_text[:100]}...")
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        return 1
    
    # 3. Analyze structure
    print("\n🔍 Stage 2: Structure Analysis")
    try:
        analysis = analyze_structure(
            extraction.raw_text, 
            title_hint="Test Novel Verification", 
            mock_mode=True
        )
        print(f"   ✅ Analysis successful: {analysis.book_meta.title}")
        print(f"   👥 Characters found: {len(analysis.character_voice_map)}")
        print(f"   😊 Emotion snapshots: {len(analysis.emotion_snapshots)}")
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        return 1
    
    # 4. Annotate paragraphs (process first few paragraphs)
    print("\n🏷️  Stage 3: Paragraph Annotation")
    try:
        # Split text into paragraphs (simple approach)
        paragraphs = [p.strip() for p in novel_text.split('\n\n') if p.strip()]
        if not paragraphs:
            paragraphs = [novel_text]  # fallback to whole text
        
        print(f"   📄 Found {len(paragraphs)} paragraphs to process")
        
        # Process first 3 paragraphs for verification
        annotations = []
        for i in range(min(3, len(paragraphs))):
            para_text = paragraphs[i]
            print(f"   Processing paragraph {i+1}: '{para_text[:50]}...'")
            
            annotation = annotate_paragraph(
                paragraph_text=para_text,
                paragraph_index=i,
                chapter_index=1,
                book_meta=analysis.book_meta,
                character_voice_map=analysis.character_voice_map,
                emotion_snapshot=analysis.emotion_snapshots[0] if analysis.emotion_snapshots else EmotionSnapshot(
                    emotion="neutral",
                    intensity=0.5,
                    confidence=0.8
                ),
                story_line_summary="This is a test verification story line summary that has sufficient length to meet the minimum character requirement for the pipeline validation process, ensuring that the annotation function receives properly formatted input data.",
                global_style_notes="Test global style notes for verification.",
                mock_mode=True
            )
            annotations.append(annotation)
            print(f"      ✅ Annotated: speaker={annotation.speaker_canonical_name}, emotion={annotation.emotion}")
        
        print(f"   ✅ Annotation complete: {len(annotations)} paragraphs processed")
    except Exception as e:
        print(f"❌ Annotation failed: {e}")
        return 1
    
    # 5. Edit for TTS
    print("\n🎛️  Stage 4: TTS Editing")
    try:
        edited_results = []
        for i, annotation in enumerate(annotations):
            para_text = paragraphs[i] if i < len(paragraphs) else annotations[i].paragraph_text if hasattr(annotations[i], 'paragraph_text') else "Test paragraph"
            
            result = edit_for_tts(
                paragraph_text=para_text,
                paragraph_annotation=annotation,
                difficulty="B",
                mock_mode=True
            )
            edited_results.append(result)
            print(f"   ✅ Edited paragraph {i+1}: {len(result.changes_made)} changes made")
        
        print(f"   ✅ TTS editing complete: {len(edited_results)} paragraphs processed")
    except Exception as e:
        print(f"❌ TTS editing failed: {e}")
        return 1
    
    # 6. Synthesize
    print("\n🔊 Stage 5: Audio Synthesis")
    try:
        # Prepare TTS routing inputs
        from audiobook_studio.schemas import TtsRoutingInput, CharacterVoiceBinding
        tts_inputs = []
        for i, (annotation, edited_result) in enumerate(zip(annotations, edited_results)):
            # Create a minimal character voice binding for TTS routing input
            char_voice_bindings = [CharacterVoiceBinding(
                canonical_name="旁白",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="v1",
                sample_quote=None
            )] if not analysis.character_voice_map else analysis.character_voice_map

            tts_input = TtsRoutingInput(
                paragraph_annotation=annotation,
                text=edited_result.edited_text if hasattr(edited_result, 'edited_text') else paragraphs[i] if i < len(paragraphs) else "Test paragraph",
                character_voice_map=char_voice_bindings,
                book_id="test_book",
                chapter_index=1,
                paragraph_index=i,
                cumulative_cost_usd=0.0,
                cost_limit_per_book=20.0,
                cost_limit_per_chapter=5.0,
                prefer_local=True
            )
            tts_inputs.append(tts_input)

        synthesis = synthesize_paragraphs(
            inputs=tts_inputs,
            mock_mode=True
        )
        print(f"   ✅ Synthesis successful: {len(synthesis)} audio segments generated")
        total_duration = sum(segment.duration_ms for segment in synthesis)
        print(f"   ⏱️  Total estimated duration: {total_duration}ms")
    except Exception as e:
        print(f"❌ Synthesis failed: {e}")
        return 1
    
    # 7. Quality check
    print("\n🔍 Stage 6: Quality Check")
    try:
        # Prepare TTS routing decisions (simplified)
        routing_decisions = []
        for i, annotation in enumerate(annotations):
            routing = TtsRoutingDecision(
                segment_id=f"test_ch1_p{i}",
                engine_choice="kokoro",
                voice_id="v1",
                prosody_overrides={},
                fallback_engine="edge",
                reasoning="Mock routing decision for E2E verification test",
                estimated_cost_usd=0.0,
                estimated_duration_ms=3000,
            )
            routing_decisions.append(routing)
        
        # Prepare inputs for quality check: list of (audio_path, annotation, routing_decision, reference_text)
        quality_inputs = []
        for i, (annotation, edited_result, segment) in enumerate(zip(annotations, edited_results, synthesis)):
            audio_path = segment.file_path
            reference_text = edited_result.edited_text if hasattr(edited_result, 'edited_text') else (
                paragraphs[i] if i < len(paragraphs) else "Test paragraph"
            )
            quality_inputs.append((
                audio_path,
                annotation,
                routing_decisions[i],
                reference_text
            ))

        quality_results = quality_check(
            inputs=quality_inputs,
            mock_mode=True
        )
        # quality_results is List[QualityJudgment]
        avg_score = sum(r.overall_score for r in quality_results) / len(quality_results)
        total_issues = sum(len(r.issues) for r in quality_results)
        print(f"   ✅ Quality check complete: {avg_score:.2f} average overall score")
        print(f"   📊 Issues found: {total_issues}")
    except Exception as e:
        print(f"❌ Quality check failed: {e}")
        return 1

    print("\n" + "=" * 60)
    print("🎉 End-to-End Verification Completed Successfully!")
    print("📊 Summary:")
    print(f"   - Text extraction: ✅")
    print(f"   - Structure analysis: ✅ ({len(analysis.character_voice_map)} characters)")
    print(f"   - Paragraph annotation: ✅ ({len(annotations)} paragraphs)")
    print(f"   - TTS editing: ✅ ({len(edited_results)} paragraphs)")
    print(f"   - Audio synthesis: ✅ ({len(synthesis)} segments)")
    print(f"   - Quality check: ✅ (avg score: {avg_score:.2f})")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

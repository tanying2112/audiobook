"""Step 2 (Run A): 真实 LLM 标注管线 — 原声对照任务的系统侧标注生成.

链路: analyze_structure(全文) → annotate_paragraph(逐段) → edit_for_tts(逐段)
      → audio_director(逐段, language=en, 切句与合成侧 _split_sentences 同源)。
输入: scratch/ff_system/ch1_llm_clean_masked.txt (Run B 清洗文本, 掩蔽 ASR 起点)
输出: scratch/ff_system/run_b_annotations.json (+ .jsonl 增量, 支持断点续跑)
"""
import json, sys
from pathlib import Path

sys.path.insert(0, "src")
ROOT = Path(__file__).resolve().parents[2]
SRC_TXT = ROOT / "scratch/ff_system/ch1_llm_clean_masked.txt"
OUT = ROOT / "scratch/ff_system/run_b_annotations.json"
JSONL = OUT.with_suffix(".jsonl")


def main():
    from audiobook_studio.llm import create_router
    from audiobook_studio.schemas.book import BookAnalysisInput
    from audiobook_studio.schemas.paragraph import ParagraphAnnotationInput
    from audiobook_studio.schemas.tts_edit import TtsEditInput
    from audiobook_studio.schemas.audio_director import AudioDirectorInput
    from audiobook_studio.pipeline.analyze_structure import AnalyzeStructurePipeline
    from audiobook_studio.pipeline.annotate_paragraph import AnnotateParagraphPipeline
    from audiobook_studio.pipeline.edit_for_tts import EditForTtsPipeline
    from audiobook_studio.pipeline.audio_director import AudioDirectorPipeline
    from audiobook_studio.pipeline.synthesize import _split_sentences, list_engine_voices
    available_voices = list_engine_voices("en", "kokoro")

    raw = SRC_TXT.read_text(encoding="utf-8")
    paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
    router = create_router(mock_mode=False)

    # ── (a) 全文结构分析 ──
    print(f"[s2b] analyze_structure: {len(paras)} 段 {sum(len(p.split()) for p in paras)} 词 ...", flush=True)
    book = AnalyzeStructurePipeline(router=router, mock_mode=False).run(
        BookAnalysisInput(raw_text=raw, title_hint="Football Forever",
                          author_hint="Oxford Dominoes Level 1 graded reader (football story, Brazil)",
                          target_difficulty="A"))
    bm = book.book_meta
    print(f"[s2b] book_meta: lang={bm.language!r} title={bm.title!r} "
          f"chars={len(book.character_voice_map)} snapshots={len(book.emotion_snapshots)}", flush=True)
    snap = next((s for s in book.emotion_snapshots if s.chapter == 1), book.emotion_snapshots[0])
    book_dump = {"book_meta": bm.model_dump(), "character_voice_map": [c.model_dump() for c in book.character_voice_map],
                 "emotion_snapshot": snap.model_dump(), "story_line_summary": book.story_line_summary,
                 "global_style_notes": book.global_style_notes, "scene_tags": book.scene_tags}

    # 断点续跑: 已有 JSONL 记录跳过
    done = {}
    if JSONL.exists():
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    done[r["idx"]] = r
                except Exception:
                    pass
    print(f"[s2b] resume: {len(done)} 段已完成, 从 p{max(done) + 1 if done else 0} 续", flush=True)

    ann_pipe = AnnotateParagraphPipeline(router=router, mock_mode=False)
    edit_pipe = EditForTtsPipeline(router=router, mock_mode=False)
    dir_pipe = AudioDirectorPipeline(router=router, mock_mode=False)

    def suggested_voice(speaker):
        for c in book.character_voice_map:
            if c.canonical_name == speaker:
                return c.suggested_voice_id
        return None

    with JSONL.open("a", encoding="utf-8") as jf:
        for idx, para in enumerate(paras):
            if idx in done:
                continue
            rec = {"idx": idx, "source_text": para}
            try:
                ann = ann_pipe.run(ParagraphAnnotationInput(
                    paragraph_text=para, paragraph_index=idx, chapter_index=1,
                    book_meta=bm, character_voice_map=book.character_voice_map,
                    emotion_snapshot=snap, story_line_summary=book.story_line_summary,
                    global_style_notes=book.global_style_notes))
                rec["annotation"] = ann.model_dump()
                edit = edit_pipe.run(TtsEditInput(paragraph_text=para, paragraph_annotation=ann,
                                                  difficulty="A"))
                rec["edit"] = edit.model_dump()
                synth_text = (edit.edited_text or "").strip() or para
                sents = _split_sentences(synth_text)
                director = dir_pipe.run(AudioDirectorInput(
                    paragraph_text=synth_text, sentences=sents,
                    speaker_name=ann.speaker_canonical_name, emotion=ann.emotion,
                    emotion_intensity=ann.emotion_intensity, is_dialogue=ann.is_dialogue,
                    language="en", voice_id=suggested_voice(ann.speaker_canonical_name),
                    difficulty=(bm.difficulty or "A"),  # Gap D: 难度传导
                    available_voices=available_voices))  # Gap G: 音色表契约
                rec["synth_text"] = synth_text
                rec["sentences"] = sents
                rec["director"] = director.model_dump()
                rec["ok"] = True
                print(f"[s2b] p{idx} ok: spk={ann.speaker_canonical_name} emo={ann.emotion} "
                      f"({ann.emotion_intensity}) edits={len(edit.changes_made or [])} "
                      f"sents={len(sents)} ovr={len(director.sentence_overrides)}", flush=True)
            except Exception as e:
                rec["ok"] = False
                rec["error"] = f"{type(e).__name__}: {e}"[:400]
                print(f"[s2b] p{idx} FAIL: {rec['error'][:160]}", flush=True)
            jf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            jf.flush()

    # 汇总
    records = []
    if JSONL.exists():
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    records.sort(key=lambda r: r["idx"])
    ok_n = sum(1 for r in records if r.get("ok"))
    OUT.write_text(json.dumps({"book": book_dump, "records": records},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    fails = [r["idx"] for r in records if not r.get("ok")]
    print(f"[s2b] DONE: {ok_n}/{len(records)} 段成功 (fail={fails}) -> {OUT.name}", flush=True)
    sys.exit(1 if fails or ok_n != len(paras) else 0)


if __name__ == "__main__":
    main()

"""单轮真实验证：反馈注入 → LLM 分析 → prompt 升级 → canary → 4 门 → deploy → A/B。

用法:
  .venv/bin/python scratch/validate_round_real.py inject 12   # 仅注入反馈
  .venv/bin/python scratch/validate_round_real.py run         # 注入 + 全流程一轮
  PATTERN=pause_missing .venv/bin/python scratch/validate_round_real.py run
"""
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, "src")
os.environ.setdefault("SELF_ITERATION_MOCK", "false")
os.environ.setdefault("FCC_LOCAL_API_KEY", "freecc")
os.environ.setdefault("DATABASE_URL", "sqlite:///./src/data/audiobook.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "LiteLLM", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

PATTERN = os.environ.get("PATTERN", "pause_missing")
N_RECORDS = int(os.environ.get("N_RECORDS", "12"))

# 每个模式的「机器输出 / 人工修正 / 修改理由」对照（停顿、情感、音效等 edit 可修模式）
RATIONALE = {
    "pause_missing": (
        "机器编辑稿缺少必要的停顿标记：在人物开口说话与段落转折处应有 "
        "[pause_before_ms=500] 级别的停顿，当前输出没有任何停顿标记，"
        "直接朗读会显得急促不自然，需要补充停顿。"
    ),
    "sfx_missing": (
        "机器编辑稿缺少场景音效标记：开门、脚步、风雨等场景应使用 [sfx:类型] 标记，"
        "当前输出没有任何音效标记，听感沉浸感不足，需要补充场景音效。"
    ),
    "emotion_too_mild": (
        "机器编辑的情感表达过于平淡，情感强度不足：这段是高潮冲突情节，"
        "应使用更鲜明的情感描述词并提高情感强度值，而不是平静叙述。"
    ),
    "speaker_wrong": (
        "机器编辑稿对话归属识别错误：说话人标注错了，根据对话引导词'说道'，"
        "说话人应是前一句的主语，需要修正说话人识别。"
    ),
    "text_colloquial": (
        "机器编辑稿过于书面化，需要口语化：'然而''因此''是否'等书面连词"
        "应转换为'但是''所以''是不是'等自然口语表达。"
    ),
    "prosody_robotic": (
        "机器编辑稿句式过于工整机械，朗读起来有明显的机器人感、生硬不自然，"
        "需要调整句式结构使其符合自然口语节奏。"
    ),
}
# 修正稿相对机器稿的文本差异（体现该模式的修复动作）
CORRECTED_SUFFIX = {
    "pause_missing": " [pause_before_ms=500]",
    "sfx_missing": " [sfx:door_close]",
    "emotion_too_mild": "（他猛地攥紧拳头，声音发颤）",
    "speaker_wrong": "",
    "text_colloquial": "",
    "prosody_robotic": "……他顿了顿，才接着说。",
}


def _session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread": False})
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def inject(factory, n=N_RECORDS, pattern=PATTERN):
    from audiobook_studio.models.feedback_record import FeedbackRecord

    rationale = RATIONALE[pattern]
    suffix = CORRECTED_SUFFIX[pattern]
    base = json.loads(Path("data/golden/val/edit/edit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    inp = base["input"]

    db = factory()
    try:
        for i in range(n):
            machine_text = f"第{i + 1}段：他说道，今晚的月色很好，我们继续赶路吧。"
            corrected_text = machine_text + suffix
            rec = FeedbackRecord(
                feedback_id=f"round-{pattern}-{uuid.uuid4().hex[:12]}",
                project_id=1,
                source="human_correction",
                stage="edit",
                input_snapshot=inp,
                llm_output={
                    "edited_text": machine_text,
                    "changes_made": ["长句拆分"],
                    "forbidden_content_removed": [],
                    "confidence": 0.9,
                    "rationale": "常规编辑，无停顿/音效处理",
                },
                corrected_output={
                    "edited_text": corrected_text,
                    "changes_made": ["长句拆分", f"补充{pattern}相关处理"],
                    "forbidden_content_removed": [],
                    "confidence": 0.9,
                    "rationale": "人工修正稿",
                },
                rationale=rationale,
            )
            db.add(rec)
        db.commit()
        print(f"[inject] +{n} unprocessed edit feedback records (pattern fuel: {pattern})")
    finally:
        db.close()


def run_round(factory, pattern=PATTERN):
    from audiobook_studio.feedback.integration import SelfIterationLoop

    loop = SelfIterationLoop(
        db_session_factory=factory,
        project_id=1,
        canary_percentage=0.1,
        enable_auto_pr=False,   # 混合暂存树中 checkout 危险；PR 由驱动器末尾统一范围化提交
        enable_auto_merge=False,
        auto_deploy=True,
    )

    t0 = time.time()
    print("=" * 70)
    print("[1/3] trigger_now → 真实 LLM 批量差异分析")
    analysis = loop.auto_processor.trigger_now()
    if analysis is None:
        print("!! analysis 失败（见上方日志）")
        return 1
    print(f"    analyzed={analysis.total_analyzed}s elapsed={time.time()-t0:.0f}s")
    print(f"    top_patterns={analysis.top_patterns}")

    print("[2/3] _handle_new_analysis → upgrade → canary → 4 gates → deploy → A/B")
    loop._handle_new_analysis(analysis)

    print("[3/3] loop.get_status()")
    st = loop.get_status()
    summary = {
        "iteration_count": st["iteration_count"],
        "upgraded_prompts": st["upgraded_prompts"],
        "validation_results": st["validation_results"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str)[:4000])

    print(f"\n总耗时 {time.time()-t0:.0f}s")
    return 0


def main():
    factory = _session_factory()
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "inject":
        inject(factory)
        return 0
    inject(factory)
    return run_round(factory)


if __name__ == "__main__":
    sys.exit(main())

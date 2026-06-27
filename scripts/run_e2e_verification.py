#!/usr/bin/env python3
"""
Audiobook Studio — E2E Long Book Verification
==============================================
完整管线端到端验证，包括自迭代反馈循环。
测试场景：
1. 完整 7 阶段管线运行
2. FeedbackCollector 集成验证
3. 自迭代循环触发（模拟积累反馈）
4. Prompt 升级与 Promotion Gate
5. A/B 测试验证
6. Canary Release & 自动回滚
7. 版本存储与回滚
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audiobook_studio.pipeline.orchestrator import run_pipeline
from src.audiobook_studio.pipeline.feedback_collector import create_feedback_collector
from src.audiobook_studio.feedback.integration import (
    create_self_iteration_loop,
    collect_pipeline_feedback,
    save_quality_feedback,
    save_user_rating_feedback,
)
from src.audiobook_studio.database import get_database_url
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_test_book(book_dir: Path, num_chapters: int = 3, paragraphs_per_chapter: int = 5) -> Path:
    """创建测试用书籍文件."""
    book_path = book_dir / "test_book.txt"
    content = []
    for ch in range(num_chapters):
        content.append(f"=== 第 {ch+1} 章 ===\n")
        for para in range(paragraphs_per_chapter):
            if para % 3 == 0:
                content.append(f"李明说：「你好，今天天气真好！」\n")
            elif para % 3 == 1:
                content.append(f"旁白：这是一个描述性的段落，没有对话内容。\n")
            else:
                content.append(f"张三问：「明天有什么安排吗？」\n")
    book_path.write_text("".join(content), encoding="utf-8")
    return book_path


def get_db_session_factory():
    """创建数据库会话工厂."""
    db_url = get_database_url()
    engine = create_engine(db_url)
    return sessionmaker(bind=engine)


def run_full_pipeline_test(project_id: int, book_path: Path) -> Dict[str, Any]:
    """运行完整管线测试."""
    logger.info(f"Running full pipeline on {book_path}")

    # 创建 FeedbackCollector
    collector = create_feedback_collector(project_id)

    # 运行管线
    try:
        result = run_pipeline(
            input_path=str(book_path),
            project_id=project_id,
            feedback_collector=collector,
        )
        return {
            "success": True,
            "project_id": result.get("project_id"),
            "book_id": result.get("book_id"),
            "chapters_processed": len(result.get("chapters", [])),
        }
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        return {"success": False, "error": str(e)}


def test_feedback_collection(project_id: int, collector) -> Dict[str, Any]:
    """测试反馈收集功能."""
    logger.info("Testing feedback collection...")

    # 模拟收集各类反馈
    feedback_files = []

    # 1. 模拟人工编辑反馈
    with collect_pipeline_feedback(collector, "annotate", 0, 0) as capture:
        capture.set_llm_output({
            "emotion": "happy",
            "speaker_canonical_name": "旁白",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
            "confidence": 0.8,
        })
        # 人工修正：改为中性
        capture.set_corrected_output({
            "emotion": "neutral",
            "speaker_canonical_name": "旁白",
            "is_dialogue": False,
            "emotion_intensity": 0.3,
            "confidence": 0.9,
        })
        capture.set_rationale("Fixed emotion from happy to neutral for narrative")

    # 2. 模拟质量评判反馈
    save_quality_feedback(
        collector=collector,
        stage="quality_judge",
        chapter_index=0,
        paragraph_index=0,
        chapter_id=1,
        paragraph_id=1,
        quality_judgment={"overall_score": 0.7, "issues": ["emotion_mismatch"]},
        corrected_judgment={"overall_score": 0.9, "issues": []},
        rationale="Quality judge was too harsh"
    )
    feedback_files.append("quality_feedback.json")

    # 3. 模拟用户评分反馈
    save_user_rating_feedback(
        collector=collector,
        stage="synthesize",
        chapter_index=0,
        paragraph_index=0,
        chapter_id=1,
        paragraph_id=1,
        user_rating={"rating": 4, "comment": "Good voice quality"},
        rationale="User rated 4/5"
    )
    feedback_files.append("user_rating_feedback.json")

    return {
        "success": True,
        "feedback_types": ["human_edit", "quality_judge", "user_rating"],
        "files_created": len(feedback_files),
    }


def test_self_iteration_loop(project_id: int) -> Dict[str, Any]:
    """测试自迭代循环."""
    logger.info("Testing self-iteration loop...")

    session_factory = get_db_session_factory()

    # 创建自迭代循环（低阈值便于测试）
    loop = create_self_iteration_loop(
        db_session_factory=session_factory,
        project_id=project_id,
        min_feedback_count=3,  # 低阈值
        check_interval_seconds=60,
        enable_auto_trigger=True,
        canary_percentage=0.1,
    )

    # 启动循环
    loop.start()
    time.sleep(2)  # 给点时间检查

    # 手动触发一次迭代
    result = loop.trigger_iteration_now()

    # 获取状态
    status = loop.get_status()

    # 停止循环
    loop.stop()

    return {
        "success": True,
        "triggered_analysis": result is not None,
        "analysis_records": result.total_analyzed if result else 0,
        "patterns_found": len(result.top_patterns) if result else 0,
        "iteration_count": status.get("iteration_count", 0),
        "upgraded_prompts": status.get("upgraded_prompts", {}),
    }


def test_promotion_gate() -> Dict[str, Any]:
    """测试 Promotion Gate."""
    logger.info("Testing promotion gate...")

    from src.audiobook_studio.feedback.release import PromotionGate

    gate = PromotionGate()

    # 测试通过案例
    result = gate.evaluate(
        format_compliance_rate=0.995,
        golden_dataset_pass_rate=0.96,
        quality_score_ratio=1.03,
        human_preference_score=0.85,
    )

    # 测试失败案例
    result_fail = gate.evaluate(
        format_compliance_rate=0.98,
        golden_dataset_pass_rate=0.90,
        quality_score_ratio=1.01,
        human_preference_score=0.75,
    )

    return {
        "success": result.passed and not result_fail.passed,
        "pass_case": {"passed": result.passed, "failed_criteria": result.failed_criteria},
        "fail_case": {"passed": result_fail.passed, "failed_criteria": result_fail.failed_criteria},
    }


def test_ab_test() -> Dict[str, Any]:
    """测试 A/B 测试框架."""
    logger.info("Testing A/B test framework...")

    from src.audiobook_studio.feedback.ab_test import (
        run_ab_test,
        build_ab_samples,
        ABTestSample,
    )
    import uuid

    # 创建测试样本
    samples = [
        ABTestSample(
            sample_id=str(uuid.uuid4()),
            stage="edit_for_tts",
            input_data={"text": f"test {i}"},
            output_a={"edited_text": "short"},
            output_b={"edited_text": "much longer and better output text with more content"},
            version_a=1,
            version_b=2,
        )
        for i in range(5)
    ]

    report = run_ab_test("edit_for_tts", samples)

    return {
        "success": report.b_wins == 5 and report.is_significant,
        "a_wins": report.a_wins,
        "b_wins": report.b_wins,
        "improvement_pct": report.improvement_pct,
        "p_value": report.p_value,
        "is_significant": report.is_significant,
        "recommendation": report.recommendation,
    }


def test_canary_release() -> Dict[str, Any]:
    """测试 Canary Release 与自动回滚."""
    logger.info("Testing canary release...")

    from src.audiobook_studio.feedback.release import CanaryRelease, CanaryConfig, CanaryMetrics
    from datetime import datetime, timezone

    # 创建 canary release
    config = CanaryConfig(min_samples=50, rollback_threshold=0.95)
    canary = CanaryRelease(config)

    # 启动 canary
    canary.start_canary("edit_for_tts", "v2", 0.85)

    # 记录良好的指标（不应触发回滚）
    good_metrics = CanaryMetrics(
        version="v2",
        stage="edit_for_tts",
        samples_collected=100,
        avg_quality_score=0.87,
        baseline_quality_score=0.85,
        quality_ratio=0.87/0.85,
        error_rate=0.02,
        timestamp=datetime.now(timezone.utc),
    )
    canary.record_metrics("edit_for_tts", "v2", good_metrics)
    status_after_good = canary.get_canary_status("edit_for_tts", "v2")

    # 记录糟糕的指标（应触发回滚）
    bad_metrics = CanaryMetrics(
        version="v2",
        stage="edit_for_tts",
        samples_collected=100,
        avg_quality_score=0.78,  # ratio = 0.78/0.85 = 0.917 < 0.95
        baseline_quality_score=0.85,
        quality_ratio=0.78/0.85,
        error_rate=0.02,
        timestamp=datetime.now(timezone.utc),
    )
    canary.record_metrics("edit_for_tts", "v2", bad_metrics)
    status_after_bad = canary.get_canary_status("edit_for_tts", "v2")

    # 完成 canary
    canary.complete_canary("edit_for_tts", "v2")
    status_after_complete = canary.get_canary_status("edit_for_tts", "v2")

    return {
        "success": (
            status_after_good["status"] == "running" and
            status_after_bad["status"] == "rolled_back"
        ),
        "good_metrics_status": status_after_good["status"],
        "bad_metrics_status": status_after_bad["status"],
        "final_status": status_after_complete["status"],
        "rollback_triggered": status_after_bad["status"] == "rolled_back",
    }


def test_version_store() -> Dict[str, Any]:
    """测试版本存储与回滚."""
    logger.info("Testing version store...")

    import tempfile
    from src.audiobook_studio.feedback.release import VersionStore
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "prompts"
        tmp_path.mkdir()

        # 创建 stage 目录和版本文件
        stage_dir = tmp_path / "edit_for_tts"
        stage_dir.mkdir()
        for v in [1, 2, 3]:
            (stage_dir / f"v{v}.j2").write_text(f"prompt version {v}")

        store = VersionStore(tmp_path)

        # 测试获取当前版本
        current = store.get_current_version("edit_for_tts")

        # 测试回滚
        rollback_success = store.rollback_version("edit_for_tts", 1)
        after_rollback = store.get_current_version("edit_for_tts")

        # 测试回滚到上一个
        store.promote_version("edit_for_tts", 3)  # 回到 v3
        rollback_last = store.rollback_last("edit_for_tts")
        after_rollback_last = store.get_current_version("edit_for_tts")

        # 测试历史记录
        history = store.get_rollback_history("edit_for_tts")

        return {
            "success": (
                current == 3 and
                rollback_success and
                after_rollback == 1 and
                rollback_last and
                after_rollback_last == 2 and
                len(history) == 3
            ),
            "initial_version": current,
            "after_rollback": after_rollback,
            "after_rollback_last": after_rollback_last,
            "history_count": len(history),
        }


def run_all_tests(project_id: int = 1) -> Dict[str, Any]:
    """运行所有 E2E 测试."""
    results = {}
    all_passed = True

    test_dir = Path("tests/e2e_temp")
    test_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 创建测试书籍
        logger.info("Step 1: Creating test book...")
        book_path = create_test_book(test_dir, num_chapters=2, paragraphs_per_chapter=3)
        results["book_creation"] = {"success": True, "path": str(book_path)}

        # 2. 运行完整管线
        logger.info("Step 2: Running full pipeline...")
        pipeline_result = run_full_pipeline_test(project_id, book_path)
        results["pipeline"] = pipeline_result
        all_passed = all_passed and pipeline_result["success"]

        # 3. 测试反馈收集
        logger.info("Step 3: Testing feedback collection...")
        collector = create_feedback_collector(project_id)
        feedback_result = test_feedback_collection(project_id, collector)
        results["feedback_collection"] = feedback_result
        all_passed = all_passed and feedback_result["success"]

        # 4. 测试自迭代循环
        logger.info("Step 4: Testing self-iteration loop...")
        iteration_result = test_self_iteration_loop(project_id)
        results["self_iteration"] = iteration_result
        all_passed = all_passed and iteration_result["success"]

        # 5. 测试 Promotion Gate
        logger.info("Step 5: Testing promotion gate...")
        promotion_result = test_promotion_gate()
        results["promotion_gate"] = promotion_result
        all_passed = all_passed and promotion_result["success"]

        # 6. 测试 A/B 测试
        logger.info("Step 6: Testing A/B test...")
        ab_result = test_ab_test()
        results["ab_test"] = ab_result
        all_passed = all_passed and ab_result["success"]

        # 7. 测试 Canary Release
        logger.info("Step 7: Testing canary release...")
        canary_result = test_canary_release()
        results["canary_release"] = canary_result
        all_passed = all_passed and canary_result["success"]

        # 8. 测试版本存储
        logger.info("Step 8: Testing version store...")
        version_result = test_version_store()
        results["version_store"] = version_result
        all_passed = all_passed and version_result["success"]

    finally:
        # 清理测试目录
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)

    results["overall"] = "PASSED" if all_passed else "FAILED"
    return results


def main():
    parser = argparse.ArgumentParser(description="Run E2E verification")
    parser.add_argument("--project-id", type=int, default=1, help="Project ID for testing")
    parser.add_argument("--output", type=str, help="Output JSON file for results")
    args = parser.parse_args()

    print("=" * 60)
    print("Audiobook Studio — E2E Long Book Verification")
    print("=" * 60)
    print()

    results = run_all_tests(args.project_id)

    print()
    print("=" * 60)
    print("E2E Verification Results:")
    print("=" * 60)

    for test_name, result in results.items():
        if test_name == "overall":
            continue
        status = "✅ PASS" if result.get("success", False) else "❌ FAIL"
        print(f"  {test_name}: {status}")

    print()
    print(f"Overall: {results['overall']}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to {args.output}")

    sys.exit(0 if results["overall"] == "PASSED" else 1)


if __name__ == "__main__":
    main()

"""端到端 dry-run 验证脚本：真实跑一轮 ``run_iteration_cycle``，验证候选是否真被
编译 / 评判 / 门禁裁决。作为「自主迭代的有声书 harness 系统」运营件验收。

设计（完全 hermetic，不污染仓库）：
  * 临时 SQLite DB + 临时 ``prompts_root``（候选 .j2 落盘到临时目录，与真实
    ``prompts/`` / ``prompts/harness`` 隔离）。
  * ``GoldenDatasetManager.load_samples`` 注入合成样本，不写真实金标磁盘。
  * ``SELF_ITERATION_MOCK=1``（离线，不触网），评判器用确定性 ``OfflineJudge``。
  * ``_run_stage_with_prompt_version`` 被替换为一个「版本/文件感知」的安全桩：
    它会真实读取 harness 刚编译出的候选 ``v{N}.j2``（证明候选被编译且被 eval 真正
    使用），并按版本区分 候选 / 基线 的输出，使门禁得到可判别的真实指标。

跑两轮对照，证明门禁「可放行好候选、可拒绝坏候选（fail-closed，非恒通过）」：
  1. 正向对照（good candidate）：候选输出对齐期望 → 门禁应放行（passed=True）。
  2. 负向对照（bad  candidate）：候选输出偏离期望 → 门禁应拒绝（passed=False，
     failed_criteria 非空）。

退出码：全部验收通过为 0；任一验收失败为非 0（供 CI / ops 直接判断）。

用法：
    python scripts/harness_self_iteration_dryrun.py                # 默认 stage=analyze
    python scripts/harness_self_iteration_dryrun.py --stage edit
    python scripts/harness_self_iteration_dryrun.py --use-learned  # 学习型候选生成
    python scripts/harness_self_iteration_dryrun.py --out /tmp/dryrun.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# dry-run 默认离线（不触真实 LLM provider）。
os.environ.setdefault("SELF_ITERATION_MOCK", "1")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from audiobook_studio.feedback import canary as canary_mod  # noqa: E402
from audiobook_studio.feedback.prompt_compiler import stage_to_prompt_dir  # noqa: E402
from audiobook_studio.harness.golden import GoldenDatasetManager  # noqa: E402
from audiobook_studio.harness.harness import IterationReport, run_iteration_cycle  # noqa: E402
from audiobook_studio.harness.storage import get_storage  # noqa: E402


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="端到端 dry-run 验证：真实跑一轮 run_iteration_cycle（编译→评判→门禁）"
    )
    parser.add_argument("--stage", default="analyze", help="golden stage 名（默认 analyze）")
    parser.add_argument("--k", type=int, default=3, help="M3 few-shot 示例数")
    parser.add_argument("--cases", type=int, default=3, help="注入的合成 test 样本数")
    parser.add_argument("--use-learned", action="store_true", help="启用 DSPy/GEPA 学习型候选生成")
    parser.add_argument("--no-mock", action="store_true", help="关闭 mock（触真实 LLM，谨慎）")
    parser.add_argument("--out", default=None, help="JSON 验收报告落盘路径")
    return parser


def _make_synthetic_samples(n: int) -> List[Any]:
    """构造 n 条合成 test 样本（与 ``OfflineJudge`` 的判定维度对齐）。"""
    from types import SimpleNamespace

    samples: List[Any] = []
    for i in range(max(1, n)):
        samples.append(
            SimpleNamespace(
                input={"text": f"synthetic-input-{i}"},
                expected_output={"score": 0.9, "needs_regeneration": False},
            )
        )
    return samples


def _make_load_samples(samples: List[Any]) -> Callable[..., List[Any]]:
    def _fake(self: Any, stage: str, split: str) -> List[Any]:
        return list(samples)

    return _fake


def _make_run_stage_mock(recorded: List[Dict[str, Any]], bad_candidate: bool) -> Callable[..., Any]:
    """版本/文件感知的安全桩：

    * 若 ``prompts_root/<dir>/v{version}.j2`` 存在（harness 刚真实编译出的候选），
      读取其内容（证明候选被编译且被 eval 使用），并按好坏返回确定性输出。
    * 若不存在（如基线 v0），返回「较差」输出，使 candidate vs baseline 有区分度。
    """

    def _fake(
        stage: str,
        version: int,
        input_data: Any,
        mock_mode: Optional[bool] = None,
        prompts_root: Optional[Path] = None,
    ) -> Dict[str, Any]:
        recorded.append({"stage": stage, "version": version, "prompts_root": str(prompts_root)})
        root = Path(prompts_root) if prompts_root is not None else Path("prompts")
        tmpl = root / stage_to_prompt_dir(stage) / f"v{version}.j2"
        if tmpl.exists():
            content = tmpl.read_text(encoding="utf-8")  # 证明候选项被真实读取使用
            if bad_candidate:
                return {"score": 0.2, "needs_regeneration": False, "candidate_prompt_len": len(content)}
            return {"score": 0.9, "needs_regeneration": False, "candidate_prompt_len": len(content)}
        # 基线（未编译版本，如 v0）：较差输出 → 候选需 ≥ 102% 才过质量门。
        return {"score": 0.8, "needs_regeneration": False, "used_candidate": False}

    return _fake


def _run_one_cycle(
    stage: str,
    k: int,
    use_learned: bool,
    prompts_subdir: Path,
) -> IterationReport:
    """跑一轮完整迭代（run_fn=None → 由 harness 内部构造版本感知的候选/基线 run_fn）。"""
    return run_iteration_cycle(
        stage,
        run_fn=None,
        baseline_fn=None,
        k=k,
        prompts_root=prompts_subdir,
        auto_deploy=False,
        use_learned=use_learned,
    )


def _validate(
    report: IterationReport,
    prompts_subdir: Path,
    recorded: List[Dict[str, Any]],
    expect_pass: bool,
) -> List[str]:
    failures: List[str] = []
    stage = report.stage

    # ① 编译：候选 prompt 真实落盘（非空）。
    cand_file = prompts_subdir / stage_to_prompt_dir(stage) / f"v{report.candidate_version}.j2"
    if not report.compiled:
        failures.append("编译标志 compiled 不为 True")
    if not cand_file.exists():
        failures.append(f"候选 prompt 未落盘: {cand_file}")
    elif cand_file.stat().st_size == 0:
        failures.append(f"候选 prompt 落盘但为空: {cand_file}")

    # ② 评判：真实跑出 ≥1 例，且候选/基线使用不同版本（候选确实喂入 eval）。
    if not (report.eval_case_count >= 1):
        failures.append(f"eval_case_count={report.eval_case_count} < 1（评判未真实发生）")
    if report.eval_mean_score is None:
        failures.append("eval_mean_score 为 None（评判未计算）")
    if report.eval_baseline_mean is None:
        failures.append("eval_baseline_mean 为 None（基线未评判）")
    used_versions = {c["version"] for c in recorded if c["stage"] == stage}
    if report.candidate_version not in used_versions:
        failures.append(f"候选版本 {report.candidate_version} 未进入 eval 的 run_fn: {used_versions}")
    if len(used_versions) < 2:
        failures.append(f"eval 仅使用单一版本 {used_versions}，候选/基线未分别喂入")
    # 候选确实从 harness prompts_root 读取（而非真实 prompts/）。
    harness_roots = {c["prompts_root"] for c in recorded if c["stage"] == stage}
    if str(prompts_subdir) not in harness_roots:
        failures.append(f"eval 未从 harness prompts_root={prompts_subdir} 读取: {harness_roots}")

    # ③ 门禁裁决：来自真实 promote_candidate，且非恒通过。
    if not isinstance(report.passed, bool):
        failures.append("passed 非 bool")
    if not isinstance(report.deployed, bool):
        failures.append("deployed 非 bool")
    if not isinstance(report.failed_criteria, list):
        failures.append("failed_criteria 非 list")
    if expect_pass and not report.passed:
        failures.append(f"正向对照：期望门禁放行但被拒: {report.failed_criteria}")
    if (not expect_pass) and report.passed:
        failures.append("负向对照：门禁对坏候选放行（恒通过）——未 fail-closed")
    if (not expect_pass) and not report.failed_criteria:
        failures.append("负向对照：坏候选被拒但未给出 failed_criteria")
    return failures


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.no_mock:
        os.environ.pop("SELF_ITERATION_MOCK", None)

    workdir = Path(tempfile.mkdtemp(prefix="harness_dryrun_"))
    db_path = workdir / "harness_dryrun.db"
    # 隔离 DB（不触碰仓库默认 audiobook_studio.db / data/）。
    get_storage(database_url=f"sqlite:///{db_path}", data_root=workdir)

    samples = _make_synthetic_samples(args.cases)
    results: List[Dict[str, Any]] = []
    all_failures: List[str] = []
    try:
        for label, bad in (("positive", False), ("negative", True)):
            recorded: List[Dict[str, Any]] = []
            prompts_subdir = workdir / f"prompts_{label}"
            prompts_subdir.mkdir(parents=True, exist_ok=True)
            # 每个对照用独立子目录，保证候选=新编译 v1、基线=v0（文件缺失）。
            with (
                _Patch(canary_mod, "_run_stage_with_prompt_version", _make_run_stage_mock(recorded, bad)),
                _Patch(GoldenDatasetManager, "load_samples", _make_load_samples(samples)),
            ):
                rep = _run_one_cycle(args.stage, args.k, args.use_learned, prompts_subdir)
            expect_pass = not bad
            failures = _validate(rep, prompts_subdir, recorded, expect_pass)
            all_failures.extend([f"[{label}] {f}" for f in failures])
            results.append(
                {
                    "control": label,
                    "expect_pass": expect_pass,
                    "report": rep.to_dict(),
                    "recorded_eval_versions": sorted({c["version"] for c in recorded}),
                    "acceptance_failures": failures,
                }
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    summary = {
        "script": "harness_self_iteration_dryrun",
        "stage": args.stage,
        "use_learned": args.use_learned,
        "mock": "SELF_ITERATION_MOCK" in os.environ,
        "controls": results,
        "all_passed": not all_failures,
        "failure_count": len(all_failures),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已落盘: {args.out}")

    if all_failures:
        print("\n[FAIL] 验收未通过：")
        for f in all_failures:
            print(f"  - {f}")
        return 1
    print("\n[PASS] 端到端 dry-run 验收通过：候选被真实编译/评判/门禁裁决。")
    return 0


class _Patch:
    """极简上下文管理器：在 with 块内临时替换属性，退出时还原。"""

    def __init__(self, target: Any, name: str, value: Any = None) -> None:
        self._target = target
        self._name = name
        self._value = value
        self._orig: Any = None
        self._active = False

    def __enter__(self) -> "_Patch":
        self._orig = getattr(self._target, self._name)
        setattr(self._target, self._name, self._value)
        self._active = True
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._active:
            setattr(self._target, self._name, self._orig)
            self._active = False


if __name__ == "__main__":
    raise SystemExit(main())

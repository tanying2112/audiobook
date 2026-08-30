"""自主调度层：把 ``run_iteration_cycle`` 接进后台 worker / 定时调度。

这是「可自我迭代」闭环的驱动端：一个守护线程周期性地对各 stage 跑完整迭代
（编译→评判→晋升→部署），使 harness 在无人干预下持续进化。

默认关闭，以防在测试/生产误触。真实运行期由
``pipeline.sop_reflection.SOPBackgroundThread`` 在 ``start()`` 时（当
``AUDIOBOOK_HARNESS_AUTONOMOUS=1``）拉起一个独立的 ``HarnessScheduler`` 守护线程，
该线程以自身 ``interval``（默认 3600s）周期性调用 ``HarnessScheduler.tick()`` 驱动
``run_iteration_cycle``，与反思链路解耦、互不阻塞。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认参与自主迭代的 stage（与 feedback 闭环的 stage 对齐）。
DEFAULT_STAGES: List[str] = [
    "extract",
    "analyze",
    "annotate",
    "edit",
    "judge",
    "route",
    "translate",
]


class HarnessScheduler:
    """后台调度器：周期性驱动 harness 自我迭代闭环。"""

    def __init__(
        self,
        stages: Optional[List[str]] = None,
        run_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        *,
        interval: float = 3600.0,
        auto_deploy: bool = False,
        judge: Optional[Any] = None,
        use_learned: bool = False,
    ) -> None:
        self.stages = list(stages or DEFAULT_STAGES)
        self.run_fn = run_fn
        self.baseline_fn = baseline_fn
        self.interval = interval
        self.auto_deploy = auto_deploy
        self.judge = judge
        # 学习型候选生成开关：True 时在每轮迭代用 DSPy/GEPA 反思变异覆盖候选 prompt。
        # 默认关，避免在无训练样本/无本地 LLM 时产生无效变异；由环境变量
        # AUDIOBOOK_HARNESS_USE_LEARNED=1 或显式传入开启。
        self.use_learned = use_learned
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.last_run: Dict[str, float] = {}
        self.last_report: Dict[str, Any] = {}

    # ── 单轮驱动（可被测试直接调用，无需起线程）──────────────────────────────
    def tick(
        self,
        stages: Optional[List[str]] = None,
        *,
        use_learned: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """对配置的 stage 各跑一轮 ``run_iteration_cycle``，返回每 stage 的简要报告。

        任一 stage 失败不影响其余 stage；异常被吞并记录，保证调度循环不中断。
        """
        from .harness import run_iteration_cycle, run_stage

        stages = stages or self.stages
        # 参数级覆盖优先于实例级开关。
        effective_learned = self.use_learned if use_learned is None else use_learned
        report: Dict[str, Any] = {}
        for stage in stages:
            try:
                # 未注入 run_fn 时回退到真实 stage 运行器（run_stage 跑 live v1），
                # 使生产自主迭代 worker 真正执行 stage，而非空转置 0 分。
                run_fn = self.run_fn or (lambda inp, _s=stage: run_stage(_s, inp))
                baseline_fn = self.baseline_fn or (lambda inp, _s=stage: run_stage(_s, inp))
                rep = run_iteration_cycle(
                    stage,
                    run_fn=run_fn,
                    baseline_fn=baseline_fn,
                    auto_deploy=self.auto_deploy,
                    judge=self.judge,
                    use_learned=effective_learned,
                )
                report[stage] = {
                    "compiled": rep.compiled,
                    "candidate_version": rep.candidate_version,
                    "passed": rep.passed,
                    "deployed": rep.deployed,
                    "eval_mean_score": rep.eval_mean_score,
                    "learned": effective_learned,
                }
                self.last_run[stage] = time.time()
            except Exception as exc:  # noqa: BLE001
                logger.error("[HarnessScheduler] stage %s 迭代失败: %s", stage, exc)
                report[stage] = {"error": str(exc)}
        self.last_report = report
        return report

    # ── 后台线程 ────────────────────────────────────────────────────────────
    def start(self) -> None:
        """启动后台调度线程（守护线程，主进程退出即终止）。"""
        if self._thread and self._thread.is_alive():
            logger.warning("[HarnessScheduler] 调度线程已在运行")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="HarnessScheduler", daemon=True)
        self._thread.start()
        logger.info("[HarnessScheduler] 已启动（interval=%.0fs, stages=%s）", self.interval, self.stages)

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台调度线程。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("[HarnessScheduler] 已停止")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                logger.error("[HarnessScheduler] 调度循环异常: %s", exc)
            # 以可中断方式休眠，便于 stop() 立即生效
            self._stop.wait(self.interval)


def create_harness_scheduler(
    stages: Optional[List[str]] = None,
    run_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    *,
    interval: float = 3600.0,
    auto_deploy: bool = False,
    judge: Optional[Any] = None,
    use_learned: bool = False,
) -> HarnessScheduler:
    """便捷工厂：返回一个配置好的 ``HarnessScheduler``。"""
    return HarnessScheduler(
        stages=stages,
        run_fn=run_fn,
        baseline_fn=baseline_fn,
        interval=interval,
        auto_deploy=auto_deploy,
        judge=judge,
        use_learned=use_learned,
    )

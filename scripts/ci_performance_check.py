#!/usr/bin/env python3
"""
Audiobook Studio — CI性能检查脚本
========================================
在CI中运行性能基准测试并检查是否有显著退化。
设计为在GitHub Actions工作流中使用。
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def run_benchmark(script_path: str, mock: bool = True) -> Optional[Dict[str, float]]:
    """运行基准脚本并返回结果。"""
    try:
        cmd = [sys.executable, script_path, "--mock"]

        # 只在不输出到文件时捕获输出
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60  # 60秒超时
        )

        if result.returncode != 0:
            print(f"警告: 基准脚本 {script_path} 失败:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            return None

        # 解析输出以提取基准数据
        # 为了简单起见，我们假设脚本能够生成JSON输出
        # 但实际上我们的当前脚本不会这样做
        # 所以我们需要修改它们或者以其他方式解析

        # 作为临时解决方案，让我们运行带有输出文件选项的脚本
        output_file = f"/tmp/baseline_{os.path.basename(script_path)}.json"
        cmd_with_output = [
            sys.executable,
            script_path,
            "--mock",
            "--output",
            output_file,
        ]

        result = subprocess.run(
            cmd_with_output, capture_output=True, text=True, timeout=60
        )

        if result.returncode != 0:
            print(f"警告: 基准脚本 {script_path} 带输出失败:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            return None

        # 读取生成的基准文件
        if os.path.exists(output_file):
            with open(output_file, "r") as f:
                data = json.load(f)
                # 根据我们的基准脚本结构提取适当的数据
                if "latency_ms" in data:
                    return data["latency_ms"]
                elif "cost_usd" in data:
                    return data["cost_usd"]
                else:
                    # 尝试找到任何数值数据
                    for key, value in data.items():
                        if isinstance(value, dict) and all(
                            isinstance(v, (int, float)) for v in value.values()
                        ):
                            return value
                    return {}
        else:
            print(f"警告: 基准文件 {output_file} 未被生成")
            return None

    except subprocess.TimeoutExpired:
        print(f"错误: 基准脚本 {script_path} 超时")
        return None
    except Exception as e:
        print(f"错误: 运行基准脚本 {script_path} 时发生异常: {e}")
        return None


def load_baseline(baseline_path: str) -> Optional[Dict[str, float]]:
    """从文件加载基准数据。"""
    try:
        if os.path.exists(baseline_path):
            with open(baseline_path, "r") as f:
                data = json.load(f)
                # 根据我们的基准脚本结构提取适当的数据
                if "latency_ms" in data:
                    return data["latency_ms"]
                elif "cost_usd" in data:
                    return data["cost_usd"]
                else:
                    # 尝试找到任何数值数据
                    for key, value in data.items():
                        if isinstance(value, dict) and all(
                            isinstance(v, (int, float)) for v in value.values()
                        ):
                            return value
                    return {}
        else:
            print(f"信息: 基准文件 {baseline_path} 不存在，将跳过比较")
            return None
    except Exception as e:
        print(f"警告: 加载基准文件 {baseline_path} 失败: {e}")
        return None


def compare_performance(
    current: Dict[str, float], baseline: Dict[str, float], threshold: float = 110.0
) -> Tuple[bool, List[Dict]]:
    """比较当前性能与基准性能。

    返回:
        (是否通过, 性能问题列表)
    """
    if not baseline:
        # 如果没有基准，则认为通过（但会警告）
        return True, []

    issues = []
    passed = True

    for stage, current_value in current.items():
        if stage in baseline:
            baseline_value = baseline[stage]
            if baseline_value > 0:
                ratio = (current_value / baseline_value) * 100
                if ratio > threshold:
                    passed = False
                    issues.append(
                        {
                            "stage": stage,
                            "current_value": round(current_value, 6),
                            "baseline_value": round(baseline_value, 6),
                            "ratio_percent": round(ratio, 2),
                            "threshold_percent": threshold,
                            "status": "FAILED" if ratio > threshold else "PASSED",
                        }
                    )

    return passed, issues


def main():
    parser = argparse.ArgumentParser(description="Audiobook Studio CI性能检查")
    parser.add_argument(
        "--latency-script", default="scripts/bench_latency.py", help="延迟基准脚本路径"
    )
    parser.add_argument(
        "--cost-script", default="scripts/bench_cost.py", help="成本基准脚本路径"
    )
    parser.add_argument("--baselines-dir", default="baselines", help="基准文件目录")
    parser.add_argument(
        "--threshold", type=float, default=110.0, help="性能退化阈值百分比"
    )
    parser.add_argument(
        "--fail-on-error", action="store_true", help="如果任何基准运行失败则退出错误"
    )

    args = parser.parse_args()

    print("=== Audiobook Studio CI性能检查 ===")
    print(f"性能退化阈值: {args.threshold}%")
    print(f"基准目录: {args.baselines_dir}")
    print()

    # 运行延迟基准
    print("正在运行延迟基准测试...")
    latency_current = run_benchmark(args.latency_script, mock=True)
    if latency_current is None:
        if args.fail_on_error:
            print("错误: 延迟基准测试失败")
            sys.exit(1)
        else:
            print("警告: 延迟基准测试失败，跳过")
            latency_current = {}
    else:
        print(f"延迟基准测试完成，测量了 {len(latency_current)} 个阶段")

    # 运行成本基准
    print("正在运行成本基准测试...")
    cost_current = run_benchmark(args.cost_script, mock=True)
    if cost_current is None:
        if args.fail_on_error:
            print("错误: 成本基准测试失败")
            sys.exit(1)
        else:
            print("警告: 成本基准测试失败，跳过")
            cost_current = {}
    else:
        print(f"成本基准测试完成，测量了 {len(cost_current)} 个阶段")

    print()

    # 加载基准数据并进行比较
    all_passed = True

    # 检查延迟基准
    if latency_current:
        latency_baseline_path = os.path.join(
            args.baselines_dir, "latency_baseline.json"
        )
        latency_baseline = load_baseline(latency_baseline_path)
        if latency_baseline:
            print("正在比较延迟性能...")
            latency_passed, latency_issues = compare_performance(
                latency_current, latency_baseline, args.threshold
            )
            if not latency_passed:
                all_passed = False
                print("🚨 延迟性能退化检测:")
                for issue in latency_issues:
                    status_emoji = "❌" if issue["status"] == "FAILED" else "✅"
                    print(
                        f"  {status_emoji} {issue['stage']}: "
                        f"{issue['current_value']} "
                        f"(基准: {issue['baseline_value']}, "
                        f"比率: {issue['ratio_percent']}% "
                        f"(阈值: {issue['threshold_percent']}%)"
                    )
            else:
                print("✅ 延迟性能在可接受范围内")
        else:
            print("信息: 未找到延迟基准，仅保存当前测量值作为基准")
            # 保存当前测量值作为基准用于未来比较
            baseline_data = {
                "timestamp": __import__("time").time(),
                "latency_ms": latency_current,
            }
            os.makedirs(args.baselines_dir, exist_ok=True)
            with open(
                os.path.join(args.baselines_dir, "latency_baseline.json"), "w"
            ) as f:
                json.dump(baseline_data, f, indent=2)

    print()

    # 检查成本基准
    if cost_current:
        cost_baseline_path = os.path.join(args.baselines_dir, "cost_baseline.json")
        cost_baseline = load_baseline(cost_baseline_path)
        if cost_baseline:
            print("正在比较成本性能...")
            cost_passed, cost_issues = compare_performance(
                cost_current, cost_baseline, args.threshold
            )
            if not cost_passed:
                all_passed = False
                print("🚨 成本性能退化检测:")
                for issue in cost_issues:
                    status_emoji = "❌" if issue["status"] == "FAILED" else "✅"
                    print(
                        f"  {status_emoji} {issue['stage']}: "
                        f"${issue['current_value']} "
                        f"(基准: ${issue['baseline_value']}, "
                        f"比率: {issue['ratio_percent']}% "
                        f"(阈值: {issue['threshold_percent']}%)"
                    )
            else:
                print("✅ 成本性能在可接受范围内")
        else:
            print("信息: 未找到成本基准，仅保存当前测量值作为基准")
            # 保存当前测量值作为基准用于未来比较
            baseline_data = {
                "timestamp": __import__("time").time(),
                "cost_usd": cost_current,
            }
            os.makedirs(args.baselines_dir, exist_ok=True)
            with open(os.path.join(args.baselines_dir, "cost_baseline.json"), "w") as f:
                json.dump(baseline_data, f, indent=2)

    print()
    if all_passed:
        print("✅ 所有性能检查通过")
        sys.exit(0)
    else:
        print("❌ 性能检查失败 - 检测到退化")
        sys.exit(1)


if __name__ == "__main__":
    main()

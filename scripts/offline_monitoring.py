#!/usr/bin/env python3
"""
Audiobook Studio — 离线监控降级机制
========================================
当外部监控服务不可用时，自动降级到本地文件日志。
支持 try/except 机制，确保监控数据不丢失。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class OfflineMonitor:
    """离线监控降级管理器"""

    def __init__(self, offline_dir: str = "./logs/offline"):
        self.offline_dir = Path(offline_dir)
        self.offline_dir.mkdir(parents=True, exist_ok=True)

    def log_performance(self, metrics: Dict[str, Any]) -> bool:
        """
        记录性能指标，如果外部服务不可用则降级到本地文件

        Args:
            metrics: 性能指标字典

        Returns:
            bool: 是否成功记录（无论是外部还是离线）
        """
        # 添加时间戳
        metrics_with_timestamp = {
            **metrics,
            "timestamp": datetime.now().isoformat(),
            "logged_at": datetime.now().isoformat()
        }

        # 尝试发送到外部监控服务（这里用 Langfuse 为例）
        try:
            return self._send_to_external(metrics_with_timestamp)
        except Exception as e:
            print(f"警告: 外部监控服务不可用，降级到离线存储: {e}")
            return self._save_to_offline(metrics_with_timestamp)

    def _send_to_external(self, metrics: Dict[str, Any]) -> bool:
        """发送到外部监控服务（模拟）"""
        # 在实际实现中，这里会发送到 Langfuse、Prometheus 等
        # 为演示目的，我们随机模拟成功/失败
        import random
        if random.random() < 0.7:  # 70% 的时间成功
            print(f"✅ 性能数据已发送到外部监控: {metrics.get('stage', 'unknown')}")
            return True
        else:
            raise ConnectionError("外部监控服务暂时不可用")

    def _save_to_offline(self, metrics: Dict[str, Any]) -> bool:
        """保存到离线文件"""
        try:
            # 按日期创建文件
            date_str = datetime.now().strftime("%Y-%m-%d")
            offline_file = self.offline_dir / f"performance_{date_str}.jsonl"

            # 以 JSONL 格式追加写入
            with open(offline_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(metrics, ensure_ascii=False) + "\n")

            print(f"💾 性能数据已保存到离线存储: {offline_file}")
            return True
        except Exception as e:
            print(f"错误: 无法保存到离线存储: {e}")
            return False

    def sync_offline_data(self) -> int:
        """
        同步离线数据到外部服务（当服务恢复时调用）

        Returns:
            int: 成功同步的记录数
        """
        synced_count = 0
        offline_files = list(self.offline_dir.glob("performance_*.jsonl"))

        for offline_file in offline_files:
            try:
                with open(offline_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                if not lines:
                    continue

                # 尝试发送每条记录
                remaining_lines = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        metrics = json.loads(line)
                        if self._send_to_external(metrics):
                            synced_count += 1
                        else:
                            remaining_lines.append(line)
                    except Exception:
                        # 如果解析失败，保留该行以防数据丢失
                        remaining_lines.append(line)

                # 重写文件，只保留未同步的记录
                if remaining_lines:
                    with open(offline_file, "w", encoding="utf-8") as f:
                        for line in remaining_lines:
                            f.write(line + "\n")
                else:
                    # 所有记录都已同步，删除文件
                    offline_file.unlink()

            except Exception as e:
                print(f"错误: 同步离线文件 {offline_file} 失败: {e}")

        if synced_count > 0:
            print(f"🔄 已同步 {synced_count} 条离线监控数据到外部服务")

        return synced_count


def main():
    """主函数 - 演示离线监控降级机制"""
    print("=== Audiobook Studio 离线监控降级演示 ===")

    monitor = OfflineMonitor()

    # 模拟一些性能数据
    test_metrics = [
        {
            "stage": "extract",
            "latency_ms": 25.3,
            "cost_usd": 0.001,
            "success": True,
            "provider": "mock"
        },
        {
            "stage": "synthesize",
            "latency_ms": 450.2,
            "cost_usd": 0.009,
            "success": True,
            "provider": "kokoro"
        },
        {
            "stage": "quality_check",
            "latency_ms": 890.1,
            "cost_usd": 0.005,
            "success": False,
            "error": "模型响应超时",
            "provider": "llm_judge"
        }
    ]

    print("\n正在记录性能指标...")
    for metrics in test_metrics:
        success = monitor.log_performance(metrics)
        print(f"  {metrics['stage']}: {'✅ 成功' if success else '❌ 失败'}")

    print("\n尝试同步离线数据...")
    synced = monitor.sync_offline_data()
    print(f"同步完成，处理了 {synced} 条记录")

    print("\n✅ 离线监控降级机制演示完成")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
本地 Agent 日志消费端：即读即删，零驻留。
文件名: read_logs.py

⚠️ 凭据安全说明 (2026-07-18 docs/AUDIT_REPORT_v3.md P0-1):
    历史版本曾将 Upstash Redis host/AUTH 硬编码为本文件默认值并随 commit
    57e4759 提交到 origin/main。该默认值已撤销。现在必须通过环境变量提供
    REDIS_HOST / REDIS_PORT / REDIS_AUTH，缺失时本脚本立即退出 2 以避免
    静默连接到错误实例。详见 docs/RUNBOOK_rotate_credentials.md。
"""

import os
import sys
import time


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(
            f"❌ 环境变量 {name} 未设置。请通过 .env 注入凭据后重试。\n"
            f"   参见 docs/RUNBOOK_rotate_credentials.md（P0-1 凭据治理）。",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


REDIS_HOST = _require_env("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_AUTH = _require_env("REDIS_AUTH")

try:
    import redis

    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_AUTH or None,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    # 主动 ping 一下，尽早暴露配置错误
    r.ping()
except Exception as e:
    print(f"❌ 无法初始化 Redis 客户端: {e}", file=sys.stderr)
    sys.exit(1)

print(f"🚀 Agent 已连接到 {REDIS_HOST}:{REDIS_PORT}，开始实时消费 worker:logs...\n", flush=True)

while True:
    try:
        # 阻塞式弹出（原子操作：消费即刻从 Redis 内存中抹除）
        result = r.blpop("worker:logs", timeout=5)
        if result:
            _, log_line = result
            print(log_line, flush=True)

            # 🔍 Agent 自动化诊断埋点
            if "CRITICAL KERNEL ABORT" in log_line:
                print("\n🚨 [Agent 自动诊断] 检测到 Kaggle 容器崩溃，开始自动分析代码状态...", flush=True)
            if "核心模型下载并校验成功" in log_line:
                print("\n✨ [Agent 通知] 语音模型就位，双卡 T4 生产管线已成功激活！", flush=True)
        else:
            # 队列为空时稍微休眠，降低 CPU 负载
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n👋 停止日志消费，优雅退出。")
        sys.exit(0)
    except Exception as e:
        print(f"⚠️ Redis 连接抖动 ({e})，3 秒后尝试重新握手...")
        time.sleep(3)

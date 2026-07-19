#!/usr/bin/env python3
"""
本地 Agent 日志消费端：即读即删，零驻留。
文件名: read_logs.py
"""

import os
import redis
import time
import sys

# 从环境变量读取，若无则使用你的 Upstash 默认实例
REDIS_HOST = os.getenv("REDIS_HOST", "casual-sawfish-86152.upstash.io")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_AUTH = os.getenv("REDIS_AUTH", "gQAAAAAAAVCIAAIgcDI2Njk2ZDcyMmZkNTU0N2FmYTIxZDk4ZDY4MTBjOGM4ZA")

try:
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_AUTH or None,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
except Exception as e:
    print(f"❌ 无法初始化 Redis 客户端: {e}")
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
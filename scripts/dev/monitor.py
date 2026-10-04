#!/usr/bin/env python3
# filename: monitor.py
# 本地心跳监控：5 分钟巡检云端 GPU 存活，Telegram 报警

import json
import os
import sys
import time

import redis
import requests

REDIS_HOST = os.getenv("REDIS_HOST", "your-upstash.redis.com")
REDIS_AUTH = os.getenv("REDIS_AUTH", "your_password")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

WORKERS = ["kaggle-1", "lightning-1", "modal-t4-serverless", "aistudio-1"]

r = redis.Redis(host=REDIS_HOST, port=6379, password=REDIS_AUTH, decode_responses=True)


def send_telegram(text: str) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ 未配置 TG_BOT_TOKEN / TG_CHAT_ID，跳过报警推送")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print(f"⚠️ Telegram 推送失败: {e}", file=sys.stderr)


def check_heartbeats() -> None:
    active = []
    for w in WORKERS:
        key = f"worker:heartbeat:{w}"
        if r.exists(key):
            active.append(w)
            hb = r.get(key)
            try:
                data = json.loads(hb)
                idle = time.time() - data.get("ts", 0)
                if idle > 300:
                    print(f"⚠️ {w} 心跳过期 ({idle:.0f}s 前)")
            except Exception:
                pass

    pending = r.llen("tts:tasks")

    print(f"[{time.strftime('%H:%M:%S')}] 存活节点: {active or '无'} | 积压任务: {pending}")

    if not active and pending > 0:
        msg = f"🚨 警报：全线云端 GPU 节点全部挂机！积压任务 {pending} 条无法消费！"
        print(msg)
        send_telegram(msg)


if __name__ == "__main__":
    print("🔍 启动心跳监控 (5 分钟轮询)...")
    while True:
        try:
            check_heartbeats()
        except Exception as e:
            print(f"⚠️ 监控循环异常: {e}", file=sys.stderr)
        time.sleep(300)

import json
import os
import subprocess
import sys
import time

import modal
import redis

# 1. 定义云端隔离容器环境与依赖
worker_image = (
    modal.Image.debian_slim().pip_install("redis", "boto3")
    # 在此处追加您的 VoxCPM2 框架及 Torch 的依赖安装，例如：
    # .run_commands("pip install torch --index-url https://download.pytorch.org/whl/cu118")
)

app = modal.App("dark-night-audio-factory-worker")


def get_gpu_memory_used() -> int:
    """解析 nvidia-smi 获取当前显存占用 (MB)"""
    try:
        cmd = "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits"
        res = subprocess.check_output(cmd, shell=True).decode().strip()
        return int(res)
    except Exception:
        return 0


@app.function(
    image=worker_image,
    # 绑定 Modal 后台配置的 Secrets 环境变量
    secrets=[modal.Secret.from_name("upstash-redis-env"), modal.Secret.from_name("cloudflare-r2-env")],
    gpu="T4",
    timeout=32400,  # 最大对齐 9 小时生命周期
)  # type: ignore[misc]
def run_modal_consumer() -> None:
    WORKER_ID = "modal-t4-serverless"
    HEARTBEAT_KEY = f"worker:heartbeat:{WORKER_ID}"

    r = redis.Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ.get("REDIS_PORT", 6379)),
        password=os.environ["REDIS_AUTH"],
        decode_responses=True,
    )

    print("⚡ Modal Serverless GPU 节点上线。正在接入统一抢单网络...")

    # 针对 Serverless 优化的快速熔断策略
    empty_counter = 0
    max_empty_allow = 2  # 连续两次 BLPOP 超时无任务就直接自毁释放资源

    while True:
        # 心跳上报：带上显存深度与队列深度，供 Grafana/面板 抓取
        try:
            r.setex(
                HEARTBEAT_KEY,
                300,
                json.dumps(
                    {
                        "ts": time.time(),
                        "status": "processing" if empty_counter == 0 else "idle",
                        "gpu_mem_mb": get_gpu_memory_used(),
                        "queue_depth": r.llen("tts:tasks"),
                    }
                ),
            )
        except Exception as e:
            print(f"⚠️ 心跳同步失败: {e}", file=sys.stderr)

        # 阻塞长轮询 300 秒
        task_data = r.blpop("tts:tasks", timeout=300)

        if task_data:
            empty_counter = 0
            queue_name, payload = task_data
            task = json.loads(payload)

            # 抢到单后，立刻固化当刻的 Key，防止跨月漂移
            current_month_key = f"modal:usage:{time.strftime('%Y-%m')}"
            start_time = time.time()

            print(f"📦 Modal 成功拦截任务 [{task['id']}]，启动 GPU 推理...")
            try:
                # 伪代码：执行您的 VoxCPM2 核心推理及 R2 推流
                # audio_path = voxcpm2_gpu_core(task)
                # r2_url = upload_to_r2(audio_path, task['id'])
                r2_url = f"https://pub-xxx.r2.dev/{task['id']}.wav"

                # 任务成功，结算时间
                elapsed = time.time() - start_time

                total_now = r.incrbyfloat(current_month_key, elapsed)
                r.expire(current_month_key, 31 * 86400)

                print(f"⏱️ 消耗 {elapsed:.2f} 秒。本月 Modal 累计已用: {total_now/3600:.2f} / 40.00 小时")

                # 回执派发
                r.rpush(
                    "tts:results",
                    json.dumps({"id": task["id"], "status": "success", "url": r2_url, "worker": WORKER_ID}),
                )
            except Exception as e:
                r.rpush("tts:tasks", payload)  # 至少一次语义保障
                print(f"💥 推理中断，任务已安全回滚: {e}")
        else:
            empty_counter += 1
            print(f"⏳ 队列连续 {empty_counter} 次触及空值区... ", flush=True)

            # 智能判定：如果此时中央队列彻底干涸，没必要等待 15 分钟，原地解散
            if empty_counter >= max_empty_allow or r.llen("tts:tasks") == 0:
                print("🛑 队列已净空，Modal 触发 Serverless 原生熔断，立刻停止计费。")
                break

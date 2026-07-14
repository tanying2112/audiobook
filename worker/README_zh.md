# 多云 GPU Worker 生产部署指南 (v1.2.0-PRO)

## 架构总览

为实现**“代码写一次，云端跑四处”**，建议采用以下项目结构：

```
/project-root
├── src/
│   ├── worker_base.py     # 核心逻辑（Redis读写、推理抽象、R2上传、重试、优雅关闭）
│   └── tts_engine.py      # VoxCPM2 封装类
├── workers/               # 各平台入口脚本
│   ├── kaggle_worker.py
│   ├── lightning_worker.py
│   ├── baidu_paddle_worker.py
│   └── modal_worker.py
├── requirements.txt       # 统一依赖（版本锁定）
├── .env.example           # 配置模板
└── ops/                   # 运维工具箱
    ├── check_workers.sh
    ├── clean_stuck_tasks.py
    └── alert_bot.py
```

四个 Worker 共享**统一架构**：
- 消费 `tts:tasks` Redis 队列（Upstash Serverless 免费层）
- GPU 本地执行 VoxCPM2 推理
- WAV 音频上传 Cloudflare R2（免费出口流量）
- 结果推送 `tts:results` Redis 队列
- 心跳写入 `worker:heartbeat:{worker_id}` 并设 TTL（Telegram 告警监控）
- 15 分钟空闲自动退出以节省额度
- 失败重入队（至少一次语义）

| Worker | 平台 | 免费额度 | 主框架 | 定位 |
|--------|------|----------|--------|------|
| `kaggle_worker.py` | **Kaggle Kernels（主力）** | 30h/周 P100/T4 | PyTorch | **主力生产** - 额度最高、批处理模式 |
| `lightning_worker.py` | **Lightning AI Studios** | 80h/月 T4 | PyTorch | **备用/溢出** - 按月额度 |
| `baidu_paddle_worker.py` | **百度 AI Studio（飞桨）** | 12h/天 V100 | PaddlePaddle（优先） | **每日突发** - V100 适合重章节 |
| `modal_worker.py` | **Modal Serverless** | 40h/月 T4 | PyTorch | **突发需求** - 秒级冷启动 |

---

## 核心优化建议（务必在 `worker_base.py` 落地）

### A. 健壮性增强
| 机制 | 说明 |
|------|------|
| **指数退避重试** | Redis/R2 网络抖动时不直接退出，重试 3 次，间隔 1s/2s/4s |
| **优雅关闭** | 捕获 `SIGTERM`，完成当前任务再退出，防止文件损坏 |
| **模型热加载** | `__init__` 中一次性加载模型，**严禁**在任务循环中重复加载，避免显存泄漏 |
| **单次加载验证** | 启动时跑一次推理，确认模型可用再进入主循环 |

### B. 环境一致性方案
```
# requirements.txt（版本锁定）
torch>=2.3.0
torchaudio>=2.3.0
redis>=5.0.0
boto3>=1.34.0
transformers>=4.40.0
scipy>=1.13.0
soundfile>=0.12.0
# Kaggle/Baidu/Lightning: 启动脚本首行 pip install -r requirements.txt
# Modal: 镜像定义中 .pip_install_from_requirements("requirements.txt")
```

---

## 各平台部署深度优化

### Kaggle：注意“在线模式”
- **Internet Access**：Settings 中**必须开启**，否则无法连接 Upstash Redis
- **保活逻辑**：在 `kaggle_worker.py` 添加每 10 分钟 `print()` 一行日志，防止平台判定为死进程回收
- **Dataset 挂载**：模型放私有 Dataset，`kernel-metadata.json` 中 `dataset_sources` 引用

### Lightning AI：利用 Workspace 状态
- **Custom Environment**：为 Studio 制作 Docker 镜像，内置 VoxCPM2 与依赖，比每次 `pip` 快得多
- **Persistent Storage**：模型权重放 `/home/user/` 持久化目录，Studio 重启无需重新上传

### 百度 AI Studio：环境隔离
- **Paddle 与 PyTorch 共存**：百度环境较老，建议 `conda create -n voxcpm python=3.10`，全流程在虚拟环境运行，防止与系统飞桨库冲突
- **Paddle 优先**：`PREFER_PADDLE=true`，PyTorch 作为回退

### Modal：Serverless 优势
- **Concurrency Limit**：杀手锏。配置 `@app.function(concurrency_limit=2)` 限制并发，防瞬间烧光额度
- **Volume 挂载模型**：`modal.Volume` 挂载模型，无需镜像构建时下载，大幅加速冷启动

---

## 生产级运维工具箱（新增）

### A. 一键状态查询（本地 CLI）
```bash
# ops/check_workers.sh
#!/usr/bin/env bash
WORKERS=("kaggle-p100-01" "lightning-t4-01" "baidu-v100-01" "modal-t4-serverless")
for w in "${WORKERS[@]}"; do
    ttl=$(redis-cli -h "$REDIS_HOST" -a "$REDIS_AUTH" TTL "worker:heartbeat:$w" 2>/dev/null)
    if [[ $ttl -gt 0 ]]; then
        echo "✅ $w  在线 (TTL: ${ttl}s)"
    else
        echo "❌ $w  离线"
    fi
done
```

### B. Redis 队列清理脚本
```python
# ops/clean_stuck_tasks.py
import os, redis, json
r = redis.Redis(host=os.getenv("REDIS_HOST"), password=os.getenv("REDIS_AUTH"), decode_responses=True)

stuck = r.lrange("tts:results", 0, -1)
requeued = 0
for item in stuck:
    data = json.loads(item)
    if data.get("status") in ("processing", "started", "pending"):
        r.rpush("tts:tasks", json.dumps({"id": data["id"], "text": data.get("text", ""), "voice_id": data.get("voice_id", "zh_female_1")}))
        requeued += 1

r.delete("tts:results")
print(f"Requeued {requeued} stuck tasks. Queue reset.")
```

### C. Telegram 告警 Bot（cron 每 5 分钟）
```python
# ops/alert_bot.py
import os, redis, requests, json, time
r = redis.Redis(host=os.getenv("REDIS_HOST"), password=os.getenv("REDIS_AUTH"), decode_responses=True)
BOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")

for key in r.scan_iter("worker:heartbeat:*"):
    raw = r.get(key)
    if raw:
        hb = json.loads(raw)
        if time.time() - hb["ts"] > 900:
            msg = f"🚨 Worker {hb['worker_id']} 离线 >15分。最后心跳: {hb['ts']:.0f}, 队列: {r.llen('tts:tasks')}"
            requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", json={"chat_id": CHAT, "text": msg})
```

---

## 成本与负载均衡策略（高级）

**不要同时 24/7 跑满四个 Worker**。采用分级调度：

| 优先级 | 平台 | 触发条件 | 额度消耗 |
|--------|------|----------|----------|
| **T1** | Modal | 常驻 1 冷节点，突发秒级扩容 | ~40h/月 |
| **T2** | Kaggle + Lightning | 队列 > 50 任务 → 批量唤醒 | ~110h/月 |
| **T3** | 百度 | T1+T2 额度耗尽或离线时才启动 | ~360h/月 (12h/天) |

**控制器逻辑（集成在 Celery App 中）：**
```python
# src/audiobook_studio/tasks/queue_controller.py
def auto_scale_workers():
    r = get_redis()
    qlen = r.llen("tts:tasks")
    
    if qlen > 100:
        wake_up("lightning"); wake_up("baidu")
    elif qlen > 50:
        wake_up("lightning")
    # qlen == 0 时 Worker 会因 15min 空闲自动退出，无需干预

def wake_up(platform: str):
    if platform == "kaggle":
        kaggle_api.kernels_start("yourusername/audiobook-tts-worker")
    elif platform == "lightning":
        lightning_api.studio_start("audiobook-tts-worker")
    elif platform == "baidu":
        baidu_api.project_run("audiobook-tts-worker")
    # Modal 通过 concurrency_limit 自动弹性
```

---

## 任务提交与结果获取

### 方式一：Celery（推荐）
```python
from src.audiobook_studio.tasks.tts_tasks import synthesize_chapter_task, get_tts_status

task = synthesize_chapter_task.delay(
    project_id=123, chapter_id=456, chapter_index=1,
    paragraphs=[{"paragraph_id": 1, "paragraph_index": 0, "text": "第一章...", "voice_id": "zh_female_1"}]
)
status = get_tts_status(task.id)
```

### 方式二：直连 Redis（绕过 Celery）
```python
import redis, json, hashlib, os
r = redis.Redis(host=os.getenv("REDIS_HOST"), port=6379, password=os.getenv("REDIS_AUTH"), decode_responses=True)

def submit_tts(text: str, voice_id: str, prosody: dict = None) -> str:
    task_id = f"tts-{hashlib.md5(text.encode()).hexdigest()[:8]}"
    idem_key = f"tts:idem:{hashlib.sha256(f'{text}|{voice_id}|{json.dumps(prosody or {})}'.encode()).hexdigest()[:16]}"
    if r.set(idem_key, "1", nx=True, ex=3600):
        r.rpush("tts:tasks", json.dumps({"id": task_id, "text": text, "voice_id": voice_id, "prosody": prosody or {}}))
    return task_id

# 阻塞等待结果
_, payload = r.blpop("tts:results", timeout=300)
result = json.loads(payload)
```

---

## 故障排查速查表

| 现象 | 修复 |
|------|------|
| `CUDA not available` | 开启平台 GPU（Kaggle: 开关；Lightning: GPU 实例；百度: 选 V100） |
| `Model not found` | 核对 `VOXCPM2_MODEL_PATH` 与挂载路径；确认文件存在 |
| `Redis connection failed` | 确认 Upstash host/port/auth；Kaggle 需开 Internet |
| `R2 upload failed` | `R2_ENDPOINT` 必须含 `https://`；核对凭证与桶名 |
| `Worker 秒退` | 查日志找导入错误；执行 `pip install -r requirements.txt` |
| `OOM` | 减小 batch；开 `torch.compile`；启用 gradient checkpointing |
| `Kaggle kernel 被回收` | 开启 Internet；加 10 分钟保活 `print()` |

---

## 最终生产就绪清单

- [ ] **安全**：所有 `.env` 已加入 `.gitignore`；密钥仅存平台 Secret Store
- [ ] **模型完整性**：四平台模型文件 MD5 校验一致
- [ ] **监控**：Telegram Bot 能收到“Worker 离线”告警
- [ ] **冷启动**：队列为空时 Worker 优雅进入 sleep（无报错刷屏）
- [ ] **数据卫生**：R2 生命周期规则 → 30 天后自动清理旧音频
- [ ] **依赖固定**：`requirements.txt` 锁版本；四平台均从此安装
- [ ] **基类落地**：`src/worker_base.py` 实现重试、优雅关闭、单次模型加载
- [ ] **自动扩缩容**：控制器逻辑已集成 Celery App
- [ ] **运维脚本**：`check_workers.sh`、`clean_stuck_tasks.py`、`alert_bot.py` 已部署并加入 cron

---

## 架构图

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  主程序     │────▶│  Upstash     │◀───▶│  Worker 集群    │
│  (Celery)   │     │  Redis 队列  │     │  (4 平台)       │
└─────────────┘     │  tts:tasks   │     └────────┬────────┘
                    └──────┬───────┘              │
                           │                      │
                    ┌──────▼───────┐     ┌────────▼────────┐
                    │  tts:results │     │  Cloudflare R2  │
                    │  (结果队列)  │     │  (音频文件)     │
                    └──────────────┘     └─────────────────┘
                           │
                    ┌──────▼───────┐
                    │  心跳监控    │
                    │  (Telegram)  │
                    └──────────────┘
                           │
                    ┌──────▼───────┐
                    │  控制器      │
                    │ (自动扩缩容) │
                    └──────────────┘
```

---

*Version 1.2.0-PRO — 架构解耦、生产级健壮性、运维完备。*
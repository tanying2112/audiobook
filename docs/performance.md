# 性能优化指南

> **目标**: 5 万字小说 < 30 分钟全流程完成

## 📊 性能基准

| 阶段 | 当前 P50 | 目标 P50 | 当前 P95 | 目标 P95 |
|-----|---------|---------|---------|---------|
| extract | 50ms | 30ms | 200ms | 100ms |
| analyze | 2s | 1s | 8s | 4s |
| annotate | 800ms | 400ms | 3s | 1.5s |
| edit | 600ms | 300ms | 2s | 1s |
| synthesize | 200ms/段 | 100ms/段 | 1s/段 | 500ms/段 |
| quality_check | 300ms | 200ms | 2s | 1s |

**总计**: 5万字 ≈ 1500段 → 30分钟内完成

---

## ⚡ 性能优化策略

### 1. 并行处理 (Parallel Processing)

#### 管线阶段并行

```bash
# 启用并行处理 (默认: 4 workers)
export PIPELINE_MAX_WORKERS=8

# 或在配置中设置
# config/performance.yaml
performance:
  max_workers: 8
  batch_size: 10
  prefetch_ahead: 50
```

#### TTS 合成并行

```python
# 在 SynthesizePipeline 中启用批量合成
pipeline = SynthesizePipeline(
    output_dir="./output",
    mock_mode=False,
    batch_size=10,  # 一次处理 10 个段落
)

# Kokoro 引擎支持批量
# 参考 src/audiobook_studio/tts/kokoro_backend.py
```

### 2. 缓存策略 (Caching)

```bash
# 启用 Redis 缓存
export REDIS_URL=redis://localhost:6379

# 缓存 LLM 响应 (相同文本/参数)
CACHE_TTL_HOURS=24
CACHE_MAX_SIZE_MB=1000
```

### 3. 硬件配置

#### GPU 优化

```bash
# VoxCPM2 GPU 配置
export CUDA_VISIBLE_DEVICES=0
export TORCH_CUDA_ARCH_LIST="8.6"  # RTX 30/40 系列

# 量化模式 (减少 VRAM 使用)
export VOXCPM2_DTYPE=fp16  # 或 int8
```

#### Kokoro-ONNX 优化

```bash
# CPU 线程数
OMP_NUM_THREADS=8
OMP_PROC_BIND=true

# ONNX Runtime 优化
export ORT_ENABLE_FPGA_EP=1
export ORT_ENABLE_CUDA=1
```

---

## 🚀 快速模式 (Quick Mode)

### Mock 模式 (无需 API Key)

```bash
# 5分钟内完成 (使用内置模拟)
export MOCK_LLM=true
export MOCK_TTS=true

curl -X POST http://localhost:8000/api/auto-run/ \
  -d '{"book_path": "data/novel.txt", "use_mock": true}'
```

### 快速路由配置

```yaml
# config/pipeline.yaml
synthesize:
  default_engine: kokoro
  batch_size: 10
  max_parallel: 4
  skip_quality_check: false  # 保持质量检查
  streaming: true  # 流式输出
```

---

## 📦 批处理脚本

```bash
#!/bin/bash
# scripts/quick_book.sh - 5分钟快速制作

BOOK_PATH="$1"
OUTPUT_NAME="$2"

if [ -z "$BOOK_PATH" ]; then
    echo "Usage: ./quick_book.sh <book_path> [output_name]"
    exit 1
fi

# 1. 创建项目
PROJECT_ID=$(curl -s -X POST http://localhost:8000/api/projects/ \
    -d "{\"title\": \"$(basename $BOOK_PATH)\"}" | jq -r '.id')

# 2. 快速合成 (Mock 模式)
export MOCK_LLM=true
curl -X POST http://localhost:8000/api/auto-run/$PROJECT_ID/run \
    -d '{"use_mock": true, "max_workers": 8}'

# 3. 等待完成 (最多 5 分钟)
for i in {1..30}; do
    STATUS=$(curl -s http://localhost:8000/api/auto-run/$PROJECT_ID/status | jq -r '.status')
    if [ "$STATUS" == "completed" ]; then
        break
    fi
    sleep 10
done

# 4. 导出 M4B
curl -X POST http://localhost:8000/api/export/ \
    -d "{\"project_id\": $PROJECT_ID, \"format\": \"m4b\"}" \
    --output "${OUTPUT_NAME:-output}.m4b"
```

---

## 📈 性能监控

### 延迟监控

```bash
# 查看各阶段耗时
python scripts/bench_latency.py --stage all

# 导出指标
curl http://localhost:8000/metrics | jq '.pipeline'
```

### 成本监控

```bash
# 当前成本估算
curl http://localhost:8000/api/cost-estimate?chars=50000

# 历史成本
cat reports/bench_cost.json
```

---

## 🛠️ 常见性能问题

### 1. LLM 速率限制

```yaml
# config/llm_providers.yaml
providers:
  ollama:
    base_delay_seconds: 1.0  # 退避时间
    retry_count: 3
    fallback_chain: [deepseek, openai]
```

### 2. 内存不足

```bash
# 减少批大小
export BATCH_SIZE=4

# 启用流式处理
export STREAMING=true
```

### 3. 磁盘 I/O 满

```bash
# 使用 SSD 存储
STORAGE_PATH=/fast-ssd/storage

# 清理旧文件
find storage/ -name "*.mp3" -mtime +7 -delete
```

---

## 📋 检查清单

- [ ] 设置 `MOCK_LLM=true` (快速测试)
- [ ] 配置 `batch_size: 10`
- [ ] 设置 `PIPELINE_MAX_WORKERS=4-8`
- [ ] 启用 Redis 缓存
- [ ] 检查 FFmpeg 路径
- [ ] 准备 Kokoro 模型文件

---

*最后更新: 2026-06-28*
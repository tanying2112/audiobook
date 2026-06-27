# Pipeline 与 TTS 引擎配置

本文档详细说明 Audiobook Studio 的流水线配置和 TTS 引擎选择。

## 流水线概览

Audiobook Studio 采用 7 阶段流水线设计：

```
┌─────────────────────────────────────────────────────────────────┐
│  原始文本 → 提取 → 结构分析 → 段落标注 → 编辑 → 路由 → 合成 → 质检  │
└─────────────────────────────────────────────────────────────────┘
```

### 阶段说明

| 阶段 | 功能 | 输入 | 输出 |
|------|------|------|------|
| **提取** | 从 PDF/EPUB/TXT 提取文本 | 原始文件 | 纯文本 |
| **结构分析** | 识别章节、角色、情感 | 文本 | BookAnalysis |
| **段落标注** | 标注说话人、情感、语调 | 段落 + 上下文 | ParagraphAnnotation |
| **编辑** | TTS 友好化改写 | 标注段落 | 编辑后文本 |
| **路由** | 选择最佳 TTS 引擎 | 编辑文本 + 标注 | 路由决策 |
| **合成** | 生成音频 | 文本 + 语音配置 | 音频文件 |
| **质检** | 质量检测与修复 | 音频 + 原文本 | QualityJudgment |

## TTS 引擎配置

### 支持的引擎

| 引擎 | 类型 | 成本 | 质量 | 延迟 | 推荐场景 |
|------|------|------|------|------|----------|
| **Kokoro-82M** | 本地 ONNX | 免费 | ★★★☆☆ | 快 | 快速迭代 |
| **Edge TTS** | 云端免费 | 免费 | ★★★★☆ | 中 | 生产部署 |
| **Azure TTS** | 云端付费 | $$/百万字 | ★★★★★ | 快 | 高品质需求 |
| **GCP TTS** | 云端付费 | $$/百万字 | ★★★★☆ | 快 | 多语言支持 |
| **CosyVoice** | 本地/云端 | 免费 | ★★★★☆ | 中 | 声音克隆 |
| **F5-TTS** | 本地 | 免费 | ★★★★☆ | 中 | 零样本 TTS |

### 引擎优先级配置

在 `config/hardware_profile.yaml` 中配置：

```yaml
tts_engine_priority:
  # 引擎列表（按优先级降序排列）
  engines:
    - name: kokoro-onnx
      enabled: true
      max_chars_per_request: 500
      rate_limit_per_minute: 60
    - name: edge-tts
      enabled: true
      max_chars_per_request: 1000
      rate_limit_per_minute: 30
    - name: azure-tts
      enabled: false  # 需要 API key
      max_chars_per_request: 2000
      rate_limit_per_minute: 60

  # Fallback 配置
  fallback:
    max_retries: 3
    retry_delay_seconds: 5
    timeout_seconds: 30
```

### 引擎特性对比

```yaml
# Kokoro-82M (本地)
kokoro:
  pros:
    - 完全离线，隐私安全
    - 零成本
    - 低延迟 (~100ms/句)
  cons:
    - 声音选择有限
    - 情感表达较弱
  config:
    device: auto  # cpu/cuda/auto
    language: zh-CN
    model_path: models/kokoro-v1.0.onnx

# Edge TTS (云端免费)
edge_tts:
  pros:
    - 免费，无需 API key
    - 声音质量高
    - 多语言支持好
  cons:
    - 需要网络连接
    - 速率限制 (~30 请求/分钟)
  config:
    voice: zh-CN-XiaoxiaoNeural
    rate: +0%
    pitch: +0Hz

# Azure TTS (云端付费)
azure_tts:
  pros:
    - 最高质量
    - 神经 voices
    - 情感控制精细
  cons:
    - 需要 Azure 订阅
    - 成本较高
  config:
    region: eastasia
    voice: zh-CN-YunjianNeural
    style: cheerful

# CosyVoice (本地/云端）
cosyvoice:
  pros:
    - 声音克隆支持
    - 本地部署
    - 开源免费
  cons:
    - 需要 GPU 加速
    - 模型较大 (2GB+)
  config:
    mode: sft  # sft/fzero
    seed: 42
    max_input_len: 512
```

## 流水线配置

### 难度分级

```yaml
difficulty_weights:
  char_count_weight: 0.30       # 字符数权重
  dialect_ratio_weight: 0.25    # 方言比例权重
  term_density_weight: 0.20     # 术语密度权重
  emotion_complexity_weight: 0.15  # 情感复杂度权重
  speaker_count_weight: 0.10    # 说话人数量权重
  base_difficulty: 0.1          # 基础难度

difficulty_tiers:
  easy: 0.3    # A 级：童书/简单文本
  medium: 0.5  # B 级：通俗小说
  hard: 0.7    # C 级：文学/专业
  expert: 1.0  # D 级：古文/极难
```

### 路由规则

```yaml
tts_routing:
  # 基于难度路由
  by_difficulty:
    easy:
      preferred_engine: kokoro
      fallback: edge
    medium:
      preferred_engine: edge
      fallback: azure
    hard:
      preferred_engine: azure
      fallback: cosyvoice

  # 基于情感路由
  by_emotion:
    neutral:
      voice: default
    happy:
      voice: +10% rate
    sad:
      voice: -10% rate, +50Hz pitch
    angry:
      voice: +20% rate, -50Hz pitch

  # 基于成本路由
  cost_optimization:
    enabled: true
    max_cost_per_1000_chars: 0.01
    prefer_free_tier: true
```

## 质量门槛

```yaml
quality_thresholds:
  # 整体质量
  overall:
    min_acceptable_score: 0.7    # 低于此值触发重合成
    excellent_score: 0.9         # 高于此值为优秀
    schema_compliance_rate: 0.99 # 目标合规率

  # 单项维度
  dimensions:
    speaker_clarity: 0.85        # 说话人清晰度
    emotion_match: 0.80          # 情感匹配度
    prosody_naturalness: 0.75    # 韵律自然度
    text_audio_alignment: 0.80   # 文本 - 音频同步

  # 错误计数
  errors:
    max_silent_segments: 0       # 静默段不允许
    max_stuttering_issues: 0     # 卡顿问题
    max_truncation_issues: 0     # 截断问题

  # 音频参数
  audio:
    silence_threshold_db: -40    # 静音检测阈值
    clipping_threshold_percent: 0.1  # 削波阈值
    volume_normalization_target_db: -20  # 标准化音量
```

## 性能调优

### 并发配置

```yaml
concurrency:
  # 最大并发合成数
  max_concurrent_synthesis: 4

  # 基于硬件的调整
  hardware_scaling:
    cpu_only: 2
    gpu_4gb: 4
    gpu_8gb: 8
    gpu_16gb+: 16

  # 批量处理
  batch_processing:
    enabled: true
    batch_size: 10
    interval_seconds: 5
```

### 缓存策略

```yaml
caching:
  # 音频缓存
  audio_cache:
    enabled: true
    max_size_gb: 10
    ttl_hours: 72

  # LLM 响应缓存
  llm_response_cache:
    enabled: true
    max_size_mb: 500
    ttl_hours: 24
```

## 监控与日志

```yaml
monitoring:
  # Langfuse 集成
  langfuse:
    enabled: true
    public_key: ${LANGFUSE_PUBLIC_KEY}
    secret_key: ${LANGFUSE_SECRET_KEY}
    host: https://cloud.langfuse.com

  # 性能指标
  metrics:
    enabled: true
    export_interval_seconds: 60
    include:
      - latency
      - cost
      - quality_score
      - error_rate
```

## 故障排查

### 常见问题

**TTS 合成失败**
```bash
# 检查引擎状态
python -m src.audiobook_studio.tts.health_check

# 切换到备用引擎
export TTS_ENGINE=edge-tts
```

**路由失败**
```bash
# 查看路由日志
tail -f logs/routing.log

# 强制指定引擎
export FORCE_TTS_ENGINE=kokoro
```

**质量检查不通过**
```bash
# 查看详细质量报告
python -m src.audiobook_studio.quality.report --run-id <run_id>
```
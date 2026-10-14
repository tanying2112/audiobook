# 架构图解

本文档详细解析 Audiobook Studio 的四档变速架构设计。

## 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Audiobook Studio                               │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     Presentation Layer                            │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │  │
│  │  │   CLI    │  │   REST   │  │  WebSocket │  │  Web UI (Vue)   │ │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Application Layer                              │  │
│  │  ┌────────────────────────────────────────────────────────────┐   │  │
│  │  │                   Pipeline Orchestrator                     │   │  │
│  │  │  extract → analyze → annotate → edit → route → synthesize   │   │  │
│  │  └────────────────────────────────────────────────────────────┘   │  │
│  │                                                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐   │  │
│  │  │  LLM Router │  │ TTS Engine  │  │  Quality Judge          │   │  │
│  │  │  (3-Tier)   │  │  Registry   │  │  (Multi-modal)          │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Domain Layer                                 │  │
│  │  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────┐ │  │
│  │  │   Book Model      │  │  Paragraph Model  │  │  Audio Model  │ │  │
│  │  └───────────────────┘  └───────────────────┘  └───────────────┘ │  │
│  │  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────┐ │  │
│  │  │  Character Model  │  │  Chapter Model    │  │  Quality 💾   │ │  │
│  │  └───────────────────┘  └───────────────────┘  └───────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Infrastructure Layer                           │  │
│  │  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌────────────────────┐ │  │
│  │  │ SQLite  │  │ Langfuse │  │ Redis   │  │  File Storage      │ │  │
│  │  │  (ORM)  │  │ (Monitor)│  │ (Cache) │  │  (Local/S3)        │ │  │
│  │  └─────────┘  └──────────┘  └─────────┘  └────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 四档变速架构 (4-Tier Hardware Profiles)

> 四档：potato（纯本地 CPU）| offline（完全离线兜底，零档）| cloud_hybrid（默认：免费云 API + 本地 TTS）| pro_studio（显卡 + 重型模型）。

### 🥔 土豆模式 (Potato Mode)

**适用场景**: 无 GPU、断网环境、隐私敏感

```yaml
hardware_profile: potato
llm:
  provider: local
  model: Qwen2.5-3B-GGUF        # GGUF 格式，CPU 推理
  memory_usage: ~2GB
  tokens_per_second: ~15
tts:
  engine: kokoro-onnx           # ONNX 格式，CPU 推理
  memory_usage: ~500MB
  latency_per_sentence: ~200ms
cost:
  api_cost: $0
  electricity: ~$0.01/hour
```

### ☁️ 云端混合模式 (Cloud-Hybrid) - 默认

**适用场景**: 日常开发、一般质量需求

```yaml
hardware_profile: cloud-hybrid
llm:
  provider: openrouter
  models:
    - poolside/laguna-m.1:free  # 免费层
    - deepseek/deepseek-chat:free
  fallback: claude-sonnet-4-5   # 付费兜底
tts:
  engine: edge-tts              # 微软免费服务
  quality: ★★★★☆
  latency: ~500ms/sentence
cost:
  api_cost: $0 (free tier)
  fallback_cost: ~$0.10/1000chars
```

### 🚀 专业工作室模式 (Pro Studio)

**适用场景**: 商业项目、高质量需求、声音克隆

```yaml
hardware_profile: pro-studio
llm:
  provider: anthropic
  model: claude-sonnet-4-5-20250929
  temperature: 0
  max_tokens: 4096
tts:
  engine: cosyvoice             # 零样本声音克隆
  voice_clone: true
  quality: ★★★★★
  latency: ~1s/sentence
cost:
  api_cost: ~$3/100000chars
  tts_cost: ~$1/hour
```

---

## HARNESS 三层架构

### 契约层 (Contract Layer)

```python
# schemas/book.py - 输入/输出契约
class BookAnalysisInput(BaseModel):
    raw_text: str = Field(..., max_length=100000)
    contract_version: int = 2

class BookAnalysisOutput(BaseModel):
    title: str
    author: str
    chapters: List[ChapterInfo]
    characters: List[CharacterVoiceBinding]
    emotion_snapshot: EmotionSnapshot
```

### 执行层 (Execution Layer)

```python
# pipeline/orchestrator.py - 阶段执行
class StageRegistry:
    stages = {
        "extract": ExtractStage(),
        "analyze_structure": AnalyzeStage(),
        "annotate_paragraph": AnnotateStage(),
        "edit_for_tts": EditStage(),
        "tts_routing": RoutingStage(),
        "synthesize": SynthesizeStage(),
        "quality_check": QualityStage(),
    }
```

### 评估层 (Evaluation Layer)

```python
# monitoring/quality_metrics.py - 质量评估
class QualityMetrics:
    def evaluate(self, audio: AudioSegment, text: str) -> QualityScore:
        return QualityScore(
            overall=self._compute_overall(),
            dimensions=self._compute_dimensions(),
            issues=self._detect_issues()
        )
```

---

## 数据流详解

### 阶段 1: 文本提取

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ PDF/EPUB    │ ──> │  Parser     │ ──> │ Raw Text    │
│ TXT/Image   │     │ (多格式)     │     │ (纯文本)     │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │ OCR 兜底     │
                    │ (Tesseract) │
                    └─────────────┘
```

### 阶段 2: 结构分析

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Raw Text    │ ──> │  LLM Router │ ──> │ Book Meta   │
│ (50k chars) │     │ (选择模型)   │     │ Characters  │
└─────────────┘     └─────────────┘     │ Emotions    │
                                        └─────────────┘
```

### 阶段 3-7: 流水线处理

```
┌────────────────────────────────────────────────────────────────┐
│  Paragraph Pipeline                                            │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐        │
│  │Annotate │ ─>│  Edit   │ ─>│  Route  │ ─>│Synthesize│        │
│  │说话人    │   │ TTS 改写 │   │ 引擎选择 │   │ 音频生成 │        │
│  │情感标注  │   │ 归一化   │   │ 成本优化 │   │ 批量并发 │        │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘        │
│                                               │                 │
│                                               v                 │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐ │                 │
│  │  M4B    │ <── │  Export │ <── │ Quality │ <─┘              │
│  │  SRT    │     │  多格式  │     │  检测   │                   │
│  └─────────┘     └─────────┘     └─────────┘                   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 关键设计决策

### 1. 为什么使用 SQLite？

| 考量 | 决策理由 |
|------|----------|
| 简单性 | 零配置，单文件数据库 |
| 可移植性 | 随项目文件一起移动 |
| 性能 | 对于 <100 万条记录足够快 |
| 升级路径 | 可迁移到 PostgreSQL |

### 2. 为什么多 TTS 引擎？

```
单一引擎风险 → 多引擎冗余
   │
   ├─> 引擎故障 → 自动 Fallback
   ├─> 成本优化 → 免费优先
   ├─> 质量需求 → 按需升级
   └─> 隐私考虑 → 本地可选
```

### 3. 为什么 7 阶段设计？

```
粗粒度 (3 阶段) vs 细粒度 (7 阶段)
   │
   ├─> 细粒度优势:
   │    - 每阶段独立测试
   │    - 失败可单独重试
   │    - 质量检查点更密
   │    - 支持人工介入
   │
   └─> 代价：阶段切换开销
       缓解：内存数据库 + 批量处理
```

---

## 扩展点

### 添加新的 TTS 引擎

```python
# src/audiobook_studio/tts/engines/my_new_engine.py
class MyNewEngine(TTSEngine):
    def synthesize(self, text: str, output_path: str) -> SynthesisResult:
        # 实现合成逻辑
        pass
```

### 添加新的流水线阶段

```python
# src/audiobook_studio/pipeline/stages/my_stage.py
class MyStage(BaseStage):
    def execute(self, context: StageContext) -> StageResult:
        # 实现阶段逻辑
        pass

# 注册
from audiobook_studio.pipeline import StageRegistry
StageRegistry.register("my_stage", MyStage)
```

### 添加新的 LLM 提供商

```python
# src/audiobook_studio/llm/providers/my_provider.py
class MyProviderLLR(LLMRouter):
    def _select_model(self, task: LLMTask) -> str:
        # 实现选择逻辑
        pass
```

---

## 性能基准

| 模式 | 5 万字处理时间 | 成本 | 质量评分 |
|------|----------------|------|----------|
| 土豆 | ~8 小时 | $0 | 3.5/5 |
| 云端 | ~4 小时 | $0 | 4.0/5 |
| 专业 | ~2 小时 | $15 | 4.8/5 |

*基准测试条件：M2 MacBook Pro, 16GB RAM*
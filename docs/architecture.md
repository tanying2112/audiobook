# Architecture Overview

The Audiobook Studio is built with FastAPI as the web framework, SQLAlchemy 2.0 for ORM, and SQLite as the default database. The project follows a modular structure with clear separation of concerns.

## System Architecture

### Full Pipeline Flow

```mermaid
flowchart TD
    A[上传文件<br/>PDF/EPUB/DOCX/TXT/图片] --> B[Extract Pipeline<br/>文本提取 + 语言检测]
    B --> C[原始文本 + 元数据]
    C --> D[Analyze Pipeline<br/>结构分析 + 角色声纹映射]
    D --> E[BookAnalysisOutput<br/>角色声纹绑定 + 情感快照 + 场景标签]
    E --> F[Annotate Pipeline<br/>逐段并行标注<br/>角色/情感/语速/停顿]
    F --> G[ParagraphAnnotation<br/>角色/情感/语速/停顿/SFX]
    G --> H[Edit for TTS Pipeline<br/>文本润色 + 禁词过滤]
    H --> I[TtsEditOutput<br/>润色文本 + 修改记录]
    I --> J[Audio Postprocess<br/>声学参数最终确定]
    J --> K[最终声学参数<br/>语速/音高/音量/SFX]
    K --> L[Synthesize Pipeline<br/>并发 TTS 合成]
    L --> M[AudioSegment 列表<br/>文件路径/时长/引擎/音色]
    M --> N[Quality Check Pipeline<br/>多模态质检]
    N --> O[QualityJudgment<br/>多维评分/问题/修复建议]
    O --> P{需重生成?}
    P -- 是(≤2次) --> L
    P -- 否 --> Q[Export Pipeline<br/>M4B/SRT/RSS/MP4]
    Q --> R[成品交付<br/>M4B/有声书/字幕/视频]
    
    style A fill:#e1f5fe
    style R fill:#e8f5e9
    style P fill:#fff3e0
```

### Self-Iteration Loop (HARNESS)

```mermaid
flowchart TD
    A[用户反馈/质量判定差异] --> B[Feedback Collector<br/>自动采集人工修改]
    B --> C[SOP Reflection Engine<br/>结构化反思生成规则]
    C --> D[Prompt Version Store<br/>版本化提示词管理]
    D --> E[Canary Deploy<br/>小流量灰度验证]
    E --> F{晋升门禁<br/>格式≥99%/金集≥95%/质量≥102%}
    F -- 通过 --> G[Promote to Production<br/>生效新 Prompt 版本]
    F -- 拒绝 --> H[Rollback + Alert<br/>回滚+告警]
    F -- Canary中拒绝 --> I[Auto Rollback<br/>自动回滚]
    
    style G fill:#e8f5e9
    style H fill:#ffebee
    style I fill:#fff3e0
```

### TTS Synthesis & Voice Pipeline

```mermaid
flowchart TD
    A[文本输入] --> B{引擎选择}
    B -- 本地免费 --> B1[Kokoro-ONNX<br/>CPU/GPU 82M模型]
    B -- 云端免费 --> B2[Edge-TTS<br/>微软免费云端]
    B -- 专业GPU --> B3[CosyVoice/VoxCPM2<br/>零样本声纹克隆]
    B1 --> C[音频合成]
    B2 --> C
    B3 --> C
    C --> D[Audio Postprocess<br/>Ducking/规格化/规格化]
    D --> E[Quality Check<br/>DNSMOS/WER/SpeakerSim]
    E --> F{通过?}
    F -- 否(≤2次) --> A
    F -- 是 --> G[Export M4B/SRT/MP4]
    
    style B1 fill:#e3f2fd
    style B2 fill:#e8f5e9
    style B3 fill:#fff3e0
```

### Publish & Export Pipeline

```mermaid
flowchart TD
    A[AudioSegment 列表] --> B[Export Pipeline]
    B --> C{输出格式}
    C -- M4B --> D[M4B 章节分章<br/>元数据嵌入<br/>封面图嵌入]
    C -- SRT --> E[字幕生成<br/>时间轴对齐<br/>字符/行限制]
    C -- RSS --> F[RSS 2.0 Feed<br/>iTunes 标签<br/>Podcast 就绪]
    C -- MP4 --> G[视频封装<br/>音频+静态图/波形<br/>硬字幕烧录]
    D --> H[Audiobookshelf 推送<br/>API 上传 + 元数据]
    E --> H
    F --> H
    G --> H
    H --> I[完成交付]
    
    style I fill:#e8f5e9
```

### HARNESS Three-Layer Architecture

```mermaid
flowchart TB
    subgraph Contract["Layer 1: Contract (契约层)"]
        C1[Pydantic Schemas<br/>输入/输出契约]
        C2[Versioned Contracts<br/>config/contract_versions.yaml]
        C3[Golden Dataset<br/>tests/golden/{stage}/*.jsonl]
    end
    
    subgraph Execution["Layer 2: Execution (执行层)"]
        E1[Instructor<br/>结构化输出+自动重试]
        E2[LiteLLM Router<br/>多厂商路由/成本追踪]
        E3[Constitutional Rules<br/>config/constitutional_rules.yaml]
        E4[Few-shot Injection<br/>动态注入黄金示例]
    end
    
    subgraph Evaluation["Layer 3: Evaluation (评估层)"]
        V1[LLM-as-Judge<br/>独立评委模型]
        V2[Golden Dataset Regression<br/>CI 自动回归]
        V3[Feedback Loop<br/>feedback/collector.py]
        V4[Promotion Gate<br/>格式≥99%/金集≥95%/质量≥102%]
    end
    
    Contract --> Execution --> Evaluation
    Evaluation -.->|Feedback Loop| Contract
    
    style Contract fill:#e3f2fd
    style Execution fill:#e8f5e9
    style Evaluation fill:#fff3e0
```

### Data Flow Overview

```mermaid
flowchart LR
    subgraph Input["输入"]
        I1[文件上传<br/>PDF/EPUB/DOCX/TXT/图片]
    end
    
    subgraph Pipeline["7-Stage Pipeline"]
        P1[Extract]
        P2[Analyze]
        P3[Annotate]
        P4[Edit]
        P5[Audio Post]
        P6[Synthesize]
        P7[Quality]
    end
    
    subgraph Output["输出"]
        O1[M4B 有声书]
        O2[SRT 字幕]
        O3[RSS Feed]
        O4[MP4 视频]
    end
    
    I1 --> P1 --> P2 --> P3 --> P4 --> P5 --> P6 --> P7 --> Output
    P7 -.->|重试≤2次| P6
    
    style Input fill:#e1f5fe
    style Pipeline fill:#fff3e0
    style Output fill:#e8f5e9
```

## Core Components

### 1. Pipeline Stages (7 Stages)

| Stage | Module | Input | Output | Mock Mode |
|-------|--------|-------|--------|-----------|
| **Extract** | `extract.py` | File path | `ExtractionResult` (raw_text, language, page_count, warnings) | ✅ |
| **Analyze** | `analyze_structure.py` | Text + title | `BookAnalysisOutput` (book_meta, character_voice_map, emotion_snapshots, story_line_summary, global_style_notes) | ✅ |
| **Annotate** | `annotate_paragraph.py` | Paragraph + context | `ParagraphAnnotation` (speaker, emotion, speech_rate, pitch, pauses, SFX tags) | ✅ |
| **Edit** | `edit_for_tts.py` | Text + annotation | `TtsEditOutput` (edited_text, changes_made, forbidden_removed, rationale) | ✅ |
| **Audio Post** | `audio_postprocess.py` | Annotation + voice_map | `AudioPostProcessParams` (final speech_rate, pitch, SFX tags) | ✅ |
| **Synthesize** | `synthesize.py` | TTS inputs | `AudioSegment` (file_path, duration, engine, voice_id) | ✅ |
| **Quality** | `quality_check.py` | Audio + reference | `QualityJudgment` (scores, issues, fix_suggestions, needs_regeneration) | ✅ |
| **Translate** | `translate.py` | Chapters + target_lang | Translated chapters with voice characteristic preservation | ✅ |

### 2. Data Models (SQLAlchemy 2.0)

```
Project (1) ─────< Chapter (N)
Chapter (1) ─────< Paragraph (N)
Paragraph (1) ──< AudioSegment (1)
Paragraph (1) ──< Quality (1)
Paragraph (1) ──< TTSEdit (N)
Project (1) ────< Character (N)
```

Key models in `src/audiobook_studio/models/`:
- `Project` - 书籍项目元数据
- `Chapter` - 章节层级、状态追踪
- `Paragraph` - 段落文本、标注、编辑、质量分数
- `AudioSegment` - 音频文件路径、时长、引擎、音色
- `Quality` - 多维度质量评分、问题列表
- `TTSEdit` - 编辑历史版本
- `Character` - 角色声纹绑定
- `CharacterVersion` - 角色版本快照

### 3. HARNESS Three-Layer Architecture

#### Layer 1: Contract (契约层)
- **Pydantic Schemas** - 定义每个管线阶段的输入/输出契约
- **Versioned Contracts** - `config/contract_versions.yaml` 管理版本兼容性
- **Golden Dataset** - `tests/golden/{stage}/few_shot.jsonl` 种子用例

#### Layer 2: Execution (执行层)
- **Instructor** - 结构化输出解析 + 自动重试
- **LiteLLM Router** - 多厂商路由、成本追踪、Token Budget
- **Constitutional Rules** - `config/constitutional_rules.yaml` 自我修正规则
- **Few-shot Injection** - 动态注入黄金数据集示例

#### Layer 3: Evaluation (评估层)
- **LLM-as-Judge** - 质量检测管线使用独立 Judge 模型
- **Golden Dataset Regression** - CI 自动回归所有种子用例
- **Feedback Loop** - `feedback/collector.py` 自动采集人工修改/质量判断差异
- **Promotion Gate** - 格式合规≥99% / 金数据集≥95% / 质量≥旧版102%

### 4. Storage Layout

```
storage/
└─ books/
   └─ {project_id}/
      ├─ raw/              # 原始上传文件
      ├─ extracted/        # 提取后文本 (extracted.txt)
      ├─ annotated/        # 段落标注 JSONL
      ├─ audio/            # 合成音频片段
      │   └─ ch{chapter_index}/
      │       ├─ p{paragraph_index}.mp3
      │       └─ metadata.json
      └─ reports/          # 质量报告、导出产物
          ├─ quality_report.json
          ├─ compliance_report.json
          ├─ output.m4b
          └─ output.srt
```

### 5. LLM Provider Management

`config/llm_providers.yaml` 配置：
- 20+ 提供商: OpenAI, Anthropic, Google, Groq, NVIDIA, OpenRouter, DeepSeek, Ollama, Cerebras, etc.
- 多 Key 池: `api_key_pool_env`, `key_rotation_strategy`
- 免费模型定价归零
- 阶段级路由策略 (视觉/长文本/高频/高质量)

### 6. Monitoring & Compliance

- **ComplianceMonitor** - 实时追踪 Schema 合规率、契约版本分布
- **BaselineRecorder** - 性能基线记录、回归检测
- **Cost Dashboard** - 按阶段/模型/难度分解成本
- **Alert System** - 钉钉/Slack Webhook 告警

## Data Flow

```mermaid
flowchart TD
    A[上传文件] --> B[Extract Pipeline]
    B --> C[原始文本]
    C --> D[Analyze Pipeline]
    D --> E[BookAnalysisOutput]
    E --> F[Annotate Pipeline<br/>逐段并行]
    F --> G[ParagraphAnnotation]
    G --> H[Edit for TTS Pipeline]
    H --> I[TtsEditOutput]
    I --> J[Audio Postprocess]
    J --> K[最终声学参数]
    K --> L[Synthesize Pipeline]
    L --> M[AudioSegment 列表]
    M --> N[Quality Check Pipeline]
    N --> O[QualityJudgment]
    O --> P{需重生成?}
    P -- 是 --> L
    P -- 否 --> Q[Export M4B/SRT/RSS]
```

## Key Design Principles

1. **Pure Pipeline Stages** - 管线类无 DB 感知，Orchestrator 负责持久化
2. **Mock Mode Everywhere** - 所有类支持 `mock_mode=True` 实现无外部依赖测试
3. **Contract Versioning** - 每个阶段契约版本化，支持热加载和兼容性检查
4. **Checkpoint Resume** - 长任务支持断点续传，基于 `CheckpointManager`
5. **Observability First** - 所有 LLM 调用自动上报 Langfuse，成本/延迟/合规全链路可视
6. **Graceful Degradation** - 三层纵深防御: CircuitBreaker + HealthProbe + KeyPool + 启发式兜底
# 音频项目LLM参与环节"马具规范"（Harness Specifications）

> **适用对象**：所有参与本项目开发的 AI Agent 和开发人员，特别是LLM相关功能的实施者。
> **生效时间**：自本文件创建起永久生效。
> **维护要求**：如规范需修改，必须在本文档中更新并提交 `docs:` commit。
> **相关文档**：[`AGENTS.md`](./AGENTS.md)（Agent 通用行为准则）｜[`PROJECT.md`](./PROJECT.md)（项目业务说明）

---

## 〇、规范使用指南

| 读者 | 推荐阅读路径 |
|------|-------------|
| **业务/产品/编辑** | 一、1.1 → 二、各环节 What/Why/Success → 五、路线图 → 六、效果评估 |
| **算法/提示词工程师** | 一、1.2/1.3 三层架构与升级链 → 二、各环节 How → 三、3.3 提示词最佳实践 |
| **后端/平台工程师** | 一、1.4 厂商轮换 → 三、3.1/3.2 目录与契约 → 三、3.4 厂商适配层 → 三、3.9/3.10 CI/CD 与监控 → 八、代码骨架 |
| **质量/评估工程师** | 二、2.5 质量检测 → 三、3.5 黄金数据集 → 三、3.6 反馈处理 → 三、3.8 版本回滚 → 六、6.2 升级门禁 |

> **核心原则**：马具规范不仅是静态的指导文档，而是一个能够通过使用而自我改进的活系统。它结合了 LLM 的理解能力、人类的创造判断和自动化反馈机制，共同构建音频制作领域的质量标杆。

---

## 一、总体架构与逻辑链条

### 1.1 马具规范体系概览

马具规范（Harness Specifications）是为LLM参与音频制作全链路各环节设置的强制适用标准规范体系。它规定：

- **目标明确**：在该环节 LLM 要做什么（What）
- **资源界定**：可用资源和技能（Resources & Skills）
- **执行方法**：怎么做（How）
- **目的阐释**：为什么这样做（Why）
- **成功标准**：成功及验收标准（Success Criteria）
- **验证方法**：如何验收（Verification Methods）

### 1.2 三层架构（Contract / Execution / Evaluation）

```
╔══════════════════════════════════════════════════════════════════════════╗
║              第一层：契约层（Contract Layer）                              ║
║  ┌────────────┬─────────────┬─────────────┬──────────────────────────┐   ║
║  │ Pydantic   │ JSON Schema │ 黄金数据集 Golden Dataset │   ║
║  │  Schemas   │ (.baml)     │ (fallback)  │ (tests/golden/*.jsonl)    │   ║
║  └────────────┴─────────────┴─────────────┴──────────────────────────┘   ║
║  职责：定义每个环节"输入什么、输出什么、字段是否必填"                          ║
╚══════════════════════════════════════════════════════════════════════════╝
                                  ↓ 调用
╔══════════════════════════════════════════════════════════════════════════╗
║              第二层：执行层（Execution Layer）                              ║
║  ┌─────────────┬──────────────┬──────────────┬─────────────────────┐   ║
║  │ Instructor  │ LiteLLM      │ Few-shot     │ Constitutional       │   ║
║  │ (解析+重试)  │ (厂商路由)    │ Examples     │ Rules                │   ║
║  └─────────────┴──────────────┴──────────────┴─────────────────────┘   ║
║  职责：真正调用 LLM，强制按契约解析，按规则重试，按宪法自我修正                  ║
╚══════════════════════════════════════════════════════════════════════════╝
                                  ↓ 评估
╔══════════════════════════════════════════════════════════════════════════╗
║              第三层：评估与反馈层（Evaluation & Feedback Layer）              ║
║  ┌────────────┬─────────────┬────────────┬──────────────────────────┐    ║
║  │ 规则检查    │ LLM-as-a-   │ 人工校准                │    ║
║  │ (单元测试)  │ (A/B 对比)  │ Judge       │ Human-in-the-Loop      │    ║
║  └────────────┴─────────────┴────────────┴──────────────────────────┘    ║
║  职责：打分、对比、回流；通过则升级提示词版本，失败则阻止合并                     ║
╚══════════════════════════════════════════════════════════════════════════╝
```

**依赖规则**：
- 契约层变了 → 必须重跑评估层（用新契约校验历史输出会失败）
- 执行层变了（换模型/换提示词）→ 必须重跑评估层（验证质量不退化）
- 评估层变了（新增指标/规则）→ 必须回归全部黄金数据集

### 1.3 自我迭代升级逻辑链条

```
LLM执行 → 生成输出 → 人工编辑/质量检测反馈 →
反馈内容分析（修改理由 vs 原始理由） →
风格/偏好/差异规律总结 →
马具规范迭代更新 →
新一轮LLM执行
```

关键机制：
- **反馈收集**：质量检测环节和人工编辑过程自动捕获修改建议及理由
- **差异分析**：LLM比较原始生成理由与人工修改理由，提取模式
- **规律总结**：基于历史修改数据，统计风格偏好、常见错误类型、改进方向
- **规范更新**：将总结的规律转化为马具规范的具体改进
- **A/B测试**：新旧规范并行运行，基于质量指标自动选择优胜方案
- **安全回滚**：新规范导致质量下降时自动回滚至上一版本

### 1.4 多LLM提供商轮换机制

为提高可用性和鲁棒性，马具规范执行时采用轮换策略：

- **提供商池**：OpenAI、Anthropic、Google Gemini、Groq、NVIDIA、OpenRouter、DeepSeek、本地模型（可配置）
- **轮换策略**：基于服务健康状态、响应速度、成本效益的动态权重分配
- **故障转移**：单个提供商不可用时自动切换至下一个可用提供商
- **质量监控**：每个提供商的输出质量实时监控，劣质提供商自动降权

**厂商能力矩阵（路由决策依据）**：

| 任务 \ 厂商 | GPT-4o | Claude 3.5 | Gemini 2.0 | Groq Llama3.1 | DeepSeek |
|------------|--------|-----------|------------|--------------|----------|
| 复杂 JSON 输出 | ★★★★★ | ★★★★★ | ★★★★ | ★★★ | ★★★★ |
| 长文本理解（≥50k） | ★★★★ | ★★★★★ | ★★★★★ | ★★ | ★★★★ |
| 中文小说理解 | ★★★ | ★★★★ | ★★★★ | ★★★ | ★★★★★ |
| 响应速度 | ★★★ | ★★★ | ★★★★ | ★★★★★ | ★★★ |
| 免费额度 | ✗ | ✗ | ★★ | ★★★★ | ★★★ |

**路由策略**：
- 环节①+②（提取+结构语义工程，**多模态 LLM 流式**）：GPT-4o Vision / Claude 3.5 Sonnet Vision / Gemini 2.0 Pro Vision（按视觉理解能力 + 上下文长度自动选型）
- 环节③（段落分析，高频次）：Gemini 2.0 / Groq（成本+速度，无需多模态）
- 环节④（文本编辑，中等复杂度）：DeepSeek / GPT-4o
- 环节⑥（Judge，高质量必备）：Claude 3.5（Pairwise 比对时尤其稳定）

### 1.5 端到端逻辑链条

```
                       [输入文件]
              PDF / EPUB / DOCX / 图片 (现代简体/繁体横排)
                           │
                  ┌────────┴────────┐
                  │ 质量预检 (规则)   │  ← 古籍竖排 / 扫描模糊 / 复杂版式
                  │ quality_precheck │     → 直接标记 needs_human_review=true
                  └────────┬────────┘     → 跳过 LLM,转人工补录
                           ▼
        ┌────────────────────────────────────────────────────────┐
        │ ①+② 文本提取 + 结构语义工程 (LLM 编排,流式)            │
        │     extract_and_analyze.py                             │
        │                                                        │
        │   ┌──────────────┐    ┌────────────────────────┐       │
        │   │ 规则工具      │ ←→ │ 多模态 LLM (按章节流式)  │       │
        │   │ · PDF/EPUB 解码│    │ · GPT-4o Vision        │       │
        │   │ · 章节切分器   │    │ · Claude 3.5 Sonnet V  │       │
        │   │ · 图像分块器   │    │ · Gemini 2.0 Pro V     │       │
        │   │ · OCR 兜底     │    │  (按视觉能力自动选型)   │       │
        │   └──────────────┘    └────────────────────────┘       │
        │                                                        │
        │   每章节结束 → partial_output (单章增量)               │
        │   全本完成  → BookAnalysisOutput (合并 + 冲突解决)      │
        └────────────────────────┬───────────────────────────────┘
                                ▼
                ┌──────────────────────┐
                │ ③ 段落分析  (LLM)   │  ← 注入"上帝视角"上下文
                │  annotate_paragraph │     逐段:角色/情感/语速/音高/SFX
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │ ④ 文本编辑  (LLM#3) │  ← 朗读脚本生成
                │   edit_for_tts       │     断句、归一化、删除练习页
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │ ⑤ 音频合成           │  ← TTS 引擎（Kokoro / Edge）
                │   synthesize_audio   │     LLM 决策路由/声音克隆
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │ ⑥ 质量检测  (LLM#4) │  ← LLM-as-a-Judge
                │   quality_check      │     检查:情绪/卡顿/无声/截断
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │ ⑦ 输出 M4B + 字幕    │
                └──────────────────────┘

   ┌──────────────────────────────────────────────────────────────┐
   │ 反馈回路（横切所有 LLM 环节）                                    │
   │  人工编辑意见 / 质量检测失败 / 用户评分                           │
   │           ↓                                                   │
   │  反馈聚合 → 黄金数据集增量 → 评估回归 → 提示词版本升级评估         │
   │           ↓                                                   │
   │  通过 → 提升为新 default；失败 → 保持旧版本 + 告警                 │
   └──────────────────────────────────────────────────────────────┘
```

### 1.6 关键不变量（无论哪家 LLM、何时执行都必须满足）

1. **角色名一致性**：本本内同一角色只能有 1 个 canonical name（首次出现时确定）
2. **情感标签枚举固定**：只能从预定义枚举中选取
3. **语速范围**：7 档离散值
4. **音高范围**：半音 `-5` 到 `+5` 整数
5. **时间戳连续**：每个段落必须有 `start_char, end_char`，且全局不重叠

---

## 二、各环节马具规范详细制定

> **每节按 "What / Resources / How / Why / Success / Verification" 六段式呈现**；
> **"📦 契约代码" 折叠块为该环节的 Pydantic 模型实现，供工程师直接落地。**

### 2.1 文本提取环节（剧本结构语义工程清洗）

#### 2.1.1 目标（What）
LLM在原始文本提取基础上进行深度语义清洗和结构重建，生成具有统一故事线、角色关系图和情感强度快照的剧本基础版本。

#### 2.1.2 可用资源和技能（Resources & Skills）
- 输入：OCR语言检测后的原始文本流
- 可调用工具：标准NLP库（spaCy, NLTK），实体识别工具，情感分析模型
- 上下文窗口：最多32K tokens（依赖具体LLM提供商）
- 训练知识：文学理论，叙事结构模型，角色弧典型模式
- 输出格式：结构化剧本（JSON或类Airtable格式），包含：
  - 故事线摘要
  - 角色关系图（带特征标签）
  - 情感强度时间序列
  - 难度分级建议
  - 章节/段落结构

#### 2.1.3 执行方法（How）
1. **预处理阶段**：
   - 去除页眉页脚、版权声明、广告等非正文内容
   - 标准化标点符号和全半角字符
   - 语言混合文本的初步分离

2. **语义理解阶段**：
   - 使用思维链（CoT）提示进行深层语义分析
   - 识别 narrative arc（叙事弧）、关键转折点、高潮部分
   - 构建人物关系网络（家庭、友情、敌对、师徒等关系类型）

3. **结构重建阶段**：
   - 基于Freytag金字塔或英雄之旅模型识别剧情结构
   - 提取并标化角色口吻、语气特征
   - 检测并标记潜在的逻辑不一致或角色人设崩塌点
   - 生成情感强度曲线（为后续TTS提供参考）

4. **输出生成阶段**：
   - 生成结构化剧本JSON
   - 为每个角色分配一致的语音特征标签（ pitch range, speed preference, emotional tendency）
   - 标记需要特殊处理的章节（梦境、闪回、内心独白等）

#### 2.1.4 目的和理由（Why）
- 解决长篇小说常见问题：前后角色声音跑调、人设崩塌
- 为后续LLM处理提供统一的"上帝视角"背景
- 减少后续环节的上下文负担，提高处理一致性和质量
- 为个性化难度分级提供依据（A级保留原文，B/C级适当简化）

#### 2.1.5 成功及验收标准（Success Criteria）
- **角色一致性**：同一角色在不同章节的情感/语调偏差＜15%（通过情感分析模型检测）
- **结构完整性**：主要情节点覆盖率≥95%（与人工大纲对比）
- **噪声抑制**：非正文内容残留率＜2%
- **输出格式规范**：100%符合预定义JSON Schema
- **处理效率**：单卷本（300K字）处理时间＜5分钟

#### 2.1.6 验证方法（Verification Methods）
- 自动一致性检查：运行角色情感/语调连续性验证脚本
- 人工抽样检验：每10K字抽取1段进行专家评审
- 结构对比：与文学理论标准结构（如save the cat beats）进行映射匹配
- 质量门禁：未通过验证的输出不得进入后续环节

#### 📦 2.1.7 契约代码（输入/输出）

```python
# src/audiobook_studio/schemas/extraction.py
from pydantic import BaseModel, Field
from typing import Literal

class ExtractionInput(BaseModel):
    file_path: str
    mime_type: Literal["application/pdf", "application/epub+zip",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       "text/plain", "image/*"]
    detect_language: bool = True

class ExtractionResult(BaseModel):
    raw_text: str = Field(..., min_length=100)
    language: str                              # ISO 639-1
    page_count: int
    has_ocr: bool
    ocr_page_ratio: float = Field(0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"
```

#### 📦 2.1.8 验收脚本

```python
# tests/test_extraction.py
def test_extraction_not_empty(result: ExtractionResult):
    assert len(result.raw_text) > 100

def test_language_confidence(result: ExtractionResult):
    assert result.language in {"zh", "en", "ja", "fr", "es", "de"}

def test_ocr_ratio_threshold(result: ExtractionResult):
    assert result.ocr_page_ratio < 0.30, "OCR 页占比过高,需人工复核"
```

---

### 2.2 文本分析环节（智能区分与参数标注）

#### 2.2.1 目标（What）
LLM依照马具规范，根据难度分级智能区分剧本内容详略，自动剥离非核心内容，并重新分割文本、标注角色、情感、语速、音高、场景音效参数。

#### 2.2.2 可用资源和技能（Resources & Skills）
- 输入：来自文本提取环节的结构化剧本
- 知识库：语言难度评估标准（如CEFR, HSK），声学特征数据库，情感标注体系（如Plutchik's wheel of emotions）
- 参数范围：
  - 语速：0.7x - 1.3x（7 档离散）
  - 音高：-5 ~ +5 半音（整数）
  - 情感维度：愉悦度、唤醒度、支配度（PAD模型）
  - 场景音效类型：100+预定义类别（雨声、脚步声、门铃等）
- 输出：分段处理的文本块，每块附带完整参数标注

#### 2.2.3 执行方法（How）
1. **难度分级阶段**：
   - 基于语法复杂度、词汇稀有度、句子长度等维度计算难度分数
   - A级（难度＜0.3）：保留原文不变，保留章回元数据
   - B级（0.3≤难度＜0.7）：适当简化复杂句式，解释难点典故
   - C级（难度≥0.7）：转化为通俗叙事，重点保留情节和角色互动

2. **内容过滤阶段**：
   - 自动识别并标记：前言、版权页、致谢、索引、附录、习题等非核心内容
   - 根据难度级别决定保留程度：A级保留全部，B级保留摘要，C级仅保留情节相关

3. **参数标注阶段**：
   - 情感标注：基于文本线索（形容词、动词选择、标点使用）标注情感强度
   - 语速推断：基于句子复杂度、标点密度、修辞手法推断合适语速
   - 音高分配：根据角色特征（年龄、性别、身份）和当前情感状态确定基准音高
   - 场景音效匹配：识别环境描述、动作描述中的声音线索并匹配预定义音效库

4. **输出优化阶段**：
   - 平滑处理：相邻段落参数突变时进行过渡处理
   - 冲突解决：当多种标注产生冲突时，基于上下文和难度级别进行权衡
   - 一致性检查：确保同一角色在相似情境下的参数保持相对稳定

#### 2.2.4 目的和理由（Why）
- 实现个性化听书体验：不同听众可以选择适合自己的难度级别
- 为TTS合成提供精细控制参数，提高音频自然感和情感表达力
- 减少后期人工调参工作量，提高制作效率
- 保留原著核心价值同时降低听觉门槛

#### 2.2.5 成功及验收标准（Success Criteria）
- 难度分级准确性：与人工评定Kendall's τ系数≥0.8
- 情感标注一致性：与人工标注F1-score≥0.75（针对6种基础情感）
- 参数合理性：95%的参数落在人类语音可接受范围内
- 内容保留率：A级≥98%，B级≥85%，C级≥70%（核心情节保留）
- 处理一致性：相同输入多次运行参数方差＜5%

#### 2.2.6 验证方法（Verification Methods）
- 自动基准测试：使用标注良好的文学作品进行回归测试
- 人工评估：语言学专家对难度分级进行评分
- 参数合理性检查：语音合成试听后的人工评分（1-5分）
- 边界情况测试：专门测试对话密集段、盲文诗歌、术语说明等特殊内容

#### 📦 2.2.7 契约代码（输入/输出）

**环节② 输入/输出**（一次生成全本"上帝视角"档案）：

```python
# src/audiobook_studio/schemas/book.py
from pydantic import BaseModel, Field, conint, confloat
from typing import Literal

class BookAnalysisInput(BaseModel):
    raw_text: str = Field(..., max_length=200_000)
    title_hint: str | None = None
    author_hint: str | None = None
    target_difficulty: Literal["A", "B", "C", "D"] = "B"

class BookMeta(BaseModel):
    title: str
    author: str | None
    genre: Literal["小说", "散文", "诗歌", "历史", "科普", "童话", "其他"]
    difficulty: Literal["A", "B", "C", "D"]
    language: str  # ISO 639-1
    era: str | None
    total_chapters_estimated: int = Field(..., ge=1)

class CharacterVoiceBinding(BaseModel):
    canonical_name: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    gender: Literal["male", "female", "neutral", "unknown"]
    age_range: Literal["child", "young", "adult", "elderly", "unknown"]
    suggested_voice_id: str | None = None
    sample_quote: str  # 用于声音克隆

class EmotionSnapshot(BaseModel):
    chapter: int = Field(..., ge=1)
    dominant_emotion: Literal[
        "neutral", "happy", "sad", "angry", "fearful",
        "surprised", "disgusted", "tense", "tender", "contemplative"
    ]
    intensity: confloat(ge=0.0, le=1.0)
    notes: str = ""

class BookAnalysisOutput(BaseModel):
    book_meta: BookMeta
    character_voice_map: list[CharacterVoiceBinding] = Field(..., min_length=1)
    emotion_snapshots: list[EmotionSnapshot] = Field(..., min_length=1)
    story_line_summary: str = Field(..., min_length=100, max_length=500)
    global_style_notes: str
```

**环节③ 输入/输出**（逐段标注，注入"上帝视角"）：

```python
# src/audiobook_studio/schemas/paragraph.py
class ParagraphAnnotationInput(BaseModel):
    paragraph_text: str = Field(..., min_length=10, max_length=2000)
    paragraph_index: int = Field(..., ge=0)
    chapter_index: int = Field(..., ge=1)
    # 注入的"上帝视角"上下文
    book_meta: BookMeta
    character_voice_map: list[CharacterVoiceBinding]
    emotion_snapshot: EmotionSnapshot
    story_line_summary: str
    global_style_notes: str

class ParagraphAnnotation(BaseModel):
    paragraph_index: int
    speaker_canonical_name: str   # 必须命中 character_voice_map 或为 "_narrator_"
    is_dialogue: bool
    emotion: Literal[
        "neutral", "happy", "sad", "angry", "fearful",
        "surprised", "disgusted", "tense", "tender", "contemplative",
        "whisper", "cold_laugh", "sigh", "sarcastic"
    ]
    emotion_intensity: confloat(ge=0.0, le=1.0)
    speech_rate: Literal[0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
    pitch_shift_semitones: conint(ge=-5, le=5)
    needs_sfx: bool
    sfx_tags: list[str] = Field(default_factory=list)
    pause_before_ms: int = Field(0, ge=0, le=2000)
    pause_after_ms: int = Field(0, ge=0, le=2000)
    confidence: confloat(ge=0.0, le=1.0)
    notes: str | None = None
```

#### 📦 2.2.8 Hard Rules（违反任意一条即解析失败）

1. **禁止编造角色**：gender/age 不确定时填 `unknown`，禁止猜测
2. **canonical_name 唯一**：同一角色在全本所有 paragraphs 中只能有 1 个 canonical name
3. **story_line_summary 字数硬限**：100 ≤ 字数 ≤ 500
4. **emotion_snapshots 必填**：必须为估计章节数生成快照
5. **speaker 命中规则**：`speaker_canonical_name` 必须命中 `character_voice_map` 或为 `_narrator_`
6. **置信度透明**：`confidence < 0.6` 的标注必须在 UI 高亮，提示人工复核
7. **降级策略**：当 LLM 调用失败时，使用启发式规则：含冒号且长度 < 50 字标为 dialogue，其余为旁白
8. **批量处理**：每批 10-20 段，减少 LLM 调用次数

#### 📦 2.2.9 提示词骨架（`prompts/analyze_structure/v1.j2`）

```jinja
你是一位资深剧本顾问。下面是用户上传的长篇小说前若干章节,请你一次性完成"上帝视角"分析。

【任务】
1. 提取元信息(title/author/genre/difficulty/era)
2. 识别所有主要角色并绑定声音特征
3. 为每一章生成情感快照
4. 总结 100-500 字的故事主线(供后续段落分析时持续注入)
5. 总结文风与特殊处理建议

【Hard Rules】
- 不确定的信息填 null/unknown,禁止编造
- 角色 canonical_name 必须保持全本一致
- 输出必须是严格的 JSON,符合以下 Pydantic 模型:
  {{ schema_json }}

【Few-shot Example】
{{ fewshot_example }}

【正文开始】
{{ raw_text }}
```

#### 📦 2.2.10 验收脚本

```python
# tests/test_analyze_structure.py
def test_analyze_structure_output_is_valid(output: dict):
    BookAnalysisOutput.model_validate(output)  # Pydantic 强校验

def test_canonical_names_are_unique(output: BookAnalysisOutput):
    names = [c.canonical_name for c in output.character_voice_map]
    assert len(names) == len(set(names)), "角色名重复"

def test_story_line_length_in_range(output: BookAnalysisOutput):
    assert 100 <= len(output.story_line_summary) <= 500

def test_speaker_in_voice_map(annotation: ParagraphAnnotation, voice_map):
    assert annotation.speaker_canonical_name in (
        {c.canonical_name for c in voice_map} | {"_narrator_"}
    ), f"speaker {annotation.speaker_canonical_name} 不在角色表中"
```

---

### 2.3 文本编辑环节（LLM与人工互动）

#### 2.3.1 目标（What）
通过web页展现标注文本，支持LLM与人工互动与编辑。LLM需要能够理解人工修改意图，并基于此提供智能建议和自动完成。

#### 2.3.2 可用资源和技能（Resources & Skills）
- 输入：来自文本分析环节的参数标注文本块
- 人工交互：实时捕获用户在web界面上的修改（增删改）、注释和标记
- 上下文窗口：当前编辑段落及其前后文（可配置窗口大小）
- 预测能力：基于历史编辑模式和文档风格进行智能补全
- 建议生成：提供多种候选修改方案，附带理由和预期影响评估
- 输出：修改后的文本块以及LLM对修改的理解和学习目标

#### 2.3.3 执行方法（How）
1. **实时理解阶段**：
   - 捕获人工修改操作（插入、删除、替换、格式调整）
   - 分析修改意图：是纠错、风格调整、情感强化还是信息补充？
   - 使用注意力机制聚焦于修改相关的上下文

2. **意图建模阶段**：
   - 将人工修改映射到预定义的编辑意图分类：
     * 语法纠错
     * 用词精准化
     * 情感强度调整
     * 节奏/语速优化
     * 文化适应性修改
     * 信息补充/澄清
   - 每种意图分配置信度分数

3. **建议生成阶段**：
   - 基于当前编辑状态和历史模式生成智能补全建议
   - 提供风格化替换方案（例如：正式vs口语化表达）
   - 预测修改对后续参数的影响（如：增加悲伤情感描述会降低推荐语速）
   - 生成修改理由模板，以便后续学习

4. **学习强化阶段**：
   - 暂存人工修改及其上下文作为训练样本
   - 为马具规范迭代提供原始数据
   - 更新本地风格偏好模型（不泄露隐私）

#### 2.3.4 目的和理由（Why）
- 发挥人类创造力和LLM效率的协同优势
- 减少纯人工编辑的重复劳动
- 快速适应特定文学风格或作者偏好
- 建立人机协同的持续改进机制
- 保留人工编辑的最终决定权，同时获得LLM的辅助能力

#### 2.3.5 成功及验收标准（Success Criteria）
- 建议采纳率：LLM提供的编辑建议被人工采纳比率≥40%
- 编辑效率提升：使用LLM辅助编辑时平均每段编辑时间降低≥30%
- 意图识别准确率：对人工修改意图的分类准确率≥85%
- 建议多样性：对于相同上下文，建议方案熵值≥1.5（避免单一化）
- 用户满意度：编辑体验主观评分≥4/5

#### 2.3.6 验证方法（Verification Methods）
- A/B测试：对比开启/关闭LLM辅助编辑的用户行为和成果
- 日志分析：分析人工编辑日志中LLM建议的接受情况
- 意图混淆矩阵：使用已标注的编辑样本测试意图识别准确率
- 逆向验证：故意制造已知错误，测试LLM是否能主动提出修改建议
- 长期跟踪：观察用户在多次编辑会话中对LLM辅助的依赖程度变化

#### 📦 2.3.7 契约代码（输入/输出）

```python
# src/audiobook_studio/schemas/tts_edit.py
class TtsEditInput(BaseModel):
    paragraph_text: str
    paragraph_annotation: ParagraphAnnotation
    difficulty: Literal["A", "B", "C", "D"]
    forbid_edit: bool = False   # 难度≤A 或人工标记"原文锁定"时为 true

class TtsEditOutput(BaseModel):
    edited_text: str
    changes_made: list[str] = Field(default_factory=list)
    forbidden_content_removed: list[str] = Field(default_factory=list)
    confidence: confloat(ge=0.0, le=1.0)
    rationale: str
```

#### 📦 2.3.8 马具规则

1. **难度锁**：`difficulty ≤ A` 或 `forbid_edit=true` → 直接返回原文，`changes_made` 为空
2. **数字归一化**：阿拉伯数字 vs 中文数字需统一（推荐阿拉伯数字，朗读更自然）
3. **断句**：长句 > 50 字必须拆分，每句 ≤ 30 字
4. **标点处理**：删除朗读无意义的符号（`·`、`※` 等），保留逗号句号
5. **禁止删改对话主体**：dialogue 文本必须 1:1 保留，只调整标点

---

### 2.4 音频合成编排环节（LLM 决策路由）

> 注：TTS 引擎本身（Kokoro-ONNX / Edge-TTS）不是 LLM，但**编排决策**（哪段用什么声音、要不要情感增强）由一个轻量 LLM 决策。

#### 2.4.1 目标（What）
根据段落标注和系统状态，决定 TTS 引擎、声音、韵律覆盖、降级路径，平衡质量/成本/延迟。

#### 2.4.2 可用资源
- 输入：ParagraphAnnotation + 角色声音绑定表
- 可用引擎：kokoro（本地免费）、edge（云端）、human_clone（已克隆声音）
- 输出：TtsRoutingDecision

#### 📦 2.4.3 契约代码

```python
# src/audiobook_studio/schemas/tts_routing.py
class TtsRoutingDecision(BaseModel):
    segment_id: str
    engine_choice: Literal["kokoro", "edge", "human_clone"]
    voice_id: str              # 必须从 character_voice_map.suggested_voice_id 中选
    prosody_overrides: dict | None = None
    fallback_engine: Literal["kokoro", "edge", "human_clone"]
    reasoning: str
```

#### 📦 2.4.4 马具规则

1. **Kokoro 优先**：本地免费优先；超长或情感过强时降级到 Edge
2. **声音克隆**：仅当 `character_voice_map.sample_quote` 非空时启用
3. **成本监控**：单本书 TTS 成本 > 阈值时暂停并告警

---

### 2.5 质量检测环节（多模态模型与LLM反馈）

#### 2.5.1 目标（What）
引入可理解音频的多模态模型，自动化检测合成后音频质量，检测无声/卡顿/截断/情感/场景音效等问题，并向LLM提供修复和迭代建议。

#### 2.5.2 可用资源和技能（Resources & Skills）
- 输入：TTS合成后的音频段落及其对应的文本和参数标注
- 检测模型：多模态音频理解模型（能够同时处理音频和文本）
- 问题类库：预定义的音频质量问题类型及其特征征兆
- LLMs能力：基于音频问题描述生成具体的修复建议（文本层面或参数层面）
- 修复建议格式：具体到可以直接应用的调整（如"将第15句的悲伤强度从0.7提升到0.85"或在"句尾添加0.2秒停顿"）
- 输出：质量报告 + 针对LLM的修复建议包

#### 2.5.3 执行方法（How）
1. **多模态分析阶段**：
   - 音频特征提取：语速、停顿模式、音频能量分布、频谱特征
   - 文本-音频对齐：使用强制对齐技术验证内容一致性
   - 语义一致性检查：音频传达的情感是否与文本标注匹配
   - 声学合规性检测：响度、动态范围、失真等技术指标

2. **问题识别阶段**：
   - 基于规则和机器学习模型的混合方法识别问题：
     * 声音问题：无声段超过阈值、异常卡顿、意外截断
     * 情感问题：音频情感强度与文本标注偏离＞30%
     * 语速问题：实际语速与标注语速偏离＞20%
     * 场景音效问题：缺失、错误或过强的环境音
     * 配音一致性问题：同一角色在相似情境下音色突变
   - 每个问题分配严重程度等级（低/中/高/致命）

3. **LLM建议生成阶段**：
   - 为每个检测到的问题生成结构化的修复建议提交给LLM：
     * 问题描述：具体是什么地方出现了什么问题
     * 影响评估：这个问题对听众体验的影响程度
     * 可能原因：基于参数标注推断可能的根源
     * 建议动作：具体应该如何修改（文本/参数/两者都修改）
     * 置信度：系统对这个建议的信心程度
   - 鼓励LLM提供多种可能的解决方案及其权衡

4. **修复优化阶段**：
   - 基于LLM建议生成可直接执行的修复脚本
   - 自动应用低风险修复（如轻微语速调整）
   - 为高风险修复生成人工确认请求
   - 记录修复前后的质量指标变化以供学习

#### 2.5.4 目的和理由（Why）
- 开创智能音频质量闭环：从发现问题到自动建议解决方案
- 减少人工听音检测的主观性和疲劳问题
- 为LLM提供真实世界的反馈，促进其在音频领域的理解提升
- 实现"先合成后检测"的质量保障，而非仅靠经验预判
- 大幅降低返工率：问题早期发现，修复成本低

#### 2.5.5 成功及验收标准（Success Criteria）
- 问题检出率：已知问题检出率≥90%（针对预定义问题类型）
- 误报率：正常音频被误判为问题的比率＜5%
- 建议有效性：采纳LLM建议后问题解决率≥75%
- 修复精准度：参数修改建议导致质量改善的比率≥80%
- 响应时长：从音频生成到质量报告＋修改建议的总时长＜30秒/分钟音频
- LLMs学习效率：连续10次相似问题后，LLM建议采纳率提升≥25%

#### 2.5.6 验证方法（Verification Methods）
- 注人工金标准：由资深音频工作者标注问题作为基准
- 对照测试：引入已知问题的合成音测试检出能力
- 建议回溯：对历史问题，验证当时的LLM建议是否包含有效方案
- A/B测试：比较使用LLM建议修复 vs 人工修复的质量结果和时间消耗
- 漏检分析：定期复检已通过质量检测的音频，发现漏检问题以改进模型

#### 📦 2.5.7 检测维度与 Judge 契约

| 维度 | 评估方法 | 阈值 |
|------|---------|------|
| **角色一致性** | LLM Judge 比对 `speaker_canonical_name` 与音频可识别声纹 | ≥ 0.85 |
| **情感对齐** | LLM Judge 听音频描述情绪 vs `paragraph_annotation.emotion` | 一致 / 不一致 |
| **无声/卡顿/截断** | 音频规则脚本（pydub + numpy） | 0 个错误 |
| **敏感内容** | 关键词规则 + LLM 复核 | 0 命中 |
| **节奏合理性** | 句间停顿 vs `pause_before_ms / pause_after_ms` | 误差 < 200ms |

```python
# src/audiobook_studio/schemas/quality.py
class QualityJudgment(BaseModel):
    segment_id: str
    speaker_clarity: confloat(ge=0.0, le=1.0)
    emotion_match: confloat(ge=0.0, le=1.0)
    prosody_naturalness: confloat(ge=0.0, le=1.0)
    text_audio_alignment: confloat(ge=0.0, le=1.0)
    overall_score: confloat(ge=0.0, le=1.0)
    issues: list[Literal[
        "wrong_speaker", "emotion_mismatch", "silent_segment",
        "stuttering", "truncation", "sensitive_content",
        "wrong_speed", "wrong_pitch"
    ]] = Field(default_factory=list)
    fix_suggestions: list[str] = Field(default_factory=list)
    needs_regeneration: bool
```

#### 📦 2.5.8 Judge 提示词骨架（`prompts/quality_judge/v1.j2`）

```jinja
你是一位资深有声书质检员。请评估以下音频片段的质量。

【音频转写文本】
{{ transcribed_text }}

【剧本期望】
- 角色: {{ expected_speaker }}
- 情感: {{ expected_emotion }} (强度 {{ expected_intensity }})
- 语速: {{ expected_rate }}
- 音高: {{ expected_pitch }}

【音频描述】（由多模态模型生成）
{{ audio_description }}

【评估维度】（0-1 打分,1 为最佳）
1. 角色识别准确度: speaker_clarity
2. 情感匹配度: emotion_match
3. 韵律自然度: prosody_naturalness
4. 文本-音频一致性: text_audio_alignment

【输出 JSON】
{{ schema_json }}
```

#### 📦 2.5.9 反馈回路触发条件

- 任何维度 < 0.7 → 标记 `needs_regeneration: true`
- 连续 3 段同一角色 wrong_speaker → 触发"角色声音绑定重新评估"
- 情感不匹配占比 > 20% → 触发"提示词版本升级评估"

---

## 三、马具规范架构实施细节

### 3.1 配置和存储结构

```
audiobook/
├── harness_specs/                          # 规范版本化资产
│   ├── text_extraction/
│   │   ├── v1.0.yaml                       # 版本化规范文件
│   │   ├── Prompt_Templates/               # 不同LLM提供商的提示词模板
│   │   └── Validation_Rules/               # 自动验证规则
│   ├── text_analysis/
│   │   ├── v1.0.yaml
│   │   ├── Difficulty_Standards/
│   │   └── Parameter_Ranges/
│   ├── text_editing/
│   │   ├── v1.0.yaml
│   │   ├── Intent_Taxonomy/
│   │   └── Suggestion_Engine/
│   ├── tts_routing/
│   │   └── v1.0.yaml
│   └── quality_detection/
│       ├── v1.0.yaml
│       ├── Problem_Taxonomy/
│       └── Suggestion_Templates/
├── src/audiobook_studio/                   # 代码实现
│   ├── llm/
│   │   ├── router.py                       # LiteLLM 路由 + Fallback
│   │   ├── client.py                       # Instructor 封装
│   │   └── judge.py                        # LLM-as-a-Judge 工具
│   ├── schemas/                            # 契约层 (Pydantic v2)
│   │   ├── extraction.py                   # ExtractionResult
│   │   ├── book.py                         # BookMeta, CharacterVoiceBinding
│   │   ├── paragraph.py                    # ParagraphAnnotation
│   │   ├── tts_edit.py                     # TtsEditOutput
│   │   ├── tts_routing.py                  # TtsRoutingDecision
│   │   ├── quality.py                      # QualityJudgment
│   │   └── feedback.py                     # FeedbackRecord
│   ├── pipeline/
│   │   ├── extract.py                      # 环节①
│   │   ├── analyze_structure.py            # 环节②
│   │   ├── annotate_paragraph.py           # 环节③
│   │   ├── edit_for_tts.py                 # 环节④
│   │   ├── synthesize.py                   # 环节⑤
│   │   └── quality_check.py                # 环节⑥
│   └── harness.py                          # 顶层 Harness 编排入口
├── prompts/                                # 提示词即资产
│   ├── analyze_structure/
│   │   ├── v1.j2
│   │   └── v2.j2
│   ├── annotate_paragraph/
│   ├── edit_for_tts/
│   ├── tts_routing/
│   └── quality_judge/
├── tests/
│   ├── golden/                             # 黄金数据集
│   ├── test_extraction.py
│   ├── test_analyze_structure.py
│   ├── test_annotate_paragraph.py
│   ├── test_edit_for_tts.py
│   ├── test_tts_routing.py
│   └── test_quality_judge.py
├── eval/                                   # 评估脚本
│   ├── deepeval_config.py
│   ├── promptfooconfig.yaml
│   └── promote.py                          # 升级评估脚本
├── logs/
│   ├── harness_feedback/                   # 人工修改和质量检测反馈日志
│   └── performance_metrics/                # 马具规范执行性能指标
├── checkpoints/
│   └── harness_versions/                   # 马具规范版本快照（用于回滚）
└── scripts/
    ├── harness_validator.py                # 规范自验证脚本
    ├── feedback_processor.py               # 反馈处理和规律总结脚本
    └── version_manager.py                  # 版本管理和A/B测试脚本
```

### 3.2 提示词工程最佳实践

所有马具规范的LLM交互都应遵循以下提示词原则：

1. **清晰的角色定义**：
   ```
   您是一位专业的文学编辑和音频制作顾问，具有丰富的古典和现代文学处理经验。
   ```

2. **结构化输出要求**：
   ```
   请以JSON格式返回结果，包含以下字段：{
     "analysis": "...",
     "recommendations": [...],
     "confidence": 0.0-1.0,
     "reasoning": "..."
   }
   ```

3. **思维链激活**：
   ```
   请一步一步地思考：首先，识别文本中的主要情感线索；其次，分析这些线索如何转化为音频参数；最后，提供具体的参数建议。
   ```

4. **上下文限定**：
   ```
   基于之前分析的角色特征（主角：年轻女性，勇敢但含蓄；反派：中年男性，威严但内心孤独），请为当前段落生成适合的情感强度曲线。
   ```

5. **失败安全模式**：
   ```
   如果不确定具体数值，请提供合理范围而非猜测具体数字，并说明不确定性来源。
   ```

6. **Schema 注入**：模板末尾注入 `{{ schema_json }}`，让 LLM 明确知道要返回的 Pydantic 模型结构
7. **Few-shot 范例**：每个提示词配套 1-3 条来自 `tests/golden/` 的真实样本
8. **温度与最大 token**：分析/编辑类用 `temperature=0.2-0.3`、建议生成类用 `0.5-0.7`、JSON 输出统一 `max_tokens` 留余量

### 3.3 LLM 厂商适配层（LiteLLM + Instructor）

```python
# src/audiobook_studio/llm/router.py
from litellm import completion
from tenacity import retry, stop_after_attempt, wait_exponential
import instructor
import logging

logger = logging.getLogger(__name__)

class AllModelsFailedError(Exception):
    pass

class LLMRouter:
    """按场景自动路由 + 失败降级"""

    PRIMARY_MODEL = "gpt-4o"
    FALLBACK_CHAIN = [
        "claude-3-5-sonnet-20241022",
        "gemini-2.0-flash-exp",
        "groq/llama-3.1-70b",
        "deepseek/deepseek-chat",
    ]

    def __init__(self, primary: str | None = None, fallback: list[str] | None = None):
        self.primary_model = primary or self.PRIMARY_MODEL
        self.fallback = fallback or self.FALLBACK_CHAIN
        self.client = instructor.from_litellm(completion)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def call(self, messages, response_model, **kwargs):
        for model in [self.primary_model, *self.fallback]:
            try:
                return self.client.chat.completions.create(
                    model=model,
                    response_model=response_model,
                    messages=messages,
                    max_retries=3,        # Instructor 内置重试
                    **kwargs,
                )
            except Exception as e:
                logger.warning(f"模型 {model} 失败: {e}, 降级到下一个")
                continue
        raise AllModelsFailedError("所有 LLM 厂商均不可用")
```

**故障转移策略细节**：
- 单个提供商不可用时自动切换至下一个可用提供商
- 失败 3 次后停止重试，避免雪崩
- 降级链顺序按"质量优先 + 成本递减"排列：GPT-4o → Claude 3.5 → Gemini 2.0 → Groq（免费）→ DeepSeek

### 3.4 黄金数据集（Golden Dataset）设计

#### 3.4.1 目录结构

```
tests/golden/
├── analyze_structure/
│   ├── 01_jinyu.jsonl        # 红楼梦节选 + 期望输出
│   ├── 02_three_body.jsonl   # 三体节选
│   └── ...
├── annotate_paragraph/
│   ├── 01_dialogue_heavy.jsonl
│   ├── 02_narrative_heavy.jsonl
│   └── 03_mixed.jsonl
├── edit_for_tts/
│   ├── 01_long_sentence.jsonl
│   └── 02_with_numbers.jsonl
├── tts_routing/
│   └── 01_emotional_heavy.jsonl
└── quality_judge/
    ├── 01_good_audio.jsonl
    └── 02_bad_audio.jsonl
```

#### 3.4.2 单条用例格式（JSONL）

```json
{
  "id": "analyze_001",
  "input": {
    "raw_text": "林黛玉葬花那日,落红满地,她独自提着花锄,..."
  },
  "expected_output": {
    "book_meta": {
      "title": "红楼梦（节选）",
      "author": "曹雪芹",
      "genre": "小说",
      "difficulty": "C",
      "language": "zh",
      "era": "清代",
      "total_chapters_estimated": 1
    },
    "character_voice_map": [
      {
        "canonical_name": "林黛玉",
        "aliases": ["黛玉"],
        "gender": "female",
        "age_range": "young",
        "suggested_voice_id": null,
        "sample_quote": "侬今葬花人笑痴,他年葬侬知是谁?"
      }
    ],
    "emotion_snapshots": [...],
    "story_line_summary": "...",
    "global_style_notes": "..."
  },
  "difficulty_tags": ["emotional", "classical_chinese"],
  "source": "人工标注"
}
```

#### 3.4.3 黄金数据集增长机制

```
新反馈（人工编辑 / 质量失败 / 用户评分）
        │
        ▼
人工/Agent 审核 → 是否为"金标准"？
        │
   ┌────┴────┐
   是        否
   │         │
   ▼         ▼
入仓 +    归档为"参考资料",
创建 PR  供后续 fine-tuning 使用
```

#### 3.4.4 反馈数据契约

```python
# src/audiobook_studio/schemas/feedback.py
from datetime import datetime
from typing import Literal

class FeedbackRecord(BaseModel):
    id: str
    timestamp: datetime
    source: Literal["human_edit", "quality_judge", "user_rating"]
    stage: Literal[
        "extract", "analyze_structure", "annotate_paragraph",
        "edit_for_tts", "tts_routing", "quality_judge"
    ]
    book_id: str
    paragraph_index: int | None
    input_snapshot: dict        # 当时的输入
    llm_output: dict           # 当时 LLM 的输出
    corrected_output: dict     # 人工/期望的输出
    rationale: str             # 修改理由（必填）
    diff_summary: str          # 由 Agent 自动生成
    pattern_tags: list[str] = Field(default_factory=list)
    # 例: ["missed_dialogue_attribution", "emotion_too_mild"]
```

### 3.5 反馈处理和规律总结机制

#### 3.5.1 反馈收集管道
```
人工编辑 → 编辑日志捕获 → 结构化存储 → 周期性批处理
质量检测 → 问题报告生成 → 修复建议记录 → 实时流处理
```

#### 3.5.2 差异分析算法
1. **意图解析**：将人工修改映射到编辑意图分类法
2. **理由对比**：比较LLM原生理由与人工修改理由的语义相似度
3. **特征提取**：从修改中抽取风格特征（用词偏好、句型倾向、情感表达习惯）
4. **模式挖掘**：使用聚类和关联规则发现修改模式

#### 3.5.3 规律总结输出
总结结果应包含：
- **高频修改类型**：排名前10的修改意图及其出现频率
- **风格偏好 drift**： LLMs原始输出 vs 人工偏好的系统性差异
- **错误模式**： 特定文本类型下LLM容易出错的情况
- **改进建议**： 针对马具规范的具体修订方案
- **置信度评估**: 基于样本量和一致性的统计显著性检验

#### 3.5.4 自动规范更新流程

```
                  触发条件
        (反馈累积 ≥ 10 条 或 质量检测告警)
                       │
                       ▼
            ┌──────────────────────┐
            │ Agent 差异分析        │  ← 对比 llm_output vs corrected_output
            │ 提取 pattern_tags    │
            └──────────┬───────────┘
                       ▼
            ┌──────────────────────┐
            │ 创建提示词新版本       │  ← prompts/<stage>/v2.j2
            │ (基于 pattern_tags    │
            │  调整 few-shot)        │
            └──────────┬───────────┘
                       ▼
            ┌──────────────────────┐
            │ 全量黄金数据集回归     │  ← 规则检查 + LLM Judge
            └──────────┬───────────┘
                       ▼
                  通过？
              ┌────┴────┐
              是        否
              │         │
              ▼         ▼
         提升 v2     保留 v1,
         为 default  记录失败原因,
                     等待下次迭代
```

### 3.6 版本控制和回滚机制

1. **语义化版本控制**：MAJOR.MINOR.PATCH
   - MAJOR：不兼容的重大变更（可能影响输出格式）
   - MINOR：向后兼容的功能增强
   - PATCH： bug修复和微小调整

2. **自动回滚触发条件**：
   - 新版本导致关键质量指标下降＞10%
   - 人工评估满意度显著下降
   - 检测到明显的输出格式破坏

3. **灰度发布策略**：
   - 金丝雀发布：5%流量使用新版本
   - 逐步扩大：25% → 50% → 100%
   - 实时监控：质量指标、错误率、用户反馈

4. **回滚执行**：
   - 自动切回上一个稳定版本
   - 保留问题版本用于诊断
   - 通知开发团队进行根因分析

5. **Promotion Gate 4 项硬指标**（任意一项不达标 → 升级失败，自动开 issue）：
   - **格式合规率**：≥ 99%（Pydantic 校验通过的比例）
   - **黄金数据集通过率**：≥ 95%
   - **整体质量分**：≥ 旧版本 102%（不低于旧版 2%，防止回归）
   - **成本/延迟退化**：不超过旧版 110%

### 3.7 CI/CD 集成

#### 3.7.1 GitHub Actions 工作流

```yaml
# .github/workflows/llm_quality_gate.yml
name: LLM Quality Gate

on:
  pull_request:
    paths:
      - 'prompts/**'
      - 'src/audiobook_studio/schemas/**'
      - 'src/audiobook_studio/llm/**'
      - 'tests/golden/**'

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install
        run: pip install -e ".[eval]"
      - name: Run Quality Checks
        run: pytest tests/unit/test_quality_check.py tests/unit/test_llm_judge.py -v
      - name: Run LLM Judge Tests
        run: pytest tests/unit/test_llm_judge.py -v
      - name: Coverage Gate
        run: pytest --cov=src --cov-fail-under=80
```

#### 3.7.2 Quality Gate 行为

| 触发条件 | 行为 |
|---------|------|
| 提示词文件变更 | 强制重跑黄金数据集 |
| 契约文件变更 | 强制回归 + 警告"API 破坏" |
| 厂商配置变更 | 强制跑兼容性测试（5 个厂商 × 10 个用例） |
| 黄金数据集新增 | 自动重新评估旧提示词在新数据上的表现 |

### 3.8 监控与可观测性

#### 3.8.1 必须采集的 Trace 字段

```python
class LLMTrace(BaseModel):
    trace_id: str
    timestamp: datetime
    stage: str
    model_used: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    raw_output: str
    parsed_output: dict | None
    parse_success: bool
    retry_count: int
    fallback_used: bool
    error: str | None
    book_id: str
    paragraph_index: int | None
```

#### 3.8.2 监控仪表盘指标

- **格式合规率**（按 stage、按 model）
- **P50 / P95 延迟**（按 stage）
- **每千字成本**（按 stage、按 model）
- **Fallback 触发率**（告警阈值 > 5%）
- **黄金数据集最新得分**（每周趋势）
- **反馈记录数 / 升级触发数**（每月）

#### 3.8.3 推荐工具

- **Langfuse**（开源、自托管友好）—— Trace + 评估 + 提示词版本管理
- **LiteLLM Proxy** —— 统一日志 + 成本统计
- **Prometheus + Grafana** —— 系统级监控

---

## 四、参考市场最新案例和最佳实践

### 4.1 多模态LLM在音频理解领域的进展
- **谷歌的AudioLM**：展示了仅凭音频提示生成连贯语音的能力，验证了音频-语义深度关联的可行性
- **Meta的Voicebox**：支持多种风格的语音编辑和噪声 removal，为质量检测环节提供技术参考
- **开源项目Coqui TTS**：展示了端到端可训练的TTS系统，结合LLM进行前后文理解

### 4.2 LLM自我改进系统的前沿研究
- **自我改进语言模型（Self-Refine）**：通过自我评估和反馈循环迭代改进输出
- **反思式大语言模型（Reflexion）**：强化学习+语言反馈的自我改进框架
- **进化式提示词工程**：利用遗传算法自动发现优秀提示词模式

### 4.3 人机协同内容创作的实践
- **GitHub Copilot**：展示了LLM在IDE实时辅助编辑的成功模式，特别是意图理解和建议生成
- **Notion AI**：提供了文档编辑中的智能补全和风格转换功能
- **企业级内容平台**：如Adobe Firefly中的创意辅助功能，强调可控性和迭代性

### 4.4 自动化质量控制在多媒体制作中的应用
- **Netflix的自动化质量检查**：用于视频内容的技术规格和内容合规性自动检验
- **Spotify的音频标准化**：响度标准化和内容审核的自动化流程
- **有声书行业标准**：如Audible的制作规范，为质量检测提供参考基准

### 4.5 基于反馈的规范演化系统
- **Wikipedia的编辑战争检测与解决**：通过编辑模式分析预测和缓解内容分歧
- **开源项目的issue闭环**：从bug报告到修复验证的完整流程管理
- **机器学习操作（MLOps）中的模型监控**：持续监控模型性能并在下降时触发重新训练

### 4.6 现代 LLM 工程化工具链选型矩阵（2025）

| 实践 | 采用理由 | 本项目对应位置 | 状态 |
|------|---------|----------------|------|
| **Instructor**（Pydantic 驱动） | 与 Pydantic v2 深度集成，自动重试，最适合云端多模型 | 全部 6 个 LLM 环节的解析层 | ✅ 已集成 |
| **DSPy**（声明式 + 优化器） | 自动用 BootstrapFewShot 优化 Prompt，无需手写 | 文本分析、文本编辑两个高质量环节 | ⚠️ 预留集成 |
| **Langfuse** | 生产级 Trace + 自动评估 | 监控、Golden Dataset 采集 | ✅ 已集成 |
| **Constitutional AI** | 原则驱动自我修正 | 质量检测环节的反馈循环 | ✅ 已实现 |
| **LiteLLM** | 100+ 厂商统一接口 + 自动 Fallback | 厂商适配层 | ✅ 已集成 |
| **LLM-as-a-Judge** | 语义评估，支持 Pairwise 比对 | 质量检测、版本对比 | ✅ 已实现 |
| **规则检查** | DNSMOS/ASR/SpeakerSim 硬指标 | 客观质量门禁 | ✅ 已实现 |

> **本项目的选型**：以 **Instructor + Pydantic** 为主（生态最广、上手最快），**LiteLLM** 做厂商路由，**LLM-as-a-Judge + 规则检查 (DNSMOS/ASR/SpeakerSim) + Langfuse** 形成评估闭环。
> **注**：BAML、DeepEval、Promptfoo、RAGAS 为业界优秀工具，当前版本未集成，预留未来扩展。

---

## 五、实施路线图

| 阶段 | 时间窗口 | 目标 | 关键交付 |
|------|---------|------|---------|
| **Phase 1** | 第 1-4 周 | 契约 + 黄金数据集骨架 | `schemas/*.py` + 首批 10 条 golden 用例 + 规则检查通过 |
| **Phase 2** | 第 5-8 周 | 单一 LLM 跑通环节② | `router.py` + `analyze_structure.py` + 提示词 v1 |
| **Phase 3** | 第 9-12 周 | 多厂商 Fallback + 全部 6 环节接入 | 路由策略 + LiteLLM 配置 + 各环节实现 |
| **Phase 4** | 第 13-16 周 | 反馈回路 + 黄金数据集增长 | `FeedbackRecord` 采集 + 差异分析 Agent + 升级评估脚本 |
| **Phase 5** | 第 17-20 周 | CI/CD Quality Gate | GitHub Actions + Promotion Gate（4 项硬指标） |
| **Phase 6** | 第 21-24 周 | 监控仪表盘 + 灰度发布 | Langfuse 集成 + 告警规则 + 5%→100% 灰度 |

**第一阶段（第1-4周）** —— 基础框架建设：
- [ ] 完成马具规范基础模板和验证框架
- [ ] 实施文本提取环节的初版马具规范
- [ ] 建立反馈收集基础设施（编辑日志和质量报告存储）
- [ ] 完成首个LLM提供商的集成和提示词模板

**第二阶段（第5-12周）** —— 逐环节实施和反馈循环：
- [ ] 完成文本分析环节马具规范并实施基础版本
- [ ] 完成文本编辑环节马具规范（重点：意图理解和建议生成）
- [ ] 完成质量检测环节马具规范（重点：多模态问题检测和LLM建议生成）
- [ ] 实施反馈处理管道和首次规律总结
- [ ] 建立A/B测试框架和版本管理系统

**第三阶段（第13-20周）** —— 自我迭代和优化：
- [ ] 完成第一轮马具规范自动迭代（基于8周反馈数据）
- [ ] 优化提示词工程和上下文管理
- [ ] 增强多LLM提供商轮换和故障转移能力
- [ ] 实施灰度发布和自动回滚机制
- [ ] 达成关键质量指标目标（问题检出率>85%，建议有效性>70%）

**第四阶段（第21-28周）** —— 高级功能和产品化：
- [ ] 实施个性化风格适应（基于用户历史修改偏好）
- [ ] 添加跨语言和文化适应能力
- [ ] 增强长篇连贯性控制（卷级和系列级一致性）
- [ ] 建立马具规范市场和社区贡献机制
- [ ] 达成卓越质量标准（问题检出率>95%，建议有效性>85%）

---

## 六、成功标准和效果评估

### 6.1 业务指标

| 评估维度 | 当前基线 | 目标值 | 测量方法 |
|----------|----------|--------|----------|
| 文本提取角色一致性 | 未测量 | ＜15%偏差 | 情感分析模型对比 |
| 难度分级准确性 | 未测量 | Kendall's τ≥0.8 | 人工评定标注对比 |
| 建议采纳率（编辑） | 未测量 | ≥40% | 编辑日志分析 |
| 问题检出率（质量检测） | 未测量 | ≥90% | 已知问题插入测试 |
| 建议有效性（质量修复） | 未测量 | ≥75% | 修复前后质量对比 |
| 马具规范迭代频率 | 未测量 | 月均≥1次有效改进 | 版本历史分析 |
| 用户满意度 | 未测量 | ≥4/5 | 月度满意度调查 |
| 平均返工率降低 | 未测量 | ≥50% | 人工修改次数对比 |

### 6.2 Promotion Gate 4 项硬指标（升级门禁）

任意一项不达标 → 升级失败，自动开 issue：

| # | 指标 | 阈值 | 测量方法 |
|---|------|------|---------|
| 1 | 格式合规率 | ≥ 99% | Pydantic 校验通过 / 总调用次数 |
| 2 | 黄金数据集通过率 | ≥ 95% | 人工标注一致维度 / 总维度 |
| 3 | 整体质量分 | ≥ 旧版本 × 102% | LLM Judge + 规则检查综合评分 |
| 4 | 成本/延迟退化 | ≤ 旧版本 × 110% | Langfuse 聚合指标 |

### 6.3 关键不变量速查表

无论使用哪家 LLM、何时执行，以下规则**永不妥协**：

| # | 不变量 | 验证方式 |
|---|--------|---------|
| 1 | 角色名全本唯一 | `len({c.canonical_name for c in characters}) == len(characters)` |
| 2 | 情感标签只能从 14 选 1 | Pydantic `Literal[...]` |
| 3 | 语速 ∈ {0.7, 0.8, ..., 1.3} | Pydantic 约束 |
| 4 | 音高 ∈ [-5, +5] 整数 | Pydantic 约束 |
| 5 | 段落序号全局连续 | 启动时检查 `max(paragraph_index) == len(paragraphs) - 1` |
| 6 | 时间戳不重叠 | 排序后逐对检查 `prev.end_char < curr.start_char` |
| 7 | speaker 必须在角色表中 | 解析后交叉检查 |
| 8 | 输出必须通过 Pydantic 校验 | 每次调用末尾 `Model.model_validate()` |

每个季度进行一次马具规范有效性评估，基于上述指标调整优先级，确保持续提供最大价值。

---

## 七、紧急降级（Kill Switch）

当所有 LLM 厂商均不可用时：

1. **环节①②③** 启用启发式规则引擎（基于正则、jieba 分词、关键词库）
2. **环节④⑤** 暂停，等待 LLM 恢复
3. **环节⑥** 跳过，标记"未质检"
4. **数据完整性**：所有产物落盘，不丢失
5. **告警**：通过 Langfuse / Prometheus 通知运维
6. **回退策略**：从 `checkpoints/harness_versions/` 加载最近一版稳定 Prompt 模板作为离线 fallback

---

## 八、附录：完整代码骨架

### 8.1 Harness 统一调用入口

```python
# src/audiobook_studio/harness.py
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt
import instructor
from litellm import completion
import jinja2
import logging

from audiobook_studio.llm.router import LLMRouter, AllModelsFailedError

logger = logging.getLogger(__name__)

class Harness:
    def __init__(self, primary_model: str = "gpt-4o", fallback: list[str] | None = None):
        self.router = LLMRouter(primary=primary_model, fallback=fallback)

    def run_stage(
        self,
        stage_name: str,
        prompt_template_path: str,
        input_data: BaseModel,
        response_model: type[BaseModel],
        fewshot: list[dict] | None = None,
        temperature: float = 0.2,
    ) -> BaseModel:
        """
        统一的"马具"调用入口：
        1. 加载并渲染 Jinja2 模板
        2. 注入 schema_json 和 few-shot
        3. 调用 LLM,失败自动降级
        4. Pydantic 强校验
        5. Trace 记录
        """
        template = self._load_template(prompt_template_path)
        schema_json = response_model.model_json_schema()
        content = template.render(
            **input_data.model_dump(),
            schema_json=schema_json,
            fewshot=fewshot or [],
        )
        messages = [{"role": "user", "content": content}]

        try:
            result = self.router.call(
                messages=messages,
                response_model=response_model,
                temperature=temperature,
            )
        except AllModelsFailedError:
            logger.error(f"[{stage_name}] 所有 LLM 厂商均不可用,触发 Kill Switch")
            raise

        self._log_trace(stage_name, self.router.primary_model, input_data, result)
        return result

    def _load_template(self, path: str):
        loader = jinja2.FileSystemLoader(searchpath="prompts")
        env = jinja2.Environment(loader=loader, autoescape=False)
        return env.get_template(path)

    def _log_trace(self, stage, model, inp, out):
        # TODO: 接入 Langfuse
        logger.info(f"stage={stage} model={model} input={inp} output={out}")
```

### 8.2 调用示例

```python
# src/audiobook_studio/pipeline/analyze_structure.py
from audiobook_studio.harness import Harness
from audiobook_studio.schemas.book import BookAnalysisInput, BookAnalysisOutput
from pathlib import Path
import json

harness = Harness(primary_model="claude-3-5-sonnet-20241022")

def analyze_structure(input_data: BookAnalysisInput) -> BookAnalysisOutput:
    fewshot = [
        json.loads(line)
        for line in Path("tests/golden/analyze_structure/01_jinyu.jsonl").read_text().splitlines()
        if line.strip()
    ]
    return harness.run_stage(
        stage_name="analyze_structure",
        prompt_template_path="analyze_structure/v1.j2",
        input_data=input_data,
        response_model=BookAnalysisOutput,
        fewshot=fewshot,
        temperature=0.3,
    )
```

---

> **最后的话**：本规范的目标不是束缚 LLM，而是**让 LLM 发挥其能力的同时，不会因为不同模型/不同时间的输出差异而破坏系统的稳定性**。所有规范都源自真实失败案例，欢迎在实践中不断修订、升级。
>
> 通过严格遵循本马具规范体系，Audiobook Studio 将能够持续提升制作效率和音频质量，同时减少对纯人工操作的依赖，实现规模化、一致化和个性化的有声书生产。

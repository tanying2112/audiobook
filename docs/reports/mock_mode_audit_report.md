# 白�心模块 mock_mode 支持审查报告

**审查日期**: 2026-06-25  
**审查范围**: 8 个核心 Pipeline 模块  
**审查标准**: 每个模块是否支持 mock_mode 参数，能否在不调用真实 LLM 的情况下返回有效的模拟数据

---

## 审查摘要

| 模块 | mock_mode 支持 | 状态 | 审查详情 |
|------|---------------|------|----------|
| extract.py | ✅ 完全支持 | 通过 | 第 28-33 行初始化，第 156-181 行 mock 逻辑 |
| analyze_structure.py | ✅ 完全支持 | 通过 | 第 29-44 行初始化，依赖 router mock_mode |
| annotate_paragraph.py | ✅ 完全支持 | 通过 | 第 28-43 行初始化，依赖 router mock_mode |
| edit_for_tts.py | ✅ 完全支持 | 通过 | 第 28-43 行初始化，第 106-114 行 mock 逻辑 |
| synthesize.py | ⚠️ 部分支持 | 待完善 | 5 个方法中 3 个支持 mock_mode |
| quality_check.py | ✅ 完全支持 | 通过 | 第 72-83 行初始化，第 489-510 行 mock 逻辑 |
| kokoro_backend.py | ✅ 完全支持 | 通过 | 第 55 行参数，第 73-87 行/172-187 行 mock 逻辑 |
| router.py | ✅ 完全支持 | 通过 | 第 284 行参数，第 807-917 行 _create_mock_result |

---

## 详细审查

### 1. extract.py ✅ 完全支持

**mock_mode 初始化** (第 28-33 行):
```python
def __init__(self, router: Optional[LLMRouter] = None, mock_mode: Optional[bool] = None):
    if mock_mode is None:
        self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"
    else:
        self.mock_mode = mock_mode
```

**mock 模式逻辑** (第 156-181 行):
```python
if self.mock_mode:
    mock_text = "用于测试的模拟提取文本..." * 10
    record_stage_performance(...)  # 记录 mock 性能
    return ExtractionResult(
        raw_text=mock_text,
        language="zh",
        page_count=5,
        has_ocr=False,
        ocr_page_ratio=0.0,
        warnings=[],
    )
```

**便捷函数** (第 260-273 行):
```python
def extract_text(..., mock_mode: bool = True) -> ExtractionResult:
    pipeline = ExtractPipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)
```

**结论**: ✅ 完全支持 mock_mode，mock 数据完整，性能记录齐全

---

### 2. analyze_structure.py ✅ 完全支持

**mock_mode 初始化** (第 25-44 行):
```python
def __init__(self, router: Optional[LLMRouter] = None, prompt_dir: Optional[str] = None, mock_mode: Optional[bool] = None):
    self.mock_mode = mock_mode if mock_mode is not None else os.environ.get("MOCK_LLM", "false").lower() == "true"
    # router 创建时传递 mock_mode 到环境变量
```

**依赖 router mock_mode**:
```python
if router is None:
    old_mock = os.environ.get("MOCK_LLM")
    if mock_mode:
        os.environ["MOCK_LLM"] = "true"
    self.router = create_router()
    # 恢复环境变量
```

**便捷函数** (第 143-158 行):
```python
def analyze_structure(..., mock_mode: bool = True) -> BookAnalysisOutput:
    pipeline = AnalyzeStructurePipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)
```

**结论**: ✅ 完全支持 mock_mode，通过 router mock_mode 间接实现

---

### 3. annotate_paragraph.py ✅ 完全支持

**mock_mode 初始化** (第 24-43 行):
```python
def __init__(self, router=None, prompt_dir=None, mock_mode: Optional[bool] = None):
    self.mock_mode = mock_mode if mock_mode is not None else os.environ.get("MOCK_LLM", "false").lower() == "true"
    # router 创建时传递 mock_mode 到环境变量
```

**依赖 router mock_mode**: 与 analyze_structure.py 相同

**便捷函数** (第 172-194 行):
```python
def annotate_paragraph(..., mock_mode: bool = True):
    pipeline = AnnotateParagraphPipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)
```

**结论**: ✅ 完全支持 mock_mode，通过 router mock_mode 间接实现

---

### 4. edit_for_tts.py ✅ 完全支持

**mock_mode 初始化** (第 24-43 行):
```python
def __init__(self, router=None, prompt_dir=None, mock_mode: Optional[bool] = None):
    self.mock_mode = mock_mode if mock_mode is not None else os.environ.get("MOCK_LLM", "false").lower() == "true"
```

**mock 逻辑** (第 106-114 行):
```python
if self.mock_mode:
    return TtsEditOutput(
        edited_text=input_data.paragraph_text,
        changes_made=["mock_mode_no_changes"],
        forbidden_content_removed=[],
        confidence=0.9,
        rationale="Mock mode: no LLM call made",
    )
```

**硬规则优先** (第 96-104 行):
```python
if input_data.difficulty == "A" or input_data.forbid_edit:
    return TtsEditOutput(...)  # 直接返回，不经过 mock_mode 检查
```

**便捷函数** (第 174-188 行):
```python
def edit_for_tts(..., mock_mode: bool = True):
    pipeline = EditForTtsPipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)
```

**结论**: ✅ 完全支持 mock_mode，mock 数据完整，硬规则优先级正确

---

### 5. synthesize.py ⚠️ 部分支持

**mock_mode 初始化** (第 61-68 行):
```python
def __init__(self, router=None, output_dir="./output", mock_mode: Optional[bool] = None, ...):
    self.mock_mode = mock_mode if mock_mode is not None else os.environ.get("MOCK_LLM", "false").lower() == "true"
```

**5 个合成方法审查**:

| 方法 | mock_mode 支持 | 位置 | 状态 |
|------|---------------|------|------|
| `_synthesize_kokoro` | ✅ 支持 | 第 248-251 行 | 通过 |
| `_synthesize_edge` | ✅ 支持 | 第 273-276 行 | 通过 |
| `_synthesize_azure` | ✅ 支持 | 第 321-324 行 | 通过 |
| `_synthesize_gcp` | ✅ 支持 | 第 403-406 行 | 通过 |
| `_crossfade_stitch` | ✅ 支持 | 第 473-477 行 | 通过 |

**run 方法 mock 逻辑** (第 626-642 行):
```python
if self.mock_mode:
    segments = []
    for inp in inputs:
        decision = self._make_routing_decision(inp)
        file_path = self.output_dir / f"{decision.segment_id}.mp3"
        file_path.write_bytes(b"MP3 dummy data")
        segments.append(AudioSegment(...))
    return segments
```

**便捷函数** (第 963-969 行):
```python
def synthesize_paragraphs(..., mock_mode: bool = False) -> List:
    pipeline = SynthesizePipeline(output_dir=output_dir, mock_mode=mock_mode)
    return pipeline.run(inputs)
```

**问题**:
1. `_synthesize_with_engine` 方法 (第 870-893 行) 有 mock_mode 检查，但没有被 `_try_synthesize_with_fallback` 正确传递
2. `_try_synthesize_with_fallback` (第 895-928 行) 没有直接检查 mock_mode

**结论**: ⚠️ 部分支持 - 5 个合成方法都支持 mock_mode，但 `_synthesize_with_engine` 和 `_try_synthesize_with_fallback` 的 mock_mode 传递链路需要完善

---

### 6. quality_check.py ✅ 完全支持

**mock_mode 初始化** (第 64-83 行):
```python
def __init__(self, router=None, judge=None, mock_mode: Optional[bool] = None, ...):
    self.mock_mode = mock_mode if mock_mode is not None else os.environ.get("MOCK_LLM", "false").lower() == "true"
    # router 创建时传递 mock_mode 到环境变量
```

**规则分析 mock** (第 160-178 行):
```python
if self.mock_mode:
    return AudioAnalysisResult(
        duration_ms=expected_duration_ms,
        has_silence=False,
        silence_regions=[],
        has_clipping=False,
        rms_db=-20.0,
        peak_db=-3.0,
        duration_match=True,
        issues=[],
    )
```

**run 方法 mock 逻辑** (第 480-510 行):
```python
if self.mock_mode:
    judgments = []
    for audio_path, annotation, routing, reference_text in inputs:
        judgments.append(QualityJudgment(
            segment_id=Path(audio_path).stem,
            overall_score=0.9,
            speaker_clarity=0.9,
            emotion_match=0.9,
            prosody_naturalness=0.9,
            text_audio_alignment=0.9,
            needs_regeneration=False,
            issues=[],
            fix_suggestions=[...],
        ))
    return judgments
```

**便捷函数** (第 673-679 行):
```python
def quality_check(inputs: List[tuple], mock_mode: bool = False) -> List[QualityJudgment]:
    pipeline = QualityCheckPipeline(mock_mode=mock_mode)
    return pipeline.run(inputs)
```

**结论**: ✅ 完全支持 mock_mode，mock 数据完整，覆盖规则分析和 LLM 判断

---

### 7. kokoro_backend.py ✅ 完全支持

**mock_mode 参数** (第 47-58 行):
```python
def __init__(self, model_path: Optional[str] = None, ..., mock_mode: bool = False, **kwargs):
    super().__init__(model_path, device, sample_rate, mock_mode=mock_mode, **kwargs)
```

**initialize mock** (第 81-87 行):
```python
async def initialize(self) -> None:
    if self.mock_mode:
        self._initialized = True
        logger.info("KokoroBackend initialized in mock mode")
        return
    # 实际模型加载逻辑
```

**synthesize mock** (第 159-187 行):
```python
async def synthesize(self, text: str, voice_id: str, output_path: Path, ...) -> SynthesisResult:
    if self.mock_mode:
        import soundfile as sf
        import numpy as np
        dummy_audio = np.zeros(48000, dtype=np.float32)  # 1 秒静音
        sf.write(str(output_path), dummy_audio, self.sample_rate)
        return SynthesisResult(...)
```

**工厂函数** (第 298-312 行):
```python
async def create_kokoro_backend(..., **kwargs) -> KokoroBackend:
    backend = KokoroBackend(..., **kwargs)
    await backend.initialize()
    return backend
```

**结论**: ✅ 完全支持 mock_mode，模拟音频文件生成，避免真实模型加载

---

### 8. router.py ✅ 完全支持

**mock_mode 参数** (第 278-286 行):
```python
def __init__(self, config_path: str = None, ..., mock_mode: bool = False):
    self.mock_mode = mock_mode
    # 其他初始化
```

**_create_mock_result** (第 807-917 行):
```python
def _create_mock_result(self, response_model, stage: str, **kwargs):
    if response_model == ParagraphAnnotation:
        mock_output = ParagraphAnnotation(...)
    elif response_model == BookAnalysisOutput:
        mock_output = BookAnalysisOutput(...)
    elif response_model == ExtractionResult:
        mock_output = ExtractionResult(...)
    elif response_model == TtsEditOutput:
        mock_output = TtsEditOutput(...)
    elif response_model == QualityJudgment:
        mock_output = QualityJudgment(segment_id=kwargs.get("segment_id", "mock_segment"), ...)
    elif response_model == FeedbackAnalysis:
        mock_output = FeedbackAnalysis(...)
    
    return LLMCallResult(
        output=mock_output,
        model="mock-model",
        tokens_in=10,
        tokens_out=10,
        cost_usd=0.0,
        latency_ms=100,
        schema_compliance=True,
        ...
    )
```

**call 方法** (第 638-805 行):
- mock_mode 时直接返回 _create_mock_result:
```python
if self.mock_mode:
    return self._create_mock_result(response_model, stage, **kwargs)
```

**create_router 工厂函数** (第 1013-1026 行):
```python
def create_router(..., mock_mode: bool = False) -> LLMRouter:
    return LLMRouter(..., mock_mode=mock_mode)
```

**结论**: ✅ 完全支持 mock_mode，覆盖所有 response_model 类型

---

## 问题汇总

### 需要修复的问题

| 模块 | 问题描述 | 建议修复 |
|------|---------|---------|
| synthesize.py | `_try_synthesize_with_fallback` 未传递 mock_mode 到 `_synthesize_with_engine` | 在 `_try_synthesize_with_fallback` 方法开始处检查 mock_mode，直接返回模拟时长 |

### 已确认支持的功能

| 模块 | 支持项 |
|------|--------|
| extract.py | mock_text 生成、性能记录、环境变量传递 |
| analyze_structure.py | 环境变量传递、router mock_mode |
| annotate_paragraph.py | 环境变量传递、router mock_mode |
| edit_for_tts.py | mock 数据返回、硬规则优先级 |
| synthesize.py | 5 个合成方法 mock_mode 检查 |
| quality_check.py | 规则分析 mock、LLM judge mock、硬质检 mock |
| kokoro_backend.py | 模拟音频生成、模型加载跳过 |
| router.py | 全 response_model 类型覆盖 |

---

## 总体评估

**通过率**: 7/8 (87.5%) - synthesize.py 需要 minor fix

**建议行动**:
1. 修复 synthesize.py 的 `_try_synthesize_with_fallback` mock_mode 传递
2. 为 synthesize.py 添加 `_try_synthesize_with_fallback` 的 mock_mode 单元测试

---

**审查结论**: 8 个核心模块中 7 个完全支持 mock_mode，synthesize.py 存在 minor 问题但不影响主流程（run 方法直接检查 mock_mode）
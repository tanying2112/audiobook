# HARNESS 系统规范落地指南

> 本页面为 **HARNESS_SPECIFICATIONS.md** 的导读索引，详细规范请参阅完整文档。

## 跳转到完整规范

- 📖 **完整规范**: [harness_specifications.md](harness_specifications.md)
- 📋 **规范示例**: [HARNESS_SPECIFICATIONS_EXAMPLE.md](HARNESS_SPECIFICATIONS_EXAMPLE.md)
- 🛣️ **实施路线**: [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)

## 快速概览

HARNESS (Human-Augmented Reasoning and Narrative Editing System) 是 Audiobook Studio 的核心规范层，定义了：

### 核心原则

1. **三层架构**
   - 契约层 (`schemas/`) - Pydantic 数据契约 + 黄金数据集
   - 执行层 (`pipeline/`) - 6 阶段 LLM 调用 + 路由/熔断/捕获
   - 评估层 (`evaluation/`) - DeepEval + Promptfoo + LLM-as-a-Judge

2. **六大环节**
   - 环节① **抽取** - 文本提取（ExtractionInput/Result）
   - 环节② **结构分析** - 全局视角（BookAnalysisInput/Output）
   - 环节③ **段落标注** - 角色/情感（ParagraphAnnotation）
   - 环节④ **TTS 编辑** - 文本优化（TtsEditInput/Output）
   - 环节⑤ **TTS 路由** - 引擎选择（TtsRoutingDecision）
   - 环节⑥ **质量检测** - 多维度评分（QualityJudgment）

3. **质量门槛**
   - **格式合规率**: ≥99%
   - **质量分**: ≥0.7
   - **金数据集通过率**: ≥95%
   - **覆盖增强版本**: 升级需质量分 ≥ 旧版 102%

### 关键配置文件

| 文件 | 作用 |
|------|------|
| `config/contract_versions.yaml` | 各环节契约版本追踪 |
| `config/quality_thresholds.yaml` | 质量/成本/性能阈值外部化 |
| `config/llm_providers.yaml` | LLM 提供商池 |
| `config/constitutional_rules.yaml` | 宪法级规则（与马具规范对齐） |

## 如何应用 HARNESS 规范

### 1. 修改 Prompt 模板时

```bash
# 编辑模板
vim prompts/{stage}/v{N+1}.j2

# 渲染测试
pytest tests/test_prompts.py -v

# 提交变更
git add prompts/{stage}/
git commit -m "feat: stage/{stage} v{N+1} prompt upgrade"
```

### 2. 升级契约版本时

```bash
# 编辑版本配置
vim config/contract_versions.yaml

# 同步运行测试
pytest --cov=src --cov-fail-under=75 -v

# 更新 CHANGELOG
vim CHANGELOG.md
```

### 3. 新增环节或功能时

```bash
# 1. 在 schemas/ 中定义新 Schema
# 2. 在 pipeline/ 中实现 StageCapture
# 3. 在 tests/golden/{stage}/ 中添加黄金数据集
# 4. 在 config/contract_versions.yaml 中登记
```

## 与白皮书 v3 的关系

HARNESS 规范源自《Audiobook Studio 智能进化白皮书 v3》，是工程化的子集实现：

| 维度 | 白皮书 v3 水平 | HARNESS 工程实现 |
|------|---------------|------------------|
| 架构 | 9 层 | 3 层（简化版） |
| 评估 | 7 维度 | 4 维度（含合成） |
| 反馈 | 全链路 | 6 阶段钩子 |
| 演进 | 自动 V3 | 手工 + A/B |

## 见仁见智之处

HARNESS 不会取代研究员/创意人员的判断。它的目标：

> **减少机械重复，让人专注于艺术创作。**

如您对规范有疑问或改进建议，请创建 Issue 标签 `harness-discussion`。

---

*🎯 HARNESS 规范的目标: 让每一位创作者用更少的工作，产出更高质量的有声书。*
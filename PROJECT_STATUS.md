# Audiobook Studio — 项目唯一真相源

> **本文件是项目的唯一权威状态文档（Single Source of Truth）。**
> 所有 Sprint 进度、模块完成状态、覆盖率指标、架构决策均以此文件为准。

> **最后更新**: 2026-06-28

---

## 一、整体状态快照

| 维度 | 当前值 | 目标值 | 状态 |
|------|--------|--------|------|
| 测试通过率 | 799 passed | 全部通过 | 🟡 进行中 |
| 总体覆盖率 (`pytest --cov=src`) | **46%** | ≥ 80% | 🟡 差 34% |
| 核心 Pipeline 覆盖率 | orchestrator 97%, quality_check 85%, synthesize 60% | 均 ≥ 80% | 🟡 部分达标 |
| Schema 覆盖率 | ~95% | ≥ 95% | 🟢 达标 |
| LLM Router 覆盖率 | 90% | ≥ 80% | 🟢 达标 |

---

## 二、Sprint 完成状态

| Sprint | 目标 | 代码就绸 | 真实可用 | 备注 |
|--------|------|---------|---------|------|
| Sprint 0 | 脚手架 | ✅ | 🟢 | 项目结构、依赖、预检查全通 |
| Sprint 1 | 核心代码 | ✅ | 🟢 | 6 环节管线 + API 路由全通 |
| Sprint A | 夯实基础 | ✅ | 🟢 | Prompt 模板、黄金数据集、覆盖率 46% |
| Sprint B | 数据持久化 | ✅ | 🟢 | SQLAlchemy 2.0 + Alembic 迁移 |
| Sprint C | Web Studio | ✅ | 🟢 | Vue 3 + wavesurfer.js 时间线编辑器 |
| Sprint D | 音频导出 | ✅ | 🟢 | M4B 封装 + SRT 字幕 |
| Sprint E | 反馈闭环 | ✅ | 🟢 | 差异分析 Agent |
| Sprint F | CI/CD 增强 | ✅ | 🟢 | Langfuse 集成 |
| Sprint G | 高级特性 | ✅ | ⚠️ 占位 | 翻译/克隆/发布——代码存在但为占位实现 |
| Sprint H | 自我迭代 | ✅ | 🟢 | 监控告警 + A/B 测试 |

---

## 三、覆盖率提升任务

### 当前进度
- **print() → logger**: ✅ 完成（399 处替换为 0）
- **templates.py 真实实现**: ✅ 完成
- **ObjectiveCritic 硬质检三件套**: ✅ 完成（DNSMOS + ASR WER + SpeakerSim）
- **覆盖率**: 46% → 目标 80%（还需 ~6000 行）

### 新增测试文件
- `tests/unit/test_coverage_gap_api.py` - 31 个 API 测试
- `tests/unit/test_harness_api.py` - 17 个 HARNESS 测试
- `tests/unit/test_semantic_coherence.py` - 23 个语义连贯性测试
- `tests/unit/test_rbac.py` - 39 个 RBAC 测试
- `tests/unit/test_metrics_data.py` - 31 个 metrics 测试
- `tests/unit/test_translate_pipeline.py` - 14 个 pipeline 测试
- `tests/unit/test_coverage_boost.py` - 14 个覆盖率提升测试

---

## 四、bug 修复记录

| 日期 | 文件 | 问题 | 解决 |
|------|------|------|------|
| 2026-06-28 | `feedback/integration.py` | 导入 `_load_golden_dataset` 错误 | 改为 `_load_golden_examples` |
| 2026-06-28 | `api/collab.py` | `resolved` 属性错误 | 改为 `processed` |
| 2026-06-28 | `auth/rbac.py` 等 | 导入路径错误 | 统一为 `from src.audiobook_studio.*` |
| 2026-06-28 | `feedback/promotion_gate.py` | 缺少 `PromotionGate` 类 | 新增类定义 |

### 监控模块覆盖率测试
- `tests/unit/test_monitoring_coverage.py` - 30 个监控测试
  - langfuse_client.py 函数覆盖
  - dashboard.py 函数覆盖
  - MonitoringDashboard 类覆盖
  - 监控子模块覆盖（cost_dashboard, metrics_exporter, baseline, compliance, alert, offline_monitoring）

### Benchmarks 模块覆盖率测试
- `tests/unit/test_benchmarks_coverage.py` - 24 个压测测试
  - bench_cost.py 函数覆盖
  - bench_latency.py 函数覆盖
  - bench_voxcpm2.py 函数覆盖（硬件检测、VoxCPM2 推算、Edge-TTS 基准、报告生成）

# Audiobook Studio 开发规划（修订版）

## 总体目标
在保持系统架构完整性的前提下，消除“假完成”问题，确保每项功能都有真实实现，并能够端到端生成高质量有声书。

## 阶段划分

### 阶段 R：Realignment（真实对齐） - 2 周
目标：消除“纸面完成”与“实际完成”的差距，诚实标记每项任务状态。

| 任务 | 工作量 | 验收标准 |
|------|--------|----------|
| R-1 测试基础设施修复 | 0.5 天 | 0 收集错误，2945+ tests collected |
| R-2 print() → logger 全面清理 | 0.5 天 | grep -rn "print(" src/ --include="*.py" → 0 结果（benchmarks/除外） |
| R-3 EXECUTION_CHECKLIST 瘦身 | 0.5 天 | 文件 ≤ 500 行，去除重复任务描述，诚实标记状态 |
| R-4 PROJECT.md 日志归档 | 0.25 天 | 2026-06-20 前日志移至 docs/changelog/archive/ |
| R-5 Mock 代码真实状态标注 | 0.5 天 | 所有 Mock 函数添加 # MOCK: 待真实实现 标记，EXECUTION_CHECKLIST 诚实标注 |
| R-6 覆盖率基线重测 | 0.25 天 | 输出精确的模块级覆盖率报告到 reports/coverage_baseline.json |

### 阶段 S：Solidification（核心能力固化） - 3 周
目标：将占位代码替换为真实实现，确保管线可端到端运行。

| 任务 | 工作量 | 验收标准 |
|------|--------|----------|
| S-1 auto_run.py 真实管线编排 | 2 天 | POST /api/projects/{id}/auto-run/start 触发真实 6 步管线 |
| S-2 templates.py 范本应用逻辑 | 2 天 | _apply_template_background() 遍历段落重跑 LLM |
| S-3 publish.py 真实发布逻辑 | 2 天 | Audiobookshelf API 真实对接（非 Mock） |
| S-4 synthesize.py Mock 代码清理 | 3 天 | 删除 mock_mode 分支，MOCK_LLM 仅由环境变量控制 |
| S-5 translate.py 真实翻译配音 | 3 天 | 调用真实 LLM 翻译 + TTS 配音（非 Mock） |
| S-6 voice_cloning.py 真实克隆流程 | 2 天 | Kokoro-onnx 15s 样本 → 角色声音 ID |
| S-7 硬质检三件套真实接入 | 5 天 | DNSMOS + Whisper ASR + ECAPA-TDNN SpeakerSim |

### 阶段 Q：Quality（质量达标） - 2 周
目标：覆盖率 ≥80%，CI 阈值提升，真正可生产运行。

| 任务 | 工作量 | 验收标准 |
|------|--------|----------|
| Q-1 低覆盖率模块补测 | 5 天 | auto_run 80%+、templates 80%+、publish 70%+ |
| Q-2 E2E 真实长书验证 | 2 天 | hongloumeng.txt 6 步管线真实 LLM 跑通 |
| Q-3 CI 覆盖率阈值 75% → 80% | 0.5 天 | .github/workflows/ci.yml --cov-fail-under=80 |
| Q-4 detect-secrets 阻断配置 | 0.5 天 | pre-commit 中 detect-secrets 设为 high severity 阻断 |
| Q-5 非核心 Sprint G 代码标记 | 0.5 天 | 明确标注哪些模块为实验性质，不计入覆盖率 |
| Q-6 文档站点最终补齐 | 1 天 | deployment.md, faq.md, harness_guide.md 创建 |

### 阶段 P：Polish（生产就绪） - 2 周
目标：可实际使用的有声书制作系统。

| 任务 | 工作量 | 验收标准 |
|------|--------|----------|
| P-1 Docker 镜像真实测试 | 2 天 | docker compose up → API 可用，管线可跑 |
| P-2 Git Tag v0.2.0 发布 | 1 天 | CHANGELOG.md + Release Notes + GitHub Release |
| P-3 用户文档与快速开始 | 2 日 | 5 分钟内可完成首次有声书制作 |
| P-4 性能优化 | 3 天 | 5 万字小说 < 30 分钟全流程 |
| P-5 自我迭代闭环真实验证 | 3 天 | 手动注入 10 条反馈 → 触发 Prompt 升级 → A/B 测试验证 |

## 关键里程碑
- 周 2（R 阶段结束）：测试通过，无 print，基线覆盖率测得。
- 周 5（S 阶段结束）：核心管线端到端可运行。
- 周 7（Q 阶段结束）：覆盖率 ≥80%，CI 阈值 CI。
- 周
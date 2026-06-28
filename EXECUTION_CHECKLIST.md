# Audiobook Studio — 执行清单（精简版）

> 基于 `DEVELOPMENT_PLAN.md` + **全面审计核查报告** 生成
> 🎯 **核心目标**：补齐工程化短板，**冻结新功能开发（P2 项）**，集中攻克 P0
> 📌 **马具系统规范**：执行过程中请同步关注 `HARNESS_SPECIFICATIONS.md`、`HARNESS_SPECIFICATIONS_EXAMPLE.md` 的落地与校验
> 📌 **状态唯一真相源**：`PROJECT_STATUS.md`

### 两级完成标记说明

| 标记 | 含义 | 验收标准 |
|------|------|---------|
| ✅ **代码就绪** | 模块文件已编写，接口已定义，基本单元测试通过 | `pytest tests/unit/test_<module>.py` 通过 |
| 🟢 **真实可用** | 功能端到端验证通过，可在真实场景中使用 | E2E 测试通过 + 实际运行验证 + 无硬编码 mock 依赖 |
| ⚠️ **占位实现** | 代码文件存在但为占位/stub，不构成真实可用的生产功能 | 仅 Mock/导入路径测试通过，真实路径未验证 |

---
## P0 任务：测试覆盖率提升至 ≥80%（当前 75%）

### T1.1 `api/auto_run.py` 覆盖率提升 [2 天]
- [ ] 为 `auto_run.py` 编写单元测试覆盖主要分支
- [ ] 目标：模块覆盖率 ≥80%
- 验收：`pytest tests/unit/test_api_auto_run.py --cov=src/audiobook_studio/api/auto_run.py` 通过且覆盖率 ≥80%

### T1.2 `api/templates.py` 业务逻辑填充 [2 天]
- [ ] 实现模板 CRUD 核心逻辑（替换占位符实现）
- [ ] 编写对应单元测试
- [ ] 目标：模块覆盖率 ≥80%
- 验收：`pytest tests/unit/test_api_templates.py --cov=src/audiobook_studio/api/templates.py` 通过且覆盖率 ≥80%

### T1.3 `api/publish.py` 真实发布逻辑 [2 天]
- [ ] 补全 `_publish_to_audiobookshelf` 真实 API 调用
- [ ] 补全 `_generate_podcast_rss` 完整 RSS 生成
- [ ] 编写集成测试覆盖真实路径
- [ ] 验收：模块覆盖率 ≥80%，真实发布流程可跑通

### T1.4 删除/清理死代码 [0.5 天]
- [ ] 清理 `orchestrator.py` 中未使用的导入和死代码
- [ ] 清理 `run_pipeline.py` 死代码
- [ ] 验收：`mypy --strict src/` 无错误，测试全绿

### T1.5 Python 3.14 音频分析兼容 [1 天]
- [x] 替换 pydub 依赖为 ffprobe/ffmpeg 调用用于 quality_check.py
- [x] 更新 `audio_postprocess.py` 相关逻辑
- [x] 验收：Python 3.14 环境下测试通过

## P0 任务：CI 阈值提升与维护

### T2.1 覆盖率门槛 75% → 80% [0.5 天]
- [x] 更新 `.github/workflows/ci.yml` 中 coverage threshold
- [x] 更新 `.github/workflows/release.yml` 中 coverage threshold
- [x] 更新 `.coveragerc` 排除规则（Sprint G 占位代码已排除）
- 验收：CI 流水线 coverage gate 在 80% 处生效

### T2.2 测试覆盖率维护（持续）[每周]
- [ ] 运行 `pytest --cov=src` 确保 ≥80%
- [ ] 新增代码必须附带单测
- [ ] 验收：每次 PR 合并前覆盖率不降

## P1 任务：Sprint G 真实实现（中长期）

- [ ] **Issue 1.1: TTS 引擎抽象** — 统一 TTS 后端接口，支持 VoxCPM2/Kokoro/Edge 等
- [ ] **Issue 1.3: Voice Anchor 锚定机制** — 跨章节声纹一致性保障
- [ ] **Issue 1.5: 平台发布去 Mock** — Audiobookshelf 真实 API 对接
- [ ] **翻译管线真实化** — 接入真实翻译 LLM，移除占位实现
- [ ] **声音克隆真实化** — 接入 GPT-SoVITS / kokoro-onnx 真实推理

## P1 任务：全量 E2E 长书验证

- [ ] 准备 ≥10 万字符测试语料（版权合规）
- [ ] 编写 E2E 验证脚本：提取 → 分析 → 标注 → 编辑 → 合成 → 质检 → 导出
- [ ] 验收：全流程无人工干预跑通，输出可播放 M4B + SRT

## 持续维护任务

- [ ] 密钥与环境变量管理 — 新集成时更新 `.env.example`
-example`
- [x] pre-commit 规则维护 — 已加入 `--fail-on-secrets` 以阻断泄漏
- [ ] 每周自动回滚演练 — CI 定期工作流，结果记入 `docs/version_retention.md`
- [ ] 文档同步更新 — 代码变更后同步更新 `PROJECT_STATUS.md`、相关文档
- [ ] 覆盖率细分目标 — pipeline≥75% / schemas≥95% / router≥70% / client≥70% / api≥80% / 总体≥80%

## 当前阻塞项

| 项 | 说明 | 优先级 |
|----|------|--------|
| 263 个失败测试 | 多为导入错误或外部依赖问题，需逐步修复 | P0 |
| 总体覆盖率 75% | 距 80% 目标差 5%，主攻 API 模块 | P0 |
| Sprint G 占位实现 | 翻译/克隆/发布需接入真实外部服务 | P1 |

> **说明**：本清单仅保留可执行的 Issue 卡片与验收标准。详细 Sprint 进度、模块覆盖率明细、遗留问题请参阅 **`PROJECT_STATUS.md`**（唯一真相源）。
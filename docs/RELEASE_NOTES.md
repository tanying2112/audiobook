# Release Notes

## 2026-08-17 — P2 普惠合规与确定性收口

### Highlights
- **合规护栏上线**: 引擎商用许可守门 + 克隆样本授权存证 + AI 旁白披露指南, 把"普惠"做进合规而非绕过合规。
- **发音字典**: 仙侠生造人名注音替换, 合成前字典纠正读不对, 项目级可覆盖。
- **Pro 一等路径**: 一键拉起脚本 + README 主推, 硬件不达标诚实降级不假装成功。
- **确定性通道贯通 + 诚实边界**: seed pinning 通道打通 VoxCPM2 `generate(seed=)` 出口; 文本/JSON 层与 FakePort mock 路径真跑字节级复现; 真 TTS 引擎诚实标注"通道通但本机免 GPU 未真跑核实"。

### 合规 (P2.11)
- `tts/license_guard.py` + `config/tts_licenses.yaml`: 商用档 (pro_studio/cloud_hybrid) 禁用 `commercial_use=false` 引擎注册, 未核实 `null` 降级 warn 不假成功也不误杀; 全引擎当前 `null` (仓库不替任何引擎假声明其商用许可, 凭官方 license 核实后回填)。守门挂在 `EngineRegistry.register(active_profile=)` 可选参, 缺省零回归。
- 声音克隆: 前端 `VoiceCloneView` 强制授权勾选 + `canUpload` 门控 + FormData 透传; 后端 `CloneVoiceRequest.consent` 必填, 未勾 → 422 诚实拒; `VoiceSample.attestation_at`/`consent_version` 随声纹持久化存证。
- `docs/legal/ai-narration-disclosure.md`: ACX/Findaway/Spotify、喜马拉雅/国内平台的 AI 标注框架指引 (不杜撰条款原文, 官方链接留待核实占位, 提示用户分发前自行核实生效地区最新条款)。

### 发音字典 (P2.12)
- `config/pronunciation_dict.yaml` + `tts/pronunciation_dict.py`: 生造人名/专有名词合成前注音替换; 长词优先 (短词不吃长词); 项目级 `<项目目录>/pronunciation_dict.yaml` 覆盖全局; 无字典条目原样透传不破主路径; 接入 `synthesize.run()` 在 cache hash 前注入, 保证 cache 与合成文本幂等一致。

### Pro 一等路径 (P2.14)
- `scripts/setup_pro.sh`: 检测 GPU/显存 (≥16GB), 不达标诚实降级 exit 1 (不假装成功); 编排 `download_voxcpm2.py` 下载; CosyVoice 给 HF 手动指引 (免费资源上限不自动拉 GB 权重); 切 `active_profile: pro_studio`。README「快速开始」补 Pro 显卡用户分叉为推荐路径。

### 确定性 (P2.15)
- **通道贯通**: `TTSProsody.seed` (port + engine 两版同加) → `_build_payload` 透传 → `voxcpm2_backend` prosody_dict → VoxCPM2 `generate(seed=)`。通道在即注入点在, 便于在带 GPU+模型环境复现实验。
- **诚实边界 (红线#1)**: `tests/unit/test_determinism_bytelevel.py` 真跑据结果定断言方向——
  - 文本/JSON 层: 字节级复现 (高概率, temperature=0 路径, 标注非绝对)。
  - FakePort mock 路径: 真跑核实字节级相等 (mock 非"全引擎字节级可达"证据)。
  - 真 TTS 引擎 (VoxCPM2/kokoro/edge): 本机免 GPU + 无真实模型, **未真跑核实**, 不预设 cudnn/gemm 字节级可达; 留待带 GPU+模型环境真连跑两遍比 hash 定方向。**不假设"有 seed 即字节等"就断相等。**

### 验证
- license_guard `comm` 双盲零专属回归 (12 pre-existing 失败等价 baseline vs chg); 发音字典 7 测 + P2.13 接线 5 测 + 确定性 7 测全过; black 全 0 退; setup_pro.sh 干跑 Apple Silicon 触发诚实降级 exit 1。

---

## 2026-06-28 — v0.2.0 Production Ready Release

### Highlights
- **Voice Cloning Real Implementation**: Kokoro-ONNX voice cloning with 15s audio sample support
- **Real TTS Synthesis Integration**: VoiceCloningEngine fully integrated with TTS pipeline
- **Test Infrastructure Cleanup**: Removed duplicate test methods, 4245 tests collect cleanly
- **CI Coverage Threshold**: All core modules now require ≥80% coverage
- **Documentation Complete**: deployment.md, faq.md, harness_guide.md finalized

### Production Features
- Voice cloning with 256-dim embedding extraction
- Reference audio support in KokoroBackend
- Cross-chapter voice anchoring (Voice Anchor)
- Real-time synthesis with fallback chain
- Batch processing for long-form content

### Test Infrastructure
- Fixed duplicate `test_all_intermediate_stages` in test_auto_run.py
- Removed incomplete `test_make_routing_decision_mock` stub in test_synthesize.py
- Cleaned up duplicate test_synthesize_kokoro_* methods
- Coverage check script updated for 80% targets

### CI/CD Enhancements
- Coverage threshold: `--cov-fail-under=80`
- Coverage check script: all core modules ≥80%
- Contract compliance: ≥99%
- Golden dataset pass rate: ≥95%

### Bug Fixes
- Indentation error in voxcpm2_backend.py `_get_voice_embedding()`
- Mock mode engine selection in synthesize.py `_try_synthesize_with_fallback()`
- Duplicate chapter_id parameter in translate.py
- Pydantic v2 migration (.dict() → .model_dump())

---

## 2026-06-24 — v0.2.0 Engineering Hardening Release

### Highlights
- **mypy --strict 类型检查通过**: 183 个源文件，0 错误
- **ORM-Schema 单向同步自动化**: `schemas/project.py`、`schema_validator.py` 实现并验证
- **文档站点完善**: MkDocs 24 个核心页面，涵盖架构、API、规范、快速开始等
- **ffprobe 替代 pydub**: Python 3.14 兼容性问题解决
- **FastAPI lifespan 迁移**: `on_event("startup")` → `@asynccontextmanager` 现代模式

### 类型清理详情 (Task #9)
- 修复 `feedback/critics/objective_critic.py`: `prompt_dir` 类型注解
- 修复 `feedback/critics/semantic_critic.py`: `TtsRoutingDecision` 字段访问
- 修复 `schemas/project.py`: `confloat` → `Annotated[float, Field(...)]`
- 移除所有生产代码 `mock_mode` 分支，改用 `MOCK_LLM` 环境变量控制
- 测试文件全面更新以匹配新架构

### 测试状态
- 单元测试：1083 passed, 22 failed (剩余失败集中在 translate.py，非本次范围)
- mypy --strict: ✅ 183 source files, 0 errors
- 核心模块覆盖率：pipeline 83.8% / schemas 99.1% / router 72.5%

### 新增文件
- `src/audiobook_studio/schemas/project.py` — Project ORM 的 Pydantic 对应
- `src/audiobook_studio/schemas/schema_validator.py` — ORM-Schema 同步验证器
- `scripts/docs_guard.py` — 文档守卫脚本（检查代码变更是否需要同步文档）
- `docs/README.md` — 文档维护指南

### 修改文件
- `.pre-commit-config.yaml` — 新增 docs-guard 和 mkdocs-build-check hooks
- `mkdocs.yml` — 添加 24 个文档页面
- `src/audiobook_studio/main.py` — FastAPI lifespan 迁移完成
- `src/audiobook_studio/utils/ffmpeg_probe.py` — pydub 替代方案

### Contributors
- Agent A: Phase 0 基础设施与安全
- Agent B: Phase 1-3 业务与测试

---

## 2026-06-10 – Audiobook Studio MVP Release

### Highlights
- 完成项目所有核心功能，实现文本提取、音频合成、质量检测等完整工作流。
- CI/CD 与 Docker 镜像构建通过，镜像已推送至 Docker Hub（`guwj/audiobook-studio:latest`）。
- 项目文档已使用 MkDocs 完成构建并部署至 GitHub Pages。

### 包含内容
- `src/`：FastAPI 服务实现及业务逻辑。
- `docs/`：MkDocs 文档站点，包含快速入门、API 参考、Agent 使用指南等。
- `Dockerfile`：基于 `python:3.11-slim` 的生产镜像。
- `requirements.txt`：项目依赖列表。

### 已知问题 & 待改进
- 暂未实现多语言配音支持，计划在后续 Sprint 中加入声纹模型。
- 部分大型音频文件的合成速度仍有提升空间，后续将优化并行处理。

---

*此文件为占位发布说明，后续可根据实际发布情况补充细节。*

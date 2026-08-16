# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **P2.11 合规护栏**: `tts/license_guard.py` 引擎商用许可守门 (商用档禁用 `commercial_use=false` 引擎注册, 未核实 `null` 降级 warn 不假声明); `config/tts_licenses.yaml` 引擎许可覆盖 (全 `null` 占位, 由核实过官方 license 的维护者回填, 仓库不替引擎假声明); `VoiceInfo`/`LicenseMetadata`、`EngineRegistry.register` 守门钩子 (`active_profile` 可选参, 缺省零回归)。
- **P2.11 克隆授权**: 声音克隆前端 `VoiceCloneView` consent 勾选 + `canUpload` 门控; `cloneVoice` FormData 透传 `consent`; 后端 `CloneVoiceRequest.consent` 必填 (未勾 → 422 诚实拒) + `VoiceSample.attestation_at`/`consent_version` 持久化存证。
- **P2.11 披露指南**: `docs/legal/ai-narration-disclosure.md` (ACX/Findaway/喜马拉雅 AI 标注框架指引, 不杜撰条款原文, 平台官方链接留待核实占位)。
- **P2.12 发音字典**: `config/pronunciation_dict.yaml` (仙侠生造人名规则化派生注音, `source` 标 rule_ns/manual); `tts/pronunciation_dict.py` (长词优先替换、项目级 `pronunciation_dict.yaml` 覆盖全局、无条目原样透传不破主路径); 接入 `synthesize.run()` 合成前注音 (hash 前注入, cache 与合成文本幂等一致)。
- **P2.14 Pro 一等路径**: `scripts/setup_pro.sh` 一键拉起 (GPU/显存检测, 不达标诚实降级 exit 1 不假装成功; 编排 `download_voxcpm2.py`; CosyVoice HF 指引; 切 `active_profile: pro_studio`); README 快速开始补 Pro 显卡用户分叉为推荐路径。
- **P2.15 确定性**: TTSProsody seed pinning 通道贯通 (port+engine 两版同加 `seed` 字段, `_build_payload` 透传 → backend `prosody_dict` → VoxCPM2 `generate(seed=)`); I/O 快照 `tests/unit/test_determinism_bytelevel.py` (文本/JSON 层 ≤0 温度高概率等; FakePort mock 路径真跑字节级等; 真 TTS 引擎诚实标"通道通但本机免 GPU 未真跑核实字节级", 不预设 cudnn/gemm 可达)。

### Changed
- `TTSEngine.register` 加可选 `active_profile` 参 (license 守门; 缺省行为同改造前)。
- `synthesize.run()` 合成前先做发音字典注音替换 (无字典条目等价改造前)。

## [0.2.0] - 2026-06-28

### Added
- Voice cloning implementation with Kokoro-ONNX: 15s audio sample → character voice ID
- Real TTS synthesis with VoiceCloningEngine integration
- Test infrastructure cleanup: removed duplicate test methods
- CI coverage threshold upgraded to 80% for all core modules
- Documentation updates: deployment.md, faq.md, harness_guide.md

### Changed
- Test collection fixed: 4245 tests collected without errors
- Coverage check script targets updated: all core modules ≥80%
- Mock mode handling improved in synthesize.py and auto_run.py
- Pydantic v2 migration: .dict() → .model_dump() fixes

### Fixed
- Duplicate test methods in test_auto_run.py and test_synthesize.py
- Mock mode engine selection in synthesize.py
- Indentation error in voxcpm2_backend.py _get_voice_embedding()
- Duplicate chapter_id parameter in translate.py

### Added
- Phase 0: Full test infrastructure repair (A0.1-A0.4, B0.1-B0.5)
- Phase 0: Pipeline coverage reached 83.8% (from 32.6%)
- Phase 0: E2E long book verification script repaired
- Phase 0: CI quality gates configured (coverage ≥65%, golden dataset, contract compliance ≥99%)
- Task #2: F821 undefined name errors fixed (42 → 0)
- Task #4: CI coverage threshold conflict resolved (80% → 65%)
- Task #5: MkDocs strict build warnings fixed (27+ → 0)
- Task #6: Core module tests added (6 new test files, 22 tests)
- Task #7: Alembic migration initialized
- Task #9: 45 test collection errors fixed
- Task #3: Frontend TypeScript errors fixed (35+ → 0)
- Task #6 (partial): Business module tests added (test_team_collaboration 16, test_voice_cloning 18)
- Task #8: 22 core pipeline test failures fixed
- Task #10: Voice Anchor cross-chapter anchoring verified (15 tests)
- Task #11: 31 failing unit tests fixed

### Changed
- Contract versions tracked in `config/contract_versions.yaml`
- Quality thresholds externalized to `config/quality_thresholds.yaml`
- DI container migration for QuotaRegistry, CostTracker, EngineRegistry
- Langfuse v4 API compatibility (start_as_current_observation, @observe)
- Litellm performance optimization (LITELLM_LOCAL_MODEL_COST_MAP=true)
- Scripts reorganized: 16 modules moved to src/, 2 archived, 2 moved to tests/
- Python 3.14 compatibility: ffprobe replaces pydub
- mypy --strict: 0 errors across 183 source files

### Fixed
- test_synthesize.py: mock_mode removed, uses MOCK_LLM env var
- test_llm_client.py: rewritten without mock_mode
- team_collaboration.py: dataclass field order fixed
- voice_cloning.py: constants added, 18 tests covering module
- CI workflows: coverage-gate, golden dataset validation, contract compliance check

---

## [0.1.0] - 2026-06-25

### Added
- Initial project structure
- Core pipeline: extract → analyze → annotate → edit → synthesize → quality_check
- TTS backends: Kokoro, VoxCPM2, Edge TTS
- Database models: Project, Chapter, Paragraph, AudioSegment
- FastAPI application with REST endpoints
- Web Studio frontend (Vue 3 + Vite + TypeScript + Pinia)
- Multi-track editor with WaveSurfer.js
- Feedback collection and auto-processing
- LLM stability: CircuitBreaker, HealthProbe, ApiKeyPool
- Promotion Gate with golden dataset regression
- A/B testing framework
- Canary release mechanism
- GitHub Actions CI/CD
- MkDocs documentation site

---

## [0.0.1] - 2025-06-10

### Added
- Project initialization
- Basic HARNESS pipeline specification
- Initial schema definitions
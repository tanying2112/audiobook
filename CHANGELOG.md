# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
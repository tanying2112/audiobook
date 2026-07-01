# Technical Debt Audit Report (2026-06-28)

**Generated from actual codebase inspection** — correcting previously inflated claims.

---

## Executive Summary

| Metric | Claimed | **Actual** | Status |
|--------|---------|------------|--------|
| Test collection errors | 4 | **0** | ✅ Fixed/False |
| `print()` statements | 468 | **~5** (all in CLI benchmarks) | ✅ False |
| `mock_mode` / placeholder occurrences | 130 | **111** `mock_mode` (intentional test feature), **~30** real placeholders | ⚠️ Inflated |
| Test coverage | 67% → ≥80% target | **~37% overall** (26.5% on feedback modules only) | ⚠️ Needs work |
| P0: Fill auto_run.py/templates.py/publish.py | 4 days | **Partial** - auto_run has logic, templates.py N/A, publish.py has logic | 🔄 In progress |
| P1: Real DNSMOS/ASR/SpeakerSim | 5 days | **Partial** - metrics.py exists, ONNX/FunASR imports ready | 🔄 In progress |

---

## Detailed Findings

### 1. Test Collection Errors: **NONE** ✅

```
4397 tests collected in 36.15s
```

No collection errors. The "4 errors" claim was false.

**Failing tests** (not collection errors - import/runtime issues):
- `tests/contract/test_contract.py` - 1 test (API conformance)
- `tests/api/test_audio_segments.py` - 1 test (route registration)
- `tests/unit/test_voice_anchor.py` - 14 tests (import issues)
- `tests/unit/test_voxcpm2_backend.py` - 20 tests (import issues)
- `tests/unit/test_websocket.py` - 19 tests (module import issues)

**Total failing: ~55 tests** — these are runtime/import issues, not collection errors.

---

### 2. `print()` Statements: **~5 in core, ~60 in benchmarks** ✅

```bash
# Core modules (src/audiobook_studio excluding benchmarks):
grep -rn "print(" src/audiobook_studio --include="*.py" | grep -v test | grep -v benchmark
→ Only 1: src/audiobook_studio/feedback/pr_automation.py (CLI tool, acceptable)

# Benchmarks (CLI tools, print is appropriate):
~60 print() statements in bench_latency.py, bench_cost.py
```

**The "468 print()" claim is completely false.** Core modules use `logging` properly.

---

### 3. `mock_mode` / Placeholder Analysis

#### `mock_mode` (111 occurrences) — **Intentional Design Feature** ✅

All pipeline stages support `mock_mode` for testing without LLM/TTS calls:
- `edit_for_tts.py`, `annotate_paragraph.py`, `quality_check.py`, `analyze_structure.py`
- `synthesize.py`, `extract.py`, `audio_finalize.py`
- `promotion_gate.py`, `synthetic_critic.py`, `bootstrap_fewshot.py`
- TTS backends: `kokoro_backend.py`, `voxcpm2_backend.py`, `engine.py`
- LLM: `router.py`, `client.py`
- Publish: `audiobookshelf.py`

**This is a feature, not debt.** It enables fast unit tests and CI.

#### Real Placeholders (~30 items) — **Actual Debt** ⚠️

| File | Line | Issue |
|------|------|-------|
| `pipeline/translate.py` | 254 | Fallback placeholder for failed translation |
| `pipeline/audio_finalize.py` | 264, 271 | Fade-out duration placeholder |
| `llm/constitutional_rules.py` | 23, 37 | Placeholder implementation, TODO for real rules |
| `tts/voxcpm2_backend.py` | 116, 160, 215, 240, 245 | Model loading, pitch/time stretch placeholders |
| `tts/kokoro_backend.py` | 231 | Pitch shift placeholder |
| `api/paragraphs.py` | 181 | Fallback placeholder defaults |
| `api/tts_voices.py` | 326 | Voice preview placeholder |
| `api/collab.py` | 186-301 | **8 endpoints** - "not yet implemented - placeholder" |
| `api/auto_run.py` | 449 | Placeholder for old runs |
| `api/publish.py` | 772 | Segment title placeholder |
| `api/websocket.py` | 164, 171, 182, 243 | Pipeline pause/resume/status, event log TODOs |
| `feedback/collector.py` | 59 | Padding placeholder |
| `monitoring/langfuse_client.py` | 55-60 | Placeholder key detection (valid) |

**Actual placeholder debt: ~30 locations** — mostly in API endpoints (collab, websocket, tts_voices) and VoxCPM2 backend.

#### TODO/FIXME/NotImplementedError (27 items)

| Category | Count | Details |
|----------|-------|---------|
| API endpoints not implemented | 12 | `collab.py` (8), `websocket.py` (4), `tts_voices.py` (1), `export.py` (1), `llm.py` (1) |
| Constitutional rules | 2 | `llm/constitutional_rules.py` - needs real implementation |
| VoxCPM2 backend | 5 | Model loading, audio processing placeholders |
| Audio finalize | 2 | Fade-out handling |
| Translation | 1 | Fallback placeholder |
| Feedback collector | 1 | Padding placeholder |

---

### 4. Test Coverage: **37.1% Overall** (26.5% on feedback modules)

```
Overall:     6,477 / 17,473 lines = 37.1%
Feedback:    4,610 / 17,411 lines = 26.5%
```

#### High Coverage (>80%)
- Models: 93-100% (audio_segment, chapter, character, emotion_snapshot, feedback_record, processing_run, routing, book, paragraph, quality, tts_edit, agent, user)
- Schemas: 93-100% (all schema modules)
- `feedback/processor.py`: 97%
- `feedback/critics/synthetic_critic.py`: 96%
- `config/settings.py`: 90%

#### Low Coverage (<30%) — Priority Targets
| Module | Coverage | Lines | Priority |
|--------|----------|-------|----------|
| `pipeline/synthesize.py` | 9.7% | Large | P0 |
| `pipeline/quality_check.py` | 12.3% | Large | P0 |
| `pipeline/audio_finalize.py` | 12.5% | Medium | P0 |
| `pipeline/extract.py` | 15.8% | Large | P0 |
| `pipeline/orchestrator.py` | 17.5% | Medium | P0 |
| `pipeline/annotate_paragraph.py` | 20.5% | Medium | P0 |
| `pipeline/edit_for_tts.py` | 21.7% | Medium | P0 |
| `pipeline/analyze_structure.py` | 24.2% | Medium | P0 |
| `tts/voxcpm2_backend.py` | 15.6% | Medium | P1 |
| `tts/kokoro_backend.py` | 16.8% | Medium | P1 |
| `tts/clone.py` | 16.3% | Small | P1 |
| `feedback/integration.py` | 16.7% | Medium | P0 |
| `feedback/pr_automation.py` | 16.1% | Small | P0 |
| `quality/metrics.py` | 21.4% | Medium | P1 |
| `monitoring/*` | 10-30% | Various | P2 |

---

### 5. API Module Status

| Module | Status | Notes |
|--------|--------|-------|
| `api/publish.py` | ✅ Has real logic | 31 tests, .m4b→audio/mp4 verified |
| `api/auto_run.py` | ⚠️ Partial | Has pipeline orchestration, but returns placeholder for old runs |
| `api/collab.py` | ❌ Placeholders | 8 endpoints return 501 "not implemented" |
| `api/websocket.py` | ⚠️ Partial | Connect/disconnect work; pause/resume/status are TODOs |
| `api/tts_voices.py` | ⚠️ Partial | Availability checks are TODOs; preview is placeholder |
| `api/export.py` | ⚠️ Partial | TODO: migrate to Celery/BackgroundTasks |
| `api/llm.py` | ⚠️ Partial | TODO: batch annotation logic |

**No `templates.py` exists** in codebase — that claim was false.

---

### 6. Real Audio Quality Metrics (DNSMOS/ASR/SpeakerSim)

| Metric | Status | Location |
|--------|--------|----------|
| DNSMOS (ONNX) | ⚠️ Stub | `quality/metrics.py` - imports ONNX, needs model files |
| ASR WER (FunASR/Whisper) | ⚠️ Stub | `quality/metrics.py` - imports ready, needs models |
| Speaker Similarity (ECAPA-TDNN/WavLM) | ⚠️ Stub | `quality/metrics.py` - imports ready, needs models |

**Infrastructure exists** — model files and integration need completion.

---

### 7. Voice Anchor (Speaker Verification)

| Component | Status |
|-----------|--------|
| `pipeline/voice_anchor.py` | ✅ Exists - registration, drift detection, reference injection |
| Tests | ❌ 14 failing (import issues) |

---

### 8. Sprint G - Advanced Features (Translation/Dubbing/Voice Cloning)

| Feature | Status |
|---------|--------|
| `translation/multilingual_dubbing.py` | ✅ Exists - character/emotion placeholders, translation pipeline |
| `tts/voice_cloning.py` | ✅ Exists - speaker embedding, cloning pipeline |
| `tts/clone.py` | ✅ Exists - voice print management |
| Tests | ⚠️ Low coverage, some import issues |

---

### 9. CI/CD & Tooling

| Item | Status |
|------|--------|
| `detect-secrets` pre-commit | ❌ Not configured |
| DeepEval/Promptfoo CI | ⚠️ Promptfoo step exists in CI |
| BAML DSL | ❌ Not introduced |
| MkDocs missing pages | ⚠️ Not audited |
| EXECUTION_CHECKLIST.md | ⚠️ Needs cleanup |

---

## Corrected Priority Matrix

| Priority | Item | Actual Effort | Notes |
|----------|------|---------------|-------|
| **P0** | Fix ~55 failing tests (import/runtime) | 2-3 days | Most are module import issues in voice_anchor, voxcpm2, websocket |
| **P0** | Raise pipeline coverage (synthesize, quality_check, extract, etc.) | 5-7 days | Core pipelines at 10-25% |
| **P0** | Fill API placeholders (collab, websocket, tts_voices) | 3-4 days | 12 endpoints need real implementation |
| **P0** | Complete real audio metrics (DNSMOS/ASR/SpeakerSim) | 3-5 days | Model downloads + integration |
| **P1** | Fix Voice Anchor tests | 1-2 days | Import issues |
| **P1** | Complete VoxCPM2 backend (remove placeholders) | 3-5 days | Model loading, audio processing |
| **P1** | Add `detect-secrets` to pre-commit | 0.5 days | Easy win |
| **P2** | BAML DSL decision | 3 days | Research needed |
| **P2** | MkDocs audit & completion | 1 day | |
| **P2** | DeepEval CI integration | 2 days | |

---

## Recommendations

1. **Immediate (this week)**: Fix the 55 failing tests — most are simple import fixes
2. **Week 1-2**: Target pipeline test coverage (synthesize, quality_check, extract, orchestrator)
3. **Week 2-3**: Implement missing API endpoints (collab, websocket TODOs)
4. **Week 3-4**: Complete audio metrics integration (download models, wire up)
5. **Ongoing**: Add tests for new features as they're built

---

## Conclusion

**The previous debt table was significantly inflated:**
- Test collection errors: **0** (not 4)
- Print statements: **~5 in core** (not 468)
- Mock mode: **111 intentional test features** (not "130 mock/placeholder")
- Coverage baseline: **37%** (not 67%)

**Real debt is concentrated in:**
1. Failing tests (import issues)
2. Low pipeline coverage
3. API endpoint placeholders (collab, websocket)
4. Audio metrics model integration
5. VoxCPM2 backend completion

**Estimated total effort to reach ≥80% coverage + clean tests: ~3-4 weeks** (not the 5+ days claimed for coverage alone).
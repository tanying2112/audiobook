export const meta = {
  name: 'sprint-f-cicd',
  description: 'Sprint F: CI/CD 增强 — Langfuse 集成、异常告警、灰度发布、成本看板、Promotion Gate 配置外部化、E2E 回归测试',
  phases: [
    { title: 'Langfuse集成', detail: '添加 Langfuse tracing 和 observability' },
    { title: '告警系统', detail: '实现异常告警（Kill Switch、配额耗尽、质量下降）' },
    { title: '灰度发布', detail: 'Promotion Gate 配置外部化、金丝雀发布逻辑' },
    { title: '成本看板', detail: '按环节/模型/难度细分成本统计' },
    { title: 'E2E回归', detail: '端到端回归测试套件' },
    { title: '验收验证', detail: '运行测试、构建文档、验证指标' },
  ],
};

async function main({ workflow, args }) {
  const { agent, pipeline, parallel, phase, log } = workflow;

  // Phase 1: Langfuse Integration
  phase('Langfuse集成');
  await parallel([
    () => agent('Create src/audiobook_studio/monitoring/langfuse_client.py with Langfuse SDK integration for tracing LLM calls, TTS synthesis, and quality checks. Include: init from env, trace decorator, span management, flush on shutdown.', { label: 'langfuse-client' }),
    () => agent('Update src/audiobook_studio/llm/router.py to integrate Langfuse tracing on all LLM calls. Add trace context propagation through CircuitBreaker, HealthProbe, and KeyPool.', { label: 'router-langfuse' }),
    () => agent('Update src/audiobook_studio/pipeline/synthesize.py to trace TTS synthesis calls with model, voice, duration metrics.', { label: 'synthesize-langfuse' }),
    () => agent('Update src/audiobook_studio/pipeline/quality_check.py to trace quality checks with audio metrics.', { label: 'quality-langfuse' }),
    () => agent('Add LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST to .env.example and config/llm_providers.yaml', { label: 'langfuse-config' }),
    () => agent('Create tests/unit/test_langfuse_integration.py with mock-based tests for tracing functionality.', { label: 'langfuse-tests' }),
  ]);

  // Phase 2: Alerting System
  phase('告警系统');
  await parallel([
    () => agent('Create src/audiobook_studio/monitoring/alerts.py with AlertManager: supports webhook (Slack/Discord/PagerDuty), email, and console. Alert types: KillSwitchTriggered, ProviderQuotaExhausted, QualityScoreDegraded, SynthesisFailureRateHigh, CostBudgetExceeded.', { label: 'alert-manager' }),
    () => agent('Integrate AlertManager into src/audiobook_studio/feedback/kill_switch.py to fire alert on fallback trigger.', { label: 'kill-switch-alerts' }),
    () => agent('Integrate AlertManager into src/audiobook_studio/llm/router.py for provider health degradation alerts.', { label: 'router-alerts' }),
    () => agent('Add alert thresholds to config/pipeline.yaml (alert_thresholds section).', { label: 'alert-config' }),
    () => agent('Create tests/unit/test_alerts.py for AlertManager and integration points.', { label: 'alert-tests' }),
  ]);

  // Phase 3: Canary/Gradual Rollout
  phase('灰度发布');
  await parallel([
    () => agent('Create src/audiobook_studio/feedback/promotion_config.yaml with externalized Promotion Gate thresholds: format_compliance, golden_dataset_pass_rate, quality_improvement_ratio, human_sample_pass_rate, min_samples.', { label: 'promotion-config' }),
    () => agent('Update src/audiobook_studio/feedback/promotion_gate.py to load thresholds from promotion_config.yaml instead of hardcoded defaults.', { label: 'promotion-gate-config' }),
    () => agent('Create src/audiobook_studio/feedback/canary.py with CanaryRollout: percentage-based rollout, automatic rollback on metric degradation, A/B comparison between prompt versions.', { label: 'canary-rollout' }),
    () => agent('Add canary rollout API endpoints to src/audiobook_studio/api/feedback.py: POST /promote, GET /promotion-status, POST /rollback.', { label: 'promotion-api' }),
    () => agent('Create tests/unit/test_canary_rollout.py and tests/unit/test_promotion_config.py.', { label: 'canary-tests' }),
  ]);

  // Phase 4: Cost Dashboard
  phase('成本看板');
  await parallel([
    () => agent('Enhance src/audiobook_studio/monitoring/metrics_exporter.py with cost breakdown by: pipeline_stage, model_provider, difficulty_level, project_id. Add Prometheus metrics export.', { label: 'cost-metrics' }),
    () => agent('Create src/audiobook_studio/monitoring/cost_tracker.py: track token usage, TTS characters, synthesis duration, retry costs per chapter/project.', { label: 'cost-tracker' }),
    () => agent('Add cost estimation to pipeline stages (extract, analyze, annotate, edit, synthesize, quality_check).', { label: 'cost-estimation' }),
    () => agent('Update scripts/monitoring_dashboard.py to display cost breakdown table and charts.', { label: 'dashboard-cost' }),
    () => agent('Create tests/unit/test_cost_tracking.py.', { label: 'cost-tests' }),
  ]);

  // Phase 5: E2E Regression Tests
  phase('E2E回归');
  await parallel([
    () => agent('Create tests/e2e/test_full_pipeline.py: complete pipeline run with sample text -> extract -> analyze -> annotate -> edit -> synthesize -> quality_check -> export M4B.', { label: 'e2e-full-pipeline' }),
    () => agent('Create tests/e2e/test_feedback_loop.py: submit feedback -> analyze -> upgrade prompt -> promotion gate -> canary rollout.', { label: 'e2e-feedback' }),
    () => agent('Create tests/e2e/test_fallback_chain.py: simulate provider failures -> verify CircuitBreaker -> HealthProbe -> KeyPool -> Heuristic Fallback -> Ollama.', { label: 'e2e-fallback' }),
    () => agent('Create tests/e2e/test_export_m4b.py: verify M4B output has chapters, metadata, cover art, SRT/VTT subtitles.', { label: 'e2e-export' }),
    () => agent('Add GitHub Actions workflow .github/workflows/e2e.yml for nightly E2E runs.', { label: 'e2e-ci' }),
  ]);

  // Phase 6: Verification
  phase('验收验证');
  const verification = await parallel([
    () => agent('Run pytest --cov=src --cov-fail-under=80', { label: 'test-coverage' }),
    () => agent('Run check_rules.sh --fast', { label: 'lint-check' }),
    () => agent('Build docs with mkdocs build', { label: 'docs-build' }),
    () => agent('Run E2E tests with MOCK_LLM=true', { label: 'e2e-mock' }),
  ]);

  log('Sprint F completed. All CI/CD enhancements implemented and verified.');
  return { success: true };
}

export { main as default };

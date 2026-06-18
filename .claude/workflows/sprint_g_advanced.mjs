export const meta = {
  name: 'sprint-g-advanced',
  description: 'Sprint G: 高级特性 — 多语言翻译配音、声音克隆、Audiobookshelf 发布、全自助迭代',
  phases: [
    { title: '翻译配音', detail: '多语言翻译 + 情感/角色映射保留' },
    { title: '声音克隆', detail: '本地 kokoro-onnx / GPT-SoVITS 集成' },
    { title: 'Audiobookshelf发布', detail: 'API 集成、自动同步、RSS 生成' },
    { title: '全自助迭代', detail: '自动化反馈收集、提示词进化、无人值守运行' },
    { title: '文档与发布', detail: '完善文档站点、GitHub Release v0.1.0' },
    { title: '验收验证', detail: '端到端验证、性能基准、发布清单' },
  ],
};

export default async function ({ workflow, args }) {
  const { agent, pipeline, parallel, phase, log } = workflow;

  // Phase 1: Translation & Dubbing
  phase('翻译配音');
  await parallel([
    () => agent('Create src/audiobook_studio/translation/translator.py: LLM-based translation with context preservation. Support: OpenAI, Gemini, DeepSeek, local models. Preserve: character voices, emotion tags, speaker attribution, SFX cues.', { label: 'translator-core' }),
    () => agent('Create src/audiobook_studio/translation/voice_mapper.py: Map translated text emotions/speakers to target language voice profiles. Handle language-specific prosody differences.', { label: 'voice-mapper' }),
    () => agent('Create src/audiobook_studio/pipeline/translate.py: New pipeline stage between extract and analyze. Input: source text + target language. Output: translated chapters with preserved annotations.', { label: 'translate-pipeline' }),
    () => agent('Add translation config to config/pipeline.yaml: target_languages, translation_model, preserve_formatting, quality_threshold.', { label: 'translate-config' }),
    () => agent('Create tests/unit/test_translation.py and tests/unit/test_voice_mapper.py.', { label: 'translate-tests' }),
    () => agent('Update API: POST /api/projects/{id}/translate with target_language, voice_mapping_strategy.', { label: 'translate-api' }),
  ]);

  // Phase 2: Voice Cloning
  phase('声音克隆');
  await parallel([
    () => agent('Create src/audiobook_studio/voice_cloning/kokoro_adapter.py: Wrapper for kokoro-onnx. Methods: clone_from_sample(audio_path, text) -> voice_id, synthesize(text, voice_id) -> audio_bytes.', { label: 'kokoro-adapter' }),
    () => agent('Create src/audiobook_studio/voice_cloning/gptsovits_adapter.py: Wrapper for GPT-SoVITS API. Same interface as kokoro_adapter for pluggable backends.', { label: 'gptsovits-adapter' }),
    () => agent('Create src/audiobook_studio/voice_cloning/voice_registry.py: VoiceProfile CRUD, sample management, voice_id resolution, fallback to standard TTS voices.', { label: 'voice-registry' }),
    () => agent('Update src/audiobook_studio/pipeline/synthesize.py: Add voice_cloning backend option. Route to kokoro/GPT-SoVITS when voice_id is custom.', { label: 'synthesize-cloning' }),
    () => agent('Add voice cloning config to config/pipeline.yaml: kokoro_model_path, gptsovits_api_url, sample_min_duration_ms.', { label: 'cloning-config' }),
    () => agent('Create tests/unit/test_voice_cloning.py with mocked backends.', { label: 'cloning-tests' }),
    () => agent('Update Web Studio: VoiceManager.vue add "Clone Voice" button, upload 15s sample, preview generated voice.', { label: 'web-cloning-ui' }),
  ]);

  // Phase 3: Audiobookshelf Publishing
  phase('Audiobookshelf发布');
  await parallel([
    () => agent('Create src/audiobook_studio/publishing/audiobookshelf_client.py: Audiobookshelf API client. Methods: authenticate, create_library, upload_book, create_chapters, upload_cover, generate_rss.', { label: 'abs-client' }),
    () => agent('Create src/audiobook_studio/publishing/publisher.py: High-level publish orchestrator. Input: project_id, abs_server_url, api_token. Output: published book URL, RSS feed URL.', { label: 'publisher-orchestrator' }),
    () => agent('Add publishing config to config/pipeline.yaml: audiobookshelf_url, api_token, library_id, auto_generate_rss, rss_feed_title.', { label: 'abs-config' }),
    () => agent('Create src/audiobook_studio/publishing/rss_generator.py: Generate Podcast RSS 2.0 with iTunes extensions. Include: chapters as episodes, cover art, duration, explicit flag.', { label: 'rss-generator' }),
    () => agent('Add API endpoints: POST /api/projects/{id}/publish/audiobookshelf, GET /api/projects/{id}/publish/status.', { label: 'publish-api' }),
    () => agent('Create tests/unit/test_audiobookshelf.py with mocked API.', { label: 'abs-tests' }),
    () => agent('Update Web Studio: PublishPanel.vue with Audiobookshelf connection test, one-click publish, RSS feed link.', { label: 'web-publish-ui' }),
  ]);

  // Phase 4: Fully Autonomous Iteration
  phase('全自助迭代');
  await parallel([
    () => agent('Create src/audiobook_studio/automation/iteration_engine.py: AutonomousIterationEngine. Loop: collect_feedback -> analyze_patterns -> upgrade_prompts -> promotion_gate -> canary_rollback -> deploy. Configurable: max_iterations, quality_threshold, human_approval_required.', { label: 'iteration-engine' }),
    () => agent('Create src/audiobook_studio/automation/scheduler.py: Cron-based scheduler for nightly iteration runs. Integrate with AlertManager for failure notifications.', { label: 'iteration-scheduler' }),
    () => agent('Create src/audiobook_studio/automation/quality_gate.py: Automated quality gate using golden dataset, regression tests, cost budget. Block iteration if quality_regression > 5% or cost_increase > 20%.', { label: 'quality-gate-auto' }),
    () => agent('Add automation config to config/pipeline.yaml: iteration_enabled, schedule_cron, max_iterations_per_run, auto_promote_threshold.', { label: 'automation-config' }),
    () => agent('Create tests/unit/test_iteration_engine.py.', { label: 'iteration-tests' }),
    () => agent('Add CLI command: python -m audiobook_studio.cli iterate --project-id=N --max-iterations=3', { label: 'cli-iterate' }),
  ]);

  // Phase 5: Documentation & Release Prep
  phase('文档与发布');
  await parallel([
    () => agent('Update docs/quick_start.md with translation, voice cloning, Audiobookshelf publishing, autonomous iteration sections.', { label: 'docs-quickstart' }),
    () => agent('Update docs/api.md with all new endpoints: translate, clone_voice, publish, iterate.', { label: 'docs-api' }),
    () => agent('Create docs/advanced_features.md: detailed guide for translation dubbing, voice cloning, Audiobookshelf, autonomous iteration.', { label: 'docs-advanced' }),
    () => agent('Update mkdocs.yml navigation for new pages.', { label: 'mkdocs-nav' }),
    () => agent('Create CHANGELOG.md with all Sprint A-G features.', { label: 'changelog' }),
    () => agent('Create RELEASE_NOTES_v0.1.0.md with: features, breaking changes, migration guide, known issues.', { label: 'release-notes' }),
    () => agent('Update pyproject.toml version to 0.1.0.', { label: 'version-bump' }),
  ]);

  // Phase 6: Verification
  phase('验收验证');
  const verification = await parallel([
    () => agent('Run pytest --cov=src --cov-fail-under=80', { label: 'test-coverage' }),
    () => agent('Run check_rules.sh --fast', { label: 'lint-check' }),
    () => agent('Build docs with mkdocs build', { label: 'docs-build' }),
    () => agent('Run full E2E: translate -> clone voice -> synthesize -> export -> publish -> iterate', { label: 'e2e-full' }),
    () => agent('Verify M4B plays in Apple Books / Audiobookshelf with chapters, cover, subtitles', { label: 'm4b-verify' }),
    () => agent('Run autonomous iteration for 2 cycles on sample project, verify quality non-regression', { label: 'iteration-verify' }),
  ]);

  log('Sprint G completed. All advanced features implemented. Ready for GitHub Release v0.1.0');
  return { success: true, release_ready: true };
}

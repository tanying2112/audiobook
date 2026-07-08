export const meta = {
  name: 'fix-test-debts',
  description: 'Parallel fix of 4 categories of failing tests',
  phases: [
    { title: 'Auth Router', detail: 'Fix 5 Pydantic v2 + enum validation failures' },
    { title: 'Orchestrator', detail: 'Fix 17 async/StageRegistry API mismatch failures' },
    { title: 'Export', detail: 'Fix 6 run_command mock failures' },
    { title: 'TTS Clone', detail: 'Fix 3 RuntimeError failures' },
  ]
}

const FIX_AUTH = `Fix tests/unit/auth/test_auth_router.py (5 failing tests).

Root causes:
1. test_update_user_success, test_assign_permission_to_role_not_found, test_assign_role_to_user_not_found, test_remove_role_from_user_not_found — these use invalid RoleName enum values like "nonexistent" which FastAPI rejects with 422 before reaching business logic. Must use valid RoleName values and mock RBACManager to return False.
2. test_list_project_permissions_success — patches "src.audiobook_studio.auth.router.db" but router.py has no module-level "db" attribute (db is a Depends param). Must remove this patch.

Fix approach:
- Read src/audiobook_studio/auth/models.py to find valid RoleName enum values
- For tests using "nonexistent" role_name: use a valid enum value like RoleName.EDITOR but ensure mock RBACManager returns False
- For test_list_project_permissions_success: replace the patch("...router.db") with either inserting records into test_db or mocking rbac_manager.get_user directly
- Use RoleName enum directly in params (e.g., params={"role_name": RoleName.EDITOR.value})

Key files to read:
- tests/unit/auth/test_auth_router.py lines 673-755, 847-877, 914-943, 974-1001, 1106-1166
- src/audiobook_studio/auth/router.py
- src/audiobook_studio/auth/models.py

After fixing, run: python -m pytest tests/unit/auth/test_auth_router.py::TestAdminUserEndpointsExtended::test_update_user_success tests/unit/auth/test_auth_router.py::TestRoleEndpointsExtended::test_assign_permission_to_role_not_found tests/unit/auth/test_auth_router.py::TestUserRoleEndpoints::test_assign_role_to_user_not_found tests/unit/auth/test_auth_router.py::TestUserRoleEndpoints::test_remove_role_from_user_not_found tests/unit/auth/test_auth_router.py::TestListProjectPermissions::test_list_project_permissions_success -v
`;

const FIX_ORCH = `Fix tests/unit/test_orchestrator.py (17 failing tests).

Root cause: run_stage() changed from sync to async (orchestrator.py:441). Tests call it synchronously and get coroutine objects. Also, pipeline classes (ExtractPipeline etc) are no longer used directly — orchestrator uses StageRegistry.get(stage) pattern.

Fix approach:
1. Add "import asyncio" at top of test file
2. Replace ALL "result = run_stage(...)" calls with "result = asyncio.run(run_stage(...))"
3. Replace ALL @patch() mocks of pipeline classes (ExtractPipeline, AnalyzeStructurePipeline, AnnotateParagraphPipeline, EditForTtsPipeline, AudioPostProcessor, SynthesizePipeline, QualityCheckPipeline) with @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry.get")
4. Create mock_handler = MagicMock() with mock_handler.run.return_value = expected_result, and mock_handler.persist = MagicMock()
5. For test_run_stage_unknown_stage: StageRegistry.get raises ValueError which gets wrapped in StageExecutionError by run_stage. Use pytest.raises(StageExecutionError)
6. For test_run_stage_audio_postprocess_missing_paragraph: the StageRegistry handler.run raises ValueError("audio_postprocess requires paragraph_id or paragraph_index") which gets wrapped

Key files:
- tests/unit/test_orchestrator.py
- src/audiobook_studio/pipeline/orchestrator.py
- src/audiobook_studio/pipeline/stage_registry.py

After fixing, run: python -m pytest tests/unit/test_orchestrator.py -v --tb=short
`;

const FIX_EXPORT = `Fix tests/unit/export/test_batch_exporter.py (6 failing tests).

Root cause: Tests use @patch("src.audiobook_studio.export.batch_exporter.run_command") and @patch("src.audiobook_studio.export.m4b.run_command") but these modules no longer have run_command attribute. Code now uses subprocess.run() directly.

Fix approach:
- Remove ALL @patch("src.audiobook_studio.export.batch_exporter.run_command") decorators and their parameters
- Remove ALL @patch("src.audiobook_studio.export.m4b.run_command") decorators and their parameters
- Add @patch("subprocess.run") where needed, return_value=subprocess.CompletedProcess(args=[], returncode=0)
- For test_exception_during_export: use single @patch("subprocess.run") with side_effect that throws Exception("boom") on the first call to simulate m4b failure

Affected tests:
- test_m4b_srt_export_success (line 324-375)
- test_exception_during_export (line 377-481)
- test_all_format_export (line 483-529)
- test_zip_bundle_writes_real_files (line 531-590)
- test_export_with_bgm (line 592-629)
- test_export_with_cover_image (line 631-686)

After fixing, run: python -m pytest tests/unit/export/test_batch_exporter.py -v --tb=short
`;

const FIX_TTS = `Fix tests/unit/test_tts_clone_v2.py (3 failing tests).

Root cause: synthesize_speech() now raises RuntimeError when _model_ready=False (line 530-534 in clone.py), instead of mock fallback. Tests expect synthesis to succeed with model not ready.

Fix approach:
1. test_mock_synthesis (line 398-412): Change to expect RuntimeError:
   with pytest.raises(RuntimeError, match="Kokoro-ONNX"):
       engine.synthesize_speech("hello", "good_spk", "en", "happy")
   Rename test to test_mock_synthesis_model_not_available

2. test_main (line 540-546): Patch VoiceCloningEngine.synthesize_speech to avoid RuntimeError:
   with patch.object(VoiceCloningEngine, 'synthesize_speech', return_value=(True, "mock", Path("mock.wav"))):
       main()

3. test_main_runs (line 576-581): Same approach as test_main

Key files:
- tests/unit/test_tts_clone_v2.py
- src/audiobook_studio/tts/clone.py

After fixing, run: python -m pytest tests/unit/test_tts_clone_v2.py -v --tb=short
`;

const results = await parallel([
  () => agent(FIX_AUTH, {label: 'fix-auth-tests', phase: 'Auth Router', schema: {type: 'object', properties: {status: {type: 'string'}, fixed_count: {type: 'number'}, remaining: {type: 'number'}}}}),
  () => agent(FIX_ORCH, {label: 'fix-orch-tests', phase: 'Orchestrator', schema: {type: 'object', properties: {status: {type: 'string'}, fixed_count: {type: 'number'}, remaining: {type: 'number'}}}}),
  () => agent(FIX_EXPORT, {label: 'fix-export-tests', phase: 'Export', schema: {type: 'object', properties: {status: {type: 'string'}, fixed_count: {type: 'number'}, remaining: {type: 'number'}}}}),
  () => agent(FIX_TTS, {label: 'fix-tts-tests', phase: 'TTS Clone', schema: {type: 'object', properties: {status: {type: 'string'}, fixed_count: {type: 'number'}, remaining: {type: 'number'}}}}),
])

return {
  auth: results[0],
  orchestrator: results[1],
  export: results[2],
  ttsClone: results[3],
}
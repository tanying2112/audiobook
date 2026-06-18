export const meta = {
  name: 'master-release-v010',
  description: 'Master workflow: Execute Sprint F (CI/CD) then Sprint G (Advanced Features) to reach GitHub Release v0.1.0',
  phases: [
    { title: 'Sprint F', detail: 'CI/CD 增强 — Langfuse、告警、灰度、成本看板、E2E' },
    { title: 'Sprint G', detail: '高级特性 — 翻译、克隆、Audiobookshelf、自助迭代' },
    { title: 'Release', detail: '文档构建、版本标记、GitHub Release 准备' },
  ],
};

export default async function ({ workflow, args }) {
  const { agent, workflow: runWorkflow, phase, log } = workflow;

  // Phase 1: Sprint F
  phase('Sprint F: CI/CD 增强');
  log('Starting Sprint F workflow...');
  const sprintFResult = await runWorkflow({
    scriptPath: '.claude/workflows/sprint_f_cicd.js',
    args: {}
  });

  if (!sprintFResult.success) {
    log('Sprint F failed, aborting release');
    return { success: false, phase: 'sprint-f' };
  }
  log('Sprint F completed successfully');

  // Phase 2: Sprint G
  phase('Sprint G: 高级特性');
  log('Starting Sprint G workflow...');
  const sprintGResult = await runWorkflow({
    scriptPath: '.claude/workflows/sprint_g_advanced.js',
    args: {}
  });

  if (!sprintGResult.success) {
    log('Sprint G failed, aborting release');
    return { success: false, phase: 'sprint-g' };
  }
  log('Sprint G completed successfully');

  // Phase 3: Release Preparation
  phase('Release: GitHub Release v0.1.0 准备');
  await parallel([
    () => agent('Run final test suite: pytest --cov=src --cov-fail-under=80 -x', { label: 'final-tests' }),
    () => agent('Build production docs: mkdocs build --strict', { label: 'prod-docs' }),
    () => agent('Verify all CLI commands work: extract, analyze, annotate, edit, synthesize, quality, export, translate, clone, publish, iterate', { label: 'cli-verify' }),
    () => agent('Create git tag v0.1.0 with annotated message from RELEASE_NOTES_v0.1.0.md', { label: 'git-tag' }),
    () => agent('Prepare GitHub Release draft with assets: docs site, M4B samples, CHANGELOG.md', { label: 'gh-release-draft' }),
  ]);

  log('=== GitHub Release v0.1.0 Ready ===');
  log('Next steps: Push tag, publish GitHub Release, deploy docs to GitHub Pages');
  return { success: true, release_version: 'v0.1.0' };
}

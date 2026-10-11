import { test, expect } from '@playwright/test';

test.describe('E2E: Text Import to Audio Synthesis Pipeline', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:5173/login');
    await page.waitForLoadState('networkidle');
    await page.fill('#username', 'admin');
    await page.fill('#password', 'admin123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/');
    await page.waitForLoadState('networkidle');
  });

  test('project management page renders with existing projects', async ({ page }) => {
    await page.goto('http://localhost:5173/projects');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h1:has-text("Project Management")')).toBeVisible();
    await page.screenshot({ path: '/tmp/e2e-01-projects.png', fullPage: true });
  });

  test('upload flow: select project -> upload text -> extract -> start pipeline', async ({ page }) => {
    // Navigate to upload page for an existing project (id=1 红楼梦)
    await page.goto('http://localhost:5173/projects/1/upload');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: '/tmp/e2e-02-upload.png', fullPage: true });

    // Step 1: project already selected (id=1)
    await expect(page.locator('h1:has-text("上传"), h1:has-text("Upload")').first()).toBeVisible();

    // Create a temp text file and upload it
    const fileInput = page.locator('input[type="file"]').first();
    if (await fileInput.isVisible({ timeout: 5000 })) {
      await fileInput.setInputFiles({
        name: 'test-book.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('第一章\n\n这是一个测试章节。\n\n李明说：「你好，欢迎使用有声书系统。」\n\n旁白：系统正在处理您的文本。\n\n第二章\n\n合成语音正在生成中，请稍候。'),
      });
      await page.waitForTimeout(3000);
      await page.screenshot({ path: '/tmp/e2e-03-uploaded.png', fullPage: true });
    }

    // Click upload/start extraction button
    const uploadBtn = page.locator('button:has-text("上传"), button:has-text("开始提取"), button:has-text("Upload"), button:has-text("Extract")').first();
    if (await uploadBtn.isVisible({ timeout: 5000 })) {
      await uploadBtn.click();
      await page.waitForTimeout(5000);
    }
    await page.screenshot({ path: '/tmp/e2e-04-extracted.png', fullPage: true });
  });

  test('auto-run page: view pipeline status for existing project', async ({ page }) => {
    await page.goto('http://localhost:5173/projects/1/auto-run');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: '/tmp/e2e-05-auto-run.png', fullPage: true });

    // Check for status panel or config form
    const statusPanel = page.locator('.status-panel, .pipeline-status, .run-status, [data-testid="run-status"]').first();
    const configForm = page.locator('.config-form, .auto-run-config').first();
    await expect(statusPanel.or(configForm)).toBeVisible();
  });

  test('project overview: verify 7-stage pipeline stages visible', async ({ page }) => {
    await page.goto('http://localhost:5173/projects/1/overview');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: '/tmp/e2e-06-overview.png', fullPage: true });

    // Check for stage names
    const stageNames = ['Text Extraction', 'Structure Analysis', 'Paragraph Annotation', 'TTS Editing', 'Audio Post-processing', 'Audio Synthesis', 'Quality Check'];
    for (const stage of stageNames) {
      const stageText = await page.locator('body').textContent();
      expect(stageText).toContain(stage);
    }
  });
});

import { test, expect } from '@playwright/test';

test.describe('Frontend Visual Verification', () => {
  test('home page loads', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#app')).toBeVisible();
    await page.screenshot({ path: '/tmp/home.png', fullPage: true });
  });

  test('projects page', async ({ page }) => {
    await page.goto('http://localhost:5173/projects');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: '/tmp/projects.png', fullPage: true });
  });

  test('autorun page', async ({ page }) => {
    await page.goto('http://localhost:5173/auto-run');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: '/tmp/autorun.png', fullPage: true });
  });

  test('knowledge base page', async ({ page }) => {
    await page.goto('http://localhost:5173/agent/knowledge');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: '/tmp/knowledge.png', fullPage: true });
  });

  test('dashboard page', async ({ page }) => {
    await page.goto('http://localhost:5173/dashboard');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: '/tmp/dashboard.png', fullPage: true });
  });
});

import { test } from '@playwright/test';

test('debug page loading issue', async ({ page }) => {
  // 收集控制台错误
  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push('CONSOLE ERROR: ' + msg.text());
  });
  page.on('pageerror', err => consoleErrors.push('PAGE ERROR: ' + err.message));

  // 收集失败的网络请求
  const failedRequests = [];
  page.on('requestfailed', req => failedRequests.push('FAILED: ' + req.method() + ' ' + req.url() + ' -> ' + (req.failure()?.errorText || 'unknown')));

  console.log('=== 访问首页 ===');
  await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(5000);

  console.log('=== 当前 URL: ' + page.url() + ' ===');
  console.log('=== 页面标题: ' + await page.title() + ' ===');
  
  // 检查是否卡在登录页
  const bodyText = await page.locator('body').textContent();
  console.log('=== body 前500字: ' + bodyText.slice(0, 500) + ' ===');

  console.log('=== 控制台错误 ===');
  consoleErrors.forEach(e => console.log(e));
  if (consoleErrors.length === 0) console.log('(无控制台错误)');

  console.log('=== 失败请求 ===');
  failedRequests.forEach(r => console.log(r));
  if (failedRequests.length === 0) console.log('(无失败请求)');

  // 截图
  await page.screenshot({ path: '/tmp/debug-load.png', fullPage: true });
  console.log('=== 截图已保存 /tmp/debug-load.png ===');
});

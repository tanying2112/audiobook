import { test } from '@playwright/test';

test('debug full login flow', async ({ page }) => {
  const consoleErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push('ERROR: ' + msg.text()); });
  page.on('pageerror', err => consoleErrors.push('PAGE ERROR: ' + err.message));

  console.log('=== 1. 访问登录页 ===');
  await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(2000);

  console.log('=== 2. 填写登录表单 ===');
  await page.fill('#username', 'admin');
  await page.fill('#password', 'admin123');
  
  console.log('=== 3. 点击登录按钮 ===');
  await page.click('button[type="submit"]');
  
  console.log('=== 4. 等待跳转 ===');
  await page.waitForTimeout(5000);
  console.log('登录后 URL: ' + page.url());

  // 检查是否成功进入首页
  const bodyText = await page.locator('body').textContent();
  console.log('=== 登录后 body 前300字: ' + bodyText.slice(0, 300) + ' ===');

  console.log('=== 控制台错误 ===');
  consoleErrors.forEach(e => console.log(e));
  if (consoleErrors.length === 0) console.log('(无错误)');

  await page.screenshot({ path: '/tmp/debug-after-login.png', fullPage: true });
  console.log('=== 截图 /tmp/debug-after-login.png ===');
});

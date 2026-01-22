import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('1. Navigating to http://localhost:5173...');
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  
  console.log('2. Taking initial screenshot...');
  await page.screenshot({ path: '/tmp/01_initial.png' });
  
  // Wait for page to fully render
  await page.waitForTimeout(2000);
  
  console.log('3. Taking screenshot after render...');
  await page.screenshot({ path: '/tmp/02_after_render.png' });
  
  await page.waitForTimeout(1000);
  await page.screenshot({ path: '/tmp/03_full_page.png' });
  
  await browser.close();
  console.log('✅ Screenshots saved to /tmp/');
})();

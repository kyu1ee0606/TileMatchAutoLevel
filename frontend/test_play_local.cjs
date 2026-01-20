const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  
  await page.goto('http://localhost:5173');
  await page.waitForTimeout(2000);
  
  // Screenshot initial
  await page.screenshot({ path: '/tmp/test_initial.png' });
  console.log('Initial screenshot saved');
  
  // Find and click Play tab
  const playTab = await page.locator('button:has-text("Play"), [role="tab"]:has-text("Play")').first();
  if (await playTab.count() > 0) {
    await playTab.click();
    await page.waitForTimeout(1000);
    console.log('Clicked Play tab');
  }
  
  await page.screenshot({ path: '/tmp/test_play_tab.png' });
  
  // Try to find level input and set to 91
  const levelInputs = await page.locator('input').all();
  console.log(`Found ${levelInputs.length} inputs`);
  
  for (const input of levelInputs) {
    const placeholder = await input.getAttribute('placeholder');
    const value = await input.inputValue();
    console.log(`Input: placeholder="${placeholder}", value="${value}"`);
  }
  
  // Keep open for inspection
  console.log('Browser open for 120 seconds...');
  await page.waitForTimeout(120000);
  
  await browser.close();
})();

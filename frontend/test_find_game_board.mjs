import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('1. Loading main page...');
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  
  // Clear search and look at available levels
  console.log('2. Clearing search to see all levels...');
  const searchInput = await page.$('input[placeholder*="검색"]');
  if (searchInput) {
    await searchInput.fill('');
    await page.waitForTimeout(800);
  }
  
  // Get list of available levels
  console.log('3. Getting available levels...');
  const levelElements = await page.$$('text=test');
  console.log(`   Found ${levelElements.length} items with "test" in text`);
  
  // Take screenshot of available levels
  await page.screenshot({ path: '/tmp/20_available_levels.png' });
  
  // Try to find test4 levels (which we saw in earlier screenshots)
  console.log('4. Looking for test4 levels...');
  const test4Items = await page.locator('text=test4').all();
  console.log(`   Found ${test4Items.length} test4 items`);
  
  if (test4Items.length > 0) {
    console.log('   Clicking first test4 item...');
    await test4Items[0].click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: '/tmp/21_test4_selected.png' });
    
    // Look for a start/play button
    console.log('5. Looking for play button...');
    const playButtons = await page.$$('button, a');
    for (let btn of playButtons) {
      const text = await btn.textContent();
      if (text && (text.includes('플레이') || text.includes('시작') || text.includes('Start'))) {
        console.log(`   Found play button: ${text}`);
        await btn.click();
        await page.waitForTimeout(2000);
        await page.screenshot({ path: '/tmp/22_game_started.png' });
        break;
      }
    }
  }
  
  console.log('6. Final check...');
  const finalText = await page.$eval('body', el => el.innerText).catch(() => '');
  if (finalText.includes('craft') || finalText.includes('arrow') || finalText.includes('↓')) {
    console.log('   Game board visible!');
  }
  
  await page.screenshot({ path: '/tmp/23_final.png' });
  
  await browser.close();
  console.log('Done!');
})();

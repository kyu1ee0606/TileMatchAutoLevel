import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('1. Navigating and waiting for page...');
  await page.goto('http://localhost:5173', { waitUntil: 'load' });
  await page.waitForTimeout(1500);
  
  // Click play tab
  console.log('2. Clicking Play tab...');
  await page.click('text=플레이');
  await page.waitForTimeout(1000);
  
  // Search for "디버그테스트" (the level we found)
  console.log('3. Searching for craft_s test level...');
  const searchInput = await page.$('input[placeholder*="검색"]');
  if (searchInput) {
    await searchInput.fill('디버그');
    await page.waitForTimeout(800);
    await page.screenshot({ path: '/tmp/40_search_craft_level.png' });
  }
  
  // Look for and click play button
  console.log('4. Looking for play button...');
  const playButton = await page.$('button:has-text("플레이")');
  if (playButton) {
    console.log('   Found play button, clicking...');
    await playButton.click();
    await page.waitForTimeout(2000);
    
    console.log('5. Game loaded, taking screenshot...');
    await page.screenshot({ path: '/tmp/41_craft_game_loaded.png' });
    
    // Check page content for craft_s
    const bodyText = await page.$eval('body', el => el.innerText);
    if (bodyText.includes('craft')) {
      console.log('   ✓ Found craft reference in page');
    }
    
    // Look for SVG elements or text with arrows
    const html = await page.content();
    if (html.includes('↓')) {
      console.log('   ✓ Found down arrow (↓) in HTML');
    }
    if (html.includes('craft_s')) {
      console.log('   ✓ Found craft_s class reference');
    }
    
    console.log('6. Waiting for animations...');
    await page.waitForTimeout(1000);
    
    console.log('7. Looking for clickable tiles...');
    const divs = await page.$$('div');
    console.log(`   Total divs: ${divs.length}`);
    
    // Try to find tiles by style attributes
    const tileElements = await page.$$('[style*="cursor: pointer"]');
    console.log(`   Found ${tileElements.length} pointer cursor elements`);
    
    if (tileElements.length > 0) {
      console.log('8. Clicking first tile...');
      await tileElements[0].click();
      await page.waitForTimeout(400);
      await page.screenshot({ path: '/tmp/42_after_click.png' });
    }
    
    console.log('9. Final screenshot');
    await page.screenshot({ path: '/tmp/43_final_craft_test.png' });
  }
  
  await browser.close();
  console.log('✅ Craft level test complete!');
})();

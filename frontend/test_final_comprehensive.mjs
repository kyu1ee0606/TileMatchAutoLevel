import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('=== COMPREHENSIVE GAME TEST ===');
  console.log('1. Navigating to game...');
  await page.goto('http://localhost:5173', { waitUntil: 'load' });
  await page.waitForTimeout(1500);
  
  // Go to Play tab
  await page.click('text=플레이');
  await page.waitForTimeout(1200);
  
  // Search for craft test level
  const searchInput = await page.$$('input[placeholder*="검색"]');
  if (searchInput.length > 0) {
    await searchInput[0].fill('디버그테스트3');
    await page.waitForTimeout(1000);
  }
  
  console.log('2. Finding and clicking play button...');
  const playButtons = await page.$$('button:has-text("플레이")');
  if (playButtons.length > 0) {
    await playButtons[0].click();
    await page.waitForTimeout(2500);
    
    console.log('3. GAME BOARD SCREENSHOT');
    await page.screenshot({ path: '/tmp/final_01_game_board.png', fullPage: false });
    
    // Get all text content
    const bodyText = await page.$eval('body', el => el.innerText);
    console.log('4. TEXT ANALYSIS:');
    if (bodyText.includes('↓')) console.log('   ✓ Down arrow (↓)');
    if (bodyText.includes('x3')) console.log('   ✓ Craft badge x3');
    if (bodyText.includes('Move')) console.log('   ✓ Moves counter');
    if (bodyText.includes('Score')) console.log('   ✓ Score display');
    
    // Get HTML
    const html = await page.content();
    console.log('5. HTML ANALYSIS:');
    let craftCnt = 0;
    for (let i = 0; i < html.length; i++) {
      if (html.substr(i, 7) === 'craft_s') craftCnt++;
    }
    console.log('   craft_s count: ' + craftCnt);
    
    // Check tile elements
    const tiles = await page.$$('.tile-renderer');
    console.log('6. TILES: ' + tiles.length + ' elements');
    
    console.log('7. FINAL SCREENSHOT');
    await page.screenshot({ path: '/tmp/final_02_final.png', fullPage: false });
    
  }
  
  await browser.close();
  console.log('Done!');
})();

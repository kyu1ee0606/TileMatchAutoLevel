import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('1. Navigating to Play tab...');
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  
  // Click Play tab
  const playTab = await page.locator('text=플레이').first();
  await playTab.click();
  await page.waitForTimeout(1500);
  
  console.log('2. Looking for local levels...');
  // Get all level items visible
  const levelItems = await page.locator('[class*="level"], div').all();
  console.log(`   Found ${levelItems.length} total items`);
  
  // Look for first playable level
  const playButtons = await page.locator('button:has-text("플레이")').all();
  console.log(`   Found ${playButtons.length} play buttons`);
  
  if (playButtons.length > 0) {
    console.log('3. Clicking first play button...');
    await playButtons[0].click();
    await page.waitForTimeout(2000);
    
    console.log('4. Game board loaded, taking screenshot...');
    await page.screenshot({ path: '/tmp/30_game_board_loaded.png' });
    
    // Check for craft_s elements
    const pageContent = await page.content();
    if (pageContent.includes('craft_s') || pageContent.includes('↓')) {
      console.log('   ✓ Found craft_s gimmick reference!');
    }
    
    console.log('5. Looking for tiles to click...');
    // Look for clickable elements
    const clickables = await page.locator('[class*="tile"], [style*="cursor: pointer"]').all();
    console.log(`   Found ${clickables.length} potentially clickable tiles`);
    
    if (clickables.length > 5) {
      console.log('6. Clicking on various tiles to test mechanics...');
      
      // Click first tile
      await clickables[0].click();
      await page.waitForTimeout(400);
      await page.screenshot({ path: '/tmp/31_after_first_click.png' });
      
      // Click another tile
      await clickables[5].click();
      await page.waitForTimeout(400);
      await page.screenshot({ path: '/tmp/32_after_second_click.png' });
      
      // Click a third tile
      await clickables[10].click();
      await page.waitForTimeout(400);
    }
    
    console.log('7. Final game state screenshot...');
    await page.screenshot({ path: '/tmp/33_game_state.png' });
  }
  
  await browser.close();
  console.log('✅ Test complete!');
})();

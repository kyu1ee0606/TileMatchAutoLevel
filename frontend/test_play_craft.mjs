import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('1. Loading page...');
  await page.goto('http://localhost:5173', { waitUntil: 'load' });
  await page.waitForTimeout(1000);
  
  // Click play tab
  await page.click('text=플레이');
  await page.waitForTimeout(1000);
  
  // Search for 디버그
  const searchInput = await page.$('input[placeholder*="검색"]');
  if (searchInput) {
    await searchInput.fill('디버그');
    await page.waitForTimeout(800);
  }
  
  console.log('2. Finding play buttons...');
  const allElements = await page.$$('button, div, a');
  let foundPlay = false;
  
  for (let elem of allElements) {
    const text = await elem.textContent().catch(() => '');
    if (text === '▶ 플레이' && !foundPlay) {
      console.log('   Clicking play button...');
      await elem.click();
      foundPlay = true;
      await page.waitForTimeout(2000);
      break;
    }
  }
  
  if (foundPlay) {
    console.log('3. Game board loaded! Taking screenshot...');
    await page.screenshot({ path: '/tmp/50_game_board.png' });
    
    // Get detailed page structure
    const tileRenderers = await page.$$('[class*="tile"]');
    console.log(`   Found ${tileRenderers.length} tile elements`);
    
    // Look for craft indicators
    const html = await page.content();
    let craftCount = (html.match(/craft_/g) || []).length;
    let arrowCount = (html.match(/↓|↑|→|←/g) || []).length;
    console.log(`   craft_ references: ${craftCount}`);
    console.log(`   arrow symbols: ${arrowCount}`);
    
    // Wait a moment and take another screenshot
    await page.waitForTimeout(500);
    
    console.log('4. Looking for interactable elements...');
    // Try clicking on different areas
    const gameArea = await page.$('[class*="game"], [class*="board"], svg');
    if (gameArea) {
      const box = await gameArea.boundingBox();
      if (box) {
        console.log(`   Game area found at: ${box.x}, ${box.y}, ${box.width}x${box.height}`);
        
        // Try clicking in the center
        const centerX = box.x + box.width / 2;
        const centerY = box.y + box.height / 2;
        console.log(`   Clicking at center: ${centerX}, ${centerY}`);
        
        await page.click(`[role="button"], button`);
        await page.waitForTimeout(300);
      }
    }
    
    console.log('5. Final screenshot');
    await page.screenshot({ path: '/tmp/51_game_interaction.png' });
    
    // Get game state from page
    const bodyHTML = await page.$eval('body', el => el.innerHTML);
    if (bodyHTML.includes('goal') || bodyHTML.includes('Goal')) {
      console.log('   ✓ Found goal indicator');
    }
    if (bodyHTML.includes('move') || bodyHTML.includes('Move')) {
      console.log('   ✓ Found move counter');
    }
  }
  
  await browser.close();
  console.log('✅ Test complete!');
})();

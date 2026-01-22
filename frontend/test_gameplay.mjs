import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('1. Loading and starting game...');
  await page.goto('http://localhost:5173', { waitUntil: 'load' });
  await page.waitForTimeout(1000);
  
  // Navigate to play
  await page.click('text=플레이');
  await page.waitForTimeout(1000);
  
  // Search and play
  const searchInput = await page.$('input[placeholder*="검색"]');
  if (searchInput) {
    await searchInput.fill('디버그');
    await page.waitForTimeout(800);
  }
  
  // Click first play button
  const playButtons = await page.$$('button:has-text("플레이")');
  if (playButtons.length > 0) {
    await playButtons[0].click();
    await page.waitForTimeout(2000);
    
    console.log('2. Initial game state screenshot');
    await page.screenshot({ path: '/tmp/60_initial_game.png' });
    
    // Get all tile positions
    console.log('3. Finding tiles...');
    const tileElements = await page.$$('[class*="tile"]');
    console.log('   Found tiles: ' + tileElements.length);
    
    // Get bounding boxes of first few tiles
    const tiles = [];
    for (let i = 0; i < Math.min(5, tileElements.length); i++) {
      const box = await tileElements[i].boundingBox();
      if (box) {
        tiles.push({ index: i, box: box });
      }
    }
    
    console.log('   Tile positions collected: ' + tiles.length);
    
    if (tiles.length >= 2) {
      console.log('4. Clicking on tiles to test matching...');
      
      // Click first tile
      if (tiles[0]) {
        const x = tiles[0].box.x + tiles[0].box.width / 2;
        const y = tiles[0].box.y + tiles[0].box.height / 2;
        console.log('   Clicking tile 0');
        await page.mouse.click(x, y);
        await page.waitForTimeout(300);
      }
      
      // Click second tile
      if (tiles[1]) {
        const x = tiles[1].box.x + tiles[1].box.width / 2;
        const y = tiles[1].box.y + tiles[1].box.height / 2;
        console.log('   Clicking tile 1');
        await page.mouse.click(x, y);
        await page.waitForTimeout(300);
      }
      
      console.log('5. After clicks screenshot');
      await page.screenshot({ path: '/tmp/61_after_clicks.png' });
    }
    
    console.log('6. Final game state');
    await page.screenshot({ path: '/tmp/63_final_game.png' });
  }
  
  await browser.close();
  console.log('Done!');
})();

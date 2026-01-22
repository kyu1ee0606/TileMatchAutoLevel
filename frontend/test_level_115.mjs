import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('1. Navigating to game...');
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  
  // Click play tab
  console.log('2. Clicking Play tab...');
  const playTab = await page.$('text=플레이');
  if (playTab) {
    await playTab.click();
    await page.waitForTimeout(1000);
  }
  
  // Search for level 115
  console.log('3. Searching for level 115...');
  const searchInput = await page.$('input[placeholder*="검색"]');
  if (searchInput) {
    await searchInput.fill('115');
    await page.waitForTimeout(800);
  }
  
  // Wait and look for results
  await page.waitForTimeout(500);
  
  // Find clickable items
  console.log('4. Looking for level 115 item...');
  const allItems = await page.$$('*');
  let found = false;
  
  for (let item of allItems) {
    const text = await item.textContent().catch(() => '');
    if (text && text.includes('115')) {
      console.log('   Found item with 115, clicking...');
      try {
        await item.click();
        found = true;
        await page.waitForTimeout(1000);
        break;
      } catch (e) {
        // Item not clickable, continue
      }
    }
  }
  
  await page.screenshot({ path: '/tmp/10_after_search.png' });
  
  // Try scrolling in the level list to find level 115
  console.log('5. Scrolling in level list...');
  const levelList = await page.$('[class*="list"], [class*="List"], div');
  if (levelList) {
    for (let i = 0; i < 10; i++) {
      await page.evaluate(() => {
        const scrollable = document.querySelector('[class*="list"]') || window;
        if (scrollable.scrollBy) {
          scrollable.scrollBy(0, 200);
        }
      });
      await page.waitForTimeout(200);
    }
  }
  
  await page.screenshot({ path: '/tmp/11_after_scroll.png' });
  
  // List all text on page containing numbers
  console.log('6. Available items on page...');
  const bodyText = await page.$eval('body', el => el.innerText);
  const lines = bodyText.split('\n');
  const levelLines = lines.filter(l => l.includes('test') || l.includes('level')).slice(0, 10);
  console.log('   Level items:', levelLines);
  
  await browser.close();
  console.log('Done!');
})();

import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  console.log('1. Navigating to http://localhost:5173...');
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  
  // Get page info
  const title = await page.title();
  console.log('   Page title:', title);
  
  // Look for level 115 in the levels list by scrolling
  console.log('2. Scrolling through levels list to find level 115...');
  const levelsList = await page.$('[class*="level"]');
  
  // Click on "플레이" tab to go to play mode
  const playTab = await page.$('text=플레이');
  if (playTab) {
    console.log('3. Found Play tab, clicking it...');
    await playTab.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: '/tmp/04_play_tab.png' });
  }
  
  // Try to find level 115
  console.log('4. Looking for level 115...');
  
  // Type in search or level selector
  const searchInput = await page.$('input[placeholder*="검색"], input[placeholder*="search"]');
  if (searchInput) {
    console.log('   Found search input, typing level 115...');
    await searchInput.fill('115');
    await page.waitForTimeout(500);
    await page.screenshot({ path: '/tmp/05_search_level.png' });
  }
  
  // Look for clickable level item
  const level115 = await page.$('text=level_115');
  if (!level115) {
    console.log('   Level 115 not found with exact match, looking for alternatives...');
    const allLevelItems = await page.$$('[class*="level"], button:has-text("115")');
    console.log(`   Found ${allLevelItems.length} potential level items`);
  } else {
    console.log('   Found level 115!');
    await level115.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: '/tmp/06_level_115_selected.png' });
  }
  
  // Look for play button
  console.log('5. Looking for play/start button...');
  const buttons = await page.$$('button');
  for (let i = 0; i < Math.min(10, buttons.length); i++) {
    const text = await buttons[i].textContent();
    const ariaLabel = await buttons[i].getAttribute('aria-label');
    console.log(`   Button ${i}: "${text}" (aria: ${ariaLabel})`);
    
    if (text.includes('플레이') || text.includes('시작') || text.includes('Start')) {
      console.log(`   >> Clicking button ${i}`);
      await buttons[i].click();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: '/tmp/07_game_started.png' });
      break;
    }
  }
  
  // Take final screenshot
  console.log('6. Taking final screenshots...');
  await page.screenshot({ path: '/tmp/08_final_state.png' });
  
  // Check page structure
  const html = await page.content();
  if (html.includes('craft_s') || html.includes('arrow')) {
    console.log('   ✓ Found craft_s or arrow reference in HTML');
  }
  if (html.includes('↓')) {
    console.log('   ✓ Found ↓ arrow symbol in HTML');
  }
  
  await browser.close();
  console.log('✅ Test completed!');
})();

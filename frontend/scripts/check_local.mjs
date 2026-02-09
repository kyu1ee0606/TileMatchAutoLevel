import { chromium } from 'playwright';

const BASE_URL = 'http://localhost:5173';

async function main() {
  const browser = await chromium.launch({ headless: false, slowMo: 300 });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();
  
  try {
    console.log('📱 페이지 접속...');
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // Check localStorage
    const storageCheck = await page.evaluate(() => {
      const keys = Object.keys(localStorage);
      const result = {};
      keys.forEach(key => {
        try {
          const value = localStorage.getItem(key);
          result[key] = value ? value.substring(0, 200) + '...' : 'empty';
        } catch (e) {
          result[key] = 'error';
        }
      });
      return { keys, result, tilematch: localStorage.getItem('tilematch_local_levels') };
    });
    
    console.log('\n📦 localStorage 키 목록:');
    storageCheck.keys.forEach(k => console.log(`   - ${k}`));
    
    if (storageCheck.tilematch) {
      const parsed = JSON.parse(storageCheck.tilematch);
      console.log(`\n✅ tilematch_local_levels: ${parsed.length}개 레벨`);
      parsed.slice(0, 3).forEach(l => console.log(`   - ${l.id}: ${l.name}`));
    } else {
      console.log('\n❌ tilematch_local_levels 키가 비어있음!');
    }
    
    // Navigate to Local Levels tab
    console.log('\n🔍 로컬 레벨 탭으로 이동...');
    
    // Click on "로컬 레벨" tab
    const localLevelTab = await page.locator('button:has-text("로컬 레벨")');
    if (await localLevelTab.count() > 0) {
      await localLevelTab.click();
      await page.waitForTimeout(2000);
      console.log('   로컬 레벨 탭 클릭됨');
    } else {
      console.log('   로컬 레벨 탭 못찾음, 다른 방법 시도...');
      // Try finding by different selector
      const tabs = await page.locator('button').allTextContents();
      console.log('   사용 가능한 버튼:', tabs.filter(t => t.length < 30).join(', '));
    }
    
    await page.screenshot({ path: 'screenshots/local_levels_check.png', fullPage: true });
    console.log('\n📸 스크린샷: screenshots/local_levels_check.png');
    
    // Keep browser open for inspection
    console.log('\n⏳ 브라우저 열린 상태 유지 (30초)...');
    await page.waitForTimeout(30000);
    
  } catch (error) {
    console.error('❌ 오류:', error.message);
  } finally {
    await browser.close();
  }
}

main().catch(console.error);

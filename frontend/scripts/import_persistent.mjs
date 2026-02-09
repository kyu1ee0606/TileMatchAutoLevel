import { chromium } from 'playwright';
import { readFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

const BASE_URL = 'http://localhost:5173';
const LEVELS_FILE = '/Users/casualdev/TileMatchAutoLevel/backend/test_results/pattern_mix_levels_20260128_182121.json';

// Use a persistent user data directory
const USER_DATA_DIR = join(homedir(), '.tilematch-test-browser');

async function main() {
  console.log('🚀 영구 브라우저 시작...');
  console.log(`   데이터 저장 위치: ${USER_DATA_DIR}`);
  
  // Launch with persistent context
  const context = await chromium.launchPersistentContext(USER_DATA_DIR, {
    headless: false,
    viewport: { width: 1400, height: 900 },
    slowMo: 200
  });
  
  const page = context.pages()[0] || await context.newPage();
  
  try {
    const levelsData = JSON.parse(readFileSync(LEVELS_FILE, 'utf-8'));
    console.log(`📦 ${levelsData.length}개 레벨 로드됨`);
    
    console.log('📱 페이지 접속...');
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // Save to localStorage
    console.log('💾 로컬 스토리지에 저장 중...');
    
    const result = await page.evaluate((levels) => {
      const LOCAL_LEVELS_KEY = 'tilematch_local_levels';
      const now = new Date().toISOString();
      
      let existingLevels = [];
      try {
        const stored = localStorage.getItem(LOCAL_LEVELS_KEY);
        if (stored) existingLevels = JSON.parse(stored);
      } catch (e) {}
      
      const newLevels = levels.map(level => ({
        id: level.id,
        name: level.name,
        description: `패턴 믹싱 테스트`,
        tags: level.tags || ['pattern_mix'],
        source: 'api_test',
        level_data: level.level_data,
        created_at: level.created_at || now,
        saved_at: now,
        difficulty: level.difficulty,
        grade: level.grade,
        validation_status: 'not_tested'
      }));
      
      const existingIds = new Set(existingLevels.map(l => l.id));
      const levelsToAdd = newLevels.filter(l => !existingIds.has(l.id));
      const merged = [...existingLevels, ...levelsToAdd];
      
      localStorage.setItem(LOCAL_LEVELS_KEY, JSON.stringify(merged));
      
      return { added: levelsToAdd.length, total: merged.length };
    }, levelsData);
    
    console.log(`✅ 저장 완료! 추가: ${result.added}개, 전체: ${result.total}개`);
    
    // Navigate to Local Levels tab
    console.log('\n🔍 로컬 레벨 탭으로 이동...');
    const localTab = page.locator('button:has-text("로컬 레벨")');
    if (await localTab.count() > 0) {
      await localTab.click();
      await page.waitForTimeout(2000);
    }
    
    // Take screenshot
    await page.screenshot({ path: 'screenshots/local_levels_saved.png', fullPage: true });
    console.log('📸 스크린샷 저장됨');
    
    console.log('\n⏳ 브라우저 열린 상태 유지 (60초)...');
    console.log('   이 브라우저에서 로컬 레벨을 확인하세요!');
    await page.waitForTimeout(60000);
    
  } catch (error) {
    console.error('❌ 오류:', error.message);
  } finally {
    await context.close();
    console.log('\n🏁 완료!');
  }
}

main().catch(console.error);

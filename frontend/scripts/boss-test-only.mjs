/**
 * Boss Level Test Only - 보스 레벨 난이도 검증만 실행
 * 이미 레벨이 생성된 상태에서 테스트만 수행
 */

import { chromium } from 'playwright';

const BASE_URL = 'http://localhost:5173';

async function main() {
  console.log('🚀 브라우저 시작...');

  const browser = await chromium.launch({
    headless: false,
    slowMo: 400
  });

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });

  const page = await context.newPage();

  try {
    // 1. 메인 페이지 접속
    console.log('📱 메인 페이지 접속...');
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    // 2. 프로덕션 탭 클릭
    console.log('🚀 프로덕션 탭 클릭...');
    await page.click('button:has-text("프로덕션")');
    await page.waitForTimeout(2000);

    // 3. 배치 선택 (드롭다운에서 톱니바퀴 배치 선택)
    console.log('📦 배치 선택...');
    const batchSelect = await page.locator('select').first();

    if (await batchSelect.count() > 0) {
      // 옵션 목록 확인
      const batchOptions = await batchSelect.locator('option').allTextContents();
      console.log('📋 배치 옵션:', batchOptions);

      // 톱니바퀴 배치 찾기
      const sawtoothBatch = batchOptions.find(opt => opt.includes('톱니바퀴'));
      if (sawtoothBatch) {
        await batchSelect.selectOption({ label: sawtoothBatch });
        console.log(`✅ 배치 선택됨: ${sawtoothBatch}`);
      } else if (batchOptions.length > 0) {
        // 첫 번째 배치 선택
        await batchSelect.selectOption({ index: 0 });
        console.log(`✅ 첫 번째 배치 선택됨: ${batchOptions[0]}`);
      }
    } else {
      console.log('⚠️ 배치 드롭다운을 찾을 수 없음');
    }

    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'screenshots/boss-01-batch-selected.png' });

    // 4. 테스트 서브탭 클릭
    console.log('🧪 테스트 서브탭 클릭...');
    await page.click('text=테스트');
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'screenshots/boss-02-test-tab.png' });

    // 5. "자동 (일괄)" 버튼 클릭
    console.log('🚀 자동 (일괄) 모드 선택...');

    // 모든 버튼 중에서 "일괄" 텍스트를 포함하는 버튼 찾기
    const allButtons = await page.locator('button').all();
    for (const btn of allButtons) {
      const text = await btn.textContent();
      if (text && text.includes('일괄')) {
        await btn.click();
        console.log(`✅ 클릭됨: ${text}`);
        break;
      }
    }

    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'screenshots/boss-03-batch-mode.png' });

    // 6. 보스 레벨 필터 선택
    console.log('👑 보스 레벨 필터 선택...');

    // 모든 select 요소 확인
    const allSelects = await page.locator('select').all();
    console.log(`📋 Select 요소 수: ${allSelects.length}`);

    for (let i = 0; i < allSelects.length; i++) {
      const select = allSelects[i];
      const options = await select.locator('option').allTextContents();
      console.log(`  Select ${i}: ${options.join(', ')}`);

      // 보스 레벨 옵션이 있는 select 찾기
      const bossOption = options.find(opt => opt.includes('보스'));
      if (bossOption) {
        await select.selectOption({ label: bossOption });
        console.log(`✅ 보스 필터 선택됨: ${bossOption}`);
        break;
      }
    }

    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/boss-04-filter.png' });

    // 7. 일괄 테스트 시작 버튼 클릭
    console.log('🎯 일괄 테스트 시작...');

    // 버튼 텍스트로 찾기
    const testButtons = await page.locator('button').all();
    let testStarted = false;

    for (const btn of testButtons) {
      const text = await btn.textContent();
      if (text && (text.includes('일괄 테스트 시작') || text.includes('테스트 시작'))) {
        const isDisabled = await btn.isDisabled();
        if (!isDisabled) {
          await btn.click();
          console.log(`✅ 테스트 시작됨: ${text}`);
          testStarted = true;
          break;
        } else {
          console.log(`⚠️ 버튼 비활성화됨: ${text}`);
        }
      }
    }

    if (!testStarted) {
      console.log('⚠️ 테스트 시작 버튼을 클릭할 수 없음');
      await page.screenshot({ path: 'screenshots/boss-error-no-start-btn.png', fullPage: true });
    } else {
      // 테스트 진행 모니터링
      console.log('⏳ 테스트 진행 중...');
      let lastProgress = '';
      let stableCount = 0;

      while (true) {
        await page.waitForTimeout(5000);

        // 페이지 텍스트에서 진행 상태 찾기
        const bodyText = await page.locator('body').textContent();
        const progressMatch = bodyText.match(/진행[:\s]*(\d+)\s*\/\s*(\d+)/);

        if (progressMatch) {
          const progressStr = `${progressMatch[1]}/${progressMatch[2]}`;
          if (progressStr !== lastProgress) {
            console.log(`🧪 진행: ${progressStr}`);
            lastProgress = progressStr;
            stableCount = 0;

            // 완료 확인
            if (progressMatch[1] === progressMatch[2]) {
              console.log('✅ 테스트 완료!');
              break;
            }
          } else {
            stableCount++;
          }
        }

        // 테스트 중지 버튼 확인
        const stopBtnExists = await page.locator('button:has-text("테스트 중지")').count() > 0;
        if (!stopBtnExists && stableCount > 0) {
          console.log('✅ 테스트 완료! (중지 버튼 없음)');
          break;
        }

        // 타임아웃
        if (stableCount > 60) {
          console.log('⚠️ 타임아웃');
          break;
        }
      }
    }

    // 8. 최종 결과 스크린샷
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'screenshots/boss-05-result.png', fullPage: true });

    // 9. 결과 요약
    console.log('\n📊 결과 확인 중...');
    const finalText = await page.locator('body').textContent();

    // 통계 추출
    const stats = finalText.match(/평균[^:]*:\s*[\d.]+|통과[^:]*:\s*[\d.]+%?|점수[^:]*:\s*[\d.]+/g);
    if (stats) {
      console.log('📈 결과:');
      stats.slice(0, 10).forEach(s => console.log(`   ${s}`));
    }

    console.log('\n✨ 완료!');
    console.log('📁 스크린샷: frontend/screenshots/boss-*.png');

    // 브라우저 유지
    await page.waitForTimeout(300000);

  } catch (error) {
    console.error('❌ 오류:', error.message);
    await page.screenshot({ path: 'screenshots/boss-error.png' }).catch(() => {});
  } finally {
    await browser.close();
  }
}

main().catch(console.error);

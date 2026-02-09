/**
 * Production Level Generation & Boss Level Test Automation
 * 1500개 레벨 톱니바퀴 형식 생성 및 보스 레벨 난이도 검증
 */

import { chromium } from 'playwright';

const BASE_URL = 'http://localhost:5173';

async function main() {
  console.log('🚀 브라우저 시작...');

  const browser = await chromium.launch({
    headless: false,
    slowMo: 200
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

    // 3. 배치 존재 여부 확인
    const noBatchMessage = await page.$('text=배치가 없습니다');

    if (noBatchMessage) {
      console.log('📦 새 1500 배치 (톱니바퀴) 생성...');
      await page.click('button:has-text("새 1500 배치 (톱니바퀴)")');
      await page.waitForTimeout(2000);
      console.log('✅ 배치 생성 완료');
    }

    // 4. 배치 정보 확인
    const batchInfo = await page.$eval(
      'select',
      el => el.value || el.textContent
    ).catch(() => '');
    console.log(`📊 현재 배치: ${batchInfo}`);

    // 5. "생성" 서브탭 클릭
    console.log('🎲 생성 서브탭 이동...');
    // 서브탭들 중 "생성" 찾기 (자동 생성이 아닌)
    const subTabs = await page.$$('button, a');
    for (const tab of subTabs) {
      const text = await tab.textContent();
      // "생성" 탭 (자동 생성이 아닌, 서브탭)
      if (text === '생성') {
        await tab.click();
        break;
      }
    }
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'screenshots/01-generation-tab.png' });

    // 6. 현재 생성된 레벨 수 확인 (0/1500 형식에서 추출)
    const allText = await page.locator('body').textContent();
    const countMatch = allText.match(/\((\d+)\/1500\)/);
    let generatedCount = countMatch ? parseInt(countMatch[1]) : 0;
    console.log(`📊 현재 생성된 레벨: ${generatedCount}/1500`);

    // 7. 생성 시작 (1500개 미만인 경우)
    if (generatedCount < 1500) {
      // "검증 기반 생성 시작" 버튼 찾기
      const startBtn = await page.$('button:has-text("검증 기반 생성 시작")');
      if (startBtn) {
        const isDisabled = await startBtn.evaluate(el => el.disabled);
        if (!isDisabled) {
          console.log('⏳ 1500개 레벨 생성 시작...');
          console.log('⚠️ 이 작업은 30분~2시간 소요될 수 있습니다.');
          console.log('💡 진행 상황은 15초마다 업데이트됩니다.');

          await startBtn.click();
          await page.waitForTimeout(3000);
          await page.screenshot({ path: 'screenshots/02-generation-started.png' });

          // 생성 진행 모니터링
          let lastProgress = 0;
          let stableCount = 0;

          while (true) {
            await page.waitForTimeout(15000); // 15초마다 체크

            // 진행률 확인 (X/1500 형식)
            const bodyText = await page.locator('body').textContent();
            const progressMatch = bodyText.match(/(\d+)\s*\/\s*1500/);

            let currentProgress = 0;
            if (progressMatch) {
              currentProgress = parseInt(progressMatch[1]);
            }

            if (currentProgress !== lastProgress && currentProgress > 0) {
              const percent = Math.round((currentProgress / 1500) * 100);
              console.log(`📈 진행: ${currentProgress}/1500 (${percent}%)`);
              lastProgress = currentProgress;
              stableCount = 0;

              // 100개마다 스크린샷
              if (currentProgress % 100 === 0) {
                await page.screenshot({ path: `screenshots/gen-${currentProgress}.png` });
              }
            } else {
              stableCount++;
            }

            // 완료 확인
            if (currentProgress >= 1500) {
              console.log('✅ 레벨 생성 완료!');
              break;
            }

            // 5분간 변화 없으면 확인
            if (stableCount > 20) {
              // 중지 버튼이 없으면 완료
              const stopBtn = await page.$('button:has-text("생성 중지")');
              if (!stopBtn) {
                console.log('✅ 레벨 생성 완료!');
                break;
              }
              // 있으면 계속 대기
              console.log('⏳ 생성 진행 중...');
              stableCount = 15; // 리셋하지 않고 카운트 유지
            }
          }
        }
      } else {
        // 일반 생성 시작 버튼 시도
        const altStartBtn = await page.$('button:has-text("생성 시작")');
        if (altStartBtn) {
          console.log('⏳ 레벨 생성 시작 (일반 모드)...');
          await altStartBtn.click();
        }
      }
    } else {
      console.log('✅ 이미 1500개 레벨 생성 완료');
    }

    await page.screenshot({ path: 'screenshots/03-generation-complete.png' });

    // 8. "테스트" 서브탭 이동
    console.log('🧪 테스트 서브탭 이동...');
    const testSubTabs = await page.$$('button, a');
    for (const tab of testSubTabs) {
      const text = await tab.textContent();
      if (text === '테스트') {
        await tab.click();
        break;
      }
    }
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'screenshots/04-test-tab.png' });

    // 9. "자동 (일괄)" 모드 선택
    console.log('🚀 일괄 자동 테스트 모드 선택...');
    const batchModeBtn = await page.$('button:has-text("자동 (일괄)")');
    if (batchModeBtn) {
      await batchModeBtn.click();
      await page.waitForTimeout(1000);
    }

    // 10. 보스 레벨 필터 선택
    console.log('👑 보스 레벨 필터 선택...');
    const filterSelect = await page.$('select');
    if (filterSelect) {
      // 보스 레벨 옵션 선택
      await filterSelect.selectOption({ label: '보스 레벨 (10배수)' });
      console.log('✅ 보스 레벨 필터 적용');
    }

    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'screenshots/05-boss-filter.png' });

    // 11. 일괄 테스트 시작
    console.log('🎯 보스 레벨 난이도 검증 시작...');
    const testStartBtn = await page.$('button:has-text("일괄 테스트 시작")');
    if (testStartBtn) {
      const isDisabled = await testStartBtn.evaluate(el => el.disabled);
      if (!isDisabled) {
        await testStartBtn.click();
        console.log('✅ 테스트 시작됨 (150개 보스 레벨)');

        // 테스트 진행 모니터링
        let lastTestProgress = '';
        let testStableCount = 0;

        while (true) {
          await page.waitForTimeout(5000);

          // 진행 상태 확인
          const bodyText = await page.locator('body').textContent();
          const testMatch = bodyText.match(/진행[:\s]*(\d+)\s*\/\s*(\d+)/);

          if (testMatch) {
            const current = testMatch[1];
            const total = testMatch[2];
            const progressStr = `${current}/${total}`;

            if (progressStr !== lastTestProgress) {
              console.log(`🧪 테스트 진행: ${progressStr}`);
              lastTestProgress = progressStr;
              testStableCount = 0;
            } else {
              testStableCount++;
            }

            // 완료 확인
            if (parseInt(current) >= parseInt(total)) {
              console.log('✅ 테스트 완료!');
              break;
            }
          }

          // 3분간 변화 없으면 완료로 간주
          if (testStableCount > 36) {
            const stopTestBtn = await page.$('button:has-text("테스트 중지")');
            if (!stopTestBtn) {
              console.log('✅ 테스트 완료!');
              break;
            }
          }
        }
      } else {
        console.log('⚠️ 테스트 시작 버튼 비활성화 - 먼저 레벨을 생성하세요');
      }
    }

    // 12. 최종 결과 스크린샷
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'screenshots/06-test-complete.png', fullPage: true });

    // 13. 결과 요약 출력
    console.log('\n📊 테스트 결과 확인...');

    const finalText = await page.locator('body').textContent();

    // 결과 통계 추출
    const avgMatch = finalText.match(/평균[^:]*:\s*([\d.]+)/g);
    const passMatch = finalText.match(/통과[^:]*:\s*([\d.]+)/g);
    const scoreMatch = finalText.match(/점수[^:]*:\s*([\d.]+)/g);

    if (avgMatch || passMatch || scoreMatch) {
      console.log('📈 결과 요약:');
      avgMatch?.forEach(m => console.log(`   ${m}`));
      passMatch?.forEach(m => console.log(`   ${m}`));
      scoreMatch?.forEach(m => console.log(`   ${m}`));
    }

    console.log('\n✨ 자동화 완료!');
    console.log('📁 스크린샷: frontend/screenshots/');
    console.log('\n브라우저에서 상세 결과를 확인하세요.');
    console.log('종료하려면 Ctrl+C');

    // 브라우저 유지
    await page.waitForTimeout(600000);

  } catch (error) {
    console.error('❌ 오류:', error.message);
    await page.screenshot({ path: 'screenshots/error.png' }).catch(() => {});
    throw error;
  } finally {
    await browser.close();
  }
}

main().catch(console.error);

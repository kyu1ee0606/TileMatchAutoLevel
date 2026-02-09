/**
 * E2E Test: Production Dashboard - Generate 1500 levels with sawtooth pattern
 * Uses Playwright to automate the web UI at http://localhost:5173
 */

import { chromium } from 'playwright';

const BASE_URL = 'http://localhost:5173';

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function takeScreenshot(page, name) {
  const screenshotDir = '/Users/casualdev/TileMatchAutoLevel/frontend/screenshots';
  const path = `${screenshotDir}/${name}.png`;
  await page.screenshot({ path, fullPage: true });
  console.log(`[Screenshot] ${name} saved to ${path}`);
}

async function main() {
  console.log('=== E2E Test: Production 1500 Level Generation ===\n');

  const browser = await chromium.launch({
    headless: false,
    args: ['--window-size=1400,900']
  });
  const context = await browser.newContext({
    viewport: { width: 1400, height: 900 }
  });
  const page = await context.newPage();

  try {
    // ============================
    // Step 1: Navigate to the app
    // ============================
    console.log('[Step 1] Navigating to', BASE_URL);
    await page.goto(BASE_URL, { waitUntil: 'load', timeout: 60000 });
    await sleep(2000);
    await takeScreenshot(page, '01_initial_page');
    console.log('[Step 1] Initial page loaded\n');

    // ============================
    // Step 2: Click Production tab
    // ============================
    console.log('[Step 2] Clicking Production tab');
    // The tab text is "🚀 프로덕션"
    const productionTab = page.locator('button', { hasText: '프로덕션' });
    await productionTab.click();
    await sleep(1500);
    await takeScreenshot(page, '02_production_tab');
    console.log('[Step 2] Production Dashboard loaded\n');

    // ============================
    // Step 3: Create new batch with sawtooth pattern
    // ============================
    console.log('[Step 3] Creating new 1500 batch with sawtooth pattern');
    // Click "+ 새 1500 배치 (톱니바퀴)" button
    const sawtoothButton = page.locator('button', { hasText: '톱니바퀴' });
    await sawtoothButton.click();
    await sleep(1500);
    await takeScreenshot(page, '03_batch_created');
    console.log('[Step 3] Sawtooth batch created\n');

    // ============================
    // Step 4: Configure - ensure validation is DISABLED
    // ============================
    console.log('[Step 4] Configuring generation settings');
    // After creating a batch, we should be on the "생성" (Generate) tab automatically
    // Check if the validation toggle is OFF (it's OFF by default per code: useValidatedGeneration defaults to false)

    await takeScreenshot(page, '04_generate_tab');

    // The validation toggle "난이도 검증 기반 생성" - check if it's already off
    // Default is false (OFF), so we should be good. Let's verify by checking the toggle state.
    const validationToggle = page.locator('button').filter({ has: page.locator('.bg-green-500') }).first();
    const toggleExists = await validationToggle.count();

    if (toggleExists > 0) {
      // Toggle is ON (green), click to disable
      console.log('[Step 4] Validation toggle is ON, disabling...');
      // Find the toggle near "난이도 검증 기반 생성" text
      const validationSection = page.locator('text=난이도 검증 기반 생성').locator('..').locator('button');
      await validationSection.click();
      await sleep(500);
    } else {
      console.log('[Step 4] Validation toggle is already OFF (default)');
    }

    await takeScreenshot(page, '04_settings_configured');
    console.log('[Step 4] Settings configured\n');

    // ============================
    // Step 5: Start generation
    // ============================
    console.log('[Step 5] Starting level generation');

    // Click the generate button - text contains "생성 시작"
    const generateButton = page.locator('button', { hasText: '생성 시작' });
    await generateButton.click();
    await sleep(2000);
    await takeScreenshot(page, '05_generation_started');
    console.log('[Step 5] Generation started\n');

    // ============================
    // Step 6: Monitor progress
    // ============================
    console.log('[Step 6] Monitoring generation progress...');

    let isComplete = false;
    let lastProgress = '';
    let screenshotCount = 0;
    const maxWaitMs = 30 * 60 * 1000; // 30 minutes max
    const startTime = Date.now();

    while (!isComplete && (Date.now() - startTime) < maxWaitMs) {
      await sleep(10000); // Check every 10 seconds

      // Check for progress text
      const progressText = await page.locator('text=/레벨 \\d+\\/\\d+/').first().textContent().catch(() => '');
      const percentText = await page.locator('text=/\\d+\\.\\d+%/').first().textContent().catch(() => '');

      if (progressText && progressText !== lastProgress) {
        console.log(`[Progress] ${progressText} ${percentText}`);
        lastProgress = progressText;
      }

      // Check for completion
      const completedIndicator = await page.locator('text=완료').first().count();
      const statusText = await page.locator('text=/생성 중|완료|일시 정지|오류/').first().textContent().catch(() => '');

      // Take periodic screenshots (every ~60 seconds)
      screenshotCount++;
      if (screenshotCount % 6 === 0) {
        await takeScreenshot(page, `06_progress_${Math.floor((Date.now() - startTime) / 1000)}s`);
      }

      // Check if generation is complete
      if (statusText === '완료') {
        isComplete = true;
        console.log('[Step 6] Generation completed!');
      }

      // Also check if the progress shows 1500/1500
      if (progressText && progressText.includes('1500/1500')) {
        isComplete = true;
        console.log('[Step 6] All 1500 levels generated!');
      }
    }

    if (!isComplete) {
      console.log('[Step 6] WARNING: Timed out waiting for generation to complete');
    }

    await takeScreenshot(page, '07_generation_complete');

    // ============================
    // Step 7: Verify results
    // ============================
    console.log('\n[Step 7] Verifying generation results');

    // Get final progress info
    const finalProgressText = await page.locator('text=/레벨 \\d+\\/\\d+/').first().textContent().catch(() => 'N/A');
    const finalStatus = await page.locator('text=/완료|생성 중|오류/').first().textContent().catch(() => 'N/A');

    console.log(`[Result] Final progress: ${finalProgressText}`);
    console.log(`[Result] Status: ${finalStatus}`);

    // Check for completion notification
    const notification = await page.locator('text=/레벨 생성 완료/').first().textContent().catch(() => null);
    if (notification) {
      console.log(`[Result] Notification: ${notification}`);
    }

    // Take final screenshot
    await takeScreenshot(page, '08_final_result');

    // Click on Overview tab to see stats
    const overviewTab = page.locator('button', { hasText: '개요' });
    await overviewTab.click();
    await sleep(2000);
    await takeScreenshot(page, '09_overview_stats');

    console.log('\n=== E2E Test Complete ===');

    // Keep browser open for a bit so user can see results
    await sleep(5000);

  } catch (error) {
    console.error('[ERROR]', error.message);
    await takeScreenshot(page, 'error_state');
    throw error;
  } finally {
    await browser.close();
  }
}

main().catch(err => {
  console.error('Test failed:', err);
  process.exit(1);
});

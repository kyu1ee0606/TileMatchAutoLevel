/**
 * Production Dashboard Level Generation Automation
 *
 * This script automates the level generation process using Playwright.
 * Run with: node scripts/production-automation.mjs
 */

import { chromium } from 'playwright';

const BASE_URL = 'http://localhost:5173';

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function main() {
  console.log('Starting Production Dashboard automation...');

  // Launch browser
  const browser = await chromium.launch({
    headless: false, // Set to true for headless mode
    slowMo: 100 // Slow down for visibility
  });

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });

  const page = await context.newPage();

  try {
    // Step 1: Navigate to the application
    console.log('Step 1: Navigating to the application...');
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');
    console.log('  - Page loaded successfully');

    // Take initial screenshot
    await page.screenshot({ path: 'screenshots/01-initial-page.png', fullPage: true });
    console.log('  - Screenshot saved: 01-initial-page.png');

    // Step 2: Click on Production tab
    console.log('Step 2: Clicking on Production tab...');
    const productionTab = page.locator('button:has-text("프로덕션")');
    await productionTab.click();
    await sleep(1000);
    console.log('  - Production tab clicked');

    await page.screenshot({ path: 'screenshots/02-production-tab.png', fullPage: true });
    console.log('  - Screenshot saved: 02-production-tab.png');

    // Step 3: Check if we need to create a new batch or use existing one
    console.log('Step 3: Checking for existing batches...');

    // Look for "새 1500 배치 (톱니바퀴)" button
    const newBatchButton = page.locator('button:has-text("새 1500 배치 (톱니바퀴)")');

    if (await newBatchButton.isVisible()) {
      console.log('  - Creating new 1500 level batch (sawtooth)...');
      await newBatchButton.click();
      await sleep(2000);
      console.log('  - New batch created');

      await page.screenshot({ path: 'screenshots/03-batch-created.png', fullPage: true });
      console.log('  - Screenshot saved: 03-batch-created.png');
    } else {
      console.log('  - Using existing batch');
    }

    // Step 4: Navigate to Generate tab if not already there
    console.log('Step 4: Navigating to Generate tab...');
    const generateTabButton = page.locator('button:has-text("레벨 생성")');
    if (await generateTabButton.isVisible()) {
      await generateTabButton.click();
      await sleep(1000);
    }

    await page.screenshot({ path: 'screenshots/04-generate-tab.png', fullPage: true });
    console.log('  - Screenshot saved: 04-generate-tab.png');

    // Step 5: Start generation
    console.log('Step 5: Starting level generation...');
    const startButton = page.locator('button:has-text("생성 시작")');

    if (await startButton.isVisible()) {
      await startButton.click();
      console.log('  - Generation started');
    } else {
      console.log('  - Start button not visible, generation may already be in progress');
    }

    await page.screenshot({ path: 'screenshots/05-generation-started.png', fullPage: true });
    console.log('  - Screenshot saved: 05-generation-started.png');

    // Step 6: Monitor progress
    console.log('Step 6: Monitoring generation progress...');
    let lastProgress = 0;
    let stableCount = 0;
    const maxStableChecks = 10; // After 10 stable checks (~50 seconds), assume complete or stuck

    while (true) {
      await sleep(5000); // Check every 5 seconds

      // Try to get progress text
      const progressText = await page.locator('text=/레벨 \\d+\\/\\d+/').first();

      if (await progressText.isVisible()) {
        const text = await progressText.textContent();
        const match = text.match(/레벨 (\d+)\/(\d+)/);

        if (match) {
          const current = parseInt(match[1]);
          const total = parseInt(match[2]);
          const percentage = ((current / total) * 100).toFixed(1);

          console.log(`  - Progress: ${current}/${total} levels (${percentage}%)`);

          if (current === lastProgress) {
            stableCount++;
          } else {
            stableCount = 0;
            lastProgress = current;
          }

          // Check if completed
          if (current >= total) {
            console.log('  - Generation completed!');
            break;
          }

          // Take periodic screenshots
          if (current % 100 === 0) {
            await page.screenshot({
              path: `screenshots/progress-${current}.png`,
              fullPage: true
            });
            console.log(`  - Screenshot saved: progress-${current}.png`);
          }
        }
      } else {
        stableCount++;
      }

      // Check if generation seems stuck or completed
      if (stableCount >= maxStableChecks) {
        console.log('  - Progress appears stable, checking status...');

        // Check for completion status
        const completedText = await page.locator('text=/완료/').first();
        if (await completedText.isVisible()) {
          console.log('  - Generation completed!');
          break;
        }

        // Check if paused or error
        const pausedText = await page.locator('text=/일시 정지|오류/').first();
        if (await pausedText.isVisible()) {
          console.log('  - Generation paused or error occurred');
          break;
        }

        // Reset stable count and continue monitoring
        stableCount = 0;
      }
    }

    // Final screenshot
    await page.screenshot({ path: 'screenshots/06-final-status.png', fullPage: true });
    console.log('  - Screenshot saved: 06-final-status.png');

    console.log('\n=== Automation Complete ===');
    console.log('Screenshots saved in frontend/screenshots/ directory');

  } catch (error) {
    console.error('Error during automation:', error);
    await page.screenshot({ path: 'screenshots/error-screenshot.png', fullPage: true });
    console.log('Error screenshot saved');
  } finally {
    // Keep browser open for manual inspection
    console.log('\nBrowser will remain open. Press Ctrl+C to close.');
    await sleep(60 * 60 * 1000); // Keep open for 1 hour
    await browser.close();
  }
}

// Create screenshots directory
import { mkdir } from 'fs/promises';
try {
  await mkdir('screenshots', { recursive: true });
} catch (e) {
  // Directory may already exist
}

main().catch(console.error);

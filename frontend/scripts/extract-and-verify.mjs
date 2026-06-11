/**
 * Extract latest production batch from IndexedDB and verify via /api/analyze/batch-verify.
 * Goal: produce a failure-distribution report so we can target improvements.
 */
import { firefox, chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const BASE_URL = 'http://localhost:5173';
const API_URL = 'http://localhost:8000';
const SAMPLE_SIZE = parseInt(process.env.SAMPLE_SIZE || '40', 10);
const ITERATIONS = parseInt(process.env.ITERATIONS || '40', 10);
const USER_DATA_DIR = process.env.USER_DATA_DIR || path.join(os.homedir(), '.tilematch-test-browser');

async function main() {
  const useFirefox = process.env.BROWSER === 'firefox' || USER_DATA_DIR.includes('ff-readonly');
  console.log(`Using ${useFirefox ? 'firefox' : 'chromium'} profile: ${USER_DATA_DIR}`);
  const launcher = useFirefox ? firefox : chromium;
  const context = await launcher.launchPersistentContext(USER_DATA_DIR, { headless: true });
  const page = context.pages()[0] || await context.newPage();

  console.log(`[1/4] Loading dashboard at ${BASE_URL}`);
  await page.goto(BASE_URL, { waitUntil: 'networkidle' });

  console.log('[2/4] Extracting latest batch + levels from IndexedDB');
  const data = await page.evaluate(async () => {
    const open = (db, ver) => new Promise((res, rej) => {
      const r = indexedDB.open(db, ver);
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    const all = (store) => new Promise((res, rej) => {
      const r = store.getAll();
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    const db = await open('TileMatchProduction', 1);
    const tx = db.transaction(['batches', 'levels'], 'readonly');
    const batches = await all(tx.objectStore('batches'));
    const allLevels = await all(tx.objectStore('levels'));
    return { batches, allLevels };
  });

  if (!data.batches.length) {
    console.error('No batches found in this profile. Run the dashboard in this profile first, or set USER_DATA_DIR to the right Chromium profile.');
    await context.close();
    process.exit(1);
  }

  // Pick most recent batch (by updated_at fallback created_at)
  const latest = [...data.batches].sort((a, b) =>
    new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at)
  )[0];
  const levels = data.allLevels.filter(l => l.batch_id === latest.id);
  console.log(`  → batch=${latest.id}  total levels=${levels.length}`);
  console.log(`  → updated_at=${latest.updated_at}  name=${latest.name || '(unnamed)'}`);

  // Sample evenly across level numbers
  levels.sort((a, b) => a.meta.level_number - b.meta.level_number);
  const stride = Math.max(1, Math.floor(levels.length / SAMPLE_SIZE));
  const sample = levels.filter((_, i) => i % stride === 0).slice(0, SAMPLE_SIZE);
  console.log(`  → sampling ${sample.length} levels (stride=${stride})`);

  // Save dump for offline reference
  const dumpPath = path.resolve('/tmp/production-sample.json');
  fs.writeFileSync(dumpPath, JSON.stringify({
    batch: latest,
    sample: sample.map(l => ({
      level_number: l.meta.level_number,
      target_difficulty: l.meta.target_difficulty,
      grade: l.meta.grade,
      pattern_index: l.meta.pattern_index,
      level_json: l.level_json,
    })),
  }, null, 2));
  console.log(`  → dumped to ${dumpPath}`);

  await context.close();

  console.log(`[3/4] Calling /api/analyze/batch-verify (iterations=${ITERATIONS})`);
  const t0 = Date.now();
  const reqBody = {
    levels: sample.map(l => ({
      level_id: `lv_${l.meta.level_number}`,
      level_json: l.level_json,
      target_difficulty: l.meta.target_difficulty,
    })),
    iterations: ITERATIONS,
    tolerance: 15.0,
    use_core_bots_only: true,
  };
  const resp = await fetch(`${API_URL}/api/analyze/batch-verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reqBody),
  });
  if (!resp.ok) {
    console.error('batch-verify failed:', resp.status, await resp.text());
    process.exit(1);
  }
  const out = await resp.json();
  console.log(`  → done in ${Date.now() - t0}ms  pass_rate=${(out.pass_rate * 100).toFixed(1)}%`);

  console.log('[4/4] Failure analysis');
  const results = out.results;
  const failed = results.filter(r => !r.passed);
  console.log(`  total=${results.length}  passed=${out.passed_count}  failed=${failed.length}`);

  // Bucket by failure mode
  const buckets = {
    unclearable: [], // any bot clear_rate == 0
    too_hard: [],    // largest gap is bot < target
    too_easy: [],    // largest gap is bot > target
  };
  const worstBotCounter = {};
  for (const r of failed) {
    let unclear = false;
    let worstBot = '';
    let worstGapPp = 0;
    let direction = 'too_easy';
    for (const [bot, rate] of Object.entries(r.bot_clear_rates || {})) {
      if (rate === 0) unclear = true;
      const target = r.target_clear_rates?.[bot] ?? 0.5;
      const gapPp = (rate - target) * 100;
      if (Math.abs(gapPp) > Math.abs(worstGapPp)) {
        worstGapPp = gapPp;
        worstBot = bot;
        direction = gapPp >= 0 ? 'too_easy' : 'too_hard';
      }
    }
    if (unclear) buckets.unclearable.push(r);
    else if (direction === 'too_hard') buckets.too_hard.push(r);
    else buckets.too_easy.push(r);
    if (worstBot) worstBotCounter[worstBot] = (worstBotCounter[worstBot] || 0) + 1;
    r._diag = { unclear, worstBot, worstGapPp, direction };
  }

  console.log(`  failure modes:`);
  console.log(`    unclearable (clear_rate=0%): ${buckets.unclearable.length}`);
  console.log(`    too_hard (real < target):    ${buckets.too_hard.length}`);
  console.log(`    too_easy (real > target):    ${buckets.too_easy.length}`);
  console.log(`  worst bot histogram:`, worstBotCounter);

  // Bucket by target_difficulty range
  const diffBuckets = { easy: 0, easyFail: 0, mid: 0, midFail: 0, hard: 0, hardFail: 0 };
  for (const r of results) {
    const td = sample.find(s => `lv_${s.meta.level_number}` === r.level_id)?.meta.target_difficulty ?? 0.5;
    const k = td < 0.4 ? 'easy' : td < 0.7 ? 'mid' : 'hard';
    diffBuckets[k]++;
    if (!r.passed) diffBuckets[k + 'Fail']++;
  }
  console.log(`  by target difficulty:`);
  console.log(`    easy(<0.4):  ${diffBuckets.easyFail}/${diffBuckets.easy} fail`);
  console.log(`    mid(<0.7):   ${diffBuckets.midFail}/${diffBuckets.mid} fail`);
  console.log(`    hard(>=0.7): ${diffBuckets.hardFail}/${diffBuckets.hard} fail`);

  // Show worst 10
  console.log('\n  ── 10 worst failures ──');
  failed
    .sort((a, b) => b.max_gap - a.max_gap)
    .slice(0, 10)
    .forEach(r => {
      const d = r._diag;
      const rates = Object.entries(r.bot_clear_rates).map(([k, v]) => `${k}=${(v * 100).toFixed(0)}%`).join(' ');
      console.log(`    ${r.level_id} score=${r.match_score?.toFixed(0)} max_gap=${r.max_gap?.toFixed(0)}pp ${d.unclear ? 'UNCLEAR' : d.direction.toUpperCase()} worst=${d.worstBot}(${d.worstGapPp.toFixed(0)}pp) | ${rates}`);
    });

  const reportPath = path.resolve('/tmp/production-verify-report.json');
  fs.writeFileSync(reportPath, JSON.stringify({
    batch_id: latest.id,
    sample_size: sample.length,
    iterations: ITERATIONS,
    pass_rate: out.pass_rate,
    failure_buckets: {
      unclearable: buckets.unclearable.length,
      too_hard: buckets.too_hard.length,
      too_easy: buckets.too_easy.length,
    },
    worst_bot_counter: worstBotCounter,
    by_difficulty: diffBuckets,
    failures: failed.map(r => ({
      level_id: r.level_id,
      match_score: r.match_score,
      max_gap: r.max_gap,
      bot_clear_rates: r.bot_clear_rates,
      target_clear_rates: r.target_clear_rates,
      diag: r._diag,
    })),
  }, null, 2));
  console.log(`\n  report saved → ${reportPath}`);
}

main().catch(e => { console.error(e); process.exit(1); });

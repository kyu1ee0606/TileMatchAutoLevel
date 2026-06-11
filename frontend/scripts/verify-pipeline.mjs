/**
 * End-to-end verification of the production sequential-validation pipeline.
 *
 * Mimics what the FE does:
 *   1. For each target level number / difficulty, call /api/generate up to N candidates.
 *   2. Apply the new playability_warning filter (clean pool first, fallback only if empty).
 *   3. Run /api/analyze/autoplay on the chosen candidate.
 *   4. Apply the FE pass-rule (dynamic threshold based on target_difficulty).
 *   5. Tally pass/fail by failure mode.
 *
 * Compares two strategies side-by-side:
 *   - "naive": pick best by static-difficulty gap only (legacy behavior).
 *   - "filtered": prefer candidates without playability_warning (new behavior).
 */
import fs from 'node:fs';
import path from 'node:path';

const API = 'http://localhost:8000';
const ITERATIONS = parseInt(process.env.ITERATIONS || '30', 10);
const CANDIDATES_PER_LEVEL = parseInt(process.env.CANDIDATES_PER_LEVEL || '15', 10);

// Realistic distribution of target difficulties / level numbers seen in a 1500-level sawtooth batch.
const ALL_LEVELS = [
  { level_number: 11, target_difficulty: 0.10 },
  { level_number: 25, target_difficulty: 0.20 },
  { level_number: 50, target_difficulty: 0.30 },
  { level_number: 90, target_difficulty: 0.45 },
  { level_number: 120, target_difficulty: 0.55 },
  { level_number: 180, target_difficulty: 0.60 },
  { level_number: 240, target_difficulty: 0.65 },
  { level_number: 300, target_difficulty: 0.70 },
  { level_number: 400, target_difficulty: 0.75 },
  { level_number: 500, target_difficulty: 0.80 },
];
const N = parseInt(process.env.N || ALL_LEVELS.length, 10);
const TEST_LEVELS = ALL_LEVELS.slice(0, N);

function computePassThreshold(td) {
  let mult = 1.0;
  if (td >= 0.7) mult = 1.3;
  else if (td >= 0.5) mult = 1.0 + ((td - 0.5) / 0.2) * 0.3;
  return Math.max(50, Math.round(100 - 15 * mult * 2));
}

function calculateMatchScore(botStats) {
  if (!botStats.length) return 0;
  const gaps = botStats.map(s => {
    const raw = (s.clear_rate - s.target_clear_rate) * 100;
    return raw > 0 ? raw * 0.5 : Math.abs(raw) * 0.7;
  });
  const avg = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  const max = Math.max(...gaps);
  return Math.max(0, 100 - (avg * 0.7 + max * 0.3) * 2);
}

const PROFESSIONAL_GIMMICK_UNLOCK_LEVELS = {
  craft: 1, stack: 1, chain: 50, frog: 100, ice: 75,
  grass: 125, link: 150, bomb: 175, curtain: 200, teleport: 225, unknown: 25,
};

async function generateOne(levelNumber, td) {
  const isEarly = levelNumber <= 30;
  const isBoss = levelNumber % 10 === 0 && levelNumber > 0;
  const symModes = ['none', 'horizontal', 'vertical', 'both'];
  const symmetry_mode = symModes[Math.floor(Math.random() * symModes.length)];
  const goalDirection = ['s', 'n', 'e', 'w'][Math.floor(Math.random() * 4)];
  const goalType = Math.random() < 0.5 ? 'craft' : 'stack';
  let grid_size = [7, 7];
  if (isBoss && td > 0.3) grid_size = [8, 8];
  else if (!isEarly && Math.random() < 0.3) grid_size = [8, 8];
  const max_layers = Math.min(7, 3 + Math.floor(td * 4));

  const body = {
    target_difficulty: td,
    grid_size,
    max_layers,
    obstacle_types: [],
    goals: [{ type: goalType, direction: goalDirection, count: Math.max(2, Math.floor(3 + td * 2)) }],
    symmetry_mode,
    pattern_type: 'aesthetic',
    auto_select_gimmicks: true,
    available_gimmicks: ['craft', 'stack', 'chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
    gimmick_intensity: Math.min(td, levelNumber / 500),
    gimmick_unlock_levels: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
    level_number: levelNumber,
  };
  const r = await fetch(`${API}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) return null;
  return await r.json();
}

async function autoplayCheck(level_json, td) {
  const r = await fetch(`${API}/api/analyze/autoplay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      level_json,
      iterations: ITERATIONS,
      target_difficulty: td,
      // default profiles = average/expert/optimal
    }),
  });
  if (!r.ok) {
    return { ok: false, error: await r.text() };
  }
  return { ok: true, ...(await r.json()) };
}

function selectCandidate(candidates, td, useFilter) {
  const targetScore = td * 100;
  let bestClean = null, bestCleanGap = Infinity;
  let bestFallback = null, bestFallbackGap = Infinity;
  let cleanCount = 0, warningCount = 0;
  for (const c of candidates) {
    if (!c) continue;
    const gap = Math.abs(c.actual_difficulty - td); // both 0-1 scale (FE bug: targetScore=td*100 but here use td)
    const flagged = !!c.playability_warning;
    if (useFilter && flagged) {
      warningCount++;
      if (gap < bestFallbackGap) { bestFallbackGap = gap; bestFallback = c; }
    } else {
      if (!flagged) cleanCount++;
      if (gap < bestCleanGap) { bestCleanGap = gap; bestClean = c; }
    }
  }
  const chosen = bestClean || bestFallback;
  return { chosen, cleanCount, warningCount };
}

function classifyResult(autoplayResult, td) {
  const passThreshold = computePassThreshold(td);
  const matchScore = calculateMatchScore(autoplayResult.bot_stats);
  let worstBot = '', worstGap = 0;
  let unclear = false;
  for (const s of autoplayResult.bot_stats) {
    if (s.clear_rate === 0) unclear = true;
    const gap = (s.clear_rate - s.target_clear_rate) * 100;
    if (Math.abs(gap) > Math.abs(worstGap)) { worstGap = gap; worstBot = s.profile; }
  }
  const direction = unclear ? 'unclear' : Math.abs(worstGap) <= 5 ? 'ok' : worstGap > 0 ? 'too_easy' : 'too_hard';
  return { matchScore, passThreshold, passed: matchScore >= passThreshold, worstBot, worstGap, direction };
}

async function genCandidatePool(level) {
  const candidates = [];
  for (let i = 0; i < CANDIDATES_PER_LEVEL; i++) {
    const c = await generateOne(level.level_number, level.target_difficulty);
    if (c) candidates.push(c);
  }
  return candidates;
}

async function runOneShared(level, candidates, useFilter) {
  const sel = selectCandidate(candidates, level.target_difficulty, useFilter);
  if (!sel.chosen) return { level, error: 'no_candidate' };
  const auto = await autoplayCheck(sel.chosen.level_json, level.target_difficulty);
  if (!auto.ok) return { level, error: auto.error };
  const cls = classifyResult(auto, level.target_difficulty);
  return {
    level,
    cleanCount: sel.cleanCount,
    warningCount: sel.warningCount,
    chosen_static_difficulty: sel.chosen.actual_difficulty,
    chosen_clear_rate_estimate: sel.chosen.estimated_clear_rate,
    chosen_warning: !!sel.chosen.playability_warning,
    matchScore: cls.matchScore,
    passThreshold: cls.passThreshold,
    passed: cls.passed,
    worstBot: cls.worstBot,
    worstGap: cls.worstGap,
    direction: cls.direction,
    bot_clear_rates: Object.fromEntries(auto.bot_stats.map(s => [s.profile, s.clear_rate])),
  };
}

async function main() {
  console.log(`Pipeline verification: ${TEST_LEVELS.length} levels × ${CANDIDATES_PER_LEVEL} candidates × autoplay(${ITERATIONS} iter)`);
  console.log(`Comparing strategies: NAIVE (legacy) vs FILTERED (new playability flag)`);
  console.log('');

  const naiveResults = [];
  const filteredResults = [];

  for (let i = 0; i < TEST_LEVELS.length; i++) {
    const lvl = TEST_LEVELS[i];
    process.stdout.write(`[${i + 1}/${TEST_LEVELS.length}] Lv.${lvl.level_number} td=${lvl.target_difficulty} ... `);

    // Generate one shared candidate pool, then evaluate both strategies against it
    const pool = await genCandidatePool(lvl);
    const naive = await runOneShared(lvl, pool, false);
    const filtered = await runOneShared(lvl, pool, true);

    naiveResults.push(naive);
    filteredResults.push(filtered);

    const fmt = (r) => r.error
      ? `ERR(${r.error})`
      : `match=${r.matchScore.toFixed(0)}/${r.passThreshold} ${r.passed ? '✓' : '✗'} ${r.direction} W=${r.warningCount}/${r.cleanCount + r.warningCount}`;
    console.log(`naive=${fmt(naive)} | filtered=${fmt(filtered)}`);
  }

  function summarize(results, label) {
    const passed = results.filter(r => r.passed).length;
    const errors = results.filter(r => r.error).length;
    const distrib = { unclear: 0, too_hard: 0, too_easy: 0, ok: 0 };
    for (const r of results) {
      if (r.direction) distrib[r.direction] = (distrib[r.direction] || 0) + 1;
    }
    const totalCandidates = results.reduce((s, r) => s + ((r.cleanCount || 0) + (r.warningCount || 0)), 0);
    const totalWarnings = results.reduce((s, r) => s + (r.warningCount || 0), 0);
    const chosenWarnings = results.filter(r => r.chosen_warning).length;
    console.log(`\n=== ${label} ===`);
    console.log(`  pass: ${passed}/${results.length}  errors: ${errors}`);
    console.log(`  direction:`, distrib);
    console.log(`  warning candidates: ${totalWarnings}/${totalCandidates} produced  (${(totalWarnings / totalCandidates * 100).toFixed(1)}%)`);
    console.log(`  chosen levels with warning flag: ${chosenWarnings}`);
  }

  summarize(naiveResults, 'NAIVE strategy (legacy)');
  summarize(filteredResults, 'FILTERED strategy (new)');

  const reportPath = '/tmp/verify-pipeline-report.json';
  fs.writeFileSync(reportPath, JSON.stringify({ naive: naiveResults, filtered: filteredResults }, null, 2));
  console.log(`\nFull report → ${reportPath}`);
}

main().catch(e => { console.error(e); process.exit(1); });

/**
 * Targeted probe for Lv.219 — the user's reported failing level.
 * Tries multiple realistic difficulty values, generates several candidates each,
 * and runs full autoplay to identify the actual failure mode.
 */
const API = 'http://localhost:8000';

const LEVEL = 219;
const CAND_PER = 6;
const ITERS = 40;

// Plausible sawtooth-pattern target difficulties around level 219 (~mid)
const DIFFS = [0.45, 0.55, 0.60, 0.65, 0.70];

const PROFESSIONAL_GIMMICK_UNLOCK_LEVELS = {
  craft: 1, stack: 1, chain: 50, frog: 100, ice: 75,
  grass: 125, link: 150, bomb: 175, curtain: 200, teleport: 225, unknown: 25,
};

async function generate(td, cfg = {}) {
  const isSpecial = LEVEL % 10 === 9;
  const symModes = cfg.symModes || ['horizontal', 'vertical', 'both'];
  const symmetry_mode = symModes[Math.floor(Math.random() * symModes.length)];
  const goalDirection = ['s', 'n', 'e', 'w'][Math.floor(Math.random() * 4)];
  const goalType = Math.random() < 0.5 ? 'craft' : 'stack';
  const grid_size = Math.random() < 0.3 ? [8, 8] : [7, 7];
  const max_layers = Math.min(7, 3 + Math.floor(td * 4));
  const body = {
    target_difficulty: td,
    grid_size, max_layers,
    obstacle_types: [],
    goals: [{ type: goalType, direction: goalDirection, count: Math.max(2, Math.floor(3 + td * 2)) }],
    symmetry_mode,
    pattern_type: 'aesthetic',
    auto_select_gimmicks: true,
    available_gimmicks: ['craft', 'stack', 'chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
    gimmick_intensity: Math.min(td, LEVEL / 500),
    gimmick_unlock_levels: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
    level_number: LEVEL,
  };
  const r = await fetch(`${API}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) return { error: r.status + ' ' + await r.text() };
  const j = await r.json();
  return { ...j, _config: { symmetry_mode, goalType, grid_size, max_layers } };
}

async function autoplay(level_json, td) {
  const r = await fetch(`${API}/api/analyze/autoplay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level_json, iterations: ITERS, target_difficulty: td }),
  });
  return r.ok ? await r.json() : null;
}

function computePassThreshold(td) {
  let mult = 1.0;
  if (td >= 0.7) mult = 1.3;
  else if (td >= 0.5) mult = 1.0 + ((td - 0.5) / 0.2) * 0.3;
  return Math.max(50, Math.round(100 - 15 * mult * 2));
}
function matchScore(stats) {
  const gaps = stats.map(s => {
    const r = (s.clear_rate - s.target_clear_rate) * 100;
    return r > 0 ? r * 0.5 : Math.abs(r) * 0.7;
  });
  const a = gaps.reduce((x, y) => x + y, 0) / gaps.length;
  const m = Math.max(...gaps);
  return Math.max(0, 100 - (a * 0.7 + m * 0.3) * 2);
}

async function main() {
  console.log(`Probing Lv.${LEVEL} across difficulties [${DIFFS.join(', ')}]`);
  console.log(`${CAND_PER} candidates × ${ITERS} autoplay iter per difficulty\n`);

  for (const td of DIFFS) {
    console.log(`── td=${td} ──`);
    const cands = [];
    for (let i = 0; i < CAND_PER; i++) cands.push(await generate(td));
    const warnCount = cands.filter(c => c.playability_warning).length;
    console.log(`  generated ${cands.length}  warning_flag=${warnCount}  estimated_clear_rates=[${cands.map(c => (c.estimated_clear_rate ?? 1).toFixed(2)).join(', ')}]`);

    // Apply FE filter: prefer clean
    const clean = cands.filter(c => !c.playability_warning);
    const pool = clean.length ? clean : cands;
    const targetScore = td * 100;
    pool.sort((a, b) => Math.abs(a.actual_difficulty - td) - Math.abs(b.actual_difficulty - td));
    const chosen = pool[0];

    console.log(`  chosen: actual_difficulty=${(chosen.actual_difficulty * 100).toFixed(0)} cfg=${JSON.stringify(chosen._config)} warning=${chosen.playability_warning}`);

    const auto = await autoplay(chosen.level_json, td);
    if (!auto) { console.log('  autoplay FAILED'); continue; }
    const ms = matchScore(auto.bot_stats);
    const cut = computePassThreshold(td);
    const rates = auto.bot_stats.map(s => `${s.profile}=${(s.clear_rate * 100).toFixed(0)}%(t${(s.target_clear_rate * 100).toFixed(0)})`).join('  ');
    console.log(`  match=${ms.toFixed(0)}/${cut} ${ms >= cut ? '✓PASS' : '✗FAIL'}  ${rates}\n`);
  }
}
main().catch(e => { console.error(e); process.exit(1); });

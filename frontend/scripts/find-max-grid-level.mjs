/**
 * 가장 최근 프로덕션 배치에서 최대 grid_size를 가진 레벨 찾기.
 */
import { firefox } from 'playwright';
import path from 'node:path';
import os from 'node:os';

const BASE_URL = 'http://localhost:5173';
const USER_DATA_DIR = process.env.USER_DATA_DIR || '/tmp/ff-readonly-profile';

async function main() {
  const context = await firefox.launchPersistentContext(USER_DATA_DIR, { headless: true });
  const page = context.pages()[0] || await context.newPage();
  await page.goto(BASE_URL, { waitUntil: 'networkidle' });

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
    console.error('No batches in profile.');
    await context.close();
    process.exit(1);
  }

  const latest = [...data.batches].sort((a, b) =>
    new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at)
  )[0];
  const levels = data.allLevels.filter(l => l.batch_id === latest.id);
  console.log(`Latest batch: ${latest.id} (name=${latest.name || 'unnamed'})`);
  console.log(`Updated: ${latest.updated_at}`);
  console.log(`Total levels: ${levels.length}`);
  console.log('');

  // 각 레벨의 최대 col, row 계산
  let maxLevel = null;
  let maxSide = 0;
  const distribution = {};
  for (const lvl of levels) {
    const lj = lvl.level_json;
    if (!lj) continue;
    const numLayers = lj.layer || 0;
    let lvMaxSide = 0;
    for (let i = 0; i < numLayers; i++) {
      const layer = lj[`layer_${i}`];
      if (!layer) continue;
      const col = parseInt(String(layer.col || 0), 10);
      const row = parseInt(String(layer.row || 0), 10);
      lvMaxSide = Math.max(lvMaxSide, col, row);
    }
    distribution[lvMaxSide] = (distribution[lvMaxSide] || 0) + 1;
    if (lvMaxSide > maxSide) {
      maxSide = lvMaxSide;
      maxLevel = lvl;
    }
  }

  console.log(`Grid side 최대값별 레벨 분포:`);
  Object.entries(distribution).sort((a, b) => Number(b[0]) - Number(a[0])).forEach(([k, v]) => {
    console.log(`  side=${k}: ${v}개 레벨`);
  });
  console.log('');

  if (maxLevel) {
    const lj = maxLevel.level_json;
    console.log(`=== 최대 grid 레벨: Lv.${maxLevel.meta.level_number} ===`);
    console.log(`max_side: ${maxSide}`);
    console.log(`target_difficulty: ${maxLevel.meta.target_difficulty}`);
    console.log(`actual_difficulty: ${maxLevel.meta.actual_difficulty}`);
    console.log(`grade: ${maxLevel.meta.grade}`);
    console.log(`useTileCount: ${lj.useTileCount}`);
    console.log(`max_moves: ${lj.max_moves}`);
    console.log(`pattern_index: ${maxLevel.meta.pattern_index}`);
    console.log(`레이어:`);
    for (let i = 0; i < (lj.layer || 0); i++) {
      const layer = lj[`layer_${i}`];
      if (!layer) continue;
      const tc = Object.keys(layer.tiles || {}).length;
      console.log(`  L${i}: ${layer.col}x${layer.row}, ${tc} tiles`);
    }
  }

  await context.close();
}

main().catch(e => { console.error(e); process.exit(1); });

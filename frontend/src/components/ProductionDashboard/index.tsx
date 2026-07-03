/**
 * Production Dashboard
 * 1500개 레벨 프로덕션 관리 대시보드
 */

import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { generateLevel, enhanceLevel } from '../../api/generate';
import apiClient from '../../api/client';
import { analyzeAutoPlay, fixCentering, analyzeSolvability } from '../../api/analyze';
import { simulateLevelSkillSweep } from '../../api/rlSim';
import GamePlayer from '../GamePlayer';
import GameBoard from '../GamePlayer/GameBoard';
import { createGameEngine, resolveT0TileTypes } from '../../engine/gameEngine';
import { zWellRandom } from '../../engine/tileDistributor';
import type { GameStats, LevelInfo, GameTile } from '../../types/game';
import type { GenerationParams, GenerationResult, DifficultyGrade, LevelJSON } from '../../types';
import {
  ProductionBatch,
  ProductionLevel,
  ProductionLevelMeta,
  ProductionStats,
  PlaytestResult,
  PlaytestQueueConfig,
  PlaytestStrategy,
  LevelStatus,
  ProductionGenerationProgress,
  PRODUCTION_1500_PRESETS,
  shouldRequirePlaytest,
} from '../../types/production';
import {
  PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
} from '../../types/levelSet';
import {
  initProductionDB,
  createProductionBatch,
  getProductionBatch,
  updateProductionBatch,
  listProductionBatches,
  saveProductionLevels,
  getProductionLevelsByBatch,
  getPlaytestQueue,
  addPlaytestResult,
  approveLevel,
  rejectLevel,
  calculateProductionStats,
  deleteProductionBatch,
  renameProductionBatch,
  recalculateBatchCounts,
} from '../../storage/productionStorage';
import { syncBidirectional, pushBatchToServer, registerAutoSync, setConflictHandler, setDivisibilityWarningHandler, SyncConflictError } from '../../storage/productionServerSync';
import { ProductionExport } from './ProductionExport';
import { BatchApprovalPanel } from './BatchApprovalPanel';
import { BatchVerifyPanel } from './BatchVerifyPanel';
import { MetaIntegrityPanel, checkTileDivisibility, detectOOBTiles } from './MetaIntegrityPanel';
import { LevelDistributionChart } from './LevelDistributionChart';
// PatternSelector import removed - using inline grid instead
import { getPatternByIndex, BOSS_PATTERNS, SPECIAL_PATTERNS, PATTERN_CATEGORIES } from '../../constants/patterns';

/**
 * 타일 종류 수(V) 분포 프로파일 — 백엔드 generator.py TILE_TYPE_PROFILES + LEVEL_CONFIG_TABLE 미러.
 * ⚠️ 백엔드 변경 시 수동 동기화 필요. 형식: [최대레벨, V] 오름차순.
 */
const TILE_TYPE_PROFILE_CURVES: Record<string, Array<[number, number]>> = {
  baseline: [[3, 4], [10, 5], [30, 6], [60, 8], [100, 9], [225, 9], [600, 10], [1125, 11], [1500, 12]],
  hard_steep: [[3, 4], [10, 5], [30, 8], [60, 10], [100, 11], [225, 11], [600, 12], [1125, 12], [1500, 13]],
};

function vAtLevel(brackets: Array<[number, number]>, level: number): number {
  for (const [cap, v] of brackets) if (level <= cap) return v;
  return brackets[brackets.length - 1][1];
}

/**
 * V(타일 종류 수) 분포 미리보기 그래프. baseline(회색) + 선택 프로파일(파랑) 겹쳐 표시.
 * y=0~15, x=레벨 1~1500. 좌우 풀스트레치, 마우스오버 시 크로스헤어+값 툴팁.
 */
function TileTypeProfileGraph({ profile }: { profile: string }) {
  const PADL = 30, PADR = 14, PADT = 8, PADB = 22;
  const H = 180, MAXL = 1500, MAXV = 15;
  // 컨테이너 실제 px 폭을 측정해 viewBox 폭으로 사용 → 1:1 비율, 텍스트 왜곡 없음
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [vbw, setVbw] = useState(560);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setVbw(Math.round(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const W = Math.max(120, vbw - PADL - PADR);  // 플롯 영역 폭
  const VBW = vbw, VBH = PADT + H + PADB;
  const xs = (l: number) => PADL + Math.min(l, MAXL) / MAXL * W;
  const ys = (v: number) => PADT + H - (v / MAXV) * H;
  const stepPoints = (brackets: Array<[number, number]>) => {
    const pts: string[] = [];
    let prev = 1;
    for (const [cap, v] of brackets) {
      const end = Math.min(cap, MAXL);
      pts.push(`${xs(prev).toFixed(1)},${ys(v).toFixed(1)}`);
      pts.push(`${xs(end).toFixed(1)},${ys(v).toFixed(1)}`);
      prev = end;
    }
    return pts.join(' ');
  };
  const sel = TILE_TYPE_PROFILE_CURVES[profile] ?? TILE_TYPE_PROFILE_CURVES.baseline;
  const base = TILE_TYPE_PROFILE_CURVES.baseline;
  const showBaseline = profile !== 'baseline';

  const [hover, setHover] = useState<{ level: number; vSel: number; vBase: number } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const logicalX = (e.clientX - rect.left) / rect.width * VBW;  // 컨테이너→논리 좌표
    const frac = (logicalX - PADL) / W;
    const level = Math.max(1, Math.min(MAXL, Math.round(frac * MAXL)));
    setHover({ level, vSel: vAtLevel(sel, level), vBase: vAtLevel(base, level) });
  };

  return (
    <div ref={wrapRef} className="w-full mt-1">
    <svg
      ref={svgRef}
      viewBox={`0 0 ${VBW} ${VBH}`}
      width="100%"
      height={VBH}
      className="cursor-crosshair"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      {/* y축 격자 */}
      {[0, 3, 6, 9, 12, 15].map((v) => (
        <g key={v}>
          <line x1={PADL} y1={ys(v)} x2={PADL + W} y2={ys(v)} stroke="#374151" strokeWidth={0.5} />
          <text x={PADL - 5} y={ys(v) + 3} textAnchor="end" fontSize={9} fill="#9ca3af">{v}</text>
        </g>
      ))}
      {showBaseline && (
        <polyline points={stepPoints(base)} fill="none" stroke="#6b7280" strokeWidth={1.4} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
      )}
      <polyline points={stepPoints(sel)} fill="none" stroke="#3b82f6" strokeWidth={2} vectorEffect="non-scaling-stroke" />

      {/* x축 라벨 */}
      {[1, 300, 600, 900, 1200, 1500].map((l) => (
        <text key={l} x={xs(l)} y={PADT + H + 14} textAnchor="middle" fontSize={9} fill="#9ca3af">{l}</text>
      ))}

      {/* 마우스오버 크로스헤어 + 값 */}
      {hover && (
        <g>
          <line x1={xs(hover.level)} y1={PADT} x2={xs(hover.level)} y2={PADT + H} stroke="#f59e0b" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />
          {showBaseline && <circle cx={xs(hover.level)} cy={ys(hover.vBase)} r={3} fill="#6b7280" />}
          <circle cx={xs(hover.level)} cy={ys(hover.vSel)} r={3.5} fill="#3b82f6" />
          <g transform={`translate(${Math.min(xs(hover.level) + 6, VBW - 110)}, ${PADT + 4})`}>
            <rect width={104} height={showBaseline ? 40 : 26} rx={3} fill="#111827" opacity={0.92} stroke="#374151" strokeWidth={0.5} />
            <text x={6} y={13} fontSize={10} fill="#e5e7eb">Lv {hover.level}</text>
            <text x={6} y={showBaseline ? 25 : 24} fontSize={10} fill="#60a5fa">선택 V={hover.vSel}</text>
            {showBaseline && <text x={6} y={37} fontSize={10} fill="#9ca3af">base V={hover.vBase}</text>}
          </g>
        </g>
      )}
    </svg>
    </div>
  );
}

/**
 * 레벨 번호에 따른 예상 useTileCount 범위 계산
 * 백엔드의 get_gboost_style_layer_config (레벨 기반) + TILE_RANGES (난이도 기반) 통합
 *
 * 두 가지 생성 방식:
 * 1. /api/generate: 레벨 번호 기반 고정값 (get_use_tile_count_for_level)
 * 2. /api/generate/validated: 난이도 등급 기반 범위 (TILE_RANGES)
 *
 * 검증 시에는 두 방식 모두 허용하도록 최소/최대 범위 사용
 */
function getExpectedUseTileCountRange(levelNumber: number, targetDifficulty?: number): {
  min: number;
  max: number;
  levelBased: number;  // 레벨 기반 고정값
} {
  // 레벨 번호 기반 고정값 (get_gboost_style_layer_config)
  let levelBased: number;
  if (levelNumber <= 10) levelBased = 4;
  else if (levelNumber <= 30) levelBased = 5;
  else if (levelNumber <= 60) levelBased = 7;
  else if (levelNumber <= 100) levelBased = 8;
  else if (levelNumber <= 225) levelBased = 8;
  else if (levelNumber <= 600) levelBased = 9;
  else if (levelNumber <= 1125) levelBased = 10;
  else if (levelNumber <= 1500) levelBased = 11;
  else levelBased = 12;

  // 난이도 등급 기반 범위 (TILE_RANGES from /generate/validated)
  // TILE_RANGES = { "S": (6, 5, 7), "A": (7, 6, 8), "B": (8, 6, 10), "C": (8, 7, 10), "D": (9, 7, 11), "E": (10, 8, 12) }
  let difficultyMin = 4;
  let difficultyMax = 12;

  if (targetDifficulty !== undefined) {
    if (targetDifficulty < 0.2) {
      // S등급: 6 ± 1
      difficultyMin = 5; difficultyMax = 7;
    } else if (targetDifficulty < 0.35) {
      // A등급: 7 ± 1
      difficultyMin = 6; difficultyMax = 8;
    } else if (targetDifficulty < 0.5) {
      // B등급: 8 ± 2
      difficultyMin = 6; difficultyMax = 10;
    } else if (targetDifficulty < 0.7) {
      // C등급: 8, 최소 7
      difficultyMin = 7; difficultyMax = 10;
    } else if (targetDifficulty < 0.85) {
      // D등급: 9 ± 2
      difficultyMin = 7; difficultyMax = 11;
    } else {
      // E등급: 10 ± 2
      difficultyMin = 8; difficultyMax = 12;
    }
  }

  // 두 방식을 모두 허용: 레벨 기반 값 또는 난이도 기반 범위 내
  const min = Math.min(levelBased, difficultyMin);
  const max = Math.max(levelBased, difficultyMax);

  return { min, max, levelBased };
}

/**
 * 레벨의 useTileCount가 올바른지 검사
 * 레벨 기반 고정값 또는 난이도 기반 범위 내에 있으면 유효
 */
function validateUseTileCount(levelNumber: number, useTileCount: number, targetDifficulty?: number): {
  isValid: boolean;
  range: { min: number; max: number };
  levelBased: number;
} {
  const { min, max, levelBased } = getExpectedUseTileCountRange(levelNumber, targetDifficulty);

  // useTileCount가 허용 범위 내에 있으면 유효
  // 또는 레벨 기반 고정값과 정확히 일치하면 유효
  const isValid = (useTileCount >= min && useTileCount <= max) || useTileCount === levelBased;

  return {
    isValid,
    range: { min, max },
    levelBased
  };
}

const VISUAL_POOL = 15; // 비주얼 스프라이트 풀 t1~t15

// [보스 난이도] 보스(10의 배수) 레벨의 목표 클리어율 배율 — 일반 목표의 절반(더 어려워야 통과).
// RL 검증(초기/순차/재생성) 전 경로에서 target_clear_rate_scale로 백엔드에 전달.
const BOSS_TARGET_CLEAR_SCALE = 0.5;
const bossTargetScale = (levelNumber: number | undefined): number | undefined =>
  levelNumber && levelNumber > 0 && levelNumber % 10 === 0 ? BOSS_TARGET_CLEAR_SCALE : undefined;

// [보스 생성기/디바이스 제약] 선언 그리드 최대변 상한 — 9x9 이상은 타일이 작아 플레이 불가.
const MAX_PLAYABLE_GRID = 8;
const maxDeclaredGridDim = (levelJson: LevelJsonLike | undefined): number => {
  const lj = levelJson as unknown as Record<string, unknown> | undefined;
  if (!lj) return 0;
  let mx = 0;
  const layerCount = Number(lj.layer) || 0;
  for (let i = 0; i < layerCount; i++) {
    const ld = lj[`layer_${i}`] as { col?: string | number; row?: string | number; tiles?: Record<string, unknown> } | undefined;
    if (!ld || !ld.tiles || Object.keys(ld.tiles).length === 0) continue;
    mx = Math.max(mx, Number(ld.col) || 0, Number(ld.row) || 0);
  }
  return mx;
};

// 🔴 게임 배포 게이트: craft/stack 명시 내부(신포맷 [count,"ids"])는 **게임 v1.10.382+** 배포 후에만 emit.
// 구 게임에 신포맷 가면 내부 강제 t0 재분배 → relabel board와 불일치 → 매칭 붕괴.
// 게임 빌드가 플레이어에 배포된 뒤 true로 전환. false면 현행(순수고정 relabel + 순수t0 시드) 유지.
const ENABLE_INNER_TILE_BAKE = true;

// LevelJSON은 string 인덱스 시그니처가 없어 Record<string,unknown>에 직접 대입 불가 → 완화 타입 + 내부 캐스트.
type LevelJsonLike = { layer?: unknown; visualTileSeed?: number } | null | undefined;

/**
 * 레벨 스캔: t0 존재(top-level) + craft/stack 존재(내부 t0 = 명시와 타입 공유) + 명시 인덱스(1~15).
 * craft/stack은 내부에 t0(런타임 랜덤)를 품어 게임에서 명시타일과 타입을 공유하므로,
 * 명시 relabel 시 craft 방출 정렬이 깨질 수 있음 → 순수 고정 판정에서 제외해야 함.
 */
function scanLevelTiles(levelJson: Record<string, unknown>): { hasT0: boolean; hasCraftStack: boolean; explicitIds: Set<number> } {
  const explicitIds = new Set<number>();
  let hasT0 = false;
  let hasCraftStack = false;
  const layerCount = Number((levelJson as { layer?: unknown }).layer) || 0;
  for (let i = 0; i < layerCount; i++) {
    const ld = levelJson[`layer_${i}`] as { tiles?: Record<string, unknown[]> } | undefined;
    const tiles = ld?.tiles;
    if (!tiles) continue;
    for (const t of Object.values(tiles)) {
      if (!Array.isArray(t) || !t.length) continue;
      const tt = String(t[0] ?? '');
      if (tt === 't0') { hasT0 = true; continue; }
      if (tt.startsWith('stack_') || tt.startsWith('craft_')) { hasCraftStack = true; continue; }
      const m = /^t(\d+)$/.exec(tt);
      if (m) { const id = parseInt(m[1], 10); if (id >= 1 && id <= VISUAL_POOL) explicitIds.add(id); }
    }
  }
  return { hasT0, hasCraftStack, explicitIds };
}

/** seed로 pool[1..15]에서 count개 distinct 선택 → usedTypes(오름차순) 1:1 매핑. 인게임 remap과 동일 방식. */
function buildVisualIndexMap(usedTypes: number[], seed: number): Record<number, number> {
  const vrnd = new zWellRandom((seed + 1) >>> 0); // WELL512 seed 0(=시간기반) 회피
  const pool: number[] = [];
  for (let i = 0; i < VISUAL_POOL; i++) pool.push(i + 1);
  const n = usedTypes.length;
  for (let i = 0; i < n; i++) {
    const j = vrnd.rand(i, VISUAL_POOL - 1); // inclusive
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  const map: Record<number, number> = {};
  for (let k = 0; k < n; k++) map[usedTypes[k]] = pool[k];
  return map;
}

/** "t7"→7, "key"/"t16"→16, 그 외→0. */
function tileNum(s: string): number {
  if (s === 'key') return 16;
  const m = /^t(\d+)$/.exec(s);
  return m ? parseInt(m[1], 10) : 0;
}

/**
 * [전체 보드 bake] craft/stack 명시 내부 지원(게임 v1.10.382+) 전제. t0/craft/stack 내부 타입을
 * 게임 분배로 사전계산 → 보드 전체(명시+t0+내부) 논리타입을 1~15 풀 relabel(bijective) → 명시화 emit.
 *  - top-level t0 → tiles[pos][0] = "t{visual}"
 *  - board 명시 t1~15 → relabel
 *  - craft/stack → tiles[pos][2] = [count, "v0_v1_..v(n-1)"] (stackIdx 0..n-1 순서 = 게임 stackCTileList[k])
 * 결과: t0 소멸 → 전 레벨 비주얼 다양화. 매칭/난이도/÷3 불변(relabel bijective, 내부타입=게임분배결과).
 * randSeed 구체값(>0)만. stage 1~3 제외.
 */
function bakeFullBoard(levelJsonIn: LevelJsonLike, levelNumber: number): void {
  if (!levelJsonIn || typeof levelNumber !== 'number' || levelNumber <= 3) return;
  const levelJson = levelJsonIn as unknown as Record<string, unknown>;
  const randSeed = typeof levelJson.randSeed === 'number' ? levelJson.randSeed : 0;
  if (!(randSeed > 0)) return; // -1/0(런타임) → bake 불가

  // 1. 게임 분배 재현 (top-level t0 flat key `${i}_${pos}` + craft/stack inner `${i}_${x}_${y}_${stackIdx}`)
  let t0Map: Map<string, string>;
  try { t0Map = resolveT0TileTypes(levelJson); } catch { return; }

  const layerCount = Number(levelJson.layer) || 0;

  // 2. 전체 논리 타입 수집
  const present = new Array(VISUAL_POOL + 1).fill(false);
  const mark = (id: number) => { if (id >= 1 && id <= VISUAL_POOL) present[id] = true; };
  for (let i = 0; i < layerCount; i++) {
    const tiles = (levelJson[`layer_${i}`] as { tiles?: Record<string, unknown[]> } | undefined)?.tiles;
    if (!tiles) continue;
    for (const [pos, t] of Object.entries(tiles)) {
      if (!Array.isArray(t) || !t.length) continue;
      const tt = String(t[0] ?? '');
      if (tt === 't0') { mark(tileNum(t0Map.get(`${i}_${pos}`) ?? '')); }
      else if (tt.startsWith('stack_') || tt.startsWith('craft_')) {
        const cnt = Array.isArray(t[2]) && typeof t[2][0] === 'number' ? t[2][0] as number : 0;
        const [xs, ys] = pos.split('_');
        for (let k = 0; k < cnt; k++) mark(tileNum(t0Map.get(`${i}_${xs}_${ys}_${k}`) ?? ''));
      } else { mark(tileNum(tt)); }
    }
  }
  const usedTypes: number[] = [];
  for (let v = 1; v <= VISUAL_POOL; v++) if (present[v]) usedTypes.push(v);
  if (usedTypes.length === 0) return;
  const map = buildVisualIndexMap(usedTypes, levelNumber);
  const rel = (id: number) => (id >= 1 && id <= VISUAL_POOL ? map[id] : id); // key(16) 등 그대로

  // 3. 재기록
  for (let i = 0; i < layerCount; i++) {
    const tiles = (levelJson[`layer_${i}`] as { tiles?: Record<string, unknown[]> } | undefined)?.tiles;
    if (!tiles) continue;
    for (const [pos, t] of Object.entries(tiles)) {
      if (!Array.isArray(t) || !t.length) continue;
      const tt = String(t[0] ?? '');
      if (tt === 't0') {
        const id = tileNum(t0Map.get(`${i}_${pos}`) ?? '');
        if (id >= 1 && id <= VISUAL_POOL) t[0] = `t${rel(id)}`;
      } else if (tt.startsWith('stack_') || tt.startsWith('craft_')) {
        const cnt = Array.isArray(t[2]) && typeof t[2][0] === 'number' ? t[2][0] as number : 0;
        if (cnt <= 0) continue;
        const [xs, ys] = pos.split('_');
        const ids: string[] = [];
        let anyUnresolved = false;
        for (let k = 0; k < cnt; k++) {
          const raw = t0Map.get(`${i}_${xs}_${ys}_${k}`) ?? '';
          const id = tileNum(raw);
          if (id === 16) { ids.push('key'); }
          else if (id >= 1 && id <= VISUAL_POOL) { ids.push(`t${rel(id)}`); }
          else { anyUnresolved = true; break; } // 미해결 inner: t1 폴백 금지 → 개수만 유지, 게임이 일반 타일과 동일 재분배
        }
        if (anyUnresolved) {
          // 명시 bake 스킵 → td[2]=[cnt] 개수만 → 게임 런타임이 필드 일반 타일과 동일 종류 분배(÷3 보장)
          t[2] = [cnt];
        } else {
          // 순서 규약: id_string[k] = 게임 stackCTileList[k] (k=0 바닥). 에디터 stackIdx는 face(0)=꼭대기라
          // 게임과 물리 반대 → reverse해서 게임 물리 index 기준으로 emit. (E6 읽기도 reverse로 대칭)
          ids.reverse();
          t[2] = [cnt, ids.join('_')];
        }
      } else {
        const id = tileNum(tt);
        if (id >= 1 && id <= VISUAL_POOL) t[0] = `t${rel(id)}`;
      }
    }
  }
}

/**
 * [고정 레벨 비주얼 랜덤화] t0 미사용 레벨의 명시 타일을 1~15 풀에서 랜덤 distinct로 재라벨(baked).
 *
 * 배경: 생성기가 useTileCount를 인덱스 상한으로도 해석(generator.py:3198 valid_range)해서
 *   고정 레벨은 항상 t1..t{n} 순차만 씀 → t13~15 등 미사용. 필터/검증(다운스트림) 다 통과한
 *   최종 JSON에서 명시 id를 일괄 relabel → 필터 함정 우회. bijective라 매칭/난이도/÷3 불변.
 * 시드=level_number → 결정적(재현·미리보기==export). stage 1~3 제외(사용자 지정: 기존 유지).
 * t0/혼재 레벨은 미적용(t0 런타임 remap과 충돌 방지 — scanLevelTiles.hasT0 가드).
 */
function remapFixedTileVisuals(levelJsonIn: LevelJsonLike, levelNumber: number): void {
  if (!levelJsonIn || typeof levelNumber !== 'number' || levelNumber <= 3) return;
  const levelJson = levelJsonIn as unknown as Record<string, unknown>;
  const { hasT0, hasCraftStack, explicitIds } = scanLevelTiles(levelJson);
  if (hasT0 || hasCraftStack) return; // t0/craft/stack(내부 t0) 레벨 제외 — 명시-t0 타입 공유로 매칭 붕괴 위험
  if (explicitIds.size === 0) return;

  const usedTypes = [...explicitIds].sort((a, b) => a - b);
  const map = buildVisualIndexMap(usedTypes, levelNumber);

  const layerCount = Number((levelJson as { layer?: unknown }).layer) || 0;
  for (let i = 0; i < layerCount; i++) {
    const ld = levelJson[`layer_${i}`] as { tiles?: Record<string, unknown[]> } | undefined;
    const tiles = ld?.tiles;
    if (!tiles) continue;
    for (const t of Object.values(tiles)) {
      if (!Array.isArray(t) || !t.length) continue;
      const m = /^t(\d+)$/.exec(String(t[0] ?? ''));
      if (m) { const id = parseInt(m[1], 10); if (id >= 1 && id <= VISUAL_POOL) t[0] = `t${map[id]}`; }
    }
  }
}

/**
 * [비주얼 타일 시드] 순수 t0 레벨에만 구체 랜덤 시드 베이크 → 게임이 런타임 t0 스프라이트 재매핑.
 *
 * 기본값 판단: -1(런타임랜덤=미리보기≠인게임)·0(전역 고정=단조) 둘 다 부적합 → 구체 랜덤 베이크(결정적+다양성).
 * ⚠️ 가드: **순수 t0(명시타일과 타입 공유 없음)** 만 적용. 혼재(t0+명시) 레벨은 게임 ApplyVisualTileRemap이
 *   t0 타일만 리맵 → 명시타일과 공유하던 매칭 트리플 깨짐(클리어 불가). 그래서 명시타일 있으면 미설정.
 */
function bakeVisualTileSeed(levelJsonIn: LevelJsonLike): void {
  if (!levelJsonIn) return;
  if (typeof levelJsonIn.visualTileSeed === 'number') return; // 이미 지정됨 → 보존
  const levelJson = levelJsonIn as unknown as Record<string, unknown>;
  const { hasT0, explicitIds } = scanLevelTiles(levelJson);
  if (!hasT0 || explicitIds.size > 0) return; // 순수 t0 아니면 미적용 (혼재 버그 차단)
  (levelJsonIn as { visualTileSeed?: number }).visualTileSeed = Math.floor(Math.random() * 2_000_000_000) + 1;
}

/**
 * 프로덕션 레벨 비주얼 확정(생성/재생성 시 1회). 상호배타:
 *  - 고정(t0無, lvl>3) → 명시타일 1~15 랜덤 relabel
 *  - 순수 t0 → visualTileSeed 베이크 (런타임 remap)
 *  - 혼재/stage1~3 → 미적용(기존 유지)
 */
function applyProductionTileVisuals(levelJson: LevelJsonLike, levelNumber: number): void {
  if (!levelJson) return;
  if (ENABLE_INNER_TILE_BAKE) {
    // 게임 v1.10.382+ 배포 후: t0/craft/stack 전부 명시화 bake → 전 레벨 다양화
    bakeFullBoard(levelJson, levelNumber);
  } else {
    // 현행(구 게임 안전): 순수 고정 relabel + 순수 t0 시드
    remapFixedTileVisuals(levelJson, levelNumber);
    bakeVisualTileSeed(levelJson);
  }
}

/**
 * 레벨 목록에서 useTileCount가 잘못된 레벨들을 찾기
 * 너무 낮은 값(3 이하)만 문제로 간주 - fallback 버그로 인한 케이스
 */
function findLevelsWithWrongTileCount(levels: ProductionLevel[]): ProductionLevel[] {
  return levels.filter(level => {
    const levelNumber = level.meta.level_number;
    const useTileCount = level.level_json?.useTileCount;
    const targetDifficulty = level.meta.target_difficulty;

    if (typeof useTileCount !== 'number') return false;

    // 명백한 오류: useTileCount가 3 이하 (fallback 버그)
    // 레벨 1-10 튜토리얼은 4가 정상이므로 3 이하만 문제
    if (useTileCount <= 3 && levelNumber > 10) {
      return true;
    }

    // 범위 검증
    const validation = validateUseTileCount(levelNumber, useTileCount, targetDifficulty);
    return !validation.isValid;
  });
}

type DashboardTab = 'overview' | 'generate' | 'verify' | 'test' | 'playtest' | 'review' | 'export';

interface ProductionDashboardProps {
  onLevelSelect?: (level: ProductionLevel) => void;
}

// 필수 기믹 언락 정보 (튜토리얼 스테이지)
const GIMMICK_TUTORIAL_INFO: Array<{
  level: number;
  gimmick: string;
  name: string;
  type: 'goal' | 'obstacle';
  difficulty: string;
  description: string;
}> = [
  { level: 11, gimmick: 'craft', name: '공예', type: 'goal', difficulty: '⭐⭐⭐', description: '여러 타일을 모아 완성하는 목표 타일' },
  { level: 21, gimmick: 'stack', name: '스택', type: 'goal', difficulty: '⭐⭐⭐', description: '쌓인 타일을 순서대로 제거' },
  { level: 31, gimmick: 'ice', name: '얼음', type: 'obstacle', difficulty: '⭐⭐⭐', description: '얼어있는 타일, 매칭하면 해제' },
  { level: 51, gimmick: 'link', name: '연결', type: 'obstacle', difficulty: '⭐⭐⭐⭐', description: '연결된 타일은 함께 이동' },
  { level: 81, gimmick: 'chain', name: '사슬', type: 'obstacle', difficulty: '⭐⭐⭐', description: '사슬로 묶인 타일, 인접 매칭 시 해제' },
  { level: 111, gimmick: 'key', name: '버퍼잠금', type: 'obstacle', difficulty: '⭐⭐⭐', description: '열쇠로 잠긴 슬롯 해제' },
  { level: 151, gimmick: 'grass', name: '풀', type: 'obstacle', difficulty: '⭐⭐⭐', description: '풀 위의 타일, 매칭하면 풀 제거' },
  { level: 191, gimmick: 'unknown', name: '상자', type: 'obstacle', difficulty: '⭐⭐', description: '내용물이 숨겨진 상자 타일' },
  { level: 241, gimmick: 'curtain', name: '커튼', type: 'obstacle', difficulty: '⭐⭐', description: '커튼 뒤에 숨겨진 타일' },
  { level: 291, gimmick: 'bomb', name: '폭탄', type: 'obstacle', difficulty: '⭐⭐⭐⭐', description: '시간 내 제거 필요' },
  { level: 341, gimmick: 'time_attack', name: '타임어택', type: 'obstacle', difficulty: '⭐⭐⭐⭐', description: '제한 시간 내 클리어' },
  { level: 391, gimmick: 'frog', name: '개구리', type: 'obstacle', difficulty: '⭐⭐⭐⭐⭐', description: '타일을 먹는 개구리' },
  { level: 441, gimmick: 'teleport', name: '텔레포터', type: 'obstacle', difficulty: '⭐⭐⭐', description: '타일이 이동하는 포탈' },
];

/**
 * 순차 검증 통과 컷오프 (target_difficulty 동적)
 * BE _verify_single_level 의 tolerance 곡선 (0.5→0.7 구간 1.0→1.3×)과 동일.
 * - target < 0.5  → 70 (1.0×)
 * - 0.5~0.7      → 70 → 61 선형
 * - target ≥ 0.7 → 61 (1.3×)
 * UI 표시/필터링과 handleSequentialProcess 가 동일 기준을 사용해야
 * "순차에서 통과한 레벨이 리스트에서 실패로 보이는" 불일치가 사라진다.
 */
function computeSequentialPassThreshold(targetDifficulty: number | undefined): number {
  const td = typeof targetDifficulty === 'number' ? targetDifficulty : 0.5;
  let toleranceMult = 1.0;
  if (td >= 0.7) toleranceMult = 1.3;
  else if (td >= 0.5) toleranceMult = 1.0 + ((td - 0.5) / 0.2) * 0.3;
  const allowedGap = 15 * toleranceMult;
  return Math.max(50, Math.round(100 - allowedGap * 2));
}

/**
 * [v16 자가개선] 생성 난이도 학습 보정 (localStorage).
 * 난이도=f(보드,타일,배치,층...) 고차원이라 손으로 표 못 만듦 → 검증결과로 자동 학습.
 * (밴드 × td버킷) → 통과한 difficultyOffset 의 지수이동평균. 검증 돌릴수록 출발점이 좋아져
 * 첫시도 통과율↑·시도횟수↓. 콜드스타트(데이터 없음)면 0(기존 공식).
 */
const CALIB_KEY = 'levelgen_calib_v1';
function calibBucket(levelNumber: number, td: number): string {
  const band = Math.floor(levelNumber / 100) * 100;     // 100단위 레벨밴드(보드크기 근사)
  const tdb = Math.round(td * 20) / 20;                  // 0.05 td 버킷
  return `${band}_${tdb}`;
}
function getLearnedOffset(levelNumber: number, td: number): number {
  try {
    const m = JSON.parse(localStorage.getItem(CALIB_KEY) || '{}');
    const e = m[calibBucket(levelNumber, td)];
    return e && typeof e.avg === 'number' ? Math.round(e.avg) : 0;
  } catch { return 0; }
}
function recordPassedOffset(levelNumber: number, td: number, offset: number): void {
  try {
    const m = JSON.parse(localStorage.getItem(CALIB_KEY) || '{}');
    const k = calibBucket(levelNumber, td);
    const e = m[k] || { avg: offset, count: 0 };
    // 통과한 offset 쪽으로 지수이동평균(최근 가중) — 변동 흡수하며 수렴
    e.avg = (e.count || 0) === 0 ? offset : e.avg * 0.7 + offset * 0.3;
    e.count = (e.count || 0) + 1;
    m[k] = e;
    localStorage.setItem(CALIB_KEY, JSON.stringify(m));
  } catch { /* localStorage 불가 시 무시 (학습만 비활성) */ }
}

/**
 * [v16] RL 통과 판정 (튜토리얼 예외 포함).
 * 일반 레벨: 백엔드 verification_passed (|gap|<=tol AND not unclearable).
 * 튜토리얼(1~10): 튜토리얼 겸 스테이지라 목표보다 쉬워도 OK — 한쪽 밴드(너무쉬움 허용,
 *   너무어려움만 실패). gap = predicted - target (양수=쉬움). gap >= -tol 이면 통과.
 */
const TUTORIAL_MAX_LEVEL = 10;
const RL_CLEAR_TOL = 0.12; // 백엔드 CLEAR_RATE_TOLERANCE 와 동일
function rlVerificationPassed(
  levelNumber: number,
  rl: { verification_passed: boolean | null; classification: string; clear_rate_gap: number | null },
): boolean {
  if (rl.classification === 'unclearable_suspect') return false;
  if (levelNumber <= TUTORIAL_MAX_LEVEL) {
    return (rl.clear_rate_gap ?? 0) >= -RL_CLEAR_TOL; // 너무어려움(gap<<0)만 실패
  }
  return rl.verification_passed === true;
}

export function ProductionDashboard({ onLevelSelect }: ProductionDashboardProps) {
  const { addNotification } = useUIStore();
  const [activeTab, setActiveTab] = useState<DashboardTab>('overview');
  const [batches, setBatches] = useState<ProductionBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [stats, setStats] = useState<ProductionStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showGimmickInfo, setShowGimmickInfo] = useState(false);

  // Generation state
  const [isGenerating, setIsGenerating] = useState(false);
  const [useValidatedGeneration, setUseValidatedGeneration] = useState(false); // 검증 기반 생성 (기본 OFF - 빠른 생성)

  // [v15.55] 레벨 템플릿 할당 (프로덕션 생성 시 특정 레벨을 템플릿으로 대체)
  //  - 수동 할당: templateAssignments[레벨번호] = templateId
  //  - 자동 배치: autoAssignTemplates=ON 이면 미할당 템플릿을 measured_difficulty 가까운 슬롯에 배치
  const [templateAssignments, setTemplateAssignments] = useState<Record<number, string>>({});
  const [autoAssignTemplates, setAutoAssignTemplates] = useState<boolean>(true);
  // localStorage persist — batch별이 아닌 projectId(현재 단일 프로젝트이므로 공용 키)
  const TEMPLATE_ASSIGN_KEY = 'prod_template_assignments_v1';
  const AUTO_ASSIGN_KEY = 'prod_template_auto_assign_v1';
  useEffect(() => {
    try {
      const raw = localStorage.getItem(TEMPLATE_ASSIGN_KEY);
      if (raw) setTemplateAssignments(JSON.parse(raw));
      const autoRaw = localStorage.getItem(AUTO_ASSIGN_KEY);
      if (autoRaw !== null) setAutoAssignTemplates(autoRaw === '1');
    } catch { /* ignore */ }
  }, []);
  useEffect(() => {
    try { localStorage.setItem(TEMPLATE_ASSIGN_KEY, JSON.stringify(templateAssignments)); } catch { /* ignore */ }
  }, [templateAssignments]);
  useEffect(() => {
    try { localStorage.setItem(AUTO_ASSIGN_KEY, autoAssignTemplates ? '1' : '0'); } catch { /* ignore */ }
  }, [autoAssignTemplates]);
  const [useCoreBots, setUseCoreBots] = useState(true); // 3봇 코어 모드 (기본 ON - 40% 빠름)
  const [validationConfig, setValidationConfig] = useState({
    max_retries: 3,           // 최대 재시도 횟수
    tolerance: 20.0,          // 허용 오차 (%)
    simulation_iterations: 20, // 시뮬레이션 반복 횟수 (가볍게)
  });
  // [역생성] concrete 솔버블 보장 모드. 켜면 컨테이너/순서기믹 없는 plain concrete로 생성되며
  // witness-peeling 타입배정으로 솔버블·÷3 구조적 보장. 적용 레벨은 🧩역 배지 표시.
  const [useReverseGen, setUseReverseGen] = useState(false);
  // 타일 종류 분포(V) 프로파일. 'baseline'=기존 LEVEL_CONFIG_TABLE, 그 외=오버라이드
  const [tileTypeProfile, setTileTypeProfile] = useState<string>('baseline');
  // [RL 난이도 기준 스킬] 순차검증 RL 예측 클리어율을 이 실력(0=최고초보~1=최고고수) 중심으로 가중.
  // 낮추면 검증 엄격(쉬운 레벨만 통과=게임 쉬움), 높이면 관대(어려운 레벨도 통과=게임 어려움).
  // 기본 0.47(캐주얼). 프로덕션 전체 난이도 기준 조절 노브. localStorage 저장(리로드 유지).
  const RL_SKILL_MEAN_KEY = 'prod_rl_skill_mean_v1';
  const [rlSkillMean, setRlSkillMean] = useState<number>(() => {
    try {
      const v = parseFloat(localStorage.getItem(RL_SKILL_MEAN_KEY) ?? '');
      return (Number.isFinite(v) && v >= 0 && v <= 1) ? v : 0.47;
    } catch { return 0.47; }
  });
  useEffect(() => {
    try { localStorage.setItem(RL_SKILL_MEAN_KEY, String(rlSkillMean)); } catch { /* ignore */ }
  }, [rlSkillMean]);
  // 독(트레이7) 천장 무시 → V 최대 15까지 허용 (고난이도 레버). 솔버블은 봇검증이 거름.
  // [B] 층별 그리드 크기 다양화 시작 레벨. 이 레벨 이상부터 각 층 채움 크기를 랜덤(min 3~그리드)으로
  // 다양화(인접층 회피)하고 중앙 배치 → 스택 실루엣 다양화. 튜토리얼/초반(<start)은 단순 유지.
  // 0/빈값이면 미적용. col/row(교대값)는 유지되어 게임과 정합.
  const [sizeDiversityStartLevel, setSizeDiversityStartLevel] = useState<number>(101);
  const [generationProgress, setGenerationProgress] = useState<ProductionGenerationProgress>({
    status: 'idle',
    total_sets: 0,
    completed_sets: 0,
    current_set_index: 0,
    total_levels: 0,
    completed_levels: 0,
    current_level: 0,
    elapsed_ms: 0,
    estimated_remaining_ms: 0,
    failed_levels: [],
    checkpoint_interval_levels: 50,
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  // Throttled progress updater: max 2 renders/sec instead of ~630 during generation
  const progressRef = useRef<ProductionGenerationProgress>(generationProgress);
  const progressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushProgress = useCallback(() => {
    setGenerationProgress({ ...progressRef.current });
  }, []);

  const updateProgressThrottled = useCallback((
    updater: (prev: ProductionGenerationProgress) => ProductionGenerationProgress
  ) => {
    progressRef.current = updater(progressRef.current);
    if (!progressTimerRef.current) {
      progressTimerRef.current = setTimeout(() => {
        progressTimerRef.current = null;
        flushProgress();
      }, 500);
    }
  }, [flushProgress]);

  const flushProgressImmediate = useCallback(() => {
    if (progressTimerRef.current) {
      clearTimeout(progressTimerRef.current);
      progressTimerRef.current = null;
    }
    flushProgress();
  }, [flushProgress]);

  // Initialize DB and load batches
  useEffect(() => {
    // 자동 서버 동기화: 레벨 편집(순차처리·재생성·승인 등)마다 디바운스 push.
    // 충돌(다른 브라우저 선수정) 시 경고만 — 새로고침 시 최신 반영(로컬 미저장분 보호).
    registerAutoSync();
    setConflictHandler((bid, sv) =>
      addNotification('warning', `배치(${bid.slice(0, 12)})가 다른 브라우저에서 수정됨(v${sv}) — 새로고침하면 최신이 반영됩니다`));
    // 저장 시 서버 ÷3 게이트가 클리어 불가(÷3 위반) 레벨을 검출하면 경고.
    setDivisibilityWarningHandler((_bid, flagged, levels) =>
      addNotification('warning', `⚠️ ÷3 위반(클리어 불가) ${flagged}개 레벨 검출 → verification_passed=false 처리됨${levels.length ? ` (예: ${levels.slice(0, 10).join(', ')}${levels.length > 10 ? '…' : ''})` : ''}. 재생성 필요.`));

    async function init() {
      try {
        await initProductionDB();
        // 로컬 배치를 먼저 표시해 탭이 즉시 뜨게 한다(서버 동기화로 UI를 막지 않음).
        const loadedBatches = await listProductionBatches();
        setBatches(loadedBatches);
        if (loadedBatches.length > 0) {
          const latest = [...loadedBatches].sort((a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          )[0];
          setSelectedBatchId(latest.id);
        }
        setIsLoading(false);

        // 서버(로컬 파일) 동기화는 백그라운드 — 다른 브라우저 배치 반영. UI 블로킹 안 함.
        syncBidirectional()
          .then(({ pushed, pulled }) => {
            if (pushed > 0 || pulled > 0) {
              addNotification('info', `서버 동기화: 업로드 ${pushed}개 · 다운로드 ${pulled}개`);
              listProductionBatches().then(setBatches).catch(() => {});
            }
          })
          .catch(() => { /* 서버 미가동 등 — 무시 */ });
      } catch (err) {
        console.error('Failed to initialize production DB:', err);
        addNotification('error', '프로덕션 DB 초기화 실패');
        setIsLoading(false);
      }
    }
    init();
  }, [addNotification]);

  // Load stats when batch changes
  useEffect(() => {
    async function loadStats() {
      if (!selectedBatchId) {
        setStats(null);
        return;
      }
      try {
        const batchStats = await calculateProductionStats(selectedBatchId);
        setStats(batchStats);
      } catch (err) {
        console.error('Failed to load stats:', err);
      }
    }
    loadStats();
  }, [selectedBatchId]);

  // Create new 1500 level batch
  const handleCreateBatch = useCallback(async (preset: keyof typeof PRODUCTION_1500_PRESETS) => {
    const presetConfig = PRODUCTION_1500_PRESETS[preset];

    try {
      const batch = await createProductionBatch({
        name: `${presetConfig.name} - ${new Date().toLocaleDateString()}`,
        total_levels: 1500,
        levels_per_set: 10,
        total_sets: 150,
        generated_count: 0,
        playtest_count: 0,
        approved_count: 0,
        rejected_count: 0,
        exported_count: 0,
        difficulty_start: presetConfig.difficulty_start,
        difficulty_end: presetConfig.difficulty_end,
        use_sawtooth: presetConfig.use_sawtooth,
        gimmick_unlock_levels: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
      });

      setBatches(prev => [batch, ...prev]);
      setSelectedBatchId(batch.id);
      addNotification('success', `배치 "${batch.name}" 생성됨`);
      setActiveTab('generate');
    } catch (err) {
      addNotification('error', '배치 생성 실패');
    }
  }, [addNotification]);

  // Generate levels for batch
  const handleStartGeneration = useCallback(async (
    playtestConfig: PlaytestQueueConfig
  ) => {
    if (!selectedBatchId) return;

    const batch = await getProductionBatch(selectedBatchId);
    if (!batch) return;

    setIsGenerating(true);
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    // [v15.55] 템플릿 자동 배치 — 미할당 템플릿을 measured_difficulty 기반 슬롯에 매핑
    // manual 할당은 우선. auto 토글 OFF면 manual만 사용.
    let effectiveAssignments: Record<number, string> = { ...templateAssignments };
    console.log('[generate] 수동 할당 (initial):', templateAssignments, 'autoAssign:', autoAssignTemplates);
    const autoAssignWarnings: string[] = [];
    if (autoAssignTemplates) {
      try {
        const tplRes = await apiClient.get('/debug/level-templates');
        const allTemplates = (tplRes.data.templates || []) as Array<{
          template_id: string;
          measured_difficulty?: number | null;
          name?: string;
        }>;
        const takenLevels = new Set<number>(Object.keys(effectiveAssignments).map(k => parseInt(k)));
        const takenTemplateIds = new Set<string>(Object.values(effectiveAssignments));

        // 모든 슬롯의 target_difficulty 계산
        const slots: Array<{ level: number; targetDiff: number }> = [];
        for (let level = 1; level <= batch.total_levels; level++) {
          const setIdx = Math.floor((level - 1) / batch.levels_per_set);
          const localIdx = ((level - 1) % batch.levels_per_set) + 1;
          const baseDifficulty = batch.difficulty_start +
            (batch.difficulty_end - batch.difficulty_start) * setIdx / Math.max(1, batch.total_sets - 1);
          let targetDifficulty = baseDifficulty;
          if (batch.use_sawtooth) {
            const localProgress = (localIdx - 1) / (batch.levels_per_set - 1);
            const sawtoothBonus = localIdx === 10 ? 0.1 : localProgress * 0.05;
            targetDifficulty = Math.min(0.95, baseDifficulty + sawtoothBonus);
          }
          slots.push({ level, targetDiff: targetDifficulty });
        }

        // [보스 배치 정책] 템플릿을 보스 레벨(%10==0)에 measured_difficulty 오름차순 순차 배치.
        //   쉬운 템플릿 → 첫 보스(10), 다음 → 20 ... 보스 다 차면 overflow.
        //   확장성: primary/overflow 정책 상수만 바꿔 (보스전용 → non-boss spill → 전 레벨) 전환.
        const TEMPLATE_SLOT_POLICY: { primary: 'boss'; overflow: 'unused' | 'spill' } = {
          primary: 'boss',
          overflow: 'unused', // 미래: 'spill' → 초과 템플릿을 non-boss 슬롯에 난이도 매칭
        };

        // 미할당 + 측정된 템플릿만 대상, 난이도 오름차순
        const sortedTpls = allTemplates
          .filter(t => t.measured_difficulty != null && !takenTemplateIds.has(t.template_id))
          .sort((a, b) => (a.measured_difficulty || 0) - (b.measured_difficulty || 0));

        // 보스 슬롯 (미점유, 레벨 오름차순)
        const bossSlots = slots
          .filter(s => s.level % 10 === 0 && !takenLevels.has(s.level))
          .sort((a, b) => a.level - b.level);

        // [보스 템플릿 차용+크롭] 보스 슬롯에 기존 템플릿 모양을 배정하되, 생성 시 crop_max_dim=8로
        // 빈 가장자리 크롭(A타입=원래≤8 그대로, B타입=크롭시≤8). 크롭 불가(D타입)면 생성 단계에서
        // boss_mode 레시피 생성기로 자동 폴백(그리드 게이트). 순차 배치: 쉬운 템플릿 → 낮은 보스.
        const placedCount = Math.min(sortedTpls.length, bossSlots.length);
        for (let i = 0; i < placedCount; i++) {
          effectiveAssignments[bossSlots[i].level] = sortedTpls[i].template_id;
          takenLevels.add(bossSlots[i].level);
        }

        // overflow: 보스 슬롯 초과분
        const overflowTpls = sortedTpls.slice(placedCount);
        if (overflowTpls.length > 0) {
          if (TEMPLATE_SLOT_POLICY.overflow === 'spill') {
            // [확장 격리] 기존 best-gap: 남은 템플릿을 non-boss 슬롯에 targetDiff 근접 매칭
            for (const tpl of overflowTpls) {
              const diff = tpl.measured_difficulty!;
              let bestSlot: typeof slots[number] | null = null;
              let bestGap = Infinity;
              for (const slot of slots) {
                if (takenLevels.has(slot.level)) continue;
                const gap = Math.abs(slot.targetDiff - diff);
                if (gap < bestGap) { bestGap = gap; bestSlot = slot; }
              }
              if (bestSlot) { effectiveAssignments[bestSlot.level] = tpl.template_id; takenLevels.add(bestSlot.level); }
              else { autoAssignWarnings.push(`${tpl.name || tpl.template_id}: 빈 슬롯 없음`); }
            }
          } else {
            // unused: 보스 부족 → 초과 템플릿 미배치 (쉬운 것부터 보스 채움)
            for (const tpl of overflowTpls) {
              autoAssignWarnings.push(`${tpl.name || tpl.template_id}: 보스 슬롯 부족 — 미배치 (overflow=unused)`);
            }
          }
        }
        // underflow(템플릿 < 보스): 남는 보스는 effectiveAssignments 미설정 → 기존 절차생성 경로 (변경 없음)

        // 측정 안 된 템플릿 경고
        for (const tpl of allTemplates) {
          if (tpl.measured_difficulty == null && !takenTemplateIds.has(tpl.template_id)) {
            autoAssignWarnings.push(`${tpl.name || tpl.template_id}: 난이도 미측정 — 자동 배치 스킵`);
          }
        }
        if (autoAssignWarnings.length > 0) {
          console.warn('[template-auto-assign]', autoAssignWarnings);
        }
        const manualCount = Object.keys(templateAssignments).length;
        const totalCount = Object.keys(effectiveAssignments).length;
        const addedCount = totalCount - manualCount;
        if (totalCount > 0) {
          addNotification('info',
            `📋 템플릿 할당: 총 ${totalCount}개 (수동 ${manualCount} + 자동 ${addedCount}), 경고 ${autoAssignWarnings.length}개`);
        } else if (allTemplates.length > 0) {
          // 템플릿은 있지만 하나도 할당 안 됨 → 원인 알림
          const measured = allTemplates.filter(t => t.measured_difficulty != null).length;
          addNotification('warning',
            `📋 템플릿 ${allTemplates.length}개 존재하나 0개 할당됨 (측정 ${measured}/${allTemplates.length}). 템플릿을 사용하려면 디버거 탭에서 먼저 난이도 측정 필요.`);
        }
      } catch (err) {
        console.error('Template auto-assignment failed:', err);
        addNotification('warning', `템플릿 자동 배치 실패: ${(err as Error).message} — manual 할당만 사용`);
      }
    }

    const startTime = Date.now();
    const initialProgress: ProductionGenerationProgress = {
      status: 'generating',
      total_sets: batch.total_sets,
      completed_sets: 0,
      current_set_index: 0,
      total_levels: batch.total_levels,
      completed_levels: 0,
      current_level: 0,
      elapsed_ms: 0,
      estimated_remaining_ms: 0,
      started_at: new Date().toISOString(),
      failed_levels: [],
      checkpoint_interval_levels: 50,
    };
    progressRef.current = initialProgress;
    setGenerationProgress(initialProgress);

    const pendingLevels: ProductionLevel[] = [];
    let completedCount = 0;
    const failedLevels: number[] = [];

    // In-memory counters to avoid post-generation full IndexedDB scans
    const statusCounts = { generated_count: 0, playtest_count: 0, approved_count: 0, rejected_count: 0, exported_count: 0 };
    const gradeCounts: Record<string, number> = { S: 0, A: 0, B: 0, C: 0, D: 0 };
    let totalMatchScore = 0;
    let matchScoreCount = 0;

    try {
      for (let setIdx = 0; setIdx < batch.total_sets; setIdx++) {
        if (signal.aborted) throw new Error('cancelled');

        updateProgressThrottled(prev => ({
          ...prev,
          current_set_index: setIdx,
        }));

        // Calculate difficulty for this set
        const setProgress = setIdx / (batch.total_sets - 1);
        let baseDifficulty: number;

        if (batch.use_sawtooth) {
          // Sawtooth pattern: increase within set, reset at new set
          const overallDifficulty =
            batch.difficulty_start +
            setProgress * (batch.difficulty_end - batch.difficulty_start);

          baseDifficulty = overallDifficulty;
        } else {
          baseDifficulty =
            batch.difficulty_start +
            setProgress * (batch.difficulty_end - batch.difficulty_start);
        }

        // PARALLEL GENERATION: Generate all levels in this set concurrently
        // 비검증 모드: 10개 동시 (빠름, 요청당 ~3ms)
        // 검증 모드: 8개 동시 (ProcessPoolExecutor 병렬화 + 4 uvicorn workers)
        const CONCURRENCY = useValidatedGeneration ? 8 : 10;

        // Prepare level generation tasks for this set
        interface LevelTask {
          localIdx: number;
          levelNumber: number;
          targetDifficulty: number;
          patternIndex: number;  // Pre-computed pattern index
          // [v15.55] 할당된 레벨 템플릿 ID — 있으면 템플릿 기반 생성 사용
          templateId?: string;
        }

        // [v15.40] 비활성 패턴 목록을 서버에서 가져옴 (그리드 크기별)
        let disabledPatternsMap: Record<string, number[]> = {};
        try {
          const configRes = await apiClient.get('/debug/pattern-config');
          const raw = configRes.data.disabled_patterns_all || configRes.data.disabled_patterns;
          if (Array.isArray(raw)) {
            for (const s of [6,7,8,9]) disabledPatternsMap[String(s)] = raw;
          } else {
            disabledPatternsMap = raw;
          }
        } catch {
          const fb = [5, 22, 25, 29, 39, 40, 42, 47, 54, 57, 60];
          for (const s of [6,7,8,9]) disabledPatternsMap[String(s)] = fb;
        }
        // gridSize에 맞는 disabled 선택하는 헬퍼
        const getDisabledForSize = (gs: number) => new Set(disabledPatternsMap[String(gs)] || []);

        // OPTION D: Pre-compute pattern indices to prevent consecutive same patterns
        const preComputePatternIndices = (count: number, startLevelNumber: number): number[] => {
          const indices: number[] = [];
          let previousIndex = -1;

          for (let i = 0; i < count; i++) {
            const levelNumber = startLevelNumber + i;
            const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;
            const isSpecialShape = levelNumber % 10 === 9;

            let pool: number[];
            if (isBossLevel) {
              pool = [...BOSS_PATTERNS];
            } else if (isSpecialShape) {
              pool = [...SPECIAL_PATTERNS];
            } else {
              // General levels: 64 patterns excluding POOR quality (fill<40%)
              // POOR: #5,22,25,29,39,42,47,54,57,60 - 너무 성겨서 형태 불명확
              const EXCLUDED_PATTERNS = getDisabledForSize(8);
              pool = Array.from({ length: 64 }, (_, i) => i).filter(i => !EXCLUDED_PATTERNS.has(i));
            }

            // Remove previous pattern from pool to prevent consecutive same pattern
            if (previousIndex >= 0 && pool.length > 1) {
              pool = pool.filter(p => p !== previousIndex);
            }

            // Random selection from filtered pool
            const selectedIndex = pool[Math.floor(Math.random() * pool.length)];
            indices.push(selectedIndex);
            previousIndex = selectedIndex;
          }

          return indices;
        };

        const patternIndices = preComputePatternIndices(batch.levels_per_set, setIdx * batch.levels_per_set + 1);

        const levelTasks: LevelTask[] = [];
        for (let localIdx = 1; localIdx <= batch.levels_per_set; localIdx++) {
          const levelNumber = setIdx * batch.levels_per_set + localIdx;
          let targetDifficulty = baseDifficulty;
          if (batch.use_sawtooth) {
            const localProgress = (localIdx - 1) / (batch.levels_per_set - 1);
            const sawtoothBonus = localIdx === 10 ? 0.1 : localProgress * 0.05;
            targetDifficulty = Math.min(0.95, baseDifficulty + sawtoothBonus);
          }
          // [v15.55] 이 레벨에 수동/자동 할당된 템플릿이 있는지 확인
          const tplId = effectiveAssignments[levelNumber];
          levelTasks.push({
            localIdx,
            levelNumber,
            targetDifficulty,
            patternIndex: patternIndices[localIdx - 1],
            templateId: tplId,
          });
        }

        // Helper: Generate a single level (returns ProductionLevel or null on failure)
        const generateOneLevel = async (task: LevelTask): Promise<ProductionLevel | null> => {
          const { localIdx, levelNumber, targetDifficulty, patternIndex, templateId } = task;

          // [v15.55] 레벨 템플릿 할당됨 → from-template 엔드포인트 분기
          // [보스 크롭] 보스(10의 배수)는 crop_max_dim=8로 빈 가장자리 크롭(A/B타입). 크롭 후에도
          // >8(D타입)이면 템플릿 폐기하고 아래 절차생성(boss_mode 레시피)으로 폴백.
          const isBossTemplate = levelNumber % 10 === 0 && levelNumber > 0;
          if (templateId) {
            try {
              const tplStartTime = Date.now();
              const tplResp = await apiClient.post('/generate/from-template', {
                template_id: templateId,
                level_number: levelNumber,
                use_tile_count: 6,
                randomize_tiles: true,
                random_seed: levelNumber,
                crop_max_dim: isBossTemplate ? MAX_PLAYABLE_GRID : undefined,
              });
              const levelJson = tplResp.data.level_json;
              // 보스인데 크롭해도 >8(D타입) → 템플릿 폐기, 절차생성 폴백
              if (isBossTemplate && maxDeclaredGridDim(levelJson) > MAX_PLAYABLE_GRID) {
                throw new Error(`boss template ${templateId} uncroppable (>${MAX_PLAYABLE_GRID}) → 절차생성 폴백`);
              }
              const generationTime = Date.now() - tplStartTime;

              // 봇 검증 (기존 파이프라인과 동일하게 autoplay 실행)
              let matchScore = 0;
              let botStats: Array<{ profile: string; clear_rate: number; target_clear_rate: number }> = [];
              try {
                const autoplayRes = await apiClient.post('/analyze/autoplay', {
                  level_json: levelJson,
                  iterations: useCoreBots ? 50 : 100,
                  target_difficulty: targetDifficulty,
                  bot_profiles: useCoreBots ? ['average', 'expert', 'optimal'] : undefined,
                }, { timeout: 310000 });
                botStats = (autoplayRes.data.bot_stats || []).map((b: { profile: string; clear_rate: number; target_clear_rate: number }) => ({
                  profile: b.profile,
                  clear_rate: b.clear_rate,
                  target_clear_rate: b.target_clear_rate,
                }));
                if (botStats.length > 0) {
                  const gaps = botStats.map(s => {
                    const g = (s.clear_rate - s.target_clear_rate) * 100;
                    return g > 0 ? g * 0.5 : Math.abs(g) * 0.7;
                  });
                  const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
                  const maxGap = Math.max(...gaps);
                  matchScore = Math.max(0, 100 - (avgGap * 0.7 + maxGap * 0.3) * 2);
                }
              } catch (botErr) {
                console.warn(`[template-bot-sim] level ${levelNumber}:`, botErr);
              }

              const botClearRates = {
                average: botStats.find(s => s.profile === 'average')?.clear_rate ?? 0,
                expert: botStats.find(s => s.profile === 'expert')?.clear_rate ?? 0,
                optimal: botStats.find(s => s.profile === 'optimal')?.clear_rate ?? 0,
              };
              const meta: ProductionLevelMeta = {
                level_number: levelNumber,
                set_index: setIdx,
                local_index: localIdx,
                generated_at: new Date().toISOString(),
                target_difficulty: targetDifficulty,
                actual_difficulty: tplResp.data.actual_difficulty ?? 0,
                grade: (tplResp.data.grade || 'C') as DifficultyGrade,
                status: 'playtest_queue',
                status_updated_at: new Date().toISOString(),
                playtest_required: true,
                playtest_priority: levelNumber,
                playtest_results: [],
                match_score: matchScore,
                bot_clear_rates: botClearRates,
                validation_attempts: 0,
                pattern_index: -1,            // 템플릿 기반 — 패턴 인덱스 의미 없음
                pattern_type: 'aesthetic',
                template_id: templateId,       // 템플릿 출처 표시
                template_source_difficulty: tplResp.data.template_measured_difficulty ?? undefined,
              };
              void generationTime;  // 수집 안 하지만 측정은 해둠 (future use)
              applyProductionTileVisuals(levelJson, levelNumber);  // 고정=명시 relabel / 순수t0=시드 베이크
              return { meta, level_json: levelJson };
            } catch (tplErr) {
              const errMsg = (tplErr as Error).message || String(tplErr);
              console.error(`[template-gen] level ${levelNumber} failed, falling back to pattern:`, errMsg);
              addNotification('warning',
                `레벨 ${levelNumber} 템플릿 생성 실패 → 패턴으로 fallback: ${errMsg}`);
              // 실패 시 기존 패턴 기반 생성으로 fallback (아래 코드 진행)
            }
          }

          // Local helper: Calculate match score from bot stats (asymmetric penalty)
          // [v14.2] 방안 B+D: maxGap 가중치 감소(0.4→0.3) + 어려움 패널티 완화(1.0→0.7)
          const calcMatchScore = (botStats: { clear_rate: number; target_clear_rate: number }[]) => {
            if (!botStats.length) return 0;
            const gaps = botStats.map(s => {
              const rawGap = (s.clear_rate - s.target_clear_rate) * 100;
              // 방안 D: 너무 쉬움 = 50% 패널티, 너무 어려움 = 70% 패널티 (기존 100%)
              return rawGap > 0 ? rawGap * 0.5 : Math.abs(rawGap) * 0.7;
            });
            const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
            const maxGap = Math.max(...gaps);
            // 방안 B: avgGap×0.7 + maxGap×0.3 (기존 0.6/0.4)
            const weightedGap = (avgGap * 0.7 + maxGap * 0.3);
            return Math.max(0, 100 - weightedGap * 2);
          };

          try {
            const isEarlyLevel = levelNumber <= 30;
            const isSpecialShape = levelNumber % 10 === 9;
            const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;

            // Pattern type: 항상 aesthetic 사용 (64개 패턴 중 선택)
            // geometric/clustered 제거 - 모든 레벨이 명확한 모양을 가지도록
            const patternType: 'aesthetic' = 'aesthetic';

            // Symmetry mode selection
            const symmetryRoll = Math.random();
            let symmetryMode: 'none' | 'horizontal' | 'vertical' | 'both';
            if (isEarlyLevel) {
              symmetryMode = symmetryRoll < 0.25 ? 'horizontal' : symmetryRoll < 0.50 ? 'vertical' : 'both';
            } else if (isSpecialShape) {
              symmetryMode = symmetryRoll < 0.30 ? 'none' : symmetryRoll < 0.65 ? 'horizontal' : 'vertical';
            } else if (isBossLevel) {
              symmetryMode = symmetryRoll < 0.20 ? 'horizontal' : symmetryRoll < 0.40 ? 'vertical' : 'both';
            } else {
              symmetryMode = symmetryRoll < 0.05 ? 'none' : symmetryRoll < 0.40 ? 'horizontal' : symmetryRoll < 0.75 ? 'vertical' : 'both';
            }

            // Goal direction
            let goalDirections: Array<'s' | 'n' | 'e' | 'w'>;
            if (symmetryMode === 'both' || symmetryMode === 'vertical') {
              goalDirections = Math.random() < 0.7 ? ['s', 'n'] : ['e', 'w'];
            } else if (symmetryMode === 'horizontal') {
              goalDirections = Math.random() < 0.7 ? ['e', 'w'] : ['s', 'n'];
            } else {
              goalDirections = ['s', 'n', 'e', 'w'];
            }
            const goalDirection = goalDirections[Math.floor(Math.random() * goalDirections.length)];
            const goalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];

            // Pattern index: Use pre-computed value from task
            // OPTION D: Consecutive same pattern prevention applied at task creation
            // (patternIndex is already set in task from preComputePatternIndices)

            // Grid size
            let gridSize: [number, number] = [7, 7];
            if (isBossLevel && targetDifficulty > 0.3) {
              gridSize = [8, 8];
            } else if (!isEarlyLevel && Math.random() < 0.3) {
              gridSize = [8, 8];
            }

            // Layers
            let minLayers = 2;
            let maxLayers = Math.min(10, 3 + Math.floor(targetDifficulty * 7));
            if (isEarlyLevel) { minLayers = 2; maxLayers = Math.min(4, maxLayers); }
            else if (isBossLevel) { minLayers = Math.max(3, Math.floor(2 + targetDifficulty * 2)); maxLayers = Math.min(10, 4 + Math.floor(targetDifficulty * 6)); }

            // Tile types: 백엔드에서 level_number 기반 자동 선택 (톱니바퀴 패턴 + t0)
            // - 사이클 첫 레벨 (1, 11, 21...): 특정 타일 세트 (t1-t5, t6-t10, t11-t15)
            // - 나머지 레벨: t0 (클라이언트에서 런타임 결정)

            const params: GenerationParams = {
              target_difficulty: targetDifficulty,
              grid_size: isBossLevel ? [7, 7] : gridSize, // 보스: 백엔드가 (7,7)→선언 최대 8 사용
              min_layers: isBossLevel ? 5 : minLayers,
              max_layers: isBossLevel ? 6 : maxLayers,
              tile_types: undefined, // 백엔드에서 level_number 기반 자동 선택
              tile_type_profile: tileTypeProfile === 'baseline' ? undefined : tileTypeProfile,
              obstacle_types: [],
              goals: [{ type: goalType, direction: goalDirection, count: Math.max(2, Math.floor(3 + targetDifficulty * 2)) }],
              symmetry_mode: symmetryMode,
              pattern_type: patternType,
              // 보스: pattern_index 미지정 → 백엔드 auto-mix가 BOSS_RECIPES(레벨번호 결정적) 적용
              pattern_index: isBossLevel ? undefined : patternIndex,
              // [B] 층별 크기 다양화 (0이면 미적용)
              size_diversity_start_level: sizeDiversityStartLevel > 0 ? sizeDiversityStartLevel : undefined,
              // [보스 생성기] 그리드≤8·5~6층·화려한 레시피. 목표 클리어율 절반은 RL 검증에서 적용.
              boss_mode: isBossLevel || undefined,
            };

            const gimmickOptions = {
              auto_select_gimmicks: true,
              available_gimmicks: ['craft', 'stack', 'chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
              gimmick_unlock_levels: batch.gimmick_unlock_levels || PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
              level_number: levelNumber,
              // [역생성] 켜면 백엔드가 컨테이너/기믹 제거 후 witness 타입배정 → 솔버블 보장
              use_reverse_generation: useReverseGen,
            };

            let result;
            let validationPassed = true;
            let validationAttempts = 1;
            let matchScore: number | undefined = undefined;
            // [v15.14] novice/casual은 optional (검증에서 제외됨)
            let botClearRates: { novice?: number; casual?: number; average: number; expert: number; optimal: number } | undefined = undefined;

            // === 공통: 허용 오차 다중 후보 방식으로 정적 난이도 오차 0.05 이내 달성 ===
            // [v15.6] 개선: 점진적 허용오차 + 재시도 로직 + 후보 다양성 증가
            const BASE_TOLERANCE = 5.0; // 0.05 in 0-1 scale = 5.0 in 0-100 scale
            const CANDIDATES_PER_ATTEMPT = 3;
            const MAX_ATTEMPTS = 6; // 5 → 6 증가
            const targetScore = targetDifficulty * 100;

            let bestResult: GenerationResult | null = null;
            let bestGap = Infinity;
            let actualAttempts = 0;
            let totalCandidatesGenerated = 0;

            // Helper: 단일 후보 생성 (1회 재시도 포함)
            const generateOneCandidate = async (
              candidateGoalDirection: 's' | 'n' | 'e' | 'w',
              candidateGoalType: 'craft' | 'stack',
              layerVariation: number,
              intensityMultiplier: number
            ): Promise<GenerationResult | null> => {
              const candidateParams = {
                ...params,
                // 레이어 수 변화로 다양성 증가
                min_layers: Math.max(2, (params.min_layers ?? 2) + layerVariation),
                max_layers: Math.min(10, (params.max_layers ?? 5) + layerVariation),
                goals: [{
                  type: candidateGoalType,
                  direction: candidateGoalDirection,
                  count: Math.max(2, Math.floor(3 + targetDifficulty * 2))
                }],
              };
              const candidateGimmickOptions = {
                ...gimmickOptions,
                // 기믹 강도 변화로 다양성 증가
                gimmick_intensity: Math.min(targetDifficulty * intensityMultiplier, levelNumber / 500),
              };

              try {
                return await generateLevel(candidateParams, candidateGimmickOptions);
              } catch {
                // 첫 번째 실패 시 1회 재시도
                try {
                  return await generateLevel(candidateParams, candidateGimmickOptions);
                } catch {
                  return null;
                }
              }
            };

            for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
              actualAttempts = attempt + 1;

              // 점진적 허용오차: attempt가 증가할수록 오차 허용 범위 확대
              // attempt 0-2: 5.0, attempt 3-4: 7.5, attempt 5: 10.0
              const currentTolerance = attempt < 3 ? BASE_TOLERANCE :
                                        attempt < 5 ? BASE_TOLERANCE * 1.5 :
                                        BASE_TOLERANCE * 2.0;

              // 후보 다양성: 레이어 수와 기믹 강도를 변화시켜 다양한 난이도 생성
              const layerVariations = [-1, 0, 1]; // 레이어 ±1
              const intensityMultipliers = [0.8, 1.0, 1.2]; // 기믹 강도 ±20%

              const candidates = await Promise.all(
                Array.from({ length: CANDIDATES_PER_ATTEMPT }, (_, idx) => {
                  // 미형 로직 유지: pattern_type, symmetry_mode, pattern_index는 기존 params 사용
                  let candidateGoalDirections: Array<'s' | 'n' | 'e' | 'w'>;
                  if (symmetryMode === 'both' || symmetryMode === 'vertical') {
                    candidateGoalDirections = Math.random() < 0.7 ? ['s', 'n'] : ['e', 'w'];
                  } else if (symmetryMode === 'horizontal') {
                    candidateGoalDirections = Math.random() < 0.7 ? ['e', 'w'] : ['s', 'n'];
                  } else {
                    candidateGoalDirections = ['s', 'n', 'e', 'w'];
                  }
                  const candidateGoalDirection = candidateGoalDirections[Math.floor(Math.random() * candidateGoalDirections.length)];
                  const candidateGoalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];

                  // 각 후보마다 다른 변화 적용
                  const layerVar = layerVariations[idx % layerVariations.length];
                  const intensityMult = intensityMultipliers[idx % intensityMultipliers.length];

                  return generateOneCandidate(candidateGoalDirection, candidateGoalType, layerVar, intensityMult);
                })
              );

              totalCandidatesGenerated += CANDIDATES_PER_ATTEMPT;

              for (const c of candidates) {
                if (!c) continue;
                const gap = Math.abs(c.actual_difficulty - targetScore);
                if (gap < bestGap) {
                  bestGap = gap;
                  bestResult = c;
                }
              }

              // 현재 허용오차 이내면 즉시 채택
              if (bestGap <= currentTolerance) break;
            }

            if (!bestResult) {
              // 모든 API 호출 실패 (네트워크 오류 등)
              console.error(`Level ${levelNumber}: All ${totalCandidatesGenerated} candidates failed (API errors)`);
              throw new Error(`${totalCandidatesGenerated}개 후보 모두 API 실패`);
            }

            // Best-match 폴백: 허용오차 초과해도 최선의 결과 사용 (경고 로그)
            if (bestGap > BASE_TOLERANCE) {
              console.warn(`Level ${levelNumber}: Using best-match fallback (gap: ${bestGap.toFixed(1)}%, tolerance: ${BASE_TOLERANCE}%)`);
            }
            result = bestResult;
            validationAttempts = actualAttempts;

            // === 검증 활성화 시: 봇 시뮬레이션으로 match_score 측정 ===
            if (useValidatedGeneration && validationConfig.simulation_iterations > 0) {
              try {
                // [v15.14] 검증용 봇: average, expert, optimal (novice/casual 제외)
                const botProfiles = useCoreBots
                  ? ['average', 'expert', 'optimal']  // 코어 3봇 (검증용)
                  : ['average', 'expert', 'optimal'];  // 동일 (레거시 호환)
                const simResult = await analyzeAutoPlay(result.level_json, {
                  iterations: validationConfig.simulation_iterations,
                  targetDifficulty: targetDifficulty,
                  botProfiles: botProfiles,
                });
                matchScore = calcMatchScore(simResult.bot_stats);
                botClearRates = {
                  // novice/casual은 검증에서 제외되므로 undefined
                  average: simResult.bot_stats.find(s => s.profile === 'average')?.clear_rate || 0,
                  expert: simResult.bot_stats.find(s => s.profile === 'expert')?.clear_rate || 0,
                  optimal: simResult.bot_stats.find(s => s.profile === 'optimal')?.clear_rate || 0,
                };
                validationPassed = matchScore !== undefined && matchScore >= validationConfig.tolerance;
              } catch (simErr) {
                console.warn(`Bot simulation failed for level ${levelNumber}:`, simErr);
                // 시뮬레이션 실패 시 match_score 없이 진행
              }
            }

            const meta: ProductionLevelMeta = {
              level_number: levelNumber,
              set_index: setIdx,
              local_index: localIdx,
              generated_at: new Date().toISOString(),
              target_difficulty: targetDifficulty,
              actual_difficulty: result.actual_difficulty,
              grade: result.grade as DifficultyGrade,
              status: validationPassed ? 'generated' : 'playtest_queue',
              status_updated_at: new Date().toISOString(),
              playtest_required: !validationPassed || shouldRequirePlaytest(
                { level_number: levelNumber, grade: result.grade as DifficultyGrade, match_score: matchScore, target_difficulty: targetDifficulty },
                playtestConfig
              ),
              playtest_priority: validationPassed ? levelNumber : levelNumber - 10000,
              playtest_results: [],
              match_score: matchScore,
              bot_clear_rates: botClearRates,
              validation_attempts: validationAttempts,
              // 패턴 생성 정보 저장
              pattern_index: patternIndex,
              pattern_type: patternType,
            };

            if (meta.playtest_required) {
              meta.status = 'playtest_queue';
            }

            applyProductionTileVisuals(result.level_json, levelNumber);  // 고정=명시 relabel / 순수t0=시드 베이크
            return { meta, level_json: result.level_json };
          } catch (err) {
            console.error(`Failed to generate level ${levelNumber}:`, err);
            return null;
          }
        };

        // Execute in parallel batches with concurrency limit
        for (let batchStart = 0; batchStart < levelTasks.length; batchStart += CONCURRENCY) {
          if (signal.aborted) throw new Error('cancelled');

          const batchSlice = levelTasks.slice(batchStart, batchStart + CONCURRENCY);

          // Update progress for current batch (throttled to reduce re-renders)
          const lastLevelNum = batchSlice[batchSlice.length - 1].levelNumber;
          updateProgressThrottled(prev => ({
            ...prev,
            current_level: lastLevelNum,
            elapsed_ms: Date.now() - startTime,
            estimated_remaining_ms: completedCount > 0
              ? ((Date.now() - startTime) / completedCount) * (batch.total_levels - completedCount)
              : 0,
          }));

          // Run batch in parallel
          const results = await Promise.allSettled(
            batchSlice.map(task => generateOneLevel(task))
          );

          // Process results and accumulate in-memory counters
          for (let i = 0; i < results.length; i++) {
            const r = results[i];
            const task = batchSlice[i];
            if (r.status === 'fulfilled' && r.value) {
              pendingLevels.push(r.value);
              completedCount++;
              // Accumulate stats in-memory
              const meta = r.value.meta;
              if (meta.status === 'generated') statusCounts.generated_count++;
              else if (meta.status === 'playtest_queue' || meta.status === 'playtesting') statusCounts.playtest_count++;
              if (meta.grade in gradeCounts) gradeCounts[meta.grade]++;
              if (meta.match_score !== undefined) {
                totalMatchScore += meta.match_score;
                matchScoreCount++;
              }
            } else {
              failedLevels.push(task.levelNumber);
              if (r.status === 'rejected') {
                console.error(`Failed to generate level ${task.levelNumber}:`, r.reason);
              }
            }
          }

          // Update completed_levels after every batch (throttled)
          updateProgressThrottled(prev => ({
            ...prev,
            completed_levels: completedCount,
            elapsed_ms: Date.now() - startTime,
            estimated_remaining_ms: completedCount > 0
              ? ((Date.now() - startTime) / completedCount) * (batch.total_levels - completedCount)
              : 0,
          }));

          // Checkpoint save every 50 levels — non-blocking fire-and-forget
          if (pendingLevels.length >= 50 || signal.aborted) {
            const levelsToSave = [...pendingLevels];
            pendingLevels.length = 0;
            saveProductionLevels(selectedBatchId, levelsToSave).catch(err => {
              console.error('[Checkpoint] Save failed, will retry:', err);
              pendingLevels.push(...levelsToSave);
            });
            updateProgressThrottled(prev => ({
              ...prev,
              last_checkpoint_at: new Date().toISOString(),
            }));
          }
        }

        updateProgressThrottled(prev => ({
          ...prev,
          completed_sets: setIdx + 1,
          completed_levels: completedCount,
        }));
      }

      // Save remaining levels
      if (pendingLevels.length > 0) {
        await saveProductionLevels(selectedBatchId, pendingLevels);
      }

      // Update batch counts using in-memory counters (avoids full IndexedDB scan)
      await updateProductionBatch(selectedBatchId, statusCounts);

      // Flush throttled progress, then set final state immediately
      flushProgressImmediate();
      setGenerationProgress(prev => ({
        ...prev,
        status: 'completed',
        completed_levels: completedCount,
        failed_levels: failedLevels,
      }));

      // Build stats from in-memory counters (avoids second full IndexedDB scan)
      const playtestRequired = statusCounts.playtest_count;
      const inMemoryStats: ProductionStats = {
        total_levels: completedCount,
        by_status: {
          generated: statusCounts.generated_count,
          playtest_queue: statusCounts.playtest_count,
          playtesting: 0,
          approved: 0,
          rejected: 0,
          needs_rework: 0,
          exported: 0,
        } as Record<LevelStatus, number>,
        by_grade: {
          S: gradeCounts['S'] || 0,
          A: gradeCounts['A'] || 0,
          B: gradeCounts['B'] || 0,
          C: gradeCounts['C'] || 0,
          D: gradeCounts['D'] || 0,
        } as Record<DifficultyGrade, number>,
        playtest_progress: {
          total_required: playtestRequired,
          completed: 0,
          pending: playtestRequired,
        },
        quality_metrics: {
          avg_match_score: matchScoreCount > 0 ? totalMatchScore / matchScoreCount : 0,
          avg_fun_rating: 0,
          avg_perceived_difficulty: 0,
          rejection_rate: 0,
        },
        estimated_completion: {
          remaining_playtest_hours: (playtestRequired * 3) / 60,
          ready_for_export: 0,
        },
      };
      setStats(inMemoryStats);

      // Refresh batches list to show updated generated_count
      const updatedBatches = await listProductionBatches();
      setBatches(updatedBatches);

      // 서버(로컬 파일)에 자동 저장 → 같은 컴퓨터의 다른 브라우저에서도 접근 가능
      pushBatchToServer(selectedBatchId).catch(() => { /* 서버 미가동 시 무시 */ });

      addNotification(
        'success',
        `${completedCount}개 레벨 생성 완료! (실패: ${failedLevels.length}개)`
      );
    } catch (err) {
      if ((err as Error).message === 'cancelled') {
        // Save any pending levels before cancelling
        if (pendingLevels.length > 0) {
          await saveProductionLevels(selectedBatchId, pendingLevels);
        }
        // Update batch counts after pause
        await recalculateBatchCounts(selectedBatchId);
        flushProgressImmediate();
        setGenerationProgress(prev => ({
          ...prev,
          status: 'paused',
          completed_levels: completedCount,
        }));
        addNotification('info', `생성 일시 정지됨 (${completedCount}개 저장됨)`);
      } else {
        flushProgressImmediate();
        setGenerationProgress(prev => ({
          ...prev,
          status: 'error',
          last_error: (err as Error).message,
        }));
        addNotification('error', `생성 오류: ${(err as Error).message}`);
      }
    } finally {
      setIsGenerating(false);
    }
  }, [selectedBatchId, addNotification, useValidatedGeneration, validationConfig, useCoreBots, updateProgressThrottled, flushProgressImmediate, templateAssignments, autoAssignTemplates]);

  // 진행 상태를 idle로 리셋 (UI에서 프로그레스 바 사라짐)
  const resetGenerationProgress = useCallback(() => {
    const idle: ProductionGenerationProgress = {
      status: 'idle',
      total_sets: 0,
      completed_sets: 0,
      current_set_index: 0,
      total_levels: 0,
      completed_levels: 0,
      current_level: 0,
      elapsed_ms: 0,
      estimated_remaining_ms: 0,
      started_at: '',
      failed_levels: [],
      checkpoint_interval_levels: 50,
    };
    progressRef.current = idle;
    setGenerationProgress(idle);
  }, []);

  // Cancel generation
  const handleCancelGeneration = useCallback(() => {
    abortControllerRef.current?.abort();
    setIsGenerating(false);
    resetGenerationProgress();
    addNotification('info', '생성 중지됨');
  }, [addNotification, resetGenerationProgress]);

  // Delete batch
  const handleDeleteBatch = useCallback(async (batchId: string) => {
    if (!confirm('이 배치를 삭제하시겠습니까? 모든 레벨이 삭제됩니다.')) {
      return;
    }

    try {
      // 현재 생성 중이면 먼저 abort
      if (isGenerating && selectedBatchId === batchId) {
        abortControllerRef.current?.abort();
        setIsGenerating(false);
      }
      await deleteProductionBatch(batchId);
      setBatches(prev => prev.filter(b => b.id !== batchId));
      if (selectedBatchId === batchId) {
        setSelectedBatchId(batches.find(b => b.id !== batchId)?.id || null);
        // 삭제된 배치의 진행 상태 제거
        resetGenerationProgress();
      }
      addNotification('success', '배치 삭제됨');
    } catch {
      addNotification('error', '배치 삭제 실패');
    }
  }, [selectedBatchId, batches, addNotification, isGenerating, resetGenerationProgress]);

  // Rename batch state
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState('');

  // Rename batch
  const handleRenameBatch = useCallback(async () => {
    if (!selectedBatchId || !renameValue.trim()) {
      return;
    }

    try {
      await renameProductionBatch(selectedBatchId, renameValue.trim());
      setBatches(prev => prev.map(b =>
        b.id === selectedBatchId ? { ...b, name: renameValue.trim() } : b
      ));
      setIsRenaming(false);
      addNotification('success', '배치 이름 변경됨');
    } catch (err) {
      addNotification('error', '배치 이름 변경 실패');
    }
  }, [selectedBatchId, renameValue, addNotification]);

  // Start rename mode
  const startRename = useCallback(() => {
    const batch = batches.find(b => b.id === selectedBatchId);
    if (batch) {
      setRenameValue(batch.name);
      setIsRenaming(true);
    }
  }, [batches, selectedBatchId]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        로딩 중...
      </div>
    );
  }

  const selectedBatch = batches.find(b => b.id === selectedBatchId);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-white">
            프로덕션 레벨 관리
          </h2>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowGimmickInfo(true)}
            title="필수 기믹 스테이지 정보"
          >
            📋 기믹 언락 정보
          </Button>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleCreateBatch('sawtooth')}
          >
            + 새 1500 배치 (톱니바퀴)
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleCreateBatch('linear')}
          >
            + 새 1500 배치 (선형)
          </Button>
        </div>
      </div>

      {/* 기믹 언락 정보 모달 */}
      {showGimmickInfo && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-6 max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-bold text-white">📋 필수 기믹 언락 스테이지</h3>
              <button
                onClick={() => setShowGimmickInfo(false)}
                className="text-gray-400 hover:text-white text-2xl"
              >
                ×
              </button>
            </div>
            <p className="text-sm text-gray-400 mb-4">
              각 스테이지에서 해당 기믹이 처음 등장하며, 반드시 해당 기믹이 포함되어야 합니다.
            </p>
            <div className="space-y-2">
              {GIMMICK_TUTORIAL_INFO.map((info) => (
                <div
                  key={info.level}
                  className={`p-3 rounded-lg border ${
                    info.type === 'goal'
                      ? 'bg-indigo-900/30 border-indigo-600/50'
                      : 'bg-gray-700/50 border-gray-600/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl font-bold text-indigo-400 w-12">
                        {info.level}
                      </span>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-white">{info.name}</span>
                          <span className="text-xs px-2 py-0.5 rounded bg-gray-600 text-gray-300">
                            {info.gimmick}
                          </span>
                          <span className={`text-xs px-2 py-0.5 rounded ${
                            info.type === 'goal'
                              ? 'bg-indigo-600 text-indigo-100'
                              : 'bg-emerald-600 text-emerald-100'
                          }`}>
                            {info.type === 'goal' ? '목표 타일' : '장애물'}
                          </span>
                        </div>
                        <p className="text-sm text-gray-400 mt-0.5">{info.description}</p>
                      </div>
                    </div>
                    <div className="text-yellow-400 text-sm whitespace-nowrap">
                      {info.difficulty}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-6 pt-4 border-t border-gray-700">
              <div className="flex gap-4 text-sm text-gray-400">
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-indigo-600"></span>
                  <span>목표 타일 (goals): craft, stack</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-emerald-600"></span>
                  <span>장애물 (obstacles): ice, chain, etc.</span>
                </div>
              </div>
            </div>
            <div className="mt-4 flex justify-end">
              <Button onClick={() => setShowGimmickInfo(false)}>
                닫기
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Batch Selector */}
      {batches.length > 0 && (
        <div className="flex items-center gap-2 p-2 bg-gray-800 rounded-lg">
          <label className="text-sm text-gray-400">배치:</label>
          {isRenaming ? (
            <>
              <input
                type="text"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleRenameBatch();
                  if (e.key === 'Escape') setIsRenaming(false);
                }}
                className="flex-1 px-3 py-1 bg-gray-700 border border-indigo-500 rounded text-sm text-white focus:outline-none"
                autoFocus
              />
              <Button
                variant="primary"
                size="sm"
                onClick={handleRenameBatch}
              >
                확인
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setIsRenaming(false)}
              >
                취소
              </Button>
            </>
          ) : (
            <>
              <select
                value={selectedBatchId || ''}
                onChange={(e) => setSelectedBatchId(e.target.value)}
                className="flex-1 px-3 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
              >
                {batches.map((batch) => (
                  <option key={batch.id} value={batch.id}>
                    {batch.name} ({batch.generated_count + batch.playtest_count}/{batch.total_levels})
                  </option>
                ))}
              </select>
              {selectedBatch && (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={startRename}
                  >
                    이름변경
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={async () => {
                      try {
                        const ok = await pushBatchToServer(selectedBatch.id);
                        addNotification(ok ? 'success' : 'warning',
                          ok ? '서버(로컬 파일)에 저장됨 — 다른 브라우저에서도 접근 가능' : '저장할 배치 없음');
                      } catch (e) {
                        if (e instanceof SyncConflictError) {
                          if (window.confirm('다른 브라우저에서 이 배치가 먼저 수정됐습니다. 현재 내용으로 덮어쓸까요?')) {
                            try {
                              await pushBatchToServer(selectedBatch.id, { force: true });
                              addNotification('success', '서버에 강제 저장됨(덮어쓰기)');
                            } catch {
                              addNotification('error', '서버 저장 실패 (백엔드 확인)');
                            }
                          }
                        } else {
                          addNotification('error', '서버 저장 실패 (백엔드 확인)');
                        }
                      }
                    }}
                    title="이 배치를 로컬 파일로 저장 → 같은 컴퓨터의 다른 브라우저에서도 접근"
                  >
                    ☁️ 서버 저장
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => handleDeleteBatch(selectedBatch.id)}
                  >
                    삭제
                  </Button>
                </>
              )}
            </>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-700">
        {[
          { id: 'overview', label: '개요' },
          { id: 'generate', label: '생성' },
          { id: 'verify', label: '검증' },
          { id: 'test', label: '테스트' },
          { id: 'playtest', label: '플레이테스트' },
          { id: 'review', label: '검토' },
          { id: 'export', label: '내보내기' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as DashboardTab)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-indigo-400 border-b-2 border-indigo-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-[400px]">
        {activeTab === 'overview' && stats && selectedBatch && selectedBatchId && (
          <OverviewTab stats={stats} batch={selectedBatch} batchId={selectedBatchId} />
        )}

        {activeTab === 'generate' && selectedBatch && (
          <GenerateTab
            batch={selectedBatch}
            progress={generationProgress}
            isGenerating={isGenerating}
            onStart={handleStartGeneration}
            onCancel={handleCancelGeneration}
            onResetProgress={resetGenerationProgress}
            templateAssignments={templateAssignments}
            onTemplateAssignmentsChange={setTemplateAssignments}
            autoAssignTemplates={autoAssignTemplates}
            onAutoAssignChange={setAutoAssignTemplates}
            useValidation={useValidatedGeneration}
            onUseValidationChange={setUseValidatedGeneration}
            validationConfig={validationConfig}
            onValidationConfigChange={setValidationConfig}
            useCoreBots={useCoreBots}
            onUseCoreBotsChange={setUseCoreBots}
            useReverseGen={useReverseGen}
            onUseReverseGenChange={setUseReverseGen}
            tileTypeProfile={tileTypeProfile}
            onTileTypeProfileChange={setTileTypeProfile}
            sizeDiversityStartLevel={sizeDiversityStartLevel}
            onSizeDiversityStartLevelChange={setSizeDiversityStartLevel}
            rlSkillMean={rlSkillMean}
            onRlSkillMeanChange={setRlSkillMean}
          />
        )}

        {activeTab === 'verify' && selectedBatchId && (
          <div className="bg-gray-800 rounded-lg p-4">
            <BatchVerifyPanel
              batchId={selectedBatchId}
              onComplete={() => setActiveTab('review')}
              onStatsUpdate={async () => {
                const newStats = await calculateProductionStats(selectedBatchId);
                setStats(newStats);
              }}
            />
          </div>
        )}

        {activeTab === 'test' && selectedBatchId && (
          <TestTab
            batchId={selectedBatchId}
            isGenerating={isGenerating}
            tileTypeProfile={tileTypeProfile}
            rlSkillMean={rlSkillMean}
            onStatsUpdate={async () => {
              const newStats = await calculateProductionStats(selectedBatchId);
              setStats(newStats);
            }}
          />
        )}

        {activeTab === 'playtest' && selectedBatchId && (
          <PlaytestTab
            batchId={selectedBatchId}
            onLevelSelect={onLevelSelect}
          />
        )}

        {activeTab === 'review' && selectedBatchId && (
          <ReviewTab
            batchId={selectedBatchId}
            onLevelSelect={onLevelSelect}
            onStatsUpdate={async () => {
              const newStats = await calculateProductionStats(selectedBatchId);
              setStats(newStats);
            }}
          />
        )}

        {activeTab === 'export' && selectedBatchId && stats && selectedBatch && (
          <ProductionExport
            batchId={selectedBatchId}
            batchName={selectedBatch.name}
            stats={stats}
          />
        )}

        {!selectedBatch && !isLoading && (
          <div className="flex flex-col items-center justify-center h-64 text-gray-500">
            <p>배치가 없습니다.</p>
            <p className="text-sm mt-2">위의 버튼으로 새 1500 레벨 배치를 생성하세요.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// Overview Tab Component
function OverviewTab({ stats, batch, batchId }: { stats: ProductionStats; batch: ProductionBatch; batchId: string }) {
  const { addNotification } = useUIStore();
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [isLoadingLevels, setIsLoadingLevels] = useState(false);
  const [wrongTileCountLevels, setWrongTileCountLevels] = useState<ProductionLevel[]>([]);
  const [isRegeneratingTileCount, setIsRegeneratingTileCount] = useState(false);
  const [tileCountRegenProgress, setTileCountRegenProgress] = useState({ current: 0, total: 0 });

  // Load levels for chart
  useEffect(() => {
    async function loadLevels() {
      if (!batchId) return;
      setIsLoadingLevels(true);
      try {
        const loadedLevels = await getProductionLevelsByBatch(batchId);
        setLevels(loadedLevels);

        // Check for levels with wrong useTileCount
        const wrongLevels = findLevelsWithWrongTileCount(loadedLevels);
        setWrongTileCountLevels(wrongLevels);
      } catch (err) {
        console.error('Failed to load levels for chart:', err);
      } finally {
        setIsLoadingLevels(false);
      }
    }
    loadLevels();
  }, [batchId]);

  // Batch regenerate levels with wrong useTileCount
  const handleBatchRegenerateTileCount = async () => {
    if (wrongTileCountLevels.length === 0) return;

    setIsRegeneratingTileCount(true);
    setTileCountRegenProgress({ current: 0, total: wrongTileCountLevels.length });

    const currentBatch = await getProductionBatch(batchId);
    if (!currentBatch) {
      addNotification('error', '배치를 찾을 수 없습니다');
      setIsRegeneratingTileCount(false);
      return;
    }

    let successCount = 0;
    let failCount = 0;

    for (let i = 0; i < wrongTileCountLevels.length; i++) {
      const level = wrongTileCountLevels[i];
      const levelNumber = level.meta.level_number;
      setTileCountRegenProgress({ current: i + 1, total: wrongTileCountLevels.length });

      try {
        const targetDifficulty = level.meta.target_difficulty;
        const gimmickIntensity = Math.min(targetDifficulty, levelNumber / 500);

        // Pattern/symmetry selection matching handleRegenerateLevel logic
        const isEarlyLevel = levelNumber <= 30;
        const isSpecialShape = levelNumber % 10 === 9;
        const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;

        // Pattern type: 항상 aesthetic 사용 (64개 패턴 중 선택)
        const patternType: 'aesthetic' = 'aesthetic';

        const symmetryRoll = Math.random();
        let symmetryMode: 'none' | 'horizontal' | 'vertical' | 'both';
        if (isEarlyLevel) {
          symmetryMode = symmetryRoll < 0.25 ? 'horizontal' : symmetryRoll < 0.50 ? 'vertical' : 'both';
        } else if (isSpecialShape) {
          symmetryMode = symmetryRoll < 0.30 ? 'none' : symmetryRoll < 0.65 ? 'horizontal' : 'vertical';
        } else if (isBossLevel) {
          symmetryMode = symmetryRoll < 0.20 ? 'horizontal' : symmetryRoll < 0.40 ? 'vertical' : 'both';
        } else {
          symmetryMode = symmetryRoll < 0.05 ? 'none' : symmetryRoll < 0.40 ? 'horizontal' : symmetryRoll < 0.75 ? 'vertical' : 'both';
        }

        // Grid size
        let gridSize: [number, number] = [7, 7];
        if (isBossLevel && targetDifficulty > 0.3) {
          gridSize = [8, 8];
        } else if (!isEarlyLevel && Math.random() < 0.3) {
          gridSize = [8, 8];
        }

        // Layers
        let minLayers = 2;
        let maxLayers = Math.min(10, 3 + Math.floor(targetDifficulty * 7));
        if (isEarlyLevel) { minLayers = 2; maxLayers = Math.min(4, maxLayers); }
        else if (isBossLevel) { minLayers = Math.max(3, Math.floor(2 + targetDifficulty * 2)); maxLayers = Math.min(10, 4 + Math.floor(targetDifficulty * 6)); }

        // Goal selection
        let goalDirections: Array<'s' | 'n' | 'e' | 'w'>;
        if (symmetryMode === 'both' || symmetryMode === 'vertical') {
          goalDirections = Math.random() < 0.7 ? ['s', 'n'] : ['e', 'w'];
        } else if (symmetryMode === 'horizontal') {
          goalDirections = Math.random() < 0.7 ? ['e', 'w'] : ['s', 'n'];
        } else {
          goalDirections = ['s', 'n', 'e', 'w'];
        }
        const goalDirection = goalDirections[Math.floor(Math.random() * goalDirections.length)];
        const goalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];

        const result = await generateLevel(
          {
            target_difficulty: targetDifficulty,
            grid_size: isBossLevel ? [7, 7] : gridSize, // 보스: 선언 최대 8 (디바이스 제약)
            min_layers: isBossLevel ? 5 : minLayers,
            max_layers: isBossLevel ? 6 : maxLayers,
            tile_types: undefined, // 백엔드에서 level_number 기반 자동 선택
            obstacle_types: [],
            goals: [{
              type: goalType,
              direction: goalDirection,
              count: Math.max(2, Math.floor(3 + targetDifficulty * 2))
            }],
            symmetry_mode: symmetryMode,
            pattern_type: patternType,
            // [보스 생성기] 레시피 로테이션 + 그리드 캡 (재생성도 동일 적용)
            boss_mode: isBossLevel || undefined,
          },
          {
            auto_select_gimmicks: true,
            available_gimmicks: ['craft', 'stack', 'chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
            gimmick_intensity: gimmickIntensity,
            gimmick_unlock_levels: currentBatch.gimmick_unlock_levels || PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
            level_number: levelNumber,
          }
        );

        // Save regenerated level
        applyProductionTileVisuals(result.level_json, levelNumber);  // 고정=명시 relabel / 순수t0=시드 베이크
        await saveProductionLevels(batchId, [{
          meta: {
            ...level.meta,
            generated_at: new Date().toISOString(),
            actual_difficulty: result.actual_difficulty,
            grade: result.grade as DifficultyGrade,
            bot_clear_rates: undefined,
            match_score: undefined,
            status_updated_at: new Date().toISOString(),
            regen_attempts: (level.meta.regen_attempts || 0) + 1,
          },
          level_json: result.level_json,
        }]);

        successCount++;
      } catch (err) {
        console.error(`Failed to regenerate level ${levelNumber}:`, err);
        failCount++;
      }
    }

    // Reload levels to refresh the list
    const loadedLevels = await getProductionLevelsByBatch(batchId);
    setLevels(loadedLevels);
    const newWrongLevels = findLevelsWithWrongTileCount(loadedLevels);
    setWrongTileCountLevels(newWrongLevels);

    setIsRegeneratingTileCount(false);
    addNotification('success', `타일 종류 수 재생성 완료: ${successCount}개 성공, ${failCount}개 실패`);
  };

  return (
    <div className="space-y-6">
      {/* Progress Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="생성 완료" value={batch.generated_count + batch.playtest_count} total={batch.total_levels} />
        <StatCard label="플레이테스트" value={stats.playtest_progress.completed} total={stats.playtest_progress.total_required} />
        <StatCard label="승인됨" value={stats.by_status.approved} total={batch.total_levels} color="green" />
        <StatCard label="거부/수정필요" value={stats.by_status.rejected + stats.by_status.needs_rework} color="red" />
      </div>

      {/* Grade Distribution */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">등급 분포</h3>
        <div className="flex gap-2">
          {(['S', 'A', 'B', 'C', 'D'] as const).map((grade) => (
            <div key={grade} className="flex-1 text-center">
              <div className={`text-lg font-bold ${getGradeColor(grade)}`}>
                {stats.by_grade[grade]}
              </div>
              <div className="text-xs text-gray-400">{grade}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Quality Metrics */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">품질 지표</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-gray-400">평균 매치 점수</div>
            <div className="text-white font-medium">{stats.quality_metrics.avg_match_score.toFixed(1)}%</div>
          </div>
          <div>
            <div className="text-gray-400">평균 재미 점수</div>
            <div className="text-white font-medium">{stats.quality_metrics.avg_fun_rating.toFixed(1)}/5</div>
          </div>
          <div>
            <div className="text-gray-400">거부율</div>
            <div className="text-white font-medium">{(stats.quality_metrics.rejection_rate * 100).toFixed(1)}%</div>
          </div>
          <div>
            <div className="text-gray-400">출시 대기</div>
            <div className="text-white font-medium">{stats.estimated_completion.ready_for_export}개</div>
          </div>
        </div>
      </div>

      {/* Status Timeline */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">상태별 현황</h3>
        <div className="space-y-2">
          <StatusBar label="생성됨" count={stats.by_status.generated} total={batch.total_levels} color="blue" />
          <StatusBar label="플레이테스트 대기" count={stats.by_status.playtest_queue} total={batch.total_levels} color="yellow" />
          <StatusBar label="승인됨" count={stats.by_status.approved} total={batch.total_levels} color="green" />
          <StatusBar label="내보내기 완료" count={stats.by_status.exported} total={batch.total_levels} color="purple" />
        </div>
      </div>

      {/* Tile Count Warning & Batch Regenerate */}
      {wrongTileCountLevels.length > 0 && (
        <div className="p-4 bg-yellow-900/30 border border-yellow-600 rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-yellow-500 text-lg">⚠️</span>
              <h3 className="text-sm font-medium text-yellow-400">
                타일 종류 수 오류 감지: {wrongTileCountLevels.length}개 레벨
              </h3>
            </div>
            <Button
              onClick={handleBatchRegenerateTileCount}
              disabled={isRegeneratingTileCount}
              variant="warning"
              size="sm"
            >
              {isRegeneratingTileCount
                ? `재생성 중... (${tileCountRegenProgress.current}/${tileCountRegenProgress.total})`
                : `일괄 재생성 (${wrongTileCountLevels.length}개)`}
            </Button>
          </div>
          <div className="text-xs text-yellow-400/80 mb-2">
            이 레벨들은 fallback 생성으로 인해 useTileCount가 잘못 설정되었습니다.
            일괄 재생성을 통해 레벨 번호에 맞는 올바른 타일 종류 수로 수정됩니다.
          </div>
          <div className="flex flex-wrap gap-1 max-h-20 overflow-y-auto">
            {wrongTileCountLevels.slice(0, 50).map(level => {
              const validation = validateUseTileCount(
                level.meta.level_number,
                level.level_json?.useTileCount ?? 0,
                level.meta.target_difficulty
              );
              const rangeStr = validation.range.min === validation.range.max
                ? `${validation.range.min}`
                : `${validation.range.min}-${validation.range.max}`;
              return (
                <span
                  key={level.meta.level_number}
                  className="inline-flex items-center gap-1 px-2 py-0.5 bg-yellow-600/20 rounded text-xs text-yellow-300"
                  title={`현재: ${level.level_json?.useTileCount}, 허용 범위: ${rangeStr}, 레벨 기반: ${validation.levelBased}`}
                >
                  Lv.{level.meta.level_number}
                  <span className="text-yellow-500">
                    ({level.level_json?.useTileCount}→{rangeStr})
                  </span>
                </span>
              );
            })}
            {wrongTileCountLevels.length > 50 && (
              <span className="text-yellow-400/60 text-xs">
                ... 외 {wrongTileCountLevels.length - 50}개
              </span>
            )}
          </div>
        </div>
      )}

      {/* Level Distribution Chart */}
      {isLoadingLevels ? (
        <div className="p-4 bg-gray-800 rounded-lg text-center text-gray-400">
          레벨 데이터 로딩 중...
        </div>
      ) : levels.length > 0 ? (
        <LevelDistributionChart
          levels={levels}
          totalLevels={batch.total_levels}
        />
      ) : (
        <div className="p-4 bg-gray-800 rounded-lg text-center text-gray-400">
          레벨 데이터가 없습니다.
        </div>
      )}
    </div>
  );
}

// Generate Tab Component
function GenerateTab({
  batch,
  progress,
  isGenerating,
  onStart,
  onCancel,
  onResetProgress,
  templateAssignments,
  onTemplateAssignmentsChange,
  autoAssignTemplates,
  onAutoAssignChange,
  useValidation,
  onUseValidationChange,
  validationConfig,
  onValidationConfigChange,
  useCoreBots,
  onUseCoreBotsChange,
  useReverseGen,
  onUseReverseGenChange,
  tileTypeProfile,
  onTileTypeProfileChange,
  sizeDiversityStartLevel,
  onSizeDiversityStartLevelChange,
  rlSkillMean,
  onRlSkillMeanChange,
}: {
  batch: ProductionBatch;
  progress: ProductionGenerationProgress;
  isGenerating: boolean;
  onStart: (config: PlaytestQueueConfig) => void;
  onCancel: () => void;
  onResetProgress?: () => void;
  templateAssignments: Record<number, string>;
  onTemplateAssignmentsChange: (next: Record<number, string>) => void;
  autoAssignTemplates: boolean;
  onAutoAssignChange: (v: boolean) => void;
  useValidation: boolean;
  onUseValidationChange: (value: boolean) => void;
  validationConfig: { max_retries: number; tolerance: number; simulation_iterations: number };
  onValidationConfigChange: (config: { max_retries: number; tolerance: number; simulation_iterations: number }) => void;
  useCoreBots: boolean;
  onUseCoreBotsChange: (value: boolean) => void;
  useReverseGen: boolean;
  onUseReverseGenChange: (value: boolean) => void;
  tileTypeProfile: string;
  onTileTypeProfileChange: (value: string) => void;
  sizeDiversityStartLevel: number;
  onSizeDiversityStartLevelChange: (value: number) => void;
  rlSkillMean: number;
  onRlSkillMeanChange: (value: number) => void;
}) {
  const [playtestStrategy, setPlaytestStrategy] = useState<PlaytestStrategy>('sample_boss');

  const progressPercent = progress.total_levels > 0
    ? (progress.completed_levels / progress.total_levels) * 100
    : 0;

  const formatTime = (ms: number) => {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    if (hours > 0) {
      return `${hours}시간 ${minutes % 60}분`;
    }
    return `${minutes}분 ${seconds % 60}초`;
  };

  return (
    <div className="space-y-4">
      {/* Configuration */}
      {!isGenerating && progress.status !== 'generating' && (
        <div className="p-4 bg-gray-800 rounded-lg space-y-4">
          <h3 className="text-sm font-medium text-white">생성 설정</h3>

          {/* Playtest Strategy */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">플레이테스트 샘플링</label>
            <select
              value={playtestStrategy}
              onChange={(e) => setPlaytestStrategy(e.target.value as PlaytestStrategy)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            >
              <option value="sample_boss">보스 레벨만 (10의 배수, ~150개)</option>
              <option value="sample_10">10개당 1개 (~150개)</option>
              <option value="tutorial">튜토리얼 레벨만 (11개)</option>
              <option value="grade_sample">등급별 샘플 (~300개)</option>
              <option value="low_match">매치 점수 낮은 레벨 (~300개)</option>
              <option value="all">전체 (1500개)</option>
            </select>
          </div>

          {/* 타일 종류 분포(V) 프로파일 */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">타일 종류 분포(V)</label>
            <select
              value={tileTypeProfile}
              onChange={(e) => onTileTypeProfileChange(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            >
              <option value="baseline">기본 (baseline)</option>
              <option value="hard_steep">어려움 (hard_steep · 11-30=8 / 31-60=10 / 끝=13)</option>
            </select>
            {/* V 분포 미리보기 그래프 (y=타일종류수 0~15, x=레벨 1~1500) */}
            <div className="mt-2 p-2 bg-gray-900/50 rounded">
              <TileTypeProfileGraph profile={tileTypeProfile} />
              <div className="flex gap-3 mt-1 text-[10px] text-gray-400">
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-blue-500" />선택 ({tileTypeProfile})</span>
                {tileTypeProfile !== 'baseline' && (
                  <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-gray-500" style={{ borderTop: '1px dashed' }} />baseline</span>
                )}
              </div>
            </div>
          </div>

          {/* Validation Settings */}
          <div className="p-3 bg-gray-700/50 rounded-lg space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-sm text-white">난이도 검증 기반 생성</label>
              <button
                onClick={() => onUseValidationChange(!useValidation)}
                className={`w-12 h-6 rounded-full transition-colors ${
                  useValidation ? 'bg-green-500' : 'bg-gray-600'
                }`}
              >
                <div className={`w-5 h-5 bg-white rounded-full transition-transform ${
                  useValidation ? 'translate-x-6' : 'translate-x-0.5'
                }`} />
              </button>
            </div>
            {useValidation && (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">최대 재시도</span>
                  <select
                    value={validationConfig.max_retries}
                    onChange={(e) => onValidationConfigChange({
                      ...validationConfig,
                      max_retries: parseInt(e.target.value)
                    })}
                    className="px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-xs"
                  >
                    <option value={2}>2회</option>
                    <option value={3}>3회</option>
                    <option value={5}>5회</option>
                  </select>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">검증 속도</span>
                  <select
                    value={validationConfig.simulation_iterations}
                    onChange={(e) => onValidationConfigChange({
                      ...validationConfig,
                      simulation_iterations: parseInt(e.target.value)
                    })}
                    className="px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-xs"
                  >
                    <option value={0}>🚫 안함 (즉시 생성)</option>
                    <option value={10}>⚡ 빠름 (10회)</option>
                    <option value={20}>⚖️ 보통 (20회)</option>
                    <option value={50}>🎯 정밀 (50회)</option>
                  </select>
                </div>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-gray-400">봇 모드</span>
                  <select
                    value={useCoreBots ? 'core' : 'full'}
                    onChange={(e) => onUseCoreBotsChange(e.target.value === 'core')}
                    className="px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-xs"
                  >
                    <option value="core">⚡ 코어 3봇 (빠름)</option>
                    <option value="full">🎯 전체 5봇 (정밀)</option>
                  </select>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  검증 실패시 자동 재생성하여 클리어 가능한 레벨만 생성합니다.
                  {validationConfig.simulation_iterations === 0 && (
                    <span className="block text-yellow-400 mt-1">시뮬레이션 없이 빠르게 생성합니다 (캘리브레이션만 적용).</span>
                  )}
                  {useCoreBots && validationConfig.simulation_iterations > 0 && (
                    <span className="block text-blue-400 mt-1">코어 3봇 (average/expert/optimal)으로 ~40% 빠른 검증.</span>
                  )}
                </p>
              </div>
            )}
          </div>

          {/* [역생성] 솔버블 보장 모드 토글 */}
          <div className="bg-gray-700/40 rounded-lg p-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={useReverseGen}
                onChange={(e) => onUseReverseGenChange(e.target.checked)} />
              <span className="text-sm text-white font-medium">🧩 역생성 (솔버블 보장)</span>
            </label>
            <p className="text-xs text-gray-400 mt-1">
              켜면 witness-peeling 타입배정으로 <span className="text-emerald-400">솔버블·÷3을 구조적으로 보장</span>합니다.
              <span className="text-emerald-400">ice/grass/chain/link 기믹은 포함</span>(봇클리어로 검증)되며,
              적용된 레벨은 리스트에 <span className="text-emerald-400">🧩역</span> 배지로 표시됩니다.
              {useReverseGen && (
                <span className="block text-yellow-400 mt-1">
                  ⚠️ craft/stack 컨테이너와 비결정 기믹(frog/teleport/bomb/curtain)은 제외됩니다.
                  기믹이 솔버블을 깨면 자동으로 단계적 제거(chain/link→ice/grass→plain) 후 봇클리어 확정된 것만 적용.
                </span>
              )}
            </p>
          </div>

          {/* [B] 층별 그리드 크기 다양화 시작 레벨 */}
          <div className="bg-gray-700/40 rounded-lg p-3">
            <label className="flex items-center gap-2">
              <span className="text-sm text-white font-medium">🎚️ 층별 크기 다양화 시작 레벨</span>
              <input
                type="number"
                min={0}
                value={sizeDiversityStartLevel}
                onChange={(e) => onSizeDiversityStartLevelChange(Math.max(0, parseInt(e.target.value, 10) || 0))}
                className="w-20 px-2 py-1 rounded bg-gray-800 text-white text-sm border border-gray-600"
              />
            </label>
            <p className="text-xs text-gray-400 mt-1">
              이 레벨 <span className="text-emerald-400">이상</span>부터 각 층의 채움 모양 크기를
              <span className="text-emerald-400"> 랜덤(최소 3×3~그리드, 인접층 회피)</span>으로 다양화하고 중앙 배치 →
              스택 실루엣 다양화. <span className="text-yellow-400">0이면 미적용</span>(튜토리얼/초반은 단순 유지 권장, 기본 101).
              레이어 col/row(교대값)는 유지되어 게임과 정합.
            </p>
          </div>

          {/* [RL 난이도 기준 스킬] 전체 난이도 조절 슬라이더 */}
          <div className="bg-gray-700/40 rounded-lg p-3">
            <label className="flex items-center justify-between gap-2">
              <span className="text-sm text-white font-medium">🎮 난이도 기준 실력 (순차검증 RL)</span>
              <span className="text-sm text-emerald-400 font-mono tabular-nums">{rlSkillMean.toFixed(2)}</span>
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={rlSkillMean}
              onChange={(e) => onRlSkillMeanChange(parseFloat(e.target.value))}
              className="w-full mt-2 accent-blue-500"
            />
            <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
              <span>0 = 최고 초보봇 (게임 쉽게)</span>
              <span>기본 0.47</span>
              <span>고수봇 = 1 (게임 어렵게)</span>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              순차검증 RL이 <span className="text-emerald-400">이 실력 기준으로 클리어율 예측</span> → 통과 판정.
              <span className="text-emerald-400"> 높이면</span> 어려운 레벨도 "고수는 깬다"고 통과(게임 전체 난이도↑),
              <span className="text-yellow-400"> 낮추면</span> 쉬운 레벨만 통과(난이도↓). 초기 생성값은 안 바뀌고 <b>검증 기준</b>만 이동.
            </p>
          </div>

          {/* 레벨 템플릿 할당 패널 */}
          <TemplateAssignmentPanel
            batch={batch}
            assignments={templateAssignments}
            onAssignmentsChange={onTemplateAssignmentsChange}
            autoAssign={autoAssignTemplates}
            onAutoAssignChange={onAutoAssignChange}
          />

          {/* Summary */}
          <div className="text-sm text-gray-400">
            <div>총 {batch.total_levels}개 레벨 생성</div>
            <div>난이도 범위: {(batch.difficulty_start * 100).toFixed(0)}% ~ {(batch.difficulty_end * 100).toFixed(0)}%</div>
            <div>패턴: {batch.use_sawtooth ? '톱니바퀴 (보스/휴식 사이클)' : '선형 증가'}</div>
            <div className="text-blue-400">⚡ 병렬 생성: 10개 동시 처리</div>
            {useValidation && (
              <div className="text-green-400">✓ 난이도 검증 활성화 (최대 {validationConfig.max_retries}회 재시도{validationConfig.simulation_iterations === 0 ? ', 시뮬레이션 없음' : ''}{useCoreBots ? ', 코어 3봇' : ', 전체 5봇'})</div>
            )}
          </div>

          <Button
            onClick={() => onStart({ strategy: playtestStrategy })}
            className="w-full"
          >
            {useValidation ? '검증 기반 생성 시작' : '생성 시작'} ({batch.total_levels}개)
          </Button>
        </div>
      )}

      {/* Progress - Enhanced Dashboard */}
      {(isGenerating || progress.status !== 'idle') && (() => {
        // 평균 속도 계산 (레벨/분)
        const avgSpeed = progress.elapsed_ms > 0
          ? (progress.completed_levels / (progress.elapsed_ms / 60000))
          : 0;

        // 세트별 진행률 계산 (현재 세트 주변 5개 표시)
        const SETS_TO_SHOW = 7;
        const currentSetIndex = progress.current_set_index;
        const startSetIndex = Math.max(0, currentSetIndex - 2);
        const setProgresses: { index: number; completed: boolean; active: boolean; percent: number }[] = [];

        for (let i = 0; i < SETS_TO_SHOW && startSetIndex + i < progress.total_sets; i++) {
          const setIndex = startSetIndex + i;
          const levelsPerSet = 10;
          const completedInSet = Math.max(0, Math.min(levelsPerSet,
            progress.completed_levels - (setIndex * levelsPerSet)));

          setProgresses.push({
            index: setIndex,
            completed: completedInSet >= levelsPerSet,
            active: setIndex === currentSetIndex,
            percent: (completedInSet / levelsPerSet) * 100,
          });
        }

        return (
          <div className="p-4 bg-gray-800 rounded-lg space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-sm font-medium text-white flex items-center gap-2">
                📊 생성 진행률
              </h3>
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded ${
                  progress.status === 'generating' ? 'bg-indigo-900/50 text-indigo-300' :
                  progress.status === 'completed' ? 'bg-green-900/50 text-green-300' :
                  progress.status === 'paused' ? 'bg-yellow-900/50 text-yellow-300' :
                  progress.status === 'error' ? 'bg-red-900/50 text-red-300' : 'bg-gray-700 text-gray-300'
                }`}>
                  {progress.status === 'generating' ? '생성 중...' :
                   progress.status === 'completed' ? '완료' :
                   progress.status === 'paused' ? '일시 정지' :
                   progress.status === 'error' ? '오류' : '대기'}
                </span>
                {progress.status !== 'generating' && !isGenerating && onResetProgress && (
                  <button onClick={onResetProgress}
                    className="text-[10px] px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                    title="진행 상태 지우기">
                    ✕ 닫기
                  </button>
                )}
              </div>
            </div>

            {/* Main Progress Bar */}
            <div>
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>완료: {progress.completed_levels} / {progress.total_levels} 레벨</span>
                <span className="font-mono">{progressPercent.toFixed(1)}%</span>
              </div>
              <div className="h-4 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-[width] duration-500 ease-linear ${
                    progress.status === 'error' ? 'bg-red-500' :
                    progress.status === 'completed' ? 'bg-green-500' :
                    'bg-gradient-to-r from-indigo-500 to-purple-500'
                  }`}
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-4 gap-2">
              <div className="p-2 bg-gray-700/50 rounded text-center">
                <div className="text-xs text-gray-400">⏱️ 경과</div>
                <div className="text-sm font-medium text-white">{formatTime(progress.elapsed_ms)}</div>
              </div>
              <div className="p-2 bg-gray-700/50 rounded text-center">
                <div className="text-xs text-gray-400">⏳ 남은 시간</div>
                <div className="text-sm font-medium text-white">{formatTime(progress.estimated_remaining_ms)}</div>
              </div>
              <div className="p-2 bg-gray-700/50 rounded text-center">
                <div className="text-xs text-gray-400">📈 평균 속도</div>
                <div className="text-sm font-medium text-blue-300">{avgSpeed.toFixed(1)}/분</div>
              </div>
              <div className="p-2 bg-gray-700/50 rounded text-center">
                <div className="text-xs text-gray-400">📦 현재 세트</div>
                <div className="text-sm font-medium text-purple-300">{progress.current_set_index + 1}/{progress.total_sets}</div>
              </div>
            </div>

            {/* Set Progress Mini Bars */}
            <div>
              <div className="text-xs text-gray-400 mb-2">세트별 진행:</div>
              <div className="flex gap-1">
                {setProgresses.map((set) => (
                  <div key={set.index} className="flex-1">
                    <div
                      className={`h-6 rounded overflow-hidden ${
                        set.active ? 'ring-2 ring-indigo-400' : ''
                      }`}
                    >
                      <div
                        className={`h-full transition-all ${
                          set.completed ? 'bg-green-500' :
                          set.active ? 'bg-indigo-500' :
                          set.percent > 0 ? 'bg-indigo-700' : 'bg-gray-600'
                        }`}
                        style={{ width: set.completed ? '100%' : `${set.percent}%` }}
                      />
                    </div>
                    <div className={`text-[10px] text-center mt-0.5 ${
                      set.active ? 'text-indigo-300 font-medium' : 'text-gray-500'
                    }`}>
                      {set.index + 1}
                    </div>
                  </div>
                ))}
                {progress.total_sets > startSetIndex + SETS_TO_SHOW && (
                  <div className="text-xs text-gray-500 flex items-center ml-1">...</div>
                )}
              </div>
            </div>

            {/* Failed Levels Counter */}
            {progress.failed_levels && progress.failed_levels.length > 0 && (
              <div className="p-2 bg-red-900/20 border border-red-700/30 rounded-lg">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-red-300">
                    ⚠️ 실패 레벨: {progress.failed_levels.length}개
                  </span>
                  <span className="text-xs text-red-400">
                    (재생성 예정)
                  </span>
                </div>
              </div>
            )}

            {/* Error Message */}
            {progress.last_error && (
              <div className="p-2 bg-red-900/30 border border-red-700/30 rounded text-sm text-red-400">
                오류: {progress.last_error}
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2">
              {isGenerating && (
                <Button onClick={onCancel} variant="danger" className="flex-1">
                  ⏸️ 일시 정지
                </Button>
              )}
              {progress.status === 'paused' && (
                <Button onClick={() => onStart({ strategy: playtestStrategy })} className="flex-1">
                  ▶️ 계속 생성
                </Button>
              )}
              {progress.status === 'completed' && (
                <div className="w-full p-2 bg-green-900/30 border border-green-700/30 rounded text-center text-sm text-green-300">
                  ✅ 생성 완료! 테스트 탭으로 이동하세요.
                </div>
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// Helper function to extract gimmicks from level_json
function extractGimmicksFromLevel(levelJson: LevelJSON): string[] {
  const gimmicks = new Set<string>();

  // Handle nested structure: level_json might have .map wrapper
  let data = levelJson as unknown as Record<string, unknown>;
  if (data.map && typeof data.map === 'object') {
    data = data.map as Record<string, unknown>;
  }

  const numLayers = (data.layer as number) || 8;

  // Extract gimmicks from tile types and attributes
  for (let i = 0; i < numLayers; i++) {
    const layerKey = `layer_${i}`;
    const layerData = data[layerKey] as { tiles?: Record<string, unknown[]> } | undefined;
    if (!layerData || !layerData.tiles) continue;

    for (const pos in layerData.tiles) {
      const tileData = layerData.tiles[pos];
      if (!tileData || !Array.isArray(tileData) || tileData.length === 0) continue;

      // Check tile type (tileData[0]) for craft/stack goals
      const tileType = tileData[0];
      if (typeof tileType === 'string') {
        if (tileType.startsWith('craft')) {
          gimmicks.add('craft');
        } else if (tileType.startsWith('stack')) {
          gimmicks.add('stack');
        }
      }

      // Check attribute (tileData[1]) for other gimmicks
      if (tileData.length > 1) {
        const attr = tileData[1];
        // Filter out tile types (t0, t1, t2, etc.) - only match exact patterns like t0, t1, t2...
        // Don't filter 'teleport' which also starts with 't'
        if (attr && typeof attr === 'string' && !attr.match(/^t\d+$/)) {
          // Normalize gimmick names:
          // - link_e, link_w, link_n, link_s → link
          // - ice_1, ice_2, ice_3 → ice
          // - curtain_open, curtain_close → curtain
          // - grass_1, grass_2 → grass
          let baseName = attr;
          if (attr.startsWith('link_')) {
            baseName = 'link';
          } else if (attr.startsWith('curtain_')) {
            baseName = 'curtain';
          } else {
            // Remove numeric suffixes like ice_1, grass_2
            baseName = attr.replace(/_\d+$/, '');
          }
          gimmicks.add(baseName);
        }
      }
    }
  }

  return Array.from(gimmicks);
}

// Gimmick display names in Korean
const GIMMICK_NAMES: Record<string, string> = {
  chain: '체인',
  ice: '얼음',
  frog: '개구리',
  grass: '잔디',
  link: '링크',
  bomb: '폭탄',
  curtain: '커튼',
  teleport: '텔레포트',
  unknown: '???',
  craft: '생성기',
  stack: '스택',
};

// Gimmick colors for display
const GIMMICK_COLORS: Record<string, string> = {
  chain: 'bg-yellow-600',
  ice: 'bg-blue-400',
  frog: 'bg-green-500',
  grass: 'bg-green-700',
  link: 'bg-purple-500',
  bomb: 'bg-red-500',
  curtain: 'bg-gray-500',
  teleport: 'bg-indigo-500',
  unknown: 'bg-gray-600',
  craft: 'bg-orange-500',
  stack: 'bg-pink-500',
};

// Test Tab Component - 레벨 테스트 (수동/자동)
function TestTab({
  batchId,
  isGenerating,
  onStatsUpdate,
  tileTypeProfile,
  rlSkillMean,
}: {
  batchId: string;
  isGenerating?: boolean;
  onStatsUpdate: () => void;
  tileTypeProfile: string;
  rlSkillMean: number;
}) {
  const { addNotification } = useUIStore();
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedLevel, setSelectedLevel] = useState<ProductionLevel | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [filter, setFilter] = useState<LevelStatus | 'all' | 'low_match' | 'untested'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Test mode: manual (play), auto_single (bot sim for selected), auto_batch (batch bot sim)
  const [testMode, setTestMode] = useState<'manual' | 'auto_single' | 'auto_batch'>('manual');

  // Auto test state
  const [isAutoTesting, setIsAutoTesting] = useState(false);
  const [autoTestResult, setAutoTestResult] = useState<{
    match_score: number;
    autoplay_grade: string;
    balance_status: string;
    bot_stats: { profile: string; clear_rate: number; target_clear_rate: number }[];
    recommendations: string[];
    // [v16] RL 통합 — 수동테스트도 예측 유저 클리어율 1개로 표시
    predicted_clear_rate?: number;
    target_clear_rate?: number;
    clear_rate_gap?: number;
    rl_classification?: string;
  } | null>(null);
  const [autoTestIterations, setAutoTestIterations] = useState(100);

  // Sequential auto process state (test → regenerate if failed → repeat until pass)
  const [isSequentialProcessing, setIsSequentialProcessing] = useState(false);
  const [sequentialProgress, setSequentialProgress] = useState<{
    currentIndex: number;
    total: number;
    currentLevel: number;
    currentAttempt: number;
    maxAttempts: number;
    status: 'testing' | 'regenerating' | 'idle';
    results: {
      level_number: number;
      attempts: number;
      final_score: number;
      success: boolean;
      pass_threshold?: number;
      target_difficulty?: number;
      worst_bot?: string;
      worst_gap_pp?: number;
      direction?: 'too_easy' | 'too_hard' | 'ok';
    }[];
  }>({ currentIndex: 0, total: 0, currentLevel: 0, currentAttempt: 0, maxAttempts: 5, status: 'idle', results: [] });
  const [selectedSequentialLevels, setSelectedSequentialLevels] = useState<Set<number>>(new Set());
  const [lastClickedSequentialLevel, setLastClickedSequentialLevel] = useState<number | null>(null);
  const sequentialAbortRef = useRef<AbortController | null>(null);

  // Batch auto test state
  const [batchTestProgress, setBatchTestProgress] = useState<{
    status: 'idle' | 'running' | 'paused' | 'completed' | 'error';
    total: number;
    completed: number;
    currentLevel: number;
    results: {
      level_number: number;
      match_score: number;
      grade: string;
      status: string;
      target_difficulty: number;
      autoplay_score: number;
      static_score: number;
    }[];
    failedLevels: number[];
  }>({
    status: 'idle',
    total: 0,
    completed: 0,
    currentLevel: 0,
    results: [],
    failedLevels: [],
  });
  const [batchTestFilter, setBatchTestFilter] = useState<'all' | 'untested' | 'boss' | 'tutorial' | 'low_match' | 'range'>('untested');
  const [batchTestRange, setBatchTestRange] = useState({ min: 1, max: 100 });
  const [batchTestMaxLevels, setBatchTestMaxLevels] = useState(50);
  const batchAbortRef = useRef<AbortController | null>(null);

  // Preview tiles for selected level
  const [previewTiles, setPreviewTiles] = useState<GameTile[]>([]);
  const [previewScale, setPreviewScale] = useState(1);
  const previewContainerRef = useRef<HTMLDivElement>(null);
  const levelListRef = useRef<HTMLDivElement>(null);
  const levelListScrollTopRef = useRef<number>(0);
  const isLoadingLevelsRef = useRef<boolean>(false); // 로딩 중 스크롤 저장 방지 플래그

  // Playtest result state (after game ends)
  const [showResultForm, setShowResultForm] = useState(false);
  const [showLevelJson, setShowLevelJson] = useState(false);
  const [gameResult, setGameResult] = useState<{ won: boolean; stats: GameStats } | null>(null);
  const [perceivedDifficulty, setPerceivedDifficulty] = useState<1|2|3|4|5>(3);
  const [funRating, setFunRating] = useState<1|2|3|4|5>(3);
  const [comments, setComments] = useState('');
  const [issues, setIssues] = useState<string[]>([]);

  useEffect(() => {
    loadLevels();
  }, [batchId, filter]);

  // [v15.56] 생성 중엔 5초마다 자동 갱신 — 완료된 레벨 실시간 표시
  useEffect(() => {
    if (!isGenerating) return;
    const interval = setInterval(() => {
      // 테스트 진행 중이면 스킵 (정신없음 방지)
      if (isAutoTesting || isPlaying) return;
      loadLevels();
    }, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGenerating, isAutoTesting, isPlaying, batchId, filter]);

  // Preserve scroll position when levels update (during sequential/batch testing)
  // loadLevels에서 로딩 중일 때는 건너뛰고, 개별 레벨 업데이트 시에만 동작
  useEffect(() => {
    if (!isLoadingLevelsRef.current && levelListRef.current && levelListScrollTopRef.current > 0) {
      requestAnimationFrame(() => {
        if (levelListRef.current) {
          levelListRef.current.scrollTop = levelListScrollTopRef.current;
        }
      });
    }
  }, [levels]);

  // Sync selectedLevel with latest levels data (after regeneration, auto test save, etc.)
  useEffect(() => {
    if (selectedLevel) {
      const updated = levels.find(l => l.meta.level_number === selectedLevel.meta.level_number);
      if (updated && updated !== selectedLevel) {
        setSelectedLevel(updated);
      }
    }
  }, [levels]);

  // [v16] 레벨 선택 시 RL 예측 유저 클리어율 자동측정(없을 때 1회, 캐시).
  // 봇 게이지와 함께 RL 게이지를 바로 보여주기 위함. 이미 predicted 있으면 스킵.
  const rlAutoMeasuringRef = useRef<Set<number>>(new Set());
  useEffect(() => {
    const lvl = selectedLevel;
    if (!lvl || !lvl.level_json) return;
    if (lvl.meta.predicted_clear_rate !== undefined) return;          // 이미 RL 측정됨
    const ln = lvl.meta.level_number;
    if (rlAutoMeasuringRef.current.has(ln)) return;                   // 측정 중복 방지
    rlAutoMeasuringRef.current.add(ln);
    let cancelled = false;
    (async () => {
      try {
        const rl = await simulateLevelSkillSweep({
          level_json: lvl.level_json,
          target_difficulty: lvl.meta.target_difficulty,
          skill_mean: rlSkillMean,
          target_clear_rate_scale: bossTargetScale(ln),
        });
        if (cancelled) return;
        const predicted = rl.predicted_clear_rate;
        const target = rl.target_clear_rate ?? 0;
        const patch = {
          predicted_clear_rate: predicted,
          target_clear_rate: target,
          clear_rate_gap: rl.clear_rate_gap ?? undefined,
          rl_classification: rl.classification,
          luck_suspect: rl.luck_suspect,
          verified: true,
          verification_passed: rlVerificationPassed(ln, rl) && maxDeclaredGridDim(lvl.level_json) <= MAX_PLAYABLE_GRID,
        };
        await saveProductionLevels(batchId, [{ meta: { ...lvl.meta, ...patch }, level_json: lvl.level_json }]);
        setLevels(prev => prev.map(l => l.meta.level_number === ln ? { ...l, meta: { ...l.meta, ...patch } } : l));
      } catch {
        /* 측정 실패 시 무시 (봇 게이지만 표시) */
      } finally {
        rlAutoMeasuringRef.current.delete(ln);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedLevel?.meta.level_number]);

  // Generate preview tiles when selected level changes
  useEffect(() => {
    if (!selectedLevel) {
      setPreviewTiles([]);
      return;
    }

    try {
      // Parse level data
      let levelToUse = selectedLevel.level_json as unknown as Record<string, unknown>;
      if (levelToUse.map && typeof levelToUse.map === 'object') {
        levelToUse = levelToUse.map as Record<string, unknown>;
      }

      // Create game engine to extract tiles
      // previewMode: true - 맵툴에서는 첫 타일 스폰 안 함, 원래 카운트(*3) 표시
      const engine = createGameEngine();
      engine.initializeFromLevel(levelToUse, { previewMode: true });
      const tiles = engine.getTilesForUI();

      // Convert to GameTile format
      const gameTiles: GameTile[] = tiles.map(t => ({
        id: t.id,
        type: t.type,
        attribute: t.attribute,
        layer: t.layer,
        row: t.row,
        col: t.col,
        isSelectable: t.isSelectable,
        isSelected: false,
        isMatched: false,
        isHidden: t.isHidden,
        effectData: t.effectData,
        extra: t.extra,
        // Stack visual info
        isStackTile: t.isStackTile,
        stackIndex: t.stackIndex,
        stackMaxIndex: t.stackMaxIndex,
      }));

      // Calculate scale based on fixed 7x7 grid and container size
      // Fixed board size: 7 tiles + 1 extra tile + 0.5 tile for odd layer offset
      const fixedTileSize = 48;
      const fixedGridSize = 7;
      const fixedBoardWidth = (fixedGridSize) * fixedTileSize + fixedTileSize + fixedTileSize * 0.5;
      const fixedBoardHeight = fixedBoardWidth;

      if (previewContainerRef.current) {
        const containerWidth = previewContainerRef.current.clientWidth;
        const containerHeight = previewContainerRef.current.clientHeight;
        const scaleX = containerWidth / fixedBoardWidth;
        const scaleY = containerHeight / fixedBoardHeight;
        const scale = Math.min(scaleX, scaleY) * 0.95; // Fit container with slight padding
        setPreviewScale(scale);
      } else {
        setPreviewScale(1.0);
      }
      setPreviewTiles(gameTiles);
    } catch (err) {
      console.error('Failed to generate preview tiles:', err);
      setPreviewTiles([]);
    }
  }, [selectedLevel]);

  const loadLevels = async () => {
    // 스크롤 위치 보존을 위해 현재 위치 저장 (onScroll 핸들러보다 먼저)
    const savedScrollTop = levelListRef.current?.scrollTop || levelListScrollTopRef.current;

    // 로딩 중 플래그 설정 - onScroll에서 스크롤 위치 저장 방지
    isLoadingLevelsRef.current = true;

    setIsLoading(true);
    try {
      // API는 LevelStatus만 지원하므로 특수 필터(low_match, untested)는 제외
      const isStatusFilter = filter !== 'all' && filter !== 'low_match' && filter !== 'untested';
      const options = isStatusFilter ? { status: filter as LevelStatus, limit: 2000 } : { limit: 2000 };
      const loadedLevels = await getProductionLevelsByBatch(batchId, options);
      setLevels(loadedLevels);

      // 스크롤 위치 복원 (DOM 업데이트 후)
      if (savedScrollTop > 0) {
        // 여러 프레임 대기 후 복원 (React 리렌더링 완료 보장)
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            if (levelListRef.current) {
              levelListRef.current.scrollTop = savedScrollTop;
              levelListScrollTopRef.current = savedScrollTop; // ref도 업데이트
            }
            // 플래그 해제
            isLoadingLevelsRef.current = false;
          });
        });
      } else {
        isLoadingLevelsRef.current = false;
      }
    } catch (err) {
      console.error('Failed to load levels:', err);
      isLoadingLevelsRef.current = false;
    } finally {
      setIsLoading(false);
    }
  };

  // Auto test single level
  const handleAutoTestSingle = async () => {
    if (!selectedLevel) return;
    setIsAutoTesting(true);
    setAutoTestResult(null);

    try {
      // [v16] RL 예측 유저 클리어율 기반 (봇 3종 → 통합 1개)
      const rl = await simulateLevelSkillSweep({
        level_json: selectedLevel.level_json,
        target_difficulty: selectedLevel.meta.target_difficulty,
        skill_mean: rlSkillMean,
        target_clear_rate_scale: bossTargetScale(selectedLevel.meta.level_number),
      });
      const predicted = rl.predicted_clear_rate;
      const target = rl.target_clear_rate ?? 0;
      const gapPp = (rl.clear_rate_gap ?? predicted - target) * 100; // 양수=목표보다 쉬움
      const matchScore = Math.max(0, 100 - Math.abs(gapPp) * 2);
      const balance = rl.classification === 'unclearable_suspect'
        ? 'too_hard'
        : Math.abs(gapPp) <= 5 ? 'balanced' : gapPp > 0 ? 'too_easy' : 'too_hard';

      setAutoTestResult({
        match_score: matchScore,
        autoplay_grade: rl.classification,
        balance_status: balance,
        bot_stats: [],
        recommendations: rl.classification === 'unclearable_suspect'
          ? ['최고 실력으로도 클리어 불가 — 재생성 필요']
          : [],
        predicted_clear_rate: predicted,
        target_clear_rate: target,
        clear_rate_gap: rl.clear_rate_gap ?? predicted - target,
        rl_classification: rl.classification,
      });

      // Save to production storage — RL 메타 (봇 대신 예측 클리어율)
      // [P1] actual_difficulty = 실측(difficulty_score). 정적 추정 덮어씀.
      const updatedMeta = {
        ...selectedLevel.meta,
        verification_method: 'rl' as const,
        predicted_clear_rate: predicted,
        target_clear_rate: target,
        clear_rate_gap: rl.clear_rate_gap ?? undefined,
        rl_classification: rl.classification,
        luck_suspect: rl.luck_suspect,
        match_score: matchScore,
        verified: true,
        verification_passed: rlVerificationPassed(selectedLevel.meta.level_number, rl) && maxDeclaredGridDim(selectedLevel.level_json) <= MAX_PLAYABLE_GRID,
        actual_difficulty: (typeof rl.difficulty_score === 'number') ? rl.difficulty_score : Math.max(0, Math.min(1, 1 - predicted)),
      };

      await saveProductionLevels(batchId, [{
        meta: updatedMeta,
        level_json: selectedLevel.level_json,
      }]);

      addNotification('success', `레벨 ${selectedLevel.meta.level_number} 테스트 완료 (예측 클리어율 ${(predicted * 100).toFixed(0)}%, 목표 ${(target * 100).toFixed(0)}%)`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Auto test failed:', err);
      addNotification('error', '자동 테스트 실패: ' + (err instanceof Error ? err.message : '알 수 없는 오류'));
    } finally {
      setIsAutoTesting(false);
    }
  };

  // 개별 레벨 검증 (리스트에서 개별 레벨 검증 버튼 클릭 시)
  const handleValidateSingleLevel = async (level: ProductionLevel) => {
    const levelNumber = level.meta.level_number;

    // 이미 검증 중이면 무시
    if (validatingLevels.has(levelNumber)) return;

    setValidatingLevels(prev => new Set(prev).add(levelNumber));

    try {
      const result = await analyzeAutoPlay(level.level_json, {
        iterations: autoTestIterations,
        targetDifficulty: level.meta.target_difficulty,
      });

      const matchScore = calculateMatchScoreFromBots(result.bot_stats);
      // [v15.14] novice/casual 제외 - 검증용 3봇만 사용
      const botClearRates = {
        average: result.bot_stats.find(s => s.profile === 'average')?.clear_rate || 0,
        expert: result.bot_stats.find(s => s.profile === 'expert')?.clear_rate || 0,
        optimal: result.bot_stats.find(s => s.profile === 'optimal')?.clear_rate || 0,
      };

      // Save to production storage
      const updatedMeta = {
        ...level.meta,
        bot_clear_rates: botClearRates,
        match_score: matchScore,
        verified: true,
        verification_passed: matchScore >= 70,
      };

      await saveProductionLevels(batchId, [{
        meta: updatedMeta,
        level_json: level.level_json,
      }]);

      const passStatus = matchScore >= 70 ? '✓ 통과' : '✗ 미달';
      addNotification(
        matchScore >= 70 ? 'success' : 'warning',
        `Lv.${levelNumber} 검증 완료: ${matchScore.toFixed(0)}% ${passStatus}`
      );
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Level validation failed:', err);
      addNotification('error', `Lv.${levelNumber} 검증 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`);
    } finally {
      setValidatingLevels(prev => {
        const next = new Set(prev);
        next.delete(levelNumber);
        return next;
      });
    }
  };

  // Sequential auto process: test → regenerate if failed → repeat until pass (70%+)
  const handleSequentialProcess = async (targetLevelNumbers: number[]) => {
    if (targetLevelNumbers.length === 0) {
      addNotification('info', '처리할 레벨이 없습니다.');
      return;
    }

    const MAX_ATTEMPTS = 10; // [v16] 5→10: near-miss 통과율↑ (학습 출발점과 시너지). 시간↑ 감수.
    const BASE_PASS_THRESHOLD = 70; // 70% match score to pass

    sequentialAbortRef.current = new AbortController();
    const signal = sequentialAbortRef.current.signal;

    setIsSequentialProcessing(true);
    setSequentialProgress({
      currentIndex: 0,
      total: targetLevelNumbers.length,
      currentLevel: targetLevelNumbers[0],
      currentAttempt: 0,
      maxAttempts: MAX_ATTEMPTS,
      status: 'testing',
      results: [],
    });

    const results: {
      level_number: number;
      attempts: number;
      final_score: number;
      success: boolean;
      pass_threshold?: number;
      target_difficulty?: number;
      worst_bot?: string;
      worst_gap_pp?: number;
      direction?: 'too_easy' | 'too_hard' | 'ok';
    }[] = [];

    // [v16] 레벨 단위 병렬 처리. 각 레벨은 독립(생성·측정·재생성)이고 저장은 IndexedDB 레벨별 put이라
    // 동시 쓰기 안전. SEQ_CONCURRENCY개 워커가 큐에서 꺼내 동시 처리 → 4~6배 빠름.
    const SEQ_CONCURRENCY = 4;
    let _completed = 0;
    const _queue = [...targetLevelNumbers];
    const processOneLevel = async (levelNumber: number): Promise<void> => {
      if (signal.aborted) return;
      let currentLevel = levels.find(l => l.meta.level_number === levelNumber);
      if (!currentLevel) return;

      let attempts = 0;
      let matchScore = 0;
      let passed = false;
      let lastWorstBot: string | undefined;
      let lastWorstGapPp: number | undefined;
      let lastDirection: 'too_easy' | 'too_hard' | 'ok' | undefined;
      let lastTargetDifficulty: number | undefined = currentLevel.meta.target_difficulty;
      let lastPassThreshold = BASE_PASS_THRESHOLD;
      // [v16 Phase2] best-of-N 유지: 전 attempt 중 목표(gap) 가장 가까운 버전 보관.
      // 통과 못해도 최근접 버전을 최종 저장 → 단조개선 보장 (이전엔 마지막 attempt가 덮어써 더 나빠질 수 있었음).
      let bestAbsGap = Infinity;
      let bestIsClearable = false;  // [A2] 솔버블(언클리어러블 아님) 후보 우선
      let bestSnapshot: { level_json: ProductionLevel['level_json']; meta: ProductionLevelMeta } | null = null;
      // [v16 자가개선] 학습된 보정값에서 출발 (없으면 0). 검증 돌릴수록 좋은 출발점.
      let difficultyOffset = getLearnedOffset(levelNumber, currentLevel.meta.target_difficulty);
      let genOffset = difficultyOffset;  // 현재 측정중 레벨을 생성한 offset (통과 시 학습 기록용)

      while (attempts < MAX_ATTEMPTS && !passed && !signal.aborted) {
        attempts++;
        const passThreshold = computeSequentialPassThreshold(currentLevel?.meta.target_difficulty);
        lastPassThreshold = passThreshold;
        lastTargetDifficulty = currentLevel?.meta.target_difficulty;

        // Update progress: testing (병렬이라 현재 처리중 레벨/완료수 표시)
        setSequentialProgress(prev => ({
          ...prev,
          currentIndex: _completed,
          currentLevel: levelNumber,
          currentAttempt: attempts,
          status: 'testing',
        }));

        // Test the level — [v16] RL 예측 유저 클리어율 기반 검증 (봇 match_score 대체)
        try {
          const rl = await simulateLevelSkillSweep({
            level_json: currentLevel.level_json,
            target_difficulty: currentLevel.meta.target_difficulty,
            seed: attempts, // attempt별 시드 변경 — 재생성 재측정 독립성
            skill_mean: rlSkillMean,
            target_clear_rate_scale: bossTargetScale(currentLevel.meta.level_number),
          });

          const predicted = rl.predicted_clear_rate;
          const target = rl.target_clear_rate ?? 0;
          const gapPp = (rl.clear_rate_gap ?? predicted - target) * 100; // 양수=목표보다 쉬움
          // 레거시 UI/필터 호환용 match_score (0~100): 갭 작을수록 높음. 통과(±10%p)→80+
          matchScore = Math.max(0, 100 - Math.abs(gapPp) * 2);

          // [P3-D 솔버 앵커] RL이 unclearable_suspect(봇이 못 깸)라도, A* 완전탐색이 클리어 가능
          //   확정(PROVEN_SOLVABLE)하면 "불가능" 낙인 해제 — 봇 약점(고종류 독관리 등)으로 인한
          //   오탐 구제. 게이팅: unclearable_suspect일 때만 A* 호출(드묾 → 비용 적음).
          //   난이도 gap(too_hard/easy) 판정은 RL 유지 — D는 '클리어 가능성'만 담당.
          let solverClearable = false;
          if (rl.classification === 'unclearable_suspect') {
            try {
              const sv = await analyzeSolvability(currentLevel.level_json, { nodeBudget: 200000, timeBudgetS: 6 });
              if (sv.verdict === 'PROVEN_SOLVABLE') {
                solverClearable = true;
                console.info(`[solver-anchor] Lv.${levelNumber} RL=unclearable_suspect이나 A* PROVEN_SOLVABLE(${sv.moves_to_clear}수) → 클리어가능 인정`);
              }
            } catch { /* 솔버 실패시 구제 안 함(그대로) */ }
          }

          // 실패 분류: gap 부호 (too_easy/too_hard). unclearable은 too_hard로.
          lastWorstBot = undefined; // RL은 봇별 분해 없음
          lastWorstGapPp = gapPp;
          lastDirection = rl.classification === 'unclearable_suspect'
            ? 'too_hard'
            : Math.abs(gapPp) <= 5
              ? 'ok'
              : gapPp > 0
                ? 'too_easy'
                : 'too_hard';

          // [v16 피드백제어] 측정 gap → 다음 재생성 난이도 조준.
          // 생성변동(±30%p)이 커서 ±1 완만 스텝으로 점진 이동(급격 조정은 진동만 유발).
          // 주목적: 시도마다 난이도 regime을 넓혀 best-of-5가 목표를 걸치게(탐색). clamp[-3,+3].
          if (rl.classification === 'unclearable_suspect') {
            difficultyOffset -= 1;
          } else if (gapPp > 12) {
            difficultyOffset += 1; // 너무쉬움 → 어렵게
          } else if (gapPp < -12) {
            difficultyOffset -= 1; // 너무어려움 → 쉽게
          }
          difficultyOffset = Math.max(-3, Math.min(3, difficultyOffset));

          // 통과 판정: 튜토리얼(1~10) 예외 포함 (쉬움 허용). 일반은 백엔드 기준.
          // [디바이스 제약] 선언 그리드 최대변 > 8 → 실기에서 타일이 너무 작아 플레이 불가 →
          // RL 통과와 무관하게 실패 처리(재생성 유도, 보스 10x10 템플릿 잔재 정리).
          const gridDim = maxDeclaredGridDim(currentLevel.level_json);
          if (gridDim > MAX_PLAYABLE_GRID) {
            console.warn(`[seq] Lv.${levelNumber} 선언 그리드 ${gridDim} > ${MAX_PLAYABLE_GRID} → 실패 처리(재생성)`);
          }
          const isPassed = rlVerificationPassed(levelNumber, rl) && gridDim <= MAX_PLAYABLE_GRID;

          // RL 검증 메타 (봇 대신 예측 클리어율)
          // [P1] actual_difficulty = 실플레이 시뮬 측정값(difficulty_score=1-AUC). 정적 analyzer 추정 폐기.
          //   생성 시 넣던 정적 난이도를 검증 측정값으로 '덮어씀'(...currentLevel.meta 뒤에 spread).
          //   difficulty_score 없으면 1-predicted로 폴백.
          const measuredDifficulty = (typeof rl.difficulty_score === 'number')
            ? rl.difficulty_score
            : Math.max(0, Math.min(1, 1 - predicted));
          const rlMeta = {
            verification_method: 'rl' as const,
            predicted_clear_rate: predicted,
            target_clear_rate: target,
            clear_rate_gap: rl.clear_rate_gap ?? undefined,
            rl_classification: rl.classification,
            luck_suspect: rl.luck_suspect,
            match_score: matchScore,
            verified: true,
            verification_passed: isPassed,
            actual_difficulty: measuredDifficulty,  // [P1] 실측 난이도
          };

          // [v16 Phase2+A2] best-of-N: 솔버블 우선 → 그 안에서 목표 최근접(gap 최소).
          // 언클리어러블(0% 클리어)은 gap이 작아도 절대 선택 안 함 (솔버블 후보 있으면).
          const absGap = Math.abs(rl.clear_rate_gap ?? 1);
          // [P3-D] 솔버가 클리어 가능 확정하면 봇 판정(unclearable)보다 우선 → clearable 인정
          const isClearable = solverClearable || (rl.classification !== 'unclearable_suspect' && rl.max_clear_rate >= 0.05);
          const better =
            bestSnapshot === null
            || (isClearable && !bestIsClearable)                       // 솔버블이 비솔버블을 항상 이김
            || (isClearable === bestIsClearable && absGap < bestAbsGap); // 동급이면 gap 최소
          if (better) {
            bestAbsGap = absGap;
            bestIsClearable = isClearable;
            bestSnapshot = {
              level_json: currentLevel.level_json,
              meta: { ...currentLevel.meta, ...rlMeta },
            };
          }

          await saveProductionLevels(batchId, [{
            meta: { ...currentLevel.meta, ...rlMeta },
            level_json: currentLevel.level_json,
          }]);

          // Update levels state (preserve scroll position)
          const scrollTop = levelListRef.current?.scrollTop || 0;
          setLevels(prev => prev.map(l =>
            l.meta.level_number === levelNumber
              ? { ...l, meta: { ...l.meta, ...rlMeta } }
              : l
          ));
          // Restore scroll position after React re-render
          requestAnimationFrame(() => {
            if (levelListRef.current) {
              levelListRef.current.scrollTop = scrollTop;
            }
          });

          if (isPassed) {
            passed = true;
            // [v16 자가개선] 통과한 레벨을 만든 offset(genOffset)을 학습 기록 → 다음 검증의 출발점 개선.
            recordPassedOffset(levelNumber, currentLevel.meta.target_difficulty, genOffset);
          } else if (attempts < MAX_ATTEMPTS && !signal.aborted) {
            // Regenerate if not passed
            setSequentialProgress(prev => ({ ...prev, status: 'regenerating' }));

            // [unclear-template-escape] 템플릿 기반 레벨에서 모든 봇 클리어율이 사실상 0(<5%)이면
            // 같은 모양으로 색만 바꿔봐야 데드락 탈출 불가 → 일반 generate 경로로 강제 전환.
            // 데이터 분석 결과(2026-05-21) May7 배치의 23개 반복 실패 중 22개가 이 케이스였음.
            const hasTemplate = !!(currentLevel?.meta as { template_id?: string } | undefined)?.template_id;
            // RL: 최고실력(max_clear_rate)으로도 못 깨면 언클리어러블. classification도 병행 확인.
            const maxClearRate = rl.max_clear_rate;
            // [P3-D] 솔버가 클리어 가능 확정이면 템플릿 언클리어러블 탈출 강제 안 함(봇 오탐 구제)
            const unclearableTemplate = hasTemplate && !solverClearable
              && (maxClearRate < 0.05 || rl.classification === 'unclearable_suspect');
            if (unclearableTemplate) {
              addNotification(
                'warning',
                `Lv.${levelNumber} 템플릿 언클리어러블 감지 (max clear ${(maxClearRate * 100).toFixed(0)}%) → 일반 생성 경로로 전환`
              );
            }

            // Use existing regeneration logic — 피드백 offset 전달(측정 gap 기반 난이도 조준)
            // 이 regen이 만든 레벨을 다음 시도가 측정 → 그 레벨의 생성 offset 기록(통과 시 학습용)
            genOffset = difficultyOffset;
            await handleRegenerateLevel(levelNumber, undefined, undefined, {
              forceNoTemplate: unclearableTemplate,
              difficultyOffset,
            });

            // Reload the level after regeneration from storage
            const reloadedLevels = await getProductionLevelsByBatch(batchId);
            currentLevel = reloadedLevels.find((l: ProductionLevel) => l.meta.level_number === levelNumber);
            if (!currentLevel) break;
          }
        } catch (err) {
          console.error(`Sequential process failed for level ${levelNumber}:`, err);
          break;
        }
      }

      // [v16 Phase2] 통과 못했으면 전 attempt 중 최근접(best) 버전을 최종 저장.
      // bestSnapshot은 정의상 측정된 것 중 gap 최소 → 마지막 attempt가 best면 동일내용(무해), 아니면 단조개선.
      if (!passed && bestSnapshot) {
        await saveProductionLevels(batchId, [bestSnapshot]);
        const snap = bestSnapshot;
        setLevels(prev => prev.map(l =>
          l.meta.level_number === levelNumber ? { ...l, meta: snap.meta, level_json: snap.level_json } : l
        ));
        matchScore = snap.meta.match_score ?? matchScore;
        addNotification('info', `Lv.${levelNumber} 통과실패 → 최근접 버전 보관 (예측 ${((snap.meta.predicted_clear_rate ?? 0) * 100).toFixed(0)}%, 목표 ${((snap.meta.target_clear_rate ?? 0) * 100).toFixed(0)}%)`);
      }

      results.push({
        level_number: levelNumber,
        attempts,
        final_score: matchScore,
        success: passed,
        pass_threshold: lastPassThreshold,
        target_difficulty: lastTargetDifficulty,
        worst_bot: lastWorstBot,
        worst_gap_pp: lastWorstGapPp,
        direction: lastDirection,
      });
      _completed++;
      setSequentialProgress(prev => ({ ...prev, currentIndex: _completed, results: [...results] }));
    };

    // 동시성 풀: SEQ_CONCURRENCY개 워커가 큐에서 레벨을 꺼내 병렬 처리
    const _workers = Array.from({ length: Math.min(SEQ_CONCURRENCY, _queue.length || 1) }, async () => {
      while (_queue.length > 0 && !signal.aborted) {
        const ln = _queue.shift();
        if (ln === undefined) break;
        try {
          await processOneLevel(ln);
        } catch (e) {
          console.error('[seq] 레벨 처리 실패', ln, e);
        }
      }
    });
    await Promise.all(_workers);

    // [v16 QD 2차패스] 실패레벨 전용: 밴드별 다양성 풀 생성→RL측정→목표 최근접 배정.
    // 양봉분포(20%/80%만, 중간 드묾)를 '풀에서 어쩌다 나온 중간값'으로 정면돌파. 풀 한 번에 측정해
    // 통(bin)별로 두고 각 실패슬롯에 가장 근접한 솔버블 후보 배정 → 온디맨드 생성 정밀도 불필요.
    let failedNums = results.filter(r => !r.success).map(r => r.level_number);
    if (failedNums.length > 0 && !signal.aborted) {
      setSequentialProgress(prev => ({ ...prev, status: 'testing' }));
      addNotification('info', `2차패스(QD): 실패 ${failedNums.length}개 풀생성·배정 시작…`);
      const recovered = await runFailedLevelSecondPass(failedNums, signal);
      for (const ln of recovered) {
        const r = results.find(x => x.level_number === ln);
        if (r) r.success = true;
      }
      if (recovered.length > 0) {
        addNotification('success', `2차패스 회수: ${recovered.length}/${failedNums.length}개 추가 통과`);
      }
    }

    setIsSequentialProcessing(false);
    setSequentialProgress(prev => ({ ...prev, status: 'idle' }));

    const successCount = results.filter(r => r.success).length;
    const failCount = results.filter(r => !r.success).length;
    addNotification(
      successCount > 0 ? 'success' : 'warning',
      `순차 처리 완료: ${successCount}개 통과, ${failCount}개 미통과`
    );

    loadLevels();
    onStatsUpdate();
  };

  /**
   * [v16 QD 2차패스] 실패레벨 회수 — Quality-Diversity 아카이브식.
   * 밴드별로 난이도 다양성 풀을 한 번에 생성(offset 스윕 × 패턴 시드)하고 RL측정 →
   * 각 실패슬롯에 같은밴드 내 목표 클리어율 최근접·솔버블 후보를 그리디 배정.
   * 양봉/고변동이라 슬롯별 온디맨드 적중은 어려워도, 풀 전체엔 중간값이 섞여 나옴 → 배정으로 적중.
   * 반환: 새로 통과(회수)된 level_number 배열.
   */
  const runFailedLevelSecondPass = async (
    failedLevelNumbers: number[],
    signal: AbortSignal,
  ): Promise<number[]> => {
    const TOL = 0.12;
    const recovered: number[] = [];
    let fresh: ProductionLevel[] = [];
    try {
      fresh = await getProductionLevelsByBatch(batchId);
    } catch {
      return recovered;
    }
    const currentBatch = await getProductionBatch(batchId).catch(() => null);
    const gimmickUnlocks = currentBatch?.gimmick_unlock_levels || PROFESSIONAL_GIMMICK_UNLOCK_LEVELS;
    const metaOf = (ln: number) => fresh.find(l => l.meta.level_number === ln)?.meta;

    // 밴드(100단위)별 그룹
    const byBand = new Map<number, number[]>();
    for (const ln of failedLevelNumbers) {
      const band = Math.floor(ln / 100) * 100;
      byBand.set(band, [...(byBand.get(band) || []), ln]);
    }

    // 단일 후보 생성+측정
    const genCandidate = async (levelNumber: number, td: number, offset: number, seed: number) => {
      // [타일종류 고정] 재생성도 초기 생성과 동일한 그래프값(useTileCount) 유지 → 난이도 레버에서 타일종류 제외.
      // 난이도 조준은 아래 층수(ml, offset)/기믹으로만. (기존: 난이도기반 baseTileCount+offset 로 종류 축소 → 그래프 붕괴)
      const cnt = Math.max(4, Math.min(15, vAtLevel(TILE_TYPE_PROFILE_CURVES[tileTypeProfile] ?? TILE_TYPE_PROFILE_CURVES.baseline, levelNumber)));
      const ml = Math.max(2, Math.min(10, Math.min(10, 3 + Math.floor(td * 7)) + Math.trunc(offset / 2)));
      const sym = (['horizontal', 'vertical', 'both', 'none'] as const)[seed % 4];
      const res = await generateLevel(
        {
          target_difficulty: td,
          grid_size: [7, 7],
          min_layers: 2,
          max_layers: ml,
          tile_types: Array.from({ length: cnt }, (_, i) => `t${i + 1}`),
          obstacle_types: [],
          goals: [{
            type: (['craft', 'stack'] as const)[seed % 2],
            direction: (['s', 'n', 'e', 'w'] as const)[seed % 4],
            count: Math.max(2, Math.floor(3 + td * 2)),
          }],
          symmetry_mode: sym,
          pattern_type: 'aesthetic',
          pattern_index: (seed * 7 + 10) % 60,
        },
        {
          auto_select_gimmicks: true,
          available_gimmicks: ['craft', 'stack', 'chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
          gimmick_intensity: Math.min(td, levelNumber / 500),
          gimmick_unlock_levels: gimmickUnlocks,
          level_number: levelNumber,
        }
      );
      const rl = await simulateLevelSkillSweep({ level_json: res.level_json, target_difficulty: td, seed, skill_mean: rlSkillMean, target_clear_rate_scale: bossTargetScale(levelNumber) });
      return {
        level_json: res.level_json,
        grade: res.grade,
        clear: rl.predicted_clear_rate,
        solvable: rl.max_clear_rate >= 0.05 && rl.classification !== 'unclearable_suspect',
        used: false,
      };
    };

    for (const [, slots] of byBand) {
      if (signal.aborted) break;
      // 풀 생성 기준: 밴드 내 가장 낮은 실패레벨(기믹 제약 최소 → 상위 슬롯 호환). td는 슬롯 중앙값.
      const genLn = Math.min(...slots);
      const tds = slots.map(ln => metaOf(ln)?.target_difficulty ?? 0.5);
      const medTd = tds.slice().sort((a, b) => a - b)[Math.floor(tds.length / 2)];
      // offset -3..3 × 3시드 = 21후보 (난이도 촘촘히 스팬 → 양봉구멍 포착률↑). 슬롯 많으면 시드 더.
      const seedsPer = Math.max(3, Math.ceil((slots.length * 2) / 7));
      const jobs: Array<Promise<Awaited<ReturnType<typeof genCandidate>> | null>> = [];
      for (let off = -3; off <= 3; off++) {
        for (let s = 0; s < seedsPer; s++) {
          jobs.push(genCandidate(genLn, medTd, off, off * 10 + s + 1).catch(() => null));
        }
      }
      const pool = (await Promise.all(jobs)).filter(Boolean) as Array<Awaited<ReturnType<typeof genCandidate>>>;
      const solvablePool = pool.filter(c => c.solvable);
      if (solvablePool.length === 0) continue;

      // 그리디 배정: 각 실패슬롯에 목표 최근접 미사용 후보
      const sortedSlots = slots.slice().sort((a, b) => (metaOf(a)?.target_difficulty ?? 0.5) - (metaOf(b)?.target_difficulty ?? 0.5));
      for (const ln of sortedSlots) {
        if (signal.aborted) break;
        const meta = metaOf(ln);
        if (!meta) continue;
        // 목표 클리어율: 백엔드 곡선과 동기화 위해 RL 1회로 target 취득(가벼움) — 대신 후보 clear와 비교
        // 간이: 후보 중 '슬롯 target_clear' 최근접. target_clear는 백엔드가 주는 값과 동일 곡선 필요 →
        // 후보 생성 시 같은 td로 측정했으니, 슬롯 target은 그 슬롯 td의 목표. 한 후보를 슬롯 td로 재측정해 target 취득.
        const probe = solvablePool.find(c => !c.used);
        if (!probe) break;
        const tgtResp = await simulateLevelSkillSweep({ level_json: probe.level_json, target_difficulty: meta.target_difficulty, seed: 1, skill_mean: rlSkillMean, target_clear_rate_scale: bossTargetScale(meta.level_number) }).catch(() => null);
        const targetClear = tgtResp?.target_clear_rate ?? 0.4;
        let best: typeof solvablePool[number] | null = null;
        let bestGap = TOL;
        for (const c of solvablePool) {
          if (c.used) continue;
          const g = Math.abs(c.clear - targetClear);
          if (g < bestGap) { bestGap = g; best = c; }
        }
        if (!best) continue;
        best.used = true;
        // 배정: 슬롯 메타에 RL검증 결과 채워 저장 (통과 처리)
        const rlMeta = {
          verification_method: 'rl' as const,
          predicted_clear_rate: best.clear,
          target_clear_rate: targetClear,
          clear_rate_gap: best.clear - targetClear,
          rl_classification: undefined,
          match_score: Math.max(0, 100 - Math.abs(best.clear - targetClear) * 100 * 2),
          grade: best.grade as DifficultyGrade,
          verified: true,
          verification_passed: true,
        };
        // [비주얼 시드 bake] 밴드 rework 채택분도 다양색 relabel (누락 방지)
        applyProductionTileVisuals(best.level_json, ln);
        await saveProductionLevels(batchId, [{ meta: { ...meta, ...rlMeta }, level_json: best.level_json }]);
        recovered.push(ln);
      }
    }
    return recovered;
  };

  const handleStopSequentialProcess = () => {
    sequentialAbortRef.current?.abort();
    addNotification('info', '순차 처리 중지됨');
  };

  // Calculate match score from bot stats (aligned with backend formula for consistency)
  // [v14.2] 방안 B+D: maxGap 가중치 감소(0.4→0.3) + 어려움 패널티 완화(1.0→0.7)
  const calculateMatchScoreFromBots = (botStats: { clear_rate: number; target_clear_rate: number }[]) => {
    if (!botStats.length) return 0;
    const gaps = botStats.map(s => {
      const rawGap = (s.clear_rate - s.target_clear_rate) * 100; // Positive = too easy
      // 방안 D: 너무 쉬움 = 50% 패널티, 너무 어려움 = 70% 패널티 (기존 100%)
      return rawGap > 0 ? rawGap * 0.5 : Math.abs(rawGap) * 0.7;
    });
    const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
    const maxGap = Math.max(...gaps);
    // 방안 B: avgGap×0.7 + maxGap×0.3 (기존 0.6/0.4)
    const weightedGap = (avgGap * 0.7 + maxGap * 0.3);
    return Math.max(0, 100 - weightedGap * 2);
  };

  // Batch auto test
  const handleBatchAutoTest = async () => {
    batchAbortRef.current = new AbortController();
    const signal = batchAbortRef.current.signal;

    // Filter levels based on selected filter
    let filteredLevels = [...levels];

    switch (batchTestFilter) {
      case 'untested':
        filteredLevels = filteredLevels.filter(l => !l.meta.match_score && !l.meta.bot_clear_rates);
        break;
      case 'boss':
        filteredLevels = filteredLevels.filter(l => l.meta.level_number % 10 === 0);
        break;
      case 'tutorial':
        const tutorialLevels = [11, 21, 36, 51, 66, 81, 96, 111, 126, 141, 156];
        filteredLevels = filteredLevels.filter(l => tutorialLevels.includes(l.meta.level_number));
        break;
      case 'low_match':
        filteredLevels = filteredLevels.filter(l => l.meta.match_score !== undefined && l.meta.match_score < 70);
        break;
      case 'range':
        filteredLevels = filteredLevels.filter(l =>
          l.meta.level_number >= batchTestRange.min &&
          l.meta.level_number <= batchTestRange.max
        );
        break;
    }

    // Apply max levels limit
    if (filteredLevels.length > batchTestMaxLevels) {
      filteredLevels = filteredLevels.slice(0, batchTestMaxLevels);
    }

    if (filteredLevels.length === 0) {
      addNotification('warning', '테스트할 레벨이 없습니다.');
      return;
    }

    setBatchTestProgress({
      status: 'running',
      total: filteredLevels.length,
      completed: 0,
      currentLevel: 0,
      results: [],
      failedLevels: [],
    });

    const results: { level_number: number; match_score: number; grade: string; status: string; target_difficulty: number; autoplay_score: number; static_score: number }[] = [];
    const failedLevels: number[] = [];
    let completedCount = 0;

    // Process a single level's auto test
    const testOneLevel = async (level: typeof filteredLevels[0]) => {
      const result = await analyzeAutoPlay(level.level_json, {
        iterations: autoTestIterations,
        targetDifficulty: level.meta.target_difficulty,
      });

      const matchScore = calculateMatchScoreFromBots(result.bot_stats);

      const testResult = {
        level_number: level.meta.level_number,
        match_score: matchScore,
        grade: result.autoplay_grade,
        status: result.balance_status,
        target_difficulty: level.meta.target_difficulty,
        autoplay_score: result.autoplay_score,
        static_score: result.static_score,
      };

      // Save result to level meta
      // [v15.14] novice/casual 제외 - 검증용 3봇만 사용
      const botClearRates = {
        average: result.bot_stats.find(s => s.profile === 'average')?.clear_rate || 0,
        expert: result.bot_stats.find(s => s.profile === 'expert')?.clear_rate || 0,
        optimal: result.bot_stats.find(s => s.profile === 'optimal')?.clear_rate || 0,
      };

      await saveProductionLevels(batchId, [{
        meta: {
          ...level.meta,
          bot_clear_rates: botClearRates,
          match_score: matchScore,
        },
        level_json: level.level_json,
      }]);

      return testResult;
    };

    // Execute in parallel batches of 10
    const TEST_CONCURRENCY = 10;
    for (let batchStart = 0; batchStart < filteredLevels.length; batchStart += TEST_CONCURRENCY) {
      if (signal.aborted) {
        setBatchTestProgress(prev => ({ ...prev, status: 'paused' }));
        break;
      }

      const batchSlice = filteredLevels.slice(batchStart, batchStart + TEST_CONCURRENCY);

      setBatchTestProgress(prev => ({
        ...prev,
        currentLevel: batchSlice[0].meta.level_number,
      }));

      const batchResults = await Promise.allSettled(
        batchSlice.map(level => testOneLevel(level))
      );

      // Collect successful results for this batch
      const batchSuccessResults: typeof results = [];
      for (let j = 0; j < batchResults.length; j++) {
        const r = batchResults[j];
        completedCount++;
        if (r.status === 'fulfilled') {
          results.push(r.value);
          batchSuccessResults.push(r.value);
        } else {
          console.error(`Auto test failed for level ${batchSlice[j].meta.level_number}:`, r.reason);
          failedLevels.push(batchSlice[j].meta.level_number);
        }
      }

      // Update levels state directly for immediate UI feedback (preserve scroll position)
      if (batchSuccessResults.length > 0) {
        const scrollTop = levelListRef.current?.scrollTop || 0;
        setLevels(prev => prev.map(level => {
          const result = batchSuccessResults.find(r => r.level_number === level.meta.level_number);
          if (result) {
            return {
              ...level,
              meta: {
                ...level.meta,
                match_score: result.match_score,
              },
            };
          }
          return level;
        }));
        requestAnimationFrame(() => {
          if (levelListRef.current) {
            levelListRef.current.scrollTop = scrollTop;
          }
        });
      }

      setBatchTestProgress(prev => ({
        ...prev,
        completed: completedCount,
        results: [...results],
        failedLevels: [...failedLevels],
      }));
    }

    if (!signal.aborted) {
      setBatchTestProgress(prev => ({ ...prev, status: 'completed' }));
      addNotification('success', `일괄 자동 테스트 완료: ${results.length}개 성공, ${failedLevels.length}개 실패`);
      loadLevels();
      onStatsUpdate();
    }
  };

  const handleStopBatchTest = () => {
    batchAbortRef.current?.abort();
    addNotification('info', '일괄 테스트 중지됨');
  };

  // 전체 자동 승인 상태
  const [isApprovingAll, setIsApprovingAll] = useState(false);
  const [approveAllProgress, setApproveAllProgress] = useState({ current: 0, total: 0 });

  // 전체 자동 승인 - 모든 generated 상태 레벨을 approved로 변경
  const handleApproveAllLevels = async () => {
    // 전체 레벨 로드 (generated 상태)
    const allLevels = await getProductionLevelsByBatch(batchId);
    const generatedLevels = allLevels.filter(l => l.meta.status === 'generated');

    if (generatedLevels.length === 0) {
      addNotification('info', '승인할 레벨이 없습니다');
      return;
    }

    setIsApprovingAll(true);
    setApproveAllProgress({ current: 0, total: generatedLevels.length });

    try {
      for (let i = 0; i < generatedLevels.length; i++) {
        await approveLevel(batchId, generatedLevels[i].meta.level_number, '자동승인(테스트완료)');
        setApproveAllProgress({ current: i + 1, total: generatedLevels.length });
      }

      addNotification('success', `${generatedLevels.length}개 레벨 자동 승인 완료 → 익스포트 탭에서 내보내기 가능`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Auto approve failed:', err);
      addNotification('error', '자동 승인 중 오류 발생');
    } finally {
      setIsApprovingAll(false);
    }
  };

  // Regeneration state
  const [regeneratingLevels, setRegeneratingLevels] = useState<Set<number>>(new Set());
  const [enhancingLevels, setEnhancingLevels] = useState<Set<number>>(new Set());
  const [validatingLevels, setValidatingLevels] = useState<Set<number>>(new Set());  // 개별 검증 진행 중인 레벨
  const [isBatchRegenerating, setIsBatchRegenerating] = useState(false);
  const [regenerationThreshold, setRegenerationThreshold] = useState(70);
  const [selectedRegenLevels, setSelectedRegenLevels] = useState<Set<number>>(new Set());
  // Range selection state for batch regeneration
  const [rangeSelectMode, setRangeSelectMode] = useState(false);
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(100);
  const [lastClickedRegenLevel, setLastClickedRegenLevel] = useState<number | null>(null);

  // Regeneration Modal state (모양 선택 기능)
  const [regenModalOpen, setRegenModalOpen] = useState(false);
  const [regenModalLevel, setRegenModalLevel] = useState<number | null>(null);
  const [regenPatternIndex, setRegenPatternIndex] = useState<number | undefined>(undefined);
  const [regenSymmetryMode, setRegenSymmetryMode] = useState<'none' | 'horizontal' | 'vertical' | 'both'>('horizontal');
  const [regenGenerationMode, setRegenGenerationMode] = useState<'quick' | 'pattern'>('pattern');

  // Per-level regeneration progress tracking
  const [regenProgressMap, setRegenProgressMap] = useState<Map<number, {
    status: 'waiting' | 'generating' | 'saving' | 'done' | 'failed';
    matchScore?: number;
    error?: string;
  }>>(new Map());
  const [batchRegenTotal, setBatchRegenTotal] = useState(0);

  // Regenerate single level - pure generation without bot simulation
  // 봇 시뮬레이션 없이 목표 난이도에 근접한 레벨만 생성, match_score는 일괄 테스트에서 측정
  // 모달 열기: 패턴 선택 UI 표시
  const openRegenModal = (levelNumber: number) => {
    const level = levels.find(l => l.meta.level_number === levelNumber);
    if (!level) return;

    // 레벨 타입에 따른 기본 대칭 모드 설정
    const isEarlyLevel = levelNumber <= 30;
    const isSpecialShape = levelNumber % 10 === 9;
    const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;

    let defaultSymmetry: 'none' | 'horizontal' | 'vertical' | 'both' = 'horizontal';
    if (isEarlyLevel || isBossLevel) {
      defaultSymmetry = 'both';
    } else if (isSpecialShape) {
      defaultSymmetry = 'vertical';
    }

    setRegenModalLevel(levelNumber);
    setRegenPatternIndex(undefined); // 자동 선택으로 초기화
    setRegenSymmetryMode(defaultSymmetry);
    setRegenGenerationMode('pattern'); // 기본값: 패턴 생성
    setRegenModalOpen(true);
  };

  // 모달에서 재생성 실행
  const handleRegenFromModal = async () => {
    if (regenModalLevel === null) return;
    setRegenModalOpen(false);
    // 빠른 생성 모드: 패턴 인덱스 없이 자동 선택 (각 레이어 다른 패턴)
    // 패턴 생성 모드: 선택한 패턴 인덱스 사용 (모든 레이어 동일한 위치)
    const patternIndexToUse = regenGenerationMode === 'quick' ? undefined : regenPatternIndex;
    await handleRegenerateLevel(regenModalLevel, patternIndexToUse, regenSymmetryMode);
  };

  const handleRegenerateLevel = async (
    levelNumber: number,
    userPatternIndex?: number,
    userSymmetryMode?: 'none' | 'horizontal' | 'vertical' | 'both',
    // [v16 피드백제어] difficultyOffset: 순차검증이 측정 gap으로 계산한 난이도 조정값.
    // 양수=더 어렵게(타일종류↑/층↑), 음수=더 쉽게. 표 대신 측정→조정으로 목표 수렴.
    options?: { forceNoTemplate?: boolean; difficultyOffset?: number }
  ) => {
    const level = levels.find(l => l.meta.level_number === levelNumber);
    if (!level) return;

    setRegeneratingLevels(prev => new Set([...prev, levelNumber]));
    setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'generating' }));

    try {
      // Get current batch for gimmick unlock levels
      const currentBatch = await getProductionBatch(batchId);
      if (!currentBatch) {
        throw new Error('Batch not found');
      }

      const rawTargetDifficulty = level.meta.target_difficulty;
      // Guard: corrupt levels (older format / missing meta) can have NaN/undefined/out-of-range.
      // Without this, every generated request body becomes invalid (NaN→null) → 422 across all 15 candidates.
      if (typeof rawTargetDifficulty !== 'number' || !Number.isFinite(rawTargetDifficulty)) {
        throw new Error(`레벨 ${levelNumber}의 target_difficulty가 비어있거나 잘못됨 (값=${rawTargetDifficulty}). 메타 복구 필요.`);
      }
      const targetDifficulty = Math.min(0.99, Math.max(0.01, rawTargetDifficulty));
      if (targetDifficulty !== rawTargetDifficulty) {
        console.warn(`[regen] Lv.${levelNumber}: target_difficulty=${rawTargetDifficulty}을 [0.01, 0.99] 범위로 클램프 (백엔드 ge=0.0/le=1.0 보호).`);
      }
      const targetScore = targetDifficulty * 100;

      // [v15.55+] 템플릿 기반 레벨(import한 패턴 사용 중)은 별도 경로로 재생성.
      // 메타에 template_id가 있고 사용자가 패턴/대칭을 강제 지정하지 않았다면,
      // /generate/from-template으로 같은 템플릿 모양·기믹을 유지하고 타일 색만 새 시드로 랜덤화.
      // 일반 /generate 경로는 pattern_index를 요구하지만 템플릿 레벨에는 pattern_index=-1 센티넬이
      // 저장돼 있어 백엔드 ge=0 검증을 위반하므로 422가 발생함.
      const templateId = (level.meta as { template_id?: string }).template_id;
      const userOverridingPattern = userPatternIndex !== undefined || userSymmetryMode !== undefined;
      const forceNoTemplate = options?.forceNoTemplate === true;
      // [보스 크롭] 보스(10의 배수)는 from-template을 crop_max_dim=8로 호출(A/B타입 템플릿 차용).
      // 크롭 후에도 >8(D타입)이면 템플릿 폐기하고 절차생성(boss_mode 레시피)으로 폴백.
      const isBossRegen = levelNumber % 10 === 0 && levelNumber > 0;
      // [v15.x+] 템플릿 레이아웃이 언클리어러블한 경우(모든 봇 클리어율 0%) 호출자가
      // forceNoTemplate=true 로 우회 요청. 같은 모양만 유지하는 /generate/from-template 로는
      // 데드락 모양에서 탈출 불가하므로 일반 generate 경로로 전환하고 meta.template_id 도 제거한다.
      if (templateId && !userOverridingPattern && !forceNoTemplate) {
        const seed = Math.floor(Date.now() % 1_000_000);
        const tplResp = await apiClient.post('/generate/from-template', {
          template_id: templateId,
          level_number: levelNumber,
          use_tile_count: 6,
          randomize_tiles: true,
          random_seed: seed,
          crop_max_dim: isBossRegen ? MAX_PLAYABLE_GRID : undefined,
        });
        const tplLevelJson = tplResp.data?.level_json;
        if (!tplLevelJson) {
          throw new Error('템플릿 응답에 level_json 없음');
        }
        // 보스인데 크롭해도 >8(D타입) → 템플릿 폐기, 아래 절차생성(boss_mode)으로 폴백
        if (isBossRegen && maxDeclaredGridDim(tplLevelJson) > MAX_PLAYABLE_GRID) {
          console.warn(`[regen] Lv.${levelNumber} 보스 템플릿 ${templateId} 크롭 불가(>8) → boss_mode 절차생성 폴백`);
        } else {
        const tplActualDifficulty = Number(tplResp.data?.actual_difficulty ?? 0);
        const tplGrade = String(tplResp.data?.grade ?? 'C');
        setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'saving' }));
        await saveProductionLevels(batchId, [{
          meta: {
            ...level.meta,
            generated_at: new Date().toISOString(),
            actual_difficulty: tplActualDifficulty,
            grade: tplGrade as DifficultyGrade,
            bot_clear_rates: undefined,
            match_score: undefined,
            status_updated_at: new Date().toISOString(),
            regen_attempts: (level.meta.regen_attempts || 0) + 1,
            regen_lower_bound: undefined,
            regen_upper_bound: undefined,
            // 템플릿 기반 표시 보존
            pattern_index: -1,
            pattern_type: 'aesthetic',
            template_id: templateId,
          },
          level_json: tplLevelJson,
        }]);
        setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'done' }));
        addNotification('success', `레벨 ${levelNumber} 템플릿 재생성 완료 (template=${templateId}${isBossRegen ? ', 크롭≤8' : ''})`);
        loadLevels();
        onStatsUpdate();
        return;
        }  // else (보스 크롭 가능) 끝 — D타입이면 아래 절차생성으로 폴백
      }

      // 기믹 강도를 목표 난이도로 제한 (과도한 기믹으로 난이도 초과 방지)
      const gimmickIntensity = Math.min(targetDifficulty, levelNumber / 500);
      const DIFFICULTY_TOLERANCE = 5.0; // 0.05 in 0-1 scale = 5.0 in 0-100 scale (프로덕션과 동일)
      const CANDIDATES_PER_ATTEMPT = 3;
      const MAX_ATTEMPTS = 5; // 최대 15개 후보

      // === 미형 로직: 사용자 선택이 있으면 우선, 없으면 자동 선택 ===
      const isEarlyLevel = levelNumber <= 30;
      const isSpecialShape = levelNumber % 10 === 9;
      const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;

      // Pattern type: 항상 aesthetic 사용 (64개 패턴 중 선택)
      const patternType: 'aesthetic' = 'aesthetic';

      // Symmetry mode: 사용자 선택 우선, 없으면 자동 선택
      let symmetryMode: 'none' | 'horizontal' | 'vertical' | 'both';
      if (userSymmetryMode !== undefined) {
        symmetryMode = userSymmetryMode;
      } else {
        const symmetryRoll = Math.random();
        if (isEarlyLevel) {
          symmetryMode = symmetryRoll < 0.25 ? 'horizontal' : symmetryRoll < 0.50 ? 'vertical' : 'both';
        } else if (isSpecialShape) {
          symmetryMode = symmetryRoll < 0.30 ? 'none' : symmetryRoll < 0.65 ? 'horizontal' : 'vertical';
        } else if (isBossLevel) {
          symmetryMode = symmetryRoll < 0.20 ? 'horizontal' : symmetryRoll < 0.40 ? 'vertical' : 'both';
        } else {
          symmetryMode = symmetryRoll < 0.05 ? 'none' : symmetryRoll < 0.40 ? 'horizontal' : symmetryRoll < 0.75 ? 'vertical' : 'both';
        }
      }

      // Pattern index: 사용자 선택 > 기존 레벨 패턴 > 자동 선택
      // 백엔드 스키마: pattern_index ∈ [0, 99]. 음수/범위 외 값을 보내면 422.
      // 일부 저장된 레벨 메타에 sentinel -1 또는 100+가 들어있는 경우가 있어, 명시적으로 검증.
      const isValidPatternIndex = (v: unknown): v is number =>
        typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= 99;

      let patternIndex: number | undefined = isValidPatternIndex(userPatternIndex) ? userPatternIndex : undefined;
      if (patternIndex === undefined) {
        // 기존 레벨에 유효한 패턴이 있으면 그걸 우선 사용. -1 등 잘못된 값은 무시하고 자동 재선택.
        if (isValidPatternIndex(level.meta.pattern_index)) {
          patternIndex = level.meta.pattern_index;
        } else {
          if (level.meta.pattern_index !== undefined && !isValidPatternIndex(level.meta.pattern_index)) {
            console.warn(`[regen] Lv.${levelNumber}: 저장된 pattern_index=${level.meta.pattern_index} 가 유효 범위 밖이라 무시하고 자동 재선택.`);
          }
          // 모든 레벨에 패턴 지정 (빠른 생성)
          if (isBossLevel) {
            patternIndex = BOSS_PATTERNS[Math.floor(Math.random() * BOSS_PATTERNS.length)];
          } else if (isSpecialShape) {
            patternIndex = SPECIAL_PATTERNS[Math.floor(Math.random() * SPECIAL_PATTERNS.length)];
          } else {
            // 일반 레벨: 비활성 패턴 제외 (그리드 크기별)
            let excl: Set<number>;
            try {
              const r = await apiClient.get('/debug/pattern-config?grid_size=7');
              excl = new Set(r.data.disabled_patterns || []);
            } catch { excl = new Set([5, 22, 25, 29, 39, 40, 42, 47, 54, 57, 60]); }
            const pool = Array.from({ length: 64 }, (_, i) => i).filter(i => !excl.has(i));
            patternIndex = pool[Math.floor(Math.random() * pool.length)];
          }
        }
      }
      // 마지막 안전망: 어떤 경로든 최종값이 유효 범위에 있는지 한 번 더 보장
      if (!isValidPatternIndex(patternIndex)) {
        console.warn(`[regen] Lv.${levelNumber}: 최종 patternIndex=${patternIndex}가 유효하지 않아 0으로 폴백.`);
        patternIndex = 0;
      }

      // Grid size (프로덕션과 동일)
      let gridSize: [number, number] = [7, 7];
      if (isBossLevel && targetDifficulty > 0.3) {
        gridSize = [8, 8];
      } else if (!isEarlyLevel && Math.random() < 0.3) {
        gridSize = [8, 8];
      }

      // Layers (프로덕션과 동일)
      let minLayers = 2;
      let maxLayers = Math.min(10, 3 + Math.floor(targetDifficulty * 7));
      if (isEarlyLevel) { minLayers = 2; maxLayers = Math.min(4, maxLayers); }
      else if (isBossLevel) { minLayers = Math.max(3, Math.floor(2 + targetDifficulty * 2)); maxLayers = Math.min(10, 4 + Math.floor(targetDifficulty * 6)); }

      // [v16 피드백제어] 순차검증이 측정한 gap으로 난이도 조준. 난이도함수가 고차원(타일종류·배치·층·기믹)
      // 이라 표(feed-forward)로 불가 → 측정→조정(closed-loop)으로 수렴. offset 0이면 백엔드 자동(무개입).
      const diffOffset = options?.difficultyOffset ?? 0;
      // 백엔드 생성기가 다중경로라 auto useTileCount가 불안정(같은 td에 8~9 들쭉) → 항상 명시적 tile_types로
      // 타일종류를 직접 제어. 피드백 offset이 이 값을 조준한다. round(6+2.2*max(0,td-0.15)) clamp[6,8] 기준.
      // [타일종류 고정] 재생성도 초기 생성과 동일한 그래프값(useTileCount) 유지 → 난이도 레버에서 타일종류 제외.
      // 난이도 조준은 diffOffset→층수(아래)/기믹으로만. (기존: 난이도기반 baseTileCount+diffOffset 로 종류 축소 → 그래프 붕괴)
      const steeredTileCount = Math.max(4, Math.min(15, vAtLevel(TILE_TYPE_PROFILE_CURVES[tileTypeProfile] ?? TILE_TYPE_PROFILE_CURVES.baseline, levelNumber)));
      const steeredTileTypes: string[] = Array.from({ length: steeredTileCount }, (_, i) => `t${i + 1}`);
      // 층수 보조 조정(미세 레버, offset 절반)
      if (diffOffset !== 0) {
        maxLayers = Math.max(2, Math.min(8, maxLayers + Math.trunc(diffOffset / 2)));
        minLayers = Math.min(minLayers, maxLayers);
      }

      let bestResult: GenerationResult | null = null;
      let bestGap = Infinity;
      // [v15.42] Track best fallback (playability_warning=true) separately so we only use it
      // when no clean candidate was produced across all attempts. This prevents picking
      // unclearable levels purely because their static difficulty happens to be closest to target.
      let bestFallback: GenerationResult | null = null;
      let bestFallbackGap = Infinity;
      let warningCandidatesCount = 0;
      let totalCandidatesCount = 0;

      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        const candidates = await Promise.all(
          Array.from({ length: CANDIDATES_PER_ATTEMPT }, () => {
            // Goal direction selection (프로덕션과 동일 - 대칭 모드 기반)
            let goalDirections: Array<'s' | 'n' | 'e' | 'w'>;
            if (symmetryMode === 'both' || symmetryMode === 'vertical') {
              goalDirections = Math.random() < 0.7 ? ['s', 'n'] : ['e', 'w'];
            } else if (symmetryMode === 'horizontal') {
              goalDirections = Math.random() < 0.7 ? ['e', 'w'] : ['s', 'n'];
            } else {
              goalDirections = ['s', 'n', 'e', 'w'];
            }
            const goalDirection = goalDirections[Math.floor(Math.random() * goalDirections.length)];
            const goalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];

            return generateLevel(
              {
                target_difficulty: targetDifficulty,
                grid_size: isBossLevel ? [7, 7] : gridSize, // 보스: 선언 최대 8 (디바이스 제약)
                min_layers: isBossLevel ? 5 : minLayers,
                max_layers: isBossLevel ? 6 : maxLayers,
                // 피드백 offset 있으면 조준한 타일종류, 없으면 백엔드 자동선택
                tile_types: steeredTileTypes,
                obstacle_types: [],
                goals: [{
                  type: goalType,
                  direction: goalDirection,
                  count: Math.max(2, Math.floor(3 + targetDifficulty * 2))
                }],
                symmetry_mode: symmetryMode,
                pattern_type: patternType,
                // 보스: pattern_index 미지정 → 백엔드 BOSS_RECIPES(레벨번호 결정적) 적용
                pattern_index: isBossLevel ? undefined : patternIndex,
                // [보스 생성기]
                boss_mode: isBossLevel || undefined,
              },
              {
                auto_select_gimmicks: true,
                available_gimmicks: ['craft', 'stack', 'chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
                gimmick_intensity: gimmickIntensity,
                gimmick_unlock_levels: currentBatch.gimmick_unlock_levels || PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
                level_number: levelNumber,
              }
            ).catch((err: any) => {
              // Surface the first generate failure per regen so we don't silently lose visibility.
              const status = err?.response?.status;
              const detail = err?.response?.data;
              console.warn(
                `[regen] Lv.${levelNumber} 후보 생성 실패 (attempt ${attempt + 1}) status=${status}`,
                detail || err?.message
              );
              return null;
            });
          })
        );

        for (const c of candidates) {
          if (!c) continue;
          totalCandidatesCount++;
          const gap = Math.abs(c.actual_difficulty - targetScore);
          // 데드락 미해소 후보(클리어율 < 10%)는 봇 검증에서 거의 항상 실패하므로 후순위로 격리
          if (c.playability_warning) {
            warningCandidatesCount++;
            if (gap < bestFallbackGap) {
              bestFallbackGap = gap;
              bestFallback = c;
            }
            continue;
          }
          if (gap < bestGap) {
            bestGap = gap;
            bestResult = c;
          }
        }

        if (bestResult && bestGap <= DIFFICULTY_TOLERANCE) break; // 허용 오차 이내 → 즉시 채택
      }

      // 클린 후보가 하나도 없을 때만 워닝 후보로 폴백
      if (!bestResult && bestFallback) {
        console.warn(
          `[regen] Lv.${levelNumber}: 모든 ${totalCandidatesCount}개 후보가 playability_warning. 폴백 후보 채택 (clear_rate≈${(bestFallback.estimated_clear_rate ?? 0).toFixed(2)}).`
        );
        bestResult = bestFallback;
      } else if (warningCandidatesCount > 0) {
        console.info(
          `[regen] Lv.${levelNumber}: ${warningCandidatesCount}/${totalCandidatesCount} 후보를 playability_warning으로 배제했습니다.`
        );
      }

      if (!bestResult) {
        throw new Error(`${MAX_ATTEMPTS * CANDIDATES_PER_ATTEMPT}개 후보 모두 실패`);
      }
      const result = bestResult;

      // Save regenerated level - match_score/bot_clear_rates는 비워둠 (일괄 테스트에서 측정)
      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'saving' }));
      // forceNoTemplate/보스 재생성으로 진입한 경우 향후 재생성에서 다시 템플릿 경로로 빠지지 않도록
      // template_id 를 명시적으로 제거하고, 일반 generate 의 verified 패턴 정보를 기록한다.
      const baseMetaForSave: ProductionLevelMeta = (forceNoTemplate || isBossRegen)
        ? (() => {
            const m: Record<string, unknown> = { ...(level.meta as unknown as Record<string, unknown>) };
            delete m.template_id;
            return m as unknown as ProductionLevelMeta;
          })()
        : level.meta;
      // [비주얼 시드 bake] 재생성분도 1~15 중 useTileCount개 랜덤 다양색 relabel (첫생성과 동일).
      // 누락 시 재생성 레벨만 순차색(t1..tN)으로 남아 비주얼 다양성 손실 → 여기서 보정.
      applyProductionTileVisuals(result.level_json, levelNumber);
      await saveProductionLevels(batchId, [{
        meta: {
          ...baseMetaForSave,
          generated_at: new Date().toISOString(),
          actual_difficulty: result.actual_difficulty,
          grade: result.grade as any,
          bot_clear_rates: undefined,
          match_score: undefined,
          status_updated_at: new Date().toISOString(),
          regen_attempts: (level.meta.regen_attempts || 0) + 1,
          regen_lower_bound: undefined,
          regen_upper_bound: undefined,
          // 패턴 정보 보존 (사용자 선택 또는 기존 패턴)
          pattern_index: patternIndex,
          pattern_type: patternType,
        },
        level_json: result.level_json,
      }]);

      // Update batch test results if exists (remove regenerated level from results - needs re-test)
      setBatchTestProgress(prev => ({
        ...prev,
        results: prev.results.filter(r => r.level_number !== levelNumber),
      }));

      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'done' }));
      addNotification('success', `레벨 ${levelNumber} 재생성 완료 (정적 추정 ${result.actual_difficulty.toFixed(1)} — 실제 난이도는 순차검증 RL 측정값)`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error(`Regeneration failed for level ${levelNumber}:`, errMsg, err);
      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'failed', error: errMsg }));
      addNotification('error', `레벨 ${levelNumber} 재생성 실패: ${errMsg}`);
    } finally {
      setRegeneratingLevels(prev => {
        const newSet = new Set(prev);
        newSet.delete(levelNumber);
        return newSet;
      });
    }
  };

  // Enhance existing level (incremental difficulty adjustment instead of full regeneration)
  const handleEnhanceLevel = async (levelNumber: number) => {
    const level = levels.find(l => l.meta.level_number === levelNumber);
    if (!level || !level.level_json) return;

    setEnhancingLevels(prev => new Set([...prev, levelNumber]));

    try {
      const result = await enhanceLevel({
        level_json: level.level_json,
        target_difficulty: level.meta.target_difficulty,
        max_iterations: 5,
        simulation_iterations: 50,
      });

      // Calculate match score for meta update
      const matchScore = result.match_score;

      // Save enhanced level
      // [v15.14] novice/casual은 optional
      const botRates = result.bot_clear_rates as { novice?: number; casual?: number; average: number; expert: number; optimal: number };
      // [비주얼 시드 bake] enhance 결과도 다양색 relabel (누락 방지)
      applyProductionTileVisuals(result.level_json, levelNumber);
      await saveProductionLevels(batchId, [{
        meta: {
          ...level.meta,
          generated_at: new Date().toISOString(),
          bot_clear_rates: botRates,
          match_score: matchScore,
          status_updated_at: new Date().toISOString(),
        },
        level_json: result.level_json,
      }]);

      // Update batch test results if exists
      setBatchTestProgress(prev => ({
        ...prev,
        results: prev.results.map(r =>
          r.level_number === levelNumber
            ? { ...r, match_score: matchScore }
            : r
        ),
      }));

      const modsText = result.modifications.length > 0
        ? result.modifications.join(', ')
        : '변경 없음';
      addNotification(
        result.enhanced ? 'success' : 'info',
        `레벨 ${levelNumber} 개선 ${result.enhanced ? '완료' : '미개선'}: ${modsText} (일치도: ${matchScore.toFixed(0)}%)`
      );
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Enhancement failed:', err);
      addNotification('error', `레벨 ${levelNumber} 개선 실패`);
    } finally {
      setEnhancingLevels(prev => {
        const newSet = new Set(prev);
        newSet.delete(levelNumber);
        return newSet;
      });
    }
  };

  // === 일괄 재생성 공통 로직 (프로덕션 초기 생성과 동일한 고속 패턴) ===
  // batch 조회 1회, generateLevel 직접 호출, 저장은 배치 단위로 묶어서 처리
  const batchRegenerateCore = async (targetLevelNumbers: number[]) => {
    if (targetLevelNumbers.length === 0) return;

    // 1. batch 정보 1회만 조회
    const currentBatch = await getProductionBatch(batchId);
    if (!currentBatch) {
      addNotification('error', 'Batch not found');
      return;
    }
    const gimmickUnlockLevels = currentBatch.gimmick_unlock_levels || PROFESSIONAL_GIMMICK_UNLOCK_LEVELS;

    // 2. Initialize progress tracking
    const initMap = new Map<number, { status: 'waiting' | 'generating' | 'saving' | 'done' | 'failed'; matchScore?: number; error?: string }>();
    targetLevelNumbers.forEach(n => initMap.set(n, { status: 'waiting' }));
    setRegenProgressMap(initMap);
    setBatchRegenTotal(targetLevelNumbers.length);
    setIsBatchRegenerating(true);

    let successCount = 0;
    let failCount = 0;
    const REGEN_CONCURRENCY = 20; // 동시성 증가로 속도 개선

    // 3. 레벨 1개 재생성: 반복 생성으로 오차 0.05 이내 달성 (프로덕션과 동일)
    // [v15.6] 개선: 점진적 허용오차 + 재시도 로직
    const BASE_TOLERANCE = 5.0; // 0.05 in 0-1 scale = 5.0 in 0-100 scale (프로덕션과 동일)
    const CANDIDATES_PER_ATTEMPT = 3;
    const MAX_ATTEMPTS = 6; // 최대 18개 후보 (5→6 증가)

    const regenerateOne = async (levelNumber: number): Promise<void> => {
      const level = levels.find(l => l.meta.level_number === levelNumber);
      if (!level) throw new Error(`Level ${levelNumber} not found`);

      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'generating' }));

      const targetDifficulty = level.meta.target_difficulty;
      const targetScore = targetDifficulty * 100;
      // 기믹 강도를 목표 난이도로 제한 (과도한 기믹으로 난이도 초과 방지)
      const gimmickIntensity = Math.min(targetDifficulty, levelNumber / 500);

      // === 레벨 타입 기반 패턴 선택 ===
      const isEarlyLevel = levelNumber <= 30;
      const isSpecialShape = levelNumber % 10 === 9;
      const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;

      // Pattern type: 항상 aesthetic 사용 (64개 패턴 중 선택)
      const patternType: 'aesthetic' = 'aesthetic';

      // Symmetry mode selection (프로덕션과 동일)
      const symmetryRoll = Math.random();
      let symmetryMode: 'none' | 'horizontal' | 'vertical' | 'both';
      if (isEarlyLevel) {
        symmetryMode = symmetryRoll < 0.25 ? 'horizontal' : symmetryRoll < 0.50 ? 'vertical' : 'both';
      } else if (isSpecialShape) {
        symmetryMode = symmetryRoll < 0.30 ? 'none' : symmetryRoll < 0.65 ? 'horizontal' : 'vertical';
      } else if (isBossLevel) {
        symmetryMode = symmetryRoll < 0.20 ? 'horizontal' : symmetryRoll < 0.40 ? 'vertical' : 'both';
      } else {
        symmetryMode = symmetryRoll < 0.05 ? 'none' : symmetryRoll < 0.40 ? 'horizontal' : symmetryRoll < 0.75 ? 'vertical' : 'both';
      }

      // Pattern index: 기존 레벨 패턴 > 자동 선택. 저장된 값이 음수/범위 밖이면 자동 재선택으로 폴백.
      const isValidPatternIndexBatch = (v: unknown): v is number =>
        typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= 99;
      let patternIndex: number | undefined = undefined;
      if (isValidPatternIndexBatch(level.meta.pattern_index)) {
        patternIndex = level.meta.pattern_index;
      } else {
        if (level.meta.pattern_index !== undefined) {
          console.warn(`[batchRegen] Lv.${levelNumber}: 저장된 pattern_index=${level.meta.pattern_index} 무시 후 자동 재선택.`);
        }
        // 모든 레벨에 패턴 지정 (빠른 생성)
        if (isBossLevel) {
          patternIndex = BOSS_PATTERNS[Math.floor(Math.random() * BOSS_PATTERNS.length)];
        } else if (isSpecialShape) {
          patternIndex = SPECIAL_PATTERNS[Math.floor(Math.random() * SPECIAL_PATTERNS.length)];
        } else {
          // 일반 레벨: 비활성 패턴 제외 (그리드 크기별)
          let excl2: Set<number>;
          try {
            const r2 = await apiClient.get('/debug/pattern-config?grid_size=7');
            excl2 = new Set(r2.data.disabled_patterns || []);
          } catch { excl2 = new Set([5, 22, 25, 29, 39, 40, 42, 47, 54, 57, 60]); }
          const pool = Array.from({ length: 64 }, (_, i) => i).filter(i => !excl2.has(i));
          patternIndex = pool[Math.floor(Math.random() * pool.length)];
        }
      }
      if (!isValidPatternIndexBatch(patternIndex)) {
        patternIndex = 0;
      }

      // Grid size (프로덕션과 동일)
      let gridSize: [number, number] = [7, 7];
      if (isBossLevel && targetDifficulty > 0.3) {
        gridSize = [8, 8];
      } else if (!isEarlyLevel && Math.random() < 0.3) {
        gridSize = [8, 8];
      }

      // Layers (프로덕션과 동일)
      let minLayers = 2;
      let maxLayers = Math.min(10, 3 + Math.floor(targetDifficulty * 7));
      if (isEarlyLevel) { minLayers = 2; maxLayers = Math.min(4, maxLayers); }
      else if (isBossLevel) { minLayers = Math.max(3, Math.floor(2 + targetDifficulty * 2)); maxLayers = Math.min(10, 4 + Math.floor(targetDifficulty * 6)); }

      let bestResult: GenerationResult | null = null;
      let bestGap = Infinity;
      let totalCandidates = 0;

      // Helper: 단일 후보 생성 (1회 재시도 포함)
      const generateOneCandidate = async (
        goalDirection: 's' | 'n' | 'e' | 'w',
        goalType: 'craft' | 'stack',
        layerVar: number,
        intensityMult: number
      ): Promise<GenerationResult | null> => {
        const params = {
          target_difficulty: targetDifficulty,
          grid_size: (isBossLevel ? [7, 7] : gridSize) as [number, number], // 보스: 선언 최대 8
          min_layers: isBossLevel ? 5 : Math.max(2, minLayers + layerVar),
          max_layers: isBossLevel ? 6 : Math.min(10, maxLayers + layerVar),
          tile_types: undefined,
          obstacle_types: [],
          goals: [{ type: goalType, direction: goalDirection, count: Math.max(2, Math.floor(3 + targetDifficulty * 2)) }],
          symmetry_mode: symmetryMode,
          pattern_type: patternType,
          // 보스: pattern_index 미지정 → BOSS_RECIPES 적용
          pattern_index: isBossLevel ? undefined : patternIndex,
          // [보스 생성기]
          boss_mode: isBossLevel || undefined,
        };
        const gimmickOpts = {
          auto_select_gimmicks: true,
          available_gimmicks: ['craft', 'stack', 'chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
          gimmick_intensity: gimmickIntensity * intensityMult,
          gimmick_unlock_levels: gimmickUnlockLevels,
          level_number: levelNumber,
        };
        try {
          return await generateLevel(params, gimmickOpts);
        } catch {
          // 1회 재시도
          try {
            return await generateLevel(params, gimmickOpts);
          } catch {
            return null;
          }
        }
      };

      const layerVariations = [-1, 0, 1];
      const intensityMultipliers = [0.8, 1.0, 1.2];

      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        // 점진적 허용오차
        const currentTolerance = attempt < 3 ? BASE_TOLERANCE :
                                  attempt < 5 ? BASE_TOLERANCE * 1.5 :
                                  BASE_TOLERANCE * 2.0;

        const candidates = await Promise.all(
          Array.from({ length: CANDIDATES_PER_ATTEMPT }, (_, idx) => {
            // Goal direction selection (프로덕션과 동일 - 대칭 모드 기반)
            let goalDirections: Array<'s' | 'n' | 'e' | 'w'>;
            if (symmetryMode === 'both' || symmetryMode === 'vertical') {
              goalDirections = Math.random() < 0.7 ? ['s', 'n'] : ['e', 'w'];
            } else if (symmetryMode === 'horizontal') {
              goalDirections = Math.random() < 0.7 ? ['e', 'w'] : ['s', 'n'];
            } else {
              goalDirections = ['s', 'n', 'e', 'w'];
            }
            const goalDirection = goalDirections[Math.floor(Math.random() * goalDirections.length)];
            const goalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];
            const layerVar = layerVariations[idx % layerVariations.length];
            const intensityMult = intensityMultipliers[idx % intensityMultipliers.length];

            return generateOneCandidate(goalDirection, goalType, layerVar, intensityMult);
          })
        );

        totalCandidates += CANDIDATES_PER_ATTEMPT;

        for (const c of candidates) {
          if (!c) continue;
          const gap = Math.abs(c.actual_difficulty - targetScore);
          if (gap < bestGap) {
            bestGap = gap;
            bestResult = c;
          }
        }

        if (bestGap <= currentTolerance) break; // 현재 허용 오차 이내 → 즉시 채택
      }

      if (!bestResult) {
        console.error(`Regen level ${levelNumber}: All ${totalCandidates} candidates failed (API errors)`);
        throw new Error(`${totalCandidates}개 후보 모두 API 실패`);
      }

      if (bestGap > BASE_TOLERANCE) {
        console.warn(`Regen level ${levelNumber}: Using best-match fallback (gap: ${bestGap.toFixed(1)}%)`);
      }

      // Save - match_score/bot_clear_rates는 비워둠 (일괄 테스트에서 측정)
      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'saving' }));
      // [비주얼 시드 bake] 재생성분 다양색 relabel (누락 방지)
      applyProductionTileVisuals(bestResult.level_json, levelNumber);
      await saveProductionLevels(batchId, [{
        meta: {
          ...level.meta,
          generated_at: new Date().toISOString(),
          actual_difficulty: bestResult.actual_difficulty,
          grade: bestResult.grade as any,
          bot_clear_rates: undefined,
          match_score: undefined,
          status_updated_at: new Date().toISOString(),
          regen_attempts: (level.meta.regen_attempts || 0) + 1,
          regen_lower_bound: undefined,
          regen_upper_bound: undefined,
          // 패턴 정보 보존
          pattern_index: patternIndex,
          pattern_type: patternType,
        },
        level_json: bestResult.level_json,
      }]);

      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'done' }));
    };

    // 4. Execute in parallel batches (프로덕션 초기 생성과 동일한 패턴)
    for (let batchStart = 0; batchStart < targetLevelNumbers.length; batchStart += REGEN_CONCURRENCY) {
      const batchSlice = targetLevelNumbers.slice(batchStart, batchStart + REGEN_CONCURRENCY);
      const results = await Promise.allSettled(
        batchSlice.map(num => regenerateOne(num))
      );
      for (const r of results) {
        if (r.status === 'fulfilled') successCount++;
        else {
          failCount++;
          const reason = r.reason instanceof Error ? r.reason.message : String(r.reason);
          const failedNum = batchSlice[results.indexOf(r)];
          setRegenProgressMap(prev => new Map(prev).set(failedNum, { status: 'failed', error: reason }));
        }
      }
    }

    // 5. 완료 후 1회만 리로드
    setIsBatchRegenerating(false);
    loadLevels();
    onStatsUpdate();
    return { successCount, failCount };
  };

  // Batch regenerate low match score levels from test results
  const handleBatchRegenerate = async () => {
    const lowMatchLevels = batchTestProgress.results
      .filter(r => r.match_score < regenerationThreshold)
      .sort((a, b) => a.match_score - b.match_score);
    if (lowMatchLevels.length === 0) {
      addNotification('info', `일치도 ${regenerationThreshold}% 미만 레벨이 없습니다.`);
      return;
    }
    const levelNumbers = lowMatchLevels.map(l => l.level_number);
    const result = await batchRegenerateCore(levelNumbers);
    if (result) {
      // Remove regenerated levels from results (needs re-test)
      setBatchTestProgress(prev => ({
        ...prev,
        results: prev.results.filter(r => !levelNumbers.includes(r.level_number)),
      }));
      addNotification('success', `일괄 재생성 완료: ${result.successCount}개 성공, ${result.failCount}개 실패`);
    }
  };

  // Batch regenerate low match score levels from stored level data
  const handleBatchRegenerateFromStored = async () => {
    const storedLowMatch = levels
      .filter(l => l.meta.match_score !== undefined && l.meta.match_score > 0 && l.meta.match_score < regenerationThreshold)
      .sort((a, b) => (a.meta.match_score || 0) - (b.meta.match_score || 0));
    if (storedLowMatch.length === 0) {
      addNotification('info', `저장된 일치도 ${regenerationThreshold}% 미만 레벨이 없습니다.`);
      return;
    }
    const result = await batchRegenerateCore(storedLowMatch.map(l => l.meta.level_number));
    if (result) addNotification('success', `저장된 미달 레벨 일괄 재생성 완료: ${result.successCount}개 성공, ${result.failCount}개 실패`);
  };

  // Batch regenerate selected levels only
  const handleRegenerateSelected = async () => {
    if (selectedRegenLevels.size === 0) {
      addNotification('info', '선택된 레벨이 없습니다.');
      return;
    }
    const targetLevels = [...selectedRegenLevels].sort((a, b) => {
      const aScore = levels.find(l => l.meta.level_number === a)?.meta.match_score || 0;
      const bScore = levels.find(l => l.meta.level_number === b)?.meta.match_score || 0;
      return aScore - bScore;
    });
    const result = await batchRegenerateCore(targetLevels);
    if (result) {
      setSelectedRegenLevels(new Set());
      addNotification('success', `선택 레벨 재생성 완료: ${result.successCount}개 성공, ${result.failCount}개 실패`);
    }
  };

  // Select levels within range from filtered levels list
  const handleSelectRange = useCallback(() => {
    const start = Math.min(rangeStart, rangeEnd);
    const end = Math.max(rangeStart, rangeEnd);
    const levelsInRange = levels.filter(l =>
      l.meta.level_number >= start && l.meta.level_number <= end
    );
    if (levelsInRange.length === 0) {
      addNotification('info', `범위 ${start}~${end}에 레벨이 없습니다.`);
      return;
    }
    setSelectedRegenLevels(new Set(levelsInRange.map(l => l.meta.level_number)));
    addNotification('success', `${levelsInRange.length}개 레벨 선택됨 (${start}~${end})`);
  }, [rangeStart, rangeEnd, levels, addNotification]);

  // Add range to existing selection
  const handleAddRangeToSelection = useCallback(() => {
    const start = Math.min(rangeStart, rangeEnd);
    const end = Math.max(rangeStart, rangeEnd);
    const levelsInRange = levels.filter(l =>
      l.meta.level_number >= start && l.meta.level_number <= end
    );
    if (levelsInRange.length === 0) {
      addNotification('info', `범위 ${start}~${end}에 레벨이 없습니다.`);
      return;
    }
    setSelectedRegenLevels(prev => {
      const next = new Set(prev);
      levelsInRange.forEach(l => next.add(l.meta.level_number));
      return next;
    });
    addNotification('success', `${levelsInRange.length}개 레벨 추가됨`);
  }, [rangeStart, rangeEnd, levels, addNotification]);

  // Quick select first/last N levels
  const handleQuickSelect = useCallback((type: 'first' | 'last', count: number) => {
    const sorted = [...levels].sort((a, b) => a.meta.level_number - b.meta.level_number);
    const selected = type === 'first' ? sorted.slice(0, count) : sorted.slice(-count);
    if (selected.length === 0) {
      addNotification('info', '선택할 레벨이 없습니다.');
      return;
    }
    setSelectedRegenLevels(new Set(selected.map(l => l.meta.level_number)));
    const first = selected[0].meta.level_number;
    const last = selected[selected.length - 1].meta.level_number;
    addNotification('success', `${selected.length}개 레벨 선택됨 (${first}~${last})`);
  }, [levels, addNotification]);

  // Filtered levels based on search and filter
  const filteredLevels = useMemo(() => {
    let result = levels;

    // Apply filter
    if (filter === 'low_match') {
      result = result.filter(l =>
        l.meta.match_score !== undefined && l.meta.match_score < 70
      );
    } else if (filter === 'untested') {
      result = result.filter(l =>
        l.meta.match_score === undefined || l.meta.match_score === 0
      );
    } else if (filter !== 'all') {
      result = result.filter(l => l.meta.status === filter);
    }

    // Apply search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(l =>
        l.meta.level_number.toString().includes(query) ||
        l.meta.grade.toLowerCase().includes(query)
      );
    }

    return result;
  }, [levels, searchQuery, filter]);

  const handleSelectLevel = (level: ProductionLevel) => {
    setSelectedLevel(level);
  };

  const handlePlayLevel = () => {
    if (!selectedLevel) return;
    setIsPlaying(true);
    setShowResultForm(false);
    setGameResult(null);
  };

  const handleGameEnd = (won: boolean, stats: GameStats) => {
    setGameResult({ won, stats });
    setShowResultForm(true);
    setIsPlaying(false);

    // Pre-fill perceived difficulty based on game result
    if (!won) {
      setPerceivedDifficulty(5);
    } else if (stats.moves > 50) {
      setPerceivedDifficulty(4);
    } else if (stats.moves > 30) {
      setPerceivedDifficulty(3);
    } else if (stats.moves > 15) {
      setPerceivedDifficulty(2);
    } else {
      setPerceivedDifficulty(1);
    }
  };

  const handleBack = () => {
    setIsPlaying(false);
  };

  const handleSubmitResult = async () => {
    if (!selectedLevel || !gameResult) return;

    const result: PlaytestResult = {
      tester_id: 'production_tester',
      tester_name: '프로덕션 테스터',
      tested_at: new Date().toISOString(),
      cleared: gameResult.won,
      attempts: 1,
      time_seconds: gameResult.stats.timeElapsed,
      perceived_difficulty: perceivedDifficulty,
      fun_rating: funRating,
      comments,
      issues,
    };

    try {
      await addPlaytestResult(batchId, selectedLevel.meta.level_number, result);
      addNotification('success', `레벨 ${selectedLevel.meta.level_number} 테스트 결과 저장됨`);

      // Reset form
      setShowResultForm(false);
      setGameResult(null);
      setPerceivedDifficulty(3);
      setFunRating(3);
      setComments('');
      setIssues([]);

      // Reload levels and update stats
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      addNotification('error', '결과 저장 실패');
    }
  };

  const handleSkipResult = () => {
    setShowResultForm(false);
    setGameResult(null);
    setPerceivedDifficulty(3);
    setFunRating(3);
    setComments('');
    setIssues([]);
  };

  // Level info for game player
  const levelInfo: LevelInfo | undefined = selectedLevel
    ? {
        id: `production_${selectedLevel.meta.level_number}`,
        name: `레벨 ${selectedLevel.meta.level_number}`,
        source: 'local' as const,
        difficulty: selectedLevel.meta.actual_difficulty,
        totalTiles: 0,
        layers: 0,
      }
    : undefined;

  // Playing view
  if (isPlaying && selectedLevel) {
    return (
      <div className="h-[calc(100vh-200px)] min-h-[700px] relative">
        <GamePlayer
          levelData={selectedLevel.level_json as unknown as Record<string, unknown>}
          levelInfo={levelInfo}
          onGameEnd={handleGameEnd}
          onBack={handleBack}
        />
      </div>
    );
  }

  // Result form view
  if (showResultForm && selectedLevel && gameResult) {
    return (
      <div className="p-4 space-y-4">
        <div className="p-4 bg-gray-800 rounded-lg">
          <h3 className="text-lg font-medium text-white mb-4">
            레벨 {selectedLevel.meta.level_number} 테스트 결과
          </h3>

          {/* Game result summary */}
          <div className={`p-4 rounded-lg mb-4 ${gameResult.won ? 'bg-green-900/30' : 'bg-red-900/30'}`}>
            <div className="flex items-center justify-between">
              <span className={`text-lg font-bold ${gameResult.won ? 'text-green-400' : 'text-red-400'}`}>
                {gameResult.won ? '클리어 성공!' : '클리어 실패'}
              </span>
              <div className="text-sm text-gray-300">
                <span className="mr-4">시간: {Math.floor(gameResult.stats.timeElapsed / 60)}분 {gameResult.stats.timeElapsed % 60}초</span>
                <span className="mr-4">이동: {gameResult.stats.moves}회</span>
                <span>점수: {gameResult.stats.score}</span>
              </div>
            </div>
          </div>

          {/* Rating form */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">체감 난이도</label>
              <select
                value={perceivedDifficulty}
                onChange={(e) => setPerceivedDifficulty(Number(e.target.value) as 1|2|3|4|5)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value={1}>1 - 매우 쉬움</option>
                <option value={2}>2 - 쉬움</option>
                <option value={3}>3 - 보통</option>
                <option value={4}>4 - 어려움</option>
                <option value={5}>5 - 매우 어려움</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">재미 점수</label>
              <select
                value={funRating}
                onChange={(e) => setFunRating(Number(e.target.value) as 1|2|3|4|5)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value={1}>1 - 지루함</option>
                <option value={2}>2 - 별로</option>
                <option value={3}>3 - 보통</option>
                <option value={4}>4 - 재미있음</option>
                <option value={5}>5 - 매우 재미있음</option>
              </select>
            </div>
          </div>

          <div className="mb-4">
            <label className="block text-sm text-gray-400 mb-1">코멘트</label>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="레벨에 대한 의견을 작성하세요..."
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
              rows={3}
            />
          </div>

          <div className="mb-4">
            <label className="block text-sm text-gray-400 mb-1">발견된 문제점</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {['불공정', '너무 쉬움', '너무 어려움', '막힘', '버그', '밸런스'].map((issue) => (
                <button
                  key={issue}
                  onClick={() => {
                    if (issues.includes(issue)) {
                      setIssues(issues.filter(i => i !== issue));
                    } else {
                      setIssues([...issues, issue]);
                    }
                  }}
                  className={`px-2 py-1 text-xs rounded ${
                    issues.includes(issue)
                      ? 'bg-red-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  {issue}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <Button onClick={handleSubmitResult} className="flex-1">
              결과 저장
            </Button>
            <Button onClick={handleSkipResult} variant="secondary">
              건너뛰기
            </Button>
            <Button onClick={handlePlayLevel} variant="secondary">
              다시 플레이
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Level selection view
  return (
    <div className="flex flex-col gap-4 h-[calc(100vh-250px)] min-h-[600px]">
      {/* Test Mode Tabs */}
      <div className="flex gap-2 bg-gray-800 p-2 rounded-lg">
        <button
          onClick={() => setTestMode('manual')}
          className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            testMode === 'manual'
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          🎮 수동 플레이
        </button>
        <button
          onClick={() => setTestMode('auto_single')}
          className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            testMode === 'auto_single'
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          🤖 자동 (개별)
        </button>
        <button
          onClick={() => setTestMode('auto_batch')}
          className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            testMode === 'auto_batch'
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          🚀 자동 (일괄)
        </button>
      </div>

      {/* [RL 검증 기준 실력 표시] 이 배치 자동/순차 검증 RL이 쓰는 skill_mean. 값이 낮으면(약한
          유저 가정) 예측 클리어율↓ → 통과 어려움. 조절은 생성 탭의 '난이도 기준 실력' 슬라이더. */}
      <div className="flex items-center justify-between bg-gray-800/70 border border-gray-700 rounded-lg px-4 py-2">
        <span className="text-xs text-gray-400">
          🎮 검증 기준 실력 <span className="text-gray-500">(skill_mean · RL 난이도 기준)</span>
        </span>
        <span className="text-sm font-mono flex items-center gap-1.5">
          <span className={rlSkillMean >= 0.6 ? 'text-emerald-400 font-bold' : rlSkillMean >= 0.5 ? 'text-yellow-400 font-bold' : 'text-orange-400 font-bold'}>
            {rlSkillMean.toFixed(2)}
          </span>
          <span className="text-[11px] text-gray-500">
            {rlSkillMean >= 0.7 ? '고수' : rlSkillMean >= 0.55 ? '중상급' : rlSkillMean >= 0.45 ? '캐주얼' : '초보'} 기준
          </span>
        </span>
      </div>

      {/* Sequential Auto Process Panel - auto_single mode */}
      {testMode === 'auto_single' && (() => {
        const untestedLevels = levels.filter(l => !l.meta.match_score || l.meta.match_score === 0);
        // 동적 컷오프 사용 — handleSequentialProcess 와 동일 기준이어야 통과/실패 표시가 일치한다.
        // [v16] verification_passed가 true면(튜토리얼 1~10 쉬움 허용 포함) 실패로 안 잡음.
        const failedLevels = levels.filter(l => {
          if (l.meta.verification_passed === true) return false; // 통과(튜토리얼 예외 포함)
          return l.meta.match_score !== undefined &&
            l.meta.match_score > 0 &&
            l.meta.match_score < computeSequentialPassThreshold(l.meta.target_difficulty);
        });
        const targetLevels = [...untestedLevels, ...failedLevels].sort((a, b) => a.meta.level_number - b.meta.level_number);
        const allSelected = targetLevels.length > 0 && targetLevels.every(l => selectedSequentialLevels.has(l.meta.level_number));

        return targetLevels.length > 0 || isSequentialProcessing ? (
          <div className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-white">🔄 순차 자동 처리</h3>
              <span className="text-xs text-gray-400">
                미측정: <span className="text-blue-400 font-medium">{untestedLevels.length}개</span>
                {' / '}미달: <span className="text-orange-400 font-medium">{failedLevels.length}개</span>
              </span>
            </div>

            {/* [RL 실력 기준 표시] 순차검증 RL이 사용하는 skill_mean(난이도 기준 실력). 생성/검증
                난이도 기준값 — GenerateTab 슬라이더에서 조절. 낮으면(약한 유저 가정) 통과 어려움. */}
            <div className="flex items-center justify-between bg-gray-900/50 border border-gray-700 rounded px-3 py-2">
              <span className="text-xs text-gray-400">🎮 검증 기준 실력 (skill_mean)</span>
              <span className="text-xs font-mono">
                <span className={rlSkillMean >= 0.6 ? 'text-emerald-400 font-semibold' : rlSkillMean >= 0.5 ? 'text-yellow-400 font-semibold' : 'text-orange-400 font-semibold'}>
                  {rlSkillMean.toFixed(2)}
                </span>
                <span className="text-gray-500">
                  {' '}({rlSkillMean >= 0.7 ? '고수' : rlSkillMean >= 0.55 ? '중상급' : rlSkillMean >= 0.45 ? '캐주얼' : '초보'} 기준)
                </span>
              </span>
            </div>

            <p className="text-xs text-gray-500">
              테스트 → 미달 시 재생성 → 재테스트 반복 (최대 5회). 통과 컷은 70%, 어려운 레벨(target ≥ 0.5)은 BE tolerance에 맞춰 최소 61%까지 완화.
            </p>

            {/* Progress Display */}
            {isSequentialProcessing && (
              <div className="bg-gray-900/60 border border-gray-600 rounded-lg p-3 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-300 font-medium">
                    Lv.{sequentialProgress.currentLevel} {sequentialProgress.status === 'testing' ? '테스트 중' : '재생성 중'}
                    {' '}(시도 {sequentialProgress.currentAttempt}/{sequentialProgress.maxAttempts})
                  </span>
                  <span className="text-gray-400">
                    {sequentialProgress.currentIndex + 1} / {sequentialProgress.total}
                  </span>
                </div>
                <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all ${sequentialProgress.status === 'testing' ? 'bg-blue-500' : 'bg-orange-500'}`}
                    style={{ width: `${((sequentialProgress.currentIndex + 1) / sequentialProgress.total) * 100}%` }}
                  />
                </div>
                {sequentialProgress.results.length > 0 && (
                  <div className="flex gap-2 text-xs">
                    <span className="text-green-400">✓ 통과: {sequentialProgress.results.filter(r => r.success).length}</span>
                    <span className="text-red-400">✗ 실패: {sequentialProgress.results.filter(r => !r.success).length}</span>
                  </div>
                )}
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex items-center gap-2">
              {isSequentialProcessing ? (
                <Button onClick={handleStopSequentialProcess} variant="danger" size="sm" className="flex-1">
                  ⏹️ 중지
                </Button>
              ) : (
                <>
                  <Button
                    onClick={() => handleSequentialProcess(targetLevels.map(l => l.meta.level_number))}
                    disabled={targetLevels.length === 0}
                    size="sm"
                    className="flex-1 bg-blue-600 hover:bg-blue-500"
                  >
                    🚀 전체 {targetLevels.length}개 순차 처리
                  </Button>
                  <Button
                    onClick={() => handleSequentialProcess([...selectedSequentialLevels])}
                    disabled={selectedSequentialLevels.size === 0}
                    size="sm"
                    className={`flex-1 ${selectedSequentialLevels.size > 0 ? 'bg-indigo-600 hover:bg-indigo-500' : 'bg-gray-600'}`}
                  >
                    🎯 선택 {selectedSequentialLevels.size}개 처리
                  </Button>
                </>
              )}
            </div>

            {/* Level Selection List */}
            {!isSequentialProcessing && targetLevels.length > 0 && (
              <div className="border border-gray-700 rounded-lg overflow-hidden">
                <div className="flex items-center px-3 py-2 bg-gray-700/50 text-xs text-gray-400">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedSequentialLevels(new Set(targetLevels.map(l => l.meta.level_number)));
                        } else {
                          setSelectedSequentialLevels(new Set());
                        }
                      }}
                      className="w-3 h-3"
                    />
                    전체 선택
                  </label>
                  <span className="ml-auto">레벨</span>
                  <span className="w-14 text-center">일치도</span>
                  <span className="w-12 text-center">등급</span>
                </div>
                <div className="max-h-[150px] overflow-y-auto">
                  {targetLevels.slice(0, 50).map((level, index) => {
                    const isUntested = !level.meta.match_score || level.meta.match_score === 0;
                    const levelNum = level.meta.level_number;
                    return (
                      <label
                        key={levelNum}
                        className={`flex items-center px-3 py-1.5 hover:bg-gray-700/30 cursor-pointer text-xs ${
                          selectedSequentialLevels.has(levelNum) ? 'bg-indigo-900/30' : ''
                        }`}
                        onClick={(e) => {
                          e.preventDefault();
                          const isChecked = selectedSequentialLevels.has(levelNum);

                          if (e.shiftKey && lastClickedSequentialLevel !== null) {
                            // Shift+Click: select range
                            const displayedLevels = targetLevels.slice(0, 50);
                            const lastIndex = displayedLevels.findIndex(l => l.meta.level_number === lastClickedSequentialLevel);
                            const currentIndex = index;

                            if (lastIndex !== -1) {
                              const start = Math.min(lastIndex, currentIndex);
                              const end = Math.max(lastIndex, currentIndex);
                              const rangeItems = displayedLevels.slice(start, end + 1).map(l => l.meta.level_number);

                              setSelectedSequentialLevels(prev => {
                                const next = new Set(prev);
                                rangeItems.forEach(n => next.add(n));
                                return next;
                              });
                            }
                          } else {
                            // Normal click: toggle single item
                            setSelectedSequentialLevels(prev => {
                              const next = new Set(prev);
                              if (isChecked) next.delete(levelNum);
                              else next.add(levelNum);
                              return next;
                            });
                            setLastClickedSequentialLevel(levelNum);
                          }
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={selectedSequentialLevels.has(levelNum)}
                          onChange={() => {}}
                          className="w-3 h-3 pointer-events-none"
                        />
                        <span className="ml-2 flex-1 text-gray-300">Lv.{levelNum}</span>
                        <span className={`w-14 text-center font-medium ${
                          isUntested ? 'text-gray-500' :
                          (level.meta.match_score || 0) >= computeSequentialPassThreshold(level.meta.target_difficulty) ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {isUntested ? '미측정' : `${level.meta.match_score?.toFixed(0)}%`}
                        </span>
                        <span className={`w-12 text-center font-bold ${
                          level.meta.grade === 'S' ? 'text-green-400' :
                          level.meta.grade === 'A' ? 'text-blue-400' :
                          level.meta.grade === 'B' ? 'text-yellow-400' :
                          level.meta.grade === 'C' ? 'text-orange-400' : 'text-red-400'
                        }`}>{level.meta.grade}</span>
                      </label>
                    );
                  })}
                  {targetLevels.length > 50 && (
                    <div className="px-3 py-2 text-xs text-gray-500 text-center">
                      ...외 {targetLevels.length - 50}개 더
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Results Summary */}
            {!isSequentialProcessing && sequentialProgress.results.length > 0 && (() => {
              const failed = sequentialProgress.results.filter(r => !r.success);
              const tooEasy = failed.filter(r => r.direction === 'too_easy').length;
              const tooHard = failed.filter(r => r.direction === 'too_hard').length;
              const worstBotDist = failed.reduce<Record<string, number>>((acc, r) => {
                if (r.worst_bot) acc[r.worst_bot] = (acc[r.worst_bot] || 0) + 1;
                return acc;
              }, {});
              const worstBotEntries = Object.entries(worstBotDist).sort((a, b) => b[1] - a[1]);
              return (
                <div className="border border-gray-700 rounded-lg p-3 space-y-2">
                  <div className="text-xs text-gray-400">최근 처리 결과</div>
                  {failed.length > 0 && (
                    <div className="bg-gray-900/50 rounded p-2 space-y-1 text-xs">
                      <div className="text-gray-400">실패 분포 ({failed.length}건)</div>
                      <div className="flex gap-3">
                        <span className="text-yellow-400">너무 쉬움: {tooEasy}</span>
                        <span className="text-red-400">너무 어려움: {tooHard}</span>
                      </div>
                      {worstBotEntries.length > 0 && (
                        <div className="text-gray-400">
                          주 원인 봇: {worstBotEntries.map(([b, c]) => `${b}×${c}`).join(', ')}
                        </div>
                      )}
                    </div>
                  )}
                  <div className="max-h-[140px] overflow-y-auto space-y-1">
                    {sequentialProgress.results.slice(-10).map(r => (
                      <div key={r.level_number} className={`flex items-center justify-between text-xs px-2 py-1 rounded ${
                        r.success ? 'bg-green-900/30' : 'bg-red-900/30'
                      }`}>
                        <span className="text-gray-300">Lv.{r.level_number}</span>
                        <div className="flex items-center gap-2">
                          {!r.success && r.worst_bot && r.worst_gap_pp !== undefined && (
                            <span className="text-gray-400">
                              {r.worst_bot} {r.worst_gap_pp > 0 ? '+' : ''}{r.worst_gap_pp.toFixed(0)}pp
                            </span>
                          )}
                          {r.pass_threshold !== undefined && r.pass_threshold !== 70 && (
                            <span className="text-gray-500">컷:{r.pass_threshold}</span>
                          )}
                          <span className={r.success ? 'text-green-400' : 'text-red-400'}>
                            {r.final_score.toFixed(0)}% ({r.attempts}회)
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
          </div>
        ) : (
          // [fix] 미검증/미달 레벨이 없어도 패널을 숨기지 않음 — 전체 재검증 진입점 제공.
          // (이미 검증된 배치/전부 통과/levels 로딩 직후엔 targetLevels가 비어 패널이 통째로 사라지던 문제)
          <div className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="text-sm text-gray-300">
              {levels.length === 0
                ? '레벨을 불러오는 중이거나 배치가 비어 있습니다.'
                : '미검증/미달 레벨이 없습니다 (모든 레벨 검증·통과 상태).'}
            </div>
            <Button
              onClick={() => handleSequentialProcess(levels.map(l => l.meta.level_number))}
              disabled={isSequentialProcessing || levels.length === 0}
              className="bg-blue-600 hover:bg-blue-500"
            >
              {isSequentialProcessing ? '검증 중…' : `🔁 전체 ${levels.length}개 재검증 (RL)`}
            </Button>
          </div>
        );
      })()}

      {/* Stored Low-Match Levels Regeneration */}
      {testMode === 'auto_batch' && (() => {
        const storedTestedLevels = levels.filter(l => l.meta.match_score !== undefined && l.meta.match_score > 0);
        const storedLowMatch = storedTestedLevels
          .filter(l => (l.meta.match_score || 0) < regenerationThreshold)
          .sort((a, b) => (a.meta.match_score || 0) - (b.meta.match_score || 0));
        const allSelected = storedLowMatch.length > 0 && storedLowMatch.every(l => selectedRegenLevels.has(l.meta.level_number));
        return storedTestedLevels.length > 0 ? (
          <div className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-white">미달 레벨 재생성</h3>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">
                  테스트 완료: {storedTestedLevels.length}개 / 미달: <span className={storedLowMatch.length > 0 ? 'text-orange-400 font-medium' : 'text-green-400'}>{storedLowMatch.length}개</span>
                </span>
                <select
                  value={regenerationThreshold}
                  onChange={(e) => { setRegenerationThreshold(Number(e.target.value)); setSelectedRegenLevels(new Set()); }}
                  className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs"
                  disabled={isBatchRegenerating}
                >
                  <option value={50}>50% 미만</option>
                  <option value={60}>60% 미만</option>
                  <option value={70}>70% 미만</option>
                  <option value={80}>80% 미만</option>
                </select>
              </div>
            </div>

            {/* Action Buttons */}
            {storedLowMatch.length > 0 && (
              <div className="flex items-center gap-2">
                <Button
                  onClick={handleBatchRegenerateFromStored}
                  disabled={isBatchRegenerating}
                  variant="danger"
                  size="sm"
                  className="flex-1"
                >
                  {isBatchRegenerating ? (
                    <><span className="animate-spin mr-1">⟳</span>재생성 중...</>
                  ) : (
                    `🔄 전체 ${storedLowMatch.length}개 일괄 재생성`
                  )}
                </Button>
                <Button
                  onClick={handleRegenerateSelected}
                  disabled={isBatchRegenerating || selectedRegenLevels.size === 0}
                  size="sm"
                  className={`flex-1 ${selectedRegenLevels.size > 0 ? 'bg-orange-600 hover:bg-orange-500' : 'bg-gray-600'}`}
                >
                  {isBatchRegenerating ? (
                    <><span className="animate-spin mr-1">⟳</span>재생성 중...</>
                  ) : (
                    `🎯 선택 ${selectedRegenLevels.size}개만 재생성`
                  )}
                </Button>
              </div>
            )}

            {/* Batch Regeneration Progress */}
            {/* Batch Regeneration Progress - show during and after batch regen */}
            {(isBatchRegenerating || regenProgressMap.size > 0) && batchRegenTotal > 0 && (() => {
              const entries = [...regenProgressMap.values()];
              const doneCount = entries.filter(p => p.status === 'done').length;
              const failCount = entries.filter(p => p.status === 'failed').length;
              const completedCount = doneCount + failCount;
              const generatingCount = entries.filter(p => p.status === 'generating').length;
              const savingCount = entries.filter(p => p.status === 'saving').length;
              const waitingCount = entries.filter(p => p.status === 'waiting').length;
              const progressPct = (completedCount / batchRegenTotal) * 100;
              const isFinished = !isBatchRegenerating && completedCount === batchRegenTotal;
              return (
                <div className={`border rounded-lg p-3 space-y-2 ${isFinished ? 'bg-gray-800/80 border-gray-600' : 'bg-gray-900/60 border-gray-600'}`}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-gray-300 font-medium">
                      {isFinished ? '재생성 완료' : '재생성 진행도'}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-400">
                        <span className="text-green-400 font-bold">{doneCount}</span>
                        {failCount > 0 && <> + <span className="text-red-400 font-bold">{failCount}</span></>}
                        <span className="text-gray-500"> / {batchRegenTotal}</span>
                      </span>
                      {isFinished && (
                        <button
                          onClick={() => { setRegenProgressMap(new Map()); setBatchRegenTotal(0); }}
                          className="text-gray-500 hover:text-gray-300 text-xs px-1"
                          title="닫기"
                        >✕</button>
                      )}
                    </div>
                  </div>
                  {/* Progress bar */}
                  <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-300 ease-out"
                      style={{
                        width: `${progressPct}%`,
                        background: failCount > 0
                          ? `linear-gradient(90deg, #22c55e ${completedCount > 0 ? (doneCount / completedCount) * 100 : 0}%, #ef4444 ${completedCount > 0 ? (doneCount / completedCount) * 100 : 0}%)`
                          : '#22c55e',
                      }}
                    />
                  </div>
                  {/* Status summary */}
                  <div className="flex items-center gap-3 text-xs text-gray-400 flex-wrap">
                    {isBatchRegenerating && (
                      <>
                        {generatingCount > 0 && <span className="flex items-center gap-1"><span className="animate-spin text-blue-400">⟳</span> 생성 {generatingCount}</span>}
                        {savingCount > 0 && <span className="flex items-center gap-1"><span className="animate-spin text-purple-400">⟳</span> 저장 {savingCount}</span>}
                        {waitingCount > 0 && <span className="text-gray-500">대기 {waitingCount}</span>}
                      </>
                    )}
                    {doneCount > 0 && (
                      <span className="text-green-400">완료 {doneCount}</span>
                    )}
                    {failCount > 0 && <span className="text-red-400">에러 {failCount}</span>}
                  </div>
                  {/* Show first error message for debugging */}
                  {failCount > 0 && (() => {
                    const firstError = entries.find(p => p.status === 'failed' && p.error);
                    return firstError?.error ? (
                      <div className="text-xs text-red-400/80 bg-red-900/20 rounded px-2 py-1 truncate" title={firstError.error}>
                        {firstError.error}
                      </div>
                    ) : null;
                  })()}
                </div>
              );
            })()}

            {/* Selectable Level List */}
            {storedLowMatch.length > 0 && (
              <div className="border border-gray-700 rounded-lg overflow-hidden">
                {/* Header with Select All */}
                <div className="flex items-center gap-2 px-3 py-2 bg-gray-700/60 border-b border-gray-600 text-xs">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => {
                      if (allSelected) {
                        setSelectedRegenLevels(new Set());
                      } else {
                        setSelectedRegenLevels(new Set(storedLowMatch.map(l => l.meta.level_number)));
                      }
                    }}
                    className="rounded border-gray-500 accent-orange-500"
                    disabled={isBatchRegenerating}
                  />
                  <span className="text-gray-400 flex-1">전체 선택</span>
                  <span className="w-12 text-center text-gray-500">레벨</span>
                  <span className="w-16 text-center text-gray-500">패턴</span>
                  <span className="w-14 text-center text-gray-500">일치도</span>
                  <span className="w-14 text-center text-gray-500">등급</span>
                  <span className="w-14 text-center text-gray-500">목표</span>
                  <span className="w-14 text-center text-gray-500">검증</span>
                  {isBatchRegenerating && <span className="w-16 text-center text-gray-500">상태</span>}
                </div>
                {/* Scrollable List */}
                <div className="max-h-[200px] overflow-y-auto">
                  {storedLowMatch.map(level => {
                    const score = level.meta.match_score || 0;
                    const isSelected = selectedRegenLevels.has(level.meta.level_number);
                    const isRegen = regeneratingLevels.has(level.meta.level_number);
                    const levelProgress = regenProgressMap.get(level.meta.level_number);
                    const progressStatus = levelProgress?.status;
                    const isDone = progressStatus === 'done';
                    const isFailed = progressStatus === 'failed';
                    return (
                      <label
                        key={level.meta.level_number}
                        className={`flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer transition-colors ${
                          isDone ? 'bg-green-900/20' : isFailed ? 'bg-red-900/20' :
                          isSelected ? 'bg-orange-900/30' : 'hover:bg-gray-700/40'
                        } ${isRegen ? 'opacity-70' : ''}`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {
                            setSelectedRegenLevels(prev => {
                              const next = new Set(prev);
                              if (next.has(level.meta.level_number)) next.delete(level.meta.level_number);
                              else next.add(level.meta.level_number);
                              return next;
                            });
                          }}
                          className="rounded border-gray-500 accent-orange-500"
                          disabled={isBatchRegenerating || isRegen}
                        />
                        <span className="flex-1 text-gray-300">
                        </span>
                        <span className="w-12 text-center text-gray-300 font-medium">Lv.{level.meta.level_number}</span>
                        {(level.level_json as unknown as Record<string, unknown> | undefined)?.reverse_generated === true && (
                          <span className="text-emerald-400 text-xs font-medium" title="역생성 — 솔버블·÷3 구조적 보장 (witness peeling)">🧩역</span>
                        )}
                        <span className="w-16 text-center text-xs">
                          {level.meta.template_id ? (() => {
                            // [v15.55] 템플릿 기반 레벨 — source_level_id에서 번호 파싱 → #123
                            const m = level.meta.template_id.match(/(\d+)(?!.*\d)/);
                            const label = m ? `#${m[1]}` : '📋';
                            const diffStr = level.meta.template_source_difficulty != null
                              ? ` 📊${(level.meta.template_source_difficulty * 100).toFixed(0)}`
                              : '';
                            return (
                              <span className="text-violet-300 font-medium"
                                title={`레벨 템플릿: ${level.meta.template_id}${diffStr}`}>
                                {label}
                              </span>
                            );
                          })() : level.meta.pattern_index !== undefined && level.meta.pattern_index >= 0 ? (
                            <span className="text-purple-400" title={getPatternByIndex(level.meta.pattern_index)?.name || `패턴 ${level.meta.pattern_index}`}>
                              {getPatternByIndex(level.meta.pattern_index)?.icon || '🎨'}
                            </span>
                          ) : (
                            <span className="text-gray-600">-</span>
                          )}
                        </span>
                        <span className={`w-14 text-center font-bold ${
                          isDone && levelProgress?.matchScore !== undefined
                            ? (levelProgress.matchScore >= regenerationThreshold ? 'text-green-400' : 'text-yellow-400')
                            : score >= 50 ? 'text-yellow-400' : 'text-red-400'
                        }`}>
                          {isDone && levelProgress?.matchScore !== undefined
                            ? `${levelProgress.matchScore.toFixed(0)}%`
                            : `${score.toFixed(0)}%`
                          }
                        </span>
                        <span className={`w-14 text-center font-bold ${
                          level.meta.grade === 'S' ? 'text-green-400' :
                          level.meta.grade === 'A' ? 'text-blue-400' :
                          level.meta.grade === 'B' ? 'text-yellow-400' :
                          level.meta.grade === 'C' ? 'text-orange-400' : 'text-red-400'
                        }`}>{level.meta.grade}</span>
                        <span className="w-14 text-center text-gray-400">{(level.meta.target_difficulty * 100).toFixed(0)}%</span>
                        <button
                          className="w-14 text-center text-xs px-1.5 py-0.5 bg-blue-600/50 hover:bg-blue-600 text-blue-200 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleValidateSingleLevel(level);
                          }}
                          disabled={isBatchRegenerating || validatingLevels.has(level.meta.level_number)}
                        >
                          {validatingLevels.has(level.meta.level_number) ? '⟳' : '검증'}
                        </button>
                        {isBatchRegenerating && (
                          <span className={`w-16 text-center font-medium ${
                            progressStatus === 'generating' ? 'text-blue-400' :
                            progressStatus === 'saving' ? 'text-purple-400' :
                            progressStatus === 'done' ? 'text-green-400' :
                            progressStatus === 'failed' ? 'text-red-400' :
                            'text-gray-500'
                          }`}>
                            {progressStatus === 'waiting' && '대기'}
                            {progressStatus === 'generating' && <><span className="animate-spin inline-block">⟳</span> 생성</>}
                            {progressStatus === 'saving' && <><span className="animate-spin inline-block">⟳</span> 저장</>}
                            {progressStatus === 'done' && '✓ 완료'}
                            {progressStatus === 'failed' && '✗ 실패'}
                            {!progressStatus && '-'}
                          </span>
                        )}
                      </label>
                    );
                  })}
                </div>
              </div>
            )}

            {storedLowMatch.length === 0 && (
              <div className="text-center text-xs text-green-400 py-2">✅ 미달 레벨 없음</div>
            )}
          </div>
        ) : null;
      })()}

      {/* Meta Integrity Scanner — declared useTileCount vs actual tile types */}
      {testMode === 'auto_batch' && (
        <MetaIntegrityPanel
          batchId={batchId}
          onRegenerateLevel={(n) => handleRegenerateLevel(n)}
          onBulkRegenerate={async (numbers) => {
            const result = await batchRegenerateCore(numbers);
            if (result) {
              addNotification('success', `메타 결함 일괄 재생성 완료: ${result.successCount}개 성공, ${result.failCount}개 실패`);
            }
          }}
        />
      )}

      {/* Batch Auto Test Panel */}
      {testMode === 'auto_batch' && (
        <div className="bg-gray-800 rounded-lg p-4 space-y-4">
          <h3 className="text-sm font-medium text-white">일괄 자동 테스트 설정</h3>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">필터</label>
              <select
                value={batchTestFilter}
                onChange={(e) => setBatchTestFilter(e.target.value as typeof batchTestFilter)}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                disabled={batchTestProgress.status === 'running'}
              >
                <option value="all">전체 레벨</option>
                <option value="untested">미테스트 레벨</option>
                <option value="boss">보스 레벨 (10배수)</option>
                <option value="tutorial">튜토리얼 레벨</option>
                <option value="low_match">낮은 일치도 (&lt;70%)</option>
                <option value="range">레벨 범위</option>
              </select>
            </div>

            {batchTestFilter === 'range' && (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">시작 레벨</label>
                  <input
                    type="number"
                    value={batchTestRange.min}
                    onChange={(e) => setBatchTestRange(prev => ({ ...prev, min: Number(e.target.value) }))}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    disabled={batchTestProgress.status === 'running'}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">종료 레벨</label>
                  <input
                    type="number"
                    value={batchTestRange.max}
                    onChange={(e) => setBatchTestRange(prev => ({ ...prev, max: Number(e.target.value) }))}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    disabled={batchTestProgress.status === 'running'}
                  />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">최대 레벨 수</label>
              <input
                type="number"
                value={batchTestMaxLevels}
                onChange={(e) => setBatchTestMaxLevels(Number(e.target.value))}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                disabled={batchTestProgress.status === 'running'}
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">검증 속도</label>
              <select
                value={autoTestIterations}
                onChange={(e) => setAutoTestIterations(Number(e.target.value))}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                disabled={batchTestProgress.status === 'running'}
              >
                <option value={30}>⚡ 빠름 (30회)</option>
                <option value={100}>⚖️ 보통 (100회)</option>
                <option value={200}>🎯 정밀 (200회)</option>
              </select>
            </div>
          </div>

          {/* Batch Test Progress */}
          {batchTestProgress.status !== 'idle' && (
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-gray-400">
                <span>진행: {batchTestProgress.completed}/{batchTestProgress.total}</span>
                <span>현재: 레벨 {batchTestProgress.currentLevel}</span>
              </div>
              <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-[width] duration-500 ease-linear ${
                    batchTestProgress.status === 'completed' ? 'bg-green-500' :
                    batchTestProgress.status === 'error' ? 'bg-red-500' : 'bg-indigo-500'
                  }`}
                  style={{ width: `${batchTestProgress.total > 0 ? (batchTestProgress.completed / batchTestProgress.total) * 100 : 0}%` }}
                />
              </div>
              {batchTestProgress.failedLevels.length > 0 && (
                <div className="text-xs text-red-400">
                  실패: {batchTestProgress.failedLevels.join(', ')}
                </div>
              )}
            </div>
          )}

          {/* Batch Test Results Summary - Enhanced */}
          {batchTestProgress.status === 'completed' && batchTestProgress.results.length > 0 && (() => {
            const results = batchTestProgress.results;
            const passCount = results.filter(r => r.match_score >= 70).length;
            const warnCount = results.filter(r => r.match_score >= 50 && r.match_score < 70).length;
            const failCount = results.filter(r => r.match_score < 50).length;
            const avgScore = results.reduce((sum, r) => sum + r.match_score, 0) / results.length;
            const minScore = Math.min(...results.map(r => r.match_score));
            const maxScore = Math.max(...results.map(r => r.match_score));
            const minLevel = results.find(r => r.match_score === minScore);
            const maxLevel = results.find(r => r.match_score === maxScore);

            // Grade distribution
            const gradeCount: Record<string, number> = { S: 0, A: 0, B: 0, C: 0, D: 0 };
            results.forEach(r => { gradeCount[r.grade] = (gradeCount[r.grade] || 0) + 1; });

            // Balance distribution
            const balanceCount: Record<string, number> = {};
            results.forEach(r => { balanceCount[r.status] = (balanceCount[r.status] || 0) + 1; });

            return (
              <div className="space-y-3">
                {/* Overall Summary */}
                <div className="p-3 bg-gray-700/50 rounded-lg">
                  <h4 className="text-xs text-gray-400 mb-3">📊 전체 결과 요약</h4>

                  {/* Pass/Warn/Fail Bar */}
                  <div className="mb-3">
                    <div className="flex h-4 rounded-full overflow-hidden bg-gray-600">
                      {passCount > 0 && (
                        <div
                          className="bg-green-500 flex items-center justify-center text-[10px] text-white font-medium"
                          style={{ width: `${(passCount / results.length) * 100}%` }}
                        >
                          {passCount > 2 && `${passCount}`}
                        </div>
                      )}
                      {warnCount > 0 && (
                        <div
                          className="bg-yellow-500 flex items-center justify-center text-[10px] text-white font-medium"
                          style={{ width: `${(warnCount / results.length) * 100}%` }}
                        >
                          {warnCount > 2 && `${warnCount}`}
                        </div>
                      )}
                      {failCount > 0 && (
                        <div
                          className="bg-red-500 flex items-center justify-center text-[10px] text-white font-medium"
                          style={{ width: `${(failCount / results.length) * 100}%` }}
                        >
                          {failCount > 2 && `${failCount}`}
                        </div>
                      )}
                    </div>
                    <div className="flex justify-between mt-1 text-[10px] text-gray-400">
                      <span>✅ 통과 {passCount}개 ({((passCount / results.length) * 100).toFixed(0)}%)</span>
                      <span>⚠️ 보통 {warnCount}개 ({((warnCount / results.length) * 100).toFixed(0)}%)</span>
                      <span>❌ 미달 {failCount}개 ({((failCount / results.length) * 100).toFixed(0)}%)</span>
                    </div>
                  </div>

                  {/* Score Statistics */}
                  <div className="grid grid-cols-4 gap-2 text-sm mb-3">
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-lg font-bold text-white">{avgScore.toFixed(1)}%</div>
                      <div className="text-[10px] text-gray-500">평균 일치도</div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-lg font-bold text-green-400">{maxScore.toFixed(0)}%</div>
                      <div className="text-[10px] text-gray-500">최고 (Lv.{maxLevel?.level_number})</div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-lg font-bold text-red-400">{minScore.toFixed(0)}%</div>
                      <div className="text-[10px] text-gray-500">최저 (Lv.{minLevel?.level_number})</div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-lg font-bold text-blue-400">{results.length}</div>
                      <div className="text-[10px] text-gray-500">테스트 완료</div>
                    </div>
                  </div>

                  {/* Grade Distribution */}
                  <div className="mb-3">
                    <div className="text-[10px] text-gray-400 mb-1">등급 분포</div>
                    <div className="flex gap-1">
                      {(['S', 'A', 'B', 'C', 'D'] as const).map(grade => (
                        <div key={grade} className="flex-1 text-center">
                          <div className={`text-xs font-bold ${
                            grade === 'S' ? 'text-green-400' :
                            grade === 'A' ? 'text-blue-400' :
                            grade === 'B' ? 'text-yellow-400' :
                            grade === 'C' ? 'text-orange-400' : 'text-red-400'
                          }`}>
                            {gradeCount[grade] || 0}
                          </div>
                          <div className="text-[10px] text-gray-500">{grade}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Balance Distribution */}
                  <div>
                    <div className="text-[10px] text-gray-400 mb-1">밸런스 상태</div>
                    <div className="flex flex-wrap gap-1">
                      {balanceCount.balanced && (
                        <span className="px-2 py-0.5 bg-green-900/50 text-green-400 text-[10px] rounded">
                          ✅ 균형 {balanceCount.balanced}
                        </span>
                      )}
                      {balanceCount.too_easy && (
                        <span className="px-2 py-0.5 bg-yellow-900/50 text-yellow-400 text-[10px] rounded">
                          📉 너무쉬움 {balanceCount.too_easy}
                        </span>
                      )}
                      {balanceCount.too_hard && (
                        <span className="px-2 py-0.5 bg-orange-900/50 text-orange-400 text-[10px] rounded">
                          📈 너무어려움 {balanceCount.too_hard}
                        </span>
                      )}
                      {balanceCount.unbalanced && (
                        <span className="px-2 py-0.5 bg-red-900/50 text-red-400 text-[10px] rounded">
                          ⚠️ 불균형 {balanceCount.unbalanced}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Difficulty Comparison */}
                <div className="p-3 bg-gray-700/50 rounded-lg">
                  <h4 className="text-xs text-gray-400 mb-2">🎯 난이도 비교 (목표 vs 실제)</h4>
                  <div className="grid grid-cols-3 gap-2 text-sm mb-2">
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-[10px] text-gray-500 mb-1">평균 목표 난이도</div>
                      <div className="text-white font-bold">
                        {(results.reduce((sum, r) => sum + r.target_difficulty, 0) / results.length * 100).toFixed(0)}%
                      </div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-[10px] text-gray-500 mb-1">평균 자동플레이 점수</div>
                      <div className="text-indigo-400 font-bold">
                        {(results.reduce((sum, r) => sum + r.autoplay_score, 0) / results.length).toFixed(0)}점
                      </div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-[10px] text-gray-500 mb-1">평균 정적분석 점수</div>
                      <div className="text-purple-400 font-bold">
                        {(results.reduce((sum, r) => sum + r.static_score, 0) / results.length).toFixed(0)}점
                      </div>
                    </div>
                  </div>
                  <div className="text-[10px] text-gray-500 text-center">
                    자동플레이 - 정적분석 평균 차이: {' '}
                    <span className={(() => {
                      const diff = (results.reduce((sum, r) => sum + (r.autoplay_score - r.static_score), 0) / results.length);
                      return diff > 10 ? 'text-orange-400' : diff < -10 ? 'text-yellow-400' : 'text-green-400';
                    })()}>
                      {((results.reduce((sum, r) => sum + (r.autoplay_score - r.static_score), 0) / results.length) >= 0 ? '+' : '')}
                      {(results.reduce((sum, r) => sum + (r.autoplay_score - r.static_score), 0) / results.length).toFixed(1)}점
                    </span>
                    {' '}
                    ({(() => {
                      const diff = (results.reduce((sum, r) => sum + (r.autoplay_score - r.static_score), 0) / results.length);
                      return diff > 10 ? '실제 더 어려움' : diff < -10 ? '실제 더 쉬움' : '일치';
                    })()})
                  </div>
                </div>

                {/* Batch Regeneration Controls */}
                {results.filter(r => r.match_score < 70).length > 0 && (
                  <div className="p-3 bg-orange-900/30 rounded-lg border border-orange-700/50">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-xs text-orange-400 font-medium">🔄 낮은 일치도 레벨 재생성</h4>
                      <span className="text-xs text-orange-300">
                        {results.filter(r => r.match_score < regenerationThreshold).length}개 대상
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-gray-400">기준:</label>
                      <select
                        value={regenerationThreshold}
                        onChange={(e) => setRegenerationThreshold(Number(e.target.value))}
                        className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs"
                        disabled={isBatchRegenerating}
                      >
                        <option value={50}>50% 미만</option>
                        <option value={60}>60% 미만</option>
                        <option value={70}>70% 미만</option>
                        <option value={80}>80% 미만</option>
                      </select>
                      <Button
                        onClick={handleBatchRegenerate}
                        disabled={isBatchRegenerating || results.filter(r => r.match_score < regenerationThreshold).length === 0}
                        variant="danger"
                        size="sm"
                        className="flex-1"
                      >
                        {isBatchRegenerating ? (
                          <>
                            <span className="animate-spin mr-1">⟳</span>
                            재생성 중...
                          </>
                        ) : (
                          <>
                            🔄 {results.filter(r => r.match_score < regenerationThreshold).length}개 일괄 재생성
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                )}

                {/* Individual Results List - Enhanced */}
                <div className="p-3 bg-gray-700/50 rounded-lg">
                  <h4 className="text-xs text-gray-400 mb-2">📋 개별 레벨 결과 (일치도 낮은 순)</h4>
                  {/* Header */}
                  <div className="flex items-center text-[10px] text-gray-500 px-2 py-1 border-b border-gray-600 mb-1">
                    <span className="w-14">레벨</span>
                    <span className="w-12 text-center">등급</span>
                    <span className="w-14 text-center">일치도</span>
                    <span className="w-16 text-center">목표</span>
                    <span className="w-20 text-center">자동/정적</span>
                    <span className="w-10 text-center">상태</span>
                    <span className="w-16 text-center">액션</span>
                  </div>
                  <div className="max-h-[250px] overflow-y-auto space-y-1">
                    {[...results].sort((a, b) => a.match_score - b.match_score).map(r => {
                      const scoreDiff = r.autoplay_score - r.static_score;
                      const isRegenerating = regeneratingLevels.has(r.level_number);
                      return (
                        <div
                          key={r.level_number}
                          className={`flex items-center px-2 py-1.5 rounded text-xs ${
                            r.match_score >= 70 ? 'bg-green-900/20 hover:bg-green-900/40' :
                            r.match_score >= 50 ? 'bg-yellow-900/20 hover:bg-yellow-900/40' : 'bg-red-900/20 hover:bg-red-900/40'
                          } transition-colors`}
                        >
                          <span className="w-14 text-gray-300 font-medium">Lv.{r.level_number}</span>
                          <span className={`w-12 text-center font-bold ${
                            r.grade === 'S' ? 'text-green-400' :
                            r.grade === 'A' ? 'text-blue-400' :
                            r.grade === 'B' ? 'text-yellow-400' :
                            r.grade === 'C' ? 'text-orange-400' : 'text-red-400'
                          }`}>{r.grade}</span>
                          <span className={`w-14 text-center font-bold ${
                            r.match_score >= 70 ? 'text-green-400' :
                            r.match_score >= 50 ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {r.match_score.toFixed(0)}%
                          </span>
                          <span className="w-16 text-center text-gray-400">
                            {(r.target_difficulty * 100).toFixed(0)}%
                          </span>
                          <span className="w-20 text-center">
                            <span className="text-indigo-400">{r.autoplay_score.toFixed(0)}</span>
                            <span className="text-gray-500">/</span>
                            <span className="text-purple-400">{r.static_score.toFixed(0)}</span>
                            <span className={`ml-0.5 text-[9px] ${
                              Math.abs(scoreDiff) <= 10 ? 'text-green-400' :
                              scoreDiff > 10 ? 'text-orange-400' : 'text-yellow-400'
                            }`}>
                              ({scoreDiff >= 0 ? '+' : ''}{scoreDiff.toFixed(0)})
                            </span>
                          </span>
                          <span className="w-10 text-center">
                            {r.status === 'balanced' ? '✅' :
                             r.status === 'too_easy' ? '📉' :
                             r.status === 'too_hard' ? '📈' : '⚠️'}
                          </span>
                          <span className="w-16 text-center">
                            <button
                              onClick={() => handleRegenerateLevel(r.level_number)}
                              disabled={isRegenerating || isBatchRegenerating}
                              className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                                isRegenerating
                                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                                  : r.match_score < 70
                                    ? 'bg-orange-600 hover:bg-orange-500 text-white'
                                    : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                              }`}
                            >
                              {isRegenerating ? '⟳' : '🔄 재생성'}
                            </button>
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-2 pt-2 border-t border-gray-600 text-[10px] text-gray-500 flex justify-between">
                    <span>🟣 자동플레이 = 봇 시뮬레이션</span>
                    <span>🟣 정적분석 = 레벨 구조</span>
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Batch Test Actions */}
          <div className="flex gap-2">
            {batchTestProgress.status === 'running' ? (
              <Button onClick={handleStopBatchTest} variant="danger" className="flex-1">
                ⏹️ 테스트 중지
              </Button>
            ) : (
              <Button onClick={handleBatchAutoTest} className="flex-1" disabled={levels.length === 0}>
                🚀 일괄 테스트 시작
              </Button>
            )}
            {batchTestProgress.status === 'completed' && (
              <Button
                onClick={() => setBatchTestProgress({ status: 'idle', total: 0, completed: 0, currentLevel: 0, results: [], failedLevels: [] })}
                variant="secondary"
              >
                초기화
              </Button>
            )}
          </div>

          {/* 전체 자동 승인 버튼 - 테스트 완료 후 */}
          {batchTestProgress.status === 'completed' && (
            <div className="mt-3 p-3 bg-green-900/20 border border-green-700/50 rounded-lg">
              <div className="text-sm text-green-300 mb-2">
                ✅ 테스트 완료! 전체 레벨을 승인하고 익스포트하시겠습니까?
              </div>
              {isApprovingAll ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm text-green-200">
                    <div className="w-4 h-4 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                    승인 중... {approveAllProgress.current}/{approveAllProgress.total}
                  </div>
                  <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500 transition-all"
                      style={{ width: `${approveAllProgress.total > 0 ? (approveAllProgress.current / approveAllProgress.total) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              ) : (
                <Button
                  onClick={handleApproveAllLevels}
                  className="w-full bg-green-600 hover:bg-green-700"
                >
                  ✅ 전체 자동 승인 → 익스포트
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex gap-4 flex-1 min-h-0">
      {/* Level list */}
      <div className="w-80 flex flex-col bg-gray-800 rounded-lg overflow-hidden">
        {/* Filters */}
        <div className="p-3 border-b border-gray-700 space-y-2">
          {/* [v15.56] 생성 중 실시간 갱신 인디케이터 + 수동 새로고침 */}
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-gray-400">
              레벨 {levels.length}개
              {isGenerating && (
                <span className="ml-1 text-green-400 animate-pulse">● 생성 중 — 5초마다 자동 갱신</span>
              )}
            </span>
            <button
              onClick={() => loadLevels()}
              disabled={isLoading}
              className="px-2 py-0.5 rounded text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-50"
              title="현재까지 저장된 레벨 즉시 새로고침"
            >
              🔄 새로고침
            </button>
          </div>
          <input
            type="text"
            placeholder="레벨 번호 검색..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-3 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
          />
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as LevelStatus | 'all' | 'low_match' | 'untested')}
            className="w-full px-3 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
          >
            <option value="all">전체 레벨</option>
            <option value="low_match">⚠️ 낮은 일치율 (&lt;70%)</option>
            <option value="untested">🔍 미테스트</option>
            <option value="generated">생성됨</option>
            <option value="playtest_queue">테스트 대기</option>
            <option value="approved">승인됨</option>
            <option value="needs_rework">수정필요</option>
          </select>

          {/* Range Selection Toggle */}
          <button
            onClick={() => setRangeSelectMode(!rangeSelectMode)}
            className={`w-full px-3 py-1.5 text-xs rounded transition-colors ${
              rangeSelectMode ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            🎯 범위 선택 {rangeSelectMode ? '▲' : '▼'}
          </button>

          {/* Range Selection Panel */}
          {rangeSelectMode && (
            <div className="bg-gray-900/50 rounded-lg p-2 space-y-2 border border-gray-600">
              {/* Range Inputs */}
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={rangeStart}
                  onChange={(e) => setRangeStart(Math.max(1, parseInt(e.target.value) || 1))}
                  className="flex-1 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-center"
                  placeholder="시작"
                  min={1}
                />
                <span className="text-gray-500 text-sm">~</span>
                <input
                  type="number"
                  value={rangeEnd}
                  onChange={(e) => setRangeEnd(Math.max(1, parseInt(e.target.value) || 1))}
                  className="flex-1 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-center"
                  placeholder="끝"
                  min={1}
                />
              </div>

              {/* Range Action Buttons */}
              <div className="flex gap-1">
                <button
                  onClick={handleSelectRange}
                  disabled={isBatchRegenerating}
                  className="flex-1 px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded disabled:opacity-50"
                >
                  범위 선택
                </button>
                <button
                  onClick={handleAddRangeToSelection}
                  disabled={isBatchRegenerating}
                  className="flex-1 px-2 py-1 text-xs bg-purple-600 hover:bg-purple-500 text-white rounded disabled:opacity-50"
                >
                  추가 선택
                </button>
              </div>

              {/* Quick Select Buttons */}
              <div className="flex flex-wrap gap-1">
                <button
                  onClick={() => handleQuickSelect('first', 50)}
                  disabled={isBatchRegenerating}
                  className="px-2 py-1 text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-300 rounded disabled:opacity-50"
                >
                  처음 50
                </button>
                <button
                  onClick={() => handleQuickSelect('last', 50)}
                  disabled={isBatchRegenerating}
                  className="px-2 py-1 text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-300 rounded disabled:opacity-50"
                >
                  마지막 50
                </button>
                <button
                  onClick={() => handleQuickSelect('first', 100)}
                  disabled={isBatchRegenerating}
                  className="px-2 py-1 text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-300 rounded disabled:opacity-50"
                >
                  처음 100
                </button>
                <button
                  onClick={() => setSelectedRegenLevels(new Set())}
                  disabled={isBatchRegenerating}
                  className="px-2 py-1 text-[10px] bg-red-700/50 hover:bg-red-600/50 text-red-300 rounded disabled:opacity-50"
                >
                  선택 해제
                </button>
              </div>

              {/* Selection Count & Actions */}
              {selectedRegenLevels.size > 0 && (
                <div className="flex items-center gap-2 pt-1 border-t border-gray-700">
                  <span className="text-xs text-indigo-400 flex-1">
                    {selectedRegenLevels.size}개 선택됨
                  </span>
                  <button
                    onClick={handleRegenerateSelected}
                    disabled={isBatchRegenerating}
                    className="px-2 py-1 text-xs bg-orange-600 hover:bg-orange-500 text-white rounded disabled:opacity-50"
                  >
                    {isBatchRegenerating ? '재생성 중...' : `🔄 ${selectedRegenLevels.size}개 재생성`}
                  </button>
                </div>
              )}

              {/* Batch Regeneration Progress for Range Selection */}
              {(isBatchRegenerating || regenProgressMap.size > 0) && batchRegenTotal > 0 && (() => {
                const entries = [...regenProgressMap.values()];
                const doneCount = entries.filter(p => p.status === 'done').length;
                const failCount = entries.filter(p => p.status === 'failed').length;
                const completedCount = doneCount + failCount;
                const generatingCount = entries.filter(p => p.status === 'generating').length;
                const savingCount = entries.filter(p => p.status === 'saving').length;
                const waitingCount = entries.filter(p => p.status === 'waiting').length;
                const progressPct = (completedCount / batchRegenTotal) * 100;
                const isFinished = !isBatchRegenerating && completedCount === batchRegenTotal;
                return (
                  <div className={`border rounded-lg p-2 space-y-1 mt-1 ${isFinished ? 'bg-gray-800/80 border-gray-600' : 'bg-gray-900/60 border-gray-600'}`}>
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-gray-300 font-medium">
                        {isFinished ? '✅ 완료' : '⏳ 진행중'}
                      </span>
                      <div className="flex items-center gap-1">
                        <span className="text-green-400 font-bold">{doneCount}</span>
                        {failCount > 0 && <span className="text-red-400">+{failCount}</span>}
                        <span className="text-gray-500">/ {batchRegenTotal}</span>
                        {isFinished && (
                          <button
                            onClick={() => { setRegenProgressMap(new Map()); setBatchRegenTotal(0); }}
                            className="text-gray-500 hover:text-gray-300 ml-1"
                          >✕</button>
                        )}
                      </div>
                    </div>
                    <div className="w-full h-1.5 bg-gray-700 rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-300"
                        style={{ width: `${progressPct}%`, background: failCount > 0 ? '#ef4444' : '#22c55e' }}
                      />
                    </div>
                    {isBatchRegenerating && (
                      <div className="flex items-center gap-2 text-[10px] text-gray-400">
                        {generatingCount > 0 && <span className="text-blue-400">⟳ {generatingCount}</span>}
                        {savingCount > 0 && <span className="text-purple-400">💾 {savingCount}</span>}
                        {waitingCount > 0 && <span className="text-gray-500">⏸ {waitingCount}</span>}
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          )}
        </div>

        {/* Level list */}
        <div
          ref={levelListRef}
          className="flex-1 overflow-y-auto"
          onScroll={(e) => {
            // 로딩 중에는 스크롤 위치 저장하지 않음 (리렌더링 시 0으로 덮어쓰기 방지)
            if (!isLoadingLevelsRef.current) {
              levelListScrollTopRef.current = e.currentTarget.scrollTop;
            }
          }}
        >
          {isLoading ? (
            <div className="flex items-center justify-center h-32 text-gray-400">
              로딩 중...
            </div>
          ) : filteredLevels.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-gray-400">
              레벨이 없습니다
            </div>
          ) : (
            <div className="divide-y divide-gray-700">
              {filteredLevels.map((level) => {
                const isChecked = selectedRegenLevels.has(level.meta.level_number);
                const isTemplateBased = !!level.meta.template_id;
                const templateNumMatch = isTemplateBased ? level.meta.template_id!.match(/(\d+)(?!.*\d)/) : null;
                const templateNum = templateNumMatch ? templateNumMatch[1] : null;
                return (
                <div
                  key={level.meta.level_number}
                  onClick={() => handleSelectLevel(level)}
                  className={`p-3 cursor-pointer transition-colors ${
                    selectedLevel?.meta.level_number === level.meta.level_number
                      ? (isTemplateBased ? 'bg-violet-800/60 border-l-4 border-violet-400' : 'bg-indigo-900/50')
                      : isChecked
                        ? 'bg-indigo-900/30'
                        : isTemplateBased
                          ? 'bg-violet-900/20 hover:bg-violet-900/40 border-l-4 border-violet-700'
                          : 'hover:bg-gray-700/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {/* Checkbox for batch selection with Shift+Click support */}
                      {rangeSelectMode && (
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => {}}
                          onClick={(e) => {
                            e.stopPropagation();
                            const levelNum = level.meta.level_number;

                            if (e.shiftKey && lastClickedRegenLevel !== null) {
                              // Shift+Click: select range
                              const lastIndex = filteredLevels.findIndex(l => l.meta.level_number === lastClickedRegenLevel);
                              const currentIndex = filteredLevels.findIndex(l => l.meta.level_number === levelNum);

                              if (lastIndex !== -1 && currentIndex !== -1) {
                                const start = Math.min(lastIndex, currentIndex);
                                const end = Math.max(lastIndex, currentIndex);
                                const rangeItems = filteredLevels.slice(start, end + 1).map(l => l.meta.level_number);

                                setSelectedRegenLevels(prev => {
                                  const next = new Set(prev);
                                  rangeItems.forEach(n => next.add(n));
                                  return next;
                                });
                              }
                            } else {
                              // Normal click: toggle single item
                              setSelectedRegenLevels(prev => {
                                const next = new Set(prev);
                                if (isChecked) next.delete(levelNum);
                                else next.add(levelNum);
                                return next;
                              });
                              setLastClickedRegenLevel(levelNum);
                            }
                          }}
                          className="w-4 h-4 rounded border-gray-500 accent-indigo-500"
                          disabled={isBatchRegenerating}
                        />
                      )}
                      <div>
                        <div className={`text-sm font-medium ${isTemplateBased ? 'text-violet-200' : 'text-white'}`}>
                          {isTemplateBased && <span className="text-violet-400 mr-1">📋</span>}
                          레벨 {level.meta.level_number}
                          {isTemplateBased && templateNum && (
                            <span className="ml-2 text-xs text-violet-400 font-normal">
                              ← 템플릿 #{templateNum}
                            </span>
                          )}
                        </div>
                        <div className={`text-xs ${isTemplateBased ? 'text-violet-400' : 'text-gray-400'}`}>
                          난이도: {level.meta.actual_difficulty.toFixed(3)} ({(level.meta.actual_difficulty * 100).toFixed(0)}%)
                          <span className={level.meta.verification_method === 'rl' ? 'text-emerald-400' : 'text-yellow-600'}>
                            {level.meta.verification_method === 'rl' ? ' ✓RL' : ' ~추정'}
                          </span>
                        </div>
                        {level.meta.generated_at && (
                          <div className="text-[10px] text-gray-500">
                            {new Date(level.meta.generated_at).toLocaleString('ko-KR', {
                              month: 'numeric',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Pattern / Template indicator */}
                      {isTemplateBased ? (
                        <span
                          className="text-xs px-1.5 py-0.5 rounded bg-violet-700 text-white font-bold"
                          title={`레벨 템플릿: ${level.meta.template_id}${
                            level.meta.template_source_difficulty != null
                              ? ` (측정 난이도 ${(level.meta.template_source_difficulty * 100).toFixed(0)})`
                              : ''
                          }`}
                        >
                          📋 {templateNum ? `#${templateNum}` : 'tpl'}
                        </span>
                      ) : level.meta.pattern_index !== undefined && level.meta.pattern_index >= 0 ? (
                        <span
                          className="text-xs px-1 py-0.5 rounded bg-purple-900/50 text-purple-300"
                          title={getPatternByIndex(level.meta.pattern_index)?.name || `패턴 ${level.meta.pattern_index}`}
                        >
                          {getPatternByIndex(level.meta.pattern_index)?.icon || '🎨'}
                        </span>
                      ) : null}
                      {/* Tile-deadlock check button — 정적 검사
                          빨강(확정): 타입별 3배수 위반 = 클리어 불가
                          노랑(주의): OOB 타일 (각 레이어 col/row 밖) = 디바이스에서 잘려 픽 불가 → 잠재적 데드락
                          초록(통과): 둘 다 정상 */}
                      {(() => {
                        const div = checkTileDivisibility(level.level_json);
                        const oob = detectOOBTiles(level.level_json);
                        const isDeadlock = !div.ok;
                        const hasOob = !isDeadlock && oob.count > 0;
                        let tooltip: string;
                        if (isDeadlock) {
                          tooltip = `데드락 확정: ${div.offenders.map(o => `${o.type}=${o.count} 잔여${o.remainder}`).join(' · ')}`;
                        } else if (hasOob) {
                          tooltip = `디바이스 잘림 위험: ${oob.count}개 타일이 레이어 col/row 밖 — 디바이스에서 렌더 안 되어 픽 불가`;
                        } else {
                          tooltip = '정적 검사 통과 (타입별 3배수 ✓, OOB 없음)';
                        }
                        return (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              const lines: string[] = [];
                              if (div.ok) {
                                lines.push('타입별 3배수: 통과 ✓');
                                const counts = Object.entries(div.perType)
                                  .sort((a, b) => parseInt(a[0].slice(1)) - parseInt(b[0].slice(1)))
                                  .map(([t, n]) => `${t}=${n}`).join(', ');
                                if (counts) lines.push(`(${counts})`);
                                if (div.internalCount > 0) {
                                  lines.push(`craft/stack 내부 타일 ${div.internalCount}개로 부족분 ${div.neededFromInternal}개 보충 가능 (잔여 ${div.internalCount - div.neededFromInternal}개는 3개씩 매칭).`);
                                }
                              } else {
                                lines.push(`타입별 3배수 위반: ${div.offenders.length}개 (확정 데드락)`);
                                div.offenders.forEach(o => {
                                  lines.push(`  · ${o.type} = ${o.count}개 (잔여 ${o.remainder})`);
                                });
                                if (div.internalCount > 0) {
                                  lines.push(`craft/stack 내부 ${div.internalCount}개로 부족분 ${div.neededFromInternal}개 메우려면 부족 또는 정합 안 맞음.`);
                                }
                                lines.push('→ 끝에 잔여 타일 → 클리어 불가');
                              }
                              if (oob.count === 0) {
                                lines.push('레이어 OOB 타일: 없음 ✓');
                              } else {
                                lines.push(`레이어 OOB 타일: ${oob.count}개 (디바이스에서 잘려 픽 불가)`);
                                oob.detail.slice(0, 5).forEach(d => {
                                  lines.push(`  · L${d.layer} (선언 ${d.declared}) @ ${d.pos} = ${d.tile_type}`);
                                });
                                lines.push('→ 디바이스에서 그 타일이 렌더되지 않아 클리어 불가능할 수 있음');
                              }
                              addNotification(
                                isDeadlock ? 'error' : hasOob ? 'warning' : 'success',
                                `Lv.${level.meta.level_number} 정적 데드락 검사:\n${lines.join('\n')}`
                              );
                            }}
                            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                              isDeadlock
                                ? 'bg-red-700 hover:bg-red-600 text-red-100'
                                : hasOob
                                  ? 'bg-yellow-700 hover:bg-yellow-600 text-yellow-100'
                                  : 'bg-emerald-700 hover:bg-emerald-600 text-emerald-100'
                            }`}
                            title={tooltip}
                          >
                            {isDeadlock ? '🔒 !' : hasOob ? '🔒 ⚠' : '🔒 ✓'}
                          </button>
                        );
                      })()}
                      {/* Validate button */}
                      {(() => {
                        const isValidating = validatingLevels.has(level.meta.level_number);
                        return (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleValidateSingleLevel(level);
                            }}
                            disabled={isValidating || isBatchRegenerating}
                            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                              isValidating
                                ? 'bg-cyan-600 text-white cursor-not-allowed animate-pulse'
                                : 'bg-cyan-700 hover:bg-cyan-600 text-cyan-100'
                            }`}
                            title="봇 시뮬레이션으로 검증"
                          >
                            {isValidating ? <span className="animate-spin inline-block">⟳</span> : '검증'}
                          </button>
                        );
                      })()}
                      {/* Regenerate button with status */}
                      {(() => {
                        const levelProgress = regenProgressMap.get(level.meta.level_number);
                        const isRegen = regeneratingLevels.has(level.meta.level_number);
                        const isDone = levelProgress?.status === 'done';
                        const isFailed = levelProgress?.status === 'failed';

                        return (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              openRegenModal(level.meta.level_number);
                            }}
                            disabled={isRegen || isBatchRegenerating}
                            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                              isRegen
                                ? 'bg-yellow-600 text-white cursor-not-allowed animate-pulse'
                                : isDone
                                  ? 'bg-green-600 hover:bg-green-500 text-white'
                                  : isFailed
                                    ? 'bg-red-600 hover:bg-red-500 text-white'
                                    : 'bg-orange-600 hover:bg-orange-500 text-white'
                            }`}
                            title={isRegen ? '재생성 중...' : isDone ? '재생성 완료 - 다시 재생성' : isFailed ? '재생성 실패 - 다시 시도' : '이 레벨만 재생성'}
                          >
                            {isRegen ? <span className="animate-spin inline-block">⟳</span> : isDone ? '✓ 완료' : isFailed ? '! 실패' : '재생성'}
                          </button>
                        );
                      })()}
                      {/* Match score indicator or test button */}
                      {level.meta.match_score !== undefined && level.meta.match_score > 0 ? (
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          level.meta.match_score >= 70 ? 'bg-green-900/50 text-green-400' :
                          level.meta.match_score >= 50 ? 'bg-yellow-900/50 text-yellow-400' : 'bg-red-900/50 text-red-400'
                        }`}>
                          {level.meta.match_score.toFixed(0)}%
                        </span>
                      ) : (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">
                          미측정
                        </span>
                      )}
                      <span className={`text-sm font-bold ${getGradeColor(level.meta.grade)}`}>
                        {level.meta.grade}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(level.meta.status)}`}>
                        {getStatusLabel(level.meta.status)}
                      </span>
                    </div>
                  </div>
                  {/* Gimmicks indicator */}
                  {(() => {
                    const gimmicks = extractGimmicksFromLevel(level.level_json);
                    if (gimmicks.length === 0) return null;
                    return (
                      <div className="mt-1 flex gap-1">
                        {gimmicks.slice(0, 3).map(gimmick => (
                          <span
                            key={gimmick}
                            className={`px-1.5 py-0.5 rounded text-[10px] text-white ${GIMMICK_COLORS[gimmick] || 'bg-gray-600'}`}
                          >
                            {GIMMICK_NAMES[gimmick] || gimmick}
                          </span>
                        ))}
                        {gimmicks.length > 3 && (
                          <span className="text-[10px] text-gray-500">+{gimmicks.length - 3}</span>
                        )}
                      </div>
                    );
                  })()}
                  {level.meta.playtest_results && level.meta.playtest_results.length > 0 && (
                    <div className="mt-1 text-xs text-gray-500">
                      테스트 {level.meta.playtest_results.length}회
                    </div>
                  )}
                </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="p-3 border-t border-gray-700 text-xs text-gray-400">
          {filteredLevels.length}개 레벨
        </div>
      </div>

      {/* Level preview & play */}
      <div className="flex-1 flex flex-col bg-gray-800 rounded-lg">
        {selectedLevel ? (
          <>
            {/* Level info */}
            <div className="p-4 border-b border-gray-700">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-medium text-white">
                    레벨 {selectedLevel.meta.level_number}
                  </h3>
                  <button
                    onClick={() => setShowLevelJson(!showLevelJson)}
                    className={`px-2 py-0.5 text-xs rounded ${showLevelJson ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
                  >
                    JSON
                  </button>
                </div>
                <span className={`text-xl font-bold ${getGradeColor(selectedLevel.meta.grade)}`}>
                  {selectedLevel.meta.grade}
                </span>
              </div>

              <div className="grid grid-cols-4 gap-4 text-sm">
                <div>
                  <span className="text-gray-400">목표 난이도:</span>
                  <span className="text-white ml-2">{selectedLevel.meta.target_difficulty.toFixed(3)} ({(selectedLevel.meta.target_difficulty * 100).toFixed(0)}%)</span>
                </div>
                <div>
                  <span className="text-gray-400">실제 난이도:</span>
                  <span className="text-white ml-2">{selectedLevel.meta.actual_difficulty.toFixed(3)} ({(selectedLevel.meta.actual_difficulty * 100).toFixed(0)}%)</span>
                  {/* [P2] 측정(RL 실플레이) vs 추정(정적, 검증 전) 구분 */}
                  <span className={`ml-2 text-xs ${selectedLevel.meta.verification_method === 'rl' ? 'text-emerald-400' : 'text-yellow-500'}`}>
                    {selectedLevel.meta.verification_method === 'rl' ? '(RL 실측)' : '(정적 추정·미검증)'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-400">타일:</span>
                  <span className="text-white ml-2">{previewTiles.filter(t => !t.type.startsWith('craft_') && !t.type.startsWith('stack_')).length}개</span>
                  <span className="text-gray-500 ml-1">({previewTiles.filter(t => t.isSelectable && !t.type.startsWith('craft_') && !t.type.startsWith('stack_')).length} 선택가능)</span>
                </div>
                <div>
                  <span className="text-gray-400">상태:</span>
                  <span className={`ml-2 px-2 py-0.5 rounded text-xs ${getStatusColor(selectedLevel.meta.status)}`}>
                    {getStatusLabel(selectedLevel.meta.status)}
                  </span>
                </div>
              </div>

              {/* Gimmicks used in level */}
              {(() => {
                const gimmicks = extractGimmicksFromLevel(selectedLevel.level_json);
                if (gimmicks.length === 0) return null;
                return (
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-sm text-gray-400">기믹:</span>
                    <div className="flex flex-wrap gap-1">
                      {gimmicks.map(gimmick => (
                        <span
                          key={gimmick}
                          className={`px-2 py-0.5 rounded text-xs text-white ${GIMMICK_COLORS[gimmick] || 'bg-gray-600'}`}
                        >
                          {GIMMICK_NAMES[gimmick] || gimmick}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })()}

              {/* [v16] RL 예측 유저 클리어율 (검증 주력 지표) */}
              {selectedLevel.meta.predicted_clear_rate !== undefined && (() => {
                const pred = selectedLevel.meta.predicted_clear_rate ?? 0;
                const tgt = selectedLevel.meta.target_clear_rate;
                const gap = selectedLevel.meta.clear_rate_gap;
                const cls = selectedLevel.meta.rl_classification;
                const passed = selectedLevel.meta.verification_passed;
                const clsLabel: Record<string, string> = {
                  very_easy: '매우쉬움', easy: '쉬움', normal: '보통',
                  hard: '어려움', very_hard: '매우어려움', unclearable_suspect: '⚠️클리어불가의심',
                };
                return (
                  <div className="mt-3 p-2 bg-gray-700/30 rounded">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="text-xs text-gray-400 shrink-0">예측 유저 클리어율:</span>
                      <div className="flex items-center gap-2 min-w-[140px] flex-1">
                        <div className="flex-1 h-2.5 bg-gray-600 rounded-full overflow-hidden">
                          <div className="h-full bg-emerald-500" style={{ width: `${Math.round(pred * 100)}%` }} />
                        </div>
                        <span className="text-sm font-bold text-emerald-300 w-10 text-right">{(pred * 100).toFixed(0)}%</span>
                      </div>
                      {tgt !== undefined && tgt !== null && (
                        <span className="text-[11px] text-gray-400">
                          목표 {(tgt * 100).toFixed(0)}%
                          {gap !== undefined && gap !== null && (
                            <span className={Math.abs(gap) <= 0.10 ? 'text-gray-400' : gap > 0 ? 'text-sky-400' : 'text-orange-400'}>
                              {' '}(gap {gap >= 0 ? '+' : ''}{(gap * 100).toFixed(0)}%p{gap > 0 ? ' 쉬움' : gap < 0 ? ' 어려움' : ''})
                            </span>
                          )}
                        </span>
                      )}
                      {cls && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${cls === 'unclearable_suspect' ? 'bg-red-900/50 text-red-400' : 'bg-gray-600/50 text-gray-300'}`}>
                          {clsLabel[cls] ?? cls}
                        </span>
                      )}
                      {selectedLevel.meta.luck_suspect && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-400" title="실력과 무관하게 운에 좌우되는 레벨 의심">🎲 운빨의심</span>
                      )}
                      {passed !== undefined && (
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${passed ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
                          {passed ? '✓ 통과' : '✗ 미달'}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })()}

              {/* Bot Clear Rate Gauges (레거시 봇 검증 — predicted 없을 때만) */}
              {selectedLevel.meta.bot_clear_rates && (
                <div className="mt-3 p-2 bg-gray-700/30 rounded">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-400 shrink-0">봇 클리어율:</span>
                    <div className="flex-1 flex items-center gap-2">
                      {/* [v15.14] 검증용 3봇만 표시 (average, expert, optimal) */}
                      {(['average', 'expert', 'optimal'] as const).map(bot => {
                        const rate = selectedLevel.meta.bot_clear_rates?.[bot] ?? 0;
                        const percentage = Math.round(rate * 100);
                        const botLabels: Record<string, string> = { average: '보', expert: '전', optimal: '최' };
                        const botColors: Record<string, string> = {
                          average: 'bg-yellow-500', expert: 'bg-green-500', optimal: 'bg-blue-500'
                        };
                        return (
                          <div key={bot} className="flex items-center gap-1" title={`${bot}: ${percentage}%`}>
                            <span className="text-[10px] text-gray-500 w-3">{botLabels[bot]}</span>
                            <div className="w-12 h-2 bg-gray-600 rounded-full overflow-hidden">
                              <div className={`h-full ${botColors[bot]}`} style={{ width: `${percentage}%` }} />
                            </div>
                            <span className="text-[10px] text-gray-300 w-7">{percentage}%</span>
                          </div>
                        );
                      })}
                    </div>
                    {selectedLevel.meta.match_score !== undefined && (
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                        selectedLevel.meta.match_score >= 70 ? 'bg-green-900/50 text-green-400' :
                        selectedLevel.meta.match_score >= 50 ? 'bg-yellow-900/50 text-yellow-400' : 'bg-red-900/50 text-red-400'
                      }`}>
                        일치: {selectedLevel.meta.match_score.toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* [v15.40] 중앙정렬 수정 버튼 */}
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={async () => {
                    try {
                      const levelJson = {
                        ...(selectedLevel.level_json as unknown as Record<string, unknown>),
                        level_number: selectedLevel.meta.level_number,
                      };
                      const response = await fixCentering([levelJson]);
                      if (response.results.length > 0) {
                        const result = response.results[0];
                        if (result.was_modified) {
                          const { saveProductionLevel } = await import('../../storage/productionStorage');
                          const updated = {
                            ...selectedLevel,
                            level_json: result.level_json as unknown as LevelJSON,
                          };
                          await saveProductionLevel(batchId, updated);
                          setSelectedLevel(updated);
                          addNotification('success', `중앙정렬 수정됨 (${result.center_diff_before.toFixed(1)} → ${result.center_diff_after.toFixed(1)})`);
                          loadLevels();
                        } else {
                          addNotification('info', '이미 정렬됨');
                        }
                      }
                    } catch (err) {
                      addNotification('error', '중앙정렬 실패');
                    }
                  }}
                  className="px-3 py-1 text-xs bg-blue-600/30 text-blue-300 rounded hover:bg-blue-600/50 transition-colors"
                >
                  📐 중앙정렬 수정
                </button>
              </div>

              {/* Previous playtest results */}
              {selectedLevel.meta.playtest_results && selectedLevel.meta.playtest_results.length > 0 && (
                <div className="mt-3 p-2 bg-gray-700/50 rounded">
                  <div className="text-xs text-gray-400 mb-1">
                    이전 테스트 결과 ({selectedLevel.meta.playtest_results.length}회)
                  </div>
                  <div className="flex gap-4 text-xs">
                    <span>
                      클리어율: {((selectedLevel.meta.playtest_results.filter(r => r.cleared).length / selectedLevel.meta.playtest_results.length) * 100).toFixed(0)}%
                    </span>
                    <span>
                      평균 재미: {(selectedLevel.meta.playtest_results.reduce((sum, r) => sum + r.fun_rating, 0) / selectedLevel.meta.playtest_results.length).toFixed(1)}
                    </span>
                  </div>
                </div>
              )}

              {/* Level JSON viewer */}
              {showLevelJson && (
                <div className="mt-3 p-2 bg-gray-900 rounded border border-gray-700">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-400">Level JSON</span>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(JSON.stringify(selectedLevel.level_json, null, 2));
                        addNotification('success', 'JSON 복사됨');
                      }}
                      className="px-2 py-0.5 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600"
                    >
                      복사
                    </button>
                  </div>
                  <pre className="text-xs text-gray-300 overflow-auto max-h-[300px] whitespace-pre-wrap font-mono">
                    {JSON.stringify(selectedLevel.level_json, null, 2)}
                  </pre>
                </div>
              )}

              {/* [v15.40] 레이어 실루엣 미리보기 */}
              {(() => {
                const lj = selectedLevel.level_json as unknown as Record<string, unknown>;
                const numLayers = (lj.layer as number) || 1;
                const SILHOUETTE_COLORS = ['#3b82f6', '#22c55e', '#a855f7', '#f97316', '#ec4899', '#06b6d4'];

                // 레이어별 타일 위치 수집
                type SCell = { layers: number[] };
                const layerInfos: { layer: number; cols: number; rows: number; positions: string[] }[] = [];
                for (let i = 0; i < numLayers; i++) {
                  const ld = lj[`layer_${i}`] as Record<string, unknown> | undefined;
                  if (!ld) continue;
                  const tiles = ld.tiles as Record<string, unknown> | undefined;
                  if (!tiles || Object.keys(tiles).length === 0) continue;
                  layerInfos.push({
                    layer: i,
                    cols: parseInt(String(ld.col || '8')),
                    rows: parseInt(String(ld.row || '8')),
                    positions: Object.keys(tiles).filter(k => k.includes('_')),
                  });
                }

                if (layerInfos.length < 2) return null;

                // 기준: L0
                const baseCols = layerInfos[0].cols;
                const baseRows = layerInfos[0].rows;
                const subW = baseCols * 2 + 2;
                const subH = baseRows * 2 + 2;
                const grid: SCell[][] = Array.from({ length: subH }, () =>
                  Array.from({ length: subW }, () => ({ layers: [] }))
                );

                const baseCX = baseCols / 2;
                const baseCY = baseRows / 2;

                for (const lv of layerInfos) {
                  const isOdd = lv.layer % 2 === 1;
                  const lvCX = isOdd ? (lv.cols + 1) / 2 : lv.cols / 2;
                  const lvCY = isOdd ? (lv.rows + 1) / 2 : lv.rows / 2;
                  const shiftX = baseCX - lvCX;
                  const shiftY = baseCY - lvCY;

                  for (const pos of lv.positions) {
                    const [xs, ys] = pos.split('_');
                    const x = parseInt(xs), y = parseInt(ys);
                    const vx = x + (isOdd ? 0.5 : 0) + shiftX;
                    const vy = y + (isOdd ? 0.5 : 0) + shiftY;
                    const sx = Math.round(vx * 2);
                    const sy = Math.round(vy * 2);
                    for (let dy = 0; dy < 2; dy++) {
                      for (let dx = 0; dx < 2; dx++) {
                        const ny = sy + dy, nx = sx + dx;
                        if (ny >= 0 && ny < subH && nx >= 0 && nx < subW) {
                          if (!grid[ny][nx].layers.includes(lv.layer)) {
                            grid[ny][nx].layers.push(lv.layer);
                          }
                        }
                      }
                    }
                  }
                }

                return (
                  <div className="mt-2 p-2 bg-gray-800/50 rounded">
                    <div className="text-[10px] text-gray-500 mb-1">
                      실루엣 ({layerInfos.map(l => `L${l.layer}:${l.cols}×${l.rows}`).join(' ')})
                    </div>
                    <div className="inline-block">
                      {grid.map((row, y) => (
                        <div key={y} className="flex">
                          {row.map((cell, x) => {
                            const has = cell.layers.length > 0;
                            const top = has ? cell.layers[cell.layers.length - 1] : -1;
                            return (
                              <div key={x} style={{
                                width: 3, height: 3,
                                backgroundColor: has ? SILHOUETTE_COLORS[top % SILHOUETTE_COLORS.length] : 'transparent',
                                opacity: has ? 0.8 : 0,
                              }} />
                            );
                          })}
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-1 mt-1">
                      {layerInfos.map(l => (
                        <span key={l.layer} className="text-[8px] text-gray-500 flex items-center gap-0.5">
                          <span style={{ width: 4, height: 4, backgroundColor: SILHOUETTE_COLORS[l.layer % SILHOUETTE_COLORS.length], display: 'inline-block', borderRadius: 1 }} />
                          L{l.layer}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Level preview with test controls overlay */}
            <div ref={previewContainerRef} className="flex-1 relative min-h-[400px] overflow-hidden">
              {/* Background preview - dimmed, no animations */}
              {previewTiles.length > 0 && selectedLevel && (
                <div
                  key={`preview-${selectedLevel.meta.level_number}`}
                  className="absolute inset-0 flex items-center justify-center opacity-50 pointer-events-none [&_*]:!transition-none"
                  style={{
                    transform: `scale(${previewScale})`,
                    transformOrigin: 'center center'
                  }}
                >
                  <GameBoard
                    key={`board-${selectedLevel.meta.level_number}`}
                    tiles={previewTiles}
                    onTileClick={() => {}}
                    tileSize={48}
                    showStats={false}
                    fixedGridSize={7}
                  />
                </div>
              )}

              {/* Controls overlay based on test mode */}
              <div className="absolute inset-0 flex items-center justify-center z-10">
                {testMode === 'manual' && (
                  <Button onClick={handlePlayLevel} className="px-8 py-4 text-lg shadow-2xl bg-indigo-600 hover:bg-indigo-500">
                    ▶ 플레이 시작
                  </Button>
                )}

                {testMode === 'auto_single' && (
                  <div className="flex flex-col items-center gap-4 p-6 bg-gray-900/90 rounded-xl">
                    <div className="text-center">
                      <span className="text-4xl">🤖</span>
                      <h3 className="text-white font-medium mt-2">봇 자동 테스트</h3>
                      <p className="text-sm text-gray-400">봇 프로필로 난이도 검증</p>
                    </div>

                    <div className="flex items-center gap-2">
                      <label className="text-sm text-gray-400">검증:</label>
                      <select
                        value={autoTestIterations}
                        onChange={(e) => setAutoTestIterations(Number(e.target.value))}
                        className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
                        disabled={isAutoTesting}
                      >
                        <option value={30}>⚡ 빠름</option>
                        <option value={100}>⚖️ 보통</option>
                        <option value={200}>🎯 정밀</option>
                      </select>
                    </div>

                    <Button
                      onClick={handleAutoTestSingle}
                      disabled={isAutoTesting}
                      className="px-6 py-3 bg-green-600 hover:bg-green-500"
                    >
                      {isAutoTesting ? (
                        <>
                          <span className="animate-spin mr-2">⟳</span>
                          테스트 중...
                        </>
                      ) : (
                        '🎯 자동 테스트 시작'
                      )}
                    </Button>

                    {/* Auto test result */}
                    {autoTestResult && (
                      <div className="w-full max-w-sm space-y-3">
                        {/* Match Score */}
                        <div className={`p-3 rounded-lg text-center ${
                          autoTestResult.match_score >= 70 ? 'bg-green-900/50' :
                          autoTestResult.match_score >= 50 ? 'bg-yellow-900/50' : 'bg-red-900/50'
                        }`}>
                          <div className="text-xs text-gray-400">난이도 일치도</div>
                          <div className={`text-3xl font-bold ${
                            autoTestResult.match_score >= 70 ? 'text-green-400' :
                            autoTestResult.match_score >= 50 ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {autoTestResult.match_score.toFixed(0)}%
                          </div>
                          <div className="text-xs text-gray-500 mt-1">
                            {autoTestResult.balance_status === 'balanced' ? '✅ 균형' :
                             autoTestResult.balance_status === 'too_easy' ? '📉 너무 쉬움' :
                             autoTestResult.balance_status === 'too_hard' ? '📈 너무 어려움' : '⚠️ 불균형'}
                          </div>
                        </div>

                        {/* [v16] RL 예측 유저 클리어율 (봇 3종 → 통합 1개 게이지) */}
                        {autoTestResult.predicted_clear_rate !== undefined ? (
                          <div className="space-y-1">
                            <div className="text-xs text-gray-400 text-center">예측 유저 클리어율</div>
                            <div className="flex items-center gap-2">
                              <div className="flex-1 h-3 bg-gray-700 rounded-full overflow-hidden">
                                <div className="h-full bg-emerald-500 transition-all duration-300" style={{ width: `${Math.round((autoTestResult.predicted_clear_rate ?? 0) * 100)}%` }} />
                              </div>
                              <span className="text-sm font-bold text-emerald-300 w-10 text-right">{((autoTestResult.predicted_clear_rate ?? 0) * 100).toFixed(0)}%</span>
                            </div>
                            <div className="text-[11px] text-gray-400 text-center">
                              목표 {((autoTestResult.target_clear_rate ?? 0) * 100).toFixed(0)}%
                              {autoTestResult.clear_rate_gap !== undefined && (
                                <span className={Math.abs(autoTestResult.clear_rate_gap) <= 0.12 ? 'text-gray-400' : autoTestResult.clear_rate_gap > 0 ? 'text-sky-400' : 'text-orange-400'}>
                                  {' '}(gap {autoTestResult.clear_rate_gap >= 0 ? '+' : ''}{(autoTestResult.clear_rate_gap * 100).toFixed(0)}%p)
                                </span>
                              )}
                              {autoTestResult.rl_classification === 'unclearable_suspect' && (
                                <span className="text-red-400"> · ⚠️클리어불가의심</span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-1">
                            {autoTestResult.bot_stats.map(bot => {
                              const gap = (bot.clear_rate - bot.target_clear_rate) * 100;
                              const isGood = Math.abs(gap) <= 10;
                              return (
                                <div key={bot.profile} className="flex items-center justify-between text-sm px-2 py-1 bg-gray-700/50 rounded">
                                  <span className="text-gray-300">
                                    {bot.profile === 'novice' ? '🌱 초보자' :
                                     bot.profile === 'casual' ? '🎮 캐주얼' :
                                     bot.profile === 'average' ? '👤 일반' :
                                     bot.profile === 'expert' ? '⭐ 숙련자' : '🏆 최적'}
                                  </span>
                                  <span className="text-white font-medium">
                                    {(bot.clear_rate * 100).toFixed(0)}%
                                  </span>
                                  <span className={`text-xs ${isGood ? 'text-green-400' : 'text-yellow-400'}`}>
                                    ({gap >= 0 ? '+' : ''}{gap.toFixed(0)}%p)
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        )}

                        {/* Recommendations */}
                        {autoTestResult.recommendations.length > 0 && (
                          <div className="text-xs text-gray-400">
                            💡 {autoTestResult.recommendations[0]}
                          </div>
                        )}

                        {/* Regenerate & Enhance buttons when match score is low */}
                        {autoTestResult.match_score < 70 && selectedLevel && (
                          <div className="flex flex-col gap-2">
                            <Button
                              onClick={() => {
                                const levelNum = selectedLevel.meta.level_number;
                                handleRegenerateLevel(levelNum).then(() => {
                                  setAutoTestResult(null);
                                  addNotification('success', `레벨 ${levelNum} 재생성 완료`);
                                });
                              }}
                              disabled={regeneratingLevels.has(selectedLevel.meta.level_number) || enhancingLevels.has(selectedLevel.meta.level_number)}
                              className="w-full py-2 bg-orange-600 hover:bg-orange-500"
                            >
                              {regeneratingLevels.has(selectedLevel.meta.level_number) ? (
                                <>
                                  <span className="animate-spin mr-2">⟳</span>
                                  재생성 중...
                                </>
                              ) : (
                                `🔄 미달 레벨 재생성 (${autoTestResult.match_score.toFixed(0)}%)`
                              )}
                            </Button>
                            <Button
                              onClick={() => {
                                const levelNum = selectedLevel.meta.level_number;
                                handleEnhanceLevel(levelNum).then(() => {
                                  setAutoTestResult(null);
                                });
                              }}
                              disabled={enhancingLevels.has(selectedLevel.meta.level_number) || regeneratingLevels.has(selectedLevel.meta.level_number)}
                              className="w-full py-2 bg-blue-600 hover:bg-blue-500"
                            >
                              {enhancingLevels.has(selectedLevel.meta.level_number) ? (
                                <>
                                  <span className="animate-spin mr-2">⟳</span>
                                  개선 중...
                                </>
                              ) : (
                                `🔧 레벨 개선 (${autoTestResult.match_score.toFixed(0)}%)`
                              )}
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {testMode === 'auto_batch' && (
                  <div className="flex flex-col items-center gap-4 p-6 bg-gray-900/90 rounded-xl">
                    <span className="text-4xl">📋</span>
                    <p className="text-sm text-gray-400">상단의 일괄 테스트 설정을 사용하세요</p>
                    {selectedLevel?.meta.match_score !== undefined && (
                      <div className={`px-4 py-2 rounded-lg ${
                        selectedLevel.meta.match_score >= 70 ? 'bg-green-900/50' :
                        selectedLevel.meta.match_score >= 50 ? 'bg-yellow-900/50' : 'bg-red-900/50'
                      }`}>
                        <span className="text-xs text-gray-400">저장된 일치도: </span>
                        <span className={`font-bold ${
                          selectedLevel.meta.match_score >= 70 ? 'text-green-400' :
                          selectedLevel.meta.match_score >= 50 ? 'text-yellow-400' : 'text-red-400'
                        }`}>
                          {selectedLevel.meta.match_score.toFixed(0)}%
                        </span>
                      </div>
                    )}
                    {/* [v16] RL 예측 유저 클리어율 */}
                    {selectedLevel?.meta.predicted_clear_rate !== undefined && (
                      <div className="w-full max-w-xs space-y-1 mt-2">
                        <div className="text-xs text-gray-400 text-center mb-1">예측 유저 클리어율</div>
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-3 bg-gray-700 rounded-full overflow-hidden">
                            <div className="h-full bg-emerald-500 transition-all duration-300" style={{ width: `${Math.round((selectedLevel.meta.predicted_clear_rate ?? 0) * 100)}%` }} />
                          </div>
                          <span className="text-sm font-bold text-emerald-300 w-10 text-right">{((selectedLevel.meta.predicted_clear_rate ?? 0) * 100).toFixed(0)}%</span>
                        </div>
                        {selectedLevel.meta.target_clear_rate != null && (
                          <div className="text-[11px] text-gray-400 text-center">
                            목표 {((selectedLevel.meta.target_clear_rate ?? 0) * 100).toFixed(0)}%
                            {selectedLevel.meta.clear_rate_gap != null && ` (gap ${selectedLevel.meta.clear_rate_gap >= 0 ? '+' : ''}${((selectedLevel.meta.clear_rate_gap ?? 0) * 100).toFixed(0)}%p)`}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Bot Clear Rate Gauges (레거시 — predicted 없을 때만) */}
                    {/* [v15.14] 검증용 3봇만 표시 (average, expert, optimal) */}
                    {selectedLevel?.meta.bot_clear_rates && (
                      <div className="w-full max-w-xs space-y-2 mt-2">
                        <div className="text-xs text-gray-400 text-center mb-2">봇별 클리어율</div>
                        {(['average', 'expert', 'optimal'] as const).map(bot => {
                          const rate = selectedLevel.meta.bot_clear_rates?.[bot] ?? 0;
                          const percentage = Math.round(rate * 100);
                          const botLabels: Record<string, string> = {
                            average: '보통',
                            expert: '전문가',
                            optimal: '최적'
                          };
                          const botColors: Record<string, string> = {
                            average: 'bg-yellow-500',
                            expert: 'bg-green-500',
                            optimal: 'bg-blue-500'
                          };
                          return (
                            <div key={bot} className="flex items-center gap-2">
                              <span className="text-xs text-gray-400 w-14 text-right">{botLabels[bot]}</span>
                              <div className="flex-1 h-3 bg-gray-700 rounded-full overflow-hidden">
                                <div
                                  className={`h-full ${botColors[bot]} transition-all duration-300`}
                                  style={{ width: `${percentage}%` }}
                                />
                              </div>
                              <span className="text-xs text-white w-10 text-right">{percentage}%</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            왼쪽에서 테스트할 레벨을 선택하세요
          </div>
        )}
      </div>
      </div>

      {/* Pattern Selection Modal for Regeneration */}
      {regenModalOpen && regenModalLevel !== null && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-50"
            onClick={() => setRegenModalOpen(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-gray-800 rounded-xl border border-gray-600 shadow-2xl w-full max-w-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-4 border-b border-gray-700">
                <h3 className="text-lg font-semibold text-white">
                  레벨 {regenModalLevel} 재생성
                </h3>
                <p className="text-sm text-gray-400 mt-1">
                  원하는 패턴과 대칭 모드를 선택하세요
                </p>
              </div>

              <div className="p-4 space-y-4">
                {/* Generation Mode Selection */}
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    생성 모드
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={() => setRegenGenerationMode('quick')}
                      className={`flex items-center gap-2 px-3 py-3 rounded-lg border transition-colors ${
                        regenGenerationMode === 'quick'
                          ? 'bg-blue-600 border-blue-500 text-white'
                          : 'bg-gray-700 border-gray-600 text-gray-300 hover:border-gray-500'
                      }`}
                    >
                      <span className="text-xl">⚡</span>
                      <div className="text-left">
                        <div className="text-sm font-medium">빠른 생성</div>
                        <div className="text-xs opacity-75">레이어별 다른 패턴</div>
                      </div>
                    </button>
                    <button
                      onClick={() => setRegenGenerationMode('pattern')}
                      className={`flex items-center gap-2 px-3 py-3 rounded-lg border transition-colors ${
                        regenGenerationMode === 'pattern'
                          ? 'bg-blue-600 border-blue-500 text-white'
                          : 'bg-gray-700 border-gray-600 text-gray-300 hover:border-gray-500'
                      }`}
                    >
                      <span className="text-xl">✨</span>
                      <div className="text-left">
                        <div className="text-sm font-medium">패턴 생성</div>
                        <div className="text-xs opacity-75">일관된 타일 배치</div>
                      </div>
                    </button>
                  </div>
                  <p className="text-xs text-gray-400 mt-2">
                    {regenGenerationMode === 'quick'
                      ? '⚡ 각 레이어가 독립적인 패턴으로 생성됩니다.'
                      : '✨ 모든 레이어가 동일한 타일 위치를 공유합니다.'}
                  </p>
                </div>

                {/* Pattern Selection - Only shown in pattern mode */}
                {regenGenerationMode === 'pattern' && (
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      맵 패턴
                    </label>
                    {/* Auto selection button */}
                    <button
                      onClick={() => setRegenPatternIndex(undefined)}
                      className={`mb-2 px-3 py-1.5 rounded-lg text-sm flex items-center gap-2 transition-colors w-full justify-center ${
                        regenPatternIndex === undefined
                          ? 'bg-blue-600 text-white border border-blue-500'
                          : 'bg-gray-700 text-gray-300 border border-gray-600 hover:border-gray-500'
                      }`}
                    >
                      <span>🎲</span>
                      <span>자동 선택 (보스 레벨용 패턴 자동 지정)</span>
                    </button>
                    {/* Scrollable Pattern Grid */}
                    <div className="max-h-72 overflow-y-auto bg-gray-900/50 rounded-lg p-3 border border-gray-700">
                      {PATTERN_CATEGORIES.map(category => (
                        <div key={category.id} className="mb-3 last:mb-0">
                          <div className="text-xs text-gray-400 mb-1.5 sticky top-0 bg-gray-900/95 px-1 py-0.5 font-medium">
                            {category.nameKo}
                          </div>
                          <div className="grid grid-cols-10 gap-1.5">
                            {category.patterns.map(pattern => (
                              <button
                                key={pattern.index}
                                onClick={() => setRegenPatternIndex(pattern.index)}
                                className={`p-2 rounded-lg text-xl transition-colors ${
                                  regenPatternIndex === pattern.index
                                    ? 'bg-blue-600 text-white ring-2 ring-blue-400 scale-110'
                                    : 'bg-gray-700 hover:bg-gray-600 text-gray-200 hover:scale-105'
                                }`}
                                title={`${pattern.nameKo} (${pattern.index})`}
                              >
                                {pattern.icon}
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Symmetry Mode Selection - Only shown in quick mode */}
                {regenGenerationMode === 'quick' && (
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      대칭 모드
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { value: 'none', label: '없음', icon: '⊘' },
                        { value: 'horizontal', label: '수평', icon: '↔️' },
                        { value: 'vertical', label: '수직', icon: '↕️' },
                        { value: 'both', label: '양방향', icon: '✚' },
                      ].map(option => (
                        <button
                          key={option.value}
                          onClick={() => setRegenSymmetryMode(option.value as typeof regenSymmetryMode)}
                          className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-colors ${
                            regenSymmetryMode === option.value
                              ? 'bg-blue-600 border-blue-500 text-white'
                              : 'bg-gray-700 border-gray-600 text-gray-300 hover:border-gray-500'
                          }`}
                        >
                          <span>{option.icon}</span>
                          <span className="text-sm">{option.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Preview Info */}
                <div className="bg-gray-700/50 rounded-lg p-3">
                  <div className="text-xs text-gray-400 mb-1">선택된 설정</div>
                  <div className="flex items-center gap-3 text-sm flex-wrap">
                    <span className="text-gray-300">
                      모드: {regenGenerationMode === 'quick' ? '⚡ 빠른 생성' : '✨ 패턴 생성'}
                    </span>
                    {regenGenerationMode === 'pattern' && (
                      <>
                        <span className="text-gray-500">|</span>
                        <span className="text-gray-300">
                          패턴: {regenPatternIndex !== undefined
                            ? `${getPatternByIndex(regenPatternIndex)?.icon} ${getPatternByIndex(regenPatternIndex)?.nameKo}`
                            : '🎲 자동 선택'}
                        </span>
                      </>
                    )}
                    {regenGenerationMode === 'quick' && (
                      <>
                        <span className="text-gray-500">|</span>
                        <span className="text-gray-300">
                          대칭: {regenSymmetryMode === 'none' ? '없음' :
                                 regenSymmetryMode === 'horizontal' ? '수평' :
                                 regenSymmetryMode === 'vertical' ? '수직' : '양방향'}
                        </span>
                      </>
                    )}
                  </div>
                </div>
              </div>

              <div className="p-4 border-t border-gray-700 flex justify-end gap-2">
                <button
                  onClick={() => setRegenModalOpen(false)}
                  className="px-4 py-2 text-sm bg-gray-700 text-gray-300 rounded-lg hover:bg-gray-600 transition-colors"
                >
                  취소
                </button>
                <button
                  onClick={handleRegenFromModal}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-500 transition-colors"
                >
                  재생성 시작
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// Playtest Tab Component
function PlaytestTab({
  batchId,
  onLevelSelect,
}: {
  batchId: string;
  onLevelSelect?: (level: ProductionLevel) => void;
}) {
  const { addNotification } = useUIStore();
  const [queue, setQueue] = useState<ProductionLevel[]>([]);
  const [currentLevel, setCurrentLevel] = useState<ProductionLevel | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Playtest form state
  const [cleared, setCleared] = useState(true);
  const [attempts, setAttempts] = useState(1);
  const [timeSeconds, setTimeSeconds] = useState(60);
  const [perceivedDifficulty, setPerceivedDifficulty] = useState<1|2|3|4|5>(3);
  const [funRating, setFunRating] = useState<1|2|3|4|5>(3);
  const [comments, setComments] = useState('');
  const [issues, setIssues] = useState<string[]>([]);

  useEffect(() => {
    loadQueue();
  }, [batchId]);

  const loadQueue = async () => {
    setIsLoading(true);
    try {
      const queueLevels = await getPlaytestQueue(batchId, 50);
      setQueue(queueLevels);
      if (queueLevels.length > 0 && !currentLevel) {
        setCurrentLevel(queueLevels[0]);
        onLevelSelect?.(queueLevels[0]);
      }
    } catch (err) {
      console.error('Failed to load playtest queue:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmitResult = async () => {
    if (!currentLevel) return;

    const result: PlaytestResult = {
      tester_id: 'default',
      tester_name: '테스터',
      tested_at: new Date().toISOString(),
      cleared,
      attempts,
      time_seconds: timeSeconds,
      perceived_difficulty: perceivedDifficulty,
      fun_rating: funRating,
      comments,
      issues,
    };

    try {
      await addPlaytestResult(batchId, currentLevel.meta.level_number, result);
      addNotification('success', `레벨 ${currentLevel.meta.level_number} 테스트 완료`);

      // Move to next level
      const nextLevel = queue.find(l => l.meta.level_number > currentLevel.meta.level_number);
      if (nextLevel) {
        setCurrentLevel(nextLevel);
        onLevelSelect?.(nextLevel);
      } else {
        setCurrentLevel(null);
      }

      // Reset form
      setCleared(true);
      setAttempts(1);
      setTimeSeconds(60);
      setPerceivedDifficulty(3);
      setFunRating(3);
      setComments('');
      setIssues([]);

      // Reload queue
      loadQueue();
    } catch (err) {
      addNotification('error', '결과 저장 실패');
    }
  };

  if (isLoading) {
    return <div className="text-center text-gray-400 py-8">로딩 중...</div>;
  }

  if (queue.length === 0) {
    return (
      <div className="text-center text-gray-400 py-8">
        플레이테스트 대기열이 비어있습니다.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4">
      {/* Queue List */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">
          대기열 ({queue.length}개)
        </h3>
        <div className="space-y-1 max-h-96 overflow-y-auto">
          {queue.map((level) => (
            <button
              key={level.meta.level_number}
              onClick={() => {
                setCurrentLevel(level);
                onLevelSelect?.(level);
              }}
              className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                currentLevel?.meta.level_number === level.meta.level_number
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              <div className="flex justify-between">
                <span>레벨 {level.meta.level_number}</span>
                <span className={getGradeColor(level.meta.grade)}>{level.meta.grade}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Playtest Form */}
      {currentLevel && (
        <div className="p-4 bg-gray-800 rounded-lg space-y-4">
          <h3 className="text-sm font-medium text-white">
            레벨 {currentLevel.meta.level_number} 테스트
          </h3>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">클리어 여부</label>
              <select
                value={cleared ? 'yes' : 'no'}
                onChange={(e) => setCleared(e.target.value === 'yes')}
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value="yes">클리어</option>
                <option value="no">실패</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">시도 횟수</label>
              <input
                type="number"
                value={attempts}
                onChange={(e) => setAttempts(Number(e.target.value))}
                min={1}
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">체감 난이도</label>
              <select
                value={perceivedDifficulty}
                onChange={(e) => setPerceivedDifficulty(Number(e.target.value) as 1|2|3|4|5)}
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value={1}>1 - 매우 쉬움</option>
                <option value={2}>2 - 쉬움</option>
                <option value={3}>3 - 보통</option>
                <option value={4}>4 - 어려움</option>
                <option value={5}>5 - 매우 어려움</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">재미 점수</label>
              <select
                value={funRating}
                onChange={(e) => setFunRating(Number(e.target.value) as 1|2|3|4|5)}
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value={1}>1 - 지루함</option>
                <option value={2}>2 - 별로</option>
                <option value={3}>3 - 보통</option>
                <option value={4}>4 - 재미있음</option>
                <option value={5}>5 - 매우 재미있음</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">코멘트</label>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              rows={2}
            />
          </div>

          <Button onClick={handleSubmitResult} className="w-full">
            결과 저장 & 다음 레벨
          </Button>
        </div>
      )}
    </div>
  );
}

// Review Tab Component
type ReviewFilter = LevelStatus | 'all' | 'needs_attention';

function ReviewTab({
  batchId,
  onLevelSelect,
  onStatsUpdate,
}: {
  batchId: string;
  onLevelSelect?: (level: ProductionLevel) => void;
  onStatsUpdate: () => void;
}) {
  const { addNotification } = useUIStore();
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [allLevels, setAllLevels] = useState<ProductionLevel[]>([]);
  const [filter, setFilter] = useState<ReviewFilter>('all');
  const [isLoading, setIsLoading] = useState(true);
  const [showBatchApproval, setShowBatchApproval] = useState(false);

  useEffect(() => {
    loadLevels();
  }, [batchId]);

  useEffect(() => {
    applyFilter();
  }, [allLevels, filter]);

  const loadLevels = async () => {
    setIsLoading(true);
    try {
      const loadedLevels = await getProductionLevelsByBatch(batchId, {
        limit: 2000,
      });
      setAllLevels(loadedLevels);
    } catch (err) {
      console.error('Failed to load levels:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const applyFilter = () => {
    let filtered = allLevels;

    if (filter === 'needs_attention') {
      // 주의 필요: 매치점수 60% 미만 OR D등급 OR 플레이테스트 이슈 있음
      filtered = allLevels.filter(l => {
        const matchScore = l.meta.match_score ?? 100;
        const hasIssues = l.meta.playtest_results?.some(r => r.issues.length > 0);
        return matchScore < 60 || l.meta.grade === 'D' || hasIssues;
      });
    } else if (filter !== 'all') {
      filtered = allLevels.filter(l => l.meta.status === filter);
    }

    setLevels(filtered);
  };

  // 주의 필요 레벨 수 계산
  const needsAttentionCount = useMemo(() => {
    return allLevels.filter(l => {
      const matchScore = l.meta.match_score ?? 100;
      const hasIssues = l.meta.playtest_results?.some(r => r.issues.length > 0);
      return matchScore < 60 || l.meta.grade === 'D' || hasIssues;
    }).length;
  }, [allLevels]);

  // 레벨 상태별 배경색 계산
  const getLevelBgColor = (level: ProductionLevel): string => {
    const matchScore = level.meta.match_score ?? 100;
    const grade = level.meta.grade;
    const hasIssues = level.meta.playtest_results?.some(r => r.issues.length > 0);

    // 빨강: 매치점수 60% 미만 OR D등급
    if (matchScore < 60 || grade === 'D') {
      return 'bg-red-900/30 border-l-4 border-red-500';
    }

    // 노랑: 매치점수 60-79% OR C등급 OR 이슈 있음
    if (matchScore < 80 || grade === 'C' || hasIssues) {
      return 'bg-yellow-900/20 border-l-4 border-yellow-500';
    }

    // 초록: 승인됨
    if (level.meta.status === 'approved' || level.meta.status === 'exported') {
      return 'bg-green-900/20 border-l-4 border-green-500';
    }

    // 기본
    return 'bg-gray-800';
  };

  // 이슈 아이콘 표시
  const getIssueIcon = (level: ProductionLevel): string | null => {
    const matchScore = level.meta.match_score ?? 100;
    const hasPlaytestIssues = level.meta.playtest_results?.some(r => r.issues.length > 0);
    const hasBug = level.meta.playtest_results?.some(r =>
      r.issues.some(i => i.toLowerCase().includes('bug') || i.toLowerCase().includes('버그'))
    );

    if (hasBug) return '🐛';
    if (hasPlaytestIssues) return '⚠️';
    if (matchScore < 60) return '⚠️';
    if (level.meta.status === 'approved') return '✓';
    return null;
  };

  const handleApprove = async (levelNumber: number) => {
    try {
      await approveLevel(batchId, levelNumber, '관리자');
      addNotification('success', `레벨 ${levelNumber} 승인됨`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      addNotification('error', '승인 실패');
    }
  };

  const handleReject = async (levelNumber: number, reason: string) => {
    try {
      await rejectLevel(batchId, levelNumber, reason);
      addNotification('info', `레벨 ${levelNumber} 거부됨`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      addNotification('error', '거부 실패');
    }
  };

  // [v15.40] 개별 레벨 중앙정렬
  const [centeringLevel, setCenteringLevel] = useState<number | null>(null);
  const handleFixCenteringSingle = async (level: ProductionLevel) => {
    const levelNumber = level.meta.level_number;
    setCenteringLevel(levelNumber);
    try {
      const levelJson = {
        ...(level.level_json as unknown as Record<string, unknown>),
        level_number: levelNumber,
      };
      const response = await fixCentering([levelJson]);
      if (response.results.length > 0) {
        const result = response.results[0];
        if (result.was_modified) {
          const { saveProductionLevel } = await import('../../storage/productionStorage');
          await saveProductionLevel(batchId, {
            ...level,
            level_json: result.level_json as unknown as LevelJSON,
          });
          addNotification('success', `레벨 ${levelNumber} 중앙정렬 수정됨 (${result.center_diff_before.toFixed(1)} → ${result.center_diff_after.toFixed(1)})`);
          loadLevels();
        } else {
          addNotification('info', `레벨 ${levelNumber}: 이미 정렬됨`);
        }
      }
    } catch (err) {
      addNotification('error', `레벨 ${levelNumber} 중앙정렬 실패`);
    } finally {
      setCenteringLevel(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* Mode Toggle */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <button
            onClick={() => setShowBatchApproval(false)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              !showBatchApproval
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            개별 검토
          </button>
          <button
            onClick={() => setShowBatchApproval(true)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              showBatchApproval
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            배치 승인
          </button>
        </div>
      </div>

      {/* Batch Approval Panel */}
      {showBatchApproval ? (
        <BatchApprovalPanel
          batchId={batchId}
          onComplete={() => setShowBatchApproval(false)}
          onStatsUpdate={() => {
            loadLevels();
            onStatsUpdate();
          }}
        />
      ) : (
        <>
          {/* Filter */}
          <div className="flex gap-2 flex-wrap">
            {[
              { value: 'all', label: '전체' },
              { value: 'needs_attention', label: `주의 필요 ⚠️ ${needsAttentionCount}`, highlight: needsAttentionCount > 0 },
              { value: 'generated', label: '생성됨' },
              { value: 'needs_rework', label: '수정필요' },
              { value: 'approved', label: '승인됨' },
              { value: 'rejected', label: '거부됨' },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => setFilter(opt.value as ReviewFilter)}
                className={`px-3 py-1 rounded text-sm transition-colors ${
                  filter === opt.value
                    ? 'bg-indigo-600 text-white'
                    : opt.highlight
                      ? 'bg-red-900/50 text-red-200 border border-red-700 hover:bg-red-900/70'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* Level List */}
          {isLoading ? (
            <div className="text-center text-gray-400 py-8">로딩 중...</div>
          ) : (
            <div className="space-y-2 max-h-[500px] overflow-y-auto">
              {levels.length === 0 ? (
                <div className="text-center text-gray-500 py-8">
                  {filter === 'needs_attention' ? '주의가 필요한 레벨이 없습니다' : '레벨이 없습니다'}
                </div>
              ) : (
                levels.map((level) => (
                  <div
                    key={level.meta.level_number}
                    className={`flex items-center justify-between p-3 rounded-lg transition-colors ${getLevelBgColor(level)}`}
                  >
                    <div className="flex items-center gap-4">
                      <button
                        onClick={() => onLevelSelect?.(level)}
                        className="text-indigo-400 hover:text-indigo-300 font-medium"
                      >
                        레벨 {level.meta.level_number}
                      </button>
                      <span className={getGradeColor(level.meta.grade)}>{level.meta.grade}</span>
                      <span className="text-xs text-gray-400">
                        매치 {level.meta.match_score?.toFixed(0) ?? '-'}%
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(level.meta.status)}`}>
                        {getStatusLabel(level.meta.status)}
                      </span>
                      {getIssueIcon(level) && (
                        <span className="text-sm">{getIssueIcon(level)}</span>
                      )}
                    </div>
                    <div className="flex gap-2">
                      {/* [v15.40] 중앙정렬 버튼 */}
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={centeringLevel === level.meta.level_number}
                        onClick={() => handleFixCenteringSingle(level)}
                      >
                        {centeringLevel === level.meta.level_number ? '...' : '정렬'}
                      </Button>
                      {level.meta.status !== 'approved' && level.meta.status !== 'exported' && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleApprove(level.meta.level_number)}
                        >
                          승인
                        </Button>
                      )}
                      {level.meta.status !== 'rejected' && (
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => {
                            const reason = prompt('거부 사유:');
                            if (reason) handleReject(level.meta.level_number, reason);
                          }}
                        >
                          거부
                        </Button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Helper Components
function StatCard({ label, value, total, color = 'blue' }: {
  label: string;
  value: number;
  total?: number;
  color?: 'blue' | 'green' | 'red' | 'yellow';
}) {
  const colorClasses = {
    blue: 'text-blue-400',
    green: 'text-green-400',
    red: 'text-red-400',
    yellow: 'text-yellow-400',
  };

  return (
    <div className="p-3 bg-gray-800 rounded-lg">
      <div className="text-xs text-gray-400">{label}</div>
      <div className={`text-xl font-bold ${colorClasses[color]}`}>
        {value}
        {total && <span className="text-sm text-gray-500">/{total}</span>}
      </div>
    </div>
  );
}

function StatusBar({ label, count, total, color }: {
  label: string;
  count: number;
  total: number;
  color: 'blue' | 'green' | 'yellow' | 'purple';
}) {
  const percent = total > 0 ? (count / total) * 100 : 0;
  const colorClasses = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    yellow: 'bg-yellow-500',
    purple: 'bg-purple-500',
  };

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-400">{label}</span>
        <span className="text-gray-300">{count}</span>
      </div>
      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${colorClasses[color]}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function getGradeColor(grade: DifficultyGrade): string {
  switch (grade) {
    case 'S': return 'text-green-400';
    case 'A': return 'text-blue-400';
    case 'B': return 'text-yellow-400';
    case 'C': return 'text-orange-400';
    case 'D': return 'text-red-400';
    default: return 'text-gray-400';
  }
}

function getStatusColor(status: LevelStatus): string {
  switch (status) {
    case 'generated': return 'bg-blue-900 text-blue-300';
    case 'playtest_queue': return 'bg-yellow-900 text-yellow-300';
    case 'playtesting': return 'bg-orange-900 text-orange-300';
    case 'approved': return 'bg-green-900 text-green-300';
    case 'rejected': return 'bg-red-900 text-red-300';
    case 'needs_rework': return 'bg-purple-900 text-purple-300';
    case 'exported': return 'bg-indigo-900 text-indigo-300';
    default: return 'bg-gray-700 text-gray-300';
  }
}

function getStatusLabel(status: LevelStatus): string {
  switch (status) {
    case 'generated': return '생성됨';
    case 'playtest_queue': return '테스트 대기';
    case 'playtesting': return '테스트 중';
    case 'approved': return '승인됨';
    case 'rejected': return '거부됨';
    case 'needs_rework': return '수정필요';
    case 'exported': return '출시됨';
    default: return status;
  }
}

// [v15.55] 레벨 템플릿 할당 패널 — 프로덕션 생성 전 특정 레벨에 템플릿을 바인딩
interface TemplateMeta {
  template_id: string;
  name: string;
  source_level_id?: string | null;
  measured_difficulty?: number | null;
  autoplay_grade?: string | null;
  layer_count: number;
  total_tiles: number;
}

function TemplateAssignmentPanel({
  batch,
  assignments,
  onAssignmentsChange,
  autoAssign,
  onAutoAssignChange,
}: {
  batch: ProductionBatch;
  assignments: Record<number, string>;
  onAssignmentsChange: (next: Record<number, string>) => void;
  autoAssign: boolean;
  onAutoAssignChange: (v: boolean) => void;
}) {
  const [templates, setTemplates] = useState<TemplateMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [manualAssignInput, setManualAssignInput] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await apiClient.get('/debug/level-templates');
        if (!cancelled) setTemplates(res.data.templates || []);
      } catch {
        if (!cancelled) setTemplates([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const batchRange = useMemo(() => {
    // batch의 시작/끝 레벨 범위 — batch에 level_numbers가 있으면 그 범위, 없으면 1..total
    const n = batch.total_levels || 1000;
    return { start: 1, end: n };
  }, [batch.total_levels]);

  const parseSourceLevelNum = (sourceId?: string | null): number | null => {
    if (!sourceId) return null;
    const m = sourceId.match(/(\d+)/);
    return m ? parseInt(m[1]) : null;
  };

  const handleManualAssign = (templateId: string) => {
    const inp = manualAssignInput[templateId]?.trim();
    if (!inp) return;
    const n = parseInt(inp);
    if (!isFinite(n) || n < 1) {
      alert('올바른 레벨 번호를 입력하세요.');
      return;
    }
    if (n < batchRange.start || n > batchRange.end) {
      if (!window.confirm(`레벨 ${n}은 배치 범위(${batchRange.start}~${batchRange.end}) 밖입니다. 그래도 할당할까요?`)) return;
    }
    const next = { ...assignments };
    // 같은 레벨에 다른 템플릿 이미 있으면 덮어쓰기 확인
    if (next[n] && next[n] !== templateId) {
      const prev = templates.find(t => t.template_id === next[n]);
      if (!window.confirm(`레벨 ${n}은 이미 "${prev?.name || next[n]}" 에 할당됨. 덮어쓸까요?`)) return;
    }
    // 같은 템플릿이 다른 레벨에 할당된 경우 해제
    for (const k of Object.keys(next)) {
      if (next[parseInt(k)] === templateId) delete next[parseInt(k)];
    }
    next[n] = templateId;
    onAssignmentsChange(next);
    setManualAssignInput(prev => ({ ...prev, [templateId]: '' }));
  };

  const handleClear = (levelNum: number) => {
    const next = { ...assignments };
    delete next[levelNum];
    onAssignmentsChange(next);
  };

  const handleClearAll = () => {
    if (!window.confirm('모든 템플릿 할당을 해제할까요?')) return;
    onAssignmentsChange({});
  };

  const handleAutoFillFromSource = () => {
    const next = { ...assignments };
    const warns: string[] = [];
    let added = 0;
    for (const tpl of templates) {
      const alreadyAssigned = Object.values(next).includes(tpl.template_id);
      if (alreadyAssigned) continue;
      const sourceNum = parseSourceLevelNum(tpl.source_level_id);
      if (sourceNum === null) {
        warns.push(`${tpl.name}: source 번호 파싱 실패`);
        continue;
      }
      if (sourceNum < batchRange.start || sourceNum > batchRange.end) {
        warns.push(`${tpl.name}: source ${sourceNum} 배치 범위 밖`);
        continue;
      }
      if (next[sourceNum]) {
        warns.push(`${tpl.name}: 레벨 ${sourceNum} 이미 할당됨`);
        continue;
      }
      next[sourceNum] = tpl.template_id;
      added++;
    }
    onAssignmentsChange(next);
    setWarnings(warns);
    if (added === 0 && warns.length === 0) {
      setWarnings(['자동 할당 가능한 템플릿이 없습니다.']);
    }
  };

  const assignedEntries = Object.entries(assignments)
    .map(([k, v]) => ({ level: parseInt(k), templateId: v }))
    .sort((a, b) => a.level - b.level);

  const unassignedCount = templates.filter(
    t => !Object.values(assignments).includes(t.template_id)
  ).length;
  const unmeasuredCount = templates.filter(t => t.measured_difficulty == null).length;

  return (
    <div className="bg-gray-800 rounded-lg p-3 border border-violet-900/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-violet-300">
            📋 레벨 템플릿 할당 ({assignedEntries.length}개 할당됨)
          </span>
          {templates.length > 0 && (
            <span className="text-[10px] text-gray-500">
              전체 {templates.length} · 미할당 {unassignedCount} · 미측정 {unmeasuredCount}
            </span>
          )}
        </div>
        <span className="text-xs text-violet-500">{expanded ? '접기' : '펼치기'}</span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {loading && <div className="text-xs text-gray-500">로딩 중...</div>}

          {!loading && templates.length === 0 && (
            <div className="text-xs text-gray-500 bg-gray-900/50 rounded p-3 text-center">
              저장된 레벨 템플릿이 없습니다.<br />
              패턴 임포트 탭에서 레벨 템플릿을 먼저 저장하세요.
            </div>
          )}

          {templates.length > 0 && (
            <>
              {/* 자동 배치 토글 */}
              <div className="flex items-center gap-2 bg-gray-900/50 rounded p-2">
                <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
                  <input type="checkbox" checked={autoAssign}
                    onChange={e => onAutoAssignChange(e.target.checked)}
                    className="accent-violet-500" />
                  미할당 템플릿 자동 배치 (측정 난이도 기반)
                </label>
                <span className="text-[10px] text-gray-500">
                  수동 할당 외 템플릿은 measured_difficulty에 맞는 레벨 슬롯에 자동 삽입
                </span>
              </div>

              {/* 수동 할당 — 템플릿 목록 */}
              <details open className="bg-gray-900/50 rounded p-2">
                <summary className="text-xs font-medium text-gray-300 cursor-pointer mb-2">
                  수동 할당 ({templates.length}개 템플릿)
                </summary>
                <div className="flex flex-wrap gap-1 mb-2">
                  <button
                    onClick={handleAutoFillFromSource}
                    className="px-2 py-0.5 rounded text-[10px] bg-violet-700 hover:bg-violet-600 text-white"
                    title="source_level_id 번호 기반 일괄 할당"
                  >
                    🎯 source 번호로 일괄 자동 채우기
                  </button>
                  {assignedEntries.length > 0 && (
                    <button
                      onClick={handleClearAll}
                      className="px-2 py-0.5 rounded text-[10px] bg-red-900/40 hover:bg-red-800 text-red-300"
                    >
                      🗑️ 전체 해제
                    </button>
                  )}
                </div>
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {templates.map(tpl => {
                    const assignedLevel = Object.entries(assignments).find(([, v]) => v === tpl.template_id)?.[0];
                    const sourceNum = parseSourceLevelNum(tpl.source_level_id);
                    return (
                      <div key={tpl.template_id}
                        className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] ${
                          assignedLevel ? 'bg-violet-900/40 border border-violet-700' : 'bg-gray-800'
                        }`}
                      >
                        <span className="flex-1 truncate text-gray-300" title={tpl.template_id}>
                          {tpl.name}
                          <span className="ml-1 text-gray-500">({tpl.layer_count}L, {tpl.total_tiles}t)</span>
                          {tpl.measured_difficulty != null ? (
                            <span className="ml-1 text-blue-300">📊 {(tpl.measured_difficulty * 100).toFixed(0)}</span>
                          ) : (
                            <span className="ml-1 text-gray-600">📊 -</span>
                          )}
                        </span>
                        {assignedLevel ? (
                          <>
                            <span className="text-violet-300 shrink-0">→ 레벨 {assignedLevel}</span>
                            <button onClick={() => handleClear(parseInt(assignedLevel))}
                              className="text-red-400 hover:text-red-300 shrink-0">✕</button>
                          </>
                        ) : (
                          <>
                            <input
                              type="number"
                              min={batchRange.start} max={batchRange.end}
                              value={manualAssignInput[tpl.template_id] || ''}
                              onChange={e => setManualAssignInput(prev => ({ ...prev, [tpl.template_id]: e.target.value }))}
                              placeholder={sourceNum ? `${sourceNum}` : '레벨#'}
                              className="w-14 px-1 py-0.5 bg-gray-700 border border-gray-600 rounded text-white text-[10px]"
                              onKeyDown={e => e.key === 'Enter' && handleManualAssign(tpl.template_id)}
                            />
                            <button onClick={() => handleManualAssign(tpl.template_id)}
                              className="px-1.5 py-0.5 rounded text-[10px] bg-violet-700 hover:bg-violet-600 text-white shrink-0"
                            >할당</button>
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              </details>

              {/* 현재 할당 목록 */}
              {assignedEntries.length > 0 && (
                <details open className="bg-gray-900/50 rounded p-2">
                  <summary className="text-xs font-medium text-green-400 cursor-pointer mb-2">
                    할당 완료 ({assignedEntries.length}개)
                  </summary>
                  <div className="max-h-32 overflow-y-auto space-y-0.5">
                    {assignedEntries.map(({ level, templateId }) => {
                      const tpl = templates.find(t => t.template_id === templateId);
                      return (
                        <div key={level} className="flex items-center gap-1 text-[10px] px-2 py-0.5">
                          <span className="text-gray-400 w-12">Lv.{level}</span>
                          <span className="text-violet-300 flex-1 truncate">
                            ← {tpl?.name || templateId}
                            {tpl?.measured_difficulty != null && (
                              <span className="ml-1 text-blue-400">📊{(tpl.measured_difficulty * 100).toFixed(0)}</span>
                            )}
                          </span>
                          <button onClick={() => handleClear(level)}
                            className="text-red-400 hover:text-red-300">✕</button>
                        </div>
                      );
                    })}
                  </div>
                </details>
              )}

              {warnings.length > 0 && (
                <div className="bg-yellow-900/30 border border-yellow-700 rounded p-2 space-y-0.5 max-h-24 overflow-y-auto">
                  <div className="text-[10px] text-yellow-300 font-medium">⚠️ 자동 할당 경고 ({warnings.length})</div>
                  {warnings.map((w, i) => (
                    <div key={i} className="text-[10px] text-yellow-400">{w}</div>
                  ))}
                  <button onClick={() => setWarnings([])}
                    className="text-[9px] text-yellow-500 hover:text-yellow-300 mt-1">닫기</button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Export sub-components
export { ProductionBatchList } from './ProductionBatchList';
export { ProductionProgress } from './ProductionProgress';
export { PlaytestPanel } from './PlaytestPanel';
export { LevelReviewPanel } from './LevelReviewPanel';
export { ProductionExport } from './ProductionExport';

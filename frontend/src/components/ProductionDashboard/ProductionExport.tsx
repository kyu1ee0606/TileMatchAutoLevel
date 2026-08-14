/**
 * Production Export Component
 * 프로덕션 레벨 내보내기 (JSON, 로컬레벨, GBoost)
 */

import { useState, useEffect } from 'react';
import { ProductionStats, ProductionExportConfig, ProductionLevel } from '../../types/production';
import { TileData, LevelJSON } from '../../types';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { exportProductionLevels, getProductionLevelsByBatch, renameProductionBatch, saveProductionLevel } from '../../storage/productionStorage';
import { saveLevelSetToStorage, saveLocalLevelToStorage } from '../../storage/levelStorage';
import { checkGBoostHealth, listFromGBoost, loadFromGBoost, saveToGBoost } from '../../api/gboost';
import { simulateLevelSkillSweep } from '../../api/rlSim';

// ─────────────────────────────────────────────────────────────────────
// [배포 게이트] 게임에 나가면 안 되는 레벨 판정. **순수함수** — 네트워크 try 밖에서 평가해
// 예외로 게이트 전체가 무력화(fail-OPEN)되는 일이 없게 한다.
// 모든 배포 경로(JSON 내보내기 / GBoost 업로드 / 백업업로드 / 로컬저장)가 공유해야 한다.
// 백엔드 규칙 미러: BOMB 3~5, timea 정수산술, 기믹 언락 첫 스테이지 표.
// ─────────────────────────────────────────────────────────────────────
const DEPLOY_BOMB_MIN = 3;
const DEPLOY_BOMB_MAX = 5;
const DEPLOY_TIMEA_BASE_MILLI = 900;
const DEPLOY_TIMEA_TIGHTEST_MILLI = 600;   // 티어3
const DEPLOY_TIMEA_MIN_SEC = 60;
const DEPLOY_TIMEA_MAX_SEC = 600;
const DEPLOY_TUTORIAL_GIMMICKS: Record<number, string> = {
  11: 'craft', 21: 'stack', 31: 'ice', 51: 'link', 81: 'chain', 111: 'key',
  151: 'grass', 191: 'unknown', 241: 'curtain', 291: 'bomb', 391: 'frog', 441: 'teleport',
};

function deployLevelRoot(lv: unknown): Record<string, unknown> | null {
  const root = (lv as { map?: unknown })?.map ?? lv;
  return (root && typeof root === 'object') ? root as Record<string, unknown> : null;
}

function deployScanLevel(levelNumber: number, lv: unknown): string[] {
  const lj = deployLevelRoot(lv);
  if (!lj) return [];
  const reasons: string[] = [];
  const n = parseInt(String(lj.layer ?? 0), 10) || 0;
  const attrOf = (d: unknown) => Array.isArray(d) && d.length > 1 && typeof d[1] === 'string' ? d[1] as string : '';
  const typeOf = (d: unknown) => Array.isArray(d) && d.length > 0 && typeof d[0] === 'string' ? d[0] as string : '';

  let tutFound = 0;
  const tut = DEPLOY_TUTORIAL_GIMMICKS[levelNumber];
  let collectable = 0;

  for (let i = 0; i < n; i++) {
    const layer = lj[`layer_${i}`] as { col?: unknown; row?: unknown; tiles?: Record<string, unknown> } | undefined;
    if (!layer || typeof layer !== 'object') continue;
    const tiles = layer.tiles || {};
    const keys = Object.keys(tiles);
    const col = parseInt(String(layer.col), 10);
    const row = parseInt(String(layer.row), 10);
    // 헤더-OOB: 게임은 헤더 col/row 로 격자생성 → 밖 좌표 타일은 스폰 안 됨 → 클리어 불가
    if (keys.length > 0 && (!Number.isFinite(col) || !Number.isFinite(row) || col <= 0 || row <= 0)) {
      if (!reasons.includes('header_oob')) reasons.push('header_oob');
    }
    const chains = new Set<string>();
    for (const k of keys) {
      const d = tiles[k];
      const a = attrOf(d), t0 = typeOf(d);
      const p = k.split('_');
      const c = parseInt(p[0], 10), r = parseInt(p[1], 10);
      if (c < 0 || c >= col || r < 0 || r >= row) {
        if (!reasons.includes('header_oob')) reasons.push('header_oob');
      }
      if (a === 'chain') chains.add(k);
      if (a.startsWith('bomb')) {
        const parts = a.split('_');
        const num = parts.length === 2 && /^\d+$/.test(parts[1]) ? parseInt(parts[1], 10) : NaN;
        if (!Number.isFinite(num) || num < DEPLOY_BOMB_MIN || num > DEPLOY_BOMB_MAX) {
          if (!reasons.includes('bomb_range')) reasons.push('bomb_range');
        }
      }
      if (tut && (t0.startsWith(tut) || a.startsWith(tut))) tutFound++;
      // 수집 타일 수(탭 횟수)
      if (t0.startsWith('craft_') || t0.startsWith('stack_')) {
        const extra = Array.isArray(d) ? (d as unknown[])[2] : undefined;
        let inner = 1;
        if (Array.isArray(extra) && extra.length) inner = Number(extra[0]) || 1;
        collectable += inner;
      } else collectable += 1;
    }
    // 해제 불가 사슬(최소고정점) — craft 루트만 앵커 제외, 다른 기믹은 결국 픽 가능 = 유효 앵커
    if (chains.size) {
      const ep = new Set<string>();
      let changed = true;
      while (changed) {
        changed = false;
        for (const p of chains) {
          if (ep.has(p)) continue;
          const s = p.split('_');
          const x = parseInt(s[0], 10), y = parseInt(s[1], 10);
          for (const nx of [x - 1, x + 1]) {
            const np = `${nx}_${y}`;
            if (!(np in tiles)) continue;
            if (typeOf(tiles[np]).startsWith('craft_')) continue;
            if (attrOf(tiles[np]) === 'chain' && !ep.has(np)) continue;
            ep.add(p); changed = true; break;
          }
        }
      }
      if (chains.size > ep.size && !reasons.includes('chain_unreleasable')) reasons.push('chain_unreleasable');
    }
  }

  if (tut && tut !== 'key' && tutFound === 0) reasons.push(`tutorial_missing:${tut}`);

  const ta = parseInt(String(lj.timea ?? 0), 10) || 0;
  if (ta > 0 && collectable > 0) {
    const need = Math.max(DEPLOY_TIMEA_MIN_SEC, Math.min(DEPLOY_TIMEA_MAX_SEC,
      Math.ceil((collectable * DEPLOY_TIMEA_BASE_MILLI * DEPLOY_TIMEA_TIGHTEST_MILLI) / 1_000_000)));
    if (ta < need) reasons.push('timea_tight');
  }
  return reasons;
}

/**
 * [하드 게이트] **구조적으로 망가진** 레벨만 차단한다. 난이도 판정은 여기서 보지 않는다.
 *
 * 예전엔 `verification_passed === false` / `rl_classification === 'unclearable_suspect'` /
 * `predicted_clear_rate === 0` 을 차단 사유로 썼다. 이건 전부 **RL 봇 시뮬 판정**이지
 * "레벨이 깨지는가"가 아니다. 실측으로 뒤집혔다:
 *
 *   Lv710  RL 0.000 → A* PROVEN_SOLVABLE (노드 108개, 81수)
 *   Lv730  RL 0.000 → A* PROVEN_SOLVABLE (노드 106개, 90수)
 *   Lv790  RL 0.000 → A* PROVEN_SOLVABLE (노드 818개, 168수)
 *   Lv1268 RL 0.000 → A* PROVEN_SOLVABLE (노드 171개, 138수)
 *
 * A* 가 노드 100~800개 만에 클리어 경로를 찾는 레벨을 "배포 불가"로 막고 있었다(410개).
 * 봇이 12색/독7칸에서 근시안적으로 집어 자멸하는 것을 레벨 결함으로 오판한 것.
 *
 * → 차단은 **되돌릴 수 없는 결함**만: ÷3 위반(매칭 불가 타일 잔존) · 규칙 위반 ·
 *   헤더 밖 타일 · 격자 상한 초과 · 튜토리얼 기믹 누락 · 해제 불가 사슬 · timea 부족 ·
 *   A* 가 **불가능을 증명**한 경우.
 * 난이도 미달은 `findDifficultyWarnings` 로 분리해 경고만 띄운다(배포는 사용자 판단).
 */
export function findUndeployableLevels(levels: ProductionLevel[]): Array<{ levelNumber: number; reasons: string[] }> {
  const out: Array<{ levelNumber: number; reasons: string[] }> = [];
  for (const l of levels) {
    const reasons: string[] = [];
    const m = l.meta as typeof l.meta & {
      divisibility_violation?: unknown; rule_violations?: unknown; solver_verdict?: string;
    };
    // A* 가 '불가능'을 증명한 경우만 클리어 불가로 인정한다(봇 판정 아님).
    if (m.solver_verdict === 'PROVEN_IMPOSSIBLE') reasons.push('proven_impossible');
    if (m.divisibility_violation !== undefined) reasons.push('div3');
    if (m.rule_violations !== undefined) reasons.push('rule');
    try {
      reasons.push(...deployScanLevel(m.level_number, l.level_json));
    } catch { reasons.push('scan_error'); }   // 스캔 실패 = 배포 불가(fail-CLOSED)
    if (reasons.length) out.push({ levelNumber: m.level_number, reasons });
  }
  return out;
}

/**
 * [난이도 경고] 배포를 막지는 않지만 확인이 필요한 레벨. RL 시뮬 기반이라 확정 판정이 아니다.
 * (RL 은 특정 휴리스틱 봇의 클리어율 추정치일 뿐, 클리어 가능 여부의 증명이 아니다.)
 */
export function findDifficultyWarnings(levels: ProductionLevel[]): Array<{ levelNumber: number; reason: string }> {
  const out: Array<{ levelNumber: number; reason: string }> = [];
  for (const l of levels) {
    const m = l.meta;
    if (m.rl_classification === 'unclearable_suspect') out.push({ levelNumber: m.level_number, reason: '봇 클리어 0%' });
    else if (m.verification_passed === false) out.push({ levelNumber: m.level_number, reason: 'RL 목표 미달' });
  }
  return out;
}

// Migration helper: fix tile data format for Unity client compatibility
function migrateTileData(tileData: TileData): { changed: boolean; data: TileData } {
  if (!Array.isArray(tileData) || tileData.length < 2) {
    return { changed: false, data: tileData };
  }

  const tileType = tileData[0];
  const attribute = tileData[1] || '';
  const extra = tileData.length > 2 ? tileData[2] : undefined;

  // Skip craft/stack - they need extra field for count
  if (tileType.startsWith('craft_') || tileType.startsWith('stack_')) {
    return { changed: false, data: tileData };
  }

  let newAttribute = attribute;
  let changed = false;

  // Fix ice: "ice_1", "ice_2", "ice_3" → "ice"
  if (attribute.startsWith('ice_')) {
    newAttribute = 'ice';
    changed = true;
  }

  // Fix bomb: "bomb" + [N] → "bomb_N"
  if (attribute === 'bomb' && extra && Array.isArray(extra) && extra.length > 0) {
    const countdown = extra[0];
    if (typeof countdown === 'number') {
      newAttribute = `bomb_${countdown}`;
      changed = true;
    }
  }

  // Fix teleport: "teleport" → "teleporter" (remove extra)
  if (attribute === 'teleport') {
    newAttribute = 'teleporter';
    changed = true;
  }

  if (changed) {
    // Return without extra field (except for craft/stack)
    return { changed: true, data: [tileType, newAttribute] };
  }

  // Clear extra field if not craft/stack
  if (extra !== undefined && !tileType.startsWith('craft_') && !tileType.startsWith('stack_')) {
    return { changed: true, data: [tileType, attribute] };
  }

  return { changed: false, data: tileData };
}

// Migration helper: fix level JSON format
function migrateLevelJson(levelJson: LevelJSON): { changed: boolean; level: LevelJSON } {
  let totalChanged = false;
  // Deep copy to avoid mutating original
  const newLevel = JSON.parse(JSON.stringify(levelJson)) as LevelJSON;

  const numLayers = levelJson.layer || 8;
  for (let i = 0; i < numLayers; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;
    const layerData = newLevel[layerKey];
    if (!layerData?.tiles) continue;

    const newTiles: Record<string, TileData> = {};
    for (const [pos, tileData] of Object.entries(layerData.tiles)) {
      const { changed, data } = migrateTileData(tileData);
      newTiles[pos] = data;
      if (changed) totalChanged = true;
    }

    newLevel[layerKey] = { ...layerData, tiles: newTiles };
  }

  return { changed: totalChanged, level: newLevel };
}

type GBoostPhase = 'config' | 'checking' | 'conflict' | 'uploading' | 'complete';

interface ConflictInfo {
  targetId: string;
  levelNumber: number;
}

interface ProductionExportProps {
  batchId: string;
  batchName: string;
  stats: ProductionStats;
  onExportComplete?: (count: number) => void;
}

export function ProductionExport({
  batchId,
  batchName,
  stats,
  onExportComplete,
}: ProductionExportProps) {
  const { addNotification } = useUIStore();
  const [format, setFormat] = useState<'json' | 'json_minified' | 'json_split'>('json');
  const [includeMeta, setIncludeMeta] = useState(false);
  const [filenamePattern, setFilenamePattern] = useState('level_{number:04d}.json');
  const [isExporting, setIsExporting] = useState(false);

  // Local level export
  const [localSetName, setLocalSetName] = useState('');
  const [isSavingLocal, setIsSavingLocal] = useState(false);

  // GBoost export
  const [gboostBoardId, setGboostBoardId] = useState('levels');
  const [gboostLevelPrefix, setGboostLevelPrefix] = useState('level_');
  const [gboostStartIndex, setGboostStartIndex] = useState(1);
  // [무한 레벨] 1~1500 완주 유저용. 원본 501~1500 을 `infinity_1..1000` 으로 **복사 추가**한다.
  // 오프셋 500 이 10의 배수라 `원본 % 10 === index % 10` → 보스/스페셜/autoCollect 정렬이
  // 원본과 그대로 일치하므로 보상·자동수집 규칙을 원본 레벨번호 기준으로 적용하면 된다.
  // off=원본만 · append=원본+무한 · only=무한만(원본 제외)
  const INFINITY_KEY = 'prod_export_infinity_mode_v1';
  type InfinityMode = 'off' | 'append' | 'only';
  const [infinityMode, setInfinityMode] = useState<InfinityMode>(() => {
    try {
      const v = localStorage.getItem(INFINITY_KEY);
      return v === 'append' || v === 'only' ? v : 'off';
    } catch { return 'off'; }
  });
  const infinityEnabled = infinityMode !== 'off';
  useEffect(() => {
    try { localStorage.setItem(INFINITY_KEY, infinityMode); } catch { /* ignore */ }
  }, [infinityMode]);
  const [infinityPrefix, setInfinityPrefix] = useState('infinity_');
  const [infinitySourceStart, setInfinitySourceStart] = useState(501);
  const [infinitySourceEnd, setInfinitySourceEnd] = useState(1500);
  const [gboostHealthy, setGboostHealthy] = useState(false);

  // Range selection
  const [useRange, setUseRange] = useState(false);
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(100);

  // Overwrite options
  const [overwrite, setOverwrite] = useState(true);
  const [backupBeforeOverwrite, setBackupBeforeOverwrite] = useState(true);

  // [v15.51] 업로드 대상 ID 미리보기 — 실제 level_number 기반.
  // 기존 UI는 gboostStartIndex 기반 synthetic 번호를 표시해서 batch에 레벨 7만 있어도
  // "level_1"로 보여 사용자 혼란을 일으켰음. 이제 실제 업로드되는 ID를 정확히 보여줌.
  const [previewTargetIds, setPreviewTargetIds] = useState<string[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Reward coin bulk override (applies only to GBoost upload payload — does not modify saved level)
  // mode 'preserve': use existing level_json.rewardCoin (or backend default 10)
  // mode 'fixed':    apply the same coin value to every uploaded level
  // mode 'tiered':   apply different values for boss (level%10===0) / special (level%10===9) / normal
  type RewardCoinMode = 'preserve' | 'fixed' | 'tiered';
  // [기본값] 획득 골드 일괄 5골드 (fixed 5). 필요 시 UI에서 변경.
  const [rewardCoinMode, setRewardCoinMode] = useState<RewardCoinMode>('fixed');
  const [rewardCoinFixed, setRewardCoinFixed] = useState(5);
  const [rewardCoinBoss, setRewardCoinBoss] = useState(50);
  const [rewardCoinSpecial, setRewardCoinSpecial] = useState(30);
  const [rewardCoinNormal, setRewardCoinNormal] = useState(10);

  // autoCollectCount (암호화) bulk override (upload payload only — does not modify saved level)
  // mode 'preserve':     use existing level_json.autoCollectCount (or 0)
  // mode 'multiples10':  set the given value on levels where level_number % 10 === 0, 0 (해제) on others
  type AutoCollectMode = 'preserve' | 'multiples10';
  // [기본값] autoTileCollect 레벨(level%10===0, 보스)에 autoCollectCount=3. 필요 시 UI에서 변경.
  const [autoCollectMode, setAutoCollectMode] = useState<AutoCollectMode>('multiples10');
  const [autoCollectValue, setAutoCollectValue] = useState(3);

  // Upload state
  const [gboostPhase, setGboostPhase] = useState<GBoostPhase>('config');
  const [gboostProgress, setGboostProgress] = useState({ current: 0, total: 0 });
  const [conflictingLevels, setConflictingLevels] = useState<ConflictInfo[]>([]);
  const [backupProgress, setBackupProgress] = useState({ current: 0, total: 0 });
  const [uploadResult, setUploadResult] = useState({ success: 0, failed: 0, skipped: 0 });

  // Migration state
  const [isMigrating, setIsMigrating] = useState(false);
  const [migrationProgress, setMigrationProgress] = useState<{
    current: number;
    total: number;
    fixed: number;
    skipped: number;
  } | null>(null);

  const readyCount = stats.by_status.approved;
  const exportedCount = stats.by_status.exported;
  const totalReady = readyCount + exportedCount;

  // Calculate effective range
  const effectiveStart = useRange ? rangeStart : 1;
  const effectiveEnd = useRange ? rangeEnd : totalReady;
  const effectiveCount = Math.max(0, effectiveEnd - effectiveStart + 1);

  // Check GBoost health on mount
  useEffect(() => {
    checkGBoostHealth()
      .then(res => setGboostHealthy(res.healthy ?? false))
      .catch(() => setGboostHealthy(false));
  }, []);

  // Initialize local set name
  useEffect(() => {
    if (!localSetName && batchName) {
      setLocalSetName(`${batchName}_export`);
    }
  }, [batchName, localSetName]);

  // Reset phase when config changes
  useEffect(() => {
    if (gboostPhase !== 'config') {
      setGboostPhase('config');
      setConflictingLevels([]);
      setUploadResult({ success: 0, failed: 0, skipped: 0 });
    }
  }, [gboostBoardId, gboostLevelPrefix, gboostStartIndex, useRange, rangeStart, rangeEnd]);

  // 미리보기 ID 계산 — config 변경 시마다 실제 업로드 대상 산출
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setPreviewLoading(true);
      try {
        const exportable = await getExportableLevels();
        if (cancelled) return;
        setPreviewTargetIds(buildUploadTargets(exportable).map(t => t.targetId));
      } catch {
        if (!cancelled) setPreviewTargetIds([]);
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId, gboostLevelPrefix, useRange, rangeStart, rangeEnd, totalReady,
      infinityMode, infinityPrefix, infinitySourceStart, infinitySourceEnd]);

  /**
   * [배포 표시] GBoost 업로드에 성공하면 배치 이름 끝에 마커를 남긴다.
   *
   * 왜: 어떤 배치가 실제 게임에 올라간 건지 이름만 봐선 알 수 없었다(실측: GBoost 보드가
   * 여러 배치 혼합 상태였고, 올라간 배치를 찾으려고 randSeed 지문 대조를 해야 했다).
   * 재업로드해도 마커가 누적되지 않도록 **기존 마커를 지우고 새로 붙인다**(멱등).
   */
  const DEPLOY_MARK = /\s*\[배포[^\]]*\]\s*$/;
  const stampDeployedName = async (uploaded: number, mode: InfinityMode) => {
    try {
      const base = (batchName || '').replace(DEPLOY_MARK, '').trimEnd();
      const now = new Date();
      const ts = `${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} `
        + `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
      const kind = mode === 'only' ? '무한만' : mode === 'append' ? '원본+무한' : '원본';
      const next = `${base} [배포 ${ts} · ${gboostBoardId} · ${kind} ${uploaded}]`;
      await renameProductionBatch(batchId, next);
      addNotification('info', `배치 이름에 배포 표시 추가: ${next}`);
    } catch (e) {
      // 이름 표시는 부가 기능 — 실패해도 업로드 결과에 영향 주지 않는다.
      console.warn('[export] 배포 마커 갱신 실패:', e);
    }
  };

  /**
   * [업로드 대상] 원본 + (옵션) 무한 사본.
   * 반환 항목의 `targetId` 가 GBoost 업로드 키이고, `sourceLevel` 은 보상/자동수집 규칙에
   * 쓰는 원본 레벨번호다(무한 사본도 원본 기준을 그대로 쓴다 — 위 주석의 정렬 근거 참조).
   */
  /**
   * 업로드 대상 목록.
   *
   * `slotNumber` = **게임에서 실제로 몇 번째 레벨인가**. 원본은 레벨 번호 그대로,
   * 무한 사본은 `infinity_N` 의 N(=1부터) 이다.
   * autoCollect 처럼 '10의 배수마다' 같은 위치 기반 규칙은 원본 번호가 아니라 이 값으로 판정해야 한다.
   * 지금은 sourceStart=501 이라 500 오프셋이 10의 배수여서 둘이 우연히 일치하지만,
   * 시작점을 505 등으로 바꾸면 어긋난다(Lv510 → infinity_6 인데 원본 기준으론 10배수로 판정).
   */
  const buildUploadTargets = (levels: ProductionLevel[]): Array<{
    targetId: string; level: ProductionLevel; sourceLevel: number; slotNumber: number; isInfinity: boolean;
  }> => {
    const out = infinityMode === 'only' ? [] : levels.map(l => ({
      targetId: `${gboostLevelPrefix}${l.meta.level_number}`,
      level: l, sourceLevel: l.meta.level_number, slotNumber: l.meta.level_number, isInfinity: false,
    }));
    if (infinityEnabled) {
      const src = levels
        .filter(l => l.meta.level_number >= infinitySourceStart && l.meta.level_number <= infinitySourceEnd)
        .sort((a, b) => a.meta.level_number - b.meta.level_number);
      src.forEach((l, i) => out.push({
        targetId: `${infinityPrefix}${i + 1}`,
        level: l, sourceLevel: l.meta.level_number, slotNumber: i + 1, isInfinity: true,
      }));
    }
    return out;
  };


  // JSON 파일 내보내기
  const handleExportJson = async () => {
    if (readyCount === 0) {
      addNotification('warning', '내보낼 승인된 레벨이 없습니다');
      return;
    }

    // [export 하드게이트] 클리어 불가/미검증/규칙위반 레벨이 게임 배포에 섞이는 걸 원천 차단.
    // ⚠️ 조회(네트워크/IDB)와 판정을 분리한다. 예전엔 전체가 하나의 try/catch 안에 있어
    //    새 검사에서 예외가 나면 ÷3·헤더OOB 게이트까지 통째로 무력화되는 fail-OPEN 이었다.
    let _exportSet: ProductionLevel[] | null = null;
    try {
      const _all = await getProductionLevelsByBatch(batchId);
      _exportSet = _all.filter(l => l.meta.status === 'approved' || l.meta.status === 'exported');
      // [무한 모드 정합] `exportProductionLevels` 는 only=true 일 때 원본을 버리고
      // sourceStart~sourceEnd 사본만 내보낸다. 게이트도 **같은 세트**를 봐야 한다 —
      // 안 그러면 내보내지도 않는 구간(예: Lv1~500)의 결함으로 차단당한다.
      // append 모드는 원본 전체 + 사본이라 필터가 필요 없다(사본 소스가 원본의 부분집합).
      if (infinityEnabled && infinityMode === 'only') {
        _exportSet = _exportSet.filter(
          l => l.meta.level_number >= infinitySourceStart && l.meta.level_number <= infinitySourceEnd);
      }
    } catch { /* 조회 실패 시에만 진행(서버 게이트가 최종 방어) */ }
    if (_exportSet) {
      const _bad = findUndeployableLevels(_exportSet);   // 순수함수 — try 밖에서 평가(fail-CLOSED)
      if (_bad.length > 0) {
        const nums = _bad.slice(0, 12).map(b => `${b.levelNumber}(${b.reasons[0]})`).join(', ');
        addNotification('error', `❌ 내보내기 차단 — 배포 불가 ${_bad.length}개 포함 (예: ${nums}${_bad.length > 12 ? '…' : ''}). 재검증/재생성으로 통과시킨 뒤 내보내세요.`);
        return;
      }
    }

    setIsExporting(true);

    try {
      const config: ProductionExportConfig = {
        format,
        include_meta: includeMeta,
        filename_pattern: filenamePattern,
        output_dir: '',
        // [무한 레벨] 켜져 있으면 원본 뒤에 infinity_* 사본을 덧붙인다(원본은 불변).
        infinity: infinityEnabled
          ? { enabled: true, only: infinityMode === 'only', prefix: infinityPrefix,
              sourceStart: infinitySourceStart, sourceEnd: infinitySourceEnd }
          : undefined,
      };

      const result = await exportProductionLevels(batchId, config);

      if ('files' in result) {
        addNotification('success', `${result.files.length}개 파일 생성됨`);

        if (result.files.length <= 10) {
          for (const file of result.files) {
            const url = URL.createObjectURL(file.data);
            const a = document.createElement('a');
            a.href = url;
            a.download = file.name;
            a.click();
            URL.revokeObjectURL(url);
          }
        } else {
          addNotification('info', 'ZIP 다운로드는 추후 지원 예정입니다. JSON 포맷을 권장합니다.');
        }
      } else {
        const url = URL.createObjectURL(result);
        const a = document.createElement('a');
        a.href = url;
        a.download = `production_levels_${batchId}.json`;
        a.click();
        URL.revokeObjectURL(url);

        addNotification('success', `${totalReady}개 레벨 내보내기 완료`);
      }

      onExportComplete?.(totalReady);
    } catch (err) {
      addNotification('error', `내보내기 실패: ${(err as Error).message}`);
    } finally {
      setIsExporting(false);
    }
  };

  // 로컬 레벨로 저장
  const handleSaveToLocal = async () => {
    if (totalReady === 0) {
      addNotification('warning', '저장할 레벨이 없습니다');
      return;
    }

    if (!localSetName.trim()) {
      addNotification('warning', '폴더 이름을 입력해주세요');
      return;
    }

    setIsSavingLocal(true);

    try {
      const levels = await getProductionLevelsByBatch(batchId);
      const exportableLevels = levels.filter(
        l => l.meta.status === 'approved' || l.meta.status === 'exported'
      );

      if (exportableLevels.length === 0) {
        addNotification('warning', '내보낼 수 있는 레벨이 없습니다');
        return;
      }

      exportableLevels.sort((a, b) => a.meta.level_number - b.meta.level_number);

      const result = saveLevelSetToStorage({
        name: localSetName.trim(),
        levels: exportableLevels.map(l => l.level_json),
        difficulty_profile: exportableLevels.map(l => l.meta.target_difficulty),
        actual_difficulties: exportableLevels.map(l => l.meta.actual_difficulty),
        grades: exportableLevels.map(l => l.meta.grade),
        generation_config: {
          source: 'production',
          batch_id: batchId,
          batch_name: batchName,
        },
      });

      if (result.success) {
        addNotification('success', `${exportableLevels.length}개 레벨을 '${localSetName}'로 저장했습니다`);
        onExportComplete?.(exportableLevels.length);
      } else {
        addNotification('error', result.message);
      }
    } catch (err) {
      addNotification('error', `로컬 저장 실패: ${(err as Error).message}`);
    } finally {
      setIsSavingLocal(false);
    }
  };

  // Get exportable levels with range filter
  const getExportableLevels = async (): Promise<ProductionLevel[]> => {
    const levels = await getProductionLevelsByBatch(batchId);
    // 레벨 데이터가 있는 모든 레벨 (generated, approved, exported 등)
    let exportableLevels = levels.filter(l => l.level_json);
    exportableLevels.sort((a, b) => a.meta.level_number - b.meta.level_number);

    if (useRange) {
      // 레벨 번호 기준으로 필터링
      exportableLevels = exportableLevels.filter(
        l => l.meta.level_number >= effectiveStart && l.meta.level_number <= effectiveEnd
      );
    }

    return exportableLevels;
  };

  // Check for conflicts
  const handleCheckConflicts = async () => {
    if (effectiveCount === 0) {
      addNotification('warning', '업로드할 레벨이 없습니다');
      return;
    }

    if (!gboostHealthy) {
      addNotification('error', 'GBoost 연결이 설정되지 않았습니다');
      return;
    }

    setGboostPhase('checking');
    setConflictingLevels([]);

    try {
      // [v15.51] Conflict-check 대상 ID는 실제 업로드와 동일한 규칙 — 즉 각 레벨의
      // 실제 level_number 기반으로 산출. 기존: effectiveStart부터 1씩 증가하는 synthetic
      // 번호로 만들었기 때문에 batch에 레벨 7만 있어도 ID가 level_1로 표시되어
      // 실제 업로드 대상(level_7)과 불일치 → 사용자 혼란.
      const exportableForCheck = await getExportableLevels();
      // [무한 모드 정합] 충돌 검사는 **실제 업로드 대상과 같은 소스**(buildUploadTargets)를 써야 한다.
      // 예전엔 항상 `level_{번호}` 로 대상을 만들고 서버도 `level_` 프리픽스로만 조회했다
      // → '무한만' 모드에서 실제 업로드는 `infinity_*` 인데 검사는 `level_*` 를 보게 되어
      //   기존 level_1..1500 전부를 충돌로 오판 → **불필요한 백업 1500건**이 돌았다.
      //   (게다가 업로드 루프의 skip 판정은 infinity_N 을 level_N 셋과 비교해 항상 빗나감)
      const uploadTargetsForCheck = buildUploadTargets(exportableForCheck);
      const targetIds: ConflictInfo[] = uploadTargetsForCheck.map(t => ({
        targetId: t.targetId,
        levelNumber: t.sourceLevel,
      }));

      // 조회 프리픽스도 모드에 맞춘다(원본만 / 무한만 / 둘 다).
      const prefixes = Array.from(new Set(
        uploadTargetsForCheck.map(t => (t.isInfinity ? infinityPrefix : gboostLevelPrefix))));
      const fetchLimit = Math.max(targetIds.length + 100, 2000);
      const existingIds = new Set<string>();
      for (const px of prefixes) {
        const res = await listFromGBoost(gboostBoardId, px, fetchLimit);
        res.levels.forEach(l => existingIds.add(l.id));
      }

      // Find conflicts
      const conflicts = targetIds.filter(t => existingIds.has(t.targetId));
      setConflictingLevels(conflicts);

      if (conflicts.length > 0) {
        setGboostPhase('conflict');
      } else {
        // No conflicts, proceed directly
        await handleUpload();
      }
    } catch (err) {
      console.error('Failed to check conflicts:', err);
      // If we can't check, proceed with upload
      await handleUpload();
    }
  };

  /**
   * 업로드 대상이 배포 게이트를 통과하는지 **미리** 본다.
   *
   * 예전엔 게이트가 handleUpload 안에만 있어서, 1500건 백업을 다 돌린 **뒤에야** 차단됐다
   * (실측: level_1~1500 백업 GET 1500건 완료 → 게이트 거부 → config 화면 복귀).
   * 백업은 수 분이 걸리고 되돌릴 수도 없으니, 시작 전에 같은 판정을 돌려 막는다.
   */
  const preflightBlocked = async (): Promise<boolean> => {
    try {
      const lv = await getExportableLevels();
      const targets = buildUploadTargets(lv);
      const gate = [...new Map(targets.map(t => [t.level.meta.level_number, t.level])).values()];
      const bad = findUndeployableLevels(gate);
      if (bad.length > 0) {
        const nums = bad.slice(0, 12).map(b => `${b.levelNumber}(${b.reasons[0]})`).join(', ');
        addNotification('error',
          `❌ 업로드 차단 — 배포 불가 ${bad.length}개 포함 (예: ${nums}${bad.length > 12 ? '…' : ''}). 백업 전에 중단했습니다. 재검증/재생성 후 업로드하세요.`);
        setGboostPhase('config');
        return true;
      }
      // 난이도 경고는 **막지 않는다** — RL 은 봇 시뮬 추정치라 확정 판정이 아니다.
      // 다만 규모가 크면 모르고 올리는 일이 없도록 확인만 받는다.
      const warn = findDifficultyWarnings(gate);
      if (warn.length > 0) {
        const nums = warn.slice(0, 10).map(w => `${w.levelNumber}(${w.reason})`).join(', ');
        if (!window.confirm(
          `⚠️ 난이도 경고 ${warn.length}개 (전체 ${gate.length}개 중)\n\n`
          + `${nums}${warn.length > 10 ? ' …' : ''}\n\n`
          + `RL 봇 기준 목표에 못 미치는 레벨입니다. 클리어 불가가 확정된 것은 아닙니다\n`
          + `(A* 완전탐색으로 클리어 경로가 확인된 사례 다수).\n\n`
          + `그대로 업로드할까요?`)) {
          setGboostPhase('config');
          return true;
        }
      }
    } catch (e) {
      console.warn('[export] preflight 실패(계속 진행):', e);
    }
    return false;
  };

  // Backup and upload
  const handleBackupAndUpload = async () => {
    if (await preflightBlocked()) return;
    if (backupBeforeOverwrite && conflictingLevels.length > 0) {
      setBackupProgress({ current: 0, total: conflictingLevels.length });

      for (let i = 0; i < conflictingLevels.length; i++) {
        const conflict = conflictingLevels[i];
        try {
          const serverLevel = await loadFromGBoost(gboostBoardId, conflict.targetId);
          const backupId = `backup_${conflict.targetId}_${Date.now()}`;
          saveLocalLevelToStorage({
            id: backupId,
            name: `[백업] ${conflict.targetId}`,
            description: `GBoost 서버에서 백업됨 (덮어쓰기 전)`,
            tags: ['backup', 'gboost', conflict.targetId],
            source: 'gboost_backup',
            level_data: serverLevel.level_json,
            validation_status: 'unknown',
          });
        } catch (err) {
          console.warn(`Failed to backup ${conflict.targetId}:`, err);
        }
        setBackupProgress({ current: i + 1, total: conflictingLevels.length });
      }
      // [필수] 진행률을 0으로 되돌린다. 예전엔 1500/1500 이 그대로 남아
      //   ① "백업 진행 중… 1500/1500" 이 계속 떠 있고
      //   ② `disabled={backupProgress.total > 0}` 때문에 덮어쓰기 버튼이 **영구 비활성화**됐다.
      // 업로드가 게이트에 막혀 config 로 돌아오면 사용자는 아무것도 누를 수 없는 상태가 된다.
      setBackupProgress({ current: 0, total: 0 });
    }

    await handleUpload();
  };

  // Upload to GBoost (saveToGBoost 직접 사용)
  const handleUpload = async () => {
    setGboostPhase('uploading');
    setGboostProgress({ current: 0, total: 0 });
    setUploadResult({ success: 0, failed: 0, skipped: 0 });

    try {
      const exportableLevels = await getExportableLevels();

      if (exportableLevels.length === 0) {
        addNotification('warning', '업로드할 수 있는 레벨이 없습니다');
        setGboostPhase('config');
        return;
      }

      // [배포 하드게이트] 여기가 **실제 게임 배포 경로**다. 기존엔 JSON 내보내기에만 게이트가 있어
      // 업로드로는 클리어 불가/규칙 위반 레벨이 그대로 나갔다. 순수함수라 fail-CLOSED.
      // [무한 모드 정합] 게이트 대상은 **실제로 올라가는 레벨**이어야 한다. 예전엔
      // exportableLevels(배치 전체)를 그대로 검사해서, '무한만' 모드처럼 일부 구간만 올릴 때
      // 업로드 대상이 아닌 레벨의 결함까지 차단 사유로 잡혔다(예: 501~1500만 올리는데
      // Lv11~500 의 미검증이 카운트됨). buildUploadTargets 로 좁힌 뒤 레벨 번호로 중복 제거한다
      // (append 모드는 같은 레벨이 level_N / infinity_N 두 번 나오므로).
      const _uploadTargets = buildUploadTargets(exportableLevels);
      const _gateLevels = [...new Map(
        _uploadTargets.map(t => [t.level.meta.level_number, t.level])).values()];
      // (프리플라이트에서 이미 걸렀지만, 다른 진입 경로를 위해 이중 방어로 남긴다)
      const _undeployable = findUndeployableLevels(_gateLevels);
      if (_undeployable.length > 0) {
        const nums = _undeployable.slice(0, 12).map(b => `${b.levelNumber}(${b.reasons[0]})`).join(', ');
        addNotification('error', `❌ 업로드 차단 — 배포 불가 ${_undeployable.length}개 포함 (예: ${nums}${_undeployable.length > 12 ? '…' : ''}). 재검증/재생성 후 업로드하세요.`);
        setGboostPhase('config');
        return;
      }

      // [v16] 내보내기 전 RL 일괄측정 — predicted 없는 레벨은 difficulty가 -1로 나가므로,
      // 배포 직전 미검증 레벨을 RL 측정해 predicted를 채운다(수동 클릭 불필요). 병렬 청크 처리.
      const needRL = exportableLevels.filter(l => l.meta.predicted_clear_rate === undefined);
      if (needRL.length > 0) {
        addNotification('info', `RL 일괄측정: 미검증 ${needRL.length}개 측정 시작…`);
        setGboostProgress({ current: 0, total: needRL.length });
        const RL_CONC = 5;
        let measured = 0;
        for (let s = 0; s < needRL.length; s += RL_CONC) {
          const chunk = needRL.slice(s, s + RL_CONC);
          await Promise.all(chunk.map(async (l) => {
            try {
              const rl = await simulateLevelSkillSweep({
                level_json: l.level_json,
                target_difficulty: l.meta.target_difficulty,
              });
              // in-memory 메타 갱신 → 아래 배포 루프가 predicted를 payload에 주입
              l.meta.predicted_clear_rate = rl.predicted_clear_rate;
              l.meta.target_clear_rate = rl.target_clear_rate ?? undefined;
              l.meta.clear_rate_gap = rl.clear_rate_gap ?? undefined;
              l.meta.rl_classification = rl.classification;
              l.meta.verification_method = 'rl';
              await saveProductionLevel(batchId, l); // 영속화(다음 내보내기시 재측정 방지)
            } catch {
              /* 측정 실패 레벨은 difficulty -1로 나감 (스킵) */
            }
          }));
          measured += chunk.length;
          setGboostProgress({ current: measured, total: needRL.length });
        }
        addNotification('success', `RL 일괄측정 완료: ${needRL.length}개`);
      }

      setGboostProgress({ current: 0, total: exportableLevels.length });

      let successCount = 0;
      let failCount = 0;
      let skippedCount = 0;

      // 충돌 레벨 ID 집합 (overwrite=false일 때 건너뛰기 위함)
      const conflictIds = new Set(conflictingLevels.map(c => c.targetId));

      // Decide rewardCoin per level based on UI mode (does not mutate saved level data).
      const resolveRewardCoin = (levelNumber: number, savedLevel: LevelJSON): number | null => {
        if (rewardCoinMode === 'preserve') return null; // do not override
        if (rewardCoinMode === 'fixed') return Math.max(0, Math.floor(rewardCoinFixed));
        // tiered
        const isBoss = levelNumber > 0 && levelNumber % 10 === 0;
        const isSpecial = levelNumber % 10 === 9;
        if (isBoss) return Math.max(0, Math.floor(rewardCoinBoss));
        if (isSpecial) return Math.max(0, Math.floor(rewardCoinSpecial));
        // Avoid unused-var TS warning: explicitly read savedLevel for parity with future per-level rules
        void savedLevel;
        return Math.max(0, Math.floor(rewardCoinNormal));
      };

      // Decide autoCollectCount (암호화) per level based on UI mode (upload payload only).
      // [중요] 판정 기준은 **게임 내 위치(slotNumber)** 다. 무한 사본은 원본 레벨 번호가 아니라
      // infinity_N 의 N 을 쓴다 — 플레이어가 보는 건 무한 모드의 N번째 레벨이지 원본 번호가 아니다.
      // 예전엔 sourceLevel 로 판정했는데, sourceStart=501(오프셋 500=10배수)일 때만 우연히 맞았다.
      // 시작점을 505 로 바꾸면 Lv510(10배수)이 infinity_6 에 들어가 무한 모드의 6번째가 autoCollect 를
      // 갖고, 정작 10번째(infinity_10=Lv514)는 못 갖는 어긋남이 생긴다.
      const resolveAutoCollect = (slotNumber: number): number | null => {
        if (autoCollectMode === 'preserve') return null; // do not override
        // multiples10: 10·20·30… 번째 레벨은 설정값, 나머지는 0 (해제)
        const isMultipleOf10 = slotNumber > 0 && slotNumber % 10 === 0;
        return isMultipleOf10 ? Math.max(0, Math.floor(autoCollectValue)) : 0;
      };

      // 원본 + (옵션) 무한 사본. 무한 사본은 targetId 만 다르고 페이로드/규칙은 원본과 동일.
      const uploadTargets = buildUploadTargets(exportableLevels);
      for (let i = 0; i < uploadTargets.length; i++) {
        const { targetId, level, slotNumber } = uploadTargets[i];

        // overwrite=false이고 충돌이 있으면 건너뛰기
        if (!overwrite && conflictIds.has(targetId)) {
          skippedCount++;
          setGboostProgress({ current: i + 1, total: uploadTargets.length });
          continue;
        }

        // 업로드 페이로드에만 rewardCoin / autoCollectCount 주입 (저장본은 그대로 둠)
        // rewardCoin 의 보스/특수 등급도 '게임 내 위치' 기반이라 같은 기준을 쓴다
        // (원본 번호로 매기면 무한 모드에서 보스 보상이 엉뚱한 자리에 붙는다).
        const overrideCoin = resolveRewardCoin(slotNumber, level.level_json);
        const overrideAutoCollect = resolveAutoCollect(slotNumber);
        let uploadJson: LevelJSON = level.level_json;
        if (overrideCoin !== null || overrideAutoCollect !== null) {
          uploadJson = { ...level.level_json };
          if (overrideCoin !== null) uploadJson.rewardCoin = overrideCoin;
          if (overrideAutoCollect !== null) uploadJson.autoCollectCount = overrideAutoCollect;
        }
        // [v16] 인게임 표시용 예측 클리어율 주입 → 컨버터가 difficulty=round(predicted×100)로 변환.
        // meta에만 있는 predicted를 배포 payload(level_json)에 실어 컨버터까지 전달.
        if (level.meta.predicted_clear_rate !== undefined) {
          uploadJson = { ...uploadJson, predicted_clear_rate: level.meta.predicted_clear_rate } as unknown as LevelJSON;
        }

        try {
          // saveToGBoost는 level_json을 직접 받아서 TownPop 변환 및 썸네일 생성
          await saveToGBoost(gboostBoardId, targetId, uploadJson);
          successCount++;
        } catch (err) {
          console.error(`Failed to upload ${targetId}:`, err);
          failCount++;
        }

        setGboostProgress({ current: i + 1, total: uploadTargets.length });
      }

      setUploadResult({ success: successCount, failed: failCount, skipped: skippedCount });
      setGboostPhase('complete');
      // 실제로 올라간 게 있을 때만 표시(전부 스킵/실패면 배포로 치지 않는다)
      if (successCount > 0) await stampDeployedName(successCount, infinityMode);

      if (failCount === 0 && skippedCount === 0) {
        addNotification('success', `${successCount}개 레벨을 GBoost에 업로드했습니다`);
      } else if (failCount === 0) {
        addNotification('success', `${successCount}개 업로드, ${skippedCount}개 건너뜀`);
      } else {
        addNotification('warning', `${successCount}개 성공, ${failCount}개 실패, ${skippedCount}개 건너뜀`);
      }

      onExportComplete?.(successCount);
    } catch (err) {
      addNotification('error', `GBoost 업로드 실패: ${(err as Error).message}`);
      setGboostPhase('config');
    }
  };

  // Reset to config
  const handleResetGBoost = () => {
    setGboostPhase('config');
    setConflictingLevels([]);
    setGboostProgress({ current: 0, total: 0 });
    setBackupProgress({ current: 0, total: 0 });
    setUploadResult({ success: 0, failed: 0, skipped: 0 });
  };

  // Migrate gimmick formats in local production levels
  const handleMigration = async () => {
    if (isMigrating) return;

    setIsMigrating(true);
    setMigrationProgress({ current: 0, total: 0, fixed: 0, skipped: 0 });

    try {
      // Get all levels in this batch
      const levels = await getProductionLevelsByBatch(batchId);

      if (levels.length === 0) {
        addNotification('warning', '마이그레이션할 레벨이 없습니다');
        setIsMigrating(false);
        setMigrationProgress(null);
        return;
      }

      setMigrationProgress({ current: 0, total: levels.length, fixed: 0, skipped: 0 });

      let fixed = 0;
      let skipped = 0;

      for (let i = 0; i < levels.length; i++) {
        const level = levels[i];

        try {
          // Migrate the level JSON
          const { changed, level: migratedLevel } = migrateLevelJson(level.level_json);

          if (changed) {
            // Save the migrated level back to IndexedDB
            const updatedLevel: ProductionLevel = {
              ...level,
              level_json: migratedLevel,
            };
            await saveProductionLevel(batchId, updatedLevel);
            fixed++;
          } else {
            skipped++;
          }
        } catch (err) {
          console.error(`Failed to migrate level ${level.meta.level_number}:`, err);
          skipped++;
        }

        setMigrationProgress({
          current: i + 1,
          total: levels.length,
          fixed,
          skipped,
        });
      }

      addNotification('success', `마이그레이션 완료: ${fixed}개 수정, ${skipped}개 스킵`);
    } catch (error) {
      console.error('Migration failed:', error);
      addNotification('error', '마이그레이션 중 오류 발생');
    } finally {
      setIsMigrating(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Export Summary */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">내보내기 요약</h3>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-green-400">{readyCount}</div>
            <div className="text-xs text-gray-400">승인됨 (대기)</div>
          </div>
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-indigo-400">{exportedCount}</div>
            <div className="text-xs text-gray-400">내보내기 완료</div>
          </div>
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-white">{totalReady}</div>
            <div className="text-xs text-gray-400">총 출시 가능</div>
          </div>
        </div>
      </div>

      {/* Gimmick Format Migration */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-3">
        <h3 className="text-sm font-medium text-white">기믹 포맷 마이그레이션</h3>
        <p className="text-xs text-gray-400">
          Unity 클라이언트 호환을 위해 기믹 포맷을 수정합니다.
          <br />
          • ice_1/2/3 → ice
          <br />
          • bomb + [N] → bomb_N
          <br />
          • teleport → teleporter
        </p>

        {migrationProgress && (
          <div className="space-y-2">
            <div className="flex justify-between text-xs text-gray-400">
              <span>진행 중...</span>
              <span>{migrationProgress.current} / {migrationProgress.total}</span>
            </div>
            <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-500 transition-all"
                style={{ width: `${(migrationProgress.current / migrationProgress.total) * 100}%` }}
              />
            </div>
            <div className="flex gap-4 text-xs">
              <span className="text-green-400">수정됨: {migrationProgress.fixed}</span>
              <span className="text-gray-400">스킵: {migrationProgress.skipped}</span>
            </div>
          </div>
        )}

        <Button
          onClick={handleMigration}
          disabled={isMigrating || stats.total_levels === 0}
          variant="secondary"
          className="w-full"
        >
          {isMigrating ? '마이그레이션 중...' : `기믹 포맷 마이그레이션 (${stats.total_levels}개 레벨)`}
        </Button>
      </div>

      {/* Local Level Export */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-3">
        <h3 className="text-sm font-medium text-white">로컬 레벨로 저장</h3>
        <p className="text-xs text-gray-400">
          레벨을 로컬 저장소에 새 폴더로 저장합니다. 이후 GBoost 패널에서 업로드할 수 있습니다.
        </p>

        <div>
          <label className="block text-xs text-gray-400 mb-1">폴더 이름</label>
          <input
            type="text"
            value={localSetName}
            onChange={(e) => setLocalSetName(e.target.value)}
            placeholder="예: production_v1"
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
          />
        </div>

        <Button
          onClick={handleSaveToLocal}
          disabled={isSavingLocal || totalReady === 0}
          variant="secondary"
          className="w-full"
        >
          {isSavingLocal ? '저장 중...' : `로컬에 저장 (${totalReady}개)`}
        </Button>
      </div>

      {/* GBoost Export */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-white">GBoost로 직접 업로드</h3>
          <span className={`text-xs px-2 py-1 rounded ${gboostHealthy ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
            {gboostHealthy ? '연결됨' : '연결 안됨'}
          </span>
        </div>

        {gboostHealthy ? (
          <>
            {/* Config Phase */}
            {gboostPhase === 'config' && (
              <>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Board ID</label>
                    <input
                      type="text"
                      value={gboostBoardId}
                      onChange={(e) => setGboostBoardId(e.target.value)}
                      placeholder="stage"
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">레벨 ID 프리픽스</label>
                    <input
                      type="text"
                      value={gboostLevelPrefix}
                      onChange={(e) => setGboostLevelPrefix(e.target.value)}
                      placeholder="level_"
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">시작 번호</label>
                    <input
                      type="number"
                      value={gboostStartIndex}
                      onChange={(e) => setGboostStartIndex(Math.max(1, parseInt(e.target.value) || 1))}
                      min={1}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                    />
                  </div>
                </div>

                {/* [무한 레벨] 1~1500 완주 유저용 사본 — 같은 보드에 infinity_* 로 추가 업로드 */}
                <div className="space-y-2 p-2 bg-purple-900/15 rounded border border-purple-800/40">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm text-white font-medium">♾️ 무한 레벨</span>
                    {([
                      ['off', '원본만', '무한 사본 없음(기존 동작)'],
                      ['append', '원본 + 무한', '원본 뒤에 사본을 덧붙임'],
                      ['only', '무한만', '원본 제외, 사본만 내보냄'],
                    ] as Array<[InfinityMode, string, string]>).map(([m, label, tip]) => (
                      <button key={m} onClick={() => setInfinityMode(m)} title={tip}
                        className={`px-2 py-1 rounded text-xs border transition-colors ${
                          infinityMode === m
                            ? 'bg-purple-600 border-purple-500 text-white'
                            : 'bg-gray-700 border-gray-600 text-gray-300 hover:border-gray-500'
                        }`}>
                        {label}
                      </button>
                    ))}
                    {infinityEnabled && (
                      <span className="text-xs text-gray-400">
                        원본 {infinitySourceStart}~{infinitySourceEnd} → {infinityPrefix}1~{infinityPrefix}
                        {Math.max(0, infinitySourceEnd - infinitySourceStart + 1)}
                      </span>
                    )}
                  </div>
                  {infinityEnabled && (
                    <>
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <label className="block text-[11px] text-gray-400 mb-1">ID 프리픽스</label>
                          <input type="text" value={infinityPrefix}
                            onChange={(e) => setInfinityPrefix(e.target.value)}
                            className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white" />
                        </div>
                        <div>
                          <label className="block text-[11px] text-gray-400 mb-1">원본 시작</label>
                          <input type="number" value={infinitySourceStart} min={1}
                            onChange={(e) => setInfinitySourceStart(Math.max(1, parseInt(e.target.value) || 1))}
                            className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white" />
                        </div>
                        <div>
                          <label className="block text-[11px] text-gray-400 mb-1">원본 끝</label>
                          <input type="number" value={infinitySourceEnd} min={1}
                            onChange={(e) => setInfinitySourceEnd(Math.max(1, parseInt(e.target.value) || 1))}
                            className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white" />
                        </div>
                      </div>
                      <p className="text-[11px] text-purple-300">
                        {infinityMode === 'only'
                          ? '⚠️ 무한 사본만 업로드/저장합니다 — 원본(level_*)은 포함되지 않습니다.'
                          : '원본은 그대로 두고 같은 보드에 사본을 덧붙입니다.'}
                        {(infinitySourceStart - 1) % 10 === 0
                          ? ' 오프셋이 10의 배수라 보스(10배수)·스페셜(끝자리9)·autoCollect 위치가 원본과 그대로 정렬됩니다.'
                          : ' ⚠️ 시작−1 이 10의 배수가 아니라 보스/자동수집 위치가 원본과 어긋납니다(권장: 501).'}
                      </p>
                    </>
                  )}
                </div>

                {/* Range Selection */}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={useRange}
                      onChange={(e) => setUseRange(e.target.checked)}
                      className="rounded border-gray-600"
                    />
                    <span className="text-sm text-gray-300">범위 지정</span>
                  </label>

                  {useRange && (
                    <div className="flex items-center gap-2 ml-6">
                      <input
                        type="number"
                        value={rangeStart}
                        onChange={(e) => setRangeStart(Math.max(1, parseInt(e.target.value) || 1))}
                        min={1}
                        className="w-20 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                      />
                      <span className="text-gray-400">~</span>
                      <input
                        type="number"
                        value={rangeEnd}
                        onChange={(e) => setRangeEnd(Math.max(1, parseInt(e.target.value) || 1))}
                        min={1}
                        className="w-20 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                      />
                      <span className="text-xs text-gray-500">번째 레벨</span>
                    </div>
                  )}
                </div>

                {/* Overwrite Options */}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={overwrite}
                      onChange={(e) => setOverwrite(e.target.checked)}
                      className="rounded border-gray-600"
                    />
                    <span className="text-sm text-gray-300">기존 레벨 덮어쓰기</span>
                  </label>

                  {overwrite && (
                    <label className="flex items-center gap-2 cursor-pointer ml-6">
                      <input
                        type="checkbox"
                        checked={backupBeforeOverwrite}
                        onChange={(e) => setBackupBeforeOverwrite(e.target.checked)}
                        className="rounded border-yellow-600"
                      />
                      <span className="text-sm text-yellow-300">덮어쓰기 전 기존 레벨 백업</span>
                    </label>
                  )}
                </div>

                <p className="text-xs text-gray-500">
                  {previewLoading ? (
                    <span>대상 ID 계산 중…</span>
                  ) : previewTargetIds.length === 0 ? (
                    <span>업로드 가능한 레벨이 없습니다.</span>
                  ) : previewTargetIds.length === 1 ? (
                    <span>업로드 대상: <code className="text-gray-300">{previewTargetIds[0]}</code> (1개)</span>
                  ) : previewTargetIds.length <= 5 ? (
                    <span>업로드 대상: <code className="text-gray-300">{previewTargetIds.join(', ')}</code> ({previewTargetIds.length}개)</span>
                  ) : (
                    <span>
                      업로드 대상: <code className="text-gray-300">{previewTargetIds[0]}</code> ~{' '}
                      <code className="text-gray-300">{previewTargetIds[previewTargetIds.length - 1]}</code>{' '}
                      ({previewTargetIds.length}개)
                    </span>
                  )}
                </p>

                {/* Reward Coin bulk override (upload-time only, does not modify saved level) */}
                <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-medium text-white">리워드 코인 (rewardCoin) 일괄 설정</h4>
                    <span className="text-[10px] text-gray-500">저장본 유지 · 업로드 페이로드만 덮어씀</span>
                  </div>

                  <div className="flex gap-2 text-xs">
                    {[
                      { v: 'preserve', label: '레벨 저장값 유지' },
                      { v: 'fixed', label: '일괄 고정값' },
                      { v: 'tiered', label: '타입별 차등' },
                    ].map(opt => (
                      <label
                        key={opt.v}
                        className={`flex-1 px-2 py-1.5 text-center rounded border cursor-pointer ${
                          rewardCoinMode === opt.v
                            ? 'bg-blue-900/40 border-blue-500 text-blue-200'
                            : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'
                        }`}
                      >
                        <input
                          type="radio"
                          name="rewardCoinMode"
                          value={opt.v}
                          checked={rewardCoinMode === opt.v}
                          onChange={(e) => setRewardCoinMode(e.target.value as typeof rewardCoinMode)}
                          className="hidden"
                        />
                        {opt.label}
                      </label>
                    ))}
                  </div>

                  {rewardCoinMode === 'fixed' && (
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-gray-400 whitespace-nowrap">고정값</label>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={rewardCoinFixed}
                        onChange={(e) => setRewardCoinFixed(parseInt(e.target.value, 10) || 0)}
                        className="flex-1 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                      />
                      <span className="text-xs text-gray-500">코인 / 레벨</span>
                    </div>
                  )}

                  {rewardCoinMode === 'tiered' && (
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="block text-[11px] text-orange-300 mb-0.5">보스 (10·20·…)</label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={rewardCoinBoss}
                          onChange={(e) => setRewardCoinBoss(parseInt(e.target.value, 10) || 0)}
                          className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-purple-300 mb-0.5">특수 (9·19·…)</label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={rewardCoinSpecial}
                          onChange={(e) => setRewardCoinSpecial(parseInt(e.target.value, 10) || 0)}
                          className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-gray-300 mb-0.5">일반</label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={rewardCoinNormal}
                          onChange={(e) => setRewardCoinNormal(parseInt(e.target.value, 10) || 0)}
                          className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                        />
                      </div>
                    </div>
                  )}

                  {rewardCoinMode === 'preserve' && (
                    <p className="text-[11px] text-gray-500">
                      각 레벨의 level_json.rewardCoin 값을 그대로 사용 (없으면 백엔드 기본값 10).
                    </p>
                  )}
                </div>

                {/* autoCollectCount (암호화) bulk override (upload-time only, does not modify saved level) */}
                <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-medium text-white">암호화 (autoCollectCount) 일괄 설정</h4>
                    <span className="text-[10px] text-gray-500">저장본 유지 · 업로드 페이로드만 덮어씀</span>
                  </div>

                  <div className="flex gap-2 text-xs">
                    {[
                      { v: 'preserve', label: '레벨 저장값 유지' },
                      { v: 'multiples10', label: '10의 배수 레벨만 설정' },
                    ].map(opt => (
                      <label
                        key={opt.v}
                        className={`flex-1 px-2 py-1.5 text-center rounded border cursor-pointer ${
                          autoCollectMode === opt.v
                            ? 'bg-blue-900/40 border-blue-500 text-blue-200'
                            : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'
                        }`}
                      >
                        <input
                          type="radio"
                          name="autoCollectMode"
                          value={opt.v}
                          checked={autoCollectMode === opt.v}
                          onChange={(e) => setAutoCollectMode(e.target.value as typeof autoCollectMode)}
                          className="hidden"
                        />
                        {opt.label}
                      </label>
                    ))}
                  </div>

                  {autoCollectMode === 'multiples10' && (
                    <>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-gray-400 whitespace-nowrap">설정값</label>
                        <input
                          type="number"
                          min={0}
                          max={999}
                          step={1}
                          value={autoCollectValue}
                          onChange={(e) => setAutoCollectValue(parseInt(e.target.value, 10) || 0)}
                          className="flex-1 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                        />
                        <span className="text-xs text-gray-500">(0 = 해제)</span>
                      </div>
                      <p className="text-[11px] text-gray-500">
                        10·20·30… 레벨에 설정값 적용, 나머지 레벨은 0(해제)으로 업로드.
                      </p>
                    </>
                  )}

                  {autoCollectMode === 'preserve' && (
                    <p className="text-[11px] text-gray-500">
                      각 레벨의 level_json.autoCollectCount 값을 그대로 사용 (없으면 0 = 해제).
                    </p>
                  )}
                </div>

                <Button
                  onClick={handleCheckConflicts}
                  disabled={previewTargetIds.length === 0}
                  className="w-full"
                >
                  서버 확인 후 업로드 ({previewTargetIds.length}개)
                </Button>
              </>
            )}

            {/* Checking Phase */}
            {gboostPhase === 'checking' && (
              <div className="flex flex-col items-center py-6">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mb-3"></div>
                <p className="text-sm text-gray-300">서버에서 기존 레벨 확인 중...</p>
              </div>
            )}

            {/* Conflict Phase */}
            {gboostPhase === 'conflict' && (
              <div className="space-y-3">
                <div className="bg-yellow-900/30 border border-yellow-600 rounded-lg p-3">
                  <div className="flex items-start gap-2">
                    <span className="text-xl">⚠️</span>
                    <div>
                      <h4 className="text-yellow-300 font-semibold text-sm">
                        {conflictingLevels.length}개 레벨이 이미 존재합니다
                      </h4>
                      <p className="text-yellow-200 text-xs mt-1">
                        덮어쓰기하면 기존 레벨이 대체됩니다.
                      </p>
                    </div>
                  </div>
                </div>

                <div className="bg-gray-900 rounded-lg p-2 max-h-32 overflow-y-auto">
                  {conflictingLevels.slice(0, 10).map((conflict) => (
                    <div key={conflict.targetId} className="flex items-center gap-2 text-xs py-1">
                      <span className="text-yellow-400">⚠</span>
                      <span className="text-yellow-300">{conflict.targetId}</span>
                    </div>
                  ))}
                  {conflictingLevels.length > 10 && (
                    <div className="text-xs text-gray-500 pt-1">
                      ... 외 {conflictingLevels.length - 10}개
                    </div>
                  )}
                </div>

                {backupBeforeOverwrite && (
                  <div className="bg-blue-900/30 border border-blue-700 rounded-lg p-2">
                    <p className="text-blue-300 text-xs">
                      ✓ 백업 옵션 활성화됨 - 덮어쓰기 전 기존 레벨이 로컬에 백업됩니다.
                    </p>
                  </div>
                )}

                {backupProgress.total > 0 && (
                  <div>
                    <div className="flex justify-between text-xs text-gray-400 mb-1">
                      <span>백업 진행 중...</span>
                      <span>{backupProgress.current} / {backupProgress.total}</span>
                    </div>
                    <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-yellow-500 transition-all"
                        style={{ width: `${(backupProgress.current / backupProgress.total) * 100}%` }}
                      />
                    </div>
                  </div>
                )}

                <div className="flex gap-2">
                  <Button
                    onClick={handleResetGBoost}
                    variant="secondary"
                    className="flex-1"
                  >
                    취소
                  </Button>
                  {overwrite ? (
                    <Button
                      onClick={handleBackupAndUpload}
                      // 백업이 '진행 중'일 때만 잠근다. total>0 로 잠그면 백업이 끝난 뒤에도
                      // 진행률이 남아 버튼이 영구 비활성화된다(위 setBackupProgress 리셋과 한 쌍).
                      disabled={backupProgress.total > 0 && backupProgress.current < backupProgress.total}
                      className="flex-1"
                    >
                      {backupBeforeOverwrite ? '백업 후 덮어쓰기' : '덮어쓰기'}
                    </Button>
                  ) : (
                    <Button
                      onClick={handleUpload}
                      className="flex-1"
                    >
                      충돌 건너뛰고 업로드
                    </Button>
                  )}
                </div>
              </div>
            )}

            {/* Uploading Phase */}
            {gboostPhase === 'uploading' && gboostProgress.total > 0 && (
              <div className="space-y-3">
                <div className="flex justify-between text-xs text-gray-400">
                  <span>업로드 중...</span>
                  <span>{gboostProgress.current}/{gboostProgress.total}</span>
                </div>
                <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 transition-all"
                    style={{ width: `${(gboostProgress.current / gboostProgress.total) * 100}%` }}
                  />
                </div>
              </div>
            )}

            {/* Complete Phase */}
            {gboostPhase === 'complete' && (
              <div className="space-y-3">
                <div className="bg-green-900/30 border border-green-700 rounded-lg p-3">
                  <div className="flex items-center gap-4 text-sm">
                    <div className="flex items-center gap-1">
                      <span className="text-green-400">✓</span>
                      <span className="text-gray-300">{uploadResult.success} 성공</span>
                    </div>
                    {uploadResult.failed > 0 && (
                      <div className="flex items-center gap-1">
                        <span className="text-red-400">✕</span>
                        <span className="text-gray-300">{uploadResult.failed} 실패</span>
                      </div>
                    )}
                    {uploadResult.skipped > 0 && (
                      <div className="flex items-center gap-1">
                        <span className="text-yellow-400">⊘</span>
                        <span className="text-gray-300">{uploadResult.skipped} 건너뜀</span>
                      </div>
                    )}
                  </div>
                </div>

                <Button
                  onClick={handleResetGBoost}
                  variant="secondary"
                  className="w-full"
                >
                  완료
                </Button>
              </div>
            )}
          </>
        ) : (
          <p className="text-xs text-gray-500">
            GBoost 연결을 먼저 설정해주세요. (GBoost 패널에서 설정)
          </p>
        )}
      </div>

      {/* JSON Export Settings */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-4">
        <h3 className="text-sm font-medium text-white">JSON 파일 내보내기</h3>

        {/* Format */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">파일 포맷</label>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as typeof format)}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
          >
            <option value="json">JSON (단일 파일, 포맷팅)</option>
            <option value="json_minified">JSON (단일 파일, 압축)</option>
            <option value="json_split">JSON (개별 파일)</option>
          </select>
        </div>

        {/* Filename Pattern (for split mode) */}
        {format === 'json_split' && (
          <div>
            <label className="block text-xs text-gray-400 mb-1">파일명 패턴</label>
            <input
              type="text"
              value={filenamePattern}
              onChange={(e) => setFilenamePattern(e.target.value)}
              placeholder="level_{number:04d}.json"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            />
            <p className="text-xs text-gray-500 mt-1">
              {'{number}'} = 레벨 번호, {'{number:04d}'} = 4자리 패딩, {'{grade}'} = 등급
            </p>
          </div>
        )}

        {/* Include Meta */}
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={includeMeta}
            onChange={(e) => setIncludeMeta(e.target.checked)}
            className="rounded border-gray-600"
          />
          <span className="text-sm text-gray-300">메타데이터 포함</span>
          <span className="text-xs text-gray-500">(난이도, 등급 등)</span>
        </label>

        {/* Export Button */}
        <Button
          onClick={handleExportJson}
          disabled={isExporting || readyCount === 0}
          variant="secondary"
          className="w-full"
        >
          {isExporting ? '내보내는 중...' : `JSON 다운로드 (${totalReady}개)`}
        </Button>
      </div>
    </div>
  );
}

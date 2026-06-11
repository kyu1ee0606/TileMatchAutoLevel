/**
 * Meta Integrity Panel
 * 저장된 프로덕션 레벨에서 메타 ↔ 실제 level_json 불일치 검출.
 *
 * 현재 검사 항목:
 * 1. useTileCount (메타에 기록된 타일 종류 수) ↔ level_json에 실제로 등장하는 일반 타일 종류 수
 *
 * 과거 결함:
 *   - get_tile_types_for_level이 t1..t{useTileCount} 범위를 넘는 t-인덱스를 풀에 포함시키고
 *     다운스트림 필터가 그 항목을 잘라버려 useTileCount=6인데 실제 3종만 배치되는 사례 다수 발생.
 *   - 신규 생성은 v15.45에서 수정됐으나 이미 저장된 레벨은 결함이 남아있음.
 */
import { useState } from 'react';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { getProductionLevelsByBatch } from '../../storage/productionStorage';
import { ProductionLevel } from '../../types/production';
import { LevelJSON } from '../../types';

interface MetaIntegrityPanelProps {
  batchId: string;
  onRegenerateLevel?: (levelNumber: number) => Promise<void> | void;
  onBulkRegenerate?: (levelNumbers: number[]) => Promise<void> | void;
}

interface MismatchRow {
  level_number: number;
  // 확정 데드락: 타입별 3배수 위반
  divisibility_offenders?: { type: string; count: number; remainder: number }[];
  // 정보성: useTileCount 선언 vs 실제 타입 수
  declared_use_tile_count?: number;
  actual_type_count?: number;
  actual_types?: string[];
  // OOB 타일 (각 레이어 col/row 밖) — 디바이스에서 잘려서 픽 불가 → 잠재적 데드락
  oob_count?: number;
  oob_detail?: { layer: number; pos: string; tile_type: string; declared: string }[];
  // 결함 카테고리 — 'deadlock'은 확정, 'oob_tiles'는 디바이스에서 잘릴 수 있는 위험,
  // 'useTileCount'는 메타 부정확
  issues: ('deadlock' | 'oob_tiles' | 'useTileCount')[];
  pattern_index?: number;
  template_id?: string;
}

/**
 * 타입별 카운트 + 3의 배수 위반 검출.
 *
 * 데드락 판정 로직:
 *   1) 일반 타일 타입(t1~t15)의 카운트를 집계.
 *   2) craft_x / stack_x 박스의 내부 타일 합(`internal`)을 별도 집계 — 런타임에 부족한 타입을
 *      자동 보충하는 "버퍼".
 *   3) 각 타입의 부족분 합 `needed = sum((3 - count%3) % 3)`.
 *   4) `internal >= needed`이고 `(internal - needed) % 3 == 0`이면 보충 가능 → 클리어 가능.
 *      (남는 internal은 3개씩 묶어 한 타입의 완성된 triple 추가로 사용 가능)
 *
 * 이전 로직은 일반 타일만 보고 잔여만 있으면 무조건 데드락으로 판정 → craft가 잔여를
 * 흡수하는 정상 레벨도 false positive로 잠금 표시되는 문제 있었음.
 */
export function checkTileDivisibility(
  level_json: LevelJSON | undefined | null
): {
  ok: boolean;
  perType: Record<string, number>;
  offenders: { type: string; count: number; remainder: number }[];
  internalCount: number;
  neededFromInternal: number;
} {
  const perType: Record<string, number> = {};
  let internalCount = 0;
  if (!level_json) return { ok: true, perType, offenders: [], internalCount: 0, neededFromInternal: 0 };
  const layers = level_json.layer ?? 0;
  for (let i = 0; i < layers; i++) {
    const layer = (level_json as unknown as Record<string, unknown>)[`layer_${i}`];
    if (!layer || typeof layer !== 'object') continue;
    const tiles = (layer as { tiles?: Record<string, unknown> }).tiles;
    if (!tiles) continue;
    for (const tile of Object.values(tiles)) {
      if (!Array.isArray(tile) || tile.length < 1) continue;
      const t = tile[0];
      if (typeof t !== 'string') continue;
      if (t.startsWith('t') && /^t\d+$/.test(t) && t !== 't0') {
        perType[t] = (perType[t] ?? 0) + 1;
      } else if (t.startsWith('craft_') || t.startsWith('stack_')) {
        // 내부 타일 합 — 런타임에 임의 타입으로 보충 가능한 "버퍼"
        const extra = tile[2];
        let internal = 0;
        if (Array.isArray(extra) && extra.length > 0) {
          internal = parseInt(String(extra[0]), 10) || 0;
        } else if (typeof extra === 'number') {
          internal = extra;
        } else if (extra && typeof extra === 'object') {
          const obj = extra as Record<string, unknown>;
          internal = parseInt(String(obj.totalCount ?? obj.count ?? 0), 10) || 0;
        }
        if (internal > 0) internalCount += internal;
      }
    }
  }
  const remainders: { type: string; count: number; remainder: number }[] = [];
  let needed = 0;
  for (const [type, count] of Object.entries(perType)) {
    const rem = count % 3;
    if (rem !== 0) {
      remainders.push({ type, count, remainder: rem });
      needed += (3 - rem) % 3;
    }
  }
  remainders.sort((a, b) => parseInt(a.type.slice(1)) - parseInt(b.type.slice(1)));

  // 데드락 판정: 부족분을 craft/stack 내부 타일로 메울 수 있는가?
  const surplus = internalCount - needed;
  const playable = internalCount >= needed && surplus % 3 === 0;

  return {
    ok: playable,
    perType,
    offenders: playable ? [] : remainders,
    internalCount,
    neededFromInternal: needed,
  };
}

export { detectOOBTiles };

function countActualTileTypes(level_json: LevelJSON | undefined | null): { count: number; types: string[] } {
  if (!level_json) return { count: 0, types: [] };
  const layers = level_json.layer ?? 0;
  const set = new Set<string>();
  for (let i = 0; i < layers; i++) {
    const layer = (level_json as unknown as Record<string, unknown>)[`layer_${i}`];
    if (!layer || typeof layer !== 'object') continue;
    const tiles = (layer as { tiles?: Record<string, unknown> }).tiles;
    if (!tiles || typeof tiles !== 'object') continue;
    for (const tile of Object.values(tiles)) {
      if (!Array.isArray(tile) || tile.length < 1) continue;
      const t = tile[0];
      if (typeof t !== 'string') continue;
      // 일반 색상 타일만 (t1~t15). t0 placeholder, craft_*, stack_*, key 등 제외
      if (t.startsWith('t') && /^t\d+$/.test(t) && t !== 't0') {
        set.add(t);
      }
    }
  }
  return { count: set.size, types: Array.from(set).sort((a, b) => parseInt(a.slice(1)) - parseInt(b.slice(1))) };
}

/**
 * 각 레이어의 col/row 선언 범위를 벗어난 타일 검출.
 * 클라이언트는 layer.col/row 기준으로 그리드를 렌더해 OOB 타일은 접근 불가.
 * 정적 카운트는 통과해도 실제 디바이스에서 데드락 발생.
 */
function detectOOBTiles(
  level_json: LevelJSON | undefined | null
): { count: number; detail: { layer: number; pos: string; tile_type: string; declared: string }[] } {
  if (!level_json) return { count: 0, detail: [] };
  const detail: { layer: number; pos: string; tile_type: string; declared: string }[] = [];
  const layers = level_json.layer ?? 0;
  for (let i = 0; i < layers; i++) {
    const layer = (level_json as unknown as Record<string, unknown>)[`layer_${i}`];
    if (!layer || typeof layer !== 'object') continue;
    const ld = layer as { col?: string | number; row?: string | number; tiles?: Record<string, unknown> };
    const cols = parseInt(String(ld.col ?? 0), 10);
    const rows = parseInt(String(ld.row ?? 0), 10);
    if (!Number.isFinite(cols) || !Number.isFinite(rows) || cols <= 0 || rows <= 0) continue;
    const tiles = ld.tiles ?? {};
    for (const [pos, tile] of Object.entries(tiles)) {
      const parts = pos.split('_');
      if (parts.length !== 2) continue;
      const x = parseInt(parts[0], 10);
      const y = parseInt(parts[1], 10);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      if (x >= cols || y >= rows || x < 0 || y < 0) {
        const tType = Array.isArray(tile) && typeof tile[0] === 'string' ? tile[0] : '?';
        detail.push({ layer: i, pos, tile_type: tType, declared: `${cols}x${rows}` });
      }
    }
  }
  return { count: detail.length, detail };
}

export function MetaIntegrityPanel({ batchId, onRegenerateLevel, onBulkRegenerate }: MetaIntegrityPanelProps) {
  const { addNotification } = useUIStore();
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState(false);
  const [totalScanned, setTotalScanned] = useState(0);
  const [mismatches, setMismatches] = useState<MismatchRow[]>([]);
  const [regeneratingSet, setRegeneratingSet] = useState<Set<number>>(new Set());
  const [bulkInProgress, setBulkInProgress] = useState(false);

  const handleScan = async () => {
    setScanning(true);
    try {
      const levels: ProductionLevel[] = await getProductionLevelsByBatch(batchId);
      const rows: MismatchRow[] = [];
      for (const lvl of levels) {
        const issues: MismatchRow['issues'] = [];
        const lj = lvl.level_json as LevelJSON | undefined;

        // 1) 데드락 확정: 타입별 3배수 위반 (클리어 불가)
        const div = checkTileDivisibility(lj);

        // 2) OOB 타일 — 각 레이어 col/row 밖에 배치된 타일. 디바이스가 layer.col/row를
        //    strict size로 해석해 그 밖의 타일을 렌더링하지 않음 → 픽 불가 → 잠재적 데드락.
        //    (사용자 디바이스 보고: "L1 맨 아래 2개 타일 잘림" 케이스)
        const oob = detectOOBTiles(lj);

        // 3) 정보성: useTileCount mismatch (메타 부정확하지만 게임 동작은 보통 정상)
        const declared = (lj as { useTileCount?: number } | undefined)?.useTileCount;
        const { count: actualCount, types: actualTypes } = countActualTileTypes(lj);
        const useTileCountMismatch = typeof declared === 'number' && actualCount !== declared;

        if (!div.ok) issues.push('deadlock');
        if (oob.count > 0) issues.push('oob_tiles');
        if (useTileCountMismatch) issues.push('useTileCount');

        if (issues.length === 0) continue;

        rows.push({
          level_number: lvl.meta.level_number,
          divisibility_offenders: div.offenders,
          declared_use_tile_count: declared,
          actual_type_count: actualCount,
          actual_types: actualTypes,
          oob_count: oob.count,
          oob_detail: oob.detail,
          issues,
          pattern_index: lvl.meta.pattern_index,
          template_id: (lvl.meta as { template_id?: string }).template_id,
        });
      }
      rows.sort((a, b) => {
        // 데드락(빨강)을 먼저 보여주기
        const da = a.issues.includes('deadlock') ? 0 : 1;
        const db = b.issues.includes('deadlock') ? 0 : 1;
        if (da !== db) return da - db;
        return a.level_number - b.level_number;
      });
      setTotalScanned(levels.length);
      setMismatches(rows);
      setScanned(true);
      const deadlockCount = rows.filter(r => r.issues.includes('deadlock')).length;
      const oobCount = rows.filter(r => r.issues.includes('oob_tiles')).length;
      const utcCount = rows.filter(r => r.issues.includes('useTileCount')).length;
      addNotification(
        (deadlockCount + oobCount) > 0 ? 'error' : utcCount > 0 ? 'warning' : 'success',
        `메타 정합성 검사: 총 ${levels.length}개 중 데드락 ${deadlockCount}개 · 디바이스 잘림 위험(OOB) ${oobCount}개 · useTileCount 불일치 ${utcCount}개`,
      );
    } catch (e) {
      console.error('[MetaIntegrity] scan failed:', e);
      addNotification('error', '검사 실패: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setScanning(false);
    }
  };

  const handleRegenerate = async (levelNumber: number) => {
    if (!onRegenerateLevel) return;
    setRegeneratingSet(prev => new Set([...prev, levelNumber]));
    try {
      await onRegenerateLevel(levelNumber);
      // 결과 갱신 — 다시 스캔 (저장된 level_json이 바뀌었을 수 있음)
      // 자동 재스캔은 부담될 수 있으니 행 자체만 제거
      setMismatches(prev => prev.filter(r => r.level_number !== levelNumber));
    } finally {
      setRegeneratingSet(prev => {
        const next = new Set(prev);
        next.delete(levelNumber);
        return next;
      });
    }
  };

  const handleBulkRegen = async () => {
    if (!onBulkRegenerate || mismatches.length === 0) return;
    setBulkInProgress(true);
    try {
      await onBulkRegenerate(mismatches.map(r => r.level_number));
      // 일괄 재생성 후 자동 재스캔
      await handleScan();
    } finally {
      setBulkInProgress(false);
    }
  };

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-white">🔬 메타 정합성 검사</h3>
          <p className="text-xs text-gray-400 mt-1">
            저장된 레벨 JSON에서 세 가지 결함을 검출합니다:
          </p>
          <ul className="text-xs text-gray-400 mt-1 ml-4 list-disc space-y-0.5">
            <li>
              <span className="text-red-300 font-semibold">데드락 확정</span> — 일반 타일 타입 중 카운트가 3의 배수가 아닌 게 있어 끝에 잔여 발생 → 클리어 불가
            </li>
            <li>
              <span className="text-orange-300 font-semibold">디바이스 잘림 위험 (OOB)</span> — 어떤 레이어의 선언 col/row 범위 밖 좌표에 타일이 있음. 디바이스에서 그 타일이 렌더되지 않아 픽 불가 → 잠재적 클리어 불가
            </li>
            <li>
              <span className="text-blue-300">useTileCount 불일치</span> — 선언값과 실제 등장 종류 수 차이 (메타 부정확. 게임 동작은 보통 정상)
            </li>
          </ul>
        </div>
      </div>

      <div className="flex gap-2">
        <Button
          onClick={handleScan}
          disabled={scanning}
          variant="primary"
          size="sm"
          className="flex-1"
        >
          {scanning ? '검사 중...' : scanned ? '다시 검사' : '검사 시작'}
        </Button>
        {scanned && mismatches.length > 0 && onBulkRegenerate && (
          <Button
            onClick={handleBulkRegen}
            disabled={bulkInProgress || regeneratingSet.size > 0}
            variant="danger"
            size="sm"
            className="flex-1"
          >
            {bulkInProgress ? '재생성 중...' : `결함 ${mismatches.length}개 일괄 재생성`}
          </Button>
        )}
      </div>

      {scanned && (() => {
        const dlCount = mismatches.filter(r => r.issues.includes('deadlock')).length;
        const oobOnlyCount = mismatches.filter(r => r.issues.includes('oob_tiles') && !r.issues.includes('deadlock')).length;
        const utcOnlyCount = mismatches.filter(r => r.issues.includes('useTileCount') && !r.issues.includes('deadlock') && !r.issues.includes('oob_tiles')).length;
        return (
          <div className="text-xs text-gray-300 bg-gray-900/50 rounded p-2 space-y-1">
            <div>
              총 검사: <span className="text-gray-100 font-medium">{totalScanned}</span>개
              {' · '}
              데드락 확정: <span className={dlCount === 0 ? 'text-green-400' : 'text-red-400 font-bold'}>{dlCount}</span>개
              {' · '}
              디바이스 잘림 위험: <span className={oobOnlyCount === 0 ? 'text-green-400' : 'text-orange-400 font-bold'}>{oobOnlyCount}</span>개
              {' · '}
              useTileCount 불일치: <span className={utcOnlyCount === 0 ? 'text-green-400' : 'text-blue-400'}>{utcOnlyCount}</span>개
            </div>
            {mismatches.length === 0 && <div className="text-green-400">✓ 모두 정합 — 데드락 없음, 디바이스 잘림 없음, 메타 정확</div>}
          </div>
        );
      })()}

      {mismatches.length > 0 && (
        <div className="border border-gray-700 rounded-lg overflow-hidden">
          <div className="grid grid-cols-12 gap-2 px-3 py-2 bg-gray-700/50 text-[11px] text-gray-400 font-medium">
            <span className="col-span-2">레벨</span>
            <span className="col-span-2">결함</span>
            <span className="col-span-6">상세</span>
            <span className="col-span-2 text-right">조치</span>
          </div>
          <div className="max-h-[360px] overflow-y-auto divide-y divide-gray-700">
            {mismatches.map(row => {
              const isDeadlock = row.issues.includes('deadlock');
              const hasOob = row.issues.includes('oob_tiles');
              const hasUtc = row.issues.includes('useTileCount');
              return (
                <div
                  key={row.level_number}
                  className={`grid grid-cols-12 gap-2 px-3 py-2 text-xs hover:bg-gray-700/20 ${
                    isDeadlock ? 'bg-red-950/30' : hasOob ? 'bg-orange-950/30' : ''
                  }`}
                >
                  <span className="col-span-2 text-gray-200 font-medium">
                    Lv.{row.level_number}
                    {row.template_id && (
                      <span className="ml-1 text-[9px] text-purple-400" title={`template=${row.template_id}`}>📄</span>
                    )}
                    {row.pattern_index !== undefined && row.pattern_index >= 0 && (
                      <span className="ml-1 text-[9px] text-blue-400" title={`pattern_index=${row.pattern_index}`}>#{row.pattern_index}</span>
                    )}
                  </span>
                  <span className="col-span-2 flex flex-col gap-0.5">
                    {isDeadlock && (
                      <span className="inline-block px-1.5 py-0.5 text-[10px] rounded bg-red-900/60 text-red-200 border border-red-600 font-bold">
                        🔒 데드락
                      </span>
                    )}
                    {hasOob && (
                      <span className="inline-block px-1.5 py-0.5 text-[10px] rounded bg-orange-900/60 text-orange-200 border border-orange-600 font-bold">
                        ✂ 잘림 ×{row.oob_count}
                      </span>
                    )}
                    {hasUtc && (
                      <span className="inline-block px-1.5 py-0.5 text-[10px] rounded bg-blue-900/40 text-blue-300 border border-blue-700/50">
                        useTileCount
                      </span>
                    )}
                  </span>
                  <span className="col-span-6 text-gray-400 text-[11px]">
                    {isDeadlock && row.divisibility_offenders && row.divisibility_offenders.length > 0 && (
                      <div>
                        <span className="text-red-400 font-semibold">3배수 위반:</span>{' '}
                        {row.divisibility_offenders.map(o =>
                          `${o.type}=${o.count}(잔여${o.remainder})`
                        ).join(', ')}
                        {' '}
                        <span className="text-gray-500">(craft/stack 내부 보충도 부족)</span>
                      </div>
                    )}
                    {hasOob && row.oob_detail && row.oob_detail.length > 0 && (
                      <div title={row.oob_detail.map(d => `L${d.layer} (${d.declared}) ${d.pos}=${d.tile_type}`).join(' · ')}>
                        <span className="text-orange-400 font-semibold">디바이스 잘림:</span>{' '}
                        {row.oob_detail.slice(0, 3).map(d =>
                          `L${d.layer}[${d.declared}]@${d.pos}:${d.tile_type}`
                        ).join(', ')}
                        {row.oob_detail.length > 3 && ` +${row.oob_detail.length - 3}`}
                      </div>
                    )}
                    {hasUtc && (
                      <div>
                        <span className="text-gray-500">useTileCount</span>{' '}
                        선언 {row.declared_use_tile_count} → 실제 {row.actual_type_count}
                        <span className="ml-2 text-gray-500 truncate" title={(row.actual_types ?? []).join(', ')}>
                          ({(row.actual_types ?? []).join(', ')})
                        </span>
                      </div>
                    )}
                  </span>
                  <span className="col-span-2 text-right">
                    {onRegenerateLevel && (
                      <button
                        onClick={() => handleRegenerate(row.level_number)}
                        disabled={regeneratingSet.has(row.level_number) || bulkInProgress}
                        className="px-2 py-0.5 text-[11px] rounded bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 text-white"
                      >
                        {regeneratingSet.has(row.level_number) ? '...' : '재생성'}
                      </button>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

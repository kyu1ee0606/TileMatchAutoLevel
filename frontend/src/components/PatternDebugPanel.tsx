/**
 * PatternDebugPanel
 * 패턴 템플릿 편집 + 실제 생성 결과 비교 디버그 도구
 * - 패턴 그리드를 클릭하여 셀 ON/OFF 편집
 * - 편집된 패턴을 JSON으로 복사하여 Claude Code와 소통
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import apiClient from '../api/client';
import { PatternSynthModal } from './PatternSynthModal';
import { getPatternByIndex } from '../constants/patterns';
import GameBoard from './GamePlayer/GameBoard';
import { createGameEngine } from '../engine/gameEngine';
import type { GameTile } from '../types/game';

// 프로덕션 레이어 col 크기 = 5·6·7 (홀짝 base 5→[6,5], base 6→[7,6]). 신규 커스텀 패턴은
// 이 3개 크기를 필수로 그려야 전 레벨 커버(그 외 4/8/9는 선택). 8+ 는 프로덕션 미사용.
const REQUIRED_PATTERN_SIZES = [5, 6, 7];

interface PatternInfo {
  index: number;
  count: number;
  fill_rate: number;
  is_custom?: boolean;
  grid: number[][];
}

interface PatternPreview {
  pattern_index: number;
  template_count: number;
  actual_count: number;
  missing_count: number;
  extra_count: number;
  match_rate: number;
  missing: string[];
  extra: string[];
  grid: string[][];
  template_positions: string[];
}

// 레이어별 색상
const LAYER_COLORS = ['#3b82f6', '#22c55e', '#a855f7', '#f97316', '#ec4899', '#06b6d4'];

interface SilhouetteCell {
  layers: number[]; // 이 셀을 차지하는 레이어 인덱스들
}

/**
 * 0.5 오프셋 반영 합산 실루엣 계산.
 * 각 타일은 서브그리드에서 2x2 블록으로 표현.
 * 짝수 레이어: (col, row) → 서브그리드 (col*2, row*2)
 * 홀수 레이어: (col, row) → 서브그리드 (col*2+1, row*2+1)
 */
// [v15.51] 기믹/스택 시각 표현 — 레이어 그리드에 오버레이 아이콘+배지
const GIMMICK_ICONS: Record<string, string> = {
  chain: '⛓',
  link_s: '🔗',
  link_s_n: '🔗',
  curtain_close: '🎭',
  curtain_open: '🎭',
  frog: '🐸',
  ice_1: '🧊',
  ice_2: '🧊',
  glass: '🥂',
  locked: '🔒',
};

const TILE_TYPE_ICONS: Record<string, string> = {
  craft_s: '🎯',
  stack_s: '📚',
  bomb: '💣',
  key: '🔑',
};

interface GimmickCellInfo {
  icon: string;       // 셀 중앙에 표시할 아이콘 (없으면 '')
  badge: string;      // 우하단 배지 (예: stack count, craft count). 없으면 ''
  label: string;      // 툴팁
  borderClass: string; // 구분용 border 클래스
}

function describeTile(detail: { tile_type: string; attribute: string; extra: unknown }): GimmickCellInfo {
  const { tile_type, attribute, extra } = detail;
  const hasGimmickType = tile_type && tile_type !== 't0' && !/^t\d+$/.test(tile_type);
  const hasAttr = !!attribute;
  if (!hasGimmickType && !hasAttr) {
    return { icon: '', badge: '', label: '', borderClass: '' };
  }
  const iconParts: string[] = [];
  const labelParts: string[] = [];
  let badge = '';
  if (hasGimmickType) {
    iconParts.push(TILE_TYPE_ICONS[tile_type] || '⭐');
    labelParts.push(tile_type);
  }
  if (hasAttr) {
    iconParts.push(GIMMICK_ICONS[attribute] || '⚡');
    labelParts.push(attribute);
  }
  if (Array.isArray(extra) && extra.length > 0) {
    const num = extra[0];
    if (typeof num === 'number' || /^\d+$/.test(String(num))) {
      badge = String(num);
      labelParts.push(`×${num}`);
    }
  }
  return {
    icon: iconParts[0] || '',
    badge,
    label: labelParts.join(' '),
    borderClass: hasGimmickType ? 'ring-2 ring-yellow-400' : 'ring-1 ring-amber-500/60',
  };
}

function computeSilhouette(
  layers: { layer: number; count: number; grid_cols: number; grid_rows: number; grid: number[][] }[]
): { grid: SilhouetteCell[][]; width: number; height: number } {
  if (layers.length === 0) return { grid: [], width: 0, height: 0 };

  const baseLayer = layers[0];
  const baseCols = baseLayer.grid_cols;
  const baseRows = baseLayer.grid_rows;

  // 각 레이어 타일의 시각적 위치를 0.5 단위로 계산 (×2 = 정수 서브그리드)
  // 짝수 레이어: 시각 중심 = gridCols / 2
  // 홀수 레이어: 시각 중심 = (gridCols + 1) / 2  (0.5 오프셋 포함)
  // 모든 레이어가 L0 중심에 맞도록 시프트
  const baseCenterX = baseCols / 2;  // L0 시각 중심 (even)
  const baseCenterY = baseRows / 2;

  // 서브그리드 크기 (여유 포함)
  const maxSubX = baseCols * 2 + 2;
  const maxSubY = baseRows * 2 + 2;

  const grid: SilhouetteCell[][] = Array.from({ length: maxSubY }, () =>
    Array.from({ length: maxSubX }, () => ({ layers: [] }))
  );

  for (const lv of layers) {
    if (!lv.grid.length || lv.count === 0) continue;
    const isOdd = lv.layer % 2 === 1;

    // 이 레이어의 시각 중심
    const layerCenterX = isOdd ? (lv.grid_cols + 1) / 2 : lv.grid_cols / 2;
    const layerCenterY = isOdd ? (lv.grid_rows + 1) / 2 : lv.grid_rows / 2;

    // L0 중심에 맞추기 위한 시프트 (타일 단위, 0.5 가능)
    const shiftX = baseCenterX - layerCenterX;
    const shiftY = baseCenterY - layerCenterY;

    for (let y = 0; y < lv.grid_rows; y++) {
      for (let x = 0; x < lv.grid_cols; x++) {
        if (!lv.grid[y]?.[x]) continue;

        // 시각적 좌표 (타일 단위)
        const vizX = x + (isOdd ? 0.5 : 0) + shiftX;
        const vizY = y + (isOdd ? 0.5 : 0) + shiftY;

        // 서브그리드 좌표 (×2)
        const sx = Math.round(vizX * 2);
        const sy = Math.round(vizY * 2);

        // 2×2 블록 배치 (1 타일 = 서브그리드 2셀)
        for (let dy = 0; dy < 2; dy++) {
          for (let dx = 0; dx < 2; dx++) {
            const ny = sy + dy, nx = sx + dx;
            if (ny >= 0 && ny < maxSubY && nx >= 0 && nx < maxSubX) {
              if (!grid[ny][nx].layers.includes(lv.layer)) {
                grid[ny][nx].layers.push(lv.layer);
              }
            }
          }
        }
      }
    }
  }

  return { grid, width: maxSubX, height: maxSubY };
}

export function PatternDebugPanel() {
  const [patterns, setPatterns] = useState<PatternInfo[]>([]);
  const [selectedPattern, setSelectedPattern] = useState<number | null>(null);
  const [preview, setPreview] = useState<PatternPreview | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [gridSize, setGridSize] = useState(8);

  // 표시 순서 (드래그 정렬)
  const [displayOrder, setDisplayOrder] = useState<number[]>([]);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);

  // 표시 순서 로드 (최초 1회)
  const [orderLoaded, setOrderLoaded] = useState(false);
  useEffect(() => {
    if (!orderLoaded) {
      apiClient.get('/debug/pattern-config').then(res => {
        const savedOrder = res.data.display_order as number[] | undefined;
        if (savedOrder && savedOrder.length > 0) {
          setDisplayOrder(savedOrder);
        }
        setOrderLoaded(true);
      }).catch(() => setOrderLoaded(true));
    }
  }, [orderLoaded]);

  // patterns + displayOrder 기반 정렬
  const sortedPatterns = (() => {
    if (displayOrder.length === 0) return patterns;
    const patternMap = new Map(patterns.map(p => [p.index, p]));
    const ordered = displayOrder.map(idx => patternMap.get(idx)).filter(Boolean) as PatternInfo[];
    // displayOrder에 없는 새 패턴 추가
    const inOrder = new Set(displayOrder);
    const extra = patterns.filter(p => !inOrder.has(p.index));
    return [...ordered, ...extra];
  })();

  const handleDragStart = (idx: number) => setDragIdx(idx);
  const handleDragOver = (e: React.DragEvent, idx: number) => { e.preventDefault(); setDragOverIdx(idx); };
  const handleDrop = async (targetIdx: number) => {
    if (dragIdx === null || dragIdx === targetIdx) { setDragIdx(null); setDragOverIdx(null); return; }
    const order = [...displayOrder.length > 0 ? displayOrder : patterns.map(p => p.index)];
    const fromPos = order.indexOf(dragIdx);
    const toPos = order.indexOf(targetIdx);
    if (fromPos < 0 || toPos < 0) return;
    order.splice(fromPos, 1);
    order.splice(toPos, 0, dragIdx);
    setDisplayOrder(order);
    setDragIdx(null);
    setDragOverIdx(null);
    // 서버에 순서 저장
    try {
      await apiClient.post('/debug/pattern-order', { order });
    } catch { /* ignore */ }
  };

  // 편집 모드
  const [editGrid, setEditGrid] = useState<boolean[][]>([]);
  const [isEditing, setIsEditing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [dragMode, setDragMode] = useState<'add' | 'remove'>('add');
  const [copied, setCopied] = useState(false);

  // 실루엣 미리보기
  const [silhouetteData, setSilhouetteData] = useState<{
    configs: { label: string; grid: SilhouetteCell[][]; width: number; height: number; layers: { layer: number; count: number; size: number }[] }[];
  } | null>(null);
  const [silLayerCount, setSilLayerCount] = useState(4);
  const [silCustomSizes, setSilCustomSizes] = useState<number[]>([8, 7, 6, 5]);
  const [silMode, setSilMode] = useState<'production' | 'custom'>('production');

  // 프로덕션 패턴 배치 크기 계산 (스텝 기반)
  const computeProductionSizes = (baseCols: number, numLayers: number, steps?: number[]): number[] => {
    const baseSize = baseCols + 1; // L0 패턴 크기
    const defaultSteps = steps || Array(numLayers - 1).fill(-1);
    const patternSizes = [baseSize];
    for (let i = 1; i < numLayers; i++) {
      const step = i - 1 < defaultSteps.length ? defaultSteps[i - 1] : -1;
      patternSizes.push(Math.max(4, patternSizes[i - 1] + step));
    }
    // 각 레이어 그리드(짝홀 교대) 이내로 클램프
    return patternSizes.map((ps, i) => {
      const isOdd = i % 2 === 1;
      const gridSize = isOdd ? baseCols : baseCols + 1;
      return Math.min(ps, gridSize);
    });
  };

  // 실루엣 계산 트리거
  const recomputeSilhouette = useCallback(() => {
    if (selectedPattern === null) { setSilhouetteData(null); return; }
    const sizes = [4, 5, 6, 7, 8, 9];
    Promise.all(sizes.map(s =>
      apiClient.get(`/debug/pattern-list?grid_cols=${s}&grid_rows=${s}`)
        .then(res => {
          const p = (res.data.patterns as PatternInfo[]).find((pp: PatternInfo) => pp.index === selectedPattern);
          return { size: s, grid: p?.grid || [], count: p?.count || 0 };
        })
        .catch(() => ({ size: s, grid: [] as number[][], count: 0 }))
    )).then(allSizes => {
      const makeLayers = (layerSizes: number[]) =>
        layerSizes.map((s, i) => {
          const d = allSizes.find(a => a.size === s);
          return {
            layer: i, count: d?.count || 0, size: s,
            grid_cols: s, grid_rows: s, grid: d?.grid || [],
          };
        }).filter(l => l.count > 0);

      const configs: typeof silhouetteData extends null ? never : NonNullable<typeof silhouetteData>['configs'] = [];

      if (silMode === 'production') {
        const config7 = makeLayers(computeProductionSizes(7, silLayerCount));
        const config8 = makeLayers(computeProductionSizes(8, silLayerCount));
        configs.push({
          label: `grid 7×7 (${config7.map(l => l.size).join('→')})`,
          ...computeSilhouette(config7),
          layers: config7.map(l => ({ layer: l.layer, count: l.count, size: l.size })),
        });
        configs.push({
          label: `grid 8×8 (${config8.map(l => l.size).join('→')})`,
          ...computeSilhouette(config8),
          layers: config8.map(l => ({ layer: l.layer, count: l.count, size: l.size })),
        });
      } else {
        const customLayers = makeLayers(silCustomSizes.slice(0, silLayerCount));
        configs.push({
          label: `커스텀 (${customLayers.map(l => l.size).join('→')})`,
          ...computeSilhouette(customLayers),
          layers: customLayers.map(l => ({ layer: l.layer, count: l.count, size: l.size })),
        });
      }

      setSilhouetteData({ configs });
    });
  }, [selectedPattern, silLayerCount, silMode, silCustomSizes]);

  // 패턴/설정 변경 시 실루엣 자동 재계산
  useEffect(() => { recomputeSilhouette(); }, [selectedPattern, silLayerCount, silMode, silCustomSizes]);

  // 테스트 레벨 생성
  const [testMode, setTestMode] = useState(false);
  // 렌더 프레임 크기 (0 = auto: max(8, 최대 레이어 크기))
  const [renderBaseSize, setRenderBaseSize] = useState<number>(0);
  const [testLayers, setTestLayers] = useState<{ grid_size: number; pattern_index?: number }[]>([
    { grid_size: 8 }, { grid_size: 7 }, { grid_size: 6 },
  ]);
  interface TileDetail {
    tile_type: string;
    attribute: string;
    extra: unknown;
    effective_count: number;
  }
  const [testResult, setTestResult] = useState<{
    layers: {
      layer: number;
      count: number;
      position_count?: number;
      grid_cols: number;
      grid_rows: number;
      grid: number[][];
      tiles_detail?: Record<string, TileDetail>;
    }[];
    total_tiles: number;
    total_positions?: number;
    difficulty?: number;
    grade?: string;
    level_json?: Record<string, unknown>;
  } | null>(null);
  const [isGeneratingTest, setIsGeneratingTest] = useState(false);

  // 테스트 결과를 GameTile로 변환
  const previewTiles = useMemo<GameTile[]>(() => {
    if (!testResult?.level_json) return [];
    try {
      const engine = createGameEngine();
      engine.initializeFromLevel(testResult.level_json, { previewMode: true });
      return engine.getTilesForUI().map(t => ({
        id: t.id,
        type: t.type,
        attribute: t.attribute,
        layer: t.layer,
        row: t.row,
        col: t.col,
        isSelectable: t.isSelectable,
        isSelected: false,
        isMatched: false,
        isHidden: t.isHidden || false,
      }));
    } catch {
      return [];
    }
  }, [testResult?.level_json]);

  const generateTestLevel = async () => {
    if (selectedPattern === null) return;
    setIsGeneratingTest(true);
    setTestResult(null);
    try {
      const res = await apiClient.post('/debug/test-level', {
        pattern_index: selectedPattern,
        layers: testLayers,
        target_difficulty: 0.3,
        render_base_size: renderBaseSize > 0 ? renderBaseSize : null,
      });
      setTestResult(res.data);
    } catch (err) {
      console.error('Test level failed:', err);
    } finally {
      setIsGeneratingTest(false);
    }
  };

  // 활성/비활성 설정
  const [disabledPatterns, setDisabledPatterns] = useState<Set<number>>(new Set());
  const [customNames, setCustomNames] = useState<Record<string, string>>({});
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  // [신규 패턴 다중 크기] 이름 + 크기별 그리드(각 크기 따로 그림). key=grid_size.
  const [newPatternName, setNewPatternName] = useState('');
  const [variantGrids, setVariantGrids] = useState<Record<number, boolean[][]>>({});
  const [baseCollapsed, setBaseCollapsed] = useState(false);
  const [customCollapsed, setCustomCollapsed] = useState(false);

  // [v15.50] 레벨 템플릿 (기믹 포함 원본 레벨 전체 저장)
  interface LevelTemplateMeta {
    template_id: string;
    name: string;
    source_project_id?: string | null;
    source_level_id?: string | null;
    created_at?: number;
    layer_count: number;
    total_tiles: number;
    ingame_cols: number[];
    ingame_rows: number[];
    gimmick_types: Record<string, number>;
    // [v15.53] 측정 난이도
    measured_difficulty?: number | null;
    static_score?: number | null;
    static_grade?: string | null;
    autoplay_score?: number | null;
    autoplay_grade?: string | null;
    bot_clear_rates?: Record<string, number> | null;
    difficulty_measured_at?: number | null;
  }
  const [levelTemplates, setLevelTemplates] = useState<LevelTemplateMeta[]>([]);
  const [templatesCollapsed, setTemplatesCollapsed] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  // [v15.54] 템플릿 다중 선택 + 일괄 난이도 측정
  const [selectedTemplateIds, setSelectedTemplateIds] = useState<Set<string>>(new Set());
  const [lastTemplateClickIdx, setLastTemplateClickIdx] = useState<number | null>(null);
  const [batchMeasureProgress, setBatchMeasureProgress] = useState<{ done: number; total: number; current: string; failed: { id: string; reason: string }[] } | null>(null);
  const [lastMeasureError, setLastMeasureError] = useState<string | null>(null);
  const loadLevelTemplates = useCallback(async () => {
    try {
      const res = await apiClient.get('/debug/level-templates');
      setLevelTemplates((res.data.templates as LevelTemplateMeta[]) || []);
    } catch {
      setLevelTemplates([]);
    }
  }, []);
  useEffect(() => { loadLevelTemplates(); }, [loadLevelTemplates]);

  const spawnLevelTemplate = async (tid: string) => {
    // 패턴 선택 상태 초기화 — 우측 패널이 템플릿 뷰를 우선 렌더하도록
    setSelectedPattern(null);
    setPreview(null);
    setSelectedTemplateId(tid);
    setIsGeneratingTest(true);
    setTestResult(null);
    try {
      const res = await apiClient.post(`/debug/level-template-spawn/${encodeURIComponent(tid)}`);
      setTestResult(res.data);
    } catch (err) {
      console.error('Template spawn failed:', err);
    } finally {
      setIsGeneratingTest(false);
    }
  };

  // [v15.53] 템플릿 난이도 측정 — /analyze/autoplay 실행 → set-difficulty 저장
  const [measuringDifficulty, setMeasuringDifficulty] = useState<string | null>(null);
  const measureTemplateDifficulty = async (tid: string) => {
    setMeasuringDifficulty(tid);
    setLastMeasureError(null);
    try {
      const res = await apiClient.post(
        `/debug/level-template/${encodeURIComponent(tid)}/measure?iterations=100`,
        null, { timeout: 310000 }
      );
      if (res.data.error) {
        setLastMeasureError(`${tid}: ${res.data.reason || res.data.error}`);
        return;
      }
      loadLevelTemplates();
    } catch (err) {
      const msg = (err as Error).message || String(err);
      console.error('난이도 측정 실패:', err);
      setLastMeasureError(`${tid}: ${msg}`);
    } finally {
      setMeasuringDifficulty(null);
    }
  };

  // 클릭 핸들러 — Shift/Ctrl/Cmd 지원
  const handleTemplateClick = (tid: string, idx: number, ev: React.MouseEvent) => {
    if (ev.shiftKey && lastTemplateClickIdx !== null) {
      const [lo, hi] = lastTemplateClickIdx < idx ? [lastTemplateClickIdx, idx] : [idx, lastTemplateClickIdx];
      const range = new Set(selectedTemplateIds);
      for (let i = lo; i <= hi; i++) range.add(levelTemplates[i].template_id);
      setSelectedTemplateIds(range);
    } else if (ev.ctrlKey || ev.metaKey) {
      const next = new Set(selectedTemplateIds);
      if (next.has(tid)) next.delete(tid); else next.add(tid);
      setSelectedTemplateIds(next);
      setLastTemplateClickIdx(idx);
    } else {
      // 단일 선택 + spawn
      setSelectedTemplateIds(new Set([tid]));
      setLastTemplateClickIdx(idx);
      spawnLevelTemplate(tid);
    }
  };

  // 일괄 난이도 측정 — 실패 항목 추적
  const batchMeasureTemplates = async () => {
    if (selectedTemplateIds.size === 0) return;
    const tids = [...selectedTemplateIds];
    const failed: { id: string; reason: string }[] = [];
    setLastMeasureError(null);
    setBatchMeasureProgress({ done: 0, total: tids.length, current: '', failed: [] });
    for (let i = 0; i < tids.length; i++) {
      const tid = tids[i];
      setBatchMeasureProgress({ done: i, total: tids.length, current: tid, failed: [...failed] });
      try {
        const res = await apiClient.post(
          `/debug/level-template/${encodeURIComponent(tid)}/measure?iterations=100`,
          null, { timeout: 310000 }
        );
        if (res.data.error) {
          failed.push({ id: tid, reason: res.data.reason || res.data.error });
        }
      } catch (err) {
        const msg = (err as Error).message || String(err);
        console.error(`난이도 측정 실패 (${tid}):`, err);
        failed.push({ id: tid, reason: msg });
      }
    }
    const finalProgress = { done: tids.length, total: tids.length, current: '완료', failed };
    setBatchMeasureProgress(finalProgress);
    await loadLevelTemplates();
    // 실패 항목이 있으면 더 오래 표시
    setTimeout(() => setBatchMeasureProgress(null), failed.length > 0 ? 10000 : 2500);
  };

  const batchDeleteTemplates = async () => {
    if (selectedTemplateIds.size === 0) return;
    if (!window.confirm(`선택된 템플릿 ${selectedTemplateIds.size}개를 모두 삭제할까요?`)) return;
    for (const tid of selectedTemplateIds) {
      try {
        await apiClient.delete(`/debug/level-template/${encodeURIComponent(tid)}`);
      } catch (err) {
        console.error('삭제 실패:', err);
      }
    }
    setSelectedTemplateIds(new Set());
    if (selectedTemplateId && !(await (async () => {
      const stillExists = (await apiClient.get('/debug/level-templates')).data.templates?.some((t: { template_id: string }) => t.template_id === selectedTemplateId);
      return stillExists;
    })())) {
      setSelectedTemplateId(null);
      setTestResult(null);
    }
    loadLevelTemplates();
  };

  const deleteLevelTemplate = async (tid: string) => {
    if (!window.confirm(`레벨 템플릿 "${tid}" 삭제할까요?`)) return;
    try {
      await apiClient.delete(`/debug/level-template/${encodeURIComponent(tid)}`);
      if (selectedTemplateId === tid) {
        setSelectedTemplateId(null);
        setTestResult(null);
      }
      loadLevelTemplates();
    } catch (err) {
      console.error('Template delete failed:', err);
    }
  };
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [showSynthModal, setShowSynthModal] = useState(false);
  // [유닛 조립] 소형 유닛 라이브러리 뷰어
  const [unitLib, setUnitLib] = useState<{ name: string; size: number; w: number; h: number; density: number; grid: number[][] }[]>([]);
  const [unitOpen, setUnitOpen] = useState(false);
  const UNIT_EDIT_SIZE = 5;
  const [unitEditGrid, setUnitEditGrid] = useState<boolean[][]>(() => Array.from({ length: UNIT_EDIT_SIZE }, () => Array(UNIT_EDIT_SIZE).fill(false)));
  const [unitEditName, setUnitEditName] = useState('');
  const [unitPaint, setUnitPaint] = useState<boolean | null>(null);
  const loadUnits = () => apiClient.get('/debug/unit-library').then(r => setUnitLib(r.data.units || [])).catch(() => {});
  useEffect(() => { loadUnits(); }, []);
  const unitEditCount = unitEditGrid.flat().filter(Boolean).length;
  const saveUnit = async () => {
    const cells: number[][] = [];
    unitEditGrid.forEach((row, y) => row.forEach((c, x) => { if (c) cells.push([x, y]); }));
    if (cells.length % 3 !== 0 || cells.length < 3 || cells.length > 15) { window.alert('타일수가 3의 배수 + 3~15칸이어야 함 (현재 ' + cells.length + '칸)'); return; }
    try {
      await apiClient.post('/debug/unit-save', { name: unitEditName.trim() || `u${Date.now() % 100000}`, cells });
      setUnitEditGrid(Array.from({ length: UNIT_EDIT_SIZE }, () => Array(UNIT_EDIT_SIZE).fill(false)));
      setUnitEditName('');
      loadUnits();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      window.alert(`저장 실패: ${detail || (e as Error).message}`);
    }
  };
  const deleteUnit = async (name: string) => {
    if (!window.confirm(`유닛 "${name}" 삭제?`)) return;
    await apiClient.delete(`/debug/unit-save/${encodeURIComponent(name)}`).catch(() => {});
    loadUnits();
  };
  // 랜덤 유닛: 중앙에서 자라는 연결된 랜덤 모양, 타일수 ÷3(3·6·9·12). 클릭마다 다름.
  const randomUnit = () => {
    const g = UNIT_EDIT_SIZE;
    const targets = [3, 6, 6, 9, 9, 12];
    const target = targets[Math.floor(Math.random() * targets.length)];
    const grid = Array.from({ length: g }, () => Array(g).fill(false));
    const cx = Math.floor(g / 2), cy = Math.floor(g / 2);
    const cells = new Set<string>([`${cx}_${cy}`]);
    grid[cy][cx] = true;
    let guard = 0;
    while (cells.size < target && guard < 500) {
      guard++;
      const arr = [...cells];
      const [x, y] = arr[Math.floor(Math.random() * arr.length)].split('_').map(Number);
      const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1]];
      const [dx, dy] = dirs[Math.floor(Math.random() * 4)];
      const nx = x + dx, ny = y + dy;
      if (nx >= 0 && nx < g && ny >= 0 && ny < g && !cells.has(`${nx}_${ny}`)) {
        cells.add(`${nx}_${ny}`); grid[ny][nx] = true;
      }
    }
    setUnitEditGrid(grid);
    setUnitEditName(`rnd_${cells.size}_${Math.floor(Math.random() * 1000)}`);
  };
  const editUnit = (u: { name: string; grid: number[][] }) => {
    const g = Array.from({ length: UNIT_EDIT_SIZE }, () => Array(UNIT_EDIT_SIZE).fill(false));
    u.grid.forEach((row, y) => row.forEach((c, x) => { if (c && y < UNIT_EDIT_SIZE && x < UNIT_EDIT_SIZE) g[y][x] = true; }));
    setUnitEditGrid(g); setUnitEditName(u.name); setUnitOpen(true);
  };
  const [sortMode, setSortMode] = useState<'order' | 'name' | 'count'>('order');

  useEffect(() => { loadPatterns(); loadConfig(); }, [gridSize]);

  const loadPatterns = async () => {
    try {
      const res = await apiClient.get(`/debug/pattern-list?grid_cols=${gridSize}&grid_rows=${gridSize}`);
      setPatterns(res.data.patterns);
    } catch (err) {
      console.error('Failed to load patterns:', err);
    }
  };

  const [customForSize, setCustomForSize] = useState<Set<number>>(new Set());

  const loadConfig = async () => {
    try {
      const res = await apiClient.get(`/debug/pattern-config?grid_size=${gridSize}`);
      setDisabledPatterns(new Set(res.data.disabled_patterns || []));
      setCustomNames(res.data.custom_pattern_names || {});
      setCustomForSize(new Set(res.data.custom_for_size || []));
    } catch { /* ignore */ }
  };

  // 패턴 이름 가져오기 (커스텀 이름 우선)
  // [v15.52] 커스텀 패턴은 이름에서 첫 숫자 추출 → "#{레벨번호}" 형식으로 통일 표시
  // 충돌 보조(_v2, _v3)는 suffix로 유지. 숫자 없으면 원본 이름.
  const getPatternName = (idx: number): string => {
    const raw = customNames[String(idx)];
    if (raw) {
      const m = raw.match(/(\d+)/);
      if (m) {
        const rest = raw.slice((m.index || 0) + m[0].length);
        const suffix = rest.match(/_v\d+/)?.[0] || '';
        return `#${m[1]}${suffix}`;
      }
      return raw;
    }
    return getPatternByIndex(idx)?.nameKo || `#${idx}`;
  };

  const getPatternIcon = (idx: number): string => {
    return getPatternByIndex(idx)?.icon || '🎨';
  };

  // 이름 변경
  const renamePattern = async (idx: number) => {
    const current = getPatternName(idx);
    const newName = prompt('패턴 이름:', current);
    if (!newName || newName === current) return;
    try {
      await apiClient.post(`/debug/pattern-rename?pattern_index=${idx}&name=${encodeURIComponent(newName)}`);
      setCustomNames(prev => ({ ...prev, [String(idx)]: newName }));
    } catch (err) {
      console.error('Rename failed:', err);
    }
  };

  const togglePatternEnabled = async (idx: number) => {
    const isCurrentlyDisabled = disabledPatterns.has(idx);
    try {
      await apiClient.post(`/debug/pattern-toggle?pattern_index=${idx}&enabled=${isCurrentlyDisabled}&grid_size=${gridSize}`);
      const next = new Set(disabledPatterns);
      if (isCurrentlyDisabled) next.delete(idx); else next.add(idx);
      setDisabledPatterns(next);
    } catch (err) {
      console.error('Toggle failed:', err);
    }
  };

  const createNewPattern = async () => {
    setIsCreatingNew(true);
    setSelectedPattern(null);
    setPreview(null);
    setNewPatternName('');
    setVariantGrids({});
    // 빈 그리드 (현재 gridSize)
    setEditGrid(Array.from({ length: gridSize }, () => Array(gridSize).fill(false)));
    setIsEditing(true);
  };

  // 생성 중 크기 전환: 현재 그린 그리드를 그 크기로 보관 → 새 크기 그리드 로드(보관분 or 빈).
  const switchCreatingSize = (newSize: number) => {
    setVariantGrids(prev => ({ ...prev, [gridSize]: editGrid }));
    const saved = variantGrids[newSize];
    setEditGrid(saved && saved.length === newSize
      ? saved
      : Array.from({ length: newSize }, () => Array(newSize).fill(false)));
    setGridSize(newSize);
  };

  // 크기별로 따로 그린 변형 전부를 한 인덱스+이름으로 저장.
  const saveMultiSizePattern = async () => {
    // 현재 편집 중 크기 포함해 병합
    const merged: Record<number, boolean[][]> = { ...variantGrids, [gridSize]: editGrid };
    const variants = Object.entries(merged).map(([sz, grid]) => {
      const positions: string[] = [];
      grid.forEach((row, y) => row.forEach((cell, x) => { if (cell) positions.push(`${x}_${y}`); }));
      return { grid_size: Number(sz), positions };
    }).filter(v => v.positions.length >= 3);
    if (variants.length === 0) {
      window.alert('최소 한 크기 이상 3타일 이상 그려주세요.');
      return;
    }
    // [필수 크기] 프로덕션 레이어 col = 5·6·7 → 이 3개는 반드시 그려야 전 레벨 커버.
    const drawnSizes = new Set(variants.map(v => v.grid_size));
    const missing = REQUIRED_PATTERN_SIZES.filter(s => !drawnSizes.has(s));
    if (missing.length > 0) {
      window.alert(`필수 크기 미입력: ${missing.map(s => `${s}×${s}`).join(', ')}\n프로덕션 레이어(5·6·7)를 전부 그려야 저장됩니다.`);
      return;
    }
    // [÷3 자동조정 안내] 3의 배수 아닌 크기는 저장 시 서버가 인접+대칭 우선으로 ÷3 보정 → 패턴 안정성↑
    const adjusts = variants
      .filter(v => v.positions.length % 3 !== 0)
      .map(v => `${v.grid_size}×${v.grid_size}: ${v.positions.length}→${v.positions.length + (3 - (v.positions.length % 3))}칸`);
    if (adjusts.length > 0) {
      if (!window.confirm(`일부 크기가 3의 배수가 아닙니다.\n저장 시 자동으로 ÷3 조정됩니다(인접+대칭 우선, 그리드 꽉 차면 가장자리 제거):\n\n${adjusts.join('\n')}\n\n계속할까요?`)) return;
    }
    try {
      const res = await apiClient.post('/debug/pattern-create-multi', {
        name: newPatternName.trim(),
        variants,
      });
      setIsCreatingNew(false);
      setVariantGrids({});
      setNewPatternName('');
      await loadPatterns();
      setSelectedPattern(res.data.pattern_index);
    } catch (err) {
      console.error('Create-multi failed:', err);
      window.alert(`저장 실패: ${(err as Error).message}`);
    }
  };

  // 선택된 커스텀 패턴의 저장된 크기 집합 (현재 gridSize에 변형이 없는지 판단용)
  const [savedSizesForSelected, setSavedSizesForSelected] = useState<number[]>([]);

  const loadPreview = async (idx: number) => {
    // 템플릿 선택 상태 초기화 — 우측 패널이 패턴 뷰로 돌아오도록
    setSelectedTemplateId(null);
    setSelectedPattern(idx);
    setIsLoading(true);
    setIsEditing(false);
    try {
      // 커스텀 패턴이면 저장된 크기 목록을 조회 (현재 gridSize는 존중)
      let savedSizes: number[] = [];
      if (idx >= 64) {
        try {
          const cpRes = await apiClient.get('/debug/custom-patterns');
          const allKeys: string[] = Object.keys(cpRes.data.custom_patterns || {});
          savedSizes = allKeys
            .filter(k => k.startsWith(`${idx}_`))
            .map(k => {
              const m = k.match(/^\d+_(\d+)x(\d+)$/);
              return m ? parseInt(m[1]) : NaN;
            })
            .filter(n => !isNaN(n))
            .sort((a, b) => b - a); // 내림차순 (큰 크기 먼저)
          setSavedSizesForSelected(savedSizes);

          // [v15.48] 테스트 레벨의 레이어 크기를 저장된 변형 기준으로 자동 설정
          // → 원본 레벨 재현 (L0=가장 큰 크기, L1=다음, ...)
          if (savedSizes.length > 0) {
            const autoLayers = savedSizes.map(gs => ({ grid_size: gs }));
            setTestLayers(autoLayers);
          }
        } catch {
          setSavedSizesForSelected([]);
        }
      } else {
        setSavedSizesForSelected([]);
      }
      const res = await apiClient.post(`/debug/pattern-preview?pattern_index=${idx}&grid_cols=${gridSize}&grid_rows=${gridSize}`);
      setPreview(res.data);
      // 템플릿 기반으로 편집 그리드 초기화
      const grid = Array.from({ length: gridSize }, (_, y) =>
        Array.from({ length: gridSize }, (_, x) =>
          res.data.template_positions.includes(`${x}_${y}`)
        )
      );
      setEditGrid(grid);
    } catch (err) {
      console.error('Failed to load preview:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // 셀 토글
  const toggleCell = useCallback((x: number, y: number) => {
    setEditGrid(prev => {
      const next = prev.map(r => [...r]);
      next[y][x] = !next[y][x];
      return next;
    });
    setIsEditing(true);
  }, []);

  // 드래그 페인팅
  const handleCellMouseDown = (x: number, y: number) => {
    setIsDragging(true);
    const currentState = editGrid[y][x];
    setDragMode(currentState ? 'remove' : 'add');
    toggleCell(x, y);
  };

  const handleCellMouseEnter = (x: number, y: number) => {
    if (!isDragging) return;
    setEditGrid(prev => {
      const next = prev.map(r => [...r]);
      next[y][x] = dragMode === 'add';
      return next;
    });
    setIsEditing(true);
  };

  const handleMouseUp = () => setIsDragging(false);

  // 편집된 패턴을 positions 배열로 변환
  const getEditedPositions = (): string[] => {
    const positions: string[] = [];
    editGrid.forEach((row, y) => {
      row.forEach((cell, x) => {
        if (cell) positions.push(`${x}_${y}`);
      });
    });
    return positions;
  };

  // 서버에 저장 (레벨 생성 시 자동 적용)
  const [saved, setSaved] = useState(false);
  const savePattern = async () => {
    if (selectedPattern === null) return;
    const positions = getEditedPositions();
    try {
      await apiClient.post('/debug/pattern-save', { pattern_index: selectedPattern, grid_size: gridSize, positions });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      loadPatterns(); // 목록 새로고침
    } catch (err) {
      console.error('Failed to save pattern:', err);
    }
  };

  // 커스텀 패턴 삭제 (현재 그리드 크기만, 원본 복원)
  const deleteCustomPattern = async () => {
    if (selectedPattern === null) return;
    const name = getPatternName(selectedPattern);
    if (!window.confirm(`패턴 #${selectedPattern} "${name}" (${gridSize}×${gridSize}) 커스텀을 삭제하고 원본으로 복원할까요?`)) return;
    try {
      await apiClient.delete(`/debug/pattern-save/${selectedPattern}`, { params: { grid_size: gridSize } });
      loadPreview(selectedPattern); // 원본으로 리로드
      loadPatterns();
      loadConfig();
    } catch (err) {
      console.error('Failed to delete custom pattern:', err);
    }
  };

  // 패턴 완전 삭제 (모든 크기 변형 제거)
  const purgePattern = async () => {
    if (selectedPattern === null) return;
    // [고아 방지] 이 패턴 쓰는 프로덕션 레벨 조회 → 있으면 경고(삭제 시 그 레벨 고아).
    let usageMsg = '';
    try {
      const u = await apiClient.get(`/debug/pattern-usage/${selectedPattern}`);
      const cnt = u.data?.count ?? 0;
      if (cnt > 0) {
        const ex = (u.data?.levels || []).slice(0, 5).map((l: { level_number: number }) => `Lv${l.level_number}`).join(', ');
        usageMsg = `\n\n⚠️ 이 패턴을 쓰는 프로덕션 레벨 ${cnt}개 (예: ${ex})\n삭제하면 그 레벨들이 고아(오참조)됩니다. 재생성 필요.`;
      }
    } catch { /* usage 조회 실패 시 경고 생략 */ }
    if (!window.confirm(`패턴 #${selectedPattern} 의 모든 크기 변형을 완전히 삭제할까요?\n(레벨 생성에서 더 이상 사용되지 않습니다)${usageMsg}`)) return;
    try {
      await apiClient.delete(`/debug/pattern-save/${selectedPattern}`);
      setSelectedPattern(null);
      setPreview(null);
      loadPatterns();
      loadConfig();
    } catch (err) {
      console.error('Failed to purge pattern:', err);
    }
  };

  // 클립보드에 복사
  const copyPattern = () => {
    const positions = getEditedPositions();
    const output = {
      pattern_index: selectedPattern,
      grid_size: gridSize,
      positions_count: positions.length,
      positions,
      visual: editGrid.map(row => row.map(c => c ? '██' : '··').join('')),
    };
    navigator.clipboard.writeText(JSON.stringify(output, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // 원본으로 리셋
  const resetToTemplate = () => {
    if (!preview) return;
    const grid = Array.from({ length: gridSize }, (_, y) =>
      Array.from({ length: gridSize }, (_, x) =>
        preview.template_positions.includes(`${x}_${y}`)
      )
    );
    setEditGrid(grid);
    setIsEditing(false);
  };

  // 편집된 패턴의 통계
  const editedCount = editGrid.flat().filter(Boolean).length;
  const originalCount = preview?.template_count ?? 0;
  const diff = editedCount - originalCount;

  const CELL_COLORS: Record<string, string> = {
    match: 'bg-green-500',
    missing: 'bg-red-500',
    extra: 'bg-yellow-500',
    empty: 'bg-gray-800',
  };

  return (
    <div className="p-4 space-y-4" onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}>
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-lg font-bold text-white">🔧 패턴 디버그 & 편집</h2>
        {/* 번호로 찾기 — 프로덕션 레벨의 pattern_index(#64+) 로 커스텀 패턴 바로 열기 */}
        <div className="flex items-center gap-1">
          <span className="text-[11px] text-gray-400">번호로 찾기</span>
          <input type="number" min={0} placeholder="예: 72"
            className="w-20 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                const idx = parseInt((e.target as HTMLInputElement).value, 10);
                if (!isNaN(idx)) { loadPreview(idx); setCustomCollapsed(false); }
              }
            }} />
          <span className="text-[10px] text-gray-500">Enter</span>
        </div>
      </div>
      <p className="text-sm text-gray-400">
        패턴을 선택 → 비교 확인 → 그리드 클릭/드래그로 편집 → 복사하여 공유
      </p>

      {/* [유닛 조립] 소형 유닛 라이브러리 (unit_assembly 위층 조립에 사용) */}
      <div className="bg-gray-800/50 rounded p-2">
        <button onClick={() => setUnitOpen(o => !o)} className="text-xs text-amber-300 font-medium">
          {unitOpen ? '▼' : '▶'} 🧱 유닛 라이브러리 ({unitLib.length}개) <span className="text-gray-500">— 유닛 조립 위층에 쓰이는 소형 조각(3·6·9칸)</span>
        </button>
        {unitOpen && (
          <div className="mt-2 space-y-3">
            {/* 유닛 에디터 (5×5, ÷3) */}
            <div className="flex items-center gap-3 p-2 bg-amber-900/15 rounded" onMouseLeave={() => setUnitPaint(null)} onMouseUp={() => setUnitPaint(null)}>
              <div className="text-[10px] text-amber-200">유닛 그리기<br /><span className={unitEditCount % 3 === 0 && unitEditCount >= 3 && unitEditCount <= 15 ? 'text-green-400' : 'text-yellow-400'}>{unitEditCount}칸 {unitEditCount % 3 === 0 && unitEditCount >= 3 && unitEditCount <= 15 ? '✓' : unitEditCount > 15 ? '(15칸 이하)' : '(÷3)'}</span></div>
              <div className="inline-block border border-amber-700 rounded select-none">
                {unitEditGrid.map((row, y) => (
                  <div key={y} className="flex">
                    {row.map((cell, x) => (
                      <div key={x}
                        className={`w-5 h-5 border border-gray-900/40 cursor-pointer ${cell ? 'bg-amber-500' : 'bg-gray-800 hover:bg-gray-700'}`}
                        onMouseDown={() => { const nv = !cell; setUnitPaint(nv); setUnitEditGrid(g => g.map((r, yy) => yy === y ? r.map((c, xx) => xx === x ? nv : c) : r)); }}
                        onMouseEnter={(e) => { if (unitPaint !== null && e.buttons === 1) setUnitEditGrid(g => g.map((r, yy) => yy === y ? r.map((c, xx) => xx === x ? unitPaint : c) : r)); }}
                      />
                    ))}
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-1">
                <input value={unitEditName} onChange={e => setUnitEditName(e.target.value)} placeholder="이름"
                  className="w-24 px-1.5 py-0.5 bg-gray-700 border border-gray-600 rounded text-[11px] text-white" />
                <button onClick={randomUnit}
                  className="px-2 py-1 rounded text-[10px] bg-fuchsia-700 hover:bg-fuchsia-600 text-white" title="연결된 랜덤 모양(÷3) 자동 그리기 — 클릭마다 다름">🎲 랜덤</button>
                <button onClick={saveUnit} disabled={unitEditCount % 3 !== 0 || unitEditCount < 3 || unitEditCount > 15}
                  className="px-2 py-1 rounded text-[10px] bg-amber-700 hover:bg-amber-600 text-white disabled:opacity-40">저장</button>
                <button onClick={() => setUnitEditGrid(Array.from({ length: UNIT_EDIT_SIZE }, () => Array(UNIT_EDIT_SIZE).fill(false)))}
                  className="px-2 py-1 rounded text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-200">비움</button>
              </div>
              <button onClick={async () => { await apiClient.post('/debug/unit-reset').catch(() => {}); loadUnits(); }}
                className="ml-auto self-start px-2 py-1 rounded text-[10px] bg-red-900/60 hover:bg-red-800 text-red-200" title="기본 시드로 리셋">기본값 리셋</button>
            </div>
            {/* 유닛 목록 (클릭=편집, ×=삭제) */}
            <div className="flex flex-wrap gap-3">
              {unitLib.map((u, i) => (
                <div key={i} className="flex flex-col items-center relative group">
                  <button onClick={() => editUnit(u)} className="inline-block border border-amber-800/50 rounded hover:ring-1 hover:ring-amber-400" title="클릭=편집">
                    {u.grid.map((row, y) => (
                      <div key={y} className="flex">
                        {row.map((c, x) => (
                          <div key={x} className={`w-4 h-4 border border-gray-900/40 ${c ? 'bg-amber-500' : 'bg-gray-800'}`} />
                        ))}
                      </div>
                    ))}
                  </button>
                  <button onClick={() => deleteUnit(u.name)} className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-700 text-white text-[9px] opacity-0 group-hover:opacity-100" title="삭제">×</button>
                  <div className="text-[9px] text-gray-400 mt-0.5">{u.name} · {u.size}칸 · {Math.round(u.density * 100)}%</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 그리드 크기 */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-400">그리드:</span>
        {[4, 5, 6, 7, 8, 9].map(s => {
          const drawn = isCreatingNew && ((s === gridSize ? editGrid : variantGrids[s]) || []).flat().filter(Boolean).length > 0;
          return (
            <button key={s} onClick={() => (isCreatingNew ? switchCreatingSize(s) : setGridSize(s))}
              className={`px-3 py-1 rounded text-sm ${gridSize === s ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300'} ${drawn ? 'ring-1 ring-green-400' : ''}`}
              title={isCreatingNew && drawn ? `${s}×${s} 그려짐(저장 대상)` : undefined}
            >{s}x{s}{isCreatingNew && drawn ? ' ✓' : ''}</button>
          );
        })}
      </div>

      <div className="flex gap-4">
        {/* 패턴 목록 */}
        <div className="w-[360px] shrink-0 space-y-1 max-h-[80vh] overflow-y-auto pr-1">
          {/* 툴바: 뷰 모드 + 정렬 + 새 패턴 */}
          <div className="flex items-center gap-1 mb-2">
            <button onClick={createNewPattern}
              className="px-2 py-1 rounded bg-green-700 hover:bg-green-600 text-white text-[10px]"
            >+ 추가</button>
            <button onClick={() => setShowSynthModal(true)}
              className="px-2 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white text-[10px]"
              title="절차적으로 ÷3-보장 패턴 생성 후 채택"
            >🧩 절차생성</button>
            <div className="flex-1" />
            <div className="flex gap-0.5">
              <button onClick={() => setViewMode('grid')}
                className={`px-1.5 py-1 rounded text-[10px] ${viewMode === 'grid' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400'}`}
                title="그리드 뷰">▦</button>
              <button onClick={() => setViewMode('list')}
                className={`px-1.5 py-1 rounded text-[10px] ${viewMode === 'list' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400'}`}
                title="리스트 뷰">☰</button>
            </div>
            <select value={sortMode} onChange={e => setSortMode(e.target.value as typeof sortMode)}
              className="px-1 py-1 rounded text-[10px] bg-gray-700 text-gray-300 border-none"
            >
              <option value="order">순서</option>
              <option value="name">이름순</option>
              <option value="count">타일수</option>
            </select>
          </div>

          {(() => {
            // 정렬 적용
            const applySorting = (items: PatternInfo[]) => {
              if (sortMode === 'name') return [...items].sort((a, b) => getPatternName(a.index).localeCompare(getPatternName(b.index)));
              if (sortMode === 'count') return [...items].sort((a, b) => b.count - a.count);
              return items; // order = displayOrder 유지
            };

            const basePatterns = applySorting(sortedPatterns.filter(p => !p.is_custom));
            // 커스텀은 항상 인덱스 번호순 정렬(생성/삭제 후에도 자동 정렬 → #번호로 찾기 쉬움).
            const customPatternsList = sortedPatterns.filter(p => p.is_custom).sort((a, b) => a.index - b.index);

            // 패턴 카드 렌더링 (그리드/리스트 공용)
            const renderPatternCard = (p: PatternInfo, isCyan = false) => {
              const disabled = disabledPatterns.has(p.index);
              const borderColor = isCyan
                ? (selectedPattern === p.index ? 'border-cyan-500 bg-cyan-900/30' : disabled ? 'border-red-800 bg-red-900/20 opacity-50' : 'border-cyan-800 hover:border-cyan-600')
                : (selectedPattern === p.index ? 'border-indigo-500 bg-indigo-900/30' : disabled ? 'border-red-800 bg-red-900/20 opacity-50' : 'border-gray-700 hover:border-gray-500');
              const tileColor = disabled ? 'bg-red-800' : isCyan ? 'bg-cyan-500' : 'bg-blue-500';

              if (viewMode === 'list') {
                return (
                  <div key={p.index} className="relative"
                    draggable onDragStart={() => handleDragStart(p.index)}
                    onDragOver={(e) => handleDragOver(e, p.index)}
                    onDrop={() => handleDrop(p.index)}
                    onDragEnd={() => { setDragIdx(null); setDragOverIdx(null); }}
                  >
                    <button onClick={() => loadPreview(p.index)}
                      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded border text-left ${
                        dragOverIdx === p.index ? 'border-yellow-400 bg-yellow-900/20' : borderColor
                      } ${dragIdx === p.index ? 'opacity-40' : ''}`}
                    >
                      {/* 미니 프리뷰 */}
                      <div className="w-8 h-8 shrink-0">
                        {p.grid.slice(0, 8).map((row, y) => (
                          <div key={y} className="flex">
                            {row.slice(0, 8).map((cell, x) => (
                              <div key={x} className={`flex-1 aspect-square ${cell ? tileColor : 'bg-gray-800'}`} style={{ margin: '0.2px' }} />
                            ))}
                          </div>
                        ))}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-white truncate">
                          {isCyan && '★ '}{getPatternIcon(p.index)} <b className={isCyan ? 'text-cyan-300' : 'text-indigo-300'}>#{p.index}</b>
                          {p.count % 3 !== 0 && <span className="text-red-400 ml-1">!3</span>}
                          {!customForSize.has(p.index) && <span className="text-orange-400 ml-1">⚠</span>}
                        </div>
                        <div className="text-[10px] text-gray-500 truncate">
                          {p.count}t · {p.fill_rate}%
                          {isCyan && getPatternName(p.index) && !getPatternName(p.index).startsWith('ai_') && <span className="text-gray-400 ml-1">· {getPatternName(p.index)}</span>}
                        </div>
                      </div>
                      <button onClick={(e) => { e.stopPropagation(); togglePatternEnabled(p.index); }}
                        className={`w-5 h-5 rounded text-[10px] font-bold shrink-0 ${disabled ? 'bg-red-600 text-white' : 'bg-green-600 text-white'}`}
                      >{disabled ? '✗' : '✓'}</button>
                    </button>
                  </div>
                );
              }

              // 그리드 뷰
              return (
                <div key={p.index} className="relative"
                  draggable onDragStart={() => handleDragStart(p.index)}
                  onDragOver={(e) => handleDragOver(e, p.index)}
                  onDrop={() => handleDrop(p.index)}
                  onDragEnd={() => { setDragIdx(null); setDragOverIdx(null); }}
                >
                  <button onClick={() => loadPreview(p.index)}
                    className={`w-full p-1 rounded border transition-colors ${
                      dragOverIdx === p.index ? 'border-yellow-400 bg-yellow-900/20' : borderColor
                    } ${dragIdx === p.index ? 'opacity-40' : ''}`}
                  >
                    <div className="aspect-square">
                      {p.grid.map((row, y) => (
                        <div key={y} className="flex">
                          {row.map((cell, x) => (
                            <div key={x} className={`flex-1 aspect-square ${cell ? tileColor : 'bg-gray-800'}`} style={{ margin: '0.5px' }} />
                          ))}
                        </div>
                      ))}
                    </div>
                    <div className="text-[10px] text-gray-400 text-center mt-1 truncate cursor-text"
                      title={`${getPatternName(p.index)} 더블클릭=이름변경`}
                      onDoubleClick={(e) => { e.stopPropagation(); renamePattern(p.index); }}
                    >
                      {isCyan && <span className="text-cyan-400">★ </span>}
                      {getPatternIcon(p.index)} {getPatternName(p.index)}
                      {p.count % 3 !== 0 && <span className="text-red-400 ml-0.5">!</span>}
                      {!customForSize.has(p.index) && <span className="text-orange-400 ml-0.5">⚠</span>}
                    </div>
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); togglePatternEnabled(p.index); }}
                    className={`absolute top-0 right-0 w-5 h-5 rounded-bl text-[10px] font-bold ${disabled ? 'bg-red-600 text-white' : 'bg-green-600 text-white'}`}
                  >{disabled ? '✗' : '✓'}</button>
                </div>
              );
            };

            return (<>

          {/* 기본 패턴 — 접기/펴기 */}
          <button onClick={() => setBaseCollapsed(!baseCollapsed)}
            className="w-full flex items-center justify-between px-2 py-2 rounded bg-gray-800 hover:bg-gray-750 mb-1"
          >
            <span className="text-xs text-gray-400 font-medium">{baseCollapsed ? '▶' : '▼'} 기본 패턴 ({basePatterns.length})</span>
            <span className="text-[10px] text-gray-600">{baseCollapsed ? '펼치기' : '접기'}</span>
          </button>
          {!baseCollapsed && <div className={viewMode === 'grid' ? 'grid grid-cols-4 gap-2 mb-3' : 'space-y-1 mb-3'}>
            {basePatterns.map(p => renderPatternCard(p, false))}
          </div>}

          {/* 커스텀 패턴 — 접기/펴기 */}
          {customPatternsList.length > 0 && (
            <>
              <button onClick={() => setCustomCollapsed(!customCollapsed)}
                className="w-full flex items-center justify-between px-2 py-2 rounded bg-gray-800 hover:bg-gray-750 mb-1 mt-1"
              >
                <span className="text-xs text-cyan-400 font-medium">{customCollapsed ? '▶' : '▼'} ★ 커스텀 패턴 ({customPatternsList.length})</span>
                <span className="text-[10px] text-cyan-600">{customCollapsed ? '펼치기' : '접기'}</span>
              </button>
              {!customCollapsed && <div className={viewMode === 'grid' ? 'grid grid-cols-4 gap-2' : 'space-y-1'}>
                {customPatternsList.map(p => renderPatternCard(p, true))}
              </div>}
            </>
          )}
          </>); })()}

          {/* 레벨 템플릿 — 원본 레벨 1:1 재현용 (기믹 포함), 다중 선택 + 일괄 측정 */}
          <button onClick={() => setTemplatesCollapsed(!templatesCollapsed)}
            className="w-full flex items-center justify-between px-2 py-2 rounded bg-gray-800 hover:bg-gray-750 mb-1 mt-3"
          >
            <span className="text-xs text-violet-400 font-medium">
              {templatesCollapsed ? '▶' : '▼'} 📋 레벨 템플릿 ({levelTemplates.length})
              {selectedTemplateIds.size > 0 && <span className="ml-1 text-[10px] text-cyan-300">· {selectedTemplateIds.size}개 선택</span>}
            </span>
            <span className="text-[10px] text-violet-600">{templatesCollapsed ? '펼치기' : '접기'}</span>
          </button>
          {!templatesCollapsed && (
            <div className="space-y-1">
              {levelTemplates.length > 0 && (
                <>
                  <div className="flex items-center gap-1 px-1">
                    <button onClick={() => setSelectedTemplateIds(new Set(levelTemplates.map(t => t.template_id)))}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300">전체</button>
                    <button onClick={() => setSelectedTemplateIds(new Set())}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300">해제</button>
                    <button onClick={() => setSelectedTemplateIds(new Set(levelTemplates.filter(t => t.measured_difficulty == null).map(t => t.template_id)))}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                      title="난이도 측정 안 된 항목만 선택">
                      미측정만
                    </button>
                    <span className="ml-auto text-[9px] text-gray-500">Shift/⌘ 다중 선택</span>
                  </div>

                  {selectedTemplateIds.size >= 1 && (
                    <div className="bg-violet-900/30 border border-violet-700 rounded p-1.5 space-y-1">
                      <div className="text-[10px] text-violet-200">
                        {selectedTemplateIds.size}개 선택 — 일괄 작업
                      </div>
                      <div className="flex gap-1 flex-wrap">
                        <button onClick={batchMeasureTemplates}
                          disabled={batchMeasureProgress !== null}
                          className="flex-1 px-2 py-1 rounded text-[10px] bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
                          title="선택된 템플릿 모두 봇 시뮬(100회)로 난이도 측정 → 메타 저장"
                        >
                          {batchMeasureProgress
                            ? `🔄 ${batchMeasureProgress.done}/${batchMeasureProgress.total}`
                            : '📊 난이도 일괄 측정'}
                        </button>
                        <button onClick={batchDeleteTemplates}
                          disabled={batchMeasureProgress !== null}
                          className="px-2 py-1 rounded text-[10px] bg-red-900/50 hover:bg-red-800 text-red-300 disabled:opacity-50"
                          title="선택된 템플릿 모두 삭제"
                        >🗑️</button>
                      </div>
                      {batchMeasureProgress && (
                        <>
                          <div className="h-1 bg-gray-700 rounded overflow-hidden">
                            <div className="h-full bg-blue-500 transition-all"
                              style={{ width: `${(batchMeasureProgress.done / Math.max(1, batchMeasureProgress.total)) * 100}%` }} />
                          </div>
                          <div className="text-[9px] text-gray-400 truncate">
                            {batchMeasureProgress.current === '완료'
                              ? `완료: 성공 ${batchMeasureProgress.total - batchMeasureProgress.failed.length}개, 실패 ${batchMeasureProgress.failed.length}개`
                              : `현재: ${batchMeasureProgress.current}`}
                          </div>
                          {batchMeasureProgress.failed.length > 0 && (
                            <div className="bg-red-900/30 border border-red-800 rounded p-1 max-h-32 overflow-y-auto">
                              <div className="text-[9px] text-red-300 font-medium mb-0.5">
                                ⚠️ 실패 {batchMeasureProgress.failed.length}개
                              </div>
                              {batchMeasureProgress.failed.map(f => (
                                <div key={f.id} className="text-[8px] text-red-400 truncate" title={f.reason}>
                                  {f.id}: {f.reason}
                                </div>
                              ))}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </>
              )}
              {levelTemplates.length === 0 ? (
                <div className="text-[10px] text-gray-500 px-2 py-3 text-center">
                  저장된 레벨 템플릿이 없습니다.<br />
                  임포트 탭에서 "📋 레벨 템플릿" 버튼으로 저장하세요.
                </div>
              ) : (
                levelTemplates.map((tpl, idx) => {
                  const isPrimary = selectedTemplateId === tpl.template_id;
                  const isMultiSelected = selectedTemplateIds.has(tpl.template_id);
                  const gimmickCount = Object.values(tpl.gimmick_types || {}).reduce((s, n) => s + n, 0);
                  return (
                    <div key={tpl.template_id}
                      className={`px-2 py-1.5 rounded text-[11px] flex items-center justify-between gap-1 ${
                        isPrimary ? 'bg-violet-700 text-white'
                        : isMultiSelected ? 'bg-violet-900/60 text-violet-100 border border-violet-600'
                        : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                      }`}
                    >
                      <button onClick={(ev) => handleTemplateClick(tpl.template_id, idx, ev)}
                        className="flex-1 text-left truncate flex items-center gap-1"
                        title={`${tpl.template_id}\n레이어 ${tpl.layer_count}개, 총 ${tpl.total_tiles}t${gimmickCount ? `, 기믹 ${gimmickCount}개` : ''}${tpl.measured_difficulty != null ? `\n측정 난이도: ${(tpl.measured_difficulty * 100).toFixed(1)} (${tpl.autoplay_grade || '-'})` : '\n난이도 미측정'}\nShift/⌘+Click 다중 선택`}
                      >
                        {isMultiSelected && !isPrimary && <span className="text-[10px] shrink-0">✓</span>}
                        <span className="truncate flex-1">{tpl.name}</span>
                        <span className="text-[9px] text-gray-500 shrink-0">
                          ({tpl.layer_count}L, {tpl.total_tiles}t{gimmickCount > 0 ? `, 🎁${gimmickCount}` : ''})
                        </span>
                        {tpl.measured_difficulty != null ? (
                          <span className="text-[9px] text-blue-300 shrink-0">
                            📊 {(tpl.measured_difficulty * 100).toFixed(0)}
                          </span>
                        ) : (
                          <span className="text-[9px] text-gray-600 shrink-0">📊 -</span>
                        )}
                      </button>
                      <button onClick={() => deleteLevelTemplate(tpl.template_id)}
                        className="text-[10px] px-1 py-0.5 rounded bg-red-900/40 hover:bg-red-800 text-red-300 shrink-0"
                        title="템플릿 삭제"
                      >🗑️</button>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>

        {/* 편집 + 비교 */}
        <div className="flex-1 space-y-4">
          {isLoading ? (
            <div className="flex items-center justify-center h-64 text-gray-400">로딩 중...</div>
          ) : (selectedTemplateId && testResult) ? (
            /* 레벨 템플릿 프리뷰 — 패턴과 별개 렌더 */
            (() => {
              const activeLayers = testResult.layers.filter(lv => lv.count > 0);
              const silhouette = computeSilhouette(activeLayers);
              const tplMeta = levelTemplates.find(t => t.template_id === selectedTemplateId);
              const gimmickStr = tplMeta
                ? Object.entries(tplMeta.gimmick_types || {}).map(([k, v]) => `${k}×${v}`).join(', ')
                : '';
              return (
                <div className="space-y-4">
                  <div className="bg-violet-900/30 border border-violet-700 rounded-lg p-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-medium text-violet-200">
                        📋 {tplMeta?.name || selectedTemplateId}
                      </h3>
                      <div className="flex gap-2 text-[10px] text-gray-400">
                        <span>레이어 {testResult.layers.length}</span>
                        <span>총 {testResult.total_tiles}t
                          {testResult.total_positions !== undefined && testResult.total_positions !== testResult.total_tiles &&
                            ` (${testResult.total_positions} positions)`
                          }
                        </span>
                        {testResult.total_tiles % 3 === 0
                          ? <span className="text-green-400">3✓</span>
                          : <span className="text-red-400">!3 ({testResult.total_tiles % 3})</span>}
                      </div>
                    </div>
                    {gimmickStr && (
                      <div className="text-[10px] text-violet-300 mt-1">🎁 기믹: {gimmickStr}</div>
                    )}
                    {tplMeta && (
                      <div className="text-[9px] text-gray-500 mt-0.5">
                        ingame {tplMeta.ingame_cols.map((c, i) => `L${i} ${c}×${tplMeta.ingame_rows[i]}`).join(' / ')}
                      </div>
                    )}
                  </div>

                  {/* 레이어별 그리드 — 기믹/스택 오버레이 포함 */}
                  <div className="flex flex-wrap gap-3">
                    {activeLayers.map(lv => (
                      <div key={lv.layer}>
                        <div className="text-[10px] text-gray-400 mb-1">
                          <span className="inline-block w-2 h-2 rounded-sm mr-1" style={{ backgroundColor: LAYER_COLORS[lv.layer] }} />
                          L{lv.layer} (
                          {lv.count}t
                          {lv.position_count !== undefined && lv.position_count !== lv.count && ` / ${lv.position_count} pos`},
                          {' '}{lv.grid_cols}x{lv.grid_rows})
                          {lv.count % 3 !== 0 && <span className="text-red-400 ml-1">!3</span>}
                        </div>
                        <div className="inline-block border border-gray-700 rounded">
                          {lv.grid.map((row, y) => (
                            <div key={y} className="flex">
                              {row.map((cell, x) => {
                                const pos = `${x}_${y}`;
                                const detail = cell && lv.tiles_detail ? lv.tiles_detail[pos] : undefined;
                                const g = detail ? describeTile(detail) : { icon: '', badge: '', label: '', borderClass: '' };
                                return (
                                  <div key={x}
                                    className={`relative w-6 h-6 flex items-center justify-center ${g.borderClass}`}
                                    style={{
                                      margin: '0.5px',
                                      backgroundColor: cell ? LAYER_COLORS[lv.layer] : '#111827',
                                    }}
                                    title={detail ? `${pos}: ${g.label || 'basic'}` : ''}
                                  >
                                    {g.icon && (
                                      <span className="text-[9px] leading-none select-none" style={{ textShadow: '0 0 2px rgba(0,0,0,0.9)' }}>
                                        {g.icon}
                                      </span>
                                    )}
                                    {g.badge && (
                                      <span className="absolute -bottom-0.5 -right-0.5 text-[7px] font-bold text-white bg-black/80 rounded px-0.5 leading-none">
                                        {g.badge}
                                      </span>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* 인게임 실루엣 */}
                  <div>
                    <div className="text-[10px] text-gray-400 mb-1">
                      인게임 실루엣 ({silhouette.width / 2}x{silhouette.height / 2} 타일, 0.5px 오프셋 반영)
                    </div>
                    <div className="inline-block border border-gray-600 rounded bg-gray-950 p-1">
                      {silhouette.grid.map((row, y) => (
                        <div key={y} className="flex">
                          {row.map((cell, x) => {
                            const hasLayers = cell.layers.length > 0;
                            const topLayer = hasLayers ? cell.layers[cell.layers.length - 1] : -1;
                            return (
                              <div key={x} className="w-2 h-2"
                                title={hasLayers ? `L${cell.layers.join('+')}` : ''}
                                style={{
                                  backgroundColor: hasLayers ? (LAYER_COLORS[topLayer] || '#6b7280') : 'transparent',
                                  opacity: hasLayers ? 0.8 : 0,
                                }}
                              />
                            );
                          })}
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2 mt-1 text-[9px] text-gray-500">
                      {activeLayers.map(lv => (
                        <span key={lv.layer} className="flex items-center gap-0.5">
                          <span className="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: LAYER_COLORS[lv.layer] }} />
                          L{lv.layer}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* 인게임 GameBoard 프리뷰 */}
                  {previewTiles.length > 0 && (
                    <div>
                      <div className="text-[10px] text-gray-400 mb-1">
                        인게임 프리뷰 ({previewTiles.length}t)
                      </div>
                      <div className="bg-gray-950 rounded border border-gray-600 p-2 inline-block">
                        <GameBoard
                          tiles={previewTiles}
                          onTileClick={() => { /* no-op */ }}
                          tileSize={32}
                          showStats={false}
                          fixedGridSize={7}
                        />
                      </div>
                    </div>
                  )}

                  {/* 측정 실패 알림 */}
                  {lastMeasureError && (
                    <div className="bg-red-900/40 border border-red-700 rounded p-2 text-xs text-red-300 flex items-start justify-between gap-2">
                      <div className="flex-1">
                        <div className="font-medium">⚠️ 난이도 측정 실패</div>
                        <div className="text-[10px] text-red-400 mt-0.5 break-all">{lastMeasureError}</div>
                      </div>
                      <button onClick={() => setLastMeasureError(null)}
                        className="text-[10px] text-red-400 hover:text-red-200">✕</button>
                    </div>
                  )}
                  {/* 측정 난이도 표시 */}
                  {tplMeta?.measured_difficulty != null && (
                    <div className="bg-blue-900/30 border border-blue-700 rounded-lg p-2 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-blue-200 font-medium">
                          📊 측정 난이도: {(tplMeta.measured_difficulty * 100).toFixed(1)}
                          {tplMeta.autoplay_grade && <span className="ml-1 text-blue-300">({tplMeta.autoplay_grade})</span>}
                        </span>
                        <span className="text-[9px] text-gray-500">
                          {tplMeta.difficulty_measured_at
                            ? new Date(tplMeta.difficulty_measured_at).toLocaleString()
                            : ''}
                        </span>
                      </div>
                      {tplMeta.bot_clear_rates && (
                        <div className="flex gap-2 flex-wrap text-[10px]">
                          {Object.entries(tplMeta.bot_clear_rates).map(([bot, rate]) => (
                            <span key={bot} className="text-gray-400">
                              {bot}: <span className="text-white">{(rate * 100).toFixed(0)}%</span>
                            </span>
                          ))}
                        </div>
                      )}
                      {tplMeta.static_score != null && (
                        <div className="text-[10px] text-gray-400">
                          정적: {tplMeta.static_score.toFixed(1)} ({tplMeta.static_grade || '-'})
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex gap-2 flex-wrap">
                    <button onClick={() => { setSelectedTemplateId(null); setTestResult(null); }}
                      className="px-3 py-1.5 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-300"
                    >
                      닫기
                    </button>
                    <button onClick={() => measureTemplateDifficulty(selectedTemplateId!)}
                      disabled={measuringDifficulty === selectedTemplateId}
                      className="px-3 py-1.5 rounded text-xs bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
                      title="봇 시뮬레이션(100회 × 5봇)으로 난이도 측정 후 템플릿 메타에 저장. 프로덕션 자동 배치 시 사용됨"
                    >
                      {measuringDifficulty === selectedTemplateId
                        ? '🔄 측정 중... (최대 5분)'
                        : (tplMeta?.measured_difficulty != null ? '📊 난이도 재측정' : '📊 난이도 측정')}
                    </button>
                    <button onClick={() => deleteLevelTemplate(selectedTemplateId!)}
                      className="px-3 py-1.5 rounded text-xs bg-red-900/50 hover:bg-red-800 text-red-300"
                    >
                      🗑️ 템플릿 삭제
                    </button>
                  </div>
                </div>
              );
            })()
          ) : preview ? (
            <>
              {/* 비교 통계 */}
              <div className="bg-gray-800 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-medium text-white cursor-pointer flex items-center gap-2" onDoubleClick={() => renamePattern(preview.pattern_index)}>
                    <span>{getPatternIcon(preview.pattern_index)} {getPatternName(preview.pattern_index)}</span>
                    {preview.pattern_index >= 64 && savedSizesForSelected.length > 0 && !savedSizesForSelected.includes(gridSize) && (
                      <span
                        className="px-2 py-0.5 rounded text-[10px] bg-yellow-900/60 text-yellow-300 border border-yellow-700 cursor-help"
                        title={`이 패턴은 ${savedSizesForSelected.sort((a,b)=>a-b).map(s=>`${s}×${s}`).join(', ')}로만 저장되어 있습니다. 현재 ${gridSize}×${gridSize} 표시는 가장 가까운 크기의 좌표를 그리드 범위로 잘라낸 결과라 모양이 깨질 수 있습니다. 저장 버튼으로 ${gridSize}×${gridSize} 변형을 추가 저장하거나, 상단 그리드 크기를 ${savedSizesForSelected[0]}로 바꾸세요.`}
                      >
                        ⚠️ {gridSize}×{gridSize} 변형 없음 (저장됨: {savedSizesForSelected.sort((a,b)=>a-b).map(s=>`${s}×${s}`).join(', ')})
                      </span>
                    )}
                  </h3>
                  <div className="flex gap-2 text-xs">
                    <span className="text-green-400">■ 일치</span>
                    <span className="text-red-400">■ 누락</span>
                    <span className="text-yellow-400">■ 추가</span>
                  </div>
                </div>
                <div className="grid grid-cols-5 gap-2 text-center text-xs">
                  <div>
                    <div className="text-gray-500">템플릿</div>
                    <div className="text-blue-400 font-bold">{preview.template_count}</div>
                    {preview.template_count % 3 !== 0 && <div className="text-red-400 text-[9px]">!3</div>}
                  </div>
                  <div>
                    <div className="text-gray-500">실제</div>
                    <div className="text-white font-bold">{preview.actual_count}</div>
                    {preview.actual_count % 3 !== 0 && <div className="text-red-400 text-[9px]">!3</div>}
                  </div>
                  <div><div className="text-gray-500">누락</div><div className={`font-bold ${preview.missing_count ? 'text-red-400' : 'text-green-400'}`}>{preview.missing_count}</div></div>
                  <div><div className="text-gray-500">추가</div><div className={`font-bold ${preview.extra_count ? 'text-yellow-400' : 'text-green-400'}`}>{preview.extra_count}</div></div>
                  <div><div className="text-gray-500">일치율</div><div className={`font-bold ${preview.match_rate >= 100 ? 'text-green-400' : 'text-red-400'}`}>{preview.match_rate}%</div></div>
                </div>
              </div>

              {/* 두 그리드 나란히: 비교뷰 + 편집뷰 */}
              <div className="flex gap-4">
                {/* 비교 그리드 (읽기 전용) — 현재 코드의 생성 결과 */}
                <div>
                  <h4 className="text-xs text-gray-400 mb-1">현재 생성 결과 (코드 기반)</h4>
                  <p className="text-[10px] text-gray-500 mb-1">초록=정상 / 빨강=누락(잘림) / 노랑=의도 밖 추가</p>
                  <div className="inline-block border border-gray-700 rounded">
                    {preview.grid.map((row, y) => (
                      <div key={y} className="flex">
                        {row.map((cell, x) => (
                          <div key={x}
                            className={`w-7 h-7 border border-gray-900/50 flex items-center justify-center text-[8px] ${CELL_COLORS[cell]}`}
                            title={`${x},${y}: ${cell}`}
                          >
                            {cell === 'missing' ? '✗' : cell === 'extra' ? '+' : ''}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>

                {/* 편집 그리드 — 원하는 모양으로 수정 후 저장 */}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <h4 className="text-xs text-gray-400">편집 (클릭/드래그로 수정 → 저장)</h4>
                    {isEditing && (
                      <span className="text-[10px] text-yellow-400">
                        {diff > 0 ? `+${diff}` : diff < 0 ? `${diff}` : '±0'}개 변경
                      </span>
                    )}
                  </div>
                  <div className="inline-block border border-gray-700 rounded select-none"
                    onMouseLeave={() => setIsDragging(false)}
                  >
                    {editGrid.map((row, y) => (
                      <div key={y} className="flex">
                        {row.map((cell, x) => (
                          <div key={x}
                            className={`w-7 h-7 border border-gray-900/50 cursor-pointer transition-colors ${
                              cell ? 'bg-blue-500 hover:bg-blue-400' : 'bg-gray-800 hover:bg-gray-700'
                            }`}
                            onMouseDown={() => handleCellMouseDown(x, y)}
                            onMouseEnter={() => handleCellMouseEnter(x, y)}
                          />
                        ))}
                      </div>
                    ))}
                  </div>
                  <div className="text-[10px] text-gray-500 mt-1">
                    {editedCount}개 타일 ({(editedCount / (gridSize * gridSize) * 100).toFixed(0)}% fill)
                  </div>
                </div>
              </div>

              {/* 액션 버튼 */}
              <div className="flex gap-2">
                <button onClick={savePattern}
                  className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                    saved ? 'bg-green-600 text-white' : 'bg-blue-600 hover:bg-blue-500 text-white'
                  }`}
                >
                  {saved ? '✓ 저장됨!' : '💾 저장 (레벨 생성에 적용)'}
                </button>
                <button onClick={copyPattern}
                  className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                    copied ? 'bg-green-600 text-white' : 'bg-gray-600 hover:bg-gray-500 text-white'
                  }`}
                >
                  {copied ? '✓ 복사됨!' : '📋 복사'}
                </button>
                {isEditing && (
                  <button onClick={resetToTemplate}
                    className="px-4 py-2 rounded text-sm bg-gray-700 hover:bg-gray-600 text-gray-300"
                  >
                    리셋
                  </button>
                )}
                <button onClick={deleteCustomPattern}
                  className="px-4 py-2 rounded text-sm bg-red-900/50 hover:bg-red-800 text-red-300"
                  title="현재 크기의 커스텀 수정만 삭제하고 원본으로 복원"
                >
                  커스텀 삭제
                </button>
                <button onClick={purgePattern}
                  className="px-4 py-2 rounded text-sm bg-red-700 hover:bg-red-600 text-white"
                  title="이 패턴의 모든 크기 변형을 완전히 삭제"
                >
                  🗑️ 패턴 완전 삭제
                </button>
              </div>

              {/* 누락 상세 */}
              {preview.missing.length > 0 && (
                <div className="bg-red-900/20 rounded p-2 text-xs">
                  <span className="text-red-400 font-medium">누락: </span>
                  <span className="text-red-300 font-mono">{preview.missing.join(', ')}</span>
                </div>
              )}

              {/* 실루엣 미리보기 */}
              <div className="bg-gray-800 rounded-lg p-3 space-y-3">
                <h4 className="text-sm font-medium text-white">레이어 쌓기 실루엣</h4>

                {/* 설정 */}
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  {/* 모드 */}
                  <div className="flex gap-1">
                    <button onClick={() => setSilMode('production')}
                      className={`px-2 py-1 rounded ${silMode === 'production' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300'}`}
                    >프로덕션</button>
                    <button onClick={() => setSilMode('custom')}
                      className={`px-2 py-1 rounded ${silMode === 'custom' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300'}`}
                    >커스텀</button>
                  </div>

                  {/* 레이어 수 */}
                  <div className="flex items-center gap-1">
                    <span className="text-gray-500">레이어:</span>
                    {[2, 3, 4, 5].map(n => (
                      <button key={n} onClick={() => {
                        setSilLayerCount(n);
                        setSilCustomSizes(prev => {
                          const next = [...prev];
                          while (next.length < n) next.push(Math.max(4, (next[next.length - 1] || 8) - 1));
                          return next;
                        });
                      }}
                        className={`w-6 h-6 rounded text-center ${silLayerCount === n ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400'}`}
                      >{n}</button>
                    ))}
                  </div>
                </div>

                {/* 커스텀 모드: 개별 레이어 크기 */}
                {silMode === 'custom' && (
                  <div className="space-y-1">
                    {Array.from({ length: silLayerCount }, (_, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: LAYER_COLORS[i] }} />
                        <span className="text-gray-500 w-6">L{i}</span>
                        <input type="range" min={4} max={9} value={silCustomSizes[i] || 8}
                          onChange={e => setSilCustomSizes(prev => {
                            const next = [...prev];
                            next[i] = Number(e.target.value);
                            return next;
                          })}
                          className="flex-1 h-1"
                        />
                        <span className="text-white w-10">{silCustomSizes[i] || 8}×{silCustomSizes[i] || 8}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* 실루엣 그리드 */}
                {silhouetteData && (
                  <div className="flex flex-wrap gap-4">
                    {silhouetteData.configs.map((cfg, idx) => (
                      <div key={idx}>
                        <div className="text-[10px] text-gray-400 mb-1">{cfg.label}</div>
                        <div className="inline-block border border-gray-600 rounded bg-gray-950 p-1">
                          {cfg.grid.map((row, y) => (
                            <div key={y} className="flex">
                              {row.map((cell, x) => {
                                const has = cell.layers.length > 0;
                                const top = has ? cell.layers[cell.layers.length - 1] : -1;
                                return (
                                  <div key={x} className="w-2 h-2" style={{
                                    backgroundColor: has ? LAYER_COLORS[top] || '#6b7280' : 'transparent',
                                    opacity: has ? 0.8 : 0,
                                  }} />
                                );
                              })}
                            </div>
                          ))}
                        </div>
                        <div className="flex gap-1 mt-1">
                          {cfg.layers.map(l => (
                            <span key={l.layer} className="text-[9px] text-gray-500">
                              <span className="inline-block w-2 h-2 rounded-sm mr-0.5" style={{ backgroundColor: LAYER_COLORS[l.layer] }} />
                              {l.size}×{l.size}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 테스트 레벨 생성 */}
              <div className="bg-gray-800 rounded-lg p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-medium text-white">테스트 레벨 생성</h4>
                  <button onClick={() => setTestMode(!testMode)} className="text-xs text-indigo-400 hover:text-indigo-300">
                    {testMode ? '접기' : '펼치기'}
                  </button>
                </div>
                {testMode && (
                  <div className="space-y-3">
                    {/* 렌더 프레임 크기 */}
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-400 shrink-0">렌더 프레임:</span>
                      <div className="flex gap-1">
                        {[0, 7, 8, 9, 10].map(sz => (
                          <button key={sz} onClick={() => setRenderBaseSize(sz)}
                            className={`px-2 py-0.5 text-[10px] rounded ${
                              renderBaseSize === sz ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                            }`}
                            title={sz === 0 ? '자동 (max(8, 최대 레이어))' : `짝수 레이어 ${sz}×${sz}, 홀수 레이어 ${sz-1}×${sz-1}`}
                          >
                            {sz === 0 ? 'AUTO' : `${sz}`}
                          </button>
                        ))}
                      </div>
                      <span className="text-[10px] text-gray-500">
                        {renderBaseSize === 0 ? '자동' : `짝 ${renderBaseSize}, 홀 ${renderBaseSize - 1}`} → 소형 패턴 중앙 배치
                      </span>
                    </div>

                    {/* 레이어 설정 */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-400">레이어 ({testLayers.length}개)</span>
                        <div className="flex gap-1">
                          {savedSizesForSelected.length > 0 && (
                            <button
                              onClick={() => setTestLayers(
                                [...savedSizesForSelected].sort((a, b) => b - a).map(gs => ({ grid_size: gs }))
                              )}
                              className="px-2 py-0.5 text-[10px] bg-emerald-700 rounded hover:bg-emerald-600 text-white"
                              title="저장된 변형 크기대로 레이어를 재설정 (원본 레벨 재현)"
                            >
                              원본 크기
                            </button>
                          )}
                          <button onClick={() => setTestLayers(prev => [...prev, { grid_size: Math.max(4, (prev[prev.length-1]?.grid_size || 8) - 1) }])}
                            className="px-2 py-0.5 text-xs bg-gray-700 rounded hover:bg-gray-600 text-gray-300" disabled={testLayers.length >= 10}>+</button>
                          <button onClick={() => setTestLayers(prev => prev.slice(0, -1))}
                            className="px-2 py-0.5 text-xs bg-gray-700 rounded hover:bg-gray-600 text-gray-300" disabled={testLayers.length <= 1}>-</button>
                        </div>
                      </div>
                      {testLayers.map((layer, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <span className="text-xs text-gray-500 w-8">L{i}:</span>
                          {/* 패턴 선택 */}
                          <select
                            value={layer.pattern_index ?? ''}
                            onChange={e => setTestLayers(prev => prev.map((l, j) =>
                              j === i ? { ...l, pattern_index: e.target.value ? Number(e.target.value) : undefined } : l
                            ))}
                            className="w-20 px-1 py-0.5 text-[10px] bg-gray-700 border border-gray-600 rounded text-white"
                            title="레이어 패턴 (비워두면 기본 패턴)"
                          >
                            <option value="">기본</option>
                            {sortedPatterns.map(p => (
                              <option key={p.index} value={p.index}>
                                {getPatternIcon(p.index)} {getPatternName(p.index)}
                              </option>
                            ))}
                          </select>
                          {/* 크기 슬라이더 — 선택 패턴의 저장 변형 최댓값까지 허용 */}
                          <input type="range" min={2}
                            max={Math.max(10, ...savedSizesForSelected)}
                            value={layer.grid_size}
                            onChange={e => setTestLayers(prev => prev.map((l, j) => j === i ? { ...l, grid_size: Number(e.target.value) } : l))}
                            className="flex-1 h-1"
                          />
                          <span className="text-xs text-white w-10">{layer.grid_size}x{layer.grid_size}</span>
                        </div>
                      ))}
                    </div>
                    <button onClick={generateTestLevel} disabled={isGeneratingTest}
                      className="w-full px-3 py-2 rounded text-sm bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-50"
                    >
                      {isGeneratingTest ? '생성 중...' : '테스트 레벨 생성'}
                    </button>

                    {/* 결과: 레이어별 그리드 + 합산 실루엣 */}
                    {testResult && (() => {
                      const activeLayers = testResult.layers.filter(lv => lv.count > 0);
                      const silhouette = computeSilhouette(activeLayers);
                      return (
                        <div className="space-y-3">
                          <div className="text-xs text-gray-400">
                            총 {testResult.total_tiles}t
                            {testResult.total_tiles % 3 !== 0 && (
                              <span className="text-red-400 font-bold ml-1">
                                (3의 배수 아님! 나머지={testResult.total_tiles % 3})
                              </span>
                            )}
                            {testResult.total_tiles % 3 === 0 && (
                              <span className="text-green-400 ml-1">3✓</span>
                            )}
                          </div>

                          {/* 레이어별 개별 그리드 */}
                          <div className="flex flex-wrap gap-3">
                            {activeLayers.map(lv => (
                              <div key={lv.layer}>
                                <div className="text-[10px] text-gray-400 mb-1">
                                  <span className="inline-block w-2 h-2 rounded-sm mr-1" style={{ backgroundColor: LAYER_COLORS[lv.layer] }} />
                                  L{lv.layer} ({lv.count}t, {lv.grid_cols}x{lv.grid_rows})
                                  {lv.count % 3 !== 0 && <span className="text-red-400 ml-1">!3</span>}
                                </div>
                                <div className="inline-block border border-gray-700 rounded">
                                  {lv.grid.map((row, y) => (
                                    <div key={y} className="flex">
                                      {row.map((cell, x) => (
                                        <div key={x} className="w-4 h-4" style={{
                                          margin: '0.5px',
                                          backgroundColor: cell ? LAYER_COLORS[lv.layer] : '#111827',
                                        }} />
                                      ))}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>

                          {/* 합산 실루엣 (0.5 오프셋 반영) */}
                          <div>
                            <div className="text-[10px] text-gray-400 mb-1">
                              인게임 실루엣 ({silhouette.width/2}x{silhouette.height/2} 타일, 0.5px 오프셋 반영)
                            </div>
                            <div className="inline-block border border-gray-600 rounded bg-gray-950 p-1">
                              {silhouette.grid.map((row, y) => (
                                <div key={y} className="flex">
                                  {row.map((cell, x) => {
                                    const hasLayers = cell.layers.length > 0;
                                    const topLayer = hasLayers ? cell.layers[cell.layers.length - 1] : -1;
                                    return (
                                      <div key={x} className="w-2 h-2" title={
                                        hasLayers ? `L${cell.layers.join('+')}`  : ''
                                      } style={{
                                        backgroundColor: hasLayers
                                          ? LAYER_COLORS[topLayer] || '#6b7280'
                                          : 'transparent',
                                        opacity: hasLayers ? 0.8 : 0,
                                      }} />
                                    );
                                  })}
                                </div>
                              ))}
                            </div>
                            <div className="flex gap-2 mt-1 text-[9px] text-gray-500">
                              {activeLayers.map(lv => (
                                <span key={lv.layer} className="flex items-center gap-0.5">
                                  <span className="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: LAYER_COLORS[lv.layer] }} />
                                  L{lv.layer}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                      );
                    })()}

                    {/* 실제 게임 프리뷰 (GameBoard) */}
                    {previewTiles.length > 0 && (
                      <div>
                        <div className="text-[10px] text-gray-400 mb-1">
                          인게임 프리뷰 ({previewTiles.length}t)
                        </div>
                        <div className="bg-gray-950 rounded border border-gray-600 p-2 inline-block">
                          <GameBoard
                            tiles={previewTiles}
                            onTileClick={() => {}}
                            tileSize={32}
                            showStats={false}
                            fixedGridSize={7}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          ) : isCreatingNew ? (
            <div className="space-y-4">
              <div className="bg-green-900/20 rounded-lg p-3 space-y-2">
                <h3 className="text-sm font-medium text-green-400">새 패턴 만들기 (크기별로 따로 그리기)</h3>
                <p className="text-xs text-gray-400">
                  ① 이름 입력 → ② 상단 그리드 크기 버튼으로 크기 전환하며 각 크기마다 모양 그림 → ③ 저장 (그린 크기만 저장됨)
                </p>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-10">이름</span>
                  <input
                    type="text" value={newPatternName}
                    onChange={e => setNewPatternName(e.target.value)}
                    placeholder="예: 하트, 왕관, 고양이"
                    className="flex-1 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                  />
                </div>
                {/* 필수 크기 현황 (5·6·7 반드시) */}
                <div className="flex items-center gap-1 flex-wrap text-[10px]">
                  <span className="text-gray-500">필수(5·6·7):</span>
                  {REQUIRED_PATTERN_SIZES.map(s => {
                    const cnt = ((s === gridSize ? editGrid : variantGrids[s]) || []).flat().filter(Boolean).length;
                    const ok = cnt >= 3;
                    const div3 = cnt % 3 === 0;
                    const adj = ok && !div3 ? cnt + (3 - (cnt % 3)) : cnt;   // 저장 시 자동 ÷3(추가 우선)
                    const cls = !ok ? 'bg-red-800 text-red-200' : (div3 ? 'bg-green-700 text-green-100' : 'bg-amber-700 text-amber-100');
                    return <span key={s} className={`px-1.5 py-0.5 rounded ${cls}`}
                      title={ok && !div3 ? `3의 배수 아님 → 저장 시 ${cnt}→${adj}칸 자동조정` : undefined}>
                      {!ok ? '✗' : (div3 ? '✓' : '≈')} {s}×{s}{ok ? ` (${cnt}${div3 ? '' : `→${adj}`})` : ''}</span>;
                  })}
                </div>
                {/* 선택 크기(4·8·9) 현황 */}
                <div className="flex items-center gap-1 flex-wrap text-[10px]">
                  <span className="text-gray-500">선택:</span>
                  {[4, 8, 9].map(s => {
                    const cnt = ((s === gridSize ? editGrid : variantGrids[s]) || []).flat().filter(Boolean).length;
                    if (cnt < 3) return null;
                    return <span key={s} className="px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">{s}×{s} ({cnt})</span>;
                  })}
                  <span className="text-gray-600">(8·9는 프로덕션 미사용)</span>
                </div>
              </div>
              <div>
                <h4 className="text-xs text-gray-400 mb-1">편집: {gridSize}×{gridSize} ({editedCount}개 타일)</h4>
                <div className="inline-block border border-gray-700 rounded select-none"
                  onMouseLeave={() => setIsDragging(false)}
                >
                  {editGrid.map((row, y) => (
                    <div key={y} className="flex">
                      {row.map((cell, x) => (
                        <div key={x}
                          className={`w-7 h-7 border border-gray-900/50 cursor-pointer transition-colors ${
                            cell ? 'bg-green-500 hover:bg-green-400' : 'bg-gray-800 hover:bg-gray-700'
                          }`}
                          onMouseDown={() => handleCellMouseDown(x, y)}
                          onMouseEnter={() => handleCellMouseEnter(x, y)}
                        />
                      ))}
                    </div>
                  ))}
                </div>
              </div>
              <div className="flex gap-2">
                {(() => {
                  const reqMet = REQUIRED_PATTERN_SIZES.every(s =>
                    ((s === gridSize ? editGrid : variantGrids[s]) || []).flat().filter(Boolean).length >= 3);
                  return (
                    <button onClick={saveMultiSizePattern} disabled={!reqMet}
                      title={reqMet ? '5·6·7 전부 그려짐 → 저장' : '필수 크기 5×5·6×6·7×7 를 모두 그려야 저장됨'}
                      className="px-4 py-2 rounded text-sm bg-green-600 hover:bg-green-500 text-white disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      + 새 패턴으로 저장 {reqMet ? '(그린 크기 전부)' : '(5·6·7 필수)'}
                    </button>
                  );
                })()}
                <button onClick={() => { setIsCreatingNew(false); setVariantGrids({}); setNewPatternName(''); }}
                  className="px-4 py-2 rounded text-sm bg-gray-700 hover:bg-gray-600 text-gray-300"
                >
                  취소
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-500">
              왼쪽에서 패턴을 선택하세요
            </div>
          )}
        </div>
      </div>

      {showSynthModal && (
        <PatternSynthModal
          onClose={() => setShowSynthModal(false)}
          onAccepted={() => loadPatterns()}
        />
      )}
    </div>
  );
}

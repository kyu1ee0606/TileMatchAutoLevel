/**
 * PatternImportPanel
 * JSON 파일 드래그&드롭으로 기존 레벨에서 패턴 추출 → 커스텀 패턴 저장
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import apiClient from '../api/client';
import type { LevelMetadata } from '../types';

interface TileDetail {
  tileType: string;
  attribute: string;
  extra: unknown;
  effectiveCount: number;
}

interface ExtractedLayer {
  layer: number;
  gridCols: number;
  gridRows: number;
  tileCount: number;          // 위치 수 (positions.length)
  effectiveCount: number;     // stack 전개 후 실효 타일 수
  positions: string[];        // 정규화된 좌표 (0,0 원점, 중앙 패딩)
  grid: number[][];
  tilesDetail: Record<string, TileDetail>;  // 정규화 좌표 → 기믹/스택 정보
  gimmickCount: number;       // 기믹(non-t0) + attribute 있는 타일 수
  // 인게임 컨텍스트
  ingameCol: number;
  ingameRow: number;
  ingameOrigin: [number, number];
  ingameBbox: [number, number];
}

// 타일 1개의 실효 카운트 — stack_s는 extra[0], 그 외 1
function tileEffectiveCount(tile: unknown): number {
  if (!Array.isArray(tile) || tile.length < 1) return 1;
  if (tile[0] === 'stack_s') {
    const extra = tile[2];
    if (Array.isArray(extra) && extra.length >= 1) {
      const n = Number(extra[0]);
      if (!isNaN(n) && n > 0) return n;
    }
  }
  return 1;
}

// 기믹 시각 표현 매핑
const GIMMICK_ICONS: Record<string, string> = {
  chain: '⛓', link_s: '🔗', link_s_n: '🔗',
  curtain_close: '🎭', curtain_open: '🎭',
  frog: '🐸', ice_1: '🧊', ice_2: '🧊', glass: '🥂', locked: '🔒',
};
const TILE_TYPE_ICONS: Record<string, string> = {
  craft_s: '🎯', stack_s: '📚', bomb: '💣', key: '🔑',
};

function describeTile(d: TileDetail): { icon: string; badge: string; label: string; ring: string } {
  const { tileType, attribute, extra } = d;
  const hasGimmickType = tileType && tileType !== 't0' && !/^t\d+$/.test(tileType);
  const hasAttr = !!attribute;
  if (!hasGimmickType && !hasAttr) return { icon: '', badge: '', label: '', ring: '' };
  let icon = '';
  const labelParts: string[] = [];
  let badge = '';
  if (hasGimmickType) {
    icon = TILE_TYPE_ICONS[tileType] || '⭐';
    labelParts.push(tileType);
  }
  if (hasAttr) {
    if (!icon) icon = GIMMICK_ICONS[attribute] || '⚡';
    labelParts.push(attribute);
  }
  if (Array.isArray(extra) && extra.length > 0) {
    const n = extra[0];
    if (typeof n === 'number' || /^\d+$/.test(String(n))) {
      badge = String(n);
      labelParts.push(`×${n}`);
    }
  }
  return {
    icon, badge,
    label: labelParts.join(' '),
    ring: hasGimmickType ? 'ring-2 ring-yellow-400' : 'ring-1 ring-amber-500/60',
  };
}

interface ImportResult {
  fileName: string;
  levelNumber?: number;
  layers: ExtractedLayer[];
  patternIndex?: number;
  // [v15.50] 레벨 템플릿 저장용 — 원본 level_json (기믹 포함)
  rawLevelJson?: Record<string, unknown>;
}

// [v15.47] localStorage 기반 임포트 결과 캐시
const CACHE_VERSION = 1;
const CACHE_TTL_MS = 7 * 24 * 3600 * 1000; // 7일
const cacheKey = (projectId: string) => `pattern_import_cache_v${CACHE_VERSION}_${projectId}`;

interface CachePayload {
  version: number;
  projectId: string;
  fetchedAt: number;
  results: ImportResult[];
}

function loadCachedResults(projectId: string): { results: ImportResult[]; fetchedAt: number } | null {
  if (!projectId) return null;
  try {
    const raw = localStorage.getItem(cacheKey(projectId));
    if (!raw) return null;
    const data = JSON.parse(raw) as CachePayload;
    if (data.version !== CACHE_VERSION) {
      localStorage.removeItem(cacheKey(projectId));
      return null;
    }
    if (Date.now() - data.fetchedAt > CACHE_TTL_MS) {
      localStorage.removeItem(cacheKey(projectId));
      return null;
    }
    if (!Array.isArray(data.results)) return null;
    return { results: data.results, fetchedAt: data.fetchedAt };
  } catch {
    try { localStorage.removeItem(cacheKey(projectId)); } catch { /* ignore */ }
    return null;
  }
}

function saveCachedResults(projectId: string, results: ImportResult[], fetchedAt?: number): void {
  if (!projectId) return;
  try {
    const payload: CachePayload = {
      version: CACHE_VERSION,
      projectId,
      fetchedAt: fetchedAt ?? Date.now(),
      results,
    };
    localStorage.setItem(cacheKey(projectId), JSON.stringify(payload));
  } catch (err) {
    console.warn('[PatternImport] 캐시 저장 실패 (용량 초과 가능):', err);
  }
}

function clearCachedResults(projectId: string): void {
  if (!projectId) return;
  try { localStorage.removeItem(cacheKey(projectId)); } catch { /* ignore */ }
}

function formatCacheAge(fetchedAt: number): string {
  const ageMs = Date.now() - fetchedAt;
  const mins = Math.floor(ageMs / 60000);
  if (mins < 1) return '방금 전';
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}시간 전`;
  const days = Math.floor(hrs / 24);
  return `${days}일 전`;
}

export function PatternImportPanel() {
  const [isDragOver, setIsDragOver] = useState(false);
  const [results, setResults] = useState<ImportResult[]>([]);
  const [selectedResult, setSelectedResult] = useState<ImportResult | null>(null);
  const [selectedLayer, setSelectedLayer] = useState<number>(0);
  const [saveTargetIndex, setSaveTargetIndex] = useState<number>(0);
  const [saveCustomName, setSaveCustomName] = useState('');
  const [saved, setSaved] = useState<string | null>(null);
  const [pasteText, setPasteText] = useState('');

  // [v15.45] 다중 선택 (Shift+Click 범위, Ctrl/Cmd+Click 토글) + 일괄 저장
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [lastClickedIdx, setLastClickedIdx] = useState<number | null>(null);
  const [batchPrefix, setBatchPrefix] = useState<string>('');
  const [batchSaving, setBatchSaving] = useState(false);

  // 파일명에서 숫자 추출 (level_41 → 41, 없으면 fallback)
  const extractLevelNumber = (fileName: string, fallbackIdx: number): string => {
    const levelMatch = fileName.match(/level[_-]?(\d+)/i);
    if (levelMatch) return levelMatch[1];
    const anyNum = fileName.match(/(\d+)(?!.*\d)/);
    if (anyNum) return anyNum[1];
    return String(fallbackIdx + 1);
  };

  const handleFileListClick = (idx: number, ev: React.MouseEvent) => {
    if (ev.shiftKey && lastClickedIdx !== null) {
      const [lo, hi] = lastClickedIdx < idx ? [lastClickedIdx, idx] : [idx, lastClickedIdx];
      const range = new Set(selectedIndices);
      for (let i = lo; i <= hi; i++) range.add(i);
      setSelectedIndices(range);
    } else if (ev.ctrlKey || ev.metaKey) {
      const next = new Set(selectedIndices);
      if (next.has(idx)) next.delete(idx); else next.add(idx);
      setSelectedIndices(next);
      setLastClickedIdx(idx);
    } else {
      setSelectedIndices(new Set([idx]));
      setLastClickedIdx(idx);
    }
    setSelectedResult(results[idx]);
    setSelectedLayer(0);
  };

  // 게임부스트 가져오기 (프로젝트 ID는 localStorage 저장)
  const [gboostProjectId, setGboostProjectId] = useState<string>(
    () => localStorage.getItem('pattern_import_gboost_project_id') || '21ff4576052'
  );
  useEffect(() => {
    localStorage.setItem('pattern_import_gboost_project_id', gboostProjectId);
  }, [gboostProjectId]);

  // 캐시 메타: 복원된 시각 표시용
  const [cacheFetchedAt, setCacheFetchedAt] = useState<number | null>(null);

  // results가 비어있지 않게 바뀔 때마다 캐시 자동 동기화 (드래그/붙여넣기/개별 임포트 포함)
  // 빈 상태에서는 save하지 않음. TTL 갱신 방지 위해 기존 fetchedAt 유지.
  useEffect(() => {
    if (results.length > 0 && gboostProjectId) {
      saveCachedResults(gboostProjectId, results, cacheFetchedAt ?? Date.now());
    }
  }, [results, gboostProjectId, cacheFetchedAt]);

  // [v15.47] 마운트 + projectId 변경 시 캐시 복원 (results가 비어있을 때만 덮어씀)
  // 첫 마운트에 실행되고, 이후 projectId 변경 시 교체
  const initialLoadRef = useRef<boolean>(false);
  useEffect(() => {
    const cached = loadCachedResults(gboostProjectId);
    if (cached && cached.results.length > 0) {
      // 이미 같은 fileName이 메모리에 있을 수 있으므로 중복 제거
      setResults(prev => {
        if (prev.length === 0) {
          setSelectedResult(cached.results[0]);
          return cached.results;
        }
        const existing = new Set(prev.map(r => r.fileName));
        const fresh = cached.results.filter(r => !existing.has(r.fileName));
        if (fresh.length === 0) return prev;
        const merged = [...prev, ...fresh];
        return merged;
      });
      setCacheFetchedAt(cached.fetchedAt);
    } else {
      setCacheFetchedAt(null);
      // 다른 projectId로 전환 시 이전 결과 초기화 (첫 마운트는 제외)
      if (initialLoadRef.current) {
        setResults([]);
        setSelectedResult(null);
        setSelectedIndices(new Set());
        setLastClickedIdx(null);
      }
    }
    initialLoadRef.current = true;
  }, [gboostProjectId]);
  const [gboostLevels, setGboostLevels] = useState<LevelMetadata[]>([]);
  const [gboostLoading, setGboostLoading] = useState(false);
  const [gboostError, setGboostError] = useState('');

  // 진행률 표시용
  const [gboostProgress, setGboostProgress] = useState<{ done: number; total: number } | null>(null);

  const fetchGBoostLevels = async () => {
    if (!gboostProjectId.trim()) return;
    setGboostLoading(true);
    setGboostError('');
    setGboostProgress(null);
    try {
      const res = await apiClient.get(`/gboost/levels`, {
        params: { prefix: 'level_', limit: 500, project_id: gboostProjectId.trim() }
      });
      const levels: LevelMetadata[] = res.data.levels || [];
      setGboostLevels(levels);
      if (levels.length === 0) {
        setGboostError('레벨이 없습니다.');
        return;
      }

      // [v15.46] 조회 즉시 전체 자동 임포트 (개별 클릭 불필요)
      setGboostProgress({ done: 0, total: levels.length });
      const importedResults: ImportResult[] = [];
      const existingIds = new Set(results.map(r => r.fileName));
      for (let i = 0; i < levels.length; i++) {
        const lv = levels[i];
        const name = `${gboostProjectId}/${lv.id}`;
        if (existingIds.has(name)) { setGboostProgress({ done: i + 1, total: levels.length }); continue; }
        try {
          const lr = await apiClient.get(`/gboost/levels/${lv.id}`, {
            params: { project_id: gboostProjectId.trim() }
          });
          const lj = lr.data.level_json as Record<string, unknown>;
          importedResults.push(extractPatterns(lj, name));
        } catch { /* skip failed level */ }
        setGboostProgress({ done: i + 1, total: levels.length });
      }
      if (importedResults.length > 0) {
        setResults(prev => {
          const merged = [...prev, ...importedResults];
          saveCachedResults(gboostProjectId, merged);
          setCacheFetchedAt(Date.now());
          return merged;
        });
        setSelectedResult(importedResults[0]);
      } else {
        // 모두 기존 캐시와 중복이라도 fetchedAt 갱신 (최신 확인 표시)
        if (results.length > 0) {
          saveCachedResults(gboostProjectId, results);
          setCacheFetchedAt(Date.now());
        }
      }
    } catch (err) {
      setGboostError(`조회 실패: ${err}`);
      setGboostLevels([]);
    } finally {
      setGboostLoading(false);
      setGboostProgress(null);
    }
  };

  // 재조회: 캐시 삭제 후 강제 fetch
  const refetchGBoostLevels = async () => {
    clearCachedResults(gboostProjectId);
    setCacheFetchedAt(null);
    setResults([]);
    setSelectedResult(null);
    setSelectedIndices(new Set());
    setLastClickedIdx(null);
    await fetchGBoostLevels();
  };

  const importFromGBoost = async (levelId: string) => {
    // 이미 임포트된 항목이면 선택만
    const existing = results.find(r => r.fileName.includes(levelId));
    if (existing) {
      setSelectedResult(existing);
      return;
    }
    try {
      const res = await apiClient.get(`/gboost/levels/${levelId}`, {
        params: { project_id: gboostProjectId.trim() }
      });
      const lj = res.data.level_json as Record<string, unknown>;
      const result = extractPatterns(lj, `${gboostProjectId}/${levelId}`);
      setResults(prev => [...prev, result]);
      setSelectedResult(result);
    } catch {
      setGboostError(`${levelId} 로드 실패`);
    }
  };

  // JSON 파일에서 레이어별 패턴 추출
  // [v15.42] 레이어의 col/row (원본 인게임 그리드)를 사용 → 디자이너 센터링 의도 보존.
  // col/row 없으면 bbox 기반 정사각형 크롭으로 fallback.
  const extractPatterns = useCallback((rawJson: Record<string, unknown>, fileName: string): ImportResult => {
    const levelJson = (rawJson.map && typeof rawJson.map === 'object' && (rawJson.map as Record<string, unknown>).layer)
      ? rawJson.map as Record<string, unknown>
      : rawJson;
    const numLayers = (levelJson.layer as number) || 1;
    const levelNumber = (rawJson as Record<string, unknown>).level_number as number | undefined
      || (rawJson as Record<string, unknown>).idx as number | undefined;
    const patternIndex = (levelJson as Record<string, unknown>).pattern_index as number | undefined;

    const layers: ExtractedLayer[] = [];

    for (let i = 0; i < numLayers; i++) {
      const layerData = levelJson[`layer_${i}`] as Record<string, unknown> | undefined;
      if (!layerData) continue;
      const tiles = layerData.tiles as Record<string, unknown> | undefined;
      if (!tiles || Object.keys(tiles).length === 0) continue;

      const positions = Object.keys(tiles).filter(k => /^\d+_\d+$/.test(k));
      if (positions.length === 0) continue;

      // 원본 tile 데이터 참조 (기믹/스택 추출용)
      const tileData = tiles as Record<string, unknown>;

      const xs = positions.map(p => parseInt(p.split('_')[0]));
      const ys = positions.map(p => parseInt(p.split('_')[1]));
      const minX = Math.min(...xs), minY = Math.min(...ys);
      const maxX = Math.max(...xs), maxY = Math.max(...ys);
      const bboxW = maxX - minX + 1;
      const bboxH = maxY - minY + 1;

      // [v15.43] 저장용 grid는 bbox 기반 정사각형 (각 레이어의 실제 content 크기 보존)
      // col/row는 ingame 그리드(0.5 오프셋 렌더용)이지 content 크기가 아님 → 실루엣용 메타로만 보존
      const gridSize = Math.max(bboxW, bboxH);
      const padX = Math.round((gridSize - bboxW) / 2);
      const padY = Math.round((gridSize - bboxH) / 2);
      const normalizedPositions = positions.map(p => {
        const [px, py] = p.split('_').map(Number);
        return `${px - minX + padX}_${py - minY + padY}`;
      });

      const grid: number[][] = Array.from({ length: gridSize }, () => Array(gridSize).fill(0));
      for (const pos of normalizedPositions) {
        const [x, y] = pos.split('_').map(Number);
        if (x >= 0 && x < gridSize && y >= 0 && y < gridSize) {
          grid[y][x] = 1;
        }
      }

      // level_json은 col/row를 문자열("10")로 저장하는 경우가 있음 → Number()로 파싱
      const parsedCol = Number(layerData.col);
      const parsedRow = Number(layerData.row);
      const ingameCol = parsedCol > 0 ? parsedCol : gridSize;
      const ingameRow = parsedRow > 0 ? parsedRow : gridSize;

      // 정규화 좌표 → 원본 좌표 매핑으로 기믹 추출
      const tilesDetail: Record<string, TileDetail> = {};
      let effectiveCount = 0;
      let gimmickCount = 0;
      for (let idx = 0; idx < positions.length; idx++) {
        const origPos = positions[idx];
        const normPos = normalizedPositions[idx];
        const raw = tileData[origPos];
        const tile = Array.isArray(raw) ? raw : ['t0', ''];
        const tileType = typeof tile[0] === 'string' ? tile[0] : 't0';
        const attribute = typeof tile[1] === 'string' ? tile[1] : '';
        const extra = tile[2];
        const eff = tileEffectiveCount(tile);
        effectiveCount += eff;
        if ((tileType && tileType !== 't0' && !/^t\d+$/.test(tileType)) || attribute) {
          gimmickCount++;
        }
        tilesDetail[normPos] = { tileType, attribute, extra, effectiveCount: eff };
      }

      layers.push({
        layer: i,
        gridCols: gridSize,
        gridRows: gridSize,
        tileCount: normalizedPositions.length,
        effectiveCount,
        positions: normalizedPositions,
        grid,
        tilesDetail,
        gimmickCount,
        ingameCol,
        ingameRow,
        ingameOrigin: [minX, minY],
        ingameBbox: [bboxW, bboxH],
      });
    }

    // levelJson을 rawLevelJson으로 보존 (레벨 템플릿 저장 시 기믹 포함)
    return { fileName, levelNumber, layers, patternIndex, rawLevelJson: levelJson };
  }, []);

  // 클립보드 붙여넣기 (Ctrl+V)
  useEffect(() => {
    const handlePaste = (e: ClipboardEvent) => {
      const text = e.clipboardData?.getData('text');
      if (!text) return;
      try {
        const json = JSON.parse(text);
        if (json.layer || json.level_json) {
          const lj = json.level_json
            ? (typeof json.level_json === 'string' ? JSON.parse(json.level_json) : json.level_json)
            : json;
          const result = extractPatterns(lj, 'clipboard');
          setResults(prev => [...prev, result]);
          setSelectedResult(result);
        }
      } catch { /* not JSON */ }
    };
    window.addEventListener('paste', handlePaste);
    return () => window.removeEventListener('paste', handlePaste);
  }, [extractPatterns]);

  // 파일 처리
  const handleFiles = useCallback((files: FileList) => {
    const newResults: ImportResult[] = [];

    Array.from(files).forEach(file => {
      if (!file.name.endsWith('.json')) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const json = JSON.parse(e.target?.result as string);

          // 단일 레벨 또는 배열
          if (Array.isArray(json)) {
            json.forEach((level, idx) => {
              newResults.push(extractPatterns(level, `${file.name}[${idx}]`));
            });
          } else if (json.layer) {
            newResults.push(extractPatterns(json, file.name));
          } else if (json.level_json) {
            // GenerateResponse 형식
            const lj = typeof json.level_json === 'string' ? JSON.parse(json.level_json) : json.level_json;
            newResults.push(extractPatterns(lj, file.name));
          }

          setResults(prev => [...prev, ...newResults]);
          if (newResults.length > 0) setSelectedResult(newResults[0]);
        } catch (err) {
          console.error('Failed to parse JSON:', err);
        }
      };
      reader.readAsText(file);
    });
  }, [extractPatterns]);

  // 드래그&드롭
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragOver(true); };
  const handleDragLeave = () => setIsDragOver(false);
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
  };

  // 파일 선택
  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) handleFiles(e.target.files);
  };

  // 선택한 레이어 패턴을 커스텀으로 저장
  const [autoAssign, setAutoAssign] = useState(true);

  // 레이어 → 정사각형 gridSize로 저장 가능한 positions + bbox_pad 메타.
  // gridCols === gridRows면 그대로 사용. 아니면 max로 정사각형 만들고 Math.round 패딩.
  const normalizeLayer = (layer: ExtractedLayer): { gridSize: number; positions: string[]; bboxPad: [number, number] } => {
    if (layer.gridCols === layer.gridRows) {
      // 이미 extractPatterns에서 Math.round 중앙 패딩이 적용됨
      const [bw, bh] = layer.ingameBbox;
      const padX = Math.round((layer.gridCols - bw) / 2);
      const padY = Math.round((layer.gridRows - bh) / 2);
      return { gridSize: layer.gridCols, positions: layer.positions.slice(), bboxPad: [padX, padY] };
    }
    const gridSize = Math.max(layer.gridCols, layer.gridRows);
    const [bw, bh] = layer.ingameBbox;
    const extraPadX = Math.round((gridSize - layer.gridCols) / 2);
    const extraPadY = Math.round((gridSize - layer.gridRows) / 2);
    const positions = layer.positions.map(p => {
      const [px, py] = p.split('_').map(Number);
      return `${px + extraPadX}_${py + extraPadY}`;
    });
    // 최종 pad = extract 시 pad + 저장 시 추가 pad
    const padX = Math.round((layer.gridCols - bw) / 2) + extraPadX;
    const padY = Math.round((layer.gridRows - bh) / 2) + extraPadY;
    return { gridSize, positions, bboxPad: [padX, padY] };
  };

  // 현재 미사용 인덱스 조회 (64+부터)
  const findNextFreeIndex = async (): Promise<number> => {
    try {
      const configRes = await apiClient.get('/debug/custom-patterns');
      const existingKeys = Object.keys(configRes.data.custom_patterns || {});
      const usedIndices = new Set(existingKeys.map(k => parseInt(k.split('_')[0])).filter(n => !isNaN(n)));
      let idx = 64;
      while (usedIndices.has(idx)) idx++;
      return idx;
    } catch {
      return 64 + Date.now() % 1000;
    }
  };

  const saveAsCustomPattern = async (layerIdx?: number) => {
    if (!selectedResult) return;
    const li = layerIdx ?? selectedLayer;
    const layer = selectedResult.layers[li];
    if (!layer) return;

    const { gridSize, positions, bboxPad } = normalizeLayer(layer);
    const targetIndex = autoAssign ? await findNextFreeIndex() : saveTargetIndex;

    try {
      await apiClient.post('/debug/pattern-save', {
        pattern_index: targetIndex,
        grid_size: gridSize,
        positions,
        ingame_origin: layer.ingameOrigin,
        ingame_col: layer.ingameCol,
        ingame_row: layer.ingameRow,
        bbox_pad: bboxPad,
      });
      if (saveCustomName.trim()) {
        await apiClient.post(`/debug/pattern-rename?pattern_index=${targetIndex}&name=${encodeURIComponent(saveCustomName.trim())}`);
      }
      setSaveTargetIndex(targetIndex);
      setSaved(`패턴 #${targetIndex} "${saveCustomName || ''}" (${gridSize}x${gridSize}) 저장됨!`);
      setTimeout(() => setSaved(null), 3000);
    } catch (err) {
      console.error('Save failed:', err);
    }
  };

  interface SaveVariant {
    positions: string[];
    bboxPad: [number, number];
    ingameOrigin: [number, number];
    ingameCol: number;
    ingameRow: number;
  }

  // 레이어들을 size별로 그룹핑 (크기 충돌 허용)
  const groupLayersBySize = (layers: ExtractedLayer[]): Map<number, SaveVariant[]> => {
    const groups = new Map<number, SaveVariant[]>();
    for (const layer of layers) {
      const { gridSize, positions, bboxPad } = normalizeLayer(layer);
      if (!groups.has(gridSize)) groups.set(gridSize, []);
      groups.get(gridSize)!.push({
        positions,
        bboxPad,
        ingameOrigin: layer.ingameOrigin,
        ingameCol: layer.ingameCol,
        ingameRow: layer.ingameRow,
      });
    }
    return groups;
  };

  // 한 ImportResult를 N개의 패턴 인덱스에 저장. 크기 충돌 시 secondary 인덱스(_v2, _v3)로.
  // targetIndices는 [primary, ...secondaries] 순. 반환: 실제로 사용된 인덱스 개수
  const savePatternForResult = async (result: ImportResult, targetIndices: number[], name: string): Promise<number> => {
    const groups = groupLayersBySize(result.layers);
    // 필요한 인덱스 수 = 최대 크기 충돌 수
    const needed = Math.max(1, ...Array.from(groups.values()).map(arr => arr.length));
    if (needed > targetIndices.length) {
      throw new Error(`인덱스 부족: needed=${needed}, given=${targetIndices.length}`);
    }
    // 각 인덱스에 크기별 1개씩 저장 (+ ingame 메타데이터)
    for (const [gridSize, variants] of groups.entries()) {
      for (let j = 0; j < variants.length; j++) {
        const v = variants[j];
        await apiClient.post('/debug/pattern-save', {
          pattern_index: targetIndices[j],
          grid_size: gridSize,
          positions: v.positions,
          ingame_origin: v.ingameOrigin,
          ingame_col: v.ingameCol,
          ingame_row: v.ingameRow,
          bbox_pad: v.bboxPad,
        });
      }
    }
    // 이름 부여 (2번째부터 _v2, _v3 suffix)
    if (name.trim()) {
      for (let k = 0; k < needed; k++) {
        const suffix = k === 0 ? '' : `_v${k + 1}`;
        await apiClient.post(
          `/debug/pattern-rename?pattern_index=${targetIndices[k]}&name=${encodeURIComponent(name.trim() + suffix)}`
        );
      }
    }
    return needed;
  };

  // [v15.50] 레벨 템플릿 저장 (기믹 포함, 원본 level_json 통째로)
  const saveLevelTemplate = async (result: ImportResult, name?: string): Promise<string | null> => {
    if (!result.rawLevelJson) return null;
    const parts = result.fileName.split('/');
    const sourceLevelId = parts.length > 1 ? parts[1] : result.fileName;
    const sourceProjectId = parts.length > 1 ? parts[0] : null;
    try {
      const res = await apiClient.post('/debug/level-template-save', {
        name: name || result.fileName,
        source_project_id: sourceProjectId,
        source_level_id: sourceLevelId,
        level_json: result.rawLevelJson,
      });
      return res.data.template_id as string;
    } catch (err) {
      console.error('Level template save failed:', err);
      return null;
    }
  };

  const [savingTemplate, setSavingTemplate] = useState(false);

  const saveSelectedAsTemplate = async () => {
    if (!selectedResult) return;
    setSavingTemplate(true);
    try {
      const tid = await saveLevelTemplate(selectedResult);
      if (tid) {
        setSaved(`레벨 템플릿 저장 완료: ${tid}`);
      } else {
        setSaved('레벨 템플릿 저장 실패 (원본 JSON 없음)');
      }
      setTimeout(() => setSaved(null), 3000);
    } finally {
      setSavingTemplate(false);
    }
  };

  const batchSaveAsTemplates = async () => {
    if (selectedIndices.size === 0) return;
    const ordered = [...selectedIndices].sort((a, b) => a - b);
    setSavingTemplate(true);
    try {
      let ok = 0, skipped = 0;
      for (const resultIdx of ordered) {
        const result = results[resultIdx];
        const num = extractLevelNumber(result.fileName, resultIdx);
        const name = `${batchPrefix || ''}${num}`.trim() || result.fileName;
        const tid = await saveLevelTemplate(result, name);
        if (tid) ok++; else skipped++;
      }
      setSaved(`레벨 템플릿 ${ok}개 저장 완료${skipped > 0 ? ` (${skipped}개 스킵)` : ''}`);
      setTimeout(() => setSaved(null), 4000);
    } finally {
      setSavingTemplate(false);
    }
  };

  // [신규] 선택된 레벨들을 prefix+번호 형식으로 일괄 저장
  const batchSaveSelected = async () => {
    if (selectedIndices.size === 0) return;
    const orderedIndices = [...selectedIndices].sort((a, b) => a - b);
    setBatchSaving(true);
    try {
      // 각 레벨의 크기 충돌로 인한 추가 인덱스 수요 계산
      const perLevelNeeded = orderedIndices.map(i => {
        const groups = groupLayersBySize(results[i].layers);
        return Math.max(1, ...Array.from(groups.values()).map(arr => arr.length));
      });
      const totalNeeded = perLevelNeeded.reduce((s, n) => s + n, 0);

      // 미사용 인덱스 일괄 확보
      const configRes = await apiClient.get('/debug/custom-patterns');
      const used = new Set<number>(
        Object.keys(configRes.data.custom_patterns || {})
          .map((k: string) => parseInt(k.split('_')[0]))
          .filter(n => !isNaN(n))
      );
      const freeIndices: number[] = [];
      let cursor = 64;
      while (freeIndices.length < totalNeeded) {
        if (!used.has(cursor)) { freeIndices.push(cursor); used.add(cursor); }
        cursor++;
      }

      let savedLevels = 0, totalPatterns = 0, collisions = 0;
      let cursorIdx = 0;
      for (let i = 0; i < orderedIndices.length; i++) {
        const resultIdx = orderedIndices[i];
        const result = results[resultIdx];
        const need = perLevelNeeded[i];
        const slice = freeIndices.slice(cursorIdx, cursorIdx + need);
        cursorIdx += need;
        const num = extractLevelNumber(result.fileName, resultIdx);
        const name = `${batchPrefix}${num}`;
        const usedN = await savePatternForResult(result, slice, name);
        savedLevels++;
        totalPatterns += usedN;
        if (usedN > 1) collisions++;
      }
      const rangeMsg = `idx ${freeIndices[0]}~${freeIndices[totalNeeded - 1]}`;
      const collisionMsg = collisions > 0 ? ` (${collisions}개 레벨은 크기 충돌로 보조 인덱스 추가)` : '';
      setSaved(`${savedLevels}개 레벨 → ${totalPatterns}개 패턴 "${batchPrefix}*" 저장 완료${collisionMsg}, ${rangeMsg}`);
      setTimeout(() => setSaved(null), 6000);
    } catch (err) {
      console.error('Batch save failed:', err);
      setSaved('일괄 저장 실패');
      setTimeout(() => setSaved(null), 3000);
    } finally {
      setBatchSaving(false);
    }
  };

  // [신규] 전체 레이어를 하나의 패턴 인덱스에 크기별 변형으로 저장
  // 동일 gridSize에 여러 레이어가 있으면 보조 인덱스(_v2, _v3)로 자동 분할
  const saveAllLayersAsOnePattern = async () => {
    if (!selectedResult) return;
    const layers = selectedResult.layers;
    if (layers.length === 0) return;

    try {
      const groups = groupLayersBySize(layers);
      const needed = Math.max(1, ...Array.from(groups.values()).map(arr => arr.length));

      // 인덱스 확보
      const configRes = await apiClient.get('/debug/custom-patterns');
      const used = new Set<number>(
        Object.keys(configRes.data.custom_patterns || {})
          .map((k: string) => parseInt(k.split('_')[0]))
          .filter(n => !isNaN(n))
      );
      const targetIndices: number[] = [];
      if (autoAssign) {
        let cursor = 64;
        while (targetIndices.length < needed) {
          if (!used.has(cursor)) { targetIndices.push(cursor); used.add(cursor); }
          cursor++;
        }
      } else {
        // 수동 모드: primary만 saveTargetIndex, 보조가 필요하면 이후 미사용 인덱스
        targetIndices.push(saveTargetIndex);
        let cursor = saveTargetIndex + 1;
        while (targetIndices.length < needed) {
          if (!used.has(cursor)) { targetIndices.push(cursor); used.add(cursor); }
          cursor++;
        }
      }

      const usedN = await savePatternForResult(selectedResult, targetIndices, saveCustomName);
      setSaveTargetIndex(targetIndices[0]);
      const sizesStr = [...groups.keys()].sort((a, b) => a - b).map(s => `${s}×${s}`).join(', ');
      const collisionMsg = usedN > 1 ? ` + 보조 ${usedN - 1}개(_v2~_v${usedN})` : '';
      setSaved(`패턴 #${targetIndices[0]} "${saveCustomName || ''}" 크기별 변형(${sizesStr})${collisionMsg} 저장됨!`);
      setTimeout(() => setSaved(null), 5000);
    } catch (err) {
      console.error('Save-all failed:', err);
    }
  };

  const LAYER_COLORS = ['#3b82f6', '#22c55e', '#a855f7', '#f97316', '#ec4899', '#06b6d4'];

  return (
    <div className="p-4 space-y-4">
      <h2 className="text-lg font-bold text-white">📁 패턴 임포트</h2>
      <p className="text-sm text-gray-400">
        기존 레벨 JSON 파일을 드래그하여 패턴을 추출하고 커스텀 패턴으로 저장합니다.
      </p>

      {/* 드래그 영역 */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
          isDragOver ? 'border-indigo-400 bg-indigo-900/20' : 'border-gray-600 hover:border-gray-500'
        }`}
      >
        <div className="text-3xl mb-2">📄</div>
        <div className="text-sm text-gray-400">
          레벨 JSON 파일을 여기에 드래그하세요
        </div>
        <div className="text-xs text-gray-500 mt-1">또는</div>
        <label className="mt-2 inline-block px-4 py-2 rounded text-sm bg-gray-700 hover:bg-gray-600 text-gray-300 cursor-pointer">
          파일 선택
          <input type="file" accept=".json" multiple onChange={handleFileInput} className="hidden" />
        </label>
      </div>

      {/* JSON 붙여넣기 */}
      <div className="space-y-1">
        <div className="text-xs text-gray-400">또는 JSON 붙여넣기 (Ctrl+V 또는 아래 입력)</div>
        <div className="flex gap-2">
          <textarea
            value={pasteText}
            onChange={e => setPasteText(e.target.value)}
            placeholder='{"layer": 2, "layer_0": {...}, ...}'
            className="flex-1 h-16 px-2 py-1 text-xs bg-gray-800 border border-gray-600 rounded text-gray-300 font-mono resize-none"
          />
          <button
            onClick={() => {
              if (!pasteText.trim()) return;
              try {
                const json = JSON.parse(pasteText);
                const lj = json.level_json
                  ? (typeof json.level_json === 'string' ? JSON.parse(json.level_json) : json.level_json)
                  : json;
                const result = extractPatterns(lj, 'paste');
                setResults(prev => [...prev, result]);
                setSelectedResult(result);
                setPasteText('');
              } catch { /* invalid */ }
            }}
            className="px-3 py-1 rounded text-sm bg-indigo-600 hover:bg-indigo-500 text-white shrink-0 self-end"
          >
            추출
          </button>
        </div>
      </div>

      {/* 게임부스트에서 가져오기 */}
      <div className="bg-gray-800 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h3 className="text-sm font-medium text-white">☁️ 게임부스트에서 가져오기</h3>
          {cacheFetchedAt && results.length > 0 && (
            <span
              className="text-[10px] px-2 py-0.5 rounded bg-emerald-900/40 text-emerald-300 border border-emerald-800"
              title={`캐시 복원됨 — projectId=${gboostProjectId}, ${new Date(cacheFetchedAt).toLocaleString()}`}
            >
              📦 캐시 {formatCacheAge(cacheFetchedAt)} ({results.length}개)
            </span>
          )}
        </div>
        <p className="text-[10px] text-gray-500">프로젝트 ID를 입력하면 자동 임포트. 같은 ID로 재진입 시 캐시에서 즉시 복원 (TTL 7일)</p>
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="text-[10px] text-gray-500 block mb-0.5">프로젝트 ID</label>
            <input
              type="text"
              value={gboostProjectId}
              onChange={e => setGboostProjectId(e.target.value)}
              placeholder="예: 6d126f4db852"
              className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded text-white"
              onKeyDown={e => e.key === 'Enter' && fetchGBoostLevels()}
            />
          </div>
          <button onClick={fetchGBoostLevels} disabled={gboostLoading || !gboostProjectId.trim()}
            className="px-4 py-1.5 rounded text-sm bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50 shrink-0"
          >
            {gboostLoading ? '조회 중...' : '레벨 조회'}
          </button>
        </div>

        {gboostError && <div className="text-xs text-red-400">{gboostError}</div>}

        {gboostProgress && (
          <div className="space-y-1">
            <div className="text-[10px] text-cyan-300">
              자동 임포트 중... {gboostProgress.done}/{gboostProgress.total}
            </div>
            <div className="h-1 bg-gray-700 rounded overflow-hidden">
              <div className="h-full bg-cyan-500 transition-all"
                style={{ width: `${(gboostProgress.done / Math.max(1, gboostProgress.total)) * 100}%` }} />
            </div>
          </div>
        )}

        {gboostLevels.length > 0 && !gboostProgress && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">{gboostLevels.length}개 레벨 자동 임포트 완료</span>
              <button onClick={refetchGBoostLevels} disabled={gboostLoading}
                className="px-2 py-0.5 rounded text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-300"
                title="캐시 삭제 + 재fetch"
              >
                🔄 재조회
              </button>
            </div>
            <details className="bg-gray-900 rounded">
              <summary className="px-2 py-1 text-[10px] text-gray-400 cursor-pointer hover:text-gray-300">
                레벨 ID 목록 보기/선택 이동
              </summary>
              <div className="max-h-40 overflow-y-auto space-y-0.5 p-1">
                {gboostLevels.map(lv => {
                  const existing = results.find(r => r.fileName.includes(lv.id));
                  const isPrimary = existing && selectedResult === existing;
                  return (
                    <button key={lv.id}
                      onClick={() => { if (existing) setSelectedResult(existing); else importFromGBoost(lv.id); }}
                      className={`w-full text-left px-2 py-1 rounded text-xs flex items-center justify-between ${
                        isPrimary ? 'bg-indigo-600 text-white'
                        : existing ? 'bg-cyan-900/30 text-cyan-300 hover:bg-cyan-900/50'
                        : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                      }`}
                    >
                      <span>{lv.id}</span>
                      {existing && <span className="text-[10px] text-cyan-500">✓</span>}
                    </button>
                  );
                })}
              </div>
            </details>
          </div>
        )}
      </div>

      {/* 결과 목록 */}
      {results.length > 0 && (
        <div className="flex gap-4">
          {/* 파일 목록 (왼쪽) */}
          <div className="w-56 shrink-0 space-y-1 max-h-[70vh] overflow-y-auto">
            <div className="sticky top-0 bg-gray-900 py-1 space-y-1 z-10">
              <div className="flex items-center justify-between">
                <h3 className="text-xs text-gray-400 font-medium">
                  임포트된 파일 ({results.length})
                </h3>
                <div className="flex gap-1">
                  <button onClick={() => setSelectedIndices(new Set(results.map((_, i) => i)))}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                    title="모두 선택">전체</button>
                  <button onClick={() => setSelectedIndices(new Set())}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                    title="선택 해제">해제</button>
                </div>
              </div>
              <p className="text-[9px] text-gray-500">Shift+Click: 범위, Ctrl/⌘+Click: 토글</p>

              {/* 일괄 저장 영역 */}
              {selectedIndices.size > 1 && (
                <div className="bg-indigo-900/30 border border-indigo-800 rounded p-1.5 space-y-1">
                  <div className="text-[10px] text-indigo-300">
                    {selectedIndices.size}개 선택됨 → 일괄 저장
                  </div>
                  <input type="text" value={batchPrefix}
                    onChange={e => setBatchPrefix(e.target.value)}
                    placeholder="prefix (예: 하트_)"
                    className="w-full px-1.5 py-1 text-[11px] bg-gray-800 border border-gray-600 rounded text-white"
                  />
                  <div className="text-[9px] text-gray-500">
                    이름: <span className="text-indigo-300">{batchPrefix}</span>
                    <span className="text-gray-400">{'{레벨번호}'}</span>
                    {' '}(파일명에서 파싱)
                  </div>
                  <button onClick={batchSaveSelected} disabled={batchSaving || savingTemplate}
                    className="w-full px-2 py-1 rounded text-[11px] bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50"
                    title="레이어별 분해 → 패턴 인덱스로 저장 (프로덕션 생성용)"
                  >
                    {batchSaving ? '저장 중...' : `💾 ${selectedIndices.size}개 패턴으로 저장`}
                  </button>
                  <button onClick={batchSaveAsTemplates} disabled={batchSaving || savingTemplate}
                    className="w-full px-2 py-1 rounded text-[11px] bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-50"
                    title="레벨 전체 통째로 저장 (기믹·위치 보존, 1:1 재현용)"
                  >
                    {savingTemplate ? '저장 중...' : `📋 ${selectedIndices.size}개 레벨 템플릿으로 저장`}
                  </button>
                </div>
              )}
            </div>

            {results.map((r, idx) => {
              const isSelected = selectedIndices.has(idx);
              const isPrimary = selectedResult === r;
              const parsedNum = extractLevelNumber(r.fileName, idx);
              return (
                <button key={idx}
                  onClick={(ev) => handleFileListClick(idx, ev)}
                  className={`w-full text-left px-2 py-1.5 rounded text-xs truncate flex items-center gap-1 ${
                    isPrimary ? 'bg-indigo-600 text-white'
                    : isSelected ? 'bg-indigo-900/60 text-indigo-200 border border-indigo-700'
                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                  }`}
                  title={r.fileName}
                >
                  {isSelected && !isPrimary && <span className="text-[10px] shrink-0">✓</span>}
                  <span className="flex-1 truncate">{r.fileName}</span>
                  <span className="text-[10px] text-gray-500 shrink-0">#{parsedNum}</span>
                </button>
              );
            })}
            <button onClick={() => {
                clearCachedResults(gboostProjectId);
                setCacheFetchedAt(null);
                setResults([]);
                setSelectedResult(null);
                setSelectedIndices(new Set());
                setLastClickedIdx(null);
              }}
              className="w-full px-2 py-1 rounded text-xs bg-red-900/30 text-red-300 hover:bg-red-800"
              title="캐시까지 완전 삭제">
              전체 삭제 (캐시 포함)
            </button>
          </div>

          {/* 레이어 상세 (오른쪽) */}
          {selectedResult && (
            <div className="flex-1 space-y-3">
              <div className="bg-gray-800 rounded-lg p-3">
                <h3 className="text-sm font-medium text-white mb-2">
                  {selectedResult.fileName}
                  {selectedResult.levelNumber && <span className="text-gray-400 ml-2">Lv.{selectedResult.levelNumber}</span>}
                </h3>

                {/* 모든 레이어 그리드 나란히 표시 — 기믹/스택 오버레이 포함 */}
                <div className="flex flex-wrap gap-3 mb-3">
                  {selectedResult.layers.map((lv) => (
                    <div key={lv.layer}>
                      <div className="text-[10px] text-gray-400 mb-0.5">
                        <span className="inline-block w-2 h-2 rounded-sm mr-0.5" style={{ backgroundColor: LAYER_COLORS[lv.layer] }} />
                        L{lv.layer} (
                        {lv.effectiveCount}t
                        {lv.effectiveCount !== lv.tileCount && <span className="text-gray-500">/{lv.tileCount} pos</span>},
                        {' '}{lv.gridCols}×{lv.gridRows})
                        {lv.effectiveCount % 3 !== 0 && <span className="text-red-400 ml-1">!3</span>}
                        {lv.gimmickCount > 0 && <span className="text-amber-400 ml-1">🎁{lv.gimmickCount}</span>}
                      </div>
                      <div className="inline-block border border-gray-700 rounded">
                        {lv.grid.map((row, y) => (
                          <div key={y} className="flex">
                            {row.map((cell, x) => {
                              const pos = `${x}_${y}`;
                              const detail = cell ? lv.tilesDetail[pos] : undefined;
                              const g = detail ? describeTile(detail) : { icon: '', badge: '', label: '', ring: '' };
                              return (
                                <div key={x}
                                  className={`relative w-5 h-5 flex items-center justify-center ${g.ring}`}
                                  style={{ margin: '0.5px', backgroundColor: cell ? LAYER_COLORS[lv.layer] : '#111827' }}
                                  title={detail ? `${pos}: ${g.label || 'basic'}` : ''}
                                >
                                  {g.icon && (
                                    <span className="text-[8px] leading-none select-none" style={{ textShadow: '0 0 2px rgba(0,0,0,0.9)' }}>
                                      {g.icon}
                                    </span>
                                  )}
                                  {g.badge && (
                                    <span className="absolute -bottom-0.5 -right-0.5 text-[6px] font-bold text-white bg-black/80 rounded px-0.5 leading-none">
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
                <div className="text-[10px] text-gray-500">
                  {(() => {
                    const totalEff = selectedResult.layers.reduce((s, l) => s + l.effectiveCount, 0);
                    const totalPos = selectedResult.layers.reduce((s, l) => s + l.tileCount, 0);
                    const totalGim = selectedResult.layers.reduce((s, l) => s + l.gimmickCount, 0);
                    return (
                      <>
                        총 {totalEff}t{totalEff !== totalPos && ` (${totalPos} positions)`}
                        {totalEff % 3 !== 0
                          ? <span className="text-red-400 ml-1">3배수 아님 (나머지 {totalEff % 3})</span>
                          : <span className="text-green-400 ml-1">3✓</span>}
                        {totalGim > 0 && <span className="text-amber-400 ml-2">🎁 기믹 {totalGim}개</span>}
                      </>
                    );
                  })()}
                </div>
              </div>

              {/* 실루엣 — 각 레이어를 인게임 col/row 좌표로 오버레이 (0.5 오프셋 반영) */}
              {selectedResult.layers.length >= 2 && (() => {
                const baseCols = Math.max(...selectedResult.layers.map(l => l.ingameCol));
                const baseRows = Math.max(...selectedResult.layers.map(l => l.ingameRow));
                const subW = baseCols * 2 + 2;
                const subH = baseRows * 2 + 2;
                const silGrid: number[][] = Array.from({ length: subH }, () => Array(subW).fill(-1));

                for (const lv of selectedResult.layers) {
                  const isOdd = lv.layer % 2 === 1;
                  // 각 레이어는 자신의 ingameCol×ingameRow 안에 위치. 베이스에 중심 정렬.
                  const lvCX = isOdd ? (lv.ingameCol + 1) / 2 : lv.ingameCol / 2;
                  const lvCY = isOdd ? (lv.ingameRow + 1) / 2 : lv.ingameRow / 2;
                  const shiftX = baseCols / 2 - lvCX;
                  const shiftY = baseRows / 2 - lvCY;

                  // 정규화된 좌표를 원본 ingame 좌표로 복원: normalized - pad + origin
                  const [bboxW, bboxH] = lv.ingameBbox;
                  const [ox, oy] = lv.ingameOrigin;
                  const gridSize = Math.max(bboxW, bboxH);
                  const padX = Math.round((gridSize - bboxW) / 2);
                  const padY = Math.round((gridSize - bboxH) / 2);

                  for (const pos of lv.positions) {
                    const [xs, ys] = pos.split('_');
                    const nx = parseInt(xs), ny = parseInt(ys);
                    const ingameX = nx - padX + ox;
                    const ingameY = ny - padY + oy;
                    const vx = ingameX + (isOdd ? 0.5 : 0) + shiftX;
                    const vy = ingameY + (isOdd ? 0.5 : 0) + shiftY;
                    const sx = Math.round(vx * 2), sy = Math.round(vy * 2);
                    for (let dy = 0; dy < 2; dy++) {
                      for (let dx = 0; dx < 2; dx++) {
                        const ry = sy + dy, rx = sx + dx;
                        if (ry >= 0 && ry < subH && rx >= 0 && rx < subW) {
                          silGrid[ry][rx] = lv.layer;
                        }
                      }
                    }
                  }
                }

                return (
                  <div className="bg-gray-800 rounded-lg p-3">
                    <h4 className="text-xs text-gray-400 mb-1">인게임 실루엣 (base {baseCols}×{baseRows}, 0.5 오프셋 반영)</h4>
                    <div className="inline-block border border-gray-600 rounded bg-gray-950 p-1">
                      {silGrid.map((row, y) => (
                        <div key={y} className="flex">
                          {row.map((cell, x) => (
                            <div key={x} className="w-2 h-2" style={{
                              backgroundColor: cell >= 0 ? LAYER_COLORS[cell % LAYER_COLORS.length] : 'transparent',
                              opacity: cell >= 0 ? 0.8 : 0,
                            }} />
                          ))}
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-1 mt-1">
                      {selectedResult.layers.map(lv => (
                        <span key={lv.layer} className="text-[9px] text-gray-500 flex items-center gap-0.5">
                          <span className="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: LAYER_COLORS[lv.layer % LAYER_COLORS.length] }} />
                          L{lv.layer}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })()}

              {/* 저장 */}
              <div className="bg-gray-800 rounded-lg p-3 space-y-2">
                <h4 className="text-xs text-gray-400">커스텀 패턴으로 저장</h4>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex-1">
                    <label className="text-[10px] text-gray-500 block">패턴 이름</label>
                    <input type="text" value={saveCustomName}
                      onChange={e => setSaveCustomName(e.target.value)}
                      placeholder="이름 입력 → 자동 번호 할당"
                      className="w-full px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white"
                    />
                  </div>
                  {!autoAssign && (
                    <div>
                      <label className="text-[10px] text-gray-500 block">번호</label>
                      <input type="number" min={0} max={99} value={saveTargetIndex}
                        onChange={e => setSaveTargetIndex(Number(e.target.value))}
                        className="w-16 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white"
                      />
                    </div>
                  )}
                  <div className="self-end flex gap-1">
                    <button onClick={() => setAutoAssign(!autoAssign)}
                      className={`px-2 py-1.5 rounded text-[10px] ${autoAssign ? 'bg-green-700 text-green-200' : 'bg-gray-700 text-gray-400'}`}
                      title={autoAssign ? '자동 번호 할당' : '수동 번호 지정'}
                    >
                      {autoAssign ? '자동#' : '수동#'}
                    </button>
                    <button onClick={() => saveAsCustomPattern()}
                      className="px-3 py-1.5 rounded text-sm bg-blue-600 hover:bg-blue-500 text-white"
                      title="선택한 레이어 하나만 저장 (새 인덱스)"
                    >
                      💾 선택 레이어
                    </button>
                    {selectedResult && selectedResult.layers.length > 1 && (
                      <button onClick={saveAllLayersAsOnePattern}
                        className="px-3 py-1.5 rounded text-sm bg-emerald-600 hover:bg-emerald-500 text-white"
                        title="모든 레이어를 하나의 패턴 인덱스에 크기별 변형(4×4, 5×5, 6×6, 7×7 등)으로 저장"
                      >
                        💾 전체 레이어 (크기별 변형)
                      </button>
                    )}
                    {selectedResult?.rawLevelJson && (
                      <button onClick={saveSelectedAsTemplate} disabled={savingTemplate}
                        className="px-3 py-1.5 rounded text-sm bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-50"
                        title="레벨 전체를 통째로 보존 (기믹·위치·타일 모두 그대로). 패턴 분해와 별개로 디버거에서 1:1 재현 가능"
                      >
                        {savingTemplate ? '저장 중...' : '📋 레벨 템플릿'}
                      </button>
                    )}
                  </div>
                </div>
                {/* 레이어별 개별 저장 */}
                {selectedResult.layers.length > 1 && (
                  <div className="text-[10px] text-gray-500 space-y-0.5">
                    <div>레이어별 개별 저장:</div>
                    <div className="flex gap-1">
                      {selectedResult.layers.map((lv, idx) => (
                        <button key={idx}
                          onClick={() => saveAsCustomPattern(idx)}
                          className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                        >
                          L{lv.layer} ({lv.gridCols}×{lv.gridRows})
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {saved && (
                  <div className="text-xs text-green-400">{saved}</div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import { useMemo, useEffect, useCallback } from 'react';
import { TileGrid } from './TileGrid';
import { LayerSelector } from './LayerSelector';
import { ToolPalette } from './ToolPalette';
import { Minimap } from './Minimap';
import { LayerStackPreview } from './LayerStackPreview';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { Button, Tooltip } from '../ui';
import { Eye, EyeOff, FileJson, RotateCcw, ZoomIn, Grid3X3, Map, AlertTriangle, CheckCircle, Undo2, Redo2, Copy, Clipboard, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { validateTileCount } from '../../utils/helpers';
import type { LevelJSON, LevelLayer, TileData } from '../../types';

// Gimmick counting helper
interface GimmickCounts {
  chain: number;
  frog: number;
  ice: number;
  grass: number;
  link: number;
  bomb: number;
  unknown: number;
  teleport: number;
  curtain: number;
  craft: number;
  stack: number;
}

const GIMMICK_INFO: Record<string, { icon: string; name: string }> = {
  chain: { icon: '⛓️', name: 'Chain' },
  frog: { icon: '🐸', name: 'Frog' },
  ice: { icon: '❄️', name: 'Ice' },
  grass: { icon: '🌿', name: 'Grass' },
  link: { icon: '🔗', name: 'Link' },
  bomb: { icon: '💣', name: 'Bomb' },
  unknown: { icon: '❓', name: 'Unknown' },
  teleport: { icon: '🌀', name: 'Teleport' },
  curtain: { icon: '🎭', name: 'Curtain' },
  craft: { icon: '🎁', name: 'Craft' },
  stack: { icon: '📚', name: 'Stack' },
};

function countGimmicks(levelData: LevelJSON): GimmickCounts {
  const counts: GimmickCounts = {
    chain: 0, frog: 0, ice: 0, grass: 0, link: 0,
    bomb: 0, unknown: 0, teleport: 0, curtain: 0,
    craft: 0, stack: 0,
  };

  // Scan all layers (0-7)
  for (let i = 0; i < 8; i++) {
    const layer = (levelData as any)[`layer_${i}`] as LevelLayer | undefined;
    if (!layer?.tiles) continue;

    for (const pos in layer.tiles) {
      const tileData = layer.tiles[pos] as TileData;
      if (!tileData || !Array.isArray(tileData)) continue;

      const [tileType, attribute] = tileData;

      // Count tile type gimmicks (craft, stack)
      if (tileType && typeof tileType === 'string') {
        if (tileType.startsWith('craft_')) counts.craft++;
        else if (tileType.startsWith('stack_')) counts.stack++;
      }

      // Count attribute gimmicks
      if (!attribute) continue;
      if (attribute === 'chain') counts.chain++;
      else if (attribute === 'frog') counts.frog++;
      else if (attribute.startsWith('ice')) counts.ice++;
      else if (attribute.startsWith('grass')) counts.grass++;
      else if (attribute.startsWith('link')) counts.link++;
      else if (attribute === 'bomb') counts.bomb++;
      else if (attribute === 'unknown') counts.unknown++;
      else if (attribute.startsWith('teleport')) counts.teleport++;
      else if (attribute === 'curtain') counts.curtain++;
    }
  }
  return counts;
}

interface GridEditorProps {
  className?: string;
}

export function GridEditor({ className }: GridEditorProps) {
  const { level, selectedLayer, resetLevel, undo, redo, canUndo, canRedo, selection, clipboard, copySelection, deleteSelection } = useLevelStore();
  const {
    setJsonModalOpen,
    addNotification,
    showOtherLayers,
    setShowOtherLayers,
    gridZoom,
    setGridZoom,
    showGridCoordinates,
    setShowGridCoordinates,
    showMinimap,
    setShowMinimap,
  } = useUIStore();

  // Keyboard shortcuts for undo/redo
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Check for Ctrl+Z (undo) or Cmd+Z on Mac
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
      e.preventDefault();
      if (canUndo()) {
        undo();
        addNotification('info', '실행 취소');
      }
    }
    // Check for Ctrl+Y or Ctrl+Shift+Z (redo)
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
      e.preventDefault();
      if (canRedo()) {
        redo();
        addNotification('info', '다시 실행');
      }
    }
  }, [undo, redo, canUndo, canRedo, addNotification]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  const handleReset = () => {
    if (confirm('레벨을 초기화하시겠습니까?')) {
      resetLevel();
      addNotification('info', '레벨을 초기화했습니다');
    }
  };

  const handleViewJson = () => {
    setJsonModalOpen(true);
  };

  // Validate tile count
  const tileValidation = useMemo(() => validateTileCount(level), [level]);

  // Helper to count tiles including hidden tiles in craft/stack boxes
  const countTilesInLayer = (layerData: typeof level[`layer_${number}`] | undefined): number => {
    if (!layerData?.tiles) return 0;
    let count = 0;
    for (const tileData of Object.values(layerData.tiles)) {
      const tileType = tileData[0];
      const extra = tileData[2];
      // Check if this is a stack/craft box tile with hidden tiles
      if (tileType.startsWith('stack_') || tileType.startsWith('craft_')) {
        if (extra && Array.isArray(extra) && extra.length >= 1) {
          const tileCount = typeof extra[0] === 'number' ? extra[0] : 1;
          count += tileCount;
        } else {
          count += 1;
        }
      } else {
        count += 1;
      }
    }
    return count;
  };

  // Count tiles in current layer (including hidden tiles in craft/stack)
  const currentLayerTileCount = useMemo(() => {
    const layerKey = `layer_${selectedLayer}` as `layer_${number}`;
    return countTilesInLayer(level[layerKey]);
  }, [level, selectedLayer]);

  // Count total tiles across all layers (including hidden tiles in craft/stack)
  const totalTileCount = useMemo(() => {
    let total = 0;
    for (let i = 0; i < level.layer; i++) {
      const layerKey = `layer_${i}` as `layer_${number}`;
      total += countTilesInLayer(level[layerKey]);
    }
    return total;
  }, [level]);

  // Count gimmicks in level
  const gimmickCounts = useMemo(() => countGimmicks(level), [level]);
  const activeGimmicks = useMemo(() =>
    Object.entries(gimmickCounts).filter(([_, count]) => count > 0),
    [gimmickCounts]
  );

  return (
    <div className={clsx('flex flex-col gap-4 p-4 bg-gray-800 rounded-xl shadow-lg border border-gray-700', className)}>
      {/* Tile count info and validation */}
      <div className="flex items-center gap-4">
        {/* Current layer tile count */}
        <div className="flex items-center gap-2 px-3 py-2 bg-gray-700/50 rounded-lg text-sm">
          <span className="text-gray-400">레이어 {selectedLayer}:</span>
          <span className="font-mono font-bold text-blue-300">{currentLayerTileCount}</span>
          <span className="text-gray-500">타일</span>
        </div>

        {/* Total tile count */}
        <div className="flex items-center gap-2 px-3 py-2 bg-gray-700/50 rounded-lg text-sm">
          <span className="text-gray-400">전체:</span>
          <span className="font-mono font-bold text-purple-300">{totalTileCount}</span>
          <span className="text-gray-500">타일</span>
        </div>

        {/* Validation status */}
        {tileValidation.totalTiles > 0 && (
          <div
            className={clsx(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm flex-1',
              tileValidation.isValid
                ? 'bg-green-900/30 border border-green-700 text-green-300'
                : 'bg-amber-900/30 border border-amber-600 text-amber-300'
            )}
          >
            {tileValidation.isValid ? (
              <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            )}
            <span>{tileValidation.message}</span>
            {!tileValidation.isValid && (
              <span className="text-amber-500 ml-auto text-xs">
                3의 배수가 아니면 클리어 불가
              </span>
            )}
          </div>
        )}
      </div>

      {/* Gimmick counts display */}
      {activeGimmicks.length > 0 && (
        <div className="flex items-center gap-2 px-3 py-2 bg-gray-700/30 rounded-lg">
          <span className="text-gray-400 text-sm">기믹:</span>
          <div className="flex flex-wrap gap-2">
            {activeGimmicks.map(([gimmick, count]) => (
              <span
                key={gimmick}
                className="inline-flex items-center gap-1 px-2 py-1 text-sm bg-gray-700/80 rounded-md"
                title={`${GIMMICK_INFO[gimmick]?.name}: ${count}개`}
              >
                <span>{GIMMICK_INFO[gimmick]?.icon}</span>
                <span className="text-gray-200 font-medium">{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Selection info bar */}
      {selection && (
        <div className="flex items-center gap-3 px-3 py-2 bg-blue-900/30 border border-blue-700 rounded-lg text-sm">
          <span className="text-blue-300">
            선택 영역: ({Math.abs(selection.endX - selection.startX) + 1} x {Math.abs(selection.endY - selection.startY) + 1})
          </span>
          <span className="text-blue-400/70">|</span>
          <span className="text-blue-400/70 text-xs">Ctrl+C: 복사 | Ctrl+V: 붙여넣기 | Del: 삭제 | Esc: 취소</span>
        </div>
      )}

      {/* Clipboard indicator */}
      {clipboard && !selection && (
        <div className="flex items-center gap-3 px-3 py-2 bg-green-900/30 border border-green-700 rounded-lg text-sm">
          <span className="text-green-300">
            클립보드: {Object.keys(clipboard.tiles).length}개 타일 ({clipboard.bounds.maxX + 1} x {clipboard.bounds.maxY + 1})
          </span>
          <span className="text-green-400/70">|</span>
          <span className="text-green-400/70 text-xs">Ctrl+V: 마우스 위치에 붙여넣기 | Shift+드래그: 새 영역 선택</span>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-100">그리드 에디터</h2>
        <div className="flex gap-2">
          {/* Undo/Redo buttons */}
          <div className="flex gap-1 mr-2">
            <Tooltip content="실행 취소 (Ctrl+Z)">
              <Button
                onClick={() => { undo(); addNotification('info', '실행 취소'); }}
                variant="secondary"
                size="sm"
                disabled={!canUndo()}
                icon={<Undo2 className="w-full h-full" />}
              />
            </Tooltip>
            <Tooltip content="다시 실행 (Ctrl+Y)">
              <Button
                onClick={() => { redo(); addNotification('info', '다시 실행'); }}
                variant="secondary"
                size="sm"
                disabled={!canRedo()}
                icon={<Redo2 className="w-full h-full" />}
              />
            </Tooltip>
          </div>

          {/* Copy/Paste buttons */}
          <div className="flex gap-1 mr-2">
            <Tooltip content="선택 영역 복사 (Ctrl+C) - Shift+드래그로 선택">
              <Button
                onClick={() => { copySelection(); addNotification('info', '복사됨'); }}
                variant="secondary"
                size="sm"
                disabled={!selection}
                icon={<Copy className="w-full h-full" />}
              />
            </Tooltip>
            <Tooltip content={clipboard ? `클립보드: ${Object.keys(clipboard.tiles).length}개 타일` : '클립보드 비어있음'}>
              <Button
                variant={clipboard ? 'primary' : 'secondary'}
                size="sm"
                disabled={true}
                icon={<Clipboard className="w-full h-full" />}
              />
            </Tooltip>
            <Tooltip content="선택 영역 삭제 (Delete)">
              <Button
                onClick={() => { deleteSelection(); addNotification('info', '삭제됨'); }}
                variant="danger"
                size="sm"
                disabled={!selection}
                icon={<Trash2 className="w-full h-full" />}
              />
            </Tooltip>
          </div>

          {/* Layer transparency toggle */}
          <Tooltip content={showOtherLayers ? '다른 레이어 숨기기' : '다른 레이어 표시'}>
            <Button
              onClick={() => setShowOtherLayers(!showOtherLayers)}
              variant={showOtherLayers ? 'primary' : 'secondary'}
              size="sm"
              icon={showOtherLayers ? <Eye className="w-full h-full" /> : <EyeOff className="w-full h-full" />}
            >
              {showOtherLayers ? '다른층 표시' : '다른층 숨김'}
            </Button>
          </Tooltip>
          <Tooltip content="JSON 데이터 보기">
            <Button
              onClick={handleViewJson}
              variant="secondary"
              size="sm"
              icon={<FileJson className="w-full h-full" />}
            >
              JSON
            </Button>
          </Tooltip>
          <Tooltip content="레벨 초기화">
            <Button
              onClick={handleReset}
              variant="danger"
              size="sm"
              icon={<RotateCcw className="w-full h-full" />}
            >
              초기화
            </Button>
          </Tooltip>
        </div>
      </div>

      {/* View controls: zoom, coordinates, minimap */}
      <div className="flex items-center gap-4 px-2 py-2 bg-gray-750 rounded-lg">
        {/* Zoom slider */}
        <Tooltip content="그리드 확대/축소 (Ctrl+휠)">
          <div className="flex items-center gap-2">
            <ZoomIn className="w-4 h-4 text-gray-400" />
            <input
              type="range"
              min="0.5"
              max="2"
              step="0.1"
              value={gridZoom}
              onChange={(e) => setGridZoom(parseFloat(e.target.value))}
              className="w-24 h-1.5 bg-gray-600 rounded-lg appearance-none cursor-pointer accent-primary-500"
            />
            <span className="text-xs text-gray-400 w-10">{Math.round(gridZoom * 100)}%</span>
          </div>
        </Tooltip>

        <div className="w-px h-4 bg-gray-600" />

        {/* Coordinates toggle */}
        <Tooltip content="좌표 표시 토글">
          <button
            onClick={() => setShowGridCoordinates(!showGridCoordinates)}
            className={clsx(
              'px-2 py-1 text-xs rounded transition-colors flex items-center gap-1',
              showGridCoordinates
                ? 'bg-primary-700 text-primary-100'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
            )}
          >
            <Grid3X3 className="w-3.5 h-3.5" />
            좌표
          </button>
        </Tooltip>

        {/* Minimap toggle */}
        <Tooltip content="미니맵 표시 토글">
          <button
            onClick={() => setShowMinimap(!showMinimap)}
            className={clsx(
              'px-2 py-1 text-xs rounded transition-colors flex items-center gap-1',
              showMinimap
                ? 'bg-primary-700 text-primary-100'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
            )}
          >
            <Map className="w-3.5 h-3.5" />
            미니맵
          </button>
        </Tooltip>
      </div>

      <LayerSelector />

      <div className="flex gap-4">
        <div className="flex-1 overflow-auto relative flex justify-center items-start min-h-[400px] bg-gray-900/50 rounded-lg p-4">
          <TileGrid />
          {/* Minimap overlay */}
          {showMinimap && (
            <div className="absolute bottom-2 right-2 z-20">
              <Minimap />
            </div>
          )}
        </div>
        <div className="w-56 flex-shrink-0 flex flex-col gap-3">
          <ToolPalette />
          <LayerStackPreview />
        </div>
      </div>
    </div>
  );
}

export { TileGrid } from './TileGrid';
export { LayerSelector } from './LayerSelector';
export { ToolPalette } from './ToolPalette';
export { Minimap } from './Minimap';
export { LayerStackPreview } from './LayerStackPreview';

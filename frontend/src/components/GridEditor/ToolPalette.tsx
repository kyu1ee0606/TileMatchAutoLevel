import { useState, useEffect, useCallback } from 'react';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { TILE_TYPES, ATTRIBUTES, type TileData } from '../../types';
import { Button, Tooltip } from '../ui';
import { Paintbrush, Eraser, Palette, Box, PaintBucket, Trash2, Timer } from 'lucide-react';
import clsx from 'clsx';

// 타일 카테고리 정의
type TileCategory = 'basic' | 'generator';

const TILE_CATEGORIES: Record<TileCategory, { label: string; icon: typeof Palette; filter: (type: string) => boolean }> = {
  basic: {
    label: '기본',
    icon: Palette,
    filter: (type) => /^t\d+$/.test(type), // t0, t1, t2, ...
  },
  generator: {
    label: '생성기',
    icon: Box,
    filter: (type) => type.startsWith('craft_') || type.startsWith('stack_'), // 타일 생성 기믹
  },
};

interface ToolPaletteProps {
  className?: string;
}

export function ToolPalette({ className }: ToolPaletteProps) {
  const {
    level,
    selectedTileType,
    selectedAttribute,
    selectedLayer,
    setSelectedTileType,
    setSelectedAttribute,
    setTimeAttack,
    clearLayer,
    fillLayer,
  } = useLevelStore();

  const { activeTool, setActiveTool } = useUIStore();

  const [selectedCategory, setSelectedCategory] = useState<TileCategory>('basic');

  const tileTypes = Object.entries(TILE_TYPES);
  const attributes = Object.entries(ATTRIBUTES);

  // 현재 카테고리에 맞는 타일만 필터링
  const filteredTileTypes = tileTypes.filter(([type]) =>
    TILE_CATEGORIES[selectedCategory].filter(type)
  );

  // 기본 타일 배열 (단축키용)
  const basicTiles = tileTypes
    .filter(([type]) => TILE_CATEGORIES.basic.filter(type))
    .slice(0, 9); // 1-9 단축키용

  // 단축키 핸들러
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // input, textarea 등에서는 동작하지 않도록
    if (e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement) {
      return;
    }

    // 1-9: 기본 타일 선택
    if (e.key >= '1' && e.key <= '9') {
      const index = parseInt(e.key) - 1;
      if (basicTiles[index]) {
        setSelectedTileType(basicTiles[index][0]);
        setSelectedCategory('basic');
        setActiveTool('paint');
      }
      return;
    }

    // E: 지우기 모드
    if (e.key === 'e' || e.key === 'E') {
      setActiveTool('erase');
      return;
    }

    // P: 페인트 모드
    if (e.key === 'p' || e.key === 'P') {
      setActiveTool('paint');
      return;
    }
  }, [basicTiles, setSelectedTileType, setActiveTool]);

  // 단축키 이벤트 등록
  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  const handleFillLayer = () => {
    const tileData: TileData = [selectedTileType, selectedAttribute];
    fillLayer(selectedLayer, tileData);
  };

  const handleClearLayer = () => {
    if (confirm(`레이어 ${selectedLayer}의 모든 타일을 삭제하시겠습니까?`)) {
      clearLayer(selectedLayer);
    }
  };

  return (
    <div className={clsx('flex flex-col gap-4', className)}>
      {/* Tool Selection */}
      <div>
        <label className="text-sm font-medium text-gray-300 mb-2 block">도구</label>
        <div className="flex gap-1">
          <Tooltip content="타일 배치 (P)">
            <button
              onClick={() => setActiveTool('paint')}
              className={clsx(
                'px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1.5',
                activeTool === 'paint'
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              )}
            >
              <Paintbrush className="w-4 h-4" />
              그리기
              <kbd className="text-[10px] px-1 py-0.5 bg-gray-900 rounded border border-gray-600">P</kbd>
            </button>
          </Tooltip>
          <Tooltip content="타일 삭제 (E)">
            <button
              onClick={() => setActiveTool('erase')}
              className={clsx(
                'px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1.5',
                activeTool === 'erase'
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              )}
            >
              <Eraser className="w-4 h-4" />
              지우기
              <kbd className="text-[10px] px-1 py-0.5 bg-gray-900 rounded border border-gray-600">E</kbd>
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Time Attack Setting */}
      <div>
        <label className="text-sm font-medium text-gray-300 mb-2 block">
          <Timer className="w-4 h-4 inline mr-1" />
          타임어택
        </label>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min="0"
            max="999"
            value={level.timeAttack || 0}
            onChange={(e) => setTimeAttack(parseInt(e.target.value) || 0)}
            className="w-20 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white text-center"
            placeholder="0"
          />
          <span className="text-sm text-gray-400">초</span>
          <span className="text-xs text-gray-500">(0 = 비활성)</span>
        </div>
      </div>

      {/* Tile Type Selection */}
      <div>
        <label className="text-sm font-medium text-gray-300 mb-2 block">타일 타입</label>

        {/* Category Tabs */}
        <div className="flex gap-1 mb-2 border-b border-gray-700 pb-2">
          {(Object.entries(TILE_CATEGORIES) as [TileCategory, typeof TILE_CATEGORIES[TileCategory]][]).map(
            ([category, config]) => {
              const Icon = config.icon;
              return (
                <button
                  key={category}
                  onClick={() => setSelectedCategory(category)}
                  className={clsx(
                    'px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1.5',
                    selectedCategory === category
                      ? 'bg-primary-600 text-white'
                      : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                  )}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{config.label}</span>
                </button>
              );
            }
          )}
        </div>

        {/* Filtered Tile Grid */}
        <div className="grid grid-cols-4 gap-1 max-h-48 overflow-y-auto">
          {filteredTileTypes.map(([type, info], index) => {
            // 기본 타일 카테고리에서만 단축키 번호 표시
            const shortcutNumber = selectedCategory === 'basic' && index < 9 ? index + 1 : null;

            return (
              <button
                key={type}
                onClick={() => setSelectedTileType(type)}
                title={`${info.name}${shortcutNumber ? ` (단축키: ${shortcutNumber})` : ''}`}
                className={clsx(
                  'w-10 h-10 rounded-md border-2 flex items-center justify-center text-xs font-bold text-white transition-transform hover:scale-105 overflow-hidden relative',
                  selectedTileType === type
                    ? 'border-primary-500 ring-2 ring-primary-300'
                    : 'border-gray-600'
                )}
                style={{ backgroundColor: info.color }}
              >
                {info.image ? (
                  <img
                    src={info.image}
                    alt={info.name}
                    className="w-full h-full object-cover"
                    draggable={false}
                    onError={(e) => {
                      // 이미지 로드 실패 시 fallback 표시
                      const img = e.target as HTMLImageElement;
                      img.style.display = 'none';
                      const parent = img.parentElement;
                      if (parent && !parent.querySelector('.fallback-text')) {
                        const fallback = document.createElement('span');
                        fallback.className = 'fallback-text text-white text-xs';
                        fallback.textContent = type.replace('_s', '').replace('craft_', 'C').replace('stack_', 'S');
                        parent.appendChild(fallback);
                      }
                    }}
                  />
                ) : (
                  type.replace('_s', '')
                )}
                {/* 단축키 번호 표시 */}
                {shortcutNumber && (
                  <span className="absolute -top-1 -right-1 w-4 h-4 bg-gray-900 text-white text-[10px] rounded-full flex items-center justify-center border border-gray-600">
                    {shortcutNumber}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* 선택된 타일 정보 + 카테고리별 타일 수 */}
        <div className="mt-1 flex justify-between text-xs text-gray-400">
          <span>선택: {TILE_TYPES[selectedTileType]?.name || selectedTileType}</span>
          <span>{filteredTileTypes.length}개</span>
        </div>
      </div>

      {/* Attribute Selection */}
      <div>
        <label className="text-sm font-medium text-gray-300 mb-2 block">속성 (기믹)</label>
        <div className="grid grid-cols-5 gap-1 max-h-32 overflow-y-auto">
          {attributes.map(([attr, info]) => (
            <button
              key={attr || 'none'}
              onClick={() => setSelectedAttribute(attr)}
              title={info.name}
              className={clsx(
                'w-10 h-10 rounded-md border-2 flex items-center justify-center text-lg transition-transform hover:scale-105',
                selectedAttribute === attr
                  ? 'border-primary-500 ring-2 ring-primary-300 bg-primary-600'
                  : 'border-gray-600 bg-gray-700 hover:bg-gray-600'
              )}
            >
              {info.icon || '∅'}
            </button>
          ))}
        </div>
        {/* 선택된 속성 정보 */}
        <div className="mt-1 text-xs text-gray-400">
          선택: {ATTRIBUTES[selectedAttribute]?.icon} {ATTRIBUTES[selectedAttribute]?.name || 'None'}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="border-t border-gray-700 pt-4">
        <label className="text-sm font-medium text-gray-300 mb-2 block">빠른 작업</label>
        <div className="flex gap-2">
          <Tooltip content="선택한 타일로 레이어 전체 채우기">
            <Button
              onClick={handleFillLayer}
              variant="success"
              size="sm"
              icon={<PaintBucket className="w-full h-full" />}
              className="flex-1"
            >
              레이어 채우기
            </Button>
          </Tooltip>
          <Tooltip content="레이어의 모든 타일 삭제">
            <Button
              onClick={handleClearLayer}
              variant="danger"
              size="sm"
              icon={<Trash2 className="w-full h-full" />}
              className="flex-1"
            >
              레이어 지우기
            </Button>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}

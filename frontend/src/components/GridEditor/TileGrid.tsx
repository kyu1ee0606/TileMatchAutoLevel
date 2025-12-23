import { useCallback, useState, useMemo, useRef, useEffect } from 'react';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { TILE_TYPES, ATTRIBUTES, SPECIAL_IMAGES, type TileData, type LevelLayer } from '../../types';
import clsx from 'clsx';
import type { ValidationResult } from '../../stores/levelStore';

interface TileGridProps {
  className?: string;
}

const BASE_TILE_SIZE = 40; // px
const GAP_SIZE = 2; // px (gap-0.5)

export function TileGrid({ className }: TileGridProps) {
  const {
    level,
    selectedLayer,
    selectedTileType,
    selectedAttribute,
    setTile,
    removeTile,
  } = useLevelStore();

  const { activeTool, showOtherLayers, gridZoom, setGridZoom, showGridCoordinates, addNotification } = useUIStore();

  const [isDragging, setIsDragging] = useState(false);
  const [isLayerTransitioning, setIsLayerTransitioning] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const prevLayerRef = useRef(selectedLayer);

  // Calculate tile size based on zoom
  const TILE_SIZE = Math.round(BASE_TILE_SIZE * gridZoom);

  // Layer transition animation
  useEffect(() => {
    if (prevLayerRef.current !== selectedLayer) {
      setIsLayerTransitioning(true);
      prevLayerRef.current = selectedLayer;

      const timer = setTimeout(() => {
        setIsLayerTransitioning(false);
      }, 200);

      return () => clearTimeout(timer);
    }
  }, [selectedLayer]);

  // Mouse wheel zoom handler
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? -0.1 : 0.1;
        setGridZoom(gridZoom + delta);
      }
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, [gridZoom, setGridZoom]);

  const layerKey = `layer_${selectedLayer}` as `layer_${number}`;
  const layerData = level[layerKey];

  // Collect other layers for semi-transparent display
  const otherLayers = useMemo(() => {
    if (!showOtherLayers) return [];

    const layers: { layer: number; data: LevelLayer; brightness: number }[] = [];

    // Show only layers BELOW current layer (lower index = below)
    // Maximum 2 layers below (same as townpop editor)
    for (let i = selectedLayer - 1; i >= Math.max(0, selectedLayer - 2); i--) {
      const key = `layer_${i}` as `layer_${number}`;
      const data = level[key];
      if (data && data.tiles && Object.keys(data.tiles).length > 0) {
        const layerDiff = selectedLayer - i;
        const brightness = Math.max(50, 255 - layerDiff * 50) / 255;
        layers.push({ layer: i, data, brightness });
      }
    }

    return layers;
  }, [level, selectedLayer, showOtherLayers]);

  if (!layerData) {
    return (
      <div className={clsx('flex items-center justify-center p-8 text-gray-400 bg-gray-900 rounded-lg', className)}>
        <div className="text-center">
          <span className="text-2xl block mb-2">📭</span>
          <span>레이어 {selectedLayer} 데이터가 없습니다</span>
          <p className="text-xs mt-1 text-gray-500">다른 레이어를 선택하세요</p>
        </div>
      </div>
    );
  }

  const currentCols = parseInt(layerData.col) || 8;
  const currentRows = parseInt(layerData.row) || 8;
  const tiles = layerData.tiles || {};

  // Calculate max grid size for container (considering all visible layers)
  const { maxCols, maxRows } = useMemo(() => {
    let maxC = currentCols;
    let maxR = currentRows;

    if (showOtherLayers) {
      otherLayers.forEach((layerInfo) => {
        const otherCols = parseInt(layerInfo.data.col) || 0;
        const otherRows = parseInt(layerInfo.data.row) || 0;
        maxC = Math.max(maxC, otherCols);
        maxR = Math.max(maxR, otherRows);
      });
    }

    return { maxCols: maxC, maxRows: maxR };
  }, [currentCols, currentRows, showOtherLayers, otherLayers]);

  // Calculate container size based on max grid dimensions
  const containerWidth = maxCols * TILE_SIZE + (maxCols - 1) * GAP_SIZE;
  const containerHeight = maxRows * TILE_SIZE + (maxRows - 1) * GAP_SIZE;

  // Track last shown warning to avoid spamming during drag
  const lastWarningRef = useRef<string>('');
  const lastWarningTimeRef = useRef<number>(0);

  const handleTileAction = useCallback(
    (x: number, y: number) => {
      let result: ValidationResult;

      if (activeTool === 'paint') {
        const tileData: TileData = [selectedTileType, selectedAttribute];
        result = setTile(selectedLayer, x, y, tileData);
      } else if (activeTool === 'erase') {
        result = removeTile(selectedLayer, x, y);
      } else {
        return;
      }

      // Show warning if validation failed (throttle to avoid spam)
      if (!result.valid && result.reason) {
        const now = Date.now();
        if (result.reason !== lastWarningRef.current || now - lastWarningTimeRef.current > 2000) {
          addNotification('warning', result.reason);
          lastWarningRef.current = result.reason;
          lastWarningTimeRef.current = now;
        }
      }
    },
    [activeTool, selectedLayer, selectedTileType, selectedAttribute, setTile, removeTile, addNotification]
  );

  const handleMouseDown = (x: number, y: number) => {
    setIsDragging(true);
    handleTileAction(x, y);
  };

  const handleMouseEnter = (x: number, y: number) => {
    if (isDragging) {
      handleTileAction(x, y);
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  // Render a single tile (for other layers)
  const renderOtherLayerSingleTile = (
    x: number,
    y: number,
    layerInfo: { layer: number; data: LevelLayer; brightness: number }
  ) => {
    const pos = `${x}_${y}`;
    const tileData = layerInfo.data.tiles?.[pos];

    if (!tileData) {
      // Empty cell placeholder for grid alignment
      return (
        <div
          key={`other-${layerInfo.layer}-${pos}`}
          style={{ width: TILE_SIZE, height: TILE_SIZE }}
        />
      );
    }

    const [tileType, attribute] = tileData;
    const tileInfo = TILE_TYPES[tileType];
    const attrImage = attribute ? SPECIAL_IMAGES[attribute] : null;

    return (
      <div
        key={`other-${layerInfo.layer}-${pos}`}
        className="flex items-center justify-center relative"
        style={{
          width: TILE_SIZE,
          height: TILE_SIZE,
          border: '1px solid rgba(100, 100, 100, 0.5)',
        }}
      >
        {tileInfo?.image ? (
          <img
            src={tileInfo.image}
            alt={tileInfo.name}
            className="w-full h-full object-cover"
            draggable={false}
          />
        ) : (
          <div
            className="w-full h-full flex items-center justify-center text-xs font-bold"
            style={{ backgroundColor: tileInfo?.color || '#888' }}
          >
            <span className="text-white">{tileType.replace('_s', '')}</span>
          </div>
        )}
        {attrImage && (
          <img
            src={attrImage}
            alt={attribute}
            className="absolute inset-0 w-full h-full object-cover opacity-70"
            draggable={false}
          />
        )}
      </div>
    );
  };

  // Render entire other layer grid as centered overlay
  const renderOtherLayerGrid = (layerInfo: { layer: number; data: LevelLayer; brightness: number }) => {
    const otherCols = parseInt(layerInfo.data.col) || 0;
    const otherRows = parseInt(layerInfo.data.row) || 0;

    const brightnessPercent = Math.round(layerInfo.brightness * 100);

    // Grid size for this layer
    const gridWidth = otherCols * TILE_SIZE + (otherCols - 1) * GAP_SIZE;
    const gridHeight = otherRows * TILE_SIZE + (otherRows - 1) * GAP_SIZE;

    return (
      <div
        key={`other-layer-grid-${layerInfo.layer}`}
        className="absolute pointer-events-none"
        style={{
          // Center this layer grid within the container (centered pivot)
          left: '50%',
          top: '50%',
          width: gridWidth,
          height: gridHeight,
          transform: 'translate(-50%, -50%)',
          filter: `brightness(${brightnessPercent}%)`,
          zIndex: layerInfo.layer,
        }}
      >
        <div
          className="grid"
          style={{
            gridTemplateColumns: `repeat(${otherCols}, ${TILE_SIZE}px)`,
            gap: `${GAP_SIZE}px`,
          }}
        >
          {Array.from({ length: otherRows }, (_, y) =>
            Array.from({ length: otherCols }, (_, x) =>
              renderOtherLayerSingleTile(x, y, layerInfo)
            )
          )}
        </div>
      </div>
    );
  };

  // Render current layer tile
  const renderCurrentTile = (x: number, y: number) => {
    const pos = `${x}_${y}`;
    const tileData = tiles[pos];

    // Empty cell - fully transparent, border only for grid recognition
    if (!tileData) {
      return (
        <div
          key={pos}
          className="border border-gray-600/30 hover:border-gray-400/50 cursor-pointer transition-colors"
          style={{
            width: TILE_SIZE,
            height: TILE_SIZE,
            backgroundColor: 'transparent',
          }}
          onMouseDown={() => handleMouseDown(x, y)}
          onMouseEnter={() => handleMouseEnter(x, y)}
        />
      );
    }

    const [tileType, attribute] = tileData;
    const tileInfo = TILE_TYPES[tileType];
    const attrInfo = ATTRIBUTES[attribute || ''];
    const attrImage = attribute ? SPECIAL_IMAGES[attribute] : null;

    // t0 is random tile (icon only), t1+ shows t0 background + tile icon
    const isRandomTile = tileType === 't0';
    const t0Info = TILE_TYPES['t0'];

    return (
      <div
        key={pos}
        className="cursor-pointer flex items-center justify-center text-xs font-bold relative transition-transform hover:scale-105 overflow-hidden"
        style={{
          width: TILE_SIZE,
          height: TILE_SIZE,
          backgroundColor: 'transparent',
        }}
        onMouseDown={() => handleMouseDown(x, y)}
        onMouseEnter={() => handleMouseEnter(x, y)}
        title={`${tileInfo?.name || tileType} ${attrInfo?.name || ''}`}
      >
        {/* t0 background layer (for t1+ tiles) */}
        {!isRandomTile && t0Info?.image && (
          <div className="absolute inset-0">
            <img
              src={t0Info.image}
              alt="tile background"
              className="w-full h-full object-cover pointer-events-none"
              draggable={false}
            />
          </div>
        )}
        {/* Current layer tile icon */}
        <div className="absolute inset-0 flex items-center justify-center">
          {tileInfo?.image ? (
            <img
              src={tileInfo.image}
              alt={tileInfo.name}
              className="w-full h-full object-cover pointer-events-none"
              draggable={false}
            />
          ) : (
            // Fallback color block when no image
            <div
              className="w-full h-full flex items-center justify-center"
              style={{ backgroundColor: tileInfo?.color || '#888' }}
            >
              <span className="text-white text-shadow">
                {tileType.replace('_s', '')}
              </span>
            </div>
          )}
        </div>
        {attrImage && (
          <img
            src={attrImage}
            alt={attribute}
            className="absolute inset-0 w-full h-full object-cover pointer-events-none opacity-80 z-20"
            draggable={false}
          />
        )}
        {attribute && !attrImage && (
          <span className="absolute bottom-0 right-0 text-[10px] bg-black/50 px-0.5 rounded z-20">
            {attrInfo?.icon || attribute[0]}
          </span>
        )}
        {tileData[2] && (
          <span className="absolute top-0 left-0 text-[10px] bg-black/50 text-white px-0.5 rounded z-20">
            {tileData[2][0]}
          </span>
        )}
      </div>
    );
  };

  // Current layer grid size
  const currentGridWidth = currentCols * TILE_SIZE + (currentCols - 1) * GAP_SIZE;
  const currentGridHeight = currentRows * TILE_SIZE + (currentRows - 1) * GAP_SIZE;

  // Ruler size for coordinates
  const RULER_SIZE = showGridCoordinates ? 24 : 0;

  return (
    <div
      ref={containerRef}
      className={clsx('select-none', className)}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {/* Grid container with optional rulers */}
      <div
        className="relative bg-gray-900 rounded-lg shadow-inner"
        style={{
          width: containerWidth + 32 + RULER_SIZE,
          height: containerHeight + 32 + RULER_SIZE,
          padding: 16,
        }}
      >
        {/* Top ruler (X coordinates) */}
        {showGridCoordinates && (
          <div
            className="absolute flex"
            style={{
              left: 16 + RULER_SIZE + (containerWidth - currentGridWidth) / 2,
              top: 8,
              width: currentGridWidth,
              height: RULER_SIZE - 4,
            }}
          >
            {Array.from({ length: currentCols }, (_, x) => (
              <div
                key={`ruler-x-${x}`}
                className="flex items-center justify-center text-[10px] text-gray-500 font-mono"
                style={{ width: TILE_SIZE + (x < currentCols - 1 ? GAP_SIZE : 0) }}
              >
                {x}
              </div>
            ))}
          </div>
        )}

        {/* Left ruler (Y coordinates) */}
        {showGridCoordinates && (
          <div
            className="absolute flex flex-col"
            style={{
              left: 4,
              top: 16 + RULER_SIZE + (containerHeight - currentGridHeight) / 2,
              width: RULER_SIZE - 4,
              height: currentGridHeight,
            }}
          >
            {Array.from({ length: currentRows }, (_, y) => (
              <div
                key={`ruler-y-${y}`}
                className="flex items-center justify-center text-[10px] text-gray-500 font-mono"
                style={{ height: TILE_SIZE + (y < currentRows - 1 ? GAP_SIZE : 0) }}
              >
                {y}
              </div>
            ))}
          </div>
        )}

        {/* Main grid area */}
        <div
          className="relative flex items-center justify-center"
          style={{
            marginLeft: RULER_SIZE,
            marginTop: RULER_SIZE,
            width: containerWidth,
            height: containerHeight,
          }}
        >
        {/* Other layers rendered as separate grids (centered pivot) */}
        {showOtherLayers && otherLayers.map((layerInfo) => renderOtherLayerGrid(layerInfo))}

        {/* Current layer grid (centered, always on top with z-index 10) */}
        <div
          className="absolute grid z-10 transition-transform duration-150 ease-out"
          style={{
            left: '50%',
            top: '50%',
            width: currentGridWidth,
            height: currentGridHeight,
            transform: isLayerTransitioning ? 'translate(-50%, -50%) scale(0.98)' : 'translate(-50%, -50%) scale(1)',
            gridTemplateColumns: `repeat(${currentCols}, ${TILE_SIZE}px)`,
            gap: `${GAP_SIZE}px`,
          }}
        >
          {Array.from({ length: currentRows }, (_, y) =>
            Array.from({ length: currentCols }, (_, x) => renderCurrentTile(x, y))
          )}
        </div>
        </div>
      </div>
    </div>
  );
}

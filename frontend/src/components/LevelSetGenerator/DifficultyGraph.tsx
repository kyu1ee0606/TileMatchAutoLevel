import { useRef, useState, useCallback, useEffect } from 'react';
import type { DifficultyPoint, DifficultyPreset } from '../../types/levelSet';
import { scalePresetToLevelCount } from '../../types/levelSet';
import { getAllPresets, saveCustomPreset, deleteCustomPreset, pointsToPreset } from '../../api/levelSet';
import { getGradeColor } from '../../utils/helpers';
import type { DifficultyGrade } from '../../types';
import { Button, Tooltip } from '../ui';

interface DifficultyGraphProps {
  levelCount: number;
  points: DifficultyPoint[];
  onPointsChange: (points: DifficultyPoint[]) => void;
  width?: number;
  height?: number;
}

const PADDING = { top: 20, right: 30, bottom: 40, left: 50 };
const POINT_RADIUS = 8;
const POINT_HOVER_RADIUS = 10;

function getGradeFromDifficulty(difficulty: number): DifficultyGrade {
  const score = difficulty * 100;
  if (score <= 20) return 'S';
  if (score <= 40) return 'A';
  if (score <= 60) return 'B';
  if (score <= 80) return 'C';
  return 'D';
}

export function DifficultyGraph({
  levelCount,
  points,
  onPointsChange,
  width = 500,
  height = 250,
}: DifficultyGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  // Preset management
  const [presets, setPresets] = useState<DifficultyPreset[]>([]);
  const [showPresetMenu, setShowPresetMenu] = useState(false);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [newPresetName, setNewPresetName] = useState('');
  const [newPresetDescription, setNewPresetDescription] = useState('');

  // Load presets
  useEffect(() => {
    setPresets(getAllPresets());
  }, []);

  // Handle preset selection
  const handlePresetSelect = useCallback((preset: DifficultyPreset) => {
    const scaledPoints = scalePresetToLevelCount(preset, levelCount);
    onPointsChange(scaledPoints);
    setShowPresetMenu(false);
  }, [levelCount, onPointsChange]);

  // Handle save preset
  const handleSavePreset = useCallback(() => {
    if (!newPresetName.trim()) return;

    const presetData = pointsToPreset(points, levelCount, newPresetName.trim(), newPresetDescription.trim() || undefined);
    saveCustomPreset(presetData);
    setPresets(getAllPresets());
    setNewPresetName('');
    setNewPresetDescription('');
    setShowSaveDialog(false);
  }, [points, levelCount, newPresetName, newPresetDescription]);

  // Handle delete preset
  const handleDeletePreset = useCallback((presetId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (deleteCustomPreset(presetId)) {
      setPresets(getAllPresets());
    }
  }, []);

  const chartWidth = width - PADDING.left - PADDING.right;
  const chartHeight = height - PADDING.top - PADDING.bottom;

  // Convert data point to SVG coordinates
  const toSvgX = useCallback(
    (levelIndex: number) => PADDING.left + ((levelIndex - 1) / Math.max(1, levelCount - 1)) * chartWidth,
    [levelCount, chartWidth]
  );

  const toSvgY = useCallback(
    (difficulty: number) => PADDING.top + (1 - difficulty) * chartHeight,
    [chartHeight]
  );

  // Convert SVG coordinates to data point
  const fromSvgX = useCallback(
    (x: number) => {
      const levelIndex = 1 + ((x - PADDING.left) / chartWidth) * (levelCount - 1);
      return Math.max(1, Math.min(levelCount, Math.round(levelIndex)));
    },
    [levelCount, chartWidth]
  );

  const fromSvgY = useCallback(
    (y: number) => {
      const difficulty = 1 - (y - PADDING.top) / chartHeight;
      return Math.max(0, Math.min(1, difficulty));
    },
    [chartHeight]
  );

  // Get mouse position relative to SVG
  const getMousePos = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };

    const rect = svg.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };
  }, []);

  // Handle click to add new point
  const handleClick = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (dragIndex !== null) return;

      const { x, y } = getMousePos(e);

      // Check if clicking within chart area
      if (
        x < PADDING.left ||
        x > width - PADDING.right ||
        y < PADDING.top ||
        y > height - PADDING.bottom
      ) {
        return;
      }

      // Check if clicking on existing point
      const clickedPointIndex = points.findIndex((p) => {
        const px = toSvgX(p.levelIndex);
        const py = toSvgY(p.difficulty);
        const dist = Math.sqrt((x - px) ** 2 + (y - py) ** 2);
        return dist < POINT_RADIUS * 2;
      });

      if (clickedPointIndex >= 0) return;

      const newPoint: DifficultyPoint = {
        levelIndex: fromSvgX(x),
        difficulty: Math.round(fromSvgY(y) * 100) / 100,
      };

      // Check if a point at this level already exists
      const existingIndex = points.findIndex((p) => p.levelIndex === newPoint.levelIndex);
      if (existingIndex >= 0) {
        // Update existing point
        const newPoints = [...points];
        newPoints[existingIndex] = newPoint;
        onPointsChange(newPoints);
      } else {
        // Add new point
        onPointsChange([...points, newPoint]);
      }
    },
    [points, onPointsChange, getMousePos, fromSvgX, fromSvgY, toSvgX, toSvgY, dragIndex, width, height]
  );

  // Handle double-click to delete point
  const handleDoubleClick = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const { x, y } = getMousePos(e);

      const pointIndex = points.findIndex((p) => {
        const px = toSvgX(p.levelIndex);
        const py = toSvgY(p.difficulty);
        const dist = Math.sqrt((x - px) ** 2 + (y - py) ** 2);
        return dist < POINT_RADIUS * 2;
      });

      if (pointIndex >= 0) {
        const newPoints = points.filter((_, i) => i !== pointIndex);
        onPointsChange(newPoints);
      }
    },
    [points, onPointsChange, getMousePos, toSvgX, toSvgY]
  );

  // Handle mouse down to start dragging
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const { x, y } = getMousePos(e);

      const pointIndex = points.findIndex((p) => {
        const px = toSvgX(p.levelIndex);
        const py = toSvgY(p.difficulty);
        const dist = Math.sqrt((x - px) ** 2 + (y - py) ** 2);
        return dist < POINT_RADIUS * 2;
      });

      if (pointIndex >= 0) {
        setDragIndex(pointIndex);
        e.preventDefault();
      }
    },
    [points, getMousePos, toSvgX, toSvgY]
  );

  // Handle mouse move during drag
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const { x, y } = getMousePos(e);

      // Update hover state
      const hoveredIndex = points.findIndex((p) => {
        const px = toSvgX(p.levelIndex);
        const py = toSvgY(p.difficulty);
        const dist = Math.sqrt((x - px) ** 2 + (y - py) ** 2);
        return dist < POINT_RADIUS * 2;
      });
      setHoverIndex(hoveredIndex >= 0 ? hoveredIndex : null);

      if (dragIndex === null) return;

      const newLevelIndex = fromSvgX(x);
      const newDifficulty = Math.round(fromSvgY(y) * 100) / 100;

      const newPoints = [...points];
      newPoints[dragIndex] = {
        levelIndex: newLevelIndex,
        difficulty: newDifficulty,
      };
      onPointsChange(newPoints);
    },
    [points, dragIndex, onPointsChange, getMousePos, fromSvgX, fromSvgY, toSvgX, toSvgY]
  );

  // Handle mouse up to stop dragging
  const handleMouseUp = useCallback(() => {
    setDragIndex(null);
  }, []);

  // Global mouse up listener for drag release outside SVG
  useEffect(() => {
    const handleGlobalMouseUp = () => setDragIndex(null);
    window.addEventListener('mouseup', handleGlobalMouseUp);
    return () => window.removeEventListener('mouseup', handleGlobalMouseUp);
  }, []);

  // Sort points by levelIndex for line drawing
  const sortedPoints = [...points].sort((a, b) => a.levelIndex - b.levelIndex);

  // Generate path for the line
  const linePath =
    sortedPoints.length > 1
      ? sortedPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${toSvgX(p.levelIndex)} ${toSvgY(p.difficulty)}`).join(' ')
      : '';

  // Generate grade background zones
  const gradeZones = [
    { grade: 'S' as DifficultyGrade, min: 0, max: 0.2 },
    { grade: 'A' as DifficultyGrade, min: 0.2, max: 0.4 },
    { grade: 'B' as DifficultyGrade, min: 0.4, max: 0.6 },
    { grade: 'C' as DifficultyGrade, min: 0.6, max: 0.8 },
    { grade: 'D' as DifficultyGrade, min: 0.8, max: 1.0 },
  ];

  const builtInPresets = presets.filter(p => p.isBuiltIn);
  const customPresets = presets.filter(p => !p.isBuiltIn);

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      {/* Header with preset controls */}
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm font-medium text-gray-300">난이도 그래프</span>
        <div className="flex items-center gap-2">
          {/* Preset selector */}
          <div className="relative">
            <Button
              onClick={() => setShowPresetMenu(!showPresetMenu)}
              variant="secondary"
              size="sm"
            >
              📋 프리셋
            </Button>
            {showPresetMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-gray-700 rounded-lg shadow-xl border border-gray-600 w-64 max-h-80 overflow-y-auto">
                {/* Built-in presets */}
                <div className="p-2 border-b border-gray-600">
                  <span className="text-xs text-gray-400 font-medium">기본 프리셋</span>
                </div>
                {builtInPresets.map(preset => (
                  <button
                    key={preset.id}
                    onClick={() => handlePresetSelect(preset)}
                    className="w-full px-3 py-2 text-left hover:bg-gray-600 transition-colors flex items-center gap-2"
                  >
                    <span className="text-lg">{preset.icon || '📊'}</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-gray-200 truncate">{preset.name}</div>
                      {preset.description && (
                        <div className="text-xs text-gray-400 truncate">{preset.description}</div>
                      )}
                    </div>
                  </button>
                ))}

                {/* Custom presets */}
                {customPresets.length > 0 && (
                  <>
                    <div className="p-2 border-t border-b border-gray-600">
                      <span className="text-xs text-gray-400 font-medium">내 프리셋</span>
                    </div>
                    {customPresets.map(preset => (
                      <button
                        key={preset.id}
                        onClick={() => handlePresetSelect(preset)}
                        className="w-full px-3 py-2 text-left hover:bg-gray-600 transition-colors flex items-center gap-2 group"
                      >
                        <span className="text-lg">⭐</span>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-gray-200 truncate">{preset.name}</div>
                          {preset.description && (
                            <div className="text-xs text-gray-400 truncate">{preset.description}</div>
                          )}
                        </div>
                        <Tooltip content="삭제">
                          <button
                            onClick={(e) => handleDeletePreset(preset.id, e)}
                            className="opacity-0 group-hover:opacity-100 p-1 text-red-400 hover:text-red-300 transition-all"
                          >
                            ✕
                          </button>
                        </Tooltip>
                      </button>
                    ))}
                  </>
                )}

                {/* Close button */}
                <div className="p-2 border-t border-gray-600">
                  <button
                    onClick={() => setShowPresetMenu(false)}
                    className="w-full text-xs text-gray-400 hover:text-gray-300 py-1"
                  >
                    닫기
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Save preset button */}
          <div className="relative">
            <Tooltip content="현재 그래프를 프리셋으로 저장">
              <Button
                onClick={() => setShowSaveDialog(!showSaveDialog)}
                variant="secondary"
                size="sm"
                disabled={points.length === 0}
              >
                💾 저장
              </Button>
            </Tooltip>
            {showSaveDialog && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-gray-700 rounded-lg shadow-xl border border-gray-600 p-3 w-64">
                <div className="text-sm font-medium text-gray-200 mb-2">프리셋 저장</div>
                <input
                  type="text"
                  value={newPresetName}
                  onChange={(e) => setNewPresetName(e.target.value)}
                  placeholder="프리셋 이름"
                  className="w-full px-2 py-1.5 bg-gray-800 border border-gray-600 rounded text-sm text-gray-200 mb-2"
                  autoFocus
                />
                <input
                  type="text"
                  value={newPresetDescription}
                  onChange={(e) => setNewPresetDescription(e.target.value)}
                  placeholder="설명 (선택)"
                  className="w-full px-2 py-1.5 bg-gray-800 border border-gray-600 rounded text-sm text-gray-200 mb-3"
                />
                <div className="flex gap-2">
                  <Button
                    onClick={handleSavePreset}
                    variant="primary"
                    size="sm"
                    className="flex-1"
                    disabled={!newPresetName.trim()}
                  >
                    저장
                  </Button>
                  <Button
                    onClick={() => {
                      setShowSaveDialog(false);
                      setNewPresetName('');
                      setNewPresetDescription('');
                    }}
                    variant="secondary"
                    size="sm"
                  >
                    취소
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Help text */}
      <div className="text-xs text-gray-500 mb-2">
        클릭: 점 추가 | 드래그: 이동 | 더블클릭: 삭제
      </div>

      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="cursor-crosshair"
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {/* Background */}
        <rect x={0} y={0} width={width} height={height} fill="#1f2937" rx={8} />

        {/* Grade zones */}
        {gradeZones.map((zone) => (
          <rect
            key={zone.grade}
            x={PADDING.left}
            y={toSvgY(zone.max)}
            width={chartWidth}
            height={(zone.max - zone.min) * chartHeight}
            fill={getGradeColor(zone.grade)}
            opacity={0.1}
          />
        ))}

        {/* Grid lines - horizontal */}
        {[0, 0.2, 0.4, 0.6, 0.8, 1].map((d) => (
          <g key={d}>
            <line
              x1={PADDING.left}
              y1={toSvgY(d)}
              x2={width - PADDING.right}
              y2={toSvgY(d)}
              stroke="#374151"
              strokeWidth={1}
            />
            <text
              x={PADDING.left - 8}
              y={toSvgY(d) + 4}
              textAnchor="end"
              fill="#9ca3af"
              fontSize={10}
            >
              {Math.round(d * 100)}%
            </text>
          </g>
        ))}

        {/* Grid lines - vertical */}
        {Array.from({ length: Math.min(levelCount, 10) + 1 }, (_, i) => {
          const levelIndex = Math.round(1 + (i * (levelCount - 1)) / Math.min(levelCount - 1, 10));
          return (
            <g key={i}>
              <line
                x1={toSvgX(levelIndex)}
                y1={PADDING.top}
                x2={toSvgX(levelIndex)}
                y2={height - PADDING.bottom}
                stroke="#374151"
                strokeWidth={1}
              />
              <text
                x={toSvgX(levelIndex)}
                y={height - PADDING.bottom + 16}
                textAnchor="middle"
                fill="#9ca3af"
                fontSize={10}
              >
                {levelIndex}
              </text>
            </g>
          );
        })}

        {/* Axis labels */}
        <text
          x={width / 2}
          y={height - 5}
          textAnchor="middle"
          fill="#9ca3af"
          fontSize={11}
        >
          레벨
        </text>
        <text
          x={12}
          y={height / 2}
          textAnchor="middle"
          fill="#9ca3af"
          fontSize={11}
          transform={`rotate(-90, 12, ${height / 2})`}
        >
          난이도
        </text>

        {/* Line connecting points */}
        {linePath && (
          <path
            d={linePath}
            fill="none"
            stroke="#60a5fa"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {/* Points */}
        {sortedPoints.map((point) => {
          const originalIndex = points.findIndex(
            (p) => p.levelIndex === point.levelIndex && p.difficulty === point.difficulty
          );
          const isHovered = hoverIndex === originalIndex;
          const isDragging = dragIndex === originalIndex;
          const grade = getGradeFromDifficulty(point.difficulty);
          const color = getGradeColor(grade);

          return (
            <g key={`${point.levelIndex}-${point.difficulty}`}>
              {/* Glow effect */}
              <circle
                cx={toSvgX(point.levelIndex)}
                cy={toSvgY(point.difficulty)}
                r={(isHovered || isDragging ? POINT_HOVER_RADIUS : POINT_RADIUS) + 4}
                fill={color}
                opacity={0.3}
              />
              {/* Point */}
              <circle
                cx={toSvgX(point.levelIndex)}
                cy={toSvgY(point.difficulty)}
                r={isHovered || isDragging ? POINT_HOVER_RADIUS : POINT_RADIUS}
                fill={color}
                stroke="#fff"
                strokeWidth={2}
                className="cursor-grab"
                style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
              />
              {/* Label */}
              {(isHovered || isDragging) && (
                <text
                  x={toSvgX(point.levelIndex)}
                  y={toSvgY(point.difficulty) - 15}
                  textAnchor="middle"
                  fill="#fff"
                  fontSize={11}
                  fontWeight="bold"
                >
                  Lv.{point.levelIndex}: {Math.round(point.difficulty * 100)}%
                </text>
              )}
            </g>
          );
        })}

        {/* Chart border */}
        <rect
          x={PADDING.left}
          y={PADDING.top}
          width={chartWidth}
          height={chartHeight}
          fill="none"
          stroke="#4b5563"
          strokeWidth={1}
        />
      </svg>

      {/* Points summary */}
      <div className="mt-2 flex flex-wrap gap-1">
        {sortedPoints.map((point) => {
          const grade = getGradeFromDifficulty(point.difficulty);
          return (
            <span
              key={`${point.levelIndex}-${point.difficulty}`}
              className="px-2 py-0.5 text-xs rounded"
              style={{ backgroundColor: getGradeColor(grade), color: '#fff' }}
            >
              Lv.{point.levelIndex}: {grade}
            </span>
          );
        })}
        {sortedPoints.length === 0 && (
          <span className="text-xs text-gray-500">그래프를 클릭하여 점을 추가하세요</span>
        )}
      </div>
    </div>
  );
}

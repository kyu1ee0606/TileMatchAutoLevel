/**
 * SlotArea - 선택된 타일이 모이는 슬롯 영역
 */
import React from 'react';
import type { SlotTile } from '../../types/game';
import { TILE_COLORS } from '../../types/game';

interface SlotAreaProps {
  slots: SlotTile[];
  maxSlots: number;
  tileSize?: number;
  onSlotClick?: (index: number) => void;
  lockedSlots?: number;  // unlockTile: 잠긴 슬롯 수 (뒤에서부터)
}

// 타일 이미지 경로
const getTileImagePath = (type: string, skinId: number = 0): string => {
  if (type.startsWith('craft_')) {
    return '/tiles/special/tile_craft.png';
  }
  if (type.startsWith('stack_')) {
    const dir = type.split('_')[1] || 's';
    return `/tiles/special/stack_${dir}.png`;
  }
  return `/tiles/skin${skinId}/s${skinId}_${type}.png`;
};

export function SlotArea({
  slots,
  maxSlots,
  tileSize = 48,
  onSlotClick,
  lockedSlots = 0,
}: SlotAreaProps) {
  // 실제 사용 가능한 슬롯 수 (잠긴 슬롯 제외)
  const availableSlots = maxSlots - lockedSlots;
  // Group consecutive same-type tiles for visual feedback
  const groupedSlots = React.useMemo(() => {
    const groups: { type: string; count: number; startIndex: number }[] = [];
    let currentType = '';
    let currentCount = 0;
    let startIndex = 0;

    slots.forEach((slot, index) => {
      if (slot.type === currentType) {
        currentCount++;
      } else {
        if (currentCount >= 2 && currentType) {
          groups.push({ type: currentType, count: currentCount, startIndex });
        }
        currentType = slot.type;
        currentCount = 1;
        startIndex = index;
      }
    });

    if (currentCount >= 2 && currentType) {
      groups.push({ type: currentType, count: currentCount, startIndex });
    }

    return groups;
  }, [slots]);

  // Check if index is part of a matching group
  const isInMatchingGroup = (index: number) => {
    return groupedSlots.some(
      g => index >= g.startIndex && index < g.startIndex + g.count && g.count >= 3
    );
  };

  // Check if we're about to match (2 same tiles in a row)
  const isAboutToMatch = (index: number) => {
    return groupedSlots.some(
      g => index >= g.startIndex && index < g.startIndex + g.count && g.count === 2
    );
  };

  const slotsUsed = slots.length;
  const isFull = slotsUsed >= availableSlots;  // 잠긴 슬롯 제외한 사용 가능 슬롯 기준

  return (
    <div className="slot-area">
      {/* Slot container */}
      <div
        className={`
          flex items-center justify-center gap-1 p-3 rounded-xl
          ${isFull ? 'bg-red-900/50 border-2 border-red-500' : 'bg-gray-800/80'}
          transition-colors duration-200
        `}
        style={{
          minWidth: maxSlots * (tileSize + 8) + 24,
        }}
      >
        {/* Render slots */}
        {Array.from({ length: maxSlots }).map((_, index) => {
          const slot = slots[index];
          const isEmpty = !slot;
          const matching = slot && isInMatchingGroup(index);
          const almostMatching = slot && isAboutToMatch(index);
          const isLocked = index >= availableSlots;  // 뒤에서부터 잠긴 슬롯

          return (
            <div
              key={index}
              className={`
                relative rounded-lg overflow-hidden transition-all duration-150
                ${isLocked ? 'bg-amber-900/60 border-2 border-amber-600' :
                  isEmpty ? 'bg-gray-700/50 border-2 border-dashed border-gray-600' : 'bg-gray-700'}
                ${matching ? 'ring-2 ring-green-400 animate-pulse' : ''}
                ${almostMatching ? 'ring-2 ring-yellow-400' : ''}
              `}
              style={{
                width: tileSize,
                height: tileSize,
              }}
              onClick={() => !isLocked && onSlotClick?.(index)}
            >
              {/* 잠긴 슬롯 표시 */}
              {isLocked && (
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <img
                    src="/tiles/special/item_key.png"
                    alt="locked"
                    className="w-6 h-6 opacity-60"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />
                  <div className="text-amber-400 text-[10px] mt-0.5">🔒</div>
                </div>
              )}

              {slot && !isLocked && (
                <>
                  {/* Base background */}
                  <img
                    src="/tiles/skin0/s0_t0.png"
                    alt=""
                    className="absolute inset-0 w-full h-full object-contain"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />

                  {/* Tile image */}
                  <img
                    src={getTileImagePath(slot.type)}
                    alt={slot.type}
                    className="absolute inset-0 w-full h-full object-contain"
                    onError={(e) => {
                      // Fallback to colored div
                      const img = e.target as HTMLImageElement;
                      img.style.display = 'none';
                      const fallbackColor = TILE_COLORS[slot.type] || TILE_COLORS.t0;
                      const parent = img.parentElement;
                      if (parent) {
                        const fallback = document.createElement('div');
                        fallback.style.cssText = `
                          width: 100%;
                          height: 100%;
                          background-color: ${fallbackColor};
                          border-radius: 6px;
                          position: absolute;
                          top: 0;
                          left: 0;
                        `;
                        parent.appendChild(fallback);
                      }
                    }}
                  />

                  {/* Match indicator */}
                  {matching && (
                    <div className="absolute inset-0 bg-green-400/30 animate-pulse" />
                  )}
                </>
              )}

              {/* Empty slot number (not locked) */}
              {isEmpty && !isLocked && (
                <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-xs">
                  {index + 1}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Status text */}
      <div className="text-center mt-2 text-sm">
        {isFull ? (
          <span className="text-red-400 font-bold">Slots Full! Game Over</span>
        ) : lockedSlots > 0 ? (
          <span className="text-gray-400">
            {slotsUsed} / {availableSlots} slots used
            <span className="text-amber-400 ml-2">🔒 {lockedSlots} locked</span>
          </span>
        ) : (
          <span className="text-gray-400">
            {slotsUsed} / {maxSlots} slots used
          </span>
        )}
      </div>
    </div>
  );
}

export default SlotArea;

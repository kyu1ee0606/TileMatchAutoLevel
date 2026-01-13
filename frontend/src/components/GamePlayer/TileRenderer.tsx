/**
 * TileRenderer - 개별 타일 렌더링 컴포넌트
 */
import React from 'react';
import type { GameTile } from '../../types/game';
import { TILE_COLORS, isSpecialTile } from '../../types/game';

interface TileRendererProps {
  tile: GameTile;
  size: number;
  onClick?: (tile: GameTile) => void;
  showDebug?: boolean;
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

// 속성 오버레이 이미지 경로
const getAttributeImagePath = (attribute: string): string | null => {
  const attrMap: Record<string, string> = {
    chain: '/tiles/special/tile_chain.png',
    frog: '/tiles/special/frog.png',
    ice: '/tiles/special/tile_ice_1.png',
    ice_1: '/tiles/special/tile_ice_1.png',
    ice_2: '/tiles/special/tile_ice_2.png',
    ice_3: '/tiles/special/tile_ice_3.png',
    grass: '/tiles/special/tile_grass.png',
    grass_1: '/tiles/special/tile_grass.png',
    grass_2: '/tiles/special/tile_grass.png',
    bomb: '/tiles/special/bomb.png',
    link: '/tiles/special/tile_link.png',
    link_n: '/tiles/special/tile_link_n.png',
    link_s: '/tiles/special/tile_link_s.png',
    link_e: '/tiles/special/tile_link_e.png',
    link_w: '/tiles/special/tile_link_w.png',
    unknown: '/tiles/special/tile_unknown.png',
    curtain: '/tiles/special/curtain_close.png',
    curtain_close: '/tiles/special/curtain_close.png',
    curtain_open: '/tiles/special/curtain_open.png',
    teleport: '/tiles/special/teleport.png',
  };
  return attrMap[attribute] || null;
};

export function TileRenderer({ tile, size, onClick, showDebug }: TileRendererProps) {
  const handleClick = () => {
    if (tile.isSelectable && onClick) {
      onClick(tile);
    }
  };

  const baseStyle: React.CSSProperties = {
    width: size,
    height: size,
    position: 'relative',
    cursor: tile.isSelectable ? 'pointer' : 'not-allowed',
    opacity: tile.isMatched ? 0 : tile.isSelectable ? 1 : 0.6,
    transition: 'all 0.15s ease',
    transform: tile.isSelected ? 'scale(1.1)' : 'scale(1)',
    zIndex: tile.isSelected ? 100 : tile.layer,
  };

  const tileImageStyle: React.CSSProperties = {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    position: 'absolute',
    top: 0,
    left: 0,
  };

  const overlayStyle: React.CSSProperties = {
    ...tileImageStyle,
    opacity: 0.9,
  };

  const selectionRingStyle: React.CSSProperties = {
    position: 'absolute',
    top: -2,
    left: -2,
    right: -2,
    bottom: -2,
    border: '3px solid #fbbf24',
    borderRadius: 8,
    boxShadow: '0 0 10px rgba(251, 191, 36, 0.5)',
    pointerEvents: 'none',
  };

  const debugStyle: React.CSSProperties = {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    fontSize: 8,
    backgroundColor: 'rgba(0,0,0,0.7)',
    color: 'white',
    textAlign: 'center',
    padding: '1px 2px',
  };

  // Fallback color if image doesn't load
  const fallbackColor = TILE_COLORS[tile.type] || TILE_COLORS.t0;

  return (
    <div
      style={baseStyle}
      onClick={handleClick}
      className={`tile-renderer ${tile.isSelectable ? 'selectable' : ''} ${tile.isSelected ? 'selected' : ''}`}
    >
      {/* Base tile background (t0) */}
      <img
        src="/tiles/skin0/s0_t0.png"
        alt=""
        style={tileImageStyle}
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = 'none';
        }}
      />

      {/* Main tile image */}
      <img
        src={getTileImagePath(tile.type)}
        alt={tile.type}
        style={tileImageStyle}
        onError={(e) => {
          // Fallback to colored div
          const img = e.target as HTMLImageElement;
          img.style.display = 'none';
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

      {/* Attribute overlay */}
      {tile.attribute && getAttributeImagePath(tile.attribute) && (
        <img
          src={getAttributeImagePath(tile.attribute)!}
          alt={tile.attribute}
          style={overlayStyle}
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = 'none';
          }}
        />
      )}

      {/* Hidden overlay (unknown/curtain) */}
      {tile.isHidden && (
        <div
          style={{
            ...tileImageStyle,
            backgroundColor: 'rgba(0,0,0,0.8)',
            borderRadius: 6,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white',
            fontSize: size * 0.4,
          }}
        >
          ?
        </div>
      )}

      {/* Selection ring */}
      {tile.isSelected && <div style={selectionRingStyle} />}

      {/* Craft/Stack indicator */}
      {isSpecialTile(tile.type) && tile.extra && tile.extra[0] > 1 && (
        <div
          style={{
            position: 'absolute',
            top: 2,
            right: 2,
            backgroundColor: '#8b5cf6',
            color: 'white',
            fontSize: 10,
            fontWeight: 'bold',
            padding: '1px 4px',
            borderRadius: 4,
          }}
        >
          x{tile.extra[0]}
        </div>
      )}

      {/* Debug info */}
      {showDebug && (
        <div style={debugStyle}>
          L{tile.layer} {tile.row},{tile.col}
        </div>
      )}
    </div>
  );
}

export default TileRenderer;

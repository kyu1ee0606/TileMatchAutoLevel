/**
 * TileRenderer - 개별 타일 렌더링 컴포넌트
 * 기믹 상태 표시 포함 (시뮬레이션과 동일한 방식)
 */
import React from 'react';
import type { GameTile } from '../../types/game';
import { TILE_COLORS, isSpecialTile } from '../../types/game';
import clsx from 'clsx';

interface TileRendererProps {
  tile: GameTile;
  size: number;
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

export function TileRenderer({ tile, size, showDebug }: TileRendererProps) {

  // Extract gimmick states from effectData
  const effectData = tile.effectData || {};
  const attribute = tile.attribute || '';

  // Ice gimmick
  const isIce = attribute === 'ice' || attribute.startsWith('ice');
  const iceRemaining = effectData.remaining;
  const iceLevel = isIce ? (iceRemaining ?? 3) : 0;

  // Chain gimmick
  const isChain = attribute === 'chain';
  const isChainUnlocked = effectData.unlocked === true;

  // Grass gimmick
  const isGrass = attribute === 'grass' || attribute.startsWith('grass');
  const grassRemaining = effectData.remaining;
  const grassLevel = isGrass ? (grassRemaining ?? 1) : 0;

  // Bomb gimmick
  const isBomb = attribute === 'bomb';
  const bombRemaining = effectData.remaining;

  // Link gimmick
  const isLink = attribute.startsWith('link_');
  const canPickLink = effectData.canPick === true;

  // Curtain gimmick
  const isCurtain = attribute.startsWith('curtain');
  const isCurtainOpen = effectData.isOpen === true;

  // Frog gimmick
  const hasFrog = effectData.onFrog === true;

  // Teleport gimmick
  const isTeleport = attribute === 'teleport';

  // Check if any gimmick is active (for border styling)
  const hasActiveGimmick = (isIce && iceLevel > 0) || isChain || (isGrass && grassLevel > 0) ||
    isLink || isBomb || isCurtain || isTeleport;

  // Get gimmick border color
  const getGimmickBorderColor = () => {
    if (isIce && iceLevel > 0) return `rgba(96, 165, 250, ${0.5 + iceLevel * 0.15})`;
    if (isChain) return isChainUnlocked ? 'rgba(74, 222, 128, 0.6)' : 'rgba(161, 161, 170, 0.6)';
    if (isGrass && grassLevel > 0) return `rgba(34, 197, 94, ${0.5 + grassLevel * 0.15})`;
    if (isLink) return canPickLink ? 'rgba(74, 222, 128, 0.6)' : 'rgba(234, 179, 8, 0.6)';
    if (isBomb) return bombRemaining !== undefined && bombRemaining <= 3 ? 'rgba(239, 68, 68, 0.8)' : 'rgba(239, 68, 68, 0.5)';
    if (isCurtain) return isCurtainOpen ? 'rgba(168, 85, 247, 0.4)' : 'rgba(124, 58, 237, 0.6)';
    if (isTeleport) return 'rgba(6, 182, 212, 0.6)';
    return 'transparent';
  };

  const baseStyle: React.CSSProperties = {
    width: size,
    height: size,
    position: 'relative',
    cursor: tile.isSelectable ? 'pointer' : 'not-allowed',
    opacity: tile.isMatched ? 0 : 1,  // 매치된 타일만 숨김, 나머지는 불투명
    transition: 'all 0.15s ease',
    transform: tile.isSelected ? 'scale(1.1)' : 'scale(1)',
    zIndex: tile.isSelected ? 100 : tile.layer,
    border: hasActiveGimmick ? `2px solid ${getGimmickBorderColor()}` : undefined,
    borderRadius: 4,
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

  // Badge style for gimmick indicators
  const badgeStyle: React.CSSProperties = {
    position: 'absolute',
    bottom: 0,
    left: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderTopRightRadius: 4,
    fontSize: size * 0.2,
    padding: '1px 3px',
    zIndex: 20,
  };

  // Fallback color if image doesn't load
  const fallbackColor = TILE_COLORS[tile.type] || TILE_COLORS.t0;

  // Determine if attribute image should be hidden
  // Frog overlay is handled separately based on effectData.onFrog
  // Chain overlay is hidden when unlocked
  const isFrogAttribute = attribute === 'frog';
  const shouldHideAttribute = (isGrass && grassLevel <= 0) || (isIce && iceLevel <= 0) || isTeleport || isFrogAttribute || (isChain && isChainUnlocked);

  return (
    <div
      style={baseStyle}
      className={clsx(
        'tile-renderer',
        tile.isSelectable && 'selectable',
        tile.isSelected && 'selected',
        isCurtain && !isCurtainOpen && 'grayscale',
        isBomb && bombRemaining !== undefined && bombRemaining <= 3 && 'animate-pulse',
        hasFrog && 'ring-2 ring-green-400'
      )}
    >
      {/* Base tile background (t0) - hidden 타일에도 표시 */}
      <img
        src="/tiles/skin0/s0_t0.png"
        alt=""
        style={tileImageStyle}
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = 'none';
        }}
      />

      {/* Main tile image - hidden 타일은 타입을 숨김 */}
      {!tile.isHidden && (
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
      )}

      {/* Attribute overlay (hide when gimmick is removed) */}
      {tile.attribute && !shouldHideAttribute && getAttributeImagePath(tile.attribute) && (
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

      {/* Gray mask for non-selectable tiles */}
      {!tile.isSelectable && !tile.isMatched && !tile.isHidden && (
        <div
          style={{
            ...tileImageStyle,
            backgroundColor: 'rgba(0, 0, 0, 0.4)',
            borderRadius: 6,
          }}
        />
      )}

      {/* Ice gimmick badge */}
      {isIce && iceLevel > 0 && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: 'rgba(96, 165, 250, 0.8)',
            color: 'white',
          }}
          className={clsx(iceLevel === 1 && 'animate-pulse')}
          title={`얼음 ${iceLevel}단계`}
        >
          ❄️{iceLevel}
        </div>
      )}

      {/* Chain gimmick badge */}
      {isChain && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: isChainUnlocked ? 'rgba(74, 222, 128, 0.8)' : 'rgba(107, 114, 128, 0.8)',
            color: 'white',
          }}
          title={isChainUnlocked ? '체인 해제됨' : '체인 잠김'}
        >
          {isChainUnlocked ? '🔓' : '⛓️'}
        </div>
      )}

      {/* Grass gimmick badge */}
      {isGrass && grassLevel > 0 && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: 'rgba(34, 197, 94, 0.8)',
            color: 'white',
          }}
          className={clsx(grassLevel === 1 && 'animate-pulse')}
          title={`풀 ${grassLevel}단계`}
        >
          {grassLevel === 1 ? '🌱' : '🌿'}{grassLevel}
        </div>
      )}

      {/* Bomb gimmick badge */}
      {isBomb && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: bombRemaining !== undefined && bombRemaining <= 2
              ? 'rgba(239, 68, 68, 0.9)'
              : bombRemaining !== undefined && bombRemaining <= 5
                ? 'rgba(249, 115, 22, 0.8)'
                : 'rgba(107, 114, 128, 0.8)',
            color: 'white',
          }}
          className={clsx(bombRemaining !== undefined && bombRemaining <= 2 && 'animate-pulse')}
          title={`폭탄 ${bombRemaining ?? '?'}턴`}
        >
          💣{bombRemaining ?? '?'}
        </div>
      )}

      {/* Link gimmick badge */}
      {isLink && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: canPickLink ? 'rgba(74, 222, 128, 0.8)' : 'rgba(234, 179, 8, 0.8)',
            color: 'white',
          }}
          title={canPickLink ? '링크 선택 가능' : '링크 잠김'}
        >
          🔗
        </div>
      )}

      {/* Curtain gimmick badge */}
      {isCurtain && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: isCurtainOpen ? 'rgba(168, 85, 247, 0.8)' : 'rgba(124, 58, 237, 0.8)',
            color: 'white',
          }}
          title={isCurtainOpen ? '커튼 열림' : '커튼 닫힘'}
        >
          {isCurtainOpen ? '🎭' : '🎪'}
        </div>
      )}

      {/* Teleport gimmick badge */}
      {isTeleport && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: 'rgba(6, 182, 212, 0.8)',
            color: 'white',
          }}
          title="텔레포트"
        >
          🌀
        </div>
      )}

      {/* Frog overlay image (follows effectData.onFrog) */}
      {hasFrog && (
        <img
          src="/tiles/special/frog.png"
          alt="frog"
          style={overlayStyle}
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = 'none';
          }}
        />
      )}

      {/* Frog indicator badge (bottom right) */}
      {hasFrog && (
        <div
          style={{
            position: 'absolute',
            bottom: 0,
            right: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderTopLeftRadius: 4,
            backgroundColor: 'rgba(34, 197, 94, 0.8)',
            fontSize: size * 0.2,
            padding: '1px 3px',
            zIndex: 20,
          }}
          title="개구리"
        >
          🐸
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

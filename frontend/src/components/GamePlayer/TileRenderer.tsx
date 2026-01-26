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

  // Stack tile visual info - ONLY for stack tiles, NOT craft tiles
  // Craft tiles should only show badge on the craft BOX, not on spawned tiles
  const isStackTile = tile.isStackTile === true;
  const isCraftTile = tile.isCraftTile === true;
  const stackIndex = tile.stackIndex ?? -1;
  const stackMaxIndex = tile.stackMaxIndex ?? -1;
  // Calculate remaining tiles in stack (including current tile)
  const stackRemainingCount = isStackTile && !isCraftTile && stackIndex >= 0 && stackMaxIndex >= 0
    ? stackMaxIndex - stackIndex + 1
    : 0;
  // Show stack effect only for STACK tiles (not craft) with more underneath (remaining > 1)
  const showStackEffect = isStackTile && !isCraftTile && stackRemainingCount > 1;

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
  // Gimmick overlays are hidden when:
  // - Frog: handled separately based on effectData.onFrog
  // - Chain: when unlocked
  // - Ice/Grass: when remaining <= 0
  // - Link: when canPick is true (link unlocked)
  // - Unknown: when tile is selectable (unknown revealed)
  // - Curtain: when open (handled specially below)
  // - Teleport: always hidden (shown as badge only)
  const isFrogAttribute = attribute === 'frog';
  const isUnknown = attribute === 'unknown';
  const shouldHideAttribute =
    (isGrass && grassLevel <= 0) ||
    (isIce && iceLevel <= 0) ||
    isTeleport ||
    isFrogAttribute ||
    (isChain && isChainUnlocked) ||
    (isLink && canPickLink) ||
    (isUnknown && tile.isSelectable) ||
    (isCurtain && isCurtainOpen);

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
      {/* Stack effect - tile-like shadow copies behind (TileBuster style) */}
      {showStackEffect && (
        <>
          {/* Show up to 3 stacked tile layers based on remaining count */}
          {stackRemainingCount >= 4 && (
            <div
              style={{
                position: 'absolute',
                top: 6,
                left: 6,
                width: size,
                height: size,
                borderRadius: 6,
                zIndex: -3,
                overflow: 'hidden',
                filter: 'brightness(0.5)',
              }}
            >
              <img
                src="/tiles/skin0/s0_t0.png"
                alt=""
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </div>
          )}
          {stackRemainingCount >= 3 && (
            <div
              style={{
                position: 'absolute',
                top: 4,
                left: 4,
                width: size,
                height: size,
                borderRadius: 6,
                zIndex: -2,
                overflow: 'hidden',
                filter: 'brightness(0.65)',
              }}
            >
              <img
                src="/tiles/skin0/s0_t0.png"
                alt=""
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </div>
          )}
          {stackRemainingCount >= 2 && (
            <div
              style={{
                position: 'absolute',
                top: 2,
                left: 2,
                width: size,
                height: size,
                borderRadius: 6,
                zIndex: -1,
                overflow: 'hidden',
                filter: 'brightness(0.8)',
              }}
            >
              <img
                src="/tiles/skin0/s0_t0.png"
                alt=""
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </div>
          )}
        </>
      )}

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

      {/* Link gimmick badge with direction (hidden when unlocked) */}
      {isLink && !canPickLink && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: 'rgba(234, 179, 8, 0.8)',
            color: 'white',
          }}
          title={`링크 잠김 (${attribute === 'link_n' ? '위' : attribute === 'link_s' ? '아래' : attribute === 'link_e' ? '오른쪽' : '왼쪽'})`}
        >
          🔗
        </div>
      )}

      {/* Link direction arrow indicator (always visible for link tiles) */}
      {isLink && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            fontSize: size * 0.4,
            color: canPickLink ? 'rgba(74, 222, 128, 0.9)' : 'rgba(234, 179, 8, 0.9)',
            textShadow: '0 0 4px rgba(0,0,0,0.9), 0 0 8px rgba(0,0,0,0.6)',
            fontWeight: 'bold',
            zIndex: 15,
            pointerEvents: 'none',
          }}
          title={`연결 방향: ${attribute === 'link_n' ? '위' : attribute === 'link_s' ? '아래' : attribute === 'link_e' ? '오른쪽' : '왼쪽'}`}
        >
          {attribute === 'link_s' && '↓'}
          {attribute === 'link_n' && '↑'}
          {attribute === 'link_e' && '→'}
          {attribute === 'link_w' && '←'}
        </div>
      )}

      {/* Curtain gimmick badge (hidden when open) */}
      {isCurtain && !isCurtainOpen && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: 'rgba(124, 58, 237, 0.8)',
            color: 'white',
          }}
          title="커튼 닫힘"
        >
          🎪
        </div>
      )}

      {/* Unknown gimmick badge (hidden when revealed/selectable) */}
      {isUnknown && !tile.isSelectable && (
        <div
          style={{
            ...badgeStyle,
            backgroundColor: 'rgba(107, 114, 128, 0.8)',
            color: 'white',
          }}
          title="미공개 타일"
        >
          ❓
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

      {/* Craft direction arrow indicator */}
      {tile.type.startsWith('craft_') && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            fontSize: size * 0.35,
            color: 'white',
            textShadow: '0 0 3px rgba(0,0,0,0.8), 0 0 6px rgba(0,0,0,0.5)',
            zIndex: 15,
            pointerEvents: 'none',
          }}
        >
          {tile.type === 'craft_s' && '↓'}
          {tile.type === 'craft_n' && '↑'}
          {tile.type === 'craft_e' && '→'}
          {tile.type === 'craft_w' && '←'}
        </div>
      )}

      {/* Top tile indicator for stack boxes (TileBuster style) */}
      {tile.type.startsWith('stack_') && effectData.currentTileType && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            width: size * 0.6,
            height: size * 0.6,
            borderRadius: 4,
            overflow: 'hidden',
            zIndex: 10,
            boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
          }}
        >
          <img
            src={getTileImagePath(effectData.currentTileType)}
            alt={effectData.currentTileType}
            style={{ width: '100%', height: '100%', objectFit: 'contain' }}
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
        </div>
      )}

      {/* Craft/Stack count indicator (for box tiles) */}
      {/* remaining: 남은 배출 횟수 (count=3, 첫 스폰 후 remaining=2) */}
      {isSpecialTile(tile.type) && tile.extra && tile.extra[0] >= 1 && (
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

      {/* Stack remaining count indicator (for spawned stack tiles) */}
      {showStackEffect && (
        <div
          style={{
            position: 'absolute',
            bottom: 2,
            right: 2,
            backgroundColor: 'rgba(139, 92, 246, 0.9)',
            color: 'white',
            fontSize: 9,
            fontWeight: 'bold',
            padding: '1px 4px',
            borderRadius: 4,
            zIndex: 25,
          }}
          title={`남은 타일: ${stackRemainingCount}`}
        >
          x{stackRemainingCount}
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

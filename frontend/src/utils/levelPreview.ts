/**
 * 레벨 미리보기 캔버스 렌더러 (공유) — 플레이테스트(GamePlayer/TileRenderer)와 동일한 합성 규칙.
 * RL 시뮬레이션 탭과 솔버블 검증 탭에서 공통 사용.
 *
 * 합성 순서: t0 배경 → 타입 이미지(craft/stack/key 특수 경로) → 속성 오버레이 → 화살표/아이콘.
 * 홀수 레이어 0.5칸 오프셋, 아래 레이어부터 그려 위 레이어가 덮는 인게임 스택 표현.
 */
import type { LevelJSON } from '../types';
import { TILE_TYPES } from '../types';
import { resolveT0TileTypes } from '../engine/gameEngine';

// 미리보기용 타일 이미지 캐시 (경로 → 로드된 이미지, 실패 시 null)
const previewImageCache = new Map<string, HTMLImageElement | null>();

function loadPreviewImage(src: string): Promise<HTMLImageElement | null> {
  if (previewImageCache.has(src)) {
    return Promise.resolve(previewImageCache.get(src) ?? null);
  }
  return new Promise(resolve => {
    const img = new Image();
    img.onload = () => { previewImageCache.set(src, img); resolve(img); };
    img.onerror = () => { previewImageCache.set(src, null); resolve(null); };
    img.src = src;
  });
}

const PREVIEW_BASE_TILE = '/tiles/skin0/s0_t0.png';
const PREVIEW_KEY_ICON = '/tiles/special/item_key.png';

function previewTileImagePath(type: string): string {
  if (type.startsWith('craft_')) return '/tiles/special/tile_craft.png';
  if (type.startsWith('stack_')) return `/tiles/special/stack_${type.split('_')[1] || 's'}.png`;
  if (type === 'key') return PREVIEW_BASE_TILE; // 열쇠는 t0 배경 + 아이콘 오버레이
  return `/tiles/skin0/s0_${type}.png`;
}

const PREVIEW_ATTR_IMAGES: Record<string, string> = {
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

const PREVIEW_DIR_ARROWS: Record<string, string> = { s: '↓', n: '↑', e: '→', w: '←' };

export async function renderLevelCanvasPreview(lv: LevelJSON, size = 420): Promise<string | null> {
  const layerCount = Number(lv.layer) || 0;
  const tiles: { layer: number; x: number; y: number; type: string; attr: string }[] = [];
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;

  // t0 셀을 인게임/플레이테스트와 동일한 비주얼 선정(visualTileSeed 반영)으로 해소.
  // 실패해도 미리보기는 t0 배경으로 폴백.
  let t0Map: Map<string, string>;
  try {
    t0Map = resolveT0TileTypes(lv as unknown as Record<string, unknown>);
  } catch {
    t0Map = new Map();
  }

  for (let i = 0; i < layerCount; i++) {
    const ld = (lv as unknown as Record<string, unknown>)[`layer_${i}`] as
      | { tiles?: Record<string, [string, string?]> }
      | undefined;
    if (!ld?.tiles) continue;
    for (const [pos, d] of Object.entries(ld.tiles)) {
      if (!Array.isArray(d)) continue;
      const [xs, ys] = pos.split('_');
      const x = parseInt(xs, 10);
      const y = parseInt(ys, 10);
      if (Number.isNaN(x) || Number.isNaN(y)) continue;
      const rawType = String(d[0] ?? '');
      // 평면 t0 → 분배된 실제 스프라이트 타입 (인게임 동일). craft_/stack_은 전용 경로라 그대로.
      const resolvedType = rawType === 't0' ? (t0Map.get(`${i}_${pos}`) ?? rawType) : rawType;
      tiles.push({ layer: i, x, y, type: resolvedType, attr: String(d[1] ?? '') });
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
  }
  if (tiles.length === 0) return null;

  tiles.sort((a, b) => a.layer - b.layer); // 아래 레이어부터 그려서 위 레이어가 덮음

  // 필요한 이미지 일괄 로드 (캐시 재사용)
  const srcs = new Set<string>([PREVIEW_BASE_TILE]);
  for (const t of tiles) {
    srcs.add(previewTileImagePath(t.type));
    if (t.type === 'key') srcs.add(PREVIEW_KEY_ICON);
    if (t.attr && PREVIEW_ATTR_IMAGES[t.attr]) srcs.add(PREVIEW_ATTR_IMAGES[t.attr]);
  }
  await Promise.all([...srcs].map(loadPreviewImage));

  const gridW = maxX - minX + 1.5; // 홀수 레이어 0.5칸 오프셋 여유
  const gridH = maxY - minY + 1.5;
  const cell = Math.max(8, Math.floor(size / Math.max(gridW, gridH)));
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(gridW * cell);
  canvas.height = Math.ceil(gridH * cell);
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  ctx.fillStyle = '#111827';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const fallbackPalette = ['#f87171', '#4ade80', '#60a5fa', '#c084fc', '#fbbf24', '#34d399', '#f472b6', '#a3a3a3'];

  for (const t of tiles) {
    const offset = t.layer % 2 === 1 ? cell * 0.5 : 0;
    const px = (t.x - minX) * cell + offset;
    const py = (t.y - minY) * cell + offset;

    // 1) t0 배경 (모든 타일의 베이스)
    const baseImg = previewImageCache.get(PREVIEW_BASE_TILE);
    if (baseImg) ctx.drawImage(baseImg, px, py, cell, cell);

    // 2) 메인 타입 이미지 (craft/stack/key는 전용 경로)
    const mainSrc = previewTileImagePath(t.type);
    const mainImg = previewImageCache.get(mainSrc);
    if (mainImg) {
      ctx.drawImage(mainImg, px, py, cell, cell);
    } else if (!baseImg) {
      let color = TILE_TYPES[t.type]?.color;
      if (!color) {
        const n = parseInt(t.type.replace(/\D/g, ''), 10);
        color = fallbackPalette[(Number.isNaN(n) ? 0 : n) % fallbackPalette.length];
      }
      ctx.fillStyle = color;
      ctx.fillRect(px + 1, py + 1, cell - 2, cell - 2);
      ctx.strokeStyle = 'rgba(0,0,0,0.6)';
      ctx.strokeRect(px + 1, py + 1, cell - 2, cell - 2);
    }

    // 3) 열쇠 타일 아이콘 (70% 크기 중앙)
    if (t.type === 'key') {
      const keyImg = previewImageCache.get(PREVIEW_KEY_ICON);
      if (keyImg) {
        ctx.drawImage(keyImg, px + cell * 0.15, py + cell * 0.15, cell * 0.7, cell * 0.7);
      }
    }

    // 4) 속성 오버레이 (opacity 0.9)
    if (t.attr) {
      const attrSrc = PREVIEW_ATTR_IMAGES[t.attr];
      const attrImg = attrSrc ? previewImageCache.get(attrSrc) : null;
      if (attrImg) {
        ctx.globalAlpha = 0.9;
        ctx.drawImage(attrImg, px, py, cell, cell);
        ctx.globalAlpha = 1;
      } else if (cell >= 12) {
        const badge: Record<string, string> = {
          curtain: '🎪', curtain_close: '🎪', curtain_open: '🎪',
          teleport: '🌀', frog: '🐸', bomb: '💣', unknown: '❓',
        };
        const emoji = badge[t.attr];
        ctx.font = `${Math.floor(cell * 0.45)}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        if (emoji) {
          ctx.fillText(emoji, px + cell / 2, py + cell / 2);
        } else {
          ctx.fillStyle = '#fbbf24';
          ctx.beginPath();
          ctx.arc(px + cell * 0.25, py + cell * 0.25, cell * 0.16, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#111';
          ctx.font = `bold ${Math.floor(cell * 0.22)}px sans-serif`;
          ctx.fillText(t.attr[0].toUpperCase(), px + cell * 0.25, py + cell * 0.26);
        }
      }
    }

    // 5) craft/stack/link 방향 화살표
    let arrow: string | null = null;
    if (t.type.startsWith('craft_')) arrow = PREVIEW_DIR_ARROWS[t.type.split('_')[1]] ?? null;
    else if (t.attr.startsWith('link_')) arrow = PREVIEW_DIR_ARROWS[t.attr.split('_')[1]] ?? null;
    if (arrow && cell >= 14) {
      ctx.font = `bold ${Math.floor(cell * 0.4)}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.strokeStyle = 'rgba(0,0,0,0.85)';
      ctx.lineWidth = Math.max(2, cell * 0.08);
      ctx.strokeText(arrow, px + cell / 2, py + cell / 2);
      ctx.fillStyle = t.attr.startsWith('link_') ? '#eab308' : '#ffffff';
      ctx.fillText(arrow, px + cell / 2, py + cell / 2);
    }
  }

  return canvas.toDataURL('image/png');
}

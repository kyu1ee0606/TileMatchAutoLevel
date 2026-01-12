import { toPng } from 'html-to-image';
import type { LevelJSON, LevelLayer, TileData } from '../types';
import { TILE_TYPES, SPECIAL_IMAGES } from '../types';

/**
 * Calculate the bounding box of all tiles across all layers.
 */
function calculateTileBounds(levelData: LevelJSON): {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
} | null {
  const numLayers = levelData.layer || 8;
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  let hasTiles = false;

  for (let i = 0; i < numLayers; i++) {
    const layerKey = `layer_${i}` as keyof LevelJSON;
    const layer = levelData[layerKey] as LevelLayer | undefined;
    if (!layer?.tiles) continue;

    for (const pos of Object.keys(layer.tiles)) {
      const parts = pos.split('_');
      if (parts.length !== 2) continue;

      const y = parseInt(parts[0]);
      const x = parseInt(parts[1]);
      if (isNaN(x) || isNaN(y)) continue;

      hasTiles = true;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
  }

  if (!hasTiles) return null;
  return { minX, maxX, minY, maxY };
}

/**
 * Collect all tiles from all layers, sorted by layer (lower first).
 */
function collectAllTiles(levelData: LevelJSON): Array<{
  layer: number;
  x: number;
  y: number;
  tileType: string;
  attribute: string;
}> {
  const numLayers = levelData.layer || 8;
  const tiles: Array<{
    layer: number;
    x: number;
    y: number;
    tileType: string;
    attribute: string;
  }> = [];

  for (let i = 0; i < numLayers; i++) {
    const layerKey = `layer_${i}` as keyof LevelJSON;
    const layer = levelData[layerKey] as LevelLayer | undefined;
    if (!layer?.tiles) continue;

    for (const [pos, data] of Object.entries(layer.tiles)) {
      if (!Array.isArray(data)) continue;

      const parts = pos.split('_');
      if (parts.length !== 2) continue;

      const y = parseInt(parts[0]);
      const x = parseInt(parts[1]);
      if (isNaN(x) || isNaN(y)) continue;

      const tileData = data as TileData;
      tiles.push({
        layer: i,
        x,
        y,
        tileType: tileData[0],
        attribute: tileData[1] || '',
      });
    }
  }

  // Sort by layer (lower layers first, so higher layers render on top)
  tiles.sort((a, b) => a.layer - b.layer);
  return tiles;
}

/**
 * Create a DOM element with all tiles for html-to-image capture.
 * Uses inline base64 images to avoid CORS issues.
 */
async function createCaptureElement(
  tiles: ReturnType<typeof collectAllTiles>,
  bounds: NonNullable<ReturnType<typeof calculateTileBounds>>,
  targetSize: number
): Promise<{ container: HTMLDivElement; imagePromises: Promise<void>[] }> {
  // Calculate dimensions based on used area
  const usedWidth = bounds.maxX - bounds.minX + 1;
  const usedHeight = bounds.maxY - bounds.minY + 1;

  // Calculate tile size - render at larger size for better quality
  const renderSize = Math.max(targetSize * 2, 256);
  const tileSize = Math.floor(renderSize / Math.max(usedWidth, usedHeight));
  const canvasWidth = usedWidth * tileSize;
  const canvasHeight = usedHeight * tileSize;

  // Create container
  const container = document.createElement('div');
  container.style.position = 'fixed';
  container.style.left = '-9999px';
  container.style.top = '-9999px';
  container.style.width = `${canvasWidth}px`;
  container.style.height = `${canvasHeight}px`;
  container.style.backgroundColor = '#1f2937';
  container.style.overflow = 'hidden';
  container.style.zIndex = '-1';

  // Preload all images as base64 to avoid CORS
  const imageBase64Cache: Map<string, string> = new Map();
  const imagesToLoad = new Set<string>();

  for (const tile of tiles) {
    const tileInfo = TILE_TYPES[tile.tileType];
    if (tileInfo?.image) imagesToLoad.add(tileInfo.image);
    if (tile.attribute && SPECIAL_IMAGES[tile.attribute]) {
      imagesToLoad.add(SPECIAL_IMAGES[tile.attribute]);
    }
  }

  console.log(`[Thumbnail] Loading ${imagesToLoad.size} unique images`);

  // Load images and convert to base64
  const loadResults = await Promise.all(
    [...imagesToLoad].map(async (src) => {
      try {
        const response = await fetch(src);
        if (!response.ok) {
          console.warn(`[Thumbnail] Failed to fetch image: ${src} (${response.status})`);
          return { src, success: false };
        }
        const blob = await response.blob();
        return new Promise<{ src: string; success: boolean }>((resolve) => {
          const reader = new FileReader();
          reader.onloadend = () => {
            imageBase64Cache.set(src, reader.result as string);
            resolve({ src, success: true });
          };
          reader.onerror = () => {
            console.warn(`[Thumbnail] Failed to read image blob: ${src}`);
            resolve({ src, success: false });
          };
          reader.readAsDataURL(blob);
        });
      } catch (err) {
        console.warn(`[Thumbnail] Failed to load image: ${src}`, err);
        return { src, success: false };
      }
    })
  );

  const successCount = loadResults.filter(r => r?.success).length;
  console.log(`[Thumbnail] Loaded ${successCount}/${imagesToLoad.size} images as base64`);

  // Create wrapper for positioning
  const wrapper = document.createElement('div');
  wrapper.style.position = 'relative';
  wrapper.style.width = '100%';
  wrapper.style.height = '100%';
  container.appendChild(wrapper);

  // Track image load promises for DOM images
  const imagePromises: Promise<void>[] = [];

  // Render each tile
  for (const tile of tiles) {
    const relX = tile.x - bounds.minX;
    const relY = tile.y - bounds.minY;
    const px = relX * tileSize;
    const py = relY * tileSize;

    const tileInfo = TILE_TYPES[tile.tileType];

    // Create tile element
    const tileEl = document.createElement('div');
    tileEl.style.position = 'absolute';
    tileEl.style.left = `${px}px`;
    tileEl.style.top = `${py}px`;
    tileEl.style.width = `${tileSize}px`;
    tileEl.style.height = `${tileSize}px`;
    tileEl.style.backgroundColor = tileInfo?.color || '#6b7280';

    // Add tile image using base64
    if (tileInfo?.image) {
      const base64 = imageBase64Cache.get(tileInfo.image);
      if (base64) {
        const img = document.createElement('img');
        img.style.width = '100%';
        img.style.height = '100%';
        img.style.objectFit = 'cover';
        img.style.display = 'block';

        // Wait for image to load in DOM
        const loadPromise = new Promise<void>((resolve) => {
          img.onload = () => resolve();
          img.onerror = () => resolve();
        });
        imagePromises.push(loadPromise);
        img.src = base64;

        tileEl.appendChild(img);
      }
    }

    // Add attribute overlay using base64
    if (tile.attribute && SPECIAL_IMAGES[tile.attribute]) {
      const base64 = imageBase64Cache.get(SPECIAL_IMAGES[tile.attribute]);
      if (base64) {
        const attrImg = document.createElement('img');
        attrImg.style.position = 'absolute';
        attrImg.style.left = '0';
        attrImg.style.top = '0';
        attrImg.style.width = '100%';
        attrImg.style.height = '100%';
        attrImg.style.objectFit = 'cover';
        attrImg.style.opacity = '0.7';

        // Wait for image to load in DOM
        const loadPromise = new Promise<void>((resolve) => {
          attrImg.onload = () => resolve();
          attrImg.onerror = () => resolve();
        });
        imagePromises.push(loadPromise);
        attrImg.src = base64;

        tileEl.appendChild(attrImg);
      }
    }

    wrapper.appendChild(tileEl);
  }

  return { container, imagePromises };
}

/**
 * Render a level to a thumbnail image and return as base64 PNG.
 * Captures actual tile images using html-to-image.
 */
export async function renderLevelThumbnail(
  levelData: LevelJSON,
  size: number = 128
): Promise<string | null> {
  try {
    // Calculate bounds
    const bounds = calculateTileBounds(levelData);
    if (!bounds) {
      console.warn('[Thumbnail] No tiles found in level data');
      return null;
    }

    // Collect all tiles
    const tiles = collectAllTiles(levelData);
    if (tiles.length === 0) {
      console.warn('[Thumbnail] No tiles collected');
      return null;
    }

    console.log(`[Thumbnail] Rendering ${tiles.length} tiles, bounds: ${JSON.stringify(bounds)}`);

    // Create DOM element with base64 images
    const { container: element, imagePromises } = await createCaptureElement(tiles, bounds, size);
    document.body.appendChild(element);

    // Wait for all images to load in DOM
    console.log(`[Thumbnail] Waiting for ${imagePromises.length} DOM images to load`);
    await Promise.all(imagePromises);

    // Additional settle time for rendering
    await new Promise((resolve) => setTimeout(resolve, 150));

    try {
      // Calculate actual dimensions
      const canvasWidth = parseInt(element.style.width);
      const canvasHeight = parseInt(element.style.height);

      // Capture with html-to-image
      const dataUrl = await toPng(element, {
        width: canvasWidth,
        height: canvasHeight,
        pixelRatio: 1,
        backgroundColor: '#1f2937',
        skipFonts: true,
        cacheBust: true,
      });

      // Resize to target size using canvas
      const img = new Image();
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = () => reject(new Error('Failed to load captured image'));
        img.src = dataUrl;
      });

      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        return dataUrl.split(',')[1];
      }

      // Fill background
      ctx.fillStyle = '#1f2937';
      ctx.fillRect(0, 0, size, size);

      // Scale and center
      const scale = Math.min(size / canvasWidth, size / canvasHeight);
      const scaledWidth = canvasWidth * scale;
      const scaledHeight = canvasHeight * scale;
      const offsetX = (size - scaledWidth) / 2;
      const offsetY = (size - scaledHeight) / 2;

      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(img, offsetX, offsetY, scaledWidth, scaledHeight);

      const result = canvas.toDataURL('image/png').split(',')[1];
      console.log(`[Thumbnail] Generated thumbnail, base64 length: ${result.length}`);
      return result;
    } finally {
      document.body.removeChild(element);
    }
  } catch (error) {
    console.error('[Thumbnail] Render error:', error);
    return null;
  }
}

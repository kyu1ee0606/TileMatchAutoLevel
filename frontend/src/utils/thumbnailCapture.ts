import { toPng } from 'html-to-image';
import { uploadThumbnail } from '../api/gboost';

/**
 * Capture a DOM element as PNG and upload to GBoost.
 */
export async function captureAndUploadThumbnail(
  element: HTMLElement,
  boardId: string,
  levelId: string,
  size: number = 128
): Promise<{ success: boolean; message: string }> {
  try {
    // Capture element as PNG
    const dataUrl = await toPng(element, {
      width: size,
      height: size,
      pixelRatio: 1,
      backgroundColor: '#1f2937', // gray-800
    });

    // Extract base64 data (remove "data:image/png;base64," prefix)
    const base64Data = dataUrl.split(',')[1];

    // Upload to GBoost
    const result = await uploadThumbnail({
      board_id: boardId,
      level_id: levelId,
      png_base64: base64Data,
      size,
    });

    return result;
  } catch (error) {
    console.error('Thumbnail capture error:', error);
    return {
      success: false,
      message: error instanceof Error ? error.message : 'Failed to capture thumbnail',
    };
  }
}

/**
 * Capture a DOM element as base64 PNG string.
 */
export async function captureElementAsPng(
  element: HTMLElement,
  size: number = 128
): Promise<string | null> {
  try {
    const dataUrl = await toPng(element, {
      width: size,
      height: size,
      pixelRatio: 1,
      backgroundColor: '#1f2937',
    });
    return dataUrl.split(',')[1];
  } catch (error) {
    console.error('Element capture error:', error);
    return null;
  }
}

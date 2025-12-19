import apiClient from './client';
import type { LevelJSON } from '../types';
import type { VisualSimulationResponse, BotProfile } from '../types/simulation';

/**
 * Run visual simulation for a level with multiple bots.
 * Returns detailed move history for playback visualization.
 */
export async function simulateVisual(
  levelJson: LevelJSON,
  botTypes?: BotProfile[],
  maxMoves?: number,
  seed?: number
): Promise<VisualSimulationResponse> {
  const response = await apiClient.post<VisualSimulationResponse>(
    '/simulate/visual',
    {
      level_json: levelJson,
      bot_types: botTypes,
      max_moves: maxMoves,
      seed: seed,
    }
  );
  return response.data;
}

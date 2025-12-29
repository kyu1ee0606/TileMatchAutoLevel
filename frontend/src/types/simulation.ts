// Type definitions for Visual Simulation

// Bot profile types
export type BotProfile = 'novice' | 'casual' | 'average' | 'expert' | 'optimal';

// Playback speed options
export type PlaybackSpeed = 1 | 2 | 4;

// Bot move data
export interface VisualBotMove {
  move_number: number;
  layer_idx: number;
  position: string;
  tile_type: string;
  linked_positions: string[]; // Positions selected together due to LINK gimmick (layerIdx_x_y format)
  matched_positions: string[];
  tiles_cleared: number;
  goals_after: Record<string, number>;
  score_gained: number;
  decision_reason: string;
  dock_after: string[]; // Dock state after this move (tile types)
  frog_positions_after: string[]; // Frog positions after move (layerIdx_x_y format)
  bomb_states_after: Record<string, number>; // Bomb states after move (layerIdx_x_y -> remaining count)
  curtain_states_after: Record<string, boolean>; // Curtain states after move (layerIdx_x_y -> is_open)
  ice_states_after: Record<string, number>; // Ice states after move (layerIdx_x_y -> remaining layers 1-3)
  chain_states_after: Record<string, boolean>; // Chain states after move (layerIdx_x_y -> unlocked)
  grass_states_after: Record<string, number>; // Grass states after move (layerIdx_x_y -> remaining layers 1-2)
  link_states_after: Record<string, string[]>; // Link states after move (layerIdx_x_y -> connected positions)
}

// Bot simulation result
export interface VisualBotResult {
  profile: string; // Bot profile name from backend
  profile_display: string;
  moves: VisualBotMove[];
  cleared: boolean;
  total_moves: number;
  final_score: number;
  goals_completed: Record<string, number>;
}

// Game state snapshot
export interface VisualGameState {
  tiles: Record<string, unknown>;
  goals: Record<string, number>;
  grid_info: Record<string, unknown>;
  initial_frog_positions: string[]; // Initial frog positions (layerIdx_x_y format)
  initial_ice_states: Record<string, number>; // Initial ice states (layerIdx_x_y -> layers 1-3)
  initial_chain_states: Record<string, boolean>; // Initial chain states (layerIdx_x_y -> locked=false)
  initial_grass_states: Record<string, number>; // Initial grass states (layerIdx_x_y -> layers 1-2)
  initial_bomb_states: Record<string, number>; // Initial bomb states (layerIdx_x_y -> count)
  initial_curtain_states: Record<string, boolean>; // Initial curtain states (layerIdx_x_y -> is_open)
  initial_link_states: Record<string, string[]>; // Initial link states (layerIdx_x_y -> connected positions)
}

// API response
export interface VisualSimulationResponse {
  initial_state: VisualGameState;
  bot_results: VisualBotResult[];
  max_steps: number;
  metadata: Record<string, unknown>;
}

// API request
export interface VisualSimulationRequest {
  level_json: Record<string, unknown>;
  bot_types?: BotProfile[];
  max_moves?: number;
  seed?: number;
}

// Bot display info
export const BOT_PROFILES: Record<BotProfile, { name: string; color: string; icon: string }> = {
  novice: { name: '초보자', color: '#22c55e', icon: '🌱' },
  casual: { name: '캐주얼', color: '#3b82f6', icon: '🎮' },
  average: { name: '평균', color: '#eab308', icon: '⭐' },
  expert: { name: '전문가', color: '#f97316', icon: '🎯' },
  optimal: { name: '최적', color: '#ef4444', icon: '🏆' },
};

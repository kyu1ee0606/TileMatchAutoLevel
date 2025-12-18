// Type definitions for TileMatch Level Designer

// Difficulty grades
export type DifficultyGrade = 'S' | 'A' | 'B' | 'C' | 'D';

// Tile data format: [type, attribute, extra?]
export type TileData = [string, string, number[]?];

// Level layer structure
export interface LevelLayer {
  col: string;
  row: string;
  tiles: Record<string, TileData>;
  num: string;
}

// Complete level JSON structure
export interface LevelJSON {
  layer: number;
  [key: `layer_${number}`]: LevelLayer;
}

// Level metrics from analysis
export interface LevelMetrics {
  total_tiles: number;
  active_layers: number;
  chain_count: number;
  frog_count: number;
  link_count: number;
  goal_amount: number;
  layer_blocking: number;
  tile_types: Record<string, number>;
  goals: Array<{ type: string; count: number }>;
}

// Difficulty analysis result
export interface DifficultyReport {
  score: number;
  grade: DifficultyGrade;
  metrics: LevelMetrics;
  recommendations: string[];
}

// Goal configuration
export interface GoalConfig {
  type: 'craft_s' | 'stack_s';
  count: number;
}

// Level generation parameters
export interface GenerationParams {
  target_difficulty: number;
  grid_size?: [number, number];
  max_layers?: number;
  tile_types?: string[];
  obstacle_types?: string[];
  goals?: GoalConfig[];
}

// Level generation result
export interface GenerationResult {
  level_json: LevelJSON;
  actual_difficulty: number;
  grade: DifficultyGrade;
  generation_time_ms: number;
}

// Simulation result
export interface SimulationResult {
  clear_rate: number;
  avg_moves: number;
  min_moves: number;
  max_moves: number;
  difficulty_estimate: number;
}

// GBoost level metadata
export interface LevelMetadata {
  id: string;
  created_at: string;
  updated_at?: string;
  version?: string;
  difficulty?: number;
  thumbnail_data?: LevelJSON; // For thumbnail preview
}

// Tile type definitions
export const TILE_TYPES: Record<string, { name: string; color: string; image?: string }> = {
  t0: { name: '기본 타일 0', color: '#94a3b8', image: '/tiles/skin0/s0_t0.png' },
  t1: { name: '기본 타일 1', color: '#f87171', image: '/tiles/skin0/s0_t1.png' },
  t2: { name: '기본 타일 2', color: '#f87171', image: '/tiles/skin0/s0_t2.png' },
  t3: { name: '기본 타일 3', color: '#4ade80', image: '/tiles/skin0/s0_t3.png' },
  t4: { name: '기본 타일 4', color: '#4ade80', image: '/tiles/skin0/s0_t4.png' },
  t5: { name: '기본 타일 5', color: '#60a5fa', image: '/tiles/skin0/s0_t5.png' },
  t6: { name: '기본 타일 6', color: '#c084fc', image: '/tiles/skin0/s0_t6.png' },
  t7: { name: '기본 타일 7', color: '#78716c', image: '/tiles/skin0/s0_t7.png' },
  t8: { name: '기본 타일 8', color: '#78716c', image: '/tiles/skin0/s0_t8.png' },
  t9: { name: '기본 타일 9', color: '#57534e', image: '/tiles/skin0/s0_t9.png' },
  t10: { name: '기본 타일 10', color: '#facc15', image: '/tiles/skin0/s0_t10.png' },
  t11: { name: '기본 타일 11', color: '#fb923c', image: '/tiles/skin0/s0_t11.png' },
  t12: { name: '기본 타일 12', color: '#f472b6', image: '/tiles/skin0/s0_t12.png' },
  t13: { name: '기본 타일 13', color: '#22d3ee', image: '/tiles/skin0/s0_t13.png' },
  t14: { name: '기본 타일 14', color: '#22d3ee', image: '/tiles/skin0/s0_t14.png' },
  t15: { name: '기본 타일 15', color: '#a78bfa', image: '/tiles/skin0/s0_t15.png' },
  craft_s: { name: 'Craft Goal', color: '#10b981', image: '/tiles/special/tile_craft.png' },
  stack_s: { name: 'Stack Goal', color: '#8b5cf6', image: '/tiles/special/stack_s.png' },
};

// Special tile images for attributes and obstacles
export const SPECIAL_IMAGES: Record<string, string> = {
  chain: '/tiles/special/tile_chain.png',
  frog: '/tiles/special/frog.png',
  link: '/tiles/special/tile_link.png',
  link_n: '/tiles/special/tile_link_n.png',
  link_s: '/tiles/special/tile_link_s.png',
  link_e: '/tiles/special/tile_link_e.png',
  link_w: '/tiles/special/tile_link_w.png',
  ice_1: '/tiles/special/tile_ice_1.png',
  ice_2: '/tiles/special/tile_ice_2.png',
  ice_3: '/tiles/special/tile_ice_3.png',
  grass: '/tiles/special/tile_grass.png',
  crate: '/tiles/special/tile_crate.png',
  bomb: '/tiles/special/bomb.png',
  unknown: '/tiles/special/tile_unknown.png',
};

// Attribute definitions
export const ATTRIBUTES: Record<string, { name: string; icon: string }> = {
  '': { name: 'None', icon: '' },
  chain: { name: 'Chain', icon: '⛓️' },
  frog: { name: 'Frog', icon: '🐸' },
  link_w: { name: 'Link West', icon: '🔗←' },
  link_n: { name: 'Link North', icon: '🔗↑' },
};

// Grade color mapping
export const GRADE_COLORS: Record<DifficultyGrade, string> = {
  S: '#22c55e',
  A: '#84cc16',
  B: '#eab308',
  C: '#f97316',
  D: '#ef4444',
};

// Grade descriptions
export const GRADE_DESCRIPTIONS: Record<DifficultyGrade, string> = {
  S: '매우 쉬움',
  A: '쉬움',
  B: '보통',
  C: '어려움',
  D: '매우 어려움',
};

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
  timeAttack?: number;  // Time attack seconds (0 = disabled)
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

// Goal configuration with direction support
export type GoalType = 'craft' | 'stack';
export type GoalDirection = 's' | 'n' | 'e' | 'w';

export interface GoalConfig {
  type: GoalType;
  direction: GoalDirection;
  count: number;
}

// Obstacle count configuration
export interface ObstacleCountConfig {
  min: number;
  max: number;
}

// Layer tile configuration
export interface LayerTileConfig {
  layer: number;
  count: number;
}

// Layer obstacle configuration
export interface LayerObstacleConfig {
  layer: number;
  counts: Record<string, ObstacleCountConfig>;
}

// Symmetry mode options
export type SymmetryMode = 'none' | 'horizontal' | 'vertical' | 'both';

// Pattern type options
export type PatternType = 'random' | 'geometric' | 'clustered' | 'aesthetic';

// Level generation parameters
export interface GenerationParams {
  target_difficulty: number;
  grid_size?: [number, number];
  min_layers?: number;  // Minimum layers for easy difficulty
  max_layers?: number;  // Maximum layers for hard difficulty
  tile_types?: string[];
  obstacle_types?: string[];
  goals?: GoalConfig[];
  obstacle_counts?: Record<string, ObstacleCountConfig>;
  // Enhanced layer control
  total_tile_count?: number;
  active_layer_count?: number;
  layer_tile_configs?: LayerTileConfig[];
  layer_obstacle_configs?: LayerObstacleConfig[];
  // Symmetry and pattern options
  symmetry_mode?: SymmetryMode;
  pattern_type?: PatternType;
  pattern_index?: number;  // 0-49 for specific aesthetic pattern (undefined = auto-select)
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
// Note: t1~t15 are ordered first, t0 is at the end (as per design requirement)
export const TILE_TYPES: Record<string, { name: string; color: string; image?: string }> = {
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
  t0: { name: '기본 타일 0', color: '#94a3b8', image: '/tiles/skin0/s0_t0.png' },
  craft_s: { name: 'Craft Goal', color: '#10b981', image: '/tiles/special/tile_craft.png' },
  craft_e: { name: 'Craft East', color: '#10b981', image: '/tiles/special/tile_craft.png' },
  craft_w: { name: 'Craft West', color: '#10b981', image: '/tiles/special/tile_craft.png' },
  craft_n: { name: 'Craft North', color: '#10b981', image: '/tiles/special/tile_craft.png' },
  stack_s: { name: 'Stack South', color: '#8b5cf6', image: '/tiles/special/stack_s.png' },
  stack_e: { name: 'Stack East', color: '#8b5cf6', image: '/tiles/special/stack_e.png' },
  stack_w: { name: 'Stack West', color: '#8b5cf6', image: '/tiles/special/stack_w.png' },
  stack_n: { name: 'Stack North', color: '#8b5cf6', image: '/tiles/special/stack_n.png' },
  stack_ne: { name: 'Stack NorthEast', color: '#8b5cf6', image: '/tiles/special/stack_ne.png' },
  stack_nw: { name: 'Stack NorthWest', color: '#8b5cf6', image: '/tiles/special/stack_nw.png' },
  stack_se: { name: 'Stack SouthEast', color: '#8b5cf6', image: '/tiles/special/stack_se.png' },
  stack_sw: { name: 'Stack SouthWest', color: '#8b5cf6', image: '/tiles/special/stack_sw.png' },
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
  ice: '/tiles/special/tile_ice_1.png', // Default ice
  grass: '/tiles/special/tile_grass.png',
  grass_1: '/tiles/special/tile_grass.png',
  grass_2: '/tiles/special/tile_grass.png',
  bomb: '/tiles/special/bomb.png',
  unknown: '/tiles/special/tile_unknown.png',
  // Curtain gimmick
  curtain_open: '/tiles/special/curtain_open.png',
  curtain_close: '/tiles/special/curtain_close.png',
  curtain: '/tiles/special/curtain_close.png', // Default curtain
  // Teleport gimmick
  teleport: '/tiles/special/teleport.png',
  // Stack gimmick icons (direction-based)
  stack_e: '/tiles/special/stack_e.png',
  stack_w: '/tiles/special/stack_w.png',
  stack_s: '/tiles/special/stack_s.png',
  stack_n: '/tiles/special/stack_n.png',
  stack_ne: '/tiles/special/stack_ne.png',
  stack_nw: '/tiles/special/stack_nw.png',
  stack_se: '/tiles/special/stack_se.png',
  stack_sw: '/tiles/special/stack_sw.png',
  // Craft gimmick icons (all directions use same image)
  craft: '/tiles/special/tile_craft.png',
  craft_s: '/tiles/special/tile_craft.png',
  craft_e: '/tiles/special/tile_craft.png',
  craft_w: '/tiles/special/tile_craft.png',
  craft_n: '/tiles/special/tile_craft.png',
};

// Gimmick effect definitions for visualization
export interface GimmickEffect {
  name: string;
  icon: string;
  color: string;
  description: string;
}

export const GIMMICK_EFFECTS: Record<string, GimmickEffect> = {
  ice: { name: 'Ice', icon: '❄️', color: '#60a5fa', description: '얼음 - 인접 타일 제거 시 녹음' },
  ice_1: { name: 'Ice 1', icon: '❄️', color: '#93c5fd', description: '얼음 1단계' },
  ice_2: { name: 'Ice 2', icon: '❄️', color: '#60a5fa', description: '얼음 2단계' },
  ice_3: { name: 'Ice 3', icon: '❄️', color: '#3b82f6', description: '얼음 3단계' },
  chain: { name: 'Chain', icon: '⛓️', color: '#a1a1aa', description: '체인 - 수평 인접 타일 제거 시 해제' },
  grass: { name: 'Grass', icon: '🌿', color: '#22c55e', description: '풀 - 인접 타일 제거 시 제거' },
  grass_1: { name: 'Grass 1', icon: '🌿', color: '#4ade80', description: '풀 1단계' },
  grass_2: { name: 'Grass 2', icon: '🌿', color: '#22c55e', description: '풀 2단계' },
  frog: { name: 'Frog', icon: '🐸', color: '#16a34a', description: '개구리 - 매 턴 이동' },
  bomb: { name: 'Bomb', icon: '💣', color: '#ef4444', description: '폭탄 - 카운트다운 후 폭발' },
  curtain_open: { name: 'Curtain Open', icon: '🎭', color: '#a855f7', description: '커튼 열림' },
  curtain_close: { name: 'Curtain Closed', icon: '🎪', color: '#7c3aed', description: '커튼 닫힘 - 선택 불가' },
  teleport: { name: 'Teleport', icon: '🌀', color: '#06b6d4', description: '텔레포트 - 위치 이동' },
  unknown: { name: 'Unknown', icon: '❓', color: '#6b7280', description: '물음표 - 상위 타일 제거 전까지 종류 숨김' },
  link_n: { name: 'Link North', icon: '🔗↑', color: '#f59e0b', description: '북쪽 연결' },
  link_s: { name: 'Link South', icon: '🔗↓', color: '#f59e0b', description: '남쪽 연결' },
  link_e: { name: 'Link East', icon: '🔗→', color: '#f59e0b', description: '동쪽 연결' },
  link_w: { name: 'Link West', icon: '🔗←', color: '#f59e0b', description: '서쪽 연결' },
};

// Attribute definitions
export const ATTRIBUTES: Record<string, { name: string; icon: string }> = {
  '': { name: 'None', icon: '' },
  chain: { name: 'Chain', icon: '⛓️' },
  frog: { name: 'Frog', icon: '🐸' },
  link_w: { name: 'Link West', icon: '🔗←' },
  link_n: { name: 'Link North', icon: '🔗↑' },
  link_s: { name: 'Link South', icon: '🔗↓' },
  link_e: { name: 'Link East', icon: '🔗→' },
  unknown: { name: 'Unknown', icon: '❓' },
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

// Re-export simulation types
export * from './simulation';

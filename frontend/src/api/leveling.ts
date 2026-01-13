/**
 * 프로 레벨링 시스템 API
 *
 * 유명 타일 게임(Tile Buster, Tile Explorer 등)의
 * 레벨링 패턴을 분석하여 구현한 시스템입니다.
 */

const API_BASE = '/api';

// =========================================================
// 타입 정의
// =========================================================

/** 레벨 진행 단계 */
export type LevelPhase =
  | 'tutorial'      // 1-10: 순수 매칭 학습
  | 'basic'         // 11-50: 단일 기믹 학습
  | 'intermediate'  // 51-100: 2기믹 조합
  | 'advanced'      // 101-150: 3기믹 조합
  | 'expert'        // 151-200: 4기믹 조합
  | 'master';       // 201+: 최고 난이도

/** 기믹 도입 단계 */
export type GimmickIntroPhase =
  | 'tutorial'      // 첫 등장 레벨
  | 'practice'      // 연습 레벨
  | 'integration'   // 이전 기믹과 통합
  | 'mastery';      // 숙달 단계

/** 기믹 언락 설정 */
export interface GimmickUnlockConfig {
  gimmick: string;
  unlock_level: number;
  practice_levels: number;
  integration_start: number;
  difficulty_weight: number;
  description: string;
}

/** 단계별 설정 */
export interface PhaseConfig {
  phase: LevelPhase;
  level_range: [number, number];
  min_tile_types: number;
  max_tile_types: number;
  min_layers: number;
  max_layers: number;
  max_gimmick_types: number;
  base_difficulty: number;
  difficulty_increment: number;
}

/** 전체 레벨링 설정 */
export interface LevelingConfig {
  gimmick_unlocks: Record<string, GimmickUnlockConfig>;
  phase_configs: Record<LevelPhase, PhaseConfig>;
  sawtooth_pattern: number[];
  unlock_levels: Record<string, number>;
}

/** 단일 레벨 설정 */
export interface LevelConfig {
  level_number: number;
  phase: LevelPhase;
  difficulty: number;
  tile_types_count: number;
  layer_count: number;
  gimmicks: string[];
  gimmick_intro_phase: GimmickIntroPhase;
  is_tutorial_level: boolean;
  is_boss_level: boolean;
  tutorial_gimmick: string | null;
}

/** 난이도 곡선 데이터 */
export interface DifficultyCurveData {
  levels: number[];
  difficulties: number[];
  phases: LevelPhase[];
  boss_levels: number[];
  tutorial_levels: Array<{
    level: number;
    gimmick: string;
    description: string;
  }>;
}

// =========================================================
// API 함수
// =========================================================

/**
 * 전체 레벨링 설정 가져오기
 */
export async function getLevelingConfig(): Promise<LevelingConfig> {
  const response = await fetch(`${API_BASE}/leveling/config`);
  if (!response.ok) {
    throw new Error(`Failed to get leveling config: ${response.statusText}`);
  }
  return response.json();
}

/**
 * 단일 레벨 설정 가져오기
 */
export async function getLevelConfig(
  levelNumber: number,
  availableGimmicks?: string[],
  useSawtooth: boolean = true
): Promise<LevelConfig> {
  const response = await fetch(`${API_BASE}/leveling/level-config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      level_number: levelNumber,
      available_gimmicks: availableGimmicks,
      use_sawtooth: useSawtooth,
    }),
  });
  if (!response.ok) {
    throw new Error(`Failed to get level config: ${response.statusText}`);
  }
  return response.json();
}

/**
 * 레벨 진행 계획 가져오기 (여러 레벨)
 */
export async function getLevelProgression(
  startLevel: number,
  count: number,
  availableGimmicks?: string[],
  useSawtooth: boolean = true
): Promise<LevelConfig[]> {
  const response = await fetch(`${API_BASE}/leveling/progression`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      start_level: startLevel,
      count: count,
      available_gimmicks: availableGimmicks,
      use_sawtooth: useSawtooth,
    }),
  });
  if (!response.ok) {
    throw new Error(`Failed to get level progression: ${response.statusText}`);
  }
  return response.json();
}

/**
 * 특정 레벨에서 사용 가능한 기믹 목록
 */
export async function getUnlockedGimmicks(levelNumber: number): Promise<{
  level_number: number;
  unlocked_gimmicks: string[];
  total_available: number;
  phase: LevelPhase;
}> {
  const response = await fetch(`${API_BASE}/leveling/unlocked-gimmicks/${levelNumber}`);
  if (!response.ok) {
    throw new Error(`Failed to get unlocked gimmicks: ${response.statusText}`);
  }
  return response.json();
}

/**
 * 난이도 곡선 데이터 가져오기 (차트용)
 */
export async function getDifficultyCurve(
  startLevel: number = 1,
  count: number = 50,
  useSawtooth: boolean = true
): Promise<DifficultyCurveData> {
  const params = new URLSearchParams({
    start_level: startLevel.toString(),
    count: count.toString(),
    use_sawtooth: useSawtooth.toString(),
  });
  const response = await fetch(`${API_BASE}/leveling/difficulty-curve?${params}`);
  if (!response.ok) {
    throw new Error(`Failed to get difficulty curve: ${response.statusText}`);
  }
  return response.json();
}

// =========================================================
// 프론트엔드 전용 프로페셔널 언락 레벨 (API 없이 사용)
// =========================================================

/**
 * 프로페셔널 기믹 언락 레벨
 * 유명 타일 게임 패턴 분석 기반
 */
export const PROFESSIONAL_UNLOCK_LEVELS: Record<string, number> = {
  chain: 11,
  ice: 21,
  frog: 36,
  grass: 51,
  link: 66,
  bomb: 81,
  curtain: 96,
  teleport: 111,
  unknown: 126,
  craft: 141,
  stack: 156,
};

/**
 * 단계별 레벨 범위
 */
export const PHASE_LEVEL_RANGES: Record<LevelPhase, [number, number]> = {
  tutorial: [1, 10],
  basic: [11, 50],
  intermediate: [51, 100],
  advanced: [101, 150],
  expert: [151, 200],
  master: [201, 9999],
};

/**
 * 톱니바퀴 난이도 패턴 (10레벨 단위)
 */
export const SAWTOOTH_PATTERN: number[] = [
  0.0,   // 레벨 1: 새 시작
  0.1,   // 레벨 2: 쉬움
  0.2,   // 레벨 3: 약간 증가
  0.35,  // 레벨 4: 중간 진입
  0.45,  // 레벨 5: 중간
  0.55,  // 레벨 6: 중간 위
  0.7,   // 레벨 7: 어려움 시작
  0.85,  // 레벨 8: 어려움
  0.75,  // 레벨 9: 보스 전 휴식
  1.0,   // 레벨 10: 보스
];

/**
 * 레벨 번호에 해당하는 단계 반환
 */
export function getPhaseForLevel(levelNumber: number): LevelPhase {
  for (const [phase, [start, end]] of Object.entries(PHASE_LEVEL_RANGES)) {
    if (levelNumber >= start && levelNumber <= end) {
      return phase as LevelPhase;
    }
  }
  return 'master';
}

/**
 * 레벨 번호에서 언락된 기믹 목록 반환
 */
export function getUnlockedGimmicksLocal(levelNumber: number): string[] {
  return Object.entries(PROFESSIONAL_UNLOCK_LEVELS)
    .filter(([_, unlockLevel]) => unlockLevel <= levelNumber)
    .map(([gimmick]) => gimmick);
}

/**
 * 레벨이 튜토리얼 레벨인지 확인
 */
export function isTutorialLevel(levelNumber: number): string | null {
  for (const [gimmick, unlockLevel] of Object.entries(PROFESSIONAL_UNLOCK_LEVELS)) {
    if (unlockLevel === levelNumber) {
      return gimmick;
    }
  }
  return null;
}

/**
 * 레벨이 보스 레벨인지 확인
 */
export function isBossLevel(levelNumber: number): boolean {
  return levelNumber % 10 === 0;
}

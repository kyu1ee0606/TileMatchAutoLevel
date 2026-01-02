/**
 * Level Set Types - 난이도 그래프 기반 레벨 세트 생성
 */

import { GenerationParams, LevelJSON, DifficultyGrade } from './index';

/**
 * 난이도 그래프의 점
 */
export interface DifficultyPoint {
  levelIndex: number;  // 1 ~ N (레벨 번호)
  difficulty: number;  // 0 ~ 1 (난이도)
}

/**
 * 레벨 세트 메타데이터
 */
export interface LevelSetMetadata {
  id: string;
  name: string;
  created_at: string;
  level_count: number;
  difficulty_profile: number[];      // 목표 난이도 배열
  actual_difficulties: number[];     // 실제 달성 난이도 배열
  grades: DifficultyGrade[];         // 각 레벨 등급
  generation_config: Partial<GenerationParams>;
}

/**
 * 레벨 세트 전체 데이터
 */
export interface LevelSet {
  metadata: LevelSetMetadata;
  levels: LevelJSON[];
}

/**
 * 레벨 세트 목록 아이템 (경량)
 */
export interface LevelSetListItem {
  id: string;
  name: string;
  created_at: string;
  level_count: number;
  difficulty_range: {
    min: number;
    max: number;
  };
}

/**
 * 레벨 세트 생성 설정
 */
export interface LevelSetGenerationConfig {
  setName: string;
  levelCount: number;
  difficultyPoints: DifficultyPoint[];
  baseParams: Omit<GenerationParams, 'target_difficulty'>;
}

/**
 * 생성 진행 상태
 */
export interface GenerationProgressState {
  status: 'idle' | 'generating' | 'completed' | 'cancelled' | 'error';
  total: number;
  current: number;
  results: GenerationResultItem[];
  error?: string;
}

/**
 * 개별 레벨 생성 결과
 */
export interface GenerationResultItem {
  levelIndex: number;
  targetDifficulty: number;
  actualDifficulty: number;
  grade: DifficultyGrade;
  status: 'pending' | 'generating' | 'success' | 'failed';
  error?: string;
  levelJson?: LevelJSON;
  // Validation results (only present when using validated generation)
  matchScore?: number;         // 0-100, how well actual matches target
  validationPassed?: boolean;  // Whether validation criteria were met
}

/**
 * 난이도 보간 함수
 * 점들 사이를 선형 보간하여 각 레벨의 난이도 반환
 */
export function interpolateDifficulties(
  points: DifficultyPoint[],
  levelCount: number
): number[] {
  if (points.length === 0) {
    // 기본값: 0.3에서 0.8까지 선형 증가
    return Array.from({ length: levelCount }, (_, i) =>
      0.3 + (0.5 * i / Math.max(1, levelCount - 1))
    );
  }

  if (points.length === 1) {
    // 점이 하나면 모든 레벨에 동일한 난이도
    return Array(levelCount).fill(points[0].difficulty);
  }

  // 점들을 levelIndex 기준 정렬
  const sorted = [...points].sort((a, b) => a.levelIndex - b.levelIndex);

  const difficulties: number[] = [];

  for (let i = 1; i <= levelCount; i++) {
    // 현재 레벨 번호 i에 대해 보간
    difficulties.push(interpolateAt(sorted, i));
  }

  return difficulties;
}

/**
 * 특정 레벨 번호에 대해 선형 보간
 */
function interpolateAt(sortedPoints: DifficultyPoint[], levelIndex: number): number {
  // 첫 번째 점 이전
  if (levelIndex <= sortedPoints[0].levelIndex) {
    return sortedPoints[0].difficulty;
  }

  // 마지막 점 이후
  if (levelIndex >= sortedPoints[sortedPoints.length - 1].levelIndex) {
    return sortedPoints[sortedPoints.length - 1].difficulty;
  }

  // 사이에 있는 경우: 선형 보간
  for (let i = 0; i < sortedPoints.length - 1; i++) {
    const p1 = sortedPoints[i];
    const p2 = sortedPoints[i + 1];

    if (levelIndex >= p1.levelIndex && levelIndex <= p2.levelIndex) {
      const t = (levelIndex - p1.levelIndex) / (p2.levelIndex - p1.levelIndex);
      return p1.difficulty + t * (p2.difficulty - p1.difficulty);
    }
  }

  // fallback
  return sortedPoints[0].difficulty;
}

/**
 * 기본 난이도 점 생성 (우상향 곡선)
 */
export function createDefaultDifficultyPoints(levelCount: number): DifficultyPoint[] {
  // 시작점, 중간점, 끝점 3개 생성
  return [
    { levelIndex: 1, difficulty: 0.2 },
    { levelIndex: Math.ceil(levelCount / 2), difficulty: 0.5 },
    { levelIndex: levelCount, difficulty: 0.8 },
  ];
}

/**
 * 난이도 그래프 프리셋
 */
export interface DifficultyPreset {
  id: string;
  name: string;
  description?: string;
  icon?: string;
  points: DifficultyPoint[];  // 레벨 수에 맞게 스케일링됨 (1~100 기준)
  isBuiltIn?: boolean;
  created_at?: string;
}

/**
 * 프리셋 포인트를 실제 레벨 수에 맞게 스케일링
 */
export function scalePresetToLevelCount(
  preset: DifficultyPreset,
  levelCount: number
): DifficultyPoint[] {
  if (preset.points.length === 0) {
    return createDefaultDifficultyPoints(levelCount);
  }

  // 프리셋의 최대 레벨 인덱스 찾기
  const maxIndex = Math.max(...preset.points.map(p => p.levelIndex));

  // 스케일링
  return preset.points.map(p => ({
    levelIndex: Math.max(1, Math.min(levelCount, Math.round((p.levelIndex / maxIndex) * levelCount))),
    difficulty: p.difficulty,
  }));
}

/**
 * 내장 프리셋 목록
 */
export const BUILT_IN_PRESETS: DifficultyPreset[] = [
  {
    id: 'linear',
    name: '선형 증가',
    description: '일정한 속도로 난이도 증가',
    icon: '📈',
    isBuiltIn: true,
    points: [
      { levelIndex: 1, difficulty: 0.15 },
      { levelIndex: 100, difficulty: 0.85 },
    ],
  },
  {
    id: 'gentle_start',
    name: '완만한 시작',
    description: '초반 쉽게, 후반 급격히 어려워짐',
    icon: '🐢',
    isBuiltIn: true,
    points: [
      { levelIndex: 1, difficulty: 0.1 },
      { levelIndex: 50, difficulty: 0.3 },
      { levelIndex: 75, difficulty: 0.5 },
      { levelIndex: 100, difficulty: 0.9 },
    ],
  },
  {
    id: 'steep_start',
    name: '급격한 시작',
    description: '초반 빠르게 어려워지고 후반 완만',
    icon: '🚀',
    isBuiltIn: true,
    points: [
      { levelIndex: 1, difficulty: 0.2 },
      { levelIndex: 25, difficulty: 0.6 },
      { levelIndex: 50, difficulty: 0.75 },
      { levelIndex: 100, difficulty: 0.85 },
    ],
  },
  {
    id: 'wave',
    name: '파도형',
    description: '난이도가 오르내리는 패턴',
    icon: '🌊',
    isBuiltIn: true,
    points: [
      { levelIndex: 1, difficulty: 0.2 },
      { levelIndex: 25, difficulty: 0.5 },
      { levelIndex: 40, difficulty: 0.3 },
      { levelIndex: 60, difficulty: 0.7 },
      { levelIndex: 75, difficulty: 0.5 },
      { levelIndex: 100, difficulty: 0.85 },
    ],
  },
  {
    id: 'step',
    name: '계단형',
    description: '구간별로 난이도 단계 상승',
    icon: '🪜',
    isBuiltIn: true,
    points: [
      { levelIndex: 1, difficulty: 0.2 },
      { levelIndex: 20, difficulty: 0.2 },
      { levelIndex: 21, difficulty: 0.4 },
      { levelIndex: 40, difficulty: 0.4 },
      { levelIndex: 41, difficulty: 0.6 },
      { levelIndex: 60, difficulty: 0.6 },
      { levelIndex: 61, difficulty: 0.8 },
      { levelIndex: 80, difficulty: 0.8 },
      { levelIndex: 81, difficulty: 0.9 },
      { levelIndex: 100, difficulty: 0.9 },
    ],
  },
  {
    id: 'plateau',
    name: '고원형',
    description: '중간에 평탄한 구간이 있는 패턴',
    icon: '🏔️',
    isBuiltIn: true,
    points: [
      { levelIndex: 1, difficulty: 0.15 },
      { levelIndex: 30, difficulty: 0.5 },
      { levelIndex: 70, difficulty: 0.5 },
      { levelIndex: 100, difficulty: 0.9 },
    ],
  },
  {
    id: 'easy',
    name: '쉬움',
    description: '전체적으로 쉬운 난이도',
    icon: '😊',
    isBuiltIn: true,
    points: [
      { levelIndex: 1, difficulty: 0.1 },
      { levelIndex: 50, difficulty: 0.25 },
      { levelIndex: 100, difficulty: 0.4 },
    ],
  },
  {
    id: 'hard',
    name: '어려움',
    description: '전체적으로 어려운 난이도',
    icon: '💀',
    isBuiltIn: true,
    points: [
      { levelIndex: 1, difficulty: 0.4 },
      { levelIndex: 50, difficulty: 0.65 },
      { levelIndex: 100, difficulty: 0.95 },
    ],
  },
];

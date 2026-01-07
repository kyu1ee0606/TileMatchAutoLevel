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
 * 기믹 모드
 */
export type GimmickMode = 'auto' | 'manual' | 'hybrid';

/**
 * 레벨별 기믹 오버라이드 설정
 */
export interface LevelGimmickOverride {
  levelIndex: number;  // 1-based index
  gimmicks: string[];  // 해당 레벨에 적용할 기믹 리스트
}

/**
 * 다중 세트 생성 설정
 */
export interface MultiSetConfig {
  enabled: boolean;              // 다중 세트 모드 활성화
  setCount: number;              // 생성할 세트 수 (예: 10)
  difficultyShiftPerSet: number; // 세트당 난이도 시프트 (예: 0.05 = 5%)
  maxDifficultyClamp: number;    // 최대 난이도 제한 (예: 0.95)
}

/**
 * 다중 세트 생성 진행 상태
 */
export interface MultiSetProgressState {
  status: 'idle' | 'generating' | 'completed' | 'cancelled' | 'error';
  totalSets: number;
  currentSetIndex: number;
  totalLevels: number;
  currentLevelIndex: number;
  completedSets: number;
  setResults: {
    setIndex: number;
    setName: string;
    levelCount: number;
    status: 'pending' | 'generating' | 'completed' | 'failed';
    error?: string;
  }[];
  error?: string;
  startTime?: number;
}

/**
 * 레벨 세트 생성 설정
 */
export interface LevelSetGenerationConfig {
  setName: string;
  levelCount: number;
  difficultyPoints: DifficultyPoint[];
  baseParams: Omit<GenerationParams, 'target_difficulty'>;
  // 기믹 자동 선택 관련
  gimmickMode: GimmickMode;  // 자동/수동/하이브리드
  availableGimmicks: string[];  // 자동 선택 시 사용 가능한 기믹 풀
  levelGimmickOverrides?: LevelGimmickOverride[];  // 하이브리드 모드: 레벨별 기믹 오버라이드
  // 다중 세트 생성 관련
  multiSetConfig?: MultiSetConfig;
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
  // Detailed progress for long-running generations
  currentLevelStartTime?: number;   // Timestamp when current level started
  totalStartTime?: number;          // Timestamp when generation started
  averageTimePerLevel?: number;     // Average ms per level (calculated from completed)
  completedTimes?: number[];        // Time taken for each completed level (ms)
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
  // Retry information for grade matching
  retryCount?: number;         // Number of retries to achieve target grade
  targetGrade?: DifficultyGrade; // The grade we're trying to achieve
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
 * 레벨 재배치 결과
 */
export interface ReorderResult {
  reorderedLevels: LevelJSON[];
  reorderedDifficulties: number[];
  reorderedGrades: DifficultyGrade[];
  originalIndices: number[];  // 원래 순서에서의 인덱스
  improvements: {
    beforeError: number;  // 재배치 전 평균 오차
    afterError: number;   // 재배치 후 평균 오차
    swapCount: number;    // 교환된 레벨 수
  };
}

/**
 * 레벨들을 목표 난이도 그래프에 맞게 재배치
 * 등급 우선 알고리즘: 먼저 등급을 맞추고, 같은 등급 내에서 난이도 최적화
 */
export function reorderLevelsByDifficulty(
  levels: LevelJSON[],
  actualDifficulties: number[],
  grades: DifficultyGrade[],
  targetDifficulties: number[]
): ReorderResult {
  const n = levels.length;

  if (n === 0 || n !== actualDifficulties.length || n !== targetDifficulties.length) {
    return {
      reorderedLevels: levels,
      reorderedDifficulties: actualDifficulties,
      reorderedGrades: grades,
      originalIndices: Array.from({ length: n }, (_, i) => i),
      improvements: { beforeError: 0, afterError: 0, swapCount: 0 },
    };
  }

  // 재배치 전 오차 계산
  const beforeError = calculateAverageError(actualDifficulties, targetDifficulties);

  // 각 레벨에 대한 정보와 원래 인덱스 저장
  const levelInfos = levels.map((level, i) => ({
    level,
    actualDifficulty: actualDifficulties[i],
    grade: grades[i],
    originalIndex: i,
    assigned: false,
  }));

  // 결과 배열
  const result: (typeof levelInfos[0] | null)[] = new Array(n).fill(null);

  // 각 위치에 필요한 등급 계산
  const targetGrades = targetDifficulties.map(getGradeFromDifficulty);

  // 위치를 목표 난이도순으로 정렬 (쉬운 것부터)
  const sortedPositions = targetDifficulties
    .map((target, position) => ({ target, position, grade: targetGrades[position] }))
    .sort((a, b) => a.target - b.target);

  // 1단계: 등급이 일치하는 레벨을 우선 할당
  for (const { target, position, grade: requiredGrade } of sortedPositions) {
    let bestIdx = -1;
    let bestDiff = Infinity;

    // 같은 등급의 레벨 중 가장 가까운 난이도 찾기
    for (let i = 0; i < levelInfos.length; i++) {
      if (levelInfos[i].assigned) continue;
      if (levelInfos[i].grade !== requiredGrade) continue;

      const diff = Math.abs(levelInfos[i].actualDifficulty - target);
      if (diff < bestDiff) {
        bestDiff = diff;
        bestIdx = i;
      }
    }

    if (bestIdx !== -1) {
      levelInfos[bestIdx].assigned = true;
      result[position] = levelInfos[bestIdx];
    }
  }

  // 2단계: 할당되지 않은 위치에 남은 레벨 할당 (등급 무관, 난이도 우선)
  for (const { target, position } of sortedPositions) {
    if (result[position] !== null) continue;

    let bestIdx = -1;
    let bestDiff = Infinity;

    for (let i = 0; i < levelInfos.length; i++) {
      if (levelInfos[i].assigned) continue;

      const diff = Math.abs(levelInfos[i].actualDifficulty - target);
      if (diff < bestDiff) {
        bestDiff = diff;
        bestIdx = i;
      }
    }

    if (bestIdx !== -1) {
      levelInfos[bestIdx].assigned = true;
      result[position] = levelInfos[bestIdx];
    }
  }

  // 결과 추출 (null 체크)
  const validResults = result.map((r, i) => r || levelInfos[i]);
  const reorderedLevels = validResults.map(r => r.level);
  const reorderedDifficulties = validResults.map(r => r.actualDifficulty);
  const reorderedGrades = validResults.map(r => r.grade);
  const originalIndices = validResults.map(r => r.originalIndex);

  // 재배치 후 오차 계산
  const afterError = calculateAverageError(reorderedDifficulties, targetDifficulties);

  // 교환된 레벨 수 계산
  let swapCount = 0;
  for (let i = 0; i < n; i++) {
    if (originalIndices[i] !== i) swapCount++;
  }

  // 등급 일치 통계
  let gradeMatchCount = 0;
  for (let i = 0; i < n; i++) {
    if (reorderedGrades[i] === targetGrades[i]) gradeMatchCount++;
  }
  console.log(`📊 Grade matching: ${gradeMatchCount}/${n} positions match target grade`);

  return {
    reorderedLevels,
    reorderedDifficulties,
    reorderedGrades,
    originalIndices,
    improvements: {
      beforeError,
      afterError,
      swapCount,
    },
  };
}

/**
 * 평균 오차 계산 (0~1 범위)
 */
function calculateAverageError(actual: number[], target: number[]): number {
  if (actual.length === 0) return 0;
  const sum = actual.reduce((acc, val, i) => acc + Math.abs(val - target[i]), 0);
  return sum / actual.length;
}

/**
 * 등급 범위 정의
 * S: 0-20%, A: 20-40%, B: 40-60%, C: 60-80%, D: 80-100%
 */
export const GRADE_RANGES: Record<DifficultyGrade, { min: number; max: number; target: number }> = {
  S: { min: 0.0, max: 0.2, target: 0.1 },
  A: { min: 0.2, max: 0.4, target: 0.3 },
  B: { min: 0.4, max: 0.6, target: 0.5 },
  C: { min: 0.6, max: 0.8, target: 0.7 },
  D: { min: 0.8, max: 1.0, target: 0.9 },
};

/**
 * 난이도 값에서 등급 결정
 */
export function getGradeFromDifficulty(difficulty: number): DifficultyGrade {
  // Use <= to include boundary values in the lower grade
  // S: 0-20%, A: 21-40%, B: 41-60%, C: 61-80%, D: 81-100%
  if (difficulty <= 0.2) return 'S';
  if (difficulty <= 0.4) return 'A';
  if (difficulty <= 0.6) return 'B';
  if (difficulty <= 0.8) return 'C';
  return 'D';
}

/**
 * 등급별 분포 계산 결과
 */
export interface GradeDistribution {
  S: number;
  A: number;
  B: number;
  C: number;
  D: number;
  total: number;
}

/**
 * 난이도 프로필에서 등급별 필요 개수 계산
 */
export function calculateGradeDistribution(difficulties: number[]): GradeDistribution {
  const distribution: GradeDistribution = { S: 0, A: 0, B: 0, C: 0, D: 0, total: difficulties.length };

  for (const diff of difficulties) {
    const grade = getGradeFromDifficulty(diff);
    distribution[grade]++;
  }

  return distribution;
}

/**
 * 등급별 생성 계획
 * 각 등급별로 몇 개의 레벨을 생성할지와 목표 난이도
 */
export interface GradeGenerationPlan {
  grade: DifficultyGrade;
  count: number;
  targetDifficulty: number;  // 해당 등급의 중앙값
}

/**
 * 등급 분포에서 생성 계획 생성
 */
export function createGenerationPlan(distribution: GradeDistribution): GradeGenerationPlan[] {
  const grades: DifficultyGrade[] = ['S', 'A', 'B', 'C', 'D'];
  const plan: GradeGenerationPlan[] = [];

  for (const grade of grades) {
    if (distribution[grade] > 0) {
      plan.push({
        grade,
        count: distribution[grade],
        targetDifficulty: GRADE_RANGES[grade].target,
      });
    }
  }

  return plan;
}

/**
 * 기본 다중 세트 설정 생성
 */
export function createDefaultMultiSetConfig(): MultiSetConfig {
  return {
    enabled: false,
    setCount: 10,
    difficultyShiftPerSet: 0.05,  // 5% per set
    maxDifficultyClamp: 0.95,
  };
}

/**
 * 난이도 포인트를 특정 값만큼 시프트
 * @param points 원본 난이도 포인트
 * @param shift 시프트할 값 (0.05 = 5%)
 * @param maxClamp 최대 난이도 제한
 */
export function shiftDifficultyPoints(
  points: DifficultyPoint[],
  shift: number,
  maxClamp: number = 0.95
): DifficultyPoint[] {
  return points.map(p => ({
    ...p,
    difficulty: Math.min(maxClamp, Math.max(0.05, p.difficulty + shift)),
  }));
}

/**
 * 다중 세트의 총 레벨 수 계산
 */
export function calculateTotalLevels(levelCount: number, setCount: number): number {
  return levelCount * setCount;
}

/**
 * 10개 레벨 계단형 프리셋 (다중 세트 기본 패턴)
 * S(2) → A(3) → B(3) → C(2) 형태
 */
export const STEP_10_PRESET: DifficultyPoint[] = [
  { levelIndex: 1, difficulty: 0.1 },   // S
  { levelIndex: 2, difficulty: 0.15 },  // S
  { levelIndex: 3, difficulty: 0.25 },  // A
  { levelIndex: 4, difficulty: 0.30 },  // A
  { levelIndex: 5, difficulty: 0.35 },  // A
  { levelIndex: 6, difficulty: 0.45 },  // B
  { levelIndex: 7, difficulty: 0.50 },  // B
  { levelIndex: 8, difficulty: 0.55 },  // B
  { levelIndex: 9, difficulty: 0.65 },  // C
  { levelIndex: 10, difficulty: 0.70 }, // C
];

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

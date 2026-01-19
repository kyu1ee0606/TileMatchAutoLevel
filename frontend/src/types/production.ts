/**
 * Production Level Management Types
 * 1500개 레벨 출시 자동화를 위한 타입 정의
 */

import { LevelJSON, DifficultyGrade } from './index';

/**
 * 레벨 상태
 */
export type LevelStatus =
  | 'generated'      // 생성됨 (봇 검증 완료)
  | 'playtest_queue' // 플레이테스트 대기
  | 'playtesting'    // 플레이테스트 중
  | 'approved'       // 승인됨
  | 'rejected'       // 거부됨 (재생성 필요)
  | 'needs_rework'   // 수정 필요
  | 'exported';      // 출시 완료

/**
 * 플레이테스트 결과
 */
export interface PlaytestResult {
  tester_id: string;
  tester_name: string;
  tested_at: string;
  cleared: boolean;
  attempts: number;
  time_seconds: number;
  perceived_difficulty: 1 | 2 | 3 | 4 | 5; // 1=매우쉬움, 5=매우어려움
  fun_rating: 1 | 2 | 3 | 4 | 5;           // 1=지루함, 5=재미있음
  comments: string;
  issues: string[];  // 발견된 문제점들
}

/**
 * 프로덕션 레벨 메타데이터
 */
export interface ProductionLevelMeta {
  // 식별자
  level_number: number;        // 1-1500 전역 레벨 번호
  set_index: number;           // 세트 인덱스 (0-149)
  local_index: number;         // 세트 내 인덱스 (1-10)

  // 생성 정보
  generated_at: string;
  target_difficulty: number;
  actual_difficulty: number;
  grade: DifficultyGrade;

  // 봇 시뮬레이션 결과
  bot_clear_rates?: {
    novice: number;
    casual: number;
    average: number;
    expert: number;
    optimal: number;
  };
  match_score?: number;

  // 상태 관리
  status: LevelStatus;
  status_updated_at: string;

  // 플레이테스트
  playtest_required: boolean;  // 사람 테스트 필요 여부
  playtest_priority: number;   // 우선순위 (낮을수록 먼저)
  playtest_results: PlaytestResult[];

  // 승인 정보
  approved_by?: string;
  approved_at?: string;
  rejection_reason?: string;

  // 출시 정보
  exported_at?: string;
  export_version?: string;
}

/**
 * 프로덕션 레벨 전체 데이터
 */
export interface ProductionLevel {
  meta: ProductionLevelMeta;
  level_json: LevelJSON;
}

/**
 * 프로덕션 배치 (150개 세트)
 */
export interface ProductionBatch {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;

  // 생성 설정
  total_levels: number;        // 1500
  levels_per_set: number;      // 10
  total_sets: number;          // 150

  // 진행 상태
  generated_count: number;
  playtest_count: number;
  approved_count: number;
  rejected_count: number;
  exported_count: number;

  // 난이도 설정
  difficulty_start: number;    // 시작 난이도 (예: 0.1)
  difficulty_end: number;      // 종료 난이도 (예: 0.95)
  use_sawtooth: boolean;       // 톱니바퀴 패턴

  // 기믹 설정
  gimmick_unlock_levels: Record<string, number>;
}

/**
 * 플레이테스트 샘플링 전략
 */
export type PlaytestStrategy =
  | 'all'            // 모든 레벨 테스트
  | 'sample_10'      // 10개당 1개 샘플
  | 'sample_boss'    // 보스 레벨(10의 배수)만
  | 'grade_sample'   // 등급별 샘플 (S:10%, A:20%, B:30%, C:40%, D:50%)
  | 'low_match'      // 매치 점수 낮은 레벨만 (< 70%)
  | 'tutorial'       // 튜토리얼 레벨만 (기믹 해금 레벨)
  | 'custom';        // 커스텀 필터

/**
 * 플레이테스트 큐 설정
 */
export interface PlaytestQueueConfig {
  strategy: PlaytestStrategy;
  custom_filter?: {
    min_level?: number;
    max_level?: number;
    grades?: DifficultyGrade[];
    max_match_score?: number;
    include_tutorials?: boolean;
  };
}

/**
 * 프로덕션 내보내기 설정
 */
export interface ProductionExportConfig {
  format: 'json' | 'json_minified' | 'json_split';
  include_meta: boolean;
  filename_pattern: string;  // e.g., "level_{number:04d}.json"
  output_dir: string;
}

/**
 * 프로덕션 대시보드 통계
 */
export interface ProductionStats {
  total_levels: number;

  by_status: Record<LevelStatus, number>;
  by_grade: Record<DifficultyGrade, number>;

  playtest_progress: {
    total_required: number;
    completed: number;
    pending: number;
  };

  quality_metrics: {
    avg_match_score: number;
    avg_fun_rating: number;
    avg_perceived_difficulty: number;
    rejection_rate: number;
  };

  estimated_completion: {
    remaining_playtest_hours: number;
    ready_for_export: number;
  };
}

/**
 * 프로덕션 생성 진행 상태
 */
export interface ProductionGenerationProgress {
  status: 'idle' | 'generating' | 'paused' | 'completed' | 'error';

  // 전체 진행률
  total_sets: number;
  completed_sets: number;
  current_set_index: number;

  total_levels: number;
  completed_levels: number;
  current_level: number;

  // 시간 추적
  started_at?: string;
  elapsed_ms: number;
  estimated_remaining_ms: number;

  // 오류 정보
  failed_levels: number[];
  last_error?: string;

  // 자동 저장
  last_checkpoint_at?: string;
  checkpoint_interval_levels: number;  // 매 N개 레벨마다 체크포인트
}

/**
 * 1500개 레벨 프리셋
 */
export const PRODUCTION_1500_PRESETS = {
  // 기본 선형 증가
  linear: {
    name: '선형 1500',
    description: '레벨 1~1500까지 선형으로 난이도 증가',
    difficulty_start: 0.1,
    difficulty_end: 0.95,
    use_sawtooth: false,
  },

  // 톱니바퀴 패턴 (보스/휴식 사이클)
  sawtooth: {
    name: '톱니바퀴 1500',
    description: '10레벨 단위로 보스→휴식 사이클 반복',
    difficulty_start: 0.1,
    difficulty_end: 0.95,
    use_sawtooth: true,
  },

  // 3단계 구간
  three_stage: {
    name: '3단계 1500',
    description: '초급(1-500), 중급(501-1000), 고급(1001-1500)',
    difficulty_start: 0.1,
    difficulty_end: 0.95,
    stages: [
      { start: 1, end: 500, difficulty_range: [0.1, 0.4] },
      { start: 501, end: 1000, difficulty_range: [0.35, 0.7] },
      { start: 1001, end: 1500, difficulty_range: [0.6, 0.95] },
    ],
    use_sawtooth: true,
  },
} as const;

/**
 * 플레이테스트 샘플링 비율 계산
 */
export function calculatePlaytestSampleSize(
  totalLevels: number,
  strategy: PlaytestStrategy,
  grades?: Record<DifficultyGrade, number>
): number {
  switch (strategy) {
    case 'all':
      return totalLevels;
    case 'sample_10':
      return Math.ceil(totalLevels / 10);
    case 'sample_boss':
      return Math.ceil(totalLevels / 10);  // 10의 배수
    case 'grade_sample':
      if (!grades) return Math.ceil(totalLevels * 0.3);
      // S:10%, A:20%, B:30%, C:40%, D:50%
      return Math.ceil(
        (grades.S || 0) * 0.1 +
        (grades.A || 0) * 0.2 +
        (grades.B || 0) * 0.3 +
        (grades.C || 0) * 0.4 +
        (grades.D || 0) * 0.5
      );
    case 'low_match':
      return Math.ceil(totalLevels * 0.2);  // 예상 20%
    case 'tutorial':
      return 11;  // 기믹 11개 = 튜토리얼 11개
    default:
      return Math.ceil(totalLevels * 0.1);
  }
}

/**
 * 레벨 번호에서 세트 정보 계산
 */
export function getLevelSetInfo(levelNumber: number, levelsPerSet: number = 10) {
  const setIndex = Math.floor((levelNumber - 1) / levelsPerSet);
  const localIndex = ((levelNumber - 1) % levelsPerSet) + 1;
  return { setIndex, localIndex };
}

/**
 * 플레이테스트 필요 여부 결정
 */
export function shouldRequirePlaytest(
  meta: Partial<ProductionLevelMeta>,
  config: PlaytestQueueConfig
): boolean {
  const { level_number = 0, grade = 'B', match_score = 100 } = meta;
  const { strategy, custom_filter } = config;

  switch (strategy) {
    case 'all':
      return true;

    case 'sample_10':
      return level_number % 10 === 0;  // 10의 배수

    case 'sample_boss':
      return level_number % 10 === 0;  // 보스 레벨

    case 'grade_sample': {
      // 등급별 확률로 샘플링
      const rates: Record<DifficultyGrade, number> = {
        S: 0.1, A: 0.2, B: 0.3, C: 0.4, D: 0.5
      };
      return Math.random() < (rates[grade] || 0.3);
    }

    case 'low_match':
      return (match_score || 100) < 70;

    case 'tutorial': {
      // 기믹 해금 레벨
      const tutorialLevels = [11, 21, 36, 51, 66, 81, 96, 111, 126, 141, 156];
      return tutorialLevels.includes(level_number);
    }

    case 'custom':
      if (!custom_filter) return false;
      const { min_level, max_level, grades, max_match_score, include_tutorials } = custom_filter;

      if (min_level && level_number < min_level) return false;
      if (max_level && level_number > max_level) return false;
      if (grades && !grades.includes(grade)) return false;
      if (max_match_score && (match_score || 100) > max_match_score) return false;
      if (include_tutorials) {
        const tutorialLevels = [11, 21, 36, 51, 66, 81, 96, 111, 126, 141, 156];
        if (tutorialLevels.includes(level_number)) return true;
      }
      return true;

    default:
      return false;
  }
}

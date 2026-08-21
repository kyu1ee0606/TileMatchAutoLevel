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
 * 자동 테스트 (봇 시뮬레이션) 결과
 */
export interface AutoTestResult {
  tested_at: string;
  iterations: number;
  // [v15.14] novice/casual은 optional (검증에서 제외됨)
  bot_clear_rates: {
    novice?: number;
    casual?: number;
    average: number;
    expert: number;
    optimal: number;
  };
  bot_target_rates: {
    novice?: number;
    casual?: number;
    average: number;
    expert: number;
    optimal: number;
  };
  match_score: number;  // 0-100
  autoplay_score: number;
  autoplay_grade: string;
  static_score: number;
  static_grade: string;
  balance_status: 'balanced' | 'too_easy' | 'too_hard' | 'unbalanced';
  execution_time_ms: number;
}

/**
 * 테스트 모드
 */
export type TestMode = 'manual' | 'auto_single' | 'auto_batch';

/**
 * 자동 테스트 필터 타입
 */
export type AutoTestFilter =
  | 'all'              // 전체 레벨
  | 'untested'         // 미테스트 레벨만
  | 'boss'             // 보스 레벨 (10의 배수)
  | 'tutorial'         // 튜토리얼 레벨
  | 'low_match'        // 매치 점수 낮은 레벨
  | 'by_grade'         // 특정 등급
  | 'by_range'         // 레벨 범위
  | 'custom';          // 커스텀 필터

/**
 * 일괄 자동 테스트 설정
 */
export interface BatchAutoTestConfig {
  filter: AutoTestFilter;
  iterations: number;  // 봇 시뮬레이션 반복 횟수
  grades?: string[];   // by_grade 필터용
  level_range?: { min: number; max: number };  // by_range 필터용
  max_levels?: number; // 최대 테스트 레벨 수
  save_results?: boolean;  // 결과를 레벨 메타에 저장
}

/**
 * 일괄 자동 테스트 진행 상태
 */
export interface BatchAutoTestProgress {
  status: 'idle' | 'running' | 'paused' | 'completed' | 'error';
  total_levels: number;
  completed_levels: number;
  current_level_number: number;
  started_at?: string;
  elapsed_ms: number;
  estimated_remaining_ms: number;
  results: {
    level_number: number;
    match_score: number;
    autoplay_grade: string;
    balance_status: string;
  }[];
  failed_levels: number[];
  last_error?: string;
  // 통계 요약
  summary?: {
    avg_match_score: number;
    grade_distribution: Record<string, number>;
    balance_distribution: Record<string, number>;
    pass_rate: number;  // match_score >= 70 비율
  };
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
  // [v15.14] novice/casual은 optional (검증에서 제외됨)
  bot_clear_rates?: {
    novice?: number;
    casual?: number;
    average: number;
    expert: number;
    optimal: number;
  };
  match_score?: number;
  validation_attempts?: number;  // 검증 기반 생성시 재시도 횟수

  // 사후 배치 검증 결과
  target_clear_rates?: Record<string, number>;  // 목표 클리어율
  verified?: boolean;                            // 검증 완료 여부
  verification_passed?: boolean;                 // 검증 통과 여부

  // [v16] RL 검증 (예측 유저 클리어율 기반 — 주력 지표)
  verification_method?: 'bot' | 'rl';            // 검증 방식 (레거시 bot / 신규 rl)
  predicted_clear_rate?: number;                 // 예측 유저 클리어율 0~1 (캐주얼 가중)
  target_clear_rate?: number;                    // 목표곡선 기대 클리어율 0~1
  clear_rate_gap?: number;                       // predicted - target
  rl_classification?: string;                    // RL 분류 (very_easy~unclearable_suspect)
  luck_suspect?: boolean;                        // 운빨 레벨 의심 (경고)
  // [RL 신뢰도] 봇 예측이 구조와 어긋나는 레벨. true 면 이 레벨의 RL 값(predicted_clear_rate,
  // verification_passed)을 난이도 판단·통과 판정에 쓰면 안 된다.
  // 근거: 야간 A* 전수판정에서 RL 0% 인 246개가 전부 클리어 가능했고, 진짜 불가 18개는 전부 RL>0.
  rl_unreliable?: boolean;
  rl_unreliable_reason?: string;
  solver_verdict?: string;                       // A* 판정 (측정했을 때만)

  // [v15.35] 재생성 정보
  regenerated?: boolean;                         // 재생성 여부
  regeneration_attempts?: number;                // 재생성 시도 횟수

  // 패턴 생성 정보
  pattern_index?: number;                        // 사용된 패턴 인덱스 (undefined = 랜덤/패턴 없음)
  pattern_type?: 'aesthetic' | 'geometric' | 'clustered';  // 패턴 타입

  // [v15.55] 레벨 템플릿 기반 생성 출처
  template_id?: string;                          // 사용된 템플릿 ID (템플릿 기반이면 존재)
  template_source_difficulty?: number;           // 템플릿의 측정 난이도

  // 재생성 추적 (이진 탐색 수렴용)
  regen_attempts?: number;          // 재생성 시도 횟수
  regen_lower_bound?: number;       // 난이도 하한 (너무 쉬웠던 경계)
  regen_upper_bound?: number;       // 난이도 상한 (너무 어려웠던 경계)

  // [MC 0.5단계] 몬테카를로 스킬 스윕 측정/교체 기록
  mc_measurement?: {
    theta0: number | null;
    k: number | null;
    difficulty_score: number | null;   // 1-AUC
    classification: string;
    measured_at: string;
  };
  mc_replaced_backup?: LevelJSON;      // 교체 직전 원본 (1세대 롤백용)
  mc_replaced_at?: string;

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

  // [무한 레벨 사본] 내보내기 시점에만 붙는 표시(저장본에는 없음).
  // 1~1500 완주 유저용으로 원본 레벨을 `infinity_{index}` 로 복사할 때 출처를 남긴다.
  infinity_id?: string;            // 예: 'infinity_1'
  infinity_index?: number;         // 1부터
  infinity_source_level?: number;  // 복사 원본 레벨 번호
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
  /**
   * 실제 저장된 레벨 수(status 무관). '이어서 생성' 재개 판정 근거.
   * generated_count 는 status==='generated' 인 것만 세므로 검증 후 playtest_queue 로 바뀌면
   * 줄어든다 → 생성 진척도로 쓰면 안 됨. 구배치는 undefined 라 폴백 필요.
   */
  saved_level_count?: number;

  // 난이도 설정
  difficulty_start: number;    // 시작 난이도 (예: 0.1)
  difficulty_end: number;      // 종료 난이도 (예: 0.95)
  use_sawtooth: boolean;       // 톱니바퀴 패턴
  /**
   * 타일 종류 수(V) 프로파일 — 'baseline' | 'hard_steep'. 생성 시점 값을 배치에 박는다.
   *
   * 예전엔 이 값이 localStorage(전역 UI 설정)에만 있어서, 배치를 어떤 곡선으로 만들었는지
   * 데이터에 남지 않았다. 그래서 난이도 다이얼의 '타일 종류' ±2 클램프가 항상 baseline
   * 기준으로 걸렸다 — hard_steep 으로 만든 배치인데 Lv550 이 8~12 로 묶여
   * (hard_steep 기준이면 10~14) 더 올릴 수가 없었다.
   *
   * 미지정(구배치)이면 baseline 으로 본다.
   */
  tile_type_profile?: string;

  // 기믹 설정
  gimmick_unlock_levels: Record<string, number>;

  // [서버 동기화] 이 로컬 사본이 마지막으로 반영한 서버 버전. push 성공/pull 시 갱신.
  // 마운트 sync에서 서버 버전과 비교해 '서버가 더 최신'(다른 브라우저/서버측 수정)이면 자동 pull.
  __server_version?: number;
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
  // [무한 레벨] 1~1500 을 다 깬 유저용. 지정하면 원본 레벨을 `infinity_{index}` 로 **복사 추가**한다
  // (원본 1~1500 내보내기는 그대로 유지). undefined = 미포함.
  infinity?: InfinityExportConfig;
}

/**
 * [무한 레벨 복사 규칙]
 *   infinity_{index} = 원본 레벨 (sourceStart + index - 1)
 *   기본값 501~1500 → infinity_1 ~ infinity_1000
 *
 * 오프셋(sourceStart-1 = 500)이 10의 배수라 `원본레벨 % 10 === index % 10` 이 성립한다.
 * → 보스(10배수)·스페셜(끝자리9) 위치와 autoCollect 대상이 원본과 그대로 정렬되므로
 *   보상/자동수집 규칙을 **원본 레벨번호 기준으로 그대로** 적용하면 된다(별도 보정 불필요).
 */
export interface InfinityExportConfig {
  enabled: boolean;
  /** true = **무한 사본만** 내보낸다(원본 제외). false = 원본 뒤에 사본을 덧붙인다. */
  only: boolean;
  prefix: string;        // 기본 'infinity_'
  sourceStart: number;   // 기본 501
  sourceEnd: number;     // 기본 1500
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

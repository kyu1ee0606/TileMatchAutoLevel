/**
 * 실유저 클리어율 표시 라벨·문구 사전 (문서 38 §4). 화면 문자열만 정의한다 —
 * 내부 필드명(p_in_band 등)·판정 수치·임계값·저장 데이터 의미는 바꾸지 않는다.
 * 런타임 import 없음(타입만) — frontend/tests 의 node 테스트가 그대로 불러 쓴다.
 */
import type { UserExpectedResult, UserExpectedVerdict } from '../../api/clearRateTarget';

/** 근거 코드 → 사람이 읽는 문구 (ClearRateCell 배지와 검증 탭 사유가 같이 쓴다) */
export const FLAG_LABEL: Record<string, string> = {
  PLACEMENT_MISSING: '배치 위치 없음',
  LEVEL_OUT_OF_RANGE: '학습 범위 밖 레벨',
  GIMMICK_UNSEEN: '학습에 없는 기믹',
  GIMMICK_LOW_TRAIN: '기믹 데이터 부족',
  FEATURE_OOD: '학습 범위 밖 특징',
  BOT_PROTOCOL_MISMATCH: '봇 측정 불일치',
  MEASUREMENT_MISSING: '봇 측정 없음',
  BOT_CONDITION_MISMATCH: '측정 조건 불일치',
  BOT_SOURCE_UNKNOWN: '측정 출처 불명',
  BOT_CACHE_CONDITION_MISMATCH: '측정 조건 불일치 → 근거 부족',
  UNSOLVED: '봇 클리어 0',
  CAT_HELP_UNSUPPORTED: '냥이 레벨 학습 없음',
  TIME_LIMIT_UNSUPPORTED: '시간 제한 학습 없음',
  TARGET_OUT_OF_SUPPORT: '목표 범위 밖',
  LOW_CONFIDENCE: '신뢰 낮음',
  NEAR_CEILING: '천장',
  GIMMICK_FIRST: '기믹 첫 등장',
  NOVELTY_HIGH: '기믹 노출 적음',
  GIMMICK_BOT_WEAK: '봇 약점 기믹',
  STORED_CONDITION_DIFFERS: '저장값≠업로드값',
  PRED_ZONE_HIGH_ERROR: '이 예측 구간 오차 큼',
  PRED_ZONE_MID_ERROR: '이 예측 구간 오차 중간',
  SIMILAR_MAPS_FEW: '유사 맵 적음',
  COMBO_HIGH_ERROR: '기믹 조합 오차 큼',
  SELECTION_UNCONFIRMED: '확인 측정(C 시드) 없음',
};

export const reasonLabel = (code: string): string => FLAG_LABEL[code] ?? code;

/** 내부 p_in_band(기존 화면 이름 "목표 충족 확률") 의 표시 이름. 값·임계값은 그대로 */
export const TARGET_PROXIMITY_LABEL = '목표 근접 지표(참고)';
/** 백엔드 판정 reason 원문(select.verdict)에 들어 있는 옛 이름 — 화면에서는 위 이름으로 바꿔 보인다(원문 저장값 불변) */
export const LEGACY_PROXIMITY_TEXT = '목표 범위 안 확률';
export const TARGET_PROXIMITY_TOOLTIP =
  '검증된 확률이 아님(현행 모델은 과신 경향 확인됨, 문서 36). 예측 80% 범위가 목표 띠 안에 드는 정도를 0~1 점수로 표시.';

export const A_VERDICT_LABEL: Record<UserExpectedVerdict, string> = {
  PASS: '합격',
  FAIL: '불합격',
  INSUFFICIENT_EVIDENCE: '근거 부족',
};
export const A_VERDICT_CLASS: Record<UserExpectedVerdict, string> = {
  PASS: 'bg-emerald-900/60 text-emerald-200 border-emerald-700',
  FAIL: 'bg-red-900/60 text-red-200 border-red-700',
  INSUFFICIENT_EVIDENCE: 'bg-gray-700 text-gray-200 border-gray-500',
};

export const LEGACY_TARGET_TOOLTIP = '기존 목표 곡선 값(봇 척도) — 실유저 목표 아님, 참고만 (문서 31 §2)';
export const SECTION_NOTE =
  '참고 표시 — 기존 배치 검증(봇 매치 점수)·verification_passed·업로드 값과 무관. 결과는 검증 탭 전용 저장소에만 저장.';

// 목표 곡선 미리보기 — /verify/target-check(user_expected_precheck) 결과는 "입력 지원 범위"만 뜻한다(배치 위치·목표가
// 학습 범위 안인지). 측정 후 예측 구간 신뢰도 게이트는 반영되지 않으므로 "신뢰 판정 가능"처럼 쓰지 않는다.
// 모델 수치(구간 경계·오차)는 모델 교체 시 낡으므로 문구에 넣지 않는다.
export const TARGET_SUPPORT_HEADER = '현 모델 입력 지원 범위';
export const TARGET_SUPPORT_NOTE =
  '입력 지원 범위 통과는 합격이나 높은 신뢰도를 보장하지 않습니다. 실제 판정은 측정 결과와 현재 모델의 신뢰도 기준을 함께 확인합니다.';
/** target-check 항목 → 미리보기 칸 문구. 미조회는 "미확인" */
export function targetSupportText(check: { judgeable: boolean; codes: string[] } | null | undefined): string {
  if (!check) return '미확인';
  return check.judgeable ? '범위 안' : `범위 밖(${check.codes.map(reasonLabel).join(', ')})`;
}

/** 퍼센트 입력("85", "85.5") → 0~1. 빈 값·범위 밖(0 이하, 100 이상)·숫자 아님은 null (기본값 없음) */
export function parseTargetPercent(input: string): number | null {
  const s = input.trim();
  if (!/^\d+(\.\d+)?$/.test(s)) return null;
  const v = Number(s);
  return v > 0 && v < 100 ? v / 100 : null;
}

/** p_in_band → "0.62" (퍼센트로 쓰지 않는다 — 확률처럼 읽히지 않게) */
export const formatProximity = (p: number | null | undefined): string => (p == null ? '—' : p.toFixed(2));

type Verdict = UserExpectedResult['verdict'];

/** 판정 사유 코드 (중복 제거, 순서: 지원 범위 → 목표 hard 플래그 → 저신뢰) */
export function verdictReasonCodes(v: Verdict): string[] {
  if (v.verdict !== 'INSUFFICIENT_EVIDENCE') return [];
  const flags = v.target_flags ?? [];
  const codes = [...(v.support_reasons ?? []), ...flags.filter(f => f.severity === 'hard').map(f => f.code)];
  if (codes.length === 0 && (v.confidence === 'low' || flags.some(f => f.code === 'LOW_CONFIDENCE'))) {
    codes.push('LOW_CONFIDENCE');
  }
  return [...new Set(codes)];
}

export interface VerdictView {
  label: string;
  cls: string;
  reasons: string[];      // 사람이 읽는 사유 문구
  rawReason: string;      // 백엔드 reason (툴팁, 옛 지표 이름만 표시용으로 치환)
  proximity: string;      // 목표 근접 지표 표시 문자열
}

export function verdictView(r: UserExpectedResult): VerdictView {
  const v = r.verdict;
  return {
    label: A_VERDICT_LABEL[v.verdict],
    cls: A_VERDICT_CLASS[v.verdict],
    reasons: verdictReasonCodes(v).map(reasonLabel),
    rawReason: v.reason.split(LEGACY_PROXIMITY_TEXT).join('목표 근접 지표'),
    proximity: formatProximity(v.p_in_band),
  };
}

export interface ProvenanceView {
  model: string;
  bot: string;
  protocol: string;
  seedBand: string;
  source: string;
  confirmed: boolean;     // C 시드 확인 측정 여부 (봇 측정 안정성 확인일 뿐 실유저 검증 아님)
}

export function provenanceView(r: UserExpectedResult): ProvenanceView {
  const p = r.prediction;
  return {
    model: p.model_version,
    bot: p.measurement?.bot_version ?? p.bot_version,
    protocol: p.measurement?.protocol ?? p.bot_protocol,
    seedBand: p.measurement?.seed_band ?? '—',
    source: p.measurement?.source ?? '측정 없음',
    confirmed: r.verdict.bot_seed_confirmed,
  };
}

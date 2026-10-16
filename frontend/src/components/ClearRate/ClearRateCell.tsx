/**
 * 새 실유저 클리어율 예측 — 배치 표 1칸 (문서 31 §3-4 카드의 1줄 압축판, 문서 33 §1).
 * 참고용 병행 표시: 기존 predicted_clear_rate·합격 판정과 별개. 레벨 메타의 새 필드만 읽는다.
 */
import type { ClearRateEvidenceFlag } from '../../api/clearRate';
import type { ProductionLevelMeta } from '../../types/production';

export type ClearRateCellProps = Pick<ProductionLevelMeta,
  'expected_clear_rate_v1' | 'clear_rate_range80' | 'clear_rate_confidence' | 'clear_rate_evidence_flags' |
  'unaided_lb_expected' | 'help_rate_expected' | 'clear_rate_status' | 'clear_rate_model_version'>;

const FLAG_LABEL: Record<string, string> = {
  PLACEMENT_MISSING: '배치 위치 없음',
  LEVEL_OUT_OF_RANGE: '학습 범위 밖 레벨',
  GIMMICK_UNSEEN: '학습에 없는 기믹',
  GIMMICK_LOW_TRAIN: '기믹 데이터 부족',
  FEATURE_OOD: '학습 범위 밖 특징',
  BOT_PROTOCOL_MISMATCH: '봇 측정 불일치',
  MEASUREMENT_MISSING: '봇 측정 없음',
  BOT_CONDITION_MISMATCH: '측정 조건 불일치',
  BOT_SOURCE_UNKNOWN: '측정 출처 불명',
  UNSOLVED: '봇 클리어 0',
  TARGET_OUT_OF_SUPPORT: '목표 범위 밖',
  LOW_CONFIDENCE: '신뢰 낮음',
  NEAR_CEILING: '천장',
  GIMMICK_FIRST: '기믹 첫 등장',
  NOVELTY_HIGH: '기믹 노출 적음',
  GIMMICK_BOT_WEAK: '봇 약점 기믹',
};

const CONF_LABEL = { high: '높음', medium: '중간', low: '낮음' } as const;
const CONF_CLASS = { high: 'text-emerald-300', medium: 'text-yellow-300', low: 'text-orange-300' } as const;

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const pct0 = (v: number) => `${Math.round(v * 100)}`;

function FlagBadge({ f }: { f: ClearRateEvidenceFlag }) {
  const cls = f.severity === 'hard'
    ? 'bg-gray-600 text-gray-100 border-gray-500'
    : f.code === 'LOW_CONFIDENCE'
      ? 'bg-orange-900/60 text-orange-200 border-orange-700'
      : 'bg-sky-900/60 text-sky-200 border-sky-700';
  return (
    <span className={`px-1 rounded border text-[10px] leading-4 whitespace-nowrap ${cls}`} title={f.detail || f.code}>
      {FLAG_LABEL[f.code] ?? f.code}
    </span>
  );
}

export function ClearRateCell(props: ClearRateCellProps) {
  const {
    expected_clear_rate_v1: expected, clear_rate_range80: range, clear_rate_confidence: conf,
    clear_rate_evidence_flags: flags = [], unaided_lb_expected: lb, help_rate_expected: help,
    clear_rate_status: status, clear_rate_model_version: version,
  } = props;

  if (!status) {
    return <span className="text-gray-500 text-xs" title="새 예측 미계산">—</span>;
  }
  if (status === 'measurement_required') {
    return (
      <span className="text-gray-400 text-xs" title="이 게임 조건(맵·useTileCount·시드 등)의 봇 v2.4 측정(θ 4개 × 128판)이 없어 예측하지 않음">
        측정 필요
      </span>
    );
  }
  if (status === 'insufficient_evidence' || expected == null) {
    return (
      <div className="flex flex-wrap items-center gap-1" title={version ? `모델 ${version}` : undefined}>
        <span className="text-gray-300 text-xs">⏸ 근거 부족</span>
        {flags.filter(f => f.severity === 'hard').map(f => <FlagBadge key={f.code + f.detail} f={f} />)}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-0.5" title={version ? `새 예측(첫 시도·도움 포함) · 모델 ${version}` : undefined}>
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-sm font-bold text-indigo-200">{pct(expected)}</span>
        {range && <span className="text-[11px] text-gray-400">[{pct0(range[0])}–{pct0(range[1])}]</span>}
        {conf && <span className={`text-[10px] ${CONF_CLASS[conf]}`}>신뢰 {CONF_LABEL[conf]}</span>}
        {flags.map(f => <FlagBadge key={f.code + f.detail} f={f} />)}
      </div>
      <div className="text-[10px] text-gray-500">
        무도움 {lb != null ? pct0(lb) + '%' : '—'} · 도움 사용 {help != null ? pct0(help) + '%' : '—'}
      </div>
    </div>
  );
}

export default ClearRateCell;

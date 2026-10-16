/**
 * B 모드 — 봇 가상 클리어율 1칸 (문서 35 §9-6). A 열(ClearRateCell)과 별도 칸으로만 쓴다. 같은 칸에 두 숫자를 넣지 않는다.
 * "실측 미검증" 배지는 항상 보이며 끌 수 있는 prop 이 없다. 합격(초록) 색은 쓰지 않는다(중립색 + 테두리).
 * 표시 대상: target-eval 응답의 bot_virtual (봇 v2.4 규칙만·θ0.85·무도움). 업로드·표시 난이도·predicted_clear_rate 와 무관.
 */
import type { BotVirtualResult, BotVirtualVerdict } from '../../api/clearRateTarget';

export type BotVirtualCellProps = Pick<BotVirtualResult,
  'bot_virtual_rate_c' | 'bot_virtual_half_width_c' | 'bot_virtual_verdict' | 'reason' | 'bot_virtual_target' |
  'bot_virtual_games_c' | 'bot_virtual_def_id'>;

const TOOLTIP = '봇 시행 오차만 반영 — 실유저 예측 범위 아님 · 봇 목표 충족 ≠ 유저 합격';
const DEF_LABEL = 'θ0.85·v2.4 규칙만·무도움';
const VERDICT_LABEL: Record<BotVirtualVerdict, string> = {
  BOT_TARGET_MET: '봇 기준: 목표 충족',
  BOT_TARGET_NOT_MET: '봇 기준: 목표 미충족',
  BOT_MEASUREMENT_INSUFFICIENT: '봇 기준: 측정 부족',
};

/** 고정 배지 — 실유저 기준은 항상 실측 미검증 */
export function UnverifiedBadge() {
  return (
    <span className="px-1 rounded border border-gray-500 bg-gray-700 text-gray-200 text-[10px] leading-4 whitespace-nowrap"
      title={TOOLTIP}>
      실측 미검증
    </span>
  );
}

export function BotVirtualCell(props: BotVirtualCellProps) {
  const { bot_virtual_rate_c: rate, bot_virtual_half_width_c: hw, bot_virtual_verdict: verdict, reason,
    bot_virtual_target: target, bot_virtual_games_c: games, bot_virtual_def_id: defId } = props;
  return (
    <div className="flex flex-wrap items-center gap-1" title={`${TOOLTIP}\n정의 ${defId} · 목표 ${Math.round(target * 100)}%`}>
      {rate != null && hw != null ? (
        <span className="text-gray-200 text-xs whitespace-nowrap">
          봇 가상 {Math.round(rate * 100)}% ±{(hw * 100).toFixed(1)}%p
        </span>
      ) : (
        <span className="text-gray-400 text-xs">봇 가상 —</span>
      )}
      <UnverifiedBadge />
      <span className="px-1 rounded border border-slate-500 text-slate-200 text-[10px] leading-4 whitespace-nowrap"
        title={reason}>
        {VERDICT_LABEL[verdict]}
      </span>
      <span className="text-gray-500 text-[10px] whitespace-nowrap">{DEF_LABEL}{games ? ` · ${games}판` : ''}</span>
    </div>
  );
}

export default BotVirtualCell;

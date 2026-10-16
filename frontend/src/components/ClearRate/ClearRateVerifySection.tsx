/**
 * 검증 탭(BatchVerifyPanel) 하단 — 실유저 예상 클리어율(A)·봇 가상 클리어율(B) 참고 판정 (문서 38).
 * - 기존 배치 검증·verification_passed·업로드·게임 표시값과 무관. 결과는 화면에만 두고 저장하지 않는다.
 * - A/B 는 사용자가 각각 버튼으로 명시 실행한다(기본 목표값 없음). A 결과가 근거 부족이어도 B 로 자동 전환하지 않는다.
 * - B 는 별도 칸, 회색 "실측 미검증" 배지 고정, 초록 금지. B 값을 예상 유저 클리어율·업로드에 연결하지 않는다.
 * - 봇을 돌리지 않는다: A 는 모델 측정 캐시(/predict 와 동일 조회)만, B 는 저장된 측정이 없어 "측정 부족" 이 정상이다.
 */
import { useEffect, useState } from 'react';
import { getProductionLevelsByBatch } from '../../storage/productionStorage';
import type { ProductionLevel } from '../../types/production';
import { toClearRateMeta } from '../../api/clearRate';
import { evaluateClearRateTarget, type BotVirtualResult, type UserExpectedResult } from '../../api/clearRateTarget';
import { ClearRateCell } from './ClearRateCell';
import { BotVirtualCell, UnverifiedBadge } from './BotVirtualCell';
import {
  LEGACY_TARGET_TOOLTIP, SECTION_NOTE, TARGET_PROXIMITY_LABEL, TARGET_PROXIMITY_TOOLTIP,
  parseTargetPercent, provenanceView, verdictView,
} from './clearRateLabels';

type Mode = 'A' | 'B';
interface Row { a?: UserExpectedResult | null; b?: BotVirtualResult | null; aError?: string; bError?: string }

const errText = (e: unknown): string => {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return detail != null ? JSON.stringify(detail) : e instanceof Error ? e.message : String(e);
};

export function ClearRateVerifySection({ batchId }: { batchId: string }) {
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [aTarget, setATarget] = useState('');
  const [bTarget, setBTarget] = useState('');
  const [rows, setRows] = useState<Record<number, Row>>({});
  const [running, setRunning] = useState<Mode | null>(null);
  const [progress, setProgress] = useState({ done: 0, total: 0 });

  useEffect(() => {
    let alive = true;
    setRows({});
    getProductionLevelsByBatch(batchId)
      .then(ls => { if (alive) setLevels([...ls].sort((x, y) => x.meta.level_number - y.meta.level_number)); })
      .catch(err => console.error('[ClearRateVerify] load failed:', err));
    return () => { alive = false; };
  }, [batchId]);

  const run = async (mode: Mode) => {
    const target = parseTargetPercent(mode === 'A' ? aTarget : bTarget);
    if (target == null || running) return;
    setRunning(mode);
    setProgress({ done: 0, total: levels.length });
    for (let i = 0; i < levels.length; i++) {
      const lv = levels[i];
      const n = lv.meta.level_number;
      try {
        const res = await evaluateClearRateTarget(mode === 'A'
          ? { target_mode: 'user_expected', target, level_json: lv.level_json, placement_level: n, use_cached_measurement: true }
          : { target_mode: 'bot_virtual', target, level_json: lv.level_json, placement_level: n });
        setRows(prev => ({
          ...prev,
          [n]: mode === 'A' ? { ...prev[n], a: res.user_expected, aError: undefined }
                            : { ...prev[n], b: res.bot_virtual, bError: undefined },
        }));
      } catch (e) {
        const msg = errText(e);
        setRows(prev => ({ ...prev, [n]: mode === 'A' ? { ...prev[n], aError: msg } : { ...prev[n], bError: msg } }));
      }
      setProgress({ done: i + 1, total: levels.length });
    }
    setRunning(null);
  };

  const counts = Object.values(rows).reduce((c, r) => {
    if (r.a) c[r.a.verdict.verdict] += 1;
    return c;
  }, { PASS: 0, FAIL: 0, INSUFFICIENT_EVIDENCE: 0 });

  const targetInput = (mode: Mode, label: string, hint: string, value: string, set: (s: string) => void) => (
    <label className="flex flex-col gap-1 text-xs text-gray-300">
      <span>{label}</span>
      <div className="flex items-center gap-2">
        <input
          data-testid={`cr-target-${mode}`}
          type="text" inputMode="decimal" placeholder="예: 90" value={value}
          onChange={e => set(e.target.value)}
          className="w-20 px-2 py-1 text-sm border rounded bg-gray-700 border-gray-600"
        />
        <span>%</span>
        <button
          data-testid={`cr-run-${mode}`}
          onClick={() => run(mode)}
          disabled={running !== null || levels.length === 0 || parseTargetPercent(value) == null}
          className="px-3 py-1 rounded bg-slate-600 hover:bg-slate-500 disabled:opacity-40 text-white text-xs"
        >
          {mode === 'A' ? 'A 예상 유저 클리어율 계산' : 'B 봇 가상 클리어율 계산'}
        </button>
      </div>
      <span className="text-[10px] text-gray-500">{hint}</span>
    </label>
  );

  return (
    <div className="border-t border-gray-700 pt-4 space-y-3" data-testid="clear-rate-verify-section">
      <div className="flex items-baseline justify-between">
        <h4 className="font-medium text-sm">실유저 예상 클리어율 판정 (참고)</h4>
        <span className="text-[11px] text-gray-500">{SECTION_NOTE}</span>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {targetInput('A', 'A 목표 실유저 클리어율 (첫 시도·도움 포함)',
          '배치 전 레벨에 같은 목표 적용 · 레벨 번호 = 배치 위치', aTarget, setATarget)}
        {targetInput('B', 'B 봇 목표 성공률 (θ0.85·v2.4 규칙만·무도움)',
          'A 목표와 비교 불가 · 결과는 실측 미검증', bTarget, setBTarget)}
      </div>

      {running && (
        <div className="text-xs text-gray-400">{running} 계산 중… {progress.done} / {progress.total}</div>
      )}
      {counts.PASS + counts.FAIL + counts.INSUFFICIENT_EVIDENCE > 0 && (
        <div className="text-xs text-gray-300" data-testid="cr-a-counts">
          A 판정: 합격 {counts.PASS} · 불합격 {counts.FAIL} · 근거 부족 {counts.INSUFFICIENT_EVIDENCE}
        </div>
      )}

      <div className="overflow-x-auto max-h-[480px]">
        <table className="w-full text-xs">
          <thead className="text-gray-400 text-left sticky top-0 bg-gray-800">
            <tr>
              <th className="px-2 py-1">레벨(배치)</th>
              <th className="px-2 py-1">목표</th>
              <th className="px-2 py-1">예상 실유저 클리어율 (A) · 범위 · 신뢰도</th>
              <th className="px-2 py-1" title={TARGET_PROXIMITY_TOOLTIP}>{TARGET_PROXIMITY_LABEL}</th>
              <th className="px-2 py-1">A 판정 · 사유</th>
              <th className="px-2 py-1">봇 가상 클리어율 (B)</th>
              <th className="px-2 py-1">모델 · 봇 · 측정</th>
            </tr>
          </thead>
          <tbody>
            {levels.map(lv => {
              const n = lv.meta.level_number;
              const r = rows[n] ?? {};
              const vv = r.a ? verdictView(r.a) : null;
              const pv = r.a ? provenanceView(r.a) : null;
              return (
                <tr key={n} className="border-t border-gray-700 align-top" data-testid={`cr-row-${n}`}>
                  <td className="px-2 py-1 whitespace-nowrap">L{n}</td>
                  <td className="px-2 py-1 whitespace-nowrap">
                    <div>{r.a ? `A ${Math.round(r.a.target * 100)}%` : 'A —'}</div>
                    {lv.meta.target_clear_rate != null && (
                      <div className="text-[10px] text-gray-500" title={LEGACY_TARGET_TOOLTIP}>
                        기존 목표(봇 척도) {Math.round(lv.meta.target_clear_rate * 100)}%
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-1">
                    {r.aError ? <span className="text-red-300">오류: {r.aError}</span>
                      : r.a ? <ClearRateCell {...toClearRateMeta(r.a.prediction)} />
                      : <span className="text-gray-500">미계산</span>}
                  </td>
                  <td className="px-2 py-1 whitespace-nowrap" title={TARGET_PROXIMITY_TOOLTIP}>
                    {vv ? <span className="text-gray-300">{vv.proximity}</span> : '—'}
                  </td>
                  <td className="px-2 py-1">
                    {vv && (
                      <div className="flex flex-wrap items-center gap-1" title={vv.rawReason}>
                        <span className={`px-1 rounded border text-[10px] leading-4 ${vv.cls}`}>{vv.label}</span>
                        {vv.reasons.map(t => <span key={t} className="text-[10px] text-gray-400">{t}</span>)}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-1">
                    {r.bError ? <span className="text-red-300">오류: {r.bError}</span>
                      : r.b ? <BotVirtualCell {...r.b} />
                      : <span className="flex items-center gap-1 text-gray-500">미계산 <UnverifiedBadge /></span>}
                  </td>
                  <td className="px-2 py-1 text-[10px] text-gray-400">
                    {pv && (
                      <div>
                        <div>모델 {pv.model}</div>
                        <div>봇 {pv.bot} · {pv.protocol}</div>
                        <div>측정 {pv.source} · 시드 {pv.seedBand} · 확인 측정(C) {pv.confirmed ? '있음' : '없음'}</div>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default ClearRateVerifySection;

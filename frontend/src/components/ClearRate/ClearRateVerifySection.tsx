/**
 * 검증 탭(BatchVerifyPanel) 하단 — 실유저 예상 클리어율(A)·봇 가상 클리어율(B) 참고 판정 (문서 38).
 * 흐름: A 레벨별 목표 곡선 입력 → 미리보기 → 적용(저장) → [A 탐색 계산(캐시)] 또는 [C 확인 측정 준비 → 확인 → 실행]
 *       → 작업 완료 후 [C 판정] → 판정 기록 저장 → 새로고침 시 목표·작업·결과 복원.
 * - 기존 배치 검증·verification_passed·업로드·게임 표시값·생산 저장소와 무관(별도 저장소 clearRateVerifyStore).
 * - 측정은 사용자가 확인 화면에서 [실행]을 누를 때만. 탭 진입·복원·목표 수정은 상태 조회·재평가 표시만 한다.
 * - 실행 상태(미측정/대기/측정 중/완료/실패/취소/결과 오래됨)와 판정(합격/불합격/근거 부족)은 다른 칸.
 * - A 결과가 근거 부족이어도 B 로 자동 전환하지 않는다. B 는 별도 칸·별도 목표, 회색 "실측 미검증" 배지 고정.
 * - C 측정은 봇 측정 재현성 확인이며 실유저 클리어율 독립 검증이 아니다.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getProductionLevelsByBatch } from '../../storage/productionStorage';
import type { ProductionLevel } from '../../types/production';
import { toClearRateMeta } from '../../api/clearRate';
import { evaluateClearRateTarget } from '../../api/clearRateTarget';
import {
  cancelConfirm, checkTargets, evaluateConfirm, getVerifyInfo, planConfirm, queryConfirmJobs, submitConfirm,
  type TargetCheckItem, type VerifyInfo, type VerifyPlanResponse,
} from '../../api/clearRateVerify';
import { ClearRateCell } from './ClearRateCell';
import { BotVirtualCell, UnverifiedBadge } from './BotVirtualCell';
import {
  LEGACY_TARGET_TOOLTIP, SECTION_NOTE, TARGET_PROXIMITY_LABEL, TARGET_PROXIMITY_TOOLTIP,
  formatProximity, parseTargetPercent, reasonLabel,
} from './clearRateLabels';
import {
  curveHash, curveToDraft, draftToCurve, emptySegmentDraft, previewCurve, resolveTarget, validateCurve,
  type OverrideDraft, type ResolvedTarget, type SegmentDraft, type TargetCurve,
} from './targetCurve';
import {
  C_NOTE, KIND_LABEL, RUN_STATE_LABEL, VALIDITY_LABEL, assessRecord, confirmLockKey, displayVerdict, isActiveJob,
  isCompletedC, jobRefKey, mapHash, planSummary, recordFromBotVirtual, recordFromUserExpected, recordKey, runState,
  type ConfirmJobRef, type EvaluationRecord, type RunState,
} from './clearRateVerifyModel';
import {
  loadBatchVerifyState, putJobRef, putRecord, saveBTarget, saveCurve,
} from './clearRateVerifyStore';

type Busy = null | 'A' | 'B' | 'preview' | 'plan' | 'submit' | 'judge';
const POLL_MS = 3000;
const SOURCE_LABEL: Record<string, string> = { override: '개별', cycle: '주기', segment: '구간' };
const RUN_CLASS: Record<RunState, string> = {
  not_measured: 'text-gray-500', queued: 'text-amber-300', running: 'text-sky-300', done: 'text-gray-200',
  failed: 'text-red-300', cancelled: 'text-gray-400', stale: 'text-amber-400',
};

const errText = (e: unknown): string => {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail && typeof detail === 'object' && 'detail' in (detail as Record<string, unknown>)) {
    const d = detail as { code?: string; detail?: string };
    return `${d.code ?? ''} ${d.detail ?? ''}`.trim();
  }
  return detail != null ? JSON.stringify(detail) : e instanceof Error ? e.message : String(e);
};
const pct = (t: number | null | undefined) => (t == null ? '—' : `${Math.round(t * 1000) / 10}%`);
const nowIso = () => new Date().toISOString();

export function ClearRateVerifySection({ batchId }: { batchId: string }) {
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [curve, setCurve] = useState<TargetCurve | null>(null);
  const [segDraft, setSegDraft] = useState<SegmentDraft[]>([emptySegmentDraft()]);
  const [ovDraft, setOvDraft] = useState<OverrideDraft[]>([]);
  const [preview, setPreview] = useState<{ curve: TargetCurve; rows: ResolvedTarget[]; errors: string[]; unset: number[];
    checks: Record<number, TargetCheckItem>; checkError?: string } | null>(null);
  const [bInput, setBInput] = useState('');
  const [records, setRecords] = useState<Record<string, EvaluationRecord>>({});
  const [unsaved, setUnsaved] = useState<Set<string>>(new Set());
  const [jobs, setJobs] = useState<Record<number, ConfirmJobRef>>({});
  const [rowError, setRowError] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [plan, setPlan] = useState<VerifyPlanResponse | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [info, setInfo] = useState<VerifyInfo | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const locks = useRef(new Set<string>());

  const persistJob = useCallback(async (ref: ConfirmJobRef) => {
    setJobs(prev => ({ ...prev, [ref.level_number]: ref }));
    try { await putJobRef(ref); } catch (e) { setSaveError(`작업 참조 저장 실패: ${errText(e)}`); }
  }, []);

  const refreshJobs = useCallback(async (refs: ConfirmJobRef[]) => {
    const got = await queryConfirmJobs(refs.map(r => r.job.job_id));
    for (const r of refs) {
      const j = got[r.job.job_id];
      if (j && (j.status !== r.job.status || j.games_done !== r.job.games_done || j.cancel_requested !== r.job.cancel_requested)) {
        await persistJob({ ...r, job: j });
      }
    }
  }, [persistJob]);

  // 진행 중 작업만 상태 조회(폴링). 측정을 새로 요청하지 않는다.
  const activeRefs = useMemo(() => Object.values(jobs).filter(r => isActiveJob(r.job)), [jobs]);
  useEffect(() => {
    if (activeRefs.length === 0) return;
    const t = setInterval(() => { refreshJobs(activeRefs).catch(() => undefined); }, POLL_MS);
    return () => clearInterval(t);
  }, [activeRefs, refreshJobs]);

  // ── 복원 (측정 요청 없음: 레벨·저장 상태 읽기 + 작업 상태 조회 + 현재 모델/기준 버전 조회) ─────────────────
  useEffect(() => {
    let alive = true;
    setRecords({}); setJobs({}); setPlan(null); setPreview(null); setSelected(new Set()); setRowError({});
    getProductionLevelsByBatch(batchId)
      .then(ls => { if (alive) setLevels([...ls].sort((x, y) => x.meta.level_number - y.meta.level_number)); })
      .catch(err => console.error('[ClearRateVerify] load levels failed:', err));
    loadBatchVerifyState(batchId).then(st => {
      if (!alive) return;
      setCurve(st.curve);
      const d = curveToDraft(st.curve);
      setSegDraft(d.segments); setOvDraft(d.overrides);
      setBInput(st.bTarget != null ? String(Math.round(st.bTarget * 1000) / 10) : '');
      setRecords(Object.fromEntries(st.records.map(r => [r.key, r])));
      setJobs(Object.fromEntries(st.jobs.map(j => [j.level_number, j])));
      if (st.skipped) setMessage(`이전 저장 항목 ${st.skipped}개는 형식이 맞지 않아 무시함`);
      if (st.jobs.length) refreshJobs(st.jobs).catch(() => undefined);
    }).catch(err => setSaveError(`저장소 읽기 실패: ${errText(err)}`));
    getVerifyInfo().then(i => { if (alive) setInfo(i); }).catch(() => undefined);
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId]);

  const hashes = useMemo(() => Object.fromEntries(levels.map(l => [l.meta.level_number, mapHash(l.level_json)])), [levels]);
  const cHash = useMemo(() => curveHash(curve), [curve]);
  const bTarget = parseTargetPercent(bInput);

  const saveRec = async (rec: EvaluationRecord) => {
    setRecords(prev => ({ ...prev, [rec.key]: rec }));
    try {
      await putRecord(rec);
      setUnsaved(prev => { const n = new Set(prev); n.delete(rec.key); return n; });
    } catch (e) {
      setUnsaved(prev => new Set(prev).add(rec.key));
      setSaveError(`판정 기록 저장 실패(화면에만 있음): ${errText(e)}`);
    }
  };

  // ── 목표 곡선: 미리보기 → 적용 ───────────────────────────────────────────────────────────────────────────
  const doPreview = async () => {
    const { curve: c, errors } = draftToCurve(segDraft, ovDraft, (curve?.version ?? 0) + 1);
    const ns = levels.map(l => l.meta.level_number);
    const v = validateCurve(c, ns);
    const rows = previewCurve(c, ns);
    const all = [...errors, ...v.errors.map(e => e.message)];
    setPreview({ curve: c, rows, errors: all, unset: v.unset, checks: {} });
    if (all.length) return;
    setBusy('preview');
    try {
      const items = rows.filter(r => r.target != null).map(r => ({ placement_level: r.level, target: r.target as number }));
      const res = items.length ? await checkTargets(items) : { items: [] as TargetCheckItem[] };
      setPreview(p => p && ({ ...p, checks: Object.fromEntries(res.items.map(i => [i.placement_level, i])) }));
    } catch (e) {
      setPreview(p => p && ({ ...p, checkError: errText(e) }));
    } finally { setBusy(null); }
  };

  const applyCurve = async () => {
    if (!preview || preview.errors.length) return;
    try {
      await saveCurve(batchId, preview.curve);
      setCurve(preview.curve);
      setPreview(null);
      setMessage(`A 목표 곡선 v${preview.curve.version} 적용 — 기존 판정은 "재평가 필요"로 표시(측정 자동 실행 없음)`);
    } catch (e) { setSaveError(`목표 곡선 저장 실패(적용 안 됨): ${errText(e)}`); }
  };

  const applyB = async () => {
    try { await saveBTarget(batchId, bTarget); setMessage('B 봇 목표 저장'); }
    catch (e) { setSaveError(`B 목표 저장 실패: ${errText(e)}`); }
  };

  // ── A 탐색(캐시) / B 계산 — 봇 실행 없음 ─────────────────────────────────────────────────────────────────
  const runExploration = async (mode: 'A' | 'B') => {
    if (busy) return;
    const targets = levels.map(l => ({ lv: l, t: mode === 'A' ? resolveTarget(curve, l.meta.level_number) : null }))
      .filter(x => (mode === 'A' ? x.t?.target != null : bTarget != null));
    if (targets.length === 0) return;
    setBusy(mode); setProgress({ done: 0, total: targets.length });
    for (let i = 0; i < targets.length; i++) {
      const { lv, t } = targets[i];
      const n = lv.meta.level_number;
      try {
        if (mode === 'A') {
          const res = await evaluateClearRateTarget({ target_mode: 'user_expected', target: t!.target as number,
            level_json: lv.level_json, placement_level: n, use_cached_measurement: true });
          await saveRec(recordFromUserExpected({ batchId, level: n, levelJson: lv.level_json, kind: 'exploration',
            result: res.user_expected!, target: { target: t!.target, source: t!.source, curveHash: cHash, curveVersion: curve?.version ?? null },
            judgeVersion: info?.judge_version ?? null, now: nowIso() }));
        } else {
          const res = await evaluateClearRateTarget({ target_mode: 'bot_virtual', target: bTarget as number,
            level_json: lv.level_json, placement_level: n });
          await saveRec(recordFromBotVirtual({ batchId, level: n, levelJson: lv.level_json, result: res.bot_virtual!, now: nowIso() }));
        }
        setRowError(prev => { const x = { ...prev }; delete x[n]; return x; });
      } catch (e) { setRowError(prev => ({ ...prev, [n]: `${mode}: ${errText(e)}` })); }
      setProgress({ done: i + 1, total: targets.length });
    }
    setBusy(null);
  };

  // ── C 확인 측정: 준비(plan, 봇 실행 없음) → 확인 → 실행 ───────────────────────────────────────────────────
  const prepareC = async () => {
    if (busy || selected.size === 0) return;
    setBusy('plan');
    try {
      const items = levels.filter(l => selected.has(l.meta.level_number)).map(l => ({
        level_json: l.level_json, placement_level: l.meta.level_number,
        map_id: `${batchId}:${l.meta.level_number}`, batch_id: batchId }));
      setPlan(await planConfirm(items));
    } catch (e) { setMessage(`C 준비 실패: ${errText(e)}`); } finally { setBusy(null); }
  };

  const executeC = async () => {
    if (!plan || busy) return;
    setBusy('submit');
    const byLevel = Object.fromEntries(levels.map(l => [l.meta.level_number, l]));
    for (const it of plan.items) {
      const lv = byLevel[it.placement_level];
      if (!lv || !it.cond_hash || it.error || it.blocking?.length || it.protocol_problems?.length) continue;
      const lock = confirmLockKey(batchId, it.placement_level, it.cond_hash);
      if (locks.current.has(lock)) continue;
      locks.current.add(lock);
      try {
        const r = await submitConfirm({ level_json: lv.level_json, placement_level: it.placement_level,
          map_id: it.map_id, batch_id: batchId, expected_cond_hash: it.cond_hash });
        await persistJob({ schema: 1, key: jobRefKey(batchId, it.placement_level), batch_id: batchId,
          level_number: it.placement_level, map_hash: hashes[it.placement_level], job: r.job });
      } catch (e) {
        setRowError(prev => ({ ...prev, [it.placement_level]: `C 요청: ${errText(e)}` }));
      } finally { locks.current.delete(lock); }
    }
    setPlan(null); setBusy(null);
  };

  const cancelC = async (ref: ConfirmJobRef) => {
    try { await persistJob({ ...ref, job: await cancelConfirm(ref.job.job_id) }); }
    catch (e) { setRowError(prev => ({ ...prev, [ref.level_number]: `취소: ${errText(e)}` })); }
  };

  /** 완료 C 측정으로 현재 목표 판정(봇 실행 없음). 맵이 바뀐 작업·목표 미설정 레벨은 건너뛴다 */
  const judgeC = async () => {
    if (busy) return;
    const todo = levels.filter(l => {
      const n = l.meta.level_number, ref = jobs[n];
      return ref && isCompletedC(ref.job) && runState(ref, hashes[n], n) === 'done' && resolveTarget(curve, n).target != null;
    });
    if (todo.length === 0) return;
    setBusy('judge'); setProgress({ done: 0, total: todo.length });
    for (let i = 0; i < todo.length; i++) {
      const lv = todo[i], n = lv.meta.level_number, ref = jobs[n], t = resolveTarget(curve, n);
      try {
        const res = await evaluateConfirm({ job_id: ref.job.job_id, target: t.target as number, level_json: lv.level_json, placement_level: n });
        await saveRec(recordFromUserExpected({ batchId, level: n, levelJson: lv.level_json, kind: 'confirm',
          result: res.user_expected, target: { target: t.target, source: t.source, curveHash: cHash, curveVersion: curve?.version ?? null },
          judgeVersion: res.provenance.judge_version, job: ref.job, provenance: res.provenance, now: nowIso() }));
        setRowError(prev => { const x = { ...prev }; delete x[n]; return x; });
      } catch (e) { setRowError(prev => ({ ...prev, [n]: `C 판정: ${errText(e)}` })); }
      setProgress({ done: i + 1, total: todo.length });
    }
    setBusy(null);
  };

  // ── 표시 ──────────────────────────────────────────────────────────────────────────────────────────────
  const ctxFor = (n: number) => ({
    mapHash: hashes[n], level: n, target: resolveTarget(curve, n).target, curveHash: cHash,
    modelVersion: info?.model_version ?? null, judgeVersion: info?.judge_version ?? null,
    botVersion: info?.bot_version ?? null, botProtocol: info?.bot_protocol ?? null,
  });
  const counts = levels.reduce((c, l) => {
    const n = l.meta.level_number;
    const rec = records[recordKey(batchId, n, 'A', 'confirm')];
    if (rec && rec.verdict && assessRecord(rec, ctxFor(n)).validity === 'current') c[rec.verdict] = (c[rec.verdict] ?? 0) + 1;
    return c;
  }, {} as Record<string, number>);
  const summary = plan ? planSummary(plan.items) : null;
  const doneCount = levels.filter(l => { const r = jobs[l.meta.level_number]; return r && isCompletedC(r.job); }).length;
  const toggle = (n: number) => setSelected(prev => { const s = new Set(prev); if (s.has(n)) s.delete(n); else s.add(n); return s; });
  const btn = 'px-3 py-1 rounded bg-slate-600 hover:bg-slate-500 disabled:opacity-40 text-white text-xs';
  const inp = 'px-1 py-0.5 text-xs border rounded bg-gray-700 border-gray-600';

  return (
    <div className="border-t border-gray-700 pt-4 space-y-3" data-testid="clear-rate-verify-section">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="font-medium text-sm">실유저 예상 클리어율 판정 (참고)</h4>
        <span className="text-[11px] text-gray-500">{SECTION_NOTE}</span>
      </div>
      <div className="text-[11px] text-amber-200/80" data-testid="cr-c-note">{C_NOTE}</div>
      {saveError && <div className="text-xs text-red-300" data-testid="cr-save-error">{saveError}</div>}
      {message && <div className="text-xs text-gray-300" data-testid="cr-message">{message}</div>}

      {/* A 목표 곡선 */}
      <div className="rounded border border-gray-700 p-2 space-y-2" data-testid="cr-curve-editor">
        <div className="flex items-baseline justify-between">
          <span className="text-xs text-gray-200">A 목표 실유저 클리어율 곡선 (첫 시도·도움 포함) — 우선순위: 개별 &gt; 주기 &gt; 구간, 경계 포함</span>
          <span className="text-[10px] text-gray-500" data-testid="cr-curve-applied">
            {curve ? `적용됨 v${curve.version} · ${cHash}` : '목표 미설정 (기본값 없음)'}
          </span>
        </div>
        <div className="text-[10px] text-gray-500">기존 목표(봇 척도, meta.target_clear_rate)는 A 목표로 변환하지 않음. 85% 미만도 입력값 그대로 유지(판정 가능 여부는 미리보기에 별도 표시).</div>
        {segDraft.map((d, i) => (
          <div key={`s${i}`} className="flex flex-wrap items-center gap-1 text-[11px] text-gray-300" data-testid={`cr-seg-${i}`}>
            <span>구간</span>
            <input className={`${inp} w-14`} placeholder="시작" value={d.from} onChange={e => setSegDraft(s => s.map((x, k) => k === i ? { ...x, from: e.target.value } : x))} />
            <span>~</span>
            <input className={`${inp} w-14`} placeholder="끝" value={d.to} onChange={e => setSegDraft(s => s.map((x, k) => k === i ? { ...x, to: e.target.value } : x))} />
            <input className={`${inp} w-12`} placeholder="목표%" value={d.target} onChange={e => setSegDraft(s => s.map((x, k) => k === i ? { ...x, target: e.target.value } : x))} />
            <span className="ml-2">주기</span>
            <input className={`${inp} w-10`} placeholder="10" value={d.period} onChange={e => setSegDraft(s => s.map((x, k) => k === i ? { ...x, period: e.target.value } : x))} />
            <span>위치</span>
            <input className={`${inp} w-14`} placeholder="10" value={d.positions} onChange={e => setSegDraft(s => s.map((x, k) => k === i ? { ...x, positions: e.target.value } : x))} />
            <input className={`${inp} w-12`} placeholder="목표%" value={d.cycleTarget} onChange={e => setSegDraft(s => s.map((x, k) => k === i ? { ...x, cycleTarget: e.target.value } : x))} />
            <button className="text-gray-500 hover:text-red-300" onClick={() => setSegDraft(s => s.filter((_, k) => k !== i))}>삭제</button>
          </div>
        ))}
        {ovDraft.map((d, i) => (
          <div key={`o${i}`} className="flex items-center gap-1 text-[11px] text-gray-300" data-testid={`cr-ov-${i}`}>
            <span>개별 레벨</span>
            <input className={`${inp} w-14`} value={d.level} onChange={e => setOvDraft(s => s.map((x, k) => k === i ? { ...x, level: e.target.value } : x))} />
            <input className={`${inp} w-12`} placeholder="목표%" value={d.target} onChange={e => setOvDraft(s => s.map((x, k) => k === i ? { ...x, target: e.target.value } : x))} />
            <button className="text-gray-500 hover:text-red-300" onClick={() => setOvDraft(s => s.filter((_, k) => k !== i))}>삭제</button>
          </div>
        ))}
        <div className="flex gap-2">
          <button className={btn} onClick={() => setSegDraft(s => [...s, emptySegmentDraft()])}>+ 구간</button>
          <button className={btn} onClick={() => setOvDraft(s => [...s, { level: '', target: '' }])}>+ 개별 레벨</button>
          <button className={btn} data-testid="cr-curve-preview" disabled={busy !== null} onClick={doPreview}>미리보기</button>
          <button className={btn} data-testid="cr-curve-apply" disabled={!preview || preview.errors.length > 0 || busy !== null} onClick={applyCurve}>적용</button>
        </div>
        {preview && (
          <div className="text-[11px] space-y-1" data-testid="cr-curve-preview-panel">
            {preview.errors.map(e => <div key={e} className="text-red-300">오류: {e}</div>)}
            {preview.errors.length === 0 && (
              <div className="text-gray-300">
                적용 시 목표 설정 {preview.rows.length - preview.unset.length}레벨 · 목표 미설정 {preview.unset.length}레벨
                {preview.checkError && <span className="text-red-300"> · 판정 가능 여부 조회 실패: {preview.checkError}</span>}
              </div>
            )}
            <div className="max-h-40 overflow-y-auto">
              <table className="text-[10px]">
                <thead className="text-gray-500"><tr><th className="px-1">레벨</th><th className="px-1">목표</th><th className="px-1">출처</th><th className="px-1">입력</th><th className="px-1">현 모델로 신뢰 판정</th></tr></thead>
                <tbody>
                  {preview.rows.map(r => {
                    const c = preview.checks[r.level];
                    return (
                      <tr key={r.level}>
                        <td className="px-1">L{r.level}</td>
                        <td className="px-1">{r.target == null ? '목표 미설정' : pct(r.target)}</td>
                        <td className="px-1">{r.source ? SOURCE_LABEL[r.source] : '—'}</td>
                        <td className="px-1">{r.target == null ? '—' : '입력 가능'}</td>
                        <td className="px-1">{r.target == null ? '—' : !c ? '미확인' : c.judgeable ? '가능' : `불가: ${c.codes.map(reasonLabel).join(', ')}`}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* B 봇 목표 (A 와 별도 데이터) */}
      <div className="flex items-center gap-2 text-xs text-gray-300">
        <span>B 봇 목표 성공률 (θ0.85·v2.4 규칙만·무도움 — A 와 비교 불가, 실측 미검증)</span>
        <input data-testid="cr-target-B" className={`${inp} w-16`} placeholder="예: 20" value={bInput} onChange={e => setBInput(e.target.value)} />
        <span>%</span>
        <button className={btn} onClick={applyB} disabled={bInput.trim() !== '' && bTarget == null}>B 목표 저장</button>
      </div>

      {/* 실행 */}
      <div className="flex flex-wrap items-center gap-2">
        <button className={btn} data-testid="cr-run-A" disabled={busy !== null || !curve || levels.length === 0} onClick={() => runExploration('A')}>A 탐색 계산(캐시 측정·C 아님)</button>
        <button className={btn} data-testid="cr-c-prepare" disabled={busy !== null || selected.size === 0} onClick={prepareC}>C 확인 측정 준비 ({selected.size}개 선택)</button>
        <button className={btn} data-testid="cr-c-judge" disabled={busy !== null || !curve || doneCount === 0} onClick={judgeC}>C 판정 (완료 {doneCount}개 · 측정 없음)</button>
        <button className={btn} data-testid="cr-run-B" disabled={busy !== null || bTarget == null || levels.length === 0} onClick={() => runExploration('B')}>B 봇 가상 계산</button>
        <button className="text-[11px] text-gray-400 hover:text-gray-200" onClick={() => setSelected(new Set(levels.filter(l => resolveTarget(curve, l.meta.level_number).target != null).map(l => l.meta.level_number)))}>목표 설정된 레벨 선택</button>
        <button className="text-[11px] text-gray-400 hover:text-gray-200" onClick={() => setSelected(new Set())}>선택 해제</button>
      </div>

      {plan && summary && (
        <div className="rounded border border-amber-700/60 bg-amber-950/30 p-2 text-xs space-y-1" data-testid="cr-c-confirm">
          <div className="text-amber-200">C 확인 측정 실행 전 확인 — {plan.note}</div>
          <div data-testid="cr-c-summary">
            대상 맵 {summary.maps}개 · 새로 측정 {summary.runnable}개 · 예상 {summary.games.toLocaleString()}판
            (맵당 {plan.items[0]?.games_planned ?? '—'}판, 시드 묶음 {plan.seed_band}) · 동시 실행 상한 {plan.max_concurrent}
          </div>
          <div className="text-gray-400">
            이미 완료(재사용·재측정 없음) {summary.reuseDone} · 진행 중 {summary.active} · 판정 불가로 제외 {summary.blocked} · 오류 {summary.errors}
          </div>
          {plan.items.filter(i => i.blocking?.length || i.error || i.protocol_problems?.length).map(i => (
            <div key={i.map_id} className="text-[10px] text-gray-400">
              L{i.placement_level}: {i.error ?? [...(i.protocol_problems ?? []), ...(i.blocking ?? []).map(reasonLabel)].join(', ')}
            </div>
          ))}
          <div className="flex gap-2">
            <button className={btn} data-testid="cr-c-execute" disabled={busy !== null || summary.runnable === 0} onClick={executeC}>실행</button>
            <button className={btn} onClick={() => setPlan(null)}>취소</button>
          </div>
        </div>
      )}

      {busy && busy !== 'preview' && busy !== 'plan' && busy !== 'submit' && (
        <div className="text-xs text-gray-400">{busy} 진행 중… {progress.done} / {progress.total}</div>
      )}
      {Object.keys(counts).length > 0 && (
        <div className="text-xs text-gray-300" data-testid="cr-a-counts">
          C 판정(현재 유효): 합격 {counts.PASS ?? 0} · 불합격 {counts.FAIL ?? 0} · 근거 부족 {counts.INSUFFICIENT_EVIDENCE ?? 0}
        </div>
      )}

      <div className="overflow-x-auto max-h-[520px]">
        <table className="w-full text-xs">
          <thead className="text-gray-400 text-left sticky top-0 bg-gray-800">
            <tr>
              <th className="px-1 py-1">선택</th>
              <th className="px-2 py-1">레벨(배치)</th>
              <th className="px-2 py-1">A 목표</th>
              <th className="px-2 py-1">C 실행 상태</th>
              <th className="px-2 py-1">예상 실유저 클리어율 (A) · 범위 · 신뢰도</th>
              <th className="px-2 py-1" title={TARGET_PROXIMITY_TOOLTIP}>{TARGET_PROXIMITY_LABEL}</th>
              <th className="px-2 py-1">A 판정 · 사유 · 유효성</th>
              <th className="px-2 py-1">봇 가상 클리어율 (B)</th>
              <th className="px-2 py-1">출처</th>
            </tr>
          </thead>
          <tbody>
            {levels.map(lv => {
              const n = lv.meta.level_number;
              const t = resolveTarget(curve, n);
              const ref = jobs[n];
              const rs = runState(ref, hashes[n], n);
              const rec = records[recordKey(batchId, n, 'A', 'confirm')] ?? records[recordKey(batchId, n, 'A', 'exploration')];
              const recB = records[recordKey(batchId, n, 'B', 'exploration')];
              const ctx = ctxFor(n);
              const asm = rec ? assessRecord(rec, ctx) : null;
              const dv = rec && asm ? displayVerdict(rec, asm.validity) : null;
              const bValid = recB ? assessRecord(recB, { ...ctx, target: bTarget, curveHash: null }) : null;
              return (
                <tr key={n} className="border-t border-gray-700 align-top" data-testid={`cr-row-${n}`}>
                  <td className="px-1 py-1"><input type="checkbox" checked={selected.has(n)} onChange={() => toggle(n)} /></td>
                  <td className="px-2 py-1 whitespace-nowrap">L{n}</td>
                  <td className="px-2 py-1 whitespace-nowrap">
                    <div>{t.target == null ? <span className="text-gray-500">목표 미설정</span> : `A ${pct(t.target)}`}
                      {t.source && <span className="ml-1 text-[10px] text-gray-500">({SOURCE_LABEL[t.source]})</span>}</div>
                    {lv.meta.target_clear_rate != null && (
                      <div className="text-[10px] text-gray-500" title={LEGACY_TARGET_TOOLTIP}>기존 목표(봇 척도) {Math.round(lv.meta.target_clear_rate * 100)}%</div>
                    )}
                  </td>
                  <td className="px-2 py-1 whitespace-nowrap" data-testid={`cr-run-state-${n}`}>
                    <span className={RUN_CLASS[rs]}>{RUN_STATE_LABEL[rs]}</span>
                    {ref && (rs === 'running' || rs === 'queued' || rs === 'failed' || rs === 'cancelled') && (
                      <span className="ml-1 text-[10px] text-gray-500">{ref.job.games_done}/{ref.job.games_planned}판{rs !== 'running' && rs !== 'queued' ? ' (완료 C 아님)' : ''}</span>
                    )}
                    {ref?.job.cancel_requested && isActiveJob(ref.job) && <span className="ml-1 text-[10px] text-gray-400">취소 요청됨</span>}
                    {ref && isActiveJob(ref.job) && !ref.job.cancel_requested && (
                      <button className="ml-1 text-[10px] text-gray-400 hover:text-red-300" onClick={() => cancelC(ref)}>취소</button>
                    )}
                    {ref?.job.error && <div className="text-[10px] text-red-300 max-w-[180px] truncate" title={ref.job.error}>{ref.job.error}</div>}
                  </td>
                  <td className="px-2 py-1">
                    {rec?.user_expected ? (
                      <div className={asm?.validity !== 'current' ? 'opacity-60' : ''}>
                        <ClearRateCell {...toClearRateMeta(rec.user_expected.prediction)} />
                      </div>
                    ) : <span className="text-gray-500">미계산</span>}
                  </td>
                  <td className="px-2 py-1 whitespace-nowrap" title={TARGET_PROXIMITY_TOOLTIP}>
                    {rec ? <span className="text-gray-300">{formatProximity(rec.proximity)}</span> : '—'}
                  </td>
                  <td className="px-2 py-1">
                    {rowError[n] && <div className="text-[10px] text-red-300">오류: {rowError[n]}</div>}
                    {rec && dv && asm && (
                      <div className="flex flex-wrap items-center gap-1" title={rec.raw_reason}>
                        <span className={`px-1 rounded border text-[10px] leading-4 ${dv.cls}`}>{dv.label}</span>
                        <span className="text-[10px] text-gray-500">[{KIND_LABEL[rec.measurement_kind]}]</span>
                        {rec.reason_codes.map(c => <span key={c} className="text-[10px] text-gray-400">{reasonLabel(c)}</span>)}
                        {asm.validity !== 'current' && (
                          <span className="text-[10px] text-amber-300" title={asm.reasons.join(' · ')}>{VALIDITY_LABEL[asm.validity]}</span>
                        )}
                        {unsaved.has(rec.key) && <span className="text-[10px] text-red-300">저장 안 됨</span>}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-1">
                    {recB?.bot_virtual ? (
                      <div className={bValid?.validity !== 'current' ? 'opacity-60' : ''}>
                        <BotVirtualCell {...recB.bot_virtual} />
                        {bValid && bValid.validity !== 'current' && <div className="text-[10px] text-amber-300">{VALIDITY_LABEL[bValid.validity]}</div>}
                      </div>
                    ) : <span className="flex items-center gap-1 text-gray-500">미계산 <UnverifiedBadge /></span>}
                  </td>
                  <td className="px-2 py-1 text-[10px] text-gray-400">
                    {rec && (
                      <div>
                        <div>모델 {rec.model_version ?? '—'} · 기준 {rec.judge_version ?? '—'}</div>
                        <div>봇 {rec.bot_version ?? '—'} · {rec.bot_protocol ?? '—'}</div>
                        <div>{KIND_LABEL[rec.measurement_kind]} · {rec.measurement_source} · 시드 {rec.seed_band ?? '—'}{rec.games_completed != null ? ` · ${rec.games_completed}판` : ''}</div>
                        <div>목표 {pct(rec.target)}{rec.target_curve_version != null ? ` (곡선 v${rec.target_curve_version})` : ''} · {rec.evaluated_at.slice(0, 16)}</div>
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

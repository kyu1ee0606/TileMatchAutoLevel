/**
 * 허들 구간 추천 패널 — 게임 레포 range_rec/run.sh 를 버튼으로 실행하고,
 * (1) 실시간 설정 hurdleActiveLevels 에 복붙할 묶음 형식 문자열, (2) 그래프, (3) 근거 표를 보여 준다.
 * 게임부스트 쓰기 없음 — 문자열은 사람이 복사해 실시간 설정에 붙인다.
 * API: frontend/src/api/hurdleRec.ts · 백엔드 app/core/hurdle_range_rec.py(결과 정규화는 그쪽 한 곳).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ComposedChart, Line, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ReferenceArea, ReferenceLine, Bar, BarChart, Cell, ErrorBar,
} from 'recharts';
import {
  hurdleRecApi, type BandRow, type JobView, type LevelRow, type PlanName, type RecResult, type RunListItem, type ToolInfo,
} from '../../api/hurdleRec';

const PLAN_KEY = 'hurdleRec.plan';
const PLAN_LABEL: Record<PlanName, string> = { conservative: '보수안', aggressive: '적극안' };
const PRESET_COLOR: Record<string, string> = { harder: '#ef4444', hard: '#f59e0b' };
const NONE_COLOR = '#60a5fa';
const EXCL_COLOR = '#6b7280';

const pct = (x: number | null | undefined, d = 1) => (x == null ? '-' : `${(x * 100).toFixed(d)}%`);
const pp = (x: number | null | undefined) => (x == null ? '-' : `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}%p`);

function compress(levels: number[]): string {
  const s = [...new Set(levels)].sort((a, b) => a - b);
  const out: [number, number][] = [];
  for (const L of s) {
    const last = out[out.length - 1];
    if (last && last[1] + 1 === L) last[1] = L; else out.push([L, L]);
  }
  return out.map(([a, b]) => (a === b ? `${a}` : `${a}-${b}`)).join(',');
}

async function copyText(t: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(t);
    return true;
  } catch {
    const ta = document.createElement('textarea');
    ta.value = t;
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  }
}

type Sel = { start: number; end: number; label: string } | null;

export function HurdleRangeRecPanel() {
  const [info, setInfo] = useState<ToolInfo | null>(null);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [runId, setRunId] = useState<string>('latest');
  const [res, setRes] = useState<RecResult | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const [err, setErr] = useState<string>('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [versions, setVersions] = useState('');
  const [memo, setMemo] = useState('');
  // 적용 안 선택 저장(기본 = 보수안: 운영 순서상 첫 적용안, DECISIONS 2026-11-06)
  const [plan, setPlan] = useState<PlanName>(() => {
    try { return (localStorage.getItem(PLAN_KEY) as PlanName) === 'aggressive' ? 'aggressive' : 'conservative'; } catch { return 'conservative'; }
  });
  const savePlan = (p: PlanName) => { setPlan(p); try { localStorage.setItem(PLAN_KEY, p); } catch { /* 저장 실패 무시 */ } };
  const [sel, setSel] = useState<Sel>(null);
  const [hl, setHl] = useState<number | null>(null);
  const [view, setView] = useState<[number, number]>([1, 1530]);
  const pollRef = useRef<number | null>(null);

  const loadRuns = useCallback(async () => {
    const r = await hurdleRecApi.runs();
    setRuns(r);
    return r;
  }, []);

  const loadResult = useCallback(async (id: string) => {
    try {
      setRes(await hurdleRecApi.result(id === 'latest' ? undefined : id));
      setErr('');
    } catch (e: any) {
      setRes(null);
      setErr(e?.response?.data?.detail || String(e));
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const i = await hurdleRecApi.info();
        setInfo(i);
        setVersions((i.defaultVersions || []).join(','));
        await loadRuns();
        setJob(i.running || (await hurdleRecApi.status()));
      } catch (e: any) {
        setErr(`백엔드 /api/hurdle-rec 응답 없음 — 맵툴 백엔드 재시작 필요할 수 있음 (${e?.message || e})`);
      }
    })();
  }, [loadRuns]);

  useEffect(() => { loadResult(runId); }, [runId, loadResult]);

  // 실행 중이면 2초 폴링, 끝나면 목록·최신 결과 갱신
  useEffect(() => {
    if (job?.status !== 'running') return;
    pollRef.current = window.setInterval(async () => {
      try {
        const s = await hurdleRecApi.status(job.id);
        setJob(s);
        if (s.status !== 'running') {
          const r = await loadRuns();
          const mine = r.find(x => x.id === `maptool:${s.id}`);
          setRunId(mine ? mine.id : 'latest');
          if (mine) loadResult(mine.id);
        }
      } catch { /* 다음 폴링 */ }
    }, 2000);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [job?.status, job?.id, loadRuns, loadResult]);

  const startRun = async () => {
    setErr('');
    try {
      const v = versions.split(',').map(x => x.trim()).filter(Boolean);
      setJob(await hurdleRecApi.run({ since: since || undefined, until: until || undefined, versions: v.length ? v : undefined, memo }));
    } catch (e: any) {
      setErr(e?.response?.data?.detail || String(e));
    }
  };

  const stopRun = async () => {
    if (job?.id) setJob(await hurdleRecApi.stop(job.id));
  };

  // 그래프 클릭 → 선택 구간(표 필터·그래프 확대)
  const selectRange = (start: number, end: number, label: string) => {
    setSel({ start, end, label });
    const pad = Math.max(20, Math.round((end - start + 1) * 0.6));
    setView([Math.max(1, start - pad), end + pad]);
  };

  return (
    <div className="space-y-4 p-2 text-sm text-gray-200">
      <MainBox info={info} job={job} res={res} plan={plan} setPlan={savePlan} onRun={startRun} onStop={stopRun} />

      {err && <div className="text-red-400 bg-red-900/20 border border-red-800 rounded p-2">{err}</div>}

      <details className="bg-gray-800/30 border border-gray-700 rounded">
        <summary className="cursor-pointer px-3 py-2 text-gray-300 select-none">자세히 — 실행 옵션 · 다른 안 · 기존 형식 · 변경 내역 · 그래프 · 근거 표</summary>
        <div className="space-y-4 p-3">
          <RunOptions job={job} since={since} until={until} versions={versions} memo={memo}
            setSince={setSince} setUntil={setUntil} setVersions={setVersions} setMemo={setMemo} />
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-gray-400">결과</label>
            <select className="bg-gray-800 border border-gray-600 rounded px-2 py-1" value={runId} onChange={e => setRunId(e.target.value)}>
              <option value="latest">최신</option>
              {[...runs].reverse().map(r => (
                <option key={r.id} value={r.id}>{r.runAt || '?'} · {r.source === 'maptool' ? '맵툴' : '게임레포'} · {r.id.split(':')[1]} · {r.schema}</option>
              ))}
            </select>
          </div>
          {res && (
            <>
              <DataLine res={res} />
              <CopyBoxes res={res} />
              <LevelChart res={res} plan={plan} view={view} setView={setView} sel={sel} hl={hl}
                onPick={(L) => { setHl(L); const lv = res.levels.find(x => x.level === L); const b = plan === 'conservative' ? lv?.bandCons : lv?.bandAggr;
                  if (b) selectRange(b[0], b[1], `구간 L${b[0]}-${b[1]}`); else selectRange(L, L, `L${L}`); }} />
              <BandChart bands={res.bands} sel={sel} onPick={(b) => selectRange(b.start, b.end, `구간 L${b.start}-${b.end}`)} />
              {res.hurdleLevels.length > 0 && <HurdleCompare res={res} />}
              <ReasonTable res={res} plan={plan} sel={sel} clearSel={() => { setSel(null); setView([1, 1530]); }}
                hl={hl} onRow={(L) => { setHl(L); setView([Math.max(1, L - 40), L + 40]); }} />
              {res.notes && res.notes.length > 0 && (
                <ul className="text-xs text-gray-500 list-disc pl-5">{res.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
              )}
            </>
          )}
        </div>
      </details>
    </div>
  );
}

// ── 맨 위: 계산 버튼 + 붙여 넣을 문자열 1개 + 자동 검증 ─────────────────────────
function MainBox({ info, job, res, plan, setPlan, onRun, onStop }: {
  info: ToolInfo | null; job: JobView | null; res: RecResult | null; plan: PlanName; setPlan: (p: PlanName) => void;
  onRun: () => void; onStop: () => void;
}) {
  const running = job?.status === 'running';
  const [copied, setCopied] = useState(false);
  const s = res?.strings[plan];
  const chk = s?.check;
  const ok = !!chk?.pass;
  const text = s?.grouped || '';
  return (
    <div className={`rounded-lg border-2 p-4 space-y-3 ${!res ? 'border-gray-700 bg-gray-800/60' : ok ? 'border-emerald-600 bg-emerald-950/20' : 'border-red-600 bg-red-950/30'}`}>
      <div className="flex flex-wrap items-center gap-3">
        <button disabled={running || !info?.exists} onClick={onRun} data-testid="hurdle-calc"
          className="px-5 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-base font-semibold">
          {running ? '계산 중…' : '허들 레벨 계산'}
        </button>
        {running && <button onClick={onStop} className="px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-xs">중지</button>}
        {job && job.status !== 'idle' && (
          <span className={`text-xs ${job.status === 'done' ? 'text-green-400' : job.status === 'running' ? 'text-yellow-300' : 'text-red-400'}`} data-testid="hurdle-job">
            {({ running: '계산 중', done: '완료', failed: '실패', stopped: '중지됨' } as Record<string, string>)[job.status] || job.status}
            {' · '}{job.elapsedSec ?? 0}초{job.status === 'running' ? ` · ${job.pct ?? 0}% · ${job.phase || ''}` : ''}
            {job.exitCode != null && job.exitCode !== 0 ? ` · 종료 코드 ${job.exitCode}${job.exitCode === 2 ? '(식별자 검사 실패)' : ''}` : ''}
          </span>
        )}
        <span className="ml-auto flex items-center gap-1 text-xs text-gray-400">
          적용 안:
          {(['conservative', 'aggressive'] as PlanName[]).map(p => (
            <button key={p} onClick={() => setPlan(p)} data-testid={`plan-${p}`}
              className={`px-2 py-0.5 rounded ${plan === p ? 'bg-gray-200 text-gray-900' : 'bg-gray-700 text-gray-300'}`}>
              {PLAN_LABEL[p]}{p === 'conservative' ? '(기본)' : ''}
            </button>
          ))}
        </span>
      </div>
      {running && (
        <div className="h-2 bg-gray-700 rounded overflow-hidden">
          <div className="h-full bg-indigo-500 transition-all" style={{ width: `${job?.pct ?? 2}%` }} />
        </div>
      )}
      {res && s && (
        <>
          <div className="flex items-center justify-between">
            <div className="text-sm">
              실시간 설정 <code className="text-white">hurdleActiveLevels</code> 에 붙여 넣을 값 — <b className="text-white">{PLAN_LABEL[plan]}</b>
              <span className="text-xs text-gray-400"> · 데이터 끝 {res.dataSources.tmax} · 계산 {res.runAt}</span>
            </div>
            <span data-testid="hurdle-verdict" className={`px-2 py-0.5 rounded text-xs font-semibold ${ok ? 'bg-emerald-600 text-white' : 'bg-red-600 text-white'}`}>
              {ok ? '검증 통과 ✓' : '검증 실패 — 붙여 넣지 마세요'}
            </span>
          </div>
          <div className="flex gap-2 items-stretch">
            <textarea readOnly value={text} rows={5} onFocus={e => e.currentTarget.select()} data-testid="hurdle-string"
              className={`flex-1 font-mono text-sm bg-gray-950 border rounded p-2 text-gray-100 ${ok ? 'border-emerald-700' : 'border-red-600'}`} />
            <button className={`px-5 rounded text-white font-semibold ${ok ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-red-700 hover:bg-red-600'}`}
              onClick={async () => { if (await copyText(text)) { setCopied(true); setTimeout(() => setCopied(false), 1500); } }}>
              {copied ? '복사됨 ✓' : '복사'}
            </button>
          </div>
          <CheckList s={s} />
        </>
      )}
    </div>
  );
}

function CheckList({ s }: { s: RecResult['strings'][PlanName] }) {
  const c = s.check;
  if (!c) return <div className="text-xs text-red-400">검증 정보 없음(백엔드 구버전) — 붙여 넣기 전 확인 필요</div>;
  const mark = (v: boolean | null | undefined) => (v === true ? <span className="text-emerald-400">✓</span> : v === false ? <span className="text-red-400">✗</span> : <span className="text-gray-400">–</span>);
  return (
    <ul className="text-xs space-y-0.5 text-gray-300" data-testid="hurdle-checks">
      <li>{mark(c.parse.ok)} ① 게임 파서 규칙 해석: 오류 항목 {c.parse.nBad} · 토큰 {c.parse.tokens}/{c.parse.maxTokens} · 길이 {c.parse.length}/{c.parse.maxLength}자 · 형식 {c.parse.format === 'grouped' ? '묶음' : c.parse.format}
        <span className="text-gray-500"> ({c.parse.parser === 'csharp' ? 'C# 하네스' : '백엔드 함수'} — {c.parse.parserSrc})</span>
        {c.parse.nBad > 0 && <span className="text-red-400"> 오류: {c.parse.bad.join(' | ')}</span>}</li>
      <li>{mark(c.intent.ok)} ② 결과 의도와 일치(L{c.intent.range[0]}~{c.intent.range[1]}): 펼친 {c.intent.levels}레벨 vs 의도 {c.intent.intentLevels}레벨 · 불일치 {c.intent.nMismatch}
        {Object.keys(c.intent.byPreset).length > 0 && <span className="text-gray-500"> ({Object.entries(c.intent.byPreset).map(([k, v]) => `${k} ${v}`).join(' · ')})</span>}
        {c.intent.nMismatch > 0 && <span className="text-red-400"> 불일치 레벨 {c.intent.mismatch}</span>}</li>
      <li>{mark(c.data.ok)} ③ 빌드 데이터 level_hurdle.json 항목: 없는 레벨 {c.data.nMissing ?? '-'}
        {c.data.nMissing ? <span className="text-gray-400" title={c.data.missing}> (정보 — 보스·L1 등은 게임이 자동 제외: {c.data.missing})</span> : null}
        {c.data.unknownPresets && c.data.unknownPresets.length > 0 && <span className="text-red-400"> 데이터에 없는 강도 {c.data.unknownPresets.join(',')}</span>}
        {c.data.error && <span className="text-red-400"> {c.data.error}</span>}
        <span className="text-gray-500"> · 데이터 {c.data.created}{c.data.sameAsRun === false ? ' (계산 이후 빌드 데이터가 다시 만들어짐 — 현재 파일 기준 검사)' : ''}</span></li>
      <li>{mark(c.equivalent.ok)} ④ 도구 결과 equivalent = {String(c.equivalent.value)}{s.groupedMethod ? ` (${s.groupedMethod})` : ''}</li>
    </ul>
  );
}

// ── 실행 옵션(접힌 영역) ─────────────────────────────────────────────────────
function RunOptions(p: {
  job: JobView | null; since: string; until: string; versions: string; memo: string;
  setSince: (s: string) => void; setUntil: (s: string) => void; setVersions: (s: string) => void; setMemo: (s: string) => void;
}) {
  const [showLog, setShowLog] = useState(false);
  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded p-3 space-y-2">
      <div className="text-xs text-gray-400">계산 옵션(비우면 도구 기본값) — "허들 레벨 계산" 버튼에 적용</div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-xs text-gray-400">시작일(이상)
          <input type="date" value={p.since} onChange={e => p.setSince(e.target.value)} className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-200" />
        </label>
        <label className="flex flex-col text-xs text-gray-400">끝일(미만)
          <input type="date" value={p.until} onChange={e => p.setUntil(e.target.value)} className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-200" />
        </label>
        <label className="flex flex-col text-xs text-gray-400">버전(쉼표)
          <input value={p.versions} onChange={e => p.setVersions(e.target.value)} className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-200 w-56" />
        </label>
        <label className="flex flex-col text-xs text-gray-400">메모
          <input value={p.memo} onChange={e => p.setMemo(e.target.value)} className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-200 w-48" />
        </label>
        {p.job && p.job.status !== 'idle' && (
          <button className="text-xs text-gray-400 underline" onClick={() => setShowLog(!showLog)}>작업 {p.job.id} 로그 {showLog ? '접기' : '보기'}</button>
        )}
      </div>
      {showLog && <pre className="text-xs bg-gray-900 rounded p-2 max-h-40 overflow-auto text-gray-400">{(p.job?.logTail || []).join('\n') || '(로그 없음)'}</pre>}
    </div>
  );
}

function DataLine({ res }: { res: RecResult }) {
  const d = res.dataSources;
  return (
    <div className="text-xs text-gray-400 bg-gray-800/40 rounded px-3 py-2">
      실행 {res.runAt} · {res.source === 'maptool' ? '맵툴 실행' : '게임 레포 실행'} · 스키마 {res.schema}
      {' · '}데이터 {d.platform} {d.tmin} ~ <b className="text-gray-200">{d.tmax}</b> (끝 시각)
      {' · '}버전 {(d.versions || []).join(',')}
      {(d.since || d.until) && <> · 기간 지정 {d.since || '처음'} ~ {d.until || '끝'}</>}
      {' · '}판 {d.runs?.toLocaleString()}
      {d.byVersion && <> · {Object.entries(d.byVersion).map(([v, x]) => `${v} ${x?.[1]?.toLocaleString()}첫판`).join(' · ')}</>}
    </div>
  );
}

// ── 복사 박스 ──────────────────────────────────────────────────────────────
function CopyBoxes({ res }: { res: RecResult }) {
  const [legacy, setLegacy] = useState(false);
  const [copied, setCopied] = useState<string>('');
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-3 text-xs text-gray-400">
        <span>실시간 설정 <code className="text-gray-200">hurdleActiveLevels</code> 에 붙여 넣을 문자열 (앞 묶음·앞 항목 우선)</span>
        <label className="flex items-center gap-1"><input type="checkbox" checked={legacy} onChange={e => setLegacy(e.target.checked)} />기존 형식(a-b:강도) 보기</label>
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {(['conservative', 'aggressive'] as PlanName[]).map(p => {
          const s = res.strings[p];
          const text = legacy ? s.legacy : s.grouped;
          const df = res.diffFromPrev[p];
          return (
            <div key={p} className="bg-gray-800 border border-gray-700 rounded p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-white">{PLAN_LABEL[p]}</span>
                <button className="px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs"
                  onClick={async () => { if (await copyText(text)) { setCopied(p); setTimeout(() => setCopied(''), 1500); } }}>
                  {copied === p ? '복사됨 ✓' : '복사'}
                </button>
              </div>
              <textarea readOnly value={text} rows={4} onFocus={e => e.currentTarget.select()}
                className="w-full font-mono text-xs bg-gray-900 border border-gray-600 rounded p-2 text-gray-100" />
              <div className="text-xs text-gray-400 flex flex-wrap gap-x-3">
                <span>{text.length}자</span>
                <span>항목 {legacy ? (s.legacyItems ?? s.items) : s.items}</span>
                <span>대상 {s.levels}레벨 ({Object.entries(s.byPreset).map(([k, v]) => `${k} ${v}`).join(' · ')})</span>
                <span>허들 데이터 있음 {s.withData ?? '-'}</span>
                {s.missing.length > 0 && <span className="text-yellow-400" title={compress(s.missing)}>데이터 없음 {s.missing.length}(게임이 자동 제외)</span>}
                {s.valid === false && <span className="text-red-400">형식 오류</span>}
                {!legacy && s.groupedSource === 'maptool' && <span className="text-yellow-500" title="도구 결과에 묶음 형식이 없어 맵툴이 기존 형식에서 변환(펼친 결과 동일 확인)">묶음=맵툴 변환</span>}
                {s.groupedLegacySame === false && <span className="text-red-400">묶음≠기존 형식 결과</span>}
                {s.equivalent === true && s.groupedLegacySame !== false && <span className="text-green-400" title={`도구 equivalent=true · 맵툴 재확인 ${s.groupedLegacySame ? '일치' : '-'}`}>동등성 확인됨(묶음≡기존{s.groupedMethod ? ` · ${s.groupedMethod}` : ''})</span>}
                {s.equivalent === false && <span className="text-red-400">도구: 묶음≠기존 형식 — 복붙 전 확인</span>}
              </div>
              <div className="text-xs border-t border-gray-700 pt-1">
                {df ? (df.same ? <span className="text-gray-400">직전 실행({res.diffFromPrev.prevRunId}) 대비 동일</span> : (
                  <span className="space-x-2">
                    <span className="text-gray-400">직전 실행 대비:</span>
                    {df.nAdd > 0 && <span className="text-green-400" title={df.added}>+추가 {df.nAdd} ({df.added})</span>}
                    {df.nRem > 0 && <span className="text-red-400" title={df.removed}>−제거 {df.nRem} ({df.removed})</span>}
                    {df.nChg > 0 && <span className="text-yellow-400" title={df.changed}>강도 변경 {df.nChg} ({df.changed})</span>}
                  </span>
                )) : <span className="text-gray-500">직전 실행 없음</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── 그래프 ① 레벨별 ─────────────────────────────────────────────────────────
function pointColor(l: LevelRow, plan: PlanName) {
  const p = l.plan[plan];
  if (p) return PRESET_COLOR[p] || '#a855f7';
  if (l.excluded) return EXCL_COLOR;
  return NONE_COLOR;
}

function LevelChart({ res, plan, view, setView, sel, hl, onPick }: {
  res: RecResult; plan: PlanName; view: [number, number]; setView: (v: [number, number]) => void; sel: Sel; hl: number | null; onPick: (L: number) => void;
}) {
  const data = useMemo(() => res.levels
    .filter(l => l.level >= view[0] && l.level <= view[1])
    .map(l => ({
      level: l.level, actual: l.actual, expDesign: l.expDesign, expBot: l.expBot, expNeighbor: l.expNeighbor,
      err: l.actual != null && l.ciLo != null && l.ciHi != null ? [l.actual - l.ciLo, l.ciHi - l.actual] : [0, 0],
      color: pointColor(l, plan), row: l,
    })), [res, plan, view]);
  const ranges = res.strings[plan].ranges || [];
  const maxL = res.levels.length ? res.levels[res.levels.length - 1].level : 1530;
  const [a, b] = view;
  const span = b - a + 1;
  const showErr = span <= 300;
  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <h4 className="font-semibold text-white">① 레벨별 첫 시도 무도움 클리어율 vs 기대치 ({PLAN_LABEL[plan]} 색)</h4>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-gray-400">범위</span>
          <input type="number" value={a} min={1} max={maxL} onChange={e => setView([Math.max(1, +e.target.value || 1), b])} className="w-20 bg-gray-900 border border-gray-600 rounded px-1" />
          <span>~</span>
          <input type="number" value={b} min={1} max={maxL} onChange={e => setView([a, Math.min(maxL, +e.target.value || maxL)])} className="w-20 bg-gray-900 border border-gray-600 rounded px-1" />
          {[[1, maxL], [1, 300], [301, 700], [701, 1100], [1101, maxL]].map(([x, y]) => (
            <button key={`${x}`} onClick={() => setView([x, y])} className="px-2 py-0.5 bg-gray-700 rounded">{x}-{y}</button>
          ))}
        </div>
      </div>
      <div className="text-xs text-gray-400 mb-1 flex gap-3 flex-wrap">
        <span><b style={{ color: PRESET_COLOR.harder }}>●</b> harder 적용</span>
        <span><b style={{ color: PRESET_COLOR.hard }}>●</b> hard 적용</span>
        <span><b style={{ color: NONE_COLOR }}>●</b> 미적용</span>
        <span><b style={{ color: EXCL_COLOR }}>●</b> 판정 제외(보스·첫 등장·표본 부족 등)</span>
        <span>노란 배경 = {PLAN_LABEL[plan]} 구간(채움) · 점 클릭 → 근거 표 · 오차막대 = 95% 신뢰구간(300레벨 이하 범위에서 표시)</span>
      </div>
      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid stroke="#374151" strokeDasharray="3 3" />
          <XAxis dataKey="level" type="number" domain={[a, b]} allowDataOverflow tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <YAxis domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} allowDataOverflow tickFormatter={v => `${Math.round(v * 100)}%`} tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <Tooltip content={<LevelTip plan={plan} />} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {ranges.filter(([x, y]) => y >= a && x <= b).map(([x, y]) => (
            <ReferenceArea key={`${x}-${y}`} x1={Math.max(x, a)} x2={Math.min(y, b)} fill="#f59e0b" fillOpacity={0.08} stroke="#f59e0b" strokeOpacity={0.3} />
          ))}
          {sel && <ReferenceArea x1={Math.max(sel.start - 0.5, a)} x2={Math.min(sel.end + 0.5, b)} fill="#818cf8" fillOpacity={0.15} />}
          {hl != null && hl >= a && hl <= b && <ReferenceLine x={hl} stroke="#e879f9" strokeDasharray="4 2" />}
          <Line dataKey="expDesign" name="설계 기대" stroke="#22d3ee" dot={false} strokeWidth={1.2} connectNulls isAnimationActive={false} />
          <Line dataKey="expBot" name="봇 기대" stroke="#a3e635" dot={false} strokeWidth={1} strokeDasharray="4 3" connectNulls isAnimationActive={false} />
          <Line dataKey="expNeighbor" name="이웃 평균" stroke="#9ca3af" dot={false} strokeWidth={1} strokeDasharray="2 3" connectNulls isAnimationActive={false} />
          <Scatter dataKey="actual" name="실측" isAnimationActive={false}
            onClick={(d: any) => { const L = d?.payload?.level ?? d?.level; if (L) onPick(L); }}
            shape={(props: any) => {
              const { cx, cy, payload } = props;
              if (cx == null || cy == null || payload?.actual == null) return <g />;
              const r = span > 600 ? 2 : span > 200 ? 3 : 4;
              return <circle cx={cx} cy={cy} r={payload.level === hl ? r + 3 : r} fill={payload.color} stroke={payload.level === hl ? '#fff' : 'none'} style={{ cursor: 'pointer' }} />;
            }}>
            {showErr && <ErrorBar dataKey="err" width={2} stroke="#6b7280" strokeWidth={1} direction="y" />}
          </Scatter>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function LevelTip({ active, payload, plan }: any) {
  if (!active || !payload?.length) return null;
  const l: LevelRow | undefined = payload[0]?.payload?.row;
  if (!l) return null;
  return (
    <div className="bg-gray-900 border border-gray-600 rounded p-2 text-xs max-w-sm text-gray-200">
      <div className="font-semibold">L{l.level} · difficulty {l.difficulty ?? '-'} · 첫 시도 판 {l.ftRuns}</div>
      <div>실측 {pct(l.actual)} ({pct(l.ciLo)}~{pct(l.ciHi)}) · 설계 {pct(l.expDesign)} · 봇 {pct(l.expBot)} · 이웃 {pct(l.expNeighbor)}</div>
      <div>{PLAN_LABEL[plan as PlanName]}: <b>{l.plan[plan as PlanName] || '미적용'}</b>{l.excluded && <span className="text-gray-400"> · 제외: {l.excluded}</span>}</div>
      {l.reason && <div className="text-gray-400 mt-1">{l.reason}</div>}
    </div>
  );
}

// ── 그래프 ② 20레벨 구간 ───────────────────────────────────────────────────
function BandChart({ bands, sel, onPick }: { bands: BandRow[]; sel: Sel; onPick: (b: BandRow) => void }) {
  const data = bands.map(b => ({ ...b, name: `${b.start}`, actualV: b.actual, surroundV: b.surround }));
  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded p-3">
      <h4 className="font-semibold text-white mb-1">② 20레벨 구간: 실측 vs 주변 평균 (막대 클릭 → 해당 구간 근거)</h4>
      <div className="text-xs text-gray-400 mb-1 flex gap-3">
        <span><b className="text-red-400">■</b> 보수·적극 통과</span><span><b className="text-amber-400">■</b> 적극만 통과</span>
        <span><b className="text-blue-400">■</b> 미통과</span><span><b className="text-gray-400">■</b> 주변 평균</span>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }} barGap={0}
          onClick={(e: any) => { const i = e?.activeTooltipIndex ?? e?.activeIndex; const b = i != null ? data[Number(i)] : null; if (b) onPick(b); }}>
          <CartesianGrid stroke="#374151" strokeDasharray="3 3" />
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 10 }} interval={3} />
          <YAxis domain={[0.4, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} tick={{ fill: '#9ca3af', fontSize: 11 }} allowDataOverflow />
          <Tooltip content={({ active, payload }: any) => {
            if (!active || !payload?.length) return null;
            const b: BandRow = payload[0].payload;
            return (
              <div className="bg-gray-900 border border-gray-600 rounded p-2 text-xs max-w-sm text-gray-200">
                <div className="font-semibold">L{b.start}-{b.end} · 실측 {pct(b.actual)} · 주변 {pct(b.surround)} · {pp(b.gap)}</div>
                <div className="text-gray-400">{b.reason}</div>
              </div>
            );
          }} />
          <Bar dataKey="actualV" name="실측" isAnimationActive={false} style={{ cursor: 'pointer' }}>
            {data.map(b => (
              <Cell key={b.start} fill={b.passCons ? '#ef4444' : b.passAggr ? '#f59e0b' : '#3b82f6'}
                stroke={sel && b.start >= sel.start && b.end <= sel.end ? '#fff' : 'none'} strokeWidth={2} />
            ))}
          </Bar>
          <Bar dataKey="surroundV" name="주변 평균" fill="#6b7280" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── 그래프 ③ 허들 판 vs 일반 판 ────────────────────────────────────────────
function HurdleCompare({ res }: { res: RecResult }) {
  const data = res.hurdleLevels.map(h => ({ ...h, name: `${h.level}·${h.strength}` }));
  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded p-3">
      <h4 className="font-semibold text-white mb-1">③ 허들 판 vs 일반 판 (같은 레벨 첫 시도 클리어율) — 빨간 테두리 = 제거 후보</h4>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data}>
          <CartesianGrid stroke="#374151" strokeDasharray="3 3" />
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 10 }} />
          <YAxis domain={[0, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <Tooltip formatter={(v: any) => pct(v)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="ftc" name="허들 판" fill="#f59e0b" isAnimationActive={false}>
            {data.map(h => <Cell key={h.name} stroke={h.removeCandidate ? '#ef4444' : 'none'} strokeWidth={2} />)}
          </Bar>
          <Bar dataKey="baseFtc" name="일반 판" fill="#3b82f6" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── 근거 표 ────────────────────────────────────────────────────────────────
function ReasonTable({ res, plan, sel, clearSel, hl, onRow }: {
  res: RecResult; plan: PlanName; sel: Sel; clearSel: () => void; hl: number | null; onRow: (L: number) => void;
}) {
  const [mode, setMode] = useState<'applied' | 'all' | 'excluded' | 'bands'>('applied');
  const [preset, setPreset] = useState<string>('');
  const [q, setQ] = useState('');
  const [limit, setLimit] = useState(200);
  const rows = useMemo(() => {
    let r = res.levels;
    if (sel) r = r.filter(l => l.level >= sel.start && l.level <= sel.end);
    else if (mode === 'applied') r = r.filter(l => l.plan.conservative || l.plan.aggressive);
    else if (mode === 'excluded') r = r.filter(l => l.excluded);
    if (preset) r = r.filter(l => (preset === 'none' ? !l.plan[plan] : l.plan[plan] === preset));
    if (q.trim()) {
      const t = q.trim();
      const m = t.match(/^(\d+)(?:-(\d+))?$/);
      r = m ? r.filter(l => l.level >= +m[1] && l.level <= +(m[2] || m[1])) : r.filter(l => `${l.reason} ${l.excluded} ${l.judge}`.includes(t));
    }
    return r;
  }, [res, mode, preset, q, sel, plan]);
  const bandRows = useMemo(() => {
    let b = res.bands;
    if (sel) b = b.filter(x => x.end >= sel.start && x.start <= sel.end);
    if (q.trim()) b = b.filter(x => x.reason.includes(q.trim()) || `${x.start}-${x.end}`.includes(q.trim()));
    return b;
  }, [res, sel, q]);
  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-semibold text-white mr-2">근거 표</h4>
        {(['applied', 'all', 'excluded', 'bands'] as const).map(m => (
          <button key={m} onClick={() => setMode(m)} className={`px-2 py-0.5 rounded text-xs ${mode === m ? 'bg-indigo-600 text-white' : 'bg-gray-700'}`}>
            {{ applied: '적용 레벨(둘 중 하나)', all: '전체 레벨', excluded: '판정 제외 레벨', bands: '20레벨 구간' }[m]}
          </button>
        ))}
        {mode !== 'bands' && (
          <select value={preset} onChange={e => setPreset(e.target.value)} className="bg-gray-900 border border-gray-600 rounded px-1 text-xs">
            <option value="">{PLAN_LABEL[plan]} 강도: 전체</option>
            <option value="harder">harder</option><option value="hard">hard</option><option value="none">미적용</option>
          </select>
        )}
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="레벨(예 221-260) 또는 문구 검색"
          className="bg-gray-900 border border-gray-600 rounded px-2 py-0.5 text-xs w-56" />
        {sel && <span className="text-xs text-indigo-300">선택: {sel.label} <button className="underline" onClick={clearSel}>해제</button></span>}
        <span className="text-xs text-gray-500">{mode === 'bands' ? bandRows.length : rows.length}행</span>
      </div>
      <div className="max-h-[480px] overflow-auto">
        {mode === 'bands' ? (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-800 text-gray-400"><tr>
              <th className="text-left p-1">구간</th><th>실측</th><th>주변</th><th>차이</th><th>첫판</th><th>보수</th><th>적극</th><th className="text-left">근거</th>
            </tr></thead>
            <tbody>{bandRows.map(b => (
              <tr key={b.start} className={`border-t border-gray-700 ${b.pass ? 'bg-amber-900/20' : ''}`}>
                <td className="p-1">L{b.start}-{b.end}</td><td className="text-center">{pct(b.actual)}</td><td className="text-center">{pct(b.surround)}</td>
                <td className="text-center">{pp(b.gap)}</td><td className="text-center">{b.ftRuns.toLocaleString()}</td>
                <td className="text-center">{b.passCons ? '✓' : ''}</td><td className="text-center">{b.passAggr ? '✓' : ''}</td>
                <td className="text-gray-300">{b.reason}</td>
              </tr>))}</tbody>
          </table>
        ) : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-800 text-gray-400"><tr>
              <th className="text-left p-1">레벨</th><th>보수</th><th>적극</th><th>실측(95%)</th><th>설계</th><th>봇</th><th>첫판</th><th>판정</th><th className="text-left">근거</th><th className="text-left">제외 사유</th>
            </tr></thead>
            <tbody>{rows.slice(0, limit).map(l => (
              <tr key={l.level} onClick={() => onRow(l.level)}
                className={`border-t border-gray-700 cursor-pointer hover:bg-gray-700/40 ${hl === l.level ? 'bg-fuchsia-900/30' : ''}`}>
                <td className="p-1 font-mono">L{l.level}</td>
                <td className="text-center"><PresetTag p={l.plan.conservative} /></td>
                <td className="text-center"><PresetTag p={l.plan.aggressive} /></td>
                <td className="text-center">{pct(l.actual)} <span className="text-gray-500">({pct(l.ciLo, 0)}~{pct(l.ciHi, 0)})</span></td>
                <td className="text-center">{pct(l.expDesign)}</td><td className="text-center">{pct(l.expBot)}</td>
                <td className="text-center">{l.ftRuns}</td><td className="text-center">{l.judge}</td>
                <td className="text-gray-300">{l.reason}</td>
                <td className="text-gray-500">{l.excluded}</td>
              </tr>))}</tbody>
          </table>
        )}
        {mode !== 'bands' && rows.length > limit && (
          <button className="mt-1 text-xs underline text-gray-400" onClick={() => setLimit(limit + 300)}>더 보기 ({rows.length - limit}행 남음)</button>
        )}
      </div>
    </div>
  );
}

function PresetTag({ p }: { p?: string | null }) {
  if (!p) return <span className="text-gray-600">-</span>;
  return <span className="px-1 rounded text-white" style={{ background: PRESET_COLOR[p] || '#a855f7' }}>{p}</span>;
}

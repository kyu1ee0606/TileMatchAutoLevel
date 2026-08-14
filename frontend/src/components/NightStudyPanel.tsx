/**
 * [야간 연구 배치] 난이도 판정 체계의 미결 쟁점을 장시간 잡으로 확정한다.
 *
 * 배경: 난이도 판정을 RL 봇 시뮬에 의존해 왔는데 신뢰도가 불명이다. 실측으로
 *   - RL 전 구간 0.000 인 Lv710 을 A* 는 108노드로 해결(PROVEN_SOLVABLE)
 *   - 색 종류(V)가 난이도 분산의 89.9%, 기믹 강도는 3.0%
 *   - RL 스킬곡선이 64롤아웃에도 비단조
 * 가 나왔다. 이 잡은 봇에 의존하지 않는 A* 지표로 같은 레벨을 재서 RL 눈금을 검증한다.
 *
 * 잡은 **백엔드 스레드**에서 돌고 상태를 파일에 기록한다 → 브라우저를 닫아도 계속 진행되고,
 * 재접속하면 이어서 조회된다(14시간짜리를 탭에 매달아 둘 수 없으므로).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import apiClient from '../api/client';

interface Progress { done: number; total: number }
interface StudyState {
  status?: string;
  alive?: boolean;
  batch_id?: string;
  phase?: string;
  started_at?: string;
  finished_at?: string;
  elapsed_s?: number;
  progress?: Progress;
  error?: string;
  log?: string[];
  phases?: {
    verdict?: { summary?: Record<string, number>; measured?: number;
                rl0_but_solvable?: number; rl0_but_solvable_levels?: number[] };
    vsweep?: { rows?: Array<{ base: number; V: number; safe_move_ratio?: number | null;
                              min_safe_ratio?: number | null; points?: number; error?: string }> };
    corr?: { rows?: Array<Record<string, unknown>>; correlation?: { rho?: number | null; n?: number } };
    deep?: { rows?: Array<{ level: number; V?: number; safe_move_ratio?: number | null }> };
  };
}

const PHASE_LABEL: Record<string, string> = {
  load: '배치 로드',
  verdict: '1단계 · 전수 A* 판정',
  vsweep: '2단계 · V 스윕 실수내성',
  corr: '3단계 · RL↔실수내성 상관',
  deep: '4단계 · RL 0% 정밀',
  finished: '완료',
};

export function NightStudyPanel({ batchId }: { batchId?: string | null }) {
  const [open, setOpen] = useState(false);
  const [st, setSt] = useState<StudyState>({});
  const [hours, setHours] = useState(13);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const poll = useCallback(async () => {
    try {
      const r = await apiClient.get('/study/night');
      setSt(r.data as StudyState);
    } catch { /* 폴링 실패는 무시 — 다음 주기에 재시도 */ }
  }, []);

  useEffect(() => {
    if (!open) return;
    void poll();
    // 장시간 잡이라 5초 주기면 충분하다(진행률은 초 단위로 안 움직인다).
    timer.current = window.setInterval(() => { void poll(); }, 5000);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [open, poll]);

  const start = async () => {
    if (!batchId) { setMsg('배치를 먼저 선택하세요'); return; }
    if (!window.confirm(
      `야간 연구 배치를 시작합니다 (약 ${hours}시간).\n\n`
      + `1단계 전수 A* 판정 → "RL 0% 레벨이 진짜 클리어 불가인가"\n`
      + `2단계 V 스윕 실수내성 → "V 절벽이 봇과 무관하게 어디인가"\n`
      + `3단계 RL↔실수내성 상관 → "RL 눈금이 얼마나 맞나"\n`
      + `4단계 RL 0% 정밀\n\n`
      + `백엔드에서 돌기 때문에 브라우저를 닫아도 계속됩니다.\n`
      + `CPU를 계속 쓰므로 이 시간엔 레벨 생성/검증을 돌리지 마세요.`)) return;
    setBusy(true); setMsg(null);
    try {
      await apiClient.post('/study/night/start', { batch_id: batchId, hours });
      setMsg('시작됨');
      await poll();
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setMsg(d || '시작 실패');
    } finally { setBusy(false); }
  };

  const stop = async () => {
    if (!window.confirm('중지할까요? 지금까지의 결과는 보존됩니다.')) return;
    try { await apiClient.post('/study/night/stop'); setMsg('중지 요청됨'); await poll(); }
    catch { setMsg('중지 실패'); }
  };

  const p = st.progress || { done: 0, total: 0 };
  const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : 0;
  const running = st.status === 'running';
  const v = st.phases?.verdict;
  const vs = st.phases?.vsweep?.rows || [];
  const corr = st.phases?.corr;

  // V별 평균 실수내성 — 기준 레벨들을 묶어 절벽 위치를 본다
  const byV = new Map<number, number[]>();
  for (const r of vs) {
    if (typeof r.safe_move_ratio === 'number') {
      byV.set(r.V, [...(byV.get(r.V) || []), r.safe_move_ratio]);
    }
  }

  return (
    <div className="bg-gray-800/50 rounded p-2">
      <button onClick={() => setOpen(o => !o)} className="text-xs text-violet-300 font-medium">
        {open ? '▼' : '▶'} 🌙 야간 연구 배치 (난이도 판정 검증)
        {st.status && st.status !== 'idle' && (
          <span className={running ? 'text-emerald-400' : 'text-gray-400'}> — {st.status} · {PHASE_LABEL[st.phase || ''] || st.phase}</span>
        )}
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          <p className="text-[10px] text-gray-500 leading-relaxed">
            RL 봇 시뮬 대신 <span className="text-violet-300">A* 완전탐색</span>으로 같은 레벨을 재서
            난이도 눈금을 검증합니다. 백엔드에서 돌기 때문에 브라우저를 닫아도 계속됩니다.
            <span className="text-yellow-400"> 실행 중엔 레벨 생성/검증을 돌리지 마세요(CPU 경합).</span>
          </p>

          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] text-gray-400">시간 예산</span>
            <input type="number" min={1} max={24} step={0.5} value={hours}
              onChange={e => setHours(Number(e.target.value))}
              disabled={running}
              className="w-16 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-[11px] text-white" />
            <span className="text-[11px] text-gray-500">시간</span>
            {running ? (
              <button onClick={stop}
                className="px-2 py-1 rounded text-[11px] bg-red-700 hover:bg-red-600 text-white">
                ⏹ 중지
              </button>
            ) : (
              <button onClick={start} disabled={busy || !batchId}
                className="px-2 py-1 rounded text-[11px] bg-violet-700 hover:bg-violet-600 text-white disabled:opacity-50">
                🌙 시작
              </button>
            )}
            {msg && <span className="text-[11px] text-gray-400">{msg}</span>}
            {st.batch_id && <span className="text-[10px] text-gray-600 truncate">대상 {st.batch_id}</span>}
          </div>

          {st.status && st.status !== 'idle' && (
            <div>
              <div className="flex justify-between text-[10px] text-gray-400 mb-1">
                <span>{PHASE_LABEL[st.phase || ''] || st.phase}</span>
                <span>{p.done} / {p.total} ({pct}%)
                  {st.elapsed_s ? ` · ${Math.round(st.elapsed_s / 60)}분 경과` : ''}</span>
              </div>
              <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                <div className="h-full bg-violet-500 transition-all" style={{ width: `${pct}%` }} />
              </div>
            </div>
          )}

          {st.error && <div className="text-[11px] text-red-400">오류: {st.error}</div>}

          {/* 1단계 결과 — 이 잡의 핵심 질문 */}
          {v && (
            <div className="p-2 bg-gray-900/50 rounded">
              <div className="text-[11px] text-white mb-1">1단계 · 전수 A* 판정 ({v.measured}개)</div>
              <div className="text-[10px] text-gray-300 space-y-0.5">
                {Object.entries(v.summary || {}).map(([k, n]) => (
                  <div key={k}>{k}: <span className="text-white">{n}</span></div>
                ))}
                <div className="text-amber-300 pt-1">
                  RL 0% 인데 A* 는 풀 수 있다고 판정: <span className="font-bold">{v.rl0_but_solvable ?? 0}개</span>
                  {(v.rl0_but_solvable ?? 0) > 0 && ' → RL 과소평가 확정'}
                </div>
              </div>
            </div>
          )}

          {/* 2단계 결과 — V 절벽 */}
          {byV.size > 0 && (
            <div className="p-2 bg-gray-900/50 rounded">
              <div className="text-[11px] text-white mb-1">2단계 · V별 평균 실수내성 (1.0=아무 수나 둬도 클리어)</div>
              <div className="flex flex-wrap gap-1">
                {[...byV.entries()].sort((a, b) => a[0] - b[0]).map(([vv, arr]) => {
                  const avg = arr.reduce((s, x) => s + x, 0) / arr.length;
                  return (
                    <div key={vv} className="px-1.5 py-1 rounded bg-gray-800 text-[10px]">
                      <div className="text-gray-400">V={vv}</div>
                      <div className={avg >= 0.7 ? 'text-emerald-400' : avg >= 0.4 ? 'text-yellow-400' : 'text-red-400'}>
                        {avg.toFixed(2)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 3단계 결과 — 상관 */}
          {corr?.correlation && (
            <div className="p-2 bg-gray-900/50 rounded text-[10px] text-gray-300">
              <div className="text-[11px] text-white mb-1">3단계 · RL 예측 ↔ 실수내성 순위상관</div>
              <div>
                Spearman ρ = <span className="text-white font-bold">{corr.correlation.rho ?? '—'}</span>
                {' '}(표본 {corr.correlation.n})
              </div>
              <div className="text-gray-500 mt-0.5">
                ρ이 1에 가까우면 두 눈금이 같은 순서 → RL 상대순서 신뢰 가능.
                0에 가까우면 RL이 난이도를 제대로 못 잡는 것.
              </div>
            </div>
          )}

          {(st.log || []).length > 0 && (
            <details className="text-[10px] text-gray-500">
              <summary className="cursor-pointer">로그 ({(st.log || []).length})</summary>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap">{(st.log || []).slice(-40).join('\n')}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

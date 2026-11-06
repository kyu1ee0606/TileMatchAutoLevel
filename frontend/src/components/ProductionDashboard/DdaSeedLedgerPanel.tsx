/**
 * DDA 시드 이력 장부 패널 — 스냅샷 목록 · 두 스냅샷(또는 스냅샷 vs 현재 배치) 비교 · 레벨 타임라인 · 기준점 만들기.
 * 데이터: 백엔드 파일 backend/data/dda_seed_ledger/ (추가만). 업로드 탭의 실제 업로드가 자동으로 스냅샷을 남긴다.
 * 이 패널은 서버에 쓰지 않는다(기준점 '서버 읽기'만 서버 조회).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { getProductionLevelsByBatch } from '../../storage/productionStorage';
import {
  LEDGER_SEED_FIELDS, LEDGER_FIELD_STEP,
  listLedgerSnapshots, diffLedger, diffLedgerBatch, fetchLedgerDiffCsv, getLedgerTimeline,
  createLedgerBaselineFromFile, createLedgerBaselineFromServer,
  type LedgerSnapshotSummary, type LedgerDiffResponse, type LedgerDiffItem, type LedgerClass,
  type LedgerTimelineEntry, type LockModel,
} from '../../api/ddaSeedLedger';
import { RestorePreviewBox } from './RestorePreviewBox';

const BATCH_KEY = '__batch__';
const DEFAULT_RAW = '~/sp_meowsgarden/tools/out/dda_seed_random_20261028/readback_132545/levels.raw.json';
const SHOW_MAX = 300;

const CLASS_LABEL: Record<LedgerClass, string> = {
  same: '동일', reordered: '순서만', replaced: '토큰 교체', added: '토큰 추가', removed: '토큰 삭제',
  resized: '개수+교체', filled: '채움', cleared: '비움', unknown: '모름',
};
const CLASS_COLOR: Record<LedgerClass, string> = {
  same: 'text-gray-500', reordered: 'text-sky-300', replaced: 'text-orange-300', added: 'text-green-300',
  removed: 'text-red-300', resized: 'text-orange-400', filled: 'text-green-400', cleared: 'text-red-400',
  unknown: 'text-gray-400',
};
const KIND_LABEL: Record<string, string> = { upload: '업로드', baseline: '기준점', dryrun: '가상' };

function snapLabel(s: LedgerSnapshotSummary): string {
  const t = (s.createdAt || '').replace('T', ' ').slice(0, 16);
  return `${t} · ${KIND_LABEL[s.kind] || s.kind}${s.status === 'open' ? '(진행/미마감)' : ''}`
    + `${s.tag ? ` · ${s.tag}` : ''}${s.memo ? ` · ${s.memo.slice(0, 30)}` : ''} · ${s.counts?.total ?? 0}행`;
}

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

interface Props {
  batchId: string;
  batchName: string;
  infinityMode: 'off' | 'append' | 'only';
  infinityRelabel: boolean;
  infinitySourceStart: number;
  infinitySourceEnd: number;
  /** 값이 바뀌면 목록을 다시 읽는다(업로드 마감 후) */
  refreshKey?: number;
}

export function DdaSeedLedgerPanel(p: Props) {
  const [open, setOpen] = useState(false);
  const [snaps, setSnaps] = useState<LedgerSnapshotSummary[]>([]);
  const [lockModel, setLockModel] = useState<LockModel | null>(null);
  const [dir, setDir] = useState('');
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [q, setQ] = useState('');
  const [klass, setKlass] = useState('');
  const [persistVirtual, setPersistVirtual] = useState(false);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [res, setRes] = useState<LedgerDiffResponse | null>(null);
  const [tlId, setTlId] = useState('');
  const [tl, setTl] = useState<LedgerTimelineEntry[] | null>(null);
  const [rawPath, setRawPath] = useState(DEFAULT_RAW);
  const [baseTag, setBaseTag] = useState('v0');
  const [restoreSnap, setRestoreSnap] = useState<LedgerSnapshotSummary | null>(null);

  const reload = useCallback(async () => {
    try {
      const r = await listLedgerSnapshots(true);
      setSnaps(r.snapshots);
      setLockModel(r.lockModel);
      setDir(r.dir);
      const real = r.snapshots.filter(s => s.kind !== 'dryrun');
      setA(prev => prev || (real.length >= 2 ? real[real.length - 2].id : real[0]?.id || ''));
      setB(prev => prev || (real.length >= 2 ? real[real.length - 1].id : BATCH_KEY));
    } catch (e) {
      setErr(`목록 실패: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => { if (open) void reload(); }, [open, reload, p.refreshKey]);

  const loadBatchLevels = async () => {
    const levels = await getProductionLevelsByBatch(p.batchId);
    return levels.map(l => ({ level_number: l.meta.level_number, level_json: l.level_json }));
  };

  const runDiff = async () => {
    if (!a || !b) return;
    setBusy('비교 중…'); setErr('');
    try {
      if (b === BATCH_KEY || a === BATCH_KEY) {
        const base = a === BATCH_KEY ? b : a;
        const r = await diffLedgerBatch({
          base, batch_id: p.batchId, batch_name: p.batchName, levels: await loadBatchLevels(),
          infinity_mode: p.infinityMode, infinity_relabel: p.infinityRelabel,
          infinity_source_start: p.infinitySourceStart, infinity_source_end: p.infinitySourceEnd,
          persist: persistVirtual, q, klass, only_changed: true,
        }) as LedgerDiffResponse;
        setRes(r);
        if (r.saved) void reload();
      } else {
        setRes(await diffLedger(a, b, { q, klass, onlyChanged: true }));
      }
    } catch (e) {
      setErr(`비교 실패: ${(e as Error).message}`);
    } finally { setBusy(''); }
  };

  const exportCsv = async () => {
    if (!a || !b) return;
    setBusy('CSV…');
    try {
      let text: string;
      if (b === BATCH_KEY || a === BATCH_KEY) {
        text = await diffLedgerBatch({
          base: a === BATCH_KEY ? b : a, batch_id: p.batchId, batch_name: p.batchName, levels: await loadBatchLevels(),
          infinity_mode: p.infinityMode, infinity_relabel: p.infinityRelabel,
          infinity_source_start: p.infinitySourceStart, infinity_source_end: p.infinitySourceEnd, q, klass,
        }, 'csv') as string;
      } else {
        text = await fetchLedgerDiffCsv(a, b, q, klass);
      }
      download(`dda_seed_diff_${a}_vs_${b === BATCH_KEY ? 'batch' : b}.csv`, text, 'text/csv');
    } catch (e) {
      setErr(`CSV 실패: ${(e as Error).message}`);
    } finally { setBusy(''); }
  };

  const runTimeline = async (id?: string) => {
    const rid = (id ?? tlId).trim();
    if (!rid) return;
    const norm = /^\d+$/.test(rid) ? `level_${rid}` : /^i\d+$/i.test(rid) ? `infinity_${rid.slice(1)}` : rid;
    setTlId(norm);
    setBusy('타임라인…');
    try {
      setTl((await getLedgerTimeline(norm, true)).entries);
    } catch (e) {
      setErr(`타임라인 실패: ${(e as Error).message}`);
    } finally { setBusy(''); }
  };

  const makeBaselineFile = async () => {
    setBusy('기준점(파일)…'); setErr('');
    try { await createLedgerBaselineFromFile(rawPath, baseTag); await reload(); }
    catch (e) { setErr(`기준점 실패: ${(e as Error).message}`); }
    finally { setBusy(''); }
  };

  const makeBaselineServer = async () => {
    setBusy('기준점(서버 읽기)…'); setErr('');
    try { await createLedgerBaselineFromServer(baseTag, '기준점 — 서버 읽기'); await reload(); }
    catch (e) { setErr(`기준점 실패: ${(e as Error).message}`); }
    finally { setBusy(''); }
  };

  const reorderCount = useMemo(() => {
    if (!res) return 0;
    return LEDGER_SEED_FIELDS.reduce((n, f) => n + (res.summary.byField[f]?.reordered ?? 0), 0);
  }, [res]);

  const shown: LedgerDiffItem[] = res ? res.items.slice(0, SHOW_MAX) : [];

  return (
    <div className="mt-3 p-3 bg-gray-900 rounded-lg border border-teal-800/60 text-xs space-y-2">
      <button onClick={() => setOpen(o => !o)} className="flex items-center gap-2 w-full text-left">
        <span className="text-teal-300 font-semibold">{open ? '▾' : '▸'} DDA 시드 이력 (업로드별 스냅샷·비교)</span>
        <span className="text-gray-500">업로드할 때마다 레벨별 시드 4열 값·순서를 자동 기록 — 수정·삭제 없음</span>
      </button>
      {open && (
        <div className="space-y-3">
          {lockModel && (
            <div className={`p-2 rounded border ${lockModel.stores === 'index' ? 'border-red-700 bg-red-950/40 text-red-200' : 'border-sky-800 bg-sky-950/30 text-sky-200'}`}>
              <div className="font-semibold">게임 시드 잠금: {lockModel.stores === 'value' ? '값 저장' : '인덱스 저장 — 순서 변경 위험'}</div>
              <div>{lockModel.summary}</div>
              <details className="text-gray-400"><summary className="cursor-pointer">근거(코드)</summary>
                <ul className="list-disc ml-4">{lockModel.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
              </details>
            </div>
          )}

          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-gray-300 font-semibold">스냅샷 {snaps.length}개</span>
              <button onClick={() => void reload()} className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600">새로고침</button>
              <span className="text-gray-600 truncate">{dir}</span>
            </div>
            <div className="max-h-40 overflow-auto border border-gray-800 rounded">
              <table className="w-full">
                <tbody>
                  {[...snaps].reverse().map(s => (
                    <tr key={s.id} className="border-b border-gray-800">
                      <td className="px-1 font-mono text-gray-400">{s.id}</td>
                      <td className="px-1">{KIND_LABEL[s.kind] || s.kind}{s.auto ? '(자동)' : ''}</td>
                      <td className={`px-1 ${s.status === 'open' ? 'text-yellow-300' : 'text-gray-400'}`}>{s.status === 'open' ? '미마감' : '마감'}</td>
                      <td className="px-1 text-teal-200">{s.tag}</td>
                      <td className="px-1 text-gray-300">{s.memo}</td>
                      <td className="px-1 text-gray-400">{s.batchName}</td>
                      <td className="px-1 text-gray-400">{Object.entries(s.counts || {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</td>
                      <td className="px-1">
                        {s.kind === 'upload' ? (
                          <button onClick={() => setRestoreSnap(s)} title="이 업로드가 바꾼 열을 업로드 직전 서버 값으로 되돌리는 계획(미리보기는 쓰기 없음)"
                            className="px-1.5 py-0.5 rounded bg-amber-800 hover:bg-amber-700 text-white whitespace-nowrap">이 시점으로 복원 미리보기</button>
                        ) : s.kind === 'baseline' ? (
                          <span className="text-gray-600" title="기준점은 시드·맵 sha 만 기록 — 행 전체 복원은 '라이브 전체 백업' 목록의 파일 백업(10-28 readback)을 쓰세요">백업 목록 사용</span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {restoreSnap && (
            <RestorePreviewBox key={restoreSnap.id}
              base={{ type: 'snapshot', id: restoreSnap.id, label: `업로드 직전 값 — ${snapLabel(restoreSnap)}` }}
              onClose={() => setRestoreSnap(null)} />
          )}

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-gray-400">A</span>
            <select value={a} onChange={e => setA(e.target.value)} className="bg-gray-800 rounded px-1 py-0.5 max-w-[22rem]">
              <option value="">(선택)</option>
              {snaps.map(s => <option key={s.id} value={s.id}>{snapLabel(s)}</option>)}
            </select>
            <span className="text-gray-400">→ B</span>
            <select value={b} onChange={e => setB(e.target.value)} className="bg-gray-800 rounded px-1 py-0.5 max-w-[22rem]">
              <option value="">(선택)</option>
              <option value={BATCH_KEY}>현재 배치 — 지금 업로드하면 보낼 값(가상, 서버 호출 없음)</option>
              {snaps.map(s => <option key={s.id} value={s.id}>{snapLabel(s)}</option>)}
            </select>
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="레벨: 5, 10-20, i3, infinity_7"
              className="bg-gray-800 rounded px-1 py-0.5 w-44" />
            <select value={klass} onChange={e => setKlass(e.target.value)} className="bg-gray-800 rounded px-1 py-0.5">
              <option value="">모든 변경</option>
              {(Object.keys(CLASS_LABEL) as LedgerClass[]).filter(c => c !== 'same').map(c =>
                <option key={c} value={c}>{CLASS_LABEL[c]}</option>)}
              <option value="mapChanged">맵 변경</option>
              <option value="gameChanged">게임 사용 앞 3개 변경</option>
              <option value="rowAdded">행 추가</option>
              <option value="rowRemoved">행 없음</option>
            </select>
            {(b === BATCH_KEY || a === BATCH_KEY) && (
              <label className="flex items-center gap-1 text-gray-400">
                <input type="checkbox" checked={persistVirtual} onChange={e => setPersistVirtual(e.target.checked)} />
                가상 스냅샷으로 저장
              </label>
            )}
            <button disabled={!a || !b || !!busy} onClick={() => void runDiff()}
              className="px-2 py-1 rounded bg-teal-700 hover:bg-teal-600 text-white disabled:opacity-50">비교</button>
            <button disabled={!a || !b || !!busy} onClick={() => void exportCsv()}
              className="px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50">CSV</button>
            <button disabled={!res} onClick={() => res && download(`dda_seed_diff_${res.a.id}_vs_${res.b.id}.json`, JSON.stringify(res, null, 1), 'application/json')}
              className="px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50">JSON</button>
            {busy && <span className="text-yellow-300">{busy}</span>}
          </div>
          {err && <div className="text-red-300">{err}</div>}

          {res && (
            <div className="space-y-1">
              <div className="text-gray-300">
                행 {res.summary.rows} · 변경 행 <b>{res.summary.changedRows}</b> · 맵 변경 <span className="text-purple-300">{res.summary.mapChanged}</span>
                {' '}· useTileCount 변경 {res.summary.useTileCountChanged} · 게임 사용 앞 3개 변경 {res.summary.gameChanged}
                {' '}· 행 추가 {res.summary.rowAdded} · 행 없음 {res.summary.rowRemoved}
              </div>
              <table className="text-gray-400">
                <thead><tr><th className="pr-2 text-left">열</th>{(Object.keys(CLASS_LABEL) as LedgerClass[]).map(c =>
                  <th key={c} className={`px-1 ${CLASS_COLOR[c]}`}>{CLASS_LABEL[c]}</th>)}</tr></thead>
                <tbody>{LEDGER_SEED_FIELDS.map(f => (
                  <tr key={f}><td className="pr-2">{f} ({LEDGER_FIELD_STEP[f]})</td>
                    {(Object.keys(CLASS_LABEL) as LedgerClass[]).map(c =>
                      <td key={c} className="px-1 text-center">{res.summary.byField[f]?.[c] ?? 0}</td>)}</tr>
                ))}</tbody>
              </table>
              {reorderCount > 0 && lockModel?.stores === 'index' && (
                <div className="text-red-300 font-semibold">⚠ 순서만 바뀐 열 {reorderCount}개 — 게임 잠금이 인덱스 저장이라 진행 중 유저 시드가 바뀝니다</div>
              )}
              {reorderCount > 0 && lockModel?.stores === 'value' && (
                <div className="text-sky-300">순서만 바뀐 열 {reorderCount}개 — 잠금은 값 저장이라 진행 중 유저 영향 없음(분석 이벤트 dda_variant 의 index 의미만 바뀜)</div>
              )}
              {res.summary.mapChanged > 0 && (
                <div className="text-purple-300">맵 변경 {res.summary.mapChanged}행 — 맵이 바뀌면 같은 시드라도 다른 변형이 됩니다(잠긴 옛 시드가 새 맵에 적용)</div>
              )}
              <div className="max-h-96 overflow-auto border border-gray-800 rounded">
                <table className="w-full">
                  <thead className="sticky top-0 bg-gray-900"><tr className="text-gray-400">
                    <th className="text-left px-1">레벨</th><th className="text-left px-1">열</th><th className="text-left px-1">분류</th>
                    <th className="text-left px-1">A</th><th className="text-left px-1">B</th><th className="text-left px-1">위치 변경</th><th className="text-left px-1">행</th>
                  </tr></thead>
                  <tbody>
                    {shown.flatMap(it => {
                      const fs = LEDGER_SEED_FIELDS.filter(f => it.fields[f].class !== 'same' && !it.fields[f].bothUnknown);
                      const rowNote = [it.mapChanged ? '맵 변경' : '', it.useTileCountChanged ? `useTileCount ${String(it.useTileCountA)}→${String(it.useTileCountB)}` : '',
                        it.rowAdded ? '행 추가' : '', it.rowRemoved ? '행 없음' : '', it.statusB && it.statusB !== 'baseline' ? it.statusB : ''].filter(Boolean).join(' · ');
                      const list = fs.length ? fs : [null];
                      return list.map((f, i) => (
                        <tr key={`${it.id}-${f ?? 'row'}`} className="border-b border-gray-800 align-top">
                          <td className="px-1">{i === 0 && <button className="text-teal-300 hover:underline" onClick={() => void runTimeline(it.id)}>{it.id}</button>}</td>
                          <td className="px-1 text-gray-400">{f ? `${f} (${LEDGER_FIELD_STEP[f]})` : '—'}</td>
                          <td className={`px-1 ${f ? CLASS_COLOR[it.fields[f].class] : ''}`}>{f ? CLASS_LABEL[it.fields[f].class] : ''}{f && it.fields[f].gameChanged ? ' ●' : ''}</td>
                          <td className="px-1 font-mono text-gray-400">{f ? (it.fields[f].from ?? '(모름)') : ''}</td>
                          <td className="px-1 font-mono text-gray-200">{f ? (it.fields[f].to ?? '(모름)') : ''}</td>
                          <td className="px-1 font-mono text-orange-200">{f ? (it.fields[f].positions || []).map(x => `#${x.pos + 1} ${x.from ?? '∅'}→${x.to ?? '∅'}`).join(', ') : ''}</td>
                          <td className="px-1 text-purple-300">{i === 0 ? rowNote : ''}</td>
                        </tr>
                      ));
                    })}
                  </tbody>
                </table>
              </div>
              {res.items.length > SHOW_MAX && <div className="text-gray-500">표는 처음 {SHOW_MAX}행만 — 전체는 CSV/JSON</div>}
              <div className="text-gray-600">● = 게임이 읽는 앞 3개(순서 포함)가 바뀜 · 값 기준: 업로드 후 재조회 &gt; 전송 값 &gt; 업로드 직전 서버 값</div>
            </div>
          )}

          <div className="space-y-1 border-t border-gray-800 pt-2">
            <div className="flex items-center gap-2">
              <span className="text-gray-300 font-semibold">레벨 타임라인</span>
              <input value={tlId} onChange={e => setTlId(e.target.value)} placeholder="level_5 / 5 / i3"
                onKeyDown={e => { if (e.key === 'Enter') void runTimeline(); }}
                className="bg-gray-800 rounded px-1 py-0.5 w-36" />
              <button onClick={() => void runTimeline()} className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600">조회</button>
            </div>
            {tl && (tl.length === 0 ? <div className="text-gray-500">기록 없음</div> : (
              <table className="w-full">
                <thead><tr className="text-gray-400"><th className="text-left px-1">스냅샷</th><th className="text-left px-1">상태</th>
                  {LEDGER_SEED_FIELDS.map(f => <th key={f} className="text-left px-1">{LEDGER_FIELD_STEP[f]}</th>)}<th className="text-left px-1">맵</th></tr></thead>
                <tbody>{tl.map(e => (
                  <tr key={e.snapshot.id} className="border-b border-gray-800 align-top">
                    <td className="px-1 text-gray-400">{snapLabel(e.snapshot)}</td>
                    <td className="px-1">{e.status}{e.message ? <span className="text-red-300"> {e.message}</span> : null}</td>
                    {LEDGER_SEED_FIELDS.map(f => {
                      const ch = e.changeFromPrev?.[f];
                      return <td key={f} className="px-1 font-mono">
                        <span className={ch ? CLASS_COLOR[ch.class] : 'text-gray-300'}>{e.seeds[f] ?? '(모름)'}</span>
                        {ch && ch.class !== 'same' && <span className="text-gray-500"> [{CLASS_LABEL[ch.class]}]</span>}
                        {e.omitted?.[f] && e.status !== 'baseline' && <div className="text-gray-600">생략: {e.omitted[f]}</div>}
                      </td>;
                    })}
                    <td className={`px-1 font-mono ${e.mapChangedFromPrev ? 'text-purple-300' : 'text-gray-500'}`}>
                      {(e.mapSha256 || '').slice(0, 10)}{e.relabel ? ` ${e.relabel.rule}` : ''}</td>
                  </tr>
                ))}</tbody>
              </table>
            ))}
          </div>

          <details className="border-t border-gray-800 pt-2">
            <summary className="cursor-pointer text-gray-300">기준점 만들기 (v0)</summary>
            <div className="mt-1 space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-gray-400">태그</span>
                <input value={baseTag} onChange={e => setBaseTag(e.target.value)} className="bg-gray-800 rounded px-1 py-0.5 w-20" />
              </div>
              <div className="flex items-center gap-2">
                <input value={rawPath} onChange={e => setRawPath(e.target.value)} className="bg-gray-800 rounded px-1 py-0.5 flex-1 font-mono" />
                <button disabled={!!busy} onClick={() => void makeBaselineFile()} className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600">파일로 (서버 호출 없음)</button>
              </div>
              <button disabled={!!busy} onClick={() => void makeBaselineServer()} className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600">
                서버 읽기로 (levels 보드 전체 조회 1회 · 쓰기 없음)</button>
            </div>
          </details>
        </div>
      )}
    </div>
  );
}

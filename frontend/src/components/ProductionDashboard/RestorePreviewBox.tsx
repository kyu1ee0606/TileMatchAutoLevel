/**
 * 복원 2단계 UI — ① 미리보기(쓰기 없음: 현재 서버 읽기 1회와 비교) → ② 확인 문구 "복원" 입력 후 실행.
 * 기준(base): 라이브 전체 백업 또는 시드 장부 업로드 스냅샷(업로드 직전 행 전체).
 */
import { useState } from 'react';
import {
  previewRestore, executeRestore, waitJob,
  type RestorePreview, type RestoreResult, type JobView,
} from '../../api/liveBackup';

interface Props {
  base: { type: 'backup' | 'snapshot'; id: string; label?: string };
  onClose?: () => void;
}

function short(v: unknown): string {
  if (v && typeof v === 'object' && 'mapSha256' in (v as Record<string, unknown>)) {
    return `map ${String((v as Record<string, unknown>).mapSha256 ?? '').slice(0, 10)}`;
  }
  const s = v === null ? 'null' : v === undefined ? '(없음)' : typeof v === 'string' ? `"${v}"` : JSON.stringify(v);
  return s.length > 60 ? s.slice(0, 60) + '…' : s;
}

export function RestorePreviewBox({ base, onClose }: Props) {
  const [q, setQ] = useState('');
  const [scopeSnap, setScopeSnap] = useState('');
  const [pv, setPv] = useState<RestorePreview | null>(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [confirm, setConfirm] = useState('');
  const [checked, setChecked] = useState(false);
  const [job, setJob] = useState<JobView<RestoreResult> | null>(null);

  const doPreview = async () => {
    setBusy('미리보기 — 현재 서버 읽는 중(쓰기 없음)…'); setErr(''); setPv(null); setJob(null); setConfirm(''); setChecked(false);
    try {
      setPv(await previewRestore({ base: { type: base.type, id: base.id }, q, scope_snapshot: scopeSnap || undefined }));
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setErr(`미리보기 실패: ${d || (e as Error).message}`);
    } finally { setBusy(''); }
  };

  const doExecute = async () => {
    if (!pv) return;
    setBusy('복원 실행 중…'); setErr('');
    try {
      const j = await executeRestore({ plan_id: pv.planId, plan_digest: pv.planDigest, confirm_text: confirm });
      await waitJob<RestoreResult>(j.id, setJob);
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setErr(`실행 실패: ${d || (e as Error).message}`);
    } finally { setBusy(''); }
  };

  const res = job?.result;
  return (
    <div className="mt-2 p-2 rounded border border-amber-700/70 bg-amber-950/20 text-xs space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-amber-300 font-semibold">복원 미리보기 — 기준: {base.label || `${base.type} ${base.id}`}</span>
        {onClose && <button onClick={onClose} className="ml-auto px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600">닫기</button>}
      </div>
      <div className="text-gray-400">
        ① 미리보기: 현재 서버(읽기만)와 비교해 기준과 다른 열만 되돌리는 계획을 만듭니다. ② 내용을 확인하고 &quot;복원&quot; 입력 후 실행.
        보내지 않은 열은 서버 값 유지 · 행 삭제는 하지 않음(업로드로 새로 생긴 행은 수동 처리) · 미리보기 뒤 서버가 바뀐 행은 실행 때 자동 차단.
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="레벨 범위(비우면 전체): 5, 10-20, i3"
          className="bg-gray-800 rounded px-1 py-0.5 w-56" />
        {base.type === 'backup' && (
          <input value={scopeSnap} onChange={e => setScopeSnap(e.target.value)} placeholder="(선택) 업로드 스냅샷 id — 그 업로드가 바꾼 열만"
            className="bg-gray-800 rounded px-1 py-0.5 w-72 font-mono" />
        )}
        <button disabled={!!busy} onClick={() => void doPreview()}
          className="px-2 py-1 rounded bg-amber-700 hover:bg-amber-600 text-white disabled:opacity-50">미리보기</button>
        {busy && <span className="text-yellow-300">{busy}</span>}
      </div>
      {err && <div className="text-red-300">{err}</div>}
      {pv && (
        <div className="space-y-1">
          {pv.warnings.map((w, i) => <div key={i} className="text-red-300">⚠ {w}</div>)}
          <div className="text-gray-200">
            되돌릴 행 <b>{pv.rowCount}</b> · 열별: {Object.entries(pv.columnCounts).sort((a, b) => b[1] - a[1]).map(([c, n]) => `${c} ${n}`).join(' · ') || '없음'}
          </div>
          <div className="text-gray-400">
            표현 미확인 열 포함 행 {pv.unverifiedRows}(기본 제외) · 서버에 없는 행 {pv.missingCount}(복원 불가) ·
            기준에 없는 서버 행 {pv.extraCount}(건드리지 않음){pv.createdByUpload.length > 0 && ` · 업로드로 생긴 행 ${pv.createdByUpload.length}(수동)`}
          </div>
          <div className="max-h-64 overflow-auto border border-gray-800 rounded">
            <table className="w-full">
              <thead className="sticky top-0 bg-gray-900"><tr className="text-gray-400">
                <th className="text-left px-1">행</th><th className="text-left px-1">열</th><th className="text-left px-1">현재 서버</th><th className="text-left px-1">→ 복원 값</th><th className="text-left px-1">표현</th></tr></thead>
              <tbody>
                {pv.sample.flatMap(r => r.changes.map((c, i) => (
                  <tr key={`${r.id}-${c.col}`} className="border-b border-gray-800">
                    <td className="px-1 text-teal-300">{i === 0 ? r.id : ''}</td>
                    <td className="px-1">{c.col}</td>
                    <td className="px-1 font-mono text-gray-400">{short(c.current)}</td>
                    <td className="px-1 font-mono text-gray-100">{short(c.restore)}</td>
                    <td className={`px-1 ${c.verified ? 'text-gray-500' : 'text-red-300'}`} title={c.why}>{c.verified ? '실측' : '미확인'}</td>
                  </tr>
                )))}
              </tbody>
            </table>
          </div>
          {pv.rowCount > pv.sample.length && <div className="text-gray-500">대표 {pv.sample.length}행만 표시 (계획 {pv.planId})</div>}
          {pv.rowCount > 0 && !res && (
            <div className="flex items-center gap-2 flex-wrap border-t border-gray-800 pt-1">
              <label className="flex items-center gap-1 text-gray-300">
                <input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} />
                위 {pv.rowCount}행을 기준 값으로 서버에 다시 씁니다(실서버 쓰기)
              </label>
              <input value={confirm} onChange={e => setConfirm(e.target.value)} placeholder={`확인 문구 "${pv.confirmText}" 입력`}
                className="bg-gray-800 rounded px-1 py-0.5 w-40" />
              <button disabled={!checked || confirm !== pv.confirmText || !!busy} onClick={() => void doExecute()}
                className="px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-white disabled:opacity-40">복원 실행</button>
            </div>
          )}
          {job && (
            <div className="text-gray-200">
              {job.status === 'running' && <>진행 {job.current}/{job.total} · {job.elapsed}s</>}
              {job.status === 'failed' && <span className="text-red-300">실패: {job.error}</span>}
              {res && <>완료 — 검증 일치 {res.verified} · 불일치 {res.mismatch} · 실패 {res.failed} · 차단 {res.blocked}
                (장부 기록 {res.ledgerSession})
                {res.results.filter(x => x.status !== 'verified').slice(0, 20).map(x =>
                  <div key={x.id} className="text-orange-300">{x.id}: {x.status} {x.reason || ''} {(x.mismatchCols || []).join(',')}</div>)}</>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

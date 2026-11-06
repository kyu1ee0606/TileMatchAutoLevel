/**
 * 라이브 levels 보드 전체 백업 (업로드 전 권장) + 백업 목록 + 백업 기준 복원 미리보기.
 * 백업 = GameBoost levels 보드 전체를 읽기만 해서(1회 요청) 원문 그대로 backend/data/live_backup/ 에 저장. 쓰기 없음.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  getBackupStatus, listBackups, startBackup, waitJob,
  type BackupStatus, type LiveBackupSummary, type JobView,
} from '../../api/liveBackup';
import { RestorePreviewBox } from './RestorePreviewBox';

export function LiveBackupPanel({ enabled }: { enabled: boolean }) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [backups, setBackups] = useState<LiveBackupSummary[]>([]);
  const [memo, setMemo] = useState('');
  const [job, setJob] = useState<JobView<LiveBackupSummary> | null>(null);
  const [err, setErr] = useState('');
  const [showList, setShowList] = useState(false);
  const [restoreBase, setRestoreBase] = useState<LiveBackupSummary | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  const reload = useCallback(async () => {
    try {
      setStatus(await getBackupStatus());
      setBackups((await listBackups()).backups);
    } catch (e) {
      setErr(`백업 상태 조회 실패: ${(e as Error).message}`);
    }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  const run = async () => {
    setErr(''); setJob(null);
    try {
      const j = await startBackup(memo);
      const done = await waitJob<LiveBackupSummary>(j.id, setJob);
      if (done.status === 'failed') setErr(`백업 실패: ${done.error}`);
      await reload();
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setErr(`백업 실패: ${d || (e as Error).message}`);
    }
  };

  const r = job?.result;
  const running = job?.status === 'running';
  return (
    <div className="p-2 rounded border border-sky-800/70 bg-sky-950/20 text-xs space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sky-300 font-semibold">라이브 전체 백업</span>
        <input value={memo} onChange={e => setMemo(e.target.value)} placeholder="메모 (예 1.1.2 업로드 직전)"
          className="flex-1 min-w-[10rem] px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
        <button disabled={!enabled || running} onClick={() => void run()}
          className="px-2 py-1 rounded bg-sky-700 hover:bg-sky-600 text-white disabled:opacity-50">
          {running ? '백업 중…' : '라이브 전체 백업 (읽기만)'}</button>
        <button onClick={() => setShowHelp(h => !h)} className="px-2 py-1 rounded bg-gray-700 hover:bg-gray-600">사용법</button>
      </div>
      {status && (
        <div className={status.warn ? 'text-yellow-300' : 'text-gray-400'}>
          {status.warn ? '⚠ ' : '✓ '}업로드 전 백업 권장 — {status.message}
        </div>
      )}
      {running && <div className="text-sky-200">진행: {job?.phase === 'reading' ? '서버에서 levels 보드 전체 읽는 중' : job?.phase === 'saving' ? '파일 저장 중' : job?.phase} · {job?.elapsed}s</div>}
      {r && (
        <div className={r.complete ? 'text-green-300' : 'text-orange-300'}>
          {r.complete ? '완료' : '불완전 백업'} — {r.rowCount}행 ({Object.entries(r.rowKinds).map(([k, v]) => `${k} ${v}`).join(' · ')})
          {!r.complete && ` · 문제 행 ${r.problemCount}`} · 원문 sha256 {r.rawSha256.slice(0, 16)}… · {r.readSeconds}s
          <div className="text-gray-400 font-mono break-all">{r.file}</div>
        </div>
      )}
      {err && <div className="text-red-300">{err}</div>}
      {showHelp && (
        <div className="p-2 rounded bg-gray-900 text-gray-300 space-y-1">
          <div><b>업로드 전</b>: 메모 입력 → [라이브 전체 백업] → 완료 행 수·sha 확인 → 아래 시드 이력 메모 입력 → [서버 확인 후 업로드].</div>
          <div><b>문제 시</b>: [백업 목록] → 업로드 직전 백업의 [복원 미리보기] → (선택) 레벨 범위·업로드 스냅샷 id로 좁히기 → [미리보기]
            → 되돌릴 행·열·대표 diff·경고 확인 → 체크 + &quot;복원&quot; 입력 → [복원 실행] → 검증 결과 확인.</div>
          <div>또는 시드 이력 패널의 업로드 스냅샷 [이 시점으로 복원 미리보기] — 그 업로드가 바꾼 열만 업로드 직전 값으로.</div>
          <div className="text-gray-500">백업은 읽기만(보드 전체 1회 요청). 복원은 바뀐 열만 update(new=0)로 보내며 행 삭제·새 행 생성은 하지 않습니다.
            파일에서 가져온 백업(10-28 readback 등)은 그 뒤 서버 변경을 덮어쓸 수 있어 경고가 뜹니다.</div>
        </div>
      )}
      <button onClick={() => setShowList(s => !s)} className="text-sky-300 hover:underline">
        {showList ? '▾' : '▸'} 백업 목록 {backups.length}개</button>
      {showList && (
        <div className="max-h-48 overflow-auto border border-gray-800 rounded">
          <table className="w-full">
            <tbody>{[...backups].reverse().map(b => (
              <tr key={b.id} className="border-b border-gray-800">
                <td className="px-1 font-mono text-gray-400">{b.id}</td>
                <td className="px-1">{b.source === 'file' ? '파일(오래됨 주의)' : '서버 읽기'}</td>
                <td className={`px-1 ${b.complete ? 'text-gray-400' : 'text-orange-300'}`}>{b.complete ? '완전' : '불완전'}</td>
                <td className="px-1 text-gray-400">{b.rowCount}행</td>
                <td className="px-1 text-gray-300">{b.memo}</td>
                <td className="px-1"><button onClick={() => setRestoreBase(b)}
                  className="px-1.5 py-0.5 rounded bg-amber-800 hover:bg-amber-700 text-white">복원 미리보기</button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {restoreBase && (
        <RestorePreviewBox key={restoreBase.id}
          base={{ type: 'backup', id: restoreBase.id, label: `백업 ${restoreBase.id}${restoreBase.memo ? ` (${restoreBase.memo})` : ''}` }}
          onClose={() => setRestoreBase(null)} />
      )}
    </div>
  );
}

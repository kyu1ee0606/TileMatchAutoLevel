/**
 * DDA 시드만 내보내기 v2 (PLAN_DDA_SEED_ONLY_EXPORT_FIX_20261103) — levels 보드 기존 행의 시드 4열 중
 * '서버와 다르고 클리어 판정 근거가 있는' 열만 update(new=0) 로 보낸다. map·다른 칸·썸네일은 보내지 않는다.
 *
 * 1) 미리보기(dry_run): 백엔드가 **맵툴 배치 파일**(서버 저장본)에서 레벨을 읽고, GameBoost 보드를 1회 조회해 칸 단위 판정.
 *    탭(IndexedDB) 사본은 쓰지 않는다 — 탭이 아는 배치 버전이 파일과 다르거나 아직 저장 안 된 편집이 있으면 차단.
 * 2) 업로드: 미리보기의 배치 파일 sha·행 digest 가 그대로일 때만, 250행씩 순차 전송, 첫 실패에서 정지.
 *    변경(서버 값 → 다른 값)은 확인 체크 필요. 1회 실행 후 미리보기 폐기(재시도 = 새 미리보기).
 * 3) 부분 수정 게이트: 시험 1행 통과 기록(현재 코드 해시)이 없으면 실제 전송은 막힌다(미리보기는 가능).
 */
import { useEffect, useRef, useState } from 'react';
import { useUIStore } from '../../stores/uiStore';
import {
  ddaSeedExport, type DdaSeedExportResponse, type DdaSeedExportResult, type DdaSeedCellState,
} from '../../api/gboost';
import { openLedgerSession, finalizeLedgerSession } from '../../api/ddaSeedLedger';
import { chunkAbortReason, previewIdentity, shouldStopAfterChunk, targetsKey, type SeedOnlySelection } from './ddaSeedOnlyGuards';

const REASON: Record<string, string> = {
  not_seed_row: 'level_N/infinity_N 행 아님',
  no_batch_level: '배치에 원본 레벨 없음',
  no_server_row: '서버 행 없음(시드만 경로는 새 행을 만들지 않음)',
  server_row_invalid: '서버 행 형식 오류',
  no_seed_column: '서버 시드 컬럼 없음',
  server_map_differs: '서버 map/useTileCount 가 배치와 다름',
  server_map_unverifiable: '서버 map 확인 불가',
  server_changed_since_preview: '미리보기 후 서버 행 변경',
  needs_dda_confirm: '변경 확인 필요',
  partial_update_unverified: '부분 수정 시험 통과 기록 없음',
  stopped_after_failure: '앞선 전송 실패로 정지',
  batch_changed_during_export: '전송 중 배치 파일 변경',
  payload_invalid: '전송 값 형식 검사 실패(정지)',
  interrupted_uncertain: '전송 중 끊김(반영 여부 불명)',
};
const CELL_LABEL: Record<DdaSeedCellState, string> = {
  send: '보냄(변경)', same: '같음', kept: '보내지 않음', unverified: '근거 없음(보내지 않음)', blocked: '차단',
};
const CHUNK = 250;

type Target = { target_id: string; source_level: number };

function errMsg(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  if (d && typeof d === 'object' && 'message' in (d as Record<string, unknown>)) return String((d as { message: string }).message);
  if (typeof d === 'string') return d;
  return (e as Error).message;
}

function sendCount(r: DdaSeedExportResult): number {
  return Object.values(r.cells ?? {}).filter(c => c?.state === 'send').length;
}

export function DdaSeedOnlyExport({
  boardId, enabled, batchId, getTargets, infinityRelabel, getTabVersion, getUnsyncedEdits, selection,
}: {
  boardId: string;
  /** GBoost 연결 정상 + 다른 업로드 단계 아님 + 프리픽스 level_/infinity_ */
  enabled: boolean;
  batchId: string;
  /** 업로드와 같은 대상 규칙(buildUploadTargets) — 행 id + 원본 레벨 번호 */
  getTargets: () => Promise<Target[]>;
  infinityRelabel: boolean;
  /** 탭이 마지막으로 안 서버 배치 버전(knownVersions → __server_version) */
  getTabVersion: () => Promise<number | undefined>;
  /** 탭에서 아직 배치 파일로 올리지 않은 편집 수 — 클라이언트가 세는 값(서버가 독립 보장 못 함; 서버 방어 = 배치 sha 재확인) */
  getUnsyncedEdits: () => number;
  /** 미리보기를 묶는 대상·옵션 식별값(배치 id·범위·무한 모드·relabel·프리픽스). 바뀌면 미리보기 폐기 */
  selection: SeedOnlySelection;
}) {
  const { addNotification } = useUIStore();
  const [preview, setPreview] = useState<{
    resp: DdaSeedExportResponse; targets: Target[]; tabVersion: number; selection: SeedOnlySelection; identity: string;
  } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [trialOk, setTrialOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [done, setDone] = useState<DdaSeedExportResult[] | null>(null);
  const [info, setInfo] = useState('');
  const inFlight = useRef(false);
  // [재리뷰 v3] 전송 중 청크 재확인은 '지금' 화면 선택값과 비교해야 한다(클릭 시점 클로저 값이면 항상 같아 무효)
  const selRef = useRef(selection);
  selRef.current = selection;
  const selKey = previewIdentity(selection);

  // [리뷰 반영 v2] 대상·옵션이 바뀌면 미리보기와 확인 체크를 버린다(전송 중이면 청크 검사가 멈춘다).
  useEffect(() => {
    if (inFlight.current) return;
    setPreview(p => (p && previewIdentity(p.selection) !== selKey ? null : p));
    setConfirm(false);
    setTrialOk(false);
  }, [selKey]);

  if (boardId !== 'levels') return null;
  const stale = !!preview && previewIdentity(preview.selection) !== selKey;

  const runPreview = async () => {
    if (inFlight.current || !enabled) return;
    const dirty = getUnsyncedEdits();
    if (dirty > 0) {
      addNotification('error', `탭에 아직 저장되지 않은 편집 ${dirty}개 — 동기화된 뒤 미리보기하세요(시드만 경로는 저장된 배치 파일 값을 보냅니다).`);
      return;
    }
    inFlight.current = true;
    setBusy(true); setDone(null); setConfirm(false); setTrialOk(false); setInfo('');
    try {
      const tabVersion = await getTabVersion();
      if (tabVersion === undefined) throw new Error('탭의 배치 버전을 모릅니다 — 새로고침(배치 당기기) 후 다시 하세요');
      const targets = await getTargets();
      const sel = { ...selection };
      const resp = await ddaSeedExport({
        batch_id: batchId, expected_batch_version: tabVersion, targets, dry_run: true,
        infinity_relabel: infinityRelabel, client_unsynced_edits: dirty, selection: sel,
      });
      setPreview({ resp, targets, tabVersion, selection: sel, identity: previewIdentity(sel, targets) });
    } catch (e) {
      setPreview(null);
      addNotification('error', `DDA 시드만 미리보기 실패 — 업로드하지 않음: ${errMsg(e)}`);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const runSend = async (trial: boolean) => {
    if (inFlight.current || !preview || !enabled) return;
    inFlight.current = true;                 // [재리뷰 v3] 첫 await 전에 잡아 더블클릭 차단
    setBusy(true);
    try {
      await sendOnce(trial, preview);
    } catch (e) {
      // 선검사(getTabVersion/getTargets) 등 sendOnce 내부 try 밖 예외도 알린다
      addNotification('error', `DDA 시드만 업로드 준비 실패 — 전송하지 않음: ${errMsg(e)}`);
    } finally {
      inFlight.current = false;
      setBusy(false);
      setProgress(null);
    }
  };

  const sendOnce = async (trial: boolean, used: NonNullable<typeof preview>) => {
    // 미리보기 뒤 대상·옵션·탭 버전·대상 목록이 바뀌었으면 전송하지 않는다
    const pre = chunkAbortReason({ dirty: getUnsyncedEdits(), selectionNow: selRef.current, selectionAtPreview: used.selection,
      tabVersionNow: await getTabVersion(), tabVersionAtPreview: used.tabVersion });
    const nowTargets = pre ? null : await getTargets();
    if (pre || (nowTargets && targetsKey(nowTargets) !== targetsKey(used.targets))) {
      setPreview(null); setConfirm(false); setTrialOk(false);
      addNotification('error', `${pre ?? '대상 목록이 미리보기 후 바뀜'} — 다시 미리보기하세요.`);
      return;
    }
    const todo = used.resp.results.filter(r => !r.blocked && sendCount(r) > 0);
    let rows = todo;
    if (trial) {
      // 시험 행: '채움' 1열짜리 정식 행 우선, 없으면 1열 행
      const one = todo.filter(r => sendCount(r) === 1);
      const pick = one.find(r => r.change === 'fill' && r.target_id.startsWith('level_')) ?? one.find(r => r.change === 'fill') ?? one[0] ?? todo[0];
      if (!pick) return;
      rows = [pick];
      if (!trialOk) { addNotification('warning', '시험 1행 전송 승인 체크 후 실행하세요.'); return; }
    } else if (!used.resp.partialUpdate.allowed) {
      addNotification('error', '부분 수정 시험 통과 기록이 없습니다 — 시험 1행을 먼저 통과해야 합니다.');
      return;
    }
    if (rows.some(r => r.change === 'change') && !confirm) {
      addNotification('warning', '서버 값 변경 대상이 있습니다 — 확인 체크 후 업로드하세요.');
      return;
    }
    setPreview(null);                        // 1회용: 재시도는 새 미리보기
    const out: DdaSeedExportResult[] = [];
    let ledgerSid: string | undefined;
    try {
      ledgerSid = (await openLedgerSession({
        board: 'levels', batch_id: batchId, source: 'dda_seed_export',
        options: { trial, rows: rows.length, infinityRelabel, batchVersion: used.resp.batchVersion },
      })).id;
    } catch (e) {
      addNotification('warning', `DDA 시드 이력 세션 생성 실패 — 요청별 자동 세션에 기록: ${errMsg(e)}`);
    }
    try {
      const chunkSize = trial ? 1 : CHUNK;
      setProgress({ done: 0, total: rows.length });
      for (let i = 0; i < rows.length; i += chunkSize) {
        const chunk = rows.slice(i, i + chunkSize);
        // [리뷰 반영 v2] 청크마다 미동기 편집·옵션·탭 버전 재확인 — 하나라도 바뀌면 즉시 중단
        const dirty = getUnsyncedEdits();
        const why = chunkAbortReason({ dirty, selectionNow: selRef.current, selectionAtPreview: used.selection,
          tabVersionNow: await getTabVersion(), tabVersionAtPreview: used.tabVersion });
        if (why) throw new Error(why);
        const r = await ddaSeedExport({
          batch_id: batchId, expected_batch_version: used.tabVersion, expected_batch_sha256: used.resp.batchFileSha256,
          targets: chunk.map(t => ({ target_id: t.target_id, source_level: t.source_level as number, expected_server_digest: t.serverDigest })),
          dry_run: false, confirm, trial, infinity_relabel: infinityRelabel, client_unsynced_edits: dirty,
          preview_id: used.resp.preview_id ?? undefined, selection: used.selection,
        }, ledgerSid);
        out.push(...r.results);
        setProgress({ done: Math.min(i + chunk.length, rows.length), total: rows.length });
        if (trial && r.trial) {
          setInfo(`시험 1행 ${r.trial.target_id as string}: ${r.trial.judge?.passed ? '통과' : '실패'} · 기록 ${r.trial.recordPath ?? '(저장 실패)'}`);
        }
        if (shouldStopAfterChunk(r.results)) break;                       // 첫 실패(failed·payload_invalid·interrupted·stopped)에서 정지
      }
      setDone(out);
      const saved = out.filter(x => x.status === 'saved').length;
      addNotification(saved === rows.length ? 'success' : 'warning',
        `DDA 시드만 ${trial ? '시험 ' : ''}업로드: 저장 ${saved}/${rows.length}, 차단/실패/무변경 ${out.length - saved}`);
    } catch (e) {
      const part = (e as { response?: { data?: { detail?: { results?: DdaSeedExportResult[] } } } }).response?.data?.detail?.results;
      if (Array.isArray(part)) out.push(...part);          // 서버가 중단 전 처리한 행(409 batch_changed_during_export)
      setDone(out);
      addNotification('error', `DDA 시드만 업로드 중단: ${errMsg(e)} — 결과 확인 후 다시 미리보기하세요`);
    } finally {
      if (ledgerSid) {
        try { await finalizeLedgerSession(ledgerSid, { results: out.length, trial }); }
        catch (e) { addNotification('warning', `DDA 시드 이력 마감 실패: ${errMsg(e)}`); }
      }
      setConfirm(false); setTrialOk(false);
    }
  };

  const resp = preview?.resp;
  const res = resp?.results ?? [];
  const cells = resp?.summary.cells;
  const blocked = res.filter(r => r.blocked).reduce<Record<string, string[]>>((a, r) => { (a[r.reason] ??= []).push(r.target_id); return a; }, {});
  const sendRows = res.filter(r => !r.blocked && sendCount(r) > 0);
  const changeCells = sendRows.reduce((n, r) => n + Object.values(r.cells ?? {}).filter(c => c?.state === 'send' && c.kind === 'change').length, 0);
  const doneGroups = done ? done.reduce<Record<string, number>>((a, r) => { const k = `${r.status}:${r.reason}`; a[k] = (a[k] ?? 0) + 1; return a; }, {}) : null;

  return (
    <div className="mt-3 p-3 bg-gray-900 rounded-lg border border-indigo-800/60 space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-indigo-300 font-semibold">DDA 시드만 내보내기</span>
        <span className="text-gray-500">시드 4열 중 바뀌고 근거 있는 열만 · 값 = 저장된 배치 파일 · 서버 보드 1회 조회 · map/다른 칸/썸네일 미전송</span>
      </div>
      <div className="flex gap-2 flex-wrap">
        <button onClick={runPreview} disabled={!enabled || busy}
          className="px-2 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-50">
          {busy && !preview ? '확인 중…' : '시드만 미리보기'}
        </button>
        {preview && (
          <>
            <button onClick={() => runSend(true)} disabled={!enabled || busy || stale || sendRows.length === 0}
              className="px-2 py-1 rounded bg-amber-800 hover:bg-amber-700 text-white disabled:opacity-50">
              시험 1행 전송
            </button>
            <button onClick={() => runSend(false)} disabled={!enabled || busy || stale || sendRows.length === 0 || !resp?.partialUpdate.allowed}
              className="px-2 py-1 rounded bg-green-800 hover:bg-green-700 text-white disabled:opacity-50">
              시드만 업로드 ({sendRows.length}행)
            </button>
          </>
        )}
      </div>
      {stale && <div className="text-red-300">대상/옵션이 미리보기 후 바뀌었습니다 — 다시 미리보기하세요(전송 막힘).</div>}
      {progress && <div className="text-gray-400">전송 {progress.done}/{progress.total}</div>}
      {preview && resp && cells && (
        <div className="space-y-1 text-gray-300">
          <div className="text-gray-400">
            배치 버전 탭 v{preview.tabVersion} · 파일 v{resp.batchVersion} · 파일 sha {resp.batchFileSha256.slice(0, 8)} ·
            부분 수정 {resp.partialUpdate.allowed
              ? <span className="text-green-300">허용({resp.partialUpdate.by})</span>
              : <span className="text-yellow-300">시험 통과 기록 없음 — 전체 전송 차단</span>}
          </div>
          <div>
            칸 {res.length * 4}: {(['send', 'same', 'kept', 'unverified', 'blocked'] as DdaSeedCellState[]).map(k => (
              <span key={k} className={k === 'send' ? 'text-orange-300' : k === 'blocked' ? 'text-red-300' : 'text-gray-400'}>
                {' '}{CELL_LABEL[k]} {cells[k] ?? 0}{k !== 'blocked' ? ' ·' : ''}
              </span>))}
          </div>
          <div className="text-gray-400">보낼 행 {sendRows.length} · 그중 서버 값 변경 칸 {changeCells}</div>
          {Object.entries(blocked).map(([k, v]) => (
            <div key={k} className="text-gray-400">
              차단 {REASON[k] ?? k} {v.length}: {v.slice(0, 8).join(', ')}{v.length > 8 ? ' …' : ''}
            </div>
          ))}
          {changeCells > 0 && (
            <label className="flex items-center gap-1 text-orange-300">
              <input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} />
              서버 값 변경 {changeCells}칸을 확인했습니다
            </label>
          )}
          <label className="flex items-center gap-1 text-amber-300">
            <input type="checkbox" checked={trialOk} onChange={e => setTrialOk(e.target.checked)} />
            시험 1행 실서버 전송을 승인했습니다(전송 후 보드 재조회 대조 · 통과 기록 생성)
          </label>
        </div>
      )}
      {info && <div className="text-gray-300">{info}</div>}
      {doneGroups && (
        <div className="text-gray-300">
          결과: {Object.entries(doneGroups).map(([k, v]) => `${k} ${v}`).join(' · ')}
        </div>
      )}
    </div>
  );
}

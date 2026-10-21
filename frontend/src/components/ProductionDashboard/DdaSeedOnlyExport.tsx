/**
 * DDA 시드만 내보내기 (문서 47 §5) — levels 보드 기존 행에서 ddaEasySeeds/ddaHardSeeds 두 컬럼만 바꾼다.
 *
 * 1) 미리보기(dry_run): 백엔드가 서버 행을 strict 조회하고 출시 원본 행 스냅샷과 비교한다.
 *    두 컬럼 외 값/키가 다르거나 map 이 다르거나 조회에 실패하면 그 대상은 '차단'이다(기본값 추정 없음).
 * 2) 업로드: 미리보기 digest 와 서버 행이 그대로일 때만 저장한다(바뀌었으면 차단 → 새 미리보기).
 *    비움/변경은 확인 체크가 필요하다. 1회 실행 후 미리보기를 폐기한다(재시도 = 새 검증).
 * map·다른 컬럼·자료형·미지 필드는 서버 행 값을 그대로 돌려보낸다(변환·썸네일 없음).
 */
import { useRef, useState } from 'react';
import { useUIStore } from '../../stores/uiStore';
import type { LevelJSON } from '../../types';
import { ddaSeedExport, type DdaSeedExportResult } from '../../api/gboost';

const REASON: Record<string, string> = {
  not_level_row: 'level_N 행 아님',
  catalog_error: '개발용 목록 검증 실패',
  no_snapshot: '원본 행 스냅샷 없음',
  no_server_row: '서버 행 없음',
  server_row_invalid: '서버 행 형식 오류',
  no_seed_column: '서버 시드 컬럼 없음',
  server_row_differs: '서버 행이 검증 기준과 다름',
  server_map_unverifiable: '서버 map 확인 불가',
  server_map_differs: '서버 map 이 검증 기준과 다름',
  lookup_failed: '서버 행 조회 실패',
  server_changed_since_preview: '미리보기 후 서버 행 변경',
  needs_dda_confirm: '비움/변경 확인 필요',
};

function group<T>(arr: T[], key: (x: T) => string): Record<string, T[]> {
  return arr.reduce<Record<string, T[]>>((a, x) => { (a[key(x)] ??= []).push(x); return a; }, {});
}

export function DdaSeedOnlyExport({
  boardId,
  enabled,
  getTargets,
}: {
  boardId: string;
  /** GBoost 연결 정상 + 다른 업로드 단계 아님 + level_ 프리픽스 */
  enabled: boolean;
  getTargets: () => Promise<Array<{ target_id: string; level_json: LevelJSON }>>;
}) {
  const { addNotification } = useUIStore();
  const [preview, setPreview] = useState<{ results: DdaSeedExportResult[]; targets: Map<string, LevelJSON> } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<DdaSeedExportResult[] | null>(null);
  const inFlight = useRef(false);

  if (boardId !== 'levels') return null;

  const runPreview = async () => {
    if (inFlight.current || !enabled) return;
    inFlight.current = true;
    setBusy(true);
    setDone(null);
    setConfirm(false);
    try {
      const targets = await getTargets();
      const r = await ddaSeedExport({ targets, dry_run: true });
      setPreview({ results: r.results, targets: new Map(targets.map(t => [t.target_id, t.level_json])) });
    } catch (e) {
      setPreview(null);
      addNotification('error', `DDA 시드만 미리보기 실패 — 업로드하지 않음: ${(e as Error).message}`);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const runUpload = async () => {
    if (inFlight.current || !preview || !enabled) return;
    const todo = preview.results.filter(r => !r.blocked && r.change !== 'same');
    const risky = todo.some(r => r.change === 'clear' || r.change === 'change');
    if (risky && !confirm) {
      addNotification('warning', '서버 값 비움/변경 대상이 있습니다 — 확인 체크 후 업로드하세요.');
      return;
    }
    inFlight.current = true;
    setBusy(true);
    const used = preview;
    setPreview(null);                        // 1회용: 재시도는 새 미리보기
    try {
      const r = await ddaSeedExport({
        targets: todo.map(t => ({
          target_id: t.target_id,
          level_json: used.targets.get(t.target_id) as LevelJSON,
          expected_server_digest: t.serverDigest,
        })),
        dry_run: false,
        confirm,
      });
      setDone(r.results);
      const saved = r.results.filter(x => x.status === 'saved').length;
      const bad = r.results.length - saved;
      addNotification(bad ? 'warning' : 'success', `DDA 시드만 업로드: 저장 ${saved}, 차단/실패/무변경 ${bad}`);
    } catch (e) {
      addNotification('error', `DDA 시드만 업로드 실패: ${(e as Error).message} — 결과 확인 후 다시 미리보기하세요`);
    } finally {
      inFlight.current = false;
      setBusy(false);
      setConfirm(false);
    }
  };

  const res = preview?.results ?? [];
  const blocked = group(res.filter(r => r.blocked), r => r.reason);
  const byChange = group(res.filter(r => !r.blocked), r => r.change ?? '?');
  const doneGroups = done ? group(done, r => `${r.status}:${r.reason}`) : null;

  return (
    <div className="mt-3 p-3 bg-gray-900 rounded-lg border border-indigo-800/60 space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-indigo-300 font-semibold">DDA 시드만 내보내기</span>
        <span className="text-gray-500">기존 서버 행에서 두 컬럼만 변경 · 다른 값/map 보존 · 검증 실패 대상은 차단</span>
      </div>
      <div className="flex gap-2">
        <button onClick={runPreview} disabled={!enabled || busy}
          className="px-2 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-50">
          {busy && !preview ? '확인 중…' : '시드만 미리보기'}
        </button>
        {preview && (
          <button onClick={runUpload} disabled={!enabled || busy || !res.some(r => !r.blocked && r.change !== 'same')}
            className="px-2 py-1 rounded bg-green-800 hover:bg-green-700 text-white disabled:opacity-50">
            시드만 업로드 ({res.filter(r => !r.blocked && r.change !== 'same').length})
          </button>
        )}
      </div>
      {preview && (
        <div className="space-y-1 text-gray-300">
          <div>
            신규 기입 {byChange.fill?.length ?? 0} · 동일(전송 안 함) {byChange.same?.length ?? 0} ·
            <span className="text-orange-300"> 변경 {byChange.change?.length ?? 0}</span> ·
            <span className="text-red-300"> 비움 {byChange.clear?.length ?? 0}</span> ·
            <span className="text-gray-400"> 차단 {res.filter(r => r.blocked).length}</span>
          </div>
          {Object.entries(blocked).map(([k, v]) => (
            <div key={k} className="text-gray-400">
              차단 {REASON[k] ?? k} {v.length}: {v.slice(0, 8).map(x => x.target_id + (x.detail ? `(${x.detail.slice(0, 60)})` : '')).join(', ')}{v.length > 8 ? ' …' : ''}
            </div>
          ))}
          {(byChange.clear?.length || byChange.change?.length) ? (
            <label className="flex items-center gap-1 text-orange-300">
              <input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} />
              서버 값 비움 {byChange.clear?.length ?? 0} · 변경 {byChange.change?.length ?? 0} 을 확인했습니다
            </label>
          ) : null}
        </div>
      )}
      {doneGroups && (
        <div className="text-gray-300">
          결과: {Object.entries(doneGroups).map(([k, v]) => `${k} ${v.length}`).join(' · ')}
        </div>
      )}
    </div>
  );
}

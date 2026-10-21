/**
 * 'DDA 시드 갱신' (문서 47) — 프로덕션 → 테스트 탭.
 *
 * 1) 버튼 → 변경 없는 사전검사/미리보기 (백엔드 /api/dda-seeds/preview, 개발용 목록 기준)
 * 2) 사용자가 '적용' → 맵에디터 내부 레벨(level_json.ddaEasySeeds/ddaHardSeeds)만 저장
 *    서버 전송·봇 실행·샤드 굽기와 연결하지 않는다.
 * - 저장 직전 디스크(IndexedDB) 값을 다시 읽어 미리보기 시점과 다르면 경합으로 건너뜀
 * - 미저장 편집(다이얼 조정 중인 레벨)은 건너뜀 / 처리 중 중복 클릭 차단 / 다시 눌러도 같은 결과(멱등)
 * - 새 시드를 만들지 않는다. 목록 값으로 빈칸/형식 오류만 보충하고, 다른 정상 값은 충돌로 보고만 한다.
 */
import { useRef, useState } from 'react';
import { useUIStore } from '../../stores/uiStore';
import {
  getProductionLevelsByBatch,
  getProductionLevel,
  saveProductionLevel,
} from '../../storage/productionStorage';
import { previewDdaSeeds, type DdaLevelPlan, type DdaPreviewResponse, type DdaSeedField } from '../../api/ddaSeeds';
import { applyDdaPlans, type DdaApplyResult } from './ddaSeedApply';

const REASON_LABEL: Record<string, string> = {
  no_data: '자료 없음(L1~31 등)',
  hold: '보류(126)',
  partial_hold: '부분 보류(L322)',
  excluded: '자동 적용 제외',
  map_mismatch: '원본 맵 불일치',
  n_mismatch: 'N(타일 종류 수) 불일치',
  catalog_error: '개발용 목록 검증 실패',
  check_error: '검사 오류',
};

function fmt(v: string | null | undefined): string {
  if (v === null || v === undefined) return '(없음)';
  if (v === '') return '(빈 값)';
  return v;
}

function levelList(nums: number[], max = 30): string {
  const s = nums.slice(0, max).join(', ');
  return nums.length > max ? `${s} … (+${nums.length - max})` : s;
}

export function DdaSeedRefreshPanel({
  batchId,
  busy,
  unsavedLevelNumber,
  onApplied,
}: {
  batchId: string;
  /** 다른 일괄 작업(순차검증·재생성 등) 진행 중이면 true → 버튼 비활성 */
  busy: boolean;
  /** 미저장 편집이 있는 레벨 번호(없으면 null) — 적용 시 건너뜀 */
  unsavedLevelNumber: number | null;
  onApplied: () => void;
}) {
  const { addNotification } = useUIStore();
  const [phase, setPhase] = useState<'idle' | 'checking' | 'preview' | 'applying' | 'done'>('idle');
  const [preview, setPreview] = useState<DdaPreviewResponse | null>(null);
  const [range, setRange] = useState<{ count: number; min: number; max: number } | null>(null);
  const [result, setResult] = useState<DdaApplyResult | null>(null);
  const inFlight = useRef(false);
  const snapshot = useRef<Map<number, string>>(new Map());

  const working = phase === 'checking' || phase === 'applying';

  const runCheck = async () => {
    if (inFlight.current || busy) return;
    inFlight.current = true;
    setPhase('checking');
    setResult(null);
    try {
      const levels = (await getProductionLevelsByBatch(batchId)).filter(l => l.level_json);
      const nums = levels.map(l => l.meta.level_number);
      setRange(nums.length ? { count: nums.length, min: Math.min(...nums), max: Math.max(...nums) } : null);
      const res = await previewDdaSeeds(levels.map(l => ({ level_number: l.meta.level_number, level_json: l.level_json })));
      const snap = new Map<number, string>();
      const byNum = new Map(levels.map(l => [l.meta.level_number, l]));
      for (const r of res.results) {
        if (r.action === 'update') snap.set(r.level, JSON.stringify(byNum.get(r.level)?.level_json));
      }
      snapshot.current = snap;
      setPreview(res);
      setPhase('preview');
    } catch (e) {
      addNotification('error', `DDA 시드 사전검사 실패: ${(e as Error).message}`);
      setPhase('idle');
    } finally {
      inFlight.current = false;
    }
  };

  const runApply = async () => {
    if (inFlight.current || !preview) return;
    inFlight.current = true;
    setPhase('applying');
    try {
      const out = await applyDdaPlans(
        preview.results, snapshot.current, unsavedLevelNumber,
        n => getProductionLevel(batchId, n),
        lv => saveProductionLevel(batchId, lv),
      );
      setResult(out);
      setPhase('done');
      const partial = out.failed.length + out.raced.length + out.skippedDirty.length;
      addNotification(partial ? 'warning' : 'success',
        `DDA 시드 저장 ${out.saved.length}개` + (partial ? ` · 실패 ${out.failed.length} · 경합 ${out.raced.length} · 미저장 편집 ${out.skippedDirty.length}` : ''));
      onApplied();
    } finally {
      inFlight.current = false;
    }
  };

  const byAction = (a: string) => preview?.results.filter(r => r.action === a) ?? [];
  const updates = byAction('update');
  const conflicts = byAction('conflict');
  const skips = byAction('skip');
  const skipGroups = skips.reduce<Record<string, number[]>>((acc, r) => {
    (acc[r.reason] ??= []).push(r.level);
    return acc;
  }, {});

  const fieldCell = (r: DdaLevelPlan, f: DdaSeedField) => {
    const fp = r.fields?.[f];
    if (!fp) return null;
    if (fp.state === 'match') return <span className="text-gray-400">유지</span>;
    return (
      <span>
        <span className="text-red-300">{fmt(fp.before)}</span>
        <span className="text-gray-500"> → </span>
        <span className="text-green-300">{fmt(fp.after)}</span>
        <span className="text-gray-500"> ({fp.state === 'missing' ? '보충' : '복구'})</span>
      </span>
    );
  };

  return (
    <div className="p-3 bg-gray-800 rounded-lg border border-indigo-700/50 space-y-2">
      <div className="flex items-center gap-2">
        <button
          onClick={runCheck}
          disabled={busy || working}
          className="px-3 py-1.5 text-sm rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          title="검증된 DDA 시드(easy/hard 각 5개)를 레벨 설정에 채울지 미리 확인합니다. 이 단계에서는 아무것도 바꾸지 않습니다."
        >
          {phase === 'checking' ? '검사 중…' : '🎚️ DDA 시드 갱신'}
        </button>
        <span className="text-[11px] text-gray-400">
          미리보기 → 확인 후 맵에디터 내부 레벨 설정만 저장 (서버 전송 없음). 준비된 시드 ≠ 실제 난이도/Unity 검증 완료
        </span>
        {busy && <span className="text-[11px] text-yellow-400">다른 작업 진행 중 — 대기</span>}
      </div>

      {preview && !preview.catalog.ok && (
        <div className="text-xs text-red-400">개발용 목록 검증 실패: {preview.catalog.error} — 모든 레벨 건너뜀</div>
      )}

      {preview && (phase === 'preview' || phase === 'applying' || phase === 'done') && (
        <div className="text-xs text-gray-300 space-y-2">
          <div>
            대상 범위: {range ? `${range.count}개 (Lv${range.min}~${range.max})` : '0개'}
            {preview.catalog.ok && <span className="text-gray-500"> · 목록 {preview.catalog.catalogVersion} ({preview.catalog.sha256?.slice(0, 12)})</span>}
          </div>
          <div className="flex flex-wrap gap-3">
            <span className="text-green-400">갱신 예정 {updates.length}</span>
            <span className="text-gray-300">유지 {byAction('keep').length}</span>
            <span className="text-orange-400">충돌 {conflicts.length}</span>
            <span className="text-gray-400">보류·건너뜀 {skips.length}</span>
          </div>
          {Object.keys(skipGroups).length > 0 && (
            <ul className="list-disc ml-5 text-gray-400">
              {Object.entries(skipGroups).map(([reason, nums]) => (
                <li key={reason}>{REASON_LABEL[reason] ?? reason} {nums.length}: {levelList(nums, 15)}</li>
              ))}
            </ul>
          )}
          {conflicts.length > 0 && (
            <div className="text-orange-300">
              충돌(정상 형식이지만 검증값과 다름 — 자동 덮어쓰기 안 함, 두 방향 모두 건너뜀): {levelList(conflicts.map(r => r.level))}
            </div>
          )}
          {updates.length > 0 && (
            <div className="max-h-48 overflow-auto border border-gray-700 rounded">
              <table className="w-full text-[11px]">
                <thead className="text-gray-400 sticky top-0 bg-gray-800">
                  <tr><th className="text-left px-2">레벨</th><th className="text-left px-2">easy</th><th className="text-left px-2">hard</th></tr>
                </thead>
                <tbody>
                  {updates.slice(0, 200).map(r => (
                    <tr key={r.level} className="border-t border-gray-700/50">
                      <td className="px-2">{r.level}</td>
                      <td className="px-2 font-mono">{fieldCell(r, 'ddaEasySeeds')}</td>
                      <td className="px-2 font-mono">{fieldCell(r, 'ddaHardSeeds')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {updates.length > 200 && <div className="px-2 text-gray-500">… 외 {updates.length - 200}개</div>}
            </div>
          )}

          {phase !== 'done' && (
            <div className="flex gap-2">
              <button
                onClick={runApply}
                disabled={working || busy || updates.length === 0}
                className="px-3 py-1 rounded bg-green-700 hover:bg-green-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {phase === 'applying' ? '저장 중…' : `적용 (${updates.length}개 레벨 저장)`}
              </button>
              <button
                onClick={() => { setPreview(null); setPhase('idle'); }}
                disabled={working}
                className="px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 disabled:opacity-50"
              >
                취소
              </button>
            </div>
          )}

          {result && (
            <div className="space-y-1">
              <div className="text-green-400">저장 {result.saved.length}개</div>
              {result.raced.length > 0 && <div className="text-orange-300">경합(검사 후 편집됨, 건너뜀) {result.raced.length}: {levelList(result.raced)}</div>}
              {result.skippedDirty.length > 0 && <div className="text-orange-300">미저장 편집 있어 건너뜀: {levelList(result.skippedDirty)}</div>}
              {result.failed.length > 0 && (
                <div className="text-red-400">
                  저장 실패 {result.failed.length}: {result.failed.slice(0, 20).map(f => `${f.level}(${f.message})`).join(', ')}
                </div>
              )}
              <div className="text-gray-500">다시 누르면 저장된 레벨은 '유지'로 표시됩니다.</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

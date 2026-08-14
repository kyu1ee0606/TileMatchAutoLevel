/**
 * [초반 고정 레벨 1~31] 튜토리얼 구간을 매 배치마다 같은 모양으로 내보내기 위한 관리 패널.
 *
 * 왜: 초반은 학습 흐름이라 배치마다 모양이 바뀌면 난이도 곡선이 흔들린다. 기존엔 Lv1~3 만
 * 생성기에 하드코딩돼 있었고 4~31 은 매번 절차생성이었다. 여기 등록된 레벨은 생성 시 그대로 쓰인다.
 *
 * 보스 슬롯(10·20·30)은 **읽기 전용**이다 — 보스 템플릿(from-boss-template)이 정본이라
 * 여기서 또 고정하면 정본이 둘이 되어 드리프트가 난다. 모양 확인만 가능하고 저장/삭제는 403.
 */
import { useCallback, useEffect, useState } from 'react';
import apiClient from '../api/client';
import { FixedLevelEditor } from './FixedLevelEditor';

interface Slot {
  level: number;
  readonly: boolean;
  reason?: string | null;
  fixed: boolean;
  source?: string | null;
  updated_at?: string | null;
  note?: string | null;
  layer_count?: number;
  total_tiles?: number;
  layers?: Array<{ col: number; cells: string[] }>;
  boss_template_id?: string;
}

/** 층을 겹쳐 그린 미니 실루엣. 위층일수록 밝게. */
function MiniStack({ layers, size = 46, color = '#60a5fa' }:
  { layers?: Slot['layers']; size?: number; color?: string }) {
  if (!layers || layers.length === 0) return (
    <div className="rounded bg-gray-900/60 flex items-center justify-center text-[9px] text-gray-600"
      style={{ width: size, height: size }}>없음</div>
  );
  const base = Math.max(...layers.map(l => l.col || 0), 1);
  const u = size / base;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="rounded bg-gray-900/60">
      {layers.map((L, li) => {
        // 홀짝 교대로 격자가 1 작은 층은 반 칸 안쪽에 놓인다
        const off = ((base - (L.col || base)) / 2) * u;
        const op = 0.3 + (0.7 * li) / Math.max(1, layers.length - 1);
        return (
          <g key={li} opacity={op}>
            {L.cells.map(c => {
              const [x, y] = c.split('_').map(Number);
              if (Number.isNaN(x) || Number.isNaN(y)) return null;
              return <rect key={c} x={off + x * u + u * 0.08} y={off + y * u + u * 0.08}
                width={u * 0.84} height={u * 0.84} rx={u * 0.2} fill={color} />;
            })}
          </g>
        );
      })}
    </svg>
  );
}

export function FixedLevelsPanel() {
  const [open, setOpen] = useState(false);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);
  const [seedBatchId, setSeedBatchId] = useState('');
  const [editing, setEditing] = useState<number | null>(null);   // 에디터 대상 레벨
  const [batches, setBatches] = useState<Array<{ batch_id: string; name: string | null; level_count: number }>>([]);

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get('/debug/fixed-levels');
      setSlots((r.data?.slots || []) as Slot[]);
    } catch { setMsg({ kind: 'err', text: '목록 조회 실패 (백엔드 확인)' }); }
  }, []);

  useEffect(() => {
    if (!open) return;
    void load();
    apiClient.get('/production/batches')
      .then(r => {
        const list = (r.data || []) as Array<{ batch_id: string; name: string | null; level_count: number }>;
        const usable = list.filter(b => (b.level_count ?? 0) >= 31);
        setBatches(usable);
        if (!seedBatchId && usable[0]) setSeedBatchId(usable[0].batch_id);
      })
      .catch(() => { /* 배치 목록 없으면 시드 UI만 비활성 */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, load]);

  const fixedCount = slots.filter(s => s.fixed).length;
  const editable = slots.filter(s => !s.readonly).length;

  const seed = async (overwrite: boolean) => {
    if (!seedBatchId) { setMsg({ kind: 'err', text: '시드 배치를 선택하세요' }); return; }
    setBusy(true);
    try {
      const r = await apiClient.post(
        `/debug/fixed-levels/seed-from-batch?batch_id=${encodeURIComponent(seedBatchId)}&overwrite=${overwrite}`);
      setMsg({ kind: 'ok', text: `${r.data?.count ?? 0}개 고정 등록 (스킵 ${(r.data?.skipped || []).length})` });
      await load();
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setMsg({ kind: 'err', text: d || '시드 실패' });
    } finally { setBusy(false); }
  };

  const unfix = async (n: number) => {
    if (!window.confirm(`Lv${n} 고정을 해제할까요? (다시 절차생성으로 돌아갑니다)`)) return;
    try {
      await apiClient.delete(`/debug/fixed-levels/${n}`);
      setMsg({ kind: 'ok', text: `Lv${n} 고정 해제` });
      await load();
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setMsg({ kind: 'err', text: d || '해제 실패' });
    }
  };

  return (
    <div className="bg-gray-800/50 rounded p-2">
      <button onClick={() => setOpen(o => !o)} className="text-xs text-sky-300 font-medium">
        {open ? '▼' : '▶'} 🔒 초반 고정 레벨 (1~31)
        {slots.length > 0 && <span className="text-gray-400"> — 고정 {fixedCount}/{editable}</span>}
        <span className="text-gray-500"> · 등록된 레벨은 매 배치 같은 모양으로 생성됨</span>
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          {/* 시드 */}
          <div className="p-2 bg-sky-900/15 rounded flex items-center gap-2 flex-wrap">
            <span className="text-[11px] text-sky-200">기존 배치에서 가져오기</span>
            <select value={seedBatchId} onChange={e => setSeedBatchId(e.target.value)}
              className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-[11px] text-white max-w-[22rem]">
              {batches.length === 0 && <option value="">(31레벨 이상 배치 없음)</option>}
              {batches.map(b => (
                <option key={b.batch_id} value={b.batch_id}>{b.name || b.batch_id}</option>
              ))}
            </select>
            <button onClick={() => seed(false)} disabled={busy || !seedBatchId}
              className="px-2 py-1 rounded text-[11px] bg-sky-700 hover:bg-sky-600 text-white disabled:opacity-50">
              비어있는 슬롯만 채우기
            </button>
            <button onClick={() => seed(true)} disabled={busy || !seedBatchId}
              className="px-2 py-1 rounded text-[11px] bg-amber-700 hover:bg-amber-600 text-white disabled:opacity-50"
              title="이미 고정된 슬롯도 이 배치 내용으로 덮어씁니다">
              전체 덮어쓰기
            </button>
            {msg && (
              <span className={`text-[11px] ${msg.kind === 'ok' ? 'text-emerald-400' : 'text-red-400'}`}>
                {msg.text}
              </span>
            )}
          </div>

          {/* 슬롯 격자 */}
          <div className="grid grid-cols-4 lg:grid-cols-6 gap-1.5">
            {slots.map(s => (
              <div key={s.level}
                className={`p-1.5 rounded border flex gap-1.5 items-center ${
                  s.readonly
                    ? 'border-amber-800/60 bg-amber-900/15'
                    : s.fixed
                      ? 'border-sky-700 bg-sky-900/20'
                      : 'border-gray-700 bg-gray-800/60'
                }`}>
                <MiniStack layers={s.layers} size={42}
                  color={s.readonly ? '#fbbf24' : s.fixed ? '#60a5fa' : '#4b5563'} />
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] text-white">
                    Lv{s.level}
                    {s.readonly && <span className="ml-1 text-[9px] text-amber-400">🔒보스</span>}
                    {!s.readonly && s.fixed && <span className="ml-1 text-[9px] text-sky-400">고정</span>}
                  </div>
                  <div className="text-[10px] text-gray-400">
                    {s.layer_count ? `${s.layer_count}층 · ${s.total_tiles}타일` : '미등록'}
                  </div>
                  {s.readonly ? (
                    <div className="text-[9px] text-amber-500/80 truncate" title={s.reason || ''}>
                      확인 전용
                    </div>
                  ) : (
                    <div className="flex gap-1">
                      <button onClick={() => setEditing(s.level)}
                        className="text-[9px] text-sky-400 hover:text-sky-300">
                        {s.fixed ? '편집' : '그리기'}
                      </button>
                      {s.fixed && (
                        <button onClick={() => unfix(s.level)}
                          className="text-[9px] text-red-400 hover:text-red-300">해제</button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {editing !== null && (
            <FixedLevelEditor
              level={editing}
              onClose={() => setEditing(null)}
              onSaved={() => { void load(); }}
            />
          )}

          <p className="text-[10px] text-gray-500">
            🔒 보스(10·20·30)는 <span className="text-amber-400">보스 템플릿이 정본</span>이라 여기서 수정할 수 없습니다(모양 확인만).
            고정 해제하면 해당 레벨은 다시 매 배치 절차생성됩니다.
          </p>
        </div>
      )}
    </div>
  );
}

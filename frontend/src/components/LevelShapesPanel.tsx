/**
 * [층별 패턴(Level Shapes)] 층마다 고정 모양을 갖는 레벨 스택 라이브러리.
 *
 * 기존 "패턴 디버그" 탭과 저장 모델이 다르다:
 *   패턴 라이브러리 : 한 모양의 **그리드 크기별 변형**({index}_{S}x{S})
 *   층별 패턴(여기) : 레벨 1개 = **층마다 다른 고정 모양**의 스택 전체
 *
 * 원본 타운팝 템플릿(level_templates.json)은 읽기 전용이고, 인게임 규격(최대변 8)으로
 * 크롭한 사본만 여기에 저장된다 → 원본 보존·재크롭 가능.
 *
 * 게임 격자 규칙: 보드 크기 = layer_0.row, 짝수층 S×S / 홀수층 (S-1)×(S-1) 정사각.
 */
import { useEffect, useMemo, useState } from 'react';
import apiClient from '../api/client';
import { useUIStore } from '../stores/uiStore';

interface ShapeSummary {
  id: string;
  name?: string;
  source_template_id: string;
  tier: 'A' | 'B' | 'C';
  orig_max_dim: number;
  max_dim: number;
  target_max_dim: number;
  crop: number[];
  lost_tiles: number;
  loss_pct: number;
  iou: number;
  layer_count: number;
  total_tiles: number;
  gimmicks: string[];
  min_level: number;
  enabled: boolean;
}

type LayerData = { col?: unknown; row?: unknown; tiles?: Record<string, unknown[]> };
type ShapeDetail = ShapeSummary & { level_json: Record<string, unknown> };

const TIER_STYLE: Record<string, string> = {
  A: 'bg-emerald-800 text-emerald-100',
  B: 'bg-amber-800 text-amber-100',
  C: 'bg-red-900 text-red-200',
};

/** 층 스택 미니 겹침뷰 — 홀수층은 반칸 스태거(게임 홀짝 배치). */
function StackPreview({ lj, cell = 7 }: { lj: Record<string, unknown>; cell?: number }) {
  const n = parseInt(String(lj?.layer ?? 0), 10) || 0;
  const layers: Array<{ i: number; col: number; row: number; keys: Set<string> }> = [];
  for (let i = 0; i < n; i++) {
    const L = lj[`layer_${i}`] as LayerData | undefined;
    const t = L?.tiles;
    if (!L || !t) continue;
    const col = parseInt(String(L.col), 10) || 0;
    const row = parseInt(String(L.row), 10) || 0;
    if (!col || !row) continue;
    layers.push({ i, col, row, keys: new Set(Object.keys(t)) });
  }
  if (!layers.length) return <div className="text-[10px] text-gray-600">빈 레벨</div>;
  const base = Math.max(...layers.map(l => l.col));
  const COLORS = ['bg-emerald-500', 'bg-sky-400', 'bg-fuchsia-400', 'bg-amber-400', 'bg-rose-400', 'bg-lime-400'];
  return (
    <div className="relative" style={{ width: base * cell + cell, height: base * cell + cell }}>
      {layers.map(({ i, col, row, keys }, li) => {
        const off = i % 2 === 1 ? cell / 2 : 0;
        return (
          <div key={i} className="absolute" style={{ left: off, top: off, opacity: li === 0 ? 0.95 : 0.5 }}>
            {Array.from({ length: row }, (_, y) => (
              <div key={y} className="flex">
                {Array.from({ length: col }, (_, x) => (
                  <div key={x} style={{ width: cell, height: cell }}
                    className={keys.has(`${x}_${y}`) ? COLORS[i % COLORS.length] : ''} />
                ))}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

export function LevelShapesPanel() {
  const { addNotification } = useUIStore();
  const [shapes, setShapes] = useState<ShapeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [selected, setSelected] = useState<ShapeDetail | null>(null);
  const [tierFilter, setTierFilter] = useState<string>('all');
  const [minLevelFilter, setMinLevelFilter] = useState<string>('all');
  const [enabledOnly, setEnabledOnly] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get('/debug/level-shapes');
      setShapes(r.data?.shapes || []);
    } catch {
      addNotification('error', '층별 패턴 목록 조회 실패');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  const runImport = async () => {
    if (!window.confirm('원본 레벨 템플릿을 스캔해 최대변 8로 크롭 후 편입합니다.\n원본은 수정되지 않습니다. 계속할까요?')) return;
    setImporting(true);
    try {
      const r = await apiClient.post('/debug/level-shapes/import', {
        target_max_dim: 8, iou_gate: 0.85, tiers: ['A', 'B'],
      });
      const s = r.data?.stats || {};
      addNotification('success',
        `임포트 완료 — 저장 ${r.data?.saved}개 (A ${s.A} / B ${s.B} / C ${s.C} 제외, 거부 ${s.rejected})`);
      await load();
    } catch {
      addNotification('error', '임포트 실패');
    } finally {
      setImporting(false);
    }
  };

  const openDetail = async (id: string) => {
    try {
      const r = await apiClient.get(`/debug/level-shapes/${id}`);
      setSelected(r.data);
    } catch {
      addNotification('error', '상세 조회 실패');
    }
  };

  const toggleEnabled = async (s: ShapeSummary) => {
    try {
      await apiClient.patch(`/debug/level-shapes/${s.id}`, { enabled: !s.enabled });
      setShapes(prev => prev.map(x => x.id === s.id ? { ...x, enabled: !x.enabled } : x));
    } catch {
      addNotification('error', '토글 실패');
    }
  };

  const removeShape = async (id: string) => {
    if (!window.confirm('이 크롭본을 삭제합니다. (원본 템플릿은 그대로)')) return;
    try {
      await apiClient.delete(`/debug/level-shapes/${id}`);
      setShapes(prev => prev.filter(x => x.id !== id));
      if (selected?.id === id) setSelected(null);
    } catch {
      addNotification('error', '삭제 실패');
    }
  };

  const minLevels = useMemo(
    () => Array.from(new Set(shapes.map(s => s.min_level))).sort((a, b) => a - b), [shapes]);

  const filtered = useMemo(() => shapes.filter(s =>
    (tierFilter === 'all' || s.tier === tierFilter) &&
    (minLevelFilter === 'all' || String(s.min_level) === minLevelFilter) &&
    (!enabledOnly || s.enabled)
  ), [shapes, tierFilter, minLevelFilter, enabledOnly]);

  return (
    <div className="space-y-4">
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h2 className="text-lg font-semibold text-white">🧩 층별 패턴</h2>
            <p className="text-xs text-gray-400 mt-1">
              층마다 다른 고정 모양을 갖는 레벨 스택. 원본 템플릿(타운팝)을 인게임 규격(최대변 8)으로
              크롭한 <b className="text-gray-300">사본</b>이며 원본은 수정되지 않습니다.
              <span className="text-yellow-400"> min_level</span> = 사용된 기믹의 해금 레벨 → 그 이상 레벨에만 배정 가능.
            </p>
          </div>
          <button onClick={runImport} disabled={importing}
            className="px-3 py-1.5 rounded text-sm bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40">
            {importing ? '임포트 중…' : '📥 원본 스캔·편입'}
          </button>
        </div>

        <div className="flex items-center gap-3 mt-3 flex-wrap text-xs">
          <span className="text-gray-400">총 {shapes.length}개 · 표시 {filtered.length}개</span>
          <select value={tierFilter} onChange={e => setTierFilter(e.target.value)}
            className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white">
            <option value="all">Tier 전체</option>
            <option value="A">A (무손실)</option>
            <option value="B">B (경미손실)</option>
          </select>
          <select value={minLevelFilter} onChange={e => setMinLevelFilter(e.target.value)}
            className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white">
            <option value="all">min_level 전체</option>
            {minLevels.map(v => <option key={v} value={String(v)}>Lv {v}+</option>)}
          </select>
          <label className="flex items-center gap-1 text-gray-300 cursor-pointer">
            <input type="checkbox" checked={enabledOnly} onChange={e => setEnabledOnly(e.target.checked)} />
            사용중만
          </label>
        </div>
      </div>

      {loading ? (
        <div className="text-center text-gray-500 py-10">불러오는 중…</div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {filtered.map(s => (
            <div key={s.id}
              className={`bg-gray-800 rounded-lg p-2 border cursor-pointer transition-colors
                ${selected?.id === s.id ? 'border-indigo-400' : 'border-gray-700 hover:border-gray-500'}
                ${s.enabled ? '' : 'opacity-40'}`}
              onClick={() => void openDetail(s.id)}>
              <div className="flex items-center justify-between mb-1">
                <span className={`text-[10px] px-1 rounded ${TIER_STYLE[s.tier]}`}>{s.tier}</span>
                <span className="text-[10px] text-gray-400">{s.orig_max_dim}→{s.max_dim}</span>
              </div>
              <div className="text-[10px] text-gray-500 truncate" title={s.name}>{s.name}</div>
              <div className="text-[10px] text-gray-400">
                {s.layer_count}층 · {s.total_tiles}타일
                {s.min_level > 0 && <span className="text-yellow-400"> · Lv{s.min_level}+</span>}
              </div>
              {s.lost_tiles > 0 && (
                <div className="text-[10px] text-amber-400">손실 {s.lost_tiles}({s.loss_pct}%) IoU{s.iou}</div>
              )}
              <div className="flex gap-1 mt-1">
                <button onClick={e => { e.stopPropagation(); void toggleEnabled(s); }}
                  className={`flex-1 text-[10px] px-1 py-0.5 rounded ${s.enabled ? 'bg-emerald-700 text-emerald-100' : 'bg-gray-700 text-gray-400'}`}>
                  {s.enabled ? '사용중' : '미사용'}
                </button>
                <button onClick={e => { e.stopPropagation(); void removeShape(s.id); }}
                  className="text-[10px] px-1 py-0.5 rounded bg-gray-700 text-gray-400 hover:bg-red-800 hover:text-red-200">🗑</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {selected && (
        <div className="bg-gray-800 rounded-lg p-4 space-y-3">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-white font-medium">{selected.name}</h3>
              <p className="text-[11px] text-gray-400">
                원본 <code className="text-gray-300">{selected.source_template_id}</code> ·
                Tier {selected.tier} · {selected.orig_max_dim}→{selected.max_dim} ·
                크롭 [{selected.crop.join(',')}] · 손실 {selected.lost_tiles}({selected.loss_pct}%) · IoU {selected.iou}
              </p>
              <p className="text-[11px] text-gray-400">
                기믹: {selected.gimmicks.length ? selected.gimmicks.join(', ') : '없음'} ·
                <span className="text-yellow-400"> 최소 레벨 {selected.min_level}</span>
              </p>
            </div>
            <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-gray-300">✕</button>
          </div>

          <div className="flex items-start gap-6 flex-wrap">
            <div>
              <div className="text-[11px] text-gray-400 mb-1">겹침뷰(홀수층 반칸 스태거)</div>
              <StackPreview lj={selected.level_json} cell={12} />
            </div>
            <div>
              <div className="text-[11px] text-gray-400 mb-1">층별</div>
              <div className="flex gap-3 flex-wrap">
                {Array.from({ length: parseInt(String(selected.level_json?.layer ?? 0), 10) || 0 }, (_, i) => {
                  const L = selected.level_json[`layer_${i}`] as LayerData | undefined;
                  const t = L?.tiles;
                  if (!L || !t) return null;
                  const col = parseInt(String(L.col), 10) || 0;
                  const row = parseInt(String(L.row), 10) || 0;
                  const keys = new Set(Object.keys(t));
                  return (
                    <div key={i} className="text-center">
                      <div className="inline-block border border-gray-700 rounded overflow-hidden">
                        {Array.from({ length: row }, (_, y) => (
                          <div key={y} className="flex">
                            {Array.from({ length: col }, (_, x) => (
                              <div key={x} style={{ width: 10, height: 10 }}
                                className={keys.has(`${x}_${y}`) ? 'bg-emerald-500' : 'bg-gray-800'} />
                            ))}
                          </div>
                        ))}
                      </div>
                      <div className="text-[9px] text-gray-500 mt-0.5">L{i} {col}×{row} · {keys.size}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default LevelShapesPanel;

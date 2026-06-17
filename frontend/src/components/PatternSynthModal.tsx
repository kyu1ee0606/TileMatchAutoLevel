import { useCallback, useState } from 'react';
import apiClient from '../api/client';

// [v16 🅑] 절차적 패턴 '컨셉 묶음' 생성 + 큐레이션 모달
// 한 컨셉 = (전략·대칭·채움률 고정)을 여러 그리드 사이즈로 렌더한 변형 묶음.
// 레벨은 레이어마다 grid/grid+1 사이즈를 번갈아 쓰므로 한 인덱스에 모든 사이즈 변형이 필요.
// 백엔드 /patterns/synthesize 로 ÷3-보장 컨셉을 받아 사이즈별 미리보기로 보여주고,
// 채택분만 /patterns/accept 로 묶음 통째 custom_patterns.json 에 저장.

interface SynthVariant {
  grid_size: number;
  positions: string[];
  count: number;
  grid: number[][];
  score: number;
  breakdown: {
    symmetry: number;
    connectivity: number;
    solidity: number;
    single_holes: number;
    fill_rate: number;
    components: number;
  };
}

interface SynthConcept {
  symmetry: string;
  strategy: string;
  score: number;
  sizes: number[];
  variants: SynthVariant[];
}

interface Props {
  onClose: () => void;
  onAccepted: () => void; // 저장 후 부모 패턴목록 새로고침
}

const SYMMETRY_OPTIONS = [
  { value: '', label: '자동(혼합)' },
  { value: 'both', label: '상하좌우 대칭' },
  { value: 'quad', label: '4방 회전' },
  { value: 'h', label: '좌우 대칭' },
  { value: 'v', label: '상하 대칭' },
  { value: 'rot180', label: '점대칭(180°)' },
  { value: 'none', label: '비대칭' },
];

function VariantPreview({ v }: { v: SynthVariant }) {
  return (
    <div className="flex flex-col items-center">
      <div className="w-14 h-14">
        {v.grid.map((row, y) => (
          <div key={y} className="flex">
            {row.map((cell, x) => (
              <div key={x} className={`flex-1 aspect-square ${cell ? 'bg-blue-500' : 'bg-gray-800'}`} style={{ margin: '0.3px' }} />
            ))}
          </div>
        ))}
      </div>
      <div className="text-[8px] text-gray-500 mt-0.5">{v.grid_size}×{v.grid_size}·{v.count}t</div>
    </div>
  );
}

export function PatternSynthModal({ onClose, onAccepted }: Props) {
  const [maxGrid, setMaxGrid] = useState(7);
  const [minGrid, setMinGrid] = useState(4);
  const [count, setCount] = useState(12);
  const [symmetry, setSymmetry] = useState('');
  const [fillMin, setFillMin] = useState(0.45);
  const [fillMax, setFillMax] = useState(0.85);
  const [concepts, setConcepts] = useState<SynthConcept[]>([]);
  const [loading, setLoading] = useState(false);
  const [accepted, setAccepted] = useState<Set<number>>(new Set()); // 채택된 컨셉 인덱스
  const [acceptedCount, setAcceptedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    setConcepts([]);
    setAccepted(new Set());
    try {
      const res = await apiClient.post('/patterns/synthesize', {
        max_grid: maxGrid,
        min_grid: minGrid,
        count,
        symmetry: symmetry || null,
        fill_min: fillMin,
        fill_max: fillMax,
        seed: Math.floor(Math.random() * 1_000_000),
      });
      setConcepts(res.data.concepts || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : '생성 실패');
    } finally {
      setLoading(false);
    }
  }, [maxGrid, minGrid, count, symmetry, fillMin, fillMax]);

  const acceptOne = useCallback(async (concept: SynthConcept, idx: number) => {
    if (accepted.has(idx)) return;
    try {
      await apiClient.post('/patterns/accept', {
        variants: concept.variants.map(v => ({ grid_size: v.grid_size, positions: v.positions })),
        name: `synth_${concept.strategy}_${concept.symmetry}`,
      });
      setAccepted(prev => new Set(prev).add(idx));
      setAcceptedCount(c => c + 1);
      onAccepted();
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패');
    }
  }, [accepted, onAccepted]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-lg w-full max-w-5xl max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}>
        {/* 헤더 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
          <div className="text-sm font-bold text-white">
            🧩 절차적 패턴 컨셉 생성 <span className="text-[10px] text-gray-400 font-normal">한 컨셉=모든 사이즈 묶음 · ÷3 보장 · 채택 시 인덱스 1개로 저장</span>
          </div>
          <div className="flex items-center gap-3">
            {acceptedCount > 0 && <span className="text-[11px] text-green-400">채택 {acceptedCount}개 저장됨</span>}
            <button onClick={onClose} className="text-gray-400 hover:text-white text-lg leading-none">✕</button>
          </div>
        </div>

        {/* 컨트롤 */}
        <div className="px-4 py-3 border-b border-gray-700 flex flex-wrap items-end gap-3 text-[11px]">
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-400">최소 그리드</span>
            <select value={minGrid} onChange={e => { const v = +e.target.value; setMinGrid(v); if (maxGrid < v) setMaxGrid(v); }}
              className="px-2 py-1 rounded bg-gray-800 text-white border border-gray-700">
              {[4, 5, 6, 7].map(s => <option key={s} value={s}>{s}×{s}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-400">최대 그리드</span>
            <select value={maxGrid} onChange={e => setMaxGrid(Math.max(+e.target.value, minGrid))}
              className="px-2 py-1 rounded bg-gray-800 text-white border border-gray-700">
              {[4, 5, 6, 7].filter(s => s >= minGrid).map(s => <option key={s} value={s}>{s}×{s}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-400">대칭</span>
            <select value={symmetry} onChange={e => setSymmetry(e.target.value)}
              className="px-2 py-1 rounded bg-gray-800 text-white border border-gray-700">
              {SYMMETRY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-400">컨셉 수</span>
            <input type="number" min={1} max={48} value={count} onChange={e => setCount(Math.max(1, Math.min(48, +e.target.value)))}
              className="w-16 px-2 py-1 rounded bg-gray-800 text-white border border-gray-700" />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-400">채움률 {Math.round(fillMin * 100)}~{Math.round(fillMax * 100)}%</span>
            <div className="flex items-center gap-1">
              <input type="range" min={0.2} max={0.9} step={0.05} value={fillMin}
                onChange={e => setFillMin(Math.min(+e.target.value, fillMax))} className="w-20" />
              <input type="range" min={0.3} max={1.0} step={0.05} value={fillMax}
                onChange={e => setFillMax(Math.max(+e.target.value, fillMin))} className="w-20" />
            </div>
          </label>
          <button onClick={generate} disabled={loading}
            className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-bold">
            {loading ? '생성 중…' : '🎲 생성'}
          </button>
        </div>

        {error && <div className="px-4 py-2 text-[11px] text-red-400 bg-red-900/20">{error}</div>}

        {/* 컨셉 목록 (각 컨셉 = 사이즈별 변형 묶음) */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {concepts.length === 0 && !loading && (
            <div className="text-center text-gray-500 text-xs py-12">옵션을 정하고 [생성]을 누르세요. 각 컨셉은 모든 사이즈 변형을 묶어 ÷3을 보장합니다.</div>
          )}
          {concepts.map((c, idx) => {
            const isAccepted = accepted.has(idx);
            return (
              <div key={idx} className={`rounded border p-3 flex items-center gap-4 ${isAccepted ? 'border-green-500 bg-green-900/20' : 'border-gray-700 bg-gray-800/40'}`}>
                <div className="flex-1 flex items-end gap-3 overflow-x-auto">
                  {c.variants.map((v, vi) => <VariantPreview key={vi} v={v} />)}
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-[10px] text-gray-300">{c.strategy} · {c.symmetry}</div>
                  <div className="text-[9px] text-gray-500">score {c.score} · {c.sizes.length}개 사이즈</div>
                  <button onClick={() => acceptOne(c, idx)} disabled={isAccepted}
                    className={`mt-1 px-3 py-1 rounded text-[10px] font-bold ${
                      isAccepted ? 'bg-green-700 text-white cursor-default' : 'bg-gray-700 hover:bg-indigo-600 text-gray-200'
                    }`}>
                    {isAccepted ? '✓ 채택됨' : '채택(묶음)'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

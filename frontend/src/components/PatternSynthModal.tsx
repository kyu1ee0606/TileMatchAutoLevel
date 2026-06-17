import { useCallback, useEffect, useState } from 'react';
import apiClient from '../api/client';
import { renderLevelCanvasPreview } from '../utils/levelPreview';
import type { LevelJSON, LevelLayer } from '../types';

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

// 단일 사이즈 변형을 실제 타일 렌더러로 미리보기(단색 더미 아님).
function VariantPreview({ v }: { v: SynthVariant }) {
  const [url, setUrl] = useState<string | null>(null);
  const key = `${v.grid_size}:${v.positions.length}`;
  useEffect(() => {
    let alive = true;
    setUrl(null);
    renderLevelCanvasPreview(conceptToLevelJSON([v]), 168).then(u => { if (alive) setUrl(u); }).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return (
    <div className="flex flex-col items-center">
      <div className="w-14 h-14 rounded bg-gray-900 overflow-hidden flex items-center justify-center">
        {url ? <img src={url} alt="" style={{ width: 56, height: 56, objectFit: 'contain' }} />
             : <span className="text-[7px] text-gray-600">…</span>}
      </div>
      <div className="text-[8px] text-gray-500 mt-0.5">{v.grid_size}×{v.grid_size}·{v.count}t</div>
    </div>
  );
}

// 컨셉의 모든 사이즈 변형을 레이어로 쌓아 합성한 '레벨 JSON'을 만든다.
// 큰 사이즈=하단(layer_0), 작은 사이즈=상단으로 각 변형을 공통 프레임 중앙에 배치하고,
// 실제 타일 타입(t1..6 순환)을 부여 → 프로덕션 탭과 동일한 렌더러로 실제 타일 이미지 렌더.
function conceptToLevelJSON(variants: SynthVariant[], useTileCount = 6): LevelJSON {
  const ordered = [...variants].sort((a, b) => b.grid_size - a.grid_size); // 큰→작은 = 하단→상단
  const G = ordered.length ? ordered[0].grid_size : 7;
  const lv: LevelJSON = { layer: ordered.length, useTileCount };
  ordered.forEach((v, li) => {
    const g = v.grid_size;
    const off = Math.floor((G - g) / 2); // 공통 프레임 중앙정렬
    const tiles: LevelLayer['tiles'] = {};
    v.positions.forEach((p, ti) => {
      const [x, y] = p.split('_').map(Number);
      const cx = x + off, cy = y + off;
      const t = `t${(ti % useTileCount) + 1}`; // 실제 타일 타입 순환(컬러풀)
      tiles[`${cx}_${cy}`] = [t, ''];
    });
    // 렌더러는 짝수 레이어 기준 프레임 + 홀수 레이어 0.5 오프셋 → col/row는 표시용
    (lv as unknown as Record<string, LevelLayer>)[`layer_${li}`] = {
      col: String(G), row: String(G), num: String(v.positions.length), tiles,
    };
  });
  return lv;
}

// 프로덕션 탭과 동일한 실제 타일 렌더러로 컨셉 합성 미리보기(실제 타일 이미지).
function LevelLikePreview({ variants, size = 88 }: { variants: SynthVariant[]; size?: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const key = variants.map(v => `${v.grid_size}:${v.positions.length}`).join('|');
  useEffect(() => {
    let alive = true;
    setUrl(null);
    const lv = conceptToLevelJSON(variants);
    renderLevelCanvasPreview(lv, size * 3).then(u => { if (alive) setUrl(u); }).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, size]);
  return (
    <div className="flex flex-col items-center">
      <div className="rounded bg-gray-900 overflow-hidden flex items-center justify-center"
        style={{ width: size, height: size }}>
        {url
          ? <img src={url} alt="concept preview" style={{ width: size, height: size, objectFit: 'contain' }} />
          : <span className="text-[8px] text-gray-600">렌더…</span>}
      </div>
      <div className="text-[8px] text-gray-400 mt-0.5">쌓임(실제타일)</div>
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
  const [autoCount, setAutoCount] = useState(8);   // AI 자동 채택 개수
  const [autoLoading, setAutoLoading] = useState(false);
  const [autoSaved, setAutoSaved] = useState<SynthConcept[]>([]); // 자동 저장된 컨셉(미리보기)

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

  // AI 자동 큐레이션: 대량 생성 → 비주얼 상위 N개 자동 저장
  const autoGenerate = useCallback(async () => {
    setAutoLoading(true);
    setError(null);
    setAutoSaved([]);
    try {
      const res = await apiClient.post('/patterns/auto-generate', {
        count: autoCount,
        max_grid: maxGrid,
        min_grid: minGrid,
        symmetry: symmetry || null,
        fill_min: fillMin,
        fill_max: fillMax,
        seed: Math.floor(Math.random() * 1_000_000),
      });
      // saved.patterns[].variants 는 SynthConcept.variants 와 호환
      const saved = (res.data.patterns || []).map((p: { strategy: string; symmetry: string; score: number; sizes: number[]; variants: SynthVariant[] }) => ({
        strategy: p.strategy, symmetry: p.symmetry, score: p.score, sizes: p.sizes, variants: p.variants,
      })) as SynthConcept[];
      setAutoSaved(saved);
      if (saved.length > 0) onAccepted(); // 라이브러리 새로고침
    } catch (e) {
      setError(e instanceof Error ? e.message : 'AI 자동 생성 실패');
    } finally {
      setAutoLoading(false);
    }
  }, [autoCount, maxGrid, minGrid, symmetry, fillMin, fillMax, onAccepted]);

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
          <button onClick={generate} disabled={loading || autoLoading}
            className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-bold">
            {loading ? '생성 중…' : '🎲 생성(수동채택)'}
          </button>
          {/* AI 자동 큐레이션 */}
          <div className="flex items-end gap-1 pl-3 ml-1 border-l border-gray-700">
            <label className="flex flex-col gap-0.5">
              <span className="text-gray-400">AI 자동 개수</span>
              <input type="number" min={1} max={48} value={autoCount} onChange={e => setAutoCount(Math.max(1, Math.min(48, +e.target.value)))}
                className="w-16 px-2 py-1 rounded bg-gray-800 text-white border border-gray-700" />
            </label>
            <button onClick={autoGenerate} disabled={loading || autoLoading}
              title="대량 생성 후 비주얼 점수 상위 N개를 자동 채택·저장"
              className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-bold">
              {autoLoading ? 'AI 생성 중…' : '✨ AI 자동 N개 저장'}
            </button>
          </div>
        </div>

        {error && <div className="px-4 py-2 text-[11px] text-red-400 bg-red-900/20">{error}</div>}

        {autoSaved.length > 0 && (
          <div className="px-4 py-2 border-b border-emerald-800 bg-emerald-900/20">
            <div className="text-[11px] text-emerald-300 mb-1.5">✨ AI가 비주얼 상위 {autoSaved.length}개를 자동 저장했습니다 (라이브러리에 추가됨)</div>
            <div className="flex flex-wrap gap-2">
              {autoSaved.map((c, i) => (
                <div key={i} className="rounded border border-emerald-700 bg-gray-800/40 p-1.5 flex flex-col items-center">
                  <LevelLikePreview variants={c.variants} size={72} />
                  <div className="text-[8px] text-gray-400 mt-0.5">{c.strategy}·{c.symmetry} · {c.score}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 컨셉 목록 (각 컨셉 = 사이즈별 변형 묶음) */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {concepts.length === 0 && !loading && (
            <div className="text-center text-gray-500 text-xs py-12">옵션을 정하고 [생성]을 누르세요. 각 컨셉은 모든 사이즈 변형을 묶어 ÷3을 보장합니다.</div>
          )}
          {concepts.map((c, idx) => {
            const isAccepted = accepted.has(idx);
            return (
              <div key={idx} className={`rounded border p-3 flex items-center gap-4 ${isAccepted ? 'border-green-500 bg-green-900/20' : 'border-gray-700 bg-gray-800/40'}`}>
                {/* 합성(모든 사이즈 쌓음) 미리보기 — 실제 타일 렌더(프로덕션 동일) */}
                <div className="shrink-0 pr-3 border-r border-gray-700">
                  <LevelLikePreview variants={c.variants} size={96} />
                </div>
                {/* 사이즈별 개별 변형 */}
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

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

// [프로덕션 스타일] 실제 레벨처럼 홀짝 교대(짝수층=7·홀수층=6) 6·7 변형만 4층 스택 → 인게임 룩.
function conceptToLevelJSONProduction(variants: SynthVariant[], layers = 4, useTileCount = 6): LevelJSON {
  const byCol = new Map(variants.map(v => [v.grid_size, v]));
  const v7 = byCol.get(7) || variants.find(v => v.grid_size >= 6);
  const v6 = byCol.get(6) || v7;
  if (!v7 || !v6) return conceptToLevelJSON(variants);
  const lv: LevelJSON = { layer: layers, useTileCount };
  for (let li = 0; li < layers; li++) {
    const col = li % 2 === 0 ? 7 : 6;                 // 짝수층 7, 홀수층 6 (홀짝 규칙)
    const v = col === 7 ? v7 : v6;
    const tiles: LevelLayer['tiles'] = {};
    v.positions.forEach((p, ti) => {
      const [x, y] = p.split('_').map(Number);
      if (x >= col || y >= col) return;               // col 범위 밖 방어
      tiles[`${x}_${y}`] = [`t${(ti % useTileCount) + 1}`, ''];
    });
    (lv as unknown as Record<string, LevelLayer>)[`layer_${li}`] = {
      col: String(col), row: String(col), num: String(Object.keys(tiles).length), tiles,
    };
  }
  return lv;
}

// 프로덕션 탭과 동일한 실제 타일 렌더러로 컨셉 합성 미리보기(실제 타일 이미지).
// mode: 'stack'=모든 크기(4~7) 쌓음 / 'prod'=프로덕션 홀짝(6·7 교대) 실제 룩.
function LevelLikePreview({ variants, size = 88, mode = 'stack' }: { variants: SynthVariant[]; size?: number; mode?: 'stack' | 'prod' }) {
  const [url, setUrl] = useState<string | null>(null);
  const key = mode + '|' + variants.map(v => `${v.grid_size}:${v.positions.length}`).join('|');
  useEffect(() => {
    let alive = true;
    setUrl(null);
    const lv = mode === 'prod' ? conceptToLevelJSONProduction(variants) : conceptToLevelJSON(variants);
    renderLevelCanvasPreview(lv, size * 3).then(u => { if (alive) setUrl(u); }).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, size]);
  return (
    <div className="flex flex-col items-center">
      <div className={`rounded bg-gray-900 overflow-hidden flex items-center justify-center ${mode === 'prod' ? 'ring-1 ring-emerald-600' : ''}`}
        style={{ width: size, height: size }}>
        {url
          ? <img src={url} alt="concept preview" style={{ width: size, height: size, objectFit: 'contain' }} />
          : <span className="text-[8px] text-gray-600">렌더…</span>}
      </div>
      <div className={`text-[8px] mt-0.5 ${mode === 'prod' ? 'text-emerald-400' : 'text-gray-400'}`}>
        {mode === 'prod' ? '프로덕션(6·7홀짝)' : '전체쌓임(4~7)'}
      </div>
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
  const [cellularOnly, setCellularOnly] = useState(false); // 순수 셀룰러 스프라이트 전용
  const [diversity, setDiversity] = useState(50);          // 랜덤성 0=정돈~100=최대랜덤
  // [A] 씨앗 모양: 그린 모양 기반으로 변주 생성
  const [useSeed, setUseSeed] = useState(false);
  const [seedStrength, setSeedStrength] = useState(50); // 씨앗 변형 강도 0=그대로~100=크게변형
  const SEED_SIZE = 7;
  const [seedGrid, setSeedGrid] = useState<boolean[][]>(
    () => Array.from({ length: SEED_SIZE }, () => Array(SEED_SIZE).fill(false)));
  const [seedPainting, setSeedPainting] = useState<boolean | null>(null);
  const seedPositions = (): string[] => {
    const out: string[] = [];
    seedGrid.forEach((row, y) => row.forEach((c, x) => { if (c) out.push(`${x}_${y}`); }));
    return out;
  };
  const seedCount = seedGrid.flat().filter(Boolean).length;
  // 랜덤 씨앗: 좌우대칭 + 중앙가중(연결된 덩어리풍) 랜덤 모양. 클릭마다 다른 모양.
  const randomSeed = () => {
    const g = SEED_SIZE;
    const c = (g - 1) / 2;
    const half = Math.floor(g / 2);
    const bias = 0.55 + Math.random() * 0.4;      // 전체 밀도
    const spread = 0.5 + Math.random() * 0.4;     // 중앙집중도(낮을수록 중앙쏠림)
    let grid = Array.from({ length: g }, () => Array(g).fill(false));
    for (let y = 0; y < g; y++) for (let x = 0; x <= half; x++) {
      const d = Math.max(Math.abs(x - c), Math.abs(y - c)) / c;  // 0(중앙)~1(모서리)
      const p = bias * (1 - d * (1 - spread));
      if (Math.random() < p) { grid[y][x] = true; grid[y][g - 1 - x] = true; }
    }
    // 최소 6칸 보장: 부족하면 중앙 3×3 채움
    if (grid.flat().filter(Boolean).length < 6) {
      grid = Array.from({ length: g }, () => Array(g).fill(false));
      for (let y = -1; y <= 1; y++) for (let x = -1; x <= 1; x++) grid[c + y][c + x] = true;
    }
    setSeedGrid(grid);
  };

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
        cellular_only: cellularOnly,
        diversity: diversity / 100,
        ...(useSeed && seedCount >= 4 ? { seed_positions: seedPositions(), seed_grid: SEED_SIZE, seed_strength: seedStrength / 100 } : {}),
      });
      setConcepts(res.data.concepts || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : '생성 실패');
    } finally {
      setLoading(false);
    }
  }, [maxGrid, minGrid, count, symmetry, fillMin, fillMax, cellularOnly, diversity, useSeed, seedGrid, seedStrength]);

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
        diversity: diversity / 100,
        ...(useSeed && seedCount >= 4 ? { seed_positions: seedPositions(), seed_grid: SEED_SIZE, seed_strength: seedStrength / 100 } : {}),
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
  }, [autoCount, maxGrid, minGrid, symmetry, fillMin, fillMax, onAccepted, diversity, useSeed, seedGrid, seedStrength]);

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
          <label className="flex flex-col gap-0.5" title="0=정돈(사람템플릿 위주·고품질·대칭) ~ 100=최대랜덤(유기적·셀룰러·실험적). 높일수록 특이하고 다양하지만 품질 편차 커짐.">
            <span className="text-gray-400">랜덤성 {diversity} <span className="text-gray-600">{diversity <= 30 ? '(정돈)' : diversity >= 70 ? '(실험)' : '(균형)'}</span></span>
            <input type="range" min={0} max={100} step={5} value={diversity}
              onChange={e => setDiversity(+e.target.value)} className="w-28 accent-fuchsia-500" />
          </label>
          <label className="flex items-center gap-1 cursor-pointer select-none" title="템플릿·모티프 배제, 순수 셀룰러 스프라이트(Space Invaders식)만 생성">
            <input type="checkbox" checked={cellularOnly} onChange={e => setCellularOnly(e.target.checked)} />
            <span className="text-gray-300">🛸 셀룰러 전용</span>
          </label>
          <label className="flex items-center gap-1 cursor-pointer select-none" title="아래 그린 씨앗 모양을 밑그림으로 회전·변주·재조합한 변형만 생성(찍은 모양의 변주 묶음)">
            <input type="checkbox" checked={useSeed} onChange={e => setUseSeed(e.target.checked)} />
            <span className="text-fuchsia-300">🌱 씨앗 모양 기반</span>
          </label>
        </div>

        {/* [A] 씨앗 모양 그리기 (7×7) — useSeed 시 이 모양 기반 변주 생성 */}
        {useSeed && (
          <div className="flex items-center gap-3 mb-2 p-2 bg-fuchsia-900/15 rounded"
            onMouseLeave={() => setSeedPainting(null)} onMouseUp={() => setSeedPainting(null)}>
            <div className="text-[11px] text-fuchsia-200">씨앗 그리기<br /><span className="text-gray-400">{seedCount}칸</span></div>
            <div className="inline-block border border-fuchsia-800 rounded select-none">
              {seedGrid.map((row, y) => (
                <div key={y} className="flex">
                  {row.map((cell, x) => (
                    <div key={x}
                      className={`w-6 h-6 border border-gray-900/50 cursor-pointer ${cell ? 'bg-fuchsia-500' : 'bg-gray-800 hover:bg-gray-700'}`}
                      onMouseDown={() => { const nv = !cell; setSeedPainting(nv); setSeedGrid(g => g.map((r, yy) => yy === y ? r.map((c, xx) => xx === x ? nv : c) : r)); }}
                      onMouseEnter={(e) => { if (seedPainting !== null && e.buttons === 1) setSeedGrid(g => g.map((r, yy) => yy === y ? r.map((c, xx) => xx === x ? seedPainting : c) : r)); else if (e.buttons !== 1) setSeedPainting(null); }}
                    />
                  ))}
                </div>
              ))}
            </div>
            <button onClick={randomSeed}
              className="px-2 py-1 rounded text-[10px] bg-fuchsia-700 hover:bg-fuchsia-600 text-white" title="좌우대칭 랜덤 모양 자동 그리기(클릭마다 다름)">🎲 랜덤</button>
            <button onClick={() => setSeedGrid(Array.from({ length: SEED_SIZE }, () => Array(SEED_SIZE).fill(false)))}
              className="px-2 py-1 rounded text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-200">비움</button>
            {seedCount < 4 && <span className="text-[10px] text-yellow-400">최소 4칸 필요</span>}
            <label className="flex flex-col gap-0.5 ml-2" title="0=씨앗 거의 그대로(회전만) ~ 100=씨앗 바탕 크게 변형(변주·재조합). 씨앗을 뼈대로 다른 크기·변형을 얼마나 벌릴지.">
              <span className="text-[10px] text-fuchsia-200">변형 강도 {seedStrength} <span className="text-gray-500">{seedStrength <= 30 ? '(그대로)' : seedStrength >= 70 ? '(크게)' : '(적당)'}</span></span>
              <input type="range" min={0} max={100} step={5} value={seedStrength}
                onChange={e => setSeedStrength(+e.target.value)} className="w-28 accent-fuchsia-500" />
            </label>
          </div>
        )}
        <div className="px-4 pb-3 flex flex-wrap items-center gap-3 text-[11px]">
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
                  <div className="flex gap-1.5">
                    <LevelLikePreview variants={c.variants} size={72} mode="stack" />
                    <LevelLikePreview variants={c.variants} size={72} mode="prod" />
                  </div>
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
                {/* 두 프리뷰: 전체쌓임(4~7) + 프로덕션(6·7 홀짝) — 실제 인게임 룩 비교 */}
                <div className="shrink-0 pr-3 border-r border-gray-700 flex gap-2">
                  <LevelLikePreview variants={c.variants} size={96} mode="stack" />
                  <LevelLikePreview variants={c.variants} size={96} mode="prod" />
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

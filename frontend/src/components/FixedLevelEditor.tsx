/**
 * [초반 고정 레벨 에디터] 1~31 레벨을 층 단위로 직접 그려 고정 등록한다.
 *
 * 게임 격자 규칙을 UI 가 강제한다:
 *   - 층 헤더는 **짝홀 교대** — 짝수층 S, 홀수층 S-1 (S = 바닥 격자)
 *   - 선언 격자 최대 8 (디바이스 가독성)
 *   - 매칭 타입은 ÷3 (저장 전 검증기가 판정, 마무리 파이프라인이 ±2 보정)
 *
 * 기믹은 **해당 레벨에서 해금된 것만** 팔레트에 뜬다(조기 등장 방지).
 * 보스 슬롯(10·20·30)은 애초에 이 에디터로 열리지 않는다(보스 템플릿이 정본).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import apiClient from '../api/client';

/** 기믹 해금 레벨 — 백엔드 PROFESSIONAL_GIMMICK_UNLOCK 미러. 팔레트 게이팅에만 쓴다. */
const UNLOCK: Record<string, number> = {
  craft: 11, stack: 21, ice: 31, link: 51, chain: 81, key: 111, grass: 151,
  unknown: 191, curtain: 241, bomb: 291, frog: 391, teleport: 441,
};

const COLORS = ['t0', 't1', 't2', 't3', 't4', 't5', 't6', 't7', 't8'] as const;
const COLOR_HEX: Record<string, string> = {
  t0: '#64748b', t1: '#ef4444', t2: '#f59e0b', t3: '#eab308', t4: '#22c55e',
  t5: '#14b8a6', t6: '#3b82f6', t7: '#a855f7', t8: '#ec4899',
};

type Tile = [string, string] | [string, string, [number, string?]];
type Layers = Record<number, Record<string, Tile>>;

interface Issue { kind: string; msg: string }

interface Props {
  level: number;
  onClose: () => void;
  onSaved: () => void;
}

export function FixedLevelEditor({ level, onClose, onSaved }: Props) {
  const [base, setBase] = useState(6);          // 바닥(짝수층) 격자 S
  const [layerCount, setLayerCount] = useState(2);
  const [active, setActive] = useState(0);      // 편집 중인 층
  const [layers, setLayers] = useState<Layers>({ 0: {}, 1: {} });
  const [paintColor, setPaintColor] = useState<string>('t0');
  const [paintAttr, setPaintAttr] = useState<string>('');       // '' = 속성 없음
  const [paintContainer, setPaintContainer] = useState<string>(''); // '' = 일반 타일
  const [drag, setDrag] = useState<'add' | 'del' | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [summary, setSummary] = useState<{ layer_count: number; total_tiles: number; per_layer: number[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  /** 층 i 의 헤더 격자 — 짝수층 S, 홀수층 S-1 (게임 규칙, UI 에서 강제) */
  const colOf = useCallback((i: number) => (i % 2 === 0 ? base : base - 1), [base]);

  const unlocked = useMemo(
    () => Object.entries(UNLOCK).filter(([, lv]) => level >= lv).map(([g]) => g),
    [level]);
  const attrPalette = useMemo(
    () => unlocked.filter(g => !['craft', 'stack', 'key'].includes(g)), [unlocked]);
  const containerPalette = useMemo(() => {
    const out: string[] = [];
    if (unlocked.includes('craft')) out.push('craft_s', 'craft_n', 'craft_e', 'craft_w');
    if (unlocked.includes('stack')) out.push('stack_s', 'stack_n', 'stack_e', 'stack_w');
    return out;
  }, [unlocked]);

  // 기존 고정본이 있으면 불러오기
  useEffect(() => {
    let alive = true;
    apiClient.get(`/debug/fixed-levels/${level}`)
      .then(r => {
        if (!alive) return;
        const lj = r.data?.level_json || {};
        const n = Number(lj.layer) || 1;
        const nl: Layers = {};
        let b = 0;
        for (let i = 0; i < n; i++) {
          const ld = lj[`layer_${i}`] || {};
          nl[i] = { ...(ld.tiles || {}) };
          const c = Number(ld.col) || 0;
          if (i % 2 === 0) b = Math.max(b, c);
        }
        setBase(b || 6);
        setLayerCount(n);
        setLayers(nl);
        setActive(0);
        setMsg({ kind: 'ok', text: `Lv${level} 기존 고정본 불러옴` });
      })
      .catch(() => { /* 미등록이면 빈 상태로 시작 */ });
    return () => { alive = false; };
  }, [level]);

  /** 격자를 줄이면 범위 밖 셀을 버린다(안쪽 모양은 유지) */
  useEffect(() => {
    setLayers(prev => {
      const next: Layers = {};
      for (let i = 0; i < layerCount; i++) {
        const c = colOf(i);
        const src = prev[i] || {};
        next[i] = Object.fromEntries(Object.entries(src).filter(([k]) => {
          const [x, y] = k.split('_').map(Number);
          return x < c && y < c;
        }));
      }
      return next;
    });
    setActive(a => Math.min(a, layerCount - 1));
  }, [base, layerCount, colOf]);

  const buildJson = useCallback(() => {
    const lj: Record<string, unknown> = {
      layer: layerCount, row: String(base), col: String(base),
      useTileCount: 6, randSeed: 0, autoCollectCount: 0,
    };
    for (let i = 0; i < layerCount; i++) {
      const c = colOf(i);
      const tiles = layers[i] || {};
      lj[`layer_${i}`] = { col: String(c), row: String(c), num: String(Object.keys(tiles).length), tiles };
    }
    return lj;
  }, [layerCount, base, layers, colOf]);

  // 실시간 검증(디바운스) — 저장 전에 규칙 위반을 즉시 보여준다
  useEffect(() => {
    const total = Object.values(layers).reduce((s, t) => s + Object.keys(t || {}).length, 0);
    if (total === 0) { setIssues([]); setSummary(null); return; }
    let alive = true;
    const t = setTimeout(() => {
      apiClient.post(`/debug/fixed-levels/${level}/validate`, { level_json: buildJson(), note: '' })
        .then(r => { if (alive) { setIssues(r.data?.issues || []); setSummary(r.data?.summary || null); } })
        .catch(() => { if (alive) setIssues([{ kind: 'net', msg: '검증 요청 실패' }]); });
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [layers, layerCount, base, level, buildJson]);

  const put = (x: number, y: number, mode: 'add' | 'del') => {
    const k = `${x}_${y}`;
    setLayers(prev => {
      const cur = { ...(prev[active] || {}) };
      if (mode === 'del') delete cur[k];
      else if (paintContainer) cur[k] = [paintContainer, paintAttr, [3]] as Tile;
      else cur[k] = [paintColor, paintAttr] as Tile;
      return { ...prev, [active]: cur };
    });
  };

  const fillAll = () => {
    const c = colOf(active);
    const cur: Record<string, Tile> = {};
    for (let y = 0; y < c; y++) for (let x = 0; x < c; x++) cur[`${x}_${y}`] = [paintColor, ''] as Tile;
    setLayers(prev => ({ ...prev, [active]: cur }));
  };
  const clearLayer = () => setLayers(prev => ({ ...prev, [active]: {} }));

  /** 색 균등 재배정 — ÷3 을 맞추기 가장 쉬운 방법(전 층 통합해 순환 배분) */
  const autoColors = (v: number) => {
    const all: Array<[number, string]> = [];
    for (let i = 0; i < layerCount; i++)
      for (const k of Object.keys(layers[i] || {})) {
        const t = (layers[i] || {})[k];
        if (String(t[0]).startsWith('craft_') || String(t[0]).startsWith('stack_')) continue;
        all.push([i, k]);
      }
    setLayers(prev => {
      const next: Layers = { ...prev };
      all.forEach(([i, k], idx) => {
        const cur = { ...(next[i] || {}) };
        const t = cur[k];
        cur[k] = [`t${(Math.floor(idx / 3) % v) + 1}`, t[1] || ''] as Tile;
        next[i] = cur;
      });
      return next;
    });
  };

  const save = async () => {
    setBusy(true);
    try {
      await apiClient.put(`/debug/fixed-levels/${level}`, { level_json: buildJson(), note: '에디터' });
      setMsg({ kind: 'ok', text: `Lv${level} 고정 저장 완료` });
      onSaved();
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setMsg({ kind: 'err', text: d || '저장 실패' });
    } finally { setBusy(false); }
  };

  const c = colOf(active);
  const cells = layers[active] || {};
  const blocking = issues.filter(i => ['board', 'header_oob', 'div3', 'oversized_grid', 'pipeline'].includes(i.kind));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-gray-800 border border-gray-600 rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto"
        onMouseUp={() => setDrag(null)} onMouseLeave={() => setDrag(null)}>
        <div className="p-3 border-b border-gray-700 flex items-center gap-2">
          <h3 className="text-white font-semibold">🔒 Lv{level} 고정 레벨 편집</h3>
          <span className="text-[11px] text-gray-400">
            해금 기믹: {unlocked.length ? unlocked.join(', ') : '없음'}
          </span>
          <button onClick={onClose} className="ml-auto px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-200">닫기</button>
        </div>

        <div className="p-3 space-y-3">
          {/* 격자/층 */}
          <div className="flex items-center gap-3 flex-wrap text-[11px] text-gray-300">
            <label className="flex items-center gap-1">
              바닥 격자 S
              <input type="number" min={3} max={8} value={base}
                onChange={e => setBase(Math.max(3, Math.min(8, parseInt(e.target.value) || 3)))}
                className="w-14 px-1 py-0.5 bg-gray-700 border border-gray-600 rounded text-white" />
            </label>
            <label className="flex items-center gap-1">
              층수
              <input type="number" min={1} max={8} value={layerCount}
                onChange={e => setLayerCount(Math.max(1, Math.min(8, parseInt(e.target.value) || 1)))}
                className="w-14 px-1 py-0.5 bg-gray-700 border border-gray-600 rounded text-white" />
            </label>
            <span className="text-gray-500">헤더는 짝홀 교대로 자동: {
              Array.from({ length: layerCount }, (_, i) => colOf(i)).join(' / ')
            }</span>
          </div>

          {/* 층 탭 */}
          <div className="flex gap-1 flex-wrap">
            {Array.from({ length: layerCount }, (_, i) => (
              <button key={i} onClick={() => setActive(i)}
                className={`px-2 py-1 rounded text-[11px] border ${
                  active === i ? 'bg-sky-600 border-sky-500 text-white'
                               : 'bg-gray-700 border-gray-600 text-gray-300'}`}>
                L{i} ({colOf(i)}×{colOf(i)}) · {Object.keys(layers[i] || {}).length}
              </button>
            ))}
          </div>

          <div className="flex gap-3 items-start flex-wrap">
            {/* 격자 */}
            <div className="inline-block border border-sky-800 rounded select-none">
              {Array.from({ length: c }, (_, y) => (
                <div key={y} className="flex">
                  {Array.from({ length: c }, (_, x) => {
                    const t = cells[`${x}_${y}`];
                    const isCont = t && String(t[0]).match(/^(craft|stack)_/);
                    const bg = t ? (isCont ? '#6366f1' : (COLOR_HEX[String(t[0])] || '#64748b')) : 'transparent';
                    return (
                      <div key={x}
                        onMouseDown={e => { const m = e.button === 2 || t ? (e.button === 2 ? 'del' : 'add') : 'add'; setDrag(m); put(x, y, m); }}
                        onContextMenu={e => { e.preventDefault(); setDrag('del'); put(x, y, 'del'); }}
                        onMouseEnter={() => { if (drag) put(x, y, drag); }}
                        title={t ? `${t[0]}${t[1] ? ' · ' + t[1] : ''}` : `${x}_${y}`}
                        className="w-7 h-7 border border-gray-700 cursor-pointer flex items-center justify-center text-[8px] text-white/80"
                        style={{ background: bg }}>
                        {t && t[1] ? '◆' : ''}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>

            {/* 팔레트 */}
            <div className="space-y-2 text-[11px] min-w-[15rem]">
              <div>
                <div className="text-gray-400 mb-1">타일 색 <span className="text-gray-600">(t0=런타임 분배)</span></div>
                <div className="flex gap-1 flex-wrap">
                  {COLORS.map(col => (
                    <button key={col} onClick={() => { setPaintColor(col); setPaintContainer(''); }}
                      className={`w-6 h-6 rounded border-2 ${paintColor === col && !paintContainer ? 'border-white' : 'border-gray-600'}`}
                      style={{ background: COLOR_HEX[col] }} title={col} />
                  ))}
                </div>
              </div>

              {containerPalette.length > 0 && (
                <div>
                  <div className="text-gray-400 mb-1">컨테이너 <span className="text-gray-600">(내부 3타일)</span></div>
                  <div className="flex gap-1 flex-wrap">
                    <button onClick={() => setPaintContainer('')}
                      className={`px-1.5 py-0.5 rounded border text-[10px] ${!paintContainer ? 'bg-gray-600 border-white text-white' : 'bg-gray-700 border-gray-600 text-gray-300'}`}>없음</button>
                    {containerPalette.map(k => (
                      <button key={k} onClick={() => setPaintContainer(k)}
                        className={`px-1.5 py-0.5 rounded border text-[10px] ${paintContainer === k ? 'bg-indigo-600 border-indigo-400 text-white' : 'bg-gray-700 border-gray-600 text-gray-300'}`}>{k}</button>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <div className="text-gray-400 mb-1">
                  속성 기믹 {attrPalette.length === 0 && <span className="text-gray-600">— 이 레벨엔 해금된 게 없음</span>}
                </div>
                <div className="flex gap-1 flex-wrap">
                  <button onClick={() => setPaintAttr('')}
                    className={`px-1.5 py-0.5 rounded border text-[10px] ${!paintAttr ? 'bg-gray-600 border-white text-white' : 'bg-gray-700 border-gray-600 text-gray-300'}`}>없음</button>
                  {attrPalette.map(g => (
                    <button key={g} onClick={() => setPaintAttr(g)}
                      className={`px-1.5 py-0.5 rounded border text-[10px] ${paintAttr === g ? 'bg-emerald-600 border-emerald-400 text-white' : 'bg-gray-700 border-gray-600 text-gray-300'}`}>{g}</button>
                  ))}
                </div>
              </div>

              <div className="flex gap-1 flex-wrap pt-1">
                <button onClick={fillAll} className="px-2 py-1 rounded text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-200">층 가득</button>
                <button onClick={clearLayer} className="px-2 py-1 rounded text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-200">층 비우기</button>
                {[3, 4, 5, 6].map(v => (
                  <button key={v} onClick={() => autoColors(v)}
                    className="px-2 py-1 rounded text-[10px] bg-violet-800 hover:bg-violet-700 text-white"
                    title={`전 층 타일을 ${v}색으로 3개씩 순환 배분`}>{v}색 배분</button>
                ))}
              </div>
              <p className="text-[10px] text-gray-500">좌클릭 칠하기 · 우클릭/드래그 지우기</p>
            </div>
          </div>

          {/* 검증 */}
          <div className={`p-2 rounded text-[11px] ${blocking.length ? 'bg-red-900/25 border border-red-800' : 'bg-emerald-900/20 border border-emerald-800'}`}>
            {summary && (
              <div className="text-gray-300 mb-1">
                {summary.layer_count}층 · 총 {summary.total_tiles}타일 · 층별 {summary.per_layer.join(' / ')}
                <span className="text-gray-500"> (마무리 파이프라인 ÷3 보정 반영값)</span>
              </div>
            )}
            {issues.length === 0
              ? <div className="text-emerald-400">규칙 위반 없음 — 저장 가능</div>
              : issues.slice(0, 6).map((i, k) => (
                  <div key={k} className={blocking.includes(i) ? 'text-red-300' : 'text-yellow-300'}>• {i.msg}</div>
                ))}
          </div>

          <div className="flex items-center gap-2">
            <button onClick={save} disabled={busy || blocking.length > 0}
              className="px-3 py-1.5 rounded text-sm bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-50">
              {busy ? '저장 중…' : '고정 저장'}
            </button>
            {blocking.length > 0 && <span className="text-[11px] text-red-400">치명 위반 {blocking.length}건 — 해소 후 저장 가능</span>}
            {msg && <span className={`text-[11px] ${msg.kind === 'ok' ? 'text-emerald-400' : 'text-red-400'}`}>{msg.text}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

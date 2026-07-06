/**
 * 보스 템플릿 편집기 — 프로덕션 보스(10의 배수) 레벨 전용.
 *
 * 반자동 흐름: 사용자가 각 층을 t0로 직접 그려 "모양만" 잡음(홀짝 8/7 교대 자동).
 * 저장하면 생성기가 useTileCount(난이도 그래프) + 기믹 + 검증을 오버레이해 실제 보스 생성.
 * level_min/max = 이 템플릿이 배정될 레벨 구간(깊이별 분류 — 후반 보스일수록 깊은 템플릿).
 *
 * 저장: 백엔드 /debug/boss-template-save (data/boss_templates.json).
 */
import { useState, useEffect, useCallback } from 'react';
import apiClient from '../api/client';
import { useUIStore } from '../stores/uiStore';

// 보스 그리드: base 7 → 짝수층 8, 홀수층 7 (게임 홀짝 규칙). 폭 상한 8(디바이스 가독성).
const BOSS_BASE = 7;
const layerSize = (layerIdx: number) => (layerIdx % 2 === 0 ? BOSS_BASE + 1 : BOSS_BASE); // 8 / 7
const MAX_LAYERS = 10;

interface BossLayer {
  positions: Set<string>;          // "x_y" (col_row) — t0로 채울 셀
  gimmicks: Map<string, string>;   // pos → 기믹(속성). 수동 지정, 자동배치가 보존.
}

// 수동 기믹 팔레트 — 단일 셀 안전 속성만(link/teleport/craft/stack 제외 = 자동 전용).
const GIMMICK_PALETTE: { id: string; label: string; color: string }[] = [
  { id: '', label: '모양(t0)', color: '#6366f1' },
  { id: 'ice', label: '🧊 얼음', color: '#7dd3fc' },
  { id: 'chain', label: '⛓ 체인', color: '#a8a29e' },
  { id: 'grass', label: '🌿 잔디', color: '#86efac' },
  { id: 'frog', label: '🐸 개구리', color: '#4ade80' },
  { id: 'bomb', label: '💣 폭탄', color: '#f87171' },
  { id: 'curtain_close', label: '🎭 커튼', color: '#c084fc' },
  { id: '__erase', label: '🗑 기믹지움', color: '#4b5563' },
];

interface SavedBossTemplate {
  id: string;
  name: string;
  level_min: number;
  level_max: number;
  layer_count: number;
  layers: { layer: number; col: number; row: number; positions: string[]; gimmicks?: Record<string, string> }[];
}

interface BossConcept {
  chapter: string;   // 챕터
  beat: string;      // 스토리 비트
  deco: string;      // 참조 deco
  shape: string;     // 모양 컨셉
  note: string;      // 메모
}

// [기본 컨셉] 1~5챕터 스토리 비트(할아버지 정원, 테마1 "잊혀진 온기") — 보스 10~100.
// 사용자 확정 스토리(deco_1~5) 기반. 편집/저장 가능.
const DEFAULT_CONCEPTS: Record<string, BossConcept> = {
  '10': { chapter: '1 웰컴 게이트', beat: '냥이의 도움 등장', deco: '(냥이 조력자)', shape: '🐱 고양이 얼굴', note: '이미 제작' },
  '20': { chapter: '1 피날레', beat: '우체통 해금 → 할아버지 편지 발견', deco: 'deco_1_10 할아버지의 비밀 우체통', shape: '💌 편지/우체통', note: '이미 제작' },
  '30': { chapter: '2 포근한 대기석', beat: '포근한 쉼터 등장', deco: 'deco_2_4 햇살 기다리는 벤치', shape: '🪑 벤치(등받이+다리, 대칭)', note: '' },
  '40': { chapter: '2 피날레', beat: '꽃차 한 잔의 여유', deco: 'deco_2_10 향긋한 꽃차 오늘의 메뉴', shape: '☕ 찻잔(김 모락+받침)', note: '' },
  '50': { chapter: '3 냥이의 쉼터', beat: '냥이 왕국', deco: 'deco_3_2 정원의 왕 캣캐슬', shape: '🏰 캣하우스/캣타워(지붕+입구)', note: '냥이 서브플롯' },
  '60': { chapter: '3 피날레', beat: '냥이의 밤', deco: 'deco_3_10 핑크 젤리 조명', shape: '🐾 젤리등 / 🐱 웅크린 냥이', note: '냥이 서브플롯' },
  '70': { chapter: '4 추억의 우체통 정원', beat: '추억을 읽다', deco: 'deco_4_3 손때묻은 미니 도서관', shape: '📖 책/책더미(펼친 책)', note: '' },
  '80': { chapter: '4 피날레', beat: '마음을 잇다', deco: 'deco_4_11 추억을 잇는 빨간 우체통', shape: '📮 빨간 우체통(20과 다른 형태) / 🌹 장미 넝쿨 아치', note: '할아버지 서브플롯' },
  '90': { chapter: '5 할아버지의 흔들의자', beat: '할아버지의 자리', deco: 'deco_5_4 최고급 흔들의자', shape: '🪑 흔들의자(곡선다리) / 🌷 수국 화단', note: '' },
  '100': { chapter: '5 피날레 (대형 마일스톤)', beat: '첫 편지·추억의 액자', deco: 'deco_5_10 추억의 액자와 할아버지의 첫 편지', shape: '🖼️ 액자+하트 / 💌 편지+리본', note: '20과 수미상관, 스토리 완결' },
};

export function BossTemplatePanel() {
  const { addNotification } = useUIStore();

  const [name, setName] = useState('');
  const [levelMin, setLevelMin] = useState(10);
  const [levelMax, setLevelMax] = useState(1500);
  const emptyLayer = (): BossLayer => ({ positions: new Set(), gimmicks: new Map() });
  const [layers, setLayers] = useState<BossLayer[]>([emptyLayer(), emptyLayer(), emptyLayer()]);
  const [activeLayer, setActiveLayer] = useState(0);
  const [paintMode, setPaintMode] = useState<string>(''); // '' = 모양, 'ice'.. = 기믹, '__erase' = 기믹지움
  const [saved, setSaved] = useState<SavedBossTemplate[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [painting, setPainting] = useState<boolean | null>(null); // 드래그 페인트: true=칠, false=지움

  const loadSaved = useCallback(async () => {
    try {
      const res = await apiClient.get('/debug/boss-templates');
      const map = res.data.boss_templates || {};
      setSaved(Object.values(map) as SavedBossTemplate[]);
    } catch { /* 서버 미가동 무시 */ }
  }, []);
  useEffect(() => { loadSaved(); }, [loadSaved]);

  // [컨셉 노트] 보스 레벨별 스토리 비트/모양 컨셉
  const [concepts, setConcepts] = useState<Record<string, BossConcept>>({});
  const [conceptsDirty, setConceptsDirty] = useState(false);
  const [conceptsOpen, setConceptsOpen] = useState(true);
  const loadConcepts = useCallback(async () => {
    try {
      const res = await apiClient.get('/debug/boss-concepts');
      const map = res.data.boss_concepts || {};
      // 서버 비어있으면 기본 컨셉(10~100) 씨딩(로컬 표시만; 저장 눌러야 서버 반영)
      setConcepts(Object.keys(map).length ? map : { ...DEFAULT_CONCEPTS });
    } catch { setConcepts({ ...DEFAULT_CONCEPTS }); }
  }, []);
  useEffect(() => { loadConcepts(); }, [loadConcepts]);

  const setConceptField = (level: string, field: keyof BossConcept, value: string) => {
    setConcepts(prev => ({ ...prev, [level]: { ...(prev[level] || { chapter: '', beat: '', deco: '', shape: '', note: '' }), [field]: value } }));
    setConceptsDirty(true);
  };
  const addConceptRow = () => {
    // 다음 10단위 레벨 추가
    const levels = Object.keys(concepts).map(k => parseInt(k)).filter(n => !isNaN(n));
    const next = (levels.length ? Math.max(...levels) : 0) + 10;
    setConcepts(prev => ({ ...prev, [String(next)]: { chapter: '', beat: '', deco: '', shape: '', note: '' } }));
    setConceptsDirty(true);
  };
  const removeConceptRow = (level: string) => {
    setConcepts(prev => { const n = { ...prev }; delete n[level]; return n; });
    setConceptsDirty(true);
  };
  const saveConcepts = async () => {
    try {
      await apiClient.post('/debug/boss-concepts-save', { concepts });
      setConceptsDirty(false);
      addNotification('success', `보스 컨셉 노트 저장 (${Object.keys(concepts).length}개)`);
    } catch (e) { addNotification('error', `컨셉 저장 실패: ${(e as Error).message}`); }
  };
  const resetConceptsToDefault = () => { setConcepts({ ...DEFAULT_CONCEPTS }); setConceptsDirty(true); };

  const cols = layerSize(activeLayer);
  const rows = layerSize(activeLayer);

  // 셀 클릭/드래그 처리 — paintMode에 따라 모양 토글 or 기믹 지정/지움.
  const applyCell = useCallback((x: number, y: number, forceVal?: boolean) => {
    setLayers(prev => {
      const next = prev.map(l => ({ positions: new Set(l.positions), gimmicks: new Map(l.gimmicks) }));
      const L = next[activeLayer];
      const key = `${x}_${y}`;
      if (paintMode === '') {
        // 모양 토글 (지우면 그 셀 기믹도 제거)
        const cur = L.positions.has(key);
        const target = forceVal !== undefined ? forceVal : !cur;
        if (target) L.positions.add(key);
        else { L.positions.delete(key); L.gimmicks.delete(key); }
      } else if (paintMode === '__erase') {
        L.gimmicks.delete(key);
      } else {
        // 기믹 지정 — 셀이 켜져있어야(t0) 함
        if (L.positions.has(key)) L.gimmicks.set(key, paintMode);
      }
      return next;
    });
  }, [activeLayer, paintMode]);

  const addLayer = () => setLayers(prev => (prev.length >= MAX_LAYERS ? prev : [...prev, emptyLayer()]));
  const removeLayer = () => setLayers(prev => {
    if (prev.length <= 1) return prev;
    const next = prev.slice(0, -1);
    if (activeLayer >= next.length) setActiveLayer(next.length - 1);
    return next;
  });

  const clearActive = () => setLayers(prev => prev.map((l, i) => (i === activeLayer ? emptyLayer() : l)));
  const fillActive = () => setLayers(prev => prev.map((l, i) => {
    if (i !== activeLayer) return l;
    const s = new Set<string>();
    const c = layerSize(i);
    for (let y = 0; y < c; y++) for (let x = 0; x < c; x++) s.add(`${x}_${y}`);
    return { positions: s, gimmicks: new Map(l.gimmicks) };
  }));

  const resetEditor = () => {
    setName(''); setLevelMin(10); setLevelMax(1500);
    setLayers([emptyLayer(), emptyLayer(), emptyLayer()]);
    setActiveLayer(0); setEditingId(null); setPaintMode('');
  };

  const totalCells = layers.reduce((a, l) => a + l.positions.size, 0);

  const save = async () => {
    if (totalCells === 0) { addNotification('warning', '빈 템플릿 — 셀을 찍으세요'); return; }
    // ÷3 안내(경고만): 총 t0가 3의 배수여야 클리어 가능(생성기가 최종 보정하나 근접 권장)
    const id = editingId || `boss_${levelMin}_${levelMax}_${totalCells}_${layers.length}L`;
    const body = {
      id,
      name: name || id,
      level_min: levelMin,
      level_max: levelMax,
      layers: layers.map((l, i) => ({
        layer: i, col: layerSize(i), row: layerSize(i), positions: [...l.positions],
        gimmicks: Object.fromEntries(l.gimmicks),
      })),
    };
    try {
      await apiClient.post('/debug/boss-template-save', body);
      addNotification('success', `보스 템플릿 저장: ${id} (${layers.length}층, ${totalCells}셀)`);
      setEditingId(id);
      loadSaved();
    } catch (e) {
      addNotification('error', `저장 실패: ${(e as Error).message}`);
    }
  };

  const loadTemplate = (t: SavedBossTemplate) => {
    setName(t.name); setLevelMin(t.level_min); setLevelMax(t.level_max);
    const ls: BossLayer[] = t.layers
      .sort((a, b) => a.layer - b.layer)
      .map(l => ({
        positions: new Set(l.positions),
        gimmicks: new Map(Object.entries((l as { gimmicks?: Record<string, string> }).gimmicks || {})),
      }));
    setLayers(ls.length ? ls : [emptyLayer()]);
    setActiveLayer(0); setEditingId(t.id);
    addNotification('info', `로드: ${t.id}`);
  };

  const deleteTemplate = async (id: string) => {
    if (!confirm(`보스 템플릿 삭제? ${id}`)) return;
    try {
      await apiClient.delete(`/debug/boss-template/${id}`);
      addNotification('info', `삭제: ${id}`);
      if (editingId === id) resetEditor();
      loadSaved();
    } catch (e) { addNotification('error', `삭제 실패: ${(e as Error).message}`); }
  };

  return (
    <div className="max-w-5xl mx-auto p-4 space-y-4" onMouseUp={() => setPainting(null)} onMouseLeave={() => setPainting(null)}>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">🏰 보스 템플릿 편집기</h2>
        <span className="text-xs text-gray-400">모양만 t0로 그림 → 생성기가 타입/기믹/검증 자동 오버레이</span>
      </div>

      <div className="bg-blue-900/20 border border-blue-700/40 rounded p-3 text-xs text-gray-300 leading-relaxed">
        각 층을 <b className="text-blue-300">t0(모양만)</b>로 그리세요. 크기는 <b>짝수층 8 · 홀수층 7</b> 자동(게임 홀짝 규칙).
        층마다 다른 모양 가능. 저장 시 <b>level_min~max 구간</b>의 보스(10의 배수)에 배정됨 —
        후반 보스일수록 깊은(층 많은) 템플릿을 만들어 구간을 나누세요.
      </div>

      {/* 메타 */}
      <div className="grid grid-cols-4 gap-3 bg-gray-800 rounded p-3">
        <div className="col-span-2">
          <label className="block text-[11px] text-gray-400 mb-1">이름</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="예: 왕관형"
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white" />
        </div>
        <div>
          <label className="block text-[11px] text-gray-400 mb-1">배정 레벨 최소</label>
          <input type="number" value={levelMin} min={10} step={10} onChange={e => setLevelMin(parseInt(e.target.value) || 10)}
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white" />
        </div>
        <div>
          <label className="block text-[11px] text-gray-400 mb-1">배정 레벨 최대</label>
          <input type="number" value={levelMax} min={10} step={10} onChange={e => setLevelMax(parseInt(e.target.value) || 1500)}
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white" />
        </div>
      </div>

      {/* 층 선택 + 관리 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-400">층:</span>
        {layers.map((l, i) => (
          <button key={i} onClick={() => setActiveLayer(i)}
            className={`px-3 py-1.5 rounded text-xs font-medium ${activeLayer === i ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}>
            L{i} <span className="opacity-70">({layerSize(i)}·{l.positions.size})</span>
          </button>
        ))}
        <button onClick={addLayer} disabled={layers.length >= MAX_LAYERS}
          className="px-2 py-1.5 rounded text-xs bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-40">+ 층</button>
        <button onClick={removeLayer} disabled={layers.length <= 1}
          className="px-2 py-1.5 rounded text-xs bg-red-800 hover:bg-red-700 text-white disabled:opacity-40">− 층</button>
        <span className="text-[11px] text-gray-500 ml-2">총 {layers.length}층 · {totalCells}셀 {totalCells % 3 !== 0 && <span className="text-yellow-400">(÷3 아님 — 생성기 보정)</span>}</span>
      </div>

      {/* 그리기 그리드 */}
      <div className="flex gap-4">
        <div className="bg-gray-800 rounded p-3 select-none">
          <div className="text-[11px] text-gray-400 mb-2">
            L{activeLayer} · {cols}×{rows} · 모드: <b className="text-white">{GIMMICK_PALETTE.find(g => g.id === paintMode)?.label}</b>
            {paintMode !== '' && paintMode !== '__erase' && <span className="text-yellow-400"> (t0 셀에만 지정됨)</span>}
          </div>
          <div className="flex gap-3">
          <div className="grid gap-0.5 flex-shrink-0" style={{ gridTemplateColumns: `repeat(${cols}, 28px)`, height: 'fit-content' }}>
            {Array.from({ length: rows }, (_, y) =>
              Array.from({ length: cols }, (_, x) => {
                const key = `${x}_${y}`;
                const on = layers[activeLayer].positions.has(key);
                const gim = layers[activeLayer].gimmicks.get(key);
                const gcolor = gim ? GIMMICK_PALETTE.find(g => g.id === gim)?.color : undefined;
                return (
                  <div key={key}
                    onMouseDown={() => { const sv = paintMode === '' ? !on : true; setPainting(sv); applyCell(x, y, sv); }}
                    onMouseEnter={() => { if (painting !== null) applyCell(x, y, painting); }}
                    className={`w-7 h-7 rounded-sm cursor-pointer border flex items-center justify-center text-[13px] ${on ? 'border-indigo-300' : 'bg-gray-700 border-gray-600 hover:bg-gray-600'}`}
                    style={on ? { background: gcolor || '#6366f1' } : undefined}
                    title={`${key}${gim ? ' · ' + gim : ''}`}>
                    {gim ? (GIMMICK_PALETTE.find(g => g.id === gim)?.label.split(' ')[0] || '') : ''}
                  </div>
                );
              })
            )}
          </div>
          {/* 기믹 팔레트 (세로) */}
          <div className="flex flex-col gap-1">
            <div className="text-[10px] text-gray-500 mb-0.5">기믹 팔레트</div>
            {GIMMICK_PALETTE.map(g => (
              <button key={g.id} onClick={() => setPaintMode(g.id)}
                className={`px-2 py-1.5 rounded text-[11px] border text-left whitespace-nowrap ${paintMode === g.id ? 'ring-2 ring-white font-semibold' : 'opacity-80 hover:opacity-100'}`}
                style={{ background: g.id === '__erase' ? '#374151' : g.color, color: g.id === '' || g.id === '__erase' ? '#fff' : '#1f2937', borderColor: 'rgba(255,255,255,0.2)' }}>
                {g.label}
              </button>
            ))}
          </div>
          </div>
          <div className="flex gap-2 mt-2">
            <button onClick={fillActive} className="px-2 py-1 rounded text-[11px] bg-gray-600 hover:bg-gray-500 text-white">전체 채움</button>
            <button onClick={clearActive} className="px-2 py-1 rounded text-[11px] bg-gray-600 hover:bg-gray-500 text-white">비움</button>
          </div>
        </div>

        {/* 게임 충실 미리보기 — 홀짝 0.5 오프셋 + 층 스택(상위층 앞) + 타일 렌더 */}
        <div className="bg-gray-900 rounded p-3">
          <div className="text-[11px] text-gray-400 mb-2">인게임 미리보기 (홀짝 오프셋 + 층 스택)</div>
          {(() => {
            const CELL = 30;
            const maxSpan = BOSS_BASE + 1;           // 짝수층 폭(8) 기준 캔버스
            const canvas = maxSpan * CELL + CELL;    // 여백
            const cx = canvas / 2, cy = canvas / 2;
            // 게임 좌표: worldX=-(rowCount/2)+0.5+col, worldY=(rowCount/2)-0.5-row (row0=위)
            // 각 층은 자기 rowCount로 센터링 → 홀수층(7)이 짝수층(8) 사이 0.5 오프셋에 자동 위치.
            // 층 팔레트(하위=어둡게, 상위=밝게) — 상위층이 앞(위)에 그려짐.
            const palette = ['#3730a3', '#4338ca', '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc', '#c7d2fe', '#e0e7ff', '#eef2ff', '#f5f7ff'];
            const tiles: { px: number; py: number; z: number; color: string }[] = [];
            layers.forEach((l, li) => {
              const rc = layerSize(li);
              const color = palette[Math.min(li, palette.length - 1)];
              l.positions.forEach(key => {
                const [xs, ys] = key.split('_');
                const col = parseInt(xs), row = parseInt(ys);
                const wx = -(rc / 2) + 0.5 + col;
                const wy = (rc / 2) - 0.5 - row;
                tiles.push({ px: cx + wx * CELL, py: cy - wy * CELL, z: li, color });
              });
            });
            tiles.sort((a, b) => a.z - b.z); // 하위층 먼저(뒤), 상위층 나중(앞) — 게임 sort 동일
            return (
              <div className="relative rounded bg-gray-800/50" style={{ width: canvas, height: canvas }}>
                {tiles.map((t, i) => (
                  <div key={i} className="absolute rounded-md" title={`L${t.z}`}
                    style={{
                      left: t.px - CELL / 2, top: t.py - CELL / 2, width: CELL - 2, height: CELL - 2,
                      background: t.color, zIndex: t.z,
                      border: '1px solid rgba(255,255,255,0.25)',
                      boxShadow: 'inset 0 2px 3px rgba(255,255,255,0.25), inset 0 -2px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.4)',
                    }} />
                ))}
              </div>
            );
          })()}
          <div className="text-[10px] text-gray-500 mt-1">어두운=하위층(뒤) · 밝은=상위층(앞). 홀수층은 0.5칸 어긋남(게임 홀짝).</div>
        </div>
      </div>

      {/* 저장 */}
      <div className="flex gap-2">
        <button onClick={save} className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium">
          {editingId ? '💾 덮어쓰기 저장' : '💾 새 템플릿 저장'}
        </button>
        {editingId && <button onClick={resetEditor} className="px-4 py-2 rounded bg-gray-700 hover:bg-gray-600 text-white text-sm">＋ 새로 만들기</button>}
      </div>

      {/* 스토리 컨셉 노트 */}
      <div className="bg-gray-800 rounded p-3">
        <div className="flex items-center justify-between mb-2">
          <button onClick={() => setConceptsOpen(o => !o)} className="text-sm font-medium text-white flex items-center gap-1">
            {conceptsOpen ? '▼' : '▶'} 🎬 보스 스토리 컨셉 노트 ({Object.keys(concepts).length})
            {conceptsDirty && <span className="text-[10px] text-yellow-400">● 미저장</span>}
          </button>
          <div className="flex gap-1">
            <button onClick={addConceptRow} className="px-2 py-0.5 rounded text-[11px] bg-emerald-700 hover:bg-emerald-600 text-white">+ 행</button>
            <button onClick={resetConceptsToDefault} className="px-2 py-0.5 rounded text-[11px] bg-gray-600 hover:bg-gray-500 text-white" title="1~5챕터 기본 컨셉(10~100)으로 리셋">기본값</button>
            <button onClick={saveConcepts} disabled={!conceptsDirty} className="px-2 py-0.5 rounded text-[11px] bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40">💾 저장</button>
          </div>
        </div>
        {conceptsOpen && (
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] text-gray-300">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left px-1 py-1 w-12">보스</th>
                  <th className="text-left px-1 py-1 w-28">챕터</th>
                  <th className="text-left px-1 py-1">스토리 비트</th>
                  <th className="text-left px-1 py-1">참조 deco</th>
                  <th className="text-left px-1 py-1">모양 컨셉</th>
                  <th className="text-left px-1 py-1 w-24">메모</th>
                  <th className="w-16"></th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(concepts).map(k => parseInt(k)).filter(n => !isNaN(n)).sort((a, b) => a - b).map(n => {
                  const lv = String(n);
                  const c = concepts[lv];
                  const hasTpl = saved.some(t => t.level_min <= n && n <= t.level_max);
                  const inp = (field: keyof BossConcept, w = '') =>
                    <input value={c[field]} onChange={e => setConceptField(lv, field, e.target.value)}
                      className={`bg-gray-700/50 border border-gray-600 rounded px-1 py-0.5 text-[11px] text-white w-full ${w}`} />;
                  return (
                    <tr key={lv} className="border-b border-gray-700/50">
                      <td className="px-1 py-1 font-mono text-purple-300 whitespace-nowrap">
                        {lv} {hasTpl && <span title="이 레벨 커버하는 템플릿 있음" className="text-emerald-400">●</span>}
                      </td>
                      <td className="px-1 py-1">{inp('chapter')}</td>
                      <td className="px-1 py-1">{inp('beat')}</td>
                      <td className="px-1 py-1">{inp('deco')}</td>
                      <td className="px-1 py-1">{inp('shape')}</td>
                      <td className="px-1 py-1">{inp('note')}</td>
                      <td className="px-1 py-1 text-right">
                        <button onClick={() => { setLevelMin(n); setLevelMax(n); addNotification('info', `배정구간 ${n}로 설정 — 이 컨셉용 템플릿 그리세요`); }}
                          className="px-1.5 py-0.5 rounded bg-gray-600 hover:bg-gray-500 text-white text-[10px]" title="이 레벨용 템플릿 그리기(배정구간 설정)">그리기</button>
                        <button onClick={() => removeConceptRow(lv)} className="px-1 py-0.5 rounded bg-red-800 hover:bg-red-700 text-white text-[10px] ml-1">×</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="text-[10px] text-gray-500 mt-1">● = 이 레벨 커버하는 보스 템플릿 있음 · "그리기" = 위 편집기 배정구간을 해당 레벨로 세팅</div>
          </div>
        )}
      </div>

      {/* 저장 목록 */}
      <div className="bg-gray-800 rounded p-3">
        <h3 className="text-sm font-medium text-white mb-2">저장된 보스 템플릿 ({saved.length})</h3>
        {saved.length === 0 ? (
          <p className="text-xs text-gray-500">없음 — 위에서 그려 저장하세요.</p>
        ) : (
          <div className="space-y-1">
            {saved.sort((a, b) => a.level_min - b.level_min).map(t => (
              <div key={t.id} className={`flex items-center justify-between px-3 py-2 rounded text-xs ${editingId === t.id ? 'bg-indigo-900/30' : 'bg-gray-700/40'}`}>
                <div className="flex-1">
                  <span className="text-white font-medium">{t.name}</span>
                  <span className="text-gray-400 ml-2">Lv {t.level_min}~{t.level_max} · {t.layer_count}층</span>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => loadTemplate(t)} className="px-2 py-0.5 rounded bg-gray-600 hover:bg-gray-500 text-white">로드</button>
                  <button onClick={() => deleteTemplate(t.id)} className="px-2 py-0.5 rounded bg-red-800 hover:bg-red-700 text-white">삭제</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

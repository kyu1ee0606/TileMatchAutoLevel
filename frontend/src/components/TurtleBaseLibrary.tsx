/**
 * [등껍질 바닥 라이브러리] 침식 스택의 **바닥 1층 모양**을 등록/관리하는 패널.
 *
 * 왜 필요: 등껍질 레벨은 바닥 모양이 층수·타일수·난이도를 전부 결정한다. 지금까지는
 * 기존 `custom_patterns` 중 우연히 자격(침식 깊이≥4·총타일≤130)을 얻은 49종만 쓸 수 있어
 * 서브보스 149레벨이 13종으로 돌려막혔다(상위 7종이 69% 차지). 여기서 전용 바닥을 늘리면
 * 후보 풀이 커져 다양성이 바로 개선된다.
 *
 * 저장은 `data/turtle_bases.json`(전용) — `custom_patterns` 는 등껍질 외 경로에서도 쓰이므로
 * 건드리지 않는다(기존 49종은 복사본으로 유입됨).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import apiClient from '../api/client';

interface TurtleBase {
  id: string;
  name: string;
  grid: number;
  enabled: boolean;
  source?: string;
  cell_count?: number;
  cells?: string[];
  turtle?: { depth: number; total: number; per_layer: number[]; base: number; est_max_total?: number };
  difficulty?: { by_v?: Record<string, { avg: number; cas: number }>; coef?: number };
  layers?: Array<{ col: number; cells: string[] }>;
}

interface Limits {
  min_depth: number;
  max_total: number;            // 순수 침식 셀 상한(검증에 쓰이는 값)
  effective_max_total: number;  // 실생성 기준 상한 — 사용자에게 보여줄 숫자
  max_overhead: number;         // ÷3 패딩 + 컨테이너 내부 타일 최악치(실측 16)
  allowed_grids: number[];
}

/** 침식 스택을 겹쳐 그린 미니 실루엣. 위층일수록 밝게 → 깎여 올라간 깊이가 보인다. */
function StackPreview({ layers, size = 52 }: { layers: TurtleBase['layers']; size?: number }) {
  if (!layers || layers.length === 0) return null;
  const base = layers[0].col;
  const u = size / base;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="rounded bg-gray-900/60">
      {layers.map((L, li) => {
        // 홀수층(col = base-1)은 짝수층 격자의 교차점에 놓이므로 반 칸 이동
        const off = ((base - L.col) / 2) * u;
        const op = 0.28 + (0.72 * li) / Math.max(1, layers.length - 1);
        return (
          <g key={li} opacity={op}>
            {L.cells.map(c => {
              const [x, y] = c.split('_').map(Number);
              return <rect key={c} x={off + x * u + u * 0.08} y={off + y * u + u * 0.08}
                width={u * 0.84} height={u * 0.84} rx={u * 0.2} fill="#34d399" />;
            })}
          </g>
        );
      })}
    </svg>
  );
}

export function TurtleBaseLibrary() {
  const [open, setOpen] = useState(false);
  const [bases, setBases] = useState<TurtleBase[]>([]);
  const [limits, setLimits] = useState<Limits>({
    min_depth: 4, max_total: 129, effective_max_total: 145, max_overhead: 16, allowed_grids: [7, 8],
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  // 에디터 상태
  const [grid, setGrid] = useState(8);
  const [cells, setCells] = useState<Set<string>>(new Set());
  const [name, setName] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [paint, setPaint] = useState<boolean | null>(null);   // 드래그 페인트 모드
  const [pendingMeta, setPendingMeta] = useState<TurtleBase['turtle'] | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get('/debug/turtle-bases');
      setBases((r.data?.turtle_bases || []) as TurtleBase[]);
      if (r.data?.limits) setLimits(r.data.limits);
    } catch {
      setMsg({ kind: 'err', text: '목록 조회 실패 (백엔드 확인)' });
    }
  }, []);

  useEffect(() => { if (open && bases.length === 0) void load(); }, [open, bases.length, load]);

  // 그리드 크기 변경 시 범위 밖 셀 제거(모양 유실 최소화 — 안쪽은 그대로 유지)
  useEffect(() => {
    setCells(prev => {
      const next = new Set<string>();
      prev.forEach(c => {
        const [x, y] = c.split('_').map(Number);
        if (x < grid && y < grid) next.add(c);
      });
      return next;
    });
  }, [grid]);

  const toggle = (x: number, y: number, force?: boolean) => {
    const k = `${x}_${y}`;
    setCells(prev => {
      const n = new Set(prev);
      const want = force !== undefined ? force : !n.has(k);
      if (want) n.add(k); else n.delete(k);
      return n;
    });
  };

  /** 침식 결과 미리보기 — 계산 정본은 백엔드(생성기와 동일 로직)라 서버에 물어본다.
      저장 없는 전용 엔드포인트라 저장소가 오염되지 않는다. */
  const [previewLayers, setPreviewLayers] = useState<TurtleBase['layers']>([]);
  useEffect(() => {
    if (cells.size === 0) { setPendingMeta(null); setPreviewLayers([]); return; }
    let alive = true;
    const t = setTimeout(() => {
      apiClient.post('/debug/turtle-bases/preview', { grid, cells: [...cells] })
        .then(r => {
          if (!alive) return;
          setPendingMeta(r.data?.turtle ?? null);
          setPreviewLayers(r.data?.layers ?? []);
          setMsg(r.data?.invalid ? { kind: 'err', text: r.data.invalid } : null);
        })
        .catch(() => { if (alive) setPendingMeta(null); });
    }, 150);   // 드래그 중 요청 폭주 방지
    return () => { alive = false; clearTimeout(t); };
  }, [cells, grid]);

  const save = async () => {
    if (cells.size === 0) { setMsg({ kind: 'err', text: '셀을 그려주세요' }); return; }
    setBusy(true);
    try {
      const r = await apiClient.post('/debug/turtle-bases', {
        id: editingId ?? undefined,
        name: name || `바닥 ${grid}x${grid}`,
        grid, cells: [...cells], enabled: true,
      });
      setMsg({ kind: 'ok', text: `저장됨: ${r.data?.base?.id} (${r.data?.base?.turtle?.depth}층 / ${r.data?.base?.turtle?.total}타일)` });
      setEditingId(null); setName('');
      await load();
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: { invalid?: string } } } }).response?.data?.detail;
      setMsg({ kind: 'err', text: d?.invalid || '저장 실패' });
    } finally { setBusy(false); }
  };

  const measure = async (id: string) => {
    setBusy(true);
    setMsg({ kind: 'ok', text: `${id} 난이도 측정 중… (V 6/9/12, 봇 시뮬)` });
    try {
      const r = await apiClient.post(`/debug/turtle-bases/${id}/measure?iterations=100`);
      const d = r.data?.difficulty;
      setMsg({ kind: 'ok', text: `${id} 측정 완료 — coef ${d?.coef} (V9 avg ${d?.by_v?.['9']?.avg})` });
      await load();
    } catch { setMsg({ kind: 'err', text: '측정 실패' }); }
    finally { setBusy(false); }
  };

  const remove = async (id: string) => {
    if (!window.confirm(`${id} 삭제할까요?`)) return;
    try { await apiClient.delete(`/debug/turtle-bases/${id}`); await load(); }
    catch { setMsg({ kind: 'err', text: '삭제 실패' }); }
  };

  const edit = (b: TurtleBase) => {
    setGrid(b.grid);
    setCells(new Set(b.cells || []));
    setName(b.name);
    setEditingId(b.id);
    setMsg({ kind: 'ok', text: `${b.id} 불러옴 — 수정 후 저장하면 덮어씁니다` });
  };

  const measured = useMemo(() => bases.filter(b => b.difficulty?.coef !== undefined).length, [bases]);

  return (
    <div className="bg-gray-800/50 rounded p-2">
      <button onClick={() => setOpen(o => !o)} className="text-xs text-emerald-300 font-medium">
        {open ? '▼' : '▶'} 🐢 등껍질 바닥 라이브러리 ({bases.length}개)
        <span className="text-gray-500"> — 침식 스택의 바닥 1층. 난이도 측정된 것만 서브보스 자동 배정에 쓰임</span>
      </button>

      {open && (
        <div className="mt-2 space-y-3">
          {/* ── 에디터 ── */}
          <div
            className="p-2 bg-emerald-900/15 rounded flex gap-3 items-start"
            onMouseUp={() => setPaint(null)}
            onMouseLeave={() => setPaint(null)}
          >
            <div className="text-[10px] text-emerald-200 w-28 shrink-0">
              <div className="mb-1">바닥 그리기</div>
              <div className="flex gap-1 mb-1">
                {limits.allowed_grids.map(g => (
                  <button key={g} onClick={() => setGrid(g)}
                    className={`px-2 py-0.5 rounded text-[10px] ${grid === g ? 'bg-emerald-600 text-white' : 'bg-gray-700 text-gray-300'}`}>
                    {g}×{g}
                  </button>
                ))}
              </div>
              <div className="text-gray-400">{cells.size}칸</div>
              {pendingMeta && (
                <div className={pendingMeta.depth >= limits.min_depth && pendingMeta.total <= limits.max_total
                  ? 'text-green-400' : 'text-yellow-400'}>
                  {pendingMeta.depth}층 / 순수 {pendingMeta.total}타일
                  {/* 실생성엔 ÷3 패딩 + craft/stack 내부 타일이 더 붙는다(실측 최대 +16).
                      순수 셀만 보면 예산을 오해하므로 예상 최대치를 함께 보여준다. */}
                  <div className="text-emerald-300">
                    실생성 최대 ~{pendingMeta.est_max_total ?? (pendingMeta.total + limits.max_overhead)}
                  </div>
                  <div className="text-gray-500">{pendingMeta.per_layer.join('→')}</div>
                </div>
              )}
              <div className="text-gray-600 mt-1">
                깊이≥{limits.min_depth}<br />실생성≤{limits.effective_max_total}
              </div>
            </div>

            <div className="inline-block border border-emerald-700 rounded select-none">
              {Array.from({ length: grid }, (_, y) => (
                <div key={y} className="flex">
                  {Array.from({ length: grid }, (_, x) => {
                    const on = cells.has(`${x}_${y}`);
                    return (
                      <div key={x}
                        onMouseDown={() => { const w = !on; setPaint(w); toggle(x, y, w); }}
                        onMouseEnter={() => { if (paint !== null) toggle(x, y, paint); }}
                        className={`w-5 h-5 border border-gray-700 cursor-pointer ${on ? 'bg-emerald-500' : 'bg-gray-800'}`}
                      />
                    );
                  })}
                </div>
              ))}
            </div>

            {previewLayers && previewLayers.length > 0 && (
              <div className="flex flex-col items-center gap-1">
                <StackPreview layers={previewLayers} size={64} />
                <div className="text-[9px] text-gray-500">침식 결과</div>
              </div>
            )}

            <div className="flex flex-col gap-1">
              <input value={name} onChange={e => setName(e.target.value)} placeholder="이름"
                className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white w-40" />
              <div className="flex gap-1">
                <button onClick={save} disabled={busy}
                  className="px-2 py-1 rounded text-xs bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50">
                  {editingId ? '덮어쓰기' : '추가'}
                </button>
                <button onClick={() => { setCells(new Set()); setEditingId(null); setName(''); setMsg(null); }}
                  className="px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-200">지우기</button>
              </div>
              {msg && (
                <div className={`text-[10px] ${msg.kind === 'ok' ? 'text-emerald-400' : 'text-red-400'} max-w-[16rem]`}>
                  {msg.text}
                </div>
              )}
            </div>
          </div>

          {/* ── 목록 ── */}
          <div className="text-[10px] text-gray-400">
            난이도 측정됨 {measured} / {bases.length}
            <span className="text-gray-600"> · 미측정은 서브보스 자동 배정에서 제외(수동 지정은 가능)</span>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5 max-h-96 overflow-y-auto pr-1">
            {bases.map(b => (
              <div key={b.id} className="flex gap-2 items-center p-1.5 rounded border border-gray-700 bg-gray-800/60">
                <StackPreview layers={b.layers} size={48} />
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] text-white truncate">{b.name}</div>
                  <div className="text-[10px] text-gray-400">
                    {b.grid}×{b.grid} · {b.turtle?.depth}층 · 순수 {b.turtle?.total}
                    <span className="text-gray-500"> (실생성 ~{b.turtle?.est_max_total ?? ((b.turtle?.total ?? 0) + limits.max_overhead)})</span>
                  </div>
                  <div className="text-[10px] text-gray-500">
                    {b.difficulty?.coef !== undefined
                      ? `coef ${b.difficulty.coef.toFixed(2)}`
                      : <span className="text-yellow-500">미측정</span>}
                  </div>
                </div>
                <div className="flex flex-col gap-0.5">
                  <button onClick={() => edit(b)} className="px-1.5 py-0.5 rounded text-[10px] bg-gray-700 hover:bg-gray-600 text-gray-200">편집</button>
                  <button onClick={() => measure(b.id)} disabled={busy}
                    className="px-1.5 py-0.5 rounded text-[10px] bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-50">측정</button>
                  <button onClick={() => remove(b.id)} className="px-1.5 py-0.5 rounded text-[10px] bg-red-800 hover:bg-red-700 text-white">삭제</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

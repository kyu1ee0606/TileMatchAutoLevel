/**
 * PvSeedPlayPanel - 시드 변형(난도 개인화 실험) 수동 플레이
 *
 * 샌드박스 selection(v4 기본, v2/v3 선택) 레벨의 tier(원맵/쉬움2/쉬움1/기준/어려움1/어려움2) 맵을 서버(cs_shuffle)가
 * tier 별 종류 수(seed@utc)로 풀어 쓴 명시 맵으로 받아 GamePlayer 로 그대로 플레이한다 (재배색/bakeFullBoard 경로 없음).
 * 5단계=전 tier, 3단계=원맵·기준·쉬움2·어려움2, 고정맵=원맵만. 07 독립 검증 판정은 배지로 표시(블라인드에선 숨김).
 * 판 종료 시 결과를 /api/pv-play/results 에 기록. production 배치와 무관.
 * 끝나기 전 Restart·Back·탭 이탈은 outcome="abandoned" 로 기록 (1수 이상). GamePlayer 는 수정하지 않고
 * 래퍼에서 헤더 'Moves:' 표시를 관찰하고 Restart 클릭을 캡처한다 (GamePlayer 마크업 의존).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import GamePlayer from '../GamePlayer';
import {
  fetchPvLevels,
  fetchPvResultsSummary,
  fetchPvTierMap,
  postPvResult,
  type PvLevelSummary,
  type PvResultsSummary,
  type PvSelection,
  type PvTier,
  type PvTierMapResponse,
  type PvVerdict,
} from '../../api/pvPlay';

const TIER_LABEL: Record<PvTier, string> = {
  orig: '원맵',
  e2: '쉬움2',
  e1: '쉬움1',
  b: '기준',
  h1: '어려움1',
  h2: '어려움2',
  easy: '참고: 구운 쉬움',
  hard: '참고: 구운 어려움',
};
// DDA 세트: 원본 + seedvar 토큰 칸(e2·e1·h1·h2, 기준 b 없음)이 주, reference_baked(easy/hard)는 뒤에 보조로
const TIER_ORDER: PvTier[] = ['orig', 'e2', 'e1', 'b', 'h1', 'h2', 'easy', 'hard'];
const BLIND_LABELS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']; // 최대 칸 수(DDA: 원본+4+참고2 = 7) 이상

const STATUS_STYLE: Record<string, string> = {
  '5tier': 'bg-green-900/50 text-green-300',
  '3tier': 'bg-teal-900/50 text-teal-300',
  fixed_map: 'bg-gray-700 text-gray-400',
  ok: 'bg-green-900/50 text-green-300',
  bidirectional_unmet: 'bg-yellow-900/50 text-yellow-300',
  unevaluable: 'bg-red-900/50 text-red-300',
  not_finished: 'bg-gray-700 text-gray-400',
};

const SELECTIONS: PvSelection[] = ['v4', 'v3', 'v2', 'dda'];
const SELECTION_LABEL: Record<PvSelection, string> = { v4: 'v4', v3: 'v3', v2: 'v2', dda: 'DDA 세트' };

const VERDICT_BADGE: Record<PvVerdict, { text: string; cls: string; title: string }> = {
  pass: { text: '✓', cls: 'text-green-400', title: '독립 검증 통과' },
  warn: { text: '⚠', cls: 'text-yellow-400', title: '독립 검증 경고' },
  stale: { text: '?', cls: 'text-gray-400', title: '검증 이후 시드 변경 (재검증 필요)' },
};

function shuffled<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

type Outcome = 'won' | 'lost' | 'abandoned';

/** GamePlayer 헤더의 'Moves:' 다음 span 값 (GamePlayer 가 이동 수를 콜백으로 주지 않아 DOM 에서 읽음) */
function readMovesFromDom(root: HTMLElement): number | null {
  const label = Array.from(root.querySelectorAll('span')).find((el) => el.textContent === 'Moves:');
  const n = Number(label?.nextElementSibling?.textContent);
  return Number.isFinite(n) ? n : null;
}

interface LastResult {
  tier: PvTier;
  won: boolean;
  moves: number;
  saved: boolean;
}

export function PvSeedPlayPanel() {
  const [levels, setLevels] = useState<PvLevelSummary[]>([]);
  const [copyId, setCopyId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<number | null>(null);
  const [blind, setBlind] = useState(false);
  const [blindOrder, setBlindOrder] = useState<PvTier[]>([]);
  const [revealed, setRevealed] = useState<Set<PvTier>>(new Set());
  const [current, setCurrent] = useState<PvTierMapResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastResult, setLastResult] = useState<LastResult | null>(null);
  const [summary, setSummary] = useState<PvResultsSummary>({});
  const [selection, setSelection] = useState<PvSelection>('v4');

  // 진행 중 판 추적 (abandoned 기록용). ref 라 언마운트 cleanup 에서도 최신값을 본다.
  const playRef = useRef<{ map: PvTierMapResponse | null; ended: boolean; moves: number; blind: boolean }>({
    map: null, ended: false, moves: 0, blind: false,
  });
  const observerRef = useRef<MutationObserver | null>(null);

  const loadLevels = useCallback(async () => {
    try {
      const res = await fetchPvLevels(selection);
      setLevels(res.levels);
      setCopyId(res.copyId);
      setError(null);
    } catch (e) {
      setLevels([]); // 다른 선별의 목록이 남아 섞이지 않게 (예: DDA 세트 파일 아직 없음 → 404)
      setError(`레벨 목록 로드 실패 (${selection}): ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [selection]);

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await fetchPvResultsSummary(selection));
    } catch {
      /* 요약 실패는 플레이에 영향 없음 */
    }
  }, [selection]);

  useEffect(() => {
    loadLevels();
    loadSummary();
  }, [loadLevels, loadSummary]);

  const level = useMemo(
    () => levels.find((l) => l.level === selectedLevel) ?? null,
    [levels, selectedLevel],
  );

  const available = useMemo(
    () => (level ? TIER_ORDER.filter((t) => level.availableTiers.includes(t)) : []),
    [level],
  );

  // 레벨 변경 / 블라인드 켬 → 새 무작위 순서, 공개 상태 초기화
  useEffect(() => {
    setBlindOrder(shuffled(available));
    setRevealed(new Set());
  }, [available, blind]);

  const tierName = (tier: PvTier) => {
    if (!blind || revealed.has(tier)) return TIER_LABEL[tier];
    return `변형 ${BLIND_LABELS[blindOrder.indexOf(tier)] ?? '?'}`;
  };

  const recordResult = useCallback(async (map: PvTierMapResponse, outcome: Outcome, moves: number, isBlind: boolean) => {
    await postPvResult({
      level: map.level,
      tier: map.tier,
      seed: map.seed,
      typesHash: map.typesHash,
      won: outcome === 'won',
      outcome,
      moves,
      // 1수 = 보드 타일 1개 선택 → 보드 잔여 근사 = 총 타일 - 수 (트레이에 남은 타일 미포함)
      boardRemainingApprox: outcome === 'won' ? 0 : Math.max(0, map.tileCount - moves),
      trayMaxOccupancy: null, // GamePlayer 가 트레이 이력을 노출하지 않음
      blind: isBlind,
      playedAt: new Date().toISOString(),
      selection: map.selection,
      utc: map.utc,
    });
  }, []);

  /** 끝나지 않은 판(1수 이상)을 abandoned 로 기록하고 추적 초기화 */
  const abandonIfInProgress = useCallback(() => {
    const st = playRef.current;
    if (st.map && !st.ended && st.moves >= 1) {
      recordResult(st.map, 'abandoned', st.moves, st.blind)
        .then(loadSummary)
        .catch(() => { /* 이탈 중 실패는 무시 */ });
    }
    st.ended = false;
    st.moves = 0;
  }, [recordResult, loadSummary]);

  // 탭 이탈(언마운트) 시 진행 중 판 기록
  useEffect(() => () => {
    observerRef.current?.disconnect();
    abandonIfInProgress();
  }, [abandonIfInProgress]);

  // GamePlayer 래퍼: 이동 수 관찰
  const gameWrapRef = useCallback((el: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!el) return;
    const obs = new MutationObserver(() => {
      const m = readMovesFromDom(el);
      if (m != null) playRef.current.moves = m;
    });
    obs.observe(el, { subtree: true, childList: true, characterData: true });
    observerRef.current = obs;
  }, []);

  // Restart / Play Again 클릭 캡처 (GamePlayer 핸들러보다 먼저 실행 → 리셋 전 이동 수로 기록)
  const handleGameClickCapture = (e: React.MouseEvent) => {
    const label = (e.target as HTMLElement).closest('button')?.textContent ?? '';
    if (label.includes('Restart') || label.includes('Play Again')) abandonIfInProgress();
  };

  const startTier = async (tier: PvTier) => {
    if (selectedLevel == null) return;
    abandonIfInProgress();
    setLoading(true);
    setLastResult(null);
    try {
      const map = await fetchPvTierMap(selectedLevel, tier, selection);
      playRef.current = { map, ended: false, moves: 0, blind };
      setCurrent(map);
      setError(null);
    } catch (e) {
      setError(`맵 로드 실패 (${selectedLevel}/${tier}): ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleGameEnd = async (won: boolean, stats: { moves: number }) => {
    if (!current) return;
    const tier = current.tier;
    playRef.current.ended = true;
    let saved = false;
    try {
      await recordResult(current, won ? 'won' : 'lost', stats.moves, blind);
      saved = true;
    } catch (e) {
      setError(`결과 기록 실패: ${e instanceof Error ? e.message : String(e)}`);
    }
    setLastResult({ tier, won, moves: stats.moves, saved });
    if (blind) setRevealed((prev) => new Set(prev).add(tier));
    loadSummary();
  };

  // ── 플레이 화면 ──
  if (current) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-300">
            레벨 {current.level} · <b>{tierName(current.tier)}</b>
          </span>
          {!blind && (
            <span className="text-gray-500 font-mono">
              {current.selection} · seed {current.seed ?? '(원맵)'} · utc {current.utc}
              {current.utc !== current.utc0 && <span className="text-amber-400"> (원맵 {current.utc0})</span>} · typesHash{' '}
              {current.typesHash.slice(0, 10)}
              {current.verification?.tier && (
                <span className={`ml-2 ${VERDICT_BADGE[current.verification.tier.verdict].cls}`}
                  title={current.verification.tier.reasons.join(', ') || VERDICT_BADGE[current.verification.tier.verdict].title}>
                  검증 {VERDICT_BADGE[current.verification.tier.verdict].text}
                </span>
              )}
            </span>
          )}
          {lastResult && (
            <span className={lastResult.won ? 'text-green-400' : 'text-red-400'}>
              {lastResult.won ? '성공' : '실패'} ({lastResult.moves}수) — 이 판:{' '}
              <b>{TIER_LABEL[lastResult.tier]}</b> {lastResult.saved ? '· 기록됨' : '· 기록 실패'}
            </span>
          )}
        </div>
        <div
          ref={gameWrapRef}
          onClickCapture={handleGameClickCapture}
          className="h-[calc(100vh-240px)] min-h-[700px] relative"
          data-testid="pv-game"
        >
          <GamePlayer
            levelData={current.levelJson}
            levelInfo={{
              id: `pv_${current.level}_${blind ? 'blind' : current.tier}`,
              name: `레벨 ${current.level} · ${tierName(current.tier)}`,
              source: 'local',
              totalTiles: current.tileCount,
              layers: Number(current.levelJson.layer) || 0,
            }}
            onGameEnd={handleGameEnd}
            onBack={() => {
              abandonIfInProgress();
              playRef.current.map = null;
              setCurrent(null);
              setLastResult(null);
            }}
          />
        </div>
      </div>
    );
  }

  // ── 선택 화면 ──
  const tierButtons = blind ? blindOrder : available;
  const levelSummary = selectedLevel != null ? summary[String(selectedLevel)] ?? {} : {};

  return (
    <div className="p-4 space-y-4" data-testid="pv-seed-play">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-white">시드 변형 플레이</h3>
          <p className="text-xs text-gray-400">
            샌드박스 {copyId || '...'} (읽기 전용) · 배정은 서버 cs_shuffle(클라 일치 포트) · 결과는
            manual_play/results.jsonl 에 기록
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-gray-300">
            선별
            <select
              value={selection}
              onChange={(e) => {
                setSelection(e.target.value as PvSelection);
                setSelectedLevel(null);
              }}
              className="bg-gray-700 rounded px-2 py-1 text-sm"
              data-testid="pv-selection"
            >
              {SELECTIONS.map((v) => (
                <option key={v} value={v}>{SELECTION_LABEL[v]}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={blind}
              onChange={(e) => setBlind(e.target.checked)}
              data-testid="pv-blind-toggle"
            />
            블라인드 모드
          </label>
          <button
            onClick={() => {
              loadLevels();
              loadSummary();
            }}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
          >
            새로고침
          </button>
        </div>
      </div>

      {error && <div className="p-2 bg-red-900/40 text-red-300 text-sm rounded">{error}</div>}

      {/* 레벨 목록 */}
      <div className="flex flex-wrap gap-2">
        {levels.map((l) => {
          const s = summary[String(l.level)];
          const attempts = s ? Object.values(s).reduce((n, v) => n + (v?.attempts ?? 0) + (v?.abandoned ?? 0), 0) : 0;
          return (
            <button
              key={l.level}
              onClick={() => setSelectedLevel(l.level)}
              title={l.reason ?? l.status}
              data-testid={`pv-level-${l.level}`}
              className={`px-2 py-1 rounded text-sm border ${
                selectedLevel === l.level ? 'border-indigo-400' : 'border-transparent'
              } ${STATUS_STYLE[l.status] ?? 'bg-gray-700 text-gray-300'}`}
            >
              {l.level}
              {!blind && l.verification && (
                <span className={`ml-1 ${VERDICT_BADGE[l.verification.verdict].cls}`}
                  data-testid={`pv-verdict-${l.level}`}>
                  {VERDICT_BADGE[l.verification.verdict].text}
                </span>
              )}
              {attempts > 0 && <span className="ml-1 text-xs opacity-70">({attempts})</span>}
            </button>
          );
        })}
      </div>
      <div className="text-xs text-gray-500">
        상태: <span className="text-green-300">5tier</span> 원맵+5칸 · <span className="text-teal-300">3tier</span> 원맵·기준·쉬움2·어려움2 ·{' '}
        <span className="text-gray-400">fixed_map</span> 원맵만 (v2/v3 는 있는 시드만 · DDA 세트 = 원본 + seedvar 토큰 칸 e2/e1/h1/h2, 원본 대비 Δ ·
        '참고: 구운' 칸은 reference_baked 행 그대로)
        {!blind && <> · 검증 배지 ✓ 통과 / ⚠ 경고(방향 신뢰 실패·바깥 |Δ|&lt;0.08) / ? 검증 후 시드 변경</>}
      </div>

      {level && (
        <div className="p-4 bg-gray-800 rounded-lg space-y-3">
          <div className="text-sm text-gray-300">
            레벨 <b>{level.level}</b> · 상태 <b>{level.status}</b>
            {level.utc != null && <> · utc {level.utc}</>}
            {!blind && level.verification && (
              <span className={VERDICT_BADGE[level.verification.verdict].cls}>
                {' '}· 검증 {VERDICT_BADGE[level.verification.verdict].text}
                {level.verification.innerUnstable.length > 0 && ` (내부 서열 불안정 ${level.verification.innerUnstable.join(', ')})`}
              </span>
            )}
            {level.wOrig != null && !blind && <> · 봇 원맵 승률 {level.wOrig.toFixed(3)}</>}
            {level.reason && <span className="text-gray-500"> · {level.reason}</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            {tierButtons.map((t) => (
              <button
                key={t}
                disabled={loading}
                onClick={() => startTier(t)}
                data-testid={`pv-tier-${blind ? BLIND_LABELS[blindOrder.indexOf(t)] : t}`}
                className="px-4 py-2 bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 rounded text-sm font-medium"
              >
                {tierName(t)}
                {!blind && t !== 'orig' && level.tierUtc[t] != null && level.tierUtc[t] !== level.utc && (
                  <span className="ml-1 text-xs text-amber-300">utc{level.tierUtc[t]}</span>
                )}
                {!blind && level.verification?.tiers[t] && (
                  <span
                    className={`ml-1 ${VERDICT_BADGE[level.verification.tiers[t]!.verdict].cls}`}
                    title={level.verification.tiers[t]!.reasons.join(', ') || '독립 검증 통과'}
                    data-testid={`pv-tier-verdict-${t}`}
                  >
                    {VERDICT_BADGE[level.verification.tiers[t]!.verdict].text}
                  </span>
                )}
                {!blind && level.deltas[t] != null && (
                  <span className="ml-1 text-xs opacity-70">
                    Δ{level.deltas[t]! >= 0 ? '+' : ''}
                    {level.deltas[t]!.toFixed(3)}
                  </span>
                )}
              </button>
            ))}
          </div>

          {blind ? (
            <div className="text-xs text-gray-400">
              블라인드: tier 이름·시드·요약 숨김, 순서 무작위. 판이 끝나면 해당 변형이 공개됩니다.
            </div>
          ) : (
            <table className="text-sm text-gray-300" data-testid="pv-summary">
              <thead>
                <tr className="text-gray-500">
                  <th className="pr-4 text-left">tier</th>
                  {available.map((t) => (
                    <th key={t} className="pr-4 text-left">{TIER_LABEL[t]}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="pr-4 text-gray-500">성공/완료판</td>
                  {available.map((t) => {
                    const v = levelSummary[t];
                    return (
                      <td key={t} className="pr-4 font-mono">
                        {v ? `${v.wins}/${v.attempts}${v.abandoned ? ` (중단 ${v.abandoned})` : ''}` : '-'}
                      </td>
                    );
                  })}
                </tr>
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

export default PvSeedPlayPanel;

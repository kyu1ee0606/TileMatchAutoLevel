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
import { PROFESSIONAL_GIMMICK_UNLOCK_LEVELS } from '../types/levelSet';

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
  { id: 'unknown', label: '📦 상자', color: '#c8a97e' },
  { id: 'teleport', label: '🌀 텔레포터', color: '#22d3ee' },
  { id: 'chain', label: '⛓ 체인', color: '#a8a29e' },
  { id: 'grass', label: '🌿 잔디', color: '#86efac' },
  { id: 'frog', label: '🐸 개구리', color: '#4ade80' },
  { id: 'bomb', label: '💣 폭탄', color: '#f87171' },
  { id: 'curtain_close', label: '🎭 커튼', color: '#c084fc' },
  { id: 'craft', label: '🔨 공예', color: '#fbbf24' },
  { id: 'stack', label: '📚 스택', color: '#60a5fa' },
  { id: '__erase', label: '🗑 기믹지움', color: '#4b5563' },
];
// craft/stack = 컨테이너 기믹(셀 1개 + 내부 ÷3). 수동 배치 시 위치·개수 고정 → 타일수 결정적.

// 팔레트 id → 언락 테이블 키(PROFESSIONAL_GIMMICK_UNLOCK_LEVELS). 게임 언락 정합.
const PALETTE_UNLOCK_KEY: Record<string, string> = {
  ice: 'ice', unknown: 'unknown', teleport: 'teleport', chain: 'chain', grass: 'grass', frog: 'frog', bomb: 'bomb', curtain_close: 'curtain',
  craft: 'craft', stack: 'stack',
};
// 컨테이너 기믹 값 파싱: "craft_e_3"(방향e·내부3) 또는 구포맷 "craft"(내부3·방향auto).
const parseContainer = (gim: string | undefined): { type: 'craft' | 'stack'; dir: string; inner: number } | null => {
  if (!gim) return null;
  const m = gim.match(/^(craft|stack)(?:_([ewsn])_(\d+))?$/);
  if (!m) return null;
  return { type: m[1] as 'craft' | 'stack', dir: m[2] || 'e', inner: m[3] ? parseInt(m[3]) : 3 };
};
const DIR_ARROW: Record<string, string> = { e: '→', w: '←', s: '↓', n: '↑' };
const DIR_LABEL: { id: string; label: string }[] = [
  { id: 'n', label: '↑상' }, { id: 's', label: '↓하' }, { id: 'w', label: '←좌' }, { id: 'e', label: '→우' },
];
// 특정 기믹 언락 레벨(없거나 도형/지움이면 0 = 항상 사용). 미정 키는 999.
const unlockOf = (paletteId: string): number => {
  const k = PALETTE_UNLOCK_KEY[paletteId];
  if (!k) return 0;
  return (PROFESSIONAL_GIMMICK_UNLOCK_LEVELS as Record<string, number>)[k] ?? 999;
};
// 전체 기믹 언락표(그리기 탭 참조용) — 라벨 + 언락레벨, 오름차순.
const GIMMICK_UNLOCK_REF: { label: string; level: number }[] = [
  { label: '🔨 공예(craft)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.craft },
  { label: '📚 스택(stack)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.stack },
  { label: '🧊 얼음(ice)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.ice },
  { label: '🔗 연결(link)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.link },
  { label: '⛓ 체인(chain)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.chain },
  { label: '🔑 잠금(key)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.key },
  { label: '🌿 잔디(grass)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.grass },
  { label: '📦 상자(unknown)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.unknown },
  { label: '🎭 커튼(curtain)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.curtain },
  { label: '💣 폭탄(bomb)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.bomb },
  { label: '⏱ 타임어택(time_attack)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.time_attack },
  { label: '🐸 개구리(frog)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.frog },
  { label: '🌀 텔레포터(teleport)', level: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS.teleport },
].sort((a, b) => a.level - b.level);

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
  // [테마2 · 치유의 아틀리에 (로즈·온실) · 구역 6~10 · 110~280] 서버 star cost 기반(챕터당 37 star=37레벨).
  // 커버: 6구역 101~137(보스110·120·130), 7구역 138~174(140·150·160·170), 8구역 175~211(180·190·200·210),
  //       9구역 212~248(220·230·240), 10구역 249~285(250·260·270·280). 각 챕터 마지막 보스=최종 deco.
  // 셰이프 = 해금 deco 순서 무관, 챕터 범위서 식별성·임팩트·좌우대칭 우선 선정. deco=근거 오브젝트.
  '110': { chapter: '6 온실 입구', beat: '유리 온실 실루엣', deco: 'deco_6_1 할아버지의 꿈이 잠든 유리 온실', shape: '🏠 유리 온실(집형 대칭)', note: '구역6 · 도입 임팩트' },
  '120': { chapter: '6 온실 입구', beat: '입구 쌍둥이 화분', deco: 'deco_6_7 입구를 다정히 지키는 쌍둥이 대형 화분', shape: '⚱️ 쌍둥이 대형 화분(좌우대칭)', note: '식별성↑' },
  '130': { chapter: '6 피날레', beat: '웅장한 이중문', deco: 'deco_6_3 세월의 온기가 깃든 이중문', shape: '🚪 이중문(대칭, 임팩트)', note: '구역6 완성' },
  '140': { chapter: '7 향기 작업실', beat: '유리 증류기', deco: 'deco_7_2 신비로운 빛을 머금은 유리 증류기', shape: '⚗️ 증류기(플라스크 대칭)', note: '구역7' },
  '150': { chapter: '7 향기 작업실', beat: '황금 천칭', deco: 'deco_7_4 향을 가늠하는 황금빛 천칭', shape: '⚖️ 천칭(완전 좌우대칭)', note: '대칭 명료' },
  '160': { chapter: '7 향기 작업실', beat: '색색 시험관', deco: 'deco_7_5 영롱한 색채를 담은 유리 시험관', shape: '🧪 시험관 세트(나란한 열)', note: '식별성↑' },
  '170': { chapter: '7 피날레', beat: '비밀 레시피 노트', deco: 'deco_7_10 할아버지의 온기가 잠든 비밀 노트', shape: '📖 펼친 책(대칭)', note: '구역7 완성' },
  '180': { chapter: '8 난초 배양실', beat: '계단식 배양대', deco: 'deco_8_2 햇살을 나눠 담는 계단식 원목 화분 선반', shape: '🪴 계단식 선반(피라미드 대칭)', note: '구역8' },
  '190': { chapter: '8 난초 배양실', beat: '이끼 벽정원', deco: 'deco_8_5 벽을 타고 흐르는 초록빛 이끼 정원', shape: '🌿 이끼 벽정원(넓은 면)', note: '' },
  '200': { chapter: '8 난초 배양실', beat: '유리 배양 상자', deco: 'deco_8_6 새 생명을 품은 투명 유리 배양 상자', shape: '🔲 유리 배양 상자(정형)', note: '라운드 마일스톤' },
  '210': { chapter: '8 피날레', beat: '여왕 난초 개화', deco: 'deco_8_3 할아버지가 평생을 바쳐 피워낸 여왕 난초', shape: '🌺 여왕 난초(거대·최대 임팩트)', note: '구역8 하이라이트' },
  '220': { chapter: '9 향기 상담실', beat: '티코지 찻주전자', deco: 'deco_9_3 온기를 머금은 손뜨개 티코지', shape: '🫖 찻주전자(주둥이+손잡이)', note: '구역9 · 식별성↑' },
  '230': { chapter: '9 향기 상담실', beat: '벨벳 소파', deco: 'deco_9_2 포근함에 잠기는 벨벳 소파 세트', shape: '🛋️ 벨벳 소파(좌우대칭)', note: '' },
  '240': { chapter: '9 피날레', beat: '할아버지의 명화', deco: 'deco_9_10 할아버지가 사랑한 고전 풍경화 액자', shape: '🖼️ 명화 액자(직사각 대칭)', note: '구역9 완성' },
  '250': { chapter: '10 향기 분수 정원', beat: '대리석 조각 분수', deco: 'deco_10_3 꽃을 든 여인의 대리석 조각 분수', shape: '⛲ 조각상 분수(대칭)', note: '구역10 클라이맥스' },
  '260': { chapter: '10 향기 분수 정원', beat: '노래하는 파랑새', deco: 'deco_10_8 노래를 주고받는 파랑새 두 마리', shape: '🐦 파랑새 두 마리(좌우대칭)', note: 'deco_08 교체본' },
  '270': { chapter: '10 향기 분수 정원', beat: '대형 꽃 아치', deco: 'deco_10_9 온실의 봄을 여는 화려한 대형 꽃 아치', shape: '🌸 대형 꽃 아치', note: '' },
  '280': { chapter: '10 피날레 (테마2 완결)', beat: '금빛 감사패 + 두 번째 편지', deco: 'deco_10_10 마을의 마음을 새긴 할아버지의 금빛 감사패와 두 번째 편지', shape: '🏵️ 금빛 감사패 / 💌 편지', note: '100(첫 편지)과 수미상관, 테마2 완결' },
};

// [테마 단위] 게임 서버 star cost 누적 기반 실제 커버 레벨. 테마=5챕터. 보스=10단위.
// 테마1: 100 star → Lv1~100 → 보스 10~100. 테마2: +185 → Lv101~285 → 보스 110~280.
const THEMES: { name: string; minBoss: number; maxBoss: number }[] = [
  { name: '테마1 · 잊혀진 온기 (챕터 1~5)', minBoss: 10, maxBoss: 100 },
  { name: '테마2 · 치유의 아틀리에 (챕터 6~10)', minBoss: 110, maxBoss: 280 },
];
// 정의된 테마 밖(신규 레벨)은 잠정 테마(마지막+1~)로 100단위 버킷.
const themeOf = (level: number): number => {
  const i = THEMES.findIndex(t => level >= t.minBoss && level <= t.maxBoss);
  if (i >= 0) return i;
  const last = THEMES[THEMES.length - 1];
  if (level > last.maxBoss) return THEMES.length + Math.floor((level - last.maxBoss - 10) / 100);
  return 0;
};
const themeLabel = (t: number) => THEMES[t]?.name || `테마${t + 1} (미정의 · 서버 테이블 필요)`;
const themeLevelRange = (t: number) => THEMES[t]
  ? `Lv${THEMES[t].minBoss}~${THEMES[t].maxBoss}`
  : `Lv${(THEMES[THEMES.length - 1]?.maxBoss ?? 0) + 10 + (t - THEMES.length) * 100}~`;

export function BossTemplatePanel() {
  const { addNotification } = useUIStore();

  const [name, setName] = useState('');
  const [bossLevel, setBossLevel] = useState(10); // 이 템플릿이 배정될 단일 보스 레벨(10의 배수)
  const emptyLayer = (): BossLayer => ({ positions: new Set(), gimmicks: new Map() });
  const [layers, setLayers] = useState<BossLayer[]>([emptyLayer(), emptyLayer(), emptyLayer()]);
  const [activeLayer, setActiveLayer] = useState(0);
  const [paintMode, setPaintMode] = useState<string>(''); // '' = 모양, 'ice'.. = 기믹, '__erase' = 기믹지움
  const [containerDir, setContainerDir] = useState<string>('e'); // craft/stack 방향(상하좌우)
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
  const [themeIndex, setThemeIndex] = useState(0); // 현재 보는 테마(5챕터 단위)
  const loadConcepts = useCallback(async () => {
    try {
      const res = await apiClient.get('/debug/boss-concepts');
      const map = res.data.boss_concepts || {};
      if (!Object.keys(map).length) {
        setConcepts({ ...DEFAULT_CONCEPTS });  // 서버 비어있으면 전체 기본(10~200) 씨딩
      } else {
        // 서버 값 우선, 없는 레벨만 DEFAULT 보충 → 기존 편집 보존하며 신규 테마(110~200) 자동 노출
        const merged = { ...map };
        let added = false;
        for (const [lv, c] of Object.entries(DEFAULT_CONCEPTS)) {
          if (!(lv in merged)) { merged[lv] = c; added = true; }
        }
        setConcepts(merged);
        if (added) setConceptsDirty(true);  // 보충됐으면 저장 유도
      }
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
    setThemeIndex(themeOf(next)); // 새 레벨이 속한 테마로 이동
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

  // [난이도 파악] 현재 편집중 템플릿을 특정 레벨로 생성 → RL 예측/목표 클리어율.
  // 목표난이도는 해당 레벨의 프로덕션 난이도곡선에서 자동 산출(슬라이더 아님).
  const [estimating, setEstimating] = useState(false);
  const [estResult, setEstResult] = useState<{ predicted: number; target: number; cls: string; td: number; useTileCount: number; tiles: number; drawn: number; chainStripped: number; grassStripped: number; t0: number; containers: number; inner: number; visual: number } | null>(null);
  // skill_mean = 난이도 기준 실력(0 초보~1 고수). 기본=프로덕션 슬라이더값(localStorage), 조절 가능.
  const [estSkillMean, setEstSkillMean] = useState<number>(() => {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem('prod_rl_skill_mean_v1') : null;
    const v = parseFloat(raw ?? '');
    return isNaN(v) ? 0.47 : v;
  });

  // hard_steep 타일종류 그래프 (백엔드 TILE_TYPE_PROFILES.hard_steep 미러): (maxLevel, V)
  const hardSteepTileCount = (level: number) => {
    const brackets: [number, number][] = [[3, 4], [10, 5], [30, 8], [60, 10], [100, 11], [225, 11], [600, 12], [1125, 12], [99999, 13]];
    for (const [cap, v] of brackets) if (level <= cap) return v;
    return 13;
  };
  // 타일 종류 (슬라이더). 기본 = 그 보스 레벨의 hard_steep 그래프값.
  const [estTileCount, setEstTileCount] = useState<number>(() => hardSteepTileCount(10));
  useEffect(() => { setEstTileCount(hardSteepTileCount(bossLevel)); }, [bossLevel]);

  // 보스 목표 클리어율 스케일 (레벨대별 완화 — ProductionDashboard와 동일)
  const bossScale = (level: number) => (level <= 30 ? 0.75 : level <= 100 ? 0.65 : 0.5);

  // 프로덕션 난이도곡선 (톱니바퀴 1500 기본: start0.1 end0.95, 150세트, 10/세트). 보스=localIdx10 +0.1.
  const productionDifficulty = (level: number) => {
    const start = 0.1, end = 0.95, totalSets = 150, perSet = 10;
    const setIdx = Math.floor((level - 1) / perSet);
    const localIdx = ((level - 1) % perSet) + 1;
    const base = start + (end - start) * setIdx / Math.max(1, totalSets - 1);
    const bonus = localIdx === 10 ? 0.1 : ((localIdx - 1) / (perSet - 1)) * 0.05;
    return Math.min(0.95, base + bonus);
  };

  const estimateDifficulty = async () => {
    if (layers.every(l => l.positions.size === 0)) { addNotification('warning', '빈 템플릿 — 셀을 찍으세요'); return; }
    setEstimating(true); setEstResult(null);
    try {
      const td = productionDifficulty(bossLevel);
      const inlineLayers = layers.map((l, i) => ({
        layer: i, col: layerSize(i), row: layerSize(i), positions: [...l.positions],
        gimmicks: Object.fromEntries(l.gimmicks),
      }));
      const gen = await apiClient.post('/generate/from-boss-template', {
        level_number: bossLevel, target_difficulty: td, layers: inlineLayers, apply_gimmicks: true,
        use_tile_count_override: estTileCount, // 슬라이더 종류수 직접 적용
      });
      const rl = await apiClient.post('/rl-sim/level', {
        level_json: gen.data.level_json, target_difficulty: td, skill_mean: estSkillMean,
        target_clear_rate_scale: bossScale(bossLevel), // 레벨대별 완화(초반 ×0.75)
      });
      setEstResult({
        predicted: rl.data.predicted_clear_rate, target: rl.data.target_clear_rate, cls: rl.data.classification, td,
        useTileCount: gen.data.level_json?.useTileCount ?? 0, tiles: gen.data.tile_count ?? 0,
        drawn: layers.reduce((a, l) => a + l.positions.size, 0), // 그린 셀 수(생성 전)
        chainStripped: gen.data.chain_stripped ?? 0, // 좌우 이웃없어 무효처리된 체인
        grassStripped: gen.data.grass_stripped ?? 0, // 4방 이웃없어 무효처리된 잔디
        t0: gen.data.t0_count ?? 0, containers: gen.data.container_count ?? 0,
        inner: gen.data.inner_count ?? 0, visual: gen.data.visual_count ?? (gen.data.tile_count ?? 0),
      });
    } catch (e) {
      addNotification('error', `난이도 파악 실패: ${(e as Error).message}`);
    } finally { setEstimating(false); }
  };

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
      } else if (paintMode === 'craft' || paintMode === 'stack') {
        // 컨테이너: 클릭당 내부 +1. 최초 클릭 = t0 있든없든 셀 점유 + 내부 1. 방향=현재 선택.
        // (생성 시 백엔드가 ÷3 클램프해 클리어 보장 — 편집기는 1단위 세밀 조정.)
        L.positions.add(key);
        const cur = parseContainer(L.gimmicks.get(key));
        const inner = cur && cur.type === paintMode ? cur.inner + 1 : 1; // 같은 타입이면 +1, 아니면 새로 1
        L.gimmicks.set(key, `${paintMode}_${containerDir}_${inner}`);
      } else {
        // 속성 기믹 — 셀이 켜져있어야(t0) 함
        if (L.positions.has(key)) L.gimmicks.set(key, paintMode);
      }
      return next;
    });
  }, [activeLayer, paintMode, containerDir]);

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
    setName(''); setBossLevel(10);
    setLayers([emptyLayer(), emptyLayer(), emptyLayer()]);
    setActiveLayer(0); setEditingId(null); setPaintMode('');
  };

  // 테두리 1겹 침식(피라미드용): 이웃 4방향 중 하나라도 off면 제거
  const erode = (pos: Set<string>): Set<string> => {
    const out = new Set<string>();
    pos.forEach(k => {
      const [x, y] = k.split('_').map(Number);
      if (pos.has(`${x - 1}_${y}`) && pos.has(`${x + 1}_${y}`) && pos.has(`${x}_${y - 1}`) && pos.has(`${x}_${y + 1}`)) out.add(k);
    });
    return out;
  };

  // [C: AI 모양 생성] 설명 → LLM이 8/7 그리드 생성 → 층 반영. 좌우대칭 옵션.
  const [llmDesc, setLlmDesc] = useState('');
  const [llmBusy, setLlmBusy] = useState(false);
  const [llmSymmetric, setLlmSymmetric] = useState(true);
  const applyLlmShape = async (mode: 'current' | 'all' | 'pyramid') => {
    if (!llmDesc.trim()) { addNotification('warning', '모양 설명 입력 (예: 왕관, 고양이 얼굴)'); return; }
    setLlmBusy(true);
    try {
      const res = await apiClient.post('/debug/boss-shape-llm', {
        description: llmDesc.trim(), sizes: [8, 7], symmetric: llmSymmetric,
      });
      const grids: Record<string, string[]> = res.data.grids || {};
      setLayers(prev => prev.map((l, i) => {
        const size = layerSize(i);
        if (mode === 'current' && i !== activeLayer) return l;
        let pos = new Set<string>(grids[String(size)] || []);
        if (mode === 'pyramid') {
          const erosions = (prev.length - 1) - i;
          for (let e = 0; e < erosions; e++) pos = erode(pos);
        }
        return { positions: pos, gimmicks: new Map(l.gimmicks) };
      }));
      addNotification('success', `LLM 모양 "${llmDesc}" 생성 → ${mode === 'current' ? `L${activeLayer}` : mode === 'all' ? '전층' : '피라미드'}`);
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } } };
      addNotification('error', `LLM 실패: ${err.response?.data?.detail || (e as Error).message}`);
    } finally { setLlmBusy(false); }
  };

  const totalCells = layers.reduce((a, l) => a + l.positions.size, 0);
  // [라이브 총타일수] 매치 대상 = 일반셀 1 + 컨테이너 내부(배출). 컨테이너 셀 자체는 제외.
  // 생성 전 추정(÷3 보정 전) — 컨테이너 내부 클릭 증가가 즉시 반영됨.
  const liveTiles = layers.reduce((a, l) => {
    let s = 0;
    for (const pos of l.positions) {
      const c = parseContainer(l.gimmicks.get(pos));
      s += c ? c.inner : 1;  // 컨테이너: 내부만(셀 제외) / 일반: 1
    }
    return a + s;
  }, 0);

  const save = async () => {
    if (totalCells === 0) { addNotification('warning', '빈 템플릿 — 셀을 찍으세요'); return; }
    // [stack 겹침 차단] stack 오프셋 방향이 전부 막힌 셀 = 주변 일반타일 덮지만 선택가능(착각) → 저장 차단.
    // (craft는 게임이 배출위치 처리 → 제외.)
    const D: Record<string, [number, number]> = { e: [1, 0], w: [-1, 0], s: [0, 1], n: [0, -1] };
    for (let i = 0; i < layers.length; i++) {
      const P = layers[i].positions; const sz = layerSize(i);
      for (const [pos, g] of layers[i].gimmicks) {
        const c = parseContainer(g); if (!c || c.type !== 'stack') continue;
        if (!P.has(pos)) continue;
        const [x, y] = pos.split('_').map(Number);
        const steps = Math.max(1, Math.floor((c.inner - 1) * 0.1) + 1);
        const clearDir = (d: string) => {
          const [dx, dy] = D[d];
          for (let s = 1; s <= steps; s++) {
            const nx = x + dx * s, ny = y + dy * s;
            if (nx < 0 || nx >= sz || ny < 0 || ny >= sz) return false;
            if (P.has(`${nx}_${ny}`)) return false;
          }
          return true;
        };
        if (!Object.keys(D).some(clearDir)) {
          addNotification('error', `L${i} ${pos} ${c.type} 오프셋 방향 전부 막힘(겹침) → 주변 비우거나 이동 후 저장`);
          return;
        }
      }
    }
    // ÷3 안내(경고만): 총 t0가 3의 배수여야 클리어 가능(생성기가 최종 보정하나 근접 권장)
    const id = editingId || `boss_L${bossLevel}_${totalCells}c_${layers.length}L`;
    const body = {
      id,
      name: name || id,
      level_min: bossLevel,  // 단일 레벨 = min==max
      level_max: bossLevel,
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
    setName(t.name); setBossLevel(t.level_min);
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
        층마다 다른 모양 가능. 저장 시 <b>지정한 보스 레벨(10의 배수)</b>에 배정됨.
      </div>

      {/* 메타 */}
      <div className="grid grid-cols-3 gap-3 bg-gray-800 rounded p-3">
        <div className="col-span-2">
          <label className="block text-[11px] text-gray-400 mb-1">이름</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="예: 고양이얼굴"
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white" />
        </div>
        <div>
          <label className="block text-[11px] text-gray-400 mb-1">보스 레벨 (10의 배수)</label>
          <input type="number" value={bossLevel} min={10} step={10} onChange={e => setBossLevel(parseInt(e.target.value) || 10)}
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
        <span className="text-[11px] text-gray-500 ml-2">총 {layers.length}층 · {totalCells}셀 · <b className="text-cyan-400">타일 {liveTiles}개</b>{liveTiles !== totalCells && <span className="text-gray-500"> (컨테이너 내부 포함)</span>} {liveTiles % 3 !== 0 && <span className="text-yellow-400">(÷3 아님 — 생성기 보정)</span>}</span>
      </div>

      {/* C: LLM 모양 생성 — 설명 → AI가 그리드 생성 */}
      <div className="p-3 bg-gradient-to-r from-cyan-900/20 to-blue-900/20 border border-cyan-700/30 rounded space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-white">🤖 AI 모양 생성</span>
          <input value={llmDesc} onChange={e => setLlmDesc(e.target.value)}
            className="flex-1 min-w-[200px] px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            placeholder="모양 설명 (예: 왕관, 고양이 얼굴, 우체통, 찻잔)" />
          <button onClick={() => applyLlmShape('current')} disabled={llmBusy} className="px-2 py-1 rounded text-[11px] bg-cyan-700 hover:bg-cyan-600 text-white disabled:opacity-50">{llmBusy ? '생성중…' : '현재층'}</button>
          <button onClick={() => applyLlmShape('all')} disabled={llmBusy} className="px-2 py-1 rounded text-[11px] bg-cyan-800 hover:bg-cyan-700 text-white disabled:opacity-50">전층</button>
          <button onClick={() => applyLlmShape('pyramid')} disabled={llmBusy} className="px-2 py-1 rounded text-[11px] bg-blue-700 hover:bg-blue-600 text-white disabled:opacity-50">피라미드</button>
          <label className="flex items-center gap-1 text-[11px] text-gray-400">
            <input type="checkbox" checked={llmSymmetric} onChange={e => setLlmSymmetric(e.target.checked)} /> 좌우대칭
          </label>
        </div>
        <div className="text-[10px] text-gray-500">임의 모양 AI 생성(8×8·7×7). Claude Code CLI 인증 사용(API키 불필요). 호출당 ~수초+토큰 소비.</div>
      </div>

      {/* 그리기 그리드 */}
      <div className="flex gap-4">
        <div className="bg-gray-800 rounded p-3 select-none">
          <div className="text-[11px] text-gray-400 mb-2">
            L{activeLayer} · {cols}×{rows} · 모드: <b className="text-white">{GIMMICK_PALETTE.find(g => g.id === paintMode)?.label}</b>
            {paintMode !== '' && paintMode !== '__erase' && paintMode !== 'craft' && paintMode !== 'stack' && <span className="text-yellow-400"> (t0 셀에만 지정됨)</span>}
            {(paintMode === 'craft' || paintMode === 'stack') && <span className="text-amber-300"> (셀 클릭 = 내부+1 · 생성 시 ÷3 반올림)</span>}
          </div>
          {(paintMode === 'craft' || paintMode === 'stack') && (
            <div className="flex items-center gap-1 mb-2 text-[11px]">
              <span className="text-gray-400">방향:</span>
              {DIR_LABEL.map(d => (
                <button key={d.id} onClick={() => setContainerDir(d.id)}
                  className={`px-1.5 py-0.5 rounded border ${containerDir === d.id ? 'bg-amber-600 text-white border-amber-400 font-semibold' : 'bg-gray-700 text-gray-300 border-gray-600 hover:bg-gray-600'}`}
                  title={paintMode === 'craft' ? 'craft 출력(배출) 방향' : 'stack 시각 오프셋 방향'}>
                  {d.label}
                </button>
              ))}
              <span className="text-gray-500 ml-1">{paintMode === 'craft' ? '배출 방향(보드 안쪽 권장)' : '스택 오프셋'}</span>
            </div>
          )}
          <div className="flex gap-3">
          <div className="grid gap-0.5 flex-shrink-0" style={{ gridTemplateColumns: `repeat(${cols}, 28px)`, height: 'fit-content' }}>
            {Array.from({ length: rows }, (_, y) =>
              Array.from({ length: cols }, (_, x) => {
                const key = `${x}_${y}`;
                const on = layers[activeLayer].positions.has(key);
                const gim = layers[activeLayer].gimmicks.get(key);
                const cont = parseContainer(gim); // craft/stack 컨테이너 파싱
                const gcolor = cont
                  ? GIMMICK_PALETTE.find(g => g.id === cont.type)?.color
                  : (gim ? GIMMICK_PALETTE.find(g => g.id === gim)?.color : undefined);
                // [무효 기믹] chain=좌/우 이웃 필요, grass=4방 이웃 필요. 없으면 언클리어러블 → 생성기 자동제거.
                const P = layers[activeLayer].positions;
                const badChain = gim === 'chain' && !P.has(`${x - 1}_${y}`) && !P.has(`${x + 1}_${y}`);
                const n4 = (P.has(`${x - 1}_${y}`) ? 1 : 0) + (P.has(`${x + 1}_${y}`) ? 1 : 0) +
                  (P.has(`${x}_${y - 1}`) ? 1 : 0) + (P.has(`${x}_${y + 1}`) ? 1 : 0);
                const badGrass = gim === 'grass' && n4 < 2; // 게임 grass remaining=2 → 4방 이웃 ≥2
                const bad = badChain || badGrass;
                const badMsg = badChain ? '체인 무효(좌우 이웃 없음)' : '잔디 무효(4방 이웃 2개 미만)';
                // [stack 오프셋] stack 내부는 방향으로 시각 오프셋 쌓여 그 방향 일반타일을 덮지만 선택가능
                // → 착각. craft는 게임이 처리(문제없음) → stack만 검사. 막힘+대안있음=자동회전(amber),
                // 모든방향막힘=겹침(red).
                let contWarn: '' | 'rotate' | 'overlap' = '';
                if (cont && cont.type === 'stack') {
                  const steps = Math.max(1, Math.floor((cont.inner - 1) * 0.1) + 1);
                  const D: Record<string, [number, number]> = { e: [1, 0], w: [-1, 0], s: [0, 1], n: [0, -1] };
                  const clearDir = (d: string) => {
                    const [dx, dy] = D[d];
                    for (let s = 1; s <= steps; s++) {
                      const nx = x + dx * s, ny = y + dy * s;
                      if (nx < 0 || nx >= cols || ny < 0 || ny >= rows) return false;
                      if (P.has(`${nx}_${ny}`)) return false;
                    }
                    return true;
                  };
                  if (!clearDir(cont.dir)) contWarn = Object.keys(D).some(clearDir) ? 'rotate' : 'overlap';
                }
                const borderCls = !on ? 'bg-gray-700 border-gray-600 hover:bg-gray-600'
                  : bad || contWarn === 'overlap' ? 'border-red-500 border-2'
                  : contWarn === 'rotate' ? 'border-amber-400 border-2'
                  : 'border-indigo-300';
                const cellText = bad ? '⚠'
                  : contWarn === 'overlap' ? '⚠'
                  : cont ? `${cont.type === 'craft' ? '🔨' : '📚'}${cont.inner}${DIR_ARROW[cont.dir] || ''}`
                  : (gim ? (GIMMICK_PALETTE.find(g => g.id === gim)?.label.split(' ')[0] || '') : '');
                return (
                  <div key={key}
                    onMouseDown={() => {
                      if (paintMode === 'craft' || paintMode === 'stack') { applyCell(x, y, true); return; } // 클릭당 +1, 드래그 없음
                      const sv = paintMode === '' ? !on : true; setPainting(sv); applyCell(x, y, sv);
                    }}
                    onMouseEnter={() => { if (painting !== null) applyCell(x, y, painting); }}
                    className={`w-7 h-7 rounded-sm cursor-pointer border flex items-center justify-center text-[10px] leading-none ${borderCls}`}
                    style={on ? { background: gcolor || '#6366f1' } : undefined}
                    title={bad ? `${key} · ${badMsg} → 생성시 제거됨`
                      : contWarn === 'overlap' ? `${key} · ${cont?.type} 오프셋 방향 전부 막힘 → 주변 타일과 겹침! 주변 비우거나 위치 이동`
                      : contWarn === 'rotate' ? `${key} · ${cont?.type} 방향 ${cont?.dir} 막힘 → 생성시 빈 방향으로 자동회전`
                      : cont ? `${key} · ${cont.type} 방향 ${cont.dir} · 내부 ${cont.inner}개 (클릭=+1)`
                      : `${key}${gim ? ' · ' + gim : ''}`}>
                    {cellText}
                  </div>
                );
              })
            )}
          </div>
          {/* 기믹 팔레트 (세로) */}
          <div className="flex flex-col gap-1">
            <div className="text-[10px] text-gray-500 mb-0.5">기믹 팔레트</div>
            {GIMMICK_PALETTE.map(g => {
              const ul = unlockOf(g.id);              // 0 = 항상, 999 = 미정
              const locked = ul > 0 && ul < 999 && bossLevel < ul;
              return (
                <button key={g.id} onClick={() => setPaintMode(g.id)}
                  title={locked ? `L${ul} 언락 — 현재 보스 L${bossLevel}에선 미언락` : (ul > 0 && ul < 999 ? `L${ul} 언락` : undefined)}
                  className={`px-2 py-1.5 rounded text-[11px] border text-left whitespace-nowrap flex items-center justify-between gap-1.5 ${paintMode === g.id ? 'ring-2 ring-white font-semibold' : 'opacity-80 hover:opacity-100'} ${locked ? 'opacity-50' : ''}`}
                  style={{ background: g.id === '__erase' ? '#374151' : g.color, color: g.id === '' || g.id === '__erase' ? '#fff' : '#1f2937', borderColor: 'rgba(255,255,255,0.2)' }}>
                  <span>{g.label}</span>
                  {ul > 0 && ul < 999 && (
                    <span className={`text-[9px] font-bold px-1 rounded ${locked ? 'bg-red-600 text-white' : 'bg-black/25'}`}>
                      {locked ? '🔒' : ''}L{ul}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          </div>
          {/* 전체 기믹 언락표 — 현재 보스 레벨 기준 사용가능/잠금 표시 */}
          <div className="mt-2 bg-gray-900/60 rounded p-2">
            <div className="text-[10px] text-gray-400 mb-1">기믹 언락 레벨표 <span className="text-gray-500">(보스 L{bossLevel} 기준 · ✅사용가능 🔒미언락)</span></div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 sm:grid-cols-3">
              {GIMMICK_UNLOCK_REF.map(r => {
                const avail = bossLevel >= r.level;
                return (
                  <div key={r.label} className={`text-[10px] flex items-center gap-1 ${avail ? 'text-emerald-300' : 'text-gray-500'}`}>
                    <span>{avail ? '✅' : '🔒'}</span>
                    <span className="flex-1 truncate">{r.label}</span>
                    <b className={avail ? 'text-emerald-400' : 'text-gray-500'}>L{r.level}</b>
                  </div>
                );
              })}
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

      {/* 난이도 파악 — 특정 레벨로 생성 시 예상/목표 클리어율 (레벨 목표난이도 자동) */}
      <div className="p-3 bg-gray-800 rounded-lg space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-white">🎯 난이도 파악 (레벨별 예상 클리어율)</span>
          <span className="text-[11px] text-gray-500">skill_mean = 프로덕션 슬라이더값 사용</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 whitespace-nowrap">보스 레벨 <b className="text-white">{bossLevel}</b> → 프로덕션 목표난이도 = <b className="text-indigo-300">{productionDifficulty(bossLevel).toFixed(2)}</b> 자동</span>
          <button onClick={estimateDifficulty} disabled={estimating}
            className="ml-auto px-3 py-1.5 rounded bg-emerald-700 hover:bg-emerald-600 text-white text-sm disabled:opacity-50">
            {estimating ? '측정중…' : '▶ 파악'}
          </button>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 whitespace-nowrap">🎮 기준 실력 (skill_mean)</span>
          <input type="range" min={0} max={1} step={0.01} value={estSkillMean}
            onChange={e => setEstSkillMean(parseFloat(e.target.value))} className="flex-1" />
          <span className="text-xs font-mono text-white w-10">{estSkillMean.toFixed(2)}</span>
          <span className="text-[11px] text-gray-500 w-16">
            {estSkillMean >= 0.7 ? '고수' : estSkillMean >= 0.55 ? '중상급' : estSkillMean >= 0.45 ? '캐주얼' : '초보'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 whitespace-nowrap">🎨 타일 종류 수</span>
          <input type="range" min={4} max={15} step={1} value={estTileCount}
            onChange={e => setEstTileCount(parseInt(e.target.value))} className="flex-1" />
          <span className="text-xs font-mono text-white w-10">{estTileCount}종</span>
          <span className="text-[11px] text-gray-500 w-24">기본 hard {hardSteepTileCount(bossLevel)}종</span>
        </div>
        {estResult && (
          <div className="flex items-center gap-4 bg-gray-900/50 rounded px-3 py-2 text-sm flex-wrap">
            <span>예상 클리어율 <b className={Math.abs(estResult.predicted - estResult.target) <= 0.12 ? 'text-emerald-400' : 'text-yellow-400'}>{(estResult.predicted * 100).toFixed(0)}%</b></span>
            <span className="text-gray-400">목표(보스 절반) {(estResult.target * 100).toFixed(0)}%</span>
            <span className="text-[11px] text-gray-500">난이도 {estResult.td.toFixed(2)} · {estResult.cls}</span>
            <span className="text-[11px] text-cyan-400">타일종류 {estResult.useTileCount} · 실제총 {estResult.tiles}개
              {estResult.containers > 0
                ? <span className="text-gray-500"> (t0 {estResult.t0} + 내부 {estResult.inner} · 컨테이너셀 {estResult.containers} 제외)</span>
                : <span className="text-gray-500"> (그린 {estResult.drawn}→t0 {estResult.t0}, ÷3 보정)</span>}
              {estResult.t0 < estResult.useTileCount * 3 && <span className="text-yellow-400"> (t0부족→종류 다 못씀)</span>}
              {estResult.tiles < 60 && <span className="text-yellow-400"> (작음→쉬움, 셀/층↑)</span>}
            </span>
            <span className="text-[11px] text-gray-500">
              {estResult.predicted > estResult.target + 0.12 ? '→ 너무 쉬움(종류/기믹↑)' : estResult.predicted < estResult.target - 0.12 ? '→ 너무 어려움' : '→ 적정'}
            </span>
            {estResult.chainStripped > 0 && (
              <span className="text-[11px] text-red-400 w-full">⚠ 체인 {estResult.chainStripped}개 무효(좌우 이웃 없음) → 자동 제거됨. 체인은 같은 층 좌/우에 타일이 있어야 함.</span>
            )}
            {estResult.grassStripped > 0 && (
              <span className="text-[11px] text-red-400 w-full">⚠ 잔디 {estResult.grassStripped}개 무효(4방 이웃 2개 미만) → 자동 제거됨. 잔디는 상하좌우 중 2칸 이상 타일이 있어야 함(게임 remaining=2).</span>
            )}
          </div>
        )}
        <div className="text-[10px] text-gray-500">레벨번호 → 그 레벨 프로덕션 목표난이도(톱니바퀴곡선) 자동 → 현재 모양+기믹으로 생성 후 RL 예측. 저장 안 함. (배치 프리셋이 다르면 실제와 소폭 차이)</div>
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
            <button onClick={resetConceptsToDefault} className="px-2 py-0.5 rounded text-[11px] bg-gray-600 hover:bg-gray-500 text-white" title="1~10챕터 기본 컨셉(10~200)으로 리셋">기본값</button>
            <button onClick={saveConcepts} disabled={!conceptsDirty} className="px-2 py-0.5 rounded text-[11px] bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40">💾 저장</button>
          </div>
        </div>
        {conceptsOpen && (() => {
          const allLevels = Object.keys(concepts).map(k => parseInt(k)).filter(n => !isNaN(n));
          const maxTheme = allLevels.length ? Math.max(...allLevels.map(themeOf), 0) : 0;
          const themeLevels = allLevels.filter(n => themeOf(n) === themeIndex).sort((a, b) => a - b);
          return (
          <div className="overflow-x-auto">
            {/* 테마 페이징 바 (5챕터 단위 좌우 이동) */}
            <div className="flex items-center justify-between mb-2 bg-gray-900/50 rounded px-2 py-1.5">
              <button onClick={() => setThemeIndex(t => Math.max(0, t - 1))} disabled={themeIndex <= 0}
                className="px-2 py-1 rounded text-sm bg-gray-700 hover:bg-gray-600 text-white disabled:opacity-30">◀</button>
              <div className="text-center">
                <div className="text-xs font-semibold text-white">{themeLabel(themeIndex)}</div>
                <div className="text-[10px] text-gray-400">{themeLevelRange(themeIndex)} · 보스 {themeLevels.length}개</div>
              </div>
              <button onClick={() => setThemeIndex(t => Math.min(maxTheme, t + 1))} disabled={themeIndex >= maxTheme}
                className="px-2 py-1 rounded text-sm bg-gray-700 hover:bg-gray-600 text-white disabled:opacity-30">▶</button>
            </div>
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
                {themeLevels.map(n => {
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
                        <button onClick={() => { setBossLevel(n); addNotification('info', `보스 레벨 ${n}로 설정 — 이 컨셉용 템플릿 그리세요`); }}
                          className="px-1.5 py-0.5 rounded bg-gray-600 hover:bg-gray-500 text-white text-[10px]" title="이 레벨용 템플릿 그리기(배정구간 설정)">그리기</button>
                        <button onClick={() => removeConceptRow(lv)} className="px-1 py-0.5 rounded bg-red-800 hover:bg-red-700 text-white text-[10px] ml-1">×</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="text-[10px] text-gray-500 mt-1">● = 이 레벨 커버하는 보스 템플릿 있음 · "그리기" = 위 편집기 배정구간을 해당 레벨로 세팅 · ◀▶ = 테마(5챕터) 전환</div>
          </div>
          );
        })()}
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
                  <span className="text-gray-400 ml-2">Lv {t.level_min} · {t.layer_count}층</span>
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

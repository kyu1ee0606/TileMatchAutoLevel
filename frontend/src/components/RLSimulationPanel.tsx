/**
 * RL 시뮬레이션 탭 (몬테카를로 스킬 스윕)
 *
 * 기존 난이도별 AI 시뮬레이션과 독립적으로, 프로덕션 배치(1500개 1세트)를
 * 선택해 레벨별 스킬 스펙트럼(theta 0~1) 몬테카를로 스윕을 돌린다.
 * - 메인 난이도 지표: 1 - AUC (강건한 연속 점수)
 * - 보조: theta0/k (로지스틱 피팅 — k 낮으면 운빨 레벨 의심), theta* (50% 교차)
 * - 백엔드 ProcessPool로 레벨 단위 병렬 처리 (워커 수만큼 청크 전송)
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  listProductionBatches,
  getProductionLevelsByBatch,
  getProductionLevel,
  saveProductionLevel,
} from '../storage/productionStorage';
import type { ProductionBatch, ProductionLevel } from '../types/production';
import type { LevelJSON } from '../types';
import { renderLevelCanvasPreview } from '../utils/levelPreview';
import {
  ResponsiveContainer, ComposedChart, Line, Area, Scatter,
  XAxis, YAxis, Tooltip, Legend, CartesianGrid,
} from 'recharts';
import {
  getRLSimConfig,
  simulateBatchSkillSweep,
  searchCurveTarget,
  type RLSimClassification,
  type RLSearchResponse,
  type RLSearchBest,
} from '../api/rlSim';
import { batchAnalyzeSolvability, type SolvabilityVerdict } from '../api/analyze';
import { useUIStore } from '../stores/uiStore';

interface LevelSweepRow {
  level_number: number;
  grade: string;
  target_difficulty: number | null;
  difficulty_score: number | null;
  theta_star: number | null;
  theta0: number | null;
  k: number | null;
  luck_suspect: boolean;
  classification: RLSimClassification;
  max_clear_rate: number;
  total_rollouts: number;
  curve_summary: { theta: number; clear_rate: number }[];
  error?: string;
}


// 0.5단계: 부적절 레벨 교체 탐색 결과 항목
interface RepairItem {
  level_number: number;
  reasons: string[];
  target_theta: number;
  old: { theta0: number | null; k: number | null; difficulty_score: number | null; classification: RLSimClassification };
  best: RLSearchBest | null;
  accepted: boolean;
  error?: string;
  selected: boolean;
  applied: boolean;
}

const CLASSIFICATION_LABELS: Record<RLSimClassification, { label: string; color: string }> = {
  very_easy: { label: '매우 쉬움', color: 'text-green-400' },
  easy: { label: '쉬움', color: 'text-green-300' },
  normal: { label: '보통', color: 'text-blue-300' },
  hard: { label: '어려움', color: 'text-orange-300' },
  very_hard: { label: '매우 어려움', color: 'text-red-300' },
  unclearable_suspect: { label: '⚠️ 언클리어러블 의심', color: 'text-red-500 font-bold' },
};

export function RLSimulationPanel() {
  const { addNotification } = useUIStore();

  // 배치/레벨 선택
  const [batches, setBatches] = useState<ProductionBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState('');
  const [batchLevelCount, setBatchLevelCount] = useState(0);

  // 범위 설정
  const [useRange, setUseRange] = useState(true);
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(20);

  // 시뮬레이션 설정
  const [rolloutsPerPoint, setRolloutsPerPoint] = useState(40);
  const [skillGrid, setSkillGrid] = useState<number[]>([]);
  const [seed, setSeed] = useState(4242);
  const [workers, setWorkers] = useState(4);

  // 실행 상태
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [avgMsPerLevel, setAvgMsPerLevel] = useState(0);
  const cancelRef = useRef(false);

  // 결과
  const [rows, setRows] = useState<LevelSweepRow[]>([]);

  // 언클리어러블 의심 레벨 → A* 솔버블 일괄 검증
  const [solvRunning, setSolvRunning] = useState(false);
  const [solvProgress, setSolvProgress] = useState({ current: 0, total: 0 });
  const [solvResults, setSolvResults] = useState<{ level_number: number; verdict: SolvabilityVerdict; reason: string }[]>([]);

  // 0.5단계: 목표 스케줄 모드
  // 'linear': 수동 2점 선형 보간 / 'batch': 배치 난이도 그래프(메타 target_difficulty) 참조
  const [schedMode, setSchedMode] = useState<'linear' | 'batch'>('linear');
  const [batchThetaMin, setBatchThetaMin] = useState(0.3);  // 배치 난이도 최소값에 대응할 θ0
  const [batchThetaMax, setBatchThetaMax] = useState(0.8);  // 배치 난이도 최대값에 대응할 θ0

  // 0.5단계: 목표 난이도 스케줄 (2점 선형 보간) + 판정 기준
  const [schedStartLevel, setSchedStartLevel] = useState(31);
  const [schedStartTheta, setSchedStartTheta] = useState(0.4);
  const [schedEndLevel, setSchedEndLevel] = useState(1500);
  const [schedEndTheta, setSchedEndTheta] = useState(0.75);
  const [schedBand, setSchedBand] = useState(0.1);
  const [schedBossBonus, setSchedBossBonus] = useState(0.05);
  const [kMax, setKMax] = useState(8);
  const [repairTargetK, setRepairTargetK] = useState(4.5);

  // 0.5단계: 교체 탐색 실행 상태
  const [isRepairing, setIsRepairing] = useState(false);
  const [repairProgress, setRepairProgress] = useState({ current: 0, total: 0 });
  const repairCancelRef = useRef(false);
  const [repairItems, setRepairItems] = useState<RepairItem[]>([]);
  const [isApplying, setIsApplying] = useState(false);

  // 레벨 미리보기 팝업
  const [preview, setPreview] = useState<{ title: string; levelJson: LevelJSON } | null>(null);
  const [previewImg, setPreviewImg] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // 곡선 타겟 탐색 (0단계)
  const [searchLevelNumber, setSearchLevelNumber] = useState(45);
  const [searchTheta0, setSearchTheta0] = useState(0.5);
  const [searchK, setSearchK] = useState(4.0);
  const [searchCandidates, setSearchCandidates] = useState(16);
  const [isSearching, setIsSearching] = useState(false);
  const [searchResult, setSearchResult] = useState<RLSearchResponse | null>(null);

  // 초기 로드: 배치 목록 + 서버 기본 설정
  useEffect(() => {
    listProductionBatches()
      .then(list => {
        setBatches(list);
        if (list.length > 0 && !selectedBatchId) {
          setSelectedBatchId(list[0].id);
        }
      })
      .catch(() => addNotification('error', '프로덕션 배치 목록을 불러올 수 없습니다'));

    getRLSimConfig()
      .then(cfg => {
        setSkillGrid(cfg.default_skill_grid);
        setRolloutsPerPoint(cfg.default_rollouts_per_point);
        setSeed(cfg.default_seed);
        setWorkers(cfg.workers);
      })
      .catch(() => addNotification('warning', 'RL 시뮬 서버 설정을 불러올 수 없습니다 (백엔드 확인)'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 배치 변경 시 레벨 수 갱신
  useEffect(() => {
    if (!selectedBatchId) return;
    getProductionLevelsByBatch(selectedBatchId)
      .then(levels => setBatchLevelCount(levels.length))
      .catch(() => setBatchLevelCount(0));
  }, [selectedBatchId]);

  const handleRun = useCallback(async () => {
    if (!selectedBatchId || isRunning) return;

    let levels: ProductionLevel[];
    try {
      levels = await getProductionLevelsByBatch(selectedBatchId);
    } catch {
      addNotification('error', '배치 레벨을 불러올 수 없습니다');
      return;
    }

    const targets = useRange
      ? levels.filter(l => l.meta.level_number >= rangeStart && l.meta.level_number <= rangeEnd)
      : levels;

    if (targets.length === 0) {
      addNotification('warning', '시뮬레이션할 레벨이 없습니다 (범위 확인)');
      return;
    }

    setIsRunning(true);
    cancelRef.current = false;
    setRows([]);
    setProgress({ current: 0, total: targets.length });
    setAvgMsPerLevel(0);

    // 백엔드가 (레벨×스킬포인트) 단위로 분배하므로 청크를 워커 수의 2배로 묶어
    // HTTP 왕복/배리어 횟수를 줄임 (최대 32 = 백엔드 MAX_BATCH_SIZE)
    const chunkSize = Math.min(32, Math.max(1, workers * 2));
    const chunks: ProductionLevel[][] = [];
    for (let i = 0; i < targets.length; i += chunkSize) {
      chunks.push(targets.slice(i, i + chunkSize));
    }

    let elapsedSum = 0;
    let done = 0;
    const newRows: LevelSweepRow[] = [];

    for (const chunk of chunks) {
      if (cancelRef.current) break;

      try {
        const response = await simulateBatchSkillSweep({
          levels: chunk.map(l => ({ level_number: l.meta.level_number, level_json: l.level_json })),
          skill_grid: skillGrid.length > 0 ? skillGrid : undefined,
          rollouts_per_point: rolloutsPerPoint,
          seed,
        });
        elapsedSum += response.elapsed_ms;

        const metaByLevel = new Map(chunk.map(l => [l.meta.level_number, l.meta]));
        for (const r of response.results) {
          const meta = metaByLevel.get(r.level_number);
          newRows.push({
            level_number: r.level_number,
            grade: meta?.grade || '-',
            target_difficulty: meta?.target_difficulty ?? null,
            difficulty_score: r.difficulty_score,
            theta_star: r.theta_star,
            theta0: r.theta0,
            k: r.k,
            luck_suspect: r.luck_suspect,
            classification: r.classification,
            max_clear_rate: r.max_clear_rate,
            total_rollouts: r.total_rollouts,
            curve_summary: r.skill_curve.map(p => ({ theta: p.theta, clear_rate: p.clear_rate })),
            error: r.error || undefined,
          });
        }
      } catch (err) {
        for (const l of chunk) {
          newRows.push({
            level_number: l.meta.level_number,
            grade: l.meta.grade,
            target_difficulty: l.meta.target_difficulty ?? null,
            difficulty_score: null,
            theta_star: null,
            theta0: null,
            k: null,
            luck_suspect: false,
            classification: 'unclearable_suspect',
            max_clear_rate: 0,
            total_rollouts: 0,
            curve_summary: [],
            error: (err as Error).message,
          });
        }
      }

      done += chunk.length;
      setProgress({ current: done, total: targets.length });
      setAvgMsPerLevel(done > 0 ? elapsedSum / done : 0);
      newRows.sort((a, b) => a.level_number - b.level_number);
      setRows([...newRows]);
    }

    setIsRunning(false);
    if (cancelRef.current) {
      addNotification('warning', `중단됨: ${done}/${targets.length}개 완료`);
    } else {
      addNotification('success', `RL 시뮬레이션 완료: ${done}개 레벨`);
    }
  }, [selectedBatchId, isRunning, useRange, rangeStart, rangeEnd, skillGrid, rolloutsPerPoint, seed, workers, addNotification]);

  const handleCancel = useCallback(() => {
    cancelRef.current = true;
  }, []);

  // 요약 통계
  const summary = useMemo(() => {
    const valid = rows.filter(r => !r.error);
    const scores = valid.map(r => r.difficulty_score).filter((s): s is number => s !== null);
    const suspects = valid.filter(r => r.classification === 'unclearable_suspect');
    const luckLevels = valid.filter(r => r.luck_suspect);
    const errors = rows.filter(r => r.error);
    const counts: Partial<Record<RLSimClassification, number>> = {};
    valid.forEach(r => { counts[r.classification] = (counts[r.classification] || 0) + 1; });
    return {
      total: rows.length,
      avgScore: scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null,
      counts,
      suspectCount: suspects.length,
      suspectLevels: suspects.map(r => r.level_number),
      luckCount: luckLevels.length,
      luckLevels: luckLevels.map(r => r.level_number),
      errorCount: errors.length,
    };
  }, [rows]);

  const remainingMs = isRunning && avgMsPerLevel > 0
    ? Math.round((progress.total - progress.current) * avgMsPerLevel)
    : 0;

  const selectedBatch = batches.find(b => b.id === selectedBatchId);

  // 결과를 CSV로 직렬화 (스프레드시트 분석용)
  const buildCsv = useCallback((): string => {
    const header = ['level', 'grade', 'target_difficulty', 'difficulty_1minusAUC', 'theta0', 'k', 'luck_suspect', 'classification', 'max_clear_rate', 'total_rollouts',
      ...skillGrid.map(t => `clear@${t}`)];
    const lines = [header.join(',')];
    for (const r of rows) {
      const curveByTheta = new Map(r.curve_summary.map(p => [p.theta, p.clear_rate]));
      lines.push([
        r.level_number, r.grade,
        r.target_difficulty ?? '', r.difficulty_score ?? '', r.theta0 ?? '', r.k ?? '',
        r.luck_suspect ? 1 : 0, r.classification,
        r.max_clear_rate, r.total_rollouts,
        ...skillGrid.map(t => curveByTheta.get(t) ?? ''),
      ].join(','));
    }
    return lines.join('\n');
  }, [rows, skillGrid]);

  // AI 분석용 풀 프롬프트 생성 (측정 방법 설명 + 결과 + 분석 질문 포함)
  const buildAnalysisPrompt = useCallback((): string => {
    const cls = (c: RLSimClassification) => CLASSIFICATION_LABELS[c].label.replace('⚠️ ', '');
    const tableLines = rows.map(r => {
      const curve = r.curve_summary.map(p => `${(p.clear_rate * 100).toFixed(0)}%`).join('/');
      return `Lv.${r.level_number} | 목표난이도=${r.target_difficulty ?? '-'} | 기존등급=${r.grade} | 1-AUC=${r.difficulty_score ?? '-'} | θ0=${r.theta0 ?? '-'} | k=${r.k ?? '-'} | ${cls(r.classification)}${r.luck_suspect ? ' [운빨의심]' : ''}${r.error ? ` [오류:${r.error}]` : ''} | 곡선(θ=${skillGrid.join('/')}): ${curve}`;
    });

    return `# 타일매치 퍼즐 레벨 난이도 측정 결과 분석 요청

## 측정 방법 (몬테카를로 스킬 스윕)
- 3매치 타일 수집 퍼즐 (레이어 쌓임, 노출 타일만 선택 가능, 독 7칸, 같은 타입 3개 모으면 제거, 독 가득 차면 패배)
- 봇 실력을 연속 파라미터 θ∈[0,1]로 보간 (0=초보: 실수 45%·선읽기 없음, 1=고수: 실수 2%·선읽기 2수·기믹 인지율 높음)
- 스킬 그리드 [${skillGrid.join(', ')}] 각 지점에서 ${rolloutsPerPoint}회 롤아웃 (0%/100% 확정 시 조기 종료)
- 지표 정의:
  - 1-AUC: 스킬→클리어율 곡선 아래 면적의 보수 (0=모든 실력이 100% 클리어, 1=아무도 못 깸). 메인 연속 난이도 점수
  - θ0: 로지스틱 피팅상 클리어율 50%가 되는 스킬 지점 (음수면 초보도 50% 이상 클리어한다는 뜻)
  - k: 로지스틱 기울기 = 실력 민감도 (높을수록 실력겜, 낮으면 실력 무관)
  - 운빨의심: θ0∈[0,1]인데 최고수와 초보의 클리어율 차이 ΔP<25%p인 레벨
- 레벨은 1500개 1세트이며 레벨 번호가 커질수록 어려워지도록 설계됨 (10의 배수는 보스 레벨)

## 측정 결과 (${rows.length}개 레벨)
${tableLines.join('\n')}

## 요약
- 평균 난이도(1-AUC): ${summary.avgScore !== null ? summary.avgScore.toFixed(3) : '-'}
- 분류 분포: ${(Object.keys(CLASSIFICATION_LABELS) as RLSimClassification[]).filter(c => summary.counts[c]).map(c => `${cls(c)} ${summary.counts[c]}개`).join(', ') || '-'}
- 언클리어러블 의심: ${summary.suspectLevels.length > 0 ? summary.suspectLevels.join(', ') : '없음'}
- 운빨 의심: ${summary.luckLevels.length > 0 ? summary.luckLevels.join(', ') : '없음'}

## 분석 요청
1. 레벨 번호 대비 난이도(1-AUC) 진행 커브가 자연스러운가? 역전(뒤 레벨이 더 쉬움)이나 급격한 점프 구간을 짚어달라.
2. 목표난이도(target_difficulty)와 측정값(1-AUC)의 괴리가 큰 레벨은 어디이고, 생성기 보정 관점에서 어떤 조치가 필요한가?
3. k(실력 민감도)가 비정상적으로 낮거나 높은 레벨이 있나? 보스 레벨(10의 배수)이 일반 레벨과 적절히 차별화되어 있나?
4. 이 구간의 레벨 품질을 종합 평가하고, 재생성이 필요한 레벨 목록과 그 이유를 제시해달라.
5. 측정 설정(스킬 그리드, 롤아웃 수) 자체의 개선점이 있다면 제안해달라.`;
  }, [rows, summary, skillGrid, rolloutsPerPoint]);

  const handleCopyPrompt = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(buildAnalysisPrompt());
      addNotification('success', '분석 프롬프트가 클립보드에 복사되었습니다 — AI에게 붙여넣으세요');
    } catch {
      addNotification('error', '클립보드 복사 실패');
    }
  }, [buildAnalysisPrompt, addNotification]);

  const handleCopyCsv = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(buildCsv());
      addNotification('success', 'CSV가 클립보드에 복사되었습니다');
    } catch {
      addNotification('error', '클립보드 복사 실패');
    }
  }, [buildCsv, addNotification]);

  // 곡선 타겟 탐색 실행
  const handleSearch = useCallback(async () => {
    if (isSearching) return;
    setIsSearching(true);
    setSearchResult(null);
    try {
      const result = await searchCurveTarget({
        level_number: searchLevelNumber,
        target_theta0: searchTheta0,
        target_k: searchK,
        candidates: searchCandidates,
        rollouts_per_point: rolloutsPerPoint,
        seed,
      });
      setSearchResult(result);
      if (result.best) {
        addNotification(
          result.accepted ? 'success' : 'info',
          result.accepted
            ? `목표 곡선에 맞는 레벨을 찾았습니다 (score ${result.best.score})`
            : `최적 후보 score ${result.best.score} (허용오차 ${result.tolerance} 초과 — 후보 수를 늘려보세요)`
        );
      } else {
        addNotification('warning', '측정 가능한 후보가 없었습니다 — 목표/후보 수를 조정해보세요');
      }
    } catch (err) {
      addNotification('error', `탐색 실패: ${(err as Error).message}`);
    } finally {
      setIsSearching(false);
    }
  }, [isSearching, searchLevelNumber, searchTheta0, searchK, searchCandidates, rolloutsPerPoint, seed, addNotification]);

  const handleCopyBestJson = useCallback(async () => {
    if (!searchResult?.best) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(searchResult.best.level_json, null, 2));
      addNotification('success', '최적 레벨 JSON이 복사되었습니다 (에디터 탭에서 붙여넣기 가능)');
    } catch {
      addNotification('error', '클립보드 복사 실패');
    }
  }, [searchResult, addNotification]);

  // ─── 레벨 미리보기 팝업 ───

  const openPreview = useCallback(async (title: string, levelJson: LevelJSON) => {
    setPreview({ title, levelJson });
    setPreviewLoading(true);
    try {
      setPreviewImg(await renderLevelCanvasPreview(levelJson, 420));
    } catch {
      setPreviewImg(null);
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  // 현재 프로덕션 저장소의 레벨을 불러와 미리보기
  const openProductionPreview = useCallback(async (levelNumber: number) => {
    if (!selectedBatchId) return;
    try {
      const level = await getProductionLevel(selectedBatchId, levelNumber);
      if (!level) {
        addNotification('warning', `Lv.${levelNumber}를 저장소에서 찾을 수 없습니다`);
        return;
      }
      await openPreview(`Lv.${levelNumber} — 현재 프로덕션 레벨`, level.level_json);
    } catch {
      addNotification('error', '레벨 로드 실패');
    }
  }, [selectedBatchId, openPreview, addNotification]);

  // 언클리어러블 의심 레벨을 A* 솔버블로 일괄 검증 (의심이 진짜 불가능인지 / 봇 한계인지 확정)
  const verifySuspectsSolvability = useCallback(async () => {
    if (solvRunning || !selectedBatchId || summary.suspectLevels.length === 0) return;
    setSolvRunning(true);
    setSolvResults([]);
    setSolvProgress({ current: 0, total: summary.suspectLevels.length });
    try {
      const all = await getProductionLevelsByBatch(selectedBatchId);
      const suspectSet = new Set(summary.suspectLevels);
      const targets = all.filter(l => suspectSet.has(l.meta.level_number));
      const results: { level_number: number; verdict: SolvabilityVerdict; reason: string }[] = [];
      const chunkSize = 16;
      for (let i = 0; i < targets.length; i += chunkSize) {
        const chunk = targets.slice(i, i + chunkSize);
        try {
          const resp = await batchAnalyzeSolvability(
            chunk.map(l => ({ level_number: l.meta.level_number, level_json: l.level_json })),
            // 시간 제한 없이(노드 예산까지) 끝까지 탐색 → 의심 레벨을 최대한 확정
            { timeBudgetS: 0, nodeBudget: 1000000 },
          );
          for (const r of resp.results) results.push({ level_number: r.level_number, verdict: r.verdict, reason: r.reason });
        } catch {
          for (const l of chunk) results.push({ level_number: l.meta.level_number, verdict: 'UNCERTAIN', reason: '요청 오류' });
        }
        results.sort((a, b) => a.level_number - b.level_number);
        setSolvResults([...results]);
        setSolvProgress({ current: Math.min(i + chunkSize, targets.length), total: targets.length });
      }
      const imp = results.filter(r => r.verdict === 'PROVEN_IMPOSSIBLE').length;
      const sol = results.filter(r => r.verdict === 'PROVEN_SOLVABLE').length;
      addNotification('success', `솔버블 검증 완료: 풀림 ${sol} · 불가능 ${imp} · 미확정 ${results.length - sol - imp}`);
    } catch {
      addNotification('error', '솔버블 검증 실패');
    } finally {
      setSolvRunning(false);
    }
  }, [solvRunning, selectedBatchId, summary.suspectLevels, addNotification]);

  // ─── 0.5단계: 판정 + 자동 교체 ───

  // 레벨 → 목표 θ0
  // - linear 모드: 2점 선형 보간 + 보스 보정
  // - batch 모드: 레벨 메타의 target_difficulty(10레벨 톱니 상승 그래프)를
  //   배치 난이도 범위 [difficulty_start, difficulty_end] → [θ0 min, θ0 max]로 선형 매핑.
  //   톱니/보스 상승이 그래프에 이미 반영돼 있어 보스 보정은 추가하지 않음.
  const scheduleTarget = useCallback((levelNumber: number, targetDifficulty?: number | null): number => {
    let target: number;
    const batch = batches.find(b => b.id === selectedBatchId);
    if (schedMode === 'batch' && targetDifficulty != null && batch) {
      const dMin = batch.difficulty_start ?? 0.1;
      const dMax = batch.difficulty_end ?? 0.95;
      const t = Math.min(1, Math.max(0, (targetDifficulty - dMin) / Math.max(0.0001, dMax - dMin)));
      target = batchThetaMin + (batchThetaMax - batchThetaMin) * t;
    } else {
      const span = Math.max(1, schedEndLevel - schedStartLevel);
      const t = Math.min(1, Math.max(0, (levelNumber - schedStartLevel) / span));
      target = schedStartTheta + (schedEndTheta - schedStartTheta) * t;
      if (levelNumber > 0 && levelNumber % 10 === 0) target += schedBossBonus;
    }
    return Math.min(0.95, Math.max(0.05, Math.round(target * 100) / 100));
  }, [schedMode, batches, selectedBatchId, batchThetaMin, batchThetaMax,
      schedStartLevel, schedStartTheta, schedEndLevel, schedEndTheta, schedBossBonus]);

  // 측정 결과 판정: 부적절 사유 목록 (빈 배열 = 정상)
  const assessments = useMemo(() => {
    const map = new Map<number, { reasons: string[]; targetTheta: number }>();
    for (const row of rows) {
      const reasons: string[] = [];
      const target = scheduleTarget(row.level_number, row.target_difficulty);
      if (row.error) {
        reasons.push('측정 오류');
      } else if (row.classification === 'unclearable_suspect') {
        reasons.push('언클리어러블');
      } else {
        // 난이도 이탈은 스케줄 시작 레벨부터만 검사 (초반 레벨은 의도적으로 매우 쉬움)
        if (row.level_number >= schedStartLevel && row.theta0 !== null && Math.abs(row.theta0 - target) > schedBand) {
          reasons.push(`난이도 이탈 (θ₀ ${row.theta0} / 목표 ${target})`);
        }
        if (row.k !== null && row.k > kMax) {
          reasons.push(`계단 과다 (k=${row.k})`);
        }
        if (row.luck_suspect) {
          reasons.push('운빨 의심');
        }
      }
      map.set(row.level_number, { reasons, targetTheta: target });
    }
    return map;
  }, [rows, scheduleTarget, schedStartLevel, schedBand, kMax]);

  const badRows = useMemo(
    () => rows.filter(r => (assessments.get(r.level_number)?.reasons.length ?? 0) > 0),
    [rows, assessments]
  );

  // 기획 난이도 그래프 vs 측정 비교 — 차트 데이터 + 유사도 지표
  const graphComparison = useMemo(() => {
    // 교체 탐색에서 찾은 새 후보 θ0 (레벨별) — 그래프에 노란 점으로 오버레이
    const repairedByLevel = new Map<number, { theta0: number | null; applied: boolean }>();
    for (const item of repairItems) {
      if (item.best) {
        repairedByLevel.set(item.level_number, {
          theta0: item.best.measurement.theta0,
          applied: item.applied,
        });
      }
    }

    const data = rows.map(r => {
      const target = assessments.get(r.level_number)?.targetTheta ?? null;
      const repaired = repairedByLevel.get(r.level_number);
      return {
        level: r.level_number,
        target,
        band: target !== null
          ? [Math.max(0, target - schedBand), Math.min(1, target + schedBand)]
          : null,
        measured: r.theta0,
        unclearable: r.classification === 'unclearable_suspect' || r.error ? 0.98 : null,
        candidate: repaired ? repaired.theta0 : null,   // 교체 후보 θ0 (노랑)
      };
    });

    // 유사도 지표: 측정 가능한 레벨만 대상
    const pairs = data.filter(d => d.measured !== null && d.target !== null) as
      { level: number; target: number; measured: number }[];
    const unclearableCount = data.filter(d => d.unclearable !== null).length;

    let withinBand = 0, mae = 0, pearson: number | null = null;
    if (pairs.length > 0) {
      let sumAbs = 0;
      for (const p of pairs) {
        const diff = Math.abs(p.measured - p.target);
        sumAbs += diff;
        if (diff <= schedBand) withinBand += 1;
      }
      mae = sumAbs / pairs.length;

      if (pairs.length >= 3) {
        const mt = pairs.reduce((a, p) => a + p.target, 0) / pairs.length;
        const mm = pairs.reduce((a, p) => a + p.measured, 0) / pairs.length;
        let cov = 0, vt = 0, vm = 0;
        for (const p of pairs) {
          cov += (p.target - mt) * (p.measured - mm);
          vt += (p.target - mt) ** 2;
          vm += (p.measured - mm) ** 2;
        }
        pearson = vt > 0 && vm > 0 ? cov / Math.sqrt(vt * vm) : null;
      }
    }

    return {
      data,
      measurable: pairs.length,
      unclearableCount,
      withinBandRate: pairs.length > 0 ? withinBand / pairs.length : 0,
      mae,
      pearson,
      candidateCount: repairedByLevel.size,
    };
  }, [rows, assessments, schedBand, repairItems]);

  // 부적절 레벨 전체에 대해 교체 탐색 (순차 — search 내부가 프로세스 풀 병렬)
  const handleRepair = useCallback(async () => {
    if (isRepairing || badRows.length === 0) return;
    setIsRepairing(true);
    repairCancelRef.current = false;
    setRepairItems([]);
    setRepairProgress({ current: 0, total: badRows.length });

    const items: RepairItem[] = [];
    let done = 0;

    for (const row of badRows) {
      if (repairCancelRef.current) break;
      const assessment = assessments.get(row.level_number)!;
      const item: RepairItem = {
        level_number: row.level_number,
        reasons: assessment.reasons,
        target_theta: assessment.targetTheta,
        old: {
          theta0: row.theta0, k: row.k,
          difficulty_score: row.difficulty_score, classification: row.classification,
        },
        best: null, accepted: false, selected: false, applied: false,
      };
      try {
        let result = await searchCurveTarget({
          level_number: row.level_number,
          target_theta0: assessment.targetTheta,
          target_k: repairTargetK,
          candidates: 16,
          rollouts_per_point: rolloutsPerPoint,
          seed,
        });
        // 미달 시 후보 32개로 1회 재시도
        if (!result.accepted) {
          const retry = await searchCurveTarget({
            level_number: row.level_number,
            target_theta0: assessment.targetTheta,
            target_k: repairTargetK,
            candidates: 32,
            rollouts_per_point: rolloutsPerPoint,
            seed: seed + 1,
          });
          if (retry.best && (!result.best || retry.best.score < result.best.score)) {
            result = retry;
          }
        }
        item.best = result.best;
        item.accepted = result.accepted;
        item.selected = result.accepted; // 목표 달성한 것만 기본 선택
      } catch (err) {
        item.error = (err as Error).message;
      }
      items.push(item);
      done += 1;
      setRepairProgress({ current: done, total: badRows.length });
      setRepairItems([...items]);
    }

    setIsRepairing(false);
    addNotification(
      repairCancelRef.current ? 'warning' : 'success',
      `교체 탐색 ${repairCancelRef.current ? '중단' : '완료'}: ${done}/${badRows.length}개 (목표 달성 ${items.filter(i => i.accepted).length}개)`
    );
  }, [isRepairing, badRows, assessments, repairTargetK, rolloutsPerPoint, seed, addNotification]);

  const toggleRepairSelected = useCallback((levelNumber: number) => {
    setRepairItems(prev => prev.map(i =>
      i.level_number === levelNumber && i.best && !i.applied ? { ...i, selected: !i.selected } : i
    ));
  }, []);

  // 전체 선택/해제 (교체 가능한 항목 = best 있고 미적용)
  const selectableRepairCount = useMemo(
    () => repairItems.filter(i => i.best && !i.applied).length,
    [repairItems]
  );
  const allRepairSelected = useMemo(
    () => selectableRepairCount > 0 &&
      repairItems.filter(i => i.best && !i.applied).every(i => i.selected),
    [repairItems, selectableRepairCount]
  );
  const toggleRepairSelectAll = useCallback(() => {
    setRepairItems(prev => {
      const target = !prev.filter(i => i.best && !i.applied).every(i => i.selected);
      return prev.map(i => (i.best && !i.applied ? { ...i, selected: target } : i));
    });
  }, []);

  // 단일 레벨 교체 적용 (탐색 best → 프로덕션 저장소, 원본 백업/메타 기록 포함)
  const applySingleReplacement = useCallback(async (levelNumber: number, best: RLSearchBest) => {
    if (!selectedBatchId) throw new Error('배치가 선택되지 않음');
    const level = await getProductionLevel(selectedBatchId, levelNumber);
    if (!level) throw new Error('레벨을 찾을 수 없음');
    const m = best.measurement;
    const updated: ProductionLevel = {
      level_json: best.level_json,
      meta: {
        ...level.meta,
        mc_measurement: {
          theta0: m.theta0, k: m.k,
          difficulty_score: m.difficulty_score,
          classification: m.classification,
          measured_at: new Date().toISOString(),
        },
        mc_replaced_backup: level.level_json,  // 교체 직전 원본 보관 (롤백용)
        mc_replaced_at: new Date().toISOString(),
        regenerated: true,
        verified: false,
        verification_passed: false,
      },
    };
    await saveProductionLevel(selectedBatchId, updated);
  }, [selectedBatchId]);

  // 선택된 교체 후보를 프로덕션 저장소(IndexedDB)에 실제 적용
  const handleApplyReplacements = useCallback(async () => {
    const targets = repairItems.filter(i => i.selected && i.best && !i.applied);
    if (targets.length === 0 || isApplying || !selectedBatchId) return;
    setIsApplying(true);

    let applied = 0;
    let failed = 0;
    for (const item of targets) {
      try {
        await applySingleReplacement(item.level_number, item.best!);
        applied += 1;
        setRepairItems(prev => prev.map(i =>
          i.level_number === item.level_number ? { ...i, applied: true, selected: false } : i
        ));
      } catch (err) {
        failed += 1;
        console.error(`Failed to replace Lv.${item.level_number}:`, err);
      }
    }

    setIsApplying(false);
    if (failed === 0) {
      addNotification('success', `${applied}개 레벨 교체 완료 — GBoost 반영은 내보내기 탭에서 재업로드 필요`);
    } else {
      addNotification('warning', `${applied}개 교체, ${failed}개 실패 (콘솔 확인)`);
    }
  }, [repairItems, isApplying, selectedBatchId, applySingleReplacement, addNotification]);

  // 0단계 곡선 타겟 탐색 결과를 해당 프로덕션 레벨에 직접 교체 적용
  const handleApplySearchBest = useCallback(async () => {
    if (!searchResult?.best || isApplying) return;
    if (!selectedBatchId) {
      addNotification('warning', '교체할 프로덕션 배치를 먼저 선택하세요');
      return;
    }
    const ok = window.confirm(
      `Lv.${searchLevelNumber}의 프로덕션 레벨을 탐색된 레벨로 교체합니다.\n` +
      `(원본은 meta.mc_replaced_backup에 보관, GBoost 반영은 재업로드 필요)\n계속할까요?`
    );
    if (!ok) return;
    setIsApplying(true);
    try {
      await applySingleReplacement(searchLevelNumber, searchResult.best);
      addNotification('success', `Lv.${searchLevelNumber} 교체 완료 — 내보내기 탭에서 재업로드 필요`);
    } catch (err) {
      addNotification('error', `교체 실패: ${(err as Error).message}`);
    } finally {
      setIsApplying(false);
    }
  }, [searchResult, isApplying, selectedBatchId, searchLevelNumber, applySingleReplacement, addNotification]);

  return (
    <div className="space-y-4">
      {/* 설명 헤더 */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h2 className="text-lg font-bold text-white mb-1">🧠 RL 시뮬레이션 (몬테카를로 스킬 스윕)</h2>
        <p className="text-sm text-gray-400">
          봇 실력을 연속 파라미터 θ(0=초보, 1=고수)로 보간해 스펙트럼 전체를 시뮬레이션합니다.
          메인 난이도 지표는 <span className="text-blue-300">1-AUC</span>(곡선 기반 강건 점수),
          보조로 <span className="text-blue-300">θ₀</span>(50% 스킬 지점)와
          <span className="text-yellow-300"> k</span>(실력 민감도 — 낮으면 운빨 레벨)를 측정합니다.
          백엔드 {workers}개 프로세스로 레벨 단위 병렬 처리됩니다.
        </p>
      </div>

      {/* 설정 */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* 배치 선택 */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">프로덕션 배치 (1세트)</label>
            <select
              value={selectedBatchId}
              onChange={(e) => setSelectedBatchId(e.target.value)}
              disabled={isRunning}
              className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            >
              {batches.length === 0 && <option value="">배치 없음</option>}
              {batches.map(b => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.generated_count}/{b.total_levels})
                </option>
              ))}
            </select>
            {selectedBatch && (
              <p className="text-[11px] text-gray-500 mt-1">저장된 레벨: {batchLevelCount}개</p>
            )}
          </div>

          {/* 범위 */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              <input
                type="checkbox"
                checked={useRange}
                onChange={(e) => setUseRange(e.target.checked)}
                disabled={isRunning}
                className="mr-1"
              />
              레벨 범위 지정 (해제 시 전체)
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                value={rangeStart}
                onChange={(e) => setRangeStart(parseInt(e.target.value, 10) || 1)}
                disabled={isRunning || !useRange}
                className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white disabled:opacity-50"
              />
              <span className="text-gray-500">~</span>
              <input
                type="number"
                min={rangeStart}
                value={rangeEnd}
                onChange={(e) => setRangeEnd(parseInt(e.target.value, 10) || rangeStart)}
                disabled={isRunning || !useRange}
                className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white disabled:opacity-50"
              />
            </div>
            <p className="text-[11px] text-gray-500 mt-1">
              {workers}개씩 병렬 처리 — 청크당 가장 느린 레벨 시간만큼 소요
            </p>
          </div>

          {/* 롤아웃 설정 */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">스킬 포인트당 롤아웃 수</label>
            <input
              type="number"
              min={4}
              max={500}
              value={rolloutsPerPoint}
              onChange={(e) => setRolloutsPerPoint(parseInt(e.target.value, 10) || 40)}
              disabled={isRunning}
              className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            />
            <p className="text-[11px] text-gray-500 mt-1">
              스킬 그리드 {skillGrid.length}개 지점 × 롤아웃 {rolloutsPerPoint}회 = 레벨당 최대 {skillGrid.length * rolloutsPerPoint}판
            </p>
          </div>
        </div>

        {/* 실행 버튼 */}
        <div className="flex items-center gap-3">
          {!isRunning ? (
            <button
              onClick={handleRun}
              disabled={!selectedBatchId || batchLevelCount === 0}
              className="px-4 py-2 bg-primary-600 hover:bg-primary-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-md"
            >
              ▶ 시뮬레이션 시작
            </button>
          ) : (
            <button
              onClick={handleCancel}
              className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white text-sm font-medium rounded-md"
            >
              ■ 중단 (현재 청크 완료 후)
            </button>
          )}

          {isRunning && (
            <div className="flex-1">
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>
                  시뮬레이션 중… ({progress.current}/{progress.total})
                </span>
                <span>
                  평균 {(avgMsPerLevel / 1000).toFixed(1)}s/레벨 · 남은 시간 ~{Math.ceil(remainingMs / 60000)}분
                </span>
              </div>
              <div className="w-full bg-gray-700 rounded-full h-2">
                <div
                  className="bg-primary-500 h-2 rounded-full transition-all"
                  style={{ width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 곡선 타겟 탐색 (0단계 MC 탐색 루프) */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
        <div>
          <h3 className="text-sm font-bold text-white">🎯 곡선 타겟 탐색 (0단계)</h3>
          <p className="text-xs text-gray-400 mt-0.5">
            목표 곡선(θ₀, k)을 입력하면 생성기 파라미터를 변주한 후보들을
            스크리닝(3지점×8롤아웃) → 풀 측정으로 걸러 가장 가까운 레벨을 찾습니다.
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">레벨 번호</label>
            <input
              type="number" min={1} value={searchLevelNumber}
              onChange={(e) => setSearchLevelNumber(parseInt(e.target.value, 10) || 1)}
              disabled={isSearching}
              className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">목표 θ₀ (0~1)</label>
            <input
              type="number" min={0} max={1} step={0.05} value={searchTheta0}
              onChange={(e) => setSearchTheta0(parseFloat(e.target.value) || 0)}
              disabled={isSearching}
              className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">목표 k (민감도)</label>
            <input
              type="number" min={0.5} max={20} step={0.5} value={searchK}
              onChange={(e) => setSearchK(parseFloat(e.target.value) || 4)}
              disabled={isSearching}
              className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">후보 수</label>
            <input
              type="number" min={2} max={64} value={searchCandidates}
              onChange={(e) => setSearchCandidates(parseInt(e.target.value, 10) || 16)}
              disabled={isSearching}
              className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleSearch}
            disabled={isSearching || isRunning}
            className="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-md"
          >
            {isSearching ? '⏳ 탐색 중… (수십 초 소요)' : '🔍 목표 곡선 레벨 탐색'}
          </button>
          {searchResult?.best && (
            <>
              <button
                onClick={() => openPreview(`Lv.${searchLevelNumber} — 탐색된 최적 레벨`, searchResult.best!.level_json)}
                className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded-md"
              >
                👁 미리보기
              </button>
              <button
                onClick={handleCopyBestJson}
                className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded-md"
              >
                📋 JSON 복사
              </button>
              <button
                onClick={handleApplySearchBest}
                disabled={isApplying}
                className="px-3 py-2 bg-red-800 hover:bg-red-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs rounded-md"
              >
                {isApplying ? '⏳ 적용 중…' : `⚠️ Lv.${searchLevelNumber} 프로덕션 교체`}
              </button>
            </>
          )}
        </div>

        {searchResult && (
          <div className="space-y-2">
            {searchResult.best ? (
              <div className={`rounded-lg p-3 border ${searchResult.accepted ? 'bg-emerald-900/30 border-emerald-600' : 'bg-gray-900/50 border-gray-600'}`}>
                <div className="flex flex-wrap items-center gap-4 text-sm">
                  <span className={searchResult.accepted ? 'text-emerald-300 font-bold' : 'text-yellow-300 font-bold'}>
                    {searchResult.accepted ? '✅ 목표 달성' : '⚠️ 근사 후보'} (score {searchResult.best.score})
                  </span>
                  <span className="text-gray-300 font-mono">
                    θ₀={searchResult.best.measurement.theta0} (목표 {searchTheta0})
                  </span>
                  <span className="text-gray-300 font-mono">
                    k={searchResult.best.measurement.k} (목표 {searchK})
                  </span>
                  <span className="text-blue-300 font-mono">
                    1-AUC={searchResult.best.measurement.difficulty_score}
                  </span>
                  <span className="text-gray-400 text-xs">
                    {Object.entries(searchResult.best.gen_params).map(([k2, v]) => `${k2}=${v}`).join(' · ')}
                  </span>
                </div>
                <div className="flex items-end gap-0.5 h-8 mt-2">
                  {searchResult.best.measurement.skill_curve.map(p => (
                    <div
                      key={p.theta}
                      title={`θ=${p.theta}: ${(p.clear_rate * 100).toFixed(0)}%`}
                      className={`w-3 rounded-sm ${p.clear_rate >= 0.5 ? 'bg-emerald-500' : 'bg-red-500/70'}`}
                      style={{ height: `${Math.max(8, p.clear_rate * 100)}%` }}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-red-400">측정 가능한 후보 없음 — 전부 언클리어러블이거나 생성 실패.</p>
            )}

            <details className="text-xs text-gray-400">
              <summary className="cursor-pointer hover:text-gray-300">
                후보 트레이스 보기 ({searchResult.candidates.length}개, {(searchResult.elapsed_ms / 1000).toFixed(1)}초)
              </summary>
              <table className="w-full mt-2 text-[11px]">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-700">
                    <th className="text-left px-2 py-1">#</th>
                    <th className="text-left px-2 py-1">생성 파라미터</th>
                    <th className="text-right px-2 py-1">스크린 거리</th>
                    <th className="text-right px-2 py-1">score</th>
                    <th className="text-right px-2 py-1">θ₀ / k</th>
                    <th className="text-left px-2 py-1">상태</th>
                  </tr>
                </thead>
                <tbody>
                  {searchResult.candidates.map(c => (
                    <tr key={c.index} className="border-b border-gray-700/40">
                      <td className="px-2 py-1 font-mono">{c.index}</td>
                      <td className="px-2 py-1">{Object.entries(c.gen_params).map(([k2, v]) => `${k2}=${v}`).join(' ')}</td>
                      <td className="px-2 py-1 text-right font-mono">{c.screen_distance ?? '-'}</td>
                      <td className="px-2 py-1 text-right font-mono">{c.score ?? '-'}</td>
                      <td className="px-2 py-1 text-right font-mono">{c.theta0 ?? '-'} / {c.k ?? '-'}</td>
                      <td className="px-2 py-1">
                        {c.finalist ? (c.classification || '측정') : (c.reject_reason || (c.screen_distance !== null ? '스크린 탈락' : ''))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </div>
        )}
      </div>

      {/* 요약 */}
      {rows.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold text-white">📊 요약 ({summary.total}개 레벨)</h3>
            <div className="flex gap-2">
              <button
                onClick={handleCopyPrompt}
                className="px-3 py-1 bg-blue-700 hover:bg-blue-600 text-white text-xs rounded-md"
                title="측정 방법 + 결과 + 분석 질문이 포함된 풀 프롬프트를 복사합니다. AI에게 붙여넣으면 바로 분석받을 수 있습니다."
              >
                📋 분석 프롬프트 복사
              </button>
              <button
                onClick={handleCopyCsv}
                className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded-md"
                title="스프레드시트 분석용 CSV를 복사합니다."
              >
                📄 CSV 복사
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <span className="text-gray-300">
              평균 난이도(1-AUC): <span className="text-blue-300 font-mono">{summary.avgScore !== null ? summary.avgScore.toFixed(3) : '-'}</span>
            </span>
            {(Object.keys(CLASSIFICATION_LABELS) as RLSimClassification[]).map(cls =>
              summary.counts[cls] ? (
                <span key={cls} className={CLASSIFICATION_LABELS[cls].color}>
                  {CLASSIFICATION_LABELS[cls].label}: {summary.counts[cls]}
                </span>
              ) : null
            )}
            {summary.luckCount > 0 && (
              <span className="text-yellow-300">🎲 운빨 의심: {summary.luckCount}</span>
            )}
            {summary.errorCount > 0 && (
              <span className="text-red-400">오류: {summary.errorCount}</span>
            )}
          </div>
          {summary.suspectCount > 0 && (
            <div className="mt-2">
              <p className="text-xs text-red-400">
                언클리어러블 의심 레벨: {summary.suspectLevels.join(', ')}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                <button
                  onClick={verifySuspectsSolvability}
                  disabled={solvRunning}
                  className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-xs rounded font-medium"
                  title="의심 레벨을 A* 완전탐색으로 검증(시간 제한 없이 노드 예산까지) — 진짜 불가능인지 봇 한계(풀림)인지 확정"
                >
                  {solvRunning
                    ? `🧩 솔버블 검증 중… ${solvProgress.current}/${solvProgress.total}`
                    : `🧩 의심 레벨 솔버블 일괄 검증 (${summary.suspectCount}개, 시간무제한)`}
                </button>
                <span className="text-[11px] text-gray-500">봇이 못 깬 게 진짜 불가능인지 끝까지 탐색해 확정합니다</span>
              </div>
              {solvResults.length > 0 && (
                <div className="mt-2 bg-gray-900/50 rounded p-2">
                  {(() => {
                    const sol = solvResults.filter(r => r.verdict === 'PROVEN_SOLVABLE');
                    const imp = solvResults.filter(r => r.verdict === 'PROVEN_IMPOSSIBLE');
                    const unc = solvResults.filter(r => r.verdict === 'UNCERTAIN');
                    return (
                      <>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] mb-1">
                          <span className="text-green-400">✅ 풀림(봇 한계): {sol.length}{sol.length > 0 ? ` — ${sol.map(r => r.level_number).join(', ')}` : ''}</span>
                          <span className="text-red-400">❌ 진짜 불가능: {imp.length}{imp.length > 0 ? ` — ${imp.map(r => r.level_number).join(', ')}` : ''}</span>
                          <span className="text-yellow-400">❔ 미확정: {unc.length}{unc.length > 0 ? ` — ${unc.map(r => r.level_number).join(', ')}` : ''}</span>
                        </div>
                        <p className="text-[10px] text-gray-500">
                          ✅풀림 = 솔버가 클리어 경로를 찾음(봇만 못 깬 것, 재생성 불필요) · ❌불가능 = 구조적 데드락/÷3 위반(재생성 권장) · ❔미확정 = 예산 초과(기믹 포함 등)
                        </p>
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
          )}
          {summary.luckCount > 0 && (
            <p className="text-xs text-yellow-300 mt-1">
              운빨 의심 레벨 (실력 무관, ΔP&lt;25%p): {summary.luckLevels.join(', ')}
            </p>
          )}
        </div>
      )}

      {/* 0.5단계: 부적절 레벨 자동 교체 */}
      {rows.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
          <div>
            <h3 className="text-sm font-bold text-white">🔧 부적절 레벨 자동 교체 (0.5단계)</h3>
            <p className="text-xs text-gray-400 mt-0.5">
              목표 난이도 스케줄(레벨 번호 → 목표 θ₀ 선형 보간)에서 벗어난 레벨,
              언클리어러블, 계단 과다(k 초과), 운빨 레벨을 찾아 곡선 타겟 탐색으로 교체합니다.
              <span className="text-yellow-300"> 적용 버튼을 누르기 전까지 프로덕션 데이터는 변경되지 않습니다.</span>
            </p>
          </div>

          {/* 스케줄 모드 선택 */}
          <div className="flex gap-2 text-xs">
            {([
              { v: 'linear', label: '수동 2점 스케줄' },
              { v: 'batch', label: '배치 난이도 그래프 참조 (10레벨 톱니)' },
            ] as const).map(opt => (
              <label
                key={opt.v}
                className={`px-3 py-1.5 rounded border cursor-pointer ${
                  schedMode === opt.v
                    ? 'bg-blue-900/40 border-blue-500 text-blue-200'
                    : 'bg-gray-900 border-gray-700 text-gray-400 hover:bg-gray-700'
                }`}
              >
                <input
                  type="radio" name="schedMode" value={opt.v} className="hidden"
                  checked={schedMode === opt.v}
                  onChange={() => setSchedMode(opt.v)}
                  disabled={isRepairing}
                />
                {opt.label}
              </label>
            ))}
          </div>

          {schedMode === 'batch' && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <div className="md:col-span-2">
                <p className="text-gray-400">
                  각 레벨 메타의 target_difficulty(생성 시 설정한 10레벨 단위 톱니 상승 그래프)를
                  목표 θ₀로 매핑합니다.
                  {(() => {
                    const b = batches.find(x => x.id === selectedBatchId);
                    return b ? (
                      <span className="block mt-1 text-gray-500">
                        배치 난이도 범위: {b.difficulty_start} → {b.difficulty_end}
                        {' '}(이 범위가 아래 θ₀ 범위로 변환됨 · 보스/톱니 모양은 그래프 그대로 유지)
                      </span>
                    ) : null;
                  })()}
                </p>
              </div>
              <div>
                <label className="block text-gray-400 mb-1">θ₀ @ 난이도 최소</label>
                <input type="number" min={0} max={1} step={0.05} value={batchThetaMin} disabled={isRepairing}
                  onChange={(e) => setBatchThetaMin(parseFloat(e.target.value) || 0)}
                  className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
              </div>
              <div>
                <label className="block text-gray-400 mb-1">θ₀ @ 난이도 최대</label>
                <input type="number" min={0} max={1} step={0.05} value={batchThetaMax} disabled={isRepairing}
                  onChange={(e) => setBatchThetaMax(parseFloat(e.target.value) || 0)}
                  className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
              </div>
            </div>
          )}

          {/* 스케줄/판정 기준 설정 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div className={schedMode === 'batch' ? 'opacity-40 pointer-events-none' : ''}>
              <label className="block text-gray-400 mb-1">스케줄 시작 (레벨 / θ₀)</label>
              <div className="flex gap-1">
                <input type="number" min={1} value={schedStartLevel} disabled={isRepairing}
                  onChange={(e) => setSchedStartLevel(parseInt(e.target.value, 10) || 1)}
                  className="w-1/2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
                <input type="number" min={0} max={1} step={0.05} value={schedStartTheta} disabled={isRepairing}
                  onChange={(e) => setSchedStartTheta(parseFloat(e.target.value) || 0)}
                  className="w-1/2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
              </div>
            </div>
            <div className={schedMode === 'batch' ? 'opacity-40 pointer-events-none' : ''}>
              <label className="block text-gray-400 mb-1">스케줄 끝 (레벨 / θ₀)</label>
              <div className="flex gap-1">
                <input type="number" min={schedStartLevel} value={schedEndLevel} disabled={isRepairing}
                  onChange={(e) => setSchedEndLevel(parseInt(e.target.value, 10) || 1500)}
                  className="w-1/2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
                <input type="number" min={0} max={1} step={0.05} value={schedEndTheta} disabled={isRepairing}
                  onChange={(e) => setSchedEndTheta(parseFloat(e.target.value) || 0)}
                  className="w-1/2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
              </div>
            </div>
            <div>
              <label className="block text-gray-400 mb-1">허용 밴드 ± / 보스 보정 +</label>
              <div className="flex gap-1">
                <input type="number" min={0.02} max={0.5} step={0.01} value={schedBand} disabled={isRepairing}
                  onChange={(e) => setSchedBand(parseFloat(e.target.value) || 0.1)}
                  className="w-1/2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
                <input type="number" min={0} max={0.3} step={0.01} value={schedBossBonus} disabled={isRepairing}
                  onChange={(e) => setSchedBossBonus(parseFloat(e.target.value) || 0)}
                  className="w-1/2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
              </div>
            </div>
            <div>
              <label className="block text-gray-400 mb-1">k 상한 / 교체 목표 k</label>
              <div className="flex gap-1">
                <input type="number" min={1} max={30} step={0.5} value={kMax} disabled={isRepairing}
                  onChange={(e) => setKMax(parseFloat(e.target.value) || 8)}
                  className="w-1/2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
                <input type="number" min={0.5} max={20} step={0.5} value={repairTargetK} disabled={isRepairing}
                  onChange={(e) => setRepairTargetK(parseFloat(e.target.value) || 4.5)}
                  className="w-1/2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white" />
              </div>
            </div>
          </div>

          {/* 실행 */}
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm">
              <span className="text-red-400 font-bold">부적절 {badRows.length}개</span>
              <span className="text-gray-500"> / 정상 {rows.length - badRows.length}개</span>
            </span>
            {!isRepairing ? (
              <button
                onClick={handleRepair}
                disabled={badRows.length === 0 || isRunning || isSearching}
                className="px-4 py-2 bg-orange-700 hover:bg-orange-600 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-md"
              >
                🔍 부적절 레벨 {badRows.length}개 교체 탐색
              </button>
            ) : (
              <button
                onClick={() => { repairCancelRef.current = true; }}
                className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white text-sm font-medium rounded-md"
              >
                ■ 중단 (현재 레벨 완료 후)
              </button>
            )}
            {isRepairing && (
              <div className="flex-1 min-w-[200px]">
                <div className="text-xs text-gray-400 mb-1">
                  교체 탐색 중… ({repairProgress.current}/{repairProgress.total})
                </div>
                <div className="w-full bg-gray-700 rounded-full h-2">
                  <div className="bg-orange-500 h-2 rounded-full transition-all"
                    style={{ width: `${repairProgress.total > 0 ? (repairProgress.current / repairProgress.total) * 100 : 0}%` }} />
                </div>
              </div>
            )}
          </div>

          {/* 비교/승인 테이블 */}
          {repairItems.length > 0 && (
            <div className="space-y-2">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-700">
                      <th className="px-2 py-1 text-center">
                        <label className="inline-flex items-center gap-1 cursor-pointer" title="전체 선택/해제 (교체 가능한 항목)">
                          <input
                            type="checkbox"
                            checked={allRepairSelected}
                            disabled={selectableRepairCount === 0 || isApplying}
                            onChange={toggleRepairSelectAll}
                          />
                          전체
                        </label>
                      </th>
                      <th className="px-2 py-1 text-left">레벨</th>
                      <th className="px-2 py-1 text-left">사유</th>
                      <th className="px-2 py-1 text-right">목표 θ₀</th>
                      <th className="px-2 py-1 text-right">기존 θ₀/k/1-AUC</th>
                      <th className="px-2 py-1 text-right">신규 θ₀/k/1-AUC</th>
                      <th className="px-2 py-1 text-left">신규 곡선</th>
                      <th className="px-2 py-1 text-left">상태</th>
                    </tr>
                  </thead>
                  <tbody>
                    {repairItems.map(item => (
                      <tr key={item.level_number} className={`border-b border-gray-700/40 ${item.applied ? 'opacity-50' : ''}`}>
                        <td className="px-2 py-1 text-center">
                          <input type="checkbox" checked={item.selected}
                            disabled={!item.best || item.applied || isApplying}
                            onChange={() => toggleRepairSelected(item.level_number)} />
                        </td>
                        <td className="px-2 py-1 font-mono text-gray-200">
                          <span className="inline-flex items-center gap-1">
                            Lv.{item.level_number}
                            <button
                              onClick={() => openProductionPreview(item.level_number)}
                              title="현재 프로덕션 레벨 미리보기"
                              className="text-gray-400 hover:text-white"
                            >
                              👁
                            </button>
                          </span>
                        </td>
                        <td className="px-2 py-1 text-red-400">{item.reasons.join(' · ')}</td>
                        <td className="px-2 py-1 text-right font-mono text-gray-300">{item.target_theta}</td>
                        <td className="px-2 py-1 text-right font-mono text-gray-500">
                          {item.old.theta0 ?? '-'} / {item.old.k ?? '-'} / {item.old.difficulty_score ?? '-'}
                        </td>
                        <td className="px-2 py-1 text-right font-mono text-blue-300">
                          {item.best ? (
                            <span className="inline-flex items-center gap-1">
                              {item.best.measurement.theta0} / {item.best.measurement.k} / {item.best.measurement.difficulty_score}
                              <button
                                onClick={() => openPreview(`Lv.${item.level_number} — 교체 후보 레벨`, item.best!.level_json)}
                                title="교체 후보 레벨 미리보기"
                                className="text-gray-400 hover:text-white"
                              >
                                👁
                              </button>
                            </span>
                          ) : '-'}
                        </td>
                        <td className="px-2 py-1">
                          {item.best && (
                            <div className="flex items-end gap-0.5 h-5">
                              {item.best.measurement.skill_curve.map(p => (
                                <div key={p.theta}
                                  title={`θ=${p.theta}: ${(p.clear_rate * 100).toFixed(0)}%`}
                                  className={`w-1.5 rounded-sm ${p.clear_rate >= 0.5 ? 'bg-emerald-500' : 'bg-red-500/70'}`}
                                  style={{ height: `${Math.max(10, p.clear_rate * 100)}%` }} />
                              ))}
                            </div>
                          )}
                        </td>
                        <td className="px-2 py-1">
                          {item.applied ? <span className="text-emerald-400">✅ 적용됨</span>
                            : item.error ? <span className="text-red-400">오류: {item.error}</span>
                            : !item.best ? <span className="text-red-400">후보 없음</span>
                            : item.accepted ? <span className="text-emerald-300">목표 달성 (score {item.best.score})</span>
                            : <span className="text-yellow-300">근사 (score {item.best.score})</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={handleApplyReplacements}
                  disabled={isApplying || repairItems.filter(i => i.selected && i.best && !i.applied).length === 0}
                  className="px-4 py-2 bg-red-800 hover:bg-red-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-md"
                >
                  {isApplying ? '⏳ 적용 중…' : `⚠️ 선택한 ${repairItems.filter(i => i.selected && i.best && !i.applied).length}개 레벨 교체 적용 (프로덕션 데이터 변경)`}
                </button>
                <span className="text-[11px] text-gray-500">
                  교체 직전 원본은 meta.mc_replaced_backup에 보관됩니다 · GBoost 반영은 내보내기 탭에서 재업로드
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 기획 난이도 그래프 vs 측정 비교 */}
      {rows.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-bold text-white">📈 기획 난이도 그래프 vs 측정 비교</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                위 교체 카드의 스케줄 모드({schedMode === 'batch' ? '배치 난이도 그래프 참조' : '수동 2점'}) 기준
                목표 θ₀와 측정 θ₀를 겹쳐 표시합니다.
              </p>
            </div>
            <div className="flex flex-wrap gap-4 text-sm">
              <span>
                <span className="text-gray-400 text-xs">밴드 내 일치율</span>{' '}
                <span className={`font-mono font-bold ${
                  graphComparison.withinBandRate >= 0.8 ? 'text-emerald-400'
                  : graphComparison.withinBandRate >= 0.5 ? 'text-yellow-300' : 'text-red-400'
                }`}>
                  {(graphComparison.withinBandRate * 100).toFixed(0)}%
                </span>
              </span>
              <span>
                <span className="text-gray-400 text-xs">평균 오차(MAE)</span>{' '}
                <span className="font-mono text-blue-300">{graphComparison.mae.toFixed(3)}</span>
              </span>
              <span>
                <span className="text-gray-400 text-xs">모양 상관(r)</span>{' '}
                <span className="font-mono text-blue-300">
                  {graphComparison.pearson !== null ? graphComparison.pearson.toFixed(2) : '-'}
                </span>
              </span>
              {graphComparison.unclearableCount > 0 && (
                <span className="text-red-400 text-xs self-center">
                  언클리어러블 {graphComparison.unclearableCount}개 (지표에서 제외)
                </span>
              )}
            </div>
          </div>

          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={graphComparison.data} margin={{ top: 5, right: 10, bottom: 5, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="level" stroke="#9ca3af" fontSize={11} />
              <YAxis domain={[0, 1]} stroke="#9ca3af" fontSize={11} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #4b5563', fontSize: 12 }}
                labelFormatter={(l) => `Lv.${l}`}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area
                name={`허용 밴드 ±${schedBand}`}
                dataKey="band"
                stroke="none"
                fill="#3b82f6"
                fillOpacity={0.12}
                isAnimationActive={false}
              />
              <Line
                name="목표 θ₀ (기획 그래프)"
                dataKey="target"
                stroke="#60a5fa"
                strokeDasharray="5 3"
                dot={false}
                isAnimationActive={false}
              />
              <Line
                name="측정 θ₀"
                dataKey="measured"
                stroke="#34d399"
                strokeWidth={1.5}
                dot={{ r: 2 }}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Scatter name="언클리어러블 (측정 불가)" dataKey="unclearable" fill="#ef4444" isAnimationActive={false} />
              <Scatter
                name="교체 후보 θ₀ (탐색됨)"
                dataKey="candidate"
                fill="#facc15"
                shape="diamond"
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>

          <p className="text-[11px] text-gray-500">
            밴드 내 일치율 = |측정 θ₀ - 목표 θ₀| ≤ {schedBand}인 레벨 비율 ·
            모양 상관(r)은 그래프의 상승 패턴(톱니 포함)이 측정에서 재현되는 정도 (1에 가까울수록 유사) ·
            언클리어러블 레벨은 상단 빨간 점으로 표시
            {graphComparison.candidateCount > 0 && (
              <span className="text-yellow-300">
                {' '}· 노란 마름모 {graphComparison.candidateCount}개 = 교체 탐색으로 찾은 새 후보의 θ₀
                (기존 초록 점/빨간 점과 비교 — 밴드 안에 들어왔는지 확인)
              </span>
            )}
          </p>
        </div>
      )}

      {/* 결과 테이블 */}
      {rows.length > 0 && (
        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-gray-400 text-xs">
                <th className="px-3 py-2 text-left">레벨</th>
                <th className="px-3 py-2 text-left">기존 등급</th>
                <th className="px-3 py-2 text-right">목표 난이도</th>
                <th className="px-3 py-2 text-right">난이도 (1-AUC)</th>
                <th className="px-3 py-2 text-right">θ₀ (50% 지점)</th>
                <th className="px-3 py-2 text-right">k (민감도)</th>
                <th className="px-3 py-2 text-left">분류</th>
                <th className="px-3 py-2 text-left">판정</th>
                <th className="px-3 py-2 text-left">스킬→클리어율 곡선</th>
                <th className="px-3 py-2 text-right">최고 클리어율</th>
                <th className="px-3 py-2 text-right">롤아웃</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.level_number} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                  <td className="px-3 py-1.5 font-mono text-gray-200">
                    <span className="inline-flex items-center gap-1">
                      Lv.{row.level_number}
                      {row.luck_suspect && <span title="운빨 레벨 의심">🎲</span>}
                      <button
                        onClick={() => openProductionPreview(row.level_number)}
                        title="현재 프로덕션 레벨 미리보기"
                        className="text-gray-400 hover:text-white"
                      >
                        👁
                      </button>
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-gray-300">{row.grade}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                    {row.target_difficulty !== null ? row.target_difficulty.toFixed(2) : '-'}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-blue-300">
                    {row.difficulty_score !== null ? row.difficulty_score.toFixed(3) : '-'}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-gray-300">
                    {row.theta0 !== null ? row.theta0.toFixed(2) : '-'}
                  </td>
                  <td className={`px-3 py-1.5 text-right font-mono ${row.luck_suspect ? 'text-yellow-300' : 'text-gray-300'}`}>
                    {row.k !== null ? row.k.toFixed(1) : '-'}
                  </td>
                  <td className={`px-3 py-1.5 ${CLASSIFICATION_LABELS[row.classification].color}`}>
                    {row.error ? `오류: ${row.error}` : CLASSIFICATION_LABELS[row.classification].label}
                  </td>
                  <td className="px-3 py-1.5 text-xs">
                    {(() => {
                      const a = assessments.get(row.level_number);
                      if (!a || a.reasons.length === 0) return <span className="text-green-500">✓</span>;
                      return <span className="text-red-400">{a.reasons.join(' · ')}</span>;
                    })()}
                  </td>
                  <td className="px-3 py-1.5">
                    {/* 미니 곡선: 스킬 포인트별 클리어율 막대 */}
                    <div className="flex items-end gap-0.5 h-6">
                      {row.curve_summary.map(p => (
                        <div
                          key={p.theta}
                          title={`θ=${p.theta}: ${(p.clear_rate * 100).toFixed(0)}%`}
                          className={`w-2 rounded-sm ${p.clear_rate >= 0.5 ? 'bg-green-500' : 'bg-red-500/70'}`}
                          style={{ height: `${Math.max(8, p.clear_rate * 100)}%` }}
                        />
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-gray-300">
                    {(row.max_clear_rate * 100).toFixed(0)}%
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-gray-500">{row.total_rollouts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 레벨 미리보기 팝업 */}
      {preview && (
        <div
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center"
          onClick={() => setPreview(null)}
        >
          <div
            className="bg-gray-800 border border-gray-600 rounded-xl p-4 max-w-lg w-full mx-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-white">{preview.title}</h3>
              <button
                onClick={() => setPreview(null)}
                className="text-gray-400 hover:text-white text-lg leading-none"
              >
                ✕
              </button>
            </div>

            <div className="flex items-center justify-center bg-gray-900 rounded-lg min-h-[300px]">
              {previewLoading ? (
                <span className="text-gray-400 text-sm">렌더링 중…</span>
              ) : previewImg ? (
                <img
                  src={previewImg}
                  alt="level preview"
                  className="max-w-full max-h-[420px] rounded"
                />
              ) : (
                <span className="text-red-400 text-sm">미리보기 렌더링 실패</span>
              )}
            </div>

            {/* 레벨 요약 정보 */}
            {(() => {
              const lv = preview.levelJson;
              const layerCount = Number(lv.layer) || 0;
              let tileCount = 0;
              const gimmicks = new Set<string>();
              for (let i = 0; i < layerCount; i++) {
                const layerData = (lv as unknown as Record<string, unknown>)[`layer_${i}`] as
                  | { tiles?: Record<string, [string, string?]> }
                  | undefined;
                const tiles = layerData?.tiles || {};
                tileCount += Object.keys(tiles).length;
                for (const t of Object.values(tiles)) {
                  if (t[1]) gimmicks.add(String(t[1]));
                }
              }
              return (
                <div className="mt-3 text-xs text-gray-400 flex flex-wrap gap-x-4 gap-y-1">
                  <span>레이어 {layerCount}</span>
                  <span>타일 {tileCount}개</span>
                  <span>타일종류 {lv.useTileCount ?? '-'}</span>
                  <span>시드 {lv.randSeed ?? '-'}</span>
                  <span>기믹: {gimmicks.size > 0 ? [...gimmicks].join(', ') : '없음'}</span>
                </div>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}

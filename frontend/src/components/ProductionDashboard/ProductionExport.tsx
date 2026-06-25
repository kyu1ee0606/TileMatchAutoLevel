/**
 * Production Export Component
 * 프로덕션 레벨 내보내기 (JSON, 로컬레벨, GBoost)
 */

import { useState, useEffect } from 'react';
import { ProductionStats, ProductionExportConfig, ProductionLevel } from '../../types/production';
import { TileData, LevelJSON } from '../../types';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { exportProductionLevels, getProductionLevelsByBatch, saveProductionLevel } from '../../storage/productionStorage';
import { saveLevelSetToStorage, saveLocalLevelToStorage } from '../../storage/levelStorage';
import { checkGBoostHealth, listFromGBoost, loadFromGBoost, saveToGBoost } from '../../api/gboost';
import { simulateLevelSkillSweep } from '../../api/rlSim';

// Migration helper: fix tile data format for Unity client compatibility
function migrateTileData(tileData: TileData): { changed: boolean; data: TileData } {
  if (!Array.isArray(tileData) || tileData.length < 2) {
    return { changed: false, data: tileData };
  }

  const tileType = tileData[0];
  const attribute = tileData[1] || '';
  const extra = tileData.length > 2 ? tileData[2] : undefined;

  // Skip craft/stack - they need extra field for count
  if (tileType.startsWith('craft_') || tileType.startsWith('stack_')) {
    return { changed: false, data: tileData };
  }

  let newAttribute = attribute;
  let changed = false;

  // Fix ice: "ice_1", "ice_2", "ice_3" → "ice"
  if (attribute.startsWith('ice_')) {
    newAttribute = 'ice';
    changed = true;
  }

  // Fix bomb: "bomb" + [N] → "bomb_N"
  if (attribute === 'bomb' && extra && Array.isArray(extra) && extra.length > 0) {
    const countdown = extra[0];
    if (typeof countdown === 'number') {
      newAttribute = `bomb_${countdown}`;
      changed = true;
    }
  }

  // Fix teleport: "teleport" → "teleporter" (remove extra)
  if (attribute === 'teleport') {
    newAttribute = 'teleporter';
    changed = true;
  }

  if (changed) {
    // Return without extra field (except for craft/stack)
    return { changed: true, data: [tileType, newAttribute] };
  }

  // Clear extra field if not craft/stack
  if (extra !== undefined && !tileType.startsWith('craft_') && !tileType.startsWith('stack_')) {
    return { changed: true, data: [tileType, attribute] };
  }

  return { changed: false, data: tileData };
}

// Migration helper: fix level JSON format
function migrateLevelJson(levelJson: LevelJSON): { changed: boolean; level: LevelJSON } {
  let totalChanged = false;
  // Deep copy to avoid mutating original
  const newLevel = JSON.parse(JSON.stringify(levelJson)) as LevelJSON;

  const numLayers = levelJson.layer || 8;
  for (let i = 0; i < numLayers; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;
    const layerData = newLevel[layerKey];
    if (!layerData?.tiles) continue;

    const newTiles: Record<string, TileData> = {};
    for (const [pos, tileData] of Object.entries(layerData.tiles)) {
      const { changed, data } = migrateTileData(tileData);
      newTiles[pos] = data;
      if (changed) totalChanged = true;
    }

    newLevel[layerKey] = { ...layerData, tiles: newTiles };
  }

  return { changed: totalChanged, level: newLevel };
}

type GBoostPhase = 'config' | 'checking' | 'conflict' | 'uploading' | 'complete';

interface ConflictInfo {
  targetId: string;
  levelNumber: number;
}

interface ProductionExportProps {
  batchId: string;
  batchName: string;
  stats: ProductionStats;
  onExportComplete?: (count: number) => void;
}

export function ProductionExport({
  batchId,
  batchName,
  stats,
  onExportComplete,
}: ProductionExportProps) {
  const { addNotification } = useUIStore();
  const [format, setFormat] = useState<'json' | 'json_minified' | 'json_split'>('json');
  const [includeMeta, setIncludeMeta] = useState(false);
  const [filenamePattern, setFilenamePattern] = useState('level_{number:04d}.json');
  const [isExporting, setIsExporting] = useState(false);

  // Local level export
  const [localSetName, setLocalSetName] = useState('');
  const [isSavingLocal, setIsSavingLocal] = useState(false);

  // GBoost export
  const [gboostBoardId, setGboostBoardId] = useState('levels');
  const [gboostLevelPrefix, setGboostLevelPrefix] = useState('level_');
  const [gboostStartIndex, setGboostStartIndex] = useState(1);
  const [gboostHealthy, setGboostHealthy] = useState(false);

  // Range selection
  const [useRange, setUseRange] = useState(false);
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(100);

  // Overwrite options
  const [overwrite, setOverwrite] = useState(true);
  const [backupBeforeOverwrite, setBackupBeforeOverwrite] = useState(true);

  // [v15.51] 업로드 대상 ID 미리보기 — 실제 level_number 기반.
  // 기존 UI는 gboostStartIndex 기반 synthetic 번호를 표시해서 batch에 레벨 7만 있어도
  // "level_1"로 보여 사용자 혼란을 일으켰음. 이제 실제 업로드되는 ID를 정확히 보여줌.
  const [previewTargetIds, setPreviewTargetIds] = useState<string[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Reward coin bulk override (applies only to GBoost upload payload — does not modify saved level)
  // mode 'preserve': use existing level_json.rewardCoin (or backend default 10)
  // mode 'fixed':    apply the same coin value to every uploaded level
  // mode 'tiered':   apply different values for boss (level%10===0) / special (level%10===9) / normal
  type RewardCoinMode = 'preserve' | 'fixed' | 'tiered';
  const [rewardCoinMode, setRewardCoinMode] = useState<RewardCoinMode>('preserve');
  const [rewardCoinFixed, setRewardCoinFixed] = useState(10);
  const [rewardCoinBoss, setRewardCoinBoss] = useState(50);
  const [rewardCoinSpecial, setRewardCoinSpecial] = useState(30);
  const [rewardCoinNormal, setRewardCoinNormal] = useState(10);

  // autoCollectCount (암호화) bulk override (upload payload only — does not modify saved level)
  // mode 'preserve':     use existing level_json.autoCollectCount (or 0)
  // mode 'multiples10':  set the given value on levels where level_number % 10 === 0, 0 (해제) on others
  type AutoCollectMode = 'preserve' | 'multiples10';
  const [autoCollectMode, setAutoCollectMode] = useState<AutoCollectMode>('preserve');
  const [autoCollectValue, setAutoCollectValue] = useState(1);

  // Upload state
  const [gboostPhase, setGboostPhase] = useState<GBoostPhase>('config');
  const [gboostProgress, setGboostProgress] = useState({ current: 0, total: 0 });
  const [conflictingLevels, setConflictingLevels] = useState<ConflictInfo[]>([]);
  const [backupProgress, setBackupProgress] = useState({ current: 0, total: 0 });
  const [uploadResult, setUploadResult] = useState({ success: 0, failed: 0, skipped: 0 });

  // Migration state
  const [isMigrating, setIsMigrating] = useState(false);
  const [migrationProgress, setMigrationProgress] = useState<{
    current: number;
    total: number;
    fixed: number;
    skipped: number;
  } | null>(null);

  const readyCount = stats.by_status.approved;
  const exportedCount = stats.by_status.exported;
  const totalReady = readyCount + exportedCount;

  // Calculate effective range
  const effectiveStart = useRange ? rangeStart : 1;
  const effectiveEnd = useRange ? rangeEnd : totalReady;
  const effectiveCount = Math.max(0, effectiveEnd - effectiveStart + 1);

  // Check GBoost health on mount
  useEffect(() => {
    checkGBoostHealth()
      .then(res => setGboostHealthy(res.healthy ?? false))
      .catch(() => setGboostHealthy(false));
  }, []);

  // Initialize local set name
  useEffect(() => {
    if (!localSetName && batchName) {
      setLocalSetName(`${batchName}_export`);
    }
  }, [batchName, localSetName]);

  // Reset phase when config changes
  useEffect(() => {
    if (gboostPhase !== 'config') {
      setGboostPhase('config');
      setConflictingLevels([]);
      setUploadResult({ success: 0, failed: 0, skipped: 0 });
    }
  }, [gboostBoardId, gboostLevelPrefix, gboostStartIndex, useRange, rangeStart, rangeEnd]);

  // 미리보기 ID 계산 — config 변경 시마다 실제 업로드 대상 산출
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setPreviewLoading(true);
      try {
        const exportable = await getExportableLevels();
        if (cancelled) return;
        setPreviewTargetIds(exportable.map(l => `${gboostLevelPrefix}${l.meta.level_number}`));
      } catch {
        if (!cancelled) setPreviewTargetIds([]);
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId, gboostLevelPrefix, useRange, rangeStart, rangeEnd, totalReady]);

  // Get target level ID from actual level number
  const getTargetLevelId = (levelNumber: number): string => {
    // gboostStartIndex는 GBoost에서 시작할 번호 (기본 1)
    // levelNumber는 실제 레벨 번호 (예: 35)
    // useRange가 활성화되면 레벨 번호를 그대로 사용하거나, 오프셋 적용
    // 예: 레벨 35를 level_35로 업로드하려면 gboostStartIndex를 레벨번호와 일치시키거나
    //     또는 레벨 35를 level_1로 업로드하려면 오프셋 계산 필요
    // 현재 로직: 레벨 번호를 ID에 직접 반영 (더 직관적)
    return `${gboostLevelPrefix}${levelNumber}`;
  };

  // JSON 파일 내보내기
  const handleExportJson = async () => {
    if (readyCount === 0) {
      addNotification('warning', '내보낼 승인된 레벨이 없습니다');
      return;
    }

    setIsExporting(true);

    try {
      const config: ProductionExportConfig = {
        format,
        include_meta: includeMeta,
        filename_pattern: filenamePattern,
        output_dir: '',
      };

      const result = await exportProductionLevels(batchId, config);

      if ('files' in result) {
        addNotification('success', `${result.files.length}개 파일 생성됨`);

        if (result.files.length <= 10) {
          for (const file of result.files) {
            const url = URL.createObjectURL(file.data);
            const a = document.createElement('a');
            a.href = url;
            a.download = file.name;
            a.click();
            URL.revokeObjectURL(url);
          }
        } else {
          addNotification('info', 'ZIP 다운로드는 추후 지원 예정입니다. JSON 포맷을 권장합니다.');
        }
      } else {
        const url = URL.createObjectURL(result);
        const a = document.createElement('a');
        a.href = url;
        a.download = `production_levels_${batchId}.json`;
        a.click();
        URL.revokeObjectURL(url);

        addNotification('success', `${totalReady}개 레벨 내보내기 완료`);
      }

      onExportComplete?.(totalReady);
    } catch (err) {
      addNotification('error', `내보내기 실패: ${(err as Error).message}`);
    } finally {
      setIsExporting(false);
    }
  };

  // 로컬 레벨로 저장
  const handleSaveToLocal = async () => {
    if (totalReady === 0) {
      addNotification('warning', '저장할 레벨이 없습니다');
      return;
    }

    if (!localSetName.trim()) {
      addNotification('warning', '폴더 이름을 입력해주세요');
      return;
    }

    setIsSavingLocal(true);

    try {
      const levels = await getProductionLevelsByBatch(batchId);
      const exportableLevels = levels.filter(
        l => l.meta.status === 'approved' || l.meta.status === 'exported'
      );

      if (exportableLevels.length === 0) {
        addNotification('warning', '내보낼 수 있는 레벨이 없습니다');
        return;
      }

      exportableLevels.sort((a, b) => a.meta.level_number - b.meta.level_number);

      const result = saveLevelSetToStorage({
        name: localSetName.trim(),
        levels: exportableLevels.map(l => l.level_json),
        difficulty_profile: exportableLevels.map(l => l.meta.target_difficulty),
        actual_difficulties: exportableLevels.map(l => l.meta.actual_difficulty),
        grades: exportableLevels.map(l => l.meta.grade),
        generation_config: {
          source: 'production',
          batch_id: batchId,
          batch_name: batchName,
        },
      });

      if (result.success) {
        addNotification('success', `${exportableLevels.length}개 레벨을 '${localSetName}'로 저장했습니다`);
        onExportComplete?.(exportableLevels.length);
      } else {
        addNotification('error', result.message);
      }
    } catch (err) {
      addNotification('error', `로컬 저장 실패: ${(err as Error).message}`);
    } finally {
      setIsSavingLocal(false);
    }
  };

  // Get exportable levels with range filter
  const getExportableLevels = async (): Promise<ProductionLevel[]> => {
    const levels = await getProductionLevelsByBatch(batchId);
    // 레벨 데이터가 있는 모든 레벨 (generated, approved, exported 등)
    let exportableLevels = levels.filter(l => l.level_json);
    exportableLevels.sort((a, b) => a.meta.level_number - b.meta.level_number);

    if (useRange) {
      // 레벨 번호 기준으로 필터링
      exportableLevels = exportableLevels.filter(
        l => l.meta.level_number >= effectiveStart && l.meta.level_number <= effectiveEnd
      );
    }

    return exportableLevels;
  };

  // Check for conflicts
  const handleCheckConflicts = async () => {
    if (effectiveCount === 0) {
      addNotification('warning', '업로드할 레벨이 없습니다');
      return;
    }

    if (!gboostHealthy) {
      addNotification('error', 'GBoost 연결이 설정되지 않았습니다');
      return;
    }

    setGboostPhase('checking');
    setConflictingLevels([]);

    try {
      // [v15.51] Conflict-check 대상 ID는 실제 업로드와 동일한 규칙 — 즉 각 레벨의
      // 실제 level_number 기반으로 산출. 기존: effectiveStart부터 1씩 증가하는 synthetic
      // 번호로 만들었기 때문에 batch에 레벨 7만 있어도 ID가 level_1로 표시되어
      // 실제 업로드 대상(level_7)과 불일치 → 사용자 혼란.
      const exportableForCheck = await getExportableLevels();
      const targetIds: ConflictInfo[] = exportableForCheck.map(l => ({
        targetId: getTargetLevelId(l.meta.level_number),
        levelNumber: l.meta.level_number,
      }));

      // Get existing levels from server (fetch more than needed to ensure all conflicts are detected)
      const fetchLimit = Math.max(targetIds.length + 100, 2000);
      const existingLevels = await listFromGBoost(gboostBoardId, gboostLevelPrefix, fetchLimit);
      const existingIds = new Set(existingLevels.levels.map(l => l.id));

      // Find conflicts
      const conflicts = targetIds.filter(t => existingIds.has(t.targetId));
      setConflictingLevels(conflicts);

      if (conflicts.length > 0) {
        setGboostPhase('conflict');
      } else {
        // No conflicts, proceed directly
        await handleUpload();
      }
    } catch (err) {
      console.error('Failed to check conflicts:', err);
      // If we can't check, proceed with upload
      await handleUpload();
    }
  };

  // Backup and upload
  const handleBackupAndUpload = async () => {
    if (backupBeforeOverwrite && conflictingLevels.length > 0) {
      setBackupProgress({ current: 0, total: conflictingLevels.length });

      for (let i = 0; i < conflictingLevels.length; i++) {
        const conflict = conflictingLevels[i];
        try {
          const serverLevel = await loadFromGBoost(gboostBoardId, conflict.targetId);
          const backupId = `backup_${conflict.targetId}_${Date.now()}`;
          saveLocalLevelToStorage({
            id: backupId,
            name: `[백업] ${conflict.targetId}`,
            description: `GBoost 서버에서 백업됨 (덮어쓰기 전)`,
            tags: ['backup', 'gboost', conflict.targetId],
            source: 'gboost_backup',
            level_data: serverLevel.level_json,
            validation_status: 'unknown',
          });
        } catch (err) {
          console.warn(`Failed to backup ${conflict.targetId}:`, err);
        }
        setBackupProgress({ current: i + 1, total: conflictingLevels.length });
      }
    }

    await handleUpload();
  };

  // Upload to GBoost (saveToGBoost 직접 사용)
  const handleUpload = async () => {
    setGboostPhase('uploading');
    setGboostProgress({ current: 0, total: 0 });
    setUploadResult({ success: 0, failed: 0, skipped: 0 });

    try {
      const exportableLevels = await getExportableLevels();

      if (exportableLevels.length === 0) {
        addNotification('warning', '업로드할 수 있는 레벨이 없습니다');
        setGboostPhase('config');
        return;
      }

      // [v16] 내보내기 전 RL 일괄측정 — predicted 없는 레벨은 difficulty가 -1로 나가므로,
      // 배포 직전 미검증 레벨을 RL 측정해 predicted를 채운다(수동 클릭 불필요). 병렬 청크 처리.
      const needRL = exportableLevels.filter(l => l.meta.predicted_clear_rate === undefined);
      if (needRL.length > 0) {
        addNotification('info', `RL 일괄측정: 미검증 ${needRL.length}개 측정 시작…`);
        setGboostProgress({ current: 0, total: needRL.length });
        const RL_CONC = 5;
        let measured = 0;
        for (let s = 0; s < needRL.length; s += RL_CONC) {
          const chunk = needRL.slice(s, s + RL_CONC);
          await Promise.all(chunk.map(async (l) => {
            try {
              const rl = await simulateLevelSkillSweep({
                level_json: l.level_json,
                target_difficulty: l.meta.target_difficulty,
              });
              // in-memory 메타 갱신 → 아래 배포 루프가 predicted를 payload에 주입
              l.meta.predicted_clear_rate = rl.predicted_clear_rate;
              l.meta.target_clear_rate = rl.target_clear_rate ?? undefined;
              l.meta.clear_rate_gap = rl.clear_rate_gap ?? undefined;
              l.meta.rl_classification = rl.classification;
              l.meta.verification_method = 'rl';
              await saveProductionLevel(batchId, l); // 영속화(다음 내보내기시 재측정 방지)
            } catch {
              /* 측정 실패 레벨은 difficulty -1로 나감 (스킵) */
            }
          }));
          measured += chunk.length;
          setGboostProgress({ current: measured, total: needRL.length });
        }
        addNotification('success', `RL 일괄측정 완료: ${needRL.length}개`);
      }

      setGboostProgress({ current: 0, total: exportableLevels.length });

      let successCount = 0;
      let failCount = 0;
      let skippedCount = 0;

      // 충돌 레벨 ID 집합 (overwrite=false일 때 건너뛰기 위함)
      const conflictIds = new Set(conflictingLevels.map(c => c.targetId));

      // Decide rewardCoin per level based on UI mode (does not mutate saved level data).
      const resolveRewardCoin = (levelNumber: number, savedLevel: LevelJSON): number | null => {
        if (rewardCoinMode === 'preserve') return null; // do not override
        if (rewardCoinMode === 'fixed') return Math.max(0, Math.floor(rewardCoinFixed));
        // tiered
        const isBoss = levelNumber > 0 && levelNumber % 10 === 0;
        const isSpecial = levelNumber % 10 === 9;
        if (isBoss) return Math.max(0, Math.floor(rewardCoinBoss));
        if (isSpecial) return Math.max(0, Math.floor(rewardCoinSpecial));
        // Avoid unused-var TS warning: explicitly read savedLevel for parity with future per-level rules
        void savedLevel;
        return Math.max(0, Math.floor(rewardCoinNormal));
      };

      // Decide autoCollectCount (암호화) per level based on UI mode (upload payload only).
      const resolveAutoCollect = (levelNumber: number): number | null => {
        if (autoCollectMode === 'preserve') return null; // do not override
        // multiples10: 10·20·30… 레벨은 설정값, 나머지는 0 (해제)
        const isMultipleOf10 = levelNumber > 0 && levelNumber % 10 === 0;
        return isMultipleOf10 ? Math.max(0, Math.floor(autoCollectValue)) : 0;
      };

      for (let i = 0; i < exportableLevels.length; i++) {
        const level = exportableLevels[i];
        const targetId = getTargetLevelId(level.meta.level_number);

        // overwrite=false이고 충돌이 있으면 건너뛰기
        if (!overwrite && conflictIds.has(targetId)) {
          skippedCount++;
          setGboostProgress({ current: i + 1, total: exportableLevels.length });
          continue;
        }

        // 업로드 페이로드에만 rewardCoin / autoCollectCount 주입 (저장본은 그대로 둠)
        const overrideCoin = resolveRewardCoin(level.meta.level_number, level.level_json);
        const overrideAutoCollect = resolveAutoCollect(level.meta.level_number);
        let uploadJson: LevelJSON = level.level_json;
        if (overrideCoin !== null || overrideAutoCollect !== null) {
          uploadJson = { ...level.level_json };
          if (overrideCoin !== null) uploadJson.rewardCoin = overrideCoin;
          if (overrideAutoCollect !== null) uploadJson.autoCollectCount = overrideAutoCollect;
        }
        // [v16] 인게임 표시용 예측 클리어율 주입 → 컨버터가 difficulty=round(predicted×100)로 변환.
        // meta에만 있는 predicted를 배포 payload(level_json)에 실어 컨버터까지 전달.
        if (level.meta.predicted_clear_rate !== undefined) {
          uploadJson = { ...uploadJson, predicted_clear_rate: level.meta.predicted_clear_rate } as unknown as LevelJSON;
        }

        try {
          // saveToGBoost는 level_json을 직접 받아서 TownPop 변환 및 썸네일 생성
          await saveToGBoost(gboostBoardId, targetId, uploadJson);
          successCount++;
        } catch (err) {
          console.error(`Failed to upload ${targetId}:`, err);
          failCount++;
        }

        setGboostProgress({ current: i + 1, total: exportableLevels.length });
      }

      setUploadResult({ success: successCount, failed: failCount, skipped: skippedCount });
      setGboostPhase('complete');

      if (failCount === 0 && skippedCount === 0) {
        addNotification('success', `${successCount}개 레벨을 GBoost에 업로드했습니다`);
      } else if (failCount === 0) {
        addNotification('success', `${successCount}개 업로드, ${skippedCount}개 건너뜀`);
      } else {
        addNotification('warning', `${successCount}개 성공, ${failCount}개 실패, ${skippedCount}개 건너뜀`);
      }

      onExportComplete?.(successCount);
    } catch (err) {
      addNotification('error', `GBoost 업로드 실패: ${(err as Error).message}`);
      setGboostPhase('config');
    }
  };

  // Reset to config
  const handleResetGBoost = () => {
    setGboostPhase('config');
    setConflictingLevels([]);
    setGboostProgress({ current: 0, total: 0 });
    setBackupProgress({ current: 0, total: 0 });
    setUploadResult({ success: 0, failed: 0, skipped: 0 });
  };

  // Migrate gimmick formats in local production levels
  const handleMigration = async () => {
    if (isMigrating) return;

    setIsMigrating(true);
    setMigrationProgress({ current: 0, total: 0, fixed: 0, skipped: 0 });

    try {
      // Get all levels in this batch
      const levels = await getProductionLevelsByBatch(batchId);

      if (levels.length === 0) {
        addNotification('warning', '마이그레이션할 레벨이 없습니다');
        setIsMigrating(false);
        setMigrationProgress(null);
        return;
      }

      setMigrationProgress({ current: 0, total: levels.length, fixed: 0, skipped: 0 });

      let fixed = 0;
      let skipped = 0;

      for (let i = 0; i < levels.length; i++) {
        const level = levels[i];

        try {
          // Migrate the level JSON
          const { changed, level: migratedLevel } = migrateLevelJson(level.level_json);

          if (changed) {
            // Save the migrated level back to IndexedDB
            const updatedLevel: ProductionLevel = {
              ...level,
              level_json: migratedLevel,
            };
            await saveProductionLevel(batchId, updatedLevel);
            fixed++;
          } else {
            skipped++;
          }
        } catch (err) {
          console.error(`Failed to migrate level ${level.meta.level_number}:`, err);
          skipped++;
        }

        setMigrationProgress({
          current: i + 1,
          total: levels.length,
          fixed,
          skipped,
        });
      }

      addNotification('success', `마이그레이션 완료: ${fixed}개 수정, ${skipped}개 스킵`);
    } catch (error) {
      console.error('Migration failed:', error);
      addNotification('error', '마이그레이션 중 오류 발생');
    } finally {
      setIsMigrating(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Export Summary */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">내보내기 요약</h3>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-green-400">{readyCount}</div>
            <div className="text-xs text-gray-400">승인됨 (대기)</div>
          </div>
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-indigo-400">{exportedCount}</div>
            <div className="text-xs text-gray-400">내보내기 완료</div>
          </div>
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-white">{totalReady}</div>
            <div className="text-xs text-gray-400">총 출시 가능</div>
          </div>
        </div>
      </div>

      {/* Gimmick Format Migration */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-3">
        <h3 className="text-sm font-medium text-white">기믹 포맷 마이그레이션</h3>
        <p className="text-xs text-gray-400">
          Unity 클라이언트 호환을 위해 기믹 포맷을 수정합니다.
          <br />
          • ice_1/2/3 → ice
          <br />
          • bomb + [N] → bomb_N
          <br />
          • teleport → teleporter
        </p>

        {migrationProgress && (
          <div className="space-y-2">
            <div className="flex justify-between text-xs text-gray-400">
              <span>진행 중...</span>
              <span>{migrationProgress.current} / {migrationProgress.total}</span>
            </div>
            <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-500 transition-all"
                style={{ width: `${(migrationProgress.current / migrationProgress.total) * 100}%` }}
              />
            </div>
            <div className="flex gap-4 text-xs">
              <span className="text-green-400">수정됨: {migrationProgress.fixed}</span>
              <span className="text-gray-400">스킵: {migrationProgress.skipped}</span>
            </div>
          </div>
        )}

        <Button
          onClick={handleMigration}
          disabled={isMigrating || stats.total_levels === 0}
          variant="secondary"
          className="w-full"
        >
          {isMigrating ? '마이그레이션 중...' : `기믹 포맷 마이그레이션 (${stats.total_levels}개 레벨)`}
        </Button>
      </div>

      {/* Local Level Export */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-3">
        <h3 className="text-sm font-medium text-white">로컬 레벨로 저장</h3>
        <p className="text-xs text-gray-400">
          레벨을 로컬 저장소에 새 폴더로 저장합니다. 이후 GBoost 패널에서 업로드할 수 있습니다.
        </p>

        <div>
          <label className="block text-xs text-gray-400 mb-1">폴더 이름</label>
          <input
            type="text"
            value={localSetName}
            onChange={(e) => setLocalSetName(e.target.value)}
            placeholder="예: production_v1"
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
          />
        </div>

        <Button
          onClick={handleSaveToLocal}
          disabled={isSavingLocal || totalReady === 0}
          variant="secondary"
          className="w-full"
        >
          {isSavingLocal ? '저장 중...' : `로컬에 저장 (${totalReady}개)`}
        </Button>
      </div>

      {/* GBoost Export */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-white">GBoost로 직접 업로드</h3>
          <span className={`text-xs px-2 py-1 rounded ${gboostHealthy ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
            {gboostHealthy ? '연결됨' : '연결 안됨'}
          </span>
        </div>

        {gboostHealthy ? (
          <>
            {/* Config Phase */}
            {gboostPhase === 'config' && (
              <>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Board ID</label>
                    <input
                      type="text"
                      value={gboostBoardId}
                      onChange={(e) => setGboostBoardId(e.target.value)}
                      placeholder="stage"
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">레벨 ID 프리픽스</label>
                    <input
                      type="text"
                      value={gboostLevelPrefix}
                      onChange={(e) => setGboostLevelPrefix(e.target.value)}
                      placeholder="level_"
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">시작 번호</label>
                    <input
                      type="number"
                      value={gboostStartIndex}
                      onChange={(e) => setGboostStartIndex(Math.max(1, parseInt(e.target.value) || 1))}
                      min={1}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                    />
                  </div>
                </div>

                {/* Range Selection */}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={useRange}
                      onChange={(e) => setUseRange(e.target.checked)}
                      className="rounded border-gray-600"
                    />
                    <span className="text-sm text-gray-300">범위 지정</span>
                  </label>

                  {useRange && (
                    <div className="flex items-center gap-2 ml-6">
                      <input
                        type="number"
                        value={rangeStart}
                        onChange={(e) => setRangeStart(Math.max(1, parseInt(e.target.value) || 1))}
                        min={1}
                        className="w-20 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                      />
                      <span className="text-gray-400">~</span>
                      <input
                        type="number"
                        value={rangeEnd}
                        onChange={(e) => setRangeEnd(Math.max(1, parseInt(e.target.value) || 1))}
                        min={1}
                        className="w-20 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
                      />
                      <span className="text-xs text-gray-500">번째 레벨</span>
                    </div>
                  )}
                </div>

                {/* Overwrite Options */}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={overwrite}
                      onChange={(e) => setOverwrite(e.target.checked)}
                      className="rounded border-gray-600"
                    />
                    <span className="text-sm text-gray-300">기존 레벨 덮어쓰기</span>
                  </label>

                  {overwrite && (
                    <label className="flex items-center gap-2 cursor-pointer ml-6">
                      <input
                        type="checkbox"
                        checked={backupBeforeOverwrite}
                        onChange={(e) => setBackupBeforeOverwrite(e.target.checked)}
                        className="rounded border-yellow-600"
                      />
                      <span className="text-sm text-yellow-300">덮어쓰기 전 기존 레벨 백업</span>
                    </label>
                  )}
                </div>

                <p className="text-xs text-gray-500">
                  {previewLoading ? (
                    <span>대상 ID 계산 중…</span>
                  ) : previewTargetIds.length === 0 ? (
                    <span>업로드 가능한 레벨이 없습니다.</span>
                  ) : previewTargetIds.length === 1 ? (
                    <span>업로드 대상: <code className="text-gray-300">{previewTargetIds[0]}</code> (1개)</span>
                  ) : previewTargetIds.length <= 5 ? (
                    <span>업로드 대상: <code className="text-gray-300">{previewTargetIds.join(', ')}</code> ({previewTargetIds.length}개)</span>
                  ) : (
                    <span>
                      업로드 대상: <code className="text-gray-300">{previewTargetIds[0]}</code> ~{' '}
                      <code className="text-gray-300">{previewTargetIds[previewTargetIds.length - 1]}</code>{' '}
                      ({previewTargetIds.length}개)
                    </span>
                  )}
                </p>

                {/* Reward Coin bulk override (upload-time only, does not modify saved level) */}
                <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-medium text-white">리워드 코인 (rewardCoin) 일괄 설정</h4>
                    <span className="text-[10px] text-gray-500">저장본 유지 · 업로드 페이로드만 덮어씀</span>
                  </div>

                  <div className="flex gap-2 text-xs">
                    {[
                      { v: 'preserve', label: '레벨 저장값 유지' },
                      { v: 'fixed', label: '일괄 고정값' },
                      { v: 'tiered', label: '타입별 차등' },
                    ].map(opt => (
                      <label
                        key={opt.v}
                        className={`flex-1 px-2 py-1.5 text-center rounded border cursor-pointer ${
                          rewardCoinMode === opt.v
                            ? 'bg-blue-900/40 border-blue-500 text-blue-200'
                            : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'
                        }`}
                      >
                        <input
                          type="radio"
                          name="rewardCoinMode"
                          value={opt.v}
                          checked={rewardCoinMode === opt.v}
                          onChange={(e) => setRewardCoinMode(e.target.value as typeof rewardCoinMode)}
                          className="hidden"
                        />
                        {opt.label}
                      </label>
                    ))}
                  </div>

                  {rewardCoinMode === 'fixed' && (
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-gray-400 whitespace-nowrap">고정값</label>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={rewardCoinFixed}
                        onChange={(e) => setRewardCoinFixed(parseInt(e.target.value, 10) || 0)}
                        className="flex-1 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                      />
                      <span className="text-xs text-gray-500">코인 / 레벨</span>
                    </div>
                  )}

                  {rewardCoinMode === 'tiered' && (
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="block text-[11px] text-orange-300 mb-0.5">보스 (10·20·…)</label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={rewardCoinBoss}
                          onChange={(e) => setRewardCoinBoss(parseInt(e.target.value, 10) || 0)}
                          className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-purple-300 mb-0.5">특수 (9·19·…)</label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={rewardCoinSpecial}
                          onChange={(e) => setRewardCoinSpecial(parseInt(e.target.value, 10) || 0)}
                          className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-gray-300 mb-0.5">일반</label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={rewardCoinNormal}
                          onChange={(e) => setRewardCoinNormal(parseInt(e.target.value, 10) || 0)}
                          className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                        />
                      </div>
                    </div>
                  )}

                  {rewardCoinMode === 'preserve' && (
                    <p className="text-[11px] text-gray-500">
                      각 레벨의 level_json.rewardCoin 값을 그대로 사용 (없으면 백엔드 기본값 10).
                    </p>
                  )}
                </div>

                {/* autoCollectCount (암호화) bulk override (upload-time only, does not modify saved level) */}
                <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-medium text-white">암호화 (autoCollectCount) 일괄 설정</h4>
                    <span className="text-[10px] text-gray-500">저장본 유지 · 업로드 페이로드만 덮어씀</span>
                  </div>

                  <div className="flex gap-2 text-xs">
                    {[
                      { v: 'preserve', label: '레벨 저장값 유지' },
                      { v: 'multiples10', label: '10의 배수 레벨만 설정' },
                    ].map(opt => (
                      <label
                        key={opt.v}
                        className={`flex-1 px-2 py-1.5 text-center rounded border cursor-pointer ${
                          autoCollectMode === opt.v
                            ? 'bg-blue-900/40 border-blue-500 text-blue-200'
                            : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'
                        }`}
                      >
                        <input
                          type="radio"
                          name="autoCollectMode"
                          value={opt.v}
                          checked={autoCollectMode === opt.v}
                          onChange={(e) => setAutoCollectMode(e.target.value as typeof autoCollectMode)}
                          className="hidden"
                        />
                        {opt.label}
                      </label>
                    ))}
                  </div>

                  {autoCollectMode === 'multiples10' && (
                    <>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-gray-400 whitespace-nowrap">설정값</label>
                        <input
                          type="number"
                          min={0}
                          max={999}
                          step={1}
                          value={autoCollectValue}
                          onChange={(e) => setAutoCollectValue(parseInt(e.target.value, 10) || 0)}
                          className="flex-1 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs text-white"
                        />
                        <span className="text-xs text-gray-500">(0 = 해제)</span>
                      </div>
                      <p className="text-[11px] text-gray-500">
                        10·20·30… 레벨에 설정값 적용, 나머지 레벨은 0(해제)으로 업로드.
                      </p>
                    </>
                  )}

                  {autoCollectMode === 'preserve' && (
                    <p className="text-[11px] text-gray-500">
                      각 레벨의 level_json.autoCollectCount 값을 그대로 사용 (없으면 0 = 해제).
                    </p>
                  )}
                </div>

                <Button
                  onClick={handleCheckConflicts}
                  disabled={previewTargetIds.length === 0}
                  className="w-full"
                >
                  서버 확인 후 업로드 ({previewTargetIds.length}개)
                </Button>
              </>
            )}

            {/* Checking Phase */}
            {gboostPhase === 'checking' && (
              <div className="flex flex-col items-center py-6">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mb-3"></div>
                <p className="text-sm text-gray-300">서버에서 기존 레벨 확인 중...</p>
              </div>
            )}

            {/* Conflict Phase */}
            {gboostPhase === 'conflict' && (
              <div className="space-y-3">
                <div className="bg-yellow-900/30 border border-yellow-600 rounded-lg p-3">
                  <div className="flex items-start gap-2">
                    <span className="text-xl">⚠️</span>
                    <div>
                      <h4 className="text-yellow-300 font-semibold text-sm">
                        {conflictingLevels.length}개 레벨이 이미 존재합니다
                      </h4>
                      <p className="text-yellow-200 text-xs mt-1">
                        덮어쓰기하면 기존 레벨이 대체됩니다.
                      </p>
                    </div>
                  </div>
                </div>

                <div className="bg-gray-900 rounded-lg p-2 max-h-32 overflow-y-auto">
                  {conflictingLevels.slice(0, 10).map((conflict) => (
                    <div key={conflict.targetId} className="flex items-center gap-2 text-xs py-1">
                      <span className="text-yellow-400">⚠</span>
                      <span className="text-yellow-300">{conflict.targetId}</span>
                    </div>
                  ))}
                  {conflictingLevels.length > 10 && (
                    <div className="text-xs text-gray-500 pt-1">
                      ... 외 {conflictingLevels.length - 10}개
                    </div>
                  )}
                </div>

                {backupBeforeOverwrite && (
                  <div className="bg-blue-900/30 border border-blue-700 rounded-lg p-2">
                    <p className="text-blue-300 text-xs">
                      ✓ 백업 옵션 활성화됨 - 덮어쓰기 전 기존 레벨이 로컬에 백업됩니다.
                    </p>
                  </div>
                )}

                {backupProgress.total > 0 && (
                  <div>
                    <div className="flex justify-between text-xs text-gray-400 mb-1">
                      <span>백업 진행 중...</span>
                      <span>{backupProgress.current} / {backupProgress.total}</span>
                    </div>
                    <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-yellow-500 transition-all"
                        style={{ width: `${(backupProgress.current / backupProgress.total) * 100}%` }}
                      />
                    </div>
                  </div>
                )}

                <div className="flex gap-2">
                  <Button
                    onClick={handleResetGBoost}
                    variant="secondary"
                    className="flex-1"
                  >
                    취소
                  </Button>
                  {overwrite ? (
                    <Button
                      onClick={handleBackupAndUpload}
                      disabled={backupProgress.total > 0}
                      className="flex-1"
                    >
                      {backupBeforeOverwrite ? '백업 후 덮어쓰기' : '덮어쓰기'}
                    </Button>
                  ) : (
                    <Button
                      onClick={handleUpload}
                      className="flex-1"
                    >
                      충돌 건너뛰고 업로드
                    </Button>
                  )}
                </div>
              </div>
            )}

            {/* Uploading Phase */}
            {gboostPhase === 'uploading' && gboostProgress.total > 0 && (
              <div className="space-y-3">
                <div className="flex justify-between text-xs text-gray-400">
                  <span>업로드 중...</span>
                  <span>{gboostProgress.current}/{gboostProgress.total}</span>
                </div>
                <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 transition-all"
                    style={{ width: `${(gboostProgress.current / gboostProgress.total) * 100}%` }}
                  />
                </div>
              </div>
            )}

            {/* Complete Phase */}
            {gboostPhase === 'complete' && (
              <div className="space-y-3">
                <div className="bg-green-900/30 border border-green-700 rounded-lg p-3">
                  <div className="flex items-center gap-4 text-sm">
                    <div className="flex items-center gap-1">
                      <span className="text-green-400">✓</span>
                      <span className="text-gray-300">{uploadResult.success} 성공</span>
                    </div>
                    {uploadResult.failed > 0 && (
                      <div className="flex items-center gap-1">
                        <span className="text-red-400">✕</span>
                        <span className="text-gray-300">{uploadResult.failed} 실패</span>
                      </div>
                    )}
                    {uploadResult.skipped > 0 && (
                      <div className="flex items-center gap-1">
                        <span className="text-yellow-400">⊘</span>
                        <span className="text-gray-300">{uploadResult.skipped} 건너뜀</span>
                      </div>
                    )}
                  </div>
                </div>

                <Button
                  onClick={handleResetGBoost}
                  variant="secondary"
                  className="w-full"
                >
                  완료
                </Button>
              </div>
            )}
          </>
        ) : (
          <p className="text-xs text-gray-500">
            GBoost 연결을 먼저 설정해주세요. (GBoost 패널에서 설정)
          </p>
        )}
      </div>

      {/* JSON Export Settings */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-4">
        <h3 className="text-sm font-medium text-white">JSON 파일 내보내기</h3>

        {/* Format */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">파일 포맷</label>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as typeof format)}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
          >
            <option value="json">JSON (단일 파일, 포맷팅)</option>
            <option value="json_minified">JSON (단일 파일, 압축)</option>
            <option value="json_split">JSON (개별 파일)</option>
          </select>
        </div>

        {/* Filename Pattern (for split mode) */}
        {format === 'json_split' && (
          <div>
            <label className="block text-xs text-gray-400 mb-1">파일명 패턴</label>
            <input
              type="text"
              value={filenamePattern}
              onChange={(e) => setFilenamePattern(e.target.value)}
              placeholder="level_{number:04d}.json"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            />
            <p className="text-xs text-gray-500 mt-1">
              {'{number}'} = 레벨 번호, {'{number:04d}'} = 4자리 패딩, {'{grade}'} = 등급
            </p>
          </div>
        )}

        {/* Include Meta */}
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={includeMeta}
            onChange={(e) => setIncludeMeta(e.target.checked)}
            className="rounded border-gray-600"
          />
          <span className="text-sm text-gray-300">메타데이터 포함</span>
          <span className="text-xs text-gray-500">(난이도, 등급 등)</span>
        </label>

        {/* Export Button */}
        <Button
          onClick={handleExportJson}
          disabled={isExporting || readyCount === 0}
          variant="secondary"
          className="w-full"
        >
          {isExporting ? '내보내는 중...' : `JSON 다운로드 (${totalReady}개)`}
        </Button>
      </div>
    </div>
  );
}

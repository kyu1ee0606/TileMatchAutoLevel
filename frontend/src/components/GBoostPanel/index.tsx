import { useState, useEffect, useCallback } from 'react';
import {
  checkGBoostHealth,
  getGBoostConfig,
  setGBoostConfig,
  loadFromGBoost,
  saveToGBoost,
} from '../../api/gboost';
import { CollapsiblePanel, Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { Save, Plug, Info, BookOpen, CheckCircle, AlertTriangle, XCircle, Wrench, RefreshCw } from 'lucide-react';
import clsx from 'clsx';
import type { LevelJSON, TileData } from '../../types';

interface GBoostPanelProps {
  className?: string;
}

// Migration helper: fix tile format for a single tile
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
  const newLevel = { ...levelJson };

  const numLayers = levelJson.layer || 8;
  for (let i = 0; i < numLayers; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;
    const layerData = levelJson[layerKey];
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

export function GBoostPanel({ className }: GBoostPanelProps) {
  const { addNotification } = useUIStore();

  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);
  const [configUrl, setConfigUrl] = useState('https://gameboost.cafe24.com/gameboost/');
  const [configApiKey, setConfigApiKey] = useState('');
  const [configProjectId, setConfigProjectId] = useState('6d126f4db852');
  const [isSavingConfig, setIsSavingConfig] = useState(false);
  const [isTestingConnection, setIsTestingConnection] = useState(false);

  // Migration state
  const [migrationBoardId, setMigrationBoardId] = useState('levels');
  const [migrationPrefix, setMigrationPrefix] = useState('level_');
  const [migrationStartLevel, setMigrationStartLevel] = useState(1);
  const [migrationEndLevel, setMigrationEndLevel] = useState(500);
  const [isMigrating, setIsMigrating] = useState(false);
  const [migrationProgress, setMigrationProgress] = useState<{
    current: number;
    total: number;
    fixed: number;
    skipped: number;
    errors: string[];
  } | null>(null);

  // Default values
  const DEFAULT_URL = 'https://gameboost.cafe24.com/gameboost/';
  const DEFAULT_PROJECT_ID = '6d126f4db852';

  // Load GBoost config on mount
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const [config, health] = await Promise.all([
          getGBoostConfig(),
          checkGBoostHealth(),
        ]);
        // Use server config if available, otherwise keep defaults
        setConfigUrl(config.url || DEFAULT_URL);
        setConfigProjectId(config.project_id || DEFAULT_PROJECT_ID);
        setIsConfigured(health.configured);
        setIsHealthy(health.healthy ?? null);
      } catch {
        setIsConfigured(false);
        setIsHealthy(false);
      }
    };
    loadConfig();
  }, []);

  const handleSaveConfig = async () => {
    if (!configUrl || !configProjectId) {
      addNotification('warning', 'URL과 Project ID는 필수입니다');
      return;
    }

    setIsSavingConfig(true);
    try {
      const result = await setGBoostConfig({
        url: configUrl,
        api_key: configApiKey,
        project_id: configProjectId,
      });
      if (result.configured) {
        addNotification('success', '설정이 저장되었습니다');
        setIsConfigured(true);
        // Test connection after save
        const health = await checkGBoostHealth();
        setIsHealthy(health.healthy ?? false);
      } else {
        addNotification('error', '설정 저장에 실패했습니다');
      }
    } catch (error) {
      console.error('Config save failed:', error);
      addNotification('error', '설정 저장 중 오류가 발생했습니다');
    } finally {
      setIsSavingConfig(false);
    }
  };

  const handleTestConnection = async () => {
    setIsTestingConnection(true);
    try {
      const health = await checkGBoostHealth();
      setIsHealthy(health.healthy ?? false);
      if (health.healthy) {
        addNotification('success', '서버 연결 성공');
      } else {
        addNotification('error', '서버 연결 실패');
      }
    } catch {
      setIsHealthy(false);
      addNotification('error', '서버 연결 실패');
    } finally {
      setIsTestingConnection(false);
    }
  };

  // Migration handler
  const handleMigrateLevels = useCallback(async () => {
    if (!isConfigured || !isHealthy) {
      addNotification('error', 'GBoost 서버에 먼저 연결하세요');
      return;
    }

    setIsMigrating(true);
    setMigrationProgress({ current: 0, total: 0, fixed: 0, skipped: 0, errors: [] });

    try {
      // Generate level IDs to migrate
      const levelIds: string[] = [];
      for (let i = migrationStartLevel; i <= migrationEndLevel; i++) {
        levelIds.push(`${migrationPrefix}${i.toString().padStart(3, '0')}`);
      }

      setMigrationProgress(prev => ({ ...prev!, total: levelIds.length }));

      let fixed = 0;
      let skipped = 0;
      const errors: string[] = [];

      for (let i = 0; i < levelIds.length; i++) {
        const levelId = levelIds[i];
        setMigrationProgress(prev => ({ ...prev!, current: i + 1 }));

        try {
          // Load level from GBoost
          const response = await loadFromGBoost(migrationBoardId, levelId);

          // Check if level has map field (TownPop format)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const originalJson = response.level_json as any;
          const hasTownPopWrapper = originalJson.map && typeof originalJson.map === 'object';
          const levelJson = hasTownPopWrapper ? originalJson.map as LevelJSON : originalJson as LevelJSON;

          // Migrate level format
          const { changed, level: migratedLevel } = migrateLevelJson(levelJson);

          if (changed) {
            // Preserve original wrapper structure if it existed
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const levelToSave = hasTownPopWrapper
              ? { ...originalJson, map: migratedLevel } as any
              : migratedLevel;

            // Save migrated level back to GBoost
            await saveToGBoost(migrationBoardId, levelId, levelToSave);
            fixed++;
          } else {
            skipped++;
          }
        } catch (err) {
          // Level might not exist, skip silently
          const errorMsg = err instanceof Error ? err.message : String(err);
          if (!errorMsg.includes('404') && !errorMsg.includes('not found')) {
            errors.push(`${levelId}: ${errorMsg}`);
          } else {
            skipped++;
          }
        }

        setMigrationProgress({ current: i + 1, total: levelIds.length, fixed, skipped, errors });

        // Small delay to avoid overwhelming the server
        if (i % 10 === 9) {
          await new Promise(resolve => setTimeout(resolve, 100));
        }
      }

      addNotification('success', `마이그레이션 완료: ${fixed}개 수정, ${skipped}개 스킵`);
    } catch (error) {
      console.error('Migration failed:', error);
      addNotification('error', '마이그레이션 중 오류 발생');
    } finally {
      setIsMigrating(false);
    }
  }, [isConfigured, isHealthy, migrationBoardId, migrationPrefix, migrationStartLevel, migrationEndLevel, addNotification]);

  const StatusIcon = isConfigured && isHealthy ? CheckCircle : isConfigured ? AlertTriangle : XCircle;
  const statusBadge = isConfigured !== null && (
    <span
      className={clsx(
        'px-2 py-1 text-xs rounded-full inline-flex items-center gap-1',
        isConfigured && isHealthy
          ? 'bg-green-900/50 text-green-300'
          : isConfigured
            ? 'bg-yellow-900/50 text-yellow-300'
            : 'bg-red-900/50 text-red-300'
      )}
    >
      <StatusIcon className="w-3 h-3" />
      {isConfigured && isHealthy ? '연결됨' : isConfigured ? '설정됨' : '미설정'}
    </span>
  );

  return (
    <CollapsiblePanel
      title="게임부스트 설정"
      icon="⚙️"
      headerRight={statusBadge}
      className={className}
    >
      <div className="flex flex-col gap-4">
        {/* Info */}
        <div className="bg-blue-900/30 border border-blue-700 rounded-md p-3 text-sm text-blue-200">
          <p className="font-medium flex items-center gap-1.5">
            <Info className="w-4 h-4" />
            설정 안내
          </p>
          <p className="text-xs mt-1 text-blue-300">
            게임부스트 서버 연결 설정을 구성합니다. 레벨 불러오기/저장은 에디터 탭에서 진행하세요.
          </p>
        </div>

        {/* Server URL */}
        <div>
          <label className="text-sm font-medium text-gray-300 block mb-1">
            서버 URL <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={configUrl}
            onChange={(e) => setConfigUrl(e.target.value)}
            placeholder="https://gameboost.cafe24.com/gameboost/"
            className="w-full px-3 py-2 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm placeholder-gray-500"
          />
          <p className="text-xs text-gray-500 mt-1">GBoost 서버의 기본 URL</p>
        </div>

        {/* API Key */}
        <div>
          <label className="text-sm font-medium text-gray-300 block mb-1">
            API Key <span className="text-gray-500">(선택)</span>
          </label>
          <input
            type="password"
            value={configApiKey}
            onChange={(e) => setConfigApiKey(e.target.value)}
            placeholder="API 키 입력"
            className="w-full px-3 py-2 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm placeholder-gray-500"
          />
          <p className="text-xs text-gray-500 mt-1">인증이 필요한 경우 입력</p>
        </div>

        {/* Project ID */}
        <div>
          <label className="text-sm font-medium text-gray-300 block mb-1">
            Project ID <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={configProjectId}
            onChange={(e) => setConfigProjectId(e.target.value)}
            placeholder="6d126f4db852"
            className="w-full px-3 py-2 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm placeholder-gray-500"
          />
          <p className="text-xs text-gray-500 mt-1">앱 ID (예: 6d126f4db852)</p>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2">
          <Button
            onClick={handleSaveConfig}
            disabled={isSavingConfig}
            isLoading={isSavingConfig}
            variant="success"
            icon={<Save className="w-full h-full" />}
            className="flex-1"
          >
            설정 저장
          </Button>
          <Button
            onClick={handleTestConnection}
            disabled={isTestingConnection || !isConfigured}
            isLoading={isTestingConnection}
            variant="primary"
            icon={<Plug className="w-full h-full" />}
          >
            연결 테스트
          </Button>
        </div>

        {/* Connection Status Details */}
        {isConfigured && (
          <div className="bg-gray-900 border border-gray-700 rounded-md p-3">
            <h3 className="text-sm font-medium text-gray-300 mb-2">연결 상태</h3>
            <div className="space-y-1 text-xs">
              <div className="flex justify-between">
                <span className="text-gray-500">서버:</span>
                <span className="text-gray-300 truncate max-w-[200px]">{configUrl || '-'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">프로젝트:</span>
                <span className="text-gray-300">{configProjectId || '-'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">상태:</span>
                <span className={isHealthy ? 'text-green-400' : 'text-yellow-400'}>
                  {isHealthy ? '정상' : '확인 필요'}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Usage Guide */}
        <div className="bg-gray-900 border border-gray-700 rounded-md p-3">
          <h3 className="text-sm font-medium text-gray-300 mb-2 flex items-center gap-1.5">
            <BookOpen className="w-4 h-4" />
            사용 방법
          </h3>
          <ol className="text-xs text-gray-400 space-y-1 list-decimal list-inside">
            <li>위 설정을 입력하고 저장합니다</li>
            <li>연결 테스트로 서버 연결을 확인합니다</li>
            <li>에디터 탭으로 이동하여 레벨을 불러오거나 저장합니다</li>
          </ol>
        </div>

        {/* Level Migration Tool */}
        {isConfigured && isHealthy && (
          <div className="bg-amber-900/20 border border-amber-700 rounded-md p-3">
            <h3 className="text-sm font-medium text-amber-300 mb-2 flex items-center gap-1.5">
              <Wrench className="w-4 h-4" />
              레벨 포맷 마이그레이션
            </h3>
            <p className="text-xs text-amber-200/70 mb-3">
              기존 레벨의 기믹 포맷을 최신 클라이언트 형식으로 변환합니다.
              <br />• ice_N → ice
              <br />• bomb + [N] → bomb_N
              <br />• teleport → teleporter
            </p>

            <div className="grid grid-cols-2 gap-2 mb-3">
              <div>
                <label className="text-xs text-gray-400 block mb-1">Board ID</label>
                <input
                  type="text"
                  value={migrationBoardId}
                  onChange={(e) => setMigrationBoardId(e.target.value)}
                  className="w-full px-2 py-1 border border-gray-600 bg-gray-700 text-gray-100 rounded text-xs"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">Level Prefix</label>
                <input
                  type="text"
                  value={migrationPrefix}
                  onChange={(e) => setMigrationPrefix(e.target.value)}
                  className="w-full px-2 py-1 border border-gray-600 bg-gray-700 text-gray-100 rounded text-xs"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">시작 레벨</label>
                <input
                  type="number"
                  value={migrationStartLevel}
                  onChange={(e) => setMigrationStartLevel(parseInt(e.target.value) || 1)}
                  min={1}
                  className="w-full px-2 py-1 border border-gray-600 bg-gray-700 text-gray-100 rounded text-xs"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">종료 레벨</label>
                <input
                  type="number"
                  value={migrationEndLevel}
                  onChange={(e) => setMigrationEndLevel(parseInt(e.target.value) || 500)}
                  min={1}
                  className="w-full px-2 py-1 border border-gray-600 bg-gray-700 text-gray-100 rounded text-xs"
                />
              </div>
            </div>

            <Button
              onClick={handleMigrateLevels}
              disabled={isMigrating}
              isLoading={isMigrating}
              variant="warning"
              icon={<RefreshCw className="w-full h-full" />}
              className="w-full"
            >
              {isMigrating ? '마이그레이션 중...' : '마이그레이션 실행'}
            </Button>

            {migrationProgress && (
              <div className="mt-3 text-xs">
                <div className="flex justify-between text-gray-400 mb-1">
                  <span>진행: {migrationProgress.current}/{migrationProgress.total}</span>
                  <span>수정: {migrationProgress.fixed} / 스킵: {migrationProgress.skipped}</span>
                </div>
                <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-amber-500 transition-all duration-200"
                    style={{ width: `${(migrationProgress.current / Math.max(1, migrationProgress.total)) * 100}%` }}
                  />
                </div>
                {migrationProgress.errors.length > 0 && (
                  <div className="mt-2 text-red-400 text-[10px] max-h-20 overflow-y-auto">
                    {migrationProgress.errors.slice(0, 5).map((err, i) => (
                      <div key={i}>{err}</div>
                    ))}
                    {migrationProgress.errors.length > 5 && (
                      <div>... +{migrationProgress.errors.length - 5} more errors</div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </CollapsiblePanel>
  );
}

export { LevelSelector } from './LevelSelector';

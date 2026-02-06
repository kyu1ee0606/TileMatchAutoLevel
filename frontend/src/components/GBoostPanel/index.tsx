import { useState, useEffect } from 'react';
import {
  checkGBoostHealth,
  getGBoostConfig,
  setGBoostConfig,
} from '../../api/gboost';
import { CollapsiblePanel, Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { Save, Plug, Info, BookOpen, CheckCircle, AlertTriangle, XCircle } from 'lucide-react';
import clsx from 'clsx';

interface GBoostPanelProps {
  className?: string;
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
      </div>
    </CollapsiblePanel>
  );
}

export { LevelSelector } from './LevelSelector';

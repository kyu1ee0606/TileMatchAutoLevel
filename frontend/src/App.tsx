import { useState, useEffect, useRef, useCallback } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GridEditor } from './components/GridEditor';
import { DifficultyPanel } from './components/DifficultyPanel';
import { GeneratorPanel } from './components/GeneratorPanel';
import { GBoostPanel } from './components/GBoostPanel';
import { LevelBrowser } from './components/GridEditor/LevelBrowser';
import { LocalLevelBrowser } from './components/GridEditor/LocalLevelBrowser';
import { SimulationViewer } from './components/SimulationViewer';
import { PlayTab } from './components/PlayTab';
import { useLevelStore } from './stores/levelStore';
import { useUIStore } from './stores/uiStore';
import { useSimulationStore } from './stores/simulationStore';
import clsx from 'clsx';

// Create a client
const queryClient = new QueryClient();

// JSON Syntax Highlighter
function highlightJson(json: string): string {
  return json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(
      /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^"\\])*"(\s*:)?)/g,
      (match) => {
        if (/:$/.test(match)) {
          // Key
          return `<span class="text-purple-400">${match.slice(0, -1)}</span>:`;
        } else {
          // String value
          return `<span class="text-green-400">${match}</span>`;
        }
      }
    )
    .replace(/\b(true|false)\b/g, '<span class="text-yellow-400">$1</span>')
    .replace(/\b(null)\b/g, '<span class="text-gray-500">$1</span>')
    .replace(/\b(-?\d+\.?\d*)\b/g, '<span class="text-blue-400">$1</span>');
}

function JsonModal() {
  const { level, importJson } = useLevelStore();
  const { isJsonModalOpen, setJsonModalOpen, addNotification } = useUIStore();
  const [jsonText, setJsonText] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (isJsonModalOpen) {
      setJsonText(JSON.stringify(level, null, 2));
      setIsEditing(false);
    }
  }, [isJsonModalOpen, level]);

  const syncScroll = useCallback(() => {
    if (textareaRef.current && preRef.current) {
      preRef.current.scrollTop = textareaRef.current.scrollTop;
      preRef.current.scrollLeft = textareaRef.current.scrollLeft;
    }
  }, []);

  if (!isJsonModalOpen) return null;

  const handleApply = () => {
    const success = importJson(jsonText);
    if (success) {
      setJsonModalOpen(false);
      addNotification('success', 'JSON이 적용되었습니다');
    } else {
      addNotification('error', '잘못된 JSON 형식입니다');
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
      onClick={() => setJsonModalOpen(false)}
    >
      <div
        className="bg-gray-800 rounded-xl p-6 w-full max-w-2xl max-h-[80vh] flex flex-col border border-gray-700"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-bold text-gray-100">레벨 JSON</h3>
          <button
            onClick={() => setJsonModalOpen(false)}
            className="text-gray-400 hover:text-gray-200"
          >
            ✕
          </button>
        </div>

        {/* JSON Editor with Syntax Highlighting */}
        <div className="relative flex-1 min-h-[300px] border border-gray-600 rounded-md overflow-hidden">
          <pre
            ref={preRef}
            className="absolute inset-0 p-3 font-mono text-sm overflow-auto whitespace-pre bg-gray-900 pointer-events-none"
            dangerouslySetInnerHTML={{
              __html: isEditing ? highlightJson(jsonText) : highlightJson(jsonText),
            }}
          />
          <textarea
            ref={textareaRef}
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              setIsEditing(true);
            }}
            onScroll={syncScroll}
            className="absolute inset-0 w-full h-full p-3 font-mono text-sm resize-none bg-transparent text-transparent caret-white outline-none"
            spellCheck={false}
          />
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={() => setJsonModalOpen(false)}
            className="px-4 py-2 text-sm bg-gray-700 text-gray-300 rounded-md hover:bg-gray-600"
          >
            취소
          </button>
          <button
            onClick={() => {
              navigator.clipboard.writeText(jsonText);
              addNotification('success', 'JSON이 복사되었습니다');
            }}
            className="px-4 py-2 text-sm bg-blue-900 text-blue-200 rounded-md hover:bg-blue-800"
          >
            복사
          </button>
          <button
            onClick={handleApply}
            className="px-4 py-2 text-sm bg-primary-600 text-white rounded-md hover:bg-primary-700"
          >
            적용
          </button>
        </div>
      </div>
    </div>
  );
}

function NotificationItem({ notification, onRemove }: {
  notification: { id: string; type: string; message: string; duration: number; createdAt: number };
  onRemove: (id: string) => void;
}) {
  const [progress, setProgress] = useState(100);

  useEffect(() => {
    if (notification.duration <= 0) return;

    const startTime = notification.createdAt;
    const endTime = startTime + notification.duration;

    const updateProgress = () => {
      const now = Date.now();
      const remaining = Math.max(0, endTime - now);
      const newProgress = (remaining / notification.duration) * 100;
      setProgress(newProgress);

      if (newProgress > 0) {
        requestAnimationFrame(updateProgress);
      }
    };

    const animationId = requestAnimationFrame(updateProgress);
    return () => cancelAnimationFrame(animationId);
  }, [notification.duration, notification.createdAt]);

  const bgColors: Record<string, string> = {
    success: 'bg-green-500',
    error: 'bg-red-500',
    info: 'bg-blue-500',
    warning: 'bg-yellow-500',
  };

  const progressColors: Record<string, string> = {
    success: 'bg-green-300',
    error: 'bg-red-300',
    info: 'bg-blue-300',
    warning: 'bg-yellow-300',
  };

  const icons: Record<string, string> = {
    success: '✓',
    error: '✕',
    info: 'ℹ',
    warning: '⚠',
  };

  return (
    <div
      className={clsx(
        'relative px-4 py-3 rounded-lg shadow-lg text-sm text-white animate-slide-in overflow-hidden',
        bgColors[notification.type]
      )}
    >
      <div className="flex items-center gap-2">
        <span>{icons[notification.type]}</span>
        <span className="flex-1">{notification.message}</span>
        <button
          onClick={() => onRemove(notification.id)}
          className="hover:opacity-75"
        >
          ✕
        </button>
      </div>
      {notification.duration > 0 && (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/20">
          <div
            className={clsx('h-full transition-none', progressColors[notification.type])}
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  );
}

function Notifications() {
  const { notifications, removeNotification } = useUIStore();

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {notifications.map((notification) => (
        <NotificationItem
          key={notification.id}
          notification={notification}
          onRemove={removeNotification}
        />
      ))}
    </div>
  );
}

type TabId = 'editor' | 'simulation' | 'generator' | 'gboost' | 'local' | 'play';

function AppContent() {
  const [activeTab, setActiveTab] = useState<TabId>('editor');
  const [isDragging, setIsDragging] = useState(false);
  const [playLevelId, setPlayLevelId] = useState<string | null>(null);
  const { importJson, level } = useLevelStore();
  const { addNotification } = useUIStore();
  const { fetchSimulation, clearResults } = useSimulationStore();
  const dragCounterRef = useRef(0);

  // Handler for playing a level from LocalLevelBrowser
  const handlePlayLevel = useCallback((levelId: string) => {
    setPlayLevelId(levelId);
    setActiveTab('play');
  }, []);

  const tabs: { id: TabId; label: string; icon: string }[] = [
    { id: 'editor', label: '에디터', icon: '🎮' },
    { id: 'simulation', label: '시뮬레이션', icon: '🎬' },
    { id: 'generator', label: '자동 생성', icon: '🎲' },
    { id: 'local', label: '로컬 레벨', icon: '💾' },
    { id: 'gboost', label: '게임부스트', icon: '☁️' },
    { id: 'play', label: '플레이', icon: '▶️' },
  ];

  // 시뮬레이션 탭으로 전환 시 자동으로 시뮬레이션 실행
  useEffect(() => {
    if (activeTab === 'simulation') {
      clearResults();
      fetchSimulation(level);
    }
  }, [activeTab, level, fetchSimulation, clearResults]);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    if (e.dataTransfer.types.includes('Files')) {
      setIsDragging(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    dragCounterRef.current = 0;

    const files = e.dataTransfer.files;
    if (files.length === 0) return;

    const file = files[0];
    if (!file.name.endsWith('.json')) {
      addNotification('error', 'JSON 파일만 불러올 수 있습니다');
      return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      const success = importJson(content);
      if (success) {
        addNotification('success', `${file.name} 파일을 불러왔습니다`);
      } else {
        addNotification('error', '잘못된 레벨 JSON 형식입니다');
      }
    };
    reader.onerror = () => {
      addNotification('error', '파일을 읽을 수 없습니다');
    };
    reader.readAsText(file);
  }, [importJson, addNotification]);

  return (
    <div
      className="min-h-screen bg-gray-900 text-gray-100 relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag Overlay */}
      {isDragging && (
        <div className="fixed inset-0 z-50 bg-primary-600/20 backdrop-blur-sm flex items-center justify-center pointer-events-none">
          <div className="bg-gray-800 rounded-xl p-8 border-2 border-dashed border-primary-400 text-center">
            <div className="text-4xl mb-4">📁</div>
            <div className="text-xl font-bold text-primary-400">JSON 파일을 여기에 놓으세요</div>
            <div className="text-sm text-gray-400 mt-2">레벨 데이터를 불러옵니다</div>
          </div>
        </div>
      )}
      {/* Header */}
      <header className="bg-gray-800 shadow-lg border-b border-gray-700">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🎮</span>
            <h1 className="text-xl font-bold text-gray-100">
              타일매치 레벨 디자이너
            </h1>
          </div>
          <div className="flex items-center gap-2">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={clsx(
                  'px-4 py-2 text-sm font-medium rounded-md transition-colors',
                  activeTab === tab.id
                    ? 'bg-primary-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                )}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-[1600px] mx-auto px-4 py-6">
        {activeTab === 'editor' && (
          <div className="flex flex-col gap-4">
            {/* Top Row: Editor + Level Browser */}
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
              {/* Left: Grid Editor */}
              <div className="lg:col-span-3">
                <GridEditor />
              </div>
              {/* Right: Level Browser */}
              <div className="lg:col-span-1">
                <LevelBrowser className="h-full" />
              </div>
            </div>
            {/* Bottom: Difficulty Panel */}
            <DifficultyPanel />
          </div>
        )}
        {activeTab === 'generator' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <GeneratorPanel />
            </div>
            <div className="lg:col-span-1">
              <DifficultyPanel />
            </div>
          </div>
        )}
        {activeTab === 'simulation' && (
          <SimulationViewer />
        )}
        {activeTab === 'local' && (
          <div className="flex flex-col gap-4">
            {/* Top Row: Editor + Local Level Browser */}
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
              {/* Left: Grid Editor */}
              <div className="lg:col-span-3">
                <GridEditor />
              </div>
              {/* Right: Local Level Browser */}
              <div className="lg:col-span-1">
                <LocalLevelBrowser className="h-full" onPlay={handlePlayLevel} />
              </div>
            </div>
            {/* Bottom: Difficulty Panel */}
            <DifficultyPanel />
          </div>
        )}
        {activeTab === 'gboost' && (
          <div className="max-w-2xl mx-auto">
            <GBoostPanel />
          </div>
        )}
        {activeTab === 'play' && (
          <div className="h-[calc(100vh-200px)]">
            <PlayTab
              initialLevelId={playLevelId}
              onLevelLoaded={() => setPlayLevelId(null)}
            />
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="bg-gray-800 border-t border-gray-700 mt-8">
        <div className="max-w-7xl mx-auto px-4 py-4 text-center text-sm text-gray-400">
          TileMatch Level Designer Tool v1.0.0
        </div>
      </footer>

      {/* Modals */}
      <JsonModal />
      <Notifications />
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}

export default App;

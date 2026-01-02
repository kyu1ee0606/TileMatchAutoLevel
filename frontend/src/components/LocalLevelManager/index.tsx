import React, { useEffect, useState } from 'react';
import {
  listLocalLevels,
  getLocalLevel,
  deleteLocalLevel,
  deleteAllLocalLevels,
  importGeneratedLevels,
  simulateLocalLevel,
  type LocalLevelMetadata,
  type LocalLevel,
} from '../../services/localLevelsApi';
import './styles.css';

interface LocalLevelManagerProps {
  onPlayLevel?: (levelData: any, metadata: any) => void;
}

export function LocalLevelManager({ onPlayLevel }: LocalLevelManagerProps) {
  const [levels, setLevels] = useState<LocalLevelMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<LocalLevel | null>(null);
  const [importDialogOpen, setImportDialogOpen] = useState(false);

  useEffect(() => {
    loadLevels();
  }, []);

  async function loadLevels() {
    try {
      setLoading(true);
      setError(null);
      const response = await listLocalLevels();
      setLevels(response.levels);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load levels');
      console.error('Failed to load levels:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(levelId: string) {
    if (!confirm(`Delete level ${levelId}?`)) return;

    try {
      await deleteLocalLevel(levelId);
      await loadLevels();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete level');
      console.error('Failed to delete level:', err);
    }
  }

  async function handleDeleteAll() {
    if (!confirm(`정말로 모든 로컬 레벨(${levels.length}개)을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`)) return;

    try {
      const result = await deleteAllLocalLevels();
      alert(`${result.deleted_count}개의 레벨이 삭제되었습니다.`);
      await loadLevels();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete all levels');
      console.error('Failed to delete all levels:', err);
    }
  }

  async function handlePlay(levelId: string) {
    try {
      const level = await getLocalLevel(levelId);
      setSelectedLevel(level);

      if (onPlayLevel) {
        onPlayLevel(level.level_data, level.metadata);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load level');
      console.error('Failed to load level:', err);
    }
  }

  async function handleSimulate(levelId: string) {
    try {
      const level = await getLocalLevel(levelId);
      const maxMoves = level.level_data.max_moves || 50;

      const simulation = await simulateLocalLevel(
        level.level_data,
        ['optimal'],
        maxMoves,
        42
      );

      const bot = simulation.bot_results[0];
      alert(
        `Simulation Result:\n\n` +
        `Bot: ${bot.profile_display}\n` +
        `Cleared: ${bot.cleared ? 'YES' : 'NO'}\n` +
        `Moves: ${bot.total_moves}\n` +
        `Score: ${bot.final_score}`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to simulate level');
      console.error('Failed to simulate level:', err);
    }
  }

  async function handleFileImport(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const content = await file.text();
      const data = JSON.parse(content);

      const result = await importGeneratedLevels(data);

      alert(
        `Import Complete!\n\n` +
        `Imported: ${result.imported_count} levels\n` +
        `Errors: ${result.error_count}\n\n` +
        `Levels: ${result.imported_levels.join(', ')}`
      );

      await loadLevels();
      setImportDialogOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import levels');
      console.error('Failed to import levels:', err);
    }
  }

  function getDifficultyColor(difficulty: string): string {
    const colors: Record<string, string> = {
      easy: '#4CAF50',
      medium: '#FF9800',
      hard: '#F44336',
      expert: '#9C27B0',
      impossible: '#000000',
      custom: '#2196F3',
    };
    return colors[difficulty.toLowerCase()] || '#757575';
  }

  function getStatusIcon(status: string): string {
    const icons: Record<string, string> = {
      pass: '✅',
      warn: '⚠️',
      fail: '❌',
      unknown: '❓',
    };
    return icons[status] || '❓';
  }

  if (loading) {
    return (
      <div className="local-level-manager">
        <div className="loading">Loading local levels...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="local-level-manager">
        <div className="error-card">
          <h3>Error</h3>
          <p>{error}</p>
          <button onClick={loadLevels}>Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="local-level-manager">
      <div className="header">
        <h2>Local Levels ({levels.length})</h2>
        <div className="header-actions">
          <button onClick={() => loadLevels()}>
            🔄 Refresh
          </button>
          <button onClick={() => setImportDialogOpen(true)}>
            📥 Import Levels
          </button>
          {levels.length > 0 && (
            <button onClick={handleDeleteAll} className="delete-all-button">
              🗑️ Delete All
            </button>
          )}
        </div>
      </div>

      {importDialogOpen && (
        <div className="import-dialog">
          <h3>Import Generated Levels</h3>
          <p>Select a JSON file from generate_benchmark_levels.py output</p>
          <input
            type="file"
            accept=".json"
            onChange={handleFileImport}
          />
          <div className="dialog-actions">
            <button onClick={() => setImportDialogOpen(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {levels.length === 0 ? (
        <div className="empty-state">
          <h3>No Local Levels</h3>
          <p>Import generated levels or create custom levels to get started.</p>
          <button onClick={() => setImportDialogOpen(true)}>
            Import Levels
          </button>
        </div>
      ) : (
        <div className="level-grid">
          {levels.map((level) => (
            <div key={level.id} className="level-card">
              <div className="level-header">
                <h3>{level.name}</h3>
                <span
                  className="difficulty-badge"
                  style={{ backgroundColor: getDifficultyColor(level.difficulty) }}
                >
                  {level.difficulty.toUpperCase()}
                </span>
              </div>

              <p className="level-description">{level.description}</p>

              <div className="level-meta">
                <div className="level-tags">
                  {level.tags.map((tag) => (
                    <span key={tag} className="tag">
                      {tag}
                    </span>
                  ))}
                </div>
                <div className="level-status">
                  <span className="status-icon">
                    {getStatusIcon(level.validation_status)}
                  </span>
                  <span className="status-text">
                    {level.validation_status}
                  </span>
                </div>
              </div>

              <div className="level-footer">
                <span className="level-source">{level.source}</span>
                <span className="level-date">
                  {new Date(level.created_at).toLocaleDateString()}
                </span>
              </div>

              <div className="level-actions">
                <button
                  onClick={() => handlePlay(level.id)}
                  className="play-button"
                >
                  ▶️ Play
                </button>
                <button
                  onClick={() => handleSimulate(level.id)}
                  className="simulate-button"
                >
                  🤖 Simulate
                </button>
                <button
                  onClick={() => handleDelete(level.id)}
                  className="delete-button"
                >
                  🗑️ Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedLevel && (
        <div className="selected-level-info">
          <h3>Selected Level: {selectedLevel.metadata.name}</h3>
          <pre>{JSON.stringify(selectedLevel, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

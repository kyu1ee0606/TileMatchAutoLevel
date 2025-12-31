import type { LevelJSON } from '../../types';
import type { VisualSimulationResponse } from '../../types/simulation';
import { BotViewer } from './BotViewer';
import { SimulationSummary } from './SimulationSummary';
import clsx from 'clsx';

interface SimulationGridProps {
  levelJson: LevelJSON;
  results: VisualSimulationResponse;
  currentStep: number;
  className?: string;
}

export function SimulationGrid({ levelJson, results, currentStep, className }: SimulationGridProps) {
  // Display up to 5 bots in a 2x3 grid layout (last cell is summary)
  const botResults = results.bot_results.slice(0, 5);

  // Get initial states from response
  const { initial_state } = results;

  const initialFrogPositions = initial_state.initial_frog_positions || [];
  const initialBombStates = initial_state.initial_bomb_states || {};
  const initialCurtainStates = initial_state.initial_curtain_states || {};
  const initialIceStates = initial_state.initial_ice_states || {};
  const initialChainStates = initial_state.initial_chain_states || {};
  const initialGrassStates = initial_state.initial_grass_states || {};
  const initialLinkStates = initial_state.initial_link_states || {};
  const initialTeleportStates = initial_state.initial_teleport_states || {};

  // Get converted tiles from API response (t0 tiles are converted to actual types)
  const convertedTiles = initial_state.tiles as Record<string, Record<string, unknown>>;

  return (
    <div className={clsx('grid grid-cols-2 gap-4', className)}>
      {/* Bot viewers (max 5) */}
      {botResults.map((botResult) => (
        <BotViewer
          key={botResult.profile}
          levelJson={levelJson}
          botResult={botResult}
          currentStep={currentStep}
          initialFrogPositions={initialFrogPositions}
          initialBombStates={initialBombStates}
          initialCurtainStates={initialCurtainStates}
          initialIceStates={initialIceStates}
          initialChainStates={initialChainStates}
          initialGrassStates={initialGrassStates}
          initialLinkStates={initialLinkStates}
          initialTeleportStates={initialTeleportStates}
          convertedTiles={convertedTiles}
        />
      ))}

      {/* Summary panel (fills last cell) */}
      <SimulationSummary results={results} />
    </div>
  );
}

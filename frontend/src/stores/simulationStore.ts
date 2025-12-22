import { create } from 'zustand';
import type { LevelJSON } from '../types';
import type {
  VisualSimulationResponse,
  BotProfile,
  PlaybackSpeed,
} from '../types/simulation';
import { simulateVisual } from '../api/simulate';

interface SimulationState {
  // Simulation result data
  results: VisualSimulationResponse | null;
  isLoading: boolean;
  error: string | null;

  // Playback state
  isPlaying: boolean;
  currentStep: number;
  playbackSpeed: PlaybackSpeed;

  // Actions - Data fetching
  fetchSimulation: (levelJson: LevelJSON, botTypes?: BotProfile[], maxMoves?: number, seed?: number) => Promise<void>;
  clearResults: () => void;

  // Actions - Playback control
  play: () => void;
  pause: () => void;
  togglePlayPause: () => void;
  stepForward: () => void;
  stepBackward: () => void;
  seekTo: (step: number) => void;
  goToStart: () => void;
  goToEnd: () => void;
  setPlaybackSpeed: (speed: PlaybackSpeed) => void;
  reset: () => void;
}

// Internal interval reference for playback
let playbackInterval: ReturnType<typeof setInterval> | null = null;

export const useSimulationStore = create<SimulationState>((set, get) => ({
  // Initial state
  results: null,
  isLoading: false,
  error: null,
  isPlaying: false,
  currentStep: 0,
  playbackSpeed: 1,

  // Fetch simulation from API
  fetchSimulation: async (levelJson, botTypes, maxMoves, seed) => {
    set({ isLoading: true, error: null });

    try {
      const results = await simulateVisual(levelJson, botTypes, maxMoves, seed);
      set({
        results,
        isLoading: false,
        currentStep: 0,
        isPlaying: false,
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Simulation failed';
      set({
        error: errorMessage,
        isLoading: false,
        results: null,
      });
    }
  },

  clearResults: () => {
    get().pause();
    set({
      results: null,
      error: null,
      currentStep: 0,
      isPlaying: false,
    });
  },

  // Playback controls
  play: () => {
    const { results, currentStep, playbackSpeed } = get();
    if (!results || currentStep >= results.max_steps) return;

    // Clear any existing interval
    if (playbackInterval) {
      clearInterval(playbackInterval);
    }

    set({ isPlaying: true });

    // Calculate interval based on playback speed (base: 500ms per step)
    const intervalMs = 500 / playbackSpeed;

    playbackInterval = setInterval(() => {
      const { currentStep, results, isPlaying } = get();
      if (!results || !isPlaying) {
        if (playbackInterval) {
          clearInterval(playbackInterval);
          playbackInterval = null;
        }
        return;
      }

      if (currentStep >= results.max_steps) {
        set({ isPlaying: false });
        if (playbackInterval) {
          clearInterval(playbackInterval);
          playbackInterval = null;
        }
        return;
      }

      set({ currentStep: currentStep + 1 });
    }, intervalMs);
  },

  pause: () => {
    if (playbackInterval) {
      clearInterval(playbackInterval);
      playbackInterval = null;
    }
    set({ isPlaying: false });
  },

  togglePlayPause: () => {
    const { isPlaying, play, pause } = get();
    if (isPlaying) {
      pause();
    } else {
      play();
    }
  },

  stepForward: () => {
    const { currentStep, results, pause } = get();
    pause();
    if (results && currentStep < results.max_steps) {
      set({ currentStep: currentStep + 1 });
    }
  },

  stepBackward: () => {
    const { currentStep, pause } = get();
    pause();
    if (currentStep > 0) {
      set({ currentStep: currentStep - 1 });
    }
  },

  seekTo: (step) => {
    const { results, pause } = get();
    pause();
    if (results) {
      const clampedStep = Math.max(0, Math.min(step, results.max_steps));
      set({ currentStep: clampedStep });
    }
  },

  goToStart: () => {
    get().pause();
    set({ currentStep: 0 });
  },

  goToEnd: () => {
    const { results, pause } = get();
    pause();
    if (results) {
      set({ currentStep: results.max_steps });
    }
  },

  setPlaybackSpeed: (speed) => {
    const { isPlaying, play, pause } = get();
    set({ playbackSpeed: speed });

    // Restart playback with new speed if currently playing
    if (isPlaying) {
      pause();
      setTimeout(() => play(), 10);
    }
  },

  reset: () => {
    get().pause();
    set({
      currentStep: 0,
      isPlaying: false,
    });
  },
}));

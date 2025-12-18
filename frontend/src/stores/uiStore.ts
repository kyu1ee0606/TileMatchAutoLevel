import { create } from 'zustand';

type Tool = 'paint' | 'erase' | 'fill' | 'inspect';
type Panel = 'editor' | 'generator' | 'gboost';

interface UIState {
  // Tool state
  activeTool: Tool;
  setActiveTool: (tool: Tool) => void;

  // Panel visibility
  activePanel: Panel;
  setActivePanel: (panel: Panel) => void;

  // Modal state
  isJsonModalOpen: boolean;
  setJsonModalOpen: (open: boolean) => void;

  // Loading states
  isGenerating: boolean;
  setIsGenerating: (loading: boolean) => void;

  isSaving: boolean;
  setIsSaving: (saving: boolean) => void;

  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;

  // Notifications
  notifications: Array<{
    id: string;
    type: 'success' | 'error' | 'info' | 'warning';
    message: string;
    duration: number;
    createdAt: number;
  }>;
  addNotification: (type: 'success' | 'error' | 'info' | 'warning', message: string, duration?: number) => void;
  removeNotification: (id: string) => void;
  clearNotifications: () => void;

  // GBoost settings
  gboostBoardId: string;
  setGboostBoardId: (id: string) => void;

  gboostLevelId: string;
  setGboostLevelId: (id: string) => void;

  // Layer transparency
  showOtherLayers: boolean;
  setShowOtherLayers: (show: boolean) => void;

  // Grid zoom
  gridZoom: number;
  setGridZoom: (zoom: number) => void;

  // Grid coordinates display
  showGridCoordinates: boolean;
  setShowGridCoordinates: (show: boolean) => void;

  // Minimap visibility
  showMinimap: boolean;
  setShowMinimap: (show: boolean) => void;
}

export const useUIStore = create<UIState>((set, get) => ({
  // Tool state
  activeTool: 'paint',
  setActiveTool: (tool) => set({ activeTool: tool }),

  // Panel visibility
  activePanel: 'editor',
  setActivePanel: (panel) => set({ activePanel: panel }),

  // Modal state
  isJsonModalOpen: false,
  setJsonModalOpen: (open) => set({ isJsonModalOpen: open }),

  // Loading states
  isGenerating: false,
  setIsGenerating: (loading) => set({ isGenerating: loading }),

  isSaving: false,
  setIsSaving: (saving) => set({ isSaving: saving }),

  isLoading: false,
  setIsLoading: (loading) => set({ isLoading: loading }),

  // Notifications (max 5 stacked)
  notifications: [],
  addNotification: (type, message, duration = 5000) => {
    const id = Date.now().toString();
    const createdAt = Date.now();

    set((state) => {
      // Limit stack to 5 notifications (remove oldest if exceeding)
      const existingNotifications = state.notifications.length >= 5
        ? state.notifications.slice(1)
        : state.notifications;

      return {
        notifications: [...existingNotifications, { id, type, message, duration, createdAt }],
      };
    });

    // Auto-remove after duration
    if (duration > 0) {
      setTimeout(() => {
        get().removeNotification(id);
      }, duration);
    }
  },
  removeNotification: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),
  clearNotifications: () => set({ notifications: [] }),

  // GBoost settings
  gboostBoardId: 'levels',
  setGboostBoardId: (id) => set({ gboostBoardId: id }),

  gboostLevelId: 'level_001',
  setGboostLevelId: (id) => set({ gboostLevelId: id }),

  // Layer transparency
  showOtherLayers: false,
  setShowOtherLayers: (show) => set({ showOtherLayers: show }),

  // Grid zoom (0.5 ~ 2.0, default 1.0)
  gridZoom: 1.0,
  setGridZoom: (zoom) => set({ gridZoom: Math.max(0.5, Math.min(2.0, zoom)) }),

  // Grid coordinates display
  showGridCoordinates: false,
  setShowGridCoordinates: (show) => set({ showGridCoordinates: show }),

  // Minimap visibility
  showMinimap: false,
  setShowMinimap: (show) => set({ showMinimap: show }),
}));

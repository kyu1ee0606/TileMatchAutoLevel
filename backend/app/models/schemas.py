"""Pydantic schemas for API request/response validation."""
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional, Tuple


class AnalyzeRequest(BaseModel):
    """Request schema for level analysis."""
    level_json: Dict[str, Any] = Field(..., description="Level JSON data to analyze")


class AnalyzeResponse(BaseModel):
    """Response schema for level analysis."""
    score: float = Field(..., ge=0, le=100, description="Difficulty score (0-100)")
    grade: str = Field(..., description="Difficulty grade (S/A/B/C/D)")
    metrics: Dict[str, Any] = Field(..., description="Detailed metrics")
    recommendations: List[str] = Field(default=[], description="Recommendations for improvement")


class GoalConfig(BaseModel):
    """Goal configuration for level generation."""
    type: str = Field(..., description="Goal type (craft, stack) or full type (craft_s, stack_s)")
    direction: Optional[str] = Field(default=None, description="Direction suffix (s/n/e/w) for craft/stack goals")
    count: int = Field(..., ge=1, description="Required count to collect")


class ObstacleCountConfig(BaseModel):
    """Configuration for obstacle count range."""
    min: int = Field(default=0, ge=0, description="Minimum count")
    max: int = Field(default=10, ge=0, description="Maximum count")


class LayerTileConfig(BaseModel):
    """Configuration for tile count on a specific layer."""
    layer: int = Field(..., ge=0, description="Layer index (0-based)")
    count: int = Field(..., ge=0, description="Tile count for this layer")


class LayerObstacleConfig(BaseModel):
    """Configuration for obstacle counts on a specific layer."""
    layer: int = Field(..., ge=0, description="Layer index (0-based)")
    counts: Dict[str, ObstacleCountConfig] = Field(
        default_factory=dict,
        description="Obstacle counts for this layer (e.g., {'chain': {'min': 1, 'max': 3}})"
    )


class GenerateRequest(BaseModel):
    """Request schema for level generation."""
    target_difficulty: float = Field(..., ge=0.0, le=1.0, description="Target difficulty (0.0-1.0)")
    grid_size: Tuple[int, int] = Field(default=(7, 7), description="Grid size (cols, rows)")
    max_layers: int = Field(default=7, ge=1, le=7, description="Maximum number of layers (1-7)")
    tile_types: Optional[List[str]] = Field(default=None, description="Tile types to use")
    obstacle_types: Optional[List[str]] = Field(default=None, description="Obstacle types to use")
    goals: Optional[List[GoalConfig]] = Field(default=None, description="Goal configurations")
    obstacle_counts: Optional[Dict[str, ObstacleCountConfig]] = Field(
        default=None,
        description="Obstacle count ranges per type (e.g., {'chain': {'min': 3, 'max': 8}})"
    )
    # New fields for enhanced generation control
    total_tile_count: Optional[int] = Field(
        default=None, ge=9, le=500,
        description="Total tile count across all layers (must be divisible by 3)"
    )
    active_layer_count: Optional[int] = Field(
        default=None, ge=1, le=7,
        description="Number of active layers to use"
    )
    layer_tile_configs: Optional[List[LayerTileConfig]] = Field(
        default=None,
        description="Per-layer tile count settings. Unspecified layers auto-distribute remaining tiles."
    )
    layer_obstacle_configs: Optional[List[LayerObstacleConfig]] = Field(
        default=None,
        description="Per-layer obstacle count settings. Unspecified layers auto-distribute."
    )
    # Symmetry and pattern options
    symmetry_mode: Optional[str] = Field(
        default=None,
        description="Symmetry mode: 'none', 'horizontal' (left-right), 'vertical' (top-bottom), 'both' (4-way)"
    )
    pattern_type: Optional[str] = Field(
        default=None,
        description="Pattern type: 'random', 'geometric' (regular shapes), 'clustered' (grouped tiles)"
    )


class GenerateResponse(BaseModel):
    """Response schema for level generation."""
    level_json: Dict[str, Any] = Field(..., description="Generated level JSON")
    actual_difficulty: float = Field(..., description="Actual difficulty achieved (0-1)")
    grade: str = Field(..., description="Difficulty grade")
    generation_time_ms: int = Field(default=0, description="Generation time in milliseconds")


class SimulateRequest(BaseModel):
    """Request schema for level simulation."""
    level_json: Dict[str, Any] = Field(..., description="Level JSON to simulate")
    iterations: int = Field(default=500, ge=10, le=10000, description="Number of simulation iterations")
    strategy: str = Field(default="greedy", description="Simulation strategy (random/greedy/optimal)")


class SimulateResponse(BaseModel):
    """Response schema for level simulation."""
    clear_rate: float = Field(..., ge=0, le=1, description="Clear rate (0-1)")
    avg_moves: float = Field(..., description="Average moves used")
    min_moves: int = Field(..., description="Minimum moves used")
    max_moves: int = Field(..., description="Maximum moves used")
    difficulty_estimate: float = Field(..., description="Simulation-based difficulty estimate")


class GBoostSaveRequest(BaseModel):
    """Request schema for saving level to GBoost."""
    level_json: Dict[str, Any] = Field(..., description="Level JSON to save")


class GBoostSaveResponse(BaseModel):
    """Response schema for GBoost save operation."""
    success: bool = Field(..., description="Whether save was successful")
    saved_at: str = Field(..., description="ISO 8601 timestamp")
    message: str = Field(default="", description="Status message")


class GBoostLoadResponse(BaseModel):
    """Response schema for GBoost load operation."""
    level_json: Dict[str, Any] = Field(..., description="Loaded level JSON")
    metadata: Dict[str, Any] = Field(default={}, description="Level metadata")


class LevelListItem(BaseModel):
    """Item in level list response."""
    id: str = Field(..., description="Level ID")
    created_at: str = Field(default="", description="Creation timestamp")
    difficulty: Optional[float] = Field(default=None, description="Cached difficulty score")


class GBoostListResponse(BaseModel):
    """Response schema for GBoost level list."""
    levels: List[LevelListItem] = Field(default=[], description="List of levels")


class BatchAnalyzeRequest(BaseModel):
    """Request schema for batch analysis."""
    levels: Optional[List[Dict[str, Any]]] = Field(default=None, description="List of level JSONs")
    level_ids: Optional[List[str]] = Field(default=None, description="Level IDs to load from GBoost")
    board_id: Optional[str] = Field(default=None, description="GBoost board ID")


class BatchAnalyzeResultItem(BaseModel):
    """Single item in batch analysis result."""
    level_id: str = Field(..., description="Level identifier")
    score: float = Field(..., description="Difficulty score")
    grade: str = Field(..., description="Difficulty grade")
    metrics: Dict[str, Any] = Field(..., description="Detailed metrics")


class BatchAnalyzeResponse(BaseModel):
    """Response schema for batch analysis."""
    results: List[BatchAnalyzeResultItem] = Field(default=[], description="Analysis results")


class ErrorResponse(BaseModel):
    """Error response schema."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Detailed error information")


# ===== Multi-Bot Assessment Schemas =====

class BotProfileConfig(BaseModel):
    """Configuration for a custom bot profile."""
    bot_type: str = Field(..., description="Bot type (novice/casual/average/expert/optimal)")
    mistake_rate: Optional[float] = Field(default=None, ge=0, le=1, description="Mistake probability")
    lookahead_depth: Optional[int] = Field(default=None, ge=0, le=10, description="Lookahead depth")
    goal_priority: Optional[float] = Field(default=None, ge=0, le=1, description="Goal priority weight")
    weight: Optional[float] = Field(default=None, ge=0, le=2, description="Weight in final calculation")


class MultiBotAssessRequest(BaseModel):
    """Request schema for multi-bot difficulty assessment."""
    level_json: Dict[str, Any] = Field(..., description="Level JSON to assess")
    bot_types: Optional[List[str]] = Field(
        default=None,
        description="Bot types to use (novice/casual/average/expert/optimal). Defaults to all."
    )
    iterations_per_bot: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Iterations per bot (more = more accurate but slower)"
    )
    max_moves: int = Field(default=30, ge=10, le=100, description="Maximum moves per simulation")
    custom_profiles: Optional[List[BotProfileConfig]] = Field(
        default=None,
        description="Custom bot profile configurations"
    )
    quick_mode: bool = Field(
        default=False,
        description="Quick mode: fewer bots and iterations for faster results"
    )


class BotResultItem(BaseModel):
    """Result from a single bot's simulations."""
    bot_type: str = Field(..., description="Bot type")
    bot_name: str = Field(..., description="Bot display name")
    iterations: int = Field(..., description="Number of iterations run")
    clear_rate: float = Field(..., ge=0, le=1, description="Clear rate (0-1)")
    avg_moves: float = Field(..., description="Average moves used")
    min_moves: int = Field(..., description="Minimum moves")
    max_moves: int = Field(..., description="Maximum moves")
    std_moves: float = Field(..., description="Standard deviation of moves")
    avg_combo: float = Field(..., description="Average combo count")
    avg_tiles_cleared: float = Field(..., description="Average tiles cleared")


class MultiBotAssessResponse(BaseModel):
    """Response schema for multi-bot assessment."""
    # Per-bot results
    bot_results: List[BotResultItem] = Field(..., description="Results for each bot")

    # Overall difficulty metrics
    overall_difficulty: float = Field(..., ge=0, le=100, description="Overall difficulty score")
    difficulty_grade: str = Field(..., description="Difficulty grade (S/A/B/C/D)")

    # Recommendations
    target_audience: str = Field(..., description="Recommended target player type")
    recommended_moves: int = Field(..., description="Recommended move count for this level")

    # Analysis details
    difficulty_variance: float = Field(..., description="Variance in difficulty across bots")
    analysis_summary: Dict[str, Any] = Field(..., description="Detailed analysis summary")


class ComprehensiveAssessRequest(BaseModel):
    """Request schema for comprehensive difficulty assessment (static + simulation)."""
    level_json: Dict[str, Any] = Field(..., description="Level JSON to assess")
    iterations_per_bot: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Iterations per bot"
    )
    max_moves: int = Field(default=30, ge=10, le=100, description="Maximum moves")
    assessment_mode: str = Field(
        default="standard",
        description="Assessment mode: quick, standard, detailed"
    )


class ComprehensiveAssessResponse(BaseModel):
    """Response schema for comprehensive assessment."""
    static_analysis: Dict[str, Any] = Field(..., description="Static analysis results")
    simulation_analysis: Dict[str, Any] = Field(..., description="Simulation analysis results")
    combined_analysis: Dict[str, Any] = Field(..., description="Combined analysis results")


class BotProfileListResponse(BaseModel):
    """Response schema for listing available bot profiles."""
    profiles: List[Dict[str, Any]] = Field(..., description="Available bot profiles")


# ===== Visual Simulation Schemas =====

class VisualSimulationRequest(BaseModel):
    """Request schema for visual simulation (single run with move history)."""
    level_json: Dict[str, Any] = Field(..., description="Level JSON to simulate")
    bot_types: Optional[List[str]] = Field(
        default=None,
        description="Bot types to simulate (defaults to all 5)"
    )
    max_moves: int = Field(default=30, ge=10, le=100, description="Maximum moves")
    seed: Optional[int] = Field(default=None, description="Random seed for reproducibility")


class VisualBotMove(BaseModel):
    """A single move made by a bot during visual simulation."""
    move_number: int = Field(..., description="Move number (1-based)")
    layer_idx: int = Field(..., description="Layer index of selected tile")
    position: str = Field(..., description="Position of selected tile (x_y)")
    tile_type: str = Field(..., description="Type of selected tile")
    linked_positions: List[str] = Field(default=[], description="Positions of tiles selected together due to LINK gimmick (layerIdx_x_y format)")
    matched_positions: List[str] = Field(default=[], description="Positions of matched tiles")
    tiles_cleared: int = Field(default=0, description="Number of tiles cleared this move")
    goals_after: Dict[str, int] = Field(default={}, description="Goals remaining after move")
    score_gained: float = Field(default=0, description="Score gained from this move")
    decision_reason: str = Field(default="", description="Why this move was chosen")
    dock_after: List[str] = Field(default=[], description="Dock state after this move (tile types)")
    frog_positions_after: List[str] = Field(default=[], description="Frog positions after move (layerIdx_x_y format)")
    bomb_states_after: Dict[str, int] = Field(default={}, description="Bomb tile states after move (layerIdx_x_y -> remaining)")
    curtain_states_after: Dict[str, bool] = Field(default={}, description="Curtain states after move (layerIdx_x_y -> is_open)")
    ice_states_after: Dict[str, int] = Field(default={}, description="Ice tile states after move (layerIdx_x_y -> remaining layers 1-3)")
    chain_states_after: Dict[str, bool] = Field(default={}, description="Chain tile states after move (layerIdx_x_y -> unlocked)")
    grass_states_after: Dict[str, int] = Field(default={}, description="Grass tile states after move (layerIdx_x_y -> remaining layers 1-2)")
    link_states_after: Dict[str, List[str]] = Field(default={}, description="Link tile states after move (layerIdx_x_y -> list of connected positions)")
    teleport_states_after: Dict[str, str] = Field(default={}, description="Teleport tile states after move (layerIdx_x_y -> tile_type)")
    teleport_click_count_after: int = Field(default=0, description="Teleport click counter after move (activates shuffle at 3)")
    tile_type_overrides: Dict[str, str] = Field(default={}, description="Permanent tile type changes (layerIdx_x_y -> tile_type) - includes tiles from removed teleport gimmick")


class VisualBotResult(BaseModel):
    """Result of a single bot's visual simulation."""
    profile: str = Field(..., description="Bot profile name")
    profile_display: str = Field(..., description="Display name for UI")
    moves: List[VisualBotMove] = Field(default=[], description="List of moves made")
    cleared: bool = Field(..., description="Whether level was cleared")
    total_moves: int = Field(..., description="Total moves used")
    final_score: float = Field(default=0, description="Final score")
    goals_completed: Dict[str, int] = Field(default={}, description="Goals completed")


class VisualGameState(BaseModel):
    """Snapshot of game state for visualization."""
    tiles: Dict[str, Any] = Field(..., description="Tiles by layer")
    goals: Dict[str, int] = Field(..., description="Initial goals")
    grid_info: Dict[str, Any] = Field(default={}, description="Grid dimensions per layer")
    initial_frog_positions: List[str] = Field(default=[], description="Initial frog positions (layerIdx_x_y format)")
    initial_ice_states: Dict[str, int] = Field(default={}, description="Initial ice states (layerIdx_x_y -> layers 1-3)")
    initial_chain_states: Dict[str, bool] = Field(default={}, description="Initial chain states (layerIdx_x_y -> locked=False)")
    initial_grass_states: Dict[str, int] = Field(default={}, description="Initial grass states (layerIdx_x_y -> layers 1-2)")
    initial_bomb_states: Dict[str, int] = Field(default={}, description="Initial bomb states (layerIdx_x_y -> count)")
    initial_curtain_states: Dict[str, bool] = Field(default={}, description="Initial curtain states (layerIdx_x_y -> is_open)")
    initial_link_states: Dict[str, List[str]] = Field(default={}, description="Initial link states (layerIdx_x_y -> connected positions)")
    initial_teleport_states: Dict[str, str] = Field(default={}, description="Initial teleport tile states (layerIdx_x_y -> tile_type)")


class VisualSimulationResponse(BaseModel):
    """Response schema for visual simulation."""
    initial_state: VisualGameState = Field(..., description="Initial game state")
    bot_results: List[VisualBotResult] = Field(..., description="Results for each bot")
    max_steps: int = Field(..., description="Maximum steps across all bots")
    metadata: Dict[str, Any] = Field(default={}, description="Additional metadata")


# ============================================================
# AutoPlay Analysis Schemas
# ============================================================

class AutoPlayRequest(BaseModel):
    """Request schema for auto-play difficulty analysis."""
    level_json: Dict[str, Any] = Field(..., description="Level JSON to analyze")
    iterations: int = Field(default=100, ge=10, le=1000, description="Iterations per bot profile")
    bot_profiles: Optional[List[str]] = Field(
        default=None,
        description="Bot profiles to use (default: all 5 - novice, casual, average, expert, optimal)"
    )
    seed: Optional[int] = Field(default=None, description="Random seed for reproducibility")


class BotClearStats(BaseModel):
    """Statistics for a single bot profile's simulation runs."""
    profile: str = Field(..., description="Bot profile name")
    profile_display: str = Field(..., description="Display name (Korean)")
    clear_rate: float = Field(..., ge=0, le=1, description="Clear rate (0.0-1.0)")
    target_clear_rate: float = Field(..., ge=0, le=1, description="Expected clear rate for this bot")
    avg_moves: float = Field(..., description="Average moves used")
    min_moves: int = Field(..., description="Minimum moves in any run")
    max_moves: int = Field(..., description="Maximum moves in any run")
    std_moves: float = Field(..., description="Standard deviation of moves")
    avg_combo: float = Field(..., description="Average combo count")
    iterations: int = Field(..., description="Number of iterations run")


class AutoPlayResponse(BaseModel):
    """Response schema for auto-play difficulty analysis."""
    # Per-bot statistics
    bot_stats: List[BotClearStats] = Field(..., description="Statistics for each bot profile")

    # Aggregated difficulty metrics
    autoplay_score: float = Field(..., ge=0, le=100, description="Auto-play difficulty score (0-100)")
    autoplay_grade: str = Field(..., description="Auto-play difficulty grade (S/A/B/C/D)")

    # Comparison with static analysis
    static_score: float = Field(..., ge=0, le=100, description="Static analysis score (0-100)")
    static_grade: str = Field(..., description="Static analysis grade")
    score_difference: float = Field(..., description="Difference: autoplay - static score")

    # Balance assessment
    balance_status: str = Field(..., description="balanced | too_easy | too_hard | unbalanced")
    recommendations: List[str] = Field(default=[], description="Balance recommendations")

    # Metadata
    total_simulations: int = Field(..., description="Total number of simulations run")
    execution_time_ms: int = Field(..., description="Execution time in milliseconds")


# ============================================================
# Validated Generation Schemas (Simulation-verified generation)
# ============================================================

class ValidatedGenerateRequest(BaseModel):
    """Request schema for simulation-validated level generation."""
    target_difficulty: float = Field(..., ge=0.0, le=1.0, description="Target difficulty (0.0-1.0)")
    grid_size: Tuple[int, int] = Field(default=(7, 7), description="Grid size (cols, rows)")
    max_layers: int = Field(default=7, ge=1, le=7, description="Maximum number of layers")
    tile_types: Optional[List[str]] = Field(default=None, description="Tile types to use")
    obstacle_types: Optional[List[str]] = Field(default=None, description="Obstacle types to use")
    goals: Optional[List[GoalConfig]] = Field(default=None, description="Goal configurations")
    symmetry_mode: Optional[str] = Field(default=None, description="Symmetry mode")
    pattern_type: Optional[str] = Field(default=None, description="Pattern type")

    # Validation parameters
    max_retries: int = Field(default=5, ge=1, le=20, description="Maximum generation retries")
    tolerance: float = Field(default=15.0, ge=5.0, le=30.0, description="Acceptable gap percentage from target")
    simulation_iterations: int = Field(default=30, ge=10, le=100, description="Iterations for validation simulation")


class ValidatedGenerateResponse(BaseModel):
    """Response schema for validated level generation."""
    level_json: Dict[str, Any] = Field(..., description="Generated level JSON")
    actual_difficulty: float = Field(..., description="Analyzer difficulty score (0-1)")
    grade: str = Field(..., description="Difficulty grade")
    generation_time_ms: int = Field(default=0, description="Total generation time in ms")

    # Simulation validation results
    validation_passed: bool = Field(..., description="Whether simulation validation passed")
    attempts: int = Field(..., description="Number of generation attempts")

    # Bot clear rates from simulation
    bot_clear_rates: Dict[str, float] = Field(default={}, description="Clear rates per bot type (0-1)")
    target_clear_rates: Dict[str, float] = Field(default={}, description="Target clear rates per bot type")
    avg_gap: float = Field(default=0, description="Average gap from target (%)")
    max_gap: float = Field(default=0, description="Maximum gap from target (%)")
    match_score: float = Field(default=0, description="Match score (0-100%, higher is better)")

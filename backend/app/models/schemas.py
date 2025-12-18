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
    type: str = Field(..., description="Goal type (craft_s, stack_s)")
    count: int = Field(..., ge=1, description="Required count to collect")


class GenerateRequest(BaseModel):
    """Request schema for level generation."""
    target_difficulty: float = Field(..., ge=0.0, le=1.0, description="Target difficulty (0.0-1.0)")
    grid_size: Tuple[int, int] = Field(default=(7, 7), description="Grid size (cols, rows)")
    max_layers: int = Field(default=8, ge=4, le=12, description="Maximum number of layers")
    tile_types: Optional[List[str]] = Field(default=None, description="Tile types to use")
    obstacle_types: Optional[List[str]] = Field(default=None, description="Obstacle types to use")
    goals: Optional[List[GoalConfig]] = Field(default=None, description="Goal configurations")


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

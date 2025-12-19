"""Data models package.

This package contains data models, schemas, and profiles for the application.
"""
from .level import (
    DifficultyGrade,
    LevelMetrics,
    DifficultyReport,
    GenerationParams,
    GenerationResult,
    SimulationResult,
    TILE_TYPES,
    ATTRIBUTES,
)
from .bot_profile import (
    BotType,
    BotTeam,
    BotProfile,
    get_all_profiles,
    get_profile,
    create_custom_profile,
    PREDEFINED_PROFILES,
)
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    GenerateRequest,
    GenerateResponse,
    SimulateRequest,
    SimulateResponse,
    MultiBotAssessRequest,
    MultiBotAssessResponse,
    BotResultItem,
    ComprehensiveAssessRequest,
    ComprehensiveAssessResponse,
    BotProfileListResponse,
    ErrorResponse,
    # AutoPlay schemas
    AutoPlayRequest,
    AutoPlayResponse,
    BotClearStats,
)

__all__ = [
    # Level models
    "DifficultyGrade",
    "LevelMetrics",
    "DifficultyReport",
    "GenerationParams",
    "GenerationResult",
    "SimulationResult",
    "TILE_TYPES",
    "ATTRIBUTES",
    # Bot profiles
    "BotType",
    "BotTeam",
    "BotProfile",
    "get_all_profiles",
    "get_profile",
    "create_custom_profile",
    "PREDEFINED_PROFILES",
    # API schemas
    "AnalyzeRequest",
    "AnalyzeResponse",
    "GenerateRequest",
    "GenerateResponse",
    "SimulateRequest",
    "SimulateResponse",
    "MultiBotAssessRequest",
    "MultiBotAssessResponse",
    "BotResultItem",
    "ComprehensiveAssessRequest",
    "ComprehensiveAssessResponse",
    "BotProfileListResponse",
    "ErrorResponse",
    # AutoPlay schemas
    "AutoPlayRequest",
    "AutoPlayResponse",
    "BotClearStats",
]

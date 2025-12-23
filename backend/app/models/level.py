"""Level data models and structures."""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum


class DifficultyGrade(str, Enum):
    """Difficulty grade enumeration."""
    S = "S"  # Very Easy (0-20)
    A = "A"  # Easy (21-40)
    B = "B"  # Normal (41-60)
    C = "C"  # Hard (61-80)
    D = "D"  # Very Hard (81-100)

    @classmethod
    def from_score(cls, score: float) -> "DifficultyGrade":
        """Get grade from score."""
        if score <= 20:
            return cls.S
        elif score <= 40:
            return cls.A
        elif score <= 60:
            return cls.B
        elif score <= 80:
            return cls.C
        else:
            return cls.D


@dataclass
class LevelMetrics:
    """Metrics extracted from level analysis."""
    total_tiles: int = 0
    active_layers: int = 0
    chain_count: int = 0
    frog_count: int = 0
    link_count: int = 0
    goal_amount: int = 0
    layer_blocking: float = 0.0
    tile_types: Dict[str, int] = field(default_factory=dict)
    goals: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_tiles": self.total_tiles,
            "active_layers": self.active_layers,
            "chain_count": self.chain_count,
            "frog_count": self.frog_count,
            "link_count": self.link_count,
            "goal_amount": self.goal_amount,
            "layer_blocking": self.layer_blocking,
            "tile_types": self.tile_types,
            "goals": self.goals,
        }


@dataclass
class DifficultyReport:
    """Complete difficulty analysis report."""
    score: float
    grade: DifficultyGrade
    metrics: LevelMetrics
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "score": round(self.score, 2),
            "grade": self.grade.value,
            "metrics": self.metrics.to_dict(),
            "recommendations": self.recommendations,
        }


@dataclass
class ObstacleConfig:
    """Configuration for obstacle generation."""
    min_count: int = 0
    max_count: int = 10


@dataclass
class GenerationParams:
    """Parameters for level generation."""
    target_difficulty: float  # 0.0 ~ 1.0
    grid_size: Tuple[int, int] = (7, 7)
    max_layers: int = 8
    tile_types: Optional[List[str]] = None
    obstacle_types: Optional[List[str]] = None
    goals: Optional[List[Dict[str, Any]]] = None
    # Obstacle count settings (min, max for each type)
    obstacle_counts: Optional[Dict[str, Dict[str, int]]] = None

    def __post_init__(self):
        """Set default values after initialization."""
        if self.tile_types is None:
            self.tile_types = ["t0", "t2", "t4", "t5", "t6", "t8", "t9", "t10", "t11", "t12", "t14", "t15"]
        if self.obstacle_types is None:
            self.obstacle_types = ["chain", "frog"]
        # Only set default goals if None, not if empty list (empty list means no goals)
        if self.goals is None:
            self.goals = [{"type": "craft_s", "count": 3}]
        # If goals is empty list, keep it as empty (user explicitly wants no goals)

    def get_obstacle_count(self, obstacle_type: str, total_tiles: int, difficulty: float) -> Tuple[int, int]:
        """Get min/max count for an obstacle type."""
        if self.obstacle_counts and obstacle_type in self.obstacle_counts:
            config = self.obstacle_counts[obstacle_type]
            return config.get("min", 0), config.get("max", 10)
        # Default: calculate based on difficulty (legacy behavior)
        return 0, -1  # -1 means use legacy calculation


@dataclass
class GenerationResult:
    """Result of level generation."""
    level_json: Dict[str, Any]
    actual_difficulty: float
    grade: DifficultyGrade
    generation_time_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "level_json": self.level_json,
            "actual_difficulty": round(self.actual_difficulty, 3),
            "grade": self.grade.value,
            "generation_time_ms": self.generation_time_ms,
        }


@dataclass
class SimulationResult:
    """Result of level simulation."""
    clear_rate: float
    avg_moves: float
    min_moves: int
    max_moves: int
    iterations: int
    strategy: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "clear_rate": round(self.clear_rate, 3),
            "avg_moves": round(self.avg_moves, 2),
            "min_moves": self.min_moves,
            "max_moves": self.max_moves,
            "iterations": self.iterations,
            "strategy": self.strategy,
        }


# Tile type definitions
TILE_TYPES = {
    "t0": "Basic Tile",
    "t2": "Special Tile A",
    "t4": "Special Tile B",
    "t5": "Special Tile C",
    "t6": "Special Tile D",
    "t8": "Obstacle Tile A",
    "t9": "Obstacle Tile B",
    "t10": "Special Tile E",
    "t11": "Special Tile F",
    "t12": "Special Tile G",
    "t14": "Advanced Tile A",
    "t15": "Advanced Tile B",
    "craft_s": "Craft Goal",
    "stack_s": "Stack Goal",
}

# Attribute definitions with difficulty impacts
ATTRIBUTES = {
    "": {"name": "None", "difficulty_impact": 0},
    "chain": {"name": "Chain", "difficulty_impact": 3},
    "frog": {"name": "Frog", "difficulty_impact": 4},
    "link_w": {"name": "Link West", "difficulty_impact": 2},
    "link_n": {"name": "Link North", "difficulty_impact": 2},
}

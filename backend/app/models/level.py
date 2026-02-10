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
    ice_count: int = 0
    goal_amount: int = 0
    layer_blocking: float = 0.0
    tile_types: Dict[str, int] = field(default_factory=dict)
    goals: List[Dict[str, Any]] = field(default_factory=list)
    # New metrics for better bot simulation correlation
    tile_type_count: int = 0       # 타일 종류 다양성 (덱 큐 막힘 확률)
    max_moves: int = 30            # 최대 무브 수
    move_ratio: float = 0.0        # total_tiles / max_moves (높을수록 어려움)
    # 추가 기믹 카운트 (통합 가중치 시스템용)
    grass_count: int = 0           # 풀 기믹 개수
    bomb_count: int = 0            # 폭탄 기믹 개수
    curtain_count: int = 0         # 커튼 기믹 개수
    teleport_count: int = 0        # 텔레포트 기믹 개수
    unknown_count: int = 0         # 상자 기믹 개수
    has_key_gimmick: bool = False  # key 기믹 사용 여부
    has_time_attack: bool = False  # time_attack 기믹 사용 여부

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_tiles": self.total_tiles,
            "active_layers": self.active_layers,
            "chain_count": self.chain_count,
            "frog_count": self.frog_count,
            "link_count": self.link_count,
            "ice_count": self.ice_count,
            "goal_amount": self.goal_amount,
            "layer_blocking": self.layer_blocking,
            "tile_types": self.tile_types,
            "goals": self.goals,
            "tile_type_count": self.tile_type_count,
            "max_moves": self.max_moves,
            "move_ratio": round(self.move_ratio, 2),
            # 추가 기믹 카운트
            "grass_count": self.grass_count,
            "bomb_count": self.bomb_count,
            "curtain_count": self.curtain_count,
            "teleport_count": self.teleport_count,
            "unknown_count": self.unknown_count,
            "has_key_gimmick": self.has_key_gimmick,
            "has_time_attack": self.has_time_attack,
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
class LayerTileConfig:
    """Configuration for tile count on a specific layer."""
    layer: int
    count: int


@dataclass
class LayerObstacleConfig:
    """Configuration for obstacle counts on a specific layer."""
    layer: int
    counts: Dict[str, Dict[str, int]]  # obstacle_type -> {min, max}


@dataclass
class LayerPatternConfig:
    """Configuration for pattern placement on a specific layer."""
    layer: int
    pattern_type: str  # 'random', 'geometric', 'clustered', 'aesthetic'
    pattern_index: Optional[int] = None  # 0-49 for aesthetic mode


@dataclass
class GenerationParams:
    """Parameters for level generation."""
    target_difficulty: float  # 0.0 ~ 1.0
    grid_size: Tuple[int, int] = (7, 7)
    min_layers: int = 3  # Minimum layer count (for easier levels)
    max_layers: int = 8  # Maximum layer count (for harder levels)
    tile_types: Optional[List[str]] = None
    obstacle_types: Optional[List[str]] = None
    goals: Optional[List[Dict[str, Any]]] = None
    # Obstacle count settings (min, max for each type)
    obstacle_counts: Optional[Dict[str, Dict[str, int]]] = None
    # New fields for enhanced generation control
    total_tile_count: Optional[int] = None  # Total tiles across all layers
    active_layer_count: Optional[int] = None  # Number of active layers
    layer_tile_configs: Optional[List[LayerTileConfig]] = None  # Per-layer tile counts
    layer_obstacle_configs: Optional[List[LayerObstacleConfig]] = None  # Per-layer obstacle counts
    layer_pattern_configs: Optional[List[LayerPatternConfig]] = None  # Per-layer pattern settings
    # Symmetry and pattern options
    symmetry_mode: Optional[str] = None  # 'none', 'horizontal', 'vertical', 'both'
    pattern_type: Optional[str] = None  # 'random', 'geometric', 'clustered', 'aesthetic'
    pattern_index: Optional[int] = None  # 0-49 for specific aesthetic pattern (None = auto-select)
    # Gimmick intensity control
    gimmick_intensity: float = 1.0  # 0.0=no gimmicks, 1.0=normal, 2.0=double
    # Tutorial gimmick settings (for gimmick unlock levels)
    tutorial_gimmick: Optional[str] = None  # Gimmick to introduce on this level (placed on top layer)
    tutorial_gimmick_min_count: int = 2  # Minimum count for tutorial gimmick (guaranteed placement)
    # Level number for research-based unknown ratio calculation
    # [연구 근거] Room 8 Studio: 레벨 175+ 히든 타일 본격 도입
    level_number: Optional[int] = None  # Current level number for gimmick unlock & unknown ratio

    def __post_init__(self):
        """Set default values after initialization."""
        if self.tile_types is None:
            # Auto-select tile types based on level number if provided
            if self.level_number is not None:
                # Import here to avoid circular dependency
                from ..core.generator import get_tile_types_for_level
                self.tile_types = get_tile_types_for_level(self.level_number)
            else:
                # Default to t1~t15 (useTileCount=15, matches TownPop client)
                # NOTE: t0 is excluded - causes issues with bot simulation
                self.tile_types = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10", "t11", "t12", "t13", "t14", "t15"]
        if self.obstacle_types is None:
            self.obstacle_types = ["chain", "frog"]
        # Only set default goals if None, not if empty list (empty list means no goals)
        # Fixed layout levels (2, 3) are early tutorial levels without craft/stack goals
        if self.goals is None:
            if self.level_number in (2, 3):
                self.goals = []  # No goals for fixed layout levels
            else:
                self.goals = [{"type": "craft_s", "count": 3}]
        # If goals is empty list, keep it as empty (user explicitly wants no goals)

    def get_obstacle_count(self, obstacle_type: str, total_tiles: int, difficulty: float) -> Tuple[int, int]:
        """Get min/max count for an obstacle type."""
        if self.obstacle_counts and obstacle_type in self.obstacle_counts:
            config = self.obstacle_counts[obstacle_type]
            return config.get("min", 0), config.get("max", 10)
        # Default: calculate based on difficulty (legacy behavior)
        return 0, -1  # -1 means use legacy calculation

    def get_layer_tile_count(self, layer_idx: int) -> Optional[int]:
        """Get configured tile count for a specific layer, or None if not configured."""
        if not self.layer_tile_configs:
            return None
        for config in self.layer_tile_configs:
            if config.layer == layer_idx:
                return config.count
        return None

    def get_layer_obstacle_config(self, layer_idx: int, obstacle_type: str) -> Optional[Tuple[int, int]]:
        """Get configured obstacle count (min, max) for a specific layer and type."""
        if not self.layer_obstacle_configs:
            return None
        for config in self.layer_obstacle_configs:
            if config.layer == layer_idx and obstacle_type in config.counts:
                obs_config = config.counts[obstacle_type]
                return obs_config.get("min", 0), obs_config.get("max", 10)
        return None

    def get_layer_pattern_config(self, layer_idx: int) -> Optional[Tuple[str, Optional[int]]]:
        """Get configured pattern (pattern_type, pattern_index) for a specific layer.

        Returns:
            Tuple of (pattern_type, pattern_index) or None if not configured
        """
        if not self.layer_pattern_configs:
            return None
        for config in self.layer_pattern_configs:
            if config.layer == layer_idx:
                return (config.pattern_type, config.pattern_index)
        return None


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

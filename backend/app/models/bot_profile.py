"""Bot profile definitions for multi-bot difficulty assessment."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class BotType(str, Enum):
    """Bot type enumeration representing different player skill levels."""
    NOVICE = "novice"       # 초보 플레이어 - 랜덤에 가까운 선택
    CASUAL = "casual"       # 캐주얼 플레이어 - 기본 전략
    AVERAGE = "average"     # 평균 플레이어 - 그리디 전략
    EXPERT = "expert"       # 숙련 플레이어 - 최적화 전략
    OPTIMAL = "optimal"     # 최적 플레이 - MCTS 기반

    @classmethod
    def all_types(cls) -> List["BotType"]:
        """Return all bot types in order of skill level."""
        return [cls.NOVICE, cls.CASUAL, cls.AVERAGE, cls.EXPERT, cls.OPTIMAL]


@dataclass
class BotProfile:
    """
    Configuration profile for a simulation bot.

    Each profile represents a different player archetype with distinct
    decision-making characteristics and skill levels.
    """
    name: str
    bot_type: BotType
    description: str

    # Core behavior parameters (0.0 - 1.0)
    mistake_rate: float = 0.1          # 실수 확률 (잘못된 수 선택)
    lookahead_depth: int = 2           # 선읽기 깊이 (0 = 현재 상태만)
    goal_priority: float = 0.7         # 목표 달성 우선순위
    blocking_awareness: float = 0.7    # 레이어 블로킹 인식 능력
    chain_preference: float = 0.5      # 체인/콤보 선호도

    # Advanced parameters
    patience: float = 0.5              # 인내심 (낮으면 빠른 결정)
    risk_tolerance: float = 0.5        # 위험 감수 정도
    pattern_recognition: float = 0.5   # 패턴 인식 능력

    # Simulation settings
    weight: float = 1.0                # 난이도 계산 시 가중치

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "bot_type": self.bot_type.value,
            "description": self.description,
            "mistake_rate": self.mistake_rate,
            "lookahead_depth": self.lookahead_depth,
            "goal_priority": self.goal_priority,
            "blocking_awareness": self.blocking_awareness,
            "chain_preference": self.chain_preference,
            "patience": self.patience,
            "risk_tolerance": self.risk_tolerance,
            "pattern_recognition": self.pattern_recognition,
            "weight": self.weight,
        }


# Predefined bot profiles
PREDEFINED_PROFILES: Dict[BotType, BotProfile] = {
    BotType.NOVICE: BotProfile(
        name="Novice Bot",
        bot_type=BotType.NOVICE,
        description="초보 플레이어를 시뮬레이션. 거의 랜덤한 선택, 높은 실수율.",
        mistake_rate=0.4,
        lookahead_depth=0,
        goal_priority=0.3,
        blocking_awareness=0.2,
        chain_preference=0.1,
        patience=0.3,
        risk_tolerance=0.7,
        pattern_recognition=0.2,
        weight=0.5,  # 낮은 가중치 (타겟 유저가 아님)
    ),

    BotType.CASUAL: BotProfile(
        name="Casual Bot",
        bot_type=BotType.CASUAL,
        description="캐주얼 플레이어를 시뮬레이션. 기본 전략, 가끔 실수.",
        mistake_rate=0.2,
        lookahead_depth=1,
        goal_priority=0.5,
        blocking_awareness=0.4,
        chain_preference=0.3,
        patience=0.4,
        risk_tolerance=0.5,
        pattern_recognition=0.4,
        weight=1.0,  # 주요 타겟 유저
    ),

    BotType.AVERAGE: BotProfile(
        name="Average Bot",
        bot_type=BotType.AVERAGE,
        description="평균 플레이어를 시뮬레이션. 그리디 전략, 적은 실수.",
        mistake_rate=0.1,
        lookahead_depth=2,
        goal_priority=0.7,
        blocking_awareness=0.7,
        chain_preference=0.6,
        patience=0.5,
        risk_tolerance=0.4,
        pattern_recognition=0.6,
        weight=1.5,  # 가장 중요한 타겟
    ),

    BotType.EXPERT: BotProfile(
        name="Expert Bot",
        bot_type=BotType.EXPERT,
        description="숙련 플레이어를 시뮬레이션. 최적화 전략, 매우 적은 실수.",
        mistake_rate=0.03,
        lookahead_depth=4,
        goal_priority=0.9,
        blocking_awareness=0.9,
        chain_preference=0.8,
        patience=0.7,
        risk_tolerance=0.3,
        pattern_recognition=0.8,
        weight=0.8,  # 중간 가중치
    ),

    BotType.OPTIMAL: BotProfile(
        name="Optimal Bot",
        bot_type=BotType.OPTIMAL,
        description="이론적 최적 플레이를 시뮬레이션. MCTS 기반 완벽한 플레이.",
        mistake_rate=0.0,
        lookahead_depth=8,
        goal_priority=1.0,
        blocking_awareness=1.0,
        chain_preference=1.0,
        patience=1.0,
        risk_tolerance=0.2,
        pattern_recognition=1.0,
        weight=0.3,  # 낮은 가중치 (현실적이지 않음)
    ),
}


def get_profile(bot_type: BotType) -> BotProfile:
    """Get predefined profile by bot type."""
    return PREDEFINED_PROFILES[bot_type]


def get_all_profiles() -> List[BotProfile]:
    """Get all predefined profiles."""
    return list(PREDEFINED_PROFILES.values())


def create_custom_profile(
    name: str,
    base_type: BotType,
    **overrides
) -> BotProfile:
    """
    Create a custom profile based on a predefined one with overrides.

    Args:
        name: Custom profile name
        base_type: Base bot type to derive from
        **overrides: Parameters to override

    Returns:
        New BotProfile with custom settings
    """
    base = PREDEFINED_PROFILES[base_type]

    return BotProfile(
        name=name,
        bot_type=base_type,
        description=overrides.get("description", f"Custom profile based on {base.name}"),
        mistake_rate=overrides.get("mistake_rate", base.mistake_rate),
        lookahead_depth=overrides.get("lookahead_depth", base.lookahead_depth),
        goal_priority=overrides.get("goal_priority", base.goal_priority),
        blocking_awareness=overrides.get("blocking_awareness", base.blocking_awareness),
        chain_preference=overrides.get("chain_preference", base.chain_preference),
        patience=overrides.get("patience", base.patience),
        risk_tolerance=overrides.get("risk_tolerance", base.risk_tolerance),
        pattern_recognition=overrides.get("pattern_recognition", base.pattern_recognition),
        weight=overrides.get("weight", base.weight),
    )


@dataclass
class BotTeam:
    """
    A collection of bots to run simulations with.

    Allows flexible configuration of which bots to use and their
    respective iterations and weights.
    """
    profiles: List[BotProfile] = field(default_factory=list)
    iterations_per_bot: int = 100

    @classmethod
    def default_team(cls, iterations_per_bot: int = 100) -> "BotTeam":
        """Create a default team with all predefined bots."""
        return cls(
            profiles=get_all_profiles(),
            iterations_per_bot=iterations_per_bot,
        )

    @classmethod
    def casual_team(cls, iterations_per_bot: int = 100) -> "BotTeam":
        """Create a team focused on casual players."""
        return cls(
            profiles=[
                PREDEFINED_PROFILES[BotType.NOVICE],
                PREDEFINED_PROFILES[BotType.CASUAL],
                PREDEFINED_PROFILES[BotType.AVERAGE],
            ],
            iterations_per_bot=iterations_per_bot,
        )

    @classmethod
    def hardcore_team(cls, iterations_per_bot: int = 100) -> "BotTeam":
        """Create a team focused on hardcore players."""
        return cls(
            profiles=[
                PREDEFINED_PROFILES[BotType.AVERAGE],
                PREDEFINED_PROFILES[BotType.EXPERT],
                PREDEFINED_PROFILES[BotType.OPTIMAL],
            ],
            iterations_per_bot=iterations_per_bot,
        )

    def add_profile(self, profile: BotProfile) -> None:
        """Add a profile to the team."""
        self.profiles.append(profile)

    def total_iterations(self) -> int:
        """Calculate total iterations across all bots."""
        return len(self.profiles) * self.iterations_per_bot

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "profiles": [p.to_dict() for p in self.profiles],
            "iterations_per_bot": self.iterations_per_bot,
            "total_iterations": self.total_iterations(),
        }

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


# Predefined bot profiles - 실제 인간 플레이어 행동 모델링
# 각 봇은 실제 플레이어 유형의 인지적 특성과 행동 패턴을 반영
PREDEFINED_PROFILES: Dict[BotType, BotProfile] = {
    # ============================================================
    # NOVICE (사람 초보자)
    # - 게임 메카닉 이해 부족
    # - 거의 랜덤한 타일 선택
    # - 레이어/블로킹 개념 없음
    # - 기믹(chain, grass) 영향 인지 못함
    # - 독(dock) 관리 의식 없음
    # ============================================================
    BotType.NOVICE: BotProfile(
        name="Novice Bot",
        bot_type=BotType.NOVICE,
        description="사람 초보자: 게임 메카닉 미이해, 거의 랜덤 선택, 기믹 인지 없음",
        mistake_rate=0.45,       # 45% 실수 - 잘못된 선택 빈번
        lookahead_depth=0,       # 선읽기 없음 - 즉흥적 선택
        goal_priority=0.2,       # 목표 의식 거의 없음
        blocking_awareness=0.1,  # 레이어 블로킹 거의 인지 못함
        chain_preference=0.05,   # 기믹 선호도 거의 없음
        patience=0.2,            # 성급함 - 빠른 선택
        risk_tolerance=0.8,      # 위험 인지 없음 - 아무 타일이나 선택
        pattern_recognition=0.15, # 패턴 인식 거의 없음
        weight=0.5,              # 낮은 가중치 (타겟 유저 아님)
    ),

    # ============================================================
    # CASUAL (사람 초중급자)
    # - 기본 매칭 규칙 이해 (3개 매칭)
    # - 독(dock)이 차면 위험하다는 것 인지
    # - 가끔 실수하며 학습 중
    # - 레이어 개념 약간 인지
    # - 기믹은 있다는 것만 앎
    # ============================================================
    BotType.CASUAL: BotProfile(
        name="Casual Bot",
        bot_type=BotType.CASUAL,
        description="사람 초중급자: 기본 매칭 이해, 독 위험 인지, 가끔 실수",
        mistake_rate=0.25,       # 25% 실수 - 학습 과정
        lookahead_depth=1,       # 1수 앞 보기 - 즉각 매칭 인지
        goal_priority=0.45,      # 어느정도 목표 의식
        blocking_awareness=0.35, # 레이어 블로킹 약간 인지
        chain_preference=0.25,   # 기믹 존재 인지, 우선순위 낮음
        patience=0.35,           # 다소 성급 - 직관적 선택
        risk_tolerance=0.6,      # 위험 감수 높음 - 경험 부족
        pattern_recognition=0.35, # 기본 패턴만 인식
        weight=1.0,              # 주요 타겟 유저
    ),

    # ============================================================
    # AVERAGE (사람 중급자)
    # - 그리디 전략 사용 (즉시 이득 추구)
    # - 레이어 블로킹 잘 이해
    # - 독 관리 능력 있음
    # - 기믹 효과 이해하고 어느정도 고려
    # - 적은 실수, 가끔 최선 아닌 선택
    # ============================================================
    BotType.AVERAGE: BotProfile(
        name="Average Bot",
        bot_type=BotType.AVERAGE,
        description="사람 중급자: 그리디 전략, 레이어 인식, 기믹 고려, 적은 실수",
        mistake_rate=0.12,       # 12% 실수 - 가끔 판단 오류
        lookahead_depth=2,       # 2수 앞 보기 - 단기 계획
        goal_priority=0.7,       # 목표 달성 집중
        blocking_awareness=0.7,  # 레이어 블로킹 잘 인지
        chain_preference=0.6,    # 기믹 해제 우선순위 고려
        patience=0.5,            # 균형잡힌 의사결정
        risk_tolerance=0.4,      # 중간 위험 감수
        pattern_recognition=0.6, # 주요 패턴 인식
        weight=1.5,              # 가장 중요한 타겟
    ),

    # ============================================================
    # EXPERT (사람 고급자)
    # - 최적화 전략 사용
    # - chain/grass 해제 우선순위 적극 고려
    # - 장기적 게임 상태 예측
    # - 독 관리 마스터
    # - 매우 적은 실수
    # ============================================================
    BotType.EXPERT: BotProfile(
        name="Expert Bot",
        bot_type=BotType.EXPERT,
        description="사람 고급자: 최적화 전략, 기믹 우선순위 적극 고려, 장기 예측",
        mistake_rate=0.03,       # 3% 실수 - 드물게 판단 오류
        lookahead_depth=5,       # 5수 앞 보기 - 중기 계획
        goal_priority=0.92,      # 높은 목표 집중
        blocking_awareness=0.92, # 레이어 블로킹 거의 완벽
        chain_preference=0.85,   # 기믹 해제 적극 고려
        patience=0.8,            # 신중한 의사결정
        risk_tolerance=0.2,      # 보수적 플레이
        pattern_recognition=0.88, # 고급 패턴 인식
        weight=0.8,              # 중간 가중치
    ),

    # ============================================================
    # OPTIMAL (최적 경로 AI)
    # - 완벽한 정보 기반 의사결정
    # - 실수 없음, 최선의 수만 선택
    # - chain/grass 해제 시점 완벽 계산
    # - 장기적 게임 트리 탐색
    # - 데드락 회피 완벽
    # ============================================================
    BotType.OPTIMAL: BotProfile(
        name="Optimal Bot",
        bot_type=BotType.OPTIMAL,
        description="최적 경로 AI: 실수 없음, 완벽한 정보 전략, 최선의 수만 선택",
        mistake_rate=0.0,        # 0% 실수 - 완벽한 실행
        lookahead_depth=10,      # 최대 선읽기 깊이
        goal_priority=1.0,       # 완벽한 목표 집중
        blocking_awareness=1.0,  # 완벽한 블로킹 인식
        chain_preference=1.0,    # 기믹 우선순위 완벽 계산
        patience=1.0,            # 최적의 수를 항상 기다림
        risk_tolerance=0.05,     # 최소 위험 - 안전한 경로만
        # Note: 0.99 사용 - _optimal_perfect_information_strategy에
        # 특정 기믹 조합에서 버그가 있어 enhanced lookahead 사용
        pattern_recognition=0.99, # Near-perfect 패턴 인식 (enhanced lookahead 사용)
        weight=0.3,              # 낮은 가중치 (현실적 난이도 기준 아님)
    ),
}


# ============================================================
# Fast Verification Profiles - Optimized for batch verification
# Reduced lookahead depth for faster simulation while maintaining accuracy
# ============================================================
FAST_VERIFICATION_PROFILES: Dict[BotType, BotProfile] = {
    BotType.CASUAL: BotProfile(
        name="Fast Casual Bot",
        bot_type=BotType.CASUAL,
        description="빠른 검증용 캐주얼 봇: lookahead 감소",
        mistake_rate=0.25,
        lookahead_depth=0,       # 1 → 0 (즉각 선택)
        goal_priority=0.45,
        blocking_awareness=0.35,
        chain_preference=0.25,
        patience=0.35,
        risk_tolerance=0.6,
        pattern_recognition=0.35,
        weight=1.0,
    ),
    BotType.AVERAGE: BotProfile(
        name="Fast Average Bot",
        bot_type=BotType.AVERAGE,
        description="빠른 검증용 평균 봇: lookahead 감소",
        mistake_rate=0.12,
        lookahead_depth=1,       # 2 → 1 (1수 앞만)
        goal_priority=0.7,
        blocking_awareness=0.7,
        chain_preference=0.6,
        patience=0.5,
        risk_tolerance=0.4,
        pattern_recognition=0.6,
        weight=1.5,
    ),
    BotType.EXPERT: BotProfile(
        name="Fast Expert Bot",
        bot_type=BotType.EXPERT,
        description="빠른 검증용 전문가 봇: lookahead 감소",
        mistake_rate=0.03,
        lookahead_depth=2,       # 5 → 2 (2수 앞만)
        goal_priority=0.92,
        blocking_awareness=0.92,
        chain_preference=0.85,
        patience=0.8,
        risk_tolerance=0.2,
        pattern_recognition=0.88,
        weight=0.8,
    ),
}


def get_profile(bot_type: BotType, fast_mode: bool = False) -> BotProfile:
    """Get predefined profile by bot type.

    Args:
        bot_type: The bot type to get profile for
        fast_mode: If True, return fast verification profile (reduced lookahead)
    """
    if fast_mode and bot_type in FAST_VERIFICATION_PROFILES:
        return FAST_VERIFICATION_PROFILES[bot_type]
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

    @classmethod
    def fast_core_team(cls, iterations_per_bot: int = 20) -> "BotTeam":
        """Create a fast verification team with reduced lookahead depth.

        Uses only core bots (casual, average, expert) with optimized profiles
        for faster batch verification while maintaining accuracy.
        """
        return cls(
            profiles=[
                FAST_VERIFICATION_PROFILES[BotType.CASUAL],
                FAST_VERIFICATION_PROFILES[BotType.AVERAGE],
                FAST_VERIFICATION_PROFILES[BotType.EXPERT],
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

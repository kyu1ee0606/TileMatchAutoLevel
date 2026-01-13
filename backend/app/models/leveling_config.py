"""
프로급 타일 매칭 게임 레벨링 시스템 설정

Tile Buster, Tile Explorer, Triple Match 3D 등 유명 타일 게임의
레벨링 패턴을 분석하여 구현한 설정입니다.

주요 특징:
1. 점진적 기믹 도입 (Tutorial → Practice → Integration)
2. 톱니바퀴 난이도 패턴 (10레벨 단위 순환)
3. 레이어/타일 종류 점진적 증가
4. 마스터리 존 (새 기믹 전 기존 기믹 충분히 연습)
"""
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class LevelPhase(str, Enum):
    """레벨 진행 단계"""
    TUTORIAL = "tutorial"       # 1-10: 순수 매칭 학습
    BASIC = "basic"             # 11-50: 단일 기믹 학습
    INTERMEDIATE = "intermediate"  # 51-100: 2기믹 조합
    ADVANCED = "advanced"       # 101-150: 3기믹 조합
    EXPERT = "expert"           # 151+: 자유 조합
    MASTER = "master"           # 200+: 최고 난이도


class GimmickIntroPhase(str, Enum):
    """기믹 도입 단계 (각 기믹별)"""
    TUTORIAL = "tutorial"       # 첫 등장 레벨 - 매우 쉬움
    PRACTICE = "practice"       # 연습 레벨 (3-5개) - 쉬움~중간
    INTEGRATION = "integration"  # 통합 레벨 - 이전 기믹과 조합
    MASTERY = "mastery"         # 숙달 레벨 - 자유롭게 사용


@dataclass
class GimmickUnlockConfig:
    """개별 기믹 언락 설정"""
    gimmick: str
    unlock_level: int           # 언락되는 레벨
    practice_levels: int        # 연습 레벨 수 (이 기믹만 사용)
    integration_start: int      # 이전 기믹과 통합 시작 레벨
    difficulty_weight: float    # 난이도 가중치 (1.0 = 기본)
    description: str            # 기믹 설명


# =========================================================
# 프로급 기믹 언락 스케줄
# =========================================================
# 유명 타일 게임 분석 결과:
# - 첫 10레벨: 기믹 없이 순수 매칭 학습
# - 새 기믹 도입 후 충분한 연습 기간 (5-10레벨)
# - 기믹 간 조합은 점진적으로 소개
# =========================================================

PROFESSIONAL_GIMMICK_UNLOCK: Dict[str, GimmickUnlockConfig] = {
    "chain": GimmickUnlockConfig(
        gimmick="chain",
        unlock_level=11,
        practice_levels=9,  # 11-19: chain만 연습
        integration_start=20,
        difficulty_weight=1.0,
        description="체인 - 가장 기본적인 기믹, 인접 타일로 해제"
    ),
    "ice": GimmickUnlockConfig(
        gimmick="ice",
        unlock_level=21,
        practice_levels=9,  # 21-29: ice만 또는 ice+chain
        integration_start=30,
        difficulty_weight=1.2,
        description="얼음 - 인접 타일 클리어로 녹임"
    ),
    "frog": GimmickUnlockConfig(
        gimmick="frog",
        unlock_level=36,
        practice_levels=9,  # 36-44: frog 연습
        integration_start=45,
        difficulty_weight=1.3,
        description="개구리 - 매 턴 이동, 전략적 배치 필요"
    ),
    "grass": GimmickUnlockConfig(
        gimmick="grass",
        unlock_level=51,
        practice_levels=9,
        integration_start=60,
        difficulty_weight=1.1,
        description="풀 - 인접 타일 클리어로 제거"
    ),
    "link": GimmickUnlockConfig(
        gimmick="link",
        unlock_level=66,
        practice_levels=9,
        integration_start=75,
        difficulty_weight=1.4,
        description="링크 - 연결된 타일 동시 선택"
    ),
    "bomb": GimmickUnlockConfig(
        gimmick="bomb",
        unlock_level=81,
        practice_levels=9,
        integration_start=90,
        difficulty_weight=1.5,
        description="폭탄 - 카운트다운 후 폭발, 시간 압박"
    ),
    "curtain": GimmickUnlockConfig(
        gimmick="curtain",
        unlock_level=96,
        practice_levels=9,
        integration_start=105,
        difficulty_weight=1.3,
        description="커튼 - 가려진 타일, 기억력 테스트"
    ),
    "teleport": GimmickUnlockConfig(
        gimmick="teleport",
        unlock_level=111,
        practice_levels=9,
        integration_start=120,
        difficulty_weight=1.2,
        description="텔레포트 - 타일 위치 변경"
    ),
    "unknown": GimmickUnlockConfig(
        gimmick="unknown",
        unlock_level=126,
        practice_levels=9,
        integration_start=135,
        difficulty_weight=1.3,
        description="미스터리 - 상위 타일 제거 전까지 숨겨짐"
    ),
    "craft": GimmickUnlockConfig(
        gimmick="craft",
        unlock_level=141,
        practice_levels=9,
        integration_start=150,
        difficulty_weight=1.4,
        description="크래프트 목표 - 특정 방향으로 타일 수집"
    ),
    "stack": GimmickUnlockConfig(
        gimmick="stack",
        unlock_level=156,
        practice_levels=9,
        integration_start=165,
        difficulty_weight=1.5,
        description="스택 목표 - 겹쳐진 타일 수집"
    ),
}


# =========================================================
# 톱니바퀴(Sawtooth) 난이도 패턴
# =========================================================
# 10레벨 단위로 순환하는 난이도 조절 시스템
# 0.0 = 매우 쉬움, 1.0 = 매우 어려움 (상대적 조절값)
# =========================================================

SAWTOOTH_PATTERN_10: List[float] = [
    0.0,   # 레벨 1: 새 시작, 매우 쉬움
    0.1,   # 레벨 2: 여전히 쉬움
    0.2,   # 레벨 3: 약간 증가
    0.35,  # 레벨 4: 중간으로 진입
    0.45,  # 레벨 5: 중간
    0.55,  # 레벨 6: 중간 약간 위
    0.7,   # 레벨 7: 어려워지기 시작
    0.85,  # 레벨 8: 어려움
    0.75,  # 레벨 9: 보스 전 휴식
    1.0,   # 레벨 10: 보스 레벨 (해당 구간 최고 난이도)
]


# 5레벨 단위 미니 패턴 (더 세밀한 조절용)
SAWTOOTH_PATTERN_5: List[float] = [
    0.0,   # 레벨 1: 시작
    0.3,   # 레벨 2: 증가
    0.6,   # 레벨 3: 중간 높음
    0.5,   # 레벨 4: 약간 완화
    0.9,   # 레벨 5: 미니 보스
]


# =========================================================
# 레벨 단계별 파라미터 설정
# =========================================================

@dataclass
class PhaseConfig:
    """레벨 단계별 설정"""
    phase: LevelPhase
    level_range: Tuple[int, int]  # (시작, 끝) 레벨
    min_tile_types: int           # 최소 타일 종류
    max_tile_types: int           # 최대 타일 종류
    min_layers: int               # 최소 레이어
    max_layers: int               # 최대 레이어
    max_gimmick_types: int        # 최대 기믹 종류 (동시)
    base_difficulty: float        # 기본 난이도 (0-1)
    difficulty_increment: float   # 레벨당 난이도 증가


PHASE_CONFIGS: Dict[LevelPhase, PhaseConfig] = {
    LevelPhase.TUTORIAL: PhaseConfig(
        phase=LevelPhase.TUTORIAL,
        level_range=(1, 10),
        min_tile_types=3,
        max_tile_types=4,
        min_layers=1,
        max_layers=2,
        max_gimmick_types=0,  # 기믹 없음
        base_difficulty=0.05,
        difficulty_increment=0.015,
    ),
    LevelPhase.BASIC: PhaseConfig(
        phase=LevelPhase.BASIC,
        level_range=(11, 50),
        min_tile_types=4,
        max_tile_types=5,
        min_layers=2,
        max_layers=4,
        max_gimmick_types=1,  # 1개 기믹만
        base_difficulty=0.15,
        difficulty_increment=0.01,
    ),
    LevelPhase.INTERMEDIATE: PhaseConfig(
        phase=LevelPhase.INTERMEDIATE,
        level_range=(51, 100),
        min_tile_types=5,
        max_tile_types=6,
        min_layers=3,
        max_layers=5,
        max_gimmick_types=2,  # 2개 기믹 조합
        base_difficulty=0.35,
        difficulty_increment=0.008,
    ),
    LevelPhase.ADVANCED: PhaseConfig(
        phase=LevelPhase.ADVANCED,
        level_range=(101, 150),
        min_tile_types=5,
        max_tile_types=7,
        min_layers=4,
        max_layers=6,
        max_gimmick_types=3,  # 3개 기믹 조합
        base_difficulty=0.55,
        difficulty_increment=0.006,
    ),
    LevelPhase.EXPERT: PhaseConfig(
        phase=LevelPhase.EXPERT,
        level_range=(151, 200),
        min_tile_types=6,
        max_tile_types=8,
        min_layers=4,
        max_layers=7,
        max_gimmick_types=4,
        base_difficulty=0.70,
        difficulty_increment=0.004,
    ),
    LevelPhase.MASTER: PhaseConfig(
        phase=LevelPhase.MASTER,
        level_range=(201, 9999),
        min_tile_types=6,
        max_tile_types=9,
        min_layers=5,
        max_layers=7,
        max_gimmick_types=5,
        base_difficulty=0.80,
        difficulty_increment=0.002,
    ),
}


# =========================================================
# 헬퍼 함수들
# =========================================================

def get_phase_for_level(level_number: int) -> LevelPhase:
    """레벨 번호에 해당하는 단계 반환"""
    for phase, config in PHASE_CONFIGS.items():
        if config.level_range[0] <= level_number <= config.level_range[1]:
            return phase
    return LevelPhase.MASTER


def get_phase_config(level_number: int) -> PhaseConfig:
    """레벨 번호에 해당하는 단계 설정 반환"""
    phase = get_phase_for_level(level_number)
    return PHASE_CONFIGS[phase]


def get_unlocked_gimmicks(level_number: int) -> List[str]:
    """해당 레벨에서 사용 가능한 기믹 목록 반환"""
    return [
        config.gimmick
        for config in PROFESSIONAL_GIMMICK_UNLOCK.values()
        if config.unlock_level <= level_number
    ]


def get_tutorial_gimmick_at_level(level_number: int) -> Optional[str]:
    """해당 레벨이 기믹 튜토리얼 레벨인지 확인하고 기믹 반환"""
    for config in PROFESSIONAL_GIMMICK_UNLOCK.values():
        if config.unlock_level == level_number:
            return config.gimmick
    return None


def get_gimmick_intro_phase(level_number: int, gimmick: str) -> GimmickIntroPhase:
    """특정 레벨에서 해당 기믹의 도입 단계 반환"""
    config = PROFESSIONAL_GIMMICK_UNLOCK.get(gimmick)
    if not config:
        return GimmickIntroPhase.MASTERY

    if level_number < config.unlock_level:
        return GimmickIntroPhase.MASTERY  # 아직 언락 안됨
    elif level_number == config.unlock_level:
        return GimmickIntroPhase.TUTORIAL
    elif level_number < config.unlock_level + config.practice_levels:
        return GimmickIntroPhase.PRACTICE
    elif level_number < config.integration_start:
        return GimmickIntroPhase.INTEGRATION
    else:
        return GimmickIntroPhase.MASTERY


def get_recommended_gimmicks_for_level(
    level_number: int,
    available_pool: Optional[List[str]] = None
) -> List[str]:
    """
    해당 레벨에 권장되는 기믹 조합 반환

    규칙:
    1. 튜토리얼/연습 단계의 기믹이 있으면 그것만 사용
    2. 통합 단계라면 이전 기믹과 조합
    3. 숙달 단계의 기믹들은 자유롭게 조합
    """
    phase_config = get_phase_config(level_number)
    unlocked = get_unlocked_gimmicks(level_number)

    if available_pool:
        unlocked = [g for g in unlocked if g in available_pool]

    if not unlocked:
        return []

    # 튜토리얼/연습 중인 기믹 찾기
    tutorial_or_practice = []
    integration = []
    mastery = []

    for gimmick in unlocked:
        intro_phase = get_gimmick_intro_phase(level_number, gimmick)
        if intro_phase in (GimmickIntroPhase.TUTORIAL, GimmickIntroPhase.PRACTICE):
            tutorial_or_practice.append(gimmick)
        elif intro_phase == GimmickIntroPhase.INTEGRATION:
            integration.append(gimmick)
        else:
            mastery.append(gimmick)

    # 우선순위: 튜토리얼/연습 > 통합 > 숙달
    if tutorial_or_practice:
        # 튜토리얼/연습 중인 기믹만 반환 (집중 학습)
        return tutorial_or_practice[:1]  # 하나만

    if integration:
        # 통합 단계: 최근 기믹 + 이전 숙달 기믹 1개
        result = integration[:1]
        if mastery and phase_config.max_gimmick_types > 1:
            result.append(mastery[0])
        return result[:phase_config.max_gimmick_types]

    # 숙달 단계만 있으면 자유 조합
    return mastery[:phase_config.max_gimmick_types]


def calculate_level_difficulty(
    level_number: int,
    use_sawtooth: bool = True
) -> float:
    """
    레벨 번호에 따른 목표 난이도 계산

    Args:
        level_number: 레벨 번호 (1-based)
        use_sawtooth: 톱니바퀴 패턴 적용 여부

    Returns:
        0.0 ~ 1.0 사이의 난이도 값
    """
    phase_config = get_phase_config(level_number)

    # 단계 내 위치 계산
    level_in_phase = level_number - phase_config.level_range[0]

    # 기본 난이도 계산
    base = phase_config.base_difficulty + (level_in_phase * phase_config.difficulty_increment)

    if use_sawtooth:
        # 톱니바퀴 패턴 적용 (10레벨 단위)
        position_in_10 = (level_number - 1) % 10
        sawtooth_modifier = SAWTOOTH_PATTERN_10[position_in_10]

        # 톱니바퀴는 ±0.1 범위로 조절
        difficulty = base + (sawtooth_modifier - 0.5) * 0.2
    else:
        difficulty = base

    # 범위 제한
    return max(0.05, min(0.95, difficulty))


def calculate_tile_types_count(level_number: int) -> int:
    """레벨에 적합한 타일 종류 수 계산"""
    phase_config = get_phase_config(level_number)

    # 단계 내 진행도 (0.0 ~ 1.0)
    level_in_phase = level_number - phase_config.level_range[0]
    phase_length = phase_config.level_range[1] - phase_config.level_range[0] + 1
    progress = min(1.0, level_in_phase / phase_length)

    # 선형 보간
    type_range = phase_config.max_tile_types - phase_config.min_tile_types
    return phase_config.min_tile_types + int(type_range * progress)


def calculate_layer_count(level_number: int, difficulty: float) -> int:
    """레벨과 난이도에 적합한 레이어 수 계산"""
    phase_config = get_phase_config(level_number)

    # 난이도에 따른 레이어 수 조절
    layer_range = phase_config.max_layers - phase_config.min_layers

    # 난이도가 높을수록 더 많은 레이어
    difficulty_factor = min(1.0, difficulty / 0.8)

    return phase_config.min_layers + int(layer_range * difficulty_factor)


def get_complete_level_config(
    level_number: int,
    available_gimmicks: Optional[List[str]] = None,
    use_sawtooth: bool = True
) -> Dict[str, Any]:
    """
    레벨 번호에 대한 완전한 생성 설정 반환

    Returns:
        {
            "level_number": 25,
            "phase": "basic",
            "difficulty": 0.28,
            "tile_types_count": 4,
            "layer_count": 3,
            "gimmicks": ["chain"],
            "gimmick_intro_phase": "integration",
            "is_tutorial_level": False,
            "is_boss_level": False,
            "tutorial_gimmick": None,
        }
    """
    phase = get_phase_for_level(level_number)
    difficulty = calculate_level_difficulty(level_number, use_sawtooth)
    tile_types = calculate_tile_types_count(level_number)
    layers = calculate_layer_count(level_number, difficulty)

    tutorial_gimmick = get_tutorial_gimmick_at_level(level_number)
    is_tutorial = tutorial_gimmick is not None
    is_boss = (level_number % 10 == 0)

    # 기믹 선택
    if is_tutorial and tutorial_gimmick:
        gimmicks = [tutorial_gimmick]
        intro_phase = GimmickIntroPhase.TUTORIAL
    else:
        gimmicks = get_recommended_gimmicks_for_level(level_number, available_gimmicks)
        intro_phase = GimmickIntroPhase.MASTERY
        if gimmicks:
            intro_phase = get_gimmick_intro_phase(level_number, gimmicks[0])

    return {
        "level_number": level_number,
        "phase": phase.value,
        "difficulty": round(difficulty, 3),
        "tile_types_count": tile_types,
        "layer_count": layers,
        "gimmicks": gimmicks,
        "gimmick_intro_phase": intro_phase.value,
        "is_tutorial_level": is_tutorial,
        "is_boss_level": is_boss,
        "tutorial_gimmick": tutorial_gimmick,
    }


def generate_level_progression(
    start_level: int,
    count: int,
    available_gimmicks: Optional[List[str]] = None,
    use_sawtooth: bool = True
) -> List[Dict[str, Any]]:
    """
    연속된 레벨들의 진행 계획 생성

    Args:
        start_level: 시작 레벨 번호
        count: 생성할 레벨 수
        available_gimmicks: 사용 가능한 기믹 풀
        use_sawtooth: 톱니바퀴 패턴 적용 여부

    Returns:
        레벨별 설정 리스트
    """
    return [
        get_complete_level_config(
            start_level + i,
            available_gimmicks,
            use_sawtooth
        )
        for i in range(count)
    ]


# =========================================================
# 기본 언락 레벨 딕셔너리 (기존 시스템 호환)
# =========================================================

DEFAULT_PROFESSIONAL_UNLOCK_LEVELS: Dict[str, int] = {
    config.gimmick: config.unlock_level
    for config in PROFESSIONAL_GIMMICK_UNLOCK.values()
}

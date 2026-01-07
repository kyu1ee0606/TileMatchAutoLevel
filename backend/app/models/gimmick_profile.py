"""
난이도 기반 기믹 자동 선택 프로파일 시스템

등급별로 적절한 기믹 조합과 밀도를 정의합니다.
레벨 디자이너가 기믹 풀만 선택하면, 각 레벨의 난이도에 따라
자동으로 적절한 기믹이 배분됩니다.
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class GimmickType(str, Enum):
    """사용 가능한 기믹 타입"""
    CHAIN = "chain"
    FROG = "frog"
    ICE = "ice"
    LINK = "link"
    GRASS = "grass"
    BOMB = "bomb"
    CURTAIN = "curtain"
    TELEPORT = "teleport"
    CRATE = "crate"


@dataclass
class GimmickProfile:
    """난이도 등급별 기믹 프로파일"""
    grade: str
    difficulty_range: tuple  # (min, max) 0.0-1.0
    recommended_gimmicks: List[str]  # 이 등급에 적합한 기믹들
    max_gimmick_types: int  # 최대 기믹 종류 수
    gimmick_density: float  # 기믹 밀도 (0.0-1.0)
    min_gimmick_count: int  # 최소 기믹 개수
    max_gimmick_count: int  # 최대 기믹 개수


# 등급별 기믹 프로파일 정의
GIMMICK_PROFILES: Dict[str, GimmickProfile] = {
    "S": GimmickProfile(
        grade="S",
        difficulty_range=(0.0, 0.2),
        recommended_gimmicks=[],  # S등급은 기믹 없음 권장
        max_gimmick_types=0,
        gimmick_density=0.0,
        min_gimmick_count=0,
        max_gimmick_count=0,
    ),
    "A": GimmickProfile(
        grade="A",
        difficulty_range=(0.2, 0.4),
        recommended_gimmicks=["chain"],  # 가장 기본적인 기믹만
        max_gimmick_types=1,
        gimmick_density=0.05,
        min_gimmick_count=0,
        max_gimmick_count=3,
    ),
    "B": GimmickProfile(
        grade="B",
        difficulty_range=(0.4, 0.6),
        recommended_gimmicks=["chain", "frog"],  # 기본 + 전략적 기믹
        max_gimmick_types=2,
        gimmick_density=0.1,
        min_gimmick_count=2,
        max_gimmick_count=6,
    ),
    "C": GimmickProfile(
        grade="C",
        difficulty_range=(0.6, 0.8),
        recommended_gimmicks=["chain", "frog", "ice"],  # 다양한 기믹
        max_gimmick_types=3,
        gimmick_density=0.15,
        min_gimmick_count=4,
        max_gimmick_count=10,
    ),
    "D": GimmickProfile(
        grade="D",
        difficulty_range=(0.8, 1.0),
        recommended_gimmicks=["chain", "frog", "ice", "bomb", "curtain"],  # 모든 기믹
        max_gimmick_types=5,
        gimmick_density=0.2,
        min_gimmick_count=6,
        max_gimmick_count=15,
    ),
}

# 기믹 난이도 가중치 (높을수록 어려운 기믹)
GIMMICK_DIFFICULTY_WEIGHTS: Dict[str, float] = {
    "chain": 1.0,      # 기본 - 인접 타일 클리어로 해제
    "frog": 1.2,       # 중간 - 위치 이동 필요
    "ice": 1.3,        # 중간 - 2번 클리어 필요
    "grass": 1.1,      # 기본 - 인접 클리어로 해제
    "link": 1.4,       # 어려움 - 연결된 타일 동시 클리어
    "bomb": 1.5,       # 어려움 - 시간/이동 제한
    "curtain": 1.3,    # 중간 - 가려진 타일
    "teleport": 1.2,   # 중간 - 위치 변경
    "crate": 1.4,      # 어려움 - 특수 조건
}


def get_grade_from_difficulty(difficulty: float) -> str:
    """난이도 값(0.0-1.0)에서 등급 반환"""
    if difficulty < 0.2:
        return "S"
    elif difficulty < 0.4:
        return "A"
    elif difficulty < 0.6:
        return "B"
    elif difficulty < 0.8:
        return "C"
    else:
        return "D"


def get_profile_for_difficulty(difficulty: float) -> GimmickProfile:
    """난이도 값에 맞는 기믹 프로파일 반환"""
    grade = get_grade_from_difficulty(difficulty)
    return GIMMICK_PROFILES[grade]


def select_gimmicks_for_difficulty(
    target_difficulty: float,
    available_gimmicks: List[str],
    force_gimmicks: Optional[List[str]] = None,
) -> List[str]:
    """
    난이도에 맞는 기믹 자동 선택

    Args:
        target_difficulty: 목표 난이도 (0.0-1.0)
        available_gimmicks: 사용 가능한 기믹 풀 (사용자가 선택한)
        force_gimmicks: 강제로 포함할 기믹 (수동 오버라이드)

    Returns:
        선택된 기믹 리스트
    """
    if force_gimmicks is not None:
        return force_gimmicks

    profile = get_profile_for_difficulty(target_difficulty)

    # S등급이거나 사용 가능한 기믹이 없으면 빈 리스트
    if profile.max_gimmick_types == 0 or not available_gimmicks:
        return []

    # 프로파일의 권장 기믹 중 사용 가능한 것만 필터링
    recommended = [g for g in profile.recommended_gimmicks if g in available_gimmicks]

    # 권장 기믹이 없으면 사용 가능한 기믹에서 난이도에 맞게 선택
    if not recommended:
        # 난이도 가중치로 정렬하여 적절한 개수 선택
        sorted_gimmicks = sorted(
            available_gimmicks,
            key=lambda g: GIMMICK_DIFFICULTY_WEIGHTS.get(g, 1.0)
        )
        # 프로파일의 max_gimmick_types 만큼만 선택
        recommended = sorted_gimmicks[:profile.max_gimmick_types]

    # max_gimmick_types 제한 적용
    return recommended[:profile.max_gimmick_types]


def get_gimmick_count_range(
    target_difficulty: float,
    available_gimmicks: List[str],
) -> tuple:
    """
    난이도에 맞는 기믹 개수 범위 반환

    Returns:
        (min_count, max_count) 튜플
    """
    profile = get_profile_for_difficulty(target_difficulty)

    if not available_gimmicks:
        return (0, 0)

    return (profile.min_gimmick_count, profile.max_gimmick_count)


def calculate_gimmick_distribution(
    difficulty_profile: List[float],
    available_gimmicks: List[str],
    per_level_overrides: Optional[Dict[int, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """
    레벨 세트 전체에 대한 기믹 분배 계산

    Args:
        difficulty_profile: 레벨별 목표 난이도 리스트 [0.2, 0.3, 0.5, ...]
        available_gimmicks: 전체 세트에서 사용 가능한 기믹 풀
        per_level_overrides: 레벨별 기믹 오버라이드 {level_index: [gimmicks]}

    Returns:
        레벨별 기믹 설정 리스트
        [{
            "level_index": 0,
            "target_difficulty": 0.2,
            "grade": "A",
            "gimmicks": ["chain"],
            "gimmick_count_range": (0, 3),
            "is_override": False
        }, ...]
    """
    per_level_overrides = per_level_overrides or {}
    result = []

    for i, difficulty in enumerate(difficulty_profile):
        is_override = i in per_level_overrides

        if is_override:
            gimmicks = per_level_overrides[i]
        else:
            gimmicks = select_gimmicks_for_difficulty(difficulty, available_gimmicks)

        grade = get_grade_from_difficulty(difficulty)
        count_range = get_gimmick_count_range(difficulty, gimmicks)

        result.append({
            "level_index": i,
            "target_difficulty": difficulty,
            "grade": grade,
            "gimmicks": gimmicks,
            "gimmick_count_range": count_range,
            "is_override": is_override,
        })

    return result


# 편의 함수: 프로파일 정보 조회
def get_all_profiles_info() -> List[Dict[str, Any]]:
    """모든 프로파일 정보를 딕셔너리 리스트로 반환"""
    return [
        {
            "grade": profile.grade,
            "difficulty_range": profile.difficulty_range,
            "recommended_gimmicks": profile.recommended_gimmicks,
            "max_gimmick_types": profile.max_gimmick_types,
            "gimmick_density": profile.gimmick_density,
        }
        for profile in GIMMICK_PROFILES.values()
    ]

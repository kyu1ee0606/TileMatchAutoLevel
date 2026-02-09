"""
난이도 기반 기믹 자동 선택 프로파일 시스템

등급별로 적절한 기믹 조합과 밀도를 정의합니다.
레벨 디자이너가 기믹 풀만 선택하면, 각 레벨의 난이도에 따라
자동으로 적절한 기믹이 배분됩니다.
"""
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class GimmickType(str, Enum):
    """사용 가능한 기믹 타입"""
    # 목표 기믹
    CRAFT = "craft"        # 공예 - 방향별 수집 목표
    STACK = "stack"        # 스택 - 겹쳐진 타일 수집 목표
    # 장애물 기믹
    CHAIN = "chain"        # 사슬 - 인접 타일 클리어로 해제
    FROG = "frog"          # 개구리 - 매 턴 이동
    ICE = "ice"            # 얼음 - 인접 클리어로 녹임
    LINK = "link"          # 연결 - 연결된 타일 동시 선택
    GRASS = "grass"        # 풀 - 인접 클리어로 제거
    BOMB = "bomb"          # 폭탄 - 카운트다운 후 폭발
    CURTAIN = "curtain"    # 커튼 - 가려진 타일
    TELEPORT = "teleport"  # 텔레포터 - 위치 변경
    UNKNOWN = "unknown"    # 상자 - 상위 타일에 가려지면 타일 종류가 숨겨짐
    KEY = "key"            # 버퍼잠금 - unlockTile 필드로 설정
    TIME_ATTACK = "time_attack"  # 타임어택 - timea 필드로 설정


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
# 난이도 가중치는 GIMMICK_DIFFICULTY_WEIGHTS 참조 (Single Source of Truth)
#
# 프로페셔널 게임 참고 (Tile Buster, Tile Explorer 등):
# - 레벨당 기믹 종류는 최대 3개가 적정 (플레이어 인지 부하 고려)
# - 기믹 밀도보다 타일 종류와 무브 제한이 더 큰 난이도 영향
# - 튜토리얼 레벨: 1-3개 메커닉
# - 기믹은 "3회 이하 움직임으로 해제"가 기본 설계
GIMMICK_PROFILES: Dict[str, GimmickProfile] = {
    # S등급: 튜토리얼 단계 (레벨 1-225)
    # - 레벨 1-20: 기믹 없음 (순수 매칭 학습)
    # - 레벨 21+: 기믹 순차 언락 시작
    # - 언락된 기믹은 반드시 사용되어야 학습 가능
    "S": GimmickProfile(
        grade="S",
        difficulty_range=(0.0, 0.2),
        recommended_gimmicks=["chain", "grass"],  # 기본 기믹 (레벨 21, 61에서 언락)
        max_gimmick_types=2,  # 언락된 기믹 사용 허용 (기존 0 → 2)
        gimmick_density=0.05,  # 낮은 밀도 (기존 0.0 → 0.05)
        min_gimmick_count=0,   # 레벨 1-20은 기믹 없음
        max_gimmick_count=3,   # 최대 3개 (기존 0 → 3)
    ),
    "A": GimmickProfile(
        grade="A",
        difficulty_range=(0.2, 0.4),
        recommended_gimmicks=["chain", "grass", "ice", "frog"],  # 기본 + 중간 기믹
        max_gimmick_types=2,  # 기존 1 → 2 (다양한 기믹 학습)
        gimmick_density=0.08,  # 기존 0.05 → 0.08
        min_gimmick_count=0,
        max_gimmick_count=5,  # 기존 4 → 5
    ),
    "B": GimmickProfile(
        grade="B",
        difficulty_range=(0.4, 0.6),
        recommended_gimmicks=["chain", "grass", "frog", "teleport", "unknown"],  # 기본 + 중간 난이도 기믹
        max_gimmick_types=2,
        gimmick_density=0.10,
        min_gimmick_count=2,
        max_gimmick_count=6,
    ),
    "C": GimmickProfile(
        grade="C",
        difficulty_range=(0.6, 0.8),
        recommended_gimmicks=["chain", "grass", "frog", "teleport", "ice", "unknown", "curtain"],  # 다양한 기믹 (link, bomb 제외 - 고난이도 전용)
        max_gimmick_types=3,  # 최대 3종류 유지 (프로페셔널 게임 기준)
        gimmick_density=0.15,
        min_gimmick_count=3,  # 기존 4 → 3 (과도한 기믹 방지)
        max_gimmick_count=8,  # 기존 10 → 8
    ),
    "D": GimmickProfile(
        grade="D",
        difficulty_range=(0.8, 1.0),
        recommended_gimmicks=["chain", "grass", "frog", "teleport", "ice", "unknown", "curtain", "link", "bomb"],  # 모든 기믹
        max_gimmick_types=3,  # 기존 5 → 3 (프로페셔널 게임 기준: 최대 3종류)
        gimmick_density=0.18,  # 기존 0.2 → 0.18
        min_gimmick_count=4,  # 기존 6 → 4
        max_gimmick_count=10,  # 기존 15 → 10 (과도한 기믹 방지)
    ),
}

# =========================================================
# 통합 기믹 난이도 가중치 (Single Source of Truth)
# =========================================================
# 모든 기믹의 난이도 가중치를 한 곳에서 관리
# analyzer.py, leveling_config.py 모두 이 값을 참조해야 함
#
# 가중치 범위: 1.0 ~ 1.5
# 1.0 = 기본 (단순한 조건부 클리어)
# 1.1 = 쉬움 (시각적 제한만)
# 1.2 = 중간-쉬움 (인접 클리어 등 단순 메커니즘)
# 1.3 = 중간-어려움 (다단계 또는 예측 필요)
# 1.4 = 어려움 (동시 조건 또는 시간 압박)
# 1.5 = 매우 어려움 (무작위성 또는 게임오버 위험)
# =========================================================

# 기믹 점수 계산 시 기본 배율 (analyzer.py에서 사용)
# 기믹 개수 × 개별 가중치 × GIMMICK_BASE_WEIGHT = 난이도 점수 기여분
GIMMICK_BASE_WEIGHT: float = 4.0

GIMMICK_DIFFICULTY_WEIGHTS: Dict[str, float] = {
    # 기본 기믹 (1.0 ~ 1.2)
    "chain": 1.2,      # 인접 타일 클리어로 해제, 단순하지만 배치에 따라 난이도 상승
    "grass": 1.2,      # 인접 클리어로 단계별 제거, 여러 번 필요할 수 있음
    "unknown": 1.1,    # 상위 타일 제거 전 타입 숨김, 시각적 제한만

    # 중간 기믹 (1.2 ~ 1.3)
    "ice": 1.3,        # 2단계 녹임 필요, 블로킹 상태에서 추가 선택 필요
    "curtain": 1.2,    # 열림/닫힘 토글, 기억력 테스트
    "teleport": 1.3,   # 3턴마다 타입 교환 (Sattolo), 예측 필요
    "craft": 1.2,      # 방향별 수집 목표
    "stack": 1.2,      # 겹쳐진 타일 수집 목표
    "key": 1.3,        # 버퍼 잠금, 덱 슬롯 제한

    # 어려운 기믹 (1.4 ~ 1.5)
    "link": 1.4,       # 연결된 타일 동시 선택 필수, 양쪽 접근 필요
    "time_attack": 1.4,  # 시간 제한, 봇 시뮬레이션 어려움
    "frog": 1.5,       # 매 턴 무작위 이동, 예측 불가능
    "bomb": 1.5,       # 카운트다운 후 폭발 (게임오버), 우선 처리 필수
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
    ensure_even_distribution: bool = True,
) -> List[str]:
    """
    난이도에 맞는 기믹 자동 선택

    Args:
        target_difficulty: 목표 난이도 (0.0-1.0)
        available_gimmicks: 사용 가능한 기믹 풀 (언락된 기믹들)
        force_gimmicks: 강제로 포함할 기믹 (수동 오버라이드)
        ensure_even_distribution: True면 언락된 모든 기믹이 골고루 선택될 수 있도록 함

    Returns:
        선택된 기믹 리스트
    """
    if force_gimmicks is not None:
        return force_gimmicks

    profile = get_profile_for_difficulty(target_difficulty)

    # S등급이거나 사용 가능한 기믹이 없으면 빈 리스트
    if profile.max_gimmick_types == 0 or not available_gimmicks:
        return []

    max_types = profile.max_gimmick_types
    available = list(available_gimmicks)

    # 프로파일의 권장 기믹 중 사용 가능한 것만 필터링
    recommended = [g for g in profile.recommended_gimmicks if g in available]
    # 권장되지 않지만 사용 가능한 기믹
    non_recommended = [g for g in available if g not in profile.recommended_gimmicks]

    # ensure_even_distribution 모드: 모든 언락된 기믹이 골고루 사용되도록
    # 전략: 전체 available에서 균등하게 선택하되, 첫 번째 슬롯만 권장에 약간 가중치
    if ensure_even_distribution and non_recommended:
        # 가중치 기반 선택: 권장 기믹 1.2배 가중치, 비권장 기믹 1.0배 가중치
        # 이렇게 하면 권장 기믹이 약간 더 자주 나오지만, 비권장도 충분히 등장
        weights = []
        for g in available:
            if g in recommended:
                weights.append(1.2)  # 권장 기믹은 1.2배 가중치
            else:
                weights.append(1.0)  # 비권장 기믹은 1.0배 가중치

        # 가중치 기반 랜덤 선택
        result = []
        available_copy = list(available)
        weights_copy = list(weights)

        while len(result) < max_types and available_copy:
            # 가중치 합 계산
            total_weight = sum(weights_copy)
            # 가중치 기반 랜덤 선택
            r = random.random() * total_weight
            cumulative = 0
            selected_idx = 0
            for i, w in enumerate(weights_copy):
                cumulative += w
                if r <= cumulative:
                    selected_idx = i
                    break

            # 선택된 기믹 추가 및 제거
            result.append(available_copy[selected_idx])
            available_copy.pop(selected_idx)
            weights_copy.pop(selected_idx)

        return result
    else:
        # 기존 로직: 권장 기믹만 사용
        selection_pool = recommended if recommended else list(available)

        if len(selection_pool) <= max_types:
            return selection_pool

        return random.sample(selection_pool, max_types)


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

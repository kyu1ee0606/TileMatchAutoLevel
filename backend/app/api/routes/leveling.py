"""Leveling configuration API routes."""
from fastapi import APIRouter
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from ...models.leveling_config import (
    get_complete_level_config,
    generate_level_progression,
    get_unlocked_gimmicks,
    get_phase_for_level,
    calculate_level_difficulty,
    PROFESSIONAL_GIMMICK_UNLOCK,
    PHASE_CONFIGS,
    SAWTOOTH_PATTERN_10,
    DEFAULT_PROFESSIONAL_UNLOCK_LEVELS,
)


router = APIRouter(prefix="/api/leveling", tags=["leveling"])


class LevelConfigRequest(BaseModel):
    """단일 레벨 설정 요청"""
    level_number: int = Field(..., ge=1, description="레벨 번호 (1-based)")
    available_gimmicks: Optional[List[str]] = Field(
        default=None,
        description="사용 가능한 기믹 풀 (None = 모든 기믹)"
    )
    use_sawtooth: bool = Field(
        default=True,
        description="톱니바퀴 난이도 패턴 적용"
    )


class LevelProgressionRequest(BaseModel):
    """레벨 진행 계획 요청"""
    start_level: int = Field(default=1, ge=1, description="시작 레벨")
    count: int = Field(default=10, ge=1, le=200, description="생성할 레벨 수")
    available_gimmicks: Optional[List[str]] = Field(
        default=None,
        description="사용 가능한 기믹 풀"
    )
    use_sawtooth: bool = Field(
        default=True,
        description="톱니바퀴 패턴 적용"
    )


class GimmickUnlockInfo(BaseModel):
    """기믹 언락 정보"""
    gimmick: str
    unlock_level: int
    practice_levels: int
    integration_start: int
    difficulty_weight: float
    description: str


@router.get("/config")
async def get_leveling_config() -> Dict[str, Any]:
    """
    프로 레벨링 시스템 전체 설정 반환

    Returns:
        - gimmick_unlocks: 기믹별 언락 정보
        - phase_configs: 단계별 설정
        - sawtooth_pattern: 톱니바퀴 난이도 패턴
        - unlock_levels: 간단한 언락 레벨 맵
    """
    return {
        "gimmick_unlocks": {
            name: {
                "gimmick": config.gimmick,
                "unlock_level": config.unlock_level,
                "practice_levels": config.practice_levels,
                "integration_start": config.integration_start,
                "difficulty_weight": config.difficulty_weight,
                "description": config.description,
            }
            for name, config in PROFESSIONAL_GIMMICK_UNLOCK.items()
        },
        "phase_configs": {
            phase.value: {
                "phase": config.phase.value,
                "level_range": config.level_range,
                "min_tile_types": config.min_tile_types,
                "max_tile_types": config.max_tile_types,
                "min_layers": config.min_layers,
                "max_layers": config.max_layers,
                "max_gimmick_types": config.max_gimmick_types,
                "base_difficulty": config.base_difficulty,
                "difficulty_increment": config.difficulty_increment,
            }
            for phase, config in PHASE_CONFIGS.items()
        },
        "sawtooth_pattern": SAWTOOTH_PATTERN_10,
        "unlock_levels": DEFAULT_PROFESSIONAL_UNLOCK_LEVELS,
    }


@router.post("/level-config")
async def get_single_level_config(request: LevelConfigRequest) -> Dict[str, Any]:
    """
    단일 레벨의 권장 설정 반환

    Returns:
        - level_number: 레벨 번호
        - phase: 현재 단계
        - difficulty: 목표 난이도
        - tile_types_count: 권장 타일 종류 수
        - layer_count: 권장 레이어 수
        - gimmicks: 권장 기믹
        - is_tutorial_level: 튜토리얼 레벨 여부
        - is_boss_level: 보스 레벨 여부
        - tutorial_gimmick: 튜토리얼 기믹 (있는 경우)
    """
    return get_complete_level_config(
        request.level_number,
        request.available_gimmicks,
        request.use_sawtooth
    )


@router.post("/progression")
async def get_level_progression(request: LevelProgressionRequest) -> List[Dict[str, Any]]:
    """
    연속 레벨들의 진행 계획 반환

    여러 레벨을 한 번에 생성할 때 사용합니다.
    각 레벨의 난이도, 기믹, 타일 종류 등을 자동으로 계산합니다.

    Returns:
        레벨별 설정 리스트
    """
    return generate_level_progression(
        request.start_level,
        request.count,
        request.available_gimmicks,
        request.use_sawtooth
    )


@router.get("/unlocked-gimmicks/{level_number}")
async def get_unlocked_gimmicks_at_level(level_number: int) -> Dict[str, Any]:
    """
    특정 레벨에서 사용 가능한 기믹 목록 반환

    Args:
        level_number: 레벨 번호

    Returns:
        - level_number: 레벨 번호
        - unlocked_gimmicks: 언락된 기믹 목록
        - total_available: 사용 가능한 총 기믹 수
        - phase: 현재 단계
    """
    unlocked = get_unlocked_gimmicks(level_number)
    phase = get_phase_for_level(level_number)

    return {
        "level_number": level_number,
        "unlocked_gimmicks": unlocked,
        "total_available": len(unlocked),
        "phase": phase.value,
    }


@router.get("/difficulty-curve")
async def get_difficulty_curve(
    start_level: int = 1,
    count: int = 50,
    use_sawtooth: bool = True
) -> Dict[str, Any]:
    """
    난이도 곡선 데이터 반환 (차트 그리기용)

    Args:
        start_level: 시작 레벨
        count: 레벨 수
        use_sawtooth: 톱니바퀴 패턴 적용

    Returns:
        - levels: 레벨 번호 배열
        - difficulties: 난이도 배열
        - phases: 단계 배열
        - boss_levels: 보스 레벨 인덱스 배열
        - tutorial_levels: 튜토리얼 레벨 정보
    """
    levels = []
    difficulties = []
    phases = []
    boss_levels = []
    tutorial_levels = []

    for i in range(count):
        level_num = start_level + i
        difficulty = calculate_level_difficulty(level_num, use_sawtooth)
        phase = get_phase_for_level(level_num)

        levels.append(level_num)
        difficulties.append(round(difficulty, 3))
        phases.append(phase.value)

        if level_num % 10 == 0:
            boss_levels.append(level_num)

        # 튜토리얼 레벨 체크
        for config in PROFESSIONAL_GIMMICK_UNLOCK.values():
            if config.unlock_level == level_num:
                tutorial_levels.append({
                    "level": level_num,
                    "gimmick": config.gimmick,
                    "description": config.description,
                })

    return {
        "levels": levels,
        "difficulties": difficulties,
        "phases": phases,
        "boss_levels": boss_levels,
        "tutorial_levels": tutorial_levels,
    }

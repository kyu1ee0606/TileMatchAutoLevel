"""
프로급 타일 매칭 게임 레벨링 시스템 설정

Tile Buster, Tile Explorer, Triple Match 3D 등 유명 타일 게임의
레벨링 패턴을 분석하여 구현한 설정입니다.

[연구 근거 기반 설계]
- Triple Tile 연구: 초반 레벨은 "거의 너무 쉬움"으로 성취감 제공
- Tile Master 3D: 100레벨 단위 마일스톤 보상 시스템
- Room 8 Studio: 레벨 175+ 히든 타일 본격 도입
- 업계 표준: 3-레이어 시스템 (가시/부분가시/히든)
- 타일 수 점진적 증가: 초반 20-40개 → 후반 80-120개

주요 특징:
1. 점진적 기믹 도입 (Tutorial → Practice → Integration)
2. 톱니바퀴 난이도 패턴 (10레벨 단위 순환)
3. 레이어/타일 수 점진적 증가 (연구 데이터 기반)
4. 100레벨 단위 마일스톤 보스 시스템
5. 로그 난이도 곡선 (1000레벨 이후 완만한 증가)
"""
import math
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
# 프로급 기믹 언락 스케줄 (v3 - 시장 조사 기반)
# =========================================================
# [시장 조사 기반 개선]
# - Tile Busters: 레벨 5-10에서 첫 장애물 등장
# - Room 8 Studio: "50레벨 동안 메카닉 반복 금지"
# - Room 8 Studio: 히든 타일(unknown)은 레벨 175+ 본격 도입
# - 업계 공통: 장애물은 3무브 이하로 해제 가능해야 함
# - 튜토리얼 원칙: 1-3개 메카닉만 사용
#
# 개선된 스케줄 (~20레벨 간격, 레벨 6부터 시작):
# - Level 1-5: 순수 매칭 학습 (기믹 없음)
# - Level 6: chain 언락 (Tile Busters 참고)
# - Level 25: ice 언락
# - Level 45: grass 언락
# - Level 65: frog 언락
# - Level 85: bomb 언락
# - Level 105: curtain 언락
# - Level 125: teleport 언락
# - Level 145: link 언락
# - Level 175: unknown 언락 (히든 타일 - Room 8 Studio 연구)
# - Level 195: craft 언락
# - Level 215: stack 언락
# - Level 216+: 모든 기믹 언락 완료
# =========================================================

PROFESSIONAL_GIMMICK_UNLOCK: Dict[str, GimmickUnlockConfig] = {
    "chain": GimmickUnlockConfig(
        gimmick="chain",
        unlock_level=6,  # 첫 번째 기믹 (Tile Busters: 5-10에서 첫 장애물)
        practice_levels=18,  # 6-24: 연습
        integration_start=25,
        difficulty_weight=1.0,
        description="체인 - 가장 기본적인 기믹, 인접 타일로 해제"
    ),
    "ice": GimmickUnlockConfig(
        gimmick="ice",
        unlock_level=25,
        practice_levels=19,  # 25-44: 연습
        integration_start=45,
        difficulty_weight=1.1,
        description="얼음 - 인접 타일 클리어로 녹임"
    ),
    "grass": GimmickUnlockConfig(
        gimmick="grass",
        unlock_level=45,
        practice_levels=19,  # 45-64: 연습
        integration_start=65,
        difficulty_weight=1.1,
        description="풀 - 인접 타일 클리어로 제거"
    ),
    "frog": GimmickUnlockConfig(
        gimmick="frog",
        unlock_level=65,
        practice_levels=19,  # 65-84: 연습
        integration_start=85,
        difficulty_weight=1.2,
        description="개구리 - 매 턴 이동, 전략적 배치 필요"
    ),
    "bomb": GimmickUnlockConfig(
        gimmick="bomb",
        unlock_level=85,
        practice_levels=19,  # 85-104: 연습
        integration_start=105,
        difficulty_weight=1.3,
        description="폭탄 - 카운트다운 후 폭발, 시간 압박"
    ),
    "curtain": GimmickUnlockConfig(
        gimmick="curtain",
        unlock_level=105,
        practice_levels=19,  # 105-124: 연습
        integration_start=125,
        difficulty_weight=1.2,
        description="커튼 - 가려진 타일, 기억력 테스트"
    ),
    "teleport": GimmickUnlockConfig(
        gimmick="teleport",
        unlock_level=125,
        practice_levels=19,  # 125-144: 연습
        integration_start=145,
        difficulty_weight=1.2,
        description="텔레포트 - 타일 위치 변경"
    ),
    "link": GimmickUnlockConfig(
        gimmick="link",
        unlock_level=145,
        practice_levels=29,  # 145-174: 연습
        integration_start=175,
        difficulty_weight=1.3,
        description="링크 - 연결된 타일 동시 선택"
    ),
    # [Room 8 Studio 연구] 히든 타일은 레벨 175+ 본격 도입
    "unknown": GimmickUnlockConfig(
        gimmick="unknown",
        unlock_level=175,
        practice_levels=19,  # 175-194: 연습
        integration_start=195,
        difficulty_weight=1.4,
        description="미스터리 - 상위 타일 제거 전까지 숨겨짐 (레벨 175+)"
    ),
    "craft": GimmickUnlockConfig(
        gimmick="craft",
        unlock_level=195,
        practice_levels=19,  # 195-214: 연습
        integration_start=215,
        difficulty_weight=1.4,
        description="크래프트 목표 - 특정 방향으로 타일 수집"
    ),
    "stack": GimmickUnlockConfig(
        gimmick="stack",
        unlock_level=215,
        practice_levels=19,  # 215+: 연습
        integration_start=235,
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
    # [연구 근거] 타일 수 점진적 증가 (Triple Tile: 초반 쉬움 → 후반 복잡)
    min_tiles: int = 20           # 최소 타일 수
    max_tiles: int = 40           # 최대 타일 수
    # [연구 근거] 100레벨 단위 마일스톤 (Tile Master 3D 연구)
    has_milestone: bool = False   # 100레벨 단위 보스 포함 여부


PHASE_CONFIGS: Dict[LevelPhase, PhaseConfig] = {
    # =========================================================
    # 1,500레벨 난이도 분포 (v2 - 업계 표준 반영)
    # =========================================================
    # [시장 조사 기반 개선]
    # - Triple Tile: 초반 20-25레벨을 30분 내 클리어 가능하게
    # - Tile Master 3D: 100레벨 단위 마일스톤 보상
    # - Room 8 Studio: 레벨 175+ 히든 타일 본격 도입
    # - 업계 표준: 타일 종류 4-8개 (3개는 레벨1 튜토리얼만)
    #
    # 권장 분포: S(15%) → A(25%) → B(35%) → C(20%) → D(5%)
    # 기믹 언락 (v2): 21, 41, 61... 221 (레벨 222부터 모든 기믹)
    #
    # S등급 (1-225, 15%): 입문/기초 - 난이도 0.02-0.18
    #   - 1-20: 기믹 없음 (순수 매칭, 거의 너무 쉬움)
    #   - 21-175: 기믹 순차 언락 (20레벨 간격)
    #   - 175+: 히든 타일(unknown) 언락
    # A등급 (226-600, 25%): 쉬움/익숙 - 난이도 0.18-0.38
    # B등급 (601-1125, 35%): 보통/주력 - 난이도 0.38-0.58 ★핵심 재미
    # C등급 (1126-1425, 20%): 어려움/도전 - 난이도 0.58-0.78
    # D등급 (1426-1500, 5%): 심화/고수 - 난이도 0.78-0.92
    # =========================================================

    # =========================================================
    # GBoost 221레벨 분석 + 상용게임(Tile Explorer, Triple Tile) 기반 개선
    # =========================================================
    # [GBoost 분석 결과]
    # - 레벨 1-30: 타일수 9-126(평균37), 레이어 1-9(평균4)
    # - 레벨 31-60: 타일수 18-99(평균58), 레이어 2-7(평균4.6)
    # - 레벨 61-100: 타일수 21-119(평균80), 레이어 2-6(평균4.7)
    # - 레벨 101-150: 타일수 58-120(평균86), 레이어 4-5(평균4.8)
    # - 레벨 151-200: 타일수 52-116(평균82), 레이어 5(고정)
    # - 레벨 201+: 타일수 60-103(평균81), 레이어 2-5(평균4.9)
    #
    # [상용 게임 연구 - Room 8 Studio]
    # - 튜토리얼: 1-3개 메카닉만 사용
    # - 50레벨 동안 메카닉 반복 금지
    # - 6종류 레벨 타입: Tutorial, Wow-effect, Fuu-effect, Procrastinating, Skill, Visualization
    #
    # [상용 게임 연구 - Triple Tile, Tile Explorer]
    # - 초반 레벨: "거의 너무 쉬움"으로 성취감 제공
    # - 레벨별 난이도와 타일 수 점진적 증가
    # - 7슬롯 독에서 7개 타일이 차면 실패 메카닉
    # =========================================================

    LevelPhase.TUTORIAL: PhaseConfig(
        phase=LevelPhase.TUTORIAL,
        level_range=(1, 225),  # S등급 15% (225개)
        min_tile_types=4,      # 최소 4종류 (GBoost 분석: 대부분 t0 랜덤 사용)
        max_tile_types=5,      # 최대 5종류 (초반 복잡도 제한)
        # [GBoost 분석] 레벨 1-30: 평균 4레이어, 최대 9레이어 → 점진적 증가
        min_layers=1,          # 레벨 1-10: 1-2 레이어
        max_layers=4,          # 레벨 21-225: 최대 4레이어 (GBoost 평균 기준)
        max_gimmick_types=2,   # 언락된 기믹 중 최대 2개 사용
        # [Triple Tile 연구] 초반 "거의 너무 쉬움"
        base_difficulty=0.02,
        difficulty_increment=0.00071,  # 0.02 + 224*0.00071 ≈ 0.18
        # [GBoost 분석] 레벨 1-30: 평균 37타일 → 점진적 증가
        min_tiles=9,           # 레벨 1-10: 9-18타일 (GBoost 최소)
        max_tiles=60,          # 레벨 200+: 최대 60타일
        has_milestone=True,    # 100, 200레벨 마일스톤 포함
    ),

    LevelPhase.BASIC: PhaseConfig(
        phase=LevelPhase.BASIC,
        level_range=(226, 600),  # A등급 25% (375개)
        min_tile_types=5,        # 5종류로 시작 (복잡도 증가)
        max_tile_types=6,        # 최대 6종류
        # [GBoost 분석] 레벨 61-100: 평균 4.7레이어 → 4-5레이어
        min_layers=3,
        max_layers=5,
        max_gimmick_types=3,   # 언락된 기믹 중 최대 3개 사용
        base_difficulty=0.18,
        difficulty_increment=0.00053,  # 0.18 + 374*0.00053 ≈ 0.38
        # [GBoost 분석] 레벨 61-100: 평균 80타일
        min_tiles=45,
        max_tiles=84,
        has_milestone=True,    # 300, 400, 500, 600레벨 마일스톤
    ),

    LevelPhase.INTERMEDIATE: PhaseConfig(
        phase=LevelPhase.INTERMEDIATE,
        level_range=(601, 1125),  # B등급 35% (525개) ★핵심 재미 구간
        min_tile_types=5,        # 5종류 유지 (복잡도 vs 플레이어빌리티 균형)
        max_tile_types=7,        # 최대 7종류 (7슬롯 독과 균형)
        # [GBoost 분석] 레벨 101-150: 평균 4.8레이어, 151-200: 5레이어 고정
        min_layers=4,
        max_layers=5,
        max_gimmick_types=4,   # 언락된 기믹 중 최대 4개 사용
        base_difficulty=0.38,
        difficulty_increment=0.00038,  # 0.38 + 524*0.00038 ≈ 0.58
        # [GBoost 분석] 레벨 101-150: 평균 86타일
        min_tiles=60,
        max_tiles=100,
        has_milestone=True,    # 700, 800, 900, 1000, 1100레벨 마일스톤
    ),

    LevelPhase.ADVANCED: PhaseConfig(
        phase=LevelPhase.ADVANCED,
        level_range=(1126, 1425),  # C등급 20% (300개)
        min_tile_types=6,         # 6종류 (난이도 상승)
        max_tile_types=8,         # 최대 8종류
        # [GBoost 분석] 후반 레이어 5 고정 → 5-6레이어
        min_layers=5,
        max_layers=6,
        max_gimmick_types=5,   # 언락된 기믹 중 최대 5개 사용
        base_difficulty=0.58,
        difficulty_increment=0.00067,  # 0.58 + 299*0.00067 ≈ 0.78
        # [GBoost 분석] 후반 레벨: 80-100타일 유지
        min_tiles=72,
        max_tiles=108,
        has_milestone=True,    # 1200, 1300, 1400레벨 마일스톤
    ),

    LevelPhase.EXPERT: PhaseConfig(
        phase=LevelPhase.EXPERT,
        level_range=(1426, 1500),  # D등급 5% (75개)
        min_tile_types=6,
        max_tile_types=8,         # 최대 8종류 (7슬롯 독보다 많음 = 어려움)
        # [업계 표준] 최대 6레이어 (과도한 복잡성 방지)
        min_layers=5,
        max_layers=6,
        max_gimmick_types=6,   # 모든 기믹 자유 조합 (최대 6개)
        base_difficulty=0.78,
        difficulty_increment=0.00187,  # 0.78 + 74*0.00187 ≈ 0.92
        # [고난이도] 타일 수 최대화
        min_tiles=84,
        max_tiles=120,
        has_milestone=True,    # 1500레벨 마일스톤
    ),

    LevelPhase.MASTER: PhaseConfig(
        phase=LevelPhase.MASTER,
        level_range=(1501, 9999),  # 엔드게임 (무한 확장)
        min_tile_types=6,
        max_tile_types=8,
        # [엔드게임] 6레이어 유지 (과도한 복잡성 방지)
        min_layers=5,
        max_layers=6,
        max_gimmick_types=6,   # 모든 기믹 자유 조합 (최대 6개)
        base_difficulty=0.92,  # 최고 난이도 유지
        difficulty_increment=0.0,  # 로그 곡선으로 0.96 수렴
        # [엔드게임] 타일 수 일정 유지
        min_tiles=96,
        max_tiles=120,
        has_milestone=True,
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
    available_pool: Optional[List[str]] = None,
    target_difficulty: Optional[float] = None
) -> List[str]:
    """
    해당 레벨에 권장되는 기믹 조합 반환

    10레벨 단위 언락 시스템 규칙:
    1. 레벨 1-10: 기믹 없음 (순수 매칭 학습)
    2. 언락 레벨 (11, 21, 31...): 새 기믹 튜토리얼 (해당 기믹만)
    3. 연습 기간 (언락+1 ~ 언락+9): 새 기믹 집중 연습
    4. 이후: 언락된 기믹 풀에서 난이도에 맞게 선택

    Args:
        level_number: 레벨 번호
        available_pool: 사용 가능한 기믹 풀 (None이면 언락된 모든 기믹)
        target_difficulty: 목표 난이도 (0-1, 높을수록 더 많은/어려운 기믹)

    Returns:
        권장 기믹 리스트
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

    # 튜토리얼/연습 기간: 해당 기믹에 집중
    if tutorial_or_practice:
        # 새 기믹 튜토리얼/연습 중이면 그 기믹만 사용
        result = tutorial_or_practice[:1]
        # 통합 기간 초반이면 이전 기믹 1개 추가 가능
        if integration and phase_config.max_gimmick_types > 1:
            result.append(integration[0])
        return result[:phase_config.max_gimmick_types]

    # 통합 기간: 최근 기믹 + 숙달 기믹 조합
    if integration:
        result = integration[:1]
        if mastery and phase_config.max_gimmick_types > 1:
            # 난이도에 따라 추가 기믹 수 결정
            difficulty = target_difficulty or calculate_level_difficulty(level_number)
            extra_count = min(
                len(mastery),
                phase_config.max_gimmick_types - 1,
                int(difficulty * 3)  # 난이도 0.33마다 1개 추가
            )
            result.extend(mastery[:extra_count])
        return result[:phase_config.max_gimmick_types]

    # 숙달 기간 (모든 기믹 언락 후): 난이도 기반 기믹 선택
    if mastery:
        difficulty = target_difficulty or calculate_level_difficulty(level_number)

        # 난이도에 따른 기믹 수 결정
        # 0.0-0.2: 1-2개, 0.2-0.4: 2-3개, 0.4-0.6: 3-4개, 0.6-0.8: 4-5개, 0.8+: 5-6개
        base_count = max(1, int(difficulty * 6) + 1)
        gimmick_count = min(base_count, phase_config.max_gimmick_types, len(mastery))

        # 난이도 가중치 기반 기믹 선택 (어려운 기믹은 높은 난이도에서)
        # 기믹을 difficulty_weight로 정렬
        sorted_gimmicks = sorted(
            mastery,
            key=lambda g: PROFESSIONAL_GIMMICK_UNLOCK.get(g, GimmickUnlockConfig(
                gimmick=g, unlock_level=0, practice_levels=0,
                integration_start=0, difficulty_weight=1.0, description=""
            )).difficulty_weight
        )

        if difficulty < 0.3:
            # 쉬운 난이도: 쉬운 기믹 위주
            return sorted_gimmicks[:gimmick_count]
        elif difficulty < 0.6:
            # 중간 난이도: 골고루
            mid_start = len(sorted_gimmicks) // 4
            return sorted_gimmicks[mid_start:mid_start + gimmick_count]
        else:
            # 높은 난이도: 어려운 기믹 포함
            return sorted_gimmicks[-gimmick_count:]

    return []


def calculate_level_difficulty(
    level_number: int,
    use_sawtooth: bool = True
) -> float:
    """
    레벨 번호에 따른 목표 난이도 계산

    1,500레벨 난이도 분포 (우상향 Progression Curve):
    - S등급 (1-225, 15%): 난이도 0.05-0.20 (입문/기초)
    - A등급 (226-600, 25%): 난이도 0.20-0.40 (쉬움/익숙)
    - B등급 (601-1125, 35%): 난이도 0.40-0.60 (보통/주력) ★핵심 재미 구간
    - C등급 (1126-1425, 20%): 난이도 0.60-0.80 (어려움/도전)
    - D등급 (1426-1500, 5%): 난이도 0.80-0.95 (심화/고수)
    - 마스터 (1501+): 난이도 0.95-0.98 (엔드게임)

    Args:
        level_number: 레벨 번호 (1-based)
        use_sawtooth: 톱니바퀴 패턴 적용 여부

    Returns:
        0.0 ~ 1.0 사이의 난이도 값
    """
    phase_config = get_phase_config(level_number)

    # MASTER (1501+): 로그 곡선으로 0.96에 수렴
    # [연구 근거] 후반 난이도 완화 (연구 데이터 기반 0.95 → 0.92 → 0.96 수렴)
    if phase_config.phase == LevelPhase.MASTER:
        start_difficulty = 0.92  # D등급 종료점 (연구 기반 조정)
        max_difficulty = 0.96    # 최대 난이도 (연구 기반 조정)
        max_increase = max_difficulty - start_difficulty  # 0.03

        # 로그 곡선: 레벨 5000에서 max_difficulty에 가까워짐
        reference_level = 3500
        level_offset = level_number - 1500
        log_progress = math.log(level_offset + 1) / math.log(reference_level + 1)
        base = start_difficulty + max_increase * min(1.0, log_progress)
    else:
        # 레벨 1-1500: PHASE_CONFIGS 기반 선형 보간
        level_in_phase = level_number - phase_config.level_range[0]
        base = phase_config.base_difficulty + (level_in_phase * phase_config.difficulty_increment)

    if use_sawtooth:
        # 톱니바퀴 패턴 적용 (10레벨 단위)
        position_in_10 = (level_number - 1) % 10
        sawtooth_modifier = SAWTOOTH_PATTERN_10[position_in_10]

        # 톱니바퀴 범위: 등급별로 조절
        # S/A등급: ±0.05 (변동폭 작게)
        # B등급: ±0.06
        # C/D등급: ±0.04 (고난이도는 안정적으로)
        if level_number <= 600:  # S/A등급
            sawtooth_range = 0.10
        elif level_number <= 1125:  # B등급
            sawtooth_range = 0.12
        else:  # C/D/Master
            sawtooth_range = 0.08
        difficulty = base + (sawtooth_modifier - 0.5) * sawtooth_range
    else:
        difficulty = base

    # 범위 제한
    return max(0.05, min(0.98, difficulty))


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
    """
    레벨과 난이도에 적합한 레이어 수 계산

    [연구 근거]
    - 업계 표준 3-레이어 시스템 (가시/부분가시/히든)
    - 초반: 1-2 레이어 (가시 중심)
    - 중반: 3-4 레이어 (히든 도입)
    - 후반: 4-6 레이어 (히든 비중 증가)
    """
    phase_config = get_phase_config(level_number)

    # 난이도에 따른 레이어 수 조절
    layer_range = phase_config.max_layers - phase_config.min_layers

    # 난이도가 높을수록 더 많은 레이어
    difficulty_factor = min(1.0, difficulty / 0.8)

    return phase_config.min_layers + int(layer_range * difficulty_factor)


def calculate_tile_count(level_number: int, difficulty: float) -> int:
    """
    레벨과 난이도에 적합한 타일 총 개수 계산

    [연구 근거]
    - Triple Tile: 초반 적은 타일로 성취감 제공
    - 타일 수 점진적 증가: 20-40개(초반) → 80-120개(후반)
    - 난이도가 높을수록 더 많은 타일
    """
    phase_config = get_phase_config(level_number)

    # 단계 내 진행도 (0.0 ~ 1.0)
    level_in_phase = level_number - phase_config.level_range[0]
    phase_length = phase_config.level_range[1] - phase_config.level_range[0] + 1
    progress = min(1.0, level_in_phase / phase_length)

    # 기본 타일 수 (진행도 기반)
    tile_range = phase_config.max_tiles - phase_config.min_tiles
    base_tiles = phase_config.min_tiles + int(tile_range * progress)

    # 난이도에 따른 추가 조정 (±10%)
    difficulty_adjustment = (difficulty - 0.5) * 0.1
    adjusted_tiles = int(base_tiles * (1 + difficulty_adjustment))

    # 3의 배수로 맞춤 (매칭 게임 특성)
    adjusted_tiles = (adjusted_tiles // 3) * 3

    return max(phase_config.min_tiles, min(phase_config.max_tiles, adjusted_tiles))


def is_milestone_level(level_number: int) -> bool:
    """
    100레벨 단위 마일스톤 보스 레벨인지 확인

    [연구 근거]
    - Tile Master 3D: 100레벨 단위 보상 시스템
    - 보상 체계: Level 100, 200, 300... 에서 특별 보상
    """
    return level_number % 100 == 0 and level_number > 0


def get_milestone_difficulty_boost(level_number: int) -> float:
    """
    마일스톤 레벨의 추가 난이도 보너스 반환

    [연구 근거]
    - 100레벨 단위 보스는 해당 구간 최고 난이도
    - 일반 보스(10레벨 단위)보다 높은 난이도
    """
    if is_milestone_level(level_number):
        return 0.08  # 마일스톤 보스: +8% 난이도
    elif level_number % 10 == 0:
        return 0.04  # 일반 보스(10레벨 단위): +4% 난이도
    return 0.0


def calculate_hidden_tile_ratio(level_number: int) -> float:
    """
    레벨별 히든 타일(가려진 타일) 비율 계산

    [연구 근거]
    - Room 8 Studio: 레벨 175+ 히든 타일 본격 도입
    - 업계 표준 3-레이어 시스템:
      * 가시(visible): 즉시 볼 수 있음
      * 부분가시(partial): 일부만 보임
      * 히든(hidden): 상위 타일 제거 후 보임

    Returns:
        0.0 ~ 0.6 사이의 히든 타일 비율
        - 레벨 1-90: 0% (히든 없음, unknown 미언락)
        - 레벨 91-175: 0-15% (unknown 언락, 점진적 도입)
        - 레벨 175-400: 15-30% (본격 도입)
        - 레벨 400-800: 30-45% (중급 히든)
        - 레벨 800+: 45-60% (고급 히든)
    """
    # unknown 기믹 언락 전에는 히든 타일 없음
    if level_number < 91:
        return 0.0

    # 레벨 91-175: 점진적 도입 (0% → 15%)
    if level_number < 175:
        progress = (level_number - 91) / (175 - 91)
        return 0.15 * progress

    # 레벨 175-400: 본격 도입 (15% → 30%)
    if level_number < 400:
        progress = (level_number - 175) / (400 - 175)
        return 0.15 + 0.15 * progress

    # 레벨 400-800: 중급 히든 (30% → 45%)
    if level_number < 800:
        progress = (level_number - 400) / (800 - 400)
        return 0.30 + 0.15 * progress

    # 레벨 800+: 고급 히든 (45% → 60%, 최대)
    if level_number < 1500:
        progress = (level_number - 800) / (1500 - 800)
        return 0.45 + 0.15 * progress

    return 0.60  # 최대 60%


def get_layer_blocking_target(level_number: int, total_tiles: int) -> int:
    """
    목표 레이어 블로킹(가려진 타일) 수 계산

    [연구 근거]
    - Room 8 Studio: 레벨 175+ 히든 타일 본격 도입
    - 히든 타일 비율 기반으로 블로킹 타일 수 결정

    Args:
        level_number: 레벨 번호
        total_tiles: 총 타일 수

    Returns:
        목표 블로킹 타일 수
    """
    hidden_ratio = calculate_hidden_tile_ratio(level_number)
    return int(total_tiles * hidden_ratio)


def get_complete_level_config(
    level_number: int,
    available_gimmicks: Optional[List[str]] = None,
    use_sawtooth: bool = True
) -> Dict[str, Any]:
    """
    레벨 번호에 대한 완전한 생성 설정 반환

    [연구 근거 반영]
    - Triple Tile: 초반 "거의 너무 쉬움" 적용
    - Tile Master 3D: 100레벨 마일스톤 보스 시스템
    - 업계 표준: 타일 수 점진적 증가

    Returns:
        {
            "level_number": 25,
            "phase": "basic",
            "difficulty": 0.28,
            "tile_types_count": 4,
            "layer_count": 3,
            "tile_count": 36,  # [신규] 목표 타일 수
            "gimmicks": ["chain"],
            "gimmick_intro_phase": "integration",
            "is_tutorial_level": False,
            "is_boss_level": False,
            "is_milestone_boss": False,  # [신규] 100레벨 마일스톤
            "tutorial_gimmick": None,
        }
    """
    phase = get_phase_for_level(level_number)

    # 기본 난이도 계산
    base_difficulty = calculate_level_difficulty(level_number, use_sawtooth)

    # [연구 근거] 마일스톤/보스 난이도 부스트 적용
    milestone_boost = get_milestone_difficulty_boost(level_number)
    difficulty = min(0.98, base_difficulty + milestone_boost)

    tile_types = calculate_tile_types_count(level_number)
    layers = calculate_layer_count(level_number, difficulty)

    # [연구 근거] 타일 수 계산 (Triple Tile 패턴)
    tile_count = calculate_tile_count(level_number, difficulty)

    tutorial_gimmick = get_tutorial_gimmick_at_level(level_number)
    is_tutorial = tutorial_gimmick is not None
    is_boss = (level_number % 10 == 0)
    is_milestone = is_milestone_level(level_number)

    # 기믹 선택
    if is_tutorial and tutorial_gimmick:
        gimmicks = [tutorial_gimmick]
        intro_phase = GimmickIntroPhase.TUTORIAL
    else:
        gimmicks = get_recommended_gimmicks_for_level(level_number, available_gimmicks)
        intro_phase = GimmickIntroPhase.MASTERY
        if gimmicks:
            intro_phase = get_gimmick_intro_phase(level_number, gimmicks[0])

    # [연구 근거] 히든 타일 비율 (Room 8 Studio: 레벨 175+ 본격 도입)
    hidden_ratio = calculate_hidden_tile_ratio(level_number)
    hidden_tile_target = get_layer_blocking_target(level_number, tile_count)

    return {
        "level_number": level_number,
        "phase": phase.value,
        "difficulty": round(difficulty, 3),
        "tile_types_count": tile_types,
        "layer_count": layers,
        "tile_count": tile_count,  # [연구 근거] 타일 수 점진적 증가
        "hidden_tile_ratio": round(hidden_ratio, 2),  # [연구 근거] 히든 비율
        "hidden_tile_target": hidden_tile_target,  # [연구 근거] 목표 히든 타일 수
        "gimmicks": gimmicks,
        "gimmick_intro_phase": intro_phase.value,
        "is_tutorial_level": is_tutorial,
        "is_boss_level": is_boss,
        "is_milestone_boss": is_milestone,  # [연구 근거] 100레벨 마일스톤
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

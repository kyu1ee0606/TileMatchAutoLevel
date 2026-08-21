"""Level generator engine with difficulty targeting."""
import copy
import logging
import random
import time
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass

from .bot_simulator import BotSimulator, TileDistributor
from .pattern_templates import get_pattern_positions, get_pattern_name, PATTERN_TEMPLATES, is_layered_pattern, get_layered_pattern_positions

logger = logging.getLogger(__name__)


# ============ [B] Layer Size Diversity Policy ============
# 층별 그리드 크기 다양화. 프로덕션 멀티레이어에서 모든 층이 홀짝 교대 크기로 고정돼
# 스택 실루엣이 단조로운 문제를 해소. 각 층 채움 모양을 랜덤 s×s(min 3)로 다양화하고
# 중앙 배치하되, 레이어 col/row(교대값)는 그대로 유지 → 게임(TileLayer.LayerSpawn은
# rowCount 교대값으로 그리드 생성, FindAllUpperTiles는 데이터 xCol 비교로 블로킹 계산)과 정합.
# MODE:
#   "single"    (기본) 전 층 동일 pattern_index, 크기만 층별 다양화
#   "per_layer" (예약) 층마다 다른 pattern_index — 추후 확장용, 현재 미사용
SIZE_DIVERSITY_MODE = "single"
SIZE_DIVERSITY_MIN_SIZE = 3


# ============ Tile Distribution Uniformity by Difficulty ============
# 난이도별 타일 분포 균등도 설정
# 높은 균등도 = 쉬운 레벨 (모든 타입 동일 수량)
# 낮은 균등도 = 어려운 레벨 (의도적 불균형 허용)
TILE_UNIFORMITY_BY_DIFFICULTY = {
    # (min_difficulty, max_difficulty): uniformity (0.0 ~ 1.0)
    (0.0, 0.2): 1.0,    # S등급: 완전 균등 - 가장 쉬움
    (0.2, 0.35): 0.95,  # A등급: 거의 균등
    (0.35, 0.5): 0.85,  # B등급: 약간 불균형 허용
    (0.5, 0.7): 0.75,   # C등급: 불균형 허용
    (0.7, 0.85): 0.65,  # D등급: 상당한 불균형
    (0.85, 1.0): 0.50,  # E등급: 의도적 불균형 - 가장 어려움
}


def get_tile_uniformity(target_difficulty: float) -> float:
    """
    난이도에 따른 타일 분포 균등도 반환.

    Args:
        target_difficulty: 목표 난이도 (0.0 ~ 1.0)

    Returns:
        균등도 (0.0 = 불균등 허용, 1.0 = 완전 균등)
    """
    for (min_diff, max_diff), uniformity in TILE_UNIFORMITY_BY_DIFFICULTY.items():
        if min_diff <= target_difficulty < max_diff:
            return uniformity
    return 0.5  # 기본값


# ============ GBoost-Style Level Range Gimmick Configuration ============
# 인게임 확정 기믹 언락 스케줄 (2026.02 최종 확정 - 13개 기믹)
# Gimmicks are progressively introduced to match the natural learning curve

def get_gboost_style_gimmicks(level_number: int) -> Dict[str, Any]:
    """
    Get recommended gimmick configuration based on level number.

    인게임 확정 기믹 언락 순서 (총 13개):
    - Stage   1-9:   No gimmicks (tutorial/learning phase)
    - Stage  10-19:  craft only (공예 - 첫 번째 기믹)
    - Stage  20-29:  +stack (스택) [간격: 10]
    - Stage  30-49:  +ice (얼음) [간격: 10]
    - Stage  50-79:  +link (연결) [간격: 20]
    - Stage  80-109: +chain (사슬) [간격: 30]
    - Stage 110-149: +key (버퍼잠금) [간격: 30] ★신규
    - Stage 150-189: +grass (풀) [간격: 40]
    - Stage 190-239: +unknown (상자) [간격: 40]
    - Stage 240-289: +curtain (커튼) [간격: 50]
    - Stage 290-339: +bomb (폭탄) [간격: 50]
    - Stage 340-389: +time_attack (타임어택) [간격: 50] ★신규
    - Stage 390-439: +frog (개구리) [간격: 50]
    - Stage 440+:    +teleport (텔레포터, 모든 기믹) [간격: 50]

    특수 기믹 설정:
    - key: unlockTile 필드로 버퍼 잠금 타일 수 설정
    - time_attack: timea 필드로 제한 시간(초) 설정

    Args:
        level_number: The level number (1-based)

    Returns:
        Dict with:
        - obstacle_types: List of allowed gimmick types
        - gimmick_intensity: Suggested intensity (0.0-1.5)
        - description: Human-readable description
    """
    if level_number < 10:
        return {
            "obstacle_types": [],
            "gimmick_intensity": 0.0,
            "description": "튜토리얼 - 기믹 없음"
        }
    elif level_number < 20:
        return {
            "obstacle_types": ["craft"],
            "gimmick_intensity": 0.2,
            "description": "첫 번째 기믹 - craft(공예)"
        }
    elif level_number < 30:
        return {
            "obstacle_types": ["craft", "stack"],
            "gimmick_intensity": 0.25,
            "description": "목표 기믹 - craft + stack"
        }
    elif level_number < 50:
        return {
            "obstacle_types": ["craft", "stack", "ice"],
            "gimmick_intensity": 0.3,
            "description": "얼음 추가 - +ice"
        }
    elif level_number < 80:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link"],
            "gimmick_intensity": 0.4,
            "description": "연결 추가 - +link"
        }
    elif level_number < 110:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain"],
            "gimmick_intensity": 0.5,
            "description": "사슬 추가 - +chain"
        }
    elif level_number < 150:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key"],
            "gimmick_intensity": 0.55,
            "description": "버퍼잠금 추가 - +key"
        }
    elif level_number < 190:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass"],
            "gimmick_intensity": 0.6,
            "description": "풀 추가 - +grass"
        }
    elif level_number < 240:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown"],
            "gimmick_intensity": 0.65,
            "description": "상자 추가 - +unknown"
        }
    elif level_number < 290:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain"],
            "gimmick_intensity": 0.7,
            "description": "커튼 추가 - +curtain"
        }
    elif level_number < 340:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain", "bomb"],
            "gimmick_intensity": 0.75,
            "description": "폭탄 추가 - +bomb"
        }
    elif level_number < 390:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain", "bomb", "time_attack"],
            "gimmick_intensity": 0.8,
            "description": "타임어택 추가 - +time_attack"
        }
    elif level_number < 440:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain", "bomb", "time_attack", "frog"],
            "gimmick_intensity": 0.9,
            "description": "개구리 추가 - +frog"
        }
    else:
        return {
            "obstacle_types": ["craft", "stack", "ice", "link", "chain", "key", "grass", "unknown", "curtain", "bomb", "time_attack", "frog", "teleport"],
            "gimmick_intensity": 1.0,
            "description": "모든 기믹 사용 가능 (13개)"
        }


# ============================================================================
# 레벨 설정 통합 테이블 (LEVEL_CONFIG_TABLE)
# ============================================================================
# 모든 레벨 생성 파라미터를 한 곳에서 관리
# 수정 시 이 테이블만 변경하면 됨
#
# 필드 설명:
#   max_level: 해당 설정이 적용되는 최대 레벨 번호 (이하)
#   min_layers, max_layers: 레이어 수 범위
#   grid_size: 그리드 크기 (홀수 레이어 기준, 짝수 레이어는 +1)
#   tile_range: (min, max) 타일 수 범위
#   tile_types: 사용할 타일 종류 수
#   description: 설명
# ============================================================================
LEVEL_CONFIG_TABLE = [
    # (max_level, min_layers, max_layers, grid_size, tile_range, tile_types, description)
    # [v16] 가시 그리드 최대 7x7 캡(인게임 타일 가독성). grid_size는 '홀수 레이어' 기준이고
    # 짝수 레이어는 +1이라 가시 최대 = grid_size+1 → grid_size 최대 6(짝수층 7). 줄어든 면적은
    # 레이어 층수 상향으로 보충해 난이도(깊이/블로킹)·타일 총량 유지.
    (3,    1, 2, 4, (9, 18),   4,  "Tutorial - 튜토리얼 (1-3)"),
    (10,   3, 4, 5, (30, 36),  5,  "Tutorial - 후반 튜토리얼 (4-10)"),
    (30,   3, 4, 5, (30, 48),  6,  "Early - 초반 (11-30)"),
    (60,   3, 4, 6, (30, 50),  8,  "Early-Mid - 초중반 (31-60)"),
    (100,  4, 6, 6, (50, 80),  9,  "Mid - 중반 (61-100)"),
    (225,  5, 7, 6, (60, 90),  9,  "Mid-Late - 중후반 (101-225)"),
    (600,  6, 8, 6, (70, 100), 10, "Standard - A등급 주력 (226-600)"),
    (1125, 7, 9, 6, (75, 105), 11, "Advanced - B등급 기준선 (601-1125)"),
    (1500, 8, 10, 6, (84, 120), 12, "Expert - C/D등급 (1126-1500)"),
    (99999, 8, 10, 6, (96, 120), 13, "Master - 엔드게임 (1501+)"),
]


# ─────────────────────────────────────────────────────────────────────────
# [BOSS_MODE] 보스 레벨 레시피 — 레이어별(위→아래) 화려한 대칭 템플릿 스택.
# 값 = pattern_templates.PATTERN_TEMPLATES 인덱스. level_number 기반 결정적 로테이션
# ((level//10 - 1) % len) → 보스 150개가 서로 다른 조합 순환, 재시도에도 동일 레시피 유지.
# 상단 = 임팩트(별/꽃/나비/선버스트…), 하단 = 구조 베이스(프레임/채움).
# ─────────────────────────────────────────────────────────────────────────
BOSS_RECIPES: List[List[int]] = [
    [15, 4, 5, 40, 0, 40],    # star_five → donut → concentric_diamond → frame
    [46, 7, 4, 41, 0, 40],    # flower → hexagon → donut → double_frame
    [45, 33, 32, 40, 0, 40],  # butterfly → bowtie → hourglass → frame
    [18, 16, 43, 0, 40, 0],   # sun_burst → star_six → center_hollow
    [19, 44, 1, 40, 0, 40],   # spiral → window_panes → diamond → frame
    [8, 46, 4, 41, 0, 40],    # heart → flower → donut → double_frame
    [64, 43, 41, 40, 0, 0],   # nested_frames → center_hollow → double_frame
    [55, 3, 1, 40, 0, 40],    # hub_and_spokes → cross → diamond → frame
    [57, 4, 5, 43, 0, 40],    # octagon_ring → donut → concentric → center_hollow
    [36, 37, 36, 37, 0, 40],  # pyramid ↔ inverted_pyramid 교대
    [17, 15, 2, 40, 0, 40],   # crescent_moon → star_five → oval → frame
    [49, 7, 3, 43, 0, 40],    # honeycomb → hexagon → cross → center_hollow
]


def crop_level_to_max_dim(level_json: Dict[str, Any], max_dim: int = 8) -> Tuple[bool, int]:
    """레벨의 빈 가장자리를 균일 크롭해 선언 그리드 최대변을 축소(in-place).

    전 레이어에서 공통으로 비어있는 여백(좌/우/상/하)만큼 col/row를 줄이고 모든 타일 키를
    동일량 시프트한다. 홀짝 교대 크기차(짝수층=홀수층+1)는 동일 여백 제거로 보존되고, 레이어간
    월드 정렬·블로킹 상대크기·상대위치 기믹(link 등)도 보존된다(게임 무변경, 순수 좌표 변환).

    Args:
        level_json: 대상 레벨(수정됨)
        max_dim: 목표 최대변(이하). 크롭 후에도 이 값 초과면 미적용(D타입 = 크롭 불가).

    Returns:
        (applied, new_max_dim): applied=크롭 실제 적용 여부, new_max_dim=크롭 후(또는 현재) 최대변.
    """
    n_layers = int(level_json.get("layer", 0) or 0)
    layers = []  # (idx, col, row, minx, maxx, miny, maxy or None if empty)
    for i in range(n_layers):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict):
            continue
        col = int(ld.get("col") or 0)
        row = int(ld.get("row") or 0)
        tiles = ld.get("tiles") or {}
        if tiles:
            xs = [int(p.split("_")[0]) for p in tiles]
            ys = [int(p.split("_")[1]) for p in tiles]
            layers.append((i, col, row, min(xs), max(xs), min(ys), max(ys)))
        else:
            layers.append((i, col, row, None, None, None, None))
    filled = [l for l in layers if l[3] is not None]
    if not filled:
        return (False, 0)
    lx = min(l[3] for l in filled)
    rx = min(l[1] - 1 - l[4] for l in filled)
    ty = min(l[5] for l in filled)
    by = min(l[2] - 1 - l[6] for l in filled)
    # [가드] col/row 가 null/0 인 손상 템플릿은 `if l[1] > 0` 필터가 전부 걸러 빈 시퀀스가 되고
    # max() 가 ValueError 로 터진다(실측: level_templates 211개 중 3개 — 127/137/169).
    # 크래시 대신 '크롭 불가'로 반환해 상위에서 헤더 복구 후 재시도하게 한다.
    sized = [l for l in layers if l[1] > 0 and l[2] > 0]
    if not sized:
        return (False, 0)
    cur_max = max(max(l[1], l[2]) for l in sized)
    new_max = max(max(l[1] - lx - rx, l[2] - ty - by) for l in sized)
    if lx + rx + ty + by == 0 or new_max > max_dim:
        return (False, cur_max)
    for i, col, row, *_ in layers:
        ld = level_json[f"layer_{i}"]
        was_str = isinstance(ld.get("col"), str)
        nc, nr = col - lx - rx, row - ty - by
        ld["col"] = str(nc) if was_str else nc
        ld["row"] = str(nr) if was_str else nr
        tiles = ld.get("tiles") or {}
        if tiles:
            ld["tiles"] = {
                f"{int(p.split('_')[0]) - lx}_{int(p.split('_')[1]) - ty}": v
                for p, v in tiles.items()
            }
    # 에디터 메타(패턴 위치/그리드) 시프트 — 존재 시에만
    lp = level_json.get("_pattern_locked_positions")
    if isinstance(lp, (list, set)):
        shifted = []
        for p in lp:
            try:
                x, y = p.split("_")
                shifted.append(f"{int(x) - lx}_{int(y) - ty}")
            except Exception:  # noqa: BLE001
                shifted.append(p)
        level_json["_pattern_locked_positions"] = shifted if isinstance(lp, list) else set(shifted)
    if isinstance(level_json.get("_pattern_grid_cols"), int):
        level_json["_pattern_grid_cols"] -= (lx + rx)
    if isinstance(level_json.get("_pattern_grid_rows"), int):
        level_json["_pattern_grid_rows"] -= (ty + by)
    return (True, new_max)


# ─────────────────────────────────────────────────────────────────────────
# [TIMEA v2] 타임어택 제한시간 산출 상수 — 여기 한 곳에서만 관리.
#   timea = clamp(MIN, MAX, ceil(수집타일수 * BASE * TIER_MULT[tier]))
# 티어는 난이도와 분리된 **독립 레버**: 1=넉넉 / 2=보통 / 3=촉박.
# 정수(밀리) 산술로 고정 — 프론트 미러와 부동소수 평가순서 차이로 1초 어긋나는 것 방지.
# 근거: 게임은 탭 입력 락이 없어(LevelController.cs:1269-1283) 타일 비행 0.5s 애니가
#   다음 탭을 막지 않는다 → 애니 하한 ≈0. 실질 하한은 인간 탭속도 ≈0.25s/타일.
#   BASE 0.9s 는 참조 페이스(하한 아님, C#서 도출 불가 — 실플레이 로깅으로 보정 대상).
# MIN/MAX 60~600 = 게임 스키마 계약(DESIGN_LEVEL_MAP_SCHEMA.md §2 timea).
# ─────────────────────────────────────────────────────────────────────────
# [BOMB] 폭탄 남은횟수(카운트다운) 범위 — 기획 3~5. 여기 한 곳에서만 관리.
# 게임 규칙: 다른 타일 수집 시 카운트↓, 0이면 게임오버(단 **가려진 폭탄은 틱하지 않음**).
# ⚠️ 구코드는 randint(5,10) 이라 기획 위반 + 시뮬(bot_simulator.py:1239)이 max(3,min(5,·))로
# 클램프해 **생성값과 검증값이 불일치**했다(6~10을 5로 보고 평가 → 난이도 왜곡).
BOMB_COUNTDOWN_MIN = 3
BOMB_COUNTDOWN_MAX = 5

TIMEA_BASE_MILLI = 900                     # 0.9초/타일 (참조 페이스)
TIMEA_TIER_MILLI: Dict[int, int] = {
    1: 1150,   # 넉넉  — 실효 1.035s/타일 (Lv341 튜토리얼 · 저난이도 보스)
    2: 850,    # 보통  — 실효 0.765s/타일
    3: 600,    # 촉박  — 실효 0.540s/타일 (물리하한 0.25s의 약 2.2배)
}
TIMEA_MIN_SEC = 60
TIMEA_MAX_SEC = 600
TIMEA_ABS_MIN_SEC_PER_TILE = 0.45          # 안전선: 가장 촉박한 티어도 이 아래로 못 감
# 시작 시 상수 자체 검증 — 티어 표를 잘못 조정해 물리적으로 불가능한 레벨을 만드는 것 차단
assert (TIMEA_BASE_MILLI * min(TIMEA_TIER_MILLI.values())) / 1_000_000 >= TIMEA_ABS_MIN_SEC_PER_TILE, \
    "TIMEA 티어 배수가 물리 하한(TIMEA_ABS_MIN_SEC_PER_TILE) 아래로 설정됨"

# time_attack 해금 레벨 — leveling_config 정본에서 유도(상수 중복 방지)
try:  # pragma: no cover - import 경로 방어
    from ..models.leveling_config import PROFESSIONAL_GIMMICK_UNLOCK as _GUC
    TIME_ATTACK_UNLOCK_LEVEL = int(_GUC["time_attack"].unlock_level)
except Exception:  # noqa: BLE001
    TIME_ATTACK_UNLOCK_LEVEL = 341

# ─────────────────────────────────────────────────────────────────────────
# 타일 타입 분포 프로파일 (레벨별 V = 서로 다른 타일 종류 수만 오버라이드)
# baseline = LEVEL_CONFIG_TABLE 기본값(tile_type_profile=None). 신규 프로파일은
# V만 교체하고 레이어/그리드/sawtooth/난이도/기믹 등 나머지 분포는 baseline과 동일.
# 형식: (max_level, V) 오름차순. 카탈로그 최대 15종(t1~t15).
# ─────────────────────────────────────────────────────────────────────────
TILE_TYPE_PROFILES: Dict[str, List[Tuple[int, int]]] = {
    # 기존보다 초반부터 가파른 버전. 11-30=8, 31-60=10, 끝(1126-1500)=13.
    # 중간대(61~1125)는 단조증가 보간.
    "hard_steep": [
        (3, 4), (10, 5), (30, 8), (60, 10), (100, 11),
        (225, 11), (600, 12), (1125, 12), (99999, 13),
    ],
}


def resolve_profile_tile_count(level_number: int, tile_type_profile: Optional[str]) -> Optional[int]:
    """프로파일 지정 시 해당 레벨의 V 반환. 미지정/미등록이면 None(=baseline 사용)."""
    if not tile_type_profile:
        return None
    brackets = TILE_TYPE_PROFILES.get(tile_type_profile)
    if not brackets:
        return None
    for cap, v in brackets:
        if level_number <= cap:
            return v
    return brackets[-1][1]


def get_grid_size_for_level(level_number: int) -> Tuple[int, int]:
    """
    Get recommended grid size based on level number.
    그리드 크기는 LEVEL_CONFIG_TABLE에서 가져옴.

    CRITICAL: col과 row는 항상 같아야 함 (정사각형 그리드)

    Args:
        level_number: The level number (1-based)

    Returns:
        Tuple of (cols, rows) - always square (cols == rows)
    """
    for max_level, _, _, grid_size, _, _, _ in LEVEL_CONFIG_TABLE:
        if level_number <= max_level:
            return (grid_size, grid_size)
    # Fallback to last config
    return (8, 8)


def get_gboost_style_layer_config(level_number: int, tile_type_profile: Optional[str] = None) -> Dict[str, Any]:
    """
    Get recommended layer configuration based on level number.
    모든 설정은 LEVEL_CONFIG_TABLE에서 가져옴.

    Args:
        level_number: The level number (1-based)
        tile_type_profile: 지정 시 tile_types(V)만 프로파일 값으로 오버라이드

    Returns:
        Dict with layer and grid configuration including tile_types
    """
    result = None
    for max_level, min_layers, max_layers, grid_size, tile_range, tile_types, description in LEVEL_CONFIG_TABLE:
        if level_number <= max_level:
            result = {
                "min_layers": min_layers,
                "max_layers": max_layers,
                "cols": grid_size,
                "rows": grid_size,
                "total_tile_range": tile_range,
                "tile_types": tile_types,
                "description": description
            }
            break

    if result is None:
        # Fallback to last config (Master)
        last = LEVEL_CONFIG_TABLE[-1]
        result = {
            "min_layers": last[1],
            "max_layers": last[2],
            "cols": last[3],
            "rows": last[3],
            "total_tile_range": last[4],
            "tile_types": last[5],
            "description": last[6]
        }

    # 프로파일 지정 시 V(tile_types)만 오버라이드 (나머지 분포는 baseline 유지)
    override_v = resolve_profile_tile_count(level_number, tile_type_profile)
    if override_v is not None:
        result["tile_types"] = override_v
    return result


def get_lowest_difficulty_positions(count: int = 3) -> Set[int]:
    """
    톱니바퀴 패턴에서 가장 낮은 난이도의 position들을 동적으로 찾습니다.

    Args:
        count: 찾을 position 개수 (기본 3개)

    Returns:
        가장 낮은 난이도의 position 집합
    """
    from ..models.leveling_config import SAWTOOTH_PATTERN_10

    # (position, difficulty) 튜플 리스트 생성 후 난이도 기준 정렬
    indexed_difficulties = [(i, diff) for i, diff in enumerate(SAWTOOTH_PATTERN_10)]
    sorted_by_difficulty = sorted(indexed_difficulties, key=lambda x: x[1])

    # 가장 낮은 count개의 position 반환
    return {pos for pos, _ in sorted_by_difficulty[:count]}


# 캐시: 톱니바퀴 패턴에서 가장 낮은 3개 난이도 position (lazy 초기화)
_LOWEST_DIFFICULTY_POSITIONS_CACHE: Optional[Set[int]] = None


def _get_lowest_positions() -> Set[int]:
    """캐시된 lowest difficulty positions 반환 (lazy 초기화)"""
    global _LOWEST_DIFFICULTY_POSITIONS_CACHE
    if _LOWEST_DIFFICULTY_POSITIONS_CACHE is None:
        _LOWEST_DIFFICULTY_POSITIONS_CACHE = get_lowest_difficulty_positions(3)
    return _LOWEST_DIFFICULTY_POSITIONS_CACHE


def get_tile_types_for_level(level_number: int, tile_type_profile: Optional[str] = None) -> List[str]:
    """
    Get recommended tile types list based on level number.

    [v2] 난이도별 타일 종류 수 (10종류 기준선):
    - 튜토리얼 (1-10): 4-5종류
    - 쉬움 (S/A): 8-9종류
    - 보통 (B): 10종류 (기준선)
    - 어려움 (C/D): 11-12종류

    톱니바퀴 패턴(10레벨 순환) 기반:
    - 쉬운 레벨 (가장 낮은 난이도 3개): 실제 타일 타입 사용 (t1~t{tile_count})
    - 일반 레벨: t0 사용 (클라이언트에서 랜덤 타일로 변환)

    Args:
        level_number: The level number (1-based)

    Returns:
        List of tile type strings (t0 for random, or t1~t{n} for fixed)
    """
    # 10레벨 주기 내 위치 (0~9)
    position_in_10 = (level_number - 1) % 10

    # 톱니바퀴 패턴에서 가장 낮은 난이도 3개 position에 해당하면 실제 타일 사용
    lowest_positions = _get_lowest_positions()
    if position_in_10 in lowest_positions:
        # 레벨에 따른 타일 종류 수 결정 (난이도 스케일링)
        config = get_gboost_style_layer_config(level_number, tile_type_profile)
        tile_count = config.get("tile_types", 10)

        # [v15.40] 색상 균등 분배: 5색상에서 골고루 선택
        tile_count = max(4, min(tile_count, 15))
        # [v15.45] max_index=tile_count: 클라이언트 useTileCount와 정합성 보장.
        # 풀을 t1..t{tile_count} 범위로 제한해 다운스트림 필터에서 잘리는 사례 방지.
        return select_color_balanced_tiles(tile_count, seed=level_number, max_index=tile_count)
    else:
        # 나머지 7개 레벨은 t0 사용 (클라이언트에서 랜덤 타일로 변환)
        return ["t0"]


def get_use_tile_count_for_level(level_number: int, tile_type_profile: Optional[str] = None) -> int:
    """
    Get useTileCount setting for level.

    레벨에 따른 타일 종류 수:
    - Level 1-30: 4종류
    - Level 31-60: 5종류
    - Level 61-225: 5종류
    - Level 226-600: 6종류
    - Level 601-1125: 6종류
    - Level 1126-1500: 7종류
    - Level 1501+: 8종류

    Args:
        level_number: The level number (1-based)

    Returns:
        useTileCount value (1-15)
    """
    config = get_gboost_style_layer_config(level_number, tile_type_profile)
    return config.get("tile_types", 5)


from ..models.level import (
    GenerationParams,
    GenerationResult,
    DifficultyGrade,
    TILE_TYPES,
)
from ..models.leveling_config import calculate_hidden_tile_ratio
from .analyzer import get_analyzer


# [v15.40] 타일 색상 버킷: 5색상 × 3타일 = 15종
COLOR_BUCKETS = {
    1: ["t1", "t2", "t3"],     # 색상1
    2: ["t4", "t5", "t6"],     # 색상2
    3: ["t7", "t8", "t9"],     # 색상3
    4: ["t10", "t11", "t12"],  # 색상4
    5: ["t13", "t14", "t15"],  # 색상5
}

def select_color_balanced_tiles(
    count: int, seed: Optional[int] = None, max_index: Optional[int] = None
) -> List[str]:
    """[v15.40] 색상 균등 분배 후 각 색상에서 랜덤 1개 선택.

    count=6이면 5색상에서 1개씩 + 1색상에서 추가 1개 = 6종류 (max_index=15 기준)
    각 색상에서 어떤 타일을 선택할지는 랜덤.

    [v15.45] max_index 파라미터 추가:
        useTileCount 같은 클라이언트 측 t-인덱스 상한과 정합성을 맞추기 위해
        타일 풀을 t1..t{max_index} 범위로 제한할 수 있음. 다른 코드 경로
        (_assign_tiles_pattern_mode, _validate_dock_tile_compatibility)가
        useTileCount를 인덱스 상한으로 해석해 범위 밖 타일을 잘라내므로,
        이 함수에서 미리 제약하지 않으면 결과 타일 수가 useTileCount보다 작아진다.
        max_index=None 또는 >=15면 기존 동작(전체 풀)을 유지.
    """
    rng = random.Random(seed)

    # Restrict pool to t1..t{max_index} when constraint provided
    if max_index is not None and max_index < 15:
        allowed = {f"t{i}" for i in range(1, max_index + 1)}
        in_range_buckets = {
            c: [t for t in tiles if t in allowed]
            for c, tiles in COLOR_BUCKETS.items()
        }
        in_range_buckets = {c: tiles for c, tiles in in_range_buckets.items() if tiles}
        if not in_range_buckets:
            # Fallback shouldn't happen with max_index>=1, but guard anyway
            return [f"t{i}" for i in range(1, max_index + 1)][:count]
        colors = list(in_range_buckets.keys())
    else:
        in_range_buckets = {c: list(tiles) for c, tiles in COLOR_BUCKETS.items()}
        colors = list(in_range_buckets.keys())  # [1,2,3,4,5]

    rng.shuffle(colors)

    selected: List[str] = []
    used_per_color: Dict[int, List[str]] = {c: [] for c in colors}
    color_idx = 0
    safety_iter = 0
    max_safety = count * len(colors) * 2 + 1

    while len(selected) < count and safety_iter < max_safety:
        color = colors[color_idx % len(colors)]
        # 해당 색상에서 아직 선택 안 된 타일 중 랜덤
        available_in_color = [t for t in in_range_buckets[color] if t not in used_per_color[color]]
        if not available_in_color:
            # 이 색상은 모두 사용됨 — 다른 색상 시도
            color_idx += 1
            safety_iter += 1
            # 모든 색상이 소진되면 (제약 안에서 더 뽑을 게 없음) 종료
            if all(not [t for t in in_range_buckets[c] if t not in used_per_color[c]] for c in colors):
                break
            continue
        tile = rng.choice(available_in_color)
        selected.append(tile)
        used_per_color[color].append(tile)
        color_idx += 1
        safety_iter += 1

    return selected


class LevelGenerator:
    """Generates levels with target difficulty."""

    # Default tile types for generation
    # [v15.40] 색상 균등 분배 방식으로 변경
    DEFAULT_TILE_TYPES = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10"]
    OBSTACLE_TILE_TYPES = ["t8", "t9"]
    SPECIAL_TILE_TYPES = ["t10", "t11", "t12", "t14", "t15"]
    # All goal types - craft and stack with all 4 directions (s=south, n=north, e=east, w=west)
    GOAL_TYPES = [
        "craft_s", "craft_n", "craft_e", "craft_w",
        "stack_s", "stack_n", "stack_e", "stack_w"
    ]

    # 기믹 언락 첫 스테이지(튜토리얼) 정본 맵 — routes/generate.py DEFAULT_GIMMICK_UNLOCK_LEVELS와 동기화.
    # generate() 종료 직전 재보장에 사용: 어떤 호출 경로(신규/재생성)든 level_number만 있으면
    # 해당 기믹이 반드시 존재하도록 자기교정. (craft/stack은 goal 타입이라 별도 처리.)
    TUTORIAL_UNLOCK_LEVELS = {
        11: "craft", 21: "stack", 31: "ice", 51: "link", 81: "chain", 111: "key",
        151: "grass", 191: "unknown", 241: "curtain", 291: "bomb", 391: "frog", 441: "teleport",
    }

    # Generation parameters
    MAX_ADJUSTMENT_ITERATIONS = 50
    DIFFICULTY_TOLERANCE = 3.0  # ±3 points (tighter tolerance for better accuracy)

    # Maximum useTileCount - user can specify up to 15 tile types
    # Note: More tile types = harder levels (with 7-slot dock)
    MAX_USE_TILE_COUNT = 15

    # Level similarity threshold (0.0-1.0) - levels more similar than this are considered duplicates
    SIMILARITY_THRESHOLD = 0.75

    # Pattern diversity tracking - class-level to persist across instances
    _recent_pattern_categories: List[int] = []
    _PATTERN_HISTORY_SIZE = 5

    # [v15.40] 커스텀 패턴 캐시
    _custom_patterns_cache: Optional[Dict] = None
    _custom_patterns_mtime: float = 0

    @classmethod
    def _get_custom_pattern(cls, pattern_index: int, cols: int, rows: int) -> Optional[List[str]]:
        """커스텀 패턴 파일에서 해당 인덱스의 패턴을 로드. 없으면 None.

        [v15.53] 그리드 크기 안전 보장: fallback 시 요청 그리드보다 큰 패턴은 반환하지 않음.
        이전 버그: pattern 11이 5x5 요청에 대해 6x6 패턴(좌표 (5,5) 포함)을 반환 →
            홀수 레이어가 5x5만 렌더하므로 외곽 타일이 디바이스에서 잘림.
        해결: 요청보다 작거나 같은 사이즈만 후보로 채택. 작은 패턴은 중앙 정렬해서 재배치.
        """
        import os, json as json_mod
        # __file__ = app/core/generator.py → ../../data/ = backend/data/
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        pattern_file = os.path.normpath(os.path.join(_this_dir, "..", "..", "data", "custom_patterns.json"))

        try:
            mtime = os.path.getmtime(pattern_file)
            if cls._custom_patterns_cache is None or mtime > cls._custom_patterns_mtime:
                with open(pattern_file, "r") as f:
                    cls._custom_patterns_cache = json_mod.load(f)
                cls._custom_patterns_mtime = mtime
        except (FileNotFoundError, json_mod.JSONDecodeError):
            return None

        # [v15.40] 크기별 키 우선
        size_key = f"{pattern_index}_{cols}x{rows}"
        if size_key in cls._custom_patterns_cache:
            return cls._custom_patterns_cache[size_key].get("positions", [])

        # [v15.53] fallback — 요청보다 작거나 같은 사이즈만 채택 (디바이스 그리드 정합 보장)
        # [v15.59] 요청 사이즈의 75% 미만인 패턴은 거부 — recenter 후 너무 sparse 해져
        # 채움률이 비정상적으로 낮아짐 (예: 9x9에 4x4 → 11% 채움). 너무 작은 후보만 있으면
        # 알고리즘 fallback에 위임해 적절한 density 확보.
        prefix = f"{pattern_index}_"
        candidates = []  # (saved_size, key, entry) — 작은 사이즈만
        target_size = min(cols, rows)
        # 최소 사이즈 임계: target의 75% (단 4 이하면 그냥 4)
        min_acceptable_size = max(4, int(target_size * 0.75))
        for k, v in cls._custom_patterns_cache.items():
            if k.startswith(prefix) and "x" in k:
                saved_size = v.get("grid_size", 0)
                if isinstance(saved_size, int) and min_acceptable_size <= saved_size <= target_size:
                    candidates.append((saved_size, k, v))

        # base 키도 후보에 추가 (크기 정보 있을 때만)
        base_key = str(pattern_index)
        if base_key in cls._custom_patterns_cache:
            entry = cls._custom_patterns_cache[base_key]
            saved_size = entry.get("grid_size", 0)
            if isinstance(saved_size, int) and min_acceptable_size <= saved_size <= target_size:
                candidates.append((saved_size, base_key, entry))

        if not candidates:
            # 요청 사이즈에 충분히 큰 fitting 패턴이 없음 → 알고리즘 fallback에 위임
            logger.debug(
                f"[CUSTOM_PATTERN] pattern={pattern_index} no entry fits {cols}x{rows} "
                f"(requires {min_acceptable_size} <= saved_size <= {target_size}); falling back to algorithmic"
            )
            return None

        # 가장 큰 (요청에 가장 근접한) fitting size 선택
        candidates.sort(key=lambda c: -c[0])
        chosen_size, chosen_key, chosen_entry = candidates[0]
        positions = chosen_entry.get("positions", [])

        # 중앙 정렬 재배치 — 작은 패턴을 큰 그리드 중앙으로
        if chosen_size < min(cols, rows) and positions:
            offset_x = max(0, (cols - chosen_size) // 2)
            offset_y = max(0, (rows - chosen_size) // 2)
            recentered = []
            for p in positions:
                try:
                    px, py = p.split("_")
                    nx = int(px) + offset_x
                    ny = int(py) + offset_y
                    if 0 <= nx < cols and 0 <= ny < rows:
                        recentered.append(f"{nx}_{ny}")
                except (ValueError, AttributeError):
                    continue
            positions = recentered
            logger.debug(
                f"[CUSTOM_PATTERN] pattern={pattern_index} {chosen_size}x{chosen_size} "
                f"recentered into {cols}x{rows} (+{offset_x},+{offset_y})"
            )

        return positions

    @classmethod
    def _get_synth_pattern_indices(cls, max_size: Optional[int] = None) -> List[int]:
        """[v16 🅑] 절차생성으로 채택된 패턴 인덱스(synth=true) 목록. 자동 믹스 풀에 주입용.

        custom_patterns.json을 _get_custom_pattern과 같은 캐시로 읽는다. max_size 지정 시
        해당 크기 이하 변형이 하나라도 있는 인덱스만 반환(렌더 시 size-fit fallback과 정합).
        """
        import os, json as json_mod
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        pattern_file = os.path.normpath(os.path.join(_this_dir, "..", "..", "data", "custom_patterns.json"))
        try:
            mtime = os.path.getmtime(pattern_file)
            if cls._custom_patterns_cache is None or mtime > cls._custom_patterns_mtime:
                with open(pattern_file, "r") as f:
                    cls._custom_patterns_cache = json_mod.load(f)
                cls._custom_patterns_mtime = mtime
        except (FileNotFoundError, json_mod.JSONDecodeError):
            return []
        found: Dict[int, bool] = {}
        for k, v in (cls._custom_patterns_cache or {}).items():
            if not isinstance(v, dict) or not v.get("synth"):
                continue
            try:
                idx = int(k.split("_")[0])
            except (ValueError, IndexError):
                continue
            size = v.get("grid_size", 0)
            if max_size is not None and isinstance(size, int) and size > max_size:
                continue
            found[idx] = True
        return sorted(found.keys())

    # ============================================================
    # Tile Creation Helper Methods
    # ============================================================
    # All tile data structures should be created through these methods
    # to ensure consistency and easy modification of tile format.

    @staticmethod
    def _create_tile(tile_type: str, attribute: str = "", extra: Optional[List] = None) -> List:
        """Create a tile data structure.

        Args:
            tile_type: The tile type (t1-t6, craft_s, stack_n, etc.)
            attribute: The attribute/gimmick (chain, ice_1, frog, etc.)
            extra: Additional data (goal count, teleport pair id, etc.)

        Returns:
            Tile data as list: [tile_type, attribute] or [tile_type, attribute, extra]
        """
        if extra is not None:
            return [tile_type, attribute, extra]
        return [tile_type, attribute]

    @staticmethod
    def _place_tile(tiles: Dict[str, List], pos: str, tile_type: str,
                    attribute: str = "", extra: Optional[List] = None) -> None:
        """Place a tile at the specified position.

        Args:
            tiles: The tiles dictionary to modify
            pos: Position string (e.g., "3_4")
            tile_type: The tile type
            attribute: The attribute/gimmick
            extra: Additional data
        """
        tiles[pos] = LevelGenerator._create_tile(tile_type, attribute, extra)

    # Minimum count for craft/stack goals (match-3 game rule)
    MIN_GOAL_COUNT = 3

    # Minimum total tile count for playable levels (industry standard: 18-30 for tutorial)
    # Based on Tile Buster, Triple Tile research: minimum 18 tiles (6 sets of 3)
    # Exception: Level 1-5 tutorial levels can have fewer tiles
    MIN_TILE_COUNT = 18
    TUTORIAL_MIN_TILE_COUNT = 9  # Level 1-5 tutorial: minimum 3 sets (9 tiles)
    MIN_TILE_COUNT_LV11 = 60     # [사용자] Lv11+ 최소 60타일(밀도 확보). ÷3 보정으로 60~63.

    @staticmethod
    def _create_goal_tile(goal_type: str, count: int) -> List:
        """Create a goal tile (craft/stack) data structure.

        Args:
            goal_type: Goal type with direction (craft_s, stack_n, etc.)
            count: Number of tiles the goal produces (minimum 3)

        Returns:
            Goal tile data as list: [goal_type, "", [count]]
        """
        # Enforce minimum count of 3 for match-3 game rule
        safe_count = max(LevelGenerator.MIN_GOAL_COUNT, count)
        return [goal_type, "", [safe_count]]

    @staticmethod
    def _place_goal_tile(tiles: Dict[str, List], pos: str, goal_type: str, count: int) -> None:
        """Place a goal tile at the specified position.

        Args:
            tiles: The tiles dictionary to modify
            pos: Position string
            goal_type: Goal type with direction
            count: Number of tiles the goal produces
        """
        tiles[pos] = LevelGenerator._create_goal_tile(goal_type, count)

    @staticmethod
    def _get_tile_type(tile_data: List) -> Optional[str]:
        """Extract tile type from tile data.

        Args:
            tile_data: Tile data list

        Returns:
            Tile type string or None if invalid
        """
        if tile_data and isinstance(tile_data, list) and len(tile_data) > 0:
            return tile_data[0]
        return None

    @staticmethod
    def _get_tile_attribute(tile_data: List) -> Optional[str]:
        """Extract attribute from tile data.

        Args:
            tile_data: Tile data list

        Returns:
            Attribute string or None if not present
        """
        if tile_data and isinstance(tile_data, list) and len(tile_data) > 1:
            return tile_data[1]
        return None

    @staticmethod
    def _get_tile_extra(tile_data: List) -> Optional[List]:
        """Extract extra data from tile data.

        Args:
            tile_data: Tile data list

        Returns:
            Extra data list or None if not present
        """
        if tile_data and isinstance(tile_data, list) and len(tile_data) > 2:
            return tile_data[2]
        return None

    @staticmethod
    def _set_tile_attribute(tile_data: List, attribute: str) -> None:
        """Set the attribute of a tile in place.

        Args:
            tile_data: Tile data list to modify
            attribute: New attribute value
        """
        if tile_data and isinstance(tile_data, list) and len(tile_data) > 1:
            tile_data[1] = attribute

    @staticmethod
    def _set_tile_extra(tile_data: List, extra: List) -> None:
        """Set the extra data of a tile in place.

        Args:
            tile_data: Tile data list to modify
            extra: New extra data value
        """
        if tile_data and isinstance(tile_data, list):
            if len(tile_data) > 2:
                tile_data[2] = extra
            elif len(tile_data) == 2:
                tile_data.append(extra)

    @staticmethod
    def calculate_level_similarity(level1: Dict[str, Any], level2: Dict[str, Any]) -> float:
        """Calculate similarity between two levels based on layout patterns.

        Returns a score from 0.0 (completely different) to 1.0 (identical).

        Compares:
        - Tile positions per layer (weighted by layer)
        - Total tile count
        - Layer structure
        """
        try:
            map1 = level1.get("map", level1)
            map2 = level2.get("map", level2)

            # Extract layer data
            layers1 = {}
            layers2 = {}

            for key, value in map1.items():
                if key.startswith("layer") and isinstance(value, dict):
                    layer_idx = int(key.replace("layer", ""))
                    positions = set(value.get("position", {}).keys())
                    layers1[layer_idx] = positions

            for key, value in map2.items():
                if key.startswith("layer") and isinstance(value, dict):
                    layer_idx = int(key.replace("layer", ""))
                    positions = set(value.get("position", {}).keys())
                    layers2[layer_idx] = positions

            if not layers1 or not layers2:
                return 0.0

            # Compare layer structure
            all_layers = set(layers1.keys()) | set(layers2.keys())
            layer_count_sim = 1.0 - abs(len(layers1) - len(layers2)) / max(len(all_layers), 1)

            # Compare positions per layer with weighted importance
            position_similarities = []
            for layer_idx in all_layers:
                pos1 = layers1.get(layer_idx, set())
                pos2 = layers2.get(layer_idx, set())

                if not pos1 and not pos2:
                    continue

                intersection = len(pos1 & pos2)
                union = len(pos1 | pos2)
                jaccard = intersection / union if union > 0 else 0.0

                # Higher layers (more visible) weighted more
                weight = 1.0 + layer_idx * 0.2
                position_similarities.append((jaccard, weight))

            if not position_similarities:
                return layer_count_sim * 0.5

            weighted_pos_sim = sum(s * w for s, w in position_similarities) / sum(w for _, w in position_similarities)

            # Compare total tile counts
            total1 = sum(len(p) for p in layers1.values())
            total2 = sum(len(p) for p in layers2.values())
            count_sim = 1.0 - abs(total1 - total2) / max(total1, total2, 1)

            # Final weighted similarity
            similarity = (
                weighted_pos_sim * 0.6 +  # Position similarity most important
                layer_count_sim * 0.2 +   # Layer structure
                count_sim * 0.2           # Total count
            )

            return min(1.0, max(0.0, similarity))

        except Exception as e:
            logger.warning(f"Error calculating level similarity: {e}")
            return 0.0

    @staticmethod
    def is_too_similar(new_level: Dict[str, Any], recent_levels: List[Dict[str, Any]], threshold: float = None) -> bool:
        """Check if new level is too similar to any recent levels.

        Args:
            new_level: The newly generated level
            recent_levels: List of recently generated levels to compare against
            threshold: Similarity threshold (default: SIMILARITY_THRESHOLD)

        Returns:
            True if the level is too similar to any recent level
        """
        if threshold is None:
            threshold = LevelGenerator.SIMILARITY_THRESHOLD

        for recent_level in recent_levels:
            similarity = LevelGenerator.calculate_level_similarity(new_level, recent_level)
            if similarity > threshold:
                logger.debug(f"Level too similar: {similarity:.2f} > {threshold}")
                return True

        return False

    def generate(self, params: GenerationParams) -> GenerationResult:
        """
        Generate a level with target difficulty.

        Args:
            params: Generation parameters including target difficulty.

        Returns:
            GenerationResult with generated level and actual difficulty.

        Raises:
            ValueError: If layer_tile_configs total is not divisible by 3.
        """
        start_time = time.time()

        # [초반 고정 레벨] 1~31 중 저장소에 등록된 레벨은 **그대로** 출고한다.
        # 튜토리얼 구간은 배치마다 모양이 바뀌면 학습 흐름이 흔들려 고정이 필요하다.
        # 보스(10·20·30)는 저장 대상이 아니라 여기서 안 걸린다(보스 템플릿이 정본).
        # 안전 tail(÷3 보장 → _finalize_level)만 태워 저장 이후의 규칙 변경에도 대응한다.
        if params.level_number is not None:
            _fx = self._load_fixed_level(params.level_number)
            if _fx is not None:
                return self._finish_fixed_level(_fx, params, start_time)

        # [등껍질 침식] 모양이 층수·타일수를 결정하므로 절차생성의 층수/타일수/골 배치 기계를
        # 통과시키면 안 된다(실측: 골 출구 강제가 스택을 관통해 구멍을 뚫어 ÷3·받침이 동시에 깨짐).
        # 템플릿 경로와 동일한 꼬리(t0 배정 → 튜토리얼 보장 → ÷3 → _finalize_level)만 태운다.
        # 실패(없는 id·깊이<2) 시 None → 마커 지우고 아래 일반 경로로 폴백.
        if getattr(params, "turtle_pattern_id", None):
            _tres = self._generate_turtle(params, start_time)
            if _tres is not None:
                return _tres
            params.turtle_pattern_id = None

        # [BOSS_MODE] 보스 전용 파라미터 오버라이드 — 그리드 상한 8(선언), 층수 5~6,
        # 대칭/화려 템플릿 레시피(auto-mix에서 level_number 결정적 적용), 기믹 강도 상향.
        if getattr(params, "boss_mode", False):
            self._apply_boss_overrides(params)

        # [역생성 v3-2단계] 모든 속성 기믹 + 컨테이너(craft/stack) goal 허용.
        # witness는 plain 타일만 배정(컨테이너 내부는 t0 분배·÷3 보장), 봇클리어 검증 + degrade로
        # 솔버블 보장. (goals를 비우지 않음 → 컨테이너 포함.)
        if getattr(params, "use_reverse_generation", False):
            if not params.obstacle_types:
                params.obstacle_types = ["ice", "grass", "chain", "link", "frog", "bomb", "curtain", "teleport"]

        # Check if user has specified per-layer tile configs OR total_tile_count (strict mode)
        # In strict mode, we respect user's tile counts exactly without adjustment
        # Only fixed layout levels (2, 3) and explicit per-layer configs are strict
        # NOTE: total_tile_count alone does NOT trigger strict mode - it's used as a
        # max_tiles limit during difficulty adjustment instead (see line ~720)
        is_fixed_layout_level = params.level_number in (1, 2, 3)
        has_strict_tile_config = (
            is_fixed_layout_level or
            (bool(params.layer_tile_configs) and len(params.layer_tile_configs) > 0)
        )

        # Calculate total goal inner tiles (craft_s with count=3 means 3 additional tiles inside)
        # Goal tiles are visual tiles that CONTAIN inner tiles, not replace them
        # Example: 21+21 tiles + craft_s(3) = 42 visual tiles + 3 inner tiles = 45 actual tiles
        goal_inner_tiles = 0
        # Fixed layout levels (2, 3) are early tutorial levels without craft/stack goals
        if is_fixed_layout_level:
            goals = params.goals if params.goals is not None else []
        else:
            goals = params.goals if params.goals is not None else [{"type": "craft_s", "count": 3}]
        if goals:
            for goal in goals:
                # Handle both dict and GoalConfig objects
                if hasattr(goal, 'count'):
                    goal_count = goal.count
                else:
                    goal_count = goal.get("count", 3)
                goal_inner_tiles += goal_count

        # Validate: In strict mode, total tile count (including goal inner tiles) must be divisible by 3
        if has_strict_tile_config:
            # Get config tiles from layer_tile_configs or total_tile_count
            if params.layer_tile_configs and len(params.layer_tile_configs) > 0:
                config_tiles = sum(config.count for config in params.layer_tile_configs)
            elif params.total_tile_count is not None:
                config_tiles = params.total_tile_count
            else:
                config_tiles = 0

            # Actual tiles = visual tiles + goal inner tiles
            # Goal tile itself is counted in config_tiles, but it contains inner tiles that need to be added
            # Example: 42 config tiles + 3 inner tiles = 45 actual tiles
            actual_tiles = config_tiles + goal_inner_tiles

            if actual_tiles % 3 != 0:
                raise ValueError(
                    f"실제 타일 수({actual_tiles})가 3의 배수가 아닙니다. "
                    f"(설정 타일 {config_tiles}개 + 골 내부 타일 {goal_inner_tiles}개 = {actual_tiles}개) "
                    f"클리어가 불가능하므로 생성할 수 없습니다. "
                    f"(예: 총 설정 타일을 {config_tiles - (actual_tiles % 3)} 또는 {config_tiles + (3 - actual_tiles % 3)}로 조정)"
                )

        # Create initial level structure
        level = self._create_base_structure(params)

        # Populate layers with tiles based on target difficulty
        level = self._populate_layers(level, params)

        # Add obstacles and attributes
        level = self._add_obstacles(level, params)

        # Add goals (in strict mode, replace existing tiles instead of adding)
        level = self._add_goals(level, params, strict_mode=has_strict_tile_config)

        # CRITICAL: Fix any goals with count below MIN_GOAL_COUNT
        # This ensures all craft/stack goals have at least 3 tiles
        level = self._fix_goal_counts(level)

        # Adjust to target difficulty (only if NOT using strict tile config)
        # When user specifies exact tile counts, don't modify them for difficulty
        if not has_strict_tile_config:
            # Pass max tile count to prevent adding tiles beyond the target
            max_tiles = params.total_tile_count if params.total_tile_count else None
            # Pass tutorial_gimmick to preserve it during difficulty adjustment
            tutorial_gimmick = getattr(params, 'tutorial_gimmick', None)
            level = self._adjust_difficulty(level, params.target_difficulty, max_tiles=max_tiles, params=params, tutorial_gimmick=tutorial_gimmick)

        # CRITICAL: Ensure tile count is divisible by 3 (only if NOT using strict config)
        # When user specifies exact counts, they are responsible for divisibility
        if not has_strict_tile_config:
            level = self._ensure_tile_count_divisible_by_3(level, params)

        # CRITICAL: Validate obstacles AFTER all tile modifications
        # This ensures all obstacles (chain, link, grass) have valid clearable neighbors
        level = self._validate_and_fix_obstacles(level)

        # Final check: if obstacle removal broke divisibility, fix it again (only if not strict)
        if not has_strict_tile_config:
            level = self._ensure_tile_count_divisible_by_3(level, params)
            # Re-validate obstacles since tile removal might have broken chain/link neighbors
            level = self._validate_and_fix_obstacles(level)

        # CRITICAL: Ensure tutorial gimmicks are maintained after all validations
        # Tutorial gimmick count may have been reduced by obstacle validation
        # level_number 정본맵 fallback: 재생성 등 일부 경로가 params.tutorial_gimmick을 비워
        # 튜토리얼 검출을 놓치는 회귀(Category A) 차단 — 언락 첫 스테이지면 무조건 보장.
        tutorial_gimmick = getattr(params, 'tutorial_gimmick', None) \
            or self.TUTORIAL_UNLOCK_LEVELS.get(getattr(params, 'level_number', None))
        tutorial_gimmick_min_count = getattr(params, 'tutorial_gimmick_min_count', 3)
        if tutorial_gimmick:
            if tutorial_gimmick == "unknown":
                # Unknown gimmicks need special handling - must be covered by upper layers
                level = self._ensure_unknown_tutorial_count(level, tutorial_gimmick_min_count)
            elif tutorial_gimmick in ("craft", "stack"):
                # craft/stack은 goal(컨테이너) 타입 — _add_goals가 배치에 실패해 0개가 되면
                # 튜토리얼 자체가 성립 안 함. 최소 1개 컨테이너 보장. (÷3은 후속 finalize가 정리.)
                level = self._ensure_container_goal_tutorial(level, tutorial_gimmick)
            else:
                level = self._ensure_tutorial_gimmick_count(level, tutorial_gimmick, tutorial_gimmick_min_count)

        # NOTE: Craft/Stack boxes wait if output position has a tile (during GAMEPLAY).
        # But during GENERATION, we should ensure no tiles exist in output positions.
        # Relocate (not delete) tiles to maintain counts.
        level = self._relocate_tiles_from_goal_outputs(level)

        # CRITICAL: Validate frog positions after ALL tile modifications
        # Frogs must be selectable at spawn (not covered by upper layers)
        # This fixes frogs that became covered due to tiles added in later steps
        level = self._validate_and_fix_frog_positions(level)

        # PRE-VALIDATION: Set up key gimmick (unlockTile)
        # key 기믹: 버퍼 슬롯 잠금 + key 타일 필요
        # CRITICAL: key 타일은 t0 distribution 또는 직접 배치 둘 중 하나로만 처리!
        # - craft/stack 골이 있으면: t0 distribution이 key 타일 생성 (TileDistributor.assign_t0_tiles)
        # - craft/stack 골이 없으면: 직접 key 타일 배치 필요 (_place_key_tiles)
        level_number = params.level_number if params.level_number else 0
        gimmick_intensity = getattr(params, 'gimmick_intensity', 1.0)
        KEY_UNLOCK_LEVEL = 111  # 백엔드 leveling_config.py와 동기화
        KEY_PROBABILITY = 0.3  # 30% 확률
        if level_number >= KEY_UNLOCK_LEVEL and gimmick_intensity > 0:
            # 튜토리얼 레벨(111)은 항상 적용, 그 외는 확률 적용
            is_key_tutorial = (level_number == KEY_UNLOCK_LEVEL)
            if is_key_tutorial or random.random() < KEY_PROBABILITY * gimmick_intensity:
                # 난이도에 따라 잠금 슬롯 수 결정 (1-2)
                unlock_tile_count = 1  # 기본값: 1칸 잠금
                if params.target_difficulty >= 0.7 and not is_key_tutorial:
                    unlock_tile_count = 2  # 고난이도: 2칸 잠금 (튜토리얼은 항상 1칸)
                level["unlockTile"] = unlock_tile_count

                # Check if craft/stack goals have enough t0 tiles for key distribution
                # t0 distribution: 첫 unlockTile 그룹(각 3개)이 key 타일이 됨
                t0_count = 0
                num_layers = level.get("layer", 8)
                for layer_idx in range(num_layers):
                    layer_key = f"layer_{layer_idx}"
                    tiles = level.get(layer_key, {}).get("tiles", {})
                    for pos, tile_data in tiles.items():
                        if isinstance(tile_data, list) and len(tile_data) > 2:
                            tile_type = tile_data[0]
                            if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                                if isinstance(tile_data[2], list) and tile_data[2]:
                                    t0_count += int(tile_data[2][0]) if tile_data[2][0] else 0

                key_tiles_needed = unlock_tile_count * 3
                # t0 distribution이 key 타일을 충분히 제공할 수 있는지 확인
                # t0_count >= key_tiles_needed면 t0 distribution이 처리함
                if t0_count < key_tiles_needed:
                    # craft/stack 골이 없거나 부족함 → 직접 key 타일 배치 필요
                    tiles_to_place = key_tiles_needed - (t0_count // 3) * 3
                    if tiles_to_place > 0:
                        self._place_key_tiles(level, tiles_to_place)

        # FINAL VALIDATION: Ensure level is playable (all tile types divisible by 3, minimum tiles)
        validation_result = self._validate_playability(level, params.level_number)
        if not validation_result["is_playable"]:
            logger.warning(
                f"Generated level may not be playable! "
                f"Total tiles: {validation_result['total_tiles']}, "
                f"Min required: {validation_result.get('min_required', 'N/A')}, "
                f"Below minimum: {validation_result.get('below_minimum', False)}, "
                f"Types with bad count: {validation_result['bad_types']}"
            )

            # If below minimum tile count, add more tiles
            if validation_result.get("below_minimum", False):
                level = self._ensure_minimum_tiles(level, params, validation_result.get("min_required", self.MIN_TILE_COUNT))
                # Re-validate after adding tiles
                validation_result = self._validate_playability(level, params.level_number)

            # Try aggressive fix for remaining issues (not divisible by 3, etc.)
            if not validation_result["is_playable"]:
                level = self._force_fix_tile_counts(level, params)

        # CRITICAL: Ensure t0 distribution results in valid tile type counts
        # This validates the randSeed produces a playable distribution
        level = self._ensure_valid_t0_distribution(level)

        # Final validation after t0 distribution fix
        final_validation = self._validate_playability(level, params.level_number)
        if not final_validation["is_playable"]:
            logger.warning(
                f"Level still not playable after t0 distribution fix! "
                f"Bad types: {final_validation['bad_types']}"
            )

        # CRITICAL: Pre-compute max_moves BEFORE deadlock check.
        # Without this, _quick_deadlock_check defaults to 50 moves, which is far below
        # what most levels require (typically total_tiles many). The bot then runs out of
        # moves on every iteration and reports clear_rate=0%, falsely flagging every level
        # as deadlocked. Set provisional max_moves now; it gets re-set after gimmick fixes below.
        level["max_moves"] = self._calculate_max_moves(level)

        # CRITICAL: Deadlock prevention - ensure tiles are well-distributed across layers
        # This prevents scenarios where matching tiles are all blocked in lower layers
        # Skip when skip_deadlock_check=True for ultra-fast generation (use batch verify later)
        # [봇클리어 수정] 단 unit_assembly는 reverse 없이 생성되므로 데드락 위험 → 강제로 체크 실행
        # (skip 무시). 언클리어러블 필터 → RL 검증 통과율 회복.
        if not params.skip_deadlock_check or getattr(params, "unit_assembly", False):
            level, deadlock_ok, deadlock_clear_rate = self._ensure_no_deadlock(level, max_attempts=10)
            if not deadlock_ok:
                logger.warning(
                    f"[generate] Level may have deadlock issues - could not fully resolve"
                )
        else:
            # LIGHTWEIGHT VALIDATION: Quick structural check without full simulation
            # 1. Ensure tile type counts are divisible by 3
            level = self._ensure_tile_divisibility(level)

            # 2. Quick deadlock check with minimal simulation
            # [v15.54] 2 attempts (was 3) — speed 회복. 한 번 실패해도 1회 reshuffle 기회.
            # 핵심 비용은 _quick_deadlock_check 시뮬 횟수이므로 attempts × iter = 2*5 = 10 sims.
            level, deadlock_ok, deadlock_clear_rate = self._ensure_no_deadlock(level, max_attempts=2)
            logger.info("[generate] Fast mode: lightweight validation with quick deadlock check")
        # Stash for response — consumed by generate() return below
        self._last_playability_warning = not deadlock_ok
        self._last_estimated_clear_rate = deadlock_clear_rate

        # DOCK CAPACITY VALIDATION: Ensure useTileCount is compatible with unlockTile
        # 규칙: 타일 종류 수가 너무 많으면 독이 금방 차서 데드락 발생
        # 안전 기준: useTileCount <= (7 - unlockTile) + 2
        level = self._validate_dock_tile_compatibility(level)

        # KEY TILE VALIDATION: Ensure key tile count matches unlockTile * 3
        # 초과 key 타일은 dock 공간만 차지하므로 클리어 불가능 야기
        level = self._validate_and_fix_key_tile_count(level)

        # Calculate final metrics
        analyzer = get_analyzer()
        report = analyzer.analyze(level)

        # Auto-calculate max_moves based on total tiles
        level["max_moves"] = self._calculate_max_moves(level)

        # time_attack 기믹: timea 필드 설정 (제한 시간, 초)
        # NOTE: level_number와 gimmick_intensity는 위 PRE-VALIDATION 섹션에서 이미 선언됨
        # 적용 규칙 (TileBuster 패턴):
        # - 레벨 341 (튜토리얼): 최초 언락 레벨에 적용
        # - 레벨 350, 360, 370...: 톱니바퀴 패턴의 보스 레벨(10번째)에만 적용
        # 제한 시간 (디자인 문서 기준):
        # - 쉬움 (difficulty < 0.3): 120초
        # - 보통 (0.3 <= difficulty < 0.5): 90초
        # - 어려움 (0.5 <= difficulty < 0.7): 60초
        # - 매우 어려움 (0.7 <= difficulty): 45초
        # [TIMEA v2] 여기서는 **티어만 결정**하고 값은 산출하지 않는다.
        # 이유: 아래 단계들이 타일 수를 바꾼다(경계트림/피라미드/OOB제거/컨테이너 튜토리얼(+2)/
        # ÷3 finalize(-2..+2)). 실측 드리프트 최대 -18타일 → 여기서 계산하면 stale.
        # 실제 timea 는 _finalize_level() → _apply_timea() 가 최종 타일 수로 산출한다.
        tier = self._decide_timea_tier(level_number, gimmick_intensity, params)
        if tier is not None:
            level["_timea_tier"] = tier

        # CRITICAL: Final boundary check - remove any tiles outside valid grid
        # This prevents tiles at positions like (7, 3) in a 7x7 grid
        # NOTE: In PATTERN mode, use the uniform grid size stored in level metadata
        if level.get("_pattern_uniform_grid"):
            # Pattern mode: use the stored uniform grid dimensions
            boundary_cols = level.get("_pattern_grid_cols", params.grid_size[0] + 1)
            boundary_rows = level.get("_pattern_grid_rows", params.grid_size[1] + 1)
        else:
            # Normal mode: use the larger of odd/even layer sizes
            boundary_cols = params.grid_size[0] + 1  # Even layer size
            boundary_rows = params.grid_size[1] + 1

        for layer_idx in range(15):  # [v16] 레이어 상한 상향(가드로 안전)
            layer_key = f"layer_{layer_idx}"
            if layer_key in level and "tiles" in level[layer_key]:
                tiles = level[layer_key]["tiles"]
                invalid_positions = []
                for pos in tiles.keys():
                    parts = pos.split("_")
                    if len(parts) == 2:
                        x, y = int(parts[0]), int(parts[1])
                        if x < 0 or x >= boundary_cols or y < 0 or y >= boundary_rows:
                            invalid_positions.append(pos)
                for pos in invalid_positions:
                    del tiles[pos]
                    logger.debug(f"[BOUNDARY] Removed out-of-bounds tile at {pos} from {layer_key}")

        # [v15.53] 진짜 원인은 _get_custom_pattern fallback이 더 큰 그리드 패턴을 작은
        # 그리드 요청에 그대로 반환했던 것. 디바이스는 layer.col/row가 아니라 level.row를
        # 보고 짝수=N/홀수=N-1로 그리드 결정하므로 layer.col/row 자동확장은 효과 없음.
        # 근본 fix는 _get_custom_pattern에서 적용했고, 여기서는 최종 sanity check만.
        # (만약 어떤 경로로 OOB 타일이 끼면 client에서 잘림 — 검출은 MetaIntegrityPanel/
        #  자물쇠 버튼에서 진행.)

        # [v15.40] 최종 피라미드 구조 강제 + 시각적 중앙정렬 보정
        level = self._enforce_pyramid_structure(level)
        level = self._fix_visual_centering(level)

        # [OOB_REPAIR] 레이어 선언 col/row 밖 타일 제거 (클리어 불가 회귀 차단).
        # 게임은 rowCount(=선언 col/row)로 그리드를 생성 → 범위 밖(x<0/x>=col/y<0/y>=row)
        # 타일은 디바이스에서 컬링되어 픽 불가 → 해당 타입 3배수가 깨져 클리어 불가.
        # 원인: 후속 변형 단계(_fix_visual_centering 위치 시프트, _enforce_pyramid_structure,
        # boundary trim 등)가 타일을 그리드 경계 밖으로 밀 수 있음(윗줄 주석의 "can violate").
        # 여기서 무조건 잘라내고, 아래 _finalize_divisibility_guarantee + FINAL_REPAIR가 ÷3 재보장.
        level = self._remove_out_of_bounds_tiles(level)

        # [유닛조립 대칭 복원] 빌더는 좌우대칭으로 배치하지만 이후 단계(_fix_visual_centering 시프트,
        # 피라미드 클램프, OOB 제거)가 한쪽만 잘라 대칭이 깨진다 → 최상층에 '구석에 치우친 덩어리'가
        # 남아 시각적으로 어색. ÷3 보정(아래) **직전**에 미러 셀을 채워 복원한다.
        # (여기서 타일이 늘어도 곧바로 _finalize_divisibility_guarantee 가 ÷3 을 재보장.)
        if level.get("_unit_assembly"):
            level = self._symmetrize_unit_layers(level)

        # CRITICAL: Final sync of layer num fields before returning
        # This ensures t0 distribution calculations are based on correct tile counts
        level = self._sync_layer_num_fields(level)

        # [v15.54] FINAL playability re-check 최적화.
        # 초기 _ensure_no_deadlock이 통과했으면(deadlock_ok=True), 후속 mutating 단계
        # (dock/key validation, boundary trimming, pyramid enforcement, visual centering)는
        # 거의 클리어 가능성을 깨지 않음 → final re-check 스킵 (속도 우선).
        # 초기 단계가 실패(=warning)했으면 그 결과를 그대로 신뢰.
        # 만약 후속 단계가 깨뜨리는 회귀가 발견되면 별도 단위 테스트로 잡고
        # 여기서는 정상 경로 속도 회복.
        # 이전(v15.43): 매 generate마다 _quick_deadlock_check 5 iter 추가 호출 → 누적 비용 큼.

        # [튜토리얼 컨테이너 생존 보장] craft/stack 튜토리얼에서 초기 배치 컨테이너가 후속
        # 변형(리셔플/경계·피라미드 트림/OOB 제거)에 사라질 수 있으므로, 모든 좌표 변형이 끝난
        # 지금(÷3 finalize 직전) 한번 더 보장 → finalize/FINAL_REPAIR가 ÷3을 마무리한다.
        _final_tut = getattr(params, 'tutorial_gimmick', None) \
            or self.TUTORIAL_UNLOCK_LEVELS.get(getattr(params, 'level_number', None))
        if _final_tut in ("craft", "stack"):
            level = self._ensure_container_goal_tutorial(level, _final_tut)

        # [v16] 최종 ÷3 클리어가능성 보장 (모든 변형 단계 이후, FINAL_REPAIR 직전).
        # 총합 (concrete + t0)을 ÷3으로 맞춘다 → t0 레벨은 분배기가 per-type을 보장,
        # concrete 레벨은 바로 아래 FINAL_REPAIR가 per-type relabel로 마무리.
        # fast/slow path 무관하게 항상 실행 — '비÷3 출고' 회귀를 구조적으로 차단.
        level = self._finalize_divisibility_guarantee(level)

        # [v15.47] STRUCTURAL guarantee: every regular tile type (t1..t15) MUST have a
        # count that is a multiple of 3 in the final level. Otherwise the level is
        # mathematically unclearable (leftover tiles can never form a triple).
        # _force_fix_tile_counts and _redistribute_tile_types_for_divisibility run earlier,
        # but pyramid enforcement / visual centering / boundary trim afterwards can violate
        # the invariant. We do one final repair pass here so a non-divisible level can
        # never reach the consumer.
        try:
            from collections import Counter as _Counter
            num_layers_final = level.get("layer", 0) or 0
            type_counts: dict = _Counter()
            type_positions: dict = {}
            for li in range(num_layers_final):
                lk = f"layer_{li}"
                ld = level.get(lk, {})
                tiles = ld.get("tiles", {}) if isinstance(ld, dict) else {}
                for pos, tile in tiles.items():
                    if not (isinstance(tile, list) and tile and isinstance(tile[0], str)):
                        continue
                    tt = tile[0]
                    if tt.startswith("t") and tt[1:].isdigit() and tt != "t0":
                        type_counts[tt] += 1
                        type_positions.setdefault(tt, []).append((li, pos))
            offenders = {t: c for t, c in type_counts.items() if c % 3 != 0}
            if offenders:
                # Repair by re-assigning surplus tiles of an offender to another (offender or
                # normal) type so both end up divisible. This never deletes positions —
                # only changes the tile-name to keep pattern shape intact.
                logger.warning(
                    f"[FINAL_REPAIR] divisibility violations after post-fix steps: {offenders} — repairing"
                )
                # Pair rem-1 + rem-2 first (1 swap fixes both)
                rem1 = [t for t in offenders if offenders[t] % 3 == 1]
                rem2 = [t for t in offenders if offenders[t] % 3 == 2]
                while rem1 and rem2:
                    a = rem1.pop(0); b = rem2.pop(0)
                    if not type_positions.get(a):
                        continue
                    li, pos = type_positions[a].pop()
                    layer_key = f"layer_{li}"
                    cur = level[layer_key]["tiles"].get(pos)
                    if isinstance(cur, list) and cur:
                        gimmick = cur[1] if len(cur) > 1 else ""
                        level[layer_key]["tiles"][pos] = [b, gimmick]
                        type_counts[a] -= 1
                        type_counts[b] = type_counts.get(b, 0) + 1
                # [FINAL_REPAIR 수렴수정] 남은 offender 잉여를 '깨끗한 타입'에 밀어넣으면(구버전) 그 타입이
                # 다시 위반돼 remainder가 이동만 되고 순환(예: rem1 3개 → 미수렴). 대신 offender끼리 '잔여완성':
                # 각 타입에서 잉여(count%3)를 풀로 떼면 각자 ÷3. _finalize가 총합 ÷3 보장하므로 |pool|=Σ잉여≡0(mod3)=3k.
                # 풀을 3개씩 묶어 타입에 재배정(+3 → ÷3 유지). 깨끗한 타입 안 건드림 → 항상 수렴.
                pool: List[Tuple[int, str]] = []
                for t in list(type_counts.keys()):
                    r = type_counts[t] % 3
                    for _ in range(r):
                        if type_positions.get(t):
                            li, pos = type_positions[t].pop()
                            pool.append((li, pos))
                            type_counts[t] -= 1
                targets = [t for t, c in type_counts.items() if c % 3 == 0 and c > 0] or list(type_counts.keys())
                if targets and len(pool) >= 3:
                    for gi in range(len(pool) // 3):
                        tgt = targets[gi % len(targets)]
                        for k in range(3):
                            li, pos = pool[gi * 3 + k]
                            cur = level[f"layer_{li}"]["tiles"].get(pos)
                            if isinstance(cur, list) and cur:
                                gimmick = cur[1] if len(cur) > 1 else ""
                                level[f"layer_{li}"]["tiles"][pos] = [tgt, gimmick]
                                type_counts[tgt] = type_counts.get(tgt, 0) + 1
                # Final assertion logging — if we still failed, mark the level so consumers can see.
                final_offenders = {t: c for t, c in type_counts.items() if c % 3 != 0}
                if final_offenders:
                    logger.error(
                        f"[FINAL_REPAIR] Could not fully repair divisibility: {final_offenders} — "
                        f"playability_warning forced True"
                    )
                    self._last_playability_warning = True
        except Exception as e:
            logger.warning(f"[FINAL_REPAIR] failed: {e}")

        # [역생성] concrete(컨테이너/순서기믹 없는) 레벨에 witness-peeling 타입배정 적용.
        # 적용 성공 시 솔버블·÷3 구조적 보장. 미지원 레벨/실패는 자동 스킵(원본 유지).
        # 표시: level["reverse_generated"] = bool, level["reverse_generation_reason"] = str.
        if getattr(params, "use_reverse_generation", False):
            try:
                from .reverse_generator import apply_reverse_generation
                utc = level.get("useTileCount", 5) or 5
                rev_level, applied, reason = apply_reverse_generation(
                    level, use_tile_count=utc,
                    max_open=getattr(params, "reverse_generation_max_open", 2),
                    verify=True,
                )
                level = rev_level
                level["reverse_generated"] = applied
                level["reverse_generation_reason"] = reason
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[REVERSE_GEN] failed: {e}")
                level["reverse_generated"] = False
                level["reverse_generation_reason"] = f"오류: {e}"

        # [생성모드 마커] 재생성(순차검증/개별)이 원본 생성모드를 판별·보존하도록 level_json에 기록.
        # (tile_type_profile·size_diversity는 level_json에 안 남던 설정 → 재생성이 놓치던 문제 차단.)
        if getattr(params, "tile_type_profile", None):
            level["_tile_type_profile"] = params.tile_type_profile
        if getattr(params, "size_diversity_start_level", None):
            level["_size_diversity_start_level"] = params.size_diversity_start_level
        if getattr(params, "concentric_deep", False):
            level["_concentric_deep"] = True

        # [LINK_SANITIZE] 모든 변형 단계(centering/÷3 삭제/OOB 제거/역생성) 이후 최종 실행.
        # 대상이 사라진 고아 link 속성을 제거 → 인게임 FindLinkTile null[0] NRE(스폰 크래시) 차단.
        level = self._strip_orphaned_link_tiles(level)

        # [INNER_DIVERSIFY] craft/stack 내부 명시 다양화 bake — 필드 전량 명시 레벨에서
        # 내부가 단색 3뭉치로 확정되는 게임 세트분배 문제 해소.
        # ⚠️ "타입 카운트 순열 불변이라 ÷3 보존"은 **key 슬롯이 없을 때만** 참이다.
        #   분배기는 unlockTile>0 이면 배정에 "key"를 섞는데, key 는 매칭 대상이 아니다.
        #   ÷3 게이트(1405줄)는 컨테이너 내부를 't0 N개 = 매칭타일 N개'로 세는데, bake 가 그중
        #   일부를 key 로 굳히면 매칭 대상이 줄어 ÷3 이 사후에 깨진다. 아무도 재검사하지 않았다.
        #   실측: 야간 A* 전수판정에서 PROVEN_IMPOSSIBLE 18개가 **전부** 이 경로였다
        #        (예: Lv336 stack_n=[5,'t9_t9_key_t9_key'] → key 2개 → 매칭 46개(%3=1)).
        # → bake 결과를 게임 정본 카운터(solver._clearability_type_counts)로 재검증하고,
        #   깨졌으면 bake 를 **되돌린다**. 다양화는 미관 최적화라 클리어가능성보다 우선할 수 없다.
        _pre_bake = copy.deepcopy(level)
        level = self._diversify_container_inner_tiles(level)
        if not self._clearability_ok(level):
            if self._clearability_ok(_pre_bake):
                logger.warning("[INNER_DIVERSIFY] bake 후 ÷3 위반 → bake 롤백(다양화 포기, 클리어가능 우선)")
                level = _pre_bake
            else:
                logger.error("[INNER_DIVERSIFY] bake 전에도 ÷3 위반 — 상위 ÷3 게이트 결함 의심")

        # [grass 홀짝착각방지] 모든 좌표/타일 변형 단계 '이후' 최종 실행 — 짝수 층차(같은 홀짝) 0오프셋으로
        # 다른 층 타일이 grass 이웃 자리에 겹쳐보여 착각 유발하는 grass 속성 일괄 제거. (모든 배치경로 공통.)
        level = self._strip_confusing_grass(level)

        # [튜토리얼 기믹 최종 보장] 모든 파괴적 변형 단계(데드락 리셔플/÷3 재분배/경계·피라미드 트림/
        # 역생성/grass strip) 이후 최종 재보장. 초기(line~1095) 보장이 후속 단계에 지워질 수 있고,
        # 재생성 등 일부 경로는 params.tutorial_gimmick이 비어 검출을 놓친다 → level_number 정본맵으로
        # 자기교정하여 언락 첫 스테이지에 해당 기믹이 반드시 존재하도록 한다. (attribute 기믹은 td[1]만
        # 추가 → 타입 카운트 불변 = ÷3 보존. craft/stack goal·key는 별도 보장 로직이 앞단에서 처리.)
        final_tut = getattr(params, 'tutorial_gimmick', None) \
            or self.TUTORIAL_UNLOCK_LEVELS.get(params.level_number)
        if final_tut:
            min_ct = getattr(params, 'tutorial_gimmick_min_count', 3) or 3
            if final_tut == "unknown":
                level = self._ensure_unknown_tutorial_count(level, min_ct)
            elif final_tut not in ("craft", "stack", "key"):
                level = self._ensure_tutorial_gimmick_count(level, final_tut, min_ct)

        # [FINALIZE 백스톱] 위 '튜토리얼 기믹 최종 보장'이 1478의 정화기 '이후'에 chain/link 속성을
        # 추가하므로, 공통 마무리를 여기서 한 번 더 돌린다(멱등):
        #   ÷3 → chain 클로저(해제불가 사슬 plain화) → link sanitize(고아 링크 plain화)
        #   → max_moves 재계산 → timea 산출.
        # max_moves: 앞선 계산이 이후 단계(craft 골 ÷3 보정 내부타일 3→6, 튜토리얼 ensure, ÷3 finalize의
        #   타일 추가/제거)로 stale되면 '수집필요 > max_moves' → 구조적으로 깰 수 있어도 무브 소진 실패
        #   (예: Lv.38 필요111 vs 108). RL 시뮬도 같은 max_moves 사용 → unclearable 오판.
        # timea: 같은 이유로 최종 타일 수에서만 정확히 산출 가능(드리프트 실측 최대 -18타일).
        level = self._finalize_level(level)

        generation_time_ms = int((time.time() - start_time) * 1000)

        return GenerationResult(
            level_json=level,
            actual_difficulty=report.score / 100.0,
            grade=report.grade,
            generation_time_ms=generation_time_ms,
            playability_warning=getattr(self, "_last_playability_warning", False),
            estimated_clear_rate=getattr(self, "_last_estimated_clear_rate", 1.0),
        )

    # ── [등껍질 침식] 완전받침 침식 스택 ─────────────────────────────────────────
    # 모델: 선정된 '두꺼운' 모양을 **바닥 1층**으로 두고, 위층은 자기가 덮는 하위 칸이
    # **전부** 있을 때만 생성한다(all-조건). 홀짝 교대 격자(짝수층 S, 홀수층 S-1)에서
    # 2층마다 테두리 한 겹이 벗겨져 거북등껍질 실루엣이 된다.
    #
    # 게임의 valid_support_mask 는 any-조건(하위 1개만 덮어도 배치 가능)이라 위층이 **넓어진다**.
    # 침식에는 반드시 all-조건을 써야 한다 — 오프셋 자체는 정본(get_cover_offsets) 그대로.
    #
    # 실측(실험 스크립트 exp_turtle_select.py): custom_patterns 474개 중 깊이≥4·총타일≤130
    # 조건을 만족한 49개 전부 격자위반 0 / ÷3 위반 0 / floating 0 / avg봇 클리어 0.82~1.00.
    TURTLE_MAX_LAYERS = 12

    @staticmethod
    def _turtle_peel_stack(base_cells: Set[Tuple[int, int]], base_col: int
                           ) -> List[Tuple[int, int, Set[Tuple[int, int]]]]:
        """바닥 1층에서 시작해 다 깎일 때까지. 반환 [(layer_idx, col, cells)]."""
        from .unit_templates import get_cover_offsets
        out: List[Tuple[int, int, Set[Tuple[int, int]]]] = [(0, base_col, set(base_cells))]
        cur, cur_layer, cur_col = set(base_cells), 0, base_col
        idx = 1
        while idx < LevelGenerator.TURTLE_MAX_LAYERS:
            ucol = base_col - (idx % 2)
            if ucol < 1:
                break
            offs = get_cover_offsets(cur_layer, idx, cur_col, ucol)
            nxt = {(ux, uy)
                   for ux in range(ucol) for uy in range(ucol)
                   if all((ux - dx, uy - dy) in cur for dx, dy in offs)}
            if not nxt:
                break
            out.append((idx, ucol, nxt))
            cur, cur_layer, cur_col = nxt, idx, ucol
            idx += 1
        return out

    @classmethod
    def load_turtle_pattern(cls, pattern_id: str) -> Optional[Tuple[Set[Tuple[int, int]], int]]:
        """등껍질 바닥 모양 조회 → (셀집합, 격자크기). 없으면 None.

        조회 순서:
          1) `turtle_bases` 전용 라이브러리 (id 가 `tb_` 로 시작) — 사용자가 패턴 디버그 탭에서
             등록한 등껍질 전용 바닥. 기존 49종도 여기로 복사돼 있다.
          2) `custom_patterns.json` 키(예 "0_6x6") — 하위호환(기존 배치의 스탬프가 이 형식).
        """
        if str(pattern_id).startswith("tb_"):
            try:
                from . import turtle_bases as _TB
                e = _TB.get_base(pattern_id)
                if e:
                    g = int(e.get("grid") or 0)
                    cs = _TB.parse_cells(e.get("cells") or [], g)
                    if cs:
                        return cs, g
            except Exception:  # noqa: BLE001
                pass
            return None
        import json as json_mod
        import os
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        pattern_file = os.path.normpath(os.path.join(_this_dir, "..", "..", "data", "custom_patterns.json"))
        try:
            mtime = os.path.getmtime(pattern_file)
            if cls._custom_patterns_cache is None or mtime > cls._custom_patterns_mtime:
                with open(pattern_file, "r") as f:
                    cls._custom_patterns_cache = json_mod.load(f)
                cls._custom_patterns_mtime = mtime
        except (FileNotFoundError, json_mod.JSONDecodeError, OSError):
            return None
        entry = (cls._custom_patterns_cache or {}).get(pattern_id)
        if not isinstance(entry, dict):
            return None
        try:
            g = int(entry.get("grid_size"))
        except (TypeError, ValueError):
            return None
        cells: Set[Tuple[int, int]] = set()
        for p in entry.get("positions") or []:
            try:
                x, y = map(int, str(p).split("_"))
            except ValueError:
                continue
            if 0 <= x < g and 0 <= y < g:
                cells.add((x, y))
        return (cells, g) if cells else None

    def _build_turtle_layers(self, level: Dict[str, Any],
                             stack: List[Tuple[int, int, Set[Tuple[int, int]]]]
                             ) -> List[Tuple[int, str]]:
        """침식 스택을 level_json 층으로 기록. 타입은 t0(뒤 파이프라인이 배정)."""
        all_positions: List[Tuple[int, str]] = []
        for (li, col, cells) in stack:
            tiles: Dict[str, Any] = {}
            for (x, y) in sorted(cells):
                pos = f"{x}_{y}"
                tiles[pos] = ["t0", ""]
                all_positions.append((li, pos))
            level[f"layer_{li}"] = {"col": str(col), "row": str(col),
                                    "num": str(len(tiles)), "tiles": tiles}
        level["layer"] = len(stack)
        logger.info(f"[TURTLE] {len(stack)}층 침식 스택, 총 {len(all_positions)} 타일 "
                    f"({[len(c) for _, _, c in stack]})")
        return all_positions

    # 난이도 → 컨테이너 개수. 컨테이너는 (a) 수집 순서를 강제하고 (b) 내부 타일을 뒤로 미뤄
    # 도크 압박을 키운다 → 등껍질처럼 기믹 없는 순수 매치 레벨의 유일한 난이도 레버.
    TURTLE_CONTAINER_BY_DIFFICULTY: List[Tuple[float, int]] = [
        (0.20, 0),   # S: 순수 매치
        (0.40, 1),
        (0.60, 2),
        (0.80, 3),
        (1.01, 4),
    ]
    TURTLE_CONTAINER_INNER = 3      # 컨테이너 1개가 뱉는 내부 타일 수(÷3 유지에 유리)

    def _turtle_place_containers(self, level: Dict[str, Any],
                                 stack: List[Tuple[int, int, Set[Tuple[int, int]]]],
                                 params: "GenerationParams", rng) -> None:
        """[등껍질] craft/stack 컨테이너 배치.

        제약:
          - craft 는 **같은 층 인접 빈칸**으로 출력한다 → 꽉 찬 아래층엔 놓을 수 없다.
            (절차생성의 골 배치는 자리가 없으면 전 층을 관통해 구멍을 뚫는다 = 스택 파괴.
             그래서 여기서 직접, 출력칸이 확보되는 셀에만 놓는다.)
          - stack 은 제자리 누적(방향=시각 오프셋)이라 빈칸 불필요.
          - 언락 레벨 미만이면 해당 타입 제외.
        """
        ln = params.level_number
        unlock = self.TUTORIAL_UNLOCK_LEVELS or {}
        # TUTORIAL_UNLOCK_LEVELS 는 {level: gimmick} 형태 → 역인덱스로 최소 레벨 조회
        min_lv = {}
        for lv, gm in unlock.items():
            if gm not in min_lv:
                min_lv[gm] = int(lv)
        pool: List[str] = []
        if ln is None or ln >= min_lv.get("craft", 11):
            pool.append("craft")
        if ln is None or ln >= min_lv.get("stack", 21):
            pool.append("stack")
        if not pool:
            return

        diff = float(getattr(params, "target_difficulty", 0.5) or 0.5)
        want = 0
        for cap, cnt in self.TURTLE_CONTAINER_BY_DIFFICULTY:
            if diff < cap:
                want = cnt
                break
        if want <= 0:
            return

        DIRS = {"e": (1, 0), "w": (-1, 0), "s": (0, 1), "n": (0, -1)}
        gcnt = level.setdefault("goalCount", {})
        placed = 0
        # 위층부터(픽 가능·빈칸 많음) 훑는다. 꼭대기 1~2칸 층은 건너뛰고 중간층 위주.
        for (li, col, _cells) in reversed(stack):
            if placed >= want:
                break
            ld = level.get(f"layer_{li}") or {}
            tmap = ld.get("tiles") or {}
            if len(tmap) < 4:            # 너무 작은 층은 컨테이너로 덮으면 층이 사라짐
                continue
            cand = [p for p, t in tmap.items()
                    if isinstance(t, list) and len(t) >= 2 and t[0] == "t0" and not t[1]]
            rng.shuffle(cand)
            for pos in cand:
                if placed >= want:
                    break
                x, y = map(int, pos.split("_"))
                ctype = rng.choice(pool)
                if ctype == "stack":
                    full = f"stack_{rng.choice(list(DIRS))}"
                else:
                    valid = [d for d, (dc, dr) in DIRS.items()
                             if 0 <= x + dc < col and 0 <= y + dr < col
                             and f"{x+dc}_{y+dr}" not in tmap]
                    if not valid:
                        continue
                    full = f"craft_{rng.choice(valid)}"
                tmap[pos] = [full, "", [self.TURTLE_CONTAINER_INNER]]
                gcnt[full] = gcnt.get(full, 0) + self.TURTLE_CONTAINER_INNER
                placed += 1
            ld["num"] = str(len(tmap))
        if placed:
            logger.info(f"[TURTLE] 컨테이너 {placed}개 배치 (난이도 {diff:.2f}, 목표 {want})")

    def _turtle_total_tiles(self, level: Dict[str, Any]) -> int:
        """매치 대상 타일 총수 = 일반 타일 + 컨테이너 내부 타일(컨테이너 셀 자체는 제외)."""
        total = 0
        for i in range(int(level.get("layer") or 0)):
            for tile in ((level.get(f"layer_{i}") or {}).get("tiles") or {}).values():
                if not (isinstance(tile, list) and tile):
                    continue
                tt = str(tile[0])
                if tt.startswith("craft_") or tt.startswith("stack_"):
                    inner = tile[2] if len(tile) > 2 else None
                    if isinstance(inner, list) and inner:
                        try:
                            total += int(inner[0])
                        except (TypeError, ValueError):
                            pass
                else:
                    total += 1
        return total

    def _turtle_pad_div3(self, level: Dict[str, Any],
                         stack: List[Tuple[int, int, Set[Tuple[int, int]]]],
                         params: "GenerationParams", rng) -> None:
        """[등껍질] ÷3 부족분을 **타일 추가**로 메운다(삭제 금지).

        추가 위치는 난이도 레버:
          - 쉬움(diff<0.5): **꼭대기 층** — 바로 집을 수 있어 부담이 없다
          - 어려움:        **바닥 층**  — 끝까지 파고들어야 나오므로 압박이 커진다
        추가 셀 조건: 같은 층 그리드 안 + 기존 셀과 4방 인접(실루엣 유지) + 아래층 받침 존재.
        """
        need = (3 - self._turtle_total_tiles(level) % 3) % 3
        if need == 0:
            return
        diff = float(getattr(params, "target_difficulty", 0.5) or 0.5)
        order = list(range(int(level.get("layer") or 0) - 1, -1, -1)) if diff < 0.5 \
            else list(range(int(level.get("layer") or 0)))

        from .unit_templates import get_cover_offsets
        added = 0
        for li in order:
            if added >= need:
                break
            ld = level.get(f"layer_{li}") or {}
            tmap = ld.get("tiles") or {}
            if not tmap:
                continue
            try:
                col = int(ld.get("col"))
            except (TypeError, ValueError):
                continue
            occupied = set()
            for p in tmap:
                try:
                    occupied.add(tuple(map(int, p.split("_"))))
                except ValueError:
                    continue
            below = level.get(f"layer_{li-1}") if li > 0 else None
            lower: Set[Tuple[int, int]] = set()
            offs = ()
            if isinstance(below, dict):
                for p in (below.get("tiles") or {}):
                    try:
                        lower.add(tuple(map(int, p.split("_"))))
                    except ValueError:
                        continue
                try:
                    offs = get_cover_offsets(li - 1, li, int(below.get("col")), col)
                except (TypeError, ValueError):
                    offs = ()
            cand = []
            for (x, y) in occupied:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < col and 0 <= ny < col) or (nx, ny) in occupied:
                        continue
                    if li > 0 and offs and not any((nx - ox, ny - oy) in lower for ox, oy in offs):
                        continue      # 받침 없음 → floating 유발이라 제외
                    cand.append((nx, ny))
            if not cand:
                continue
            rng.shuffle(cand)
            for (nx, ny) in cand:
                if added >= need:
                    break
                pos = f"{nx}_{ny}"
                if pos in tmap:
                    continue
                tmap[pos] = ["t0", ""]
                occupied.add((nx, ny))
                added += 1
            ld["num"] = str(len(tmap))
        where = "꼭대기" if diff < 0.5 else "바닥"
        logger.info(f"[TURTLE] ÷3 패딩 {added}/{need}개 추가 ({where} 우선)")

    def _turtle_strip_impossible_attrs(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """이웃이 없어 영원히 해제 불가한 chain(좌우)/grass(4방) 속성 제거.
        보스 템플릿 경로와 동일 규칙 — 등껍질은 층마다 실루엣이 급히 줄어 가장자리에서 자주 발생."""
        for li in range(int(level.get("layer") or 0)):
            tiles = ((level.get(f"layer_{li}") or {}).get("tiles") or {})
            for pos, tile in tiles.items():
                if not (isinstance(tile, list) and len(tile) >= 2):
                    continue
                if tile[1] not in ("chain", "grass"):
                    continue
                try:
                    x, y = map(int, pos.split("_"))
                except ValueError:
                    continue
                nbrs = ((1, 0), (-1, 0)) if tile[1] == "chain" else ((1, 0), (-1, 0), (0, 1), (0, -1))
                if not any(f"{x+dx}_{y+dy}" in tiles for dx, dy in nbrs):
                    tile[1] = ""
        return level

    @staticmethod
    def _load_fixed_level(level_number: int) -> Optional[Dict[str, Any]]:
        """[초반 고정 레벨] 저장소 조회. 미등록/범위밖/보스면 None."""
        try:
            from . import fixed_levels as _FX
            e = _FX.get_fixed(level_number)
            return copy.deepcopy(e["level_json"]) if e else None
        except Exception:  # noqa: BLE001 — 저장소 문제로 생성이 멈추면 안 된다
            return None

    def _finish_fixed_level(self, level: Dict[str, Any], params: "GenerationParams",
                            start_time: float) -> "GenerationResult":
        """고정 레벨을 안전 tail 만 태워 반환. 모양·타일타입·기믹은 **저장본 그대로**."""
        level["_fixed_level"] = True          # [재생성 보존] 이 마커로 모드 유지
        # [모양 보존] 고정 레벨은 사람이 그린 모양이 정본이라 ÷3 보정이 타일을 지우면 안 된다.
        # 이 플래그를 켜야 _finalize_divisibility_guarantee 가 '삭제' 대신
        # '컨테이너(craft/stack) 내부 개수 조정' 경로를 타고, _finalize_level 의
        # 피라미드 클램프/재중앙정렬도 건너뛴다. (실측: 28개 중 13개가 t0 총합 비÷3 →
        # 플래그 없이는 매 생성마다 일반 t0 타일 1~2개가 사라져 저장본과 모양이 달라졌다.)
        level["_preserve_pattern"] = True
        level = self._finalize_divisibility_guarantee(level)
        level = self._finalize_level(level)
        report = get_analyzer().analyze(level)
        # [클리어율] 예전엔 estimated_clear_rate=1.0 / playability_warning=False 를 **하드코딩**해
        # UI가 어떤 고정 레벨이든 "클리어 예상 100%" 로 표시했다(측정한 적 없는 값).
        # 절차 경로와 동일한 읽기전용 퀵체크를 태워 실제 봇 클리어율을 돌려준다.
        # _quick_deadlock_check 는 시뮬레이션만 하고 레벨을 바꾸지 않아 모양 보존과 충돌하지 않는다.
        # 측정 실패 시엔 낙관값(1.0) 대신 None 대신 0.0 을 쓰지 않고 1.0 폴백 — 고정본은 사람이
        # 검수한 모양이라 측정 불가 하나로 배포를 막을 이유가 없고, 최종 판정은 RL 순차검증이 한다.
        clear_rate, warn = 1.0, False
        try:
            chk = self._quick_deadlock_check(level)
            clear_rate = float(chk.get("clear_rate", 1.0))
            warn = bool(chk.get("has_deadlock", False))
        except Exception as ex:  # noqa: BLE001 — 측정 실패로 생성이 멈추면 안 된다
            logger.warning(f"[FIXED_LEVEL] Lv{params.level_number} 클리어율 측정 실패: {ex}")
        logger.info(f"[FIXED_LEVEL] Lv{params.level_number} 고정 레벨 사용 "
                    f"(층 {level.get('layer')}, grade {report.grade}, clear_rate {clear_rate:.2f})")
        return GenerationResult(
            level_json=level,
            actual_difficulty=report.score / 100.0,
            grade=report.grade,
            generation_time_ms=int((time.time() - start_time) * 1000),
            playability_warning=warn,
            estimated_clear_rate=clear_rate,
        )

    @staticmethod
    def filter_gimmicks_by_unlock(types: Optional[List[str]],
                                  level_number: Optional[int]) -> List[str]:
        """[언락 강제] 해당 레벨에서 아직 해금되지 않은 기믹을 제거한다.

        정본은 `models.leveling_config.PROFESSIONAL_GIMMICK_UNLOCK`.
        라우트(`select_gimmicks_with_unlock_probability`)가 이미 필터하지만 **생성기 자체엔
        방어가 없었다** → 라우트를 우회하는 호출자(후처리 스크립트 등)가 그대로 통과시켰다.
        실측: 서브보스 149개 중 23개가 언락 위반(curtain 23·unknown 18·grass 7·link 4·chain 2·ice 2).
        여기서 한 번 더 거르면 호출자가 무엇을 넘기든 위반이 불가능하다.
        """
        if not types:
            return []
        if level_number is None:
            return list(types)
        try:
            from ..models.leveling_config import PROFESSIONAL_GIMMICK_UNLOCK as _G
            unlock = {g: int(c.unlock_level) for g, c in _G.items()}
        except Exception:  # noqa: BLE001
            return list(types)
        out = [t for t in types if level_number >= unlock.get(str(t), 0)]
        dropped = [t for t in types if t not in out]
        if dropped:
            logger.info(f"[UNLOCK_FILTER] Lv{level_number}: 미해금 기믹 제외 {dropped}")
        return out

    def _generate_turtle(self, params: "GenerationParams", start_time: float
                         ) -> Optional["GenerationResult"]:
        """[등껍질 침식] 전용 생성 경로. 실패 시 None(호출자가 일반 경로로 폴백).

        절차생성 기계(층수 계산·타일수 타겟·골 출구 배치)를 **쓰지 않는다**. 모양이 층수와
        타일수를 결정하고, 타입은 템플릿 경로와 같은 꼬리에서 배정된다:
            t0 랜덤 색 → _ensure_tutorial_unlock_gimmick → _finalize_divisibility_guarantee
            → _finalize_level
        """
        import random as _r

        pid = params.turtle_pattern_id
        loaded = self.load_turtle_pattern(pid)
        if not loaded:
            logger.warning(f"[TURTLE] 패턴 없음: {pid} → 일반 경로 폴백")
            return None
        cells, base = loaded
        stack = self._turtle_peel_stack(cells, base)
        if len(stack) < 2:
            logger.warning(f"[TURTLE] {pid}: 침식 깊이 {len(stack)} < 2 → 일반 경로 폴백")
            return None

        tile_types = params.tile_types
        if not tile_types and params.level_number:
            tile_types = get_tile_types_for_level(params.level_number)
        if not tile_types:
            tile_types = self.DEFAULT_TILE_TYPES
        seed = params.level_number if params.level_number is not None else 0

        level: Dict[str, Any] = {
            "layer": len(stack),
            "row": str(base), "col": str(base),
            # useTileCount = 클라이언트가 t0 를 몇 가지 색으로 분배할지. **len(tile_types) 아님** —
            # 레벨 대부분은 tile_types 가 ['t0'] 뿐이라 len 을 쓰면 1색 = 전부 매치되는 무의미 레벨이 된다
            # (실측: 커버리지 스윕에서 전 난이도 clear 1.00 으로 붙어버림).
            "useTileCount": (get_use_tile_count_for_level(params.level_number, params.tile_type_profile)
                             if params.level_number is not None
                             else max(1, len([t for t in tile_types if t != "t0"])) or 6),
            # randSeed 는 클라이언트 t0 색분배 시드. 프로덕션 관행(1400/1500 레벨)이
            # random.randint(1, 999999) 이므로 동일 규약을 따른다. level_number 를 그대로
            # 쓰면 값이 작고 레벨마다 고정돼 색 배치가 결정적이 된다.
            "randSeed": _r.randint(1, 999999),
            "autoCollectCount": 0,
        }
        positions = self._build_turtle_layers(level, stack)
        level["_preserve_pattern"] = True        # 침식 모양 보존(피라미드 클램프/재배치 금지)
        level["_pattern_locked_positions"] = {p for _, p in positions}
        level["_turtle_peel"] = True             # [재생성 보존] 재생성이 이 마커로 모드 유지
        level["_turtle_pattern_id"] = pid

        rng = _r.Random(seed)

        # ① 컨테이너(craft/stack) 배치 — 난이도 레버 겸 타일수 조절 수단.
        #    피라미드는 아래층이 꽉 차 있어 출력칸(같은 층 인접 빈칸)이 없다 → 위층에만 놓는다.
        self._turtle_place_containers(level, stack, params, rng)

        # ② ÷3 패딩 — **삭제 대신 추가**. 꼭대기(쉬움) 또는 바닥(어려움)에 1~2개 덧댄다.
        #    (기존 _finalize_divisibility_guarantee 는 타일을 지워 꼭대기 층을 통째로 비우기도 했다.)
        self._turtle_pad_div3(level, stack, params, rng)

        for i in range(int(level.get("layer") or 0)):
            for tile in ((level.get(f"layer_{i}") or {}).get("tiles") or {}).values():
                if isinstance(tile, list) and tile and tile[0] == "t0":
                    tile[0] = rng.choice(tile_types)

        # ③ 속성 기믹(ice/chain/grass/...) — 호출자가 obstacle_types 를 넘긴 경우만.
        #    [언락 강제] 호출자가 무엇을 넘기든 미해금 기믹은 여기서 제거(방어선).
        _allowed = self.filter_gimmicks_by_unlock(params.obstacle_types, params.level_number)
        if _allowed:
            try:
                _p = copy.copy(params)
                _p.obstacle_types = _allowed
                level = self._add_obstacles(level, _p)
            except Exception as ex:  # noqa: BLE001
                logger.warning(f"[TURTLE] 기믹 배치 스킵: {ex}")
            # 이웃이 없어 영원히 못 푸는 chain/grass 정리(보스 경로와 동일 규칙)
            level = self._turtle_strip_impossible_attrs(level)

        level = self._ensure_tutorial_unlock_gimmick(level, params.level_number)
        level = self._finalize_divisibility_guarantee(level)
        level = self._finalize_level(level)
        # ÷3 보정이 꼭대기(1~2타일) 층을 통째로 비울 수 있다 → 빈 상위층 제거(층수 재계산).
        n = int(level.get("layer") or 0)
        while n > 1 and not ((level.get(f"layer_{n-1}") or {}).get("tiles") or {}):
            level.pop(f"layer_{n-1}", None)
            n -= 1
        level["layer"] = n

        report = get_analyzer().analyze(level)
        return GenerationResult(
            level_json=level,
            actual_difficulty=report.score / 100.0,
            grade=report.grade,
            generation_time_ms=int((time.time() - start_time) * 1000),
            playability_warning=False,
            estimated_clear_rate=1.0,
        )

    def _build_concentric_layers(self, level: Dict[str, Any], active_layers: List[int],
                                 cols: int, rows: int, params: "GenerationParams") -> List[Tuple[int, str]]:
        """동심 침식 스택. layer_0 = 실제 패턴 모양(다양) → 위로 갈수록 테두리 벗겨(erode) 중앙 축소
        = 거북등껍질 코히어런트 스택. 바닥에 모양 다양성 유지(사각섬 고정 아님). 2층마다 한 겹 완만 침식.
        각 층 = 그 층 그리드 중앙 정렬. 타입 t0(파이프라인/역생성 배정). 상위 무작위 흩어짐 제거."""
        import random as _r
        base = cols + 1

        def _erode(cells):
            nb = ((1, 0), (-1, 0), (0, 1), (0, -1))
            return {(x, y) for (x, y) in cells if all((x + dx, y + dy) in cells for dx, dy in nb)}

        def _fill_holes(cells):
            out = set(cells)
            for (x, y) in list(cells):
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (nx, ny) not in cells:
                        cnt = sum(1 for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                                  if (nx + ddx, ny + ddy) in cells)
                        if cnt >= 3:
                            out.add((nx, ny))
            return out

        # 마스터 모양: 패턴 지정 시 그것, 아니면 랜덤(채움 좋은 패턴 위주) → 레벨마다 다양.
        pidx = params.pattern_index if params.pattern_index is not None else _r.choice([0, 1, 2, 3, 8, 13, 16, 20])
        try:
            master_pos = self._generate_aesthetic_positions(
                base, base, target_count=1000, pattern_index=pidx,
                target_difficulty=params.target_difficulty)
            master = set()
            for p in master_pos:
                x, y = map(int, p.split("_"))
                master.add((x, y))
            master = _fill_holes(master)
        except Exception:
            master = set()
        # 너무 성기면 채운 다이아몬드로 폴백
        if len(master) < base * 2:
            c = base // 2
            master = {(x, y) for x in range(base) for y in range(base) if abs(x - c) + abs(y - c) <= c}

        # 침식 스택(완만: 2층마다 한 겹). 층수만큼 확보(더 침식 안 되면 마지막 유지).
        stack = []
        cur = set(master)
        for i in range(len(active_layers)):
            stack.append(set(cur))
            if i % 2 == 1:
                nxt = _erode(cur)
                if len(nxt) >= 3:
                    cur = nxt

        all_positions: List[Tuple[int, str]] = []
        for i, layer_idx in enumerate(active_layers):
            odd = (layer_idx % 2 == 1)
            gcol = cols if odd else cols + 1
            grow = rows if odd else rows + 1
            cells = stack[i] if i < len(stack) else stack[-1]
            # 이 층 그리드 중앙으로 이동
            xs = [x for x, y in cells]; ys = [y for x, y in cells]
            if not xs:
                continue
            bx = (min(xs) + max(xs)) / 2.0; by = (min(ys) + max(ys)) / 2.0
            ox = int(round(gcol / 2.0 - 0.5 - bx)); oy = int(round(grow / 2.0 - 0.5 - by))
            tiles: Dict[str, Any] = {}
            for (x, y) in cells:
                nx, ny = x + ox, y + oy
                if 0 <= nx < gcol and 0 <= ny < grow:
                    pos = f"{nx}_{ny}"
                    tiles[pos] = ["t0", ""]
                    all_positions.append((layer_idx, pos))
            lk = f"layer_{layer_idx}"
            if lk not in level or not isinstance(level.get(lk), dict):
                level[lk] = {}
            level[lk]["col"] = str(gcol)
            level[lk]["row"] = str(grow)
            level[lk]["tiles"] = tiles
            level[lk]["num"] = str(len(tiles))
        logger.info(f"[CONCENTRIC] pattern={pidx} {len(active_layers)}층, 총 {len(all_positions)} 위치")
        return all_positions

    def _assemble_units_in_mask(self, mask, budget, gcol, grow, rng):
        """valid_mask(받침 있는 칸) 안에 유닛을 budget(3배수)만큼 조립. 매 스텝 '맞는 가장 큰 유닛'
        부터 시도하고 안 맞으면 작은 크기로 폴백 → 빈 층 방지. [대칭] 세로 중심축 기준 좌우 짝 배치
        우선(양쪽 다 마스크에 들어올 때만) → 균형. 안 되면 단독(축 위/예산 빠듯). 겹침 0·floating 0."""
        from .unit_templates import units_by_size
        _UBS = units_by_size()
        sizes_desc = sorted(_UBS.keys(), reverse=True)
        placed = set()
        if not mask:
            return placed
        axis = (gcol - 1) / 2.0                    # 세로 중심축(좌우 대칭)
        my = sum(y for x, y in mask) / len(mask)

        def _mirror(pc):
            return {(gcol - 1 - px, py) for (px, py) in pc}

        remaining = (budget // 3) * 3
        guard = 0
        while remaining >= 3 and guard < 100:
            guard += 1
            step_placed = False
            for sz in [s for s in sizes_desc if s <= remaining]:
                units = list(_UBS.get(sz, []))
                rng.shuffle(units)
                for unit in units:
                    pair_cands, single_cands = [], []
                    for ox in range(0, gcol - unit.w + 1):
                        for oy in range(0, grow - unit.h + 1):
                            pc = unit.placed(ox, oy)
                            if not (pc <= mask) or (pc & placed):
                                continue
                            cx = ox + unit.w / 2.0
                            dist = (cx - axis) ** 2 + ((oy + unit.h / 2.0) - my) ** 2
                            pcm = _mirror(pc)
                            if pcm == pc:                      # 축 위 자기대칭 → 단독
                                single_cands.append((dist, pc))
                            elif (remaining >= 2 * sz and pcm <= mask
                                  and not (pcm & placed) and not (pcm & pc)):
                                pair_cands.append((dist, pc | pcm))   # 좌우 짝(양쪽)
                            else:
                                single_cands.append((dist, pc))
                    chosen = None
                    src = pair_cands or single_cands            # 짝 우선
                    if src:
                        src.sort(key=lambda c: c[0])
                        chosen = rng.choice(src[:min(len(src), 5)])[1]
                    if chosen:
                        placed |= chosen
                        remaining -= len(chosen)
                        step_placed = True
                        break
                if step_placed:
                    break
            if not step_placed:
                break  # 어떤 유닛도 안 맞음(마스크 소진)
        return placed

    # [유닛 조립 v2] 난이도 → 유닛 크기/개수. 층당 개수를 **고정 소수**로 제한해 조밀 폭주를 막는다.
    # 근거: v1 은 예산(budget)을 큰 유닛부터 꽉 채워(budget-fill) 조밀 구조가 되고, 실측 ~40% 가
    # 봇-언클리어러블(clear 0.0)이었다 → 프로덕션 1300/1500 통과가 붕괴해 강제 OFF 됐다.
    # v2 는 '성긴 대칭' — 층당 1~3 유닛만 좌우대칭으로 얹어 선택 여지를 남긴다.
    UNIT_V2_DIFFICULTY_PLAN: List[Tuple[float, Tuple[int, ...], Tuple[int, int]]] = [
        # (난이도 상한, 선호 유닛 크기들, (층당 최소, 최대))  — v3에서 미사용(이력 보존)
        (0.3, (3, 6), (1, 2)),
        (0.5, (6, 9), (2, 2)),
        (0.7, (9, 12), (2, 3)),
        (1.01, (12, 15), (3, 3)),
    ]

    # [유닛 조립 v3] 슬롯 모델 — 난이도는 **개수**로만 조절. 크기는 그리드가 결정한다.
    #
    # v2 결함: 개수(1~3)만 제한하고 크기를 난이도로 키워(12·15셀 = 바운딩박스 4~5) 한쪽 폭(3칸)을
    # 넘겨 중앙을 가로지르는 통짜 배치가 됐다 → "3개인데 절반 이상이 사각형으로 덮임".
    #
    # v3 규칙:
    #   1) 유닛은 **바운딩박스 정사각 슬롯**을 차지한다(3×2 유닛 → 3×3 슬롯).
    #   2) 좌우대칭 배치 → 중심축 기준 **한쪽에만** 놓고 미러. 홀수 그리드는 중앙열 제외.
    #      한쪽 폭 = 짝수 G: G/2,  홀수 G: (G-1)/2   → 슬롯 크기 s ≤ 한쪽 폭
    #   3) 슬롯끼리 **겹침 금지**(격자 분할).
    #   4) 같은 층에는 **서로 다른 모양만** → 시각적 다양성, 같은 네모 반복 방지.
    #   실제 프로덕션 그리드(5·6·7)에서 한쪽 폭은 2~3 → 사용 유닛은 셀 3~9(박스 2~3)로 자연 제한.
    UNIT_V3_SLOTS_BY_DIFFICULTY: List[Tuple[float, Tuple[int, int]]] = [
        # (난이도 상한, (한쪽 최소 슬롯수, 최대 슬롯수))
        (0.3, (1, 1)),
        (0.5, (1, 2)),
        (0.7, (2, 2)),
        (1.01, (2, 3)),
    ]

    def _symmetrize_unit_layers(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[유닛조립] 각 층을 좌우대칭으로 복원(미러 셀 추가). 바닥층(주 패턴)은 건드리지 않는다.

        빌더는 대칭 배치하지만 이후 시프트/클램프/OOB 제거가 한쪽만 잘라 대칭을 깬다.
        여기서 미러 위치에 같은 타입 타일을 채워 복원한다.
        - 추가 셀 타입은 t0(런타임 분배) → 타입 카운트 왜곡 없음
        - floating 은 하위층 지지셀을 함께 넣어 방지
        - ÷3 은 호출 직후 `_finalize_divisibility_guarantee` 가 재보장
        """
        n = int(level.get("layer", 0) or 0)
        added = 0
        for i in range(1, n):  # 바닥층(0) 제외 — 디자인 패턴 보존
            ld = level.get(f"layer_{i}")
            if not isinstance(ld, dict):
                continue
            tiles = ld.get("tiles")
            if not isinstance(tiles, dict) or not tiles:
                continue
            try:
                col = int(ld.get("col"))
            except (TypeError, ValueError):
                continue
            for pos in list(tiles.keys()):
                try:
                    x, y = map(int, pos.split("_"))
                except ValueError:
                    continue
                mx = col - 1 - x
                if mx == x or not (0 <= mx < col):
                    continue
                mpos = f"{mx}_{y}"
                if mpos in tiles:
                    continue
                tiles[mpos] = ["t0", ""]
                added += 1
                # 하위층 지지 보강(floating 방지)
                below = level.get(f"layer_{i-1}")
                if isinstance(below, dict) and isinstance(below.get("tiles"), dict):
                    try:
                        bcol = int(below.get("col"))
                    except (TypeError, ValueError):
                        continue
                    from .unit_templates import get_cover_offsets
                    offs = get_cover_offsets(i - 1, i, bcol, col)
                    bt = below["tiles"]
                    if not any(f"{mx-dx}_{y-dy}" in bt for dx, dy in offs):
                        for dx, dy in offs:
                            lx, ly = mx - dx, y - dy
                            if 0 <= lx < bcol and 0 <= ly < int(below.get("row", bcol)):
                                bt[f"{lx}_{ly}"] = ["t0", ""]
                                added += 1
                                break
        if added:
            logger.info(f"[UNIT_SYMMETRY] 미러 셀 {added}개 추가해 좌우대칭 복원")
        return level

    def _build_unit_assembly_layers(self, level: Dict[str, Any], active_layers: List[int],
                                    cols: int, rows: int, params: "GenerationParams",
                                    n_target: int) -> List[Tuple[int, str]]:
        """[유닛 조립 v2 — 성긴 대칭] 바닥층 = 주 패턴(디자인 모양 유지),
        위층 = 난이도별 소형 유닛 **1~3개만** 좌우대칭 배치(아래층 받침 안).

        v1 대비 변경(재설계 계획 PLAN_unit_assembly_sparse_symmetric.md):
          - budget-fill / top-up 루프 **제거** → 타일수는 결과값(목표 강제 안 함)
          - 밀도역전(성긴패턴이면 솔리드를 바닥에) 분기 **제거** — 조밀 주범
          - 층당 유닛 수 **고정 상한**(1~3) → 조밀 폭주 차단
          - 좌우 대칭 배치 유지(비주얼 코히어런스)
        불변식: floating 0(받침 마스크 + 사후 그림자 보강), 겹침 0, 타입은 t0(뒤에서 배정).
        """
        import random as _r
        from .unit_templates import valid_support_mask, get_cover_offsets, units_by_size

        n = len(active_layers)
        pidx = params.pattern_index if params.pattern_index is not None else _r.choice([0, 1, 2, 3, 8, 13, 16, 20])
        pos_map: Dict[int, Set[Tuple[int, int]]] = {}
        all_positions: List[Tuple[int, str]] = []

        def _gcol(layer_idx):
            return cols if (layer_idx % 2 == 1) else cols + 1

        def _aesthetic(gc):
            try:
                mp = self._generate_aesthetic_positions(
                    gc, gc, target_count=1000, pattern_index=pidx,
                    target_difficulty=params.target_difficulty)
                s = {(x, y) for x, y in (map(int, p.split("_")) for p in mp) if 0 <= x < gc and 0 <= y < gc}
            except Exception:  # noqa: BLE001
                s = set()
            if len(s) < 6:
                c = gc // 2
                s = {(x, y) for x in range(gc) for y in range(gc) if abs(x - c) + abs(y - c) <= c}
            return s

        # ── 난이도 → 한쪽 슬롯 개수 (크기는 그리드가 결정) ──
        _diff = float(getattr(params, "target_difficulty", 0.5) or 0.5)
        smin, smax = 1, 1
        for cap, cnt in self.UNIT_V3_SLOTS_BY_DIFFICULTY:
            if _diff < cap:
                smin, smax = cnt
                break

        _UBS = units_by_size()
        ALL_UNITS = [u for lst in _UBS.values() for u in lst]

        def _bbox(u):
            return max(u.w, u.h)

        def _half_width(gc):
            """중심축 한쪽 폭. 홀수 그리드는 중앙열을 비워 대칭축으로 쓴다."""
            return (gc - 1) // 2 if gc % 2 == 1 else gc // 2

        def _is_slab(cs):
            """의미없는 통짜/막대 실루엣인가 — 유닛∪미러 결과에 적용.

            - 폭 4↑ 꽉 찬 직사각형: 통짜 덮개(예: R3x2+미러 = 6×2)
            - 높이 1 · 폭 5↑: 가로 막대(예: I3_h+미러 = `###.###`)
            """
            xs = [x for x, _ in cs]
            ys = [y for _, y in cs]
            w = max(xs) - min(xs) + 1
            h = max(ys) - min(ys) + 1
            if h == 1 and w >= 5:
                return True
            return len(cs) == w * h and w >= 4

        def _place_slot_symmetric(mask, gc, want_slots, avoid_names=frozenset()):
            """[v3.1] 유닛의 **정사각 바운딩박스**를 슬롯으로 보고 좌우대칭 배치.

            v3 결함(실측): 슬롯 원점을 `range(0, half-s+1, s)` 로 잡아 half=3·s=3/2 모두
            ox=0 만 나왔다 → 유닛이 항상 최외곽 열에 고정 → 미러하면 양 끝 두 덩어리 =
            바운딩박스가 매번 전폭인 '가로 직사각형' 실루엣만 반복. 또 첫 크기에서 하나라도
            놓이면 즉시 return 해 크기 혼합이 없었고, 중앙축 배치 경로가 아예 없었다.

            v3.1 규칙(사용자 모델 유지):
              1) 유닛 슬롯 = 자기 바운딩박스 정사각(3×2 유닛 → 3×3). 슬롯끼리 겹침 금지.
                 (미러 슬롯도 함께 예약해 반대편 침범 차단)
              2) 슬롯 원점은 **자유 좌표(step 1)** — 격자 배수 제약 제거 → 가로/세로 위치 다양화
              3) 홀수 그리드는 중앙축에 **자기대칭 유닛 1개** 배치 가능 → '양 날개'만 나오는 단조로움 제거
              4) 유닛∪미러가 폭4↑ 통짜 직사각형이면 거부(예: R3x2+미러 = 6×2 슬래브)
              5) 같은 층 같은 모양 금지 + 바로 아래층에서 쓴 모양 회피(avoid_names) → 층간 다양성
            반환: (배치셀, 사용한 유닛 이름들)
            """
            placed: Set[Tuple[int, int]] = set()
            used_names: Set[str] = set()
            if not mask:
                return placed, used_names
            half = _half_width(gc)
            if half < 2:
                return placed, used_names
            odd = (gc % 2 == 1)
            boxes: List[Tuple[int, int, int]] = []   # (x, y, size) 점유 슬롯

            def _box_free(px, py, b):
                return all(not (px < bx + bb and bx < px + b and py < by + bb and by < py + b)
                           for (bx, by, bb) in boxes)

            def _cands(b, axis_mode):
                """bbox=b 유닛의 유효 배치 후보 전수. axis_mode=중앙축 자기대칭 배치."""
                out = []
                for u in ALL_UNITS:
                    if _bbox(u) != b or u.name in used_names or u.name in avoid_names:
                        continue
                    if axis_mode:
                        if not odd or b % 2 == 0:
                            continue          # 중앙축에 딱 맞으려면 홀수 박스만 가능
                        xs = [gc // 2 - (b - 1) // 2]
                    else:
                        xs = list(range(0, half - b + 1))
                    for px in xs:
                        for py in range(0, gc - b + 1):
                            pc = u.placed(px + (b - u.w) // 2, py + (b - u.h) // 2)
                            if not (pc <= mask):
                                continue
                            mc = {(gc - 1 - x, y) for (x, y) in pc}
                            if axis_mode:
                                if mc != pc:          # 자기대칭 아닌 유닛은 축에 못 놓음
                                    continue
                                if (pc & placed) or not _box_free(px, py, b):
                                    continue
                                out.append((u, px, py, b, pc))
                            else:
                                if (mc & pc) or ((pc | mc) & placed):
                                    continue
                                mbx = gc - b - px      # 미러 슬롯 좌상단 x
                                if not _box_free(px, py, b) or not _box_free(mbx, py, b):
                                    continue
                                if _is_slab(pc | mc):
                                    continue
                                out.append((u, px, py, b, pc | mc))
                return out

            sizes = list(range(min(half, 4), 1, -1))   # 큰 박스 우선(모양이 또렷)
            got = 0
            # 중앙축 유닛(홀수 그리드) — 절반 확률로 시도. 성공 시 슬롯 1개 소비.
            if odd and _r.random() < 0.55:
                for b in sizes:
                    pool = _cands(b, True)
                    if pool:
                        u, px, py, bb, cs = _r.choice(pool)
                        placed |= cs
                        boxes.append((px, py, bb))
                        used_names.add(u.name)
                        got += 1
                        break
            # 좌우 짝 유닛 — want 만큼. 큰 박스부터 후보가 있는 크기를 사용(조기 return 없음).
            while got < want_slots:
                pool = []
                for b in sizes:
                    pool = _cands(b, False)
                    if pool:
                        break
                if not pool:
                    break
                u, px, py, bb, cs = _r.choice(pool)
                placed |= cs
                boxes.append((px, py, bb))
                boxes.append((gc - bb - px, py, bb))
                used_names.add(u.name)
                got += 1
            return placed, used_names

        def _silhouette_score(cs):
            """층 실루엣의 '볼거리' 점수. 1행/1열 막대와 통짜 사각형을 밀어낸다."""
            if not cs:
                return -1.0
            xs = [x for x, _ in cs]
            ys = [y for _, y in cs]
            w = max(xs) - min(xs) + 1
            h = max(ys) - min(ys) + 1
            if h == 1 or w == 1:
                return 0.0                      # 막대 — 최하점(다른 후보 없으면만 채택)
            fill = len(cs) / float(w * h)
            if fill >= 0.95:
                return 0.1                      # 통짜 직사각형
            # 세로로도 퍼지고(h≥2) 채움이 과하지 않을수록 좋음
            s = min(2.0, h * 0.35 + (1.0 - abs(fill - 0.5)) * 0.8)
            if w >= h * 2.5:
                s -= 0.35        # 납작한 가로형(폭≫높이) 감점 — "가로 직사각형" 인상 억제
            return s

        # ── 바닥층 = 주 패턴(디자인 모양 유지) ──
        l0 = active_layers[0]
        pos_map[l0] = _aesthetic(_gcol(l0))

        # ── 위층 = 슬롯 기반 대칭 유닛층 ──
        _prev_names: Set[str] = set()
        for i, layer_idx in enumerate(active_layers[1:]):
            gc = _gcol(layer_idx)
            below = active_layers[active_layers.index(layer_idx) - 1]
            mask = valid_support_mask(pos_map[below], below, layer_idx, _gcol(below), gc, gc)
            # 위로 갈수록 슬롯 수를 줄여 탑 실루엣(자연 수렴). 최소 1개는 유지.
            want = max(1, _r.randint(smin, smax) - (i // 2))
            # [실루엣 품질] 유닛 하나하나는 합법이어도 **합집합**이 1행 막대/통짜가 될 수 있다
            # (예: 중앙축 I3_h + 좌우 짝 → `#####`). 층 단위로 K회 뽑아 최고 점수를 채택.
            best, best_names, best_score = set(), set(), -1.0
            for _try in range(6):
                cand, cnames = _place_slot_symmetric(mask, gc, want, avoid_names=_prev_names)
                if not cand and _prev_names:
                    cand, cnames = _place_slot_symmetric(mask, gc, want)
                score = _silhouette_score(cand)
                if score > best_score:
                    best, best_names, best_score = cand, cnames, score
                if best_score >= 1.0:      # 충분히 좋은 실루엣이면 조기 종료
                    break
            pos_map[layer_idx], _names = best, best_names
            _prev_names = _names


        # [floating 정화] 상위 타일이 하위 미덮으면 하위에 지지셀(그림자) 추가 → floating 0 보장.
        # top-down 처리(층 j 고치면 j-1 성장 → 다음 j-1 검사에 반영). 몇 셀 늘지만 버퍼 내.
        for j in range(len(active_layers) - 1, 0, -1):
            li = active_layers[j]
            below = active_layers[j - 1]
            uc = _gcol(li)
            bc = _gcol(below)
            offs = get_cover_offsets(below, li, bc, uc)
            for (ux, uy) in list(pos_map.get(li, set())):
                if not any((ux - dx, uy - dy) in pos_map.get(below, set()) for dx, dy in offs):
                    for (dx, dy) in offs:
                        lx, ly = ux - dx, uy - dy
                        if 0 <= lx < bc and 0 <= ly < bc:
                            pos_map.setdefault(below, set()).add((lx, ly))
                            break

        # write
        for layer_idx in active_layers:
            odd = (layer_idx % 2 == 1)
            gcol = cols if odd else cols + 1
            grow = rows if odd else rows + 1
            cells = pos_map[layer_idx]
            tiles: Dict[str, Any] = {}
            for (x, y) in cells:
                pos = f"{x}_{y}"
                tiles[pos] = ["t0", ""]
                all_positions.append((layer_idx, pos))
            lk = f"layer_{layer_idx}"
            if lk not in level or not isinstance(level.get(lk), dict):
                level[lk] = {}
            level[lk]["col"] = str(gcol)
            level[lk]["row"] = str(grow)
            level[lk]["tiles"] = tiles
            level[lk]["num"] = str(len(tiles))
        logger.info(f"[UNIT_ASSEMBLY_V3] pattern={pidx} {n}층 슬롯대칭(diff={_diff:.2f} "
                    f"한쪽슬롯{smin}~{smax}) 총{len(all_positions)}타일")
        return all_positions

    def _place_key_tiles(self, level: Dict[str, Any], count: int) -> None:
        """
        Place 'key' tiles in the level by converting existing tiles.

        key 기믹 작동 방식:
        - key 타일 3개를 모으면 잠긴 버퍼 슬롯 1개가 해제됨
        - unlockTile * 3개의 key 타일이 필요

        Args:
            level: Level JSON to modify
            count: Number of key tiles to place (should be unlockTile * 3)
        """
        if count <= 0:
            return

        # Collect all tile positions from all layers
        all_positions = []
        max_layer = level.get("layer", 5)

        for layer_idx in range(max_layer):
            layer_key = f"layer_{layer_idx}"
            if layer_key not in level:
                continue

            tiles = level[layer_key].get("tiles", {})
            for pos, tile_data in tiles.items():
                if tile_data and len(tile_data) >= 2:
                    tile_type = tile_data[0]
                    gimmick = tile_data[1] if len(tile_data) > 1 else ""
                    # Only convert regular tiles (t0~t15) without gimmicks
                    if tile_type.startswith("t") and not gimmick:
                        all_positions.append((layer_idx, pos))

        # Randomly select positions to convert to key tiles
        if len(all_positions) < count:
            # Not enough tiles, use what we have
            positions_to_convert = all_positions
        else:
            positions_to_convert = random.sample(all_positions, count)

        # Convert selected tiles to key tiles
        for layer_idx, pos in positions_to_convert:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]
            if pos in tiles:
                original_tile = tiles[pos]
                # Keep original tile type but set ID to "key"
                # Format: [tile_type, gimmick, extras...]
                # For key tiles: the tile ID becomes "key"
                tiles[pos] = ["key", original_tile[1] if len(original_tile) > 1 else ""]

    def _ensure_tile_divisibility(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Lightweight validation: Ensure all tile type counts are divisible by 3.

        This is a fast check that doesn't require simulation but catches
        basic structural issues that would make the level impossible to clear.

        Strategy:
        1. Count tiles by type (including stack/craft internal tiles)
        2. For types with remainder != 0, adjust by changing some tiles to other types
        """
        # [v15.36] 고정 레이아웃 레벨: 타일 변경 건너뛰기 (이미 3의 배수로 설계됨)
        if level.get("_skip_tile_redistribution", False):
            return level

        from collections import defaultdict
        import random

        # Count tiles by type
        type_counts = defaultdict(int)
        type_positions = defaultdict(list)  # Track positions for each type

        num_layers = level.get("layer", 8)
        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            layer_data = level.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) == 0:
                    continue

                tile_type = tile_data[0]
                if tile_type in ("t0", "empty", "", None):
                    continue

                # Handle stack/craft tiles
                if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                    # Count internal tiles
                    if len(tile_data) > 2:
                        inner = tile_data[2]
                        if isinstance(inner, list):
                            for inner_tile in inner:
                                if inner_tile and isinstance(inner_tile, str) and inner_tile not in ("t0", "empty"):
                                    type_counts[inner_tile] += 1
                        elif isinstance(inner, dict):
                            inner_count = inner.get("totalCount", inner.get("count", 1))
                            # Internal tiles are typically t0, will be distributed
                    # The container tile itself (top tile)
                    type_counts[tile_type] += 1
                    type_positions[tile_type].append((layer_idx, pos))
                else:
                    type_counts[tile_type] += 1
                    type_positions[tile_type].append((layer_idx, pos))

        # Find types with remainder issues
        bad_types = [(t, c, c % 3) for t, c in type_counts.items()
                     if c % 3 != 0 and isinstance(t, str) and not t.startswith("stack_") and not t.startswith("craft_")]

        if not bad_types:
            return level  # All good

        logger.info(f"[_ensure_tile_divisibility] Fixing {len(bad_types)} types: {bad_types[:5]}")

        # Try to fix by pairing remainder=1 with remainder=2
        rem1_types = [t for t, c, r in bad_types if r == 1]
        rem2_types = [t for t, c, r in bad_types if r == 2]

        # Strategy: Move tiles between types to fix remainders
        # If rem1 type gives 1 tile to rem2 type, both become divisible by 3
        for t1 in rem1_types[:]:
            if not rem2_types:
                break
            t2 = rem2_types.pop(0)

            # Change one t1 tile to t2
            if type_positions[t1]:
                layer_idx, pos = type_positions[t1].pop()
                layer_key = f"layer_{layer_idx}"
                if layer_key in level and "tiles" in level[layer_key]:
                    level[layer_key]["tiles"][pos][0] = t2
                    type_positions[t2].append((layer_idx, pos))
                    rem1_types.remove(t1)
                    logger.debug(f"[_ensure_tile_divisibility] Changed {t1} -> {t2} at {pos}")

        # For remaining issues, add 1 or 2 tiles by changing other types
        # This is a simplified fix - full fix would need more complex logic

        return level

    def _validate_dock_tile_compatibility(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate useTileCount is compatible with unlockTile (dock capacity).

        CRITICAL: 독 슬롯 수 대비 타일 종류가 너무 많으면 데드락 발생
        - 사용 가능 독 슬롯: 7 - unlockTile
        - 안전 기준: useTileCount <= available_dock + 2

        예시:
        - unlockTile=0 (7칸): useTileCount <= 9 (안전)
        - unlockTile=1 (6칸): useTileCount <= 8 (안전)
        - unlockTile=2 (5칸): useTileCount <= 7 (안전)

        위반 시:
        1. useTileCount 감소 (우선)
        2. unlockTile 감소 (백업)

        Args:
            level: Level JSON to validate and fix

        Returns:
            Fixed level JSON
        """
        unlock_tile = level.get("unlockTile", level.get("xUnlockTile", 0))
        use_tile_count = level.get("useTileCount", 6)

        # 사용 가능 독 슬롯
        available_dock = 7 - unlock_tile

        # [독 천장 제거 2026-07-01] 캡 상한을 카탈로그 최대(15)로 고정 → 사실상 무캡.
        # useTileCount는 그래프값 그대로. 데드락은 _ensure_no_deadlock + 봇검증이 사후 거름.
        safe_max_tile_count = self.MAX_USE_TILE_COUNT

        if use_tile_count > safe_max_tile_count:
            original_tile_count = use_tile_count
            original_unlock_tile = unlock_tile

            # 해결 방법 1: useTileCount 감소
            new_tile_count = safe_max_tile_count

            # 해결 방법 2: unlockTile도 조정 (너무 많이 감소하면)
            if new_tile_count < 5:  # 최소 5종류는 유지
                # unlockTile 감소로 독 슬롯 확보
                while new_tile_count < 5 and unlock_tile > 0:
                    unlock_tile -= 1
                    available_dock = 7 - unlock_tile
                    safe_max_tile_count = available_dock + 2
                    new_tile_count = min(original_tile_count, safe_max_tile_count)

                level["unlockTile"] = unlock_tile
                if "xUnlockTile" in level:
                    level["xUnlockTile"] = unlock_tile

            level["useTileCount"] = new_tile_count

            logger.warning(
                f"[_validate_dock_tile_compatibility] "
                f"Fixed incompatible tile/dock combo: "
                f"useTileCount {original_tile_count}→{new_tile_count}, "
                f"unlockTile {original_unlock_tile}→{unlock_tile}, "
                f"available_dock={available_dock}"
            )

            # CRITICAL FIX: Convert out-of-range tile types to valid range
            # When useTileCount is reduced, existing tiles may be out of range
            # Strategy: Count current distribution, then redistribute to maintain 3-divisibility
            num_layers = level.get("layer", 8)
            valid_range = {f"t{i}" for i in range(1, new_tile_count + 1)}
            valid_types_list = [f"t{i}" for i in range(1, new_tile_count + 1)]

            # Step 1: Count tiles by type and identify out-of-range positions
            type_counts: Dict[str, int] = {}
            out_of_range_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)

            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                            continue
                        if tile_type.startswith("t"):
                            if tile_type in valid_range:
                                type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                            else:
                                out_of_range_positions.append((i, pos))

            if out_of_range_positions:
                # Step 2: Calculate how many tiles each valid type needs to be 3-divisible
                # Total tiles to redistribute
                tiles_to_redistribute = len(out_of_range_positions)

                # Find types that need more tiles to be 3-divisible
                type_needs: Dict[str, int] = {}
                for t in valid_types_list:
                    current = type_counts.get(t, 0)
                    remainder = current % 3
                    if remainder == 1:
                        type_needs[t] = 2  # Need 2 more to make divisible
                    elif remainder == 2:
                        type_needs[t] = 1  # Need 1 more to make divisible
                    else:
                        type_needs[t] = 0  # Already divisible

                # Step 3: Redistribute out-of-range tiles
                redistributed = 0
                for layer_idx, pos in out_of_range_positions:
                    layer_key = f"layer_{layer_idx}"
                    tile_data = level[layer_key]["tiles"].get(pos)
                    if not tile_data:
                        continue

                    # Find best type to assign (prioritize types that need more)
                    best_type = None
                    for t in sorted(type_needs.keys(), key=lambda x: -type_needs.get(x, 0)):
                        if type_needs.get(t, 0) > 0:
                            best_type = t
                            break

                    if not best_type:
                        # All types are divisible, pick one that can accept 3 more
                        # Find type with lowest count
                        best_type = min(valid_types_list, key=lambda x: type_counts.get(x, 0))

                    tile_data[0] = best_type
                    type_counts[best_type] = type_counts.get(best_type, 0) + 1
                    type_needs[best_type] = max(0, type_needs.get(best_type, 0) - 1)
                    redistributed += 1

                logger.info(f"[_validate_dock_tile_compatibility] Redistributed {redistributed} tiles to valid range t1~t{new_tile_count}")

        return level

    def _validate_and_fix_key_tile_count(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and fix key tile count for game client compatibility.

        CRITICAL: 게임 클라이언트에서 unlockTile > 0이면:
        - t0 분배(TileDistributor)가 key 타일을 자동 생성함
        - 따라서 레벨 JSON에 명시적 "key" 타일이 있으면 안 됨 (이중 생성 방지)

        이 함수는:
        - unlockTile > 0: 모든 명시적 key 타일을 t0으로 변환
        - unlockTile = 0: key 타일 검증하지 않음 (t0 분배 없음)

        Args:
            level: Level JSON to validate and fix

        Returns:
            Fixed level JSON (명시적 key 타일 제거됨)
        """
        unlock_tile = level.get("unlockTile", level.get("xUnlockTile", 0))
        if unlock_tile <= 0:
            return level  # No t0-based key distribution, keep explicit keys if any

        num_layers = level.get("layer", 8)

        # Find all explicit key tiles
        key_positions = []  # [(layer_idx, pos), ...]
        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and tile_data and tile_data[0] == "key":
                    key_positions.append((layer_idx, pos))

        if key_positions:
            # CRITICAL: unlockTile > 0이면 게임 클라이언트가 t0 분배로 key 생성
            # 명시적 key 타일이 있으면 이중 생성됨 → 모두 t0으로 변환
            logger.info(
                f"[_validate_and_fix_key_tile_count] unlockTile={unlock_tile}, "
                f"found {len(key_positions)} explicit key tiles. "
                f"Converting ALL to t0 (game client will generate keys from t0 distribution)."
            )

            for layer_idx, pos in key_positions:
                layer_key = f"layer_{layer_idx}"
                tiles = level[layer_key]["tiles"]
                if pos in tiles:
                    original = tiles[pos]
                    gimmick = original[1] if len(original) > 1 else ""
                    tiles[pos] = ["t0", gimmick]

        return level

    def reshuffle_positions(self, level: Dict[str, Any], params: Optional[GenerationParams] = None) -> Dict[str, Any]:
        """
        Reshuffle tile positions while keeping tile types, gimmicks, and layer structure.

        This method:
        1. Extracts all tile data (type, gimmick, extra) from each layer
        2. Generates new positions using smart placement for gimmick tiles
        3. Places tiles with neighbor-dependent gimmicks (chain, link, grass) first
        4. Ensures these tiles have valid neighbors

        Args:
            level: Existing level JSON to reshuffle
            params: Optional generation params for validation

        Returns:
            New level JSON with reshuffled positions
        """
        import copy

        # [형태보존] 패턴/유닛조립/동심 레벨은 위치 재배치 금지 — 셔플이 모양·받침(coverage)을
        # 깨뜨려 유닛 흩어짐·floating 유발. 난이도는 타입 재배정(역생성/재분배)으로만 조정.
        if level.get("_preserve_pattern"):
            return copy.deepcopy(level)

        new_level = copy.deepcopy(level)

        num_layers = new_level.get("layer", 8)

        # Gimmicks that require at least one clearable neighbor
        NEIGHBOR_DEPENDENT_GIMMICKS = {'chain', 'link', 'link_s', 'link_n', 'link_e', 'link_w', 'grass'}

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            if layer_key not in new_level:
                continue

            layer_data = new_level[layer_key]
            tiles = layer_data.get("tiles", {})
            if not tiles:
                continue

            # Extract tile data into categories
            goal_tiles = []           # [(tile_type, gimmick, extra), ...]
            gimmick_tiles = []        # Tiles with neighbor-dependent gimmicks
            other_gimmick_tiles = []  # Tiles with other gimmicks (ice, frog, bomb, etc.)
            plain_tiles = []          # Tiles without gimmicks

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list):
                    continue
                tile_type = tile_data[0] if len(tile_data) > 0 else "t1"
                gimmick = tile_data[1] if len(tile_data) > 1 else ""
                extra = tile_data[2] if len(tile_data) > 2 else None

                if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                    goal_tiles.append((tile_type, gimmick, extra))
                elif gimmick and any(gimmick.startswith(g) for g in NEIGHBOR_DEPENDENT_GIMMICKS):
                    gimmick_tiles.append((tile_type, gimmick, extra))
                elif gimmick:
                    other_gimmick_tiles.append((tile_type, gimmick, extra))
                else:
                    plain_tiles.append((tile_type, gimmick, extra))

            # Get grid dimensions from layer
            cols = int(layer_data.get("col", 8))
            rows = int(layer_data.get("row", 8))

            # Helper to get required adjacent positions based on gimmick type
            def get_required_adjacent(pos_str, gimmick_type=""):
                col, row = map(int, pos_str.split("_"))
                adj = []

                # Chain only checks LEFT and RIGHT (horizontal neighbors)
                if gimmick_type == "chain":
                    directions = [(-1, 0), (1, 0)]  # Left, Right only
                # Link checks specific direction
                elif gimmick_type.startswith("link_"):
                    if gimmick_type == "link_n":
                        directions = [(0, -1)]  # North
                    elif gimmick_type == "link_s":
                        directions = [(0, 1)]   # South
                    elif gimmick_type == "link_e":
                        directions = [(1, 0)]   # East
                    elif gimmick_type == "link_w":
                        directions = [(-1, 0)]  # West
                    else:
                        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
                else:
                    # Default: all 4 directions
                    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

                for dc, dr in directions:
                    nc, nr = col + dc, row + dr
                    if 0 <= nc < cols and 0 <= nr < rows:
                        adj.append(f"{nc}_{nr}")
                return adj

            # Generate all positions and shuffle
            all_positions = [f"{c}_{r}" for c in range(cols) for r in range(rows)]
            random.shuffle(all_positions)

            new_tiles = {}
            used_positions = set()

            # STEP 1: Place goal tiles FIRST (need clear output direction for craft/stack)
            # Must be placed before other tiles to ensure output positions are available
            # Goal tiles (craft/stack) need their output direction to be clear of other tiles
            for tile_type, gimmick, extra in goal_tiles:
                direction = tile_type[-1] if tile_type else 's'
                valid_positions = []

                # Calculate output direction offset
                dir_offsets = {'s': (0, 1), 'n': (0, -1), 'e': (1, 0), 'w': (-1, 0)}
                dc, dr = dir_offsets.get(direction, (0, 1))

                # Calculate how many output positions need to be clear
                # stack_offset = 0.1 per item, so count=3 → max_offset=0.2 → 1 position
                stack_count = extra[0] if extra and isinstance(extra, list) and len(extra) > 0 else 3
                max_offset = (stack_count - 1) * 0.1
                positions_to_clear = max(1, int(max_offset) + 1)  # At least the immediate output position

                for pos in all_positions:
                    if pos in used_positions:
                        continue
                    col_pos, row_pos = map(int, pos.split("_"))

                    # Check boundary constraints
                    if direction == 's' and row_pos >= rows - 1:
                        continue
                    if direction == 'n' and row_pos <= 0:
                        continue
                    if direction == 'e' and col_pos >= cols - 1:
                        continue
                    if direction == 'w' and col_pos <= 0:
                        continue

                    # Check that output positions are clear (not occupied by any tile)
                    output_clear = True
                    for step in range(1, positions_to_clear + 1):
                        out_c = col_pos + dc * step
                        out_r = row_pos + dr * step
                        out_pos = f"{out_c}_{out_r}"
                        # Output position must be within bounds and not occupied
                        if out_c < 0 or out_c >= cols or out_r < 0 or out_r >= rows:
                            output_clear = False
                            break
                        if out_pos in used_positions or out_pos in new_tiles:
                            output_clear = False
                            break

                    if not output_clear:
                        continue

                    valid_positions.append(pos)

                if valid_positions:
                    random.shuffle(valid_positions)
                    pos = valid_positions[0]
                    used_positions.add(pos)
                    # Also reserve output positions so other goals don't use them
                    col_pos, row_pos = map(int, pos.split("_"))
                    for step in range(1, positions_to_clear + 1):
                        out_c = col_pos + dc * step
                        out_r = row_pos + dr * step
                        out_pos = f"{out_c}_{out_r}"
                        used_positions.add(out_pos)
                    self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                else:
                    # FALLBACK: If no valid position found, place in any available position
                    # This ensures goals are never lost during reshuffle
                    for pos in all_positions:
                        if pos not in used_positions:
                            used_positions.add(pos)
                            self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                            break

            # STEP 2: Place plain tiles (they will be neighbors for gimmick tiles)
            random.shuffle(plain_tiles)
            for tile_type, gimmick, extra in plain_tiles:
                for pos in all_positions:
                    if pos not in used_positions:
                        used_positions.add(pos)
                        self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                        break

            # STEP 3: Place neighbor-dependent gimmick tiles using gimmick-specific neighbor rules
            random.shuffle(gimmick_tiles)
            for tile_type, gimmick, extra in gimmick_tiles:
                placed = False
                candidates = []
                for pos in all_positions:
                    if pos in used_positions:
                        continue
                    required_adj = get_required_adjacent(pos, gimmick)
                    for adj_pos in required_adj:
                        if adj_pos in new_tiles:
                            adj_tile = new_tiles[adj_pos]
                            if len(adj_tile) >= 2 and (not adj_tile[1] or adj_tile[1] == "frog"):
                                candidates.append(pos)
                                break

                if candidates:
                    random.shuffle(candidates)
                    pos = candidates[0]
                    used_positions.add(pos)
                    self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                    placed = True

                if not placed:
                    for pos in all_positions:
                        if pos not in used_positions:
                            used_positions.add(pos)
                            self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                            break

            # STEP 4: Place other gimmick tiles (ice, frog, bomb, etc.)
            random.shuffle(other_gimmick_tiles)
            for tile_type, gimmick, extra in other_gimmick_tiles:
                for pos in all_positions:
                    if pos not in used_positions:
                        used_positions.add(pos)
                        self._place_tile(new_tiles, pos, tile_type, gimmick, extra)
                        break

            # Update layer with new tiles
            layer_data["tiles"] = new_tiles
            layer_data["num"] = str(len(new_tiles))

        # Re-validate obstacles (should preserve most gimmicks now)
        new_level = self._validate_and_fix_obstacles(new_level)

        # Recalculate max_moves
        new_level["max_moves"] = self._calculate_max_moves(new_level)

        # Generate new random seed
        new_level["randSeed"] = random.randint(100000, 999999)

        return new_level

    def _collectable_tile_count(self, level: Dict[str, Any]) -> int:
        """수집 필요 타일 수(= 실제 탭 횟수). plain + craft/stack 내부타일.

        [TIMEA] `_calculate_max_moves` 의 순수 버전 — max(30,·) 하한 없음.
        timea(제한시간) 산출은 반드시 이 값을 써야 한다. 하한 포함 값을 쓰면
        30타일 미만 레벨에 시간이 과다 배정된다(예: 18타일 → 30 = 1.67배).
        """
        total_tiles = 0
        num_layers = level.get("layer", 8)
        try:
            num_layers = int(num_layers)
        except (TypeError, ValueError):
            num_layers = 8

        for i in range(num_layers):
            tiles = (level.get(f"layer_{i}") or {}).get("tiles") or {}
            for _pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                        stack_count = 1
                        if len(tile_data) > 2:
                            extra = tile_data[2]
                            if isinstance(extra, list) and len(extra) > 0:
                                stack_count = int(extra[0]) if extra[0] else 1
                            elif isinstance(extra, dict):
                                stack_count = int(extra.get("totalCount", extra.get("count", 1)))
                            elif isinstance(extra, (int, float)):
                                stack_count = int(extra)
                        total_tiles += stack_count
                    else:
                        total_tiles += 1
                else:
                    total_tiles += 1
        return total_tiles

    def _calculate_max_moves(self, level: Dict[str, Any]) -> int:
        """Calculate max_moves based on total tiles in the level.

        Counts all tiles including internal tiles in stack/craft.
        """
        total_tiles = 0
        num_layers = level.get("layer", 8)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            layer_data = level.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Check for stack/craft tiles
                    if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                        # Get internal tile count from tile_data[2]
                        stack_count = 1
                        if len(tile_data) > 2:
                            extra = tile_data[2]
                            if isinstance(extra, list) and len(extra) > 0:
                                stack_count = int(extra[0]) if extra[0] else 1
                            elif isinstance(extra, dict):
                                stack_count = int(extra.get("totalCount", extra.get("count", 1)))
                            elif isinstance(extra, (int, float)):
                                stack_count = int(extra)
                        total_tiles += stack_count
                    else:
                        # Normal tile
                        total_tiles += 1
                else:
                    total_tiles += 1

        # Return total tiles as max_moves (minimum 30)
        return max(30, total_tiles)

    def _create_base_structure(self, params: GenerationParams) -> Dict[str, Any]:
        """Create the base level structure with empty layers."""
        # Auto-select grid size based on level number if level_number is provided
        # This ensures early levels (1-10) use smaller grids (4x4 ~ 5x5)
        # Check for common default grid sizes: (7, 7) from request schema, (8, 8) from old defaults
        # [BOSS_MODE] 보스는 _apply_boss_overrides의 (7,7)을 그대로 사용(테이블 축소 우회)
        DEFAULT_GRID_SIZES = {(7, 7), (8, 8)}
        if (params.level_number and params.grid_size in DEFAULT_GRID_SIZES
                and not getattr(params, "boss_mode", False)):
            # Override default grid size with level-appropriate size
            cols, rows = get_grid_size_for_level(params.level_number)
        else:
            cols, rows = params.grid_size

        # Calculate useTileCount from tile_types
        # If tile_types not specified and level_number is provided, use auto-config
        tile_types = params.tile_types
        if not tile_types and params.level_number:
            # Auto-select tile types based on level number (GBoost style)
            tile_types = get_tile_types_for_level(params.level_number, params.tile_type_profile)
        elif not tile_types:
            tile_types = self.DEFAULT_TILE_TYPES

        # Filter to only valid tile types (t0~t15)
        valid_tile_types = [t for t in tile_types if t.startswith('t') and (t == 't0' or t[1:].isdigit())]
        if valid_tile_types:
            # Check if t0 is used (placeholder for client-side random tiles)
            uses_t0 = 't0' in valid_tile_types
            if uses_t0:
                # t0 사용 시: 레벨에 맞는 useTileCount 사용 (클라이언트가 참조)
                if params.level_number:
                    use_tile_count = get_use_tile_count_for_level(params.level_number, params.tile_type_profile)
                else:
                    use_tile_count = 5  # default for t0 mode
            else:
                # 일반 타일 사용 시: 타일 개수가 useTileCount
                tile_count = len(valid_tile_types)
                use_tile_count = min(self.MAX_USE_TILE_COUNT, tile_count)
        else:
            # No valid tiles, use default of 15 (matches TownPop client - t1~t15 균등 분배)
            use_tile_count = 15

        # [독 천장 제거 2026-07-01] dock 캡(available_dock+2) 및 td-aware 캡 폐지.
        # useTileCount는 그래프값(레벨/프로파일)을 그대로 사용 — 카탈로그 상한(15)으로만 클램프.
        # 트레이7 데드락 위험은 _ensure_no_deadlock 실제 시뮬 + 프로덕션 봇 검증이 사후 거른다.
        use_tile_count = min(use_tile_count, self.MAX_USE_TILE_COUNT)

        level = {
            "layer": params.max_layers,
            "useTileCount": use_tile_count,
            "randSeed": random.randint(1, 999999),
            "autoCollectCount": 0,  # 암호화 설정 (0: 해제)
        }

        for i in range(params.max_layers):
            # 레이어 그리드: 짝수=cols+1, 홀수=cols (번갈아, 고정)
            layer_cols = str(cols + 1 if i % 2 == 0 else cols)
            layer_rows = str(rows + 1 if i % 2 == 0 else rows)

            level[f"layer_{i}"] = {
                "col": layer_cols,
                "row": layer_rows,
                "tiles": {},
                "num": "0",
            }

        return level

    @classmethod
    def _record_used_pattern_category(cls, category_idx: int) -> None:
        """Record a used pattern category for diversity tracking between levels."""
        cls._recent_pattern_categories.append(category_idx)
        # Keep only the most recent N categories
        if len(cls._recent_pattern_categories) > cls._PATTERN_HISTORY_SIZE:
            cls._recent_pattern_categories = cls._recent_pattern_categories[-cls._PATTERN_HISTORY_SIZE:]

    @classmethod
    def clear_pattern_history(cls) -> None:
        """Clear pattern history - useful when starting a new batch."""
        cls._recent_pattern_categories = []

    def _select_layer_pattern_indices(
        self, active_layers: List[int], base_pattern_index: Optional[int] = None
    ) -> Dict[int, int]:
        """Select varied pattern indices for each layer to create geometric diversity.

        Pattern Categories (50 patterns total):
        - 0-9: Basic shapes (rectangle, diamond, oval, cross, donut, etc.)
        - 10-14: Arrow/Direction patterns
        - 15-19: Star/Celestial patterns
        - 20-29: Letter shapes (H, I, L, U, X, Y, Z, S, O, C)
        - 30-39: Advanced geometric (triangles, hourglass, stairs, pyramid, zigzag)
        - 40-44: Frame/Border patterns
        - 45-49: Artistic patterns (butterfly, flower, islands, stripes, honeycomb)

        Strategy: Select patterns from different categories for adjacent layers
        to create visually interesting, non-repetitive geometric compositions.
        Also avoids recently used patterns from previous levels for batch diversity.

        Args:
            active_layers: List of layer indices that will be populated
            base_pattern_index: If specified, use as base; otherwise auto-select

        Returns:
            Dict mapping layer_idx -> pattern_index
        """
        # Define pattern categories with complementary aesthetics
        # Each category has patterns that look distinct from each other
        # Extended categories for maximum variety
        pattern_categories = [
            [0, 1, 2],      # Basic shapes: rectangle, diamond, oval
            [3, 4, 5],      # Structural: cross, donut, chevron
            [10, 11, 12],   # Directional: arrows (up, down, left)
            [13, 14],       # More arrows (right, double)
            [15, 16, 17],   # Celestial: stars (5pt, 6pt, scattered)
            [18, 19],       # Celestial: crescents
            [20, 21, 22],   # Letters: H, I, L
            [23, 24, 25],   # Letters: U, X, Y
            [26, 27, 28, 29],  # Letters: Z, S, O, C
            [30, 31, 32],   # Geometric: triangles, hourglass
            [33, 34, 35],   # Advanced: stairs, pyramid, zigzag
            [36, 37, 38, 39],  # More advanced geometric
            [40, 41, 42],   # Frames: borders
            [43, 44],       # More frames
            [45, 46, 47],   # Artistic: butterfly, flower, islands
            [48, 49],       # Artistic: stripes, honeycomb
            [6, 7, 8, 9],   # Misc basic shapes
            [50, 51],       # Bridge patterns: horizontal, vertical bridges
            [52, 53],       # Multi-island: triangle, grid arrangements
            [54, 55],       # Distributed: archipelago, hub-and-spokes
        ]

        # Flatten for random selection if needed
        all_patterns = [p for cat in pattern_categories for p in cat]

        layer_patterns: Dict[int, int] = {}
        used_categories: Set[int] = set()

        # Also consider categories used in recent levels (for batch diversity)
        recently_used_in_batch = set(self._recent_pattern_categories)

        # Sort layers to ensure consistent ordering (top to bottom)
        sorted_layers = sorted(active_layers, reverse=True)

        # Track the first category selected for this level (to record later)
        first_category_selected: Optional[int] = None

        for i, layer_idx in enumerate(sorted_layers):
            if base_pattern_index is not None:
                # CRITICAL FIX: When base_pattern_index is specified (e.g., special shape levels),
                # use the SAME pattern for ALL layers to maintain visual consistency
                # This ensures heart, star, butterfly patterns look correct across all layers
                layer_patterns[layer_idx] = base_pattern_index
                # Find which category this belongs to (for first layer tracking)
                if i == 0:
                    for cat_idx, cat in enumerate(pattern_categories):
                        if base_pattern_index in cat:
                            used_categories.add(cat_idx)
                            first_category_selected = cat_idx
                            break
            else:
                # For the first layer without base pattern, also avoid recent batch categories
                exclude_categories = used_categories.copy()
                if i == 0:
                    exclude_categories = exclude_categories.union(recently_used_in_batch)

                # Select from a different category than recent layers
                available_categories = [
                    cat_idx for cat_idx in range(len(pattern_categories))
                    if cat_idx not in exclude_categories
                ]

                # If all categories used, reset but avoid immediate repeat
                if not available_categories:
                    used_categories.clear()
                    # Keep the most recent category excluded
                    if i > 0:
                        prev_layer = sorted_layers[i - 1]
                        prev_pattern = layer_patterns.get(prev_layer, 0)
                        for cat_idx, cat in enumerate(pattern_categories):
                            if prev_pattern in cat:
                                used_categories.add(cat_idx)
                                break
                    available_categories = [
                        cat_idx for cat_idx in range(len(pattern_categories))
                        if cat_idx not in used_categories
                    ]

                if available_categories:
                    selected_cat_idx = random.choice(available_categories)
                    selected_pattern = random.choice(pattern_categories[selected_cat_idx])
                    used_categories.add(selected_cat_idx)
                    if i == 0:
                        first_category_selected = selected_cat_idx
                else:
                    # Fallback: random pattern avoiding immediate repeat
                    prev_pattern = layer_patterns.get(sorted_layers[i - 1], -1) if i > 0 else -1
                    candidates = [p for p in all_patterns if p != prev_pattern]
                    selected_pattern = random.choice(candidates) if candidates else random.choice(all_patterns)

                layer_patterns[layer_idx] = selected_pattern

        # Record the first category used for batch diversity tracking
        if first_category_selected is not None:
            self._record_used_pattern_category(first_category_selected)

        return layer_patterns

    def _apply_boss_overrides(self, params: GenerationParams) -> None:
        """[BOSS_MODE] 보스 전용 파라미터 오버라이드 (in-place).

        - 그리드: cols=7 → 짝수층 선언 8 (디바이스 가독성 한계 '9x9 이상 불가' 준수).
          기존 보스는 10x10 템플릿 배정이라 타일이 너무 작게 표시되던 문제의 근본 대체.
        - 층수 5~6 (보스 인덱스 교대): 그리드 폭 대신 깊이(블로킹)로 물량·난이도 확보.
        - pattern_index=None + layer_pattern_configs=None → auto-mix 활성화 →
          _generate_auto_layer_pattern_configs가 BOSS_RECIPES를 level_number 결정적으로 적용.
        - symmetry both, gimmick_intensity ≥1.5 (화려함/난이도).
        난이도 목표(클리어율 절반)는 프론트 검증 파이프라인에서 적용.
        """
        ln = params.level_number or 10
        params.grid_size = (7, 7)
        params.min_layers = 5
        params.max_layers = 6
        if params.active_layer_count is None:
            params.active_layer_count = 5 + ((ln // 10) % 2)  # 5/6층 교대
        params.symmetry_mode = "both"
        params.pattern_type = "aesthetic"
        params.pattern_index = None
        params.layer_pattern_configs = None
        params.gimmick_intensity = max(params.gimmick_intensity or 1.0, 1.5)

    def _generate_auto_layer_pattern_configs(
        self,
        active_layers: List[int],
        target_difficulty: float,
        total_tile_count: int,
        is_boss_level: bool = False,
        boss_level_number: Optional[int] = None,
    ) -> List["LayerPatternConfig"]:
        """Generate intelligent layer pattern configurations for aesthetic variety.

        This method creates visually appealing multi-layer compositions by mixing
        different pattern types across layers. The mixing strategy adapts to:
        - Level difficulty (easy levels use simpler patterns)
        - Number of active layers (more layers = more variety)
        - Boss level status (uses more impressive patterns)

        Pattern Type Characteristics:
        - 'aesthetic': Artistic, visually impressive (best for top/visible layers)
        - 'geometric': Structured, regular shapes (good for base layers)
        - 'clustered': Grouped tiles (creates interesting visual clusters)
        - 'random': Natural, organic feel (good for middle layers)

        IMPROVEMENT: Always use aesthetic patterns for top layer to maximize visual appeal
        and create clear layer differentiation.

        Args:
            active_layers: List of layer indices that will be populated
            target_difficulty: Target difficulty (0.0-1.0)
            total_tile_count: Total tiles across all layers
            is_boss_level: Whether this is a boss level

        Returns:
            List of LayerPatternConfig for each layer
        """
        from app.models.level import LayerPatternConfig

        configs: List[LayerPatternConfig] = []
        num_layers = len(active_layers)
        sorted_layers = sorted(active_layers, reverse=True)  # Top to bottom

        # ===== ENHANCED PATTERN SETS FOR BETTER TOP LAYER VISIBILITY =====

        # Top layer special patterns (always aesthetic, visually distinctive)
        # Priority: Star/Heart/Butterfly/Flower shapes that stand out
        top_layer_patterns = [
            8,   # star_five_point
            15,  # heart_shape
            45,  # butterfly
            46,  # flower_pattern
            16,  # crescent_moon
            17,  # spiral_outward
            50,  # bridge_horizontal
            51,  # bridge_vertical
            52,  # three_islands_triangle
            53,  # four_islands_grid
            54,  # archipelago
            55,  # hub_and_spokes
        ]

        # Boss level extra impressive patterns
        boss_top_patterns = [8, 15, 45, 46, 17, 18, 54, 55]

        # Easy level top patterns (simpler but still distinctive)
        easy_top_patterns = [8, 15, 20, 21, 50, 51, 52]  # Stars, hearts, letters, bridges

        # Medium level top patterns
        medium_top_patterns = [8, 15, 45, 46, 40, 41, 50, 51, 52, 53]

        # Hard level top patterns (complex)
        hard_top_patterns = [45, 46, 47, 48, 49, 54, 55, 8, 15]

        # Middle layer patterns (varied)
        middle_patterns = [4, 5, 10, 11, 30, 31, 40, 41, 33, 34]

        # Bottom layer patterns (structural base - can be simpler)
        bottom_patterns = [0, 1, 2, 3, 4, 5, 20, 21]

        # [v16 🅑] 절차생성(synth) 패턴을 자동 믹스 풀에 주입 — 라이브러리에 채택분이 있으면
        # 상위/중간 레이어 후보로 섞는다. synth 패턴은 ÷3·대칭·연결성이 보장돼 미관에 유리.
        # 크기 미스매치는 _get_custom_pattern의 size-fit fallback이 처리하므로 안전.
        synth_indices = self._get_synth_pattern_indices()
        if synth_indices:
            # 너무 압도하지 않게 후보 풀 크기에 비례한 소량만 가중 주입(중복 추가로 확률↑)
            top_layer_patterns = top_layer_patterns + synth_indices
            medium_top_patterns = medium_top_patterns + synth_indices
            hard_top_patterns = hard_top_patterns + synth_indices
            middle_patterns = middle_patterns + synth_indices

        # ===== PATTERN ASSIGNMENT LOGIC =====

        if is_boss_level and boss_level_number:
            # [BOSS_MODE] 결정적 레시피: 레이어별 화려한 대칭 템플릿 스택.
            # (level//10 - 1) % len 로테이션 → 보스마다 다른 조합, 재시도에도 동일 유지.
            recipe = BOSS_RECIPES[((boss_level_number // 10) - 1) % len(BOSS_RECIPES)]
            for i, layer_idx in enumerate(sorted_layers):
                configs.append(LayerPatternConfig(
                    layer=layer_idx,
                    pattern_type="aesthetic",
                    pattern_index=recipe[i % len(recipe)],
                ))
            return configs

        if is_boss_level:
            # Boss levels: Maximum visual impact on top
            for i, layer_idx in enumerate(sorted_layers):
                if i == 0:  # Top layer - most visible, impressive
                    pattern_idx = random.choice(boss_top_patterns)
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="aesthetic",
                        pattern_index=pattern_idx
                    ))
                elif i == len(sorted_layers) - 1:  # Bottom layer - structural base
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice(bottom_patterns)
                    ))
                else:  # Middle layers - mix for variety
                    if i % 2 == 0:
                        configs.append(LayerPatternConfig(
                            layer=layer_idx,
                            pattern_type="clustered",
                            pattern_index=None
                        ))
                    else:
                        configs.append(LayerPatternConfig(
                            layer=layer_idx,
                            pattern_type="aesthetic",
                            pattern_index=random.choice(middle_patterns)
                        ))
        elif target_difficulty < 0.3:
            # Easy levels: Simple but still aesthetic on top for visibility
            for i, layer_idx in enumerate(sorted_layers):
                if i == 0:  # Top layer - ALWAYS aesthetic for distinction
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="aesthetic",
                        pattern_index=random.choice(easy_top_patterns)
                    ))
                elif i == len(sorted_layers) - 1:  # Bottom layer
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice([0, 1, 2, 3])
                    ))
                else:  # Middle layers
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice(bottom_patterns)
                    ))
        elif target_difficulty < 0.6:
            # Medium difficulty: Balanced variety with aesthetic top
            for i, layer_idx in enumerate(sorted_layers):
                if i == 0:  # Top layer - aesthetic
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="aesthetic",
                        pattern_index=random.choice(medium_top_patterns)
                    ))
                elif i == len(sorted_layers) - 1:  # Bottom - geometric
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice(bottom_patterns)
                    ))
                else:  # Middle - alternate
                    pattern_type = "clustered" if i % 2 == 0 else "random"
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type=pattern_type,
                        pattern_index=None
                    ))
        else:
            # Hard levels: Complex, varied patterns with impressive top
            # Higher difficulty = more scattered patterns for increased challenge
            # Scattered/Island patterns: 47 (scattered_islands), 52-55 (island patterns)
            scattered_patterns = [47, 52, 53, 54, 55]  # More spread out patterns

            for i, layer_idx in enumerate(sorted_layers):
                if i == 0:  # Top layer - use scattered patterns for high difficulty
                    # 70% chance of scattered pattern, 30% other aesthetic
                    if random.random() < 0.7:
                        pattern_idx = random.choice(scattered_patterns)
                    else:
                        pattern_idx = random.choice(hard_top_patterns)
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="aesthetic",
                        pattern_index=pattern_idx
                    ))
                elif i == 1 and num_layers > 2:  # Second layer - scattered/random
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="random",  # More scattered than clustered
                        pattern_index=None
                    ))
                elif i == len(sorted_layers) - 1:  # Bottom - geometric base
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="geometric",
                        pattern_index=random.choice([3, 4, 5, 30, 31])
                    ))
                else:  # Other middle layers - prefer random/scattered
                    configs.append(LayerPatternConfig(
                        layer=layer_idx,
                        pattern_type="random",  # All middle layers use random for scatter
                        pattern_index=None
                    ))

        return configs

    def _create_fixed_layout_level_1(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Create fixed layout for level 1.

        [v15.40] 3×3 그리드, 9타일

        Layout (3x3 grid):
        - layer_0 only: 3×3 = 9 tiles
        - Total: 9 tiles (divisible by 3)
        - Tile types: t1, t2, t3 균등 분배 (각 3개씩)

        Grid layout:
        [###]
        [###]
        [###]
        """
        tile_assignments = []
        tile_assignments.extend(["t1"] * 3)
        tile_assignments.extend(["t2"] * 3)
        tile_assignments.extend(["t3"] * 3)

        import random
        rng = random.Random(params.level_number or 1)
        rng.shuffle(tile_assignments)

        level["layer"] = 1
        level["_skip_tile_redistribution"] = True

        level["layer_0"] = {
            "col": "3",
            "row": "3",
            "tiles": {},
            "num": "0",
        }

        tile_idx = 0
        for row in range(3):
            for col in range(3):
                pos_key = f"{row}_{col}"
                level["layer_0"]["tiles"][pos_key] = [tile_assignments[tile_idx], ""]
                tile_idx += 1

        return level

    def _create_fixed_layout_level_2(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Create fixed layout for level 2.

        [v15.40] 5×3 직사각형 + 4×3 상위 레이어

        Layout:
        - layer_0 (짝수): 5×3 = 15 tiles, cols 0-4, rows 0-2
        - layer_1 (홀수): 4×3 = 12 tiles, cols 0-3, rows 0-2
        - Total: 27 tiles (divisible by 3)
        - Tile types: t1, t2, t3 각 9개씩

        layer_0 (5×3):     layer_1 (4×3, +0.5 오프셋):
        [#####]            [####]
        [#####]            [####]
        [#####]            [####]
        """
        # [v15.40] 색상 균등 3종: t1(색1), t4(색2), t7(색3) 각 9개
        tile_assignments = []
        tile_assignments.extend(["t1"] * 9)
        tile_assignments.extend(["t4"] * 9)
        tile_assignments.extend(["t7"] * 9)

        import random
        rng = random.Random(params.level_number or 2)
        rng.shuffle(tile_assignments)

        level["layer"] = 2
        level["_skip_tile_redistribution"] = True

        tile_idx = 0

        # Layer 0 (짝수): 5×5 그리드에 5×3 패턴 중앙 배치 = 15 tiles
        level["layer_0"] = {
            "col": "5",
            "row": "5",
            "tiles": {},
            "num": "0",
        }
        for row in range(3):  # 3행 (row 1-3 중앙)
            for col in range(5):  # 5열
                pos_key = f"{col}_{row + 1}"
                level["layer_0"]["tiles"][pos_key] = [tile_assignments[tile_idx], ""]
                tile_idx += 1

        # Layer 1 (홀수): 4×4 그리드에 4×3 패턴 중앙 배치 = 12 tiles
        level["layer_1"] = {
            "col": "4",
            "row": "4",
            "tiles": {},
            "num": "0",
        }
        for row in range(3):  # 3행 (row 0-2)
            for col in range(4):  # 4열
                pos_key = f"{col}_{row}"
                level["layer_1"]["tiles"][pos_key] = [tile_assignments[tile_idx], ""]
                tile_idx += 1

        return level

    def _create_fixed_layout_level_3(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Create fixed layout for level 3.

        [v15.39] 시각적 중앙정렬 + 고정 타일 타입 균등 분배

        렌더링 규칙:
        - 짝수 레이어 (0, 2, 4...): 오프셋 없음
        - 홀수 레이어 (1, 3, 5...): +0.5 타일 오프셋

        시각적 중심 계산:
        - Layer 0 (짝수): cols 0-4, 좌표중심=2.0, 시각중심=2.0
        - Layer 1 (홀수): cols 1-2, 좌표중심=1.5, 시각중심=1.5+0.5=2.0 ✓

        Layout:
        - layer_0: 5×5 = 25 tiles
        - layer_1: 2 tiles at diagonal (1,1) and (2,2)
        - Total: 27 tiles (divisible by 3)
        - Tile types: t1, t2, t3 균등 분배 (각 9개씩)

        layer_0 (5x5):        layer_1:
        [#####]               [ #  ]  <- row 1, col 1
        [#####]               [  # ]  <- row 2, col 2
        [#####]
        [#####]
        [#####]
        """
        # [v15.40] 색상 균등 4종: t1(색1), t4(색2), t7(색3), t10(색4)
        total_tiles = 27  # 25 + 2
        tile_assignments = []
        tile_assignments.extend(["t1"] * 9)
        tile_assignments.extend(["t4"] * 6)
        tile_assignments.extend(["t7"] * 6)
        tile_assignments.extend(["t10"] * 6)

        import random
        rng = random.Random(params.level_number or 3)
        rng.shuffle(tile_assignments)

        level["layer"] = 2
        level["_skip_tile_redistribution"] = True

        tile_idx = 0

        # Layer 0: 5×5 = 25 tiles, 좌표중심=2.0, 시각중심=2.0
        level["layer_0"] = {
            "col": "5",
            "row": "5",
            "tiles": {},
            "num": "0",
        }
        for row in range(5):
            for col in range(5):
                pos_key = f"{row}_{col}"
                level["layer_0"]["tiles"][pos_key] = [tile_assignments[tile_idx], ""]
                tile_idx += 1

        # Layer 1: 2 diagonal tiles, 좌표중심=1.5, 시각중심=2.0
        level["layer_1"] = {
            "col": "5",
            "row": "5",
            "tiles": {},
            "num": "0",
        }
        # Diagonal positions: (1,1) and (2,2) → col center = 1.5 + 0.5 offset = 2.0
        level["layer_1"]["tiles"]["1_1"] = [tile_assignments[tile_idx], ""]
        tile_idx += 1
        level["layer_1"]["tiles"]["2_2"] = [tile_assignments[tile_idx], ""]
        tile_idx += 1

        return level

    def _populate_layers(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Populate layers with tiles based on difficulty and user configuration."""
        # SPECIAL CASE: Fixed layouts for specific levels (production requirement)
        if params.level_number == 1:
            return self._create_fixed_layout_level_1(level, params)
        elif params.level_number == 2:
            return self._create_fixed_layout_level_2(level, params)
        elif params.level_number == 3:
            return self._create_fixed_layout_level_3(level, params)

        target = params.target_difficulty
        # Auto-select grid size based on level number if using default
        # [BOSS_MODE] 보스는 _apply_boss_overrides의 (7,7) 유지(테이블 축소 우회)
        DEFAULT_GRID_SIZES = {(7, 7), (8, 8)}
        if (params.level_number and params.grid_size in DEFAULT_GRID_SIZES
                and not getattr(params, "boss_mode", False)):
            cols, rows = get_grid_size_for_level(params.level_number)
        else:
            cols, rows = params.grid_size

        # Auto-select tile types based on level number if not specified
        tile_types = params.tile_types
        if not tile_types and params.level_number:
            tile_types = get_tile_types_for_level(params.level_number)
        elif not tile_types:
            tile_types = self.DEFAULT_TILE_TYPES

        # Check if per-layer tile configs are provided (they take priority)
        has_layer_tile_configs = bool(params.layer_tile_configs) and len(params.layer_tile_configs) > 0

        if has_layer_tile_configs:
            # Use ONLY the layers specified in layer_tile_configs
            # This gives full control to the user
            active_layers = sorted(
                [c.layer for c in params.layer_tile_configs],
                reverse=True  # Start from top layer
            )
            active_layer_count = len(active_layers)

            # Build per-layer tile counts from config
            layer_tile_counts: Dict[int, int] = {}
            for config in params.layer_tile_configs:
                layer_tile_counts[config.layer] = config.count

            # Total is sum of configured counts
            total_target = sum(layer_tile_counts.values())
        else:
            # Determine layers from active_layer_count or calculate based on difficulty
            # [층수 상한 스위치] enforce_layer_cap=False 면 max_layers 클램프를 건너뛴다
            # (등껍질 침식처럼 '모양이 층수를 결정'하는 모드용).
            _cap_on = bool(getattr(params, "enforce_layer_cap", True)) \
                and not getattr(params, "turtle_pattern_id", None)
            if params.active_layer_count is not None:
                active_layer_count = (min(params.active_layer_count, params.max_layers)
                                      if _cap_on else params.active_layer_count)
            elif not _cap_on:
                # 상한 미적용인데 개수 지정도 없음 → 등급 클램프 대신 params 범위만 사용
                active_layer_count = max(1, params.min_layers)
            else:
                # Tile Buster style layer count based on difficulty:
                # - S grade (0-0.2): 2-3 layers (tutorial, simple)
                # - A grade (0.2-0.4): 3-4 layers (easy-medium)
                # - B grade (0.4-0.6): 4-5 layers (medium)
                # - C grade (0.6-0.8): 5-6 layers (hard)
                # - D grade (0.8-1.0): 6-8 layers (very hard)
                min_layers = max(1, params.min_layers)
                max_layers = params.max_layers

                # Tutorial mode: For very low difficulty (≤0.15) AND early levels (1-3)
                # Levels 4+ should use params.min_layers/max_layers even with low difficulty
                is_tutorial_mode = target <= 0.15 and (params.level_number is None or params.level_number <= 3)
                if is_tutorial_mode:
                    max_layers = min(max_layers, 3)
                    min_layers = min(min_layers, 2)
                # [v16] 7x7 캡으로 면적이 줄어든 만큼 깊이(레이어)로 난이도 확보 — 상한 상향.
                elif target < 0.4:
                    # A grade: 3-4 layers
                    min_layers = max(min_layers, 3)
                    max_layers = min(max_layers, 4)
                elif target < 0.6:
                    # B grade: 4-6 layers
                    min_layers = max(min_layers, 4)
                    max_layers = min(max_layers, 6)
                elif target < 0.8:
                    # C grade: 6-8 layers
                    min_layers = max(min_layers, 6)
                    max_layers = min(max_layers, 8)
                else:
                    # D/E grade: 7-10 layers (use full config range)
                    min_layers = max(min_layers, 7)

                # Ensure min <= max
                if min_layers > max_layers:
                    min_layers = max_layers

                # Linear interpolation based on difficulty within grade range
                layer_range = max_layers - min_layers
                active_layer_count = min_layers + int(layer_range * target)

                # Clamp to valid range
                active_layer_count = max(min_layers, min(max_layers, active_layer_count))

                # [생산복구] Lv11-30 +1층 원복 — 유닛조립용이었으나 일반 초반레벨도 어렵게 만들어
                # 검증 회귀 기여. 유닛조립은 빌더가 자체 층수 처리. (재도입은 성긴-대칭 재설계 시.)

                print(f"[GEN_LAYER] target={target:.2f}, params.max={params.max_layers}, min={min_layers}, max={max_layers}, active={active_layer_count}")

            # Update level["layer"] to reflect actual active layer count
            level["layer"] = active_layer_count

            # Use layers 0 to active_layer_count-1 (bottom to top)
            active_layers = list(range(active_layer_count))

            # Calculate total tile count target
            if params.total_tile_count is not None:
                total_target = (params.total_tile_count // 3) * 3
                if total_target < 9:
                    total_target = 9
            else:
                # Tile Buster style tile count ranges:
                # - Early levels (tutorial): 30-45 tiles, simple layout
                # - Mid levels: 45-60 tiles, moderate complexity
                # - Late levels: 60-90 tiles, high complexity
                #
                # S grade (0-0.2): Tutorial style, 30-45 tiles
                # A grade (0.2-0.4): Easy-medium, 45-60 tiles
                # B grade (0.4-0.6): Medium, 54-72 tiles
                # C grade (0.6-0.8): Hard, 66-84 tiles
                # D grade (0.8-1.0): Very hard, 78-99 tiles
                if target < 0.2:
                    # S grade: tutorial style
                    min_tiles = 30
                    max_tiles = 45
                elif target < 0.4:
                    # A grade: easy-medium
                    min_tiles = 45
                    max_tiles = 60
                elif target < 0.6:
                    # B grade: medium
                    min_tiles = 54
                    max_tiles = 72
                elif target < 0.8:
                    # C grade: hard
                    min_tiles = 66
                    max_tiles = 84
                else:
                    # D grade: very hard
                    min_tiles = 78
                    max_tiles = 99

                # Linear interpolation within the grade range
                if target < 0.2:
                    t = target / 0.2
                elif target < 0.4:
                    t = (target - 0.2) / 0.2
                elif target < 0.6:
                    t = (target - 0.4) / 0.2
                elif target < 0.8:
                    t = (target - 0.6) / 0.2
                else:
                    t = (target - 0.8) / 0.2

                base_tiles = int(min_tiles + (max_tiles - min_tiles) * t)
                base_tiles = max(min_tiles, min(max_tiles, base_tiles))

                # Add random variation for diversity (±15% within grade range)
                variation_range = int((max_tiles - min_tiles) * 0.3)  # 30% of grade range
                random_variation = random.randint(-variation_range, variation_range)
                base_tiles = max(min_tiles, min(max_tiles, base_tiles + random_variation))

                total_target = (base_tiles // 3) * 3
                if total_target < 30:
                    total_target = 30

            # Build per-layer tile counts with random variation for diversity
            layer_tile_counts = {}
            tiles_per_layer = total_target // len(active_layers)
            extra_tiles = total_target % len(active_layers)

            # Shuffle which layers get extra tiles for variety
            extra_tile_layers = random.sample(active_layers, min(extra_tiles, len(active_layers)))

            # CRITICAL: When exact tile count is specified (tutorial levels, etc.),
            # disable variation to ensure exact tile count
            exact_tile_mode = params.total_tile_count is not None

            if exact_tile_mode:
                # Exact mode: no variation, distribute evenly
                for layer_idx in active_layers:
                    base_count = tiles_per_layer + (3 if layer_idx in extra_tile_layers else 0)
                    layer_tile_counts[layer_idx] = (base_count // 3) * 3
            else:
                # Create varied distribution patterns
                # 'gboost_pyramid' is based on analysis of 221 human-designed GBoost levels:
                # Layer 0: ~30%, Layer 1: ~29%, Layer 2: ~22%, Layer 3: ~14%, Layer 4: ~8%
                # This creates a natural difficulty curve where bottom layers have more tiles
                distribution_pattern = random.choices(
                    ['gboost_pyramid', 'uniform', 'bottom_heavy', 'alternating', 'random'],
                    weights=[0.50, 0.15, 0.15, 0.10, 0.10],  # 50% chance for gboost_pyramid
                    k=1
                )[0]

                if distribution_pattern == 'gboost_pyramid':
                    # GBoost human-designed level ratios (analyzed from level_1 ~ level_221)
                    # These ratios create a natural difficulty progression
                    pyramid_ratios = [0.30, 0.29, 0.22, 0.14, 0.08, 0.05, 0.03, 0.02]
                    num_layers = len(active_layers)

                    # Normalize ratios to match actual layer count
                    used_ratios = pyramid_ratios[:num_layers]
                    ratio_sum = sum(used_ratios)
                    normalized_ratios = [r / ratio_sum for r in used_ratios]

                    # Distribute tiles according to pyramid ratios
                    remaining_tiles = total_target
                    for i, layer_idx in enumerate(sorted(active_layers)):
                        if i < len(active_layers) - 1:
                            layer_count = int(total_target * normalized_ratios[i])
                            # Ensure divisible by 3
                            layer_count = (layer_count // 3) * 3
                            layer_count = max(6, layer_count)  # Minimum 6 tiles
                        else:
                            # Last layer gets remaining tiles
                            layer_count = remaining_tiles
                            layer_count = (layer_count // 3) * 3
                            layer_count = max(6, layer_count)

                        layer_tile_counts[layer_idx] = layer_count
                        remaining_tiles -= layer_count
                else:
                    # Original distribution patterns
                    for layer_idx in active_layers:
                        # More aggressive per-layer variation for diversity
                        if distribution_pattern == 'uniform':
                            layer_variation = random.choice([-6, -3, 0, 3, 6])
                        elif distribution_pattern == 'bottom_heavy':
                            # Lower layers get more tiles
                            layer_variation = -(layer_idx - len(active_layers) // 2) * 3
                        elif distribution_pattern == 'alternating':
                            # Alternating heavy/light layers
                            layer_variation = 6 if layer_idx % 2 == 0 else -6
                        else:  # random
                            layer_variation = random.randint(-3, 3) * 3

                        base_count = tiles_per_layer + (3 if layer_idx in extra_tile_layers else 0)
                        final_count = max(6, base_count + layer_variation)  # Minimum 6 tiles per layer
                        # Ensure divisible by 3
                        layer_tile_counts[layer_idx] = (final_count // 3) * 3

        # Collect all positions across all layers
        all_layer_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)

        # Generate varied pattern indices for each layer (for aesthetic mode)
        # This creates geometric diversity by using different patterns per layer
        layer_pattern_indices = self._select_layer_pattern_indices(
            active_layers, base_pattern_index=params.pattern_index
        )

        # When exact tile counts are specified, force symmetry_mode="none" to get exact counts
        # (unless user explicitly requested a specific symmetry mode)
        exact_count_mode = has_layer_tile_configs or (params.total_tile_count is not None)
        effective_symmetry_mode = params.symmetry_mode
        if exact_count_mode and params.symmetry_mode is None:
            effective_symmetry_mode = "none"

        # DEBUG: Log symmetry mode in generator
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info(f"[GENERATOR_DEBUG] params.symmetry_mode={params.symmetry_mode}, "
                     f"exact_count_mode={exact_count_mode}, "
                     f"effective_symmetry_mode={effective_symmetry_mode}, "
                     f"pattern_type={params.pattern_type}")

        # Auto-mixing: Generate intelligent layer pattern configs for aesthetic variety
        # Conditions for auto-mixing:
        # 1. No explicit layer_pattern_configs provided
        # 2. Multiple active layers (>= 3 for meaningful variety)
        # 3. pattern_type is 'aesthetic' or None (default)
        # 4. NO specific pattern_index specified (special shape levels must use same pattern on all layers)
        enable_auto_mixing = (
            params.layer_pattern_configs is None and
            len(active_layers) >= 3 and
            params.pattern_type in (None, "aesthetic") and
            params.pattern_index is None  # CRITICAL: Disable auto-mixing for special shape levels
        )

        effective_layer_pattern_configs = None
        if enable_auto_mixing:
            # Calculate total tile count for auto-mixing strategy
            total_tiles = sum(layer_tile_counts.values())
            # Detect boss level: explicit boss_mode > heuristic(high tile count/multi goals)
            explicit_boss = bool(getattr(params, "boss_mode", False))
            is_boss_level = explicit_boss or total_tiles > 100 or (
                params.goals and len(params.goals) > 1
            )
            effective_layer_pattern_configs = self._generate_auto_layer_pattern_configs(
                active_layers=active_layers,
                target_difficulty=params.target_difficulty,
                total_tile_count=total_tiles,
                is_boss_level=is_boss_level,
                boss_level_number=params.level_number if explicit_boss else None,
            )
            _logger.info(f"[GENERATOR_DEBUG] Auto-mixing enabled: {len(effective_layer_pattern_configs)} layer configs generated, is_boss={is_boss_level}")
        elif params.layer_pattern_configs:
            effective_layer_pattern_configs = params.layer_pattern_configs

        # Helper function to get pattern config for a layer
        def get_effective_layer_pattern(layer_idx: int):
            """Get effective pattern config for a layer from auto or explicit configs."""
            if effective_layer_pattern_configs:
                for config in effective_layer_pattern_configs:
                    if config.layer == layer_idx:
                        return (config.pattern_type, config.pattern_index)
            return None

        # [좁고깊은/중간보스] 동심 침식 스택: layer_0 채운 모양 → 위로 erode(중앙 축소).
        # 상위층 무작위 흩어짐 제거. 나머지 패턴 블록 스킵. (타입 솔버블화는 use_reverse_generation.)
        if getattr(params, "unit_assembly", False):
            # [유닛 조립] 바닥 주패턴 + 위층 소형유닛(받침 내). sparse 해결·타겟 도달·floating 0.
            all_layer_positions = self._build_unit_assembly_layers(
                level, active_layers, cols, rows, params, total_target)
            level["_preserve_pattern"] = True   # 조립 모양 보존(피라미드 클램프/재생성 스킵)
            level["_pattern_locked_positions"] = {p for _, p in all_layer_positions}
            level["_unit_assembly"] = True      # [재생성 보존] 순차검증/개별 재생성이 이 마커로 규칙 유지
        elif getattr(params, "concentric_deep", False):
            all_layer_positions = self._build_concentric_layers(level, active_layers, cols, rows, params)
            level["_preserve_pattern"] = True  # 피라미드 클램프/재생성 스킵(동심 모양 보존)
            level["_pattern_locked_positions"] = {p for _, p in all_layer_positions}
        # CRITICAL: When pattern_index is specified (special shape levels like Heart, Star),
        # generate a MASTER pattern first and ALL layers share the SAME positions.
        # This ensures the visual shape is maintained when layers are stacked.
        elif params.pattern_index is not None:
            # Check if this is a LAYERED pattern (different shape per layer)
            use_layered_pattern = is_layered_pattern(params.pattern_index)

            if use_layered_pattern:
                # LAYERED PATTERN MODE: Each layer has a different pattern (e.g., nested frames)
                logger.info(f"[LAYERED_PATTERN] Using layered pattern {params.pattern_index}")

                all_locked_positions = set()

                for layer_idx in active_layers:
                    is_odd_layer = layer_idx % 2 == 1

                    # Calculate actual layer grid size (following alternating rule)
                    if is_odd_layer:
                        layer_cols = cols  # Smaller grid for odd layers
                        layer_rows = rows
                    else:
                        layer_cols = cols + 1  # Larger grid for even layers
                        layer_rows = rows + 1

                    # Get layer-specific pattern positions
                    layer_positions = get_layered_pattern_positions(
                        params.pattern_index, layer_idx, layer_cols, layer_rows
                    )

                    # If no layer-specific positions, fallback to standard pattern
                    if not layer_positions:
                        layer_positions = self._generate_aesthetic_positions(
                            layer_cols, layer_rows,
                            target_count=1000,
                            pattern_index=params.pattern_index,
                            target_difficulty=params.target_difficulty  # v15.7: Pattern density adjustment
                        )

                    # Update layer grid size in level data
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["col"] = str(layer_cols)
                    level[layer_key]["row"] = str(layer_rows)

                    # Add to all_layer_positions
                    for pos in layer_positions:
                        all_layer_positions.append((layer_idx, pos))
                        all_locked_positions.add(pos)

                    logger.debug(f"[LAYERED_PATTERN] Layer {layer_idx}: {len(layer_positions)} positions")

                # Store pattern lock flag
                level["_preserve_pattern"] = True
                level["_pattern_locked_positions"] = all_locked_positions
                level["_pattern_grid_cols"] = cols + 1
                level["_pattern_grid_rows"] = rows + 1

                logger.info(f"[LAYERED_PATTERN] Total positions={len(all_layer_positions)}, "
                           f"unique_positions={len(all_locked_positions)}")

            else:
                # STANDARD PATTERN MODE: All layers share same positions
                # Generate master pattern positions using the LARGEST grid size (even layer grid)
                # Even layers use cols+1 x rows+1, odd layers use cols x rows
                # We generate for the larger grid to get the FULL pattern shape
                max_cols = cols + 1  # Even layer column count
                max_rows = rows + 1  # Even layer row count
                master_positions = self._generate_aesthetic_positions(
                    max_cols, max_rows,  # Use LARGEST grid size to get full pattern
                    target_count=1000,  # Request many positions to get full pattern shape
                    pattern_index=params.pattern_index,
                    target_difficulty=params.target_difficulty  # v15.7: Pattern density adjustment
                )

                logger.debug(f"[PATTERN_SHAPE] pattern_index={params.pattern_index}, "
                             f"master_positions={len(master_positions)}, "
                             f"active_layers={active_layers}")

                # ALL layers will share the SAME pattern positions
                # The FULL pattern shape is used on each layer for visual clarity
                # This creates a stacked 3D effect while maintaining the recognizable shape

                # CRITICAL: PRESERVE EXACT PATTERN SHAPE - no modification!
                # Do NOT add or remove positions to maintain the designed visual pattern.
                # The tile type distribution will handle 3-divisibility requirements
                # by ensuring the total across all layers works out correctly.
                remainder = len(master_positions) % 3
                if remainder != 0:
                    _logger.info(f"[PATTERN_SHAPE] Pattern has {len(master_positions)} positions (remainder {remainder}). "
                                f"Preserving exact shape - tile types will be adjusted for playability.")

                # Ensure minimum of 6 positions
                if len(master_positions) < 6:
                    _logger.warning(f"[PATTERN_SHAPE] Pattern has only {len(master_positions)} positions, minimum is 6")

                # CRITICAL: Store pattern lock flag and positions in level metadata
                # This prevents later functions from adding/removing tiles outside pattern
                level["_preserve_pattern"] = True
                level["_pattern_locked_positions"] = set(master_positions)

                # Store pattern metadata
                level["_pattern_grid_cols"] = max_cols
                level["_pattern_grid_rows"] = max_rows

                # [v15.40] PATTERN MODE — 스텝 기반 패턴 배치 크기
                steps = params.layer_steps or [-1] * max(0, len(active_layers) - 1)
                pattern_base = cols + 1  # L0 패턴 크기
                pattern_sizes = [pattern_base]
                for i in range(1, len(active_layers)):
                    step = steps[i - 1] if i - 1 < len(steps) else -1
                    pattern_sizes.append(max(4, pattern_sizes[-1] + step))

                # [v15.40] 레이어별 패턴 오버라이드 맵
                overrides = {}
                if params.layer_pattern_overrides:
                    for ov in params.layer_pattern_overrides:
                        overrides[ov.get("layer", -1)] = ov

                # [B] 층별 크기 다양화 배정 (start_level 이상만; None=미적용)
                size_div_map = self._compute_layer_size_diversity(
                    active_layers,
                    [(cols if (l % 2 == 1) else cols + 1, rows if (l % 2 == 1) else rows + 1) for l in active_layers],
                    params.level_number,
                    params.size_diversity_start_level,
                )

                for li, layer_idx in enumerate(active_layers):
                    is_odd_layer = layer_idx % 2 == 1

                    # 레이어 그리드 (짝홀 교대, 고정)
                    base_cols = cols if is_odd_layer else cols + 1
                    base_rows = rows if is_odd_layer else rows + 1

                    # 레이어별 패턴 오버라이드 확인
                    ov = overrides.get(layer_idx)
                    if ov:
                        layer_pattern_idx = ov.get("pattern_index", params.pattern_index)
                        layer_size = ov.get("size", pattern_sizes[li] if li < len(pattern_sizes) else base_cols)
                    else:
                        layer_pattern_idx = params.pattern_index
                        layer_size = pattern_sizes[li] if li < len(pattern_sizes) else base_cols

                    # 패턴 배치 크기 (그리드 이내, 최소 4)
                    layer_cols = max(4, min(layer_size, base_cols))
                    layer_rows = max(4, min(layer_size, base_rows))

                    # [B] 크기 다양화 활성 시 step 기반 크기 대신 랜덤 s×s로 override
                    #     (col/row는 아래에서 base로 세팅 → 게임 정합 유지, 오프셋은 base-s로 자동 중앙)
                    if size_div_map is not None:
                        s = size_div_map[layer_idx]
                        layer_cols = s
                        layer_rows = s

                    # Generate pattern for this layer's grid size
                    layer_positions = self._generate_aesthetic_positions(
                        layer_cols, layer_rows,
                        target_count=1000,
                        pattern_index=layer_pattern_idx,
                        target_difficulty=params.target_difficulty
                    )

                    # Calculate center offset for depth emphasis (turtle shell effect)
                    layer_offset_x = (base_cols - layer_cols) // 2
                    layer_offset_y = (base_rows - layer_rows) // 2

                    # Apply offset to center smaller layers
                    if layer_offset_x > 0 or layer_offset_y > 0:
                        offset_positions = []
                        for pos in layer_positions:
                            x, y = map(int, pos.split("_"))
                            new_x = x + layer_offset_x
                            new_y = y + layer_offset_y
                            if 0 <= new_x < base_cols and 0 <= new_y < base_rows:
                                offset_positions.append(f"{new_x}_{new_y}")
                        layer_positions = offset_positions

                    # Update layer grid size in level data (use base size for grid bounds)
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["col"] = str(base_cols)
                    level[layer_key]["row"] = str(base_rows)

                    # Add to all_layer_positions
                    for pos in layer_positions:
                        all_layer_positions.append((layer_idx, pos))

                logger.info(f"[PATTERN_SHAPE] Pattern with alternating layer sizes, "
                           f"total positions={len(all_layer_positions)}")

        else:
            # [v15.40] Standard per-layer pattern generation — 스텝 기반 패턴 배치 크기
            # 레이어 그리드: 짝홀 교대 (고정)
            # 패턴 배치: 스텝 기반으로 축소 (layer_steps)
            steps = params.layer_steps or [-1] * max(0, len(active_layers) - 1)
            base_size = cols + 1  # L0 패턴 크기
            pattern_sizes = [base_size]
            for i in range(1, len(active_layers)):
                step = steps[i - 1] if i - 1 < len(steps) else -1
                next_size = max(4, pattern_sizes[-1] + step)
                pattern_sizes.append(next_size)

            # [v15.40] 레이어별 패턴 오버라이드 맵
            overrides_std = {}
            if params.layer_pattern_overrides:
                for ov in params.layer_pattern_overrides:
                    overrides_std[ov.get("layer", -1)] = ov

            # [B] 층별 크기 다양화 배정 (start_level 이상만; None=미적용)
            size_div_map = self._compute_layer_size_diversity(
                active_layers,
                [(cols if (l % 2 == 1) else cols + 1, rows if (l % 2 == 1) else rows + 1) for l in active_layers],
                params.level_number,
                params.size_diversity_start_level,
            )

            for li, layer_idx in enumerate(active_layers):
                layer_key = f"layer_{layer_idx}"
                is_odd_layer = layer_idx % 2 == 1

                # 레이어 그리드 크기 (짝홀 교대, 고정)
                base_cols = cols if is_odd_layer else cols + 1
                base_rows = rows if is_odd_layer else rows + 1

                # 레이어별 오버라이드 확인
                ov = overrides_std.get(layer_idx)
                if ov:
                    layer_size = ov.get("size", pattern_sizes[li] if li < len(pattern_sizes) else base_cols)
                else:
                    layer_size = pattern_sizes[li] if li < len(pattern_sizes) else base_cols

                layer_cols = max(4, min(layer_size, base_cols))
                layer_rows = max(4, min(layer_size, base_rows))

                # [B] 크기 다양화 활성 시 랜덤 s×s로 override (col/row는 base 유지 → 게임 정합)
                if size_div_map is not None:
                    s = size_div_map[layer_idx]
                    layer_cols = s
                    layer_rows = s

                # 중앙 정렬 오프셋
                layer_offset_x = max(0, (base_cols - layer_cols) // 2)
                layer_offset_y = max(0, (base_rows - layer_rows) // 2)

                # Get target tile count for this layer
                target_count = layer_tile_counts.get(layer_idx, 0)
                if target_count <= 0:
                    continue

                # [v15.40] 레이어별 패턴 오버라이드 우선
                ov = overrides_std.get(layer_idx)
                if ov and "pattern_index" in ov:
                    layer_pattern_type = "aesthetic"
                    layer_pattern_index = ov["pattern_index"]
                else:
                    # 기존: layer config → level-wide default
                    layer_pattern_config = get_effective_layer_pattern(layer_idx)
                    if layer_pattern_config:
                        layer_pattern_type = layer_pattern_config[0]
                        layer_pattern_index = layer_pattern_config[1] if layer_pattern_config[1] is not None else layer_pattern_indices.get(layer_idx, params.pattern_index)
                    else:
                        layer_pattern_type = params.pattern_type
                        layer_pattern_index = layer_pattern_indices.get(layer_idx, params.pattern_index)

                # Generate positions for this layer with symmetry and pattern options
                # Note: positions are generated within the shrunk layer dimensions
                positions = self._generate_layer_positions_for_count(
                    layer_cols, layer_rows, target_count,
                    symmetry_mode=effective_symmetry_mode,
                    pattern_type=layer_pattern_type,
                    pattern_index=layer_pattern_index,  # Use varied pattern per layer
                    target_difficulty=params.target_difficulty  # v15.7: Pass for pattern density adjustment
                )

                # Phase 2: Apply center offset to positions so higher layers appear centered
                if layer_offset_x > 0 or layer_offset_y > 0:
                    offset_positions = []
                    for pos in positions:
                        parts = pos.split("_")
                        x, y = int(parts[0]), int(parts[1])
                        new_x = x + layer_offset_x
                        new_y = y + layer_offset_y
                        # Ensure within original grid bounds
                        if 0 <= new_x < base_cols and 0 <= new_y < base_rows:
                            offset_positions.append(f"{new_x}_{new_y}")
                    positions = offset_positions

                # [v15.40] Phase 3: 상위 레이어 지지 검증
                # 상위 레이어 타일은 하위 레이어 타일 위에만 배치
                # 홀수/짝수 레이어 간 오프셋 규칙 적용
                if layer_idx > 0:
                    # 바로 아래 레이어의 타일 위치 수집
                    below_positions = set()
                    for lp in all_layer_positions:
                        if lp[0] == layer_idx - 1:
                            below_positions.add(lp[1])

                    if below_positions:
                        # 하위 타일의 인접 지지 위치 계산
                        # 패리티가 다르면 (홀↔짝) 오프셋 +0.5 고려 → 4방향 인접
                        same_parity = (layer_idx % 2) == ((layer_idx - 1) % 2)
                        supported = set()
                        for bp in below_positions:
                            bx, by = int(bp.split("_")[0]), int(bp.split("_")[1])
                            if same_parity:
                                # 같은 패리티: 동일 위치만 지지
                                supported.add(f"{bx}_{by}")
                            else:
                                # 다른 패리티: 4개 인접 위치 지지
                                for dx, dy in [(-1, -1), (0, -1), (-1, 0), (0, 0)]:
                                    supported.add(f"{bx+dx}_{by+dy}")

                        # 지지되는 위치만 유지
                        supported_positions = [p for p in positions if p in supported]
                        if len(supported_positions) >= 3:  # 최소 3개 이상
                            positions = supported_positions

                for pos in positions:
                    all_layer_positions.append((layer_idx, pos))

        # [v15.40] Phase 1: 피라미드 구조 강제 - 상위 레이어는 하위보다 적은 타일
        # 패턴 모드에서는 건너뜀 (패턴 형태 보존 우선)
        layer_pos_map: Dict[int, List[Tuple[int, str]]] = {}
        for lp in all_layer_positions:
            layer_pos_map.setdefault(lp[0], []).append(lp)

        sorted_layer_indices = sorted(layer_pos_map.keys())
        if len(sorted_layer_indices) >= 2 and not level.get("_preserve_pattern"):
            # 하위→상위 순으로 검사하며 상위가 하위보다 크면 축소
            for idx in range(1, len(sorted_layer_indices)):
                cur_layer = sorted_layer_indices[idx]
                prev_layer = sorted_layer_indices[idx - 1]
                cur_count = len(layer_pos_map[cur_layer])
                prev_count = len(layer_pos_map[prev_layer])
                max_allowed = int(prev_count * 0.85)  # 상위는 하위의 85% 이하

                if cur_count > max_allowed and max_allowed >= 3:
                    # 중앙에서 가까운 위치 우선 유지 (가장자리 제거)
                    positions_list = layer_pos_map[cur_layer]
                    xs = [int(p[1].split("_")[0]) for p in positions_list]
                    ys = [int(p[1].split("_")[1]) for p in positions_list]
                    cx = (min(xs) + max(xs)) / 2
                    cy = (min(ys) + max(ys)) / 2

                    # 중앙 거리 기준 정렬 → 가까운 것 우선 보존
                    positions_list.sort(key=lambda p: abs(int(p[1].split("_")[0]) - cx) + abs(int(p[1].split("_")[1]) - cy))
                    # 3의 배수로 클램프
                    clamped = (max_allowed // 3) * 3
                    if clamped < 3:
                        clamped = 3
                    layer_pos_map[cur_layer] = positions_list[:clamped]
                    logger.debug(f"[PYRAMID_CLAMP] Layer {cur_layer}: {cur_count} -> {clamped} (prev={prev_count})")

            # all_layer_positions 재구성
            all_layer_positions = []
            for li in sorted_layer_indices:
                all_layer_positions.extend(layer_pos_map[li])

        # CRITICAL: Ensure total positions is divisible by 3
        # When layers are full, clamping may break divisibility
        total_positions = len(all_layer_positions)
        remainder = total_positions % 3

        # [v15.40] 패턴 모드에서는 position 삭제 금지 — 형태 보존이 최우선
        # 3의 배수는 타일 타입 재분배로 해결 (position이 아닌 type 조정)
        symmetry = params.symmetry_mode or "none"
        is_pattern_mode = level.get("_preserve_pattern", False)

        if remainder > 0 and not is_pattern_mode and symmetry == "none":
            # 비패턴 모드 + 대칭 없음: position 제거 허용
            all_layer_positions = all_layer_positions[:total_positions - remainder]
        elif remainder > 0:
            # 패턴 모드 또는 대칭 모드: position 보존, 타일 타입 재분배로 처리
            pass  # _ensure_tile_count_divisible_by_3에서 타입 재분배로 해결

        # CRITICAL FIX: Filter tile_types to match useTileCount
        # This prevents creating tiles outside the valid range (e.g., t10~t15 when useTileCount=9)
        use_tile_count = int(level.get("useTileCount", 6))
        valid_range = {f"t{i}" for i in range(1, use_tile_count + 1)}
        filtered_tile_types = [t for t in tile_types if t in valid_range or t == "t0"]
        # [v15.45] 필터 결과가 useTileCount보다 적으면 보충 — 그렇지 않으면 결과
        # 레벨이 실제로는 N(<useTileCount) 타입만 사용하면서 메타에는 useTileCount=N+α가
        # 기록되는 거짓이 발생함 (예: 입력 [t1,t3,t5,t8,t10,t14] + useTileCount=6 → 필터
        # 후 [t1,t3,t5]만 남아 3종으로 생성되지만 useTileCount=6 그대로).
        if len(filtered_tile_types) >= use_tile_count or "t0" in filtered_tile_types:
            tile_types = filtered_tile_types
        else:
            existing = list(filtered_tile_types)
            topup = select_color_balanced_tiles(use_tile_count, max_index=use_tile_count)
            for t in topup:
                if t not in existing:
                    existing.append(t)
                if len(existing) >= use_tile_count:
                    break
            tile_types = existing if existing else select_color_balanced_tiles(use_tile_count, max_index=use_tile_count)
        logger.debug(f"[TILE_ASSIGN] Filtered tile_types to useTileCount={use_tile_count}: {len(tile_types)} types")

        # CRITICAL: Distribute tile types ensuring each type has count divisible by 3
        # Calculate how many tiles of each type we need
        total_positions = len(all_layer_positions)
        num_tile_types = len(tile_types)

        # [v15.28] 균등도 기반 타일 분배
        # 난이도에 따라 타입별 분배량 조절
        uniformity = get_tile_uniformity(target)

        # 기본 균등 분배량 계산
        base_tiles_per_type = (total_positions // num_tile_types // 3) * 3
        if base_tiles_per_type < 3:
            base_tiles_per_type = 3

        # 균등도에 따른 타입별 분배량 조정
        # 낮은 균등도 = 일부 타입에 더 많이, 다른 타입에 더 적게
        tile_assignments = []

        if uniformity >= 0.9:
            # 높은 균등도: 모든 타입에 동일 분배
            for tile_type in tile_types:
                tile_assignments.extend([tile_type] * base_tiles_per_type)
        else:
            # 낮은 균등도: 타입별 차등 분배
            # variance_strength: 균등도가 낮을수록 큰 변동
            # uniformity 0.5 → strength 2, uniformity 0.7 → strength 1
            variance_strength = int((1.0 - uniformity) * 4) + 1  # 1 ~ 3

            # 타입별 분배량 계산
            type_allocations = {}
            total_allocated = 0

            # 타입을 랜덤하게 "많음/적음" 그룹으로 분류
            shuffled_types = list(tile_types)
            random.shuffle(shuffled_types)
            half = len(shuffled_types) // 2

            for i, tile_type in enumerate(shuffled_types):
                if i < half:
                    # 전반부: 더 많이 할당 (+3 ~ +9)
                    adjustment = random.randint(1, variance_strength) * 3
                else:
                    # 후반부: 더 적게 할당 (-3 ~ -9)
                    adjustment = -random.randint(1, variance_strength) * 3

                allocation = max(3, base_tiles_per_type + adjustment)
                # 3의 배수로 보정
                allocation = (allocation // 3) * 3

                type_allocations[tile_type] = allocation
                total_allocated += allocation

            # 총 타일 수 맞추기 (3의 배수 유지)
            diff = total_positions - total_allocated
            while abs(diff) >= 3:
                if diff > 0:
                    # 부족: 랜덤 타입에 3개 추가
                    t = random.choice(tile_types)
                    type_allocations[t] += 3
                    diff -= 3
                else:
                    # 초과: 가장 많은 타입에서 3개 제거
                    max_type = max(type_allocations, key=type_allocations.get)
                    if type_allocations[max_type] > 3:
                        type_allocations[max_type] -= 3
                        diff += 3
                    else:
                        break

            # 분배량에 따라 타일 생성
            for tile_type, count in type_allocations.items():
                tile_assignments.extend([tile_type] * count)

            logger.info(f"[TILE_DIST] uniformity={uniformity:.2f}, "
                       f"allocations={type_allocations}")

        # [v15.28] Round-robin 기반 균등 분배 (random.choice 대체)
        # 부족분을 순환 방식으로 분배하여 타입별 균등성 보장
        remaining_count = len(all_layer_positions) - len(tile_assignments)
        if remaining_count > 0:
            # 균등도에 따른 분배 방식 결정
            uniformity = get_tile_uniformity(target)

            if uniformity >= 0.9:
                # 높은 균등도: 완전 round-robin (순환)
                type_idx = 0
                while len(tile_assignments) < len(all_layer_positions):
                    tile_type = tile_types[type_idx % num_tile_types]
                    tile_assignments.extend([tile_type] * 3)
                    type_idx += 1
            elif uniformity >= 0.7:
                # 중간 균등도: 가중치 기반 round-robin
                # 현재 가장 적은 타입 우선 선택
                from collections import Counter
                while len(tile_assignments) < len(all_layer_positions):
                    type_counts = Counter(tile_assignments)
                    # 가장 적은 타입들 찾기
                    min_count = min(type_counts.get(t, 0) for t in tile_types)
                    underrepresented = [t for t in tile_types if type_counts.get(t, 0) == min_count]
                    tile_type = random.choice(underrepresented)
                    tile_assignments.extend([tile_type] * 3)
            else:
                # 낮은 균등도: 가중치 적용된 랜덤 (불균형 허용)
                # 기존 분포에 따라 가중치 부여 - 적은 타입이 더 높은 확률
                from collections import Counter
                while len(tile_assignments) < len(all_layer_positions):
                    type_counts = Counter(tile_assignments)
                    # 역가중치 계산: 적은 타입 = 높은 가중치
                    max_count = max(type_counts.get(t, 0) for t in tile_types) + 1
                    weights = [max_count - type_counts.get(t, 0) + 1 for t in tile_types]

                    # 균등도에 따라 가중치 강도 조절
                    # 낮은 균등도 = 더 평탄한 가중치 (불균형 허용)
                    weight_power = uniformity * 2  # 0.0~0.7 → 0.0~1.4
                    adjusted_weights = [w ** weight_power for w in weights]

                    # 가중치 기반 선택
                    total_weight = sum(adjusted_weights)
                    r = random.random() * total_weight
                    cumulative = 0
                    selected_type = tile_types[0]
                    for i, w in enumerate(adjusted_weights):
                        cumulative += w
                        if r <= cumulative:
                            selected_type = tile_types[i]
                            break
                    tile_assignments.extend([selected_type] * 3)

            logger.debug(f"[TILE_DIST] uniformity={uniformity:.2f}, "
                        f"remaining={remaining_count}, final_count={len(tile_assignments)}")

        # If we have more assignments than positions, trim to match
        # (positions are already divisible by 3 from earlier check)
        if len(tile_assignments) > len(all_layer_positions):
            tile_assignments = tile_assignments[:len(all_layer_positions)]

        # Initialize tiles dict for each layer
        for layer_idx in active_layers:
            level[f"layer_{layer_idx}"]["tiles"] = {}

        # PATTERN MODE: Special tile distribution to prevent same-type blocking
        # When all layers share the same positions, we must ensure different types
        # are assigned to the same position across layers to prevent blocking issues
        is_pattern_mode = level.get("_preserve_pattern", False)

        if is_pattern_mode:
            # Pattern mode: Assign tiles to prevent same-type blocking
            self._assign_tiles_pattern_mode(
                level, all_layer_positions, tile_assignments, tile_types, active_layers
            )
        elif target >= 0.6:
            # HIGH DIFFICULTY: Spread same-type tiles apart for increased challenge
            self._assign_tiles_with_spread(
                level, all_layer_positions, tile_assignments, tile_types, target
            )
        else:
            # Original random shuffle for easy/medium levels
            random.shuffle(tile_assignments)

            # Assign tiles to positions
            for i, (layer_idx, pos) in enumerate(all_layer_positions):
                if i < len(tile_assignments):
                    tile_type = tile_assignments[i]
                else:
                    # Fallback (shouldn't happen)
                    tile_type = random.choice(tile_types)

                layer_key = f"layer_{layer_idx}"
                level[layer_key]["tiles"][pos] = [tile_type, ""]

        # Update tile counts
        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        return level

    def _assign_tiles_pattern_mode(
        self,
        level: Dict[str, Any],
        all_layer_positions: List[Tuple[int, str]],
        tile_assignments: List[str],
        tile_types: List[str],
        active_layers: List[int]
    ) -> None:
        """Assign tiles in pattern mode to prevent same-type blocking.

        In pattern mode, all layers share the same positions. To prevent deadlock,
        we ensure that tiles at the same position across layers have DIFFERENT types.
        This prevents same-type blocking where a tile blocks another tile of the same type.

        CRITICAL: All tile types MUST have counts divisible by 3 for playable levels.

        Strategy:
        1. Group positions by their (x, y) coordinate
        2. Ensure total tiles is divisible by 3 (remove excess if needed)
        3. Distribute tiles ensuring each type gets a multiple of 3
        4. For each position, assign rotating tile types across layers
        """
        from collections import defaultdict

        # CRITICAL: Get useTileCount from level to determine valid tile types
        use_tile_count = int(level.get("useTileCount", 6))

        # CRITICAL: When tile_types contains only 't0' (placeholder for client-side randomization),
        # we need to expand to actual tile types for pattern mode distribution.
        # Otherwise, all tiles will be 't0' causing same-type blocking in validation.
        if len(tile_types) == 1 and tile_types[0] == "t0":
            # [v15.40] 색상 균등 분배로 확장
            tile_types = select_color_balanced_tiles(use_tile_count, max_index=use_tile_count)
        else:
            # CRITICAL FIX: Ensure tile_types does not exceed useTileCount
            valid_range = {f"t{i}" for i in range(1, use_tile_count + 1)}
            in_range = [t for t in tile_types if t in valid_range]
            # [v15.45] 필터 후 부족하면 useTileCount까지 보충 (메타-실제 정합성 유지)
            if len(in_range) >= use_tile_count:
                tile_types = in_range
            else:
                topup = select_color_balanced_tiles(use_tile_count, max_index=use_tile_count)
                for t in topup:
                    if t not in in_range:
                        in_range.append(t)
                    if len(in_range) >= use_tile_count:
                        break
                tile_types = in_range if in_range else select_color_balanced_tiles(use_tile_count, max_index=use_tile_count)
            logger.debug(f"[PATTERN_MODE] Filtered tile_types to useTileCount={use_tile_count}: {tile_types}")

        # Group positions by coordinate
        positions_by_coord: Dict[str, List[int]] = defaultdict(list)
        for layer_idx, pos in all_layer_positions:
            positions_by_coord[pos].append(layer_idx)

        # Sort layers in each position (bottom to top)
        for pos in positions_by_coord:
            positions_by_coord[pos].sort()

        # [v15.40] 패턴 형태 보존: 3의 배수 보정 시 타일 위치 삭제 금지
        # 타일 타입 분배 단계에서 나머지를 흡수 (위치는 100% 보존)
        total_tiles = len(all_layer_positions)
        excess = total_tiles % 3
        if excess > 0:
            logger.debug(f"[PATTERN_MODE] Total {total_tiles} not div3 (excess={excess}). "
                        f"Positions preserved - will adjust via type distribution.")

        num_types = len(tile_types)

        # Calculate tiles per type ensuring each is divisible by 3
        # Strategy: Distribute as evenly as possible with each being a multiple of 3
        base_per_type = (total_tiles // num_types // 3) * 3
        if base_per_type < 3:
            base_per_type = 3

        # Track how many tiles of each type we've assigned
        type_counts = {t: 0 for t in tile_types}
        type_targets = {t: base_per_type for t in tile_types}

        # Distribute remaining tiles (must be multiples of 3)
        remaining = total_tiles - (base_per_type * num_types)

        # remaining must be distributed as multiples of 3 to each type
        type_idx = 0
        while remaining >= 3:
            type_targets[tile_types[type_idx % num_types]] += 3
            remaining -= 3
            type_idx += 1

        # [v15.40] 나머지 타일은 삭제하지 않고 타입 분배에서 흡수
        # 패턴은 3의 배수로 디자인할 예정이므로 이 경로는 거의 사용 안 됨
        if remaining > 0:
            logger.warning(f"[PATTERN_MODE] Remainder {remaining} tiles - assigning to first type (no deletion)")
            type_targets[tile_types[0]] += remaining

        # Shuffle positions for randomness
        all_positions = list(positions_by_coord.keys())
        random.shuffle(all_positions)

        # [v16 🅒] 타입 공간 분산(뭉침 방지). 같은 타입이 2D 평면에서 인접해 뭉치면 시각적으로
        # 어색하고 난이도 분포도 왜곡된다. 위치별 타입을 고를 때 '8-이웃 좌표에 이미 놓인 동일
        # 타입 수'를 세어 가장 적은(=덜 뭉치는) 타입을 우선 선택한다(블루노이즈식 그리디).
        # 불변식은 유지: type_targets(÷3) 초과 금지 + 같은 좌표 수직 동일타입 회피(데드락 방지).
        anti_cluster = getattr(self, "_anti_cluster_tiles", True)
        placed_2d: Dict[Tuple[int, int], List[str]] = defaultdict(list)

        def _coord(p: str) -> Tuple[int, int]:
            a, b = p.split("_")
            return int(a), int(b)

        def _neighbor_same(px: int, py: int, ttype: str) -> int:
            n = 0
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    for placed in placed_2d.get((px + dx, py + dy), ()):  # type: ignore[arg-type]
                        if placed == ttype:
                            n += 1
            return n

        # For each position, choose types minimizing local same-type clustering
        type_rotation = list(tile_types)
        random.shuffle(type_rotation)
        rotation_idx = 0

        for pos in all_positions:
            layers = positions_by_coord[pos]
            px, py = _coord(pos)

            # Assign different types to each layer at this position
            for i, layer_idx in enumerate(layers):
                prev_type = None
                if i > 0:
                    prev_tile = level[f"layer_{layers[i-1]}"]["tiles"].get(pos)
                    if prev_tile:
                        prev_type = prev_tile[0]

                # 후보: 타깃 여유가 있는 타입
                eligible = [t for t in tile_types if type_counts[t] < type_targets[t]]
                chosen = None
                if eligible:
                    if anti_cluster:
                        # (이웃 동일타입 수, 수직 동일타입 위반, 로테이션 거리)로 정렬 — 적을수록 우선
                        def _key(t: str, _start=rotation_idx):
                            vert = 1 if (prev_type is not None and t == prev_type) else 0
                            try:
                                rot = (type_rotation.index(t) - _start) % num_types
                            except ValueError:
                                rot = num_types
                            return (_neighbor_same(px, py, t), vert, rot)
                        chosen = min(eligible, key=_key)
                    else:
                        # 기존 로테이션 방식(수직 회피 우선)
                        order = [type_rotation[(rotation_idx + i + a) % num_types] for a in range(num_types)]
                        for cand in order:
                            if cand in eligible and not (prev_type is not None and cand == prev_type):
                                chosen = cand
                                break
                        if chosen is None:
                            chosen = next((c for c in order if c in eligible), eligible[0])
                else:
                    # 타깃 모두 소진 — 최후수단(÷3 후처리에서 정정)
                    chosen = random.choice(tile_types)

                level[f"layer_{layer_idx}"]["tiles"][pos] = [chosen, ""]
                type_counts[chosen] += 1
                placed_2d[(px, py)].append(chosen)

            # Rotate starting point for next position group
            rotation_idx = (rotation_idx + 1) % num_types

        # Final validation: ensure all tile types are divisible by 3
        non_divisible = {t: c for t, c in type_counts.items() if c % 3 != 0}
        if non_divisible:
            logger.warning(f"[PATTERN_MODE] Non-divisible counts found: {non_divisible}, attempting fix...")
            # Redistribute to ensure divisibility
            for tile_type, count in non_divisible.items():
                excess = count % 3
                # Need to reassign 'excess' tiles to other types
                # Find positions with this tile type and reassign some
                for layer_idx in active_layers:
                    if excess == 0:
                        break
                    layer_key = f"layer_{layer_idx}"
                    tiles = level[layer_key]["tiles"]
                    for pos, tile_data in list(tiles.items()):
                        if excess == 0:
                            break
                        if tile_data[0] == tile_type:
                            # Find a type that needs more tiles
                            for other_type in tile_types:
                                if other_type != tile_type and type_counts[other_type] % 3 != 0:
                                    other_need = 3 - (type_counts[other_type] % 3)
                                    if other_need > 0:
                                        tiles[pos] = [other_type, ""]
                                        type_counts[tile_type] -= 1
                                        type_counts[other_type] += 1
                                        excess -= 1
                                        break

        # Post-fix validation
        non_divisible_final = {t: c for t, c in type_counts.items() if c % 3 != 0}
        if non_divisible_final:
            logger.error(f"[PATTERN_MODE] CRITICAL: Still have non-divisible counts: {non_divisible_final}")
        else:
            logger.debug(f"[PATTERN_MODE] All tile types divisible by 3: {type_counts}")

    def _assign_tiles_with_spread(
        self,
        level: Dict[str, Any],
        all_layer_positions: List[Tuple[int, str]],
        tile_assignments: List[str],
        tile_types: List[str],
        target_difficulty: float
    ) -> None:
        """Assign tile types with same-type tiles spread apart for higher difficulty.

        For hard levels, this places tiles of the same type as far apart as possible,
        making it harder to find and match them.

        Args:
            level: Level dict to modify
            all_layer_positions: List of (layer_idx, pos) tuples
            tile_assignments: List of tile types to assign
            tile_types: Available tile types
            target_difficulty: Target difficulty (0.0-1.0)
        """
        from collections import defaultdict

        def get_pos_coords(pos: str) -> Tuple[int, int]:
            """Extract x, y from position string."""
            parts = pos.split("_")
            return int(parts[0]), int(parts[1])

        def calc_distance(pos1: str, layer1: int, pos2: str, layer2: int) -> float:
            """Calculate distance between two positions (including layer difference)."""
            x1, y1 = get_pos_coords(pos1)
            x2, y2 = get_pos_coords(pos2)
            # Include layer difference as additional distance factor
            layer_dist = abs(layer1 - layer2) * 2  # Layer separation adds distance
            return ((x1 - x2) ** 2 + (y1 - y2) ** 2 + layer_dist ** 2) ** 0.5

        def min_distance_to_same_type(
            pos: str, layer: int, tile_type: str, placed: Dict[str, List[Tuple[int, str]]]
        ) -> float:
            """Calculate minimum distance from pos to any placed tile of same type."""
            if tile_type not in placed or not placed[tile_type]:
                return float('inf')  # No same-type tiles yet, maximum distance

            min_dist = float('inf')
            for placed_layer, placed_pos in placed[tile_type]:
                dist = calc_distance(pos, layer, placed_pos, placed_layer)
                min_dist = min(min_dist, dist)
            return min_dist

        # Count how many of each type we need
        type_counts = defaultdict(int)
        for t in tile_assignments:
            type_counts[t] += 1

        # Track placed tiles by type: {type: [(layer, pos), ...]}
        placed_tiles: Dict[str, List[Tuple[int, str]]] = defaultdict(list)

        # Available positions (copy to modify)
        available_positions = list(all_layer_positions)
        random.shuffle(available_positions)  # Start with random order

        # Spread intensity based on difficulty (0.6 = mild spread, 1.0 = maximum spread)
        # Higher intensity = more strictly enforce distance
        spread_intensity = (target_difficulty - 0.6) / 0.4  # 0.0 to 1.0 for difficulty 0.6-1.0
        spread_intensity = max(0.0, min(1.0, spread_intensity))

        # For each tile type, place tiles trying to maximize distance from same type
        types_to_place = list(type_counts.keys())
        random.shuffle(types_to_place)

        for tile_type in types_to_place:
            count = type_counts[tile_type]

            for _ in range(count):
                if not available_positions:
                    break

                # Find position with maximum distance from existing same-type tiles
                best_pos = None
                best_layer = None
                best_score = -1

                # Sample positions to check (for performance, don't check all)
                sample_size = min(len(available_positions), max(10, int(len(available_positions) * 0.3)))
                positions_to_check = random.sample(available_positions, sample_size)

                for layer_idx, pos in positions_to_check:
                    min_dist = min_distance_to_same_type(pos, layer_idx, tile_type, placed_tiles)

                    # Score combines distance with some randomness (based on spread intensity)
                    # Low intensity = more random, High intensity = strictly distance-based
                    random_factor = random.random() * (1 - spread_intensity) * 5
                    score = min_dist + random_factor

                    if score > best_score:
                        best_score = score
                        best_pos = pos
                        best_layer = layer_idx

                if best_pos is not None:
                    # Place tile
                    layer_key = f"layer_{best_layer}"
                    level[layer_key]["tiles"][best_pos] = [tile_type, ""]

                    # Track placement
                    placed_tiles[tile_type].append((best_layer, best_pos))

                    # Remove from available
                    available_positions.remove((best_layer, best_pos))

        # If any positions left (shouldn't happen), fill with random types
        for layer_idx, pos in available_positions:
            tile_type = random.choice(tile_types)
            layer_key = f"layer_{layer_idx}"
            level[layer_key]["tiles"][pos] = [tile_type, ""]

    def _generate_layer_positions(
        self, cols: int, rows: int, density: float,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None
    ) -> List[str]:
        """Generate tile positions for a layer based on density."""
        all_positions = []
        for x in range(cols):
            for y in range(rows):
                all_positions.append(f"{x}_{y}")

        # Select positions based on density
        target_count = max(1, int(len(all_positions) * density))

        # IMPORTANT: Ensure tile count is divisible by 3 for match-3 game
        target_count = (target_count // 3) * 3
        if target_count == 0:
            target_count = 3  # Minimum 3 tiles

        selected = self._generate_positions_with_pattern(
            cols, rows, target_count, symmetry_mode, pattern_type
        )

        return selected

    def _generate_layer_positions_for_count(
        self, cols: int, rows: int, target_count: int,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None,
        pattern_index: Optional[int] = None,
        target_difficulty: Optional[float] = None
    ) -> List[str]:
        """Generate tile positions for a layer with specific count."""
        # Clamp to available positions
        max_positions = cols * rows
        actual_count = min(target_count, max_positions)
        if actual_count <= 0:
            return []

        selected = self._generate_positions_with_pattern(
            cols, rows, actual_count, symmetry_mode, pattern_type, pattern_index, target_difficulty
        )

        # CRITICAL: When symmetry is applied, do NOT trim or pad randomly
        # as it would break the symmetric pattern. Only adjust for "none" symmetry.
        has_symmetry = symmetry_mode and symmetry_mode != "none"

        if has_symmetry:
            # For symmetric patterns, return as-is to preserve symmetry
            # The tile assignment code will handle any count differences
            return selected

        # [v15.40] pattern_index 지정 시 패턴 형태를 최대한 보존
        # 트리밍하지 않고 패턴 전체를 반환 → 타일 수는 패턴이 결정
        if pattern_index is not None:
            return selected

        # Only for symmetry_mode="none" and no specific pattern:
        # Ensure exact tile count by trimming or padding
        if len(selected) > actual_count:
            # Trim excess - prefer to keep positions closer to center
            center_x, center_y = cols / 2.0, rows / 2.0
            def distance_from_center(pos: str) -> float:
                parts = pos.split("_")
                x, y = int(parts[0]), int(parts[1])
                return ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
            selected.sort(key=distance_from_center)
            selected = selected[:actual_count]
        elif len(selected) < actual_count:
            # Pad with random unused positions
            all_positions = set(f"{x}_{y}" for x in range(cols) for y in range(rows))
            unused = list(all_positions - set(selected))
            if unused:
                random.shuffle(unused)
                needed = actual_count - len(selected)
                selected.extend(unused[:needed])

        return selected

    def _generate_positions_with_pattern(
        self, cols: int, rows: int, target_count: int,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None,
        pattern_index: Optional[int] = None,
        target_difficulty: Optional[float] = None
    ) -> List[str]:
        """Generate positions with symmetry and pattern options."""
        # [v15.40] pattern_index가 지정되면 반드시 aesthetic 모드 사용
        # pattern_index는 사전 정의된 모양 템플릿 → aesthetic 경로에서만 처리됨
        # geometric/clustered/random은 pattern_index를 무시하므로 강제 전환
        if pattern_index is not None:
            pattern = "aesthetic"
        else:
            pattern = pattern_type or "geometric"

        # Resolve symmetry mode:
        # - PATTERN MODE: When pattern_index is specified, ALWAYS use "none" (pattern is pre-designed)
        # - "none" explicitly passed: truly no symmetry (for exact tile counts)
        # - None (not specified): random single-axis for visual appeal
        # - "both": 4-way symmetry for aesthetic patterns

        # CRITICAL: Pattern mode overrides all symmetry settings
        # Patterns are pre-designed shapes - applying symmetry would distort them
        if pattern_index is not None:
            symmetry = "none"
        elif symmetry_mode == "none":
            # User explicitly requested no symmetry - respect this for exact counts
            symmetry = "none"
        elif symmetry_mode is None:
            # Default: weighted random symmetry based on GBoost level analysis
            # Human-designed levels show 73% horizontal symmetry, 33% vertical symmetry
            # This creates visually balanced and appealing tile arrangements
            symmetry_options = ["horizontal", "vertical", "none", "both"]
            # 55% horizontal (primary), 15% vertical, 15% none, 15% both
            # Combined h+both = 70% horizontal influence (close to 73% observed)
            symmetry_weights = [0.55, 0.15, 0.15, 0.15]
            symmetry = random.choices(symmetry_options, weights=symmetry_weights, k=1)[0]
        else:
            symmetry = symmetry_mode

        # DEBUG: Log position generation parameters
        import logging
        _logger = logging.getLogger(__name__)
        _logger.debug(f"[POSITION_GEN_DEBUG] cols={cols}, rows={rows}, target_count={target_count}, "
                      f"symmetry_mode={symmetry_mode}, symmetry={symmetry}, pattern={pattern}")

        # Generate base positions based on pattern type
        if pattern == "aesthetic":
            # Aesthetic mode: generate pattern then apply symmetry mirroring
            raw_positions = self._generate_aesthetic_positions(cols, rows, target_count, pattern_index, target_difficulty)
            # Apply symmetry to aesthetic patterns too
            base_positions = self._apply_symmetry_to_positions(cols, rows, raw_positions, symmetry, target_count)
        elif pattern == "geometric":
            base_positions = self._generate_geometric_positions(cols, rows, target_count, symmetry)
        elif pattern == "clustered":
            base_positions = self._generate_clustered_positions(cols, rows, target_count, symmetry)
        else:  # random
            base_positions = self._generate_random_positions(cols, rows, target_count, symmetry)

        return base_positions

    def _compute_layer_size_diversity(
        self,
        active_layers: List[int],
        base_sizes: List[Tuple[int, int]],
        level_number: Optional[int],
        start_level: Optional[int],
        min_size: int = SIZE_DIVERSITY_MIN_SIZE,
    ) -> Optional[Dict[int, int]]:
        """[B] 층별 채움 크기(정사각 s) 다양화 배정.

        Args:
            active_layers: 활성 레이어 인덱스 목록.
            base_sizes: active_layers와 index 정렬된 (base_cols, base_rows) 목록(홀짝 교대값).
            level_number: 현재 레벨 번호.
            start_level: 이 값 이상부터 적용. None이면 미적용.
            min_size: 최소 채움 크기(기본 3).

        Returns:
            layer_idx -> s 매핑(정사각 채움 크기) 또는 None(미적용).
            s는 [min_size, min(base_cols, base_rows)] 범위 랜덤, 인접층과 같은 크기 회피.
            호출측은 레이어 col/row를 base(교대값) 그대로 유지해야 함(게임 정합 필수).
        """
        if start_level is None or level_number is None or level_number < start_level:
            return None

        sizes: Dict[int, int] = {}
        prev_s: Optional[int] = None
        for li, layer_idx in enumerate(active_layers):
            base_cols, base_rows = base_sizes[li]
            max_s = min(base_cols, base_rows)
            if max_s <= min_size:
                s = max_s  # 그리드가 최소 이하 → 그대로(다양화 불가)
            else:
                choices = [v for v in range(min_size, max_s + 1) if v != prev_s]
                if not choices:
                    choices = list(range(min_size, max_s + 1))
                s = random.choice(choices)
            sizes[layer_idx] = s
            prev_s = s

        logger.info(
            f"[SIZE_DIVERSITY] level={level_number} start={start_level} "
            f"mode={SIZE_DIVERSITY_MODE} sizes={sizes}"
        )
        return sizes

    def _generate_aesthetic_positions(
        self, cols: int, rows: int, target_count: int,
        pattern_index: Optional[int] = None,
        target_difficulty: Optional[float] = None
    ) -> List[str]:
        """Generate visually appealing positions using 50 diverse patterns.

        Patterns are inspired by high-level stages from Tile Buster, Triple Match 3D,
        Tile Explorer, and other popular tile-matching puzzle games.

        Categories:
        - 0-9: Basic shapes (rectangle, diamond, oval, cross, donut, etc.)
        - 10-14: Arrow/Direction patterns
        - 15-19: Star/Celestial patterns
        - 20-29: Letter shapes (H, I, L, U, X, Y, Z, S, O, C)
        - 30-39: Advanced geometric (triangles, hourglass, stairs, pyramid, zigzag)
        - 40-44: Frame/Border patterns
        - 45-49: Artistic patterns (butterfly, flower, islands, stripes, honeycomb)

        Args:
            cols: Grid columns
            rows: Grid rows
            target_count: Target number of tiles
            pattern_index: If specified (0-63), forces use of that specific pattern.
                          None = auto-select best pattern based on target_count.
            target_difficulty: Target difficulty (0.0-1.0) for dynamic fill ratio calculation.
        """
        import math

        # [v15.40] 커스텀 패턴 우선 적용
        if pattern_index is not None:
            custom = self._get_custom_pattern(pattern_index, cols, rows)
            if custom is not None:
                return custom
            else:
                logger.debug(f"[PATTERN_FALLBACK] No custom pattern for #{pattern_index} at {cols}x{rows}, using code pattern")

        center_x, center_y = cols / 2.0, rows / 2.0

        # === PATTERN DENSITY WEIGHTS (v15.7) ===
        # Patterns with higher tile density get lower fill ratio to compensate
        # 1.0 = baseline, >1.0 = dense (reduce fill), <1.0 = sparse (increase fill)
        PATTERN_DENSITY_WEIGHTS = {
            # Basic shapes - generally baseline
            0: 1.0,   # rectangle - baseline
            1: 0.9,   # diamond - slightly less
            2: 0.95,  # oval
            3: 1.15,  # cross - more tiles (full width + height)
            4: 0.8,   # donut - hollow center
            5: 0.8,   # concentric diamond - ring shape
            6: 0.85,  # corner anchored
            7: 0.9,   # hexagonal
            8: 1.1,   # heart - dense pixel art
            9: 1.0,   # T-shape
            # Arrows
            10: 1.0, 11: 1.0, 12: 1.0, 13: 1.0, 14: 0.9,  # arrows, chevron
            # Celestial - often dense
            15: 1.2,  # star 5-pointed - many tiles
            16: 1.25, # star 6-pointed - more tiles
            17: 0.85, # crescent - sparse
            18: 1.3,  # sun burst - VERY dense
            19: 0.9,  # spiral
            # Letters - variable
            20: 1.1, 21: 0.8, 22: 0.85, 23: 0.9, 24: 1.0,  # H, I, L, U, X
            25: 0.9, 26: 1.0, 27: 1.0, 28: 0.85, 29: 0.8,  # Y, Z, S, O, C
            # Geometric
            30: 0.9, 31: 0.9,  # triangles
            32: 1.0, 33: 1.0,  # hourglass, bowtie
            34: 0.85, 35: 0.85, # stairs
            36: 0.9, 37: 0.9,  # pyramid
            38: 0.95, 39: 1.0, # zigzag, wave
            # Frames - typically sparse (border only)
            40: 0.75, 41: 0.8, 42: 0.75, 43: 0.7, 44: 1.0,
            # Artistic
            45: 1.15, # butterfly - dense
            46: 1.2,  # flower - dense
            47: 0.7,  # scattered islands - sparse
            48: 0.9, 49: 1.0,  # diagonal stripes, honeycomb
            # Islands/Bridges
            50: 0.8, 51: 0.8, 52: 0.7, 53: 0.75, 54: 0.8, 55: 0.85,
            # GBoost
            56: 0.75, 57: 0.8, 58: 0.85, 59: 0.9, 60: 0.7, 61: 0.9, 62: 0.85, 63: 0.9,
            # Layered
            64: 0.85,
        }

        # PATTERN MODE FIX: When pattern_index is specified, use dynamic fill ratio
        # based on target_difficulty and pattern density weight
        if pattern_index is not None:
            # Base fill ratio from target difficulty (0.1 → 30%, 0.5 → 50%, 0.9 → 70%)
            if target_difficulty is not None:
                base_fill_ratio = 0.25 + target_difficulty * 0.5  # 0.25 ~ 0.75
            else:
                base_fill_ratio = 0.5  # Default 50%

            # Apply pattern density weight
            density_weight = PATTERN_DENSITY_WEIGHTS.get(pattern_index, 1.0)
            adjusted_fill_ratio = base_fill_ratio / density_weight

            # Clamp to reasonable range (25% ~ 70%)
            adjusted_fill_ratio = max(0.25, min(0.70, adjusted_fill_ratio))

            target_count = int(cols * rows * adjusted_fill_ratio)

        # ============ Category 1: Basic Shapes (0-9) ============

        # Pattern 0: Filled Rectangle
        def filled_rectangle():
            # [v15.40] 1칸 마진의 중앙 직사각형 (8x8 → 6x6 내부)
            margin = 1
            positions = []
            for x in range(margin, cols - margin):
                for y in range(margin, rows - margin):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 1: Diamond/Rhombus shape
        def diamond_shape():
            # Use grid-based radius for consistent visual shape
            # Diamond spans ~60% of grid for clear visual recognition
            radius = min(cols, rows) * 0.6
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dist = abs(x - center_x + 0.5) + abs(y - center_y + 0.5)
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 2: Oval/Ellipse shape
        def oval_shape():
            radius_x = int((target_count * cols / (rows * 3.14)) ** 0.5) + 1
            radius_y = int((target_count * rows / (cols * 3.14)) ** 0.5) + 1
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / max(1, radius_x)
                    dy = (y - center_y + 0.5) / max(1, radius_y)
                    if dx * dx + dy * dy <= 1.0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 3: Plus/Cross shape
        def cross_shape():
            positions = []
            arm_width = max(2, int(cols * 0.4))
            arm_height = max(2, int(rows * 0.4))
            start_x = int((cols - arm_width) / 2)
            start_y = int((rows - arm_height) / 2)
            for x in range(cols):
                for y in range(start_y, min(rows, start_y + arm_height)):
                    positions.append(f"{x}_{y}")
            for x in range(start_x, min(cols, start_x + arm_width)):
                for y in range(rows):
                    if f"{x}_{y}" not in positions:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 4: Donut shape (hollow center) - 테두리 굵기 2칸
        def donut_shape():
            # 그리드 기반 반지름 계산 (더 두꺼운 테두리)
            outer_radius = min(cols, rows) * 0.45
            border_width = 2  # 테두리 굵기 2칸으로 증가
            inner_radius = max(1, outer_radius - border_width)
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dist = ((x - center_x + 0.5) ** 2 + (y - center_y + 0.5) ** 2) ** 0.5
                    if inner_radius <= dist <= outer_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 5: Concentric diamond - 테두리 굵기 2칸 링 형태
        def concentric_diamond():
            positions = []
            # 그리드 기반 반지름 (다이아몬드 형태)
            outer_radius = min(cols, rows) * 0.45
            border_width = 2  # 테두리 굵기 2칸으로 증가
            inner_radius = max(0, outer_radius - border_width)
            for x in range(cols):
                for y in range(rows):
                    dist = abs(x - center_x + 0.5) + abs(y - center_y + 0.5)
                    # 링 형태: 내부 반지름과 외부 반지름 사이만 포함
                    if inner_radius <= dist <= outer_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 6: Corner Anchored - 4꼭짓점 삼각형 + 1타일 연결
        # 각 코너에서 삼각형 모양 + 꼭짓점 사이 1타일 너비로 연결
        def corner_anchored():
            positions = []
            # Corner triangle size based on grid
            corner_size = max(2, min(cols, rows) // 3)

            # 1. Top-left corner triangle
            for y in range(corner_size):
                for x in range(corner_size - y):
                    positions.append(f"{x}_{y}")

            # 2. Top-right corner triangle
            for y in range(corner_size):
                for x in range(cols - corner_size + y, cols):
                    positions.append(f"{x}_{y}")

            # 3. Bottom-left corner triangle
            for y in range(rows - corner_size, rows):
                for x in range(y - (rows - corner_size) + 1):
                    positions.append(f"{x}_{y}")

            # 4. Bottom-right corner triangle
            for y in range(rows - corner_size, rows):
                for x in range(cols - (y - (rows - corner_size)) - 1, cols):
                    positions.append(f"{x}_{y}")

            # 5. Connect corners with 1-tile bridges
            # Top edge (connecting top-left to top-right)
            for x in range(corner_size, cols - corner_size):
                positions.append(f"{x}_0")

            # Bottom edge (connecting bottom-left to bottom-right)
            for x in range(corner_size, cols - corner_size):
                positions.append(f"{x}_{rows - 1}")

            # Left edge (connecting top-left to bottom-left)
            for y in range(corner_size, rows - corner_size):
                positions.append(f"0_{y}")

            # Right edge (connecting top-right to bottom-right)
            for y in range(corner_size, rows - corner_size):
                positions.append(f"{cols - 1}_{y}")

            return positions

        # Pattern 7: Hexagonal-ish pattern
        def hexagonal():
            positions = []
            radius = int((target_count / 2.6) ** 0.5) + 1
            for x in range(cols):
                for y in range(rows):
                    dx = abs(x - center_x + 0.5)
                    dy = abs(y - center_y + 0.5) * 1.15
                    dist = max(dx, dy, (dx + dy) * 0.55)
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 8: Heart shape (pixel art style, scales to grid size)
        def heart_shape():
            positions = []
            # Define heart templates for different grid sizes (symmetric designs)
            if cols <= 5:
                # Small heart for tiny grids (5 columns)
                template = [
                    " # # ",
                    "#####",
                    "#####",
                    " ### ",
                    "  #  ",
                ]
            elif cols == 6:
                # 6-column symmetric heart
                template = [
                    " #  # ",
                    "######",
                    "######",
                    " #### ",
                    "  ##  ",
                    "  ##  ",
                ]
            elif cols == 7:
                # 7-column symmetric heart (centered)
                template = [
                    ".##.##.",
                    "#######",
                    "#######",
                    ".#####.",
                    "..###..",
                    "...#...",
                ]
            else:
                # Large heart for 8+ sized grids (8 columns)
                template = [
                    " ##  ## ",
                    "########",
                    "########",
                    "########",
                    " ###### ",
                    "  ####  ",
                    "   ##   ",
                    "   ##   ",
                ]

            template_rows = len(template)
            template_cols = max(len(r) for r in template)

            # Center the heart in the grid
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)

            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 9: T-shape
        def t_shape():
            positions = []
            bar_height = max(2, rows // 4)
            stem_width = max(2, cols // 3)
            stem_start_x = int((cols - stem_width) / 2)
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            for x in range(stem_start_x, min(cols, stem_start_x + stem_width)):
                for y in range(bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # ============ Category 2: Arrow/Direction Patterns (10-14) ============

        # Pattern 10: Arrow Up
        def arrow_up():
            positions = []
            tip_y = 0
            base_y = rows - 1
            arrow_width = max(2, cols // 3)
            start_x = int((cols - arrow_width) / 2)
            # Arrow head (triangle)
            for y in range(rows // 2):
                width = max(1, (y + 1) * 2)
                sx = int(center_x - width / 2)
                for x in range(sx, min(cols, sx + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            # Arrow stem
            for x in range(start_x, min(cols, start_x + arrow_width)):
                for y in range(rows // 2, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 11: Arrow Down
        def arrow_down():
            positions = []
            arrow_width = max(2, cols // 3)
            start_x = int((cols - arrow_width) / 2)
            # Arrow stem (top)
            for x in range(start_x, min(cols, start_x + arrow_width)):
                for y in range(rows // 2):
                    positions.append(f"{x}_{y}")
            # Arrow head (triangle pointing down)
            for y in range(rows // 2, rows):
                rel_y = y - rows // 2
                width = max(1, cols - rel_y * 2)
                sx = int(center_x - width / 2)
                for x in range(sx, min(cols, sx + width)):
                    if 0 <= x < cols and width > 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 12: Arrow Left
        def arrow_left():
            positions = []
            arrow_height = max(2, rows // 3)
            start_y = int((rows - arrow_height) / 2)
            # Arrow head (triangle pointing left)
            for x in range(cols // 2):
                height = max(1, (x + 1) * 2)
                sy = int(center_y - height / 2)
                for y in range(sy, min(rows, sy + height)):
                    if 0 <= y < rows:
                        positions.append(f"{x}_{y}")
            # Arrow stem
            for y in range(start_y, min(rows, start_y + arrow_height)):
                for x in range(cols // 2, cols):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 13: Arrow Right
        def arrow_right():
            positions = []
            arrow_height = max(2, rows // 3)
            start_y = int((rows - arrow_height) / 2)
            # Arrow stem (left side)
            for y in range(start_y, min(rows, start_y + arrow_height)):
                for x in range(cols // 2):
                    positions.append(f"{x}_{y}")
            # Arrow head (triangle pointing right)
            for x in range(cols // 2, cols):
                rel_x = x - cols // 2
                height = max(1, rows - rel_x * 2)
                sy = int(center_y - height / 2)
                for y in range(sy, min(rows, sy + height)):
                    if 0 <= y < rows and height > 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 14: Chevron (double arrow) - 테두리 굵기 2~3칸으로 증가
        def chevron_pattern():
            positions = []
            # 테두리 굵기 2~3칸으로 증가
            thickness = max(3, min(cols, rows) // 3)
            for x in range(cols):
                for y in range(rows):
                    # V shape - 더 두꺼운 굽은 테두리
                    v_dist = abs(y - (rows - 1 - abs(x - center_x + 0.5) * rows / cols * 0.8))
                    if v_dist <= thickness:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 3: Star/Celestial Patterns (15-19) ============

        # Pattern 15: Five-pointed Star (pixel art style, scales to grid size)
        def star_five_point():
            positions = []
            # Define star templates for different grid sizes
            if cols <= 5 or rows <= 5:
                # Small star for tiny grids
                template = [
                    "  #  ",
                    " ### ",
                    "#####",
                    " # # ",
                    "# # #",
                ]
            elif cols <= 7 or rows <= 7:
                # Medium star for 6-7 sized grids
                template = [
                    "   #   ",
                    "  ###  ",
                    " ##### ",
                    "#######",
                    " # # # ",
                    "#  #  #",
                    "#     #",
                ]
            else:
                # Large star for 8+ sized grids
                template = [
                    "   ##   ",
                    "   ##   ",
                    "  ####  ",
                    "########",
                    "########",
                    " ##  ## ",
                    "##    ##",
                    "#      #",
                ]

            template_rows = len(template)
            template_cols = max(len(r) for r in template)

            # Center the star in the grid
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)

            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 16: Six-pointed Star (Star of David)
        def star_six_point():
            positions = []
            radius = min(cols, rows) / 2.5
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    # Two overlapping triangles
                    tri1 = (dy <= radius * 0.5 - abs(dx) * 0.866) or (dy >= -radius * 0.5 + abs(dx) * 0.866 and dy <= 0)
                    tri2 = (dy >= -radius * 0.5 + abs(dx) * 0.866) or (dy <= radius * 0.5 - abs(dx) * 0.866 and dy >= 0)
                    dist = abs(dx) + abs(dy) * 0.7
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 17: Crescent Moon
        def crescent_moon():
            positions = []
            outer_radius = min(cols, rows) / 2.2
            inner_radius = outer_radius * 0.7
            offset_x = outer_radius * 0.5
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    outer_dist = (dx**2 + dy**2) ** 0.5
                    inner_dist = ((dx + offset_x)**2 + dy**2) ** 0.5
                    if outer_dist <= outer_radius and inner_dist > inner_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 18: Sun Burst
        def sun_burst():
            positions = []
            core_radius = min(cols, rows) / 4
            ray_length = min(cols, rows) / 2.5
            num_rays = 8
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx**2 + dy**2) ** 0.5
                    angle = math.atan2(dy, dx)
                    # Core circle
                    if dist <= core_radius:
                        positions.append(f"{x}_{y}")
                    # Rays
                    elif dist <= ray_length:
                        ray_angle = (angle + math.pi) % (2 * math.pi / num_rays)
                        if ray_angle < math.pi / num_rays * 0.5 or ray_angle > 2 * math.pi / num_rays - math.pi / num_rays * 0.5:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 19: Spiral
        def spiral():
            positions = []
            max_radius = min(cols, rows) / 2.2
            turns = 2.5
            thickness = max(1.5, min(cols, rows) / 8)
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx**2 + dy**2) ** 0.5
                    if dist < 0.5:
                        positions.append(f"{x}_{y}")
                        continue
                    angle = math.atan2(dy, dx)
                    expected_dist = (angle + math.pi) / (2 * math.pi) * max_radius / turns
                    for i in range(int(turns) + 1):
                        check_dist = expected_dist + i * max_radius / turns
                        if abs(dist - check_dist) <= thickness:
                            positions.append(f"{x}_{y}")
                            break
            return positions

        # ============ Category 4: Letter Shapes (20-29) ============

        # Pattern 20: Letter H (pixel art style)
        def letter_H():
            positions = []
            if cols <= 5 or rows <= 5:
                template = [
                    "# #",
                    "# #",
                    "###",
                    "# #",
                    "# #",
                ]
            elif cols <= 7 or rows <= 7:
                template = [
                    "##   ##",
                    "##   ##",
                    "##   ##",
                    "#######",
                    "##   ##",
                    "##   ##",
                    "##   ##",
                ]
            else:
                template = [
                    "##    ##",
                    "##    ##",
                    "##    ##",
                    "########",
                    "########",
                    "##    ##",
                    "##    ##",
                    "##    ##",
                ]
            template_rows = len(template)
            template_cols = max(len(r) for r in template)
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)
            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 21: Letter I (pixel art style)
        def letter_I():
            positions = []
            if cols <= 5 or rows <= 5:
                template = [
                    "###",
                    " # ",
                    " # ",
                    " # ",
                    "###",
                ]
            elif cols <= 7 or rows <= 7:
                template = [
                    "#####",
                    "  #  ",
                    "  #  ",
                    "  #  ",
                    "  #  ",
                    "  #  ",
                    "#####",
                ]
            else:
                template = [
                    "######",
                    "  ##  ",
                    "  ##  ",
                    "  ##  ",
                    "  ##  ",
                    "  ##  ",
                    "  ##  ",
                    "######",
                ]
            template_rows = len(template)
            template_cols = max(len(r) for r in template)
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)
            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 22: Letter L
        def letter_L():
            positions = []
            bar_width = max(2, cols // 3)
            bar_height = max(2, rows // 4)
            # Vertical bar
            for x in range(bar_width):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Horizontal bar at bottom
            for x in range(bar_width, cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 23: Letter U
        def letter_U():
            positions = []
            bar_width = max(2, cols // 4)
            bar_height = max(2, rows // 4)
            # Left vertical
            for x in range(bar_width):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Right vertical
            for x in range(cols - bar_width, cols):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Bottom connector
            for x in range(bar_width, cols - bar_width):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 24: Letter X (pixel art style)
        def letter_X():
            positions = []
            if cols <= 5 or rows <= 5:
                template = [
                    "# #",
                    " # ",
                    "# #",
                ]
            elif cols <= 7 or rows <= 7:
                template = [
                    "##   ##",
                    " ## ## ",
                    "  ###  ",
                    "   #   ",
                    "  ###  ",
                    " ## ## ",
                    "##   ##",
                ]
            else:
                template = [
                    "##    ##",
                    " ##  ## ",
                    "  ####  ",
                    "   ##   ",
                    "   ##   ",
                    "  ####  ",
                    " ##  ## ",
                    "##    ##",
                ]
            template_rows = len(template)
            template_cols = max(len(r) for r in template)
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)
            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 25: Letter Y
        def letter_Y():
            positions = []
            stem_width = max(2, cols // 3)
            stem_start = int((cols - stem_width) / 2)
            mid_y = rows // 2
            thickness = max(1.5, cols / 5)
            # Top diagonals
            for x in range(cols):
                for y in range(mid_y):
                    d1 = abs((x - center_x) - (y - mid_y) * cols / rows)
                    d2 = abs((x - center_x) + (y - mid_y) * cols / rows)
                    if d1 <= thickness or d2 <= thickness:
                        positions.append(f"{x}_{y}")
            # Bottom stem
            for x in range(stem_start, stem_start + stem_width):
                for y in range(mid_y, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 26: Letter Z (pixel art style)
        def letter_Z():
            positions = []
            if cols <= 5 or rows <= 5:
                template = [
                    "###",
                    " # ",
                    "# ",
                    "###",
                ]
            elif cols <= 7 or rows <= 7:
                template = [
                    "#######",
                    "    ## ",
                    "   ##  ",
                    "  ##   ",
                    " ##    ",
                    "##     ",
                    "#######",
                ]
            else:
                template = [
                    "########",
                    "     ## ",
                    "    ##  ",
                    "   ##   ",
                    "  ##    ",
                    " ##     ",
                    "##      ",
                    "########",
                ]
            template_rows = len(template)
            template_cols = max(len(r) for r in template)
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)
            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 27: Letter S (pixel art style, scales to grid size)
        def letter_S():
            positions = []
            # Define S templates for different grid sizes
            if cols <= 5 or rows <= 5:
                # Small S for tiny grids
                template = [
                    "#####",
                    "#    ",
                    "#####",
                    "    #",
                    "#####",
                ]
            elif cols <= 7 or rows <= 7:
                # Medium S for 6-7 sized grids
                template = [
                    " ##### ",
                    "##   # ",
                    " ###   ",
                    "   ### ",
                    " #   ##",
                    " ##### ",
                ]
            else:
                # Large S for 8+ sized grids
                template = [
                    "  #####  ",
                    " ##   ## ",
                    " ##      ",
                    "  #####  ",
                    "      ## ",
                    " ##   ## ",
                    "  #####  ",
                ]

            template_rows = len(template)
            template_cols = max(len(r) for r in template)

            # Center the S in the grid
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)

            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 28: Letter O (ring)
        def letter_O():
            positions = []
            outer_rx = cols / 2.2
            outer_ry = rows / 2.2
            inner_rx = outer_rx * 0.5
            inner_ry = outer_ry * 0.5
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / outer_rx
                    dy = (y - center_y + 0.5) / outer_ry
                    outer_dist = dx * dx + dy * dy
                    dx2 = (x - center_x + 0.5) / inner_rx
                    dy2 = (y - center_y + 0.5) / inner_ry
                    inner_dist = dx2 * dx2 + dy2 * dy2
                    if outer_dist <= 1.0 and inner_dist >= 1.0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 29: Letter C
        def letter_C():
            positions = []
            outer_rx = cols / 2.2
            outer_ry = rows / 2.2
            inner_rx = outer_rx * 0.5
            inner_ry = outer_ry * 0.5
            gap_width = cols / 3
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / outer_rx
                    dy = (y - center_y + 0.5) / outer_ry
                    outer_dist = dx * dx + dy * dy
                    dx2 = (x - center_x + 0.5) / inner_rx
                    dy2 = (y - center_y + 0.5) / inner_ry
                    inner_dist = dx2 * dx2 + dy2 * dy2
                    # C shape - open on the right
                    if outer_dist <= 1.0 and inner_dist >= 1.0 and x < cols - gap_width:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 5: Advanced Geometric (30-39) ============

        # Pattern 30: Triangle Up
        def triangle_up():
            positions = []
            for y in range(rows):
                width = int((rows - y) * cols / rows)
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 31: Triangle Down
        def triangle_down():
            positions = []
            for y in range(rows):
                width = int((y + 1) * cols / rows)
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 32: Hourglass
        def hourglass():
            positions = []
            for y in range(rows):
                # Distance from center row
                dist_from_center = abs(y - center_y)
                width = int(cols * (dist_from_center / center_y + 0.3))
                width = max(2, min(cols, width))
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 33: Bowtie (pixel art style - actual bow tie shape)
        def bowtie():
            positions = []
            if cols <= 5 or rows <= 5:
                template = [
                    "# #",
                    "###",
                    "# #",
                ]
            elif cols <= 7 or rows <= 7:
                template = [
                    "##   ##",
                    " ## ## ",
                    "  ###  ",
                    " ## ## ",
                    "##   ##",
                ]
            else:
                template = [
                    "###  ###",
                    " ### ## ",
                    "  ####  ",
                    "   ##   ",
                    "  ####  ",
                    " ##  ## ",
                    "###  ###",
                ]
            template_rows = len(template)
            template_cols = max(len(r) for r in template)
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)
            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 34: Stairs Ascending (left to right)
        def stairs_ascending():
            positions = []
            num_steps = min(cols, rows) // 2
            step_width = cols // num_steps
            step_height = rows // num_steps
            for step in range(num_steps):
                x_start = step * step_width
                y_start = rows - (step + 1) * step_height
                for x in range(x_start, min(cols, x_start + step_width + 1)):
                    for y in range(max(0, y_start), rows):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 35: Stairs Descending
        def stairs_descending():
            positions = []
            num_steps = min(cols, rows) // 2
            step_width = cols // num_steps
            step_height = rows // num_steps
            for step in range(num_steps):
                x_start = step * step_width
                y_end = (step + 1) * step_height
                for x in range(x_start, min(cols, x_start + step_width + 1)):
                    for y in range(min(rows, y_end)):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 36: Pyramid - 위아래로 더 길쭉하게 (세로 확장)
        def pyramid():
            positions = []
            # 세로로 더 길게 (rows 전체 사용, 가로는 좁게)
            levels = rows  # 전체 행 사용
            base_width = max(3, cols // 2)  # 기본 너비는 절반
            for level in range(levels):
                y = rows - 1 - level
                # 위로 갈수록 좁아지는 너비 (더 뾰족한 피라미드)
                progress = level / max(1, levels - 1)
                width = max(1, int(base_width * (1 - progress * 0.8)))
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols and 0 <= y < rows:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 37: Inverted Pyramid - 위아래로 더 길쭉하게 (세로 확장)
        def inverted_pyramid():
            positions = []
            # 세로로 더 길게 (rows 전체 사용)
            levels = rows
            base_width = max(3, cols // 2)
            for level in range(levels):
                y = level
                # 아래로 갈수록 좁아지는 너비
                progress = level / max(1, levels - 1)
                width = max(1, int(base_width * (1 - progress * 0.8)))
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 38: Zigzag Horizontal
        def zigzag_horizontal():
            positions = []
            amplitude = rows // 3
            period = cols // 3
            thickness = max(2, rows // 4)
            for x in range(cols):
                base_y = int(center_y + amplitude * math.sin(x * 2 * math.pi / period))
                for y in range(max(0, base_y - thickness), min(rows, base_y + thickness + 1)):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 39: Wave Pattern
        def wave_pattern():
            positions = []
            num_waves = 3
            wave_height = rows // (num_waves * 2)
            for x in range(cols):
                for y in range(rows):
                    wave_offset = int(wave_height * math.sin(x * 2 * math.pi / (cols / 2)))
                    if (y + wave_offset) % (rows // num_waves) < rows // num_waves // 2:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 6: Frame/Border Patterns (40-44) ============

        # Pattern 40: Frame Border
        def frame_border():
            positions = []
            border_width = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    if x < border_width or x >= cols - border_width or y < border_width or y >= rows - border_width:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 41: Double Frame
        def double_frame():
            positions = []
            outer_width = max(1, min(cols, rows) // 6)
            gap = max(1, min(cols, rows) // 6)
            inner_width = max(1, min(cols, rows) // 6)
            for x in range(cols):
                for y in range(rows):
                    # Outer frame
                    if x < outer_width or x >= cols - outer_width or y < outer_width or y >= rows - outer_width:
                        positions.append(f"{x}_{y}")
                    # Inner frame
                    inner_start = outer_width + gap
                    inner_end_x = cols - outer_width - gap
                    inner_end_y = rows - outer_width - gap
                    if inner_start <= x < inner_end_x and inner_start <= y < inner_end_y:
                        if x < inner_start + inner_width or x >= inner_end_x - inner_width or y < inner_start + inner_width or y >= inner_end_y - inner_width:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 42: Corner Triangles
        def corner_triangles():
            positions = []
            tri_size = min(cols, rows) // 3
            for x in range(cols):
                for y in range(rows):
                    # Top-left
                    if x + y < tri_size:
                        positions.append(f"{x}_{y}")
                    # Top-right
                    elif (cols - 1 - x) + y < tri_size:
                        positions.append(f"{x}_{y}")
                    # Bottom-left
                    elif x + (rows - 1 - y) < tri_size:
                        positions.append(f"{x}_{y}")
                    # Bottom-right
                    elif (cols - 1 - x) + (rows - 1 - y) < tri_size:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 43: Center Hollow (filled corners, hollow center)
        def center_hollow():
            positions = []
            hollow_size = min(cols, rows) // 3
            hollow_x_start = int((cols - hollow_size) / 2)
            hollow_y_start = int((rows - hollow_size) / 2)
            for x in range(cols):
                for y in range(rows):
                    # Not in center hollow
                    if not (hollow_x_start <= x < hollow_x_start + hollow_size and hollow_y_start <= y < hollow_y_start + hollow_size):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 44: Window Panes (4 quadrants)
        def window_panes():
            positions = []
            gap = max(1, min(cols, rows) // 6)
            mid_x = cols // 2
            mid_y = rows // 2
            for x in range(cols):
                for y in range(rows):
                    # Not in center cross
                    if not (mid_x - gap <= x < mid_x + gap or mid_y - gap <= y < mid_y + gap):
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 7: Artistic Patterns (45-49) ============

        # Pattern 45: Butterfly (pixel art style)
        def butterfly():
            positions = []
            # Define butterfly templates for different grid sizes
            if cols <= 5 or rows <= 5:
                # Small butterfly
                template = [
                    "# # #",
                    "## ##",
                    " # # ",
                    "## ##",
                    "# # #",
                ]
            elif cols <= 7 or rows <= 7:
                # Medium butterfly
                template = [
                    "#  #  #",
                    "## # ##",
                    "### ###",
                    "  ###  ",
                    "### ###",
                    "## # ##",
                    "#  #  #",
                ]
            else:
                # Large butterfly for 8+ sized grids
                template = [
                    "#      #",
                    "##    ##",
                    "### ####",
                    "########",
                    "   ##   ",
                    "########",
                    "### ####",
                    "##    ##",
                ]

            template_rows = len(template)
            template_cols = max(len(r) for r in template)

            # Center the butterfly in the grid
            y_offset = max(0, (rows - template_rows) // 2)
            x_offset = max(0, (cols - template_cols) // 2)

            for ty, row_str in enumerate(template):
                y = ty + y_offset
                if y >= rows:
                    continue
                for tx, char in enumerate(row_str):
                    x = tx + x_offset
                    if x >= cols:
                        continue
                    if char == '#':
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 46: Flower Pattern (petals around center)
        def flower_pattern():
            positions = []
            petal_radius = min(cols, rows) / 3
            center_radius = min(cols, rows) / 6
            num_petals = 6
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx ** 2 + dy ** 2) ** 0.5
                    # Center
                    if dist <= center_radius:
                        positions.append(f"{x}_{y}")
                    else:
                        # Petals
                        angle = math.atan2(dy, dx)
                        for i in range(num_petals):
                            petal_angle = i * 2 * math.pi / num_petals
                            petal_cx = center_x + math.cos(petal_angle) * petal_radius * 0.7
                            petal_cy = center_y + math.sin(petal_angle) * petal_radius * 0.7
                            petal_dist = ((x - petal_cx) ** 2 + (y - petal_cy) ** 2) ** 0.5
                            if petal_dist <= petal_radius * 0.5:
                                positions.append(f"{x}_{y}")
                                break
            return positions

        # Pattern 47: Scattered Islands
        def scattered_islands():
            positions = []
            # Create 4-6 island clusters with random positions for variety
            num_islands = min(6, max(4, (cols * rows) // 30))
            islands = []
            for _ in range(num_islands):
                ix = random.randint(1, cols - 2)
                iy = random.randint(1, rows - 2)
                ir = random.uniform(1.5, min(cols, rows) / 4)
                islands.append((ix, iy, ir))
            for x in range(cols):
                for y in range(rows):
                    for ix, iy, ir in islands:
                        if ((x - ix) ** 2 + (y - iy) ** 2) ** 0.5 <= ir:
                            positions.append(f"{x}_{y}")
                            break
            return positions

        # Pattern 48: Diagonal Stripes
        def diagonal_stripes():
            positions = []
            stripe_width = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    if ((x + y) // stripe_width) % 2 == 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 49: Honeycomb
        def honeycomb():
            positions = []
            cell_size = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    # Offset every other row
                    offset = (cell_size // 2) if (y // cell_size) % 2 == 1 else 0
                    cell_x = (x + offset) // cell_size
                    cell_y = y // cell_size
                    # Create hexagonal-ish cells
                    local_x = (x + offset) % cell_size
                    local_y = y % cell_size
                    # Fill cells but leave small gaps
                    if local_x > 0 and local_x < cell_size - 1 and local_y > 0 and local_y < cell_size - 1:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 8: Bridge/Island Patterns (50-55) ============
        # Inspired by Tile Explorer game's island+bridge level designs

        # Helper function for bridge patterns - calculate point to line distance
        def point_to_line_distance(px, py, x1, y1, x2, y2):
            """Calculate perpendicular distance from point (px,py) to line segment (x1,y1)-(x2,y2)."""
            line_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
            if line_len_sq == 0:
                return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
            t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))
            proj_x = x1 + t * (x2 - x1)
            proj_y = y1 + t * (y2 - y1)
            return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5

        # Pattern 50: Two Islands with Bridge (horizontal)
        def bridge_horizontal():
            """Two circular islands connected by a horizontal bridge."""
            positions = []
            island_radius = min(cols, rows) / 3.5
            bridge_width = max(2, rows // 5)

            # Left island center
            left_cx = cols / 4
            left_cy = rows / 2

            # Right island center
            right_cx = cols * 3 / 4
            right_cy = rows / 2

            for x in range(cols):
                for y in range(rows):
                    # Left island
                    left_dist = ((x - left_cx) ** 2 + (y - left_cy) ** 2) ** 0.5
                    # Right island
                    right_dist = ((x - right_cx) ** 2 + (y - right_cy) ** 2) ** 0.5
                    # Bridge (horizontal connection in center)
                    in_bridge = (left_cx <= x <= right_cx and
                                 rows / 2 - bridge_width / 2 <= y <= rows / 2 + bridge_width / 2)

                    if left_dist <= island_radius or right_dist <= island_radius or in_bridge:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 51: Two Islands with Bridge (vertical)
        def bridge_vertical():
            """Two circular islands connected by a vertical bridge."""
            positions = []
            island_radius = min(cols, rows) / 3.5
            bridge_width = max(2, cols // 5)

            # Top island center
            top_cx = cols / 2
            top_cy = rows / 4

            # Bottom island center
            bottom_cx = cols / 2
            bottom_cy = rows * 3 / 4

            for x in range(cols):
                for y in range(rows):
                    # Top island
                    top_dist = ((x - top_cx) ** 2 + (y - top_cy) ** 2) ** 0.5
                    # Bottom island
                    bottom_dist = ((x - bottom_cx) ** 2 + (y - bottom_cy) ** 2) ** 0.5
                    # Bridge (vertical connection in center)
                    in_bridge = (top_cy <= y <= bottom_cy and
                                 cols / 2 - bridge_width / 2 <= x <= cols / 2 + bridge_width / 2)

                    if top_dist <= island_radius or bottom_dist <= island_radius or in_bridge:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 52: Three Islands Triangle (with bridges)
        def three_islands_triangle():
            """Three islands arranged in a triangle with connecting bridges."""
            positions = []
            island_radius = min(cols, rows) / 4.5
            bridge_width = max(2, min(cols, rows) // 6)

            # Island centers (triangle arrangement)
            top_cx, top_cy = cols / 2, rows / 4
            left_cx, left_cy = cols / 4, rows * 3 / 4
            right_cx, right_cy = cols * 3 / 4, rows * 3 / 4

            islands = [(top_cx, top_cy), (left_cx, left_cy), (right_cx, right_cy)]

            for x in range(cols):
                for y in range(rows):
                    in_pattern = False

                    # Check islands
                    for cx, cy in islands:
                        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                        if dist <= island_radius:
                            in_pattern = True
                            break

                    # Check bridges (connecting all islands)
                    if not in_pattern:
                        # Top to left bridge
                        t_l_dist = point_to_line_distance(x, y, top_cx, top_cy, left_cx, left_cy)
                        if t_l_dist <= bridge_width / 2 and min(top_cx, left_cx) - 1 <= x <= max(top_cx, left_cx) + 1:
                            if min(top_cy, left_cy) - 1 <= y <= max(top_cy, left_cy) + 1:
                                in_pattern = True

                        # Top to right bridge
                        t_r_dist = point_to_line_distance(x, y, top_cx, top_cy, right_cx, right_cy)
                        if t_r_dist <= bridge_width / 2 and min(top_cx, right_cx) - 1 <= x <= max(top_cx, right_cx) + 1:
                            if min(top_cy, right_cy) - 1 <= y <= max(top_cy, right_cy) + 1:
                                in_pattern = True

                        # Left to right bridge
                        l_r_dist = point_to_line_distance(x, y, left_cx, left_cy, right_cx, right_cy)
                        if l_r_dist <= bridge_width / 2 and min(left_cx, right_cx) - 1 <= x <= max(left_cx, right_cx) + 1:
                            if min(left_cy, right_cy) - 1 <= y <= max(left_cy, right_cy) + 1:
                                in_pattern = True

                    if in_pattern:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 53: Four Islands Grid (with bridges)
        def four_islands_grid():
            """Four islands in a 2x2 grid with connecting bridges."""
            positions = []
            island_radius = min(cols, rows) / 4.5
            bridge_width = max(2, min(cols, rows) // 7)

            # Island centers (2x2 grid)
            islands = [
                (cols / 4, rows / 4),       # Top-left
                (cols * 3 / 4, rows / 4),   # Top-right
                (cols / 4, rows * 3 / 4),   # Bottom-left
                (cols * 3 / 4, rows * 3 / 4)  # Bottom-right
            ]

            for x in range(cols):
                for y in range(rows):
                    in_pattern = False

                    # Check islands
                    for cx, cy in islands:
                        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                        if dist <= island_radius:
                            in_pattern = True
                            break

                    # Check horizontal bridges
                    if not in_pattern:
                        # Top horizontal bridge
                        if cols / 4 <= x <= cols * 3 / 4 and abs(y - rows / 4) <= bridge_width / 2:
                            in_pattern = True
                        # Bottom horizontal bridge
                        if cols / 4 <= x <= cols * 3 / 4 and abs(y - rows * 3 / 4) <= bridge_width / 2:
                            in_pattern = True
                        # Left vertical bridge
                        if rows / 4 <= y <= rows * 3 / 4 and abs(x - cols / 4) <= bridge_width / 2:
                            in_pattern = True
                        # Right vertical bridge
                        if rows / 4 <= y <= rows * 3 / 4 and abs(x - cols * 3 / 4) <= bridge_width / 2:
                            in_pattern = True

                    if in_pattern:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 54: Corner with Center Circle - 4꼭짓점 + 중앙 원형
        def corner_with_center_circle():
            """4 corners with a circular spawn in the center."""
            positions = []
            corner_size = max(2, min(cols, rows) // 3)
            center_radius = max(1.5, min(cols, rows) / 5)

            for x in range(cols):
                for y in range(rows):
                    # 4 꼭짓점 영역
                    is_corner = (
                        (x < corner_size and y < corner_size) or
                        (x < corner_size and y >= rows - corner_size) or
                        (x >= cols - corner_size and y < corner_size) or
                        (x >= cols - corner_size and y >= rows - corner_size)
                    )
                    # 중앙 원형 영역
                    dist_from_center = ((x - center_x + 0.5) ** 2 + (y - center_y + 0.5) ** 2) ** 0.5
                    is_center_circle = dist_from_center <= center_radius

                    if is_corner or is_center_circle:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 55: Central Hub with Spokes
        def hub_and_spokes():
            """Central circular hub with radiating spoke connections."""
            positions = []
            hub_radius = min(cols, rows) / 4
            spoke_width = max(2, min(cols, rows) // 6)
            spoke_count = 4  # Four spokes

            for x in range(cols):
                for y in range(rows):
                    in_pattern = False

                    # Central hub
                    dist_from_center = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                    if dist_from_center <= hub_radius:
                        in_pattern = True

                    # Spokes (extending to edges)
                    if not in_pattern:
                        for i in range(spoke_count):
                            angle = i * math.pi / 2  # 0, 90, 180, 270 degrees
                            # Direction vector
                            dx_dir = math.cos(angle)
                            dy_dir = math.sin(angle)

                            # Project point onto spoke direction
                            px = x - center_x
                            py = y - center_y

                            # Distance along spoke direction
                            proj = px * dx_dir + py * dy_dir

                            # Distance perpendicular to spoke
                            perp_dist = abs(px * (-dy_dir) + py * dx_dir)

                            # In spoke if: beyond hub, within spoke width, and along spoke direction
                            if proj > hub_radius * 0.8 and perp_dist <= spoke_width / 2:
                                in_pattern = True
                                break

                    if in_pattern:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 9: GBoost Human-Designed Patterns (56-63) ============
        # These patterns are derived from analysis of 221 human-designed levels
        # from the GBoost production server (level_1 ~ level_221)

        # Pattern 56: GBoost Corner Blocks (inspired by level_200)
        # Four symmetric corner blocks with connecting elements
        def gboost_corner_blocks():
            """Four corner blocks with symmetric arrangement (level_200 style)."""
            positions = []
            block_size = max(2, min(cols, rows) // 4)
            margin = 1  # Edge margin

            for x in range(cols):
                for y in range(rows):
                    # Top-left corner block
                    in_tl = (margin <= x < margin + block_size and
                             margin <= y < margin + block_size)
                    # Top-right corner block
                    in_tr = (cols - margin - block_size <= x < cols - margin and
                             margin <= y < margin + block_size)
                    # Bottom-left corner block
                    in_bl = (margin <= x < margin + block_size and
                             rows - margin - block_size <= y < rows - margin)
                    # Bottom-right corner block
                    in_br = (cols - margin - block_size <= x < cols - margin and
                             rows - margin - block_size <= y < rows - margin)

                    if in_tl or in_tr or in_bl or in_br:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 57: Corner with Center Square - 4꼭짓점 + 중앙 네모
        def corner_with_center_square():
            """4 corners with a square spawn in the center."""
            positions = []
            corner_size = max(2, min(cols, rows) // 3)
            center_size = max(2, min(cols, rows) // 4)
            center_half = center_size // 2

            for x in range(cols):
                for y in range(rows):
                    # 4 꼭짓점 영역
                    is_corner = (
                        (x < corner_size and y < corner_size) or
                        (x < corner_size and y >= rows - corner_size) or
                        (x >= cols - corner_size and y < corner_size) or
                        (x >= cols - corner_size and y >= rows - corner_size)
                    )
                    # 중앙 네모 영역
                    cx, cy = cols // 2, rows // 2
                    is_center_square = (
                        cx - center_half <= x < cx + center_half and
                        cy - center_half <= y < cy + center_half
                    )

                    if is_corner or is_center_square:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 58: GBoost Diagonal Staircase (inspired by level_150)
        # Diagonal chain-like staircase pattern
        def gboost_diagonal_staircase():
            """Diagonal staircase pattern (level_150 chain style)."""
            positions = []
            step_size = max(2, min(cols, rows) // 5)

            for x in range(cols):
                for y in range(rows):
                    # Diagonal index (which step we're on)
                    step_idx = (x + y) // step_size
                    # Position within step
                    pos_in_step = (x + y) % step_size

                    # Include tiles that form the staircase pattern
                    if pos_in_step < step_size * 0.7:
                        # Add some depth to the steps
                        step_depth = abs(x - y) % step_size
                        if step_depth < step_size * 0.6:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 59: GBoost Symmetric Wings (inspired by level_100 diagonal mirror)
        # Diagonally mirrored wing pattern
        def gboost_symmetric_wings():
            """Diagonal mirrored wing pattern (level_100 style)."""
            positions = []
            wing_width = max(3, cols // 3)

            for x in range(cols):
                for y in range(rows):
                    # Distance from main diagonal
                    diag_dist = abs(x - y)
                    # Distance from anti-diagonal
                    anti_diag_dist = abs(x + y - (cols - 1))

                    # Create wings along both diagonals
                    if diag_dist <= wing_width or anti_diag_dist <= wing_width:
                        # Add some tapering toward edges
                        edge_dist = min(x, y, cols - 1 - x, rows - 1 - y)
                        if edge_dist >= 0 or diag_dist <= wing_width // 2:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 60: GBoost Scattered Clusters (common in mid-late levels)
        # Multiple small clusters distributed across the grid
        def gboost_scattered_clusters():
            """Multiple small clusters distributed across grid."""
            positions = []
            cluster_count = random.randint(4, 7)
            cluster_radius = min(cols, rows) / 5

            # Generate cluster centers with spacing
            centers = []
            for _ in range(cluster_count * 3):  # Try more times for better distribution
                cx = random.uniform(cluster_radius, cols - cluster_radius)
                cy = random.uniform(cluster_radius, rows - cluster_radius)

                # Check distance from existing centers
                too_close = False
                for ecx, ecy in centers:
                    if ((cx - ecx) ** 2 + (cy - ecy) ** 2) ** 0.5 < cluster_radius * 1.5:
                        too_close = True
                        break

                if not too_close and len(centers) < cluster_count:
                    centers.append((cx, cy))

            for x in range(cols):
                for y in range(rows):
                    for cx, cy in centers:
                        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                        if dist <= cluster_radius * random.uniform(0.6, 1.0):
                            positions.append(f"{x}_{y}")
                            break

            return positions

        # Pattern 61: GBoost Cross Bridge (inspired by level_10)
        # Alternating tiles forming a cross-bridge pattern
        def gboost_cross_bridge():
            """Alternating cross-bridge pattern (level_10 style)."""
            positions = []

            # Horizontal bridge
            h_band_start = int(rows * 0.35)
            h_band_end = int(rows * 0.65)

            # Vertical bridge
            v_band_start = int(cols * 0.35)
            v_band_end = int(cols * 0.65)

            for x in range(cols):
                for y in range(rows):
                    in_h_band = h_band_start <= y < h_band_end
                    in_v_band = v_band_start <= x < v_band_end

                    # Checkerboard-like pattern with offset
                    checker = (x + y) % 3 != 0

                    if (in_h_band or in_v_band) and checker:
                        positions.append(f"{x}_{y}")

            return positions

        # Pattern 62: GBoost Triple Bar (horizontal bars pattern)
        # Three horizontal bars with gaps
        def gboost_triple_bar():
            """Three horizontal bars pattern."""
            positions = []
            bar_height = max(2, rows // 5)
            gap = max(1, rows // 7)

            bar_positions = [
                gap,
                rows // 2 - bar_height // 2,
                rows - gap - bar_height
            ]

            for x in range(cols):
                for y in range(rows):
                    for bar_y in bar_positions:
                        if bar_y <= y < bar_y + bar_height:
                            # Slight taper at edges
                            edge_margin = max(0, 2 - min(x, cols - 1 - x))
                            if edge_margin == 0:
                                positions.append(f"{x}_{y}")
                            break
            return positions

        # Pattern 63: GBoost Frame with Center (common frame + center dot)
        def gboost_frame_center():
            """Frame border with center cluster."""
            positions = []
            border_width = max(2, min(cols, rows) // 5)
            center_radius = min(cols, rows) / 4

            for x in range(cols):
                for y in range(rows):
                    # Border frame
                    in_frame = (x < border_width or x >= cols - border_width or
                                y < border_width or y >= rows - border_width)

                    # Center cluster
                    dist_from_center = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                    in_center = dist_from_center <= center_radius

                    if in_frame or in_center:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Build Pattern List ============

        all_patterns = [
            # Category 1: Basic Shapes (0-9)
            ("filled_rectangle", filled_rectangle),       # 0
            ("diamond_shape", diamond_shape),             # 1
            ("oval_shape", oval_shape),                   # 2
            ("cross_shape", cross_shape),                 # 3
            ("donut_shape", donut_shape),                 # 4
            ("concentric_diamond", concentric_diamond),   # 5
            ("corner_anchored", corner_anchored),         # 6
            ("hexagonal", hexagonal),                     # 7
            ("heart_shape", heart_shape),                 # 8
            ("t_shape", t_shape),                         # 9
            # Category 2: Arrow/Direction (10-14)
            ("arrow_up", arrow_up),                       # 10
            ("arrow_down", arrow_down),                   # 11
            ("arrow_left", arrow_left),                   # 12
            ("arrow_right", arrow_right),                 # 13
            ("chevron_pattern", chevron_pattern),         # 14
            # Category 3: Star/Celestial (15-19)
            ("star_five_point", star_five_point),         # 15
            ("star_six_point", star_six_point),           # 16
            ("crescent_moon", crescent_moon),             # 17
            ("sun_burst", sun_burst),                     # 18
            ("spiral", spiral),                           # 19
            # Category 4: Letter Shapes (20-29)
            ("letter_H", letter_H),                       # 20
            ("letter_I", letter_I),                       # 21
            ("letter_L", letter_L),                       # 22
            ("letter_U", letter_U),                       # 23
            ("letter_X", letter_X),                       # 24
            ("letter_Y", letter_Y),                       # 25
            ("letter_Z", letter_Z),                       # 26
            ("letter_S", letter_S),                       # 27
            ("letter_O", letter_O),                       # 28
            ("letter_C", letter_C),                       # 29
            # Category 5: Advanced Geometric (30-39)
            ("triangle_up", triangle_up),                 # 30
            ("triangle_down", triangle_down),             # 31
            ("hourglass", hourglass),                     # 32
            ("bowtie", bowtie),                           # 33
            ("stairs_ascending", stairs_ascending),       # 34
            ("stairs_descending", stairs_descending),     # 35
            ("pyramid", pyramid),                         # 36
            ("inverted_pyramid", inverted_pyramid),       # 37
            ("zigzag_horizontal", zigzag_horizontal),     # 38
            ("wave_pattern", wave_pattern),               # 39
            # Category 6: Frame/Border (40-44)
            ("frame_border", frame_border),               # 40
            ("double_frame", double_frame),               # 41
            ("corner_triangles", corner_triangles),       # 42
            ("center_hollow", center_hollow),             # 43
            ("window_panes", window_panes),               # 44
            # Category 7: Artistic (45-49)
            ("butterfly", butterfly),                     # 45
            ("flower_pattern", flower_pattern),           # 46
            ("scattered_islands", scattered_islands),     # 47
            ("diagonal_stripes", diagonal_stripes),       # 48
            ("honeycomb", honeycomb),                     # 49
            # Category 8: Bridge/Island Patterns (50-55) - Tile Explorer inspired
            ("bridge_horizontal", bridge_horizontal),     # 50
            ("bridge_vertical", bridge_vertical),         # 51
            ("three_islands_triangle", three_islands_triangle),  # 52
            ("four_islands_grid", four_islands_grid),     # 53
            ("corner_with_center_circle", corner_with_center_circle),  # 54
            ("hub_and_spokes", hub_and_spokes),           # 55
            # Category 9: GBoost Human-Designed Patterns (56-63)
            # Derived from analysis of 221 human-designed production levels
            ("gboost_corner_blocks", gboost_corner_blocks),     # 56
            ("corner_with_center_square", corner_with_center_square),  # 57
            ("gboost_diagonal_staircase", gboost_diagonal_staircase),  # 58
            ("gboost_symmetric_wings", gboost_symmetric_wings), # 59
            ("gboost_scattered_clusters", gboost_scattered_clusters),  # 60
            ("gboost_cross_bridge", gboost_cross_bridge),       # 61
            ("gboost_triple_bar", gboost_triple_bar),           # 62
            ("gboost_frame_center", gboost_frame_center),       # 63
        ]

        TOTAL_PATTERNS = 64

        # [커스텀 fallthrough 결정성 fix] 커스텀 인덱스(64+)인데 요청 크기에 맞는 변형이 없어
        # (_get_custom_pattern None) 여기 도달하면, 아래 else(auto-select)가 매 호출 random 으로
        # 다른 모양을 골라 → 패턴 목록 프리뷰가 저장/리로드마다 깜빡이고(다른 커스텀이 랜덤 변경돼 보임)
        # 레벨 생성도 비결정적이 됨. → built-in 패턴으로 결정적 매핑(index % 64). 같은 인덱스는 항상 같은 모양.
        # (신규 커스텀은 5·6·7 필수 입력이라 정상적으론 여기 거의 안 옴 — 기존 불완전 변형 커스텀 방어용.)
        if pattern_index is not None and pattern_index >= TOTAL_PATTERNS:
            pattern_index = pattern_index % TOTAL_PATTERNS

        # If pattern_index is specified, use that specific pattern
        if pattern_index is not None and 0 <= pattern_index < TOTAL_PATTERNS:
            # PRIORITY 1: Use pixel-art template if available (more accurate shapes)
            if pattern_index in PATTERN_TEMPLATES:
                template_positions = get_pattern_positions(pattern_index, cols, rows)
                if template_positions:
                    pattern_name = get_pattern_name(pattern_index)
                    best_positions = template_positions
                    print(f"[AESTHETIC_PATTERN] Using TEMPLATE pattern_index={pattern_index}, name={pattern_name}, positions={len(best_positions)}")
                else:
                    # Template returned empty, fall back to procedural
                    pattern_name, pattern_fn = all_patterns[pattern_index]
                    best_positions = pattern_fn()
                    print(f"[AESTHETIC_PATTERN] Template empty, using PROCEDURAL pattern_index={pattern_index}, name={pattern_name}, positions={len(best_positions)}")
            else:
                # PRIORITY 2: Fall back to procedural function
                pattern_name, pattern_fn = all_patterns[pattern_index]
                best_positions = pattern_fn()
                print(f"[AESTHETIC_PATTERN] Using PROCEDURAL pattern_index={pattern_index}, name={pattern_name}, positions={len(best_positions)}")

            if not best_positions:
                # Fallback to filled rectangle if chosen pattern returns nothing
                best_positions = filled_rectangle()
        else:
            # Auto-select: Score all patterns and pick best match for target_count
            pattern_results = []
            for pattern_name, pattern_fn in all_patterns:
                try:
                    positions = pattern_fn()
                    if positions:
                        # Score based on how close to target count
                        score = -abs(len(positions) - target_count)
                        # Penalize if too few positions
                        if len(positions) < target_count * 0.7:
                            score -= 1000
                        # Bonus for visually interesting patterns
                        if pattern_name in ["star_five_point", "heart_shape", "butterfly", "flower_pattern"]:
                            score += 5
                        pattern_results.append((score, positions, pattern_name))
                except Exception:
                    continue

            if not pattern_results:
                return filled_rectangle()[:target_count]

            # Sort by score and pick from top candidates with randomness
            pattern_results.sort(key=lambda x: x[0], reverse=True)

            # Pick from top 5-8 candidates randomly for variety
            # Filter to only include patterns within reasonable score range
            top_score = pattern_results[0][0]
            viable_candidates = [p for p in pattern_results if p[0] >= top_score - 15]
            num_candidates = min(len(viable_candidates), random.randint(5, 8))
            top_candidates = viable_candidates[:num_candidates]

            # Weighted random selection - higher scores more likely but not guaranteed
            weights = [max(1, p[0] - top_score + 20) for p in top_candidates]
            total_weight = sum(weights)
            weights = [w / total_weight for w in weights]

            selected_idx = random.choices(range(len(top_candidates)), weights=weights, k=1)[0]
            _, best_positions, selected_pattern = top_candidates[selected_idx]

        # If we have too many positions, trim from edges (maintain symmetry)
        # CRITICAL FIX: When pattern_index is explicitly specified (e.g., special shape levels),
        # NEVER trim - preserve the exact pattern shape as defined
        # Patterns are pixel-art templates designed for visual recognition
        if len(best_positions) > target_count:
            if pattern_index is not None:
                # For specified patterns: NEVER trim - pattern shape must be preserved exactly
                # Trimming destroys carefully designed pixel-art patterns (S, letters, etc.)
                pass
            else:
                # Auto-selected pattern: trim to exact target_count
                def dist_from_center(pos: str) -> float:
                    x, y = map(int, pos.split("_"))
                    return ((x - center_x + 0.5) ** 2 + (y - center_y + 0.5) ** 2) ** 0.5
                best_positions.sort(key=dist_from_center)
                best_positions = best_positions[:target_count]

        # CRITICAL: Filter out any positions that exceed grid boundaries
        # This ensures no tiles are placed outside the valid grid area
        valid_positions = []
        for pos in best_positions:
            parts = pos.split("_")
            if len(parts) == 2:
                x, y = int(parts[0]), int(parts[1])
                if 0 <= x < cols and 0 <= y < rows:
                    valid_positions.append(pos)

        return valid_positions

    def _generate_random_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate random positions with optional symmetry."""
        if symmetry == "none":
            all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
            return random.sample(all_positions, min(target_count, len(all_positions)))

        return self._apply_symmetry(cols, rows, target_count, symmetry, "random")

    def _generate_geometric_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate geometric pattern positions with proper symmetry support."""
        # For symmetry modes, generate in base region first, then mirror
        if symmetry == "horizontal":
            # Generate in left half, mirror to right
            base_cols = (cols + 1) // 2
            base_count = (target_count + 1) // 2
            # For symmetry, don't sample - use all positions from pattern
            base_positions = self._generate_base_geometric_for_symmetry(base_cols, rows, base_count)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            # Generate in top half, mirror to bottom
            base_rows = (rows + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_geometric_for_symmetry(cols, base_rows, base_count)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            # Generate in top-left quadrant, mirror to all 4 quadrants
            base_cols = (cols + 1) // 2
            base_rows = (rows + 1) // 2
            base_count = (target_count + 3) // 4
            base_positions = self._generate_base_geometric_for_symmetry(base_cols, base_rows, base_count)
            return self._mirror_both(cols, rows, base_positions, target_count)

        else:
            # No symmetry - generate full grid patterns with sampling
            return self._generate_base_geometric(cols, rows, target_count, 0, 0)

    def _generate_base_geometric_for_symmetry(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate geometric pattern for symmetry - returns deterministic positions."""
        center_x, center_y = cols // 2, rows // 2

        # Pattern 1: Filled rectangle from center
        rect_positions = []
        rect_size = int((target_count ** 0.5) * 1.2)
        rect_half = rect_size // 2
        for x in range(max(0, center_x - rect_half), min(cols, center_x + rect_half + 1)):
            for y in range(max(0, center_y - rect_half), min(rows, center_y + rect_half + 1)):
                rect_positions.append(f"{x}_{y}")

        # Pattern 2: Diamond shape
        diamond_positions = []
        radius = int((target_count / 2) ** 0.5) + 1
        for x in range(cols):
            for y in range(rows):
                dist = abs(x - center_x) + abs(y - center_y)
                if dist <= radius:
                    diamond_positions.append(f"{x}_{y}")

        # Pattern 3: Fill all (for maximum coverage)
        all_positions = []
        for x in range(cols):
            for y in range(rows):
                all_positions.append(f"{x}_{y}")

        # Choose the best fitting pattern - return ALL positions from chosen pattern
        # No sampling to preserve symmetry!
        all_patterns = [rect_positions, diamond_positions, all_positions]

        # Find pattern closest to target count
        chosen = min(all_patterns, key=lambda p: abs(len(p) - target_count))

        # If chosen pattern is too big and we need fewer positions,
        # use a deterministic subset (from center outward)
        if len(chosen) > target_count * 1.5:
            # Sort by distance from center and take closest positions
            def dist_from_center(pos: str) -> float:
                x, y = map(int, pos.split("_"))
                return abs(x - center_x) + abs(y - center_y)
            chosen = sorted(chosen, key=dist_from_center)[:target_count]

        return chosen

    def _generate_base_geometric(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate geometric pattern in a base region with diverse shapes."""
        # Random offset to avoid always-centered shapes
        offset_range_x = max(1, cols // 4)
        offset_range_y = max(1, rows // 4)
        rand_offset_x = random.randint(-offset_range_x, offset_range_x)
        rand_offset_y = random.randint(-offset_range_y, offset_range_y)
        center_x = cols // 2 + rand_offset_x
        center_y = rows // 2 + rand_offset_y

        # Clamp center to valid range
        center_x = max(1, min(cols - 2, center_x))
        center_y = max(1, min(rows - 2, center_y))

        all_patterns = []

        # Pattern 1: Filled rectangle (traditional)
        rect_positions = []
        rect_size = int((target_count ** 0.5) * 1.2)
        rect_half = rect_size // 2
        for x in range(max(0, center_x - rect_half), min(cols, center_x + rect_half + 1)):
            for y in range(max(0, center_y - rect_half), min(rows, center_y + rect_half + 1)):
                rect_positions.append(f"{x + offset_x}_{y + offset_y}")
        if rect_positions:
            all_patterns.append(rect_positions)

        # Pattern 2: Diamond shape
        diamond_positions = []
        radius = int((target_count / 2) ** 0.5) + 1
        for x in range(cols):
            for y in range(rows):
                dist = abs(x - center_x) + abs(y - center_y)
                if dist <= radius:
                    diamond_positions.append(f"{x + offset_x}_{y + offset_y}")
        if diamond_positions:
            all_patterns.append(diamond_positions)

        # Pattern 3: L-shape (multiple rotations)
        l_rotation = random.randint(0, 3)
        l_positions = self._generate_l_shape(cols, rows, target_count, l_rotation, offset_x, offset_y)
        if l_positions:
            all_patterns.append(l_positions)

        # Pattern 4: T-shape (multiple rotations)
        t_rotation = random.randint(0, 3)
        t_positions = self._generate_t_shape(cols, rows, target_count, t_rotation, offset_x, offset_y)
        if t_positions:
            all_patterns.append(t_positions)

        # Pattern 5: Cross/Plus shape
        cross_positions = self._generate_cross_shape(cols, rows, target_count, center_x, center_y, offset_x, offset_y)
        if cross_positions:
            all_patterns.append(cross_positions)

        # Pattern 6: Donut/Ring shape
        donut_positions = self._generate_donut_shape(cols, rows, target_count, center_x, center_y, offset_x, offset_y)
        if donut_positions:
            all_patterns.append(donut_positions)

        # Pattern 7: Zigzag pattern
        zigzag_positions = self._generate_zigzag_shape(cols, rows, target_count, offset_x, offset_y)
        if zigzag_positions:
            all_patterns.append(zigzag_positions)

        # Pattern 8: Diagonal stripe
        diagonal_positions = self._generate_diagonal_shape(cols, rows, target_count, offset_x, offset_y)
        if diagonal_positions:
            all_patterns.append(diagonal_positions)

        # Pattern 9: Corner cluster (L positioned at corner)
        corner_cluster = self._generate_corner_cluster(cols, rows, target_count, offset_x, offset_y)
        if corner_cluster:
            all_patterns.append(corner_cluster)

        # Pattern 10: Scattered clusters
        scattered_positions = self._generate_scattered_clusters(cols, rows, target_count, offset_x, offset_y)
        if scattered_positions:
            all_patterns.append(scattered_positions)

        # Pattern 11: Horizontal bar
        h_bar_positions = self._generate_horizontal_bar(cols, rows, target_count, center_y, offset_x, offset_y)
        if h_bar_positions:
            all_patterns.append(h_bar_positions)

        # Pattern 12: Vertical bar
        v_bar_positions = self._generate_vertical_bar(cols, rows, target_count, center_x, offset_x, offset_y)
        if v_bar_positions:
            all_patterns.append(v_bar_positions)

        # Randomly select from all valid patterns (not just closest to target)
        valid_patterns = [p for p in all_patterns if len(p) >= target_count * 0.7]

        if valid_patterns:
            # Randomly choose a pattern for variety
            chosen = random.choice(valid_patterns)
            selected = random.sample(chosen, min(target_count, len(chosen)))
        else:
            # Fallback: use all positions and sample
            all_positions = [f"{x + offset_x}_{y + offset_y}" for x in range(cols) for y in range(rows)]
            selected = random.sample(all_positions, min(target_count, len(all_positions)))

        # Apply random position perturbation for additional diversity
        # This shifts the entire pattern by a random offset
        shift_x = random.randint(-2, 2)
        shift_y = random.randint(-2, 2)
        shifted = []
        for pos in selected:
            x, y = map(int, pos.split("_"))
            new_x = max(0, min(cols - 1, x + shift_x))
            new_y = max(0, min(rows - 1, y + shift_y))
            shifted.append(f"{new_x}_{new_y}")

        # Remove duplicates that may have been created by shifting
        shifted = list(set(shifted))

        # If we lost too many tiles due to deduplication, add random positions
        if len(shifted) < target_count:
            all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
            available = [p for p in all_positions if p not in shifted]
            if available:
                extra = random.sample(available, min(target_count - len(shifted), len(available)))
                shifted.extend(extra)

        return shifted[:target_count]

    def _generate_l_shape(
        self, cols: int, rows: int, target_count: int, rotation: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate L-shaped pattern with rotation."""
        positions = []
        size = int((target_count / 2) ** 0.5) + 2
        thickness = max(2, size // 2)

        # Base L shape (rotation 0: vertical bar on left, horizontal bar on bottom)
        for x in range(cols):
            for y in range(rows):
                in_vertical = (x < thickness and y < size)
                in_horizontal = (y >= size - thickness and x < size)

                # Apply rotation
                if rotation == 0:
                    if in_vertical or in_horizontal:
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 1:  # 90 degrees
                    if (y < thickness and x < size) or (x >= size - thickness and y < size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 2:  # 180 degrees
                    if (x >= cols - thickness and y >= rows - size) or (y < thickness and x >= cols - size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 3:  # 270 degrees
                    if (y >= rows - thickness and x >= cols - size) or (x < thickness and y >= rows - size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_t_shape(
        self, cols: int, rows: int, target_count: int, rotation: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate T-shaped pattern with rotation."""
        positions = []
        center_x, center_y = cols // 2, rows // 2
        arm_length = int((target_count / 3) ** 0.5) + 1
        thickness = max(2, arm_length // 2)

        for x in range(cols):
            for y in range(rows):
                # T shape based on rotation
                if rotation == 0:  # T pointing down
                    in_horizontal = (abs(y - center_y) < thickness and x < cols)
                    in_vertical = (abs(x - center_x) < thickness and y >= center_y)
                elif rotation == 1:  # T pointing left
                    in_vertical = (abs(x - center_x) < thickness and y < rows)
                    in_horizontal = (abs(y - center_y) < thickness and x <= center_x)
                elif rotation == 2:  # T pointing up
                    in_horizontal = (abs(y - center_y) < thickness and x < cols)
                    in_vertical = (abs(x - center_x) < thickness and y <= center_y)
                else:  # T pointing right
                    in_vertical = (abs(x - center_x) < thickness and y < rows)
                    in_horizontal = (abs(y - center_y) < thickness and x >= center_x)

                if in_horizontal or in_vertical:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_cross_shape(
        self, cols: int, rows: int, target_count: int, center_x: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate cross/plus shaped pattern."""
        positions = []
        arm_length = int((target_count / 4) ** 0.5) + 1
        thickness = max(1, arm_length // 2)

        for x in range(cols):
            for y in range(rows):
                # Horizontal arm
                in_horizontal = (abs(y - center_y) < thickness and abs(x - center_x) <= arm_length)
                # Vertical arm
                in_vertical = (abs(x - center_x) < thickness and abs(y - center_y) <= arm_length)

                if in_horizontal or in_vertical:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_donut_shape(
        self, cols: int, rows: int, target_count: int, center_x: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate donut/ring shaped pattern with hollow center."""
        positions = []
        outer_radius = int((target_count / 2.5) ** 0.5) + 2
        inner_radius = max(1, outer_radius // 2)

        for x in range(cols):
            for y in range(rows):
                dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                if inner_radius <= dist <= outer_radius:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_zigzag_shape(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate zigzag pattern."""
        positions = []
        amplitude = max(1, rows // 4)
        thickness = max(2, int((target_count / rows) ** 0.5))

        for x in range(cols):
            # Zigzag center line
            zigzag_y = rows // 2 + int(amplitude * (1 if (x // 2) % 2 == 0 else -1))
            for y in range(rows):
                if abs(y - zigzag_y) < thickness:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_diagonal_shape(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate diagonal stripe pattern."""
        positions = []
        thickness = max(2, int((target_count / max(cols, rows)) ** 0.5) + 1)
        direction = random.choice([1, -1])  # 1 = top-left to bottom-right, -1 = top-right to bottom-left

        for x in range(cols):
            for y in range(rows):
                # Diagonal line: y = x (or y = -x) with some offset
                if direction == 1:
                    diag_dist = abs(y - x)
                else:
                    diag_dist = abs(y - (cols - 1 - x))

                if diag_dist < thickness:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_corner_cluster(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate cluster positioned at a random corner."""
        positions = []
        corner = random.randint(0, 3)
        cluster_size = int((target_count ** 0.5)) + 1

        # Determine corner position
        if corner == 0:  # Top-left
            start_x, start_y = 0, 0
        elif corner == 1:  # Top-right
            start_x, start_y = max(0, cols - cluster_size), 0
        elif corner == 2:  # Bottom-left
            start_x, start_y = 0, max(0, rows - cluster_size)
        else:  # Bottom-right
            start_x, start_y = max(0, cols - cluster_size), max(0, rows - cluster_size)

        for x in range(start_x, min(cols, start_x + cluster_size)):
            for y in range(start_y, min(rows, start_y + cluster_size)):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_scattered_clusters(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate multiple small scattered clusters."""
        positions = set()
        num_clusters = random.randint(3, 5)
        tiles_per_cluster = target_count // num_clusters
        cluster_radius = max(1, int((tiles_per_cluster / 3.14) ** 0.5))

        for _ in range(num_clusters):
            # Random cluster center
            cx = random.randint(cluster_radius, cols - cluster_radius - 1)
            cy = random.randint(cluster_radius, rows - cluster_radius - 1)

            for x in range(cols):
                for y in range(rows):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if dist <= cluster_radius:
                        positions.add(f"{x + offset_x}_{y + offset_y}")

        return list(positions)

    def _generate_horizontal_bar(
        self, cols: int, rows: int, target_count: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate horizontal bar pattern."""
        positions = []
        bar_height = max(2, target_count // cols + 1)

        for x in range(cols):
            for y in range(max(0, center_y - bar_height // 2), min(rows, center_y + bar_height // 2 + 1)):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_vertical_bar(
        self, cols: int, rows: int, target_count: int, center_x: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate vertical bar pattern."""
        positions = []
        bar_width = max(2, target_count // rows + 1)

        for x in range(max(0, center_x - bar_width // 2), min(cols, center_x + bar_width // 2 + 1)):
            for y in range(rows):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _mirror_horizontal(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions horizontally (left to right).

        Note: Returns all mirrored positions to preserve symmetry.
        The target_count is used only to limit base position generation.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            result.add(f"{x}_{y}")
            mirror_x = cols - 1 - x
            if 0 <= mirror_x < cols:
                result.add(f"{mirror_x}_{y}")
        # Return all positions to preserve symmetry - don't slice!
        return list(result)

    def _mirror_vertical(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions vertically (top to bottom).

        Note: Returns all mirrored positions to preserve symmetry.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            result.add(f"{x}_{y}")
            mirror_y = rows - 1 - y
            if 0 <= mirror_y < rows:
                result.add(f"{x}_{mirror_y}")
        return list(result)

    def _mirror_both(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions in all 4 directions.

        Note: Returns all mirrored positions to preserve symmetry.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            mirror_x = cols - 1 - x
            mirror_y = rows - 1 - y
            # Add all 4 quadrants
            result.add(f"{x}_{y}")
            if 0 <= mirror_x < cols:
                result.add(f"{mirror_x}_{y}")
            if 0 <= mirror_y < rows:
                result.add(f"{x}_{mirror_y}")
            if 0 <= mirror_x < cols and 0 <= mirror_y < rows:
                result.add(f"{mirror_x}_{mirror_y}")
        return list(result)

    def _apply_symmetry_to_positions(
        self, cols: int, rows: int, positions: List[str], symmetry: str, target_count: int
    ) -> List[str]:
        """Apply symmetry transformation to a set of positions.

        Takes existing positions and enforces the specified symmetry by:
        1. Keeping positions in one half of the grid
        2. Mirroring them to create perfect symmetry
        """
        if symmetry == "horizontal":
            # Keep only left half, then mirror to right
            center_x = cols / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                if x < center_x or (cols % 2 == 1 and x == cols // 2):
                    base_positions.append(pos)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            # Keep only top half, then mirror to bottom
            center_y = rows / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                if y < center_y or (rows % 2 == 1 and y == rows // 2):
                    base_positions.append(pos)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            # Keep only top-left quadrant, then mirror to all 4
            center_x = cols / 2.0
            center_y = rows / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                in_x = x < center_x or (cols % 2 == 1 and x == cols // 2)
                in_y = y < center_y or (rows % 2 == 1 and y == rows // 2)
                if in_x and in_y:
                    base_positions.append(pos)
            return self._mirror_both(cols, rows, base_positions, target_count)

        # No symmetry - return as-is
        return positions

    def _generate_clustered_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate clustered positions with proper symmetry support."""
        # For symmetry modes, generate in base region first, then mirror
        if symmetry == "horizontal":
            base_cols = (cols + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_clustered_for_symmetry(base_cols, rows, base_count)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            base_rows = (rows + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_clustered_for_symmetry(cols, base_rows, base_count)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            base_cols = (cols + 1) // 2
            base_rows = (rows + 1) // 2
            base_count = (target_count + 3) // 4
            base_positions = self._generate_base_clustered_for_symmetry(base_cols, base_rows, base_count)
            return self._mirror_both(cols, rows, base_positions, target_count)

        else:
            return self._generate_base_clustered(cols, rows, target_count)

    def _generate_base_clustered_for_symmetry(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate clustered positions for symmetry - deterministic, no random sampling."""
        # Use center of base region as cluster center
        center_x, center_y = cols // 2, rows // 2

        # Generate all positions within cluster radius
        cluster_radius = int((target_count / 3.14) ** 0.5) + 1
        positions = []

        for x in range(cols):
            for y in range(rows):
                dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                if dist <= cluster_radius:
                    positions.append((dist, f"{x}_{y}"))

        # Sort by distance and take closest positions (deterministic)
        positions.sort(key=lambda p: p[0])
        result = [pos for _, pos in positions]

        # If we have too many, take the closest to center
        if len(result) > target_count * 1.5:
            result = result[:target_count]

        return result

    def _generate_base_clustered(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate clustered positions in a base region (with randomness for non-symmetric)."""
        positions = set()

        # Create 1-3 cluster centers
        num_clusters = random.randint(1, min(3, max(1, target_count // 6)))
        tiles_per_cluster = target_count // max(1, num_clusters)

        # Generate cluster centers (avoid edges)
        margin = max(1, min(cols, rows) // 4)
        cluster_centers = []

        for _ in range(num_clusters):
            cx = random.randint(margin, max(margin, cols - margin - 1)) if cols > 2 * margin else cols // 2
            cy = random.randint(margin, max(margin, rows - margin - 1)) if rows > 2 * margin else rows // 2
            cluster_centers.append((cx, cy))

        # Generate positions around each cluster center
        for cx, cy in cluster_centers:
            cluster_radius = int((tiles_per_cluster / 3.14) ** 0.5) + 1
            cluster_positions = []

            for x in range(max(0, cx - cluster_radius), min(cols, cx + cluster_radius + 1)):
                for y in range(max(0, cy - cluster_radius), min(rows, cy + cluster_radius + 1)):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if dist <= cluster_radius:
                        cluster_positions.append(f"{x}_{y}")

            sample_count = min(tiles_per_cluster, len(cluster_positions))
            if sample_count > 0:
                sampled = random.sample(cluster_positions, sample_count)
                positions.update(sampled)

        # Fill remaining if needed - O(n) using random.sample instead of O(n²) loop
        if len(positions) < target_count:
            all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
            remaining = [p for p in all_positions if p not in positions]
            need_count = min(target_count - len(positions), len(remaining))
            if need_count > 0:
                positions.update(random.sample(remaining, need_count))

        return list(positions)[:target_count]

    def _apply_symmetry(
        self, cols: int, rows: int, target_count: int, symmetry: str, pattern: str
    ) -> List[str]:
        """Apply symmetry by generating half and mirroring."""
        if symmetry == "horizontal":
            # Left-right symmetry: generate left half, mirror to right
            half_cols = (cols + 1) // 2
            half_count = (target_count + 1) // 2

            # Generate positions in left half
            left_positions = [f"{x}_{y}" for x in range(half_cols) for y in range(rows)]
            selected_left = random.sample(left_positions, min(half_count, len(left_positions)))

            # Mirror to right
            result = set()
            for pos in selected_left:
                x, y = map(int, pos.split("_"))
                result.add(pos)
                mirror_x = cols - 1 - x
                if mirror_x >= 0 and mirror_x < cols:
                    result.add(f"{mirror_x}_{y}")

            return list(result)[:target_count]

        elif symmetry == "vertical":
            # Top-bottom symmetry: generate top half, mirror to bottom
            half_rows = (rows + 1) // 2
            half_count = (target_count + 1) // 2

            top_positions = [f"{x}_{y}" for x in range(cols) for y in range(half_rows)]
            selected_top = random.sample(top_positions, min(half_count, len(top_positions)))

            result = set()
            for pos in selected_top:
                x, y = map(int, pos.split("_"))
                result.add(pos)
                mirror_y = rows - 1 - y
                if mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{x}_{mirror_y}")

            return list(result)[:target_count]

        elif symmetry == "both":
            # 4-way symmetry: generate top-left quadrant, mirror to all
            half_cols = (cols + 1) // 2
            half_rows = (rows + 1) // 2
            quarter_count = (target_count + 3) // 4

            quadrant_positions = [f"{x}_{y}" for x in range(half_cols) for y in range(half_rows)]
            selected_quadrant = random.sample(quadrant_positions, min(quarter_count, len(quadrant_positions)))

            result = set()
            for pos in selected_quadrant:
                x, y = map(int, pos.split("_"))
                # Add all 4 symmetric positions
                result.add(f"{x}_{y}")
                mirror_x = cols - 1 - x
                mirror_y = rows - 1 - y
                if mirror_x >= 0 and mirror_x < cols:
                    result.add(f"{mirror_x}_{y}")
                if mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{x}_{mirror_y}")
                if mirror_x >= 0 and mirror_x < cols and mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{mirror_x}_{mirror_y}")

            return list(result)[:target_count]

        # Default: no symmetry
        all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
        return random.sample(all_positions, min(target_count, len(all_positions)))

    def _is_position_covered_by_upper(
        self, level: Dict[str, Any], layer_idx: int, col: int, row: int
    ) -> bool:
        """Check if a position is covered by tiles in upper layers.

        Based on sp_template TileGroup.FindAllUpperTiles logic:
        - Same parity (layer 0→2, 1→3): Check same position only
        - Different parity: Compare layer col sizes to determine offset direction
          - Upper layer col > current layer col: Check (0,0), (+1,0), (0,+1), (+1,+1)
          - Upper layer col <= current layer col: Check (-1,-1), (0,-1), (-1,0), (0,0)

        Parity is determined by layer_idx % 2.
        """
        num_layers = level.get("layer", 8)

        # Early exit if on top layer
        if layer_idx >= num_layers - 1:
            return False

        tile_parity = layer_idx % 2
        cur_layer_data = level.get(f"layer_{layer_idx}", {})
        cur_layer_col = int(cur_layer_data.get("col", 7))

        # Blocking offsets based on parity
        BLOCKING_OFFSETS_SAME_PARITY = ((0, 0),)
        BLOCKING_OFFSETS_UPPER_BIGGER = ((0, 0), (1, 0), (0, 1), (1, 1))
        BLOCKING_OFFSETS_UPPER_SMALLER = ((-1, -1), (0, -1), (-1, 0), (0, 0))

        for upper_layer_idx in range(layer_idx + 1, num_layers):
            upper_layer_key = f"layer_{upper_layer_idx}"
            upper_layer_data = level.get(upper_layer_key, {})
            upper_tiles = upper_layer_data.get("tiles", {})

            if not upper_tiles:
                continue

            upper_parity = upper_layer_idx % 2
            upper_layer_col = int(upper_layer_data.get("col", 7))

            # [v15.49 revert] 원래 col-기반 로직 — 디바이스와 일치
            if tile_parity == upper_parity:
                blocking_offsets = BLOCKING_OFFSETS_SAME_PARITY
            elif upper_layer_col > cur_layer_col:
                blocking_offsets = BLOCKING_OFFSETS_UPPER_BIGGER
            else:
                blocking_offsets = BLOCKING_OFFSETS_UPPER_SMALLER

            for dx, dy in blocking_offsets:
                bx = col + dx
                by = row + dy
                pos_key = f"{bx}_{by}"
                if pos_key in upper_tiles:
                    return True

        return False

    def _add_tutorial_gimmick(
        self, level: Dict[str, Any], gimmick_type: str, min_count: int = 2
    ) -> Dict[str, Any]:
        """
        Add tutorial gimmick to the top layers for tutorial UI display.

        Tutorial gimmicks are placed on the topmost layers with tiles to make them
        immediately visible when the level starts, facilitating tutorial UI overlay.
        If the top layer doesn't have enough eligible positions, lower layers are tried.

        Args:
            level: Level data to modify
            gimmick_type: Type of gimmick to add (e.g., 'chain', 'ice', 'frog')
            min_count: Minimum number of gimmicks to place (default: 2)

        Returns:
            Modified level with tutorial gimmicks placed on top layers
        """
        num_layers = level.get("layer", 8)

        # Find all layers with tiles, sorted from top to bottom
        layers_with_tiles = []
        for i in range(num_layers - 1, -1, -1):  # num_layers-1 → ... → 0 (highest first)
            layer_key = f"layer_{i}"
            layer_tiles = level.get(layer_key, {}).get("tiles", {})
            if layer_tiles:
                layers_with_tiles.append(i)

        if not layers_with_tiles:
            return level  # No tiles found

        top_layer_idx = layers_with_tiles[0]
        layer_key = f"layer_{top_layer_idx}"
        layer_data = level.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        # Find eligible tiles (normal tiles without existing gimmicks)
        eligible_positions = []
        for pos, tile_data in tiles.items():
            if not isinstance(tile_data, list) or len(tile_data) == 0:
                continue
            tile_type = tile_data[0]
            # Skip goal tiles (craft_*, stack_*)
            if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                continue
            # Skip tiles with existing gimmicks
            gimmick = tile_data[1] if len(tile_data) > 1 else ""
            if gimmick:
                continue
            eligible_positions.append(pos)

        if not eligible_positions:
            return level  # No eligible positions

        # Map gimmick types to their attribute format
        GIMMICK_ATTRIBUTES = {
            "chain": "chain",
            "ice": "ice",
            "frog": "frog",
            "grass": "grass",
            "bomb": "bomb",  # Note: bomb needs countdown, handled separately below
            # 게임 파서(DB_Level.cs:320)는 "curtain_open"/"curtain_close" 만 인정한다.
            # 그냥 "curtain" 을 넣으면 else 로 떨어져 TileEffectType.None = **기믹이 사라진다**.
            "curtain": "curtain_close",
            "unknown": "unknown",
            "link": "link_e",  # Default to east direction for link
            "teleport": "teleporter",  # Client expects "teleporter"
        }

        # craft/stack/key are tile types, not attributes - skip tutorial gimmick placement
        #
        # [key 추가 이유] GIMMICK_ATTRIBUTES 에 "key" 항목이 없어 .get("key","key") 가 "key" 를
        # 그대로 돌려주고, 그게 tile_data[1](=xEffect)에 찍혔다. 게임은
        #   DB_Level.cs:234  isKeyTile => ... || xEffect.ToLower() == "key"
        # 라서 ["t8","key"] 를 t8 이 아니라 **키타일(tileIDNum=16)** 로 읽는다. 결과적으로
        # 해당 색이 1장씩 증발해 ÷3 이 깨지고 그 색은 영구 매칭불가가 된다
        # (실측 Lv111: t7 3→2, t8 3→2, t11 6→5 — 6장이 보드에 영원히 남음).
        # 키타일은 unlockTile(=xUnlockTile) 로 게임이 t0 분배에서 직접 만들므로
        # 튜토리얼이 속성으로 찍을 대상이 아니다.
        if gimmick_type in ("craft", "stack", "key"):
            logger.info(f"Tutorial gimmick '{gimmick_type}' is a goal tile type, not an attribute - skipping")
            return level

        # unknown gimmick requires tiles to be COVERED by upper layers to work
        # Placing on top layer would make them visible (no curtain effect)
        # Unknown tutorial is handled by boosting unknown ratio in _add_obstacles instead
        if gimmick_type == "unknown":
            logger.info(f"Tutorial gimmick 'unknown' requires covered tiles - will boost ratio in _add_obstacles instead")
            return level

        # SPECIAL HANDLING: Grass needs 2+ clearable neighbors
        if gimmick_type == "grass":
            grass_eligible = []
            for pos in eligible_positions:
                try:
                    col, row = map(int, pos.split('_'))
                except:
                    continue
                # Check 4 directions for clearable neighbors
                neighbors = [(col, row-1), (col, row+1), (col-1, row), (col+1, row)]
                clearable_count = 0
                for ncol, nrow in neighbors:
                    npos = f"{ncol}_{nrow}"
                    if npos in tiles:
                        ndata = tiles[npos]
                        if (isinstance(ndata, list) and len(ndata) >= 1 and
                            not (isinstance(ndata[0], str) and (ndata[0].startswith("craft_") or ndata[0].startswith("stack_")))):
                            clearable_count += 1
                # [홀짝 착각방지] 짝수 층차 0오프셋 겹침 없는 위치만 선호(최종 strip과 동일 규칙).
                if clearable_count >= 2 and self._grass_position_valid(level, top_layer_idx, col, row):
                    grass_eligible.append(pos)

            if not grass_eligible:
                logger.warning(f"Tutorial gimmick 'grass' - 홀짝안전 위치 없음, 2+이웃 위치로 폴백")
                # 1차 폴백: 홀짝검증 없이 2+이웃 위치
                for pos in eligible_positions:
                    try:
                        col, row = map(int, pos.split('_'))
                    except (ValueError, AttributeError):
                        continue
                    neighbors = [(col, row - 1), (col, row + 1), (col - 1, row), (col + 1, row)]
                    cc = sum(1 for nc, nr in neighbors if f"{nc}_{nr}" in tiles
                             and isinstance(tiles[f"{nc}_{nr}"], list) and tiles[f"{nc}_{nr}"]
                             and not str(tiles[f"{nc}_{nr}"][0]).startswith(("craft_", "stack_")))
                    if cc >= 2:
                        grass_eligible.append(pos)
            if not grass_eligible:
                grass_eligible = eligible_positions  # 최종 폴백

            eligible_positions = grass_eligible
            logger.info(f"Tutorial gimmick 'grass' - {len(eligible_positions)} positions with valid neighbors")

        # SPECIAL HANDLING: Link needs pairs with matching directions
        if gimmick_type == "link":
            placed_count = 0
            target_count = min_count  # Need at least min_count link tiles (2 tiles per pair)

            # Try each layer from top to bottom
            for current_layer_idx in layers_with_tiles:
                if placed_count >= target_count:
                    break

                current_layer_key = f"layer_{current_layer_idx}"
                current_tiles = level.get(current_layer_key, {}).get("tiles", {})

                # Find eligible positions on this layer
                layer_eligible = []
                for pos, tile_data in current_tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) == 0:
                        continue
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        continue
                    gimmick = tile_data[1] if len(tile_data) > 1 else ""
                    if gimmick:
                        continue
                    layer_eligible.append(pos)

                # Find horizontal and vertical pairs
                # CRITICAL: Also track adjacent positions to prevent link tiles from being neighbors
                link_pairs = []
                used_positions = set()  # Positions used by link pairs
                blocked_positions = set()  # Positions that cannot have links (adjacent to existing links)

                for pos in layer_eligible:
                    if pos in used_positions or pos in blocked_positions:
                        continue
                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    # Check for horizontal pair (east-west)
                    east_pos = f"{col+1}_{row}"
                    if east_pos in layer_eligible and east_pos not in used_positions and east_pos not in blocked_positions:
                        link_pairs.append((pos, east_pos, "link_e", "link_w", current_tiles))
                        used_positions.add(pos)
                        used_positions.add(east_pos)
                        # Block adjacent positions to prevent adjacent links
                        for adj in [f"{col}_{row-1}", f"{col}_{row+1}", f"{col-1}_{row}",
                                   f"{col+1}_{row-1}", f"{col+1}_{row+1}", f"{col+2}_{row}"]:
                            blocked_positions.add(adj)
                        continue

                    # Check for vertical pair (north-south)
                    south_pos = f"{col}_{row+1}"
                    if south_pos in layer_eligible and south_pos not in used_positions and south_pos not in blocked_positions:
                        # [LINK_DIR_FIX] 소스=pos(북쪽 멤버)는 남쪽 짝(row+1)을 가리켜야 하므로 link_s.
                        # 게임 FindLinkTile: link_s→(x,row+1)=south_pos. (link_n는 row-1을 봐서 짝을 못 찾음=고아)
                        link_pairs.append((pos, south_pos, "link_s", "link_n", current_tiles))
                        used_positions.add(pos)
                        used_positions.add(south_pos)
                        # Block adjacent positions to prevent adjacent links
                        for adj in [f"{col-1}_{row}", f"{col+1}_{row}", f"{col}_{row-1}",
                                   f"{col-1}_{row+1}", f"{col+1}_{row+1}", f"{col}_{row+2}"]:
                            blocked_positions.add(adj)

                # Place link pairs on this layer
                # CRITICAL: Only ONE tile in the pair should have the link attribute
                # The target tile must NOT have any attribute
                random.shuffle(link_pairs)
                for pos1, pos2, attr1, attr2, layer_tiles in link_pairs:
                    if placed_count >= target_count:
                        break

                    tile1 = layer_tiles[pos1]
                    # tile2 is the target - it should NOT have link attribute

                    # Only set link attribute on source tile (tile1)
                    if len(tile1) == 1:
                        tile1.append(attr1)
                    else:
                        tile1[1] = attr1

                    # DO NOT set link attribute on target tile (tile2)
                    # Target tile must remain without attribute

                    placed_count += 1  # Count as 1 link (not 2)
                    logger.debug(f"Tutorial gimmick 'link' placed at layer {current_layer_idx}: {pos1}({attr1}) -> {pos2}")

            logger.info(f"Tutorial gimmick 'link' placed: {placed_count} tiles total")
            return level

        # Place gimmicks on top layer (for non-special gimmicks)
        gimmick_attr = GIMMICK_ATTRIBUTES.get(gimmick_type, gimmick_type)
        placed_count = 0

        # Try to place on top layer first
        positions_to_use = min(min_count, len(eligible_positions))
        random.shuffle(eligible_positions)

        for pos in eligible_positions[:positions_to_use]:
            tile_data = tiles[pos]
            if len(tile_data) == 1:
                tile_data.append(gimmick_attr)
            else:
                tile_data[1] = gimmick_attr
            placed_count += 1
            logger.debug(f"Tutorial gimmick '{gimmick_attr}' placed at layer {top_layer_idx}, pos {pos}")

        # If we didn't place enough, try lower layers
        if placed_count < min_count and len(layers_with_tiles) > 1:
            for lower_layer_idx in layers_with_tiles[1:]:  # Skip top layer, try lower ones
                if placed_count >= min_count:
                    break

                lower_layer_key = f"layer_{lower_layer_idx}"
                lower_tiles = level.get(lower_layer_key, {}).get("tiles", {})

                # Find eligible positions on this layer
                lower_eligible = []
                for pos, tile_data in lower_tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) == 0:
                        continue
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        continue
                    gimmick = tile_data[1] if len(tile_data) > 1 else ""
                    if gimmick:
                        continue

                    # For grass, check neighbors on this layer
                    if gimmick_type == "grass":
                        try:
                            col, row = map(int, pos.split('_'))
                        except:
                            continue
                        neighbors = [(col, row-1), (col, row+1), (col-1, row), (col+1, row)]
                        clearable_count = 0
                        for ncol, nrow in neighbors:
                            npos = f"{ncol}_{nrow}"
                            if npos in lower_tiles:
                                ndata = lower_tiles[npos]
                                if isinstance(ndata, list) and len(ndata) >= 1:
                                    clearable_count += 1
                        if clearable_count < 2:
                            continue

                    lower_eligible.append(pos)

                if lower_eligible:
                    random.shuffle(lower_eligible)
                    for pos in lower_eligible:
                        if placed_count >= min_count:
                            break
                        tile_data = lower_tiles[pos]
                        if len(tile_data) == 1:
                            tile_data.append(gimmick_attr)
                        else:
                            tile_data[1] = gimmick_attr
                        placed_count += 1
                        logger.debug(f"Tutorial gimmick '{gimmick_attr}' placed at layer {lower_layer_idx}, pos {pos} (fallback)")

        logger.info(f"Tutorial gimmick '{gimmick_type}' placed: {placed_count} tiles (top layer: {top_layer_idx})")

        return level

    def _ensure_container_goal_tutorial(
        self, level: Dict[str, Any], base_type: str
    ) -> Dict[str, Any]:
        """craft/stack 튜토리얼 레벨에 해당 컨테이너 goal이 최소 1개 존재하도록 보장.

        _add_goals가 소형 레이아웃에서 배치에 실패해 컨테이너 0개가 되면 튜토리얼 성립 불가.
        최상단(비커버) 레이어의 일반 타일 1개를 컨테이너 [f'{base}_s','',[3]]로 변환한다.
        타입 카운트 -1은 후속 _finalize_divisibility_guarantee/FINAL_REPAIR가 ÷3 재보장하고,
        내부 t0 3개는 세트분배로 처리된다. 이미 컨테이너가 있으면 무변경.
        """
        num_layers = int(level.get("layer", 0) or 0)
        # 이미 해당 base 컨테이너가 있으면 skip
        for i in range(num_layers):
            for pos, td in (level.get(f"layer_{i}", {}) or {}).get("tiles", {}).items():
                if isinstance(td, list) and td and str(td[0]).startswith(base_type + "_"):
                    return level

        # 최상단 레이어부터 아래로: 비커버(윗층 없음) 일반 타일 후보 탐색
        for i in range(num_layers - 1, -1, -1):
            tiles = (level.get(f"layer_{i}", {}) or {}).get("tiles", {})
            if not tiles:
                continue
            candidates = []
            for pos, td in tiles.items():
                if not (isinstance(td, list) and td):
                    continue
                t0 = str(td[0])
                # 일반 타일(t1~t15)만, 기믹/goal/key 제외
                if not (t0.startswith("t") and t0[1:].isdigit() and t0 != "t0"):
                    continue
                if len(td) >= 2 and td[1]:
                    continue
                try:
                    col, row = map(int, pos.split("_"))
                except Exception:
                    continue
                if not self._is_position_covered_by_upper(level, i, col, row):
                    candidates.append(pos)
            if candidates:
                import random as _r
                pos = _r.choice(candidates)
                self._place_goal_tile(tiles, pos, f"{base_type}_s", self.MIN_GOAL_COUNT)
                logger.info(f"[TUTORIAL_CONTAINER] '{base_type}' 컨테이너 없음 → layer {i} pos {pos}에 {base_type}_s 배치")
                return level

        logger.warning(f"[TUTORIAL_CONTAINER] '{base_type}' 컨테이너 배치 실패 — 후보 없음")
        return level

    def _ensure_tutorial_gimmick_count(
        self, level: Dict[str, Any], gimmick_type: str, min_count: int
    ) -> Dict[str, Any]:
        """
        Ensure the tutorial gimmick has at least min_count instances after all validations.

        This is called at the END of generation after all obstacle validations, which may have
        removed some gimmicks. If count is below minimum, adds more in valid positions.

        Args:
            level: Level data
            gimmick_type: Type of gimmick to ensure (e.g., 'chain', 'ice', 'frog')
            min_count: Minimum number of gimmicks required

        Returns:
            Modified level with tutorial gimmicks ensured
        """
        # craft/stack are goal tile types, not attributes - skip
        if gimmick_type in ("craft", "stack"):
            logger.info(f"Tutorial gimmick '{gimmick_type}' is a goal tile type, not an attribute - skipping ensure count")
            return level

        num_layers = level.get("layer", 8)

        # Map gimmick types to their attribute format
        GIMMICK_ATTRIBUTES = {
            "chain": "chain",
            "ice": "ice",
            "frog": "frog",
            "grass": "grass",
            "bomb": "bomb",  # Note: bomb needs countdown, handled separately
            # 게임 파서(DB_Level.cs:320)는 "curtain_open"/"curtain_close" 만 인정한다.
            # 그냥 "curtain" 을 넣으면 else 로 떨어져 TileEffectType.None = **기믹이 사라진다**.
            "curtain": "curtain_close",
            "link": "link_e",
            "teleport": "teleporter",  # Client expects "teleporter"
        }

        gimmick_attr = GIMMICK_ATTRIBUTES.get(gimmick_type, gimmick_type)

        # Count current gimmick instances
        current_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 1:
                    attr = tile_data[1]
                    # Handle variants (link_e, link_w, link_n, link_s)
                    if attr == gimmick_attr or (gimmick_type == "link" and attr and attr.startswith("link_")):
                        current_count += 1

        if current_count >= min_count:
            return level  # Already have enough

        needed = min_count - current_count
        logger.info(f"Tutorial gimmick '{gimmick_type}' needs {needed} more (current: {current_count}, min: {min_count})")

        # Find layers with tiles, sorted from top to bottom
        layers_with_tiles = []
        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            layer_tiles = level.get(layer_key, {}).get("tiles", {})
            if layer_tiles:
                layers_with_tiles.append(i)

        if not layers_with_tiles:
            return level

        added = 0

        # For chain: need LEFT or RIGHT clearable neighbor
        if gimmick_type == "chain":
            for layer_idx in layers_with_tiles:
                if added >= needed:
                    break

                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                # Find eligible positions with valid neighbors
                candidates = []
                for pos, tile_data in tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    # Skip goal tiles
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    # Skip tiles with existing gimmicks
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue

                    # Check for clearable left or right neighbor
                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    for ncol in [col - 1, col + 1]:
                        npos = f"{ncol}_{row}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            if isinstance(ndata, list) and len(ndata) >= 2:
                                # Neighbor must be clearable (no obstacle or frog only)
                                if not ndata[1] or ndata[1] == "frog":
                                    candidates.append(pos)
                                    break

                if candidates:
                    random.shuffle(candidates)
                    for pos in candidates:
                        if added >= needed:
                            break
                        tile_data = tiles[pos]
                        if len(tile_data) == 1:
                            tile_data.append("chain")
                        else:
                            tile_data[1] = "chain"
                        added += 1
                        logger.debug(f"Tutorial gimmick 'chain' ensured at layer {layer_idx}, pos {pos}")

        # For link: need pairs
        # CRITICAL: Also track adjacent positions to prevent link tiles from being neighbors
        elif gimmick_type == "link":
            for layer_idx in layers_with_tiles:
                if added >= needed:
                    break

                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                # Find eligible pairs
                used = set()  # Positions used by link pairs
                blocked = set()  # Positions that cannot have links (adjacent to existing links)
                pairs = []
                for pos, tile_data in tiles.items():
                    if pos in used or pos in blocked:
                        continue
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue

                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    # Check east neighbor
                    east_pos = f"{col+1}_{row}"
                    if east_pos in tiles and east_pos not in used and east_pos not in blocked:
                        east_data = tiles[east_pos]
                        if isinstance(east_data, list) and len(east_data) >= 1:
                            if not (east_data[0] in self.GOAL_TYPES or east_data[0].startswith("craft_") or east_data[0].startswith("stack_")):
                                if len(east_data) < 2 or not east_data[1]:
                                    pairs.append((pos, east_pos, "link_e", "link_w"))
                                    used.add(pos)
                                    used.add(east_pos)
                                    # Block adjacent positions
                                    for adj in [f"{col}_{row-1}", f"{col}_{row+1}", f"{col-1}_{row}",
                                               f"{col+1}_{row-1}", f"{col+1}_{row+1}", f"{col+2}_{row}"]:
                                        blocked.add(adj)
                                    continue

                    # Check south neighbor
                    south_pos = f"{col}_{row+1}"
                    if south_pos in tiles and south_pos not in used and south_pos not in blocked:
                        south_data = tiles[south_pos]
                        if isinstance(south_data, list) and len(south_data) >= 1:
                            if not (south_data[0] in self.GOAL_TYPES or south_data[0].startswith("craft_") or south_data[0].startswith("stack_")):
                                if len(south_data) < 2 or not south_data[1]:
                                    # [LINK_DIR_FIX] 소스=pos(북쪽 멤버)는 남쪽 짝을 가리켜야 하므로 link_s
                                    # (게임 FindLinkTile: link_s→row+1=south_pos). link_n는 row-1 조회 → 고아.
                                    pairs.append((pos, south_pos, "link_s", "link_n"))
                                    used.add(pos)
                                    used.add(south_pos)
                                    # Block adjacent positions
                                    for adj in [f"{col-1}_{row}", f"{col+1}_{row}", f"{col}_{row-1}",
                                               f"{col-1}_{row+1}", f"{col+1}_{row+1}", f"{col}_{row+2}"]:
                                        blocked.add(adj)

                # CRITICAL: Only ONE tile in the pair should have the link attribute
                for pos1, pos2, attr1, attr2 in pairs:
                    if added >= needed:
                        break
                    tile1 = tiles[pos1]
                    # tile2 is the target - it should NOT have link attribute

                    # Only set link attribute on source tile (tile1)
                    if len(tile1) == 1:
                        tile1.append(attr1)
                    else:
                        tile1[1] = attr1
                    # DO NOT set link attribute on target tile (tile2)

                    added += 1  # Count as 1 link (not 2)
                    logger.debug(f"Tutorial gimmick 'link' ensured at layer {layer_idx}: {pos1}({attr1}) -> {pos2}")

        # For grass: need 2+ clearable neighbors
        elif gimmick_type == "grass":
            for layer_idx in layers_with_tiles:
                if added >= needed:
                    break

                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                candidates = []
                for pos, tile_data in tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue

                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    # Count clearable neighbors
                    neighbors = [(col-1, row), (col+1, row), (col, row-1), (col, row+1)]
                    clearable = 0
                    for ncol, nrow in neighbors:
                        npos = f"{ncol}_{nrow}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            if isinstance(ndata, list) and len(ndata) >= 1:
                                clearable += 1
                    # 홀짝착각 방지: _strip_confusing_grass가 나중에 제거하지 않도록
                    # parity-valid 위치에만 grass 배치.
                    if clearable >= 2 and self._grass_position_valid(level, layer_idx, col, row):
                        candidates.append(pos)

                if candidates:
                    random.shuffle(candidates)
                    for pos in candidates:
                        if added >= needed:
                            break
                        tile_data = tiles[pos]
                        if len(tile_data) == 1:
                            tile_data.append("grass")
                        else:
                            tile_data[1] = "grass"
                        added += 1
                        logger.debug(f"Tutorial gimmick 'grass' ensured at layer {layer_idx}, pos {pos}")

        # For simple gimmicks (ice, frog, bomb, curtain, teleport): just add to any empty tile
        else:
            for layer_idx in layers_with_tiles:
                if added >= needed:
                    break

                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                candidates = []
                for pos, tile_data in tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue
                    candidates.append(pos)

                if candidates:
                    random.shuffle(candidates)
                    for pos in candidates:
                        if added >= needed:
                            break
                        tile_data = tiles[pos]
                        # Bomb needs countdown in attribute (format: "bomb_N")
                        if gimmick_type == "bomb":
                            countdown = random.randint(BOMB_COUNTDOWN_MIN, BOMB_COUNTDOWN_MAX)
                            attr_to_set = f"bomb_{countdown}"
                        else:
                            attr_to_set = gimmick_attr
                        if len(tile_data) == 1:
                            tile_data.append(attr_to_set)
                        else:
                            tile_data[1] = attr_to_set
                        added += 1
                        logger.debug(f"Tutorial gimmick '{attr_to_set}' ensured at layer {layer_idx}, pos {pos}")

        logger.info(f"Tutorial gimmick '{gimmick_type}' ensured: added {added}, total now {current_count + added}")
        return level

    def _ensure_unknown_tutorial_count(
        self, level: Dict[str, Any], min_count: int
    ) -> Dict[str, Any]:
        """
        Ensure the tutorial 'unknown' gimmick has at least min_count instances.

        Unknown gimmicks are special because they MUST be covered by upper layer tiles
        to show the curtain effect. This method:
        1. Counts current covered unknown gimmicks
        2. If below minimum, finds tiles that ARE covered and adds unknown to them
        3. If not enough covered positions, adds tiles to create coverage

        Args:
            level: Level data
            min_count: Minimum number of unknown gimmicks required

        Returns:
            Modified level with unknown tutorial gimmicks ensured
        """
        num_layers = level.get("layer", 8)

        # Count current unknown gimmicks that are properly covered
        current_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 1 and tile_data[1] == "unknown":
                    # Verify it's covered
                    try:
                        col, row = map(int, pos.split('_'))
                        if self._is_position_covered_by_upper(level, i, col, row):
                            current_count += 1
                    except:
                        pass

        if current_count >= min_count:
            return level  # Already have enough

        needed = min_count - current_count
        logger.info(f"Tutorial gimmick 'unknown' needs {needed} more (current covered: {current_count}, min: {min_count})")

        # Find tiles that ARE covered by upper layers but don't have a gimmick
        covered_candidates = []
        for i in range(num_layers - 1):  # Skip top layer (can't be covered)
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 1:
                    continue
                # Skip goal tiles
                if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                    continue
                # Skip tiles with existing gimmicks
                if len(tile_data) >= 2 and tile_data[1]:
                    continue
                # Check if covered
                try:
                    col, row = map(int, pos.split('_'))
                    if self._is_position_covered_by_upper(level, i, col, row):
                        covered_candidates.append((i, pos, tile_data))
                except:
                    continue

        # Add unknown to covered candidates
        added = 0
        random.shuffle(covered_candidates)
        for layer_idx, pos, tile_data in covered_candidates:
            if added >= needed:
                break
            if len(tile_data) == 1:
                tile_data.append("unknown")
            else:
                tile_data[1] = "unknown"
            added += 1
            logger.debug(f"Tutorial gimmick 'unknown' ensured at layer {layer_idx}, pos {pos}")

        # If still need more, we need to create coverage by adding tiles above existing tiles
        if added < needed:
            remaining = needed - added
            logger.info(f"Need {remaining} more unknown gimmicks - will create coverage")

            # Find tiles without gimmicks on lower layers (0, 1, 2) that could potentially be covered
            for target_layer in range(min(3, num_layers - 1)):  # Lower layers have more room for upper tiles
                if added >= needed:
                    break

                layer_key = f"layer_{target_layer}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                for pos, tile_data in list(tiles.items()):
                    if added >= needed:
                        break
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue
                    if tile_data[0] in self.GOAL_TYPES or tile_data[0].startswith("craft_") or tile_data[0].startswith("stack_"):
                        continue
                    if len(tile_data) >= 2 and tile_data[1]:
                        continue

                    try:
                        col, row = map(int, pos.split('_'))
                    except:
                        continue

                    # Check if already covered
                    if self._is_position_covered_by_upper(level, target_layer, col, row):
                        # Already covered - just add unknown
                        if len(tile_data) == 1:
                            tile_data.append("unknown")
                        else:
                            tile_data[1] = "unknown"
                        added += 1
                        logger.debug(f"Tutorial gimmick 'unknown' added to already-covered tile at layer {target_layer}, pos {pos}")
                        continue

                    # Not covered - try to add a tile above to create coverage
                    # Find the nearest upper layer that could cover this position
                    tile_added = False
                    for upper_layer in range(target_layer + 1, num_layers):
                        upper_layer_key = f"layer_{upper_layer}"
                        if upper_layer_key not in level:
                            continue

                        upper_tiles = level.get(upper_layer_key, {}).get("tiles", {})
                        upper_layer_data = level.get(upper_layer_key, {})

                        # Calculate the covering position based on parity
                        tile_parity = target_layer % 2
                        upper_parity = upper_layer % 2

                        if tile_parity == upper_parity:
                            # Same parity - same position covers
                            cover_pos = pos
                        else:
                            upper_col = int(upper_layer_data.get("col", 7))
                            current_col = int(level.get(layer_key, {}).get("col", 7))

                            if upper_col > current_col:
                                # Check if any of the 4 positions would cover - use (0,0) for simplicity
                                cover_pos = pos
                            else:
                                # Use offset position
                                cover_pos = pos

                        # Check if position is valid for this layer (within bounds)
                        try:
                            c, r = map(int, cover_pos.split('_'))
                            layer_col = int(upper_layer_data.get("col", 7))
                            layer_row = int(upper_layer_data.get("row", 7))
                            if c < 0 or r < 0 or c >= layer_col or r >= layer_row:
                                continue
                        except:
                            continue

                        # Add tile to upper layer if position is empty
                        if cover_pos not in upper_tiles:
                            # Get a tile type from existing tiles
                            tile_types = []
                            for td in tiles.values():
                                if isinstance(td, list) and len(td) >= 1 and td[0] not in self.GOAL_TYPES:
                                    if not td[0].startswith("craft_") and not td[0].startswith("stack_"):
                                        tile_types.append(td[0])
                            if tile_types:
                                new_tile_type = random.choice(tile_types)
                                self._place_tile(upper_tiles, cover_pos, new_tile_type, "")
                                level[upper_layer_key]["tiles"] = upper_tiles
                                # Update num count
                                level[upper_layer_key]["num"] = str(len(upper_tiles))

                                # Now add unknown to the target tile
                                if len(tile_data) == 1:
                                    tile_data.append("unknown")
                                else:
                                    tile_data[1] = "unknown"
                                added += 1
                                tile_added = True
                                logger.debug(f"Tutorial gimmick 'unknown' created by adding cover tile at layer {upper_layer}, pos {cover_pos}")
                                break

                    if not tile_added:
                        # Couldn't create coverage - skip this position
                        pass

        logger.info(f"Tutorial gimmick 'unknown' ensured: added {added}, total now {current_count + added}")
        return level

    def _add_obstacles(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Add obstacles and attributes to tiles following game rules."""
        # Use None check to allow empty list (empty list means no obstacles)
        # Default: ALL obstacle types (filtering by unlock level should happen at API level)
        ALL_OBSTACLE_TYPES_DEFAULT = ["chain", "frog", "link", "grass", "ice", "bomb", "curtain", "teleport", "unknown"]
        obstacle_types = params.obstacle_types if params.obstacle_types is not None else ALL_OBSTACLE_TYPES_DEFAULT
        target = params.target_difficulty

        # Get gimmick intensity multiplier (0.0 = no gimmicks, 1.0 = normal, 2.0 = double)
        gimmick_intensity = getattr(params, 'gimmick_intensity', 1.0)

        # If gimmick_intensity is 0, skip all obstacle generation (except tutorial gimmick)
        tutorial_gimmick = getattr(params, 'tutorial_gimmick', None)
        tutorial_gimmick_min_count = getattr(params, 'tutorial_gimmick_min_count', 2)

        # Handle tutorial gimmick first (always placed on top layer for tutorial UI)
        logger.info(f"[_add_obstacles] tutorial_gimmick={tutorial_gimmick}, min_count={tutorial_gimmick_min_count}")
        if tutorial_gimmick:
            logger.info(f"[_add_obstacles] Calling _add_tutorial_gimmick with gimmick_type={tutorial_gimmick}")
            level = self._add_tutorial_gimmick(level, tutorial_gimmick, tutorial_gimmick_min_count)

        if gimmick_intensity <= 0:
            return level

        # Calculate target obstacle counts based on difficulty
        num_layers = level.get("layer", 8)
        total_tiles = sum(
            len(level.get(f"layer_{i}", {}).get("tiles", {}))
            for i in range(num_layers)
        )

        # Check if per-layer obstacle configs are provided (they take priority)
        has_layer_obstacle_configs = bool(params.layer_obstacle_configs)

        # Helper to get target count for an obstacle type (global)
        # Only used when per-layer configs are NOT provided
        # [연구 근거] Tile Busters 스타일: 개구리는 레벨당 최대 3개로 제한
        GIMMICK_MAX_COUNTS = {
            "frog": 3,  # 개구리는 선택 가능해야 하므로 최대 3개
            "bomb": 4,  # 폭탄도 과도하면 어려움
        }

        def get_global_target(obstacle_type: str, default_ratio: float) -> int:
            if has_layer_obstacle_configs:
                # Per-layer configs take priority, don't use global targets for distribution
                return 0
            if params.obstacle_counts and obstacle_type in params.obstacle_counts:
                config = params.obstacle_counts[obstacle_type]
                min_count = config.get("min", 0)
                max_count = config.get("max", 10)
                # Apply gimmick_intensity to configured counts
                result = int(random.randint(min_count, max_count) * gimmick_intensity)
                # Apply max cap if defined
                if obstacle_type in GIMMICK_MAX_COUNTS:
                    result = min(result, GIMMICK_MAX_COUNTS[obstacle_type])
                return result

            # Calculate based on difficulty
            calculated = int(total_tiles * target * default_ratio * gimmick_intensity)

            # IMPORTANT: If this gimmick is requested and gimmick_intensity > 0,
            # ensure minimum 2 instances so players can learn the mechanic
            # (언락된 기믹은 최소 2개 보장하여 학습 가능하도록)
            if obstacle_type in obstacle_types and gimmick_intensity > 0:
                min_for_learning = 2  # Minimum for player to understand the gimmick
                calculated = max(calculated, min_for_learning)

            # Apply max cap if defined (e.g., frog max 3)
            if obstacle_type in GIMMICK_MAX_COUNTS:
                calculated = min(calculated, GIMMICK_MAX_COUNTS[obstacle_type])

            return calculated

        # Helper to get per-layer obstacle target
        def get_layer_target(layer_idx: int, obstacle_type: str) -> Optional[int]:
            config = params.get_layer_obstacle_config(layer_idx, obstacle_type)
            if config is not None:
                min_count, max_count = config
                # Apply gimmick_intensity to per-layer configs
                return int(random.randint(min_count, max_count) * gimmick_intensity)
            return None

        # All supported obstacle types
        ALL_OBSTACLE_TYPES = ["chain", "frog", "link", "grass", "ice", "bomb", "curtain", "teleport", "unknown"]

        # Build per-layer obstacle targets
        layer_targets: Dict[int, Dict[str, int]] = {}
        configured_totals: Dict[str, int] = {obs: 0 for obs in ALL_OBSTACLE_TYPES}

        for i in range(num_layers):
            layer_targets[i] = {}
            for obs_type in ALL_OBSTACLE_TYPES:
                layer_target = get_layer_target(i, obs_type)
                if layer_target is not None:
                    layer_targets[i][obs_type] = layer_target
                    configured_totals[obs_type] += layer_target

        # Get global targets (use configured values or calculate from difficulty)
        # These are only used when per-layer configs are NOT provided
        #
        # Tile Buster style gimmick distribution:
        # - Gimmicks should be conservative, typically 10-20% of tiles at max difficulty
        # - S grade (0-0.2): ~0% gimmicks
        # - A grade (0.2-0.4): ~3-5% total gimmicks
        # - B grade (0.4-0.6): ~5-8% total gimmicks
        # - C grade (0.6-0.8): ~8-12% total gimmicks
        # - D grade (0.8-1.0): ~12-15% total gimmicks
        #
        # Reduced ratios to match Tile Buster style (was: chain=0.15, frog=0.08, ice=0.12)
        # Target: ~10-15% total gimmicks at max difficulty
        # [연구 근거] Room 8 Studio: 레벨 175+ 히든 타일 본격 도입
        # 레벨 번호에 따른 unknown 비율 동적 계산
        level_number = getattr(params, 'level_number', None)
        unknown_ratio = 0.02  # 기본값 2%
        if level_number is not None:
            # calculate_hidden_tile_ratio returns 0.0-0.6 based on level number
            # Level 1-90: 0%, Level 91-175: 0-15%, Level 175+: 15-60%
            unknown_ratio = max(0.02, calculate_hidden_tile_ratio(level_number))

        # Boost unknown ratio for tutorial level (unknown gimmick introduction)
        # Tutorial needs more visible unknown tiles to demonstrate the mechanic
        unknown_min_count = 0
        if tutorial_gimmick == "unknown":
            # Minimum 15% for tutorial to ensure enough unknown tiles are visible
            unknown_ratio = max(0.15, unknown_ratio)
            unknown_min_count = tutorial_gimmick_min_count  # Ensure at least min_count unknown tiles
            logger.info(f"Tutorial gimmick 'unknown' - boosted ratio to {unknown_ratio:.0%}, min_count={unknown_min_count}")

        global_targets = {
            "chain": get_global_target("chain", 0.04),
            "frog": get_global_target("frog", 0.02),
            "link": get_global_target("link", 0.02),
            "grass": get_global_target("grass", 0.03),
            "ice": get_global_target("ice", 0.03),
            "bomb": get_global_target("bomb", 0.02),  # Increased from 0.01 to ensure at least 1 bomb
            "curtain": get_global_target("curtain", 0.02),
            "teleport": get_global_target("teleport", 0.02),  # Increased from 0.01 to ensure at least 1 teleport
            # [연구 근거] 레벨 기반 동적 비율, tutorial에서는 최소 min_count 보장
            "unknown": max(unknown_min_count, get_global_target("unknown", unknown_ratio)),
        }

        # Distribute remaining to unconfigured layers
        # Only if per-layer configs are NOT provided
        if not has_layer_obstacle_configs:
            unconfigured_layers = []
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                if level.get(layer_key, {}).get("tiles", {}):
                    unconfigured_layers.append(i)

            # Gimmicks that benefit from being on lower layers (blocked by upper tiles)
            # These should be placed on layer_1+ for higher difficulty
            PREFER_LOWER_LAYER_GIMMICKS = {"chain", "grass", "ice", "link"}

            for obs_type in ALL_OBSTACLE_TYPES:
                remaining = max(0, global_targets[obs_type] - configured_totals[obs_type])
                if remaining > 0 and unconfigured_layers:
                    # Distribute remaining to layers without specific config
                    layers_needing = [
                        l for l in unconfigured_layers
                        if obs_type not in layer_targets.get(l, {})
                    ]

                    # DIFFICULTY ENHANCEMENT: For blockable gimmicks at high difficulty,
                    # prefer lower layers (layer_1+) so they can be blocked by upper tiles
                    if obs_type in PREFER_LOWER_LAYER_GIMMICKS and target >= 0.5:
                        # Sort layers by index descending (lower layers first for gimmicks)
                        # But keep some on layer_0 for variety
                        layers_needing_sorted = sorted(layers_needing, reverse=True)
                        # Allocate more to lower layers (70% to layer_1+, 30% to layer_0)
                        lower_layers = [l for l in layers_needing_sorted if l > 0]
                        if lower_layers and remaining > 1:
                            # Put majority on lower layers
                            lower_allocation = int(remaining * 0.7)
                            upper_allocation = remaining - lower_allocation
                            # Distribute to lower layers
                            if lower_allocation > 0:
                                per_lower = lower_allocation // len(lower_layers)
                                extra_lower = lower_allocation % len(lower_layers)
                                for idx, layer_idx in enumerate(lower_layers):
                                    if layer_idx not in layer_targets:
                                        layer_targets[layer_idx] = {}
                                    layer_targets[layer_idx][obs_type] = per_lower + (1 if idx < extra_lower else 0)
                            # Distribute remaining to layer_0 if it exists
                            if 0 in layers_needing and upper_allocation > 0:
                                if 0 not in layer_targets:
                                    layer_targets[0] = {}
                                layer_targets[0][obs_type] = upper_allocation
                            continue

                    if layers_needing:
                        per_layer = remaining // len(layers_needing)
                        extra = remaining % len(layers_needing)
                        for idx, layer_idx in enumerate(layers_needing):
                            if layer_idx not in layer_targets:
                                layer_targets[layer_idx] = {}
                            layer_targets[layer_idx][obs_type] = per_layer + (1 if idx < extra else 0)

        obstacles_added = {obs: 0 for obs in ALL_OBSTACLE_TYPES}

        # Add obstacles per layer
        for layer_idx in range(num_layers):
            targets = layer_targets.get(layer_idx, {})

            # Add frog obstacles (no special rules)
            if "frog" in obstacle_types:
                frog_target = targets.get("frog", 0)
                if frog_target > 0:
                    level = self._add_frog_obstacles_to_layer(
                        level, layer_idx, frog_target, obstacles_added
                    )

            # Add chain obstacles (must have clearable LEFT or RIGHT neighbor)
            if "chain" in obstacle_types:
                chain_target = targets.get("chain", 0)
                if chain_target > 0:
                    level = self._add_chain_obstacles_to_layer(
                        level, layer_idx, chain_target, obstacles_added
                    )

            # Add link obstacles (must create valid pairs with clearable neighbor)
            if "link" in obstacle_types:
                link_target = targets.get("link", 0)
                if link_target > 0:
                    level = self._add_link_obstacles_to_layer(
                        level, layer_idx, link_target, obstacles_added
                    )

            # Add grass obstacles (must have at least 2 clearable neighbors)
            if "grass" in obstacle_types:
                grass_target = targets.get("grass", 0)
                if grass_target > 0:
                    level = self._add_grass_obstacles_to_layer(
                        level, layer_idx, grass_target, obstacles_added
                    )

            # Add ice obstacles (covers tile, must be cleared by adjacent matches)
            if "ice" in obstacle_types:
                ice_target = targets.get("ice", 0)
                if ice_target > 0:
                    level = self._add_ice_obstacles_to_layer(
                        level, layer_idx, ice_target, obstacles_added
                    )

            # Add bomb obstacles (countdown bomb)
            if "bomb" in obstacle_types:
                bomb_target = targets.get("bomb", 0)
                if bomb_target > 0:
                    level = self._add_bomb_obstacles_to_layer(
                        level, layer_idx, bomb_target, obstacles_added
                    )

            # Add curtain obstacles (hides tile until adjacent match)
            if "curtain" in obstacle_types:
                curtain_target = targets.get("curtain", 0)
                if curtain_target > 0:
                    level = self._add_curtain_obstacles_to_layer(
                        level, layer_idx, curtain_target, obstacles_added
                    )

            # Add teleport obstacles (paired teleport tiles)
            if "teleport" in obstacle_types:
                teleport_target = targets.get("teleport", 0)
                if teleport_target > 0:
                    level = self._add_teleport_obstacles_to_layer(
                        level, layer_idx, teleport_target, obstacles_added
                    )

            # Add unknown obstacles (tile type hidden when covered by upper layer)
            if "unknown" in obstacle_types:
                unknown_target = targets.get("unknown", 0)
                if unknown_target > 0:
                    level = self._add_unknown_obstacles_to_layer(
                        level, layer_idx, unknown_target, obstacles_added
                    )

        # DIFFICULTY ENHANCEMENT: Place blocking tiles above chain/grass gimmicks
        # This increases difficulty by requiring players to clear upper tiles first
        if target >= 0.5:  # Only apply for medium+ difficulty levels
            level = self._add_blocking_tiles_above_gimmicks(level, target)

        return level

    def _add_blocking_tiles_above_gimmicks(
        self, level: Dict[str, Any], target_difficulty: float
    ) -> Dict[str, Any]:
        """
        DIFFICULTY ENHANCEMENT: Place blocking tiles on upper layers above chain/grass gimmicks.

        This increases difficulty by:
        - Requiring players to clear upper tiles first before accessing gimmicks
        - Chain tiles become harder because adjacent matches are blocked
        - Grass tiles become harder because neighbors are covered

        The blocking probability scales with difficulty:
        - 0.5 difficulty: ~20% of gimmicks get blocked
        - 0.7 difficulty: ~40% of gimmicks get blocked
        - 0.85 difficulty: ~60% of gimmicks get blocked
        - 1.0 difficulty: ~80% of gimmicks get blocked
        """
        num_layers = level.get("layer", 8)

        # Helper to check if gimmick type is blockable
        # Includes variants like ice_1, ice_2, link_e, link_w, link_s, link_n
        def is_blockable_gimmick(gimmick: str) -> bool:
            if not gimmick:
                return False
            return (gimmick in {"chain", "grass"} or
                    gimmick.startswith("ice") or
                    gimmick.startswith("link"))

        # Calculate blocking probability based on difficulty
        # Higher difficulty = more blocking = harder to access gimmicks
        # Maps difficulty 0.5-1.0 to probability 0.3-0.9
        blocking_probability = 0.3 + (target_difficulty - 0.5) * 1.2
        blocking_probability = max(0.3, min(0.9, blocking_probability))

        # Collect all gimmick positions per layer (except layer 0 which has no upper layer)
        gimmick_positions = []  # List of (layer_idx, position, gimmick_type)

        for layer_idx in range(1, num_layers):  # Start from 1 (layer 0 has no upper layer)
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue
                gimmick_type = tile_data[1]
                if is_blockable_gimmick(gimmick_type):
                    gimmick_positions.append((layer_idx, pos, gimmick_type))

        if not gimmick_positions:
            return level

        # Randomly select gimmicks to block based on probability
        random.shuffle(gimmick_positions)
        num_to_block = int(len(gimmick_positions) * blocking_probability)
        positions_to_block = gimmick_positions[:num_to_block]

        # Get available tile types from layer_0 for creating blocking tiles
        layer_0_tiles = level.get("layer_0", {}).get("tiles", {})
        available_tile_types = set()
        for tile_data in layer_0_tiles.values():
            if isinstance(tile_data, list) and len(tile_data) >= 1:
                tile_type = tile_data[0]
                if tile_type and tile_type not in self.GOAL_TYPES:
                    available_tile_types.add(tile_type)

        if not available_tile_types:
            # Fallback: use t0 to match the standard tile type format
            available_tile_types = {"t0"}

        tile_types_list = list(available_tile_types)

        # Place blocking tiles on upper layers
        blocked_count = 0
        for layer_idx, pos, gimmick_type in positions_to_block:
            upper_layer_idx = layer_idx - 1
            upper_layer_key = f"layer_{upper_layer_idx}"

            # Check if upper layer exists and has tiles dict
            if upper_layer_key not in level:
                continue

            upper_tiles = level[upper_layer_key].get("tiles", {})
            if upper_tiles is None:
                level[upper_layer_key]["tiles"] = {}
                upper_tiles = level[upper_layer_key]["tiles"]

            # [OOB_FIX] 차단 타일은 **그 층의 헤더(col/row) 안**에만 놓아야 한다.
            # 기존엔 경계 검사가 아예 없어 홀짝 교대로 격자 크기가 다른 층(짝수 S, 홀수 S-1)에서
            # 유효 좌표를 그대로 옮겨 적어 x/y == S-1 이 홀수층에선 범위 밖이 됐다.
            # 게임은 x >= col 타일을 조용히 스폰하지 않는다(TileLayer/TileRow) → 클리어 불가.
            # 실측: 등껍질 생성 240회 중 11회(4.6%) `L1:7_3>=7` 위반이 여기서 발생. 음수도 차단.
            try:
                _lc = int(level[upper_layer_key].get("col"))
                _lr = int(level[upper_layer_key].get("row"))
            except (TypeError, ValueError):
                continue  # 헤더 불명 → 차단 타일 생성 포기(잘못된 좌표 쓰기보다 안전)

            def _in_board(p: str) -> bool:
                try:
                    _x, _y = map(int, p.split('_'))
                except ValueError:
                    return False
                return 0 <= _x < _lc and 0 <= _y < _lr

            # Try to add blocking tile at the exact position first
            if pos not in upper_tiles and _in_board(pos):
                # Create a new blocking tile (random type, no gimmick)
                blocking_tile_type = random.choice(tile_types_list)
                self._place_tile(upper_tiles, pos, blocking_tile_type, "")
                blocked_count += 1
            else:
                # If exact position is occupied, try adjacent positions
                # This still increases difficulty by limiting access paths to the gimmick
                try:
                    col, row = map(int, pos.split('_'))
                    adjacent_positions = [
                        f"{col-1}_{row}",  # left
                        f"{col+1}_{row}",  # right
                        f"{col}_{row-1}",  # up
                        f"{col}_{row+1}",  # down
                    ]
                    for adj_pos in adjacent_positions:
                        if adj_pos not in upper_tiles and _in_board(adj_pos):
                            blocking_tile_type = random.choice(tile_types_list)
                            self._place_tile(upper_tiles, adj_pos, blocking_tile_type, "")
                            blocked_count += 1
                            break  # Only add one adjacent blocking tile
                except (ValueError, AttributeError):
                    pass

        return level

    def _add_frog_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add frog obstacles to a specific layer.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.

        [연구 근거] Tile Busters 스타일: 개구리는 레벨당 최대 3개로 제한
        """
        # Global max check - ensure we never exceed max frogs per level
        MAX_FROGS_PER_LEVEL = 3
        if counter["frog"] >= MAX_FROGS_PER_LEVEL:
            logger.debug(f"[FROG] Layer {layer_idx}: Skipping - already at max {MAX_FROGS_PER_LEVEL} frogs")
            return level

        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        added = 0
        skipped_covered = 0

        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            # Check both per-layer target and global max
            if added >= target or counter["frog"] >= MAX_FROGS_PER_LEVEL:
                break

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # RULE: Skip positions covered by upper layers (frogs must be selectable at spawn)
            try:
                col, row = map(int, pos.split('_'))
                if self._is_position_covered_by_upper(level, layer_idx, col, row):
                    skipped_covered += 1
                    continue
            except Exception as e:
                logger.warning(f"[FROG] Layer {layer_idx}: Error parsing position {pos}: {e}")
                continue

            tile_data[1] = "frog"
            added += 1
            counter["frog"] += 1
            logger.debug(f"[FROG] Layer {layer_idx}: Added frog at {pos} (total: {counter['frog']})")

        if skipped_covered > 0:
            logger.debug(f"[FROG] Layer {layer_idx}: Skipped {skipped_covered} covered positions")

        return level

    def _add_chain_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add chain obstacles to a specific layer.

        RULE: Chain tiles MUST have at least one clearable neighbor on LEFT or RIGHT.
        The neighbor must:
        1. Exist in the same layer
        2. NOT be covered by upper layers (so it can be selected first)
        3. NOT have a blocking gimmick (chain, ice, grass, link, etc.)
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Chain only checks LEFT and RIGHT neighbors (col±1 = left/right on screen)
            neighbors = [
                (col-1, row),  # Left (on screen)
                (col+1, row),  # Right (on screen)
            ]

            valid_chain = False
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos not in tiles:
                    continue
                ndata = tiles[npos]
                if not isinstance(ndata, list) or len(ndata) < 2:
                    continue
                if ndata[0] in self.GOAL_TYPES:
                    continue
                # Neighbor must be clearable (no obstacle or frog only)
                if ndata[1] and ndata[1] != "frog":
                    continue
                # CRITICAL: Neighbor must NOT be covered by upper layers
                # If covered, the chain cannot be unlocked because neighbor can't be selected first
                if self._is_position_covered_by_upper(level, layer_idx, ncol, nrow):
                    continue
                valid_chain = True
                break

            if valid_chain:
                tile_data[1] = "chain"
                added += 1
                counter["chain"] += 1

        return level

    def _add_link_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add link obstacles to a specific layer.

        Link tiles point to a direction and MUST have a tile in that direction.
        IMPORTANT: Only ONE tile in a linked pair should have the link attribute.
        The target tile must NOT have any attribute (including other links).
        A tile that is already a link target CANNOT be targeted by another link.

        Position format is "col_row" (x_y).
        - link_n: points north (up), tile must exist at row-1 (y-1)
        - link_s: points south (down), tile must exist at row+1 (y+1)
        - link_w: points west (left), tile must exist at col-1 (x-1)
        - link_e: points east (right), tile must exist at col+1 (x+1)
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 15

        positions = list(tiles.keys())

        # Track positions that are already link targets
        # This prevents multiple links pointing to the same tile
        linked_targets: set = set()

        # Also collect existing link targets from tiles that already have link attributes
        # CRITICAL: Both source (link holder) and target must be marked as used
        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) >= 2 and tile_data[1]:
                attr = tile_data[1]
                if attr.startswith("link_"):
                    try:
                        col, row = map(int, pos.split('_'))
                        # CRITICAL: Mark source position as used (link holder cannot be a target)
                        linked_targets.add(pos)
                        # Calculate target position based on link direction
                        if attr == "link_n":
                            linked_targets.add(f"{col}_{row - 1}")
                        elif attr == "link_s":
                            linked_targets.add(f"{col}_{row + 1}")
                        elif attr == "link_w":
                            linked_targets.add(f"{col - 1}_{row}")
                        elif attr == "link_e":
                            linked_targets.add(f"{col + 1}_{row}")
                    except:
                        pass

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Source tile must not be a link target already
            if pos in linked_targets:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # CRITICAL: Check if any adjacent tile already has a link attribute
            # This prevents link tiles from being adjacent to each other
            adjacent_positions = [
                f"{col}_{row - 1}",  # North
                f"{col}_{row + 1}",  # South
                f"{col - 1}_{row}",  # West
                f"{col + 1}_{row}",  # East
            ]
            has_adjacent_link = False
            for adj_pos in adjacent_positions:
                if adj_pos in tiles:
                    adj_tile = tiles[adj_pos]
                    if isinstance(adj_tile, list) and len(adj_tile) >= 2:
                        adj_attr = adj_tile[1]
                        if adj_attr and adj_attr.startswith("link_"):
                            has_adjacent_link = True
                            break
            if has_adjacent_link:
                continue

            # Direction mapping: link type -> target position
            # Position format: f"{col}_{row}"
            # link_n points north (up), so row-1
            # link_s points south (down), so row+1
            # link_w points west (left), so col-1
            # link_e points east (right), so col+1
            directions = [
                ("link_n", col, row - 1),  # North (up)
                ("link_s", col, row + 1),  # South (down)
                ("link_w", col - 1, row),  # West (left)
                ("link_e", col + 1, row),  # East (right)
            ]
            random.shuffle(directions)

            for link_type, target_col, target_row in directions:
                target_pos = f"{target_col}_{target_row}"

                # CRITICAL: The linked direction MUST have a tile
                if target_pos not in tiles:
                    continue

                # CRITICAL: Target must NOT already be a link target
                if target_pos in linked_targets:
                    continue

                target_tile = tiles[target_pos]
                if not isinstance(target_tile, list) or len(target_tile) < 2:
                    continue

                # Target tile must be a valid clearable tile (not a goal)
                if target_tile[0] in self.GOAL_TYPES:
                    continue

                # CRITICAL: Target tile must NOT have any attribute
                # This prevents both tiles in a pair from having link attributes
                # (which would count as 2 links instead of 1)
                if target_tile[1]:
                    logger.debug(f"[LINK] Skipping {pos} -> {target_pos}: target has attribute '{target_tile[1]}'")
                    continue

                # CRITICAL: Explicitly reject chain, ice, grass, and other links on target
                # This is a defensive double-check in case the generic check above fails
                BLOCKING_GIMMICKS = {"chain", "ice", "ice_1", "ice_2", "ice_3", "grass"}
                target_attr = target_tile[1]
                if target_attr in BLOCKING_GIMMICKS:
                    logger.warning(f"[LINK] BLOCKED: {pos} -> {target_pos} would create link->chain/ice/grass")
                    continue
                # CRITICAL: Target must NOT be a link source (prevents bidirectional links)
                if target_attr and target_attr.startswith("link_"):
                    logger.warning(f"[LINK] BLOCKED: {pos} -> {target_pos} target is already a link source '{target_attr}'")
                    continue

                # Valid link found - assign the link type
                tile_data[1] = link_type
                added += 1
                counter["link"] += 1

                # Mark target as linked (cannot be targeted by another link)
                linked_targets.add(target_pos)
                # Also mark source as linked target to prevent it from being targeted
                linked_targets.add(pos)
                break

        return level

    def _add_grass_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add grass obstacles to a specific layer (must have 2+ clearable neighbors)."""
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Grass checks all 4 directions
            neighbors = [
                (col, row-1),  # Up
                (col, row+1),  # Down
                (col-1, row),  # Left
                (col+1, row),  # Right
            ]

            clearable_count = 0
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        (not ndata[1] or ndata[1] == "frog") and
                        ndata[0] not in self.GOAL_TYPES):
                        clearable_count += 1

            # Must have at least 2 clearable neighbors
            if clearable_count >= 2:
                tile_data[1] = "grass"
                added += 1
                counter["grass"] += 1

        return level

    def _add_ice_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add ice obstacles to a specific layer.
        Ice covers tiles and must be cleared by adjacent matches.
        Can have 1-3 layers of ice (ice_1, ice_2, ice_3).
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            if added >= target:
                break

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Client only recognizes "ice" (not "ice_1", "ice_2", etc.)
            tile_data[1] = "ice"
            added += 1
            counter["ice"] += 1

        return level

    def _add_bomb_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add bomb obstacles to a specific layer.

        Bombs have a countdown and explode if not cleared in time.
        CRITICAL: Bombs should ONLY be placed on VISIBLE tiles (not covered by upper layers).
        This ensures players can see the bomb countdown from the start.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        num_layers = level.get("layer", 8)

        # Pre-compute positions covered by upper layers
        covered_positions = set()
        for upper_layer_idx in range(layer_idx + 1, num_layers):
            upper_layer_key = f"layer_{upper_layer_idx}"
            upper_tiles = level.get(upper_layer_key, {}).get("tiles", {})
            covered_positions.update(upper_tiles.keys())

        added = 0
        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            if added >= target:
                break

            # CRITICAL: Skip positions covered by upper layers
            # Bombs on covered tiles are invisible to the player
            if pos in covered_positions:
                continue

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Set bomb with countdown (format: "bomb_N" where N is countdown)
            # Client expects xEffect = "bomb_5" format, not separate extra array
            countdown = random.randint(BOMB_COUNTDOWN_MIN, BOMB_COUNTDOWN_MAX)
            tile_data[1] = f"bomb_{countdown}"
            # Clear extra field if exists (countdown is now in attribute)
            if len(tile_data) >= 3:
                tile_data[2] = []
            added += 1
            counter["bomb"] += 1

        return level

    def _add_curtain_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add curtain obstacles to a specific layer.
        Curtain hides the tile underneath until an adjacent match is made.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Curtain needs at least one adjacent tile to be cleared
            neighbors = [
                (col, row-1), (col, row+1),
                (col-1, row), (col+1, row),
            ]

            has_neighbor = False
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        ndata[0] not in self.GOAL_TYPES):
                        has_neighbor = True
                        break

            if has_neighbor:
                tile_data[1] = "curtain_close"
                added += 1
                counter["curtain"] += 1

        return level

    def _add_teleport_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add teleport obstacles to a specific layer.
        Teleports work in pairs - clearing one affects the paired teleport.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        # Need at least 2 tiles for a teleport pair
        if len(tiles) < 2:
            return level

        added = 0
        # Teleports are added in pairs
        pairs_to_add = target // 2
        if pairs_to_add == 0 and target > 0:
            pairs_to_add = 1

        available_positions = [
            pos for pos, data in tiles.items()
            if isinstance(data, list) and len(data) >= 2 and
            data[0] not in self.GOAL_TYPES and not data[1]
        ]
        random.shuffle(available_positions)

        pair_id = 0
        for i in range(0, len(available_positions) - 1, 2):
            if pair_id >= pairs_to_add:
                break

            pos1 = available_positions[i]
            pos2 = available_positions[i + 1]

            # Set teleport attribute (no extra field - client handles pairing)
            self._set_tile_attribute(tiles[pos1], "teleporter")
            self._set_tile_attribute(tiles[pos2], "teleporter")

            added += 2
            counter["teleport"] += 2
            pair_id += 1

        return level

    def _add_unknown_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add unknown obstacles to a specific layer.

        RULE: Unknown tiles should ONLY be placed on tiles that ARE covered by upper layers.
        This is because the unknown effect only activates when the tile is hidden by upper tiles.
        When upper tiles are removed, the tile type becomes visible.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())
        random.shuffle(positions)

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # RULE: Unknown tiles must be covered by upper layers to have any effect
            if not self._is_position_covered_by_upper(level, layer_idx, col, row):
                continue

            tile_data[1] = "unknown"
            added += 1
            counter["unknown"] += 1

        return level

    def _add_frog_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add frog obstacles.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.

        [연구 근거] Tile Busters 스타일: 개구리는 레벨당 최대 3개로 제한
        """
        MAX_FROGS_PER_LEVEL = 3
        num_layers = level.get("layer", 8)

        for i in range(num_layers - 1, -1, -1):
            # Check both target and global max
            if counter["frog"] >= target or counter["frog"] >= MAX_FROGS_PER_LEVEL:
                break

            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in list(tiles.items()):
                if counter["frog"] >= target or counter["frog"] >= MAX_FROGS_PER_LEVEL:
                    break

                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                # Skip goal tiles and tiles with attributes
                if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                    continue

                # RULE: Skip positions covered by upper layers (frogs must be selectable at spawn)
                try:
                    col, row = map(int, pos.split('_'))
                    if self._is_position_covered_by_upper(level, i, col, row):
                        continue
                except:
                    continue

                if random.random() < 0.15:
                    tile_data[1] = "frog"
                    counter["frog"] += 1

        return level

    def _add_chain_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add chain obstacles following the rule:
        Chain tiles MUST have at least one clearable neighbor on LEFT or RIGHT (same row).
        Chain is released by clearing adjacent tiles on the left or right side only.
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer with their positions
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = {
                    "tiles": tiles,
                    "cols": int(level[layer_key].get("col", 8)),
                    "rows": int(level[layer_key].get("row", 8))
                }

        # Try to add chains
        attempts = 0
        max_attempts = target * 10  # Prevent infinite loop

        while counter["chain"] < target and attempts < max_attempts:
            attempts += 1

            # Pick a random layer with tiles
            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            layer_data = layer_tiles[layer_idx]
            tiles = layer_data["tiles"]

            # Pick a random tile
            positions = list(tiles.keys())
            if not positions:
                continue

            pos = random.choice(positions)
            tile_data = tiles[pos]

            # Skip if not valid
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Parse position (format is col_row = x_y)
            try:
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Chain only checks LEFT and RIGHT neighbors (col±1 = left/right on screen)
            neighbors = [
                (col-1, row),  # Left (on screen)
                (col+1, row),  # Right (on screen)
            ]

            valid_chain = False
            for ncol, nrow in neighbors:
                neighbor_pos = f"{ncol}_{nrow}"
                if neighbor_pos not in tiles:
                    continue

                neighbor_data = tiles[neighbor_pos]
                if not isinstance(neighbor_data, list) or len(neighbor_data) < 2:
                    continue

                # Skip goal tiles
                if neighbor_data[0] in self.GOAL_TYPES:
                    continue

                # RULE: Neighbor must be clearable (no obstacle or frog only)
                if neighbor_data[1] and neighbor_data[1] != "frog":
                    continue

                # CRITICAL: Neighbor must NOT be covered by upper layers
                # If covered, the chain cannot be unlocked because neighbor can't be selected first
                if self._is_position_covered_by_upper(level, layer_idx, ncol, nrow):
                    continue

                # Valid chain position found!
                valid_chain = True
                break

            if valid_chain:
                tile_data[1] = "chain"
                counter["chain"] += 1

        return level

    def _add_grass_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add grass obstacles following the rule:
        Grass tiles MUST have at least 2 clearable neighbors in 4 directions (up/down/left/right).
        Grass is released by clearing adjacent tiles (needs at least 2 to be clearable).
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = tiles

        attempts = 0
        max_attempts = target * 10

        while counter["grass"] < target and attempts < max_attempts:
            attempts += 1

            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            tiles = layer_tiles[layer_idx]

            positions = list(tiles.keys())
            if not positions:
                continue

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Grass checks all 4 directions
            neighbors = [
                (col, row-1),  # Up
                (col, row+1),  # Down
                (col-1, row),  # Left
                (col+1, row),  # Right
            ]

            clearable_count = 0
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        (not ndata[1] or ndata[1] == "frog") and
                        ndata[0] not in self.GOAL_TYPES):
                        clearable_count += 1

            # RULE: Must have at least 2 clearable neighbors
            if clearable_count >= 2:
                tile_data[1] = "grass"
                counter["grass"] += 1

        return level

    def _add_link_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add link obstacles following the rules:
        1. Linked tiles must have their partner tile exist in the connected direction.
        2. ONLY ONE tile in a linked pair has the link attribute (not both).
        3. The target tile must NOT have any attribute.
        4. A tile that is already a link target CANNOT be targeted by another link.

        Position format is "col_row" (x_y).
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = tiles

        # Track positions that are already link targets (per layer)
        # This prevents multiple links pointing to the same tile
        linked_targets_per_layer: Dict[int, set] = {i: set() for i in layer_tiles.keys()}

        # Collect existing link targets from tiles that already have link attributes
        for layer_idx, tiles in layer_tiles.items():
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) >= 2 and tile_data[1]:
                    attr = tile_data[1]
                    if attr.startswith("link_"):
                        try:
                            col, row = map(int, pos.split('_'))
                            # Calculate target position based on link direction
                            if attr == "link_n":
                                linked_targets_per_layer[layer_idx].add(f"{col}_{row - 1}")
                            elif attr == "link_s":
                                linked_targets_per_layer[layer_idx].add(f"{col}_{row + 1}")
                            elif attr == "link_w":
                                linked_targets_per_layer[layer_idx].add(f"{col - 1}_{row}")
                            elif attr == "link_e":
                                linked_targets_per_layer[layer_idx].add(f"{col + 1}_{row}")
                            # Also add source position as it's part of a link pair
                            linked_targets_per_layer[layer_idx].add(pos)
                        except:
                            pass

        attempts = 0
        max_attempts = target * 10

        while counter["link"] < target and attempts < max_attempts:
            attempts += 1

            # Pick a random layer
            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            tiles = layer_tiles[layer_idx]
            linked_targets = linked_targets_per_layer[layer_idx]

            # Pick a random tile
            positions = list(tiles.keys())
            if not positions:
                continue

            pos1 = random.choice(positions)
            tile_data1 = tiles[pos1]

            # Skip if not valid
            if not isinstance(tile_data1, list) or len(tile_data1) < 2:
                continue
            if tile_data1[0] in self.GOAL_TYPES or tile_data1[1]:
                continue

            # Source tile must not be a link target already
            if pos1 in linked_targets:
                continue

            # Parse position (format is col_row = x_y)
            try:
                col1, row1 = map(int, pos1.split('_'))
            except:
                continue

            # CRITICAL: Check if any adjacent tile already has a link attribute
            # This prevents link tiles from being adjacent to each other
            adjacent_positions = [
                f"{col1}_{row1 - 1}",  # North
                f"{col1}_{row1 + 1}",  # South
                f"{col1 - 1}_{row1}",  # West
                f"{col1 + 1}_{row1}",  # East
            ]
            has_adjacent_link = False
            for adj_pos in adjacent_positions:
                if adj_pos in tiles:
                    adj_tile = tiles[adj_pos]
                    if isinstance(adj_tile, list) and len(adj_tile) >= 2:
                        adj_attr = adj_tile[1]
                        if adj_attr and adj_attr.startswith("link_"):
                            has_adjacent_link = True
                            break
            if has_adjacent_link:
                continue

            # Try to find a valid partner in one of 4 directions
            directions = [
                ("link_n", col1, row1 - 1),  # North (up = row-1)
                ("link_s", col1, row1 + 1),  # South (down = row+1)
                ("link_w", col1 - 1, row1),  # West (left = col-1)
                ("link_e", col1 + 1, row1),  # East (right = col+1)
            ]
            random.shuffle(directions)

            valid_link = False
            for link_type, col2, row2 in directions:
                pos2 = f"{col2}_{row2}"

                # RULE 1: Partner tile MUST exist
                if pos2 not in tiles:
                    continue

                # CRITICAL: Target must NOT already be a link target
                if pos2 in linked_targets:
                    continue

                tile_data2 = tiles[pos2]
                if not isinstance(tile_data2, list) or len(tile_data2) < 2:
                    continue

                # Skip goal tiles
                if tile_data2[0] in self.GOAL_TYPES:
                    continue

                # CRITICAL: Target tile must NOT have any attribute
                # This ensures only one tile in the pair has link attribute
                if tile_data2[1]:
                    logger.debug(f"[LINK] Skipping {pos1} -> {pos2}: target has attribute '{tile_data2[1]}'")
                    continue

                # CRITICAL: Explicitly reject chain, ice, grass, and other links on target
                # Defensive double-check
                BLOCKING_GIMMICKS = {"chain", "ice", "ice_1", "ice_2", "ice_3", "grass"}
                target_attr = tile_data2[1]
                if target_attr in BLOCKING_GIMMICKS:
                    logger.warning(f"[LINK] BLOCKED: {pos1} -> {pos2} would create link->blocking gimmick")
                    continue
                # CRITICAL: Target must NOT be a link source (prevents bidirectional links)
                if target_attr and target_attr.startswith("link_"):
                    logger.warning(f"[LINK] BLOCKED: {pos1} -> {pos2} target is already a link source '{target_attr}'")
                    continue

                # Valid link found - assign the link type to ONLY the source tile
                tile_data1[1] = link_type
                counter["link"] += 1  # Count as 1 link (not 2)

                # Mark both source and target as linked (cannot be targeted by another link)
                linked_targets.add(pos1)
                linked_targets.add(pos2)
                valid_link = True
                break

            if valid_link:
                pass  # Successfully added link pair

        return level

    def _link_pair_has_clearable_neighbor(
        self, tiles: Dict, pos1: str, pos2: str,
        row1: int, col1: int, row2: int, col2: int
    ) -> bool:
        """
        Check if at least one tile in the link pair has a clearable neighbor.
        A clearable neighbor is a tile without obstacle attribute (or frog only).
        The link partner itself doesn't count as a clearable neighbor.
        """
        # Get all neighbors for both tiles (excluding each other)
        neighbors1 = [
            (row1+1, col1), (row1-1, col1), (row1, col1+1), (row1, col1-1)
        ]
        neighbors2 = [
            (row2+1, col2), (row2-1, col2), (row2, col2+1), (row2, col2-1)
        ]

        # Check neighbors of tile 1 (excluding pos2)
        for nrow, ncol in neighbors1:
            npos = f"{nrow}_{ncol}"
            if npos == pos2:
                continue
            if npos in tiles:
                ndata = tiles[npos]
                if (isinstance(ndata, list) and len(ndata) >= 2 and
                    (not ndata[1] or ndata[1] == "frog") and
                    ndata[0] not in self.GOAL_TYPES):
                    return True

        # Check neighbors of tile 2 (excluding pos1)
        for nrow, ncol in neighbors2:
            npos = f"{nrow}_{ncol}"
            if npos == pos1:
                continue
            if npos in tiles:
                ndata = tiles[npos]
                if (isinstance(ndata, list) and len(ndata) >= 2 and
                    (not ndata[1] or ndata[1] == "frog") and
                    ndata[0] not in self.GOAL_TYPES):
                    return True

        return False

    def _add_goals(
        self, level: Dict[str, Any], params: GenerationParams, strict_mode: bool = False
    ) -> Dict[str, Any]:
        """Add goal tiles to the level.

        In strict mode (when layer_tile_configs is specified), goal tiles REPLACE
        existing tiles rather than being added, to maintain exact tile counts.

        Direction rules for goals:
        - craft_s / stack_s: outputs tiles downward (row+1), cannot be at bottom row
        - craft_n / stack_n: outputs tiles upward (row-1), cannot be at top row
        - craft_e / stack_e: outputs tiles rightward (col+1), cannot be at rightmost column
        - craft_w / stack_w: outputs tiles leftward (col-1), cannot be at leftmost column

        Stack additional rule: output position must not overlap with existing tiles
        """
        # Use None check instead of falsy check to allow empty list
        # Fixed layout levels (2, 3) are early tutorial levels without craft/stack goals
        is_fixed_layout_level = params.level_number in (1, 2, 3)
        if is_fixed_layout_level:
            goals = params.goals if params.goals is not None else []
        else:
            goals = params.goals if params.goals is not None else [{"type": "craft_s", "count": 3}]

        # If goals is empty list, skip adding goals
        if not goals:
            return level

        # PATTERN MODE: Check if pattern positions should be preserved
        preserve_pattern = level.get("_preserve_pattern", False)
        pattern_locked_positions = level.get("_pattern_locked_positions", set())

        # Find the topmost active layer
        num_layers = level.get("layer", 8)
        top_layer_idx = None

        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                top_layer_idx = i
                break

        if top_layer_idx is None:
            return level

        layer_key = f"layer_{top_layer_idx}"
        tiles = level[layer_key]["tiles"]

        # Find the bottom row positions for goals
        cols = int(level[layer_key]["col"])
        rows = int(level[layer_key]["row"])

        def get_output_direction(goal_type: str) -> tuple:
            """Get output direction offset (col_offset, row_offset) for goal type."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                return (0, 1)   # output downward
            elif direction == 'n':
                return (0, -1)  # output upward
            elif direction == 'e':
                return (1, 0)   # output rightward
            elif direction == 'w':
                return (-1, 0)  # output leftward
            return (0, 1)  # default: south

        def has_adjacent_gimmick(col: int, row: int, gimmick_types: List[str]) -> bool:
            """Check if any adjacent position (4-way) has specified gimmicks.

            Chain and grass gimmicks need adjacent tiles to be cleared.
            Placing craft/stack next to them would block the clearing mechanism.
            """
            adjacent_offsets = [(0, 1), (0, -1), (1, 0), (-1, 0)]  # 4-way adjacency

            for dc, dr in adjacent_offsets:
                adj_col, adj_row = col + dc, row + dr
                if adj_col < 0 or adj_col >= cols or adj_row < 0 or adj_row >= rows:
                    continue

                adj_pos = f"{adj_col}_{adj_row}"

                # Check ALL layers for gimmicks at adjacent position
                for i in range(num_layers):
                    layer_key_i = f"layer_{i}"
                    layer_tiles = level.get(layer_key_i, {}).get("tiles", {})
                    if adj_pos in layer_tiles:
                        tile_data = layer_tiles[adj_pos]
                        if isinstance(tile_data, list) and len(tile_data) > 1:
                            attribute = tile_data[1] or ""
                            # Check for chain or grass gimmicks
                            for gimmick in gimmick_types:
                                if attribute == gimmick or attribute.startswith(f"{gimmick}_"):
                                    return True
            return False

        def is_valid_goal_position(col: int, row: int, goal_type: str) -> bool:
            """Check if position is valid for goal considering output direction.

            Rules for craft/stack goals:
            1. Output position must be within bounds
            2. Output position must be empty across ALL layers (both craft and stack)
            3. Goal position must NOT be adjacent to chain/grass gimmicks
               (chain/grass need adjacent tiles cleared, craft/stack blocks this)

            NOTE: Goal position having tiles in lower layers is handled by clearing them
            during placement.
            """
            col_off, row_off = get_output_direction(goal_type)
            output_col = col + col_off
            output_row = row + row_off

            # Check output position is within bounds
            if output_col < 0 or output_col >= cols:
                return False
            if output_row < 0 or output_row >= rows:
                return False

            # For BOTH craft AND stack goals, output position must not overlap with existing tiles
            # CRITICAL: Check ALL layers, not just current layer
            # Both craft and stack spawn tiles at output position, which would conflict with any existing tile
            if goal_type.startswith("stack") or goal_type.startswith("craft"):
                output_pos = f"{output_col}_{output_row}"
                # Check ALL layers for existing tiles at output position
                for i in range(num_layers):
                    layer_key_i = f"layer_{i}"
                    layer_tiles = level.get(layer_key_i, {}).get("tiles", {})
                    if output_pos in layer_tiles:
                        return False

                # CRITICAL: Craft/Stack must NOT be adjacent to chain or grass gimmicks
                # Chain/grass need adjacent tiles cleared to be removed.
                # Craft/stack tiles are permanent until goal is met, blocking clearance.
                if has_adjacent_gimmick(col, row, ["chain", "grass"]):
                    return False

                # Also check output position - don't output next to chain/grass
                if has_adjacent_gimmick(output_col, output_row, ["chain", "grass"]):
                    return False

            return True

        def get_preferred_row_for_direction(goal_type: str) -> int:
            """Get preferred starting row based on goal direction."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                # South: prefer upper rows (not bottom row)
                return 0
            elif direction == 'n':
                # North: prefer lower rows (not top row)
                return rows - 1
            else:
                # East/West: prefer bottom row
                return rows - 1

        def get_row_search_order(goal_type: str) -> range:
            """Get row search order based on goal direction."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                # South: search from top to bottom-1
                return range(0, rows - 1)
            elif direction == 'n':
                # North: search from bottom to top+1
                return range(rows - 1, 0, -1)
            else:
                # East/West: search from bottom to top
                return range(rows - 1, -1, -1)

        # In strict mode, goals are ADDED (not replacing existing tiles)
        # Goal tiles contain inner tiles, so:
        # - Visual tiles = config tiles + num_goals
        # - Actual tiles = config tiles + goal_inner_tiles
        # Example: 21+21 config + craft(3) = 42 visual + 1 goal = 43 visual, 42 + 3 = 45 actual

        # Find available positions for goals (positions not already occupied)
        center_col = cols // 2
        center_row = rows // 2
        # PATTERN MODE: Force symmetry to "none" to avoid mirror goal placement
        # Patterns are pre-designed shapes - symmetry would distort them
        if preserve_pattern:
            symmetry_mode = "none"
        else:
            symmetry_mode = params.symmetry_mode or "none"
        placed_positions = set()  # Track positions used by goals
        output_positions = set()  # Track output positions of goals
        goal_positions_info = []  # Track (pos, goal_type) for adjacency check

        def is_self_symmetric_position(col: int, row: int) -> bool:
            """Check if position is its own mirror (for placing single goals in symmetric mode)."""
            if symmetry_mode == "horizontal":
                # For horizontal symmetry, only the exact center column(s) work
                # But for even cols, there's no perfect center. Allow near-center.
                mirror_col = cols - 1 - col
                return col == mirror_col  # Only true if col == (cols-1)/2, i.e., odd cols
            elif symmetry_mode == "vertical":
                mirror_row = rows - 1 - row
                return row == mirror_row
            elif symmetry_mode == "both":
                mirror_col = cols - 1 - col
                mirror_row = rows - 1 - row
                return col == mirror_col and row == mirror_row
            return True  # No symmetry, any position works

        def get_mirror_position(col: int, row: int) -> Tuple[int, int]:
            """Get the mirror position for symmetry mode."""
            if symmetry_mode == "horizontal":
                return (cols - 1 - col, row)
            elif symmetry_mode == "vertical":
                return (col, rows - 1 - row)
            elif symmetry_mode == "both":
                return (cols - 1 - col, rows - 1 - row)
            return (col, row)

        def get_mirrored_direction(direction: str) -> str:
            """Get the mirrored goal direction for symmetry mode.

            horizontal symmetry (left-right): e <-> w, n and s stay same
            vertical symmetry (top-bottom): n <-> s, e and w stay same
            """
            if symmetry_mode == "horizontal":
                if direction == 'e':
                    return 'w'
                elif direction == 'w':
                    return 'e'
            elif symmetry_mode == "vertical":
                if direction == 'n':
                    return 's'
                elif direction == 's':
                    return 'n'
            elif symmetry_mode == "both":
                # Mirror both axes
                if direction == 'e':
                    return 'w'
                elif direction == 'w':
                    return 'e'
                elif direction == 'n':
                    return 's'
                elif direction == 's':
                    return 'n'
            return direction

        def get_preferred_columns_for_symmetry() -> List[int]:
            """Get column order that respects symmetry."""
            if symmetry_mode in ("horizontal", "both"):
                # For horizontal symmetry, prefer center column
                # If cols=8, center is between 3 and 4. For even cols, prefer 3 or 4.
                if cols % 2 == 1:
                    # Odd cols: exact center exists
                    return [cols // 2]
                else:
                    # Even cols: no exact center, use the two middle columns
                    # They are at (cols//2 - 1) and (cols//2)
                    # e.g., for cols=8: 3 and 4
                    return [cols // 2 - 1, cols // 2]
            else:
                # No horizontal symmetry constraint
                return list(range(cols))

        def get_adjacent_positions(col: int, row: int) -> set:
            """Get all adjacent positions (including diagonals)."""
            adjacent = set()
            for dc in [-1, 0, 1]:
                for dr in [-1, 0, 1]:
                    if dc == 0 and dr == 0:
                        continue
                    adjacent.add(f"{col + dc}_{row + dr}")
            return adjacent

        def would_face_each_other(pos1: str, type1: str, pos2: str, type2: str) -> bool:
            """Check if two craft tiles would face each other (output into each other)."""
            col1, row1 = map(int, pos1.split("_"))
            col2, row2 = map(int, pos2.split("_"))

            dir1 = type1[-1] if type1.endswith(('_s', '_n', '_e', '_w')) else 's'
            dir2 = type2[-1] if type2.endswith(('_s', '_n', '_e', '_w')) else 's'

            # Get output positions
            offsets = {'s': (0, 1), 'n': (0, -1), 'e': (1, 0), 'w': (-1, 0)}
            out1 = (col1 + offsets[dir1][0], row1 + offsets[dir1][1])
            out2 = (col2 + offsets[dir2][0], row2 + offsets[dir2][1])

            # Check if they face each other (output to each other's position)
            if out1 == (col2, row2) or out2 == (col1, row1):
                return True

            # Check if outputs collide
            if out1 == out2:
                return True

            return False

        def would_craft_stack_conflict(
            try_pos: str, try_type: str,
            existing_goals: List[Tuple[str, str]],
            existing_output_positions: set
        ) -> bool:
            """Check if placing a goal would create craft-stack output conflict.

            Rules:
            - Stack tiles must NOT be placed at craft output positions
            - Craft tiles must NOT output into stack tile positions
            """
            try_col, try_row = map(int, try_pos.split("_"))
            is_try_stack = try_type.startswith("stack_")
            is_try_craft = try_type.startswith("craft_")

            # Get output position for the tile being placed
            try_col_off, try_row_off = get_output_direction(try_type)
            try_output_pos = f"{try_col + try_col_off}_{try_row + try_row_off}"

            for existing_pos, existing_type in existing_goals:
                is_existing_stack = existing_type.startswith("stack_")
                is_existing_craft = existing_type.startswith("craft_")

                existing_col, existing_row = map(int, existing_pos.split("_"))
                existing_col_off, existing_row_off = get_output_direction(existing_type)
                existing_output_pos = f"{existing_col + existing_col_off}_{existing_row + existing_row_off}"

                # Rule 1: Stack tile placed at craft output position
                if is_try_stack and is_existing_craft:
                    if try_pos == existing_output_pos:
                        logger.debug(f"Craft-Stack conflict: Stack {try_pos} at Craft {existing_pos} output")
                        return True

                # Rule 2: Craft tile output into stack position
                if is_try_craft and is_existing_stack:
                    if try_output_pos == existing_pos:
                        logger.debug(f"Craft-Stack conflict: Craft {try_pos} output into Stack {existing_pos}")
                        return True

                # Rule 3: Stack tile output into craft position (blocks craft)
                if is_try_stack and is_existing_craft:
                    if try_output_pos == existing_pos:
                        logger.debug(f"Craft-Stack conflict: Stack {try_pos} output into Craft {existing_pos}")
                        return True

                # Rule 4: Craft tile placed at stack output position
                if is_try_craft and is_existing_stack:
                    if try_pos == existing_output_pos:
                        logger.debug(f"Craft-Stack conflict: Craft {try_pos} at Stack {existing_pos} output")
                        return True

            return False

        for i, goal in enumerate(goals):
            # Handle both old format (type="craft_s") and new format (type="craft", direction="s")
            base_type = goal.get("type", "craft")
            goal_direction = goal.get("direction") or "s"  # Handle None value

            # If type already includes direction suffix, use as-is
            if base_type.endswith(('_s', '_n', '_e', '_w')):
                goal_type = base_type
            else:
                # Combine type and direction
                goal_type = f"{base_type}_{goal_direction}"

            goal_count = max(self.MIN_GOAL_COUNT, goal.get("count", self.MIN_GOAL_COUNT))

            # Calculate preferred column with more spacing between goals
            # For symmetric modes, prefer center columns
            if symmetry_mode in ("horizontal", "both"):
                preferred_cols = get_preferred_columns_for_symmetry()
                target_col = preferred_cols[i % len(preferred_cols)]
            else:
                spacing = 2  # Minimum 2 columns apart
                target_col = center_col - (len(goals) * spacing) // 2 + i * spacing
            target_col = max(0, min(cols - 1, target_col))

            # Find valid position considering direction rules
            pos = None
            row_order = get_row_search_order(goal_type)

            # Build column search order - RANDOMIZED for variety
            if symmetry_mode in ("horizontal", "both"):
                # Start with preferred symmetric columns, then expand outward
                preferred = get_preferred_columns_for_symmetry()
                col_search_order = preferred[:]
                for offset in range(1, cols):
                    for c in preferred:
                        if c - offset >= 0 and (c - offset) not in col_search_order:
                            col_search_order.append(c - offset)
                        if c + offset < cols and (c + offset) not in col_search_order:
                            col_search_order.append(c + offset)
            else:
                # Randomized column search for variety in goal placement
                col_search_order = list(range(cols))
                random.shuffle(col_search_order)

            # Randomize row order while respecting direction constraints
            # (e.g., craft_s can't be at bottom row, craft_n can't be at top row)
            row_order_list = list(row_order)
            random.shuffle(row_order_list)

            # For symmetric modes, goals should REPLACE existing tiles at self-symmetric positions
            # to preserve overall symmetry. For non-symmetric modes, add at new positions.
            # PATTERN MODE: In pattern mode, ALWAYS replace existing tiles (never add new positions)
            use_replacement_mode = symmetry_mode in ("horizontal", "vertical", "both") or preserve_pattern

            # [v15.56] Tutorial 레벨/필수 기믹: 1차 패턴 안에서 시도 → 실패 시 2차 패턴 잠금 해제.
            # 패턴 모양 보존보다 골(=기믹) 배치가 우선이므로 craft/stack 등 필수 골이 항상 배치됨.
            relax_pattern_lock = False

            # Try positions in randomized order
            for try_row in row_order_list:
                for try_col in col_search_order:
                    try_pos = f"{try_col}_{try_row}"

                    # In symmetric mode OR pattern mode: REPLACE existing tiles
                    # In non-symmetric non-pattern mode: ADD at new positions (original behavior)
                    if use_replacement_mode:
                        # For symmetry/pattern preservation: must be an existing tile position
                        if try_pos not in tiles:
                            continue

                        # PATTERN MODE: Prefer positions within locked pattern positions in pass 1.
                        # On fallback pass (relax_pattern_lock), allow any existing tile position.
                        # This ensures tutorial levels (Lv.11/21 craft/stack unlock) always get
                        # the goal tile placed even when pattern shape doesn't accommodate
                        # output direction. Tile is placed slightly outside designed pattern
                        # but the gimmick is guaranteed to be present.
                        if preserve_pattern and pattern_locked_positions and not relax_pattern_lock:
                            if try_pos not in pattern_locked_positions:
                                continue

                        # Check if this is a self-symmetric position OR we can place mirrored goal
                        mirror_col, mirror_row = get_mirror_position(try_col, try_row)
                        mirror_pos = f"{mirror_col}_{mirror_row}"
                        is_self_symmetric = is_self_symmetric_position(try_col, try_row)

                        # If not self-symmetric, check if mirror position is also valid
                        if not is_self_symmetric and symmetry_mode in ("horizontal", "vertical", "both"):
                            # Mirror position must exist and not be used
                            # Also check if mirror position is another goal's output position
                            if mirror_pos not in tiles or mirror_pos in placed_positions or mirror_pos in output_positions:
                                continue
                            # Get mirrored goal type and check validity
                            goal_dir = goal_type[-1]
                            mirrored_dir = get_mirrored_direction(goal_dir)
                            mirrored_goal_type = goal_type[:-1] + mirrored_dir
                            if not is_valid_goal_position(mirror_col, mirror_row, mirrored_goal_type):
                                continue

                        # Must not be already used by another goal
                        if try_pos in placed_positions:
                            continue
                    else:
                        # Original behavior: add at new positions
                        if try_pos in tiles or try_pos in placed_positions:
                            continue

                    # CRITICAL: Position must not be another goal's output position
                    # This prevents goals from being placed where other goals output tiles
                    # which would cause facing/collision issues
                    if try_pos in output_positions:
                        continue

                    # Check if this position is valid for the goal direction
                    if not is_valid_goal_position(try_col, try_row, goal_type):
                        continue

                    # Get output position for this goal
                    col_off, row_off = get_output_direction(goal_type)
                    output_pos = f"{try_col + col_off}_{try_row + row_off}"

                    # Check output position is not occupied by goals
                    if output_pos in placed_positions or output_pos in output_positions:
                        continue
                    # For replacement mode, output can overlap existing tiles (they'll be cleared)
                    # For non-replacement mode, output should not overlap existing tiles
                    if not use_replacement_mode and output_pos in tiles:
                        continue

                    # Check no adjacent to existing goals (minimum 1 cell gap)
                    adjacent = get_adjacent_positions(try_col, try_row)
                    if adjacent & placed_positions:
                        continue

                    # Check output position adjacency
                    output_adjacent = get_adjacent_positions(try_col + col_off, try_row + row_off)
                    if output_adjacent & output_positions:
                        continue

                    # Check not facing any existing goal
                    facing_conflict = False
                    for existing_pos, existing_type in goal_positions_info:
                        if would_face_each_other(try_pos, goal_type, existing_pos, existing_type):
                            facing_conflict = True
                            break
                    if facing_conflict:
                        continue

                    # Check craft-stack output conflict
                    # (stack tile at craft output position or craft output into stack position)
                    if would_craft_stack_conflict(try_pos, goal_type, goal_positions_info, output_positions):
                        continue

                    pos = try_pos
                    break
                if pos:
                    break

            # [v15.56/v15.57] 골 배치 실패 0% 보장 — 다단계 fallback.
            #   1st pass (위쪽 inner loop): 패턴 안에서만 시도 (모양 보존)
            #   2nd pass (아래): 패턴 잠금 해제 + ADD 모드 (패턴 외부 빈 자리)
            #   3rd pass (사용자 제안): 기존 일반 타일을 craft/stack으로 직접 치환
            #     - 일반 타일(t1~t15) 위치 중 출구 방향이 grid 안인 곳 선택
            #     - 출구 위치에 다른 타일이 있으면 제거하고 골 출구 공간 확보
            #     - 일반 타일 1개 제거 → craft/stack 박스로 치환 (내부 4개)
            #     - FINAL_REPAIR가 타입 카운트 정합성 보정
            if pos is None and preserve_pattern and pattern_locked_positions:
                relax_pattern_lock = True
                logger.warning(f"[_add_goals_pass2] 1st failed for {goal_type}, retrying with pattern_lock relaxed (locked_pos_count={len(pattern_locked_positions)}, tile_count={len(tiles)})")
                for try_row in row_order_list:
                    for try_col in col_search_order:
                        try_pos = f"{try_col}_{try_row}"
                        # ADD 모드: 빈 위치(아직 타일 없음) 우선, 단 placed_positions/output_positions 충돌 금지
                        if try_pos in placed_positions or try_pos in output_positions:
                            continue
                        # [고립 방지] preserve 모드: 클러스터에 4-인접한 빈칸만 허용 → 골이 유닛에 붙음.
                        # 인접 자리 없으면 pos=None 유지 → pass3가 클러스터 내부 타일 대체로 처리(연결 유지).
                        if preserve_pattern and not any(
                            f"{try_col + dx}_{try_row + dy}" in tiles
                            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                        ):
                            continue
                        # [출력칸 자연확보] preserve 모드는 4방향 모두 시도 → 자연히 빈 출력칸 있는
                        # 방향 채택. 클리어(=하위타일 제거→floating) 없이 연결 배치.
                        base_g2 = goal_type[:-2] if goal_type.endswith(('_s', '_n', '_e', '_w')) else goal_type
                        cur_d = goal_type[-1] if goal_type.endswith(('_s', '_n', '_e', '_w')) else 's'
                        dirs_try = [cur_d] + [d for d in ('s', 'n', 'e', 'w') if d != cur_d] if preserve_pattern else [cur_d]
                        chosen_type = None
                        for _d in dirs_try:
                            cand_type = f"{base_g2}_{_d}"
                            if not is_valid_goal_position(try_col, try_row, cand_type):
                                continue
                            c_off, r_off = get_output_direction(cand_type)
                            out_p = f"{try_col + c_off}_{try_row + r_off}"
                            if out_p in placed_positions or out_p in output_positions or out_p in tiles:
                                continue
                            if get_adjacent_positions(try_col, try_row) & placed_positions:
                                continue
                            if get_adjacent_positions(try_col + c_off, try_row + r_off) & output_positions:
                                continue
                            if any(would_face_each_other(try_pos, cand_type, ep, et) for ep, et in goal_positions_info):
                                continue
                            if would_craft_stack_conflict(try_pos, cand_type, goal_positions_info, output_positions):
                                continue
                            chosen_type = cand_type
                            break
                        if chosen_type is None:
                            continue
                        goal_type = chosen_type
                        pos = try_pos
                        logger.warning(f"[_add_goals_pass2] Found new position {pos} for {goal_type} (adjacent, no-clear)")
                        break
                    if pos:
                        break

            # [v15.57] 3rd pass — 강제 치환 (사용자 요청: 절대 누락 금지).
            # 일반 타일(t1~t15) 위치를 골 박스로 직접 치환. 출구 자리도 비워서 확보.
            # 패턴 모양은 약간 변형되지만 craft/stack 기믹은 100% 포함됨을 보장.
            if pos is None:
                logger.warning(f"[_add_goals_pass3] 2nd failed for {goal_type}, FORCING tile replacement")
                # 모든 4 방향 시도 (s, n, e, w 순)
                base_g = goal_type[:-2] if goal_type.endswith(('_s', '_n', '_e', '_w')) else goal_type
                direction_priority = [goal_type[-1] if goal_type.endswith(('_s', '_n', '_e', '_w')) else 's']
                for d in ['s', 'n', 'e', 'w']:
                    if d not in direction_priority:
                        direction_priority.append(d)

                # 일반 타일 위치 후보 — 모든 레이어에서 t1~t15 타일 위치만
                regular_positions = []
                for li in range(num_layers):
                    lk = f"layer_{li}"
                    ltiles = level.get(lk, {}).get("tiles", {})
                    for p, td in ltiles.items():
                        if isinstance(td, list) and td and isinstance(td[0], str):
                            tt = td[0]
                            if tt.startswith('t') and tt[1:].isdigit() and tt != 't0':
                                regular_positions.append((li, p))

                # top 레이어부터 우선 (top_layer_idx 기준)
                regular_positions.sort(key=lambda x: -x[0])

                replaced = False
                for try_dir in direction_priority:
                    if replaced:
                        break
                    forced_goal_type = f"{base_g}_{try_dir}"
                    fcol_off, frow_off = get_output_direction(forced_goal_type)
                    for li, try_pos in regular_positions:
                        if li != top_layer_idx:
                            continue  # top 레이어 우선만 고려
                        try:
                            tx, ty = map(int, try_pos.split("_"))
                        except ValueError:
                            continue
                        # 출구 위치가 grid 안에 있어야 함
                        ox, oy = tx + fcol_off, ty + frow_off
                        if ox < 0 or ox >= cols or oy < 0 or oy >= rows:
                            continue
                        # 자기 자신 이미 다른 골 사용중이면 skip
                        if try_pos in placed_positions or try_pos in output_positions:
                            continue
                        # 인접 골 충돌 검사 (완화 — 마지막 fallback이라 일부 룰 무시)
                        # craft-stack 충돌만 최소한 보존
                        if would_craft_stack_conflict(try_pos, forced_goal_type, goal_positions_info, output_positions):
                            continue
                        # 출구 위치 강제 비우기 — 모든 레이어에서 (oy_pos) 제거
                        output_pos_str = f"{ox}_{oy}"
                        if output_pos_str in placed_positions or output_pos_str in output_positions:
                            continue
                        for li_clear in range(num_layers):
                            lk = f"layer_{li_clear}"
                            ct = level.get(lk, {}).get("tiles", {})
                            if output_pos_str in ct:
                                del ct[output_pos_str]
                                level[lk]["num"] = str(len(ct))
                                logger.warning(f"[_add_goals_pass3] Cleared {lk} @{output_pos_str} for goal output")

                        pos = try_pos
                        goal_type = forced_goal_type  # 방향 갱신
                        logger.warning(f"[_add_goals_pass3] FORCED placement at {pos} dir={try_dir} (replacing {tiles.get(pos, '?')[0] if pos in tiles else 'unknown'})")
                        replaced = True
                        break

            if pos:
                p_col, p_row = map(int, pos.split("_"))
                col_off, row_off = get_output_direction(goal_type)
                output_pos = f"{p_col + col_off}_{p_row + row_off}"

                placed_positions.add(pos)
                output_positions.add(output_pos)
                goal_positions_info.append((pos, goal_type))

                self._place_goal_tile(tiles, pos, goal_type, goal_count)

                # CRITICAL: Clear tiles from lower layers at goal position
                # This ensures the goal is visible and not visually confusing
                # PATTERN MODE: Skip clearing to preserve pattern shape - goals are on top layer anyway
                if not preserve_pattern:
                    for i in range(top_layer_idx):
                        lower_layer_key = f"layer_{i}"
                        lower_tiles = level.get(lower_layer_key, {}).get("tiles", {})
                        if pos in lower_tiles:
                            del lower_tiles[pos]
                            level[lower_layer_key]["num"] = str(len(lower_tiles))
                            logger.debug(f"[_add_goals] Cleared tile at {lower_layer_key}:{pos} for goal visibility")

                # CRITICAL: Clear tiles from ALL layers at output position
                # Stack/Craft goals spawn tiles at output position, so existing tiles would block them
                # PATTERN MODE: Skip clearing to preserve pattern shape - output tiles will overlap
                if not preserve_pattern:
                    for i in range(level.get("layer", 8)):
                        check_layer_key = f"layer_{i}"
                        check_tiles = level.get(check_layer_key, {}).get("tiles", {})
                        if output_pos in check_tiles:
                            del check_tiles[output_pos]
                            level[check_layer_key]["num"] = str(len(check_tiles))
                            logger.debug(f"[_add_goals] Cleared tile at {check_layer_key}:{output_pos} for goal output")

                # CRITICAL: For stack goals, clear additional positions in stack direction
                # Stack tiles are offset by 0.1 per stacked tile in the output direction
                # [연구 근거] townpop sp_template: interval_stackOffSetY = 0.1f
                # Example: stack_e with count=6 extends 5*0.1=0.5 units east (half tile)
                # Example: stack_e with count=11 extends 10*0.1=1.0 unit east (exactly 1 tile)
                # Example: stack_e with count=12 extends 11*0.1=1.1 units east (need to block 2nd tile)
                #
                # Stacked tiles extend from stack position by (count-1) * 0.1 tiles
                # Output position is 1 tile from stack (already cleared)
                # Need to clear positions BEYOND output if extension > 1.0
                #
                # Formula: additional_positions_to_clear = ceil(max_offset) - 1
                # - count <= 11: max_offset <= 1.0, ceil=1, 1-1=0 → no extra clearing
                # - count 12-21: max_offset 1.1-2.0, ceil=2, 2-1=1 → clear 1 extra
                # - count 22+: max_offset > 2.0, ceil >= 3, 3-1=2 → clear 2 extra
                if goal_type.startswith("stack_"):
                    import math
                    STACK_OFFSET = 0.1  # 타일당 오프셋 (타운팝 기준)
                    # Calculate how far stacked tiles extend from stack position
                    max_offset = (goal_count - 1) * STACK_OFFSET

                    # Positions beyond output to clear = ceil(max_offset) - 1
                    # Output position (1 tile from stack) is already cleared
                    additional_blocked = max(0, math.ceil(max_offset) - 1)

                    if additional_blocked > 0:
                        logger.debug(f"[_add_goals] Stack {goal_type} count={goal_count}, offset={max_offset:.1f}: blocking {additional_blocked} additional positions beyond output")

                        # Clear tiles in the extended stack direction (positions beyond output)
                        for ext_idx in range(1, additional_blocked + 1):
                            # ext_idx=1: 2 tiles from stack (1 beyond output)
                            # ext_idx=2: 3 tiles from stack (2 beyond output)
                            ext_col = p_col + col_off * (ext_idx + 1)
                            ext_row = p_row + row_off * (ext_idx + 1)
                            ext_pos = f"{ext_col}_{ext_row}"

                            # Check bounds
                            if ext_col < 0 or ext_col >= cols or ext_row < 0 or ext_row >= rows:
                                continue

                            # Clear from all layers
                            # PATTERN MODE: Skip clearing to preserve pattern shape
                            if not preserve_pattern:
                                for i in range(level.get("layer", 8)):
                                    check_layer_key = f"layer_{i}"
                                    check_tiles = level.get(check_layer_key, {}).get("tiles", {})
                                    if ext_pos in check_tiles:
                                        del check_tiles[ext_pos]
                                        level[check_layer_key]["num"] = str(len(check_tiles))
                                        logger.debug(f"[_add_goals] Cleared tile at {check_layer_key}:{ext_pos} for stack extension")

                            # Also add to output_positions to prevent other goals from using it
                            output_positions.add(ext_pos)

                # In symmetric mode, also place mirrored goal if not self-symmetric position
                # PATTERN MODE: Skip mirror placement if only using pattern mode (no symmetry)
                if use_replacement_mode and symmetry_mode in ("horizontal", "vertical", "both") and not is_self_symmetric_position(p_col, p_row):
                    mirror_col, mirror_row = get_mirror_position(p_col, p_row)
                    mirror_pos = f"{mirror_col}_{mirror_row}"

                    # Get mirrored goal type
                    goal_dir = goal_type[-1]
                    mirrored_dir = get_mirrored_direction(goal_dir)
                    mirrored_goal_type = goal_type[:-1] + mirrored_dir

                    # Check if mirrored goal would face the original goal or any existing goals
                    mirror_facing_conflict = False
                    # Check against original goal
                    if would_face_each_other(mirror_pos, mirrored_goal_type, pos, goal_type):
                        mirror_facing_conflict = True
                    # Check against all existing goals
                    if not mirror_facing_conflict:
                        for existing_pos, existing_type in goal_positions_info:
                            if would_face_each_other(mirror_pos, mirrored_goal_type, existing_pos, existing_type):
                                mirror_facing_conflict = True
                                break

                    # Check craft-stack conflict for mirrored goal
                    mirror_craft_stack_conflict = would_craft_stack_conflict(
                        mirror_pos, mirrored_goal_type, goal_positions_info, output_positions
                    )

                    # Only place mirrored goal if no facing conflict and no craft-stack conflict
                    if not mirror_facing_conflict and not mirror_craft_stack_conflict:
                        # Calculate mirrored output position
                        mirror_col_off, mirror_row_off = get_output_direction(mirrored_goal_type)
                        mirror_output_pos = f"{mirror_col + mirror_col_off}_{mirror_row + mirror_row_off}"

                        # Place mirrored goal
                        placed_positions.add(mirror_pos)
                        output_positions.add(mirror_output_pos)
                        goal_positions_info.append((mirror_pos, mirrored_goal_type))

                        self._place_goal_tile(tiles, mirror_pos, mirrored_goal_type, goal_count)

                        # CRITICAL: Clear tiles from lower layers at mirrored goal position
                        # PATTERN MODE: Skip clearing to preserve pattern shape
                        if not preserve_pattern:
                            for i in range(top_layer_idx):
                                lower_layer_key = f"layer_{i}"
                                lower_tiles = level.get(lower_layer_key, {}).get("tiles", {})
                                if mirror_pos in lower_tiles:
                                    del lower_tiles[mirror_pos]
                                    level[lower_layer_key]["num"] = str(len(lower_tiles))
                                    logger.debug(f"[_add_goals] Cleared tile at {lower_layer_key}:{mirror_pos} for mirrored goal visibility")

                        # CRITICAL: Clear tiles from ALL layers at mirrored output position
                        # PATTERN MODE: Skip clearing to preserve pattern shape
                        if not preserve_pattern:
                            for i in range(level.get("layer", 8)):
                                check_layer_key = f"layer_{i}"
                                check_tiles = level.get(check_layer_key, {}).get("tiles", {})
                                if mirror_output_pos in check_tiles:
                                    del check_tiles[mirror_output_pos]
                                    level[check_layer_key]["num"] = str(len(check_tiles))
                                    logger.debug(f"[_add_goals] Cleared tile at {check_layer_key}:{mirror_output_pos} for mirrored goal output")
            else:
                logger.warning(f"[_add_goals] Could not find position for {goal_type}")

        # Update tile count
        level[layer_key]["num"] = str(len(tiles))

        # Set goalCount for the level - ONLY include goals that were actually placed
        # Build goalCount from successfully placed tiles, not from requested goals
        goalCount = {}
        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) > 0:
                tile_type = tile_data[0]
                # Check if it's a craft/stack goal tile
                if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                    # Extract count from tile_data[2]
                    tile_count = self.MIN_GOAL_COUNT  # Default to minimum
                    if len(tile_data) > 2:
                        extra = tile_data[2]
                        if isinstance(extra, list) and len(extra) > 0:
                            tile_count = max(self.MIN_GOAL_COUNT, int(extra[0]) if extra[0] else self.MIN_GOAL_COUNT)
                        elif isinstance(extra, (int, float)):
                            tile_count = max(self.MIN_GOAL_COUNT, int(extra))
                    goalCount[tile_type] = goalCount.get(tile_type, 0) + tile_count

        # Warn if not all requested goals were placed
        requested_goals = set()
        for goal in goals:
            base_type = goal.get("type", "craft")
            direction = goal.get("direction") or "s"
            if base_type.endswith(('_s', '_n', '_e', '_w')):
                full_goal_type = base_type
            else:
                full_goal_type = f"{base_type}_{direction}"
            requested_goals.add(full_goal_type)

        placed_goals = set(goalCount.keys())
        missing_goals = requested_goals - placed_goals
        if missing_goals:
            logger.warning(f"Could not place some goals: {missing_goals}. Placed: {placed_goals}")

        level["goalCount"] = goalCount

        return level

    def _adjust_difficulty(
        self, level: Dict[str, Any], target: float, max_tiles: Optional[int] = None, params: Optional["GenerationParams"] = None, tutorial_gimmick: Optional[str] = None
    ) -> Dict[str, Any]:
        """Adjust level to match target difficulty within tolerance.

        Args:
            level: The level to adjust
            target: Target difficulty (0.0-1.0)
            max_tiles: If specified, don't add tiles beyond this count
            params: Generation parameters (for symmetry awareness)
            tutorial_gimmick: Tutorial gimmick type to preserve during adjustment
        """
        analyzer = get_analyzer()
        target_score = target * 100
        symmetry_mode = params.symmetry_mode if params else "none"

        # Track if we've hit tile limit - need to use obstacles
        tiles_maxed_out = False
        # Track consecutive no-change iterations
        no_change_count = 0
        last_score = None

        for iteration in range(self.MAX_ADJUSTMENT_ITERATIONS):
            report = analyzer.analyze(level)
            current_score = report.score
            diff = target_score - current_score

            if abs(diff) <= self.DIFFICULTY_TOLERANCE:
                break

            # Check if score isn't changing (stuck)
            if last_score is not None and abs(current_score - last_score) < 0.1:
                no_change_count += 1
                if no_change_count >= 3:
                    # Score is stuck, need to use obstacles to increase further
                    tiles_maxed_out = True
            else:
                no_change_count = 0
            last_score = current_score

            if diff > 0:
                # Need to increase difficulty
                # If max_tiles is set, check if we can add more tiles
                if max_tiles is not None:
                    current_tiles = sum(
                        len(level.get(f"layer_{i}", {}).get("tiles", {}))
                        for i in range(level.get("layer", 8))
                    )
                    if current_tiles >= max_tiles:
                        tiles_maxed_out = True

                # Pass target difficulty to enable aggressive obstacle addition for high targets
                level = self._increase_difficulty(level, params, tiles_maxed_out=tiles_maxed_out, target_difficulty=target)
            else:
                # Need to decrease difficulty - pass target for aggressive reduction at low targets
                # Also pass tutorial_gimmick to preserve it during obstacle removal
                level = self._decrease_difficulty(level, params, target_difficulty=target, tutorial_gimmick=tutorial_gimmick)

        return level

    def _increase_difficulty(self, level: Dict[str, Any], params: Optional["GenerationParams"] = None, tiles_maxed_out: bool = False, target_difficulty: float = 0.5) -> Dict[str, Any]:
        """Apply a random modification to increase difficulty.

        When tiles are maxed out or target difficulty is high, adds obstacles
        (chain, frog, ice) to increase difficulty. This allows generating B, C, D grade levels.

        Strategy based on target_difficulty:
        - target < 0.4 (S/A grade): Primarily add tiles
        - target >= 0.4 (B grade): Mix of tiles and obstacles (50% chance each)
        - target >= 0.6 (C grade): Primarily obstacles, multiple per iteration
        - target >= 0.8 (D grade): Aggressive obstacle addition, activate more layers

        CRITICAL: When pattern_index is specified (special shape levels like Heart, Star),
        we MUST NOT add/remove tiles as it would break the pattern shape.
        Only gimmicks (obstacles) are used for difficulty adjustment in this case.
        """
        symmetry_mode = params.symmetry_mode if params else "none"

        # CRITICAL: Check if pattern_index is specified (special shape level)
        # When pattern_index is set, we preserve tile positions and only adjust via gimmicks
        pattern_index = getattr(params, 'pattern_index', None) if params else None
        # 패턴 보호는 level 자체의 플래그도 인정한다. 저장된 프로덕션 레벨은 pattern_index를
        # 잃어버린 채(_preserve_pattern만 보유) 제자리 재튜닝되므로, 이 플래그를 존중해야
        # 난이도 조정이 패턴 타일을 제거하지 않는다.
        preserve_pattern_shape = pattern_index is not None or bool(level.get("_preserve_pattern"))

        # Check gimmick_intensity - if 0, don't add obstacles, only add tiles
        # For values between 0 and 1, use as probability multiplier
        gimmick_intensity = getattr(params, 'gimmick_intensity', 1.0) if params else 1.0

        # Also check obstacle_types - if empty list, no obstacles should be added
        # This respects the gimmick unlock system where certain levels have no unlocked gimmicks
        obstacle_types = getattr(params, 'obstacle_types', None) if params else None
        obstacles_disabled = gimmick_intensity <= 0 or (obstacle_types is not None and len(obstacle_types) == 0)

        # Obstacle addition actions - filter by allowed obstacle types
        # NOTE: link, grass, bomb, curtain, teleport are NOT in this list because they:
        # - Are added during initial generation (_add_obstacles)
        # - Require special placement rules (pairs, neighbors, etc.)
        # - Should not be randomly added during difficulty adjustment
        all_obstacle_actions = {
            "chain": self._add_chain_to_tile,
            "frog": self._add_frog_to_tile,
            "ice": self._add_ice_to_tile,
            "unknown": self._add_unknown_to_tile,
        }
        # Core obstacles that are always available for difficulty adjustment
        # These are the most reliable obstacles that can be added to any tile
        core_obstacles = ["chain", "ice"]

        # If obstacle_types is specified, only allow those actions
        if obstacle_types is not None and len(obstacle_types) > 0:
            obstacle_actions = [all_obstacle_actions[t] for t in obstacle_types if t in all_obstacle_actions]
            # For high difficulty targets (C/D grade), always include core obstacles as fallback
            # This ensures we can always increase difficulty even if selected gimmicks don't overlap
            if target_difficulty >= 0.6:
                for core_obs in core_obstacles:
                    if core_obs not in obstacle_types and core_obs in all_obstacle_actions:
                        obstacle_actions.append(all_obstacle_actions[core_obs])
        else:
            obstacle_actions = list(all_obstacle_actions.values())

        # If no valid obstacle actions available, mark obstacles as disabled for this adjustment
        if not obstacle_actions:
            obstacles_disabled = True

        # Helper: check if we should add obstacles based on gimmick_intensity probability
        def should_add_obstacle() -> bool:
            if obstacles_disabled:
                return False
            if gimmick_intensity >= 1.0:
                return True
            # For values 0 < gimmick_intensity < 1, use as probability
            return random.random() < gimmick_intensity

        # For low gimmick_intensity (< 0.5), prefer adding tiles over obstacles
        # This ensures early levels have minimal gimmicks
        prefer_tiles_over_obstacles = gimmick_intensity < 0.5

        # Tile Buster style: Very conservative gimmick addition
        # - Primary difficulty comes from tiles and layers, not obstacles
        # - Obstacles are added very sparingly (10-20% chance)
        # - Skip obstacle addition if already at target gimmick percentage

        # Count current gimmicks to cap at ~15% of total tiles
        total_tiles = 0
        total_gimmicks = 0
        for layer_idx in range(15):  # [v16] 레이어 상한 상향(가드로 안전)
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            total_tiles += len(tiles)
            for tile_data in tiles.values():
                if len(tile_data) > 1 and tile_data[1]:
                    total_gimmicks += 1

        # Cap gimmicks based on target difficulty
        # Low difficulty (S/A): 15% cap
        # Medium difficulty (B): 25% cap
        # High difficulty (C/D): 40% cap
        if target_difficulty >= 0.6:
            max_gimmick_ratio = 0.40
        elif target_difficulty >= 0.4:
            max_gimmick_ratio = 0.25
        else:
            max_gimmick_ratio = 0.15
        max_gimmicks = int(total_tiles * max_gimmick_ratio)
        gimmicks_capped = total_gimmicks >= max_gimmicks

        # Helper: Try to add an obstacle, trying multiple types if one fails
        def try_add_obstacle() -> Tuple[Dict[str, Any], bool]:
            """Try to add obstacle, return (level, success)."""
            if not obstacle_actions or gimmicks_capped:
                return level, False
            # Shuffle actions to try different types
            shuffled_actions = obstacle_actions.copy()
            random.shuffle(shuffled_actions)
            for action in shuffled_actions:
                old_gimmick_count = total_gimmicks
                new_level = action(level)
                # Check if obstacle was actually added
                new_gimmick_count = 0
                for layer_idx in range(15):  # [v16] 레이어 상한 상향(가드로 안전)
                    layer_key = f"layer_{layer_idx}"
                    tiles = new_level.get(layer_key, {}).get("tiles", {})
                    for tile_data in tiles.values():
                        if len(tile_data) > 1 and tile_data[1]:
                            new_gimmick_count += 1
                if new_gimmick_count > old_gimmick_count:
                    return new_level, True
            return level, False

        # For symmetric patterns, we MUST use obstacles since tiles can't be added
        # Be more aggressive with obstacle addition
        is_symmetric = symmetry_mode != "none"

        # CRITICAL: When pattern_index is specified, preserve tile positions
        # Adding random tiles would break the visual pattern shape (Heart, Star, etc.)
        # Use obstacles ONLY for difficulty adjustment
        if preserve_pattern_shape:
            # Only adjust via gimmicks - try multiple times to add obstacles
            if not gimmicks_capped and should_add_obstacle():
                for _ in range(5):  # Try up to 5 times for pattern preservation
                    new_level, success = try_add_obstacle()
                    if success:
                        return new_level
            # If obstacles capped or can't add, return unchanged
            # Pattern shape takes priority over exact difficulty matching
            return level

        # D grade (target >= 0.8): Add obstacles aggressively
        # For D grade, we STRONGLY prefer obstacles over tiles
        if target_difficulty >= 0.8:
            # Only add tiles if gimmick_intensity is low (tutorial-style levels)
            if prefer_tiles_over_obstacles and not tiles_maxed_out and not is_symmetric:
                return self._add_tile_to_layer(level)
            # For high difficulty, always try to add obstacles - try multiple times
            if not gimmicks_capped and should_add_obstacle():
                for _ in range(3):  # Try up to 3 times
                    new_level, success = try_add_obstacle()
                    if success:
                        return new_level
            # Fall back to tiles only if obstacles completely failed AND not tiles maxed
            if not is_symmetric and not tiles_maxed_out:
                # But prefer obstacle retry for high difficulty
                if not gimmicks_capped and random.random() < 0.5:
                    new_level, success = try_add_obstacle()
                    if success:
                        return new_level
                return self._add_tile_to_layer(level)
            # For symmetric patterns, keep trying obstacles
            if is_symmetric and not gimmicks_capped:
                new_level, success = try_add_obstacle()
                if success:
                    return new_level

        # C grade (target >= 0.6): Add obstacles frequently
        if target_difficulty >= 0.6:
            if prefer_tiles_over_obstacles and not tiles_maxed_out and not is_symmetric:
                return self._add_tile_to_layer(level)
            # C grade: 70% obstacle, 30% tile
            if not gimmicks_capped and random.random() < 0.70 and should_add_obstacle():
                new_level, success = try_add_obstacle()
                if success:
                    return new_level
            # Fall back to tiles if not symmetric
            if not is_symmetric and not tiles_maxed_out:
                return self._add_tile_to_layer(level)

        # B grade (target >= 0.4): Add obstacles moderately
        if target_difficulty >= 0.4:
            if prefer_tiles_over_obstacles and not tiles_maxed_out and not is_symmetric:
                return self._add_tile_to_layer(level)
            # B grade: 50% obstacle, 50% tile
            if not gimmicks_capped and random.random() < 0.50 and should_add_obstacle():
                new_level, success = try_add_obstacle()
                if success:
                    return new_level
            # Fall back to tiles if not symmetric
            if not is_symmetric and not tiles_maxed_out:
                return self._add_tile_to_layer(level)

        # For symmetric patterns, ALWAYS try to add obstacles (this is our only option)
        # We rely on obstacles to adjust difficulty since tiles can't be added
        if is_symmetric and not gimmicks_capped and should_add_obstacle():
            # Try multiple times to find a valid obstacle placement
            for _ in range(3):
                new_level, success = try_add_obstacle()
                if success:
                    return new_level
            # No valid placement found, return unchanged
            return level

        # If tiles are maxed out, try obstacles (50% chance)
        if tiles_maxed_out and not gimmicks_capped and random.random() < 0.5 and should_add_obstacle():
            new_level, success = try_add_obstacle()
            if success:
                return new_level

        # Default: add tiles (for S/A grade targets and non-symmetric patterns)
        return self._add_tile_to_layer(level)

    def _decrease_difficulty(self, level: Dict[str, Any], params: Optional["GenerationParams"] = None, target_difficulty: float = 0.5, tutorial_gimmick: Optional[str] = None) -> Dict[str, Any]:
        """Apply a random modification to decrease difficulty.

        Strategy based on target_difficulty:
        - target >= 0.4: Remove 1 tile (gentle reduction)
        - target >= 0.2 (A grade): Remove 1-2 tiles, possibly remove obstacle
        - target < 0.2 (S grade): Aggressively remove 2-3 tiles and obstacles

        CRITICAL: When pattern_index is specified (special shape levels like Heart, Star),
        we MUST NOT remove tiles as it would break the pattern shape.
        Only gimmicks (obstacles) are removed for difficulty adjustment in this case.

        Args:
            level: Level data
            params: Generation parameters
            target_difficulty: Target difficulty score
            tutorial_gimmick: Tutorial gimmick type to preserve (don't remove this type)
        """
        symmetry_mode = params.symmetry_mode if params else "none"

        # CRITICAL: Check if pattern_index is specified (special shape level)
        # When pattern_index is set, we preserve tile positions and only adjust via gimmicks
        pattern_index = getattr(params, 'pattern_index', None) if params else None
        # 패턴 보호는 level 자체의 플래그도 인정(제자리 재튜닝되는 저장 레벨 대응).
        preserve_pattern_shape = pattern_index is not None or bool(level.get("_preserve_pattern"))

        # For symmetric patterns OR pattern-specified levels, skip random tile removal to preserve shape
        if symmetry_mode != "none" or preserve_pattern_shape:
            # Only remove obstacles, don't remove tiles (to preserve pattern shape)
            if preserve_pattern_shape:
                # Try to remove obstacles multiple times for more aggressive reduction
                num_attempts = 3 if target_difficulty < 0.2 else 2 if target_difficulty < 0.4 else 1
                for _ in range(num_attempts):
                    level = self._remove_random_obstacle(level, tutorial_gimmick=tutorial_gimmick)
            return level

        # S grade (target < 0.2): Very aggressive - remove multiple tiles and obstacles
        if target_difficulty < 0.2:
            # Remove 2-3 tiles per iteration
            num_removals = random.randint(2, 3)
            for _ in range(num_removals):
                level = self._remove_tile_from_layer(level)
            # Also try to remove obstacles if any exist (but preserve tutorial gimmick)
            if random.random() < 0.7:
                level = self._remove_random_obstacle(level, tutorial_gimmick=tutorial_gimmick)
            return level

        # A grade (target < 0.4): Moderate reduction
        if target_difficulty < 0.4:
            # Remove 1-2 tiles
            num_removals = random.randint(1, 2)
            for _ in range(num_removals):
                level = self._remove_tile_from_layer(level)
            # Sometimes remove obstacles (but preserve tutorial gimmick)
            if random.random() < 0.3:
                level = self._remove_random_obstacle(level, tutorial_gimmick=tutorial_gimmick)
            return level

        # Default: gentle reduction - remove 1 tile
        return self._remove_tile_from_layer(level)

    def _remove_random_obstacle(self, level: Dict[str, Any], tutorial_gimmick: Optional[str] = None) -> Dict[str, Any]:
        """Remove a random obstacle (chain, frog, ice) from the level.

        Args:
            level: Level data
            tutorial_gimmick: Tutorial gimmick type to preserve (don't remove this type)
        """
        num_layers = level.get("layer", 8)

        # Find all tiles with obstacles (excluding tutorial gimmick type)
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (isinstance(tile_data, list) and len(tile_data) >= 2
                    and tile_data[1] in ["chain", "frog", "ice"]):
                    # Skip if this is the tutorial gimmick type
                    if tutorial_gimmick and tile_data[1] == tutorial_gimmick:
                        continue
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = ""

        return level

    def _add_chain_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add chain attribute to a random tile.
        RULE: Chain tiles MUST have at least one clearable neighbor on LEFT or RIGHT (same row).
        The neighbor must NOT be covered by upper layers (so it can be selected first).
        Chain is released by clearing adjacent tiles on the left or right side.
        """
        num_layers = level.get("layer", 8)

        # Collect candidates: tiles without attributes that have a clearable LEFT or RIGHT neighbor
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                # Skip if already has attribute or is goal tile
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue
                if tile_data[1] or tile_data[0] in self.GOAL_TYPES:
                    continue

                # Check if has clearable neighbor on LEFT or RIGHT
                try:
                    # Position format is "col_row" (x_y)
                    col, row = map(int, pos.split('_'))
                except:
                    continue

                # Only check LEFT (col-1) and RIGHT (col+1) neighbors (on screen)
                neighbors = [
                    (col-1, row),  # Left (on screen)
                    (col+1, row),  # Right (on screen)
                ]

                has_clearable_neighbor = False
                for ncol, nrow in neighbors:
                    npos = f"{ncol}_{nrow}"
                    if npos in tiles:
                        ndata = tiles[npos]
                        # Clearable = no obstacle or frog only
                        if (isinstance(ndata, list) and len(ndata) >= 2 and
                            (not ndata[1] or ndata[1] == "frog") and
                            ndata[0] not in self.GOAL_TYPES):
                            # CRITICAL: Neighbor must NOT be covered by upper layers
                            if not self._is_position_covered_by_upper(level, i, ncol, nrow):
                                has_clearable_neighbor = True
                                break

                if has_clearable_neighbor:
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = "chain"

        return level

    def _add_frog_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add frog attribute to a random tile.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.

        [연구 근거] Tile Busters 스타일: 개구리는 레벨당 최대 3개로 제한
        """
        MAX_FROGS_PER_LEVEL = 3

        # Count existing frogs
        num_layers = level.get("layer", 8)
        current_frog_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and len(tile_data) >= 2 and tile_data[1] == "frog":
                    current_frog_count += 1

        # Don't add if already at max
        if current_frog_count >= MAX_FROGS_PER_LEVEL:
            logger.debug(f"[FROG] _add_frog_to_tile: Skipping - already at max {MAX_FROGS_PER_LEVEL} frogs")
            return level

        # Collect all tiles without attributes that are NOT covered by upper layers
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and not tile_data[1]
                    and tile_data[0] not in self.GOAL_TYPES
                ):
                    # Check if position is covered by upper layers
                    try:
                        col, row = map(int, pos.split('_'))
                        if not self._is_position_covered_by_upper(level, i, col, row):
                            candidates.append((layer_key, pos))
                    except:
                        continue

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = "frog"
            logger.debug(f"[FROG] _add_frog_to_tile: Added frog at {layer_key}/{pos}")

        return level

    def _add_ice_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add ice attribute to a random tile.

        Ice tiles require 2 taps to clear: first tap removes ice, second tap clears tile.
        Ice is a good difficulty modifier as it doesn't require neighbor rules like chain.
        """
        return self._add_attribute_to_tile(level, "ice")

    def _add_unknown_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add unknown attribute to a random tile.

        RULE: Unknown tiles should be placed on tiles that ARE covered by upper layers.
        This is because the unknown effect only works when the tile is hidden by upper tiles.
        When upper tiles are removed, the tile type becomes visible.
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles without attributes that ARE covered by upper layers
        candidates = []
        for i in range(num_layers - 1):  # Exclude top layer (no upper layers to cover)
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and not tile_data[1]
                    and tile_data[0] not in self.GOAL_TYPES
                ):
                    try:
                        col, row = map(int, pos.split('_'))
                        # Only add to tiles covered by upper layers
                        if self._is_position_covered_by_upper(level, i, col, row):
                            candidates.append((layer_key, pos))
                    except:
                        continue

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = "unknown"

        return level

    def _add_attribute_to_tile(
        self, level: Dict[str, Any], attribute: str
    ) -> Dict[str, Any]:
        """Add an attribute to a random tile without one."""
        num_layers = level.get("layer", 8)

        # Collect all tiles without attributes
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and not tile_data[1]
                    and tile_data[0] not in self.GOAL_TYPES
                ):
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = attribute

        return level

    def _remove_chain_from_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove chain attribute from a random tile."""
        return self._remove_attribute_from_tile(level, "chain")

    def _remove_frog_from_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove frog attribute from a random tile."""
        return self._remove_attribute_from_tile(level, "frog")

    def _validate_and_fix_frog_positions(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and fix frog positions to ensure they are not covered by upper layers.

        RULE: Frogs must be immediately selectable when the level spawns.
        This function should be called AFTER all tile modifications to ensure no frog
        is covered by tiles added in later generation steps.

        Covered frogs are removed (attribute cleared) as there's no safe place to move them
        that wouldn't violate placement rules or break tile count divisibility.
        """
        # [방어] 템플릿 계열 level_json 은 layer 가 문자열("5")인 경우가 있다(타운팝 임포트분).
        # int 변환 없이 range() 에 넣으면 TypeError 로 파이프라인 전체가 죽는다.
        try:
            num_layers = int(level.get("layer", 8) or 8)
        except (TypeError, ValueError):
            num_layers = 8
        removed_count = 0

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                # Check if this is a frog tile
                if tile_data[1] != "frog":
                    continue

                # Check if covered by upper layers
                try:
                    col, row = map(int, pos.split('_'))
                    if self._is_position_covered_by_upper(level, layer_idx, col, row):
                        # Remove frog attribute from covered tile
                        tile_data[1] = ""
                        removed_count += 1
                        logger.warning(
                            f"[FROG FIX] Removed frog at {layer_key}/{pos} - covered by upper layer"
                        )
                except Exception as e:
                    logger.warning(f"[FROG FIX] Error checking position {pos}: {e}")
                    continue

        if removed_count > 0:
            logger.info(f"[FROG FIX] Removed {removed_count} covered frogs from level")

        return level

    def _remove_attribute_from_tile(
        self, level: Dict[str, Any], attribute: str
    ) -> Dict[str, Any]:
        """Remove a specific attribute from a random tile."""
        num_layers = level.get("layer", 8)

        # Find tiles with the attribute
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and tile_data[1] == attribute
                ):
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = ""

        return level

    def _add_tile_to_layer(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new tile to a random layer that already has tiles.

        Uses tiles that respect the level's useTileCount setting.
        Only adds to layers that already have tiles (respects user's layer config).
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 15)

        # Collect existing tile types from level to match user's selection
        # IMPORTANT: Exclude goal types (craft_s, stack_s, etc.) - they should only be added via _add_goals
        existing_tile_types = set()
        for i in range(num_layers):
            layer_tiles = level.get(f"layer_{i}", {}).get("tiles", {})
            for tile_data in layer_tiles.values():
                if isinstance(tile_data, list) and tile_data:
                    tile_type = tile_data[0]
                    # Exclude goal types and craft/stack tiles
                    if not (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        existing_tile_types.add(tile_type)

        # Use existing tile types if available, otherwise fall back to t1~t{useTileCount}
        if existing_tile_types:
            valid_tile_types = list(existing_tile_types)
        else:
            valid_tile_types = [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Find layers that already have tiles (respect user's layer config)
        active_layer_indices = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                active_layer_indices.append(i)

        if not active_layer_indices:
            return level

        # Find a layer with tiles but with available positions
        for _ in range(10):  # Try up to 10 times
            # Only use layers that already have tiles
            layer_idx = random.choice(active_layer_indices)
            layer_key = f"layer_{layer_idx}"
            layer_data = level.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            cols = int(layer_data.get("col", 7))
            rows = int(layer_data.get("row", 7))

            # Find available position
            for _ in range(20):
                x = random.randint(0, cols - 1)
                y = random.randint(0, rows - 1)
                pos = f"{x}_{y}"

                if pos not in tiles:
                    tile_type = random.choice(valid_tile_types)
                    self._place_tile(tiles, pos, tile_type, "")
                    level[layer_key]["num"] = str(len(tiles))
                    return level

        return level

    def _remove_tile_from_layer(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a tile from a random layer.

        IMPORTANT: Do not remove tiles that are neighbors of chain/link/grass obstacles,
        as this would make them impossible to clear.
        """
        num_layers = level.get("layer", 8)

        # Find layers with tiles that can be removed
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                # Don't remove goal tiles
                if not isinstance(tile_data, list) or tile_data[0] in self.GOAL_TYPES:
                    continue

                # Don't remove tiles with obstacles
                if len(tile_data) >= 2 and tile_data[1]:
                    continue

                # Check if this tile is a neighbor of a chain (left or right on screen)
                # If removed, the chain would have no clearable neighbor
                try:
                    # Position format is "col_row" (x_y)
                    col, row = map(int, pos.split('_'))
                except:
                    continue

                is_critical_neighbor = False

                # Check if left neighbor (col-1) is chain (on screen)
                left_pos = f"{col-1}_{row}"
                if left_pos in tiles:
                    left_data = tiles[left_pos]
                    if isinstance(left_data, list) and len(left_data) >= 2 and left_data[1] == "chain":
                        # Check if chain has other clearable neighbor (left side = col-2)
                        other_side = f"{col-2}_{row}"
                        if other_side not in tiles:
                            # This tile is the only clearable neighbor for the chain
                            is_critical_neighbor = True

                # Check if right neighbor (col+1) is chain (on screen)
                right_pos = f"{col+1}_{row}"
                if right_pos in tiles:
                    right_data = tiles[right_pos]
                    if isinstance(right_data, list) and len(right_data) >= 2 and right_data[1] == "chain":
                        # Check if chain has other clearable neighbor (right side = col+2)
                        other_side = f"{col+2}_{row}"
                        if other_side not in tiles:
                            # This tile is the only clearable neighbor for the chain
                            is_critical_neighbor = True

                if not is_critical_neighbor:
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            del level[layer_key]["tiles"][pos]
            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        return level

    def _increase_goal_count(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Increase the count of a random goal."""
        return self._modify_goal_count(level, 1)

    def _decrease_goal_count(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Decrease the count of a random goal."""
        return self._modify_goal_count(level, -1)

    def _modify_goal_count(self, level: Dict[str, Any], delta: int) -> Dict[str, Any]:
        """Modify a goal's count by delta."""
        num_layers = level.get("layer", 8)

        # Find goal tiles
        goals = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 3
                    and tile_data[0] in self.GOAL_TYPES
                ):
                    goals.append((layer_key, pos))

        if goals:
            layer_key, pos = random.choice(goals)
            tile_data = level[layer_key]["tiles"][pos]

            if len(tile_data) >= 3 and isinstance(tile_data[2], list):
                # Minimum 3 tiles for craft/stack gimmicks (match-3 game rule)
                new_count = max(3, tile_data[2][0] + delta)
                tile_data[2][0] = new_count

        return level

    def _fix_goal_counts(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Fix any goals with count below MIN_GOAL_COUNT and ensure total is divisible by 3.

        This is a safety net to ensure all craft/stack goals have at least
        MIN_GOAL_COUNT tiles, regardless of how they were created.
        Also ensures total matchable tiles (regular + goal internal) is divisible by 3.
        """
        num_layers = level.get("layer", 8)
        fixed_count = 0

        # Step 1: Fix all goals to minimum count
        goal_tiles: List[Tuple[int, str, list]] = []  # (layer_idx, pos, tile_data)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 1:
                    continue

                tile_type = tile_data[0]
                if not isinstance(tile_type, str):
                    continue

                # Check if it's a goal tile
                if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                    # Ensure tile_data has the count array
                    if len(tile_data) < 3:
                        # Add count array if missing
                        while len(tile_data) < 2:
                            tile_data.append("")
                        tile_data.append([self.MIN_GOAL_COUNT])
                        fixed_count += 1
                        logger.debug(f"[_fix_goal_counts] Added missing count at {layer_key}:{pos}")
                    elif isinstance(tile_data[2], list) and len(tile_data[2]) > 0:
                        current_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                        if current_count < self.MIN_GOAL_COUNT:
                            tile_data[2][0] = self.MIN_GOAL_COUNT
                            fixed_count += 1
                            logger.warning(f"[_fix_goal_counts] Fixed count {current_count} -> {self.MIN_GOAL_COUNT} at {layer_key}:{pos}")
                    else:
                        # Count array is empty or invalid
                        tile_data[2] = [self.MIN_GOAL_COUNT]
                        fixed_count += 1
                        logger.debug(f"[_fix_goal_counts] Fixed invalid count array at {layer_key}:{pos}")

                    goal_tiles.append((i, pos, tile_data))

        # Step 2: Count total matchable tiles
        total_matchable = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        # Count internal tiles only, not the box itself
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            total_matchable += internal_count
                    else:
                        total_matchable += 1

        # Step 3: Ensure goal internal tiles (t0) are divisible by 3
        # CRITICAL: Goal internal tiles become t0 when output, so t0 must be divisible by 3
        t0_count = 0
        for layer_idx, pos, tile_data in goal_tiles:
            if isinstance(tile_data[2], list) and tile_data[2]:
                t0_count += int(tile_data[2][0])

        t0_remainder = t0_count % 3
        # PATTERN MODE: Skip goal adjustment here - let _ensure_tile_count_divisible_by_3 handle it
        # This prevents duplicate adjustments that cause goal counts to balloon
        preserve_pattern = level.get("_preserve_pattern", False)
        already_fixed = level.get("_goal_divisibility_fixed", False)

        if t0_remainder != 0 and goal_tiles and not preserve_pattern and not already_fixed:
            # Need to add (3 - remainder) internal tiles to make t0 divisible by 3
            tiles_to_add_t0 = 3 - t0_remainder  # 1 or 2

            # Add to goal counts (prefer spreading across multiple goals)
            goal_idx = 0
            while tiles_to_add_t0 > 0 and goal_tiles:
                layer_idx, pos, tile_data = goal_tiles[goal_idx % len(goal_tiles)]
                if isinstance(tile_data[2], list) and tile_data[2]:
                    tile_data[2][0] = int(tile_data[2][0]) + 1
                    tiles_to_add_t0 -= 1
                    total_matchable += 1
                    t0_count += 1
                    logger.info(f"[_fix_goal_counts] Added +1 to goal at layer_{layer_idx}:{pos} for t0 divisibility")
                goal_idx += 1
                # Safety: prevent infinite loop
                if goal_idx > len(goal_tiles) * 3:
                    break

            level["_goal_divisibility_fixed"] = True  # Mark as fixed
            logger.info(f"[_fix_goal_counts] Adjusted goal internals (t0) to {t0_count} (divisible by 3)")
        elif preserve_pattern:
            logger.debug("[_fix_goal_counts] Pattern mode: skipping goal adjustment (will be handled later)")

        # Step 4: Total divisibility will be handled by _ensure_tile_count_divisible_by_3
        # DO NOT add more to goals here - that would break t0 divisibility
        # If t0 is divisible by 3 and regular tiles are divisible by 3, total will also be divisible by 3

        # Step 4: Recalculate goalCount
        goalCount = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            tile_count = int(tile_data[2][0])
                        else:
                            tile_count = self.MIN_GOAL_COUNT
                        goalCount[tile_type] = goalCount.get(tile_type, 0) + tile_count

        level["goalCount"] = goalCount

        if fixed_count > 0 or t0_remainder != 0:
            logger.info(f"[_fix_goal_counts] Final goalCount: {goalCount}, total matchable: {total_matchable}")

        return level

    def _relocate_tiles_from_goal_outputs(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Relocate tiles from goal (craft/stack) output positions to other valid positions.

        CRITICAL: This must be called AFTER all tile modifications to ensure
        no tiles exist in stack/craft output positions. Stack and craft gimmicks
        spawn tiles at their output positions, so existing tiles would block them.

        Unlike deletion, this function RELOCATES tiles to maintain tile counts.

        Direction rules:
        - craft_s / stack_s: outputs to row+1 (south)
        - craft_n / stack_n: outputs to row-1 (north)
        - craft_e / stack_e: outputs to col+1 (east)
        - craft_w / stack_w: outputs to col-1 (west)
        """
        num_layers = level.get("layer", 8)
        grid_width = level.get("gridWidth", 7)
        grid_height = level.get("gridHeight", 7)

        # PATTERN MODE: Check if pattern positions should be preserved
        preserve_pattern = level.get("_preserve_pattern", False)
        pattern_locked_positions = level.get("_pattern_locked_positions", set())

        # PATTERN MODE: Skip relocation entirely to preserve pattern shape
        # Goal placement in pattern mode already ensures valid positioning
        if preserve_pattern:
            logger.info(f"[_relocate_tiles_from_goal_outputs] Skipping relocation in pattern mode to preserve shape")
            return level

        # Collect all goal output positions (positions that must be clear)
        goal_output_positions = set()
        goal_positions = set()
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or not tile_data:
                    continue
                tile_type = tile_data[0]
                if not (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                    continue

                goal_positions.add(pos)

                # Calculate output position based on direction
                col, row = map(int, pos.split("_"))
                direction = tile_type[-1]
                if direction == 's':
                    output_pos = f"{col}_{row + 1}"
                elif direction == 'n':
                    output_pos = f"{col}_{row - 1}"
                elif direction == 'e':
                    output_pos = f"{col + 1}_{row}"
                elif direction == 'w':
                    output_pos = f"{col - 1}_{row}"
                else:
                    continue

                goal_output_positions.add(output_pos)

        if not goal_output_positions:
            return level

        # Collect tiles that need to be relocated
        tiles_to_relocate = []  # [(layer_idx, pos, tile_data)]
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos in list(tiles.keys()):
                if pos in goal_output_positions:
                    tile_data = tiles[pos]
                    # Only relocate regular tiles, not goals themselves
                    if isinstance(tile_data, list) and tile_data:
                        tile_type = tile_data[0]
                        if not (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                            tiles_to_relocate.append((i, pos, tile_data))

        if not tiles_to_relocate:
            return level

        # Remove tiles from their current positions
        for layer_idx, pos, _ in tiles_to_relocate:
            layer_key = f"layer_{layer_idx}"
            del level[layer_key]["tiles"][pos]
            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        # Find valid positions for relocation
        relocated_count = 0
        for layer_idx, old_pos, tile_data in tiles_to_relocate:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]

            # Collect occupied positions in this layer
            occupied_positions = set(tiles.keys())

            # Find a valid new position
            new_pos = None
            # [OOB_FIX] 대상 층의 실제 헤더로 스캔 (phantom gridWidth 기본7 → OOB 방지)
            lw = int(level[layer_key].get("col", grid_width) or grid_width)
            lh = int(level[layer_key].get("row", grid_height) or grid_height)
            for row in range(lh):
                for col in range(lw):
                    candidate_pos = f"{col}_{row}"
                    # Must not be occupied, must not be goal output position, must not be goal position
                    if (candidate_pos not in occupied_positions and
                        candidate_pos not in goal_output_positions and
                        candidate_pos not in goal_positions):
                        new_pos = candidate_pos
                        break
                if new_pos:
                    break

            if new_pos:
                # Place tile at new position
                tiles[new_pos] = tile_data
                level[layer_key]["num"] = str(len(tiles))
                relocated_count += 1
                logger.debug(f"[_relocate_tiles_from_goal_outputs] Relocated {layer_key}:{old_pos} → {new_pos}")
            else:
                # If no valid position found, try another layer
                for alt_layer_idx in range(num_layers):
                    if alt_layer_idx == layer_idx:
                        continue
                    alt_layer_key = f"layer_{alt_layer_idx}"
                    alt_tiles = level.get(alt_layer_key, {}).get("tiles", {})
                    alt_occupied = set(alt_tiles.keys())

                    # [OOB_FIX] 대체 층의 실제 헤더로 스캔
                    alt_lw = int(level.get(alt_layer_key, {}).get("col", grid_width) or grid_width)
                    alt_lh = int(level.get(alt_layer_key, {}).get("row", grid_height) or grid_height)
                    for row in range(alt_lh):
                        for col in range(alt_lw):
                            candidate_pos = f"{col}_{row}"
                            if (candidate_pos not in alt_occupied and
                                candidate_pos not in goal_output_positions and
                                candidate_pos not in goal_positions):
                                new_pos = candidate_pos
                                break
                        if new_pos:
                            break

                    if new_pos:
                        alt_tiles[new_pos] = tile_data
                        level[alt_layer_key]["num"] = str(len(alt_tiles))
                        relocated_count += 1
                        logger.debug(f"[_relocate_tiles_from_goal_outputs] Relocated {layer_key}:{old_pos} → {alt_layer_key}:{new_pos}")
                        break

                if not new_pos:
                    # Last resort: log warning (tile count will be off)
                    logger.warning(f"[_relocate_tiles_from_goal_outputs] Could not relocate tile from {layer_key}:{old_pos}")

        if relocated_count > 0:
            logger.info(f"[_relocate_tiles_from_goal_outputs] Relocated {relocated_count} tiles from goal output positions")

        return level

    def _redistribute_tile_types_for_divisibility(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """
        PATTERN MODE ONLY: Redistribute tile types to ensure each type count is divisible by 3.

        This function NEVER adds or removes tiles - it only changes tile types.
        This preserves the visual pattern shape while ensuring match-3 playability.

        Algorithm:
        1. Count each tile type
        2. Identify types with remainder (1 or 2)
        3. Redistribute by changing tile types:
           - remainder=1: change 1 tile to a type with remainder=2 (or 2 tiles to other types)
           - remainder=2: change 2 tiles to other types (or 1 tile to remainder=1 type)
        4. Positions are NEVER modified
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 15)

        # Collect valid tile types - INCLUDE t0!
        valid_tile_types = [f"t{i}" for i in range(0, use_tile_count + 1)]

        # Step 0: Count goal internal tiles (they contribute to t0 count)
        goal_internal_t0_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 2:
                    tile_type = tile_data[0]
                    if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if isinstance(tile_data[2], list) and tile_data[2]:
                            goal_internal_t0_count += int(tile_data[2][0]) if tile_data[2][0] else 0

        # Step 1: Count each tile type and collect positions
        type_counts: Dict[str, int] = {}
        type_positions: Dict[str, List[Tuple[int, str]]] = {}  # type -> [(layer_idx, pos)]

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Skip goal tiles
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        continue
                    type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                    if tile_type not in type_positions:
                        type_positions[tile_type] = []
                    type_positions[tile_type].append((i, pos))

        if not type_counts:
            return level

        # Add goal internal t0 count to type_counts for calculation
        # (but we can't change goal tiles, so we adjust grid t0 instead)
        effective_t0_count = type_counts.get("t0", 0) + goal_internal_t0_count
        t0_adjustment_needed = effective_t0_count % 3
        if t0_adjustment_needed != 0:
            logger.debug(f"[REDISTRIBUTE] t0 grid={type_counts.get('t0', 0)} + goal_internal={goal_internal_t0_count} = {effective_t0_count} (remainder={t0_adjustment_needed})")

        # Step 2: Identify types with remainder
        # CRITICAL: For t0, consider goal internal tiles when calculating remainder
        rem1_types = []  # types with count % 3 == 1 (need to change 1 or add 2)
        rem2_types = []  # types with count % 3 == 2 (need to change 2 or add 1)

        for tile_type, count in type_counts.items():
            # For t0, use effective count (grid + goal internal)
            if tile_type == "t0" and goal_internal_t0_count > 0:
                remainder = effective_t0_count % 3
            else:
                remainder = count % 3
            if remainder == 1:
                rem1_types.append(tile_type)
            elif remainder == 2:
                rem2_types.append(tile_type)

        # Step 3: Redistribute by pairing rem1 with rem2
        # Strategy: Move 1 tile from rem1 type to rem2 type
        # This makes rem1 type have count%3==0 and rem2 type have count%3==0
        while rem1_types and rem2_types:
            from_type = rem1_types.pop()
            to_type = rem2_types.pop()

            # Change one tile from from_type to to_type
            if type_positions.get(from_type):
                layer_idx, pos = type_positions[from_type].pop()
                layer_key = f"layer_{layer_idx}"
                if pos in level[layer_key]["tiles"]:
                    old_data = level[layer_key]["tiles"][pos]
                    level[layer_key]["tiles"][pos] = [to_type, old_data[1] if len(old_data) > 1 else ""]

                    # Update counts
                    type_counts[from_type] -= 1
                    type_counts[to_type] = type_counts.get(to_type, 0) + 1

                    # Now both should be divisible by 3

        # Step 3.5: CRITICAL FIX - Handle multiple rem1 types by pairing them
        # If we have rem1=[A,B,C] (3 types each with remainder 1):
        # - Move 2 tiles from A to B: A becomes rem2, B becomes rem0
        # - Move 1 tile from C to A: C becomes rem0, A becomes rem0
        max_rem1_iterations = 10
        for _ in range(max_rem1_iterations):
            # Recalculate remainders
            rem1_types = [t for t, c in type_counts.items() if c % 3 == 1 and type_positions.get(t)]
            rem2_types = [t for t, c in type_counts.items() if c % 3 == 2 and type_positions.get(t)]

            if not rem1_types and not rem2_types:
                break

            # First, try to pair rem1 with rem2
            if rem1_types and rem2_types:
                from_type = rem1_types[0]
                to_type = rem2_types[0]
                if type_positions.get(from_type):
                    layer_idx, pos = type_positions[from_type].pop()
                    layer_key = f"layer_{layer_idx}"
                    if pos in level[layer_key]["tiles"]:
                        old_data = level[layer_key]["tiles"][pos]
                        level[layer_key]["tiles"][pos] = [to_type, old_data[1] if len(old_data) > 1 else ""]
                        type_counts[from_type] -= 1
                        type_counts[to_type] = type_counts.get(to_type, 0) + 1
                        if to_type not in type_positions:
                            type_positions[to_type] = []
                        type_positions[to_type].append((layer_idx, pos))
                continue

            # If we have 2+ rem1 types, move 2 tiles from one to another
            # A(rem1) gives 2 to B(rem1): A becomes rem2, B becomes rem0
            if len(rem1_types) >= 2:
                type_a = rem1_types[0]
                type_b = rem1_types[1]
                if len(type_positions.get(type_a, [])) >= 2:
                    moved = 0
                    while moved < 2 and type_positions.get(type_a):
                        layer_idx, pos = type_positions[type_a].pop()
                        layer_key = f"layer_{layer_idx}"
                        if pos in level[layer_key]["tiles"]:
                            old_data = level[layer_key]["tiles"][pos]
                            level[layer_key]["tiles"][pos] = [type_b, old_data[1] if len(old_data) > 1 else ""]
                            type_counts[type_a] -= 1
                            type_counts[type_b] = type_counts.get(type_b, 0) + 1
                            if type_b not in type_positions:
                                type_positions[type_b] = []
                            type_positions[type_b].append((layer_idx, pos))
                            moved += 1
                    # type_a: rem1->rem2, type_b: rem1->rem0
                    continue

            # If we have 2+ rem2 types, move 1 tile from one to another
            # A(rem2) gives 1 to B(rem2): A becomes rem1, B becomes rem0
            if len(rem2_types) >= 2:
                type_a = rem2_types[0]
                type_b = rem2_types[1]
                if type_positions.get(type_a):
                    layer_idx, pos = type_positions[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    if pos in level[layer_key]["tiles"]:
                        old_data = level[layer_key]["tiles"][pos]
                        level[layer_key]["tiles"][pos] = [type_b, old_data[1] if len(old_data) > 1 else ""]
                        type_counts[type_a] -= 1
                        type_counts[type_b] = type_counts.get(type_b, 0) + 1
                        if type_b not in type_positions:
                            type_positions[type_b] = []
                        type_positions[type_b].append((layer_idx, pos))
                    # type_a: rem2->rem1, type_b: rem2->rem0
                    continue

            # Single rem1 or rem2 - redistribute to highest count type
            break

        # Recalculate after step 3.5
        rem1_types = [t for t, c in type_counts.items() if c % 3 == 1 and type_positions.get(t)]
        rem2_types = [t for t, c in type_counts.items() if c % 3 == 2 and type_positions.get(t)]

        # Step 4: Handle remaining rem1 types (need to convert 1 tile to get 0 remainder)
        # CRITICAL FIX: Only use existing types with count >= 3 to prevent creating 2-count types
        for from_type in list(rem1_types):  # Use list() to avoid modification during iteration
            if not type_positions.get(from_type):
                continue  # No positions to modify
            # Best target: type with remainder=2 (both become divisible)
            target_type = None
            for t, c in type_counts.items():
                if c % 3 == 2 and t != from_type:  # Removed: t in type_positions
                    target_type = t
                    break

            # Second best: type with count >= 6 and divisible by 3 (can afford to become rem1)
            if not target_type:
                for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                    if c >= 6 and c % 3 == 0 and t != from_type:  # Removed: t in type_positions
                        target_type = t
                        break

            # Third: type with count >= 3 (minimum safe)
            if not target_type:
                for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):  # Highest count first
                    if c >= 3 and t != from_type:  # Removed: t in type_positions
                        target_type = t
                        break

            # Fallback: ANY type that isn't from_type
            if not target_type:
                for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                    if t != from_type:
                        target_type = t
                        break

            if not target_type:
                logger.warning(f"[REDISTRIBUTE] No target for rem1 type {from_type}, skipping")
                continue

            layer_idx, pos = type_positions[from_type].pop()
            layer_key = f"layer_{layer_idx}"
            if pos in level[layer_key]["tiles"]:
                old_data = level[layer_key]["tiles"][pos]
                level[layer_key]["tiles"][pos] = [target_type, old_data[1] if len(old_data) > 1 else ""]
                type_counts[from_type] -= 1
                type_counts[target_type] = type_counts.get(target_type, 0) + 1
                if target_type not in type_positions:
                    type_positions[target_type] = []
                type_positions[target_type].append((layer_idx, pos))
                if from_type in rem1_types:
                    rem1_types.remove(from_type)  # Successfully handled

        # Step 5: Handle remaining rem2 types
        for from_type in list(rem2_types):
            if from_type not in rem2_types:  # Already handled
                continue
            # Best target: type with remainder=1 (both become divisible after transfer)
            target_type = None
            # Recalculate rem1 dynamically
            current_rem1 = [t for t, c in type_counts.items() if c % 3 == 1 and t != from_type]
            for t in current_rem1:
                target_type = t
                break

            if target_type and type_positions.get(from_type) and len(type_positions[from_type]) >= 1:
                # Change 1 tile to pair with rem1
                layer_idx, pos = type_positions[from_type].pop()
                layer_key = f"layer_{layer_idx}"
                if pos in level[layer_key]["tiles"]:
                    old_data = level[layer_key]["tiles"][pos]
                    level[layer_key]["tiles"][pos] = [target_type, old_data[1] if len(old_data) > 1 else ""]
                    type_counts[from_type] -= 1
                    type_counts[target_type] = type_counts.get(target_type, 0) + 1
                    if target_type not in type_positions:
                        type_positions[target_type] = []
                    type_positions[target_type].append((layer_idx, pos))
                    if from_type in rem2_types:
                        rem2_types.remove(from_type)
            elif type_positions.get(from_type) and len(type_positions[from_type]) >= 2:
                # Change 2 tiles to an existing type with high count (to minimize impact)
                # CRITICAL FIX: Don't require type to be in type_positions - just needs high count
                best_target = None
                for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                    if c >= 3 and c % 3 == 0 and t != from_type:
                        best_target = t
                        break
                if not best_target:
                    # Use highest count type as fallback (even if it creates new remainder)
                    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                        if t != from_type and c >= 3:
                            best_target = t
                            break

                if not best_target:
                    logger.warning(f"[REDISTRIBUTE] No safe target for rem2 type {from_type}, skipping")
                    continue

                tiles_changed = 0
                for _ in range(2):
                    if not type_positions.get(from_type):
                        break
                    layer_idx, pos = type_positions[from_type].pop()
                    layer_key = f"layer_{layer_idx}"
                    if pos in level[layer_key]["tiles"]:
                        # Use best_target instead of random.choice
                        old_data = level[layer_key]["tiles"][pos]
                        level[layer_key]["tiles"][pos] = [best_target, old_data[1] if len(old_data) > 1 else ""]
                        type_counts[from_type] -= 1
                        type_counts[best_target] = type_counts.get(best_target, 0) + 1
                        if best_target not in type_positions:
                            type_positions[best_target] = []
                        type_positions[best_target].append((layer_idx, pos))
                        tiles_changed += 1

                if tiles_changed == 2 and from_type in rem2_types:
                    rem2_types.remove(from_type)

        # Final validation and emergency fix loop
        for final_attempt in range(5):  # Max 5 emergency fix attempts
            final_counts: Dict[str, int] = {}
            final_positions: Dict[str, List[Tuple[int, str]]] = {}
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if not tile_type.startswith("craft_") and not tile_type.startswith("stack_") and tile_type not in self.GOAL_TYPES:
                            final_counts[tile_type] = final_counts.get(tile_type, 0) + 1
                            if tile_type not in final_positions:
                                final_positions[tile_type] = []
                            final_positions[tile_type].append((i, pos))

            bad_types = []
            for tile_type, count in final_counts.items():
                # For t0, add goal internal count
                if tile_type == "t0":
                    effective = count + goal_internal_t0_count
                    if effective % 3 != 0:
                        bad_types.append((tile_type, count, effective % 3))
                elif count % 3 != 0:
                    bad_types.append((tile_type, count, count % 3))

            if not bad_types:
                logger.debug(f"[REDISTRIBUTE] Final validation passed - all {len(final_counts)} types divisible by 3")
                break

            # EMERGENCY FIX: Force redistribute remaining bad types
            logger.debug(f"[REDISTRIBUTE] Emergency fix attempt {final_attempt + 1}: {len(bad_types)} bad types")

            for bad_type, bad_count, remainder in bad_types:
                if not final_positions.get(bad_type):
                    continue

                # Find best target: type with count divisible by 3 and highest count
                best_target = None
                for t, c in sorted(final_counts.items(), key=lambda x: -x[1]):
                    if c % 3 == 0 and c >= 3 and t != bad_type:
                        best_target = t
                        break
                # Fallback: any type with count >= 3
                if not best_target:
                    for t, c in sorted(final_counts.items(), key=lambda x: -x[1]):
                        if c >= 3 and t != bad_type:
                            best_target = t
                            break

                if not best_target:
                    continue

                # Move tiles based on remainder
                tiles_to_move = remainder if remainder <= 2 else 3 - remainder
                moved = 0
                while moved < tiles_to_move and final_positions.get(bad_type):
                    layer_idx, pos = final_positions[bad_type].pop()
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        old_data = level[layer_key]["tiles"][pos]
                        level[layer_key]["tiles"][pos] = [best_target, old_data[1] if len(old_data) > 1 else ""]
                        final_counts[bad_type] -= 1
                        final_counts[best_target] = final_counts.get(best_target, 0) + 1
                        moved += 1
                        logger.debug(f"[REDISTRIBUTE_EMERGENCY] Moved tile from {bad_type} to {best_target}")
        else:
            # Still have bad types after all attempts
            remaining_bad = [(t, c) for t, c in final_counts.items() if c % 3 != 0]
            if remaining_bad:
                logger.warning(f"[REDISTRIBUTE] Final validation failed - bad types: {remaining_bad}")

        return level

    def _ensure_tile_count_divisible_by_3(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """
        Ensure EACH tile type count is divisible by 3 for match-3 completion.

        CRITICAL FIX: Not just total count, but EACH TYPE must be divisible by 3!
        Example: If we have 4x t0, 5x t1, 3x t2 (total 12, divisible by 3)
                 But t0=4 (not divisible), t1=5 (not divisible) -> UNPLAYABLE!

        This function adjusts tile types to ensure each has count divisible by 3.

        Also ensures all tiles are within useTileCount range (t0~t{useTileCount}).

        CRITICAL: First ensures TOTAL matchable tiles is divisible by 3 by adjusting
        craft_s internal tile counts if necessary.

        PATTERN MODE: When _preserve_pattern is True, only redistribute tile types
        without adding or removing any tiles (to preserve visual pattern shape).
        """
        # CRITICAL: Check if pattern mode is active
        # In pattern mode, try redistribution first, but allow deletion if needed for playability
        preserve_pattern = level.get("_preserve_pattern", False)
        if preserve_pattern:
            level = self._redistribute_tile_types_for_divisibility(level, params)
            # Check if redistribution was successful
            num_layers_check = level.get("layer", 8)
            type_counts_check: Dict[str, int] = {}
            for i in range(num_layers_check):
                tiles = level.get(f"layer_{i}", {}).get("tiles", {})
                for tile_data in tiles.values():
                    if isinstance(tile_data, list) and tile_data:
                        tile_type = tile_data[0]
                        if tile_type not in self.GOAL_TYPES and not tile_type.startswith("craft_") and not tile_type.startswith("stack_"):
                            type_counts_check[tile_type] = type_counts_check.get(tile_type, 0) + 1

            bad_types = [(t, c) for t, c in type_counts_check.items() if c % 3 != 0]
            if not bad_types:
                logger.debug("[PATTERN_MODE] Redistribution successful - all types divisible by 3")
                return level
            else:
                logger.warning(f"[PATTERN_MODE] Redistribution failed, bad types: {bad_types}. Continuing to full fix...")
                # Continue to full fix below (allow minimal deletion if needed)

        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 15)

        # Collect existing tile types from level to match user's selection
        existing_tile_types = set()
        for i in range(num_layers):
            layer_tiles = level.get(f"layer_{i}", {}).get("tiles", {})
            for tile_data in layer_tiles.values():
                if isinstance(tile_data, list) and tile_data:
                    tile_type = tile_data[0]
                    if tile_type.startswith("t") and tile_type not in self.GOAL_TYPES:
                        existing_tile_types.add(tile_type)

        # Use existing tile types if available, otherwise fall back to t1~t{useTileCount}
        if existing_tile_types:
            valid_tile_set = existing_tile_types
            valid_tile_types = list(existing_tile_types)
        else:
            valid_tile_set = {f"t{i}" for i in range(1, use_tile_count + 1)}
            valid_tile_types = [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Step 0: Convert out-of-range tiles to valid range
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Skip goal tiles (craft_s, craft_n, craft_e, craft_w, stack_s, etc.)
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        continue
                    # Check if tile type is out of valid range
                    if tile_type.startswith("t") and tile_type not in valid_tile_set:
                        # Convert to a random valid tile type
                        tile_data[0] = random.choice(valid_tile_types)

        # Step 0.5: Ensure TOTAL matchable tiles is divisible by 3
        # This is CRITICAL - if total is not divisible by 3, we can't make all types divisible
        # Count regular tiles on grid + internal tiles in craft/stack
        total_matchable = 0
        goal_tiles_with_internal: List[Tuple[int, str, list]] = []  # (layer_idx, pos, tile_data)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # Count internal tiles for goal tiles (craft/stack)
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            total_matchable += internal_count
                            goal_tiles_with_internal.append((i, pos, tile_data))
                    else:
                        total_matchable += 1

        # Adjust total to be divisible by 3 (NOT modifying goal counts)
        # User-specified goal internal counts should be preserved
        # Strategy: Try to add tiles first, if not possible then remove tiles
        # CRITICAL: For pattern mode, NEVER remove tiles - only add to preserve shape!
        total_remainder = total_matchable % 3
        tiles_were_removed = False  # Track if we removed tiles for total adjustment
        symmetry_mode = params.symmetry_mode or "none"

        if total_remainder != 0:
            cols, rows = params.grid_size

            # First, try to add tiles (3 - remainder tiles needed)
            tiles_to_add = 3 - total_remainder
            added_count = 0

            # PATTERN MODE FIX: When preserve_pattern is True, NEVER delete tiles
            # Priority-based approach to preserve pattern shape:
            # 1. Adjust goal (craft/stack) internal tile count
            # 2. Tile type redistribution (if total already divisible)
            # 3. Add tiles adjacent to pattern (last resort)
            #
            # CRITICAL: Check if already fixed to prevent duplicate adjustments
            if preserve_pattern:
                # Check if goal adjustment was already done
                already_fixed = level.get("_goal_divisibility_fixed", False)
                pattern_fix_success = already_fixed

                # === PRIORITY 1: Adjust goal internal tile count ===
                # This preserves pattern shape 100% by changing goal's internal t0 count
                if goal_tiles_with_internal and not pattern_fix_success:
                    # Need to add (3 - remainder) to make total divisible by 3
                    tiles_to_add_to_goal = 3 - total_remainder
                    goal_idx = 0
                    added_to_goal = 0

                    while added_to_goal < tiles_to_add_to_goal and goal_idx < len(goal_tiles_with_internal) * 3:
                        layer_idx, pos, tile_data = goal_tiles_with_internal[goal_idx % len(goal_tiles_with_internal)]
                        if isinstance(tile_data[2], list) and tile_data[2]:
                            current_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            tile_data[2][0] = current_count + 1
                            added_to_goal += 1
                            total_matchable += 1
                        goal_idx += 1

                    if added_to_goal >= tiles_to_add_to_goal:
                        pattern_fix_success = True
                        level["_goal_divisibility_fixed"] = True  # Mark as fixed
                        logger.info(f"[PATTERN_MODE] Added {added_to_goal} to goal internal tiles for 3-divisibility (shape preserved)")

                        # Update goalCount
                        goalCount = {}
                        for _, _, td in goal_tiles_with_internal:
                            tile_type = td[0]
                            internal_count = int(td[2][0]) if isinstance(td[2], list) and td[2] else 0
                            goalCount[tile_type] = goalCount.get(tile_type, 0) + internal_count
                        level["goalCount"] = goalCount

                # === PRIORITY 2: Tile type redistribution ===
                # If no goal tiles but total is somehow already 3-divisible after redistribution
                # This is handled by _redistribute_tile_types_for_divisibility earlier

                # === PRIORITY 3: [v15.40] 타입 재분배로 해결 (위치 추가 금지) ===
                if not pattern_fix_success:
                    logger.warning("[PATTERN_MODE] No goal tiles available, using type redistribution (no position addition)")
                    # 패턴 형태 보존: 타일 위치를 추가/삭제하지 않고
                    # 나머지 타일을 가장 적은 타입으로 재할당
                    pattern_fix_success = True  # 위치 추가 fallback 차단

                    # Find positions adjacent to existing pattern tiles (to maintain cohesion)
                    def get_adjacent_empty_positions(layer_idx: int) -> List[str]:
                        is_odd_layer = layer_idx % 2 == 1
                        layer_cols = cols if is_odd_layer else cols + 1
                        layer_rows = rows if is_odd_layer else rows + 1
                        layer_tiles = level.get(f"layer_{layer_idx}", {}).get("tiles", {})
                        used = set(layer_tiles.keys())

                        adjacent_empty = []
                        for pos in used:
                            parts = pos.split("_")
                            if len(parts) != 2:
                                continue
                            x, y = int(parts[0]), int(parts[1])
                            # Check 4-directional neighbors
                            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                                nx, ny = x + dx, y + dy
                                if 0 <= nx < layer_cols and 0 <= ny < layer_rows:
                                    neighbor_pos = f"{nx}_{ny}"
                                    if neighbor_pos not in used and neighbor_pos not in adjacent_empty:
                                        adjacent_empty.append(neighbor_pos)
                        return adjacent_empty

                    # Try to add tiles adjacent to existing pattern
                    for i in range(num_layers):
                        if added_count >= tiles_to_add:
                            break
                        layer_key = f"layer_{i}"
                        layer_data = level.get(layer_key, {})
                        tiles = layer_data.get("tiles", {})
                        if not tiles:
                            continue

                        adjacent_positions = get_adjacent_empty_positions(i)
                        random.shuffle(adjacent_positions)

                        for pos in adjacent_positions:
                            if added_count >= tiles_to_add:
                                break
                            # Add a t1 tile to this position
                            level[layer_key]["tiles"][pos] = ["t1", ""]
                            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                            added_count += 1
                            logger.debug(f"[PATTERN_MODE] Added tile at {pos} on layer {i} for 3-divisibility")

                    if added_count >= tiles_to_add:
                        logger.info(f"[PATTERN_MODE] Fallback: Added {added_count} tiles adjacent to pattern")
                    else:
                        logger.warning(f"[PATTERN_MODE] Fallback: Could only add {added_count}/{tiles_to_add} tiles")

            # For symmetric patterns (non-pattern mode), try to remove tiles to make total divisible
            # Strategy: Since symmetric addition is complex, use tile type redistribution
            # If redistribution fails, we'll use _force_fix_tile_counts later
            elif symmetry_mode in ("horizontal", "vertical", "both"):
                # For symmetric patterns, try to remove tiles to make total divisible
                # Remove remainder tiles (1 or 2) from center positions or paired positions
                cols, rows = params.grid_size

                # Find removable tiles (regular tiles without special attributes)
                removable: List[Tuple[int, str, str]] = []  # (layer_idx, pos, tile_type)
                for i in range(num_layers):
                    layer_key = f"layer_{i}"
                    tiles = level.get(layer_key, {}).get("tiles", {})
                    for pos, tile_data in tiles.items():
                        if isinstance(tile_data, list) and len(tile_data) >= 2:
                            tile_type = tile_data[0]
                            attribute = tile_data[1] if len(tile_data) > 1 else ""
                            if (tile_type not in self.GOAL_TYPES and
                                not tile_type.startswith("craft_") and
                                not tile_type.startswith("stack_") and
                                not attribute):
                                removable.append((i, pos, tile_type))

                # Sort by position to prefer edge tiles (less impactful)
                random.shuffle(removable)

                # Remove tiles to make total divisible by 3
                tiles_to_remove = total_remainder  # 1 or 2
                removed_count = 0
                for layer_idx, pos, _ in removable[:tiles_to_remove]:
                    layer_key = f"layer_{layer_idx}"
                    if pos in level[layer_key]["tiles"]:
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                        removed_count += 1
                        if removed_count >= tiles_to_remove:
                            break

                if removed_count > 0:
                    tiles_were_removed = True
                    logger.debug(f"[_ensure_tile_count_divisible_by_3] Removed {removed_count} tiles for symmetric level divisibility")
            else:
                for i in range(num_layers):
                    if added_count >= tiles_to_add:
                        break
                    layer_key = f"layer_{i}"
                    layer_data = level.get(layer_key, {})
                    tiles = layer_data.get("tiles", {})
                    if not tiles:
                        continue

                    is_odd_layer = i % 2 == 1
                    layer_cols = cols if is_odd_layer else cols + 1
                    layer_rows = rows if is_odd_layer else rows + 1

                    all_positions = [f"{x}_{y}" for x in range(layer_cols) for y in range(layer_rows)]
                    used_positions = set(tiles.keys())

                    for pos in all_positions:
                        if added_count >= tiles_to_add:
                            break
                        if pos not in used_positions:
                            # Add a t1 tile to this position (t0 is excluded)
                            level[layer_key]["tiles"][pos] = ["t1", ""]
                            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                            added_count += 1

            # If adding tiles failed (no available positions), remove tiles instead
            # If remainder=1, remove 1 tile. If remainder=2, remove 2 tiles.
            # CRITICAL: For symmetric patterns OR pattern mode, we SKIP removal to preserve shape!
            if added_count < tiles_to_add and symmetry_mode == "none" and not preserve_pattern:
                tiles_to_remove = total_remainder  # 1 or 2
                removed_count = 0

                # Collect removable tiles (regular tiles without attributes, not goals)
                removable_tiles: List[Tuple[int, str]] = []
                for i in range(num_layers):
                    layer_key = f"layer_{i}"
                    tiles = level.get(layer_key, {}).get("tiles", {})
                    for pos, tile_data in tiles.items():
                        if isinstance(tile_data, list) and len(tile_data) >= 2:
                            tile_type = tile_data[0]
                            attribute = tile_data[1] if len(tile_data) > 1 else ""
                            # Only remove regular tiles without attributes (not goal tiles)
                            if (tile_type not in self.GOAL_TYPES and
                                not tile_type.startswith("craft_") and
                                not tile_type.startswith("stack_") and
                                not attribute):
                                removable_tiles.append((i, pos))

                # Remove tiles from the end of the list (less impactful positions)
                random.shuffle(removable_tiles)
                for layer_idx, pos in removable_tiles[:tiles_to_remove]:
                    layer_key = f"layer_{layer_idx}"
                    if pos in level[layer_key]["tiles"]:
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                        removed_count += 1
                        if removed_count >= tiles_to_remove:
                            break

                if removed_count > 0:
                    tiles_were_removed = True
            elif added_count < tiles_to_add and preserve_pattern:
                logger.info(f"[PATTERN_MODE] Skipped tile removal to preserve pattern shape (need {tiles_to_add - added_count} more tiles)")

        # Step 1: Count each tile type across all layers
        # IMPORTANT: Also count internal tiles in craft/stack containers as t0
        type_counts: Dict[str, int] = {}
        type_positions: Dict[str, List[Tuple[int, str]]] = {}  # type -> [(layer_idx, pos), ...]

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # For craft/stack tiles, count internal tiles as t0
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # [count] = number of internal t0 tiles
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            type_counts["t0"] = type_counts.get("t0", 0) + internal_count
                    else:
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        if tile_type not in type_positions:
                            type_positions[tile_type] = []
                        type_positions[tile_type].append((i, pos))

        if not type_counts:
            return level

        # Step 2: Find types that need adjustment
        # Strategy: Reassign tiles from types with remainder to types that need more
        types_needing_add = []  # (type, tiles_needed) - needs 1 or 2 more to reach multiple of 3
        types_with_excess = []  # (type, excess_count, positions) - has 1 or 2 extra

        for tile_type, count in type_counts.items():
            remainder = count % 3
            if remainder == 0:
                continue
            elif remainder == 1:
                # Need 2 more, or remove 1
                types_needing_add.append((tile_type, 2))
            else:  # remainder == 2
                # Need 1 more, or remove 2
                types_needing_add.append((tile_type, 1))

        if not types_needing_add:
            return level

        # Step 3: Find available positions to add tiles
        active_layers = []
        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                active_layers.append(i)

        if not active_layers:
            return level

        # Collect available positions across all active layers
        available_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)
        cols, rows = params.grid_size

        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]
            is_odd_layer = layer_idx % 2 == 1
            layer_cols = cols if is_odd_layer else cols + 1
            layer_rows = rows if is_odd_layer else rows + 1

            all_positions = [f"{x}_{y}" for x in range(layer_cols) for y in range(layer_rows)]
            used_positions = set(tiles.keys())
            for pos in all_positions:
                if pos not in used_positions:
                    available_positions.append((layer_idx, pos))

        # Step 4: Add tiles to reach multiples of 3 for each type
        # IMPORTANT: Skip adding tiles if we already removed tiles for total adjustment
        # Adding tiles would undo the total divisibility fix
        # CRITICAL: For symmetric patterns, skip random tile addition to preserve symmetry!
        # PATTERN MODE: Also skip adding tiles to preserve pattern shape
        if not tiles_were_removed and symmetry_mode == "none" and not preserve_pattern:
            for tile_type, tiles_needed in types_needing_add:
                for _ in range(tiles_needed):
                    if not available_positions:
                        break
                    layer_idx, pos = available_positions.pop(0)
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos] = [tile_type, ""]
                    level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        # Step 5: Final verification - if still have issues, reassign existing tiles
        # Recount after additions (include internal t0 tiles)
        type_counts_final: Dict[str, int] = {}
        type_positions_final: Dict[str, List[Tuple[int, str]]] = {}

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # Count internal tiles as t0
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            type_counts_final["t0"] = type_counts_final.get("t0", 0) + internal_count
                    else:
                        type_counts_final[tile_type] = type_counts_final.get(tile_type, 0) + 1
                        if tile_type not in type_positions_final:
                            type_positions_final[tile_type] = []
                        type_positions_final[tile_type].append((i, pos))

        # Check if any type still has remainder
        still_broken = [(t, c % 3) for t, c in type_counts_final.items() if c % 3 != 0]

        # Keep fixing until all types are divisible by 3 or no more fixes possible
        max_fix_iterations = 10
        fix_iteration = 0

        while still_broken and fix_iteration < max_fix_iterations:
            fix_iteration += 1
            fixed_any = False

            # Separate types by remainder
            rem1_types = [t for t, r in still_broken if r == 1]
            rem2_types = [t for t, r in still_broken if r == 2]

            # Strategy 1: Pair rem1 with rem2 types
            while rem1_types and rem2_types:
                type_a = rem1_types.pop(0)  # remainder 1
                type_b = rem2_types.pop(0)  # remainder 2

                # Move 1 tile from type_a to type_b
                # type_a: -1 → remainder 0
                # type_b: +1 → remainder 0
                if type_a in type_positions_final and type_positions_final[type_a]:
                    layer_idx, pos = type_positions_final[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

            # Strategy 2: Handle 3 types with same remainder
            # 3 types with rem 1: redistribute 1 tile each to balance
            while len(rem1_types) >= 3:
                type_a = rem1_types.pop(0)
                type_b = rem1_types.pop(0)
                type_c = rem1_types.pop(0)

                # Move 1 from type_a to type_b → a:rem0, b:rem2
                # Move 2 from type_b to type_c → b:rem0, c:rem0
                if type_a in type_positions_final and type_positions_final[type_a]:
                    layer_idx, pos = type_positions_final[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

                if type_b in type_positions_final and len(type_positions_final.get(type_b, [])) >= 2:
                    for _ in range(2):
                        layer_idx, pos = type_positions_final[type_b].pop()
                        layer_key = f"layer_{layer_idx}"
                        level[layer_key]["tiles"][pos][0] = type_c
                    fixed_any = True

            # 3 types with rem 2: redistribute 2 tiles each to balance
            while len(rem2_types) >= 3:
                type_a = rem2_types.pop(0)
                type_b = rem2_types.pop(0)
                type_c = rem2_types.pop(0)

                # Move 2 from type_a to type_b → a:rem0, b:rem1
                # Move 1 from type_b to type_c → b:rem0, c:rem0
                if type_a in type_positions_final and len(type_positions_final.get(type_a, [])) >= 2:
                    for _ in range(2):
                        layer_idx, pos = type_positions_final[type_a].pop()
                        layer_key = f"layer_{layer_idx}"
                        level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

                if type_b in type_positions_final and type_positions_final[type_b]:
                    layer_idx, pos = type_positions_final[type_b].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_c
                    fixed_any = True

            if not fixed_any:
                break

            # Recount for next iteration
            type_counts_final = {}
            type_positions_final = {}
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                            if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                type_counts_final["t0"] = type_counts_final.get("t0", 0) + internal_count
                        else:
                            type_counts_final[tile_type] = type_counts_final.get(tile_type, 0) + 1
                            if tile_type not in type_positions_final:
                                type_positions_final[tile_type] = []
                            type_positions_final[tile_type].append((i, pos))

            still_broken = [(t, c % 3) for t, c in type_counts_final.items() if c % 3 != 0]

        # SPECIAL HANDLING: t0 (goal internal tiles) cannot be repositioned
        # If t0 has remainder, we must adjust goal internal counts
        t0_in_broken = [r for t, r in still_broken if t == "t0"]
        other_broken = [(t, r) for t, r in still_broken if t != "t0"]

        # CRITICAL: Check if already fixed to prevent duplicate adjustments
        already_fixed_t0 = level.get("_goal_divisibility_fixed", False)

        if t0_in_broken and goal_tiles_with_internal and not already_fixed_t0:
            t0_remainder = t0_in_broken[0]  # 1 or 2
            t0_count_current = type_counts_final.get("t0", 0)

            # Strategy: Adjust goal internal count to make t0 divisible by 3
            # If t0 remainder=1: add 2 to goal internal, OR remove 1
            # If t0 remainder=2: add 1 to goal internal, OR remove 2
            # Prefer adding to maintain more tiles

            tiles_to_add_to_goal = 3 - t0_remainder  # 2 if rem=1, 1 if rem=2

            # Check if we can balance with other broken types
            # If other type has complementary remainder, we can add tiles to both
            complementary_types = [t for t, r in other_broken if r == t0_remainder]

            if complementary_types and available_positions:
                # Add tiles to balance: t0 gets +tiles_to_add_to_goal, complementary gets +tiles_to_add_to_goal
                # This adds 2*tiles_to_add_to_goal total (which is 2 or 4, both bad for total)
                # Better strategy: reduce t0 by t0_remainder, add same amount to complementary type
                pass  # Skip this complex case, use simple goal adjustment

            # Simple fix: adjust goal internal tiles to make t0 divisible by 3
            added_to_goal = 0
            for layer_idx, pos, tile_data in goal_tiles_with_internal:
                if added_to_goal >= tiles_to_add_to_goal:
                    break
                if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                    current_internal = int(tile_data[2][0]) if tile_data[2][0] else 0
                    # Add to this goal tile
                    tile_data[2][0] = current_internal + 1
                    added_to_goal += 1

                    # Update goalCount
                    goal_type = tile_data[0]
                    if "goalCount" in level:
                        level["goalCount"][goal_type] = level["goalCount"].get(goal_type, 0) + 1

            if added_to_goal > 0:
                level["_goal_divisibility_fixed"] = True  # Mark as fixed
                logger.info(
                    f"[_ensure_tile_count_divisible_by_3] Added {added_to_goal} to goal internal tiles "
                    f"to fix t0 remainder ({t0_remainder})"
                )

                # Now fix complementary type if exists (add tiles to match the added t0)
                # This ensures total stays divisible by 3
                # Added to t0: tiles_to_add_to_goal (2 or 1)
                # Need to add complementary amount to reach total divisible by 3
                # If we added 2 to t0: total += 2, need total += 1 more (add 1 tile) or total += 4 more
                # If we added 1 to t0: total += 1, need total += 2 more (add 2 tiles) or total += 5 more

                complement_needed = 3 - added_to_goal  # 1 if added 2, 2 if added 1
                tiles_added_for_balance = 0

                # Add tiles to a regular type (prefer type with complementary remainder)
                target_type = None
                if complementary_types:
                    target_type = complementary_types[0]
                elif valid_tile_types:
                    target_type = valid_tile_types[0]

                # PATTERN MODE: Skip adding balance tiles to preserve pattern shape
                if target_type and available_positions and not preserve_pattern:
                    for _ in range(complement_needed):
                        if not available_positions:
                            break
                        layer_idx_new, pos_new = available_positions.pop(0)
                        layer_key_new = f"layer_{layer_idx_new}"
                        level[layer_key_new]["tiles"][pos_new] = [target_type, ""]
                        level[layer_key_new]["num"] = str(len(level[layer_key_new]["tiles"]))
                        tiles_added_for_balance += 1

                    if tiles_added_for_balance > 0:
                        logger.info(
                            f"[_ensure_tile_count_divisible_by_3] Added {tiles_added_for_balance} {target_type} tiles "
                            f"to balance total after t0 adjustment"
                        )

        # FINAL STEP: FORCE divisibility by 3
        # If still_broken has any types, it means the total is not divisible by 3
        # or the reassignment strategies failed. Force fix by removing tiles.
        # NOTE: Even for symmetric patterns, we must force fix if redistribution failed
        # PATTERN MODE: skip forced tile removal here — defer to _finalize_divisibility_guarantee,
        # which fixes ÷3 shape-safely (add adjacent / container-internal) instead of deleting pattern cells.
        if still_broken and preserve_pattern:
            logger.info("[_ensure_tile_count_divisible_by_3] Pattern mode: deferring ÷3 fix to finalize (no tile removal)")
        elif still_broken:
            # Recount everything one more time
            total_matchable = 0
            removable_tiles_final: List[Tuple[int, str, str]] = []  # (layer_idx, pos, tile_type)

            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                            # Count internal tiles
                            if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                total_matchable += internal_count
                        else:
                            total_matchable += 1
                            # Only add regular tiles without obstacles as removable
                            attr = tile_data[1] if len(tile_data) > 1 else ""
                            if not attr:
                                removable_tiles_final.append((i, pos, tile_type))

            total_remainder = total_matchable % 3
            if total_remainder != 0:
                # We MUST remove tiles to fix the total
                tiles_to_remove = total_remainder  # 1 or 2

                # Sort removable tiles by type - prefer removing from types with remainder
                type_counts_for_sort: Dict[str, int] = {}
                for layer_idx, pos, tile_type in removable_tiles_final:
                    type_counts_for_sort[tile_type] = type_counts_for_sort.get(tile_type, 0) + 1

                # Calculate remainder for each type
                type_remainders = {t: c % 3 for t, c in type_counts_for_sort.items()}

                # Sort: prefer types with remainder matching tiles_to_remove
                # e.g., if we need to remove 1 tile, prefer types with remainder 1
                def sort_key(item: Tuple[int, str, str]) -> Tuple[int, str]:
                    _, _, tile_type = item
                    remainder = type_remainders.get(tile_type, 0)
                    # Priority: exact match > any remainder > no remainder
                    if remainder == tiles_to_remove:
                        return (0, tile_type)
                    elif remainder > 0:
                        return (1, tile_type)
                    else:
                        return (2, tile_type)

                removable_tiles_final.sort(key=sort_key)

                removed_count = 0
                for layer_idx, pos, tile_type in removable_tiles_final:
                    if removed_count >= tiles_to_remove:
                        break
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                        removed_count += 1

                # After removing tiles for total, we need to re-run type redistribution
                # But now the total IS divisible by 3, so redistribution will work
                if removed_count > 0:
                    # Quick redistribution pass
                    type_counts_final2: Dict[str, int] = {}
                    type_positions_final2: Dict[str, List[Tuple[int, str]]] = {}

                    for i in range(num_layers):
                        layer_key = f"layer_{i}"
                        tiles = level.get(layer_key, {}).get("tiles", {})
                        for pos, tile_data in tiles.items():
                            if isinstance(tile_data, list) and len(tile_data) > 0:
                                tile_type = tile_data[0]
                                if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                                    if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                        internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                        type_counts_final2["t0"] = type_counts_final2.get("t0", 0) + internal_count
                                else:
                                    type_counts_final2[tile_type] = type_counts_final2.get(tile_type, 0) + 1
                                    if tile_type not in type_positions_final2:
                                        type_positions_final2[tile_type] = []
                                    type_positions_final2[tile_type].append((i, pos))

                    # Simple redistribution: pair rem1 with rem2
                    still_broken2 = [(t, c % 3) for t, c in type_counts_final2.items() if c % 3 != 0]
                    rem1_types2 = [t for t, r in still_broken2 if r == 1]
                    rem2_types2 = [t for t, r in still_broken2 if r == 2]

                    while rem1_types2 and rem2_types2:
                        type_a = rem1_types2.pop(0)
                        type_b = rem2_types2.pop(0)
                        if type_a in type_positions_final2 and type_positions_final2[type_a]:
                            layer_idx, pos = type_positions_final2[type_a].pop()
                            layer_key = f"layer_{layer_idx}"
                            if pos in level.get(layer_key, {}).get("tiles", {}):
                                level[layer_key]["tiles"][pos][0] = type_b

        return level

    def _enforce_pyramid_structure(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[v15.40] 최종 피라미드 구조 강제.

        상위 레이어 타일 수가 하위보다 많으면 가장자리 타일을 제거하여
        하위의 85% 이하로 줄임. 타일 타입/데이터는 보존.
        """
        num_layers = level.get("layer", 1)
        if num_layers < 2:
            return level
        if level.get("_skip_tile_redistribution"):
            return level
        # [v15.40] 패턴 모드에서는 패턴 형태 보존이 우선 → 피라미드 강제 건너뜀
        if level.get("_preserve_pattern"):
            return level

        layer_counts = []
        for i in range(num_layers):
            tiles = level.get(f"layer_{i}", {}).get("tiles", {})
            layer_counts.append(len(tiles))

        for i in range(1, num_layers):
            if layer_counts[i] == 0 or layer_counts[i - 1] == 0:
                continue
            max_allowed = int(layer_counts[i - 1] * 0.85)
            if max_allowed < 3:
                max_allowed = 3

            if layer_counts[i] > max_allowed:
                layer_key = f"layer_{i}"
                tiles = level[layer_key]["tiles"]
                excess = layer_counts[i] - max_allowed

                # 가장자리에서 먼 타일부터 제거 (중앙 보존)
                pos_list = list(tiles.keys())
                valid_pos = [p for p in pos_list if "_" in p]
                if not valid_pos:
                    continue
                xs = [int(p.split("_")[0]) for p in valid_pos]
                ys = [int(p.split("_")[1]) for p in valid_pos]
                cx = (min(xs) + max(xs)) / 2
                cy = (min(ys) + max(ys)) / 2

                # 중앙에서 먼 순서로 정렬 → 먼 것부터 제거
                valid_pos.sort(key=lambda p: -(abs(int(p.split("_")[0]) - cx) + abs(int(p.split("_")[1]) - cy)))

                removed = 0
                for pos in valid_pos:
                    if removed >= excess:
                        break
                    del tiles[pos]
                    removed += 1

                level[layer_key]["num"] = str(len(tiles))
                layer_counts[i] = len(tiles)
                logger.debug(f"[PYRAMID_ENFORCE] Layer {i}: removed {removed} tiles, now {layer_counts[i]}")

        return level

    def _decide_timea_tier(self, level_number: Optional[int], gimmick_intensity: float,
                           params: "GenerationParams") -> Optional[int]:
        """[TIMEA v2] 타임어택 티어(1~3) 결정. None = 타임어택 미적용.

        티어는 난이도와 **분리된 독립 레버**. 1=넉넉 / 2=보통 / 3=촉박.
        - params.timea_tier 명시 지정 최우선
        - Lv341(튜토리얼): gimmick_intensity 무관하게 적용 + 티어1(가장 쉬움).
          (구코드는 `gimmick_intensity > 0` 게이트에 묶여 341이 아예 제외됐다 — 보존패턴
           튜토리얼은 intensity=0 이라 timea 가 안 붙었고, 그래서 티어1이 죽은 상수였다.)
        - 그 외: 보스(10의 배수)만, 난이도 유도 <0.5→1 / <0.7→2 / else→3
        """
        if level_number is None:
            return None
        explicit = getattr(params, "timea_tier", None)
        if explicit in (1, 2, 3):
            return int(explicit)
        if level_number < TIME_ATTACK_UNLOCK_LEVEL:
            return None
        if level_number == TIME_ATTACK_UNLOCK_LEVEL:
            return 1  # 튜토리얼: 가장 쉬운 조건
        if gimmick_intensity <= 0 or level_number % 10 != 0:
            return None
        d = float(getattr(params, "target_difficulty", 0.5) or 0.5)
        if d < 0.5:
            return 1
        if d < 0.7:
            return 2
        return 3

    def _apply_timea(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[TIMEA v2] 최종 타일 수 기준으로 timea(제한시간, 초) 산출.

        공식:  timea = clamp(60, 600, ceil(tiles * 0.9s * TIER_MULT[tier]))
        - tiles = _collectable_tile_count (하한 없는 순수 수집타일수 = 실제 탭 횟수)
        - 정수 산술 고정: 프론트 미러와 부동소수 평가순서 차이로 1초 어긋나는 것 방지
          (예: n=100,mult=1.6 → (n*0.9)*t=144 vs n*(0.9*t)=145)
        - 하한 60/상한 600 = 게임 스키마 계약(DESIGN_LEVEL_MAP_SCHEMA.md: timea 60~600)

        캘리브레이션 근거: 게임은 탭 입력 락이 없어(LevelController.cs:1269-1283) 타일 비행
        0.5s 애니가 다음 탭을 막지 않는다 → 애니 하한 ≈0, 실질 하한은 인간 탭속도 ≈0.25s/타일.
        티어3 실효 0.54s/타일 = 물리하한의 약 2.2배.
        타이머는 연출 완료 후 시작 + 연출 중 레이캐스트 OFF(LevelController.cs:1192-1215)
        → 별도 오버헤드 가산 불필요.
        """
        tier = level.get("_timea_tier")
        if tier not in (1, 2, 3):
            return level
        tiles = self._collectable_tile_count(level)
        if tiles <= 0:
            return level
        milli = tiles * TIMEA_BASE_MILLI * TIMEA_TIER_MILLI[int(tier)]
        secs = -(-milli // 1_000_000)  # ceil
        secs = max(TIMEA_MIN_SEC, min(TIMEA_MAX_SEC, int(secs)))
        level["timea"] = secs
        return level

    @staticmethod
    def _tile_attr(tile_data: Any) -> str:
        """타일 속성 정규화. td[1] 이 None/누락이면 "" 로 취급.

        [CHAIN_CLOSURE] 실측: 프로덕션 배치에 td[1]=None 타일이 약 10%(수만 건) 존재.
        `td[1] == ""` 리터럴 비교만 하면 이들이 '속성 있음'으로 오분류되어
        정상 앵커가 앵커로 인정되지 않는다(주배치 사슬의 74.9% 오탐 실측).
        """
        if isinstance(tile_data, list) and len(tile_data) > 1 and isinstance(tile_data[1], str):
            return tile_data[1]
        return ""

    def _chain_release_closure(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[CHAIN_CLOSURE] 해제 불가능한 chain 속성 제거(plain화).

        게임 규칙(TileEffect.cs:932-951, 1066-1069): chain 타일은 잠긴 상태로 스폰되고
        **같은 층 수평 이웃(x±1)** 이 픽될 때만 해제된다. 잠긴 chain 은 픽 불가.

        게임의 자체 검출기 `CheckEffectTileCanUncover`(TileEffect.cs:1341)는
        `CheckRemainNearTile(true) < 1` 로 판정하는데, 이는 *살아있는* 이웃만 센다
        (Tile.cs:1542). 따라서 이웃이 '잠긴 chain' 이어도 count>=1 이 되어
        **FailReason.Chain 이 영구 미발동** → 플레이어에게 알림 없는 소프트락.
        게임에 '합법수 0 → 자동 리셔플' 구제도 없다(셔플은 유료 + 타입만 교환).

        판정: monotone 시스템(픽은 제거만 함) → "결국 픽 가능(EP)"의 최소고정점 = 정확한 답.
          EP 진입 조건(chain c): 수평 이웃 n 중 하나가
            - 보드에 존재(같은 층)              AND
            - craft 컨테이너 루트 아님(직접 픽 불가; stack 루트는 top 타일이 있어 픽 가능) AND
            - (attr(n) != chain  OR  n ∈ EP)
        ice/grass/curtain/unknown/bomb/teleport/link 등은 결국 픽 가능 → **유효 앵커**.
        frog 는 on_frog 동안 픽 불가지만 매 픽마다 이동하고 대상 없으면 제거되므로 앵커 인정.
        앵커 1개면 충분(plain 1개가 좌우 chain 둘 다 해제) → 런 길이 자체는 위반 아님.

        [커버리지 비판정] 상위층에 가려진 chain 도 위반으로 보지 않는다. 커버리지는 엄격한
        상향 DAG(FindAllUpperTiles 는 위층만 스캔)이고 픽에 매치가 필요 없어 최상층은 항상
        픽 가능 → 모든 가림은 **결국 해소**된다. '가려진 동안 앵커를 먼저 소진'하는 건
        플레이어가 순서로 회피 가능한 실수지 구조적 불가가 아니다.
        (초안은 run>=2 에 커버리지를 요구했으나 실측에서 Lv190 처럼 앵커가 plain 인
         RL 통과 레벨까지 걸려 과잉엄격이었다 — 정상 사슬 파괴가 이 검증기의 역사적 실패모드.)

        수리: 위반 chain 의 **속성만 제거**(td[1]=""). 타일/좌표/타입 불변 →
        ÷3(_clearability_type_counts)·패턴모양·max_moves 전부 보존.
        """
        num_layers = int(level.get("layer", 0) or 0)
        cleared = 0
        for i in range(num_layers):
            layer = level.get(f"layer_{i}")
            if not isinstance(layer, dict):
                continue
            tiles = layer.get("tiles")
            if not isinstance(tiles, dict) or not tiles:
                continue

            chains = {p for p, d in tiles.items() if self._tile_attr(d) == "chain"}
            if not chains:
                continue

            def _is_craft_root(pos: str) -> bool:
                d = tiles.get(pos)
                return (isinstance(d, list) and d and isinstance(d[0], str)
                        and d[0].startswith("craft_"))

            def _parse(pos: str):
                try:
                    x_s, y_s = pos.split("_")
                    return int(x_s), int(y_s)
                except (ValueError, AttributeError):
                    return None

            # 최소고정점
            ep: set = set()
            changed = True
            while changed:
                changed = False
                for p in chains - ep:
                    xy = _parse(p)
                    if xy is None:
                        continue
                    x, y = xy
                    for nx in (x - 1, x + 1):
                        npos = f"{nx}_{y}"
                        if npos not in tiles:
                            continue
                        if _is_craft_root(npos):
                            continue
                        nattr = self._tile_attr(tiles[npos])
                        if nattr == "chain" and npos not in ep:
                            continue
                        ep.add(p)
                        changed = True
                        break

            for p in sorted(chains - ep):
                data = tiles.get(p)
                if isinstance(data, list) and len(data) > 1:
                    data[1] = ""
                    cleared += 1
        if cleared:
            logger.info(f"[CHAIN_CLOSURE] stripped {cleared} unreleasable chain attr(s) (plain화; ÷3/모양 보존)")
        return level

    def _normalize_bomb_countdowns(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[BOMB_RANGE] bomb_N 의 N 을 기획 범위(3~5)로 정규화. 속성만 변경 → ÷3/모양 무영향.

        구코드가 randint(5,10) 으로 출고한 6~10, 그리고 tune/템플릿 경로가 만든 범위 밖 값을
        일괄 교정. 시뮬레이터는 max(3,min(5,·))로 클램프하므로(bot_simulator.py:1239) 범위 밖
        값은 '생성값 ≠ 검증값' 불일치를 만든다 → 난이도 평가 왜곡.
        속성만 'bomb' 인 경우(카운트 없음)도 기본값 부여.
        """
        fixed = 0
        for i in range(int(level.get("layer", 0) or 0)):
            tiles = (level.get(f"layer_{i}") or {}).get("tiles") or {}
            for _pos, td in tiles.items():
                if not (isinstance(td, list) and len(td) > 1 and isinstance(td[1], str)):
                    continue
                attr = td[1]
                if not attr.startswith("bomb"):
                    continue
                parts = attr.split("_")
                if len(parts) == 2 and parts[1].isdigit():
                    n = int(parts[1])
                    if BOMB_COUNTDOWN_MIN <= n <= BOMB_COUNTDOWN_MAX:
                        continue
                    n = max(BOMB_COUNTDOWN_MIN, min(BOMB_COUNTDOWN_MAX, n))
                elif attr == "bomb":
                    n = BOMB_COUNTDOWN_MAX  # 카운트 누락 → 가장 관대한 값
                else:
                    continue
                td[1] = f"bomb_{n}"
                fixed += 1
        if fixed:
            logger.info(f"[BOMB_RANGE] normalized {fixed} bomb countdown(s) into {BOMB_COUNTDOWN_MIN}~{BOMB_COUNTDOWN_MAX}")
        return level

    # craft/stack 방향 → 배출칸 오프셋
    _GOAL_DIR_DELTA = {"s": (0, 1), "n": (0, -1), "e": (1, 0), "w": (-1, 0)}

    def _repair_goal_output_direction(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[GOAL_OUTPUT] craft/stack 배출칸이 격자 밖이면 방향을 격자 안 빈칸으로 회전.

        게임 동작(확인됨): 배출칸에 앵커 타일이 없어도 `TileGroup.cs:1071` 이 배출을 진행하고,
        `Tile.cs:2843-2848` `AddOffset` 이 키를 `-1_3` 같은 값으로 재작성한다.
        `DB_Level.cs:898` 은 음수 인덱스에 null 을 반환 → 그 타일은 **영구 매칭 불가**(클리어 불가).
        개발팀도 형제 케이스를 v1.10.572 에서 패치했다(`TileCraft.cs:849-859` 주석).

        실측: 타운팝 템플릿 211개 중 46개에 배출칸 OOB 86건(대부분 `stack_s` 가 아래로 벗어남).
        82/83 은 방향 회전만으로 수리 가능.

        규칙: 격자 안이면서 (비어 있거나 컨테이너가 아닌) 칸을 향하는 방향으로 교체.
        후보가 없으면 그대로 두고 경고(상위에서 거부/강등 판단).
        """
        fixed = 0
        for i in range(int(level.get("layer", 0) or 0)):
            ld = level.get(f"layer_{i}")
            if not isinstance(ld, dict):
                continue
            tiles = ld.get("tiles")
            if not isinstance(tiles, dict) or not tiles:
                continue
            try:
                col, row = int(ld.get("col")), int(ld.get("row"))
            except (TypeError, ValueError):
                continue
            for pos, td in tiles.items():
                if not (isinstance(td, list) and td and isinstance(td[0], str)):
                    continue
                tp = td[0]
                if not (tp.startswith("craft_") or tp.startswith("stack_")):
                    continue
                d = tp[-1]
                delta = self._GOAL_DIR_DELTA.get(d)
                if not delta:
                    continue
                try:
                    x, y = map(int, pos.split("_"))
                except ValueError:
                    continue
                ox, oy = x + delta[0], y + delta[1]
                if 0 <= ox < col and 0 <= oy < row:
                    continue  # 정상
                # 격자 안을 향하는 대체 방향 탐색(빈칸 우선, 없으면 비컨테이너 칸)
                base = tp[:-1]
                best = None
                for nd, (dx, dy) in self._GOAL_DIR_DELTA.items():
                    if nd == d:
                        continue
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < col and 0 <= ny < row):
                        continue
                    npos = f"{nx}_{ny}"
                    occ = tiles.get(npos)
                    occ_type = occ[0] if isinstance(occ, list) and occ and isinstance(occ[0], str) else None
                    if occ is None:
                        best = nd
                        break  # 빈칸이 최선
                    if best is None and not (occ_type or "").startswith(("craft_", "stack_")):
                        best = nd
                if best:
                    td[0] = base + best
                    fixed += 1
                else:
                    logger.warning(f"[GOAL_OUTPUT] L{i} {pos} {tp}: 격자 안 배출칸 없음 — 수리 실패")
        if fixed:
            logger.info(f"[GOAL_OUTPUT] repaired {fixed} container direction(s) (배출칸 OOB → 격자 안)")
        return level

    def _ensure_tutorial_unlock_gimmick(self, level: Dict[str, Any], level_number: Optional[int],
                                        min_count: int = 3) -> Dict[str, Any]:
        """[TUTORIAL_GUARANTEE] 기믹 언락 첫 스테이지에 해당 기믹이 반드시 존재하도록 보장.

        generate() 는 말미에서 이 보장을 수행하지만, **generate() 를 우회하는 경로**
        (템플릿 기반 생성 `/generate/from-template`, 보스 템플릿)는 타지 않는다.
        실측: 폭탄 언락 레벨 Lv291 이 템플릿 경로로 만들어져 **기믹 0개**로 출고됨
        (randSeed==291·pattern_index 없음·10x10 = 템플릿 시그니처). 튜토리얼인데 폭탄이 없으면
        플레이어가 그 기믹을 학습할 기회 자체를 잃는다.

        멱등: 이미 min_count 이상 있으면 아무것도 하지 않는다.
        """
        if level_number is None:
            return level
        try:
            level_number = int(level_number)
        except (TypeError, ValueError):
            return level
        tut = self.TUTORIAL_UNLOCK_LEVELS.get(level_number)
        if not tut:
            return level
        try:
            if tut == "unknown":
                return self._ensure_unknown_tutorial_count(level, min_count)
            if tut in ("craft", "stack"):
                return self._ensure_container_goal_tutorial(level, tut)
            if tut == "key":
                return level  # key 는 게임이 런타임 배치(unlockTile) — 별도 보장 로직 소관
            return self._ensure_tutorial_gimmick_count(level, tut, min_count)
        except Exception as exc:  # noqa: BLE001 - 보장 실패가 생성 자체를 깨뜨리지 않게
            logger.warning(f"[TUTORIAL_GUARANTEE] Lv{level_number} '{tut}' 보장 실패: {exc}")
            return level

    def _finalize_level(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[FINALIZE] 레벨 출고 직전 공통 마무리. **멱등**.

        chain 클로저 → link sanitize → max_moves/timea 재산출 순서.
        generate() 말미뿐 아니라 generate() 를 우회/이후에 타일을 만지는 모든 경로
        (역생성 구제, 보스 템플릿, tune)에서 호출해야 한다. 과거 chain/link 버그의
        공통 원인은 '이 tail 이 여러 곳에 손수 복제되어 일부에 누락' 이었다.

        ⚠️ `_finalize_divisibility_guarantee` 는 **여기 넣지 않는다**. 그것은 *총합* ÷3만
        보장하고 per-type 은 바로 뒤따르는 FINAL_REPAIR relabel 블록이 마무리하는 2단 구조라,
        단독 재호출하면 per-type ÷3 이 깨진다(실측: Lv81/341/350 전부 위반 발생).
        본 함수의 두 sanitizer 는 td[1](속성)만 만지므로 ÷3 에 영향이 없다 — 그래서 ÷3
        보정 이후 어디서든 안전하게 호출 가능하다. ÷3 이 필요한 호출부는 각자
        `_finalize_divisibility_guarantee` 를 먼저 돌린 뒤 이 함수를 부른다.
        """
        level = self._chain_release_closure(level)
        level = self._strip_orphaned_link_tiles(level)
        level = self._normalize_bomb_countdowns(level)
        # frog 는 스폰 즉시 선택 가능해야 한다(가려지면 안 됨). 검증기가 1158 에 있으나
        # 그 이후 튜토리얼 ensure(1141/1501)와 상위층 블로커 배치가 frog 를 덮을 수 있어 재적용.
        level = self._validate_and_fix_frog_positions(level)
        # [GOAL_OUTPUT] 배출칸이 격자 밖인 craft/stack → 방향 회전(영구 매칭불가 타일 방지).
        # 기존엔 `_relocate_tiles_from_goal_outputs` 가 '점유'만 보고 경계는 안 봤고,
        # _preserve_pattern 이면 early-return 이라 템플릿 경로가 통째로 무방비였다.
        level = self._repair_goal_output_direction(level)
        # [GRASS] 4방 이웃 < 2 인 grass 는 게임서 FailReason.Grass_CantRevive 소프트락.
        # `_strip_confusing_grass` 가 generate()/보스 경로에만 있어 템플릿 경로는 무방비였다.
        try:
            level = self._strip_confusing_grass(level)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[GRASS] strip 실패(무시): {exc}")
        # [CONTAINER_ONLY_COLOR] 컨테이너 안에만 존재하는 색 제거. 타입 라벨만 바꾸므로
        # td[1](속성)과 마찬가지로 ÷3·모양에 영향이 없어 여기(공통 tail)에 둔다.
        try:
            level = self._repair_container_only_types(level)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[CONTAINER_ONLY_COLOR] 보정 실패(무시): {exc}")
        # [KEY_GIMMICK] 색타일에 찍힌 key '속성' 제거. 반드시 ÷3 복구보다 **먼저** 돈다
        # (이게 색 카운트를 되돌려놓아야 뒤의 ÷3 판정이 올바른 수를 본다).
        # [EFFECT_STR] 게임 파서가 모르는 기믹 문자열 정규화. key 속성 제거보다 먼저 돈다
        # (별칭이 key 로 정규화될 여지는 없지만, 문자열 계약을 먼저 세우는 편이 추론이 쉽다).
        try:
            level = self._repair_effect_strings(level)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[EFFECT_STR] 정규화 실패(무시): {exc}")
        try:
            level = self._repair_key_gimmick(level)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[KEY_GIMMICK] 복구 실패(무시): {exc}")
        # [UNLOCK_TILE] 키 공급량보다 잠금 슬롯이 많으면 영구히 안 열린다 → unlockTile 하향.
        # key 속성 제거 뒤에 돌아야 명시 키 수를 정확히 센다.
        try:
            level = self._repair_unlock_tile(level)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[UNLOCK_TILE] 복구 실패(무시): {exc}")
        # [T0_DIV3] t0 총량 ÷3. 게임 분배 루프가 인덱스를 넘기지 않으려면 필수이고,
        # per-type ÷3(_repair_clearability)의 전제이기도 하므로 그보다 먼저 돈다.
        try:
            level = self._repair_t0_divisibility(level)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[T0_DIV3] 복구 실패(무시): {exc}")
        # [CLEARABILITY 최종 게이트] 모든 경로(절차·템플릿·보스·등껍질·고정·튜너)가 지나는 이 tail
        # 에서 **게임 정본 카운터**로 per-type ÷3 을 마지막으로 확인·복구한다.
        #
        # 왜 여기인가: 야간 A* 전수판정에서 PROVEN_IMPOSSIBLE 18개가 나왔는데 전부 ÷3 위반이었고,
        #   생성기 자체 게이트(`_finalize_divisibility_guarantee`)는 통과시킨 상태였다. 원인은
        #   두 판정기가 컨테이너를 다르게 세는 것 — 생성기는 개수(td[2][0])만, 솔버는 baked 내부의
        #   실타입과 key 를 구분해서 센다. 게다가 그 18개는 '필드 t0 + baked 컨테이너' 조합이라
        #   현재 generate() 경로로는 나올 수 없는 형태였다(bake 는 field_t0>0 이면 스킵) →
        #   generate() 안에만 방어선을 두면 그 미지의 경로를 못 막는다.
        try:
            level = self._repair_clearability(level)
        except Exception as exc:  # noqa: BLE001 — 복구 실패로 생성을 막지는 않는다
            logger.warning(f"[CLEARABILITY] 최종 복구 실패(무시): {exc}")
        # [GOAL_COUNT 정합] 선언된 목표(goalCount)와 보드의 실제 컨테이너를 일치시킨다.
        #
        # 보드에 없는 목표가 선언돼 있으면 **타일을 다 치워도 클리어가 안 된다**.
        #   실측 Lv480: goalCount {stack_w:3, stack_e:3} 인데 보드엔 stack_w 뿐 →
        #   봇이 96타일을 전부 제거하고도 clear_rate 0.00. goalCount 에서 stack_e 만 빼면 1.00.
        # 생성 중 컨테이너가 배치됐다가 후속 단계(경계 트림·피라미드·÷3 삭제·OOB 제거)에서
        # 사라졌는데 goalCount 가 갱신되지 않아 생긴다.
        # A* 도 RL 도 이 결함을 못 짚는다(A*=UNCERTAIN, RL=원인 불명의 0%) → 여기서 직접 막는다.
        try:
            level = self._repair_goal_count(level)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[GOAL_COUNT] 정합 복구 실패(무시): {exc}")
        level["max_moves"] = self._calculate_max_moves(level)
        level = self._apply_timea(level)
        return level

    # 게임 파서 DB_Level.cs:272 GetTileEffectEnum() 이 인정하는 효과 문자열 전체.
    # **완전일치(소문자)** 이며 목록 밖은 전부 else → TileEffectType.None 으로 조용히 버려진다.
    # bomb 만 StartsWith("bomb") 이고, 카운트는 spInteger.Parse 가 문자열에서 숫자를 긁는다
    # (TileEffect.cs:570) — 숫자가 없으면 0 이 되어 첫 클릭에 강제 실패한다.
    GAME_EFFECT_STRINGS = frozenset({
        "ice", "link_e", "link_w", "link_s", "link_n", "unknown", "craft",
        "grass", "chain", "curtain_open", "curtain_close", "frog", "teleporter", "key",
    })
    # 에디터가 과거에 흘린 별칭 → 게임이 먹는 정식 문자열
    EFFECT_ALIASES = {
        "curtain": "curtain_close",
        "teleport": "teleporter",
        "link_east": "link_e", "link_west": "link_w",
        "link_south": "link_s", "link_north": "link_n",
    }

    def _repair_effect_strings(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """기믹 문자열을 게임 파서가 먹는 형태로 정규화한다.

        게임은 모르는 문자열을 **조용히** TileEffectType.None 으로 만든다(DB_Level.cs:336).
        로그도 경고도 없다. 그래서 에디터는 "커튼 17장 배치함"이라고 믿는데 실제 게임엔
        평범한 타일 17장이 놓인다 — 난이도가 의도와 달라지고, 튜토리얼 레벨이면
        해당 기믹을 아예 학습하지 못한다.

        실측(출시 배치): `curtain` 17장 / 11레벨. 장애물 배치기는 "curtain_close" 를 제대로
        쓰는데 **튜토리얼 배치기의 GIMMICK_ATTRIBUTES 맵만** "curtain" 이었다 — key 사건과
        같은 계통(맵이 게임 파서 계약과 어긋남)이다.

        - 별칭이면 정식 문자열로 교체
        - 그래도 모르는 문자열이면 제거(""). 게임이 어차피 None 으로 만드니 에디터 모델을
          게임에 맞추는 쪽이 안전하다 — 그래야 난이도·검증이 실제와 일치한다.
        타입·위치·개수를 건드리지 않으므로 ÷3 과 모양에 영향이 없다.
        """
        fixed, dropped = [], []
        for i in range(int(level.get("layer", 0) or 0) + 1):
            ld = level.get(f"layer_{i}")
            tiles = ld.get("tiles") if isinstance(ld, dict) else None
            if not isinstance(tiles, dict):
                continue
            for pos, td in tiles.items():
                if not (isinstance(td, list) and len(td) > 1 and isinstance(td[1], str)):
                    continue
                e = td[1]
                if not e:
                    continue
                low = e.lower()
                if low in self.GAME_EFFECT_STRINGS or low.startswith("bomb"):
                    continue
                alias = self.EFFECT_ALIASES.get(low)
                if alias:
                    td[1] = alias
                    fixed.append(f"L{i}:{pos} '{e}'→'{alias}'")
                else:
                    td[1] = ""
                    dropped.append(f"L{i}:{pos} '{e}'")

        if fixed:
            logger.error(f"[EFFECT_STR] 게임 미인식 기믹 문자열 {len(fixed)}개 정규화: {fixed[:6]}")
        if dropped:
            logger.error(f"[EFFECT_STR] 정식명 없는 기믹 문자열 {len(dropped)}개 제거: {dropped[:6]}")
        return level

    def _repair_t0_divisibility(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """t0(런타임 분배 대상) 총 개수를 3배수로 맞춘다 — 컨테이너 내부 개수만 조정.

        게임의 분배 루프(DB_Level.cs:1179/1196)는
            randomTileIndexList = DistributeTiles(emptyTilesLength / 3, ...)   ← 정수 나눗셈
            for (i = 0; i < emptyTilesLength; i++) { curIndex = setCount / 3; ... randomTileIndexList[curIndex] }
        이다. emptyTilesLength 가 3배수가 아니면 마지막 묶음이 리스트 길이를 넘겨
        **IndexOutOfRangeException** 이 나고, 예외를 피하더라도 그 타입이 3장 미만으로
        배정돼 영구 매칭불가가 된다.
        (실측 8/16 배치 Lv558/606/619/628/934/1468 — 전부 `used > len` 이었다.)

        `_finalize_divisibility_guarantee` Step 3 의 비패턴 경로는 '줄이기'만 시도하는데
            take = min(intern - MIN_GOAL_COUNT, ...)
        라서 내부 개수가 이미 MIN_GOAL_COUNT 이하인 컨테이너에서는 take<=0 이라
        아무것도 못 하고 실패 로그만 남겼다. 필드 t0 가 0 이면(전부 컨테이너 안) 특히 그렇다.
        여기서는 **늘리는 방향**으로 해결한다 — 늘리기는 하한 제약이 없고, 덤으로
        MIN_GOAL_COUNT 미달 컨테이너도 정상화된다.

        타일 위치·타입·기믹을 건드리지 않으므로 모양이 완전히 보존된다.
        goalCount 는 뒤따르는 `_repair_goal_count` 가 보드 기준으로 재계산한다.
        """
        containers: List[list] = []
        t0_regular = 0
        for i in range(int(level.get("layer", 0) or 0) + 1):
            ld = level.get(f"layer_{i}")
            tiles = ld.get("tiles") if isinstance(ld, dict) else None
            if not isinstance(tiles, dict):
                continue
            for td in tiles.values():
                if not (isinstance(td, list) and td and isinstance(td[0], str)):
                    continue
                tt = td[0]
                if tt == "t0":
                    t0_regular += 1
                elif tt.startswith("craft_") or tt.startswith("stack_"):
                    if len(td) > 2 and isinstance(td[2], list) and td[2]:
                        # baked(내부 타입 문자열 확정)는 개수만 늘리면 문자열과 어긋난다 → 제외
                        inner = td[2][1] if len(td[2]) > 1 and isinstance(td[2][1], str) else ""
                        if not inner:
                            containers.append(td)

        def _n(td: list) -> int:
            try:
                return int(td[2][0])
            except (ValueError, TypeError, IndexError):
                return 0

        total = t0_regular + sum(_n(td) for td in containers)
        rt = total % 3
        if rt == 0 or not containers:
            return level

        need = 3 - rt
        # 내부 개수가 적은 컨테이너부터 1씩 분산 — 하나만 비정상적으로 두꺼워지는 것 방지.
        # MIN_GOAL_COUNT 미달인 것을 우선 채운다.
        containers.sort(key=_n)
        for k in range(need):
            td = containers[k % len(containers)]
            td[2][0] = _n(td) + 1

        logger.error(
            f"[T0_DIV3] t0 총량 {total}→{total + need} (컨테이너 내부 +{need}). "
            f"그대로 두면 게임 분배가 randomTileIndexList 범위를 넘어 IndexOutOfRange"
        )
        return self._sync_layer_num_fields(level)

    @staticmethod
    def _repair_key_gimmick(level: Dict[str, Any]) -> Dict[str, Any]:
        """색타일에 '속성'으로 찍힌 key 를 제거한다.

        게임은 타일 타입이 아니라 **효과(xEffect)만 봐도** 키타일로 판정한다:
            DB_Level.cs:234
                isKeyTile => xTileID == "t16" || xTileID.ToLower() == "key"
                          || xEffect.ToLower() == "key";
            DB_Level.cs:257  GetTileIDNum → isKeyTile 이면 16 반환

        그래서 ["t8","key"] 는 게임에서 t8 이 아니라 키타일이다. 에디터는 t8 로 세므로
        ÷3 이 맞다고 판단하지만 실제 보드에선 t8 이 한 장 모자라 **그 색 전체가 영구
        매칭불가**가 된다. 실측 Lv111(key 언락 튜토리얼): t7 3→2, t8 3→2, t11 6→5 —
        6장이 보드에 영원히 남아 클리어 불가. 에디터 A* 는 PROVEN_SOLVABLE 로 통과시켰다.

        키타일 자체는 unlockTile(xUnlockTile)로 게임이 t0 분배에서 만들므로
        (DB_Level.cs:1173 lockBufferCount → 1179 DistributeTiles specifiedCount),
        여기서는 **속성만 지워 색을 되돌린다**. 타입·좌표·개수는 건드리지 않으므로
        모양과 총량이 보존된다.

        타입이 진짜 key 인 타일(["key",...])은 정상이므로 그대로 둔다.
        """
        stripped = 0
        for i in range(int(level.get("layer", 0) or 0) + 1):
            ld = level.get(f"layer_{i}")
            tiles = ld.get("tiles") if isinstance(ld, dict) else None
            if not isinstance(tiles, dict):
                continue
            for pos, td in tiles.items():
                if not (isinstance(td, list) and len(td) > 1 and isinstance(td[0], str)):
                    continue
                gim = td[1] if isinstance(td[1], str) else ""
                if gim.lower() != "key":
                    continue
                if td[0].lower() == "key" or td[0] == "t16":
                    continue  # 진짜 키타일 — 유지
                td[1] = ""
                stripped += 1

        if stripped:
            logger.error(
                f"[KEY_GIMMICK] 색타일에 찍힌 key 속성 {stripped}개 제거 — "
                f"게임(isKeyTile)이 색을 무시하고 키타일로 읽어 ÷3 이 깨지는 것을 방지"
            )
        return level

    @staticmethod
    def _repair_unlock_tile(level: Dict[str, Any]) -> Dict[str, Any]:
        """열 수 없는 잠금 슬롯을 없앤다 — unlockTile 을 실제 키 공급량에 맞춘다.

        게임은 잠긴 독 슬롯 1칸당 키타일 3장을 요구한다(unlockTile × 3).
        키 공급원은 둘 뿐이다:
          1) 레벨 JSON 에 박힌 명시 키 (타입 "key"/"t16", 컨테이너 baked 포함)
          2) t0 분배가 만드는 키 — DB_Level.cs:1179 DistributeTiles(..., lockBufferCount, ...)
             단 **t0 가 하나도 없으면 분배 자체를 건너뛴다**(DB_Level.cs:1172
             `if (emptyTilesLength == 0) return;`) → 이 경우 키는 1)뿐이다.

        그래서 t0 == 0 이고 명시 키가 unlockTile×3 에 못 미치면 그 슬롯은 **영원히
        잠긴 채로 남는다**(실측 Lv1200/1300/1440: unlockTile=2 인데 craft 내부 키 3장뿐).
        독이 좁아진 채 고정되므로 난이도가 의도와 달라진다.

        모양을 건드리지 않는 유일한 교정은 unlockTile 을 낮추는 것이다.
        키를 더 넣으면 그 색/총량이 바뀌어 ÷3 이 깨진다.
        """
        unlock = int(level.get("unlockTile", level.get("xUnlockTile", 0)) or 0)
        if unlock <= 0:
            return level

        explicit_keys = 0
        t0_count = 0
        for i in range(int(level.get("layer", 0) or 0) + 1):
            ld = level.get(f"layer_{i}")
            tiles = ld.get("tiles") if isinstance(ld, dict) else None
            if not isinstance(tiles, dict):
                continue
            for td in tiles.values():
                if not (isinstance(td, list) and td and isinstance(td[0], str)):
                    continue
                tt = td[0]
                gim = td[1] if len(td) > 1 and isinstance(td[1], str) else ""
                if tt == "t0":
                    t0_count += 1
                elif tt.lower() == "key" or tt == "t16" or gim.lower() == "key":
                    explicit_keys += 1
                elif tt.startswith("craft_") or tt.startswith("stack_"):
                    si = td[2] if len(td) > 2 else None
                    if not (isinstance(si, list) and si):
                        continue
                    try:
                        n = int(si[0])
                    except (ValueError, TypeError):
                        continue
                    inner = si[1] if len(si) > 1 and isinstance(si[1], str) else ""
                    ids = [s for s in inner.split("_") if s] if inner else []
                    # CTileStackInfo:149 — 개수가 정확히 맞을 때만 baked 로 채택된다
                    if len(ids) == n:
                        explicit_keys += sum(1 for s in ids if s.lower() == "key" or s == "t16")
                    else:
                        t0_count += n

        if t0_count > 0:
            return level  # 게임이 t0 분배로 부족분을 만든다

        supported = explicit_keys // 3
        if supported >= unlock:
            return level

        level["unlockTile"] = supported
        if "xUnlockTile" in level:
            level["xUnlockTile"] = supported
        logger.error(
            f"[UNLOCK_TILE] 키 공급 부족 — unlockTile {unlock}→{supported} "
            f"(명시 키 {explicit_keys}장, t0 없음 → 게임이 키를 추가 생성 못 함). "
            f"그대로 두면 잠금 슬롯 {unlock - supported}칸이 영구히 안 열린다"
        )
        return level

    @staticmethod
    def _repair_goal_count(level: Dict[str, Any]) -> Dict[str, Any]:
        """goalCount 를 보드의 실제 컨테이너 배출량으로 재계산한다.

        goalCount 는 '수집해야 할 타일 수'이고 컨테이너 내부 개수의 합과 같아야 한다.
        - 보드에 없는 타입 → 제거 (없으면 영원히 달성 불가 = 클리어 불가)
        - 개수가 다른 타입 → 보드 실제값으로 교정
        컨테이너가 하나도 없으면 goalCount 는 빈 dict 가 된다.
        """
        num_layers = int(level.get("layer", 0) or 0)
        board: Dict[str, int] = {}
        # layer 필드가 실제 층수보다 작게 적힌 레벨이 있어 +1 까지 훑는다(빈 상위층 잔재 대응).
        for i in range(num_layers + 1):
            ld = level.get(f"layer_{i}")
            tiles = ld.get("tiles") if isinstance(ld, dict) else None
            if not isinstance(tiles, dict):
                continue
            for td in tiles.values():
                if not (isinstance(td, list) and td and isinstance(td[0], str)):
                    continue
                t = td[0]
                if not (t.startswith("craft_") or t.startswith("stack_")):
                    continue
                cnt = 0
                if len(td) > 2 and isinstance(td[2], list) and td[2]:
                    try:
                        cnt = int(td[2][0])
                    except (TypeError, ValueError):
                        cnt = 0
                board[t] = board.get(t, 0) + cnt

        cur = level.get("goalCount")
        cur = dict(cur) if isinstance(cur, dict) else {}
        clean = {k: v for k, v in board.items() if v > 0}
        if cur != clean:
            ghost = {k: v for k, v in cur.items() if v and k not in clean}
            diff = {k: (v, clean.get(k)) for k, v in cur.items() if k in clean and clean[k] != v}
            if ghost:
                logger.error(
                    f"[GOAL_COUNT] 보드에 없는 목표 제거(클리어 불가 방지): {ghost} — goalCount → {clean}")
            elif diff:
                logger.warning(f"[GOAL_COUNT] 개수 교정 {diff} — goalCount → {clean}")
            level["goalCount"] = clean
        return level

    def _repair_clearability(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """정본 카운터로 per-type ÷3 을 확인하고, 깨졌으면 **baked 컨테이너 내부 라벨**로 복구한다.

        복구 수단을 baked 내부 슬롯으로 한정하는 이유: 모양(타일 위치)과 필드 색 배치는 이 시점에
        이미 확정이라 건드리면 다른 규칙(대칭·기믹·언락·헤더)이 깨진다. 반면 컨테이너 내부 문자열은
        런타임 스폰 타입일 뿐이라 라벨만 바꿔도 부작용이 없다.

        2단계로 고친다:
          A. **총합** — 매칭 총수가 ÷3 이 아니면 라벨 교체로는 절대 못 고친다(교체는 총합 불변).
             원인은 대개 `key` 개수다. key 는 매칭 대상이 아니고 정본 규약이 `unlockTile × 3` 인데,
             분배 결과를 부분만 bake 하면 이 개수가 어긋난다(실측 Lv336: unlockTile=1 인데 key 2개
             → 매칭 46개 %3=1). key↔매칭 슬롯을 바꿔 총합을 ÷3 으로 만들고, 이때 key 개수가
             규약값에 가까워지는 방향을 우선한다.
          B. **타입별** — 잉여(count%3)를 가진 슬롯들을 모아 **3개씩 한 타입에 몰아준다**.
             받는 타입은 3 증가라 나머지가 그대로다(0 유지). 잉여 총합은 총합이 ÷3 이므로 항상 ÷3.
             (잉여를 한 개씩 다른 타입에 넘기면 받는 쪽이 다시 깨진다 — 반드시 3단위로 옮긴다.)
        """
        from .solver import _clearability_type_counts

        def baked_slots() -> List[Tuple[List[Any], int, str]]:
            """(td[2] 배열, 슬롯 인덱스, 현재 라벨) — key 슬롯도 포함해서 돌려준다."""
            out: List[Tuple[List[Any], int, str]] = []
            for i in range(int(level.get("layer", 0) or 0)):
                ld = level.get(f"layer_{i}")
                tiles = ld.get("tiles") if isinstance(ld, dict) else None
                if not isinstance(tiles, dict):
                    continue
                for td in tiles.values():
                    if not (isinstance(td, list) and td and isinstance(td[0], str)):
                        continue
                    if not (td[0].startswith("craft_") or td[0].startswith("stack_")):
                        continue
                    if not (len(td) > 2 and isinstance(td[2], list) and len(td[2]) > 1
                            and isinstance(td[2][1], str) and td[2][1]):
                        continue
                    for k, part in enumerate(td[2][1].split("_")):
                        out.append((td[2], k, part))
            return out

        def relabel(arr: List[Any], k: int, dest: str) -> None:
            parts = arr[1].split("_")
            parts[k] = dest
            arr[1] = "_".join(parts)

        counts = _clearability_type_counts(level)
        if not any(c % 3 for c in counts.values()):
            return level
        before = {t: c for t, c in counts.items() if c % 3}

        slots = baked_slots()
        if not slots:
            logger.error(f"[CLEARABILITY] ÷3 위반 {before} — baked 컨테이너가 없어 복구 불가")
            self._last_playability_warning = True
            return level

        # ── A. 총합 ÷3 (key 개수 조정) ──────────────────────────────────────
        total = sum(counts.values())
        if total % 3:
            unlock = int(level.get("unlockTile", level.get("xUnlockTile", 0)) or 0)
            key_target = unlock * 3
            key_slots = [(a, k) for a, k, p in slots if p == "key"]
            tile_slots = [(a, k, p) for a, k, p in slots if p.startswith("t") and p[1:].isdigit()]
            need_less = total % 3                      # 매칭을 이만큼 줄이면 ÷3
            need_more = 3 - need_less                  # 또는 이만큼 늘리면 ÷3
            # key 를 규약값(unlockTile×3)에 가깝게 만드는 방향을 우선한다.
            grow_key = len(key_slots) + need_less <= key_target or not key_slots
            # [키 하한] key 를 매칭으로 되돌릴 때 unlockTile×3 아래로 내려가면 잠금 슬롯이
            # 영원히 안 열린다. 총합 ÷3 을 맞추려다 레벨을 다른 방식으로 망가뜨리는 셈이라
            # 이 방향은 여유분(key_target 초과분)이 있을 때만 허용한다.
            # (실측 Lv1102: unlockTile=2 인데 key 6→3 으로 깎아 슬롯 1칸이 영구 잠김.)
            can_shrink_key = len(key_slots) >= need_more and (len(key_slots) - need_more) >= key_target
            if grow_key and len(tile_slots) >= need_less:
                # 매칭 슬롯 → key : 매칭 총수 need_less 감소
                for a, k, _p in tile_slots[:need_less]:
                    relabel(a, k, "key")
            elif can_shrink_key:
                # key → 매칭 : 매칭 총수 need_more 증가. 받는 타입은 아래 B 단계가 정리한다.
                dest = next(iter(counts), "t1")
                for a, k in key_slots[:need_more]:
                    relabel(a, k, dest)
            else:
                logger.error(f"[CLEARABILITY] 매칭 총합 {total} 비÷3 — 조정 가능한 슬롯 부족 {before}")
                self._last_playability_warning = True
                return level
            counts = _clearability_type_counts(level)

        # ── B. 타입별 ÷3 (잉여를 3개씩 한 타입에 몰아주기) ──────────────────
        counts = _clearability_type_counts(level)
        rem = {t: c % 3 for t, c in counts.items() if c % 3}
        if rem:
            slots = baked_slots()
            by_type: Dict[str, List[Tuple[List[Any], int]]] = {}
            for a, k, p in slots:
                if p.startswith("t") and p[1:].isdigit():
                    by_type.setdefault(p, []).append((a, k))
            # 잉여 슬롯 수집 — 타입 t 에서 rem[t] 개
            surplus: List[Tuple[List[Any], int]] = []
            short: List[str] = []
            for t, r in rem.items():
                avail = by_type.get(t, [])
                take = min(r, len(avail))
                surplus.extend(avail[:take])
                if take < r:
                    short.append(t)
            if short:
                logger.error(f"[CLEARABILITY] 잉여 타입 {short} 의 baked 슬롯 부족 — 복구 불가 {before}")
                self._last_playability_warning = True
                return level
            # 3개씩 묶어 한 타입에 몰아준다(받는 타입은 +3 이라 나머지 불변)
            dest_pool = [t for t, c in counts.items() if c % 3 == 0 and c > 0] or list(counts)
            for i in range(0, len(surplus) - len(surplus) % 3, 3):
                dest = dest_pool[(i // 3) % len(dest_pool)]
                for a, k in surplus[i:i + 3]:
                    relabel(a, k, dest)

        after = _clearability_type_counts(level)
        left = {t: c for t, c in after.items() if c % 3}
        if left:
            logger.error(f"[CLEARABILITY] 복구 미완 — 잔여 위반 {left} (시작 {before})")
            self._last_playability_warning = True
        else:
            logger.warning(f"[CLEARABILITY] ÷3 위반 복구 완료: {before} → 해소")
        return level

    @staticmethod
    def _clearability_ok(level: Dict[str, Any]) -> bool:
        """게임 정본 기준 per-type ÷3 판정. **솔버와 같은 카운터**를 쓴다.

        생성기에는 자체 카운터(`_finalize_divisibility_guarantee._internal` 등)가 있는데,
        그건 컨테이너를 '개수'로만 세어 baked 내부의 key/실타입을 구분하지 못한다.
        판정기가 둘로 갈리면 생성기는 통과시키고 솔버는 불가 판정하는 사태가 난다
        (실측: PROVEN_IMPOSSIBLE 18개 전부 이 불일치였다). 출고 직전 검증은 솔버 것으로 통일한다.
        """
        try:
            from .solver import _clearability_type_counts
            return not any(c % 3 for c in _clearability_type_counts(level).values())
        except Exception:  # noqa: BLE001 — 판정 불가 시 막지 않는다(상위 게이트가 최종 방어)
            logger.exception("[CLEARABILITY] 판정 실패")
            return True

    def _repair_container_only_types(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[CONTAINER_ONLY_COLOR] **필드에 한 장도 없고 컨테이너 내부에만 있는 색**을 없앤다.

        왜 치명적인가 (실측 Lv280 `boss_L280_138c_4L`):
          useTileCount=9 인데 실제 색은 13종. 차이 4종(t7·t8·t14·t15)이 전부 컨테이너
          내부에만 존재했고, 그것도 서로 다른 컨테이너에 1개씩 흩어져 있었다.
            t7  : craft_n(L0 1_4) / craft_s(L2 6_3) / craft_s(L3 6_0) 에 1개씩
          t7 3장을 맞추려면 컨테이너 3개를 전부 연 뒤 그 사이 t7 을 독에 붙들고 있어야 한다.
          t8·t14·t15 도 같아서 **독 7칸 중 4칸이 반영구 점유** → 남은 3칸으로 9색을 처리해야
          하니 곧바로 오버플로. 봇 클리어율 0.00 (168타일 중 106에서 사망).
          이 4종만 필드색으로 치환하면 **0.00 → 1.00** (다른 건 아무것도 안 바꿈).

        발생 경로: `_diversify_container_inner_tiles` 가 게임 분배기(assign_t0_tiles)로
        내부 타입을 정하는데, 분배기는 '필드에 존재하는 색' 제약이 없어 새 색을 만들어낸다.
        분배기 자체(게임 정본 포트)를 손대면 인게임과 어긋나므로, 출고 tail 에서 라벨만 고친다.

        안전성: 고아 색의 총 개수는 곧 컨테이너 내부 개수이고, 분배기 불변식상 ÷3 이다.
        ÷3 인 덩어리를 통째로 다른 색으로 옮기므로 per-type ÷3 이 양쪽 다 보존된다.
        필드 t0 가 있으면 색이 런타임에 정해져 '필드에 없는 색' 판정이 불가능 → 건드리지 않는다.
        """
        num_layers = int(level.get("layer", 0) or 0)
        field_counts: Dict[str, int] = {}
        inner_slots: List[Tuple[List, int]] = []   # (td[2] 리스트, 슬롯 인덱스)
        inner_counts: Dict[str, int] = {}
        has_field_t0 = False

        for i in range(num_layers):
            layer = level.get(f"layer_{i}")
            tiles = layer.get("tiles") if isinstance(layer, dict) else None
            if not isinstance(tiles, dict):
                continue
            for _pos, td in tiles.items():
                if not (isinstance(td, list) and td and isinstance(td[0], str)):
                    continue
                tt = td[0]
                if tt == "t0":
                    has_field_t0 = True
                elif tt.startswith("craft_") or tt.startswith("stack_"):
                    if len(td) > 2 and isinstance(td[2], list) and len(td[2]) > 1 \
                            and isinstance(td[2][1], str) and td[2][1]:
                        parts = td[2][1].split("_")
                        for k, p in enumerate(parts):
                            if p.startswith("t") and p[1:].isdigit():
                                inner_counts[p] = inner_counts.get(p, 0) + 1
                                inner_slots.append((td[2], k))
                elif tt.startswith("t") and tt[1:].isdigit():
                    field_counts[tt] = field_counts.get(tt, 0) + 1

        if has_field_t0 or not inner_counts or not field_counts:
            return level

        orphans = [t for t in inner_counts if t not in field_counts]
        if not orphans:
            return level

        # 필드에 많은 색부터 라운드로빈 — 한 색만 비대해지는 것 방지
        dests = sorted(field_counts, key=lambda t: (-field_counts[t], int(t[1:])))
        remap: Dict[str, str] = {}
        di = 0
        for t in sorted(orphans, key=lambda x: int(x[1:])):
            if inner_counts[t] % 3:
                # 불변식 위반(분배기 이상) — 옮기면 ÷3 이 깨지므로 손대지 않는다
                logger.error(
                    f"[CONTAINER_ONLY_COLOR] {t} 내부 {inner_counts[t]}개가 비÷3 — 보정 생략")
                continue
            remap[t] = dests[di % len(dests)]
            di += 1
        if not remap:
            return level

        for arr, k in inner_slots:
            parts = arr[1].split("_")
            if parts[k] in remap:
                parts[k] = remap[parts[k]]
                arr[1] = "_".join(parts)

        logger.info(
            f"[CONTAINER_ONLY_COLOR] 컨테이너 전용 색 {len(remap)}종 치환 "
            f"({', '.join(f'{a}({inner_counts[a]})→{b}' for a, b in remap.items())})")
        return level

    def _strip_orphaned_link_tiles(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[LINK_SANITIZE] 대상 이웃이 없는 link_* 속성 제거(plain화).

        게임 FindLinkTile은 방향에 따라 GetTile(layer, x±1 / y±1)[0]로 대상 타일에 접근한다
        (E=x+1, W=x-1, S=y+1, N=y-1; 홀짝 보정 없음, 키="x_y"). 대상이 OOB(y<0 등)면 GetTile이
        null → null[0] → NullReferenceException으로 타일 스폰 크래시(TileEffect.FindLinkTile).
        링크는 배치 시 대상 존재를 검증하지만, 이후 변형 단계(_fix_visual_centering 위치 시프트,
        ÷3 삭제, 피라미드, OOB 제거)가 링크의 '대상 타일'을 옮기거나 지워 고아 링크가 남는다.
        마지막에 각 link 소스의 대상 존재를 재검증하고, 없으면 속성만 제거한다(타일 자체는 보존
        → ÷3/타입 무영향). 링크 개수는 소폭 줄 수 있으나 크래시보다 안전.
        """
        DELTA = {"link_e": (1, 0), "link_w": (-1, 0), "link_s": (0, 1), "link_n": (0, -1)}
        num_layers = int(level.get("layer", 0) or 0)
        stripped = 0
        for i in range(num_layers):
            layer = level.get(f"layer_{i}")
            if not layer:
                continue
            tiles = layer.get("tiles")
            if not tiles:
                continue
            for pos, data in tiles.items():
                if not (isinstance(data, list) and len(data) > 1):
                    continue
                attr = data[1]
                if not (isinstance(attr, str) and attr.startswith("link_")):
                    continue
                d = DELTA.get(attr)
                if d is None:
                    data[1] = ""  # 알 수 없는 link 변형 → 안전하게 제거
                    stripped += 1
                    continue
                try:
                    x, y = pos.split("_"); x = int(x); y = int(y)
                except ValueError:
                    continue
                tgt = tiles.get(f"{x + d[0]}_{y + d[1]}")
                # (a) 대상 없음/OOB → 고아 링크 (FindLinkTile null[0] NRE)
                if not (isinstance(tgt, list) and tgt):
                    data[1] = ""
                    stripped += 1
                    continue
                ttype = tgt[0] if isinstance(tgt[0], str) else ""
                tattr = tgt[1] if len(tgt) > 1 and isinstance(tgt[1], str) else ""
                # (b) 대상이 goal 컨테이너(craft/stack) → 링크 불가
                # (c) 대상이 비어있지 않은 속성 보유 = 다른 기믹(ice/chain/grass/frog/bomb/curtain/
                #     teleport/unknown) 또는 또다른 link → 링크 불가. 게임 링크는 'plain 타일 1:1'만
                #     유효하며, 다른 기믹이 얹힌 타일에 연결하면 동작이 깨진다(배치 후 기믹배치가
                #     링크 대상 위에 얹히는 케이스). 이 경우 링크 속성만 제거(대상 기믹은 보존).
                if ttype.startswith("craft_") or ttype.startswith("stack_") or tattr != "":
                    data[1] = ""
                    stripped += 1
                    continue
        if stripped:
            logger.warning(
                f"[LINK_SANITIZE] stripped {stripped} invalid link attr(s) "
                f"(target missing/OOB, or target is goal/gimmick/link — link needs plain 1:1 target)"
            )
        return level

    def _diversify_container_inner_tiles(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[INNER_DIVERSIFY] craft/stack 내부 타일 명시 다양화 bake.

        문제: 패턴 기반 프로덕션 레벨은 필드 타일이 전부 명시(t0 없음) → 컨테이너 내부만
        t0 분배 대상. 게임 분배(DB_Level.ShuffleEmptyTiles)는 '같은 타입 3개 = 1세트' 단위
        배정이라 내부 3슬롯이 단색 뭉치로 확정된다(예: craft 내부 = t8,t8,t8). 의도 동작은
        내부도 필드 일반 타일처럼 골고루 배출.

        수정: 게임 분배 포트(assign_t0_tiles)로 내부 타입을 먼저 확정한 뒤, 컨테이너 내
        중복 타입 슬롯을 필드의 '다른 타입' 일반 타일과 라벨 스왑(순수 순열)하고 명시
        신포맷(td[2]=[cnt,"tX_tY_.."], v1.10.382+, 게임 리터럴 스폰)으로 출고한다.
        순열이므로 전역 타입별 카운트 불변 → ÷3 완전 보존. 게임 코드 무변경.

        적용 조건: 필드 t0 == 0 일 때만. 필드 t0가 있으면 게임 분배가 자연스럽게 섞어주는
        원래 동작이므로 건드리지 않음(명시 bake 시 남은 t0 재분배와 어긋날 위험도 회피).
        'key' 슬롯은 고정 — unlockTile 키는 t0 슬롯에만 스폰 가능하므로 내부에 보존 필수.
        """
        import random as _random

        num_layers = int(level.get("layer", 0) or 0)
        containers: List[Tuple[int, str, List]] = []  # (layer_idx, pos, td)
        field_swappable: List[Tuple[int, str, List]] = []  # 명시 t1~t15 일반 타일
        concrete: Dict[str, int] = {}
        field_t0 = 0

        for i in range(num_layers):
            layer = level.get(f"layer_{i}")
            tiles = layer.get("tiles") if isinstance(layer, dict) else None
            if not isinstance(tiles, dict):
                continue
            for pos, td in tiles.items():
                if not (isinstance(td, list) and td and isinstance(td[0], str)):
                    continue
                tt = td[0]
                if tt == "t0":
                    field_t0 += 1
                elif tt.startswith("craft_") or tt.startswith("stack_"):
                    # count-only(구포맷)만 대상. 이미 명시 inner면 보존.
                    if (len(td) > 2 and isinstance(td[2], list) and td[2]
                            and isinstance(td[2][0], (int, float)) and int(td[2][0]) > 0
                            and not (len(td[2]) > 1 and isinstance(td[2][1], str) and td[2][1])):
                        containers.append((i, pos, td))
                elif tt.startswith("t") and tt[1:].isdigit():
                    concrete[tt] = concrete.get(tt, 0) + 1
                    if 1 <= int(tt[1:]) <= 15:
                        field_swappable.append((i, pos, td))

        if not containers or field_t0 > 0:
            return level

        total_inner = sum(int(td[2][0]) for _, _, td in containers)
        if total_inner <= 0:
            return level

        # 게임 분배 재현 (solver._clearability_type_counts와 동일 파라미터)
        from .bot_simulator import TileDistributor
        use_tile_count = min(int(level.get("useTileCount", 6) or 6), 15)
        existing = [t for t in concrete if t[1:].isdigit()]
        offset = 0
        if existing:
            mn = min(int(t[1:]) for t in existing)
            offset = mn - 1 if mn > use_tile_count else 0
        rand_seed = int(level.get("randSeed", 0) or 0)
        try:
            assigns = TileDistributor.assign_t0_tiles(
                t0_count=total_inner, use_tile_count=use_tile_count,
                rand_seed=rand_seed,
                shuffle_tile=level.get("xShuffleTile", 0),
                type_imbalance=level.get("xTypeImbalance", 0),
                unlock_tile=level.get("unlockTile", level.get("xUnlockTile", 0)),
                tile_type_offset=offset, existing_tile_counts=concrete,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[INNER_DIVERSIFY] 분배 재현 실패, 스킵: {e}")
            return level
        if len(assigns) != total_inner:
            logger.warning(f"[INNER_DIVERSIFY] 분배 수 불일치({len(assigns)}!={total_inner}), 스킵")
            return level

        # 안전 검증용 전역 멀티셋 (필드 + 내부) — 스왑은 순열이므로 불변이어야 함
        def _global_counts() -> Dict[str, int]:
            c: Dict[str, int] = dict(concrete)
            for s in assigns:
                c[s] = c.get(s, 0) + 1
            return c

        before_counts = _global_counts()

        # 컨테이너별 슬롯 배정 (결정적 순서) + 중복 슬롯 ↔ 필드 라벨 스왑
        rng = _random.Random(rand_seed * 1000003 + 8161)
        containers.sort(key=lambda c: (c[0], c[1]))
        swapped = 0
        cursor = 0
        for _, _, td in containers:
            cnt = int(td[2][0])
            slots = assigns[cursor:cursor + cnt]
            for k in range(cnt):
                if slots[k] == "key" or slots[k] not in slots[:k]:
                    continue  # key 고정 / 중복 아님
                cur_types = set(s for s in slots if s != "key")
                # 1순위: 컨테이너에 없는 타입 필드 / 2순위: 현재 슬롯과 다른 타입
                strict = [f for f in field_swappable if f[2][0] not in cur_types]
                relaxed = [f for f in field_swappable if f[2][0] != slots[k]]
                pool = strict or relaxed
                if not pool:
                    continue  # 스왑 불가 → 부분 다양화 폴백
                pick = rng.choice(pool)
                slots[k], pick[2][0] = pick[2][0], slots[k]  # 라벨 스왑 (순열)
                swapped += 1
            assigns[cursor:cursor + cnt] = slots
            # 명시 신포맷 출고. id_string[k]=게임 stackCTileList[k] — 다양화 목적상 순서 무관,
            # 분배 슬롯 순서 그대로 기록 (프론트 bake/E6는 자체 reverse 대칭으로 처리).
            td[2] = [cnt, "_".join(slots)]
            cursor += cnt

        # 순열 불변 검증 — 필드 concrete 재집계 + 내부 합산이 before와 동일해야 함
        after_field: Dict[str, int] = {}
        for f in field_swappable:
            after_field[f[2][0]] = after_field.get(f[2][0], 0) + 1
        # field_swappable 외 concrete(t16 등)도 합산
        for t, c in concrete.items():
            if not (1 <= int(t[1:]) <= 15):
                after_field[t] = after_field.get(t, 0) + c
        after_counts = dict(after_field)
        for s in assigns:
            after_counts[s] = after_counts.get(s, 0) + 1
        if after_counts != before_counts:
            logger.error(f"[INNER_DIVERSIFY] 순열 불변 위반! before={before_counts} after={after_counts}")

        logger.info(
            f"[INNER_DIVERSIFY] 컨테이너 {len(containers)}개 내부 {total_inner}슬롯 명시 bake "
            f"(스왑 {swapped}회, seed={rand_seed})"
        )
        return level

    def _remove_out_of_bounds_tiles(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[OOB_REPAIR] 레이어 선언 col/row 밖 타일 제거.

        타일 키는 "x_y"(x=col축, y=row축). 게임은 선언 col/row로 그리드를 만들고
        범위 밖 타일은 렌더/픽 불가 → 매칭 3배수가 깨져 클리어 불가가 된다.
        후속 변형 단계(위치 시프트/피라미드/경계 트림)가 경계를 넘길 수 있어, 반환 직전
        단일 초크포인트에서 무조건 잘라낸다. 제거로 깨진 ÷3은 호출측 후속 단계가 재보장.
        """
        num_layers = level.get("layer", 0)
        removed = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            layer = level.get(layer_key)
            if not layer:
                continue
            tiles = layer.get("tiles")
            if not tiles:
                continue
            try:
                lc = int(layer.get("col")); lr = int(layer.get("row"))
            except (TypeError, ValueError):
                continue
            kept = {}
            for pos, data in tiles.items():
                if "_" not in pos:
                    kept[pos] = data
                    continue
                try:
                    x, y = pos.split("_"); x = int(x); y = int(y)
                except ValueError:
                    kept[pos] = data
                    continue
                if 0 <= x < lc and 0 <= y < lr:
                    kept[pos] = data
                else:
                    removed += 1
            if len(kept) != len(tiles):
                level[layer_key]["tiles"] = kept
        if removed:
            logger.warning(
                f"[OOB_REPAIR] removed {removed} out-of-bounds tile(s) "
                f"(would be grid-culled → unclearable); ÷3 re-guaranteed downstream"
            )
        return level

    def _fix_visual_centering(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[v15.40] 최종 시각적 중앙정렬 보정 (위치 시프트 방식).

        타일 종류와 개수를 변경하지 않고, 레이어 내 모든 타일의 위치를
        일괄 이동하여 시각적 중심을 Layer 0에 맞춤.

        Position format: "row_col" (예: "1_2" = row 1, col 2)
        렌더링 시 홀수 레이어는 row와 col 모두 +0.5 오프셋 적용.
        """
        num_layers = level.get("layer", 1)
        if num_layers < 2:
            return level

        # 고정 레이아웃/패턴 모드 레벨은 형태 보존이 우선
        if level.get("_skip_tile_redistribution") or level.get("_preserve_pattern"):
            return level

        # Layer 0의 시각적 중심 계산 (기준)
        l0_tiles = level.get("layer_0", {}).get("tiles", {})
        if not l0_tiles:
            return level

        l0_rows = [int(p.split("_")[0]) for p in l0_tiles.keys() if "_" in p]
        l0_cols = [int(p.split("_")[1]) for p in l0_tiles.keys() if "_" in p]
        if not l0_cols:
            return level

        ref_row_center = (min(l0_rows) + max(l0_rows)) / 2
        ref_col_center = (min(l0_cols) + max(l0_cols)) / 2

        for i in range(1, num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if len(tiles) < 2:
                continue

            is_odd = i % 2 == 1
            offset = 0.5 if is_odd else 0

            # 현재 레이어의 시각적 중심 계산
            cur_rows = [int(p.split("_")[0]) for p in tiles.keys() if "_" in p]
            cur_cols = [int(p.split("_")[1]) for p in tiles.keys() if "_" in p]
            if not cur_cols:
                continue

            vis_row = (min(cur_rows) + max(cur_rows)) / 2 + offset
            vis_col = (min(cur_cols) + max(cur_cols)) / 2 + offset

            # 시프트량 계산 (정수만 가능 - 타일은 정수 좌표)
            # math.floor(x + 0.5) 사용 → 0.5 차이를 -1로 정확히 보정
            import math
            diff_row = ref_row_center - vis_row
            diff_col = ref_col_center - vis_col
            shift_row = math.floor(diff_row + 0.5) if abs(diff_row) >= 0.4 else 0
            shift_col = math.floor(diff_col + 0.5) if abs(diff_col) >= 0.4 else 0

            if shift_row == 0 and shift_col == 0:
                continue

            # 그리드 범위 확인
            grid_rows = int(level[layer_key].get("row", 9))
            grid_cols = int(level[layer_key].get("col", 9))

            # 시프트 후 모든 타일이 그리드 안에 있는지 확인
            new_min_row = min(cur_rows) + shift_row
            new_max_row = max(cur_rows) + shift_row
            new_min_col = min(cur_cols) + shift_col
            new_max_col = max(cur_cols) + shift_col

            # 그리드 밖으로 나가면 시프트를 클램프
            if new_min_row < 0:
                shift_row -= new_min_row
            elif new_max_row >= grid_rows:
                shift_row -= (new_max_row - grid_rows + 1)

            if new_min_col < 0:
                shift_col -= new_min_col
            elif new_max_col >= grid_cols:
                shift_col -= (new_max_col - grid_cols + 1)

            if shift_row == 0 and shift_col == 0:
                continue

            # 모든 타일 위치를 일괄 이동 (타일 데이터는 보존)
            new_tiles = {}
            for pos, tile_data in tiles.items():
                if "_" not in pos:
                    new_tiles[pos] = tile_data
                    continue
                r, c = int(pos.split("_")[0]), int(pos.split("_")[1])
                new_pos = f"{r + shift_row}_{c + shift_col}"
                new_tiles[new_pos] = tile_data

            level[layer_key]["tiles"] = new_tiles
            logger.debug(f"[VISUAL_CENTER_SHIFT] Layer {i}: shift=({shift_row},{shift_col})")

        return level

    def _sync_layer_num_fields(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synchronize all layer 'num' fields with actual tile counts.

        CRITICAL FIX: Ensures num field always matches actual tiles count.
        This prevents t0 distribution calculation errors caused by
        num/tiles count mismatch.

        Args:
            level: Level data to synchronize

        Returns:
            Level with synchronized num fields
        """
        num_layers = level.get("layer", 8)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            if layer_key in level and "tiles" in level[layer_key]:
                actual_count = len(level[layer_key]["tiles"])
                stored_num = int(level[layer_key].get("num", 0))

                if actual_count != stored_num:
                    logger.warning(
                        f"[_sync_layer_num_fields] {layer_key} num mismatch: "
                        f"stored={stored_num}, actual={actual_count}. Fixing."
                    )
                    level[layer_key]["num"] = str(actual_count)

        return level

    def _validate_playability(self, level: Dict[str, Any], level_number: Optional[int] = None) -> Dict[str, Any]:
        """
        Validate that a level is playable (can be cleared).

        Rules for playability:
        1. Total matchable tiles must be divisible by 3
        2. Each tile type count must be divisible by 3 (including t0 tiles after distribution)
        3. Total tiles must meet minimum count (industry standard)
           - Level 1-5 (tutorial): minimum 9 tiles (3 sets)
           - Level 6+: minimum 18 tiles (6 sets)

        CRITICAL: This function now simulates actual t0 tile distribution to ensure
        the final tile type counts are all divisible by 3.

        Args:
            level: The level data to validate
            level_number: Optional level number for tutorial exception

        Returns:
            Dict with is_playable (bool), total_tiles (int), bad_types (list), below_minimum (bool)
        """
        num_layers = level.get("layer", 8)
        type_counts: Dict[str, int] = {}
        total_matchable = 0
        t0_count = 0

        # First pass: count regular tiles and t0 tiles separately
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Count internal tiles for craft/stack as t0
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            t0_count += internal_count
                            total_matchable += internal_count
                    else:
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        total_matchable += 1

        # CRITICAL: Simulate actual t0 tile distribution using bot_simulator logic
        # This gives us the REAL final tile type counts
        if t0_count > 0:
            use_tile_count = level.get("useTileCount", 5)
            rand_seed = level.get("randSeed", 0)
            shuffle_tile = level.get("xShuffleTile", 0)
            type_imbalance = level.get("xTypeImbalance", 0)
            unlock_tile = level.get("unlockTile", level.get("xUnlockTile", 0))

            # Detect tile type offset from existing tiles (e.g., t11~t15 instead of t1~t5)
            tile_type_offset = 0
            if type_counts:
                existing_t_types = [t for t in type_counts.keys() if t.startswith("t") and t[1:].isdigit()]
                if existing_t_types:
                    min_tile_num = min(int(t[1:]) for t in existing_t_types)
                    if min_tile_num > use_tile_count:
                        tile_type_offset = min_tile_num - 1

            # Get the actual t0 distribution
            t0_assignments = TileDistributor.assign_t0_tiles(
                t0_count=t0_count,
                use_tile_count=use_tile_count,
                rand_seed=rand_seed,
                shuffle_tile=shuffle_tile,
                type_imbalance=type_imbalance,
                unlock_tile=unlock_tile,
                tile_type_offset=tile_type_offset,
                existing_tile_counts=type_counts  # For GetToAddIndexList logic
            )

            # Count the distributed t0 tiles by type
            for tile_type in t0_assignments:
                type_counts[tile_type] = type_counts.get(tile_type, 0) + 1

        # Check for types with count not divisible by 3
        bad_types = [(t, c) for t, c in type_counts.items() if c % 3 != 0]

        # Check minimum tile count based on level number
        # Tutorial levels (1-5) have lower minimum, regular levels (6+) need more tiles
        # [수정] min60은 유닛조립(_unit_assembly 마커)에만 적용. 일반 레벨은 기존 하한(튜토9/18)
        # 유지 — min60을 전체 Lv11+에 걸면 일반 레벨이 2배로 어려워져 RL 검증 대량 실패(회귀).
        # [유닛조립 v3] min60 은 v1(조밀 채움) 시절 밀도 확보용이었다. v3 는 '성긴 대칭'이
        # 설계 목표라 이 하한이 오히려 `_ensure_minimum_tiles` 를 상시 호출해 층을 통짜로
        # 메워버렸다(실측: 빌더 6타일 → 채움 후 7×3 통짜 21타일). 계획서대로 하한을 폐기하고
        # 타일 수는 결과값으로 둔다. 일반 하한(18)은 그대로 적용해 빈 레벨은 막는다.
        if level_number is not None and level_number <= 5:
            min_tiles = self.TUTORIAL_MIN_TILE_COUNT
        else:
            min_tiles = self.MIN_TILE_COUNT
        below_minimum = total_matchable < min_tiles

        # Level is playable if: no bad types, divisible by 3, and meets minimum
        is_playable = len(bad_types) == 0 and total_matchable % 3 == 0 and not below_minimum

        return {
            "is_playable": is_playable,
            "total_tiles": total_matchable,
            "bad_types": bad_types,
            "type_counts": type_counts,
            "below_minimum": below_minimum,
            "min_required": min_tiles
        }

    def _fill_symmetric_for_units(self, level: Dict[str, Any], need: int,
                                  tile_types: List[str]) -> int:
        """[유닛조립 전용 채움] 좌우대칭 쌍으로만 타일을 추가. 반환: 추가한 타일 수.

        기본 채움(`_ensure_minimum_tiles` 본문)은 좌→우 순차 스캔이라 유닛 레벨의
        성긴 대칭 구조를 통짜 사각형으로 뭉갠다. 여기서는:
          - 아래층부터(위층은 성기게 유지 = 탑 실루엣 보존)
          - 기존 타일에 **상하좌우로 인접한** 빈칸만(흩어짐 방지)
          - 중심축 미러 쌍으로 **2칸씩** 추가(대칭 유지)
        남은 부족분은 호출부의 기본 경로가 마무리한다(멱등).
        """
        if need <= 0:
            return 0
        try:
            n = int(level.get("layer", 0) or 0)
        except (TypeError, ValueError):
            return 0
        added = 0
        ttypes = tile_types or ["t1"]
        for layer_idx in range(n):                      # 바닥층부터
            if added >= need:
                break
            L = level.get(f"layer_{layer_idx}")
            if not isinstance(L, dict):
                continue
            tiles = L.get("tiles")
            if not isinstance(tiles, dict) or not tiles:
                continue
            try:
                col, row = int(L.get("col")), int(L.get("row"))
            except (TypeError, ValueError):
                continue
            # 기존 타일에 인접한 빈칸 후보(중심축 왼쪽만 — 오른쪽은 미러로 채움)
            # [세로 우선] 가로 이웃(dx≠0)만 채우면 한 줄이 통째로 메워져 '띠 사각형'이 된다.
            # 세로 방향(dy≠0) 후보를 우선 소비해 실루엣이 세로로 자라게 한다.
            cands = []
            for pos in list(tiles.keys()):
                try:
                    x, y = map(int, pos.split("_"))
                except ValueError:
                    continue
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < col and 0 <= ny < row):
                        continue
                    mx = col - 1 - nx
                    if mx == nx or not (0 <= mx < col):
                        continue                        # 중심열은 쌍이 안 됨 → 스킵
                    np, mp = f"{nx}_{ny}", f"{mx}_{ny}"
                    if np in tiles or mp in tiles:
                        continue
                    if nx > mx:
                        np, mp = mp, np                 # 항상 왼쪽 먼저(중복 후보 방지)
                    cands.append((np, mp, 0 if dy != 0 else 1))   # 0=세로(우선), 1=가로

            def _row_fill(r_idx: int) -> int:
                """그 행이 이미 얼마나 찼는지 — 꽉 찬 행에 더 붙이면 띠가 된다."""
                return sum(1 for p in tiles if p.endswith(f"_{r_idx}"))

            # 세로 후보 먼저, 그다음 '덜 찬 행' 순
            def _key(c):
                np = c[0]
                try:
                    ry = int(np.split("_")[1])
                except (ValueError, IndexError):
                    ry = 0
                return (c[2], _row_fill(ry))
            cands.sort(key=_key)

            seen = set()
            for np, mp, _pri in cands:
                if added + 2 > need:
                    break
                if np in seen or mp in seen or np in tiles or mp in tiles:
                    continue
                try:
                    ry = int(np.split("_")[1])
                except (ValueError, IndexError):
                    ry = 0
                # [띠 방지] 이미 폭의 2/3 이상 찬 행은 더 채우지 않는다(통짜 가로줄 억제).
                if _row_fill(ry) >= max(2, int(col * 2 / 3)):
                    continue
                t = ttypes[(added // 3) % len(ttypes)]
                tiles[np] = [t, ""]
                tiles[mp] = [t, ""]
                seen.add(np)
                seen.add(mp)
                added += 2
            L["num"] = str(len(tiles))
        if added:
            logger.info(f"[UNIT_FILL] 대칭 쌍으로 {added}타일 보충(통짜 채움 방지)")
        return added

    def _ensure_minimum_tiles(
        self,
        level: Dict[str, Any],
        params: GenerationParams,
        min_required: int
    ) -> Dict[str, Any]:
        """
        Ensure level has at least the minimum required number of tiles.

        If the level has fewer tiles than required, add tiles to meet minimum.
        Tiles are added in sets of 3 to maintain match-3 game rules.

        Args:
            level: The level data
            params: Generation parameters
            min_required: Minimum number of tiles required

        Returns:
            Updated level with minimum tiles ensured
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 15)

        # Count current tiles (including color-named tiles like "red", "blue", etc.)
        current_tiles = 0
        # Define valid matchable tile types (t-prefixed and color names)
        color_tiles = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            current_tiles += int(tile_data[2][0]) if tile_data[2][0] else 0
                    elif tile_type.startswith("t") or tile_type in color_tiles:
                        current_tiles += 1

        if current_tiles >= min_required:
            return level

        # Calculate tiles needed (in sets of 3)
        tiles_needed = min_required - current_tiles
        sets_needed = (tiles_needed + 2) // 3  # Round up to sets of 3
        tiles_to_add = sets_needed * 3

        logger.info(f"[_ensure_minimum_tiles] Current: {current_tiles}, Min: {min_required}, Adding: {tiles_to_add}")

        # Get available tile types from existing tiles to preserve t0 if used
        existing_tile_types = set()
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and tile_data:
                    tile_type = tile_data[0]
                    if tile_type.startswith("t") and not tile_type.startswith("craft_") and not tile_type.startswith("stack_"):
                        existing_tile_types.add(tile_type)

        # Use existing tile types if available (preserves t0), otherwise fallback to t1~t{useTileCount}
        if existing_tile_types:
            valid_tile_types = sorted(list(existing_tile_types))
        else:
            valid_tile_types = [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Find positions to add tiles (prefer upper layers, avoid existing tiles)
        added = 0
        # [유닛조립 대칭 채움] 유닛 레벨은 좌우대칭 성긴 구조가 정체성인데, 아래 기본 채움은
        # 최상층부터 좌→우·위→아래 **순차 스캔**으로 빈칸을 메워 통짜 사각형을 만든다.
        # (실측: v3 빌더가 6타일을 놓았는데 최소치 미달로 채움이 돌아 7×3 통짜 21타일이 됨.)
        # 유닛 레벨이면 대칭 채움을 먼저 시도하고, 남은 부족분만 아래 기본 경로로 넘긴다.
        if level.get("_unit_assembly"):
            added += self._fill_symmetric_for_units(level, tiles_to_add - added, valid_tile_types)

        for layer_idx in range(num_layers - 1, -1, -1):  # Start from top layer
            layer_key = f"layer_{layer_idx}"
            if layer_key not in level:
                level[layer_key] = {"tiles": {}, "col": "8", "row": "8", "num": "0"}

            layer_tiles = level[layer_key].get("tiles", {})
            col = int(level[layer_key].get("col", 8))
            row = int(level[layer_key].get("row", 8))

            # Find empty positions
            for y in range(row):
                for x in range(col):
                    if added >= tiles_to_add:
                        break
                    pos = f"{x}_{y}"
                    if pos not in layer_tiles:
                        # Add tile - distribute types evenly in sets of 3
                        tile_type_idx = (added // 3) % len(valid_tile_types)
                        tile_type = valid_tile_types[tile_type_idx]
                        layer_tiles[pos] = [tile_type, ""]
                        added += 1

                if added >= tiles_to_add:
                    break

            level[layer_key]["tiles"] = layer_tiles
            level[layer_key]["num"] = str(len(layer_tiles))

            if added >= tiles_to_add:
                break

        logger.info(f"[_ensure_minimum_tiles] Added {added} tiles to meet minimum")

        return level

    def _force_fix_tile_counts(self, level: Dict[str, Any], params: GenerationParams) -> Dict[str, Any]:
        """
        Aggressively fix tile counts to ensure playability.
        This is a last-resort function that will force-fix any remaining issues.

        CRITICAL: This function now uses actual t0 distribution simulation to ensure
        the final tile type counts are all divisible by 3.

        PATTERN MODE: When preserve_pattern is True, we NEVER delete tiles -
        only redistribute tile types to fix divisibility issues.
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 5)
        rand_seed = level.get("randSeed", 0)

        # PATTERN PRESERVATION: Check if we should preserve tile positions
        preserve_pattern = level.get("_preserve_pattern", False)

        # CRITICAL: First fix t0 (goal internals) to be divisible by 3
        # This must happen BEFORE removing regular tiles, because t0 affects total
        goal_tiles = []
        t0_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            t0_count += internal_count
                            goal_tiles.append((i, pos, tile_data))

        t0_remainder = t0_count % 3
        # CRITICAL: Check if already fixed to prevent duplicate adjustments
        already_fixed = level.get("_goal_divisibility_fixed", False)

        if t0_remainder != 0 and goal_tiles and not already_fixed:
            # Add (3 - remainder) to goal internal counts to make t0 divisible by 3
            tiles_to_add = 3 - t0_remainder
            goal_idx = 0
            while tiles_to_add > 0:
                _, _, tile_data = goal_tiles[goal_idx % len(goal_tiles)]
                if isinstance(tile_data[2], list) and tile_data[2]:
                    tile_data[2][0] = int(tile_data[2][0]) + 1
                    tiles_to_add -= 1
                    t0_count += 1
                goal_idx += 1
                if goal_idx > len(goal_tiles) * 3:
                    break
            level["_goal_divisibility_fixed"] = True  # Mark as fixed
        elif already_fixed and t0_remainder != 0:
            logger.debug("[_force_fix_tile_counts] Skipping t0 adjustment (already fixed)")

            # Update goalCount
            goalCount = {}
            for _, _, tile_data in goal_tiles:
                tile_type = tile_data[0]
                internal_count = int(tile_data[2][0]) if isinstance(tile_data[2], list) and tile_data[2] else 0
                goalCount[tile_type] = goalCount.get(tile_type, 0) + internal_count
            level["goalCount"] = goalCount

        # Now count all tiles including updated t0 WITH ACTUAL DISTRIBUTION
        type_counts: Dict[str, int] = {}
        type_positions: Dict[str, List[Tuple[int, str]]] = {}
        total_matchable = 0
        updated_t0_count = 0

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            updated_t0_count += internal_count
                            total_matchable += internal_count
                    else:
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        total_matchable += 1
                        if tile_type not in type_positions:
                            type_positions[tile_type] = []
                        type_positions[tile_type].append((i, pos))

        # CRITICAL: Simulate actual t0 distribution to get real type counts
        if updated_t0_count > 0:
            # Detect tile type offset from existing tiles
            tile_type_offset = 0
            if type_counts:
                existing_t_types = [t for t in type_counts.keys() if t.startswith("t") and t[1:].isdigit()]
                if existing_t_types:
                    min_tile_num = min(int(t[1:]) for t in existing_t_types)
                    if min_tile_num > use_tile_count:
                        tile_type_offset = min_tile_num - 1

            t0_assignments = TileDistributor.assign_t0_tiles(
                t0_count=updated_t0_count,
                use_tile_count=use_tile_count,
                rand_seed=rand_seed,
                shuffle_tile=level.get("xShuffleTile", 0),
                type_imbalance=level.get("xTypeImbalance", 0),
                unlock_tile=level.get("unlockTile", level.get("xUnlockTile", 0)),
                tile_type_offset=tile_type_offset,
                existing_tile_counts=type_counts  # For GetToAddIndexList logic
            )
            for tile_type in t0_assignments:
                type_counts[tile_type] = type_counts.get(tile_type, 0) + 1

        # If total is not divisible by 3, adjust tiles
        # PATTERN MODE: NEVER delete - always add tiles to preserve shape
        total_remainder = total_matchable % 3
        cols, rows = params.grid_size if params and params.grid_size else (7, 7)

        if total_remainder != 0:
            if preserve_pattern:
                # PATTERN MODE: Priority-based approach to preserve shape
                # 1. Adjust goal internal tile count (preserves shape 100%)
                # 2. Add tiles adjacent to pattern (last resort)
                #
                # CRITICAL: Check if already fixed to prevent duplicate adjustments
                already_fixed = level.get("_goal_divisibility_fixed", False)
                tiles_to_add = 3 - total_remainder
                pattern_fix_success = already_fixed

                # === PRIORITY 1: Adjust goal internal tile count ===
                # Collect goal tiles with internal counts
                if not pattern_fix_success:
                    force_goal_tiles = []
                    for i in range(num_layers):
                        layer_key = f"layer_{i}"
                        tiles = level.get(layer_key, {}).get("tiles", {})
                        for pos, tile_data in tiles.items():
                            if isinstance(tile_data, list) and len(tile_data) > 0:
                                tile_type = tile_data[0]
                                if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                                    if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                        force_goal_tiles.append((i, pos, tile_data))

                    if force_goal_tiles:
                        goal_idx = 0
                        added_to_goal = 0
                        while added_to_goal < tiles_to_add and goal_idx < len(force_goal_tiles) * 3:
                            layer_idx, pos, tile_data = force_goal_tiles[goal_idx % len(force_goal_tiles)]
                            if isinstance(tile_data[2], list) and tile_data[2]:
                                current_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                tile_data[2][0] = current_count + 1
                                added_to_goal += 1
                                total_matchable += 1
                            goal_idx += 1

                        if added_to_goal >= tiles_to_add:
                            pattern_fix_success = True
                            level["_goal_divisibility_fixed"] = True  # Mark as fixed
                            logger.info(f"[FORCE_FIX_PATTERN] Added {added_to_goal} to goal internal tiles (shape preserved)")

                        # Update goalCount
                        goalCount = {}
                        for _, _, td in force_goal_tiles:
                            tile_type = td[0]
                            internal_count = int(td[2][0]) if isinstance(td[2], list) and td[2] else 0
                            goalCount[tile_type] = goalCount.get(tile_type, 0) + internal_count
                        level["goalCount"] = goalCount

                # === PRIORITY 2: Add tiles adjacent to pattern (last resort) ===
                if not pattern_fix_success:
                    added_count = 0
                    logger.warning("[FORCE_FIX_PATTERN] No goal tiles, falling back to adjacent tile addition")

                    # Helper: Find positions adjacent to existing tiles
                    def get_adjacent_empty_positions_for_layer(layer_idx: int) -> List[str]:
                        is_odd_layer = layer_idx % 2 == 1
                        layer_cols = cols if is_odd_layer else cols + 1
                        layer_rows = rows if is_odd_layer else rows + 1
                        layer_tiles = level.get(f"layer_{layer_idx}", {}).get("tiles", {})
                        used = set(layer_tiles.keys())

                        adjacent_empty = []
                        for pos in used:
                            parts = pos.split("_")
                            if len(parts) != 2:
                                continue
                            x, y = int(parts[0]), int(parts[1])
                            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                                nx, ny = x + dx, y + dy
                                if 0 <= nx < layer_cols and 0 <= ny < layer_rows:
                                    neighbor_pos = f"{nx}_{ny}"
                                    if neighbor_pos not in used and neighbor_pos not in adjacent_empty:
                                        adjacent_empty.append(neighbor_pos)
                        return adjacent_empty

                    for i in range(num_layers):
                        if added_count >= tiles_to_add:
                            break
                        layer_key = f"layer_{i}"
                        if not level.get(layer_key, {}).get("tiles", {}):
                            continue

                        adjacent_positions = get_adjacent_empty_positions_for_layer(i)
                        random.shuffle(adjacent_positions)

                        for pos in adjacent_positions:
                            if added_count >= tiles_to_add:
                                break
                            level[layer_key]["tiles"][pos] = ["t1", ""]
                            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                            added_count += 1
                            total_matchable += 1
                            logger.debug(f"[FORCE_FIX_PATTERN] Added tile at {pos} on layer {i}")

                    if added_count >= tiles_to_add:
                        logger.info(f"[FORCE_FIX_PATTERN] Fallback: Added {added_count} adjacent tiles")
                    else:
                        logger.warning(f"[FORCE_FIX_PATTERN] Fallback: Could only add {added_count}/{tiles_to_add} tiles")
            else:
                # Non-pattern mode: remove tiles as before
                tiles_to_remove = total_remainder

                # Find removable tiles - prefer tiles without attributes, but allow any regular tile
                removable_no_attr = []
                removable_with_attr = []
                for i in range(num_layers):
                    layer_key = f"layer_{i}"
                    tiles = level.get(layer_key, {}).get("tiles", {})
                    for pos, tile_data in tiles.items():
                        if isinstance(tile_data, list) and len(tile_data) >= 2:
                            tile_type = tile_data[0]
                            attr = tile_data[1] if len(tile_data) > 1 else ""
                            if tile_type not in self.GOAL_TYPES and not tile_type.startswith("craft_") and not tile_type.startswith("stack_"):
                                if not attr:
                                    removable_no_attr.append((i, pos, tile_type))
                                else:
                                    removable_with_attr.append((i, pos, tile_type))

                # Combine: prefer no-attr tiles, but use attr tiles if needed
                removable = removable_no_attr + removable_with_attr

                random.shuffle(removable)
                for layer_idx, pos, _ in removable[:tiles_to_remove]:
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        # Recount and fix type distribution
        # CRITICAL: Must include t0 distribution to accurately identify which types need fixing
        type_counts = {}
        type_positions = {}
        recount_t0 = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            recount_t0 += int(tile_data[2][0]) if tile_data[2][0] else 0
                    else:
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        if tile_type not in type_positions:
                            type_positions[tile_type] = []
                        type_positions[tile_type].append((i, pos))

        # Include t0 distribution in type counts
        if recount_t0 > 0:
            tile_type_offset = 0
            if type_counts:
                existing_t_types = [t for t in type_counts.keys() if t.startswith("t") and t[1:].isdigit()]
                if existing_t_types:
                    min_tile_num = min(int(t[1:]) for t in existing_t_types)
                    if min_tile_num > use_tile_count:
                        tile_type_offset = min_tile_num - 1

            t0_assignments = TileDistributor.assign_t0_tiles(
                t0_count=recount_t0,
                use_tile_count=use_tile_count,
                rand_seed=rand_seed,
                shuffle_tile=level.get("xShuffleTile", 0),
                type_imbalance=level.get("xTypeImbalance", 0),
                unlock_tile=level.get("unlockTile", level.get("xUnlockTile", 0)),
                tile_type_offset=tile_type_offset,
                existing_tile_counts=type_counts  # For GetToAddIndexList logic
            )
            for tile_type in t0_assignments:
                type_counts[tile_type] = type_counts.get(tile_type, 0) + 1

        # Pair up types with remainder 1 and remainder 2
        max_iterations = 20
        for iteration in range(max_iterations):
            rem1 = [t for t, c in type_counts.items() if c % 3 == 1 and type_positions.get(t)]
            rem2 = [t for t, c in type_counts.items() if c % 3 == 2 and type_positions.get(t)]

            if not rem1 and not rem2:
                break

            if rem1 and rem2:
                # Move 1 tile from rem1 type to rem2 type
                # rem1 loses 1 → divisible by 3, rem2 gains 1 → divisible by 3
                type_a = rem1[0]
                type_b = rem2[0]
                if type_positions[type_a]:
                    layer_idx, pos = type_positions[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        level[layer_key]["tiles"][pos][0] = type_b
                        type_counts[type_a] -= 1
                        type_counts[type_b] = type_counts.get(type_b, 0) + 1
                        if type_b not in type_positions:
                            type_positions[type_b] = []
                        type_positions[type_b].append((layer_idx, pos))
            elif len(rem2) >= 2:
                # Two rem2 types: move 1 tile from each to the other
                # Before: A=2 mod 3, B=2 mod 3
                # After swapping 1 from A to B: A=1 mod 3, B=0 mod 3
                # Then swap another: A=0 mod 3, B=1 mod 3... not good
                # Better: Move 2 tiles from rem2[0] to rem2[1]
                # A: 2 -> 0 mod 3 (remove 2), B: 2 -> 1 mod 3 (add 2)... still bad
                # Actually: swap 1 tile from A to B
                # A becomes rem1 (c-1, mod 3 = 1), B becomes rem0 (c+1, mod 3 = 0)
                type_a = rem2[0]
                type_b = rem2[1]
                if type_positions[type_a]:
                    layer_idx, pos = type_positions[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        level[layer_key]["tiles"][pos][0] = type_b
                        type_counts[type_a] -= 1
                        type_counts[type_b] = type_counts.get(type_b, 0) + 1
                        if type_b not in type_positions:
                            type_positions[type_b] = []
                        type_positions[type_b].append((layer_idx, pos))
                        # type_a: rem2 -> rem1, type_b: rem2 -> rem0
            elif len(rem1) >= 2:
                # Two rem1 types: move 1 tile from rem1[0] to rem1[1]
                # A becomes rem0 (c-1), B becomes rem2 (c+1)
                type_a = rem1[0]
                type_b = rem1[1]
                if type_positions[type_a]:
                    layer_idx, pos = type_positions[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        level[layer_key]["tiles"][pos][0] = type_b
                        type_counts[type_a] -= 1
                        type_counts[type_b] = type_counts.get(type_b, 0) + 1
                        if type_b not in type_positions:
                            type_positions[type_b] = []
                        type_positions[type_b].append((layer_idx, pos))
                        # type_a: rem1 -> rem0, type_b: rem1 -> rem2
            else:
                # Single rem1 or rem2 with no pair - can't fix with simple swaps
                # PATTERN MODE: Redistribute to existing types instead of deleting
                if preserve_pattern:
                    # Try redistribution first: move tiles to a type with high count
                    redistributed = False

                    if rem2 and type_positions.get(rem2[0]):
                        # Move 2 tiles from rem2 type to a rem0 type with high count
                        type_a = rem2[0]
                        # Find best target: type with highest count that's divisible by 3
                        # CRITICAL FIX: Don't require target to be in type_positions
                        best_target = None
                        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                            if c % 3 == 0 and c >= 6 and t != type_a:
                                best_target = t
                                break
                        if not best_target:
                            for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                                if c % 3 == 0 and c >= 3 and t != type_a:
                                    best_target = t
                                    break
                        # Fallback: any type with count >= 3
                        if not best_target:
                            for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                                if c >= 3 and t != type_a:
                                    best_target = t
                                    break

                        if best_target and len(type_positions.get(type_a, [])) >= 2:
                            moved = 0
                            while moved < 2 and type_positions.get(type_a):
                                layer_idx, pos = type_positions[type_a].pop()
                                layer_key = f"layer_{layer_idx}"
                                if pos in level.get(layer_key, {}).get("tiles", {}):
                                    level[layer_key]["tiles"][pos][0] = best_target
                                    type_counts[type_a] -= 1
                                    type_counts[best_target] = type_counts.get(best_target, 0) + 1
                                    if best_target not in type_positions:
                                        type_positions[best_target] = []
                                    type_positions[best_target].append((layer_idx, pos))
                                    moved += 1
                            if moved == 2:
                                redistributed = True
                                logger.debug(f"[FORCE_FIX_PATTERN] Redistributed 2 tiles from {type_a} to {best_target}")

                    elif rem1 and type_positions.get(rem1[0]):
                        # Move 1 tile from rem1 type to a rem0 type
                        type_a = rem1[0]
                        best_target = None
                        # CRITICAL FIX: Don't require target to be in type_positions
                        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                            if c % 3 == 0 and c >= 3 and t != type_a:
                                best_target = t
                                break
                        # Fallback: any type with count >= 3
                        if not best_target:
                            for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                                if c >= 3 and t != type_a:
                                    best_target = t
                                    break

                        if best_target and type_positions.get(type_a):
                            layer_idx, pos = type_positions[type_a].pop()
                            layer_key = f"layer_{layer_idx}"
                            if pos in level.get(layer_key, {}).get("tiles", {}):
                                level[layer_key]["tiles"][pos][0] = best_target
                                type_counts[type_a] -= 1
                                type_counts[best_target] = type_counts.get(best_target, 0) + 1
                                if best_target not in type_positions:
                                    type_positions[best_target] = []
                                type_positions[best_target].append((layer_idx, pos))
                                redistributed = True
                                logger.debug(f"[FORCE_FIX_PATTERN] Redistributed 1 tile from {type_a} to {best_target}")

                    if redistributed:
                        continue  # Continue loop to handle the new type distribution

                    # Redistribution failed: do NOT delete pattern cells here.
                    # Defer ÷3 to _finalize_divisibility_guarantee (shape-safe add / container-internal).
                    logger.info("[_force_fix_tile_counts] Pattern mode: redistribution failed, deferring ÷3 fix to finalize (no tile removal)")
                    break

                # Need to remove tiles (non-pattern mode)
                if rem2 and type_positions.get(rem2[0]):
                    # Remove 2 tiles from rem2 type to make it rem0
                    type_a = rem2[0]
                    removed = 0
                    while removed < 2 and type_positions[type_a]:
                        layer_idx, pos = type_positions[type_a].pop()
                        layer_key = f"layer_{layer_idx}"
                        if pos in level.get(layer_key, {}).get("tiles", {}):
                            del level[layer_key]["tiles"][pos]
                            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                            type_counts[type_a] -= 1
                            removed += 1
                elif rem1 and type_positions.get(rem1[0]):
                    # Remove 1 tile from rem1 type to make it rem0
                    type_a = rem1[0]
                    if type_positions[type_a]:
                        layer_idx, pos = type_positions[type_a].pop()
                        layer_key = f"layer_{layer_idx}"
                        if pos in level.get(layer_key, {}).get("tiles", {}):
                            del level[layer_key]["tiles"][pos]
                            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                            type_counts[type_a] -= 1
                else:
                    break

        return level

    def _ensure_valid_t0_distribution(
        self, level: Dict[str, Any], max_attempts: int = 50
    ) -> Dict[str, Any]:
        """
        Ensure t0 tile distribution results in all tile types having counts divisible by 3.

        CRITICAL FIX for level playability:
        - t0 tiles are distributed at runtime based on randSeed
        - If any tile type ends up with count not divisible by 3, the level is UNPLAYABLE
        - This function validates the distribution and changes randSeed if needed

        Args:
            level: Level data with t0 tiles
            max_attempts: Maximum randSeed change attempts (default 50)

        Returns:
            Level with valid t0 distribution (randSeed may be changed)
        """
        # CRITICAL: Sync num fields BEFORE counting tiles
        # This ensures t0 distribution uses correct tile counts
        level = self._sync_layer_num_fields(level)

        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 5)

        # Count t0 tiles (including goal internal tiles)
        t0_count = 0
        regular_type_counts: Dict[str, int] = {}

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # Count internal tiles for goal tiles (craft/stack)
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            t0_count += internal_count
                    elif tile_type == "t0":
                        t0_count += 1
                    else:
                        # Regular tile (t1, t2, etc.)
                        regular_type_counts[tile_type] = regular_type_counts.get(tile_type, 0) + 1

        # If no t0 tiles, nothing to validate
        if t0_count == 0:
            return level

        # Detect tile type offset from existing tiles
        tile_type_offset = 0
        if regular_type_counts:
            existing_t_types = [t for t in regular_type_counts.keys() if t.startswith("t") and t[1:].isdigit()]
            if existing_t_types:
                min_tile_num = min(int(t[1:]) for t in existing_t_types)
                if min_tile_num > use_tile_count:
                    tile_type_offset = min_tile_num - 1

        original_seed = level.get("randSeed", 0)
        best_seed = original_seed
        best_bad_count = float('inf')

        for attempt in range(max_attempts):
            test_seed = original_seed + attempt if attempt > 0 else original_seed

            # Simulate t0 distribution with this seed
            t0_assignments = TileDistributor.assign_t0_tiles(
                t0_count=t0_count,
                use_tile_count=use_tile_count,
                rand_seed=test_seed,
                shuffle_tile=level.get("xShuffleTile", 0),
                type_imbalance=level.get("xTypeImbalance", 0),
                unlock_tile=level.get("unlockTile", level.get("xUnlockTile", 0)),
                tile_type_offset=tile_type_offset,
                existing_tile_counts=regular_type_counts  # For GetToAddIndexList logic
            )

            # Combine with regular tiles
            combined_counts = dict(regular_type_counts)
            for tile_type in t0_assignments:
                combined_counts[tile_type] = combined_counts.get(tile_type, 0) + 1

            # Check for types not divisible by 3
            bad_types = [(t, c) for t, c in combined_counts.items() if c % 3 != 0]

            if not bad_types:
                # Found valid distribution!
                if test_seed != original_seed:
                    level["randSeed"] = test_seed
                    logger.info(
                        f"[_ensure_valid_t0_distribution] Changed randSeed from {original_seed} to {test_seed} "
                        f"for valid t0 distribution (attempt {attempt + 1})"
                    )
                return level

            # Track best attempt
            if len(bad_types) < best_bad_count:
                best_bad_count = len(bad_types)
                best_seed = test_seed

        # Could not find perfect distribution - use best seed and adjust t0 count
        logger.warning(
            f"[_ensure_valid_t0_distribution] Could not find valid randSeed after {max_attempts} attempts. "
            f"Best seed {best_seed} has {best_bad_count} bad types. Adjusting t0 count."
        )

        # Strategy: Adjust t0 count to make distribution work
        # The issue is t0_count % 3 remainder being assigned to last type
        # Fix: Adjust goal internal tile counts to make t0_count divisible by 3
        t0_remainder = t0_count % 3
        # CRITICAL: Check if already fixed to prevent duplicate adjustments
        already_fixed = level.get("_goal_divisibility_fixed", False)

        if t0_remainder != 0 and not already_fixed:
            tiles_to_add = 3 - t0_remainder
            # Find goal tiles to adjust
            goal_tiles = []
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                            goal_tiles.append((i, pos, tile_data))

            # Add tiles to goal internals
            added = 0
            goal_idx = 0
            while added < tiles_to_add and goal_tiles:
                layer_idx, pos, tile_data = goal_tiles[goal_idx % len(goal_tiles)]
                if isinstance(tile_data[2], list) and tile_data[2]:
                    tile_data[2][0] = int(tile_data[2][0]) + 1
                    added += 1
                    logger.info(
                        f"[_ensure_valid_t0_distribution] Added 1 to goal at layer_{layer_idx}:{pos} "
                        f"for t0 divisibility"
                    )
                goal_idx += 1
                if goal_idx > len(goal_tiles) * 3:
                    break

            # Mark as fixed and update goalCount
            if added > 0:
                level["_goal_divisibility_fixed"] = True

            if goal_tiles:
                goalCount = {}
                for layer_idx, pos, tile_data in goal_tiles:
                    tile_type = tile_data[0]
                    internal_count = int(tile_data[2][0]) if isinstance(tile_data[2], list) and tile_data[2] else 0
                    goalCount[tile_type] = goalCount.get(tile_type, 0) + internal_count
                level["goalCount"] = goalCount
        elif already_fixed and t0_remainder != 0:
            logger.debug("[_ensure_valid_t0_distribution] Skipping t0 adjustment (already fixed)")

        # Use best seed found
        level["randSeed"] = best_seed
        return level

    def _grass_position_valid(self, level: Dict[str, Any], layer_idx: int, x: int, y: int) -> bool:
        """[홀짝 착각 방지] grass 감소는 '같은 층 4방 이웃' 픽으로만 일어남(게임 IsNearTile).
        근데 게임 홀짝 렌더에서 **짝수 층차(같은 홀짝)=0오프셋**이라 다른 층 타일이 grass 이웃 자리에
        정확히 겹쳐 보임 → 유저가 그걸 이웃으로 착각해 픽 → 무반응. (홀수 층차=0.5오프셋이라 구분됨.)

        유효 조건:
        - grass 자기 위치 (x,y): 같은 홀짝 최상위 층이 자기 층 = grass가 보임(안 덮임).
        - 각 격자내부 4방 이웃: 같은 홀짝 최상위 층이 (a)자기 층=진짜 클리어 이웃 or (b)없음(빈칸/홀수차만).
          다른 같은 홀짝 층 타일이 최상위면 → 착각 유발 → 무효.
        - 진짜 클리어 이웃 ≥2 (게임 grass remaining=2).
        """
        nlayers = int(level.get("layer", 0) or 0)
        parity = layer_idx % 2

        def top_same_parity(cx: int, cy: int) -> int:
            top = -1
            key = f"{cx}_{cy}"
            for m in range(nlayers):
                if m % 2 == parity and key in (level.get(f"layer_{m}", {}) or {}).get("tiles", {}):
                    top = m
            return top

        # grass 자기 위치가 같은 홀짝 최상위여야 보임(다른 짝수차 층이 덮으면 착각/미표시)
        if top_same_parity(x, y) != layer_idx:
            return False
        ld = level.get(f"layer_{layer_idx}", {}) or {}
        cols = int(ld.get("col", 8)); rows = int(ld.get("row", 8))
        clearable = 0
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if nx < 0 or nx >= cols or ny < 0 or ny >= rows:
                continue  # 격자 밖 = 이웃 없음(엣지, 착각 없음)
            top = top_same_parity(nx, ny)
            if top == -1:
                continue  # 같은 홀짝 타일 없음(빈칸/홀수차만) → 착각 없음, 클리어 이웃도 아님
            if top != layer_idx:
                return False  # 다른 같은 홀짝 층 타일이 이웃 자리에 겹쳐보임 → 착각
            clearable += 1  # top == layer_idx → 진짜 같은 층 클리어 이웃
        return clearable >= 2

    def _strip_confusing_grass(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """[일괄 안전망] 홀짝 0오프셋 착각 유발 grass → 같은 층 유효 위치로 이동(relocate), 없으면 제거.
        최종 좌표(피라미드/OOB 정리 후) 기준 판정 → 어느 배치 단계가 만들었든 공통 커버. 이동은 grass 개수 보존
        (튜토리얼 grass 소실 방지). 이동 대상 = 같은 층의 일반 타일(컨테이너/속성 없는) 중 규칙 유효 위치."""
        nlayers = int(level.get("layer", 0) or 0)
        relocated = 0
        removed = 0
        for li in range(nlayers):
            tiles = (level.get(f"layer_{li}", {}) or {}).get("tiles", {})
            for pos, td in list(tiles.items()):
                if not (isinstance(td, list) and len(td) >= 2):
                    continue
                eff = str(td[1])
                if eff != "grass" and not eff.startswith("grass_"):
                    continue
                try:
                    x, y = map(int, pos.split("_"))
                except ValueError:
                    continue
                if self._grass_position_valid(level, li, x, y):
                    continue
                # 착각유발 → 같은 층 유효 위치로 이동 시도(일반 타일: 속성없음 + 컨테이너 아님)
                moved = False
                for cand, ctd in tiles.items():
                    if cand == pos:
                        continue
                    if not (isinstance(ctd, list) and len(ctd) >= 1):
                        continue
                    base = str(ctd[0])
                    if base.startswith("craft") or base.startswith("stack") or base == "t0":
                        continue  # 컨테이너/미분배 t0 회피
                    if len(ctd) >= 2 and ctd[1]:
                        continue  # 이미 속성 있는 타일 회피
                    try:
                        cx, cy = map(int, cand.split("_"))
                    except ValueError:
                        continue
                    if self._grass_position_valid(level, li, cx, cy):
                        td[1] = ""                       # 원 위치 grass 해제
                        while len(ctd) < 2:
                            ctd.append("")
                        ctd[1] = "grass"                 # 유효 위치로 이동
                        moved = True
                        relocated += 1
                        break
                if not moved:
                    td[1] = ""
                    removed += 1
        if relocated or removed:
            logger.info(f"[grass 홀짝착각방지] 이동 {relocated}개 · 제거 {removed}개(유효위치 없음)")
        return level

    def _finalize_divisibility_guarantee(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        [v16] 최종 ÷3 클리어가능성 보장 — generate()의 모든 변형 단계 '이후', FINAL_REPAIR '직전'에
        딱 한 번 실행하는 권위 있는 게이트.

        왜 필요한가 (이전 시도들의 결함):
        - `_ensure_tile_count_divisible_by_3`(L883/891), `_ensure_valid_t0_distribution`(L981)는
          너무 일찍 호출된다. 이후 boundary 삭제(L1083) / pyramid(L1106) / centering(L1107)이
          타일 카운트를 다시 깨뜨리는데 재검사가 없다.
        - `_ensure_valid_t0_distribution`은 `_goal_divisibility_fixed` one-shot 가드가 있어 후속
          단계가 다시 깨도 재작동하지 못하고, 폴백이 craft/stack 내부 조정에만 의존한다.
        - 인라인 FINAL_REPAIR는 타일을 relabel만 하고 위치를 추가/삭제하지 않아 '총합 비÷3'을
          절대 못 고치며, t0 레벨(전체의 70%)은 카운트 자체를 보지도 않는다.
        결과적으로 fast path(skip_deadlock_check=True, 기본값)가 비÷3 = 클리어 불가능 레벨을 출고했다
        (실측 raw의 ~80%). 이 메서드가 모든 경우를 '맨 마지막'에 한 곳에서 처리한다. 멱등(재실행 안전).

        불변식(증명): t0 분배 후 모든 매칭타입(t1~t15)이 ÷3 ⟺ (concrete_total + t0_count) ≡ 0 (mod 3).
        key 타일은 unlockTile×3로 항상 ÷3이라 무관. 따라서 (concrete + t0)를 ÷3으로 맞추면 충분하고,
        concrete-only 레벨은 이어지는 FINAL_REPAIR가 per-type relabel로 마무리한다(총합 ÷3이면 항상 성공).

        조정 수단: '잉여 t0/타일 위치 제거'(추가 아님). 타일을 빼는 것은 블로킹/난이도를 완화할 뿐
        새 데드락을 만들 수 없어 가장 안전하다. r ∈ {1,2}개만 제거하므로 구조 영향도 미미.
        """
        level = self._sync_layer_num_fields(level)
        num_layers = int(level.get("layer", 0) or 0)
        preserve_pattern = bool(level.get("_preserve_pattern"))

        def _adjacent_empty_slots(need: int) -> List[Tuple[int, str]]:
            """패턴 보존용: 기존 타일에 인접한 빈 칸을 need개까지 찾는다 (홀짝 레이어 dim 반영)."""
            found: List[Tuple[int, str]] = []
            seen_global: set = set()
            for li in range(num_layers):
                if len(found) >= need:
                    break
                ld = level.get(f"layer_{li}", {}) or {}
                tiles = ld.get("tiles", {})
                if not tiles:
                    continue
                # [OOB_FIX] 실제 층 헤더(col/row)로 경계 계산.
                # 기존: phantom gridWidth/gridHeight(생성기가 절대 안 씀→기본7) 사용 →
                # 짝수 layer_0에 nx<8 허용, 실헤더(6/7) 무시 → ÷3 애드백 타일이 헤더 밖 → 인게임 클리어불가.
                try:
                    lc = int(ld.get("col"))
                    lr = int(ld.get("row"))
                except (TypeError, ValueError):
                    continue  # 헤더 불명 → 이 층은 슬롯 소스에서 제외
                used = set(tiles.keys())

                # [모양 보존] 후보를 '실루엣을 덜 망가뜨리는' 순으로 정렬해서 고른다.
                # 기존엔 인접 빈칸을 **발견 순서 그대로** 집어서, 하트 같은 대칭 실루엣의
                # 바깥으로 튀어나온 자리에 1~2개가 얹혔다(실측: 8_7x7 템플릿 y=5 `...#...`
                # → 생성 결과 `.#.#...`, 좌우대칭 깨짐 = "이가 빠진/튀어나온" 인상).
                # 우선순위:
                #   0) 대칭 짝 자리 — 이 칸의 좌우 미러에 타일이 있으면 채워서 대칭 복원
                #   1) 실루엣 내부 구멍 — 4방이 전부 타일(밖으로 안 튀어나옴)
                #   2) 이웃이 많은 칸 — 덜 돌출
                cand: List[Tuple[Tuple[int, int, int], Tuple[int, str]]] = []
                for pos in list(used):
                    p = pos.split("_")
                    if len(p) != 2:
                        continue
                    x, y = int(p[0]), int(p[1])
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        nx, ny = x + dx, y + dy
                        npos = f"{nx}_{ny}"
                        key = (li, npos)
                        if not (0 <= nx < lc and 0 <= ny < lr):
                            continue
                        if npos in used or key in seen_global:
                            continue
                        seen_global.add(key)
                        nbrs = sum(1 for ax, ay in ((-1, 0), (1, 0), (0, -1), (0, 1))
                                   if f"{nx+ax}_{ny+ay}" in used)
                        # 대칭 점수: 0=대칭 유지, 1=대칭 깨짐
                        #  - 중앙열 칸은 미러가 자기 자신 → 넣어도 대칭 유지(자기대칭)
                        #  - 미러 자리에 이미 타일이 있으면 채워서 좌우 짝 완성
                        mirror = f"{lc - 1 - nx}_{ny}"
                        sym = 0 if (mirror == npos or mirror in used) else 1
                        cand.append(((sym, -(1 if nbrs >= 4 else 0), -nbrs), (li, npos)))
                cand.sort(key=lambda c: c[0])
                for _score, slot in cand:
                    found.append(slot)
                    if len(found) >= need:
                        return found
            return found

        def _scan():
            """현재 레벨 구성 스캔: concrete 카운트/위치, regular t0 위치, 컨테이너(craft/stack)."""
            c_counts: Dict[str, int] = {}
            t0_regular: List[Tuple[int, str]] = []
            containers: List[Tuple[int, str, list]] = []
            for li in range(num_layers):
                tiles = level.get(f"layer_{li}", {}).get("tiles", {})
                for pos, td in tiles.items():
                    if not (isinstance(td, list) and td and isinstance(td[0], str)):
                        continue
                    tt = td[0]
                    if tt == "t0":
                        t0_regular.append((li, pos))
                    elif tt.startswith("craft_") or tt.startswith("stack_"):
                        containers.append((li, pos, td))
                    elif tt.startswith("t") and tt[1:].isdigit():
                        c_counts[tt] = c_counts.get(tt, 0) + 1
                    # key/기타 특수타일은 무시 (key는 unlockTile×3로 ÷3 보장)
            return c_counts, t0_regular, containers

        def _internal(td) -> int:
            if len(td) > 2 and isinstance(td[2], list) and td[2]:
                try:
                    return int(td[2][0])
                except (ValueError, TypeError):
                    return 0
            return 0

        # concrete(고정 타일)와 t0(런타임 분배)를 '분리'해 각각 독립적으로 ÷3 보장한다.
        # 이렇게 하면 분배기의 toAdd(부분합 완성)에 의존하지 않는다 — 하이브리드(concrete 다수 +
        # 작은 컨테이너 t0)에서 t0가 toAdd에 부족해 깨지던 문제를 구조적으로 제거.
        # 불변식: concrete 각 타입 ÷3  AND  t0_count ÷3  ⟹  분배 후 전체 per-type ÷3.

        # ── Step 1: concrete 총합 ÷3 (잉여 제거; relabel은 총합을 못 바꾸므로 먼저 보정) ──
        c_counts, c_pos = self._concrete_positions(level, num_layers)
        rc = sum(c_counts.values()) % 3
        if rc:
            handled = False
            if preserve_pattern:
                # [1순위] 컨테이너(craft/stack)가 있으면 **타일을 하나도 더하거나 빼지 않고**
                # concrete 타일 rc개를 t0 로 relabel 한다. 위치·기믹은 그대로라 실루엣이 완전 보존되고,
                # 넘어간 rc개는 t0 총합에 합류해 Step 3 이 컨테이너 내부 개수로 흡수한다.
                # (인접칸 추가는 없던 자리에 타일이 생겨 모양이 변하므로 컨테이너가 없을 때만 쓴다.)
                _, _, _conts = _scan()
                if _conts:
                    moved = 0
                    # 잉여가 큰 타입부터 → Step 2 relabel 부담을 줄인다
                    for tt in sorted(c_pos, key=lambda t: (-(c_counts[t] % 3), -c_counts[t])):
                        while c_pos[tt] and moved < rc:
                            li, pos = c_pos[tt].pop()
                            cur = level.get(f"layer_{li}", {}).get("tiles", {}).get(pos)
                            if isinstance(cur, list) and cur:
                                cur[0] = "t0"
                                moved += 1
                        if moved >= rc:
                            break
                    if moved >= rc:
                        logger.info(
                            f"[FINALIZE_DIV] Pattern mode: relabeled {moved} concrete→t0 for ÷3 "
                            "(shape untouched, absorbed by container internals)")
                        level = self._sync_layer_num_fields(level)
                        handled = True
            if preserve_pattern and not handled:
                # 패턴 모드: 삭제 대신 인접 빈칸에 concrete 타일 추가(모양 보존). Step2 relabel이 per-type 마무리.
                need = 3 - rc
                slots = _adjacent_empty_slots(need)
                if len(slots) >= need:
                    add_type = next(iter(c_counts), "t1")
                    for li, pos in slots[:need]:
                        level[f"layer_{li}"]["tiles"][pos] = [add_type, ""]
                    logger.info(f"[FINALIZE_DIV] Pattern mode: added {need} adjacent concrete tile(s) for ÷3 (shape preserved)")
                    level = self._sync_layer_num_fields(level)
                    handled = True
            if not handled:
                removed = 0
                for tt in sorted(c_pos, key=lambda t: (-(c_counts[t] % 3), -c_counts[t])):
                    while c_pos[tt] and removed < rc:
                        li, pos = c_pos[tt].pop()
                        lk = f"layer_{li}"
                        if pos in level.get(lk, {}).get("tiles", {}):
                            del level[lk]["tiles"][pos]
                            removed += 1
                    if removed >= rc:
                        break
                if preserve_pattern:
                    logger.warning(f"[FINALIZE_DIV] Pattern mode: no adjacent slot, removed {removed} concrete tile(s) as last resort")
                level = self._sync_layer_num_fields(level)

        # ── Step 2: concrete per-type ÷3 (통합 relabel; 총합 ÷3 전제에서 항상 성공) ──
        self._consolidate_concrete_divisibility(level, num_layers)

        # ── Step 3: t0_count ÷3 (regular t0 → 컨테이너 내부[>=MIN_GOAL_COUNT] 제거) ──
        _, t0_regular, containers = _scan()
        t0_count = len(t0_regular) + sum(_internal(td) for _, _, td in containers)
        rt = t0_count % 3
        if rt:
            handled = False
            if preserve_pattern:
                # 패턴 모드: regular t0 삭제 대신 컨테이너 내부 t0 개수를 (3-rt) 증가 → 시각 타일 무변경.
                # 한 컨테이너에 몰아넣지 않고 내부 개수가 적은 것부터 1씩 분산한다(스택 하나만
                # 비정상적으로 두꺼워지는 것 방지). need 는 1 또는 2 라 컨테이너 1~2개만 건드린다.
                # ⚠️ **baked(내부 타입 문자열 확정) 컨테이너는 제외한다.**
                # 개수만 올리고 문자열을 그대로 두면 둘이 어긋나는데, 게임은 개수가 안 맞으면
                # baked 를 통째로 버리고 내부를 t0 로 재분배한다
                # (CTileStackInfo:149  if (ids.Length == xStackTotalCount)).
                # 그러면 우리가 센 색 구성과 실제 보드가 달라져 ÷3 이 깨진다.
                # 실측(재생성본): craft_w [2,"t4_t5_t5_t4"] → 게임 t5 7개 = 클리어 불가.
                targets = [td for _, _, td in containers
                           if len(td) > 2 and isinstance(td[2], list) and td[2]
                           and not (len(td[2]) > 1 and isinstance(td[2][1], str) and td[2][1])]
                if targets:
                    need = 3 - rt
                    targets.sort(key=_internal)
                    for i in range(need):
                        td = targets[i % len(targets)]
                        td[2][0] = _internal(td) + 1
                    gc: Dict[str, int] = {}
                    for _, _, td in containers:
                        gc[td[0]] = gc.get(td[0], 0) + _internal(td)
                    level["goalCount"] = gc
                    logger.info(
                        f"[FINALIZE_DIV] Pattern mode: +{need} to container internals for t0 ÷3 "
                        f"(shape preserved, goalCount={gc})")
                    level = self._sync_layer_num_fields(level)
                    handled = True
            if not handled:
                removed = 0
                touched_container = False
                for li, pos in sorted(t0_regular, key=lambda x: -x[0]):
                    if removed >= rt:
                        break
                    lk = f"layer_{li}"
                    if pos in level.get(lk, {}).get("tiles", {}):
                        del level[lk]["tiles"][pos]
                        removed += 1
                if removed < rt:
                    for li, pos, td in containers:
                        if removed >= rt:
                            break
                        # baked 는 개수만 줄여도 문자열과 어긋난다(위와 같은 이유) → 건너뛴다.
                        if len(td) > 2 and isinstance(td[2], list) and len(td[2]) > 1 \
                                and isinstance(td[2][1], str) and td[2][1]:
                            continue
                        intern = _internal(td)
                        take = min(intern - self.MIN_GOAL_COUNT, rt - removed)
                        if take > 0:
                            td[2][0] = intern - take
                            removed += take
                            touched_container = True
                if touched_container:
                    gc: Dict[str, int] = {}
                    for _, _, td in containers:
                        gc[td[0]] = gc.get(td[0], 0) + _internal(td)
                    level["goalCount"] = gc
                if removed < rt:
                    logger.error(
                        f"[FINALIZE_DIV] t0_count ÷3 보정 실패 (필요 {rt}, 제거 {removed})"
                    )
                    self._last_playability_warning = True
                level = self._sync_layer_num_fields(level)

        # ── Step 4: 방어적 최종 검증 (실제 분배 측정). 위 불변식이 보장하므로 통상 통과 ──
        c_final, _, containers = _scan()
        t0_final = len([p for li in range(num_layers)
                        for p in level.get(f"layer_{li}", {}).get("tiles", {})
                        if level[f"layer_{li}"]["tiles"][p][0] == "t0"]) \
            + sum(_internal(td) for _, _, td in containers)
        if t0_final > 0 and not self._t0_distribution_is_clean(level, c_final, t0_final):
            logger.error(
                f"[FINALIZE_DIV] 최종 검증 실패(예상밖) — concrete={c_final} t0={t0_final}. "
                "playability_warning=True"
            )
            self._last_playability_warning = True

        return level

    def _consolidate_concrete_divisibility(self, level: Dict[str, Any], num_layers: int) -> None:
        """
        순수 concrete 레벨의 per-type ÷3 보장(총합 ÷3 전제 — 앞 단계가 보장).
        각 타입의 잉여 단위(count%3)를 떼어 모은 뒤, 3개씩 묶어 한 타입으로 relabel한다.
        위치는 보존(패턴 모양 유지)하고 타일 이름만 바꾼다. 인라인 FINAL_REPAIR의 rem1+rem2
        페어링은 3×rem1 같은 케이스를 못 고치므로 여기서 통합 방식으로 확실히 처리한다.
        """
        counts, positions = self._concrete_positions(level, num_layers)
        offenders = {t: c for t, c in counts.items() if c % 3 != 0}
        if not offenders:
            return
        surplus: List[Tuple[int, str]] = []
        for t in offenders:
            for _ in range(counts[t] % 3):
                if positions.get(t):
                    surplus.append(positions[t].pop())
        clean_types = [t for t, c in counts.items() if c % 3 == 0 and c > 0]
        other_pool = [t for t, c in counts.items() if (c - (c % 3)) > 0]
        fallback = clean_types[0] if clean_types else (other_pool[0] if other_pool else next(iter(counts), "t1"))
        i = 0
        while i + 3 <= len(surplus):
            for li, pos in surplus[i:i + 3]:
                lk = f"layer_{li}"
                cur = level.get(lk, {}).get("tiles", {}).get(pos)
                if isinstance(cur, list) and cur:
                    gimmick = cur[1] if len(cur) > 1 else ""
                    level[lk]["tiles"][pos] = [fallback, gimmick]
            i += 3
        if len(surplus) % 3 != 0:
            logger.error(
                f"[FINALIZE_DIV] concrete 통합 relabel 잔여 {len(surplus) % 3} — 총합 비÷3 의심"
            )
            self._last_playability_warning = True

    def _concrete_positions(self, level: Dict[str, Any], num_layers: int) -> Tuple[Dict[str, int], Dict[str, List[Tuple[int, str]]]]:
        """concrete(t1~t15) 타입별 카운트와 위치 목록."""
        counts: Dict[str, int] = {}
        positions: Dict[str, List[Tuple[int, str]]] = {}
        for li in range(num_layers):
            tiles = level.get(f"layer_{li}", {}).get("tiles", {})
            for pos, td in tiles.items():
                if isinstance(td, list) and td and isinstance(td[0], str):
                    tt = td[0]
                    if tt.startswith("t") and tt[1:].isdigit() and tt != "t0":
                        counts[tt] = counts.get(tt, 0) + 1
                        positions.setdefault(tt, []).append((li, pos))
        return counts, positions

    def _detect_tile_offset(self, concrete_counts: Dict[str, int], use_tile_count: int) -> int:
        """기존 concrete 타입이 t11~ 처럼 오프셋된 경우 분배 오프셋 계산(bot/_ensure_valid_t0_distribution과 동일)."""
        existing = [t for t in concrete_counts if t.startswith("t") and t[1:].isdigit()]
        if not existing:
            return 0
        min_num = min(int(t[1:]) for t in existing)
        return min_num - 1 if min_num > use_tile_count else 0

    def _t0_distribution_is_clean(self, level: Dict[str, Any], concrete_counts: Dict[str, int], t0_count: int) -> bool:
        """현재 randSeed로 t0를 분배했을 때 모든 매칭타입이 ÷3인지 측정(인게임/봇과 동일 경로)."""
        use_tile_count = min(level.get("useTileCount", 6) or 6, self.MAX_USE_TILE_COUNT)
        offset = self._detect_tile_offset(concrete_counts, use_tile_count)
        assigns = TileDistributor.assign_t0_tiles(
            t0_count=t0_count, use_tile_count=use_tile_count,
            rand_seed=int(level.get("randSeed", 0) or 0),
            shuffle_tile=level.get("xShuffleTile", 0),
            type_imbalance=level.get("xTypeImbalance", 0),
            unlock_tile=level.get("unlockTile", level.get("xUnlockTile", 0)),
            tile_type_offset=offset, existing_tile_counts=concrete_counts,
        )
        combined = dict(concrete_counts)
        for t in assigns:
            combined[t] = combined.get(t, 0) + 1
        return not any(c % 3 for c in combined.values())

    def _validate_layer_distribution(
        self, level: Dict[str, Any], use_tile_count: int
    ) -> Dict[str, Any]:
        """
        Validate that tile types are well-distributed across layers to prevent deadlock.

        CRITICAL: If all tiles of a type are concentrated in lower (blocked) layers,
        the player cannot complete matches when those tiles are needed.

        Rules:
        1. For each tile type with 3+ tiles, at least 1 tile must be in top 50% of layers
        2. No tile type should have >70% concentration in bottom 2 layers
        3. Returns distribution quality score and problem types

        Args:
            level: Level data with tiles
            use_tile_count: Number of tile types used

        Returns:
            Dict with:
            - is_valid: bool - True if distribution is acceptable
            - problem_types: List of (tile_type, issue_description)
            - layer_distribution: Dict[tile_type, Dict[layer_idx, count]]
            - score: float - Distribution quality score (0.0-1.0)
        """
        num_layers = level.get("layer", 8)
        rand_seed = level.get("randSeed", 0)

        # Simulate t0 distribution to get actual tile types
        t0_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)
        regular_tiles: Dict[str, List[Tuple[int, str]]] = {}  # type -> [(layer_idx, pos)]

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type == "t0":
                        t0_positions.append((layer_idx, pos))
                    elif tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # Goal tiles with internal t0 tiles
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            for i in range(internal_count):
                                t0_positions.append((layer_idx, f"{pos}_internal_{i}"))
                    elif tile_type.startswith("t") and tile_type[1:].isdigit():
                        if tile_type not in regular_tiles:
                            regular_tiles[tile_type] = []
                        regular_tiles[tile_type].append((layer_idx, pos))

        # Get t0 assignments
        if t0_positions:
            # Build existing_tile_counts from regular_tiles
            existing_tile_counts = {t: len(positions) for t, positions in regular_tiles.items()}

            t0_assignments = TileDistributor.assign_t0_tiles(
                t0_count=len(t0_positions),
                use_tile_count=use_tile_count,
                rand_seed=rand_seed,
                shuffle_tile=level.get("xShuffleTile", 0),
                type_imbalance=level.get("xTypeImbalance", 0),
                unlock_tile=level.get("unlockTile", level.get("xUnlockTile", 0)),
                tile_type_offset=0,
                existing_tile_counts=existing_tile_counts  # For GetToAddIndexList logic
            )

            # Combine t0 assignments with their layer info
            for i, (layer_idx, pos) in enumerate(t0_positions):
                if i < len(t0_assignments):
                    tile_type = t0_assignments[i]
                    if tile_type not in regular_tiles:
                        regular_tiles[tile_type] = []
                    regular_tiles[tile_type].append((layer_idx, pos))

        # Analyze distribution for each type
        layer_distribution: Dict[str, Dict[int, int]] = {}
        problem_types: List[Tuple[str, str]] = []
        total_score = 0.0
        scored_types = 0

        top_half_start = num_layers // 2  # Upper layers (higher index = top)

        for tile_type, positions in regular_tiles.items():
            if len(positions) < 3:
                continue  # Skip types with less than 3 tiles

            # Count by layer
            layer_counts: Dict[int, int] = {}
            for layer_idx, pos in positions:
                layer_counts[layer_idx] = layer_counts.get(layer_idx, 0) + 1
            layer_distribution[tile_type] = layer_counts

            total_tiles = len(positions)

            # Check 1: At least 1 tile in top 50% of layers
            top_half_count = sum(
                count for layer_idx, count in layer_counts.items()
                if layer_idx >= top_half_start
            )

            # Check 2: Bottom 2 layers concentration
            bottom_2_count = sum(
                count for layer_idx, count in layer_counts.items()
                if layer_idx <= 1
            )
            bottom_concentration = bottom_2_count / total_tiles if total_tiles > 0 else 0

            # Calculate type score
            type_score = 1.0
            issues = []

            if top_half_count == 0:
                type_score -= 0.5
                issues.append(f"no tiles in top {num_layers - top_half_start} layers")

            if bottom_concentration > 0.7:
                type_score -= 0.3
                issues.append(f"{bottom_concentration*100:.0f}% in bottom 2 layers")

            if issues:
                problem_types.append((tile_type, "; ".join(issues)))

            total_score += max(0, type_score)
            scored_types += 1

        avg_score = total_score / scored_types if scored_types > 0 else 1.0

        return {
            "is_valid": len(problem_types) == 0 or avg_score >= 0.7,
            "problem_types": problem_types,
            "layer_distribution": layer_distribution,
            "score": avg_score
        }

    def _validate_blocking_structure(
        self, level: Dict[str, Any], use_tile_count: int
    ) -> Dict[str, Any]:
        """
        블로킹 구조 검증: 같은 타입 타일이 서로 막는 패턴 탐지

        검증 항목:
        1. 같은 타입 상호 블로킹: t1이 t1을 막고 있으면 데드락 위험
        2. 타입 접근성 분포: 각 타입이 다양한 접근 "창"에 분산되어야 함
        3. 초기 매칭 가능성: 게임 시작 시 최소 1개 타입은 3개 이상 접근 가능해야 함

        Returns:
            Dict with validation results and issues found
        """
        from .bot_simulator import BotSimulator

        num_layers = level.get("layer", 8)

        # 블로킹 오프셋 정의 (TownPop 방식)
        BLOCKING_OFFSETS_SAME_PARITY = [
            (0, 0), (1, 0), (0, 1), (1, 1)
        ]
        BLOCKING_OFFSETS_UPPER_SMALLER = [
            (-1, -1), (0, -1), (-1, 0), (0, 0)
        ]
        BLOCKING_OFFSETS_UPPER_BIGGER = [
            (0, 0), (1, 0), (0, 1), (1, 1)
        ]

        issues = []
        blocking_stats = {
            "same_type_blocking": 0,
            "total_blocking_pairs": 0,
            "type_accessibility_score": 0.0,
        }

        # Step 1: 모든 타일 정보 수집 (t0 타일은 시뮬레이터로 실제 타입 확인)
        all_tiles: Dict[str, List[Tuple[int, str, str]]] = {}  # type -> [(layer, pos, gimmick)]
        tile_positions: Dict[str, Tuple[int, str, str]] = {}  # "layer_pos" -> (layer, pos, type)

        # t0 타일 여부 확인
        has_t0 = False
        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and tile_data[0] == "t0":
                    has_t0 = True
                    break
            if has_t0:
                break

        # t0 타일이 있으면 시뮬레이터로 실제 타입 확인
        if has_t0:
            try:
                simulator = BotSimulator()
                max_moves = level.get("max_moves", 50)
                state = simulator._create_initial_state(level, max_moves)

                # 시뮬레이터 상태에서 실제 타입 추출
                for layer_idx, layer_tiles in state.tiles.items():
                    for pos, tile_state in layer_tiles.items():
                        tile_type = tile_state.tile_type
                        gimmick = tile_state.effect_type.value if tile_state.effect_type else ""

                        if tile_type not in all_tiles:
                            all_tiles[tile_type] = []
                        all_tiles[tile_type].append((layer_idx, pos, gimmick))
                        tile_positions[f"{layer_idx}_{pos}"] = (layer_idx, pos, tile_type)
            except Exception as e:
                logger.warning(f"[_validate_blocking_structure] Failed to get t0 types: {e}")
                # 폴백: 원본 데이터 사용
                has_t0 = False

        if not has_t0:
            # Pre-assigned 타일: 원본 데이터 사용
            for layer_idx in range(num_layers):
                layer_key = f"layer_{layer_idx}"
                tiles = level.get(layer_key, {}).get("tiles", {})

                for pos, tile_data in tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) < 1:
                        continue

                    tile_type = tile_data[0]
                    gimmick = tile_data[1] if len(tile_data) > 1 else ""

                    if tile_type not in all_tiles:
                        all_tiles[tile_type] = []
                    all_tiles[tile_type].append((layer_idx, pos, gimmick))
                    tile_positions[f"{layer_idx}_{pos}"] = (layer_idx, pos, tile_type)

        # Step 2: 블로킹 관계 분석
        def get_blocking_offsets(lower_layer: int, upper_layer: int) -> List[Tuple[int, int]]:
            """[v15.49 revert] 원래 col-기반 로직 — 디바이스와 일치."""
            lower_parity = lower_layer % 2
            upper_parity = upper_layer % 2
            lower_col = int(level.get(f"layer_{lower_layer}", {}).get("col", 7))
            upper_col = int(level.get(f"layer_{upper_layer}", {}).get("col", 7))
            if lower_parity == upper_parity:
                return BLOCKING_OFFSETS_SAME_PARITY
            elif upper_col > lower_col:
                return BLOCKING_OFFSETS_UPPER_BIGGER
            else:
                return BLOCKING_OFFSETS_UPPER_SMALLER

        def is_blocked_by(lower_layer: int, lower_pos: str, upper_layer: int) -> Optional[str]:
            """하위 타일이 상위 레이어의 어떤 타일에 막히는지 확인"""
            if upper_layer >= num_layers:
                return None

            try:
                col, row = map(int, lower_pos.split("_"))
            except:
                return None

            upper_tiles = level.get(f"layer_{upper_layer}", {}).get("tiles", {})
            offsets = get_blocking_offsets(lower_layer, upper_layer)

            for dx, dy in offsets:
                check_pos = f"{col + dx}_{row + dy}"
                if check_pos in upper_tiles:
                    return check_pos
            return None

        # Step 3: 같은 타입 상호 블로킹 검사
        same_type_blocking_pairs = []

        for tile_type, tiles in all_tiles.items():
            if tile_type == "t0":
                continue  # t0는 런타임에 할당되므로 스킵

            # 각 타일에 대해 상위 레이어에서 같은 타입이 막고 있는지 확인
            for lower_layer, lower_pos, _ in tiles:
                for check_layer in range(lower_layer + 1, num_layers):
                    blocking_pos = is_blocked_by(lower_layer, lower_pos, check_layer)
                    if blocking_pos:
                        check_key = f"{check_layer}_{blocking_pos}"
                        if check_key in tile_positions:
                            _, _, blocking_type = tile_positions[check_key]
                            blocking_stats["total_blocking_pairs"] += 1

                            if blocking_type == tile_type:
                                blocking_stats["same_type_blocking"] += 1
                                same_type_blocking_pairs.append(
                                    (tile_type, f"L{lower_layer}:{lower_pos}", f"L{check_layer}:{blocking_pos}")
                                )

        # Step 4: 같은 타입 블로킹 비율 평가
        if blocking_stats["total_blocking_pairs"] > 0:
            same_type_ratio = blocking_stats["same_type_blocking"] / blocking_stats["total_blocking_pairs"]

            # 같은 타입 블로킹이 15% 이상이면 위험
            if same_type_ratio > 0.15:
                issues.append(
                    f"High same-type blocking: {same_type_ratio*100:.1f}% "
                    f"({blocking_stats['same_type_blocking']}/{blocking_stats['total_blocking_pairs']})"
                )

            # 특정 타입이 과도하게 자기 타입에 막히는지 확인
            type_self_blocking = {}
            for tile_type, lower, upper in same_type_blocking_pairs:
                type_self_blocking[tile_type] = type_self_blocking.get(tile_type, 0) + 1

            for tile_type, count in type_self_blocking.items():
                total_of_type = len(all_tiles.get(tile_type, []))
                if total_of_type > 0 and count >= total_of_type * 0.5:
                    issues.append(
                        f"Type {tile_type}: {count}/{total_of_type} tiles blocked by same type"
                    )

        # Step 5: 초기 접근 가능 타일 분석 (시뮬레이터 사용)
        try:
            simulator = BotSimulator()
            max_moves = level.get("max_moves", 50)
            state = simulator._create_initial_state(level, max_moves)

            # 접근 가능 타일 수집
            accessible = [
                t for layer in state.tiles.values()
                for t in layer.values()
                if not t.picked and simulator._can_pick_tile(state, t)
            ]

            # 타입별 접근 가능 수
            accessible_by_type: Dict[str, int] = {}
            for t in accessible:
                accessible_by_type[t.tile_type] = accessible_by_type.get(t.tile_type, 0) + 1

            # 3개 이상 접근 가능한 타입 수
            types_with_3plus = sum(1 for c in accessible_by_type.values() if c >= 3)

            if types_with_3plus == 0:
                issues.append(
                    f"No type has 3+ accessible tiles at start! "
                    f"(accessible: {dict(accessible_by_type)})"
                )
            elif types_with_3plus < 2:
                issues.append(
                    f"Only {types_with_3plus} type(s) with 3+ accessible tiles"
                )

            # 접근성 점수 계산
            total_accessible = len(accessible)
            if total_accessible > 0:
                blocking_stats["type_accessibility_score"] = types_with_3plus / use_tile_count

        except Exception as e:
            logger.warning(f"[_validate_blocking_structure] Simulation failed: {e}")

        # 결과 반환
        is_valid = len(issues) == 0

        if issues:
            logger.warning(f"[_validate_blocking_structure] Issues found: {issues[:3]}")

        return {
            "is_valid": is_valid,
            "issues": issues,
            "stats": blocking_stats,
            "same_type_blocking_pairs": same_type_blocking_pairs[:10],  # 상위 10개만
        }

    def _fix_same_type_blocking(
        self, level: Dict[str, Any], blocking_pairs: List[Tuple[str, str, str]]
    ) -> Dict[str, Any]:
        """
        같은 타입 블로킹 문제 해결

        전략:
        - t0 타일: randSeed 변경으로 다른 타입 분포 시도
        - Pre-assigned 타일: 상위 타일의 타입을 다른 타입으로 교체
        """
        import copy
        import random

        # [v15.36] 고정 레이아웃 레벨: 타일 교체 건너뛰기
        if level.get("_skip_tile_redistribution", False):
            logger.info("[_fix_same_type_blocking] Skipping for fixed layout level")
            return level

        level = copy.deepcopy(level)
        num_layers = level.get("layer", 8)

        # t0 타일 여부 확인
        has_t0 = False
        t0_count = 0
        preassigned_count = 0

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    if tile_data[0] == "t0":
                        t0_count += 1
                    elif tile_data[0].startswith("t") and tile_data[0][1:].isdigit():
                        preassigned_count += 1

        has_t0 = t0_count > preassigned_count

        # t0 타일의 경우: randSeed 변경으로 더 좋은 타입 분포 찾기
        if has_t0:
            from .bot_simulator import BotSimulator

            current_seed = level.get("randSeed", 0)
            best_seed = current_seed
            best_blocking_count = len(blocking_pairs)
            best_clear_rate = 0.0

            simulator = BotSimulator()
            use_tile_count = level.get("useTileCount", 5)

            # 더 넓은 범위에서 seed 검색 (50개 시도)
            for seed_offset in range(1, 51):
                test_seed = current_seed + seed_offset * 137  # Larger prime for more diversity
                test_level = copy.deepcopy(level)
                test_level["randSeed"] = test_seed

                try:
                    # 빠른 시뮬레이션으로 클리어율 확인
                    from app.models.bot_profile import get_profile
                    profile = get_profile("optimal")
                    result = simulator.simulate_with_profile(
                        test_level, profile, iterations=3, max_moves=level.get("max_moves", 50)
                    )

                    # 클리어율이 더 높으면 채택
                    if result.clear_rate > best_clear_rate:
                        best_clear_rate = result.clear_rate
                        best_seed = test_seed

                        # 클리어율이 50% 이상이면 조기 종료
                        if best_clear_rate >= 0.5:
                            logger.info(
                                f"[_fix_same_type_blocking] Found good seed {test_seed} "
                                f"with {best_clear_rate*100:.0f}% clear rate"
                            )
                            break

                except Exception as e:
                    continue

            if best_seed != current_seed:
                level["randSeed"] = best_seed
                logger.info(
                    f"[_fix_same_type_blocking] Changed randSeed {current_seed} -> {best_seed} "
                    f"(clear_rate: 0% -> {best_clear_rate*100:.0f}%)"
                )
            else:
                # 더 좋은 seed를 찾지 못하면 랜덤 seed 시도
                import random
                level["randSeed"] = random.randint(100000, 999999)
                logger.info(
                    f"[_fix_same_type_blocking] No better seed found, using random: {level['randSeed']}"
                )

            return level

        # Pre-assigned 타일의 경우: 타입 교체
        rng = random.Random(level.get("randSeed", 0) + 999)

        # 모든 타일 타입 수집
        type_counts: Dict[str, int] = {}
        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    t = tile_data[0]
                    if t != "t0":
                        type_counts[t] = type_counts.get(t, 0) + 1

        # 교체 가능한 타입 쌍 찾기 (둘 다 6개 이상인 타입)
        swappable_types = [t for t, c in type_counts.items() if c >= 6]

        swaps_made = 0
        max_swaps = min(5, len(blocking_pairs))  # 최대 5개 교체

        for tile_type, lower_loc, upper_loc in blocking_pairs[:max_swaps]:
            if tile_type == "t0":
                continue

            # 상위 타일 위치 파싱
            try:
                upper_layer = int(upper_loc.split(":")[0][1:])
                upper_pos = upper_loc.split(":")[1]
            except:
                continue

            layer_key = f"layer_{upper_layer}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            if upper_pos not in tiles:
                continue

            # 교체할 타입 선택 (다른 타입 중 6개 이상인 것)
            other_types = [t for t in swappable_types if t != tile_type]
            if not other_types:
                continue

            new_type = rng.choice(other_types)
            old_tile = tiles[upper_pos]

            # 타입 교체 (gimmick 유지)
            tiles[upper_pos] = [new_type] + old_tile[1:]
            swaps_made += 1

            logger.info(
                f"[_fix_same_type_blocking] Swapped {tile_type} -> {new_type} "
                f"at layer {upper_layer}, pos {upper_pos}"
            )

        return level

    def _quick_deadlock_check(
        self, level: Dict[str, Any], max_moves: int = None
    ) -> Dict[str, Any]:
        """
        Quick simulation-based deadlock check using optimal bot.

        Runs a small number of simulations to detect if the level has
        fundamental playability issues (deadlock patterns).

        Args:
            level: Level data to check
            max_moves: Max moves for simulation (default from level)

        Returns:
            Dict with:
            - has_deadlock: bool - True if deadlock detected
            - clear_rate: float - Simulation clear rate
            - avg_moves: float - Average moves used
            - failure_reason: str - Description of failure pattern
        """
        from .bot_simulator import BotSimulator, get_profile

        if max_moves is None:
            max_moves = level.get("max_moves", level.get("maxMoves", 50))

        simulator = BotSimulator()
        profile = get_profile("optimal")

        # Run small number of simulations for quick check
        # [v15.54] 5 iterations w/ 0.3 threshold — speed/accuracy 균형. v15.43에서 10으로
        # 늘렸으나 매 generate마다 ~30~50 sims가 누적되어 생성 시간이 3-7초로 급증함.
        # 5 iter + threshold 0.3은 noise 충분히 억제하면서 cost 50% 절감.
        result = simulator.simulate_with_profile(
            level_json=level,
            profile=profile,
            iterations=5,
            max_moves=max_moves,
            seed=None
        )

        has_deadlock = result.clear_rate < 0.3

        failure_reason = ""
        if has_deadlock:
            if result.avg_moves < max_moves * 0.5:
                failure_reason = "Early game over - possible tile distribution issue"
            else:
                failure_reason = "Late game failure - possible blocking pattern"

        return {
            "has_deadlock": has_deadlock,
            "clear_rate": result.clear_rate,
            "avg_moves": result.avg_moves,
            "failure_reason": failure_reason
        }

    def _reshuffle_tiles_across_layers(
        self, level: Dict[str, Any], seed_offset: int = 0
    ) -> Dict[str, Any]:
        """
        Reshuffle tile types across layers while keeping positions and gimmicks intact.

        For pre-assigned tile levels (not using t0), this redistributes tile types
        to improve layer balance and prevent deadlock patterns.

        Strategy:
        1. Collect all tile types and their gimmicks from all layers
        2. Ensure each tile type has at least one tile in upper 50% of layers
        3. Redistribute while maintaining 3-divisibility per type

        Args:
            level: Level data with pre-assigned tile types
            seed_offset: Offset for random seed to get different shuffle

        Returns:
            Level with reshuffled tile distribution
        """
        import copy
        import random

        # [v15.36] 고정 레이아웃 레벨: 타일 재분배 건너뛰기
        if level.get("_skip_tile_redistribution", False):
            logger.info("[_reshuffle_tiles_across_layers] Skipping for fixed layout level")
            return level

        level = copy.deepcopy(level)
        num_layers = level.get("layer", 8)
        rand_seed = level.get("randSeed", 0) + seed_offset
        rng = random.Random(rand_seed)

        # Collect all tiles with their positions and gimmicks
        all_tiles: List[Tuple[int, str, str, str]] = []  # (layer_idx, pos, tile_type, gimmick)
        position_map: Dict[int, List[str]] = {}  # layer_idx -> [positions]

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            position_map[layer_idx] = []

            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    gimmick = tile_data[1] if len(tile_data) > 1 else ""

                    # Only process regular tile types (t1, t2, etc.)
                    if tile_type.startswith("t") and tile_type[1:].isdigit():
                        all_tiles.append((layer_idx, pos, tile_type, gimmick))
                        position_map[layer_idx].append(pos)

        if not all_tiles:
            return level

        # Group tiles by type
        tiles_by_type: Dict[str, List[Tuple[int, str, str]]] = {}
        for layer_idx, pos, tile_type, gimmick in all_tiles:
            if tile_type not in tiles_by_type:
                tiles_by_type[tile_type] = []
            tiles_by_type[tile_type].append((layer_idx, pos, gimmick))

        # Calculate target: each type should have at least 1 tile in upper half
        top_half_start = num_layers // 2

        # Collect all positions by layer (for reassignment)
        all_positions: List[Tuple[int, str]] = []
        for layer_idx in range(num_layers):
            for pos in position_map.get(layer_idx, []):
                all_positions.append((layer_idx, pos))

        # Sort positions by layer (top first for priority assignment)
        all_positions.sort(key=lambda x: -x[0])

        # Create new tile assignments with balanced distribution
        new_assignments: List[Tuple[int, str, str, str]] = []

        # First pass: ensure each type gets at least one top-half position
        remaining_top_positions = [p for p in all_positions if p[0] >= top_half_start]
        remaining_bottom_positions = [p for p in all_positions if p[0] < top_half_start]

        for tile_type, tiles in tiles_by_type.items():
            type_count = len(tiles)
            gimmicks = [g for _, _, g in tiles]

            # Shuffle gimmicks for variety
            rng.shuffle(gimmicks)

            assigned_positions = []

            # Assign at least 1 to top half (if available)
            if remaining_top_positions and type_count >= 3:
                pos = remaining_top_positions.pop(0)
                assigned_positions.append(pos)

            # Assign remaining to any position
            remaining_count = type_count - len(assigned_positions)
            available = remaining_top_positions + remaining_bottom_positions
            rng.shuffle(available)

            for _ in range(remaining_count):
                if available:
                    pos = available.pop(0)
                    assigned_positions.append(pos)
                    # Update remaining lists
                    if pos in remaining_top_positions:
                        remaining_top_positions.remove(pos)
                    elif pos in remaining_bottom_positions:
                        remaining_bottom_positions.remove(pos)

            # Create assignments with gimmicks
            for i, (layer_idx, pos) in enumerate(assigned_positions):
                gimmick = gimmicks[i] if i < len(gimmicks) else ""
                new_assignments.append((layer_idx, pos, tile_type, gimmick))

        # Apply new assignments to level
        for layer_idx, pos, tile_type, gimmick in new_assignments:
            layer_key = f"layer_{layer_idx}"
            if layer_key in level and "tiles" in level[layer_key]:
                if pos in level[layer_key]["tiles"]:
                    level[layer_key]["tiles"][pos] = [tile_type, gimmick]

        return level

    def _fix_layer_distribution(
        self, level: Dict[str, Any], problem_types: List[Tuple[str, str]]
    ) -> Dict[str, Any]:
        """
        Attempt to fix layer distribution issues.

        Strategy depends on level type:
        1. For t0-based levels: change randSeed
        2. For pre-assigned levels: reshuffle tiles across layers

        Args:
            level: Level data
            problem_types: List of (tile_type, issue) from validation

        Returns:
            Updated level with potentially better distribution
        """
        if not problem_types:
            return level

        # [v15.36] 고정 레이아웃 레벨: 타일 재분배 건너뛰기
        if level.get("_skip_tile_redistribution", False):
            logger.info("[_fix_layer_distribution] Skipping redistribution for fixed layout level")
            return level

        num_layers = level.get("layer", 8)

        # Check if level uses t0 or pre-assigned tiles
        t0_count = 0
        preassigned_count = 0

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type == "t0":
                        t0_count += 1
                    elif tile_type.startswith("t") and tile_type[1:].isdigit():
                        preassigned_count += 1

        use_tile_count = level.get("useTileCount", 5)

        # For pre-assigned tile levels: reshuffle tiles
        if preassigned_count > t0_count:
            logger.info(
                f"[_fix_layer_distribution] Pre-assigned tile level detected. "
                f"Attempting reshuffle..."
            )

            best_level = level
            best_score = 0.0

            for attempt in range(10):
                test_level = self._reshuffle_tiles_across_layers(level, seed_offset=attempt)
                result = self._validate_layer_distribution(test_level, use_tile_count)

                if result["score"] > best_score:
                    best_score = result["score"]
                    best_level = test_level

                    if result["is_valid"] and result["score"] >= 0.9:
                        logger.info(
                            f"[_fix_layer_distribution] Found good distribution "
                            f"at attempt {attempt + 1} (score: {best_score:.2f})"
                        )
                        return best_level

            if best_score > 0:
                logger.info(
                    f"[_fix_layer_distribution] Best reshuffle score: {best_score:.2f}"
                )
            return best_level

        # For t0-based levels: try different seeds
        original_seed = level.get("randSeed", 0)
        best_level = level.copy()
        best_score = 0.0

        for attempt in range(20):
            test_seed = original_seed + attempt + 1
            test_level = level.copy()
            test_level["randSeed"] = test_seed

            result = self._validate_layer_distribution(test_level, use_tile_count)

            if result["is_valid"] and result["score"] > best_score:
                best_score = result["score"]
                best_level = test_level

                if result["score"] >= 0.9:
                    # Good enough, stop searching
                    break

        if best_score > 0:
            logger.info(
                f"[_fix_layer_distribution] Changed randSeed from {original_seed} "
                f"to {best_level.get('randSeed')} for better distribution (score: {best_score:.2f})"
            )

        return best_level

    def _ensure_no_deadlock(
        self, level: Dict[str, Any], max_attempts: int = 10
    ) -> Tuple[Dict[str, Any], bool, float]:
        """
        Hybrid deadlock prevention: combines fast validation with simulation.

        Phase 1: Quick layer distribution check
        Phase 2: If issues found, try to fix with randSeed change or reshuffle
        Phase 3: Run simulation check
        Phase 4: If deadlock confirmed, reshuffle tiles and retry

        Args:
            level: Level data
            max_attempts: Maximum fix attempts

        Returns:
            Tuple of (fixed_level, is_valid)
        """
        import copy

        use_tile_count = level.get("useTileCount", 5)
        original_seed = level.get("randSeed", 0)
        num_layers = level.get("layer", 8)

        # Check if level uses pre-assigned tiles (not t0)
        t0_count = 0
        preassigned_count = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for tile_data in tiles.values():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type == "t0":
                        t0_count += 1
                    elif tile_type.startswith("t") and tile_type[1:].isdigit():
                        preassigned_count += 1

        is_preassigned = preassigned_count > t0_count
        original_level = copy.deepcopy(level)
        best_level = level
        best_clear_rate = 0.0

        for attempt in range(max_attempts):
            # Phase 1: Quick layer distribution validation
            dist_result = self._validate_layer_distribution(level, use_tile_count)

            if not dist_result["is_valid"]:
                # Phase 1a: Try to fix distribution via reshuffle/seed change
                logger.info(
                    f"[_ensure_no_deadlock] Attempt {attempt + 1}: "
                    f"Distribution issues found: {dist_result['problem_types'][:3]}"
                )
                level = self._fix_layer_distribution(level, dist_result["problem_types"])
                dist_result = self._validate_layer_distribution(level, use_tile_count)

            # Phase 2: Blocking structure validation (NEW)
            blocking_result = self._validate_blocking_structure(level, use_tile_count)

            if not blocking_result["is_valid"]:
                logger.info(
                    f"[_ensure_no_deadlock] Attempt {attempt + 1}: "
                    f"Blocking issues found: {blocking_result['issues'][:2]}"
                )

                # Try to fix same-type blocking
                if blocking_result["same_type_blocking_pairs"]:
                    level = self._fix_same_type_blocking(
                        level, blocking_result["same_type_blocking_pairs"]
                    )

            # Phase 3: Run simulation check
            deadlock_result = self._quick_deadlock_check(level)

            if not deadlock_result["has_deadlock"]:
                logger.info(
                    f"[_ensure_no_deadlock] Level passed deadlock check "
                    f"(clear_rate: {deadlock_result['clear_rate']:.1%})"
                )
                return level, True, float(deadlock_result.get("clear_rate", 1.0))

            # Track best result
            if deadlock_result["clear_rate"] > best_clear_rate:
                best_clear_rate = deadlock_result["clear_rate"]
                best_level = copy.deepcopy(level)

            # Phase 4: Deadlock detected - try different fix
            logger.warning(
                f"[_ensure_no_deadlock] Attempt {attempt + 1}: "
                f"Deadlock detected - {deadlock_result['failure_reason']}"
            )

            # For pre-assigned tiles: try reshuffle
            if is_preassigned:
                level = self._reshuffle_tiles_across_layers(
                    original_level, seed_offset=(attempt + 1) * 17
                )
            else:
                # For t0 tiles: try new seed
                level = copy.deepcopy(original_level)
                level["randSeed"] = original_seed + (attempt + 1) * 100

        # Return best attempt even if not perfect
        logger.error(
            f"[_ensure_no_deadlock] Could not fully resolve deadlock after {max_attempts} attempts. "
            f"Best clear_rate: {best_clear_rate:.1%}"
        )
        return best_level, best_clear_rate >= 0.1, best_clear_rate  # Accept if at least 10% clear rate

    def _validate_and_fix_obstacles(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Final validation pass to ensure all obstacles follow game rules.
        This is called AFTER all modifications (difficulty adjustment, tile addition, etc.)

        Rules:
        1. Chain tiles: At least ONE neighbor must be clearable (no obstacle attribute)
        2. Link tiles: Partner tile MUST exist AND at least one of the pair must have clearable neighbor
        """
        num_layers = level.get("layer", 8)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if not tiles:
                continue

            # Collect invalid obstacles to remove
            invalid_obstacles = []

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                attr = tile_data[1]

                # Validate chain tiles - Chain only checks LEFT and RIGHT (on screen)
                # Position format is "col_row" (x_y)
                # ENHANCED: Also check chain tile's own blocking status and layer position
                if attr == "chain":
                    col, row = map(int, pos.split('_'))
                    # Only LEFT (col-1) and RIGHT (col+1) neighbors on screen
                    neighbors = [
                        (col-1, row),  # Left (on screen)
                        (col+1, row),  # Right (on screen)
                    ]

                    has_clearable_neighbor = False
                    clearable_neighbor_count = 0

                    for ncol, nrow in neighbors:
                        npos = f"{ncol}_{nrow}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            # Check if neighbor is clearable (no obstacle or frog only)
                            if (isinstance(ndata, list) and len(ndata) >= 2 and
                                (not ndata[1] or ndata[1] == "frog")):
                                # CRITICAL: Neighbor must NOT be a goal tile (stack_*/craft_* boxes)
                                # Goal boxes can't be picked directly, so they're not clearable neighbors
                                if ndata[0] in self.GOAL_TYPES:
                                    continue
                                # CRITICAL: Neighbor must NOT be covered by upper layers
                                # If covered, the chain cannot be unlocked
                                if not self._is_position_covered_by_upper(level, i, ncol, nrow):
                                    has_clearable_neighbor = True
                                    clearable_neighbor_count += 1

                    # ENHANCED VALIDATION: Check chain tile's own blocking status
                    chain_is_blocked = self._is_position_covered_by_upper(level, i, col, row)

                    if not has_clearable_neighbor:
                        invalid_obstacles.append(pos)
                        logger.debug(f"[VALIDATE] Invalid chain at layer {i}/{pos}: no clearable uncovered horizontal neighbor")
                    elif chain_is_blocked and i <= 1:
                        # Chain in bottom layers (0 or 1) AND blocked by upper layers
                        # This makes chain very hard to unlock - consider it risky
                        # Only invalidate if in layer 0 with no accessible neighbors
                        if i == 0:
                            # Count how many layers are above this position
                            blocking_layers = 0
                            for upper_layer in range(i + 1, num_layers):
                                if self._is_position_covered_by_upper(level, i, col, row):
                                    blocking_layers += 1
                            # If chain is in layer 0 and blocked by 3+ layers, consider risky
                            if blocking_layers >= 3 and clearable_neighbor_count < 2:
                                logger.warning(f"[VALIDATE] Risky chain at layer {i}/{pos}: blocked by {blocking_layers} layers, only {clearable_neighbor_count} clearable neighbors")

                # Validate link tiles - connected direction MUST have a tile
                # Position format is "col_row" (x_y)
                elif attr and attr.startswith("link_"):
                    col, row = map(int, pos.split('_'))

                    # Determine the position that the link points to
                    # link_n points north (up), so there must be a tile at row-1
                    # link_s points south (down), so there must be a tile at row+1
                    # link_w points west (left), so there must be a tile at col-1
                    # link_e points east (right), so there must be a tile at col+1
                    if attr == "link_n":
                        target_pos = f"{col}_{row-1}"
                    elif attr == "link_s":
                        target_pos = f"{col}_{row+1}"
                    elif attr == "link_w":
                        target_pos = f"{col-1}_{row}"
                    elif attr == "link_e":
                        target_pos = f"{col+1}_{row}"
                    else:
                        continue

                    # CRITICAL: The linked direction MUST have a tile
                    # CRITICAL: Target must NOT have blocking gimmicks (chain, ice, grass)
                    BLOCKING_GIMMICKS = {"chain", "ice", "ice_1", "ice_2", "ice_3", "grass"}
                    valid_link = False
                    invalid_reason = ""

                    if target_pos in tiles:
                        target_data = tiles[target_pos]
                        if isinstance(target_data, list) and len(target_data) >= 2:
                            # Target must not be a goal tile (craft/stack)
                            target_type = target_data[0]
                            target_attr = target_data[1] if len(target_data) > 1 else ""

                            if (target_type not in self.GOAL_TYPES and
                                not target_type.startswith("craft_") and
                                not target_type.startswith("stack_")):
                                # NEW: Check if target has blocking gimmick
                                if target_attr in BLOCKING_GIMMICKS:
                                    invalid_reason = f"target has blocking gimmick '{target_attr}'"
                                # CRITICAL: Target must NOT have link attribute
                                # Link tiles cannot be targets of other links
                                elif target_attr and target_attr.startswith("link_"):
                                    invalid_reason = f"target is already a link source '{target_attr}'"
                                else:
                                    # CRITICAL: Check if any adjacent tile (other than target) has link
                                    # Link tiles should not be adjacent to other link tiles
                                    adjacent_positions = [
                                        f"{col}_{row - 1}",  # North
                                        f"{col}_{row + 1}",  # South
                                        f"{col - 1}_{row}",  # West
                                        f"{col + 1}_{row}",  # East
                                    ]
                                    has_adjacent_link = False
                                    for adj_pos in adjacent_positions:
                                        if adj_pos == target_pos:  # Skip the target itself
                                            continue
                                        if adj_pos in tiles:
                                            adj_tile = tiles[adj_pos]
                                            if isinstance(adj_tile, list) and len(adj_tile) >= 2:
                                                adj_attr = adj_tile[1]
                                                if adj_attr and adj_attr.startswith("link_"):
                                                    has_adjacent_link = True
                                                    invalid_reason = f"adjacent tile {adj_pos} has link '{adj_attr}'"
                                                    break
                                    if not has_adjacent_link:
                                        valid_link = True
                            else:
                                invalid_reason = "target is a goal tile"
                        else:
                            invalid_reason = "invalid target data"
                    else:
                        invalid_reason = "target tile does not exist"

                    if not valid_link:
                        logger.debug(f"[VALIDATE] Invalid link at {layer_key}/{pos} ({attr}): {invalid_reason}")
                        invalid_obstacles.append(pos)

                # Validate grass tiles - must have at least 2 clearable neighbors in 4 directions
                # Position format is "col_row" (x_y)
                elif attr and (attr == "grass" or attr.startswith("grass_")):
                    col, row = map(int, pos.split('_'))
                    neighbors = [
                        (col, row-1),  # Up
                        (col, row+1),  # Down
                        (col-1, row),  # Left
                        (col+1, row),  # Right
                    ]

                    clearable_count = 0
                    for ncol, nrow in neighbors:
                        npos = f"{ncol}_{nrow}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            if (isinstance(ndata, list) and len(ndata) >= 2 and
                                (not ndata[1] or ndata[1] == "frog")):
                                # CRITICAL: Neighbor must NOT be a goal tile (stack_*/craft_* boxes)
                                if ndata[0] in self.GOAL_TYPES:
                                    continue
                                clearable_count += 1

                    # RULE: Must have at least 2 clearable neighbors
                    if clearable_count < 2:
                        invalid_obstacles.append(pos)

                # Validate unknown tiles - must be covered by upper layer
                # Position format is "col_row" (x_y)
                elif attr == "unknown":
                    col, row = map(int, pos.split('_'))
                    # Unknown tiles MUST be covered by upper layers to show curtain effect
                    if not self._is_position_covered_by_upper(level, i, col, row):
                        invalid_obstacles.append(pos)

            # Remove invalid obstacles
            for pos in invalid_obstacles:
                if pos in tiles and tiles[pos][1]:
                    tiles[pos][1] = ""

        return level


# Singleton instance
_generator = None


def get_generator() -> LevelGenerator:
    """Get or create generator singleton instance."""
    global _generator
    if _generator is None:
        _generator = LevelGenerator()
    return _generator

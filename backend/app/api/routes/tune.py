"""
난이도 미세조절 — 색 재배치 튜너 (모양 고정, 재생성 없음).

기존 프로덕션 생성 파이프라인과 완전 분리된 독립 도구. 이미 생성된 레벨의 타일 '색(t1~15)'만
위치 간 재배치(순열)해 목표 클리어율에 가까운 배치를 골라낸다.

원리: match-3-collect은 같은 색 3개를 dock(7슬롯) 넘치기 전에 모아야 함.
  - 같은 색이 노출순서상 뭉침 → 빨리 매칭 = 쉬움
  - 같은 색이 흩어짐 → dock 압박 = 어려움
→ 색 배치를 뭉침~흩음 K단계로 만들어 기존 RL로 평가, target에 가장 가까운 것 선택.

불변식: 색 멀티셋의 순열이라 타입별 개수 불변 → ÷3 자동 보존. 속성(chain/grass/ice/bomb)은
위치 고정, 색(td[0])만 재배치. key(t16)/컨테이너(craft/stack)/미배정(t0)은 제외.

검증(RL)은 기존 순차검증과 동일 함수(_parallel_point_sweep + population_clear_rate) 재사용 →
튜너 통과 == 순차검증 통과 (이중잣대 없음).
"""
import copy
import random as _random
import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.mc_difficulty import (
    CASUAL_SKILL_MEAN, CASUAL_SKILL_STD, population_clear_rate,
    DEFAULT_ROLLOUTS_PER_POINT, DEFAULT_BASE_SEED, target_casual_clear_rate,
)
from .rl_sim import _parallel_point_sweep

router = APIRouter(prefix="/api/tune", tags=["tune"])
logger = logging.getLogger(__name__)

_COLOR_RE = re.compile(r"^t(\d+)$")


def _reveal_index(level: Dict[str, Any]) -> Dict[Tuple[int, str], int]:
    """각 타일이 열리는 '노출 파도' 순서. 게임 홀짝 커버 규칙으로 위→아래 peeling.
    (같은홀짝=(x,y) / 위층 큼=2x2 / 위층 작음=(-1..0)² — FindAllUpperTiles 정합.)"""
    nl = int(level.get("layer", 0) or 0)
    cols = {i: int((level.get(f"layer_{i}", {}) or {}).get("col", 8)) for i in range(nl)}
    tiles = {i: set(((level.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).keys()) for i in range(nl)}

    def covering(L: int, x: int, y: int) -> List[Tuple[int, str]]:
        out: List[Tuple[int, str]] = []
        for U in range(L + 1, nl):
            if L % 2 == U % 2:
                out.append((U, f"{x}_{y}"))
            elif cols[U] > cols[L]:
                for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    out.append((U, f"{x+dx}_{y+dy}"))
            else:
                for dx, dy in ((-1, -1), (0, -1), (-1, 0), (0, 0)):
                    out.append((U, f"{x+dx}_{y+dy}"))
        return out

    rem = {(i, p) for i in range(nl) for p in tiles[i]}
    cov: Dict[Tuple[int, str], List[Tuple[int, str]]] = {}
    for (L, p) in rem:
        x, y = map(int, p.split("_"))
        cov[(L, p)] = covering(L, x, y)

    idx: Dict[Tuple[int, str], int] = {}
    wave = 0
    while rem:
        exposed = [t for t in rem if not any(c in rem for c in cov[t])]
        if not exposed:  # 이론상 데드락 잔여 — 남은 것 동일 파도
            for t in rem:
                idx[t] = wave
            break
        for t in exposed:
            idx[t] = wave
        rem -= set(exposed)
        wave += 1
    return idx


def _field_colors(level: Dict[str, Any]) -> Tuple[List[Tuple[int, str]], Dict[str, int]]:
    """재배치 대상 = td[0]가 t1~t15인 필드 타일(속성 유무 무관). 색 위치 목록 + 색별 개수."""
    nl = int(level.get("layer", 0) or 0)
    positions: List[Tuple[int, str]] = []
    counts: Dict[str, int] = {}
    for i in range(nl):
        for p, td in ((level.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).items():
            if not (isinstance(td, list) and td):
                continue
            m = _COLOR_RE.match(str(td[0]))
            if m and 1 <= int(m.group(1)) <= 15:
                positions.append((i, p))
                counts[str(td[0])] = counts.get(str(td[0]), 0) + 1
    return positions, counts


def _make_seq(counts: Dict[str, int], block: int) -> List[str]:
    """색 배정 시퀀스. block 큼 → 색끼리 연속(뭉침=쉬움), block=1 → 라운드로빈(분산=어려움).
    (원래 색 튜너 K-후보 스펙트럼용 — 이산 block. tune_color는 아래 연속형 _make_seq_scatter 사용.)"""
    labels = sorted(counts, key=lambda l: int(l[1:]))
    q = dict(counts)
    seq: List[str] = []
    while any(v > 0 for v in q.values()):
        for l in labels:
            if q[l] <= 0:
                continue
            take = min(block, q[l])
            seq.extend([l] * take)
            q[l] -= take
    return seq


def _make_seq_scatter(counts: Dict[str, int], spread: float, seed: int) -> List[str]:
    """연속 인접률 기반 색 시퀀스. spread=이전과 '다른 색'을 고를 확률.
      spread 0 → 항상 같은 색 이어붙임(완전 뭉침=쉬움)
      spread 1 → 항상 다른 색(완전 분산=어려움)
      spread 0.5 → 약 절반만 인접 → 전 구간 매끄럽게 변함(이산 block의 죽은 구간 제거).
    노출순 시퀀스라 dock 압박(같은 색 3개 모으는 난이도)에 직접 대응. 결정적(seed 고정)."""
    rng = _random.Random(seed)
    q = dict(counts)
    labels = sorted(counts, key=lambda l: int(l[1:]))
    seq: List[str] = []
    prev: Optional[str] = None
    total = sum(q.values())
    for _ in range(total):
        avail = [l for l in labels if q[l] > 0]
        if not avail:
            break
        want_diff = rng.random() < spread
        others = [l for l in avail if l != prev]
        if want_diff and others:
            # 다른 색: 잔량 많은 것 우선(균형) — 한 색이 뒤에 몰려 뭉치는 것 방지
            pick = max(others, key=lambda l: q[l])
        elif (not want_diff) and prev is not None and q.get(prev, 0) > 0:
            pick = prev  # 같은 색 이어붙임
        else:
            pick = max(avail, key=lambda l: q[l])
        seq.append(pick)
        q[pick] -= 1
        prev = pick
    return seq


def _apply_colors(level: Dict[str, Any], positions: List[Tuple[int, str]], colors: List[str]) -> Dict[str, Any]:
    """positions 순서에 colors(td[0])만 재배정. 속성 td[1:]·위치 불변 → 기믹·÷3 보존."""
    lv = copy.deepcopy(level)
    for (L, p), color in zip(positions, colors):
        lv[f"layer_{L}"]["tiles"][p][0] = color
    return lv


def _apply(level: Dict[str, Any], positions: List[Tuple[int, str]], seq: List[str]) -> Dict[str, Any]:
    """positions(노출순 정렬)에 seq 색을 재배정한 새 레벨(딥카피). 속성 td[1:] 유지."""
    lv = copy.deepcopy(level)
    for (L, p), color in zip(positions, seq):
        td = lv[f"layer_{L}"]["tiles"][p]
        td[0] = color
    return lv


class TuneRequest(BaseModel):
    level_json: Dict[str, Any]
    # 목표: (a) target_clear_rate 직접 지정 or (b) target_difficulty(+scale) → 순차검증과 동일 산식으로 변환.
    target_clear_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    target_difficulty: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    target_clear_rate_scale: Optional[float] = 1.0   # 보스=0.5 등 (순차검증 정합)
    skill_mean: Optional[float] = None
    skill_std: Optional[float] = None
    candidates: int = Field(default=6, ge=2, le=12)
    seed: Optional[int] = None
    rollouts_per_point: Optional[int] = None
    skill_grid: Optional[List[float]] = None
    max_moves: Optional[int] = None


class TuneCandidate(BaseModel):
    block: int
    predicted_clear_rate: float


class TuneResult(BaseModel):
    tuned: bool
    best_level_json: Dict[str, Any]
    predicted_clear_rate: float
    original_predicted: float
    target_clear_rate: float
    candidates: List[TuneCandidate]
    field_tiles: int
    color_types: int
    elapsed_ms: int


@router.post("/arrangement", response_model=TuneResult)
def tune_arrangement(req: TuneRequest) -> TuneResult:
    """색 재배치로 목표 클리어율에 가장 가까운 배치 선택. 모양·÷3·기믹 불변."""
    if not req.level_json or not req.level_json.get("layer"):
        raise HTTPException(status_code=400, detail="유효한 level_json 필요")
    # 목표 클리어율 결정: 직접값 우선, 없으면 target_difficulty에서 순차검증 동일 산식으로 변환.
    if req.target_clear_rate is not None:
        target_cr = float(req.target_clear_rate)
    elif req.target_difficulty is not None:
        target_cr = round(target_casual_clear_rate(req.target_difficulty)
                          * float(req.target_clear_rate_scale or 1.0), 4)
    else:
        raise HTTPException(status_code=400, detail="target_clear_rate 또는 target_difficulty 필요")
    started = time.monotonic()

    positions, counts = _field_colors(req.level_json)
    n_colors = len(counts)
    # 조절 불가(색 종류<2 or 타일 부족) → 원본 그대로 반환
    if n_colors < 2 or len(positions) < 6:
        return TuneResult(
            tuned=False, best_level_json=req.level_json, predicted_clear_rate=0.0,
            original_predicted=0.0, target_clear_rate=target_cr,
            candidates=[], field_tiles=len(positions), color_types=n_colors,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    reveal = _reveal_index(req.level_json)
    positions.sort(key=lambda t: (reveal.get(t, 1 << 30), t[0], t[1]))

    # block 스펙트럼: max_count(완전 뭉침) → 1(완전 분산). K단계, 중복 제거.
    max_c = max(counts.values())
    if req.candidates >= 2 and max_c > 1:
        raw = [round(max_c - (max_c - 1) * i / (req.candidates - 1)) for i in range(req.candidates)]
    else:
        raw = [max_c, 1]
    blocks: List[int] = []
    for b in raw:
        b = max(1, int(b))
        if b not in blocks:
            blocks.append(b)

    # block 스펙트럼(양극단 확보) + 랜덤 순열(중간 채움 — block 휴리스틱이 비단조/성긴 레벨 보완).
    block_seqs = [_make_seq(counts, b) for b in blocks]
    full_multiset: List[str] = []
    for c, n in sorted(counts.items(), key=lambda kv: int(kv[0][1:])):
        full_multiset.extend([c] * n)
    n_random = 4
    rng = _random.Random(int(req.level_json.get("randSeed", 0) or 0) * 131 + 7)  # 결정적
    rand_seqs: List[List[str]] = []
    for _ in range(n_random):
        s = list(full_multiset)
        rng.shuffle(s)
        rand_seqs.append(s)
    cand_seqs = block_seqs + rand_seqs
    cand_blocks = list(blocks) + [-1] * n_random  # -1 = 랜덤 표식
    cand_levels = [_apply(req.level_json, positions, seq) for seq in cand_seqs]
    # 원본도 후보에 포함 — 현 배치가 이미 최적일 수 있음
    items = [(i, lv) for i, lv in enumerate([req.level_json] + cand_levels)]

    _rollouts = req.rollouts_per_point if req.rollouts_per_point is not None else DEFAULT_ROLLOUTS_PER_POINT
    _seed = req.seed if req.seed is not None else DEFAULT_BASE_SEED
    try:
        results = _parallel_point_sweep(
            items, req.skill_grid, _rollouts, _seed, req.max_moves,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[tune] 시뮬 실패")
        raise HTTPException(status_code=500, detail=f"시뮬레이션 실패: {exc}") from exc

    mean = req.skill_mean if req.skill_mean is not None else CASUAL_SKILL_MEAN
    std = req.skill_std if req.skill_std is not None else CASUAL_SKILL_STD

    def predicted(res: Dict[str, Any]) -> float:
        if res.get("error"):
            return -1.0  # 실패 후보 배제
        return round(population_clear_rate(res.get("skill_curve", []), mean=mean, std=std), 4)

    orig_pred = predicted(results[0])
    cand_preds = [predicted(results[i + 1]) for i in range(len(cand_levels))]

    # target 최근접 선택 (원본 포함). 실패(-1) 배제.
    pool: List[Tuple[float, Dict[str, Any]]] = []
    if orig_pred >= 0:
        pool.append((orig_pred, req.level_json))
    for lv, pr in zip(cand_levels, cand_preds):
        if pr >= 0:
            pool.append((pr, lv))
    if not pool:
        raise HTTPException(status_code=500, detail="모든 후보 시뮬 실패")
    best_pred, best_lv = min(pool, key=lambda x: abs(x[0] - target_cr))

    return TuneResult(
        tuned=(best_lv is not req.level_json),
        best_level_json=best_lv,
        predicted_clear_rate=best_pred,
        original_predicted=orig_pred if orig_pred >= 0 else 0.0,
        target_clear_rate=target_cr,
        candidates=[TuneCandidate(block=b, predicted_clear_rate=p)
                    for b, p in zip(cand_blocks, cand_preds)],
        field_tiles=len(positions),
        color_types=n_colors,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 기믹 튜너 (강도 다이얼) — 모양·색 고정, 속성기믹 밀도만 재조정. 3단 다이얼 중 '중간폭'.
#   원리: 속성기믹(chain/ice/grass/link/curtain/bomb/frog/teleport/unknown)은 td[1]만
#   추가/제거 → 타입카운트 불변 = ÷3 자동보존. key/craft/stack(구조·골)은 제외.
#   강도 0=기믹 최소(튜토리얼만) ~ 1=최대밀도. 결정적 배치(같은 강도+시드=같은 결과).
#   배치·클리어제약(chain 이웃/grass 홀짝/unknown 커버)은 생성기 검증헬퍼 재사용.
# ─────────────────────────────────────────────────────────────────────────────
from ...core.generator import LevelGenerator  # noqa: E402

_gen_for_tune = LevelGenerator()

# 속성기믹 마커(td[1]) 판별 — 마커 base(첫 '_' 앞)로 매칭해 plain/countdown/direction 변형 모두 포착
# (bomb / bomb_5, link / link_e, curtain / curtain_close, teleport / teleporter 등). key/컨테이너 제외.
_ATTR_BASES = {"chain", "ice", "grass", "frog", "unknown", "bomb", "curtain", "link", "teleport", "teleporter"}
# 강도 다이얼로 배치할 후보 타입(생성기 _ensure_* 가 유효배치 처리).
_TUNABLE_TYPES = ["chain", "ice", "grass", "link", "curtain", "bomb", "frog", "teleport"]
_MAX_GIMMICK_FRAC = 0.22  # 강도 1.0에서 필드타일의 최대 몇 %를 기믹화 (다이얼 전구간 유효밴드 유지)


def _is_attr_marker(marker: Any) -> bool:
    s = str(marker or "")
    return bool(s) and s.split("_")[0] in _ATTR_BASES


def _strip_attr_gimmicks(level: Dict[str, Any]) -> None:
    """필드 타일의 속성기믹(td[1])을 제거(리셋). key/컨테이너/색(td[0])은 불변.
    plain 'bomb' 등 변형도 base 매칭으로 확실히 제거 → _ensure가 정상 bomb_N 재배치."""
    nl = int(level.get("layer", 0) or 0)
    for i in range(nl):
        for _p, td in ((level.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).items():
            if isinstance(td, list) and len(td) > 1 and _is_attr_marker(td[1]):
                td[1] = ""


def _count_field_tiles(level: Dict[str, Any]) -> int:
    n = 0
    nl = int(level.get("layer", 0) or 0)
    for i in range(nl):
        for _p, td in ((level.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).items():
            if isinstance(td, list) and td:
                t0 = str(td[0])
                if t0.startswith("t") and t0[1:].isdigit() and t0 != "t0":
                    n += 1
    return n


def _count_attr_gimmicks(level: Dict[str, Any]) -> int:
    n = 0
    nl = int(level.get("layer", 0) or 0)
    for i in range(nl):
        for _p, td in ((level.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).items():
            if isinstance(td, list) and len(td) > 1 and _is_attr_marker(td[1]):
                n += 1
    return n


def _unlocked_attr_types(level_number: int) -> List[str]:
    """해당 레벨에서 언락된 속성기믹 타입(정본 언락맵). craft/stack/key 제외."""
    unlocked = {g for lvl, g in _gen_for_tune.TUTORIAL_UNLOCK_LEVELS.items() if lvl <= level_number}
    return [g for g in _TUNABLE_TYPES if g in unlocked]


def _gimmick_arrangement(level: Dict[str, Any], level_number: int,
                         intensity: float, seed: int) -> Tuple[Dict[str, Any], int, List[str]]:
    """강도(0~1)로 속성기믹 밀도 재배치한 새 레벨. (lv, gimmick_count, eligible) 반환.
    리셋(strip)→강도→타입분배→유효배치. 튜토리얼 기믹 최소3 보장. td[1]만 변경(÷3·색 불변)."""
    lv = copy.deepcopy(level)
    _random.seed(seed * 1009 + int(intensity * 1000) + level_number)
    field_n = _count_field_tiles(lv)
    eligible = _unlocked_attr_types(level_number)
    tutorial = _gen_for_tune.TUTORIAL_UNLOCK_LEVELS.get(level_number)
    _strip_attr_gimmicks(lv)
    total_target = round(intensity * _MAX_GIMMICK_FRAC * field_n) if field_n else 0
    tut_is_attr = tutorial in _TUNABLE_TYPES or tutorial == "unknown"
    if tut_is_attr and tutorial not in eligible and tutorial != "unknown":
        eligible = eligible + [tutorial]
    per_type: Dict[str, int] = {t: 0 for t in eligible}
    if tut_is_attr:
        per_type.setdefault(tutorial, 0)
        per_type[tutorial] = max(3, per_type[tutorial])
        total_target = max(total_target, 3)
    remaining = max(0, total_target - sum(per_type.values()))
    if eligible:
        i = 0
        while remaining > 0:
            per_type[eligible[i % len(eligible)]] += 1
            remaining -= 1
            i += 1
    for t, cnt in per_type.items():
        if cnt <= 0:
            continue
        if t == "unknown":
            lv = _gen_for_tune._ensure_unknown_tutorial_count(lv, cnt)
        else:
            lv = _gen_for_tune._ensure_tutorial_gimmick_count(lv, t, cnt)
    return lv, _count_attr_gimmicks(lv), eligible


class GimmickTuneRequest(BaseModel):
    level_json: Dict[str, Any]
    level_number: int
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)  # 다이얼: 0=최소 ~ 1=최대밀도
    seed: Optional[int] = None
    skill_mean: Optional[float] = None
    skill_std: Optional[float] = None
    rollouts_per_point: Optional[int] = None
    skill_grid: Optional[List[float]] = None
    max_moves: Optional[int] = None
    evaluate: bool = True  # False면 배치만(즉시), 예측 생략


class GimmickTuneResult(BaseModel):
    best_level_json: Dict[str, Any]
    predicted_clear_rate: float
    original_predicted: float
    intensity: float
    gimmick_count: int
    original_gimmick_count: int
    field_tiles: int
    eligible_types: List[str]
    elapsed_ms: int


@router.post("/gimmick", response_model=GimmickTuneResult)
def tune_gimmick(req: GimmickTuneRequest) -> GimmickTuneResult:
    """강도 다이얼로 속성기믹 밀도 재조정. 모양·색·÷3 불변. 결정적(강도+시드 고정)."""
    if not req.level_json or not req.level_json.get("layer"):
        raise HTTPException(status_code=400, detail="유효한 level_json 필요")
    started = time.monotonic()

    orig_gimmicks = _count_attr_gimmicks(req.level_json)
    seed = req.seed if req.seed is not None else int(req.level_json.get("randSeed", 0) or 0)
    lv, new_gimmicks, eligible = _gimmick_arrangement(req.level_json, req.level_number, req.intensity, seed)
    # [LINK_SANITIZE] 기믹 재배치가 링크 타겟에 기믹을 얹거나 링크를 옮겨 고아/불량 링크를
    # 만들 수 있다 → 인게임 FindLinkTile 크래시. 반환 전 생성기 정화기로 무효 링크 plain화.
    lv = _gen_for_tune._strip_orphaned_link_tiles(lv)

    if not req.evaluate:
        return GimmickTuneResult(
            best_level_json=lv, predicted_clear_rate=0.0, original_predicted=0.0,
            intensity=req.intensity, gimmick_count=new_gimmicks,
            original_gimmick_count=orig_gimmicks, field_tiles=_count_field_tiles(req.level_json),
            eligible_types=eligible, elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    # 6) RL 평가 (원본 + 조정본) — 색 튜너와 동일 함수
    _rollouts = req.rollouts_per_point if req.rollouts_per_point is not None else DEFAULT_ROLLOUTS_PER_POINT
    _seed = req.seed if req.seed is not None else DEFAULT_BASE_SEED
    try:
        results = _parallel_point_sweep(
            [(0, req.level_json), (1, lv)], req.skill_grid, _rollouts, _seed, req.max_moves,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[tune/gimmick] 시뮬 실패")
        raise HTTPException(status_code=500, detail=f"시뮬레이션 실패: {exc}") from exc

    mean = req.skill_mean if req.skill_mean is not None else CASUAL_SKILL_MEAN
    std = req.skill_std if req.skill_std is not None else CASUAL_SKILL_STD

    def _pred(res: Dict[str, Any]) -> float:
        if res.get("error"):
            return 0.0
        return round(population_clear_rate(res.get("skill_curve", []), mean=mean, std=std), 4)

    return GimmickTuneResult(
        best_level_json=lv,
        predicted_clear_rate=_pred(results[1]),
        original_predicted=_pred(results[0]),
        intensity=req.intensity,
        gimmick_count=new_gimmicks,
        original_gimmick_count=orig_gimmicks,
        field_tiles=_count_field_tiles(req.level_json),
        eligible_types=eligible,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Potts–Metropolis 색 뭉침 엔진 (Kawasaki 스왑 = 색개수 보존 = ÷3 안전)
#   에너지 E = Σ_(i,j)∈W w·[color_i==color_j]  (같은색 인접쌍 = Potts / join-count)
#   이웃그래프 W = 공간(같은레이어 rook 4방, α) + 노출순(reveal 연속쌍, β)
#   슬라이더 spread: E* = E_min + (E_max−E_min)(1−spread)  → 슬라이더가 지표에 선형(균등)
#   지표(UI) = 정규화 join-count index J∈[−1,+1] (Moran's I 직접 아님: 색=범주형).
# ─────────────────────────────────────────────────────────────────────────────
def _build_color_graph(level: Dict[str, Any], positions: List[Tuple[int, str]],
                       alpha: float = 1.0, beta: float = 1.0) -> List[Tuple[int, int, float]]:
    """이웃그래프 edge 목록 [(i, j, weight)] — positions 인덱스 기준.
    공간: 같은 레이어 rook 인접(가중 alpha). 노출순: reveal 정렬 연속쌍(가중 beta)."""
    idx = {p: k for k, p in enumerate(positions)}
    edges: List[Tuple[int, int, float]] = []
    seen = set()
    # 공간 rook (같은 레이어)
    for k, (layer, pos) in enumerate(positions):
        try:
            x, y = map(int, pos.split("_"))
        except Exception:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            npos = (layer, f"{x+dx}_{y+dy}")
            j = idx.get(npos)
            if j is not None and j > k:
                key = (k, j)
                if key not in seen:
                    seen.add(key)
                    edges.append((k, j, alpha))
    # 노출순 연속쌍 (positions는 호출부에서 reveal 정렬됨)
    for k in range(len(positions) - 1):
        key = (k, k + 1)
        if key not in seen:
            seen.add(key)
            edges.append((k, k + 1, beta))
        else:
            # 이미 공간 edge로 있으면 가중 합산 대신 유지(중복 방지). beta 별도 추가.
            edges.append((k, k + 1, beta))
    return edges


def _color_energy(colors: List[str], edges: List[Tuple[int, int, float]]) -> float:
    """같은색 인접 가중합 (Potts 에너지 = join-count)."""
    e = 0.0
    for i, j, w in edges:
        if colors[i] == colors[j]:
            e += w
    return e


def _adjacency(n: int, edges: List[Tuple[int, int, float]]) -> List[List[Tuple[int, float]]]:
    adj: List[List[Tuple[int, float]]] = [[] for _ in range(n)]
    for i, j, w in edges:
        adj[i].append((j, w))
        adj[j].append((i, w))
    return adj


def _anneal_colors(colors0: List[str], edges: List[Tuple[int, int, float]],
                   target_E: float, seed: int, budget: int,
                   greedy: bool = False) -> Tuple[List[str], float]:
    """Kawasaki(색 스왑)+Metropolis로 에너지를 target_E에 수렴. 색 멀티셋 불변(÷3 보존).
    greedy=True: 목표방향 개선 스왑만 수락(오르막 없음) → target 정밀 명중(중간구간 단조)."""
    import math
    colors = list(colors0)
    n = len(colors)
    adj = _adjacency(n, edges)
    E = _color_energy(colors, edges)
    total_w = sum(w for _, _, w in edges) or 1.0
    T = 1e-9 if greedy else max(1e-6, 0.02 * total_w)
    rng = _random.Random(seed)
    for _ in range(budget):
        if abs(E - target_E) < 0.5:
            break
        a = rng.randrange(n)
        b = rng.randrange(n)
        ca, cb = colors[a], colors[b]
        if ca == cb:
            continue
        dE = 0.0
        for nb, w in adj[a]:
            if nb == b:
                continue
            dE += w * ((colors[nb] == cb) - (colors[nb] == ca))
        for nb, w in adj[b]:
            if nb == a:
                continue
            dE += w * ((colors[nb] == ca) - (colors[nb] == cb))
        newE = E + dE
        cur, new = abs(E - target_E), abs(newE - target_E)
        if new < cur or (not greedy and rng.random() < math.exp(-(new - cur) / T)):
            colors[a], colors[b] = cb, ca
            E = newE
    return colors, E


def _greedy_extreme(counts: Dict[str, int], positions: List[Tuple[int, str]],
                    edges: List[Tuple[int, int, float]], cluster: bool,
                    seed: int) -> Tuple[List[str], float]:
    """극단 배치 반환: cluster=True → 최대 뭉침(E_max), False → 최대 분산(E_min).
    reveal순 quota(뭉침) 또는 scatter(분산) 시드 → SA로 극값 근접. (cols, E) 반환."""
    labels = sorted(counts, key=lambda l: int(l[1:]))
    if cluster:
        seq: List[str] = []
        for l in labels:
            seq.extend([l] * counts[l])            # 완전 뭉침 시드(색별 연속)
    else:
        seq = _make_seq_scatter(counts, 1.0, seed)  # 완전 분산 시드
    # SA로 극값 근접 (뭉침=E 최대화 target=+inf / 분산=E 최소화 target=-inf)
    target = float("inf") if cluster else float("-inf")
    cols, E = _anneal_colors(seq, edges, target, seed + 1, budget=len(positions) * 25)
    E0 = _color_energy(seq, edges)
    if (cluster and E0 > E) or ((not cluster) and E0 < E):
        return seq, E0
    return cols, E


def _color_context(level: Dict[str, Any], seed: int) -> Optional[Dict[str, Any]]:
    """색 재배치 사전계산(그래프·극단·정규화 상수). spread 스윕 시 1회만 계산해 재사용.
    조절불가(색<2 or 타일<6)면 None."""
    positions, counts = _field_colors(level)
    if len(counts) < 2 or len(positions) < 6:
        return None
    reveal = _reveal_index(level)
    positions.sort(key=lambda t: (reveal.get(t, 1 << 30), t[0], t[1]))
    edges = _build_color_graph(level, positions)
    cluster_cols, e_max = _greedy_extreme(counts, positions, edges, cluster=True, seed=seed)
    disperse_cols, e_min = _greedy_extreme(counts, positions, edges, cluster=False, seed=seed)
    if e_max <= e_min:
        e_max = e_min + 1.0
    total_w = sum(w for _, _, w in edges) or 1.0
    total_t = sum(counts.values()) or 1
    e_rand = min(e_max, max(e_min, total_w * sum((c / total_t) ** 2 for c in counts.values())))
    return {"positions": positions, "counts": counts, "edges": edges,
            "cluster_cols": cluster_cols, "disperse_cols": disperse_cols,
            "e_max": e_max, "e_min": e_min, "e_rand": e_rand, "seed": seed}


def _color_at_spread(level: Dict[str, Any], ctx: Dict[str, Any],
                     spread: float) -> Tuple[Dict[str, Any], float, int]:
    """ctx 기반으로 spread(0뭉침~1분산) 배치 생성. (lv, cluster_index, avg_run) 반환.
    index-선형 매핑(0.5=랜덤 전환점) + greedy 목표추적 → 단조·균등."""
    e_max, e_min, e_rand = ctx["e_max"], ctx["e_min"], ctx["e_rand"]
    ti = 1.0 - 2.0 * float(spread)
    target_E = e_rand + ti * (e_max - e_rand) if ti >= 0 else e_rand + ti * (e_rand - e_min)
    if spread <= 0.001:
        colors, E = ctx["cluster_cols"], e_max
    elif spread >= 0.999:
        colors, E = ctx["disperse_cols"], e_min
    else:
        seed_cols = ctx["cluster_cols"] if target_E >= (e_max + e_min) / 2 else ctx["disperse_cols"]
        budget = min(12000, max(3000, len(ctx["positions"]) * 60))
        colors, E = _anneal_colors(seed_cols, ctx["edges"], target_E, ctx["seed"], budget, greedy=True)
    lv = _apply_colors(level, ctx["positions"], colors)
    if E >= e_rand:
        ci = (E - e_rand) / max(1e-6, e_max - e_rand)
    else:
        ci = (E - e_rand) / max(1e-6, e_rand - e_min)
    ci = round(max(-1.0, min(1.0, ci)), 3)
    runs = 1
    for a, b in zip(colors, colors[1:]):
        if a != b:
            runs += 1
    block = round(len(colors) / max(1, runs)) if colors else 0
    return lv, ci, block


class ColorTuneRequest(BaseModel):
    level_json: Dict[str, Any]
    spread: float = Field(default=0.5, ge=0.0, le=1.0)  # 0=뭉침(쉬움) ~ 1=흩어짐(어려움)
    evaluate: bool = True
    skill_mean: Optional[float] = None
    skill_std: Optional[float] = None
    seed: Optional[int] = None
    rollouts_per_point: Optional[int] = None
    skill_grid: Optional[List[float]] = None
    max_moves: Optional[int] = None


class ColorTuneResult(BaseModel):
    best_level_json: Dict[str, Any]
    predicted_clear_rate: float
    original_predicted: float
    spread: float
    block: int              # 참고: 평균 런길이(뭉침 정도)
    cluster_index: float    # join-count 정규화 −1(체스판)~0(랜덤)~+1(뭉침)
    field_tiles: int
    color_types: int
    elapsed_ms: int


@router.post("/color", response_model=ColorTuneResult)
def tune_color(req: ColorTuneRequest) -> ColorTuneResult:
    """색 스프레드 직접 조절. spread 0=뭉침(쉬움)~1=흩어짐(어려움). 모양·기믹·÷3 불변."""
    if not req.level_json or not req.level_json.get("layer"):
        raise HTTPException(status_code=400, detail="유효한 level_json 필요")
    started = time.monotonic()

    positions, counts = _field_colors(req.level_json)
    n_colors = len(counts)
    seed = req.seed if req.seed is not None else (int(req.level_json.get("randSeed", 0) or 0) * 131 + 7)
    ctx = _color_context(req.level_json, seed)
    if ctx is None:
        return ColorTuneResult(
            best_level_json=req.level_json, predicted_clear_rate=0.0, original_predicted=0.0,
            spread=req.spread, block=0, cluster_index=0.0,
            field_tiles=len(positions), color_types=n_colors,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    lv, cluster_index, block = _color_at_spread(req.level_json, ctx, req.spread)

    if not req.evaluate:
        return ColorTuneResult(
            best_level_json=lv, predicted_clear_rate=0.0, original_predicted=0.0,
            spread=req.spread, block=block, cluster_index=cluster_index,
            field_tiles=len(positions), color_types=n_colors,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    _rollouts = req.rollouts_per_point if req.rollouts_per_point is not None else DEFAULT_ROLLOUTS_PER_POINT
    _seed = req.seed if req.seed is not None else DEFAULT_BASE_SEED
    try:
        results = _parallel_point_sweep(
            [(0, req.level_json), (1, lv)], req.skill_grid, _rollouts, _seed, req.max_moves,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[tune/color] 시뮬 실패")
        raise HTTPException(status_code=500, detail=f"시뮬레이션 실패: {exc}") from exc

    mean = req.skill_mean if req.skill_mean is not None else CASUAL_SKILL_MEAN
    std = req.skill_std if req.skill_std is not None else CASUAL_SKILL_STD

    def _pred(res: Dict[str, Any]) -> float:
        if res.get("error"):
            return 0.0
        return round(population_clear_rate(res.get("skill_curve", []), mean=mean, std=std), 4)

    return ColorTuneResult(
        best_level_json=lv,
        predicted_clear_rate=_pred(results[1]),
        original_predicted=_pred(results[0]),
        spread=req.spread, block=block, cluster_index=cluster_index,
        field_tiles=len(positions), color_types=n_colors,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 타일 종류 수 튜너 — 필드 타일을 N개 색 팔레트로 재타이핑. 종류↑ = 어려움(트레이 다양↑).
#   위치·기믹·컨테이너 불변. ÷3 클리어가능은 _finalize_divisibility_guarantee 로 보장.
# ─────────────────────────────────────────────────────────────────────────────
class TileCountTuneRequest(BaseModel):
    level_json: Dict[str, Any]
    tile_count: int = Field(..., ge=2, le=15)  # 목표 사용 타일 종류 수
    evaluate: bool = False                      # true면 RL 예측까지
    seed: Optional[int] = None
    skill_mean: Optional[float] = None
    skill_std: Optional[float] = None
    rollouts_per_point: Optional[int] = None
    skill_grid: Optional[List[float]] = None
    max_moves: Optional[int] = None


class TileCountTuneResult(BaseModel):
    best_level_json: Dict[str, Any]
    predicted_clear_rate: float
    original_predicted: float
    tile_count: int          # 실제 적용된 종류 수(요청값 clamp 결과)
    requested: int           # 요청값
    field_tiles: int
    color_types: int         # 최종 필드 색 종류 수(finalize 후)
    elapsed_ms: int


@router.post("/tilecount", response_model=TileCountTuneResult)
def tune_tilecount(req: TileCountTuneRequest) -> TileCountTuneResult:
    """필드 타일을 N개 색 팔레트로 재타이핑(종류 수 조절). 종류 많을수록 어려움.
    위치·기믹·컨테이너 불변. ÷3 클리어가능은 finalize 로 보장(필요시 잉여 1~2개 트림)."""
    if not req.level_json or not req.level_json.get("layer"):
        raise HTTPException(status_code=400, detail="유효한 level_json 필요")
    started = time.monotonic()

    from ...core.generator import select_color_balanced_tiles

    positions, counts = _field_colors(req.level_json)
    total = len(positions)
    # 종류당 최소 3개(÷3) 필요 → 상한 = total//3. 요청값을 [2, min(15, total//3)] 로 clamp.
    max_types = max(1, total // 3)
    n = max(1, min(int(req.tile_count), 15, max_types))
    seed = req.seed if req.seed is not None else (int(req.level_json.get("randSeed", 0) or 0) * 137 + 11)

    if total < 3 or max_types < 2:
        # 재타이핑 불가(필드 타일 부족) → 원본 그대로
        return TileCountTuneResult(
            best_level_json=req.level_json, predicted_clear_rate=0.0, original_predicted=0.0,
            tile_count=len(counts), requested=int(req.tile_count),
            field_tiles=total, color_types=len(counts),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    # [컨테이너-aware] 컨테이너(craft/stack)는 런타임에 내부 타입을 필드로 배출한다. 클리어가능은
    # 타입별 (필드 + 컨테이너배출) ÷3 이어야 한다(단순 필드 ÷3 아님). 재타이핑이 컨테이너 배출 타입을
    # 팔레트서 빼면 그 타입이 orphan(합 1~2) → 클리어불가. → 배출 타입 강제포함 + 완성분 필드 배정.
    c_out: Dict[str, int] = {}
    nl = int(req.level_json.get("layer", 0) or 0)
    for i in range(nl):
        for td in ((req.level_json.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).values():
            if isinstance(td, list) and len(td) > 2 and isinstance(td[2], list) and len(td[2]) > 1:
                for part in str(td[2][1]).split("_"):
                    if part and part[0] == "t" and part[1:].isdigit():
                        c_out[part] = c_out.get(part, 0) + 1
    # 완성 필요 타입(배출량이 ÷3 아닌 것) = 반드시 팔레트 포함
    forced = [t for t, cnt in c_out.items() if cnt % 3 != 0]
    # N색 균형 팔레트 — 강제타입 우선, 나머지 균형선택으로 채움
    n = max(n, len(forced))
    n = min(n, 15, max_types)
    palette = list(dict.fromkeys(forced))  # 강제타입(중복제거, 순서보존)
    if len(palette) < n:
        extra_pool = select_color_balanced_tiles(15, seed=seed, max_index=15)
        for t in extra_pool:
            if len(palette) >= n:
                break
            if t not in palette:
                palette.append(t)
    types = palette[:n]
    n = len(types)

    # 타입별 필드 최소분 r_t = (-c_out) mod 3 (컨테이너와 합쳐 ÷3). 나머지는 3단위 블록으로 균등 분배.
    r = {t: (3 - (c_out.get(t, 0) % 3)) % 3 for t in types}
    field_counts = {t: r[t] for t in types}
    blocks = (total - sum(field_counts.values())) // 3  # 원본 ÷3-정합이라 정수·≥0 보장
    for k in range(max(0, blocks)):
        field_counts[types[k % n]] += 3
    # 합 보정(반올림 오차 방어) — total 과 어긋나면 마지막 타입에서 ±3 조정
    diff = total - sum(field_counts.values())
    if diff:
        # diff 는 3의 배수여야 정상. 아니면 finalize 가 잉여 트림으로 마무리.
        adj = types[0]
        field_counts[adj] = max(0, field_counts[adj] + diff)

    # 노출순 라운드로빈 배정(결정적) — 분산 중립. 색 뭉침/흩어짐은 색 스프레드 다이얼로 별도 조절.
    q = dict(field_counts)
    seq: List[str] = []
    while len(seq) < total:
        placed = False
        for t in types:
            if q.get(t, 0) > 0:
                seq.append(t)
                q[t] -= 1
                placed = True
                if len(seq) >= total:
                    break
        if not placed:
            break
    # 시퀀스가 total 보다 짧으면(분배 부족) 남은 위치는 첫 타입으로 채움(finalize 가 ÷3 보정)
    while len(seq) < total:
        seq.append(types[0])

    lv = _apply_colors(req.level_json, positions, seq)
    # NOTE: _finalize_divisibility_guarantee 는 호출하지 않는다. 그 게이트는 '필드 per-type ÷3'를
    # 강제(consolidate relabel)하는데, 컨테이너 배출 타입은 필드가 ÷3 아닌 나머지(r_t)를 가져야
    # (필드+컨테이너) ÷3 이 된다. finalize 를 태우면 그 나머지를 상쇄해 orphan 을 되살린다.
    # 위 배정은 이미 타입별 (필드+컨테이너) ÷3 + 총합 보존 → 클리어가능 자체보장.
    _, final_counts = _field_colors(lv)
    lv["useTileCount"] = len(final_counts)

    if not req.evaluate:
        return TileCountTuneResult(
            best_level_json=lv, predicted_clear_rate=0.0, original_predicted=0.0,
            tile_count=n, requested=int(req.tile_count),
            field_tiles=total, color_types=len(final_counts),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    _rollouts = req.rollouts_per_point if req.rollouts_per_point is not None else DEFAULT_ROLLOUTS_PER_POINT
    _seed = req.seed if req.seed is not None else DEFAULT_BASE_SEED
    try:
        results = _parallel_point_sweep(
            [(0, req.level_json), (1, lv)], req.skill_grid, _rollouts, _seed, req.max_moves,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[tune/tilecount] 시뮬 실패")
        raise HTTPException(status_code=500, detail=f"시뮬레이션 실패: {exc}") from exc

    mean = req.skill_mean if req.skill_mean is not None else CASUAL_SKILL_MEAN
    std = req.skill_std if req.skill_std is not None else CASUAL_SKILL_STD

    def _predtc(res: Dict[str, Any]) -> float:
        if res.get("error"):
            return 0.0
        return round(population_clear_rate(res.get("skill_curve", []), mean=mean, std=std), 4)

    return TileCountTuneResult(
        best_level_json=lv,
        predicted_clear_rate=_predtc(results[1]),
        original_predicted=_predtc(results[0]),
        tile_count=n, requested=int(req.tile_count),
        field_tiles=total, color_types=len(final_counts),
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 자동 튜너 — 순차검증/생성 연동. target 클리어율에 색+기믹 스윕으로 최근접 배치 자동선택.
#   ① 색 스윕(싸고 안전, ÷3중립) → 근접하면 반환.
#   ② 부족하면 기믹 스윕(넓은폭) → 그 위에 색 미세 → best 선택.
#   검증 RL = 순차검증과 동일(_parallel_point_sweep + population_clear_rate) = 이중잣대 없음.
# ─────────────────────────────────────────────────────────────────────────────
def _sweep_pick(base_level: Dict[str, Any], cand_levels: List[Dict[str, Any]],
                target_cr: float, mean: float, std: float,
                rollouts: int, seed: int, skill_grid, max_moves) -> Tuple[float, List[Tuple[Dict[str, Any], float]]]:
    """base + 후보들 RL 1회 병렬평가 → (원본예측, [(후보, 예측)...]). target 비교는 호출부."""
    items = [(0, base_level)] + [(i + 1, lv) for i, lv in enumerate(cand_levels)]
    results = _parallel_point_sweep(items, skill_grid, rollouts, seed, max_moves)

    def _pred(res: Dict[str, Any]) -> float:
        if res.get("error"):
            return -1.0
        return round(population_clear_rate(res.get("skill_curve", []), mean=mean, std=std), 4)

    orig = _pred(results[0])
    cand = [(cand_levels[i], _pred(results[i + 1])) for i in range(len(cand_levels))]
    return orig, cand


class AutoTuneRequest(BaseModel):
    level_json: Dict[str, Any]
    level_number: int
    target_clear_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    target_difficulty: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    target_clear_rate_scale: Optional[float] = 1.0
    tolerance: float = 0.12            # 이 안이면 '충분히 근접' 판정
    skill_mean: Optional[float] = None
    skill_std: Optional[float] = None
    seed: Optional[int] = None
    rollouts_per_point: Optional[int] = None
    skill_grid: Optional[List[float]] = None
    max_moves: Optional[int] = None
    try_gimmick: bool = True           # 색으로 부족할 때 기믹 스윕 허용


class AutoTuneResult(BaseModel):
    tuned: bool
    best_level_json: Dict[str, Any]
    predicted_clear_rate: float
    original_predicted: float
    target_clear_rate: float
    close: bool                        # tolerance 안 도달 여부
    lever: str                         # none/color/gimmick/gimmick+color
    spread: Optional[float] = None
    intensity: Optional[float] = None
    cluster_index: Optional[float] = None
    gimmick_count: Optional[int] = None
    elapsed_ms: int


@router.post("/auto", response_model=AutoTuneResult)
def tune_auto(req: AutoTuneRequest) -> AutoTuneResult:
    """target 클리어율에 색→(부족시)기믹 스윕으로 최근접 배치 자동선택. 모양·÷3 보존."""
    if not req.level_json or not req.level_json.get("layer"):
        raise HTTPException(status_code=400, detail="유효한 level_json 필요")
    started = time.monotonic()

    if req.target_clear_rate is not None:
        target_cr = float(req.target_clear_rate)
    elif req.target_difficulty is not None:
        target_cr = round(target_casual_clear_rate(req.target_difficulty)
                          * float(req.target_clear_rate_scale or 1.0), 4)
    else:
        raise HTTPException(status_code=400, detail="target_clear_rate 또는 target_difficulty 필요")

    mean = req.skill_mean if req.skill_mean is not None else CASUAL_SKILL_MEAN
    std = req.skill_std if req.skill_std is not None else CASUAL_SKILL_STD
    # 스크리닝 rollout(기본 20 < 정본 64): 후보선별용 근사. 최종 확정은 순차검증이 정밀 재측정.
    rollouts = req.rollouts_per_point if req.rollouts_per_point is not None else 20
    rl_seed = req.seed if req.seed is not None else DEFAULT_BASE_SEED
    arr_seed = int(req.level_json.get("randSeed", 0) or 0) * 131 + 7

    best_lv = req.level_json
    best_pred = -1.0
    best_meta: Dict[str, Any] = {"lever": "none", "spread": None, "intensity": None,
                                 "cluster_index": None, "gimmick_count": None}
    orig_pred = 0.0

    def _consider(lv, pred, lever, **meta):
        nonlocal best_lv, best_pred, best_meta
        if pred < 0:
            return
        if best_pred < 0 or abs(pred - target_cr) < abs(best_pred - target_cr):
            best_lv, best_pred = lv, pred
            best_meta = {"lever": lever, "spread": meta.get("spread"),
                         "intensity": meta.get("intensity"),
                         "cluster_index": meta.get("cluster_index"),
                         "gimmick_count": meta.get("gimmick_count")}

    # ── ① 색 스윕 ──
    ctx = _color_context(req.level_json, arr_seed)
    if ctx is not None:
        spreads = [0.0, 0.25, 0.5, 0.75, 1.0]
        built = [(_color_at_spread(req.level_json, ctx, s), s) for s in spreads]
        cand_levels = [b[0][0] for b in built]
        orig_pred, cand = _sweep_pick(req.level_json, cand_levels, target_cr, mean, std,
                                      rollouts, rl_seed, req.skill_grid, req.max_moves)
        if orig_pred >= 0:
            _consider(req.level_json, orig_pred, "none")
        for (built_item, s), (lv, pred) in zip(built, cand):
            _consider(lv, pred, "color", spread=s, cluster_index=built_item[1])

    close = best_pred >= 0 and abs(best_pred - target_cr) <= req.tolerance

    # ── ② 기믹 스윕 (색으로 부족 시) ──
    if req.try_gimmick and not close:
        color_base = best_lv if best_meta["lever"] == "color" else req.level_json
        intensities = [0.0, 0.25, 0.5, 0.75, 1.0]
        gbuilt = []
        for it in intensities:
            glv, gcnt, _elig = _gimmick_arrangement(color_base, req.level_number, it, arr_seed)
            gbuilt.append((glv, it, gcnt))
        gorig, gcand = _sweep_pick(color_base, [b[0] for b in gbuilt], target_cr, mean, std,
                                   rollouts, rl_seed, req.skill_grid, req.max_moves)
        for (glv, it, gcnt), (lv, pred) in zip(gbuilt, gcand):
            _consider(lv, pred, "gimmick", intensity=it, gimmick_count=gcnt)
        close = best_pred >= 0 and abs(best_pred - target_cr) <= req.tolerance

    if orig_pred < 0:
        orig_pred = 0.0
    # [LINK_SANITIZE] 기믹 스윕(_gimmick_arrangement)이 링크 타겟 위에 기믹을 얹거나 링크를
    # 재배치해 고아/불량 링크(타겟=기믹/goal/부재)를 만들 수 있다. 생성기 정화기를 최종 적용해
    # 인게임 FindLinkTile 크래시(스폰 멈춤)를 막는다. (색 스윕은 링크 무영향이나 무해.)
    best_lv = _gen_for_tune._strip_orphaned_link_tiles(best_lv)
    return AutoTuneResult(
        tuned=(best_lv is not req.level_json),
        best_level_json=best_lv,
        predicted_clear_rate=best_pred if best_pred >= 0 else 0.0,
        original_predicted=orig_pred,
        target_clear_rate=target_cr,
        close=close,
        lever=best_meta["lever"],
        spread=best_meta["spread"],
        intensity=best_meta["intensity"],
        cluster_index=best_meta["cluster_index"],
        gimmick_count=best_meta["gimmick_count"],
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )

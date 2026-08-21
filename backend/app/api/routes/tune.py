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


def _t0_matchable_total(level: Dict[str, Any]) -> int:
    """런타임에 색이 배정되는 매칭 타일 총수 = 필드 t0 + 컨테이너(craft/stack) 내부 개수.

    컨테이너는 보드 위 1칸이지만 내부 타일을 필드로 배출하므로 색 분배 대상에 포함된다
    (÷3 판정도 이 합으로 한다 — 필드 t0 만 세면 컨테이너를 가진 레벨에서 항상 어긋난다).
    """
    nl = int(level.get("layer", 0) or 0)
    tot = 0
    for i in range(nl):
        for td in ((level.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).values():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            t = td[0]
            if t == "t0":
                tot += 1
            elif t.startswith("craft_") or t.startswith("stack_"):
                if len(td) > 2 and isinstance(td[2], list) and td[2]:
                    try:
                        tot += int(td[2][0])
                    except (TypeError, ValueError):
                        pass
    return tot


def _t0_split_is_clean(level: Dict[str, Any], t0_total: int) -> bool:
    """바뀐 useTileCount 로 t0 를 분배했을 때 모든 매칭타입이 ÷3 인지 실측.

    생성기의 판정기를 그대로 재사용한다 — 여기서 자체 규칙을 만들면 생성/튜닝이 이중잣대가 된다.
    """
    try:
        from ...core.generator import LevelGenerator
        gen = LevelGenerator()
        concrete, _ = gen._concrete_positions(level, int(level.get("layer", 0) or 0))
        return gen._t0_distribution_is_clean(level, concrete, t0_total)
    except Exception:  # noqa: BLE001 — 판정 불가면 보수적으로 거부
        logger.exception("[tune/tilecount] t0 분배 검사 실패")
        return False


def _sweep_predicted(levels: List[Dict[str, Any]], req: Any) -> List[float]:
    """레벨들을 RL 스윕해 인구 클리어율 예측치를 돌려준다(순차검증과 동일 경로).

    튜너의 '조절 불가' 조기반환 경로에서도 예측치를 채우기 위해 쓴다. 예전엔 그 경로가
    predicted_clear_rate=0.0 을 그대로 반환해 UI 가 "예측 클리어율 0%" 로 오표시했다
    (실측: Lv11 t0 레벨 — 튜너 0.0 vs 실제 RL 0.5834).
    """
    _rollouts = getattr(req, "rollouts_per_point", None) or DEFAULT_ROLLOUTS_PER_POINT
    _seed = getattr(req, "seed", None)
    _seed = DEFAULT_BASE_SEED if _seed is None else _seed
    mean = getattr(req, "skill_mean", None)
    mean = CASUAL_SKILL_MEAN if mean is None else mean
    std = getattr(req, "skill_std", None)
    std = CASUAL_SKILL_STD if std is None else std
    try:
        results = _parallel_point_sweep(
            list(enumerate(levels)), getattr(req, "skill_grid", None),
            _rollouts, _seed, getattr(req, "max_moves", None),
        )
    except Exception:  # noqa: BLE001 — 예측 실패로 조절 자체를 막지는 않는다
        logger.exception("[tune] 예측 스윕 실패")
        return [0.0] * len(levels)
    # _parallel_point_sweep 은 **key→결과 dict** 를 돌려준다(리스트 아님). 직접 순회하면
    # key(int)를 결과로 오인해 AttributeError 가 난다 → 인덱스로 꺼낸다.
    out: List[float] = []
    for i in range(len(levels)):
        res = results.get(i) or {}
        if res.get("error"):
            out.append(0.0)
        else:
            out.append(round(population_clear_rate(res.get("skill_curve", []), mean=mean, std=std), 4))
    return out


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
    # [FINALIZE] 기믹 재배치가 (a) 링크 타겟에 기믹을 얹거나 링크를 옮겨 고아 링크를 만들고
    # (인게임 FindLinkTile 크래시), (b) chain 을 앵커 없는 칸에 얹어 해제불가 사슬을 만들 수 있다.
    # 반환 전 공통 마무리(chain 클로저 + link sanitize + max_moves/timea) 적용.
    lv = _gen_for_tune._finalize_level(lv)

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
        # [t0 레벨] 필드에 t1~t15 가 없으면 재배치할 색 자체가 없다 — 색은 런타임에
        # useTileCount 로 분배되므로 스프레드 다이얼은 no-op 이다. 다만 evaluate 요청까지
        # 0.0 을 돌려주면 UI 가 "예측 클리어율 0%" 로 오표시한다(실측: Lv11 실제 RL 0.5834).
        # → 레벨을 바꾸지 않은 채 **실제로 측정한** 값을 돌려준다.
        pred = _sweep_predicted([req.level_json], req)[0] if req.evaluate else 0.0
        return ColorTuneResult(
            best_level_json=req.level_json, predicted_clear_rate=pred, original_predicted=pred,
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
    # [±2 제한] 기준 대비 최대 2종까지만 증감한다. 색은 난이도 지배 인자라(실측 Lv710:
    # 12색 0.000 → 7색 0.171 → 6색 0.549) 자유롭게 열어두면 난이도 곡선이 통째로 무너진다.
    # 기준은 level_number 의 정본 그래프값(get_use_tile_count_for_level). 안 주면 현재
    # useTileCount 를 기준으로 삼는데, 그 경우 호출을 반복하면 2씩 계속 이동할 수 있으니
    # 프론트는 **항상 level_number 를 넘길 것**.
    level_number: Optional[int] = None
    tile_type_profile: Optional[str] = None
    # 캘리브레이션처럼 **난이도 전 구간을 일부러 훑어야 하는** 도구만 False 로 끈다.
    # 프로덕션 경로는 절대 끄지 않는다(난이도 곡선이 무너진다).
    enforce_limit: bool = True
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

    from ...core.generator import select_color_balanced_tiles, get_use_tile_count_for_level

    positions, counts = _field_colors(req.level_json)
    total = len(positions)

    # [±2 제한] 기준 대비 최대 2종 증감. 기준 = level_number 의 정본 그래프값(없으면 현재 V).
    # 색은 난이도를 지배해서(Lv710 실측: 12색 0.000 / 9색 0.030 / 7색 0.171 / 6색 0.549)
    # 무제한 허용하면 튜너 한 번에 난이도가 목표에서 몇 배로 벗어난다.
    _cur_v = int(req.level_json.get("useTileCount") or 0)
    if req.level_number is not None:
        try:
            base_v = int(get_use_tile_count_for_level(int(req.level_number), req.tile_type_profile))
        except Exception:  # noqa: BLE001 — 그래프 조회 실패 시 현재 V 기준
            base_v = _cur_v or int(req.tile_count)
    else:
        base_v = _cur_v or int(req.tile_count)
    req_n = int(req.tile_count)
    if req.enforce_limit:
        lo, hi = max(2, base_v - 2), base_v + 2
        clamped = max(lo, min(hi, req_n))
        if clamped != req_n:
            logger.info("[tune/tilecount] ±2 제한: 요청 %s → %s (기준 %s, 허용 %s~%s)",
                        req_n, clamped, base_v, lo, hi)
    else:
        clamped = req_n
        logger.info("[tune/tilecount] ±2 제한 해제(enforce_limit=false): 요청 %s 그대로", req_n)

    # 종류당 최소 3개(÷3) 필요 → 상한 = total//3. 요청값을 [2, min(15, total//3)] 로 clamp.
    max_types = max(1, total // 3)
    n = max(1, min(clamped, 15, max_types))
    seed = req.seed if req.seed is not None else (int(req.level_json.get("randSeed", 0) or 0) * 137 + 11)

    if total < 3 or max_types < 2:
        # [t0 레벨] 필드에 t1~t15 가 하나도 없으면 재타이핑할 대상이 없다. 하지만 t0 레벨은
        # "런타임에 useTileCount 개의 색으로 분배"되는 형태라, 색 종류 수가 **useTileCount 값
        # 하나로만** 정해진다. 예전엔 여기서 원본을 그대로 돌려줘 UI 에서 "타일 종류 적용"이
        # 아무 반응 없었다(실측: Lv11·23 등 고정 레벨 t0 64~72개, 요청 9색 → field_tiles=0).
        # → 타일은 건드리지 않고 useTileCount 만 바꾼다. 위치·기믹·컨테이너 전부 불변.
        t0_total = _t0_matchable_total(req.level_json)
        if t0_total >= 6:
            lv = copy.deepcopy(req.level_json)
            # 종류당 최소 3개 확보 → 상한 t0_total//3. 하한 2(1색은 매칭 게임이 성립 안 함).
            n_t0 = max(2, min(clamped, 15, t0_total // 3))
            prev = int(lv.get("useTileCount") or 0)
            lv["useTileCount"] = n_t0
            # 분배 후 모든 타입이 ÷3 인지 **실제 분배기로** 측정. 깨지면 되돌린다
            # (총합 ÷3 이면 통상 항상 깨끗하지만, unlockTile/imbalance 조합에서 예외가 있다).
            if not _t0_split_is_clean(lv, t0_total):
                logger.warning(
                    "[tune/tilecount] t0 분배 비÷3 → useTileCount %s 유지 (요청 %s)", prev, n_t0)
                lv["useTileCount"] = prev
                n_t0 = prev
            # evaluate 면 원본/조절본을 실제로 스윕한다(조기반환이라고 0.0 을 흘리면 UI 오표시).
            p_orig, p_new = (0.0, 0.0)
            if req.evaluate:
                p_orig, p_new = _sweep_predicted([req.level_json, lv], req)
            return TileCountTuneResult(
                best_level_json=lv, predicted_clear_rate=p_new, original_predicted=p_orig,
                tile_count=n_t0, requested=int(req.tile_count),
                field_tiles=t0_total, color_types=n_t0,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        # 재타이핑 불가(필드 타일 부족) → 원본 그대로
        return TileCountTuneResult(
            best_level_json=req.level_json, predicted_clear_rate=0.0, original_predicted=0.0,
            tile_count=len(counts), requested=int(req.tile_count),
            field_tiles=total, color_types=len(counts),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    # [컨테이너-aware] 컨테이너(craft/stack)는 런타임에 내부 타입을 필드로 배출한다.
    #
    # 예전 방식: 배출 타입 중 '배출량이 ÷3 아닌 것'만 팔레트에 **강제 포함**하고 배출 문자열은
    # 손대지 않았다. 두 가지가 동시에 깨졌다.
    #   ① 색이 안 줄어든다 — 강제 타입이 8개면 2색을 요청해도 8색이 하한 (실측 Lv170).
    #   ② 오히려 고아 색이 늘어난다 — 배출량이 ÷3 인 타입(t1:3, t15:6 …)은 강제 대상이 아니라
    #      팔레트에서 빠지는데 배출 문자열엔 그대로 남는다. 그 색은 **필드에 0장 / 컨테이너에만
    #      존재** → 3장 모으려면 서로 다른 컨테이너를 다 열고 독에 붙들어야 한다.
    #      실측 Lv280: 8색 요청 후 t1·t5·t8·t10·t13·t15 6종이 컨테이너 전용이 되어 클리어율 0.
    #
    # 현재 방식: 배출 문자열도 **팔레트 안으로 다시 쓴다**. 필드+배출을 하나의 풀로 보고 배정하므로
    # 요청한 색 수가 그대로 지켜지고, 팔레트 밖 색이 원천적으로 생기지 않는다.
    # 'key'(unlockTile 키) 슬롯은 색이 아니므로 건드리지 않고 카운트에서도 제외한다.
    nl = int(req.level_json.get("layer", 0) or 0)
    emit_slots: List[Tuple[List[Any], int]] = []   # (td[2] 배열, 슬롯 인덱스)
    for i in range(nl):
        for td in ((req.level_json.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).values():
            if isinstance(td, list) and len(td) > 2 and isinstance(td[2], list) and len(td[2]) > 1 \
                    and isinstance(td[2][1], str) and td[2][1]:
                for k, part in enumerate(str(td[2][1]).split("_")):
                    if part and part[0] == "t" and part[1:].isdigit():
                        emit_slots.append((td[2], k))

    emit_total = len(emit_slots)
    grand = total + emit_total          # 매칭 대상 전체(필드 + 컨테이너 배출)
    # 종류당 최소 3개 → 상한은 필드가 아니라 **전체** 기준
    max_types = max(1, grand // 3)
    n = max(2, min(clamped, 15, max_types))
    types = [t for t in select_color_balanced_tiles(15, seed=seed, max_index=15)][:n]
    if len(types) < n:  # 안전망(선택기가 부족할 일은 없음)
        types = [f"t{i + 1}" for i in range(n)]
    n = len(types)

    # 전체를 3단위 블록으로 균등 분배 → 타입별 카운트가 항상 ÷3
    blocks, rem = divmod(grand, 3)
    counts_out = {t: 0 for t in types}
    for k in range(blocks):
        counts_out[types[k % n]] += 3
    if rem:
        # 원본이 ÷3 정합이면 여기 안 온다. 와도 나머지는 첫 타입에 얹고 아래 게이트가 마무리.
        counts_out[types[0]] += rem
        logger.warning("[tune/tilecount] 총 매칭 %s 가 비÷3 — 원본 정합성 확인 필요", grand)

    # 라운드로빈 시퀀스 → 앞쪽을 배출에, 나머지를 필드에. 배출도 팔레트 안에서 섞이므로
    # '컨테이너 하나가 여러 색을 뱉는' 기존 디자인은 유지된다(팔레트 밖으로 새지 않을 뿐).
    q = dict(counts_out)
    seq: List[str] = []
    while len(seq) < grand:
        placed = False
        for t in types:
            if q.get(t, 0) > 0:
                seq.append(t); q[t] -= 1; placed = True
                if len(seq) >= grand:
                    break
        if not placed:
            break
    while len(seq) < grand:
        seq.append(types[0])

    lv = copy.deepcopy(req.level_json)
    # 배출 문자열 재작성 — deepcopy 본에서 슬롯을 다시 찾아 쓴다
    emit_seq = seq[:emit_total]
    ei = 0
    for i in range(nl):
        for td in ((lv.get(f"layer_{i}", {}) or {}).get("tiles", {}) or {}).values():
            if isinstance(td, list) and len(td) > 2 and isinstance(td[2], list) and len(td[2]) > 1 \
                    and isinstance(td[2][1], str) and td[2][1]:
                parts = str(td[2][1]).split("_")
                for k, part in enumerate(parts):
                    if part and part[0] == "t" and part[1:].isdigit():
                        parts[k] = emit_seq[ei]; ei += 1
                td[2][1] = "_".join(parts)
    lv = _apply_colors(lv, positions, seq[emit_total:])
    # NOTE: _finalize_divisibility_guarantee 는 호출하지 않는다. 그 게이트는 '필드 per-type ÷3'를
    # 강제(consolidate relabel)하는데, 컨테이너 배출이 있으면 필드는 ÷3 아닌 나머지를 가져야
    # (필드+컨테이너) ÷3 이 된다. finalize 를 태우면 그 나머지를 상쇄해 orphan 을 되살린다.
    # 위 배정은 이미 타입별 (필드+컨테이너) ÷3 + 총합 보존 → 클리어가능 자체보장.
    _, final_counts = _field_colors(lv)
    lv["useTileCount"] = max(n, len(final_counts))

    if not req.evaluate:
        return TileCountTuneResult(
            best_level_json=lv, predicted_clear_rate=0.0, original_predicted=0.0,
            tile_count=n, requested=int(req.tile_count),
            field_tiles=grand, color_types=n,
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
        field_tiles=grand, color_types=n,
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
    # [타일 종류 레버] 색으로 부족할 때 **정본 그래프값 ±2** 안에서 종류 수를 스윕한다.
    #
    # 보스 레벨용으로 넣었다. 보스는 모양이 템플릿으로 고정이라 재생성해도 실루엣이 그대로고,
    # 그래서 '재생성' 이 난이도 레버로 거의 작동하지 않는다. 실제로 쓸 수 있는 건 색·종류뿐인데
    # 종류는 그동안 그래프값에 잠겨 있어 봉인된 상태였다.
    #
    # 기믹은 반대로 자동 스윕을 **끄는 쪽**이 맞다 — 자동 재배치가 수동으로 맞춰둔 기믹 구성을
    # 덮어쓴다. 기믹은 난이도 다이얼에서 사람이 만질 때만 바뀌게 한다.
    try_tilecount: bool = False
    tile_type_profile: Optional[str] = None   # ±2 기준 곡선(미지정=baseline)


class AutoTuneResult(BaseModel):
    tuned: bool
    best_level_json: Dict[str, Any]
    predicted_clear_rate: float
    original_predicted: float
    target_clear_rate: float
    close: bool                        # tolerance 안 도달 여부
    lever: str                         # none/color/tilecount/gimmick
    tile_count: Optional[int] = None   # lever=='tilecount' 일 때 채택된 종류 수
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
                                 "cluster_index": None, "gimmick_count": None,
                                 "tile_count": None}
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
                         "gimmick_count": meta.get("gimmick_count"),
                         "tile_count": meta.get("tile_count")}

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

    # ── ②' 타일 종류 스윕 (색으로 부족 시) ──
    # 색이 먼저다. 색은 배치만 바꾸는 '미세' 레버라 부작용이 거의 없고,
    # 종류 수는 난이도를 지배하는 '거친' 레버다(실측 Lv710: 12색 0.000 / 9색 0.030 /
    # 7색 0.171 / 6색 0.549). 그래서 색으로 못 맞출 때만 종류를 건드린다.
    if req.try_tilecount and not close:
        from ...core.generator import get_use_tile_count_for_level
        tc_base = best_lv if best_meta["lever"] == "color" else req.level_json
        try:
            base_v = int(get_use_tile_count_for_level(int(req.level_number), req.tile_type_profile))
        except Exception:  # noqa: BLE001
            base_v = int(tc_base.get("useTileCount") or 0)
        cur_v = int(tc_base.get("useTileCount") or base_v)
        # 정본 그래프값 ±2. 현재값은 이미 측정됐으므로 후보에서 뺀다.
        cands_n = [v for v in range(max(2, base_v - 2), base_v + 3) if v != cur_v]
        tbuilt = []
        for v in cands_n:
            try:
                r_tc = tune_tilecount(TileCountTuneRequest(
                    level_json=tc_base, tile_count=v, evaluate=False,
                    level_number=req.level_number, tile_type_profile=req.tile_type_profile,
                    enforce_limit=True, seed=arr_seed,
                ))
                # 클램프·÷3 상한 때문에 요청과 다른 값이 나올 수 있다 → 실제 적용값을 쓴다.
                tbuilt.append((r_tc.best_level_json, int(r_tc.tile_count)))
            except Exception as ex:  # noqa: BLE001 — 후보 하나 실패가 전체를 막지 않는다
                logger.warning("[tune/auto] tilecount %s 후보 생성 실패: %s", v, ex)
        # 같은 종류 수로 수렴한 중복 후보 제거(측정 낭비)
        seen_n = set()
        uniq = []
        for lv_c, n_c in tbuilt:
            if n_c in seen_n or n_c == cur_v:
                continue
            seen_n.add(n_c)
            uniq.append((lv_c, n_c))
        if uniq:
            _t_orig, tcand = _sweep_pick(tc_base, [u[0] for u in uniq], target_cr, mean, std,
                                         rollouts, rl_seed, req.skill_grid, req.max_moves)
            for (lv_c, n_c), (lv_r, pred) in zip(uniq, tcand):
                _consider(lv_r, pred, "tilecount", tile_count=n_c,
                          spread=best_meta.get("spread"))
            close = best_pred >= 0 and abs(best_pred - target_cr) <= req.tolerance

    # ── ③ 기믹 스윕 (색·종류로 부족 시) ──
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
    # [FINALIZE] 기믹 스윕(_gimmick_arrangement)이 링크 타겟 위에 기믹을 얹거나 링크를
    # 재배치해 고아 링크(인게임 FindLinkTile 크래시)를, 또는 앵커 없는 칸에 chain 을 얹어
    # 해제불가 사슬을 만들 수 있다. 공통 마무리를 최종 적용. (색 스윕은 무영향이나 무해.)
    best_lv = _gen_for_tune._finalize_level(best_lv)
    return AutoTuneResult(
        tuned=(best_lv is not req.level_json),
        best_level_json=best_lv,
        predicted_clear_rate=best_pred if best_pred >= 0 else 0.0,
        original_predicted=orig_pred,
        target_clear_rate=target_cr,
        close=close,
        lever=best_meta["lever"],
        tile_count=best_meta.get("tile_count"),
        spread=best_meta["spread"],
        intensity=best_meta["intensity"],
        cluster_index=best_meta["cluster_index"],
        gimmick_count=best_meta["gimmick_count"],
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )

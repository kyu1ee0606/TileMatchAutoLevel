"""Pure prediction path — shared by the parallel display now and by generation / validation / selection later.

    predict_level(model, game_map, conditions, placement_level, measurement) -> ClearRatePrediction

Inputs are the *final game conditions* (what the game will run: build-shard / upload-format map + GAME_FIELDS row
values), the placement level, and a bot measurement tagged with the condition hash it was measured under. No I/O,
no cache, no UI/route concerns. Callers that start from an editor level_json use `service.predict_editor_level`.

Naming keeps the targets apart:
  expected_ft_any / range80_ft_any  primary target — real-user first-try clear rate incl. help, ended runs (ft_any_v1)
  expected_unaided_lb               aux — real-user unaided first-try clear share (AF lower bound), predicted
  expected_help_rate                aux — real-user first-try help usage rate, predicted (output only, never an input)
  bot_unaided_win_rate              bot measurement (bot plays without help) — an input, not a clear rate
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import guard
from .features import condition_hash, level_features, map_features, normalize_conditions, present_gimmicks
from .model import ClearRateModel

STATUS_OK, STATUS_INSUFFICIENT, STATUS_NEED_MEASUREMENT = "ok", "insufficient_evidence", "measurement_required"


@dataclass(frozen=True)
class BotMeasurement:
    """Bot measurement + protocol meta. `condition_hash` = features.condition_hash of the map/conditions measured."""
    bot_version: str
    protocol: str
    condition_hash: str
    rows: Tuple[Dict[str, Any], ...]
    seed_set: str = ""
    source: str = "request"   # request | cache

    @classmethod
    def from_dict(cls, d: Dict[str, Any], source: str = "request") -> "BotMeasurement":
        return cls(bot_version=d["bot_version"], protocol=d["protocol"], condition_hash=d["condition_hash"],
                   rows=tuple(d.get("rows") or ()), seed_set=d.get("seed_set") or "", source=source)

    def meta(self) -> Dict[str, str]:
        return {"source": self.source, "bot_version": self.bot_version, "protocol": self.protocol,
                "seed_set": self.seed_set, "condition_hash": self.condition_hash}


@dataclass
class ClearRatePrediction:
    model_version: str
    target_metric: str
    bot_version: str
    bot_protocol: str
    placement_level: Optional[int]
    condition_hash: str
    status: str
    in_support: bool                                   # False → no number; reasons in insufficient_reasons
    insufficient_reasons: List[str] = field(default_factory=list)
    evidence_flags: List[Dict[str, str]] = field(default_factory=list)
    expected_ft_any: Optional[float] = None
    range80_ft_any: Optional[Tuple[float, float]] = None
    expected_unaided_lb: Optional[float] = None
    expected_help_rate: Optional[float] = None
    confidence: Optional[str] = None
    measurement: Optional[Dict[str, str]] = None
    bot_unaided_win_rate: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["range80_ft_any"] = list(self.range80_ft_any) if self.range80_ft_any else None
        return d


def segment_of(L: int) -> Optional[str]:
    for lo, hi in ((32, 100), (101, 300), (301, 500)):
        if lo <= L <= hi:
            return f"{lo}-{hi}"
    return None


def _exposure(position: Dict[str, Any], L: int) -> Dict[str, int]:
    keys = sorted(int(k) for k in position["exposure"])
    return position["exposure"][str(min(max(L, keys[0]), keys[-1]))]


def predict_level(model: ClearRateModel, game_map: Dict[str, Any], conditions: Dict[str, Any],
                  placement_level: Optional[int], measurement: Optional[BotMeasurement], *,
                  random_layout: bool) -> ClearRatePrediction:
    """random_layout: whether the map has empty slots the game fills at random (cs_shuffle.get_empty_tile_list);
    passed in so this function stays free of game-engine imports."""
    man, sup, pos = model.manifest, model.model["support"], model.model["position"]
    cond = normalize_conditions(conditions)
    h = condition_hash(game_map, cond)
    out = ClearRatePrediction(model_version=model.version, target_metric=man["target_metric"],
                              bot_version=man["bot_version"], bot_protocol=man["bot_protocol"],
                              placement_level=placement_level, condition_hash=h, status=STATUS_OK, in_support=False,
                              measurement=measurement.meta() if measurement else None)
    flags = guard.input_flags(sup, placement_level=placement_level, gimmicks=present_gimmicks(map_features(game_map)))
    rows = list(measurement.rows) if measurement else []
    if measurement:
        flags += guard.bot_flags(man, measurement.bot_version, measurement.protocol, measurement.condition_hash, h, rows)
        out.bot_unaided_win_rate = {f"theta{int(round(float(r['theta']) * 100)):03d}": round(r["wins"] / r["games"], 4)
                                    for r in rows if r.get("games")}
    else:
        flags.append(guard.flag("MEASUREMENT_MISSING", "hard", "이 게임 조건의 봇 측정이 없음"))

    def finish(status: str) -> ClearRatePrediction:
        out.status, out.evidence_flags = status, flags
        out.insufficient_reasons = [f["code"] for f in flags if f["code"] in guard.SUPPRESS]
        out.in_support = not out.insufficient_reasons
        return out

    hard_input = [f for f in flags if f["code"] in guard.SUPPRESS and f["code"] != "MEASUREMENT_MISSING"]
    if placement_level is None or hard_input:
        return finish(STATUS_INSUFFICIENT)
    if measurement is None:
        return finish(STATUS_NEED_MEASUREMENT)

    L = int(placement_level)
    acc = cond["autoCollectCount"]
    feats = level_features(
        game_map, placement_level=L, use_tile_count=cond["useTileCount"], unlock_tile=cond["unlockTile"],
        is_boss=1 <= acc <= 3, random_layout=random_layout, map2nd=False, exposure=_exposure(pos, L),
        gimmick_first=L in set(pos["gimmick_first_levels"]), bot_rows=rows)
    flags += guard.feature_flags(sup, feats)
    if guard.suppressed(flags):
        return finish(STATUS_INSUFFICIENT)

    expected = model.predict("ft_any", feats)
    lo, hi = model.range80("ft_any", feats)
    flags += guard.value_flags(expected)
    out.expected_ft_any, out.range80_ft_any = round(expected, 4), (round(lo, 4), round(hi, 4))
    out.expected_unaided_lb = round(model.predict("unaided_lb", feats), 4)
    out.expected_help_rate = round(model.predict("help_rate", feats), 4)
    out.confidence = guard.confidence(flags)
    return finish(STATUS_OK)


__all__ = ["BotMeasurement", "ClearRatePrediction", "predict_level", "STATUS_OK", "STATUS_INSUFFICIENT",
           "STATUS_NEED_MEASUREMENT", "segment_of"]

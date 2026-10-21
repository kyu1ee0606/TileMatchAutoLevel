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
The bot win rate is never substituted for the user clear rate: when the model cannot predict, expected_ft_any
stays None (a future "bot virtual clear-rate" mode must use its own fields, not these).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import guard
from .conditions import cond_hash, normalize_conditions
from .features import level_features, map_features, present_gimmicks
from .model import ClearRateModel

STATUS_OK, STATUS_INSUFFICIENT, STATUS_NEED_MEASUREMENT = "ok", "insufficient_evidence", "measurement_required"


@dataclass(frozen=True)
class BotMeasurement:
    """Bot measurement + provenance. `cond_hash` = conditions.cond_hash of the final game conditions measured;
    `seed_band` = seed range label (training "seed11M"; doc 35 S = search, C = confirmation). A confirmation band
    only re-checks bot-measurement stability — it is not an independent real-user validation."""
    bot_version: str
    protocol: str
    cond_hash: str
    rows: Tuple[Dict[str, Any], ...]
    seed_band: str = ""
    source: str = "request"   # request | cache
    skill_config: str = ""    # bot skill setting label (θ grid itself is in rows[].theta); "" = protocol default
    aids_simulated: Optional[Dict[str, bool]] = None   # {"booster": .., "revive": ..}; None = protocol default (off)

    @classmethod
    def from_dict(cls, d: Dict[str, Any], source: str = "request") -> "BotMeasurement":
        return cls(bot_version=d.get("bot_version") or "", protocol=d.get("protocol") or "",
                   cond_hash=d.get("cond_hash") or "", rows=tuple(d.get("rows") or ()),
                   seed_band=d.get("seed_band") or "", source=source, skill_config=d.get("skill_config") or "",
                   aids_simulated=d.get("aids_simulated"))

    def meta(self) -> Dict[str, Any]:
        return {"source": self.source, "bot_version": self.bot_version, "protocol": self.protocol,
                "seed_band": self.seed_band, "cond_hash": self.cond_hash, "skill_config": self.skill_config,
                "aids_simulated": self.aids_simulated}


@dataclass
class ClearRatePrediction:
    model_version: str
    target_metric: str
    bot_version: str
    bot_protocol: str
    placement_level: Optional[int]
    cond_hash: str
    status: str
    in_support: bool                                   # False → no number; reasons in insufficient_reasons
    insufficient_reasons: List[str] = field(default_factory=list)
    evidence_flags: List[Dict[str, str]] = field(default_factory=list)
    expected_ft_any: Optional[float] = None
    range80_ft_any: Optional[Tuple[float, float]] = None
    expected_unaided_lb: Optional[float] = None
    expected_help_rate: Optional[float] = None
    confidence: Optional[str] = None
    reliability: Optional[Dict[str, Any]] = None   # training OOF error for this predicted zone / gimmick combo / segment
    measurement: Optional[Dict[str, str]] = None
    bot_unaided_win_rate: Dict[str, float] = field(default_factory=dict)
    conditions: Dict[str, Any] = field(default_factory=dict)          # final game conditions the prediction is for
    upload_assumption: Optional[Dict[str, Any]] = None                # upload-panel options assumed (editor path)

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
    h = cond_hash(game_map, cond)
    out = ClearRatePrediction(model_version=model.version, target_metric=man["target_metric"],
                              bot_version=man["bot_version"], bot_protocol=man["bot_protocol"],
                              placement_level=placement_level, cond_hash=h, status=STATUS_OK, in_support=False,
                              measurement=measurement.meta() if measurement else None, conditions=cond)
    flags = guard.input_flags(sup, placement_level=placement_level, gimmicks=present_gimmicks(map_features(game_map)),
                             conditions=cond)
    rows = list(measurement.rows) if measurement else []
    if measurement:
        flags += guard.bot_flags(man, measurement, h)
        if not guard.quarantined(man, measurement):   # P5: no bot numbers from a mismatched-setting measurement
            out.bot_unaided_win_rate = {f"theta{int(round(float(r['theta']) * 100)):03d}":
                                        round(r["wins"] / r["games"], 4) for r in rows if r.get("games")}
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
    combo = "+".join(g for g in present_gimmicks(map_features(game_map)) if g != "craft") or "none"
    out.reliability = guard.reliability(sup, expected, combo, segment_of(L), (lo, hi))
    flags += guard.reliability_flags(out.reliability)
    out.expected_ft_any, out.range80_ft_any = round(expected, 4), (round(lo, 4), round(hi, 4))
    out.expected_unaided_lb = round(model.predict("unaided_lb", feats), 4)
    out.expected_help_rate = round(model.predict("help_rate", feats), 4)
    out.confidence = guard.confidence(flags)
    return finish(STATUS_OK)


__all__ = ["BotMeasurement", "ClearRatePrediction", "predict_level", "STATUS_OK", "STATUS_INSUFFICIENT",
           "STATUS_NEED_MEASUREMENT", "segment_of"]

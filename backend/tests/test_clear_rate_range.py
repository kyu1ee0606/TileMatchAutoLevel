"""P(in target band) and 80% range — boundary, monotonicity, finiteness, reproducibility (doc 36 §8–10).

These pin the behaviour of the served functions; they do not claim P is a calibrated probability (doc 36 §8-3).
"""
import json
import math

import pytest

from app.core.clear_rate import load_model
from app.core.clear_rate.features import FEATS
from app.core.clear_rate.model import MODELS_DIR, TARGET_LOGIT_CLIP, range_to_prob
from app.core.clear_rate.select import p_in_band, target_band

ACTIVE = "cr-ftany-v24r-20261016"
CANDS = ("cr-ftany-v24r-rng-20261016-r1", "cr-ftany-v24r-rng-20261016-r2")


def _lg(p):
    return math.log(p / (1 - p))


def _ex(x):
    return 1 / (1 + math.exp(-x))


EXTREME_PREDS = (1e-9, 1e-4, 0.01, 0.5, 0.85, 0.931, 0.99, 0.9999, 1 - 1e-9)
EXTREME_RANGES = ((0.0, 1.0), (0.0, 0.0), (1.0, 1.0), (0.2, 0.3), (0.9, 1.0), (0.0, 0.95), (0.912, 1.0), (0.5, 0.5))


@pytest.mark.parametrize("pred", EXTREME_PREDS)
@pytest.mark.parametrize("rng", EXTREME_RANGES)
@pytest.mark.parametrize("target", (0.5, 0.85, 0.90, 0.95))
def test_p_in_band_is_finite_and_in_unit_interval(pred, rng, target):
    p = p_in_band(pred, rng, target_band(target))
    assert math.isfinite(p) and 0.0 <= p <= 1.0


def test_p_in_band_boundaries():
    # a band covering everything holds all the mass; an empty band none
    assert p_in_band(0.9, (0.85, 0.95), (0.0, 1.0)) == pytest.approx(1.0)
    assert p_in_band(0.9, (0.85, 0.95), (0.93, 0.93)) == pytest.approx(0.0)
    # the 80% range itself holds 0.8 of the two-piece normal whenever both ends are interior
    for pred, lo, hi in ((0.9, 0.85, 0.95), (0.9, 0.80, 0.93), (0.6, 0.3, 0.9)):
        assert p_in_band(pred, (lo, hi), (lo, hi)) == pytest.approx(0.8, abs=1e-9)
    # censored upper end (1.0) borrows the lower spread → symmetric in logit around the prediction
    mu, s = _lg(0.931), (_lg(0.931) - _lg(0.912)) / 1.2815515655446004
    sym = p_in_band(0.931, (0.912, _ex(mu + (mu - _lg(0.912)))), target_band(0.9))
    assert p_in_band(0.931, (0.912, 1.0), target_band(0.9)) == pytest.approx(sym, abs=1e-9)
    assert s > 0


def test_p_in_band_monotone_in_distance_from_band():
    band = target_band(0.85)
    centre = _lg(0.85)
    s = 0.3  # fixed logit spread, symmetric 80% range around the prediction
    vals = []
    for d in (0.0, 0.2, 0.4, 0.8, 1.2, 2.0):
        row = []
        for sign in (-1, 1):
            mu = centre + sign * d
            row.append(p_in_band(_ex(mu), (_ex(mu - 1.2815515655446004 * s), _ex(mu + 1.2815515655446004 * s)), band))
        vals.append(row)
    for side in (0, 1):
        seq = [v[side] for v in vals]
        assert all(a >= b - 1e-12 for a, b in zip(seq, seq[1:])), seq


def test_p_in_band_monotone_in_band_width():
    rng = (0.80, 0.97)
    ps = [p_in_band(0.92, rng, target_band(0.9, hw)) for hw in (0.1, 0.3, 0.5, 0.7, 1.0, 2.0)]
    assert all(a <= b + 1e-12 for a, b in zip(ps, ps[1:])), ps


def test_p_in_band_reproducible():
    args = (0.931, (0.9119, 1.0), target_band(0.9))
    assert p_in_band(*args) == p_in_band(*args)


def test_range_to_prob_censoring():
    lo, hi = TARGET_LOGIT_CLIP
    assert range_to_prob(lo, hi) == (0.0, 1.0)
    assert range_to_prob(lo + 0.5, hi - 0.5) == pytest.approx((_ex(lo + 0.5), _ex(hi - 0.5)))
    assert range_to_prob(hi + 1, hi + 2)[1] == 1.0


def _feature_rows(n=40):
    m = json.loads((MODELS_DIR / ACTIVE / "model.json").read_text(encoding="utf-8"))
    return [dict(zip(FEATS, c["x"])) for c in m["check"]][:n]


def test_active_model_range_unchanged_by_range_kind_branch():
    """The active artifact has no range_kind → the original CQR path (q_lo/q_hi ± cqr_w)."""
    mdl = load_model(ACTIVE)
    h = mdl.model["heads"]["ft_any"]
    assert "range_kind" not in h
    from app.core.clear_rate.model import gbm_predict
    for f in _feature_rows():
        a = gbm_predict(h["q_lo"], [f[c] for c in h["q_lo"]["feats"]])
        b = gbm_predict(h["q_hi"], [f[c] for c in h["q_hi"]["feats"]])
        assert mdl.range80("ft_any", f) == range_to_prob(min(a, b) - h["cqr_w"], max(a, b) + h["cqr_w"])


@pytest.mark.parametrize("version", CANDS)
def test_range_candidates_keep_active_point_and_give_ordered_ranges(version):
    if not (MODELS_DIR / version / "model.json").exists():
        pytest.skip("candidate not exported")
    act, cand = load_model(ACTIVE), load_model(version)
    assert cand.model["heads"]["ft_any"]["point"] == act.model["heads"]["ft_any"]["point"]
    assert cand.model["heads"]["unaided_lb"] == act.model["heads"]["unaided_lb"]
    assert cand.bot_cache == act.bot_cache
    for f in _feature_rows():
        lo, hi = cand.range80("ft_any", f)
        assert 0.0 <= lo <= hi <= 1.0 and math.isfinite(lo) and math.isfinite(hi)
        assert cand.predict("ft_any", f) == act.predict("ft_any", f)
        if cand.model["heads"]["ft_any"]["range_kind"] == "resid_conformal":
            assert lo <= cand.predict("ft_any", f) <= hi
        assert cand.range80("ft_any", f) == cand.range80("ft_any", f)

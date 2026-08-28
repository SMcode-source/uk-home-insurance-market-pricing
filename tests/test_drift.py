"""Tests for forward price drift.

The failure this module fixes is silent: a tree predicts the last week it saw
for every week after it, so the error is a clean level offset that grows with
horizon and never shows up as a crash or a warning. These tests pin the
behaviour at the boundary, because that is the only place it differs from the
unwrapped model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mktpricing.models import approaches as _approaches  # noqa: F401  (registers)
from mktpricing.models.base import get
from mktpricing.models.drift import BrandTrend


def _series(brand, weeks, levels, n=100):
    """Expand a per-week level series into row-level residuals."""
    rows = []
    for w, lv in zip(weeks, levels):
        rows += [{"brand": brand, "week": w, "resid": lv}] * n
    return pd.DataFrame(rows)


# -- BrandTrend -------------------------------------------------------------


def test_a_linear_trend_is_recovered_and_extended():
    weeks = list(range(10))
    t = BrandTrend().fit(
        **_series("A", weeks, [0.01 * w for w in weeks]).to_dict("series")
    )
    assert t.own_slope["A"] == pytest.approx(0.01, abs=1e-6)
    # week 12 is three beyond the last observed week (9)
    assert t.level_at("A", 12) == pytest.approx(0.09 + 3 * 0.01, abs=1e-3)


def test_a_flat_series_stays_flat():
    """No evidence of drift must not become evidence of drift."""
    weeks = list(range(8))
    t = BrandTrend().fit(**_series("A", weeks, [0.05] * 8).to_dict("series"))
    assert t.slope["A"] == pytest.approx(0.0, abs=1e-9)
    assert t.level_at("A", 20) == pytest.approx(0.05, abs=1e-6)


def test_observed_weeks_return_their_observed_level():
    weeks = [0, 1, 2, 3]
    levels = [0.0, 0.3, -0.1, 0.2]
    t = BrandTrend().fit(**_series("A", weeks, levels).to_dict("series"))
    for w, lv in zip(weeks, levels):
        assert t.level_at("A", w) == pytest.approx(lv)


def test_extrapolation_is_capped_at_the_horizon():
    """A tactical move is not a claim about next year."""
    weeks = list(range(10))
    t = BrandTrend(max_horizon=4).fit(
        **_series("A", weeks, [0.01 * w for w in weeks]).to_dict("series")
    )
    capped = t.level_at("A", 9 + 4)
    assert t.level_at("A", 9 + 40) == pytest.approx(capped)
    assert t.level_at("A", 9 + 400) == pytest.approx(capped)


def test_a_thin_brand_is_shrunk_toward_the_market():
    """Two weeks of data is not enough to be trusted on its own slope."""
    weeks = list(range(12))
    thick = _series("Thick", weeks, [0.02 * w for w in weeks], n=400)
    thin = _series("Thin", [0, 1], [0.0, -0.5], n=5)
    t = BrandTrend(credibility_weeks=4.0).fit(
        **pd.concat([thick, thin], ignore_index=True).to_dict("series")
    )
    assert t.credibility["Thin"] < t.credibility["Thick"]
    # its own slope is steeply negative; the slope actually used is pulled up
    assert t.own_slope["Thin"] < t.slope["Thin"]


def test_an_unknown_brand_falls_back_to_the_market_level():
    weeks = list(range(6))
    t = BrandTrend().fit(**_series("A", weeks, [0.01 * w for w in weeks]).to_dict("series"))
    assert t.level_at("Never Seen", 3) == pytest.approx(t.level_at("__market__", 3))


def test_report_annualises_the_weekly_slope():
    weeks = list(range(10))
    t = BrandTrend().fit(
        **_series("A", weeks, [0.01 * w for w in weeks]).to_dict("series")
    )
    row = t.report().set_index("brand").loc["A"]
    assert row.used_slope_pct_wk == pytest.approx((np.exp(0.01) - 1) * 100, abs=0.01)
    assert row.annualised_pct > 0


# -- TrendAdjusted ----------------------------------------------------------


def _drifting_market(n_weeks=12, n_risks=60, weekly=0.02, seed=0):
    """A market where one brand reprices every week and the other does not."""
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(n_weeks):
        for r in range(n_risks):
            si = rng.uniform(-1, 1)
            for brand, drift in (("Mover", weekly * w), ("Static", 0.0)):
                base = 5.5 + 0.4 * si + (0.1 if brand == "Mover" else 0.0)
                rows.append(
                    {
                        "brand": brand,
                        "week": float(w),
                        "log_sum_insured": si,
                        "y": base + drift + rng.normal(0, 0.01),
                    }
                )
    return pd.DataFrame(rows)


def _fit_both(df, holdout=3):
    cut = df.week.max() - holdout + 1
    tr, te = df[df.week < cut], df[df.week >= cut]
    cols = ["log_sum_insured", "week"]
    out = {}
    for name in ("gbm_per_brand", "gbm_per_brand_trend"):
        m = get(name)(min_rows=50).fit(
            tr[cols], tr.y.to_numpy(), groups=tr.brand.to_numpy()
        )
        pred = m.predict(te[cols], groups=te.brand.to_numpy())
        out[name] = np.asarray(pred, dtype=float)
    return te, out


def test_the_unwrapped_model_flatlines_and_the_wrapped_one_does_not():
    """The whole point, stated as one comparison."""
    pytest.importorskip("lightgbm")
    df = _drifting_market()
    te, preds = _fit_both(df)
    mover = (te.brand == "Mover").to_numpy()

    plain_bias = float(np.median(preds["gbm_per_brand"][mover] - te.y.to_numpy()[mover]))
    trend_bias = float(
        np.median(preds["gbm_per_brand_trend"][mover] - te.y.to_numpy()[mover])
    )
    # the unwrapped model is systematically low on the brand that repriced
    assert plain_bias < -0.02
    assert abs(trend_bias) < abs(plain_bias) / 2


def test_the_static_brand_is_not_disturbed():
    """Modelling drift must not invent it for a brand that held price."""
    pytest.importorskip("lightgbm")
    df = _drifting_market()
    te, preds = _fit_both(df)
    static = (te.brand == "Static").to_numpy()
    bias = float(
        np.median(preds["gbm_per_brand_trend"][static] - te.y.to_numpy()[static])
    )
    assert abs(bias) < 0.02


def test_panel_rotation_is_not_mistaken_for_a_price_cut():
    """The level comes from residuals precisely so that a change in *which*
    risks appear does not read as a change in price."""
    pytest.importorskip("lightgbm")
    rng = np.random.default_rng(3)
    rows = []
    for w in range(10):
        for r in range(80):
            # later weeks systematically contain cheaper properties
            si = rng.uniform(-1, 1) - 0.15 * w
            rows.append(
                {
                    "brand": "A",
                    "week": float(w),
                    "log_sum_insured": si,
                    "y": 5.5 + 0.4 * si + rng.normal(0, 0.01),
                }
            )
    df = pd.DataFrame(rows)
    cols = ["log_sum_insured", "week"]
    m = get("gbm_per_brand_trend")(min_rows=50).fit(
        df[cols], df.y.to_numpy(), groups=df.brand.to_numpy()
    )
    # mix moved hard; price did not, so the fitted drift must be ~zero
    assert abs(m.trend.slope["A"]) < 0.01


def test_a_matrix_without_week_is_refused():
    """Silently dropping the time term would be a worse bug than the one this
    module fixes, because nothing downstream would look wrong."""
    pytest.importorskip("lightgbm")
    X = pd.DataFrame({"log_sum_insured": [0.1, 0.2, 0.3]})
    with pytest.raises(KeyError, match="week"):
        get("gbm_per_brand_trend")().fit(
            X, np.array([1.0, 2.0, 3.0]), groups=np.array(["A", "A", "A"])
        )


def test_fallback_brands_are_still_reported_through_the_wrapper():
    """The harness reads this off the model; wrapping must not hide it."""
    pytest.importorskip("lightgbm")
    df = _drifting_market(n_risks=10)
    cols = ["log_sum_insured", "week"]
    m = get("gbm_per_brand_trend")(min_rows=10_000).fit(
        df[cols], df.y.to_numpy(), groups=df.brand.to_numpy()
    )
    assert set(m.fallback_brands) == {"Mover", "Static"}


def test_wrapping_requires_brand_groups():
    pytest.importorskip("lightgbm")
    df = _drifting_market(n_risks=10)
    with pytest.raises(ValueError, match="groups"):
        get("gbm_per_brand_trend")().fit(
            df[["log_sum_insured", "week"]], df.y.to_numpy()
        )


def test_in_window_predictions_are_identical_to_the_unwrapped_model():
    """The central guarantee: this wrapper corrects the forward horizon and
    nothing else.

    An earlier version re-expressed every prediction as shape-plus-level, which
    is a strictly additive claim and false wherever a minimum premium binds -- a
    floored quote does not move when the brand's level moves. It cost 2 points
    of MdAPE at a one-week horizon, where there is almost no drift to correct.
    Identity in-window makes that class of regression impossible.
    """
    pytest.importorskip("lightgbm")
    df = _drifting_market()
    cols = ["log_sum_insured", "week"]
    plain = get("gbm_per_brand")(min_rows=50).fit(
        df[cols], df.y.to_numpy(), groups=df.brand.to_numpy()
    )
    wrapped = get("gbm_per_brand_trend")(min_rows=50).fit(
        df[cols], df.y.to_numpy(), groups=df.brand.to_numpy()
    )
    a = plain.predict(df[cols], groups=df.brand.to_numpy())
    b = wrapped.predict(df[cols], groups=df.brand.to_numpy())
    np.testing.assert_allclose(a, b, rtol=0, atol=0)


def test_the_correction_grows_with_horizon_and_stops_at_the_cap():
    pytest.importorskip("lightgbm")
    df = _drifting_market()
    cols = ["log_sum_insured", "week"]
    m = get("gbm_per_brand_trend")(min_rows=50, trend_weight=1.0, max_horizon=4).fit(
        df[cols], df.y.to_numpy(), groups=df.brand.to_numpy()
    )
    row = df[df.brand == "Mover"].iloc[[0]][cols]
    last = m.max_train_week
    preds = []
    for h in (0, 1, 2, 4, 8, 20):
        r = row.copy()
        r["week"] = last + h
        preds.append(float(m.predict(r, groups=np.array(["Mover"]))[0]))
    assert preds[0] < preds[1] < preds[2] < preds[3]      # grows with horizon
    assert preds[3] == pytest.approx(preds[4])            # capped at 4 weeks
    assert preds[4] == pytest.approx(preds[5])


# -- recalibration ----------------------------------------------------------


def _jumped(df, brand="Mover", week=12, pct=0.10, n_risks=60, seed=9):
    """One extra week in which `brand` has repriced by `pct` (log scale)."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_risks):
        si = rng.uniform(-1, 1)
        for b in ("Mover", "Static"):
            base = 5.5 + 0.4 * si + (0.1 if b == "Mover" else 0.0)
            rows.append({"brand": b, "week": float(week), "log_sum_insured": si,
                         "y": base + (pct if b == brand else 0.0)
                              + rng.normal(0, 0.01)})
    return pd.DataFrame(rows)


def _fitted(anchor_rows=0.0):
    """Fitted wrapper on a flat market, so any level move is the one we made.

    `anchor_rows=0` switches off credibility shrinkage, which is what the tests
    of the update mechanism want -- they are asserting that an observed move of
    x is carried forward as x, and shrinkage would blur that with the market.
    Shrinkage has its own test below.
    """
    df = _drifting_market(weekly=0.0)          # flat market, so drift is ~0
    cols = ["log_sum_insured", "week"]
    m = get("gbm_per_brand_trend")(min_rows=50, anchor_rows=anchor_rows).fit(
        df[cols], df.y.to_numpy(), groups=df.brand.to_numpy()
    )
    return df, cols, m


def test_a_model_that_was_never_recalibrated_is_unchanged():
    """The whole feature must be inert until it is used."""
    pytest.importorskip("lightgbm")
    df, cols, m = _fitted()
    assert m.level_offset == {}
    assert m.recalibration_report().empty
    plain = get("gbm_per_brand")(min_rows=50).fit(
        df[cols], df.y.to_numpy(), groups=df.brand.to_numpy()
    )
    np.testing.assert_allclose(
        plain.predict(df[cols], groups=df.brand.to_numpy()),
        m.predict(df[cols], groups=df.brand.to_numpy()),
        rtol=0, atol=0,
    )


def test_an_observed_reprice_moves_later_predictions_by_that_amount():
    pytest.importorskip("lightgbm")
    df, cols, m = _fitted()
    obs = _jumped(df, pct=0.10, week=12)

    later = obs[obs.brand == "Mover"].iloc[[0]][cols].copy()
    later["week"] = 13.0
    before = float(m.predict(later, groups=np.array(["Mover"]))[0])

    m.recalibrate(obs[cols], obs.y.to_numpy(), groups=obs.brand.to_numpy())
    after = float(m.predict(later, groups=np.array(["Mover"]))[0])

    assert after - before == pytest.approx(0.10, abs=0.02)


def test_a_brand_that_did_not_move_is_left_alone():
    pytest.importorskip("lightgbm")
    df, cols, m = _fitted()
    obs = _jumped(df, brand="Mover", pct=0.10, week=12)
    m.recalibrate(obs[cols], obs.y.to_numpy(), groups=obs.brand.to_numpy())
    off = dict(m.level_offset)
    assert off["Mover"] == pytest.approx(0.10, abs=0.02)
    assert off["Static"] == pytest.approx(0.0, abs=0.02)


def test_repeated_recalibration_accumulates():
    """One call per collection week is the intended usage."""
    pytest.importorskip("lightgbm")
    df, cols, m = _fitted()
    for week, pct in ((12, 0.05), (13, 0.10)):
        obs = _jumped(df, pct=pct, week=week)
        m.recalibrate(obs[cols], obs.y.to_numpy(), groups=obs.brand.to_numpy())
    # the second call sees the first correction already applied, so the total
    # is the level actually observed last, not the sum of the two moves
    assert m.level_offset["Mover"] == pytest.approx(0.10, abs=0.02)
    assert m.as_of_week == 13.0
    assert len(m.recalibrations) == 2


def test_a_brand_missing_from_the_update_keeps_its_offset():
    """A brand that stopped quoting must not silently revert to its old level."""
    pytest.importorskip("lightgbm")
    df, cols, m = _fitted()
    obs = _jumped(df, pct=0.10, week=12)
    m.recalibrate(obs[cols], obs.y.to_numpy(), groups=obs.brand.to_numpy())
    was = m.level_offset["Mover"]

    only_static = obs[obs.brand == "Static"]
    m.recalibrate(only_static[cols], only_static.y.to_numpy(),
                  groups=only_static.brand.to_numpy())
    assert m.level_offset["Mover"] == pytest.approx(was)


def test_recalibrating_before_fitting_is_refused():
    pytest.importorskip("lightgbm")
    with pytest.raises(ValueError, match="fitted"):
        get("gbm_per_brand_trend")().recalibrate(
            pd.DataFrame({"log_sum_insured": [0.1], "week": [1.0]}),
            np.array([5.0]), groups=np.array(["A"]),
        )


def test_a_thin_update_is_shrunk_toward_the_market():
    """Five quotes in a week is not proof a brand repriced 30%."""
    pytest.importorskip("lightgbm")
    df, cols, m = _fitted(anchor_rows=50.0)
    obs = _jumped(df, pct=0.30, week=12).groupby("brand", observed=True).head(5)
    m.recalibrate(obs[cols], obs.y.to_numpy(), groups=obs.brand.to_numpy())
    assert abs(m.level_offset["Mover"]) < 0.30


def test_the_report_expresses_offsets_as_percentages():
    pytest.importorskip("lightgbm")
    df, cols, m = _fitted()
    obs = _jumped(df, pct=0.10, week=12)
    m.recalibrate(obs[cols], obs.y.to_numpy(), groups=obs.brand.to_numpy())
    rep = m.recalibration_report().set_index("brand")
    assert rep.loc["Mover"].offset_pct == pytest.approx(
        (np.exp(0.10) - 1) * 100, abs=2.0
    )
    assert rep.loc["Mover"].as_of_week == 12.0

"""Tests for deciding what the data can support before anything is fitted.

The failure these guard is silent in the usual way: a rating model fitted to a
single property fits the mean and still gets a leaderboard row, and a spatial
split with one postcode area empties the training set and reports every
approach as FAILED. Both look like model problems and are data problems.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from mktpricing.collect.synthetic import generate
from mktpricing.evaluate.adequacy import LEVEL_APPROACHES, assess
from mktpricing.evaluate.compare import (
    first_holdout_week_is_identical, rolling_comparison, run_comparison,
)
from mktpricing.features.build import build_matrix, design_matrix
from mktpricing.models.base import all_approaches, get

BRAND_LEVEL = {"Aviva": 5.00, "AXA": 5.20, "Admiral": 4.90}
DIRECT_LOADING = 0.05
DRIFT_PER_WEEK = 0.02


def single_risk_panel(n_weeks: int = 6, channels=("pcw_ctm", "direct")):
    """What manual collection actually yields: one property, weekly, several
    brands on several channels, every brand drifting up 2%/week."""
    risks = pd.DataFrame([dict(
        risk_id="MY-HOUSE", postcode="BS1 4DJ", outcode="BS1",
        policy_type="combined", building_type="semi_detached",
        construction="standard", occupancy="owner_occupied",
        year_built=1930, bedrooms=3,
        buildings_sum_insured=350_000.0, contents_sum_insured=50_000.0,
        voluntary_excess=250.0, claims_last_5y=0,
        flood_history=False, subsidence_history=False, in_basket=True,
        flood_band=1.0, crime_index=0.5, subsidence_band=1, area_avg_value=300_000.0,
    )])
    rows = []
    for w in range(n_weeks):
        for brand, level in BRAND_LEVEL.items():
            for ch in channels:
                log_p = level + DRIFT_PER_WEEK * w + (DIRECT_LOADING if ch == "direct" else 0.0)
                rows.append(dict(
                    risk_id="MY-HOUSE", brand=brand, underwriter=brand, channel=ch,
                    collected_on=_dt.date(2026, 9, 1) + _dt.timedelta(weeks=w),
                    source="manual", quoted=True, premium=float(np.exp(log_p)),
                ))
    return risks, pd.DataFrame(rows)


# -- adequacy ---------------------------------------------------------------


def test_a_single_property_is_level_only():
    risks, quotes = single_risk_panel()
    a = assess(build_matrix(quotes, risks), holdout_weeks=2)
    assert a.tier == "level_only"
    assert a.n_risks == 1 and a.n_areas == 1
    assert not a.spatial_split_possible
    assert a.temporal_split_possible
    # every risk feature is a constant, so it is named as one
    assert "log_sum_insured" in a.constant_features
    assert a.varying_features == []


def test_level_only_excludes_every_rating_model_with_a_reason():
    risks, quotes = single_risk_panel()
    a = assess(build_matrix(quotes, risks), holdout_weeks=2)
    assert set(a.eligible) == set(LEVEL_APPROACHES)
    for name in all_approaches():
        if name not in LEVEL_APPROACHES:
            assert "no risk feature varies" in a.excluded[name], name
    # nothing is silently dropped: excluded + eligible is the whole registry
    assert set(a.eligible) | set(a.excluded) == set(all_approaches())


def test_a_synthetic_cross_section_supports_the_full_lineup():
    risks, quotes, _ = generate(n_risks=120, n_weeks=6, seed=3)
    a = assess(build_matrix(quotes, risks), holdout_weeks=2)
    assert a.tier == "cross_section"
    assert a.excluded == {}
    assert a.spatial_split_possible
    assert set(a.eligible) == set(all_approaches())


def test_too_few_weeks_is_said_rather_than_crashed():
    risks, quotes = single_risk_panel(n_weeks=2)
    a = assess(build_matrix(quotes, risks), holdout_weeks=2)
    assert not a.temporal_split_possible
    assert any("cannot hold out" in n for n in a.notes)


def test_an_explicit_only_request_wins_over_the_exclusion():
    """Someone naming an approach on thin data is running an experiment."""
    risks, quotes = single_risk_panel()
    a = assess(build_matrix(quotes, risks), holdout_weeks=2)
    assert a.restrict(["gbm_per_brand"]) == ["gbm_per_brand"]
    assert a.restrict(None) == list(a.eligible)


def test_format_names_the_exclusions():
    risks, quotes = single_risk_panel()
    text = assess(build_matrix(quotes, risks), holdout_weeks=2).format()
    assert "level_only" in text
    assert "gbm_per_brand" in text and "excluded" in text


# -- brand_last_level --------------------------------------------------------


def _fit_on(df, weeks):
    train = df[df.week.isin(weeks)]
    X, y = design_matrix(train, include_brand=True)
    return get("brand_last_level")().fit(X, y, groups=train["brand"].to_numpy()), X


def test_last_level_carries_the_final_training_week_forward_per_channel():
    risks, quotes = single_risk_panel()
    df = build_matrix(quotes, risks)
    model, Xtr = _fit_on(df, [0, 1, 2, 3])

    future = df[df.week == 5]
    Xf, _ = design_matrix(future, include_brand=True)
    Xf = Xf.reindex(columns=Xtr.columns, fill_value=0.0)
    pred = model.predict(Xf, groups=future["brand"].to_numpy())

    for (brand, ch), p in zip(zip(future.brand, future.channel.astype(str)), pred):
        expect = BRAND_LEVEL[brand] + DRIFT_PER_WEEK * 3 + (DIRECT_LOADING if ch == "direct" else 0.0)
        assert p == pytest.approx(expect, abs=1e-9), (brand, ch)


def test_recalibrate_replaces_the_level_with_the_week_just_seen():
    risks, quotes = single_risk_panel()
    df = build_matrix(quotes, risks)
    model, Xtr = _fit_on(df, [0, 1, 2, 3])

    wk4 = df[df.week == 4]
    X4, y4 = design_matrix(wk4, include_brand=True)
    model.recalibrate(X4.reindex(columns=Xtr.columns, fill_value=0.0), y4,
                      groups=wk4["brand"].to_numpy())

    wk5 = df[df.week == 5]
    X5, _ = design_matrix(wk5, include_brand=True)
    pred = model.predict(X5.reindex(columns=Xtr.columns, fill_value=0.0),
                         groups=wk5["brand"].to_numpy())
    assert np.allclose(pred, y4)  # week 4's levels, exactly
    assert model.as_of_week == 4


def test_last_level_falls_back_to_brand_then_market():
    risks, quotes = single_risk_panel(channels=("pcw_ctm",))
    df = build_matrix(quotes, risks)
    model, Xtr = _fit_on(df, [0, 1, 2])

    # an unseen channel: no channel_* column set -> brand level
    X = pd.DataFrame(np.zeros((2, len(Xtr.columns))), columns=Xtr.columns)
    X["week"] = 9.0
    pred = model.predict(X, groups=np.array(["Aviva", "Never Seen"]))
    assert pred[0] == pytest.approx(BRAND_LEVEL["Aviva"] + 2 * DRIFT_PER_WEEK, abs=1e-9)
    market = np.median([v + 2 * DRIFT_PER_WEEK for v in BRAND_LEVEL.values()])
    assert pred[1] == pytest.approx(market, abs=1e-9)


def test_last_level_refuses_a_matrix_without_week():
    with pytest.raises(KeyError, match="week"):
        get("brand_last_level")().fit(
            pd.DataFrame({"x": [1.0, 2.0]}), np.array([0.0, 1.0]), groups=np.array(["A", "A"])
        )


# -- the harness on thin data -------------------------------------------------


def test_harness_runs_a_level_only_panel_without_a_spatial_split():
    risks, quotes = single_risk_panel()
    df = build_matrix(quotes, risks)
    a = assess(df, holdout_weeks=2)
    board, preds, _ = run_comparison(
        df, holdout_weeks=2, only=a.eligible, spatial=a.spatial_split_possible,
        verbose=False,
    )
    assert set(board.split) == {"temporal"}
    assert "error" not in board.columns
    by = board.set_index("approach").mdape
    # a drifting level: carrying the last week forward beats the training mean
    assert by["brand_last_level"] < by["brand_geomean"] < by["global_geomean"]


def test_last_level_takes_part_in_weekly_refresh_without_leaking():
    risks, quotes = single_risk_panel()
    df = build_matrix(quotes, risks)
    summary, _, per_week, _, _ = rolling_comparison(
        df, holdout_weeks=2, only=["brand_last_level"], verbose=False,
    )
    assert set(summary.regime) == {"blind", "rolling"}
    assert first_holdout_week_is_identical(per_week)
    wk = per_week.pivot_table(index="week", columns="regime", values="mape")
    last = wk.index.max()
    assert wk.loc[last, "rolling"] < wk.loc[last, "blind"]

"""Tests for the invariants that are easy to break silently.

Each of these guards a mistake that would still produce plausible-looking
numbers, which is the dangerous kind.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from mktpricing.collect.session import CollectionSession, coverage_report, read_session
from mktpricing.collect.synthetic import generate
from mktpricing.evaluate.metrics import median_ape, top_k_metrics
from mktpricing.evaluate.splits import spatial_split, temporal_split
from mktpricing.features.build import build_matrix, design_matrix
from mktpricing.market.simulate import cheapest_k, simulate_market, top_k_table


@pytest.fixture(scope="module")
def data():
    risks, quotes, truth = generate(n_risks=120, n_weeks=6, seed=3)
    return risks, quotes, truth


# -- generator -------------------------------------------------------------


def test_quoted_rows_always_have_finite_premiums(data):
    """The NaN-sum-insured bug class: `x or 0.0` does not catch NaN."""
    _, quotes, _ = data
    q = quotes[quotes.quoted]
    assert len(q) > 0
    assert np.isfinite(q.premium.astype(float)).all()


def test_declines_carry_no_premium(data):
    _, quotes, _ = data
    assert quotes[~quotes.quoted].premium.isna().all()


def test_declines_actually_occur(data):
    """If nothing declines, the quotability model is untested by this fixture."""
    _, quotes, _ = data
    assert 0.01 < (~quotes.quoted).mean() < 0.9


def test_direct_only_brands_never_on_pcw(data):
    _, quotes, _ = data
    pcw = quotes[quotes.channel != "direct"]
    assert not set(pcw.brand) & {"NFU Mutual", "Homeprotect"}


def test_minimum_premium_creates_a_point_mass(data):
    """Cheap risks pile at the floor; a model treating premium as continuous
    everywhere will mis-handle the low end."""
    _, quotes, _ = data
    q = quotes[quotes.quoted]
    counts = q.premium.round(2).value_counts()
    assert counts.iloc[0] > 1


# -- features --------------------------------------------------------------


def test_build_matrix_rejects_quoted_rows_without_premium(data):
    risks, quotes, _ = data
    broken = quotes.copy()
    idx = broken[broken.quoted].index[0]
    broken.loc[idx, "premium"] = np.nan
    with pytest.raises(ValueError, match="null premium"):
        build_matrix(broken, risks, quoted_only=True)


def test_target_is_log_premium(data):
    risks, quotes, _ = data
    df = build_matrix(quotes, risks)
    np.testing.assert_allclose(
        np.exp(df.log_premium.to_numpy()), df.premium.to_numpy(), rtol=1e-9
    )


def test_design_matrix_is_all_numeric(data):
    risks, quotes, _ = data
    X, y = design_matrix(build_matrix(quotes, risks), include_brand=True)
    assert all(k in "fiub" for k in X.dtypes.map(lambda d: d.kind))
    assert len(X) == len(y)


# -- splits ----------------------------------------------------------------


def test_temporal_split_has_no_week_overlap(data):
    risks, quotes, _ = data
    df = build_matrix(quotes, risks)
    tr, te = temporal_split(df, holdout_weeks=2)
    assert set(tr.week) & set(te.week) == set()
    assert tr.week.max() < te.week.min()


def test_spatial_split_shares_no_postcode_area(data):
    """The whole point: a test postcode must never appear in training."""
    risks, quotes, _ = data
    df = build_matrix(quotes, risks)
    tr, te, held = spatial_split(df, holdout_frac=0.3, seed=1)
    assert set(tr.outcode) & set(te.outcode) == set()
    assert held


# -- metrics ---------------------------------------------------------------


def test_median_ape_is_zero_for_perfect_prediction():
    y = np.log(np.array([100.0, 250.0, 900.0]))
    assert median_ape(y, y) == pytest.approx(0.0)


def test_top_k_overlap_is_100_when_ranking_is_perfect():
    df = pd.DataFrame(
        {
            "risk_id": ["R1"] * 6,
            "week": [0] * 6,
            "brand": list("ABCDEF"),
            "y_true": np.log([100, 120, 140, 160, 180, 200.0]),
        }
    )
    df["y_pred"] = df.y_true
    m = top_k_metrics(df, k=3)
    assert m["cheapest_hit"] == 100.0
    assert m["top3_overlap"] == 100.0


def test_top_k_detects_wrong_ordering():
    df = pd.DataFrame(
        {
            "risk_id": ["R1"] * 4,
            "week": [0] * 4,
            "brand": list("ABCD"),
            "y_true": np.log([100, 120, 140, 160.0]),
            "y_pred": np.log([160, 140, 120, 100.0]),  # exactly reversed
        }
    )
    m = top_k_metrics(df, k=2)
    assert m["cheapest_hit"] == 0.0


# -- market ----------------------------------------------------------------


def test_cheapest_k_handles_short_panels():
    assert cheapest_k([200.0, 100.0], k=5) == pytest.approx(150.0)
    assert np.isnan(cheapest_k([], k=5))


def test_declines_raise_the_simulated_market_price():
    """The core two-part argument: ignoring declines biases the price DOWN,
    because the cheap provider that would have refused wins the top-5."""
    panel = pd.DataFrame(
        {
            "risk_id": ["R1"] * 6,
            "week": [0] * 6,
            "brand": list("ABCDEF"),
            "pred_premium": [100.0, 300, 320, 340, 360, 380],
            # the cheapest brand almost never actually quotes
            "p_quote": [0.02, 1.0, 1.0, 1.0, 1.0, 1.0],
        }
    )
    with_declines = simulate_market(panel, k=3, n_sims=400, seed=0)
    without = simulate_market(panel, k=3, n_sims=400, seed=0, include_declines=False)
    assert with_declines["top3_mean"].iloc[0] > without["top3_mean"].iloc[0]


# -- collection ------------------------------------------------------------


def test_session_template_prefills_the_full_grid(tmp_path):
    """Pre-filling matters: an uncollected provider leaves a visible empty row
    rather than vanishing."""
    s = CollectionSession(
        session_id="S1",
        collected_on=_dt.date(2026, 8, 27),
        identity_ref="me",
        risk_ids=["R1", "R2"],
        channels=["pcw_ctm", "direct"],
        brands=["Aviva", "AXA", "Admiral"],
    )
    path = s.write_template(tmp_path / "s.csv")
    rows = list(pd.read_csv(path).itertuples())
    assert len(rows) == s.expected_rows() == 12


def test_read_session_rejects_quoted_without_premium(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text(
        "risk_id,brand,channel,collected_on,quoted,premium,compulsory_excess,"
        "accidental_damage,rank_on_page,cashback,incentive_note,collector_note\n"
        "R1,Aviva,pcw_ctm,2026-08-27,y,,,,,,,\n",
        encoding="utf-8",
    )
    rows, problems = read_session(p)
    assert rows == []
    assert problems and "no premium" in problems[0]


def test_coverage_report_separates_missing_from_declined():
    rows = [
        {"brand": "Aviva", "channel": "pcw_ctm", "quoted": True},
        {"brand": "AXA", "channel": "pcw_ctm", "quoted": False},
    ]
    rep = {r["brand"]: r for r in coverage_report(rows, ["Aviva", "AXA", "LV="],
                                                  ["pcw_ctm"])}
    assert rep["AXA"]["declined"] == 1
    assert rep["AXA"]["status"] == "complete"     # asked, said no
    assert rep["LV="]["status"] == "MISSING"      # never asked -- not signal


def test_top_k_gives_each_brand_one_place():
    """Regression: a brand quoted on three channels used to occupy three slots,
    so 'the five cheapest providers' was really 'the five cheapest quotes'."""
    panel = pd.DataFrame(
        {
            "risk_id": ["R1"] * 6,
            "week": [0] * 6,
            "brand": ["Aviva", "Aviva", "Aviva", "AXA", "AXA", "Admiral"],
            "channel": ["direct", "pcw_ctm", "pcw_msm", "direct", "pcw_ctm", "direct"],
            "pred_premium": [200.0, 210, 220, 300, 290, 400],
            "p_quote": [1.0] * 6,
        }
    )
    top = top_k_table(panel, "R1", week=0, k=5)
    assert list(top.brand) == ["Aviva", "AXA", "Admiral"]
    assert top.brand.is_unique
    # each brand enters at its cheapest channel
    assert top.loc[top.brand == "Aviva", "pred_premium"].iloc[0] == 200.0
    assert top.loc[top.brand == "AXA", "best_channel"].iloc[0] == "pcw_ctm"


def test_simulate_market_panel_size_counts_brands_not_quotes():
    panel = pd.DataFrame(
        {
            "risk_id": ["R1"] * 6,
            "week": [0] * 6,
            "brand": ["Aviva", "Aviva", "Aviva", "AXA", "AXA", "Admiral"],
            "channel": ["direct", "pcw_ctm", "pcw_msm", "direct", "pcw_ctm", "direct"],
            "pred_premium": [200.0, 210, 220, 300, 290, 400],
            "p_quote": [1.0] * 6,
        }
    )
    m = simulate_market(panel, k=5, n_sims=20, seed=0)
    assert m.n_on_panel.iloc[0] == 3


def test_by_channel_keeps_channels_separate():
    panel = pd.DataFrame(
        {
            "risk_id": ["R1"] * 4,
            "week": [0] * 4,
            "brand": ["Aviva", "AXA", "Aviva", "AXA"],
            "channel": ["direct", "direct", "pcw_ctm", "pcw_ctm"],
            "pred_premium": [200.0, 300, 210, 290],
            "p_quote": [1.0] * 4,
        }
    )
    m = simulate_market(panel, k=2, n_sims=10, seed=0, by_channel=True)
    assert len(m) == 2
    assert set(m.channel) == {"direct", "pcw_ctm"}


# -- approach selection ----------------------------------------------------


def test_only_accepts_the_comma_separated_form(data):
    """Regression: `--only a,b` arrives as one comma-joined string. It used to
    match nothing and return an empty leaderboard, which reads as 'every
    approach lost' rather than 'you filtered them all out'."""
    from mktpricing.evaluate.compare import run_comparison

    risks, quotes, _ = data
    df = build_matrix(quotes, risks)
    lb, preds, _ = run_comparison(
        df, holdout_weeks=1, only=["global_geomean,ridge_log"], verbose=False
    )
    assert set(lb.approach) == {"global_geomean", "ridge_log"}
    assert not preds.empty


def test_only_rejects_an_unknown_approach(data):
    from mktpricing.evaluate.compare import run_comparison

    risks, quotes, _ = data
    df = build_matrix(quotes, risks)
    with pytest.raises(ValueError, match="unknown approach"):
        run_comparison(df, holdout_weeks=1, only=["nonsense"], verbose=False)


def test_generated_postcodes_are_valid(data):
    """The inward code excludes C, I, K, M, O and V. Drawing from the full
    alphabet produced postcodes that look right and fail features.geo parsing,
    so synthetic risks could not be geo-enriched at all."""
    from mktpricing.features.geo import parse_postcode

    risks, _, _ = data
    bad = [p for p in risks.postcode.unique() if not parse_postcode(p).valid]
    assert bad == []


# -- week derivation -------------------------------------------------------


def _dated_frame(dates):
    risks = pd.DataFrame(
        {
            "risk_id": ["R1"], "postcode": ["BS1 4DJ"], "policy_type": ["combined"],
            "building_type": ["detached"], "construction": ["standard"],
            "occupancy": ["owner_occupied"], "year_built": [1990], "bedrooms": [3],
            "buildings_sum_insured": [250000.0], "contents_sum_insured": [45000.0],
            "voluntary_excess": [250.0], "claims_last_5y": [0],
            "flood_history": [False], "subsidence_history": [False],
            "flood_band": [0.0], "crime_index": [0.3], "subsidence_band": [0.0],
            "area_avg_value": [300000.0], "outcode": ["BS1"],
        }
    )
    quotes = pd.DataFrame(
        {
            "risk_id": ["R1"] * len(dates), "brand": ["Aviva"] * len(dates),
            "channel": ["direct"] * len(dates), "collected_on": dates,
            "quoted": [True] * len(dates), "premium": [300.0] * len(dates),
        }
    )
    return risks, quotes


def test_week_is_derived_from_the_collection_date():
    """Regression: `week` used to default to 0 when absent, which collapsed
    every date into one week -- so the temporal split had nothing to hold out,
    the index was a single point, and drift was invisible. Vendor extracts and
    manual sessions carry `collected_on` and never `week`, so that was every
    real data path."""
    risks, quotes = _dated_frame(
        [_dt.date(2026, 7, 1), _dt.date(2026, 7, 8), _dt.date(2026, 7, 22)]
    )
    m = build_matrix(quotes, risks)
    assert list(m.week) == [0, 1, 3]


def test_an_explicit_week_column_is_left_alone():
    risks, quotes = _dated_frame([_dt.date(2026, 7, 1), _dt.date(2026, 7, 8)])
    quotes["week"] = [5, 9]
    assert list(build_matrix(quotes, risks).week) == [5, 9]


def test_missing_collection_dates_are_refused_not_defaulted():
    risks, quotes = _dated_frame([_dt.date(2026, 7, 1)])
    with pytest.raises(KeyError, match="collected_on"):
        build_matrix(quotes.drop(columns=["collected_on"]), risks)


def test_unparseable_dates_are_refused():
    """Guessing a week would put the quote in the wrong period of the index."""
    risks, quotes = _dated_frame([_dt.date(2026, 7, 1), _dt.date(2026, 7, 8)])
    quotes["collected_on"] = ["2026-07-01", "not a date"]
    with pytest.raises(ValueError, match="unparseable"):
        build_matrix(quotes, risks)


def test_missing_geo_features_name_themselves():
    """A bare KeyError five columns into the build sent you to the wrong file."""
    risks, quotes = _dated_frame([_dt.date(2026, 7, 1)])
    with pytest.raises(KeyError, match="features.geo"):
        build_matrix(quotes, risks.drop(columns=["flood_band"]))


# -- derived index basket ---------------------------------------------------


def _market_frame(rows):
    """(risk_id, week) pairs as a minimal simulated-market frame."""
    return pd.DataFrame(
        [{"risk_id": r, "week": w, "top5_mean": 300.0} for r, w in rows]
    )


def test_common_risks_keeps_only_risks_present_in_every_week():
    from mktpricing.market.simulate import common_risks

    m = _market_frame(
        [("A", 0), ("A", 1), ("A", 2), ("B", 0), ("B", 1), ("C", 2)]
    )
    assert common_risks(m) == ["A"]


def test_common_risks_returns_nothing_when_the_panel_fully_rotates():
    """The honest answer for a rotating panel is 'no index exists', not an
    index computed over a changing set of risks."""
    from mktpricing.market.simulate import common_risks

    assert common_risks(_market_frame([("A", 0), ("B", 1), ("C", 2)])) == []


def test_common_risks_on_a_single_week_keeps_everything():
    from mktpricing.market.simulate import common_risks

    assert common_risks(_market_frame([("A", 0), ("B", 0)])) == ["A", "B"]


def test_common_risks_on_an_empty_frame_is_empty():
    from mktpricing.market.simulate import common_risks

    assert common_risks(pd.DataFrame()) == []


def test_top_k_ranks_by_expected_premium_not_raw_price():
    """A provider that almost never quotes must not head a cheapest-five list.

    Regression: the score was computed and then discarded by sorting on raw
    premium, so the POC's example table led with three brands at p_quote < 1%
    and disagreed with the market price `simulate_market` produced for the same
    risk.
    """
    panel = pd.DataFrame(
        {
            "risk_id": ["R1"] * 3,
            "week": [0] * 3,
            "brand": ["Rarely", "Sometimes", "Always"],
            "channel": ["direct"] * 3,
            "pred_premium": [90.0, 150.0, 200.0],
            "p_quote": [0.004, 0.5, 0.99],
        }
    )
    top = top_k_table(panel, "R1", week=0, k=3)
    assert list(top.brand) == ["Always", "Sometimes", "Rarely"]
    # the cheap-but-unavailable provider is still shown, at its real price
    assert top.loc[top.brand == "Rarely", "pred_premium"].iloc[0] == 90.0


def test_top_k_order_is_unchanged_when_everyone_quotes():
    """With equal quote probability the weighting is a no-op, so the ranking is
    still simply cheapest-first."""
    panel = pd.DataFrame(
        {
            "risk_id": ["R1"] * 3,
            "week": [0] * 3,
            "brand": ["A", "B", "C"],
            "channel": ["direct"] * 3,
            "pred_premium": [300.0, 100.0, 200.0],
            "p_quote": [1.0, 1.0, 1.0],
        }
    )
    assert list(top_k_table(panel, "R1", week=0, k=3).brand) == ["B", "C", "A"]


# -- rolling (blind vs weekly refresh) --------------------------------------


def _rolling(data, **kw):
    from mktpricing.evaluate.compare import rolling_comparison

    risks, quotes, _ = data
    df = build_matrix(quotes, risks)
    return rolling_comparison(
        df, holdout_weeks=kw.pop("holdout_weeks", 3),
        only=["gbm_per_brand_trend"], verbose=False, **kw
    )


def test_rolling_scores_both_regimes_on_the_same_rows():
    pytest.importorskip("lightgbm")
    from mktpricing.collect.synthetic import generate

    risks, quotes, _ = generate(n_risks=120, n_weeks=6, seed=3)
    summary, per_brand, per_week, preds = _rolling((risks, quotes, None))
    assert set(summary.regime) == {"blind", "rolling"}
    # both regimes must score exactly the same rows, or the comparison is
    # between two different test sets rather than two ways of predicting one
    assert summary.n.nunique() == 1


def test_the_first_holdout_week_is_identical_under_both_regimes():
    """The central guard against leaking the holdout.

    Nothing has been observed when the first holdout week is priced, so there
    is nothing to correct and the two regimes must agree exactly. If they ever
    disagree, the rolling pass absorbed data before scoring it and every figure
    it produces is flattering and wrong.
    """
    pytest.importorskip("lightgbm")
    from mktpricing.collect.synthetic import generate
    from mktpricing.evaluate.compare import first_holdout_week_is_identical

    risks, quotes, _ = generate(n_risks=120, n_weeks=6, seed=3)
    _, _, per_week, _ = _rolling((risks, quotes, None))

    first = per_week.week.min()
    got = per_week[per_week.week == first].set_index("regime")
    assert got.loc["blind"].mape == pytest.approx(got.loc["rolling"].mape, abs=0)
    assert first_holdout_week_is_identical(per_week)


def test_the_leak_guard_actually_fires():
    """A guard nobody has seen fail is a guard nobody has tested."""
    import pandas as pd
    from mktpricing.evaluate.compare import first_holdout_week_is_identical

    leaking = pd.DataFrame({
        "approach": ["a", "a"], "regime": ["blind", "rolling"],
        "week": [9, 9], "mape": [5.0, 4.2],
    })
    assert not first_holdout_week_is_identical(leaking)


def test_rolling_skips_approaches_that_cannot_recalibrate():
    """gbm_per_brand has no `recalibrate`; running it in both regimes would be
    the same computation twice, reported as if it were a comparison."""
    from mktpricing.collect.synthetic import generate
    from mktpricing.evaluate.compare import rolling_comparison

    risks, quotes, _ = generate(n_risks=60, n_weeks=5, seed=1)
    summary, *_ = rolling_comparison(
        build_matrix(quotes, risks), holdout_weeks=2,
        only=["gbm_per_brand"], verbose=False,
    )
    assert summary.empty

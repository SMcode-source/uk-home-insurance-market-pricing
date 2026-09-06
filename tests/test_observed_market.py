"""Tests for the observed market price: best price, top-k, spread.

Built on a hand-sized panel where every number can be checked by eye. The
things worth pinning are the definitions -- a brand counted once across its
channels, declines counted but never priced, spread as best-to-kth -- because
each is a choice that a plausible alternative would silently change.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from mktpricing.market.observed import (
    brand_competitiveness, channel_gap, market_by_period, observed_market,
    period_key, spread_summary,
)

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "market_price.py"
_spec = importlib.util.spec_from_file_location("market_price", _PATH)
market_price = importlib.util.module_from_spec(_spec)
sys.modules["market_price"] = market_price
_spec.loader.exec_module(market_price)

D1 = _dt.date(2026, 7, 1)     # a Wednesday
D2 = _dt.date(2026, 7, 8)


def _panel():
    """Risk R1 on two dates; R2 on the first only.

    On R1/D1 six brands are asked: A 100, B 120, C 130 (direct 150, so its
    cheapest channel is the PCW), D 140, E 200, F declines. Top-5 is
    A B C D E -> mean 138, 5th = 200, spread 100 (100%).
    On R1/D2 everything is 10% dearer. On R2/D1 only A and B quote.
    """
    rows = []

    def q(risk, d, brand, ch, prem, quoted=True):
        rows.append(dict(risk_id=risk, brand=brand, channel=ch, collected_on=d,
                         quoted=quoted, premium=prem, source="manual"))

    for d, m in ((D1, 1.0), (D2, 1.1)):
        q("R1", d, "A", "pcw_ctm", 100 * m)
        q("R1", d, "B", "pcw_ctm", 120 * m)
        q("R1", d, "C", "pcw_ctm", 130 * m)
        q("R1", d, "C", "direct", 150 * m)
        q("R1", d, "D", "pcw_ctm", 140 * m)
        q("R1", d, "E", "pcw_ctm", 200 * m)
        q("R1", d, "F", "pcw_ctm", None, quoted=False)
    q("R2", D1, "A", "pcw_ctm", 300.0)
    q("R2", D1, "B", "pcw_ctm", 330.0)
    q("R2", D1, "C", "direct", None, quoted=False)
    return pd.DataFrame(rows)


# -- observed_market -----------------------------------------------------------


def test_best_price_top5_and_spread_by_hand():
    m = observed_market(_panel(), k=5)
    r = m[(m.risk_id == "R1") & (m.period == D1)].iloc[0]
    assert r.n_on_panel == 6 and r.n_quoting == 5 and r.n_declined == 1
    assert r.cheapest_brand == "A" and r.cheapest_price == 100.0
    assert r.cheapest_channel == "pcw_ctm"
    assert r.top5_mean == pytest.approx(138.0)
    assert r.top5_median == 130.0
    assert r.top5_kth == 200.0
    assert bool(r.top5_complete) is True
    assert r.top5_brands == "A|B|C|D|E"
    assert r.spread_abs == pytest.approx(100.0)
    assert r.spread_pct == pytest.approx(100.0)
    assert r.panel_max == 200.0


def test_a_brand_on_two_channels_is_counted_once_at_its_cheapest():
    """Without the collapse C's direct quote (150) would take D's place in
    the top five, and 'the five cheapest brands' would be four."""
    m = observed_market(_panel(), k=5)
    r = m[(m.risk_id == "R1") & (m.period == D1)].iloc[0]
    assert "C" in r.top5_brands and r.top5_brands.count("C") == 1
    assert r.top5_mean == pytest.approx((100 + 120 + 130 + 140 + 200) / 5)


def test_by_channel_ranks_within_each_channel():
    m = observed_market(_panel(), k=5, by_channel=True)
    d = m[(m.risk_id == "R1") & (m.period == D1) & (m.channel == "direct")].iloc[0]
    assert d.n_quoting == 1 and d.cheapest_brand == "C" and d.cheapest_price == 150.0
    assert bool(d.top5_complete) is False


def test_fewer_than_k_quoting_is_reported_not_padded():
    m = observed_market(_panel(), k=5)
    r = m[(m.risk_id == "R2")].iloc[0]
    assert r.n_quoting == 2 and r.n_declined == 1
    assert bool(r.top5_complete) is False
    assert r.top5_mean == 315.0 and r.top5_kth == 330.0
    assert r.spread_abs == 30.0


def test_declines_are_counted_never_priced():
    p = _panel()
    p.loc[~p.quoted, "premium"] = 0.0      # a vendor's placeholder zero
    m = observed_market(p, k=5)
    r = m[(m.risk_id == "R1") & (m.period == D1)].iloc[0]
    assert r.cheapest_price == 100.0        # the zero did not win
    assert r.n_declined == 1


def test_all_declined_group_has_counts_but_no_price():
    p = _panel()
    p.loc[p.risk_id == "R2", "quoted"] = False
    p.loc[p.risk_id == "R2", "premium"] = None
    m = observed_market(p, k=5)
    r = m[m.risk_id == "R2"].iloc[0]
    assert r.n_quoting == 0 and pd.isna(r.cheapest_price)


def test_missing_columns_are_an_error():
    with pytest.raises(ValueError, match="missing"):
        observed_market(pd.DataFrame({"risk_id": ["a"], "brand": ["b"]}))


# -- periods --------------------------------------------------------------------


def test_period_buckets():
    days = pd.Series([_dt.date(2026, 7, 1), _dt.date(2026, 7, 5), _dt.date(2026, 7, 6)])
    assert period_key(days, "day").tolist() == days.tolist()
    assert period_key(days, "week").tolist() == [
        _dt.date(2026, 6, 29), _dt.date(2026, 6, 29), _dt.date(2026, 7, 6)]
    assert period_key(days, "month").tolist() == [_dt.date(2026, 7, 1)] * 3
    with pytest.raises(ValueError):
        period_key(days, "fortnight")


def test_weekly_period_merges_daily_quotes_and_keeps_the_cheapest():
    p = _panel()
    extra = p[(p.risk_id == "R1") & (p.collected_on == D1)].copy()
    extra["collected_on"] = _dt.date(2026, 7, 3)     # same week, Friday
    extra["premium"] = extra["premium"] * 0.9
    m = observed_market(pd.concat([p, extra]), k=5, period="week")
    r = m[(m.risk_id == "R1") & (m.period == _dt.date(2026, 6, 29))].iloc[0]
    assert r.cheapest_price == pytest.approx(90.0)


# -- aggregates -------------------------------------------------------------------


def test_market_by_period_indexes_the_top_k_on_a_basket():
    m = observed_market(_panel(), k=5)
    bp = market_by_period(m, k=5, basket_risk_ids=["R1"])
    assert bp.n_risks.tolist() == [1, 1]
    assert bp.index_100.tolist() == [100.0, pytest.approx(110.0)]
    assert bp.wow_pct.tolist()[1] == pytest.approx(10.0)
    assert bp.cheapest_mean.tolist() == [100.0, pytest.approx(110.0)]
    # without the basket R2 drags the first period up: mix, not price
    loose = market_by_period(m, k=5)
    assert loose.n_risks.tolist() == [2, 1]
    assert loose.index_100.iloc[1] < 100.0


def test_market_by_period_per_channel_indexes_each_channel_separately():
    m = observed_market(_panel(), k=5, by_channel=True)
    bp = market_by_period(m, k=5, basket_risk_ids=["R1"], by_channel=True)
    for ch in ("direct", "pcw_ctm"):
        sub = bp[bp.channel == ch]
        assert sub.index_100.iloc[0] == 100.0
        assert sub.index_100.iloc[1] == pytest.approx(110.0)


def test_brand_competitiveness_by_hand():
    bc = brand_competitiveness(_panel(), k=5).set_index("brand")
    assert bc.loc["A", "n_asked"] == 3 and bc.loc["A", "n_cheapest"] == 3
    assert bc.loc["A", "cheapest_share_pct"] == 100.0
    assert bc.loc["A", "gap_to_cheapest_pct"] == 0.0
    assert bc.loc["B", "gap_to_cheapest_pct"] == pytest.approx(20.0, abs=0.1)  # median of 20, 20, 10
    assert bc.loc["F", "n_quoted"] == 0 and bc.loc["F", "quote_rate_pct"] == 0.0
    assert bc.loc["C", "n_asked"] == 3 and bc.loc["C", "n_quoted"] == 2
    assert bc.loc["E", "n_in_top5"] == 2 and bc.loc["E", "median_rank"] == 5.0
    assert bc.index[0] == "A"                       # sorted by cheapest share


def test_channel_gap_is_direct_over_cheapest_pcw():
    cg = channel_gap(_panel())
    assert cg.brand.tolist() == ["C"]               # the only brand quoted both ways
    assert cg.n_pairs.iloc[0] == 2
    assert cg.direct_over_pcw_pct.iloc[0] == pytest.approx(15.4, abs=0.1)   # 150/130


def test_channel_gap_is_empty_on_a_single_channel_file():
    p = _panel()
    p = p[p.channel == "pcw_ctm"]
    assert channel_gap(p).empty


def test_spread_summary_headline_keys():
    m = observed_market(_panel(), k=5)
    s = spread_summary(m, k=5)
    assert s["n_risk_periods"] == 3 and s["n_complete"] == 2
    assert s["spread_pct_median"] == 100.0
    assert set(s) >= {"cheapest_mean", "top5_mean", "spread_abs_median", "spread_pct_p90"}
    assert spread_summary(m.iloc[0:0], k=5) == {}


# -- the script -------------------------------------------------------------------


def test_market_price_script_from_parquet(tmp_path, capsys):
    p = _panel()
    p.to_parquet(tmp_path / "quotes.parquet", index=False)
    risks = pd.DataFrame({"risk_id": ["R1", "R2"], "in_basket": [True, False]})
    risks.to_parquet(tmp_path / "risks.parquet", index=False)
    out = tmp_path / "market"
    rc = market_price.main([
        "--data", str(tmp_path / "quotes.parquet"), "--risks", str(tmp_path / "risks.parquet"),
        "--out", str(out),
    ])
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "declared (Risk.in_basket)" in text
    for f in ("market_by_risk.csv", "market_by_period.csv", "brand_competitiveness.csv",
              "channel_gap.csv", "market.json"):
        assert (out / f).exists(), f
    bp = pd.read_csv(out / "market_by_period.csv")
    assert bp.index_100.tolist() == [100.0, 110.0]
    assert "spread (best -> 5th)" in text


def test_market_price_script_from_vendor_files(tmp_path, capsys):
    """Straight from a vendor-shaped CSV through a spec, no parquet step."""
    df = pd.DataFrame({
        "QuoteReference": ["R1"] * 3, "Brand": ["Aviva", "AXA", "Admiral"],
        "Channel": ["Compare the Market"] * 3, "QuoteDate": ["01/07/2026"] * 3,
        "Status": ["Quoted", "Quoted", "Declined"], "AnnualPremium": ["300", "280", ""],
        "Rank": ["2", "1", ""], "Postcode": ["BS1 4DJ"] * 3,
        "CoverType": ["Buildings & Contents"] * 3, "PropertyType": ["Detached"] * 3,
        "ConstructionType": ["Standard"] * 3, "OccupancyType": ["Owner Occupied"] * 3,
        "YearBuilt": ["1990"] * 3, "Bedrooms": ["4"] * 3,
        "BuildingsSumInsured": ["300000"] * 3, "ContentsSumInsured": ["50000"] * 3,
        "VoluntaryExcess": ["250"] * 3, "CompulsoryExcess": ["100"] * 3,
        "ClaimsCount": ["0"] * 3, "AccidentalDamage": ["No"] * 3,
    })
    f = tmp_path / "ci_2026-07-01.csv"
    df.to_csv(f, index=False)
    out = tmp_path / "market"
    rc = market_price.main([str(f), "--spec", "ci", "--out", str(out)])
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "AUDIT" in text
    m = pd.read_csv(out / "market_by_risk.csv")
    assert m.cheapest_brand.tolist() == ["AXA"] and m.cheapest_price.tolist() == [280.0]
    assert m.n_declined.tolist() == [1]
    assert "no index" in text          # a single date cannot be indexed


def test_market_price_script_with_nothing_to_price(tmp_path, capsys):
    p = _panel()
    p["quoted"] = False
    p["premium"] = None
    p.to_parquet(tmp_path / "q.parquet", index=False)
    rc = market_price.main(["--data", str(tmp_path / "q.parquet"), "--out", str(tmp_path / "m")])
    assert rc == 2

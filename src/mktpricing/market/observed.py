"""Market price from *observed* quotes: best price, top-5, spread.

`simulate.py` derives a market price from model predictions, which is what you
need when a risk was never quoted. This module answers the simpler question for
risks that were: given the quotes a vendor (or a collector) actually returned,
what did the market look like on that day?

Three numbers per risk and date, and the definitions matter:

**Best price.** The cheapest quote across the panel, with each brand counted once
at its cheapest channel. A brand on four PCWs is one brand, not four places.

**Top-k market price.** The mean of the k cheapest brands (k=5 by default). This
is the aggregator page-one experience -- the prices a customer weighs, not the
long tail of expensive quotes nobody clicks. The median and the k-th price are
carried alongside because the mean alone hides a lone outlier at the top of the
five.

**Spread.** The gap between the best price and the k-th cheapest, in GBP and as
a percentage of the best price. It is the range of the top five: a tight spread
means the leaders are pricing the risk the same way; a wide one means at least
one of them is not. The panel-wide spread (cheapest to most expensive quote) is
also reported, and is a different, noisier thing -- one specialist quoting a
mainstream risk at three times the market widens it without telling you anything
about the competitive front.

Declines are counted, never priced. A brand that refused a risk lowers
`n_quoting` and is absent from the ranking; it does not get an imputed premium.
When fewer than k brands quoted, `top{k}_complete` is False and the top-k mean
is over what there is -- reported, not padded.

Periods. Vendors deliver daily; an index wants weeks. `period="day"` keeps the
collection date, `"week"` buckets to the Monday, `"month"` to the first. The
week-on-week index is only meaningful on a fixed basket, for the same reason
as in `simulate.market_index`: on a rotating panel movement is mix, not price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .simulate import collapse_to_brand

__all__ = [
    "period_key", "observed_market", "market_by_period", "brand_competitiveness",
    "channel_gap", "spread_summary",
]


# ---------------------------------------------------------------------------
# periods
# ---------------------------------------------------------------------------


def period_key(dates, period: str = "day") -> pd.Series:
    """Bucket collection dates: 'day' (unchanged), 'week' (Monday), 'month' (1st)."""
    d = pd.to_datetime(pd.Series(dates), errors="coerce")
    if period == "day":
        out = d
    elif period == "week":
        out = d - pd.to_timedelta(d.dt.weekday, unit="D")
    elif period == "month":
        out = d.dt.to_period("M").dt.to_timestamp()
    else:
        raise ValueError(f"period must be 'day', 'week' or 'month', got {period!r}")
    return out.dt.date


def _prepare(quotes: pd.DataFrame, period: str) -> pd.DataFrame:
    need = {"risk_id", "brand", "collected_on", "quoted"}
    missing = need - set(quotes.columns)
    if missing:
        raise ValueError(f"quotes is missing {sorted(missing)}")
    q = quotes.copy()
    q["period"] = period_key(q["collected_on"], period).to_numpy()
    q = q[pd.notna(q["period"])]
    if "channel" not in q.columns:
        q["channel"] = "unknown"
    q["quoted"] = q["quoted"].astype(bool)
    if "premium" not in q.columns:
        q["premium"] = np.nan
    q["premium"] = pd.to_numeric(q["premium"], errors="coerce")
    # A quoted row without a price cannot be ranked; a declined row must not be.
    q.loc[~q["quoted"], "premium"] = np.nan
    return q


# ---------------------------------------------------------------------------
# per risk and period
# ---------------------------------------------------------------------------


def observed_market(quotes: pd.DataFrame, *, k: int = 5, period: str = "day",
                    by_channel: bool = False) -> pd.DataFrame:
    """One row per risk and period (and channel, if `by_channel`).

    Columns: n_on_panel (brands asked), n_quoting, n_declined, cheapest_brand,
    cheapest_price, cheapest_channel, top{k}_mean, top{k}_median, top{k}_kth,
    top{k}_complete, top{k}_brands, spread_abs, spread_pct, panel_median,
    panel_max, panel_spread_pct.

    `by_channel=False` is the consumer market: each brand once, at its cheapest
    channel. `by_channel=True` is "the cheapest five on Compare the Market",
    which is what a PCW-specific vendor file supports and what a brand's
    channel strategy is judged on.
    """
    q = _prepare(quotes, period)
    if q.empty:
        return pd.DataFrame()
    group = ["risk_id", "period"] + (["channel"] if by_channel else [])

    # Who was asked, who quoted, who refused -- per brand, before pricing.
    asked = q.groupby(group + ["brand"], observed=True)["quoted"].any().reset_index()
    counts = asked.groupby(group, observed=True)["quoted"].agg(
        n_on_panel="size", n_quoting="sum"
    ).reset_index()
    counts["n_quoting"] = counts["n_quoting"].astype(int)
    counts["n_declined"] = counts["n_on_panel"] - counts["n_quoting"]

    priced = q[q["quoted"] & q["premium"].notna()]
    if not by_channel:
        priced = collapse_to_brand(priced, premium_col="premium",
                                   group_cols=("risk_id", "period"))
    else:
        priced = priced.copy()
        priced["best_channel"] = priced["channel"]

    rows = []
    for keys, g in priced.groupby(group, observed=True, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        g = g.sort_values("premium", kind="mergesort")
        prem = g["premium"].to_numpy(dtype=float)
        top = prem[:k]
        best = float(prem[0])
        kth = float(top[-1])
        rec = dict(zip(group, keys))
        rec.update({
            "cheapest_brand": g["brand"].iloc[0],
            "cheapest_price": best,
            "cheapest_channel": g["best_channel"].iloc[0] if "best_channel" in g else None,
            f"top{k}_mean": float(top.mean()),
            f"top{k}_median": float(np.median(top)),
            f"top{k}_kth": kth,
            f"top{k}_complete": bool(prem.size >= k),
            f"top{k}_brands": "|".join(g["brand"].iloc[:k].astype(str)),
            "spread_abs": kth - best,
            "spread_pct": (kth - best) / best * 100.0 if best > 0 else np.nan,
            "panel_median": float(np.median(prem)),
            "panel_max": float(prem[-1]),
            "panel_spread_pct": (float(prem[-1]) - best) / best * 100.0 if best > 0 else np.nan,
        })
        rows.append(rec)

    priced_df = pd.DataFrame(rows)
    out = counts.merge(priced_df, on=group, how="left") if rows else counts
    return out.sort_values(group).reset_index(drop=True)


# ---------------------------------------------------------------------------
# aggregates
# ---------------------------------------------------------------------------


def market_by_period(market: pd.DataFrame, *, k: int = 5, basket_risk_ids=None,
                     by_channel: bool = False) -> pd.DataFrame:
    """Per period: how many risks, mean best price, mean top-k, spread, index.

    `index_100` and `wow_pct` are on the top-k mean and are only a price index
    when `basket_risk_ids` holds the panel fixed. Without a basket they are
    still computed, because the caller may know the panel is fixed -- but a
    rotating panel will make them measure composition, and the audit's
    `rotating_panel` finding is the warning to heed.
    """
    df = market
    if basket_risk_ids is not None:
        df = df[df["risk_id"].isin(set(basket_risk_ids))]
    df = df[df["cheapest_price"].notna()]
    group = ["period"] + (["channel"] if by_channel and "channel" in df.columns else [])
    if df.empty:
        return pd.DataFrame(columns=group)
    agg = df.groupby(group, observed=True).agg(
        n_risks=("risk_id", "nunique"),
        n_quoting_mean=("n_quoting", "mean"),
        cheapest_mean=("cheapest_price", "mean"),
        **{f"top{k}_mean": (f"top{k}_mean", "mean")},
        **{f"top{k}_median": (f"top{k}_median", "median")},
        spread_abs_mean=("spread_abs", "mean"),
        spread_pct_median=("spread_pct", "median"),
        panel_spread_pct_median=("panel_spread_pct", "median"),
    ).reset_index()
    col = f"top{k}_mean"
    if by_channel and "channel" in agg.columns:
        base = agg.groupby("channel", observed=True)[col].transform("first")
        agg["index_100"] = (agg[col] / base * 100.0).round(2)
        agg["wow_pct"] = (agg.groupby("channel", observed=True)[col].pct_change() * 100).round(2)
    else:
        agg["index_100"] = (agg[col] / agg[col].iloc[0] * 100.0).round(2)
        agg["wow_pct"] = (agg[col].pct_change() * 100.0).round(2)
    return agg


def brand_competitiveness(quotes: pd.DataFrame, *, k: int = 5, period: str = "day",
                          by_channel: bool = False) -> pd.DataFrame:
    """Per brand: how often it quotes, wins, makes the top k, and by how much
    it misses.

    `gap_to_cheapest_pct` is the brand's price over the best price on the same
    risk and period, median across the risk-periods it quoted. Zero means it
    was the cheapest every time; 15 means it typically sat 15% above the
    leader. `gap_to_top{k}_pct` is the same against the top-k mean, which is
    the more forgiving benchmark and the one a "we price to market" claim is
    usually about.
    """
    q = _prepare(quotes, period)
    if q.empty:
        return pd.DataFrame()
    group = ["risk_id", "period"] + (["channel"] if by_channel else [])
    asked = q.groupby(group + ["brand"], observed=True)["quoted"].any().reset_index()

    priced = q[q["quoted"] & q["premium"].notna()]
    if not by_channel:
        priced = collapse_to_brand(priced, premium_col="premium",
                                   group_cols=("risk_id", "period"))
    priced = priced.copy()
    priced["rank"] = priced.groupby(group, observed=True)["premium"].rank(method="min")
    best = priced.groupby(group, observed=True)["premium"].transform("min")
    topk_mean = priced.groupby(group, observed=True)["premium"].transform(
        lambda s: np.sort(s.to_numpy())[:k].mean()
    )
    priced["gap_to_cheapest_pct"] = (priced["premium"] / best - 1.0) * 100.0
    priced[f"gap_to_top{k}_pct"] = (priced["premium"] / topk_mean - 1.0) * 100.0
    priced["is_cheapest"] = priced["rank"] == 1
    priced[f"in_top{k}"] = priced["rank"] <= k

    a = asked.groupby("brand", observed=True)["quoted"].agg(n_asked="size", n_quoted="sum")
    p = priced.groupby("brand", observed=True).agg(
        n_cheapest=("is_cheapest", "sum"),
        **{f"n_in_top{k}": (f"in_top{k}", "sum")},
        median_rank=("rank", "median"),
        median_premium=("premium", "median"),
        gap_to_cheapest_pct=("gap_to_cheapest_pct", "median"),
        **{f"gap_to_top{k}_pct": (f"gap_to_top{k}_pct", "median")},
    )
    out = a.join(p, how="left").reset_index()
    for c in ("n_cheapest", f"n_in_top{k}"):
        out[c] = out[c].fillna(0).astype(int)
    out["n_quoted"] = out["n_quoted"].astype(int)
    out["quote_rate_pct"] = (out["n_quoted"] / out["n_asked"] * 100.0).round(1)
    out["cheapest_share_pct"] = (out["n_cheapest"] / out["n_asked"] * 100.0).round(1)
    out[f"top{k}_share_pct"] = (out[f"n_in_top{k}"] / out["n_asked"] * 100.0).round(1)
    for c in ("gap_to_cheapest_pct", f"gap_to_top{k}_pct", "median_premium", "median_rank"):
        out[c] = out[c].round(1)
    cols = ["brand", "n_asked", "n_quoted", "quote_rate_pct", "n_cheapest",
            "cheapest_share_pct", f"n_in_top{k}", f"top{k}_share_pct", "median_rank",
            "median_premium", "gap_to_cheapest_pct", f"gap_to_top{k}_pct"]
    return out[cols].sort_values(
        ["cheapest_share_pct", f"top{k}_share_pct", "gap_to_cheapest_pct"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def channel_gap(quotes: pd.DataFrame, *, period: str = "day") -> pd.DataFrame:
    """Per brand, direct price against its cheapest PCW price on the same risk
    and period. Positive means direct is dearer.

    This is the question published material never answers and the manual
    collection plan spends its dearest journeys on. Only risk-periods where the
    brand quoted on both sides count; a brand with no direct channel does not
    appear.
    """
    q = _prepare(quotes, period)
    q = q[q["quoted"] & q["premium"].notna()]
    if q.empty or q["channel"].nunique() < 2:
        return pd.DataFrame(columns=["brand", "n_pairs", "direct_median",
                                     "pcw_median", "direct_over_pcw_pct"])
    direct = q[q["channel"] == "direct"].groupby(["risk_id", "period", "brand"],
                                                  observed=True)["premium"].min()
    pcw = q[q["channel"] != "direct"].groupby(["risk_id", "period", "brand"],
                                               observed=True)["premium"].min()
    pair = pd.concat([direct.rename("direct"), pcw.rename("pcw")], axis=1).dropna()
    if pair.empty:
        return pd.DataFrame(columns=["brand", "n_pairs", "direct_median",
                                     "pcw_median", "direct_over_pcw_pct"])
    pair["gap_pct"] = (pair["direct"] / pair["pcw"] - 1.0) * 100.0
    out = pair.groupby(level="brand", observed=True).agg(
        n_pairs=("gap_pct", "size"),
        direct_median=("direct", "median"),
        pcw_median=("pcw", "median"),
        direct_over_pcw_pct=("gap_pct", "median"),
    ).reset_index()
    return out.round(1).sort_values("direct_over_pcw_pct").reset_index(drop=True)


def spread_summary(market: pd.DataFrame, *, k: int = 5) -> dict:
    """Headline distribution of the top-k spread across risk-periods."""
    m = market[market["cheapest_price"].notna()] if len(market) else market
    if m.empty:
        return {}
    pct = m["spread_pct"].dropna()
    absg = m["spread_abs"].dropna()
    return {
        "n_risk_periods": int(len(m)),
        "n_complete": int(m[f"top{k}_complete"].sum()) if f"top{k}_complete" in m else None,
        "cheapest_mean": round(float(m["cheapest_price"].mean()), 2),
        "cheapest_median": round(float(m["cheapest_price"].median()), 2),
        f"top{k}_mean": round(float(m[f"top{k}_mean"].mean()), 2),
        "spread_abs_median": round(float(absg.median()), 2) if len(absg) else None,
        "spread_pct_p10": round(float(pct.quantile(0.10)), 1) if len(pct) else None,
        "spread_pct_median": round(float(pct.median()), 1) if len(pct) else None,
        "spread_pct_p90": round(float(pct.quantile(0.90)), 1) if len(pct) else None,
        "panel_spread_pct_median": round(float(m["panel_spread_pct"].median()), 1),
        "n_quoting_mean": round(float(m["n_quoting"].mean()), 1),
    }

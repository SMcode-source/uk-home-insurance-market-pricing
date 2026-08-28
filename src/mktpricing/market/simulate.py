"""Market price from per-provider predictions.

The market price is a *derived statistic*, not a model output, and deriving it
correctly is where most of the subtlety sits.

Naively taking the cheapest five predicted premiums is wrong, because it assumes
every provider quotes. They do not -- flood zone 3, non-standard construction,
prior subsidence, unoccupancy and very high sums insured all get declined. A
provider that would have walked away must not be allowed to win the top five.

So: sample the quote decision from the quotability model, price only the
survivors, and repeat. That gives a *distribution* for the market price rather
than a point, which is more honest and lets you report an interval.

Headline metric is the mean of the cheapest five, because that is the aggregator
page-one experience a customer actually sees. The full distribution is carried
alongside, since the median of all quotes and the single cheapest answer
different commercial questions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def cheapest_k(premiums, k: int = 5):
    """Mean of the k cheapest. Fewer than k available -> mean of what there is."""
    p = np.sort(np.asarray(premiums, dtype=float))
    if p.size == 0:
        return float("nan")
    return float(p[: min(k, p.size)].mean())


def collapse_to_brand(
    predictions: pd.DataFrame,
    *,
    premium_col: str = "pred_premium",
    brand_col: str = "brand",
    channel_col: str = "channel",
    group_cols=("risk_id", "week"),
):
    """One row per brand: its cheapest channel.

    Without this a brand quoted on three channels occupies three places in the
    cheapest-5, so "the five cheapest providers" silently becomes "the five
    cheapest quotes, possibly all from two providers". A customer sees each
    brand once, at its best available price, so that is what the market price
    must be built from.

    The winning channel is retained as `best_channel` -- which is useful in its
    own right, since it tells you per brand whether direct or PCW is cheaper,
    the question no amount of published vendor material answers.
    """
    keys = [c for c in group_cols if c in predictions.columns] + [brand_col]
    idx = predictions.groupby(keys, observed=True)[premium_col].idxmin()
    out = predictions.loc[idx].copy()
    if channel_col in out.columns:
        out["best_channel"] = out[channel_col]
    return out.reset_index(drop=True)


def simulate_market(
    predictions: pd.DataFrame,
    *,
    k: int = 5,
    n_sims: int = 400,
    seed: int = 0,
    premium_col: str = "pred_premium",
    prob_col: str = "p_quote",
    brand_col: str = "brand",
    group_cols=("risk_id", "week"),
    include_declines: bool = True,
    by_channel: bool = False,
):
    """Monte Carlo the market price for each risk.

    `predictions` needs one row per (risk, brand) with a predicted premium and a
    quote probability. Set `include_declines=False` to see how much the
    quotability model is actually changing the answer -- if the two agree
    closely, your risks are all mainstream and the two-part model is not earning
    its keep on this basket.
    """
    rng = np.random.default_rng(seed)
    group_cols = list(group_cols)

    if by_channel:
        # Channel-scoped market: "the cheapest five on Compare the Market".
        if "channel" in predictions.columns and "channel" not in group_cols:
            group_cols = group_cols + ["channel"]
    else:
        # Consumer-facing market: each brand once, at its best channel.
        predictions = collapse_to_brand(
            predictions, premium_col=premium_col, brand_col=brand_col,
            group_cols=tuple(group_cols),
        )

    group_cols = [c for c in group_cols if c in predictions.columns]
    rows = []

    for keys, g in predictions.groupby(list(group_cols), observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        prem = g[premium_col].to_numpy(dtype=float)
        brands = g[brand_col].to_numpy()
        p = (
            g[prob_col].to_numpy(dtype=float)
            if include_declines and prob_col in g
            else np.ones(len(g))
        )

        topk_draws = np.empty(n_sims, dtype=float)
        cheapest_draws = np.empty(n_sims, dtype=float)
        n_quoting = np.empty(n_sims, dtype=float)
        winner_counts: dict = {}

        for s in range(n_sims):
            keep = rng.random(len(g)) < p
            if not keep.any():
                topk_draws[s] = cheapest_draws[s] = np.nan
                n_quoting[s] = 0
                continue
            live = prem[keep]
            live_brands = brands[keep]
            order = np.argsort(live)
            topk_draws[s] = cheapest_k(live, k)
            cheapest_draws[s] = float(live[order[0]])
            n_quoting[s] = keep.sum()
            w = live_brands[order[0]]
            winner_counts[w] = winner_counts.get(w, 0) + 1

        rec = dict(zip(group_cols, keys))
        rec.update(
            {
                f"top{k}_mean": float(np.nanmean(topk_draws)),
                f"top{k}_p10": float(np.nanpercentile(topk_draws, 10)),
                f"top{k}_p90": float(np.nanpercentile(topk_draws, 90)),
                "cheapest_mean": float(np.nanmean(cheapest_draws)),
                "n_quoting_mean": float(np.mean(n_quoting)),
                "n_on_panel": int(len(g)),
                "modal_winner": (
                    max(winner_counts, key=winner_counts.get) if winner_counts else None
                ),
                "modal_winner_share": (
                    round(max(winner_counts.values()) / n_sims * 100, 1)
                    if winner_counts else 0.0
                ),
            }
        )
        rows.append(rec)

    return pd.DataFrame(rows)


def top_k_table(predictions: pd.DataFrame, risk_id: str, week=None, *, k: int = 5,
                premium_col="pred_premium", prob_col="p_quote",
                by_channel: bool = False):
    """The cheapest-k list for one risk, as you would present it.

    Expected premium weights by quote probability, which is the honest way to
    rank a provider that is cheap but likely to decline: a 40%-to-quote provider
    at GBP 180 is not the same offer as a certain one at GBP 180.

    So the sort is on `expected_rank_score`, not on raw premium. Sorting on
    premium computes the probability weighting and then throws it away, which
    puts a provider that quotes 0.3% of the time at the top of a list headed
    "the five cheapest" -- and makes this table disagree with the market price
    from `simulate_market()`, which draws quote/decline and only ranks the
    providers that actually quoted. Raw premium is still shown, so a cheap
    provider that rarely quotes is visible rather than hidden; it just does not
    get to claim first place on a price nobody can buy.
    """
    g = predictions[predictions.risk_id == risk_id]
    if week is not None and "week" in g.columns:
        g = g[g.week == week]
    g = g.copy()
    if not by_channel:
        # One entry per brand, or the same insurer occupies several places.
        g = collapse_to_brand(g, premium_col=premium_col)
    if prob_col in g.columns:
        g["expected_rank_score"] = g[premium_col] / g[prob_col].clip(lower=0.01)
    else:
        g["expected_rank_score"] = g[premium_col]

    cols = ["brand", premium_col]
    if "best_channel" in g.columns:
        cols.append("best_channel")
    if prob_col in g.columns:
        cols.append(prob_col)
    cols.append("expected_rank_score")
    return g.sort_values("expected_rank_score")[cols].head(k).reset_index(drop=True)


def common_risks(market: pd.DataFrame, *, week_col: str = "week") -> list:
    """Risk ids present in *every* week of `market`.

    A declared basket -- `Risk.in_basket` -- is a collection decision: these are
    the properties we committed to re-quoting every week. Vendor extracts do not
    carry it and cannot, because which risks form your index is not a fact about
    their file. That leaves stage five with nothing to index, on every real
    dataset.

    The comparable sub-panel is still recoverable, though, because "quoted in
    every week" is exactly the property a fixed basket has. This derives it. It
    is a weaker basket than a declared one -- it was selected after the fact, so
    it is whatever the vendor happened to keep re-quoting rather than a sample
    anyone designed -- and a caller that substitutes it must say which of the
    two it used. It is not a fallback to apply quietly.

    Returns [] when the panel rotates completely, which is the honest answer:
    no index exists for that data.
    """
    if market.empty or week_col not in market.columns:
        return []
    weeks = market[week_col].nunique()
    per_risk = market.groupby("risk_id", observed=True)[week_col].nunique()
    return sorted(per_risk[per_risk == weeks].index.tolist())


def market_index(market: pd.DataFrame, *, basket_risk_ids=None, k: int = 5,
                 week_col: str = "week"):
    """Weekly index from the fixed basket.

    Restricting to a fixed basket is the whole point -- comparing weeks on a
    rotating set of risks confounds price movement with composition change. If
    `basket_risk_ids` is None this will happily compute an index over whatever
    it is given, which is exactly the mistake to avoid on rotating vendor data.
    """
    df = market
    if basket_risk_ids is not None:
        df = df[df.risk_id.isin(set(basket_risk_ids))]
    col = f"top{k}_mean"
    idx = df.groupby(week_col, observed=True)[col].mean().reset_index()
    idx = idx.rename(columns={col: "market_price"})
    base = idx["market_price"].iloc[0] if len(idx) else np.nan
    idx["index_100"] = (idx["market_price"] / base * 100.0).round(2)
    idx["wow_pct"] = (idx["market_price"].pct_change() * 100.0).round(2)
    return idx

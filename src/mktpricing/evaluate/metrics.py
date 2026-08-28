"""Accuracy metrics.

Split into two families, because they answer different business questions and a
model can be good at one while being poor at the other.

**Premium accuracy** -- how close is the predicted price?
    Reported as median APE rather than mean, because rating glitches produce
    genuine large outliers we deliberately do not clean. A mean would let a
    handful of mispricings dominate the headline.

**Ranking accuracy** -- do we pick the right winners?
    Usually the metric that actually matters. A model can sit at 6% MdAPE and
    still order the cheapest five wrongly, which for a top-5 product is the only
    thing anyone notices. `top_k_metrics` is the one to look at if the
    deliverable is a cheapest-N list.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# -- premium accuracy ------------------------------------------------------


def median_ape(y_true_log, y_pred_log) -> float:
    """Median absolute percentage error, on the GBP scale."""
    t = np.exp(np.asarray(y_true_log, dtype=float))
    p = np.exp(np.asarray(y_pred_log, dtype=float))
    return float(np.median(np.abs(p - t) / t) * 100.0)


def mean_ape(y_true_log, y_pred_log) -> float:
    t = np.exp(np.asarray(y_true_log, dtype=float))
    p = np.exp(np.asarray(y_pred_log, dtype=float))
    return float(np.mean(np.abs(p - t) / t) * 100.0)


def rmse_log(y_true_log, y_pred_log) -> float:
    """RMSE in log space -- i.e. RMSLE. Scale-free across the premium range."""
    a = np.asarray(y_true_log, dtype=float)
    b = np.asarray(y_pred_log, dtype=float)
    return float(np.sqrt(np.mean((a - b) ** 2)))


def bias_pct(y_true_log, y_pred_log) -> float:
    """Signed median error. Non-zero means systematic over/under-pricing."""
    t = np.exp(np.asarray(y_true_log, dtype=float))
    p = np.exp(np.asarray(y_pred_log, dtype=float))
    return float(np.median((p - t) / t) * 100.0)


def within_pct(y_true_log, y_pred_log, tol: float = 10.0) -> float:
    """Share of predictions within `tol` percent. Reads well to stakeholders."""
    t = np.exp(np.asarray(y_true_log, dtype=float))
    p = np.exp(np.asarray(y_pred_log, dtype=float))
    return float(np.mean(np.abs(p - t) / t <= tol / 100.0) * 100.0)


def premium_metrics(y_true_log, y_pred_log) -> dict:
    return {
        "mdape": median_ape(y_true_log, y_pred_log),
        "mape": mean_ape(y_true_log, y_pred_log),
        "rmsle": rmse_log(y_true_log, y_pred_log),
        "bias": bias_pct(y_true_log, y_pred_log),
        "within_10pct": within_pct(y_true_log, y_pred_log, 10.0),
    }


# -- ranking accuracy ------------------------------------------------------


def top_k_metrics(df: pd.DataFrame, k: int = 5, *, group_cols=("risk_id", "week"),
                  brand_col: str = "brand", true_col: str = "y_true",
                  pred_col: str = "y_pred") -> dict:
    """How well do we reproduce the cheapest-k list?

    Three separate things, often confused:

      `cheapest_hit`   did we identify the actual cheapest provider?
      `topk_overlap`   mean share of the true top-k our predicted top-k contains
      `topk_price_err` MdAPE on the *mean price of the top k* -- the headline
                       market-price number, which can be accurate even when the
                       membership is wrong, because near-ties barely move it
    """
    hits, overlaps, true_means, pred_means = [], [], [], []
    group_cols = [c for c in group_cols if c in df.columns]

    for _, g in df.groupby(list(group_cols), observed=True):
        if len(g) < 2:
            continue
        kk = min(k, len(g))
        true_sorted = g.sort_values(true_col)
        pred_sorted = g.sort_values(pred_col)

        true_top = list(true_sorted[brand_col].head(kk))
        pred_top = list(pred_sorted[brand_col].head(kk))

        hits.append(1.0 if true_top[0] == pred_top[0] else 0.0)
        overlaps.append(len(set(true_top) & set(pred_top)) / kk)

        # Price of the top-k, evaluated on TRUE premiums for both sets. The
        # question is "how much does picking the wrong five cost you", not "was
        # the model's own arithmetic self-consistent".
        true_means.append(float(np.exp(true_sorted[true_col].head(kk)).mean()))
        pred_means.append(
            float(np.exp(true_sorted.set_index(brand_col)
                         .loc[pred_top, true_col]).mean())
        )

    if not hits:
        return {"cheapest_hit": float("nan"), f"top{k}_overlap": float("nan"),
                f"top{k}_price_err": float("nan"), "n_groups": 0}

    tm = np.array(true_means)
    pm = np.array(pred_means)
    return {
        "cheapest_hit": float(np.mean(hits) * 100.0),
        f"top{k}_overlap": float(np.mean(overlaps) * 100.0),
        f"top{k}_price_err": float(np.median(np.abs(pm - tm) / tm) * 100.0),
        "n_groups": len(hits),
    }


def spearman(a, b) -> float:
    """Rank correlation, no scipy dependency."""
    a = pd.Series(np.asarray(a, dtype=float)).rank()
    b = pd.Series(np.asarray(b, dtype=float)).rank()
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def per_brand_metrics(df: pd.DataFrame, *, brand_col="brand",
                      true_col="y_true", pred_col="y_pred") -> pd.DataFrame:
    """Accuracy broken out by brand.

    Always look at this before the headline. An aggregate MdAPE hides the fact
    that thin-tail brands are far worse than the majors, and it is the tail that
    decides whether "model every provider" is achievable.
    """
    rows = []
    for brand, g in df.groupby(brand_col, observed=True):
        m = premium_metrics(g[true_col], g[pred_col])
        m["brand"] = brand
        m["n"] = len(g)
        rows.append(m)
    cols = ["brand", "n", "mdape", "mape", "rmsle", "bias", "within_10pct"]
    return pd.DataFrame(rows)[cols].sort_values("mdape").reset_index(drop=True)

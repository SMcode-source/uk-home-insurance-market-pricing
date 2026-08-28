"""Run every approach through the same splits and produce a leaderboard.

The comparison is deliberately rigid: every approach sees identical inputs, the
same splits, the same metrics. Nothing is tuned per approach, because a
comparison where one model got hyperparameter attention and the others did not
tells you about the attention, not the models.

Approaches whose library is missing are listed as skipped rather than dropped.
Silent omission reads as "we compared everything" when you did not.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ..features.build import align_columns, design_matrix
from ..models import approaches as _approaches  # noqa: F401  (registers them)
from ..models.base import all_approaches, available_approaches, unavailable_approaches
from . import metrics as M
from .splits import spatial_split, temporal_split


def _fit_predict(cls, train, test, *, include_brand: bool):
    """Fit one approach and return predictions aligned to `test`."""
    Xtr, ytr = design_matrix(train, include_brand=include_brand)
    Xte, yte = design_matrix(test, include_brand=include_brand)
    Xte = align_columns(Xte, Xtr)

    model = cls()
    t0 = time.perf_counter()
    model.fit(Xtr, ytr, groups=train["brand"].to_numpy())
    fit_s = time.perf_counter() - t0

    pred = model.predict(Xte, groups=test["brand"].to_numpy())
    return model, np.asarray(pred, dtype=float), yte, fit_s


def run_comparison(
    df: pd.DataFrame,
    *,
    holdout_weeks: int = 4,
    spatial_frac: float = 0.25,
    k: int = 5,
    include_brand: bool = True,
    only=None,
    verbose: bool = True,
):
    """Evaluate every available approach on both splits.

    Returns (leaderboard, predictions, skipped).
    """
    registry = available_approaches()
    skipped = unavailable_approaches()
    if only:
        # Accept both "--only a b" and "--only a,b"; the comma form silently
        # matched nothing and produced an empty leaderboard, which read as
        # "every approach lost" rather than "you filtered them all out".
        wanted = {
            n.strip() for spec in only for n in str(spec).split(",") if n.strip()
        }
        unknown = wanted - set(all_approaches())
        if unknown:
            raise ValueError(
                f"unknown approach(es): {sorted(unknown)}. "
                f"Available: {sorted(all_approaches())}"
            )
        blocked = wanted & set(skipped)
        registry = {n: c for n, c in registry.items() if n in wanted}
        if not registry:
            raise ValueError(
                f"--only selected nothing runnable. Requested {sorted(wanted)}; "
                + (f"missing libraries for {sorted(blocked)}" if blocked
                   else "none are registered")
            )

    splits = {}
    splits["temporal"] = temporal_split(df, holdout_weeks=holdout_weeks)
    tr, te, held = spatial_split(df, holdout_frac=spatial_frac)
    splits["spatial"] = (tr, te)
    if verbose:
        print(f"  spatial holdout areas: {', '.join(held)}")

    rows, preds = [], []

    for split_name, (train, test) in splits.items():
        if verbose:
            print(f"\n  [{split_name}] train={len(train):,}  test={len(test):,}")
        for name, cls in registry.items():
            try:
                model, pred, ytrue, fit_s = _fit_predict(
                    cls, train, test, include_brand=include_brand
                )
            except Exception as exc:  # a broken approach must not kill the run
                if verbose:
                    print(f"    {name:18} FAILED: {type(exc).__name__}: {exc}")
                rows.append({"split": split_name, "approach": name, "error": str(exc)})
                continue

            frame = pd.DataFrame(
                {
                    "risk_id": test["risk_id"].to_numpy(),
                    "brand": test["brand"].to_numpy(),
                    "week": test["week"].to_numpy(),
                    "channel": test["channel"].astype(str).to_numpy(),
                    "y_true": ytrue,
                    "y_pred": pred,
                    "approach": name,
                    "split": split_name,
                }
            )
            preds.append(frame)

            row = {"split": split_name, "approach": name, "n_test": len(test),
                   "fit_s": round(fit_s, 2)}
            row.update(M.premium_metrics(ytrue, pred))
            row.update(M.top_k_metrics(frame, k=k))
            row["fallback_brands"] = len(getattr(model, "fallback_brands", []))
            rows.append(row)

            if verbose:
                print(
                    f"    {name:18} MdAPE {row['mdape']:6.2f}%   "
                    f"top{k} overlap {row.get(f'top{k}_overlap', float('nan')):5.1f}%   "
                    f"cheapest {row['cheapest_hit']:5.1f}%   ({fit_s:.1f}s)"
                )

    leaderboard = pd.DataFrame(rows)
    predictions = pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()
    return leaderboard, predictions, skipped


def rolling_comparison(
    df: pd.DataFrame,
    *,
    holdout_weeks: int = 3,
    include_brand: bool = True,
    only=None,
    verbose: bool = True,
):
    """Score the same fitted model blind and under weekly refresh.

    `run_comparison` withholds every holdout week at once. That is the right
    test of pure extrapolation and the wrong model of operation: the panel is
    re-collected weekly, so week 9's outturn is in hand before week 10 is
    priced. Reporting only the blind number answers a question nobody asks.

    One point model is fitted once, on the training window, and used for both
    regimes. The only difference is that the rolling pass calls `recalibrate`
    on each holdout week after scoring it, so the level -- and only the level --
    reflects what has actually been observed by then.

    The first holdout week is necessarily identical under both regimes, because
    nothing has been observed yet. That identity is the check that this is not
    quietly scoring on the holdout: if week one ever differs, the information is
    leaking. `run_poc.py` asserts it rather than trusting it.

    Only approaches exposing `recalibrate` take part; for anything else the two
    regimes are the same computation twice.

    Returns (summary, per_brand, per_week, predictions).
    """
    registry = {
        n: c for n, c in available_approaches().items()
        if hasattr(c, "recalibrate")
    }
    if only:
        wanted = {
            n.strip() for spec in only for n in str(spec).split(",") if n.strip()
        }
        registry = {n: c for n, c in registry.items() if n in wanted}
    if not registry:
        if verbose:
            print("  no approach supports recalibration; nothing to compare")
        empty = pd.DataFrame()
        return empty, empty, empty, empty

    train, test = temporal_split(df, holdout_weeks=holdout_weeks)
    Xtr, ytr = design_matrix(train, include_brand=include_brand)
    gtr = train["brand"].to_numpy()
    weeks = sorted(test.week.unique())

    def _prep(frame):
        X, y = design_matrix(frame, include_brand=include_brand)
        return align_columns(X, Xtr), y, frame["brand"].to_numpy()

    preds = []
    for name, cls in registry.items():
        t0 = time.perf_counter()
        model = cls().fit(Xtr, ytr, groups=gtr)

        # Blind first: `recalibrate` mutates the model, so the order is not
        # cosmetic. Scoring blind after rolling would score a model that has
        # already seen the holdout.
        Xte, yte, gte = _prep(test)
        preds.append(pd.DataFrame({
            "approach": name, "regime": "blind",
            "brand": gte, "week": test["week"].to_numpy(),
            "y_true": yte,
            "y_pred": np.asarray(model.predict(Xte, groups=gte), dtype=float),
        }))

        for w in weeks:
            cur = test[test.week == w]
            Xc, yc, gc = _prep(cur)
            preds.append(pd.DataFrame({
                "approach": name, "regime": "rolling",
                "brand": gc, "week": cur["week"].to_numpy(),
                "y_true": yc,
                "y_pred": np.asarray(model.predict(Xc, groups=gc), dtype=float),
            }))
            model.recalibrate(Xc, yc, groups=gc)

        if verbose:
            print(f"    {name:22} fitted once, {len(weeks)} weekly updates "
                  f"({time.perf_counter() - t0:.1f}s)")

    predictions = pd.concat(preds, ignore_index=True)
    predictions["ape"] = (
        np.abs(np.exp(predictions.y_pred) - np.exp(predictions.y_true))
        / np.exp(predictions.y_true) * 100.0
    )
    predictions["pe"] = (
        (np.exp(predictions.y_pred) - np.exp(predictions.y_true))
        / np.exp(predictions.y_true) * 100.0
    )

    def _agg(g):
        return pd.Series({
            "n": len(g),
            "mape": g.ape.mean(),
            "mdape": g.ape.median(),
            "bias": g.pe.median(),
            "var_pe": g.pe.var(ddof=1),
            "within_10pct": (g.ape <= 10).mean() * 100.0,
        })

    keys = ["approach", "regime"]
    summary = predictions.groupby(keys, observed=True).apply(
        _agg, include_groups=False).reset_index()
    per_brand = predictions.groupby(keys + ["brand"], observed=True).apply(
        _agg, include_groups=False).reset_index()
    per_week = predictions.groupby(keys + ["week"], observed=True).apply(
        _agg, include_groups=False).reset_index()
    return summary, per_brand, per_week, predictions


def first_holdout_week_is_identical(per_week: pd.DataFrame, tol: float = 1e-9) -> bool:
    """Did the two regimes agree on the first holdout week?

    They must: nothing has been observed at that point, so there is nothing to
    correct. A difference means the rolling pass saw data it should not have.
    """
    if per_week.empty:
        return True
    first = per_week.week.min()
    row = per_week[per_week.week == first]
    for _, g in row.groupby("approach", observed=True):
        if g.regime.nunique() < 2:
            continue
        if g.mape.max() - g.mape.min() > tol:
            return False
    return True


def format_leaderboard(leaderboard: pd.DataFrame, k: int = 5) -> pd.DataFrame:
    """Tidy view, sorted by the metric that matters for a top-k product."""
    if leaderboard.empty:
        return leaderboard
    cols = [
        "split", "approach", "mdape", "rmsle", "bias", "within_10pct",
        "cheapest_hit", f"top{k}_overlap", f"top{k}_price_err", "fit_s",
    ]
    have = [c for c in cols if c in leaderboard.columns]
    out = leaderboard[leaderboard.get("error").isna()] if "error" in leaderboard else leaderboard
    out = out[have].copy()
    for c in out.columns:
        if out[c].dtype.kind == "f":
            out[c] = out[c].round(2)
    return out.sort_values(["split", "mdape"]).reset_index(drop=True)


def additivity_gap(leaderboard: pd.DataFrame,
                   additive="ebm_per_brand", flexible="gbm_per_brand") -> pd.DataFrame:
    """The EBM-vs-GBM gap, per split.

    Not a horse race. Sign and size both carry meaning:

      gap ~ 0    a clean multiplicative rating table. The interpretable model
                 costs you nothing -- use the EBM and keep the curves.

      gap > 0    the boosted model finds real structure the EBM cannot
                 represent: caps, collars, three-way terms, an optimisation
                 layer. The readable curves are then a simplification, and you
                 should describe them as one.

      gap < 0    the ADDITIVE model wins. Expect this on the spatial split:
                 unrestricted boosting overfits location-specific interactions
                 that do not transfer to unseen geography, while the additive
                 structure extrapolates. If you are pricing postcodes you have
                 never quoted -- which is the whole point of modelling rather
                 than tabulating -- this is the split that should decide your
                 production model, not the temporal one.
    """
    if leaderboard.empty or "approach" not in leaderboard:
        return pd.DataFrame()
    rows = []
    for split, g in leaderboard.groupby("split"):
        a = g[g.approach == additive]
        f = g[g.approach == flexible]
        if a.empty or f.empty:
            continue
        rows.append(
            {
                "split": split,
                f"{additive}_mdape": round(float(a.mdape.iloc[0]), 2),
                f"{flexible}_mdape": round(float(f.mdape.iloc[0]), 2),
                "gap_pct_points": round(
                    float(a.mdape.iloc[0]) - float(f.mdape.iloc[0]), 2
                ),
            }
        )
    return pd.DataFrame(rows)

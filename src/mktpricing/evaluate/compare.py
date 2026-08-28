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

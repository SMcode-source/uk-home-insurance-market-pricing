"""Train/test splits.

**Never random-split this data.** The same risk is quoted repeatedly across
weeks, so a random split puts near-identical rows on both sides and reports an
accuracy you will never see in production. Two splits, answering two different
questions:

`temporal`  Train on weeks 1..k, test on k+1.. -- "can we predict next week?"
            This is the operational question, and it is the one the weekly
            pipeline actually faces.

`spatial`   Hold out entire postcode areas -- "can we price geography we have
            never quoted?" This is the interpolation question, it is what makes
            the model worth more than a lookup table, and it is always the
            weaker number. If the two are close, the model is memorising
            location rather than learning risk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def temporal_split(df: pd.DataFrame, *, holdout_weeks: int = 4, week_col: str = "week"):
    """Last `holdout_weeks` weeks become the test set."""
    if week_col not in df.columns:
        raise KeyError(f"{week_col!r} not in frame; temporal split needs a week index")
    weeks = np.sort(df[week_col].unique())
    if len(weeks) <= holdout_weeks:
        raise ValueError(
            f"only {len(weeks)} weeks available, cannot hold out {holdout_weeks}"
        )
    cut = weeks[-holdout_weeks]
    train = df[df[week_col] < cut]
    test = df[df[week_col] >= cut]
    return train, test


def spatial_split(df: pd.DataFrame, *, holdout_frac: float = 0.25,
                  area_col: str = "outcode", seed: int = 0):
    """Hold out whole areas, so no test postcode appears in training."""
    if area_col not in df.columns:
        raise KeyError(f"{area_col!r} not in frame; spatial split needs an area column")
    areas = np.sort(df[area_col].unique())
    rng = np.random.default_rng(seed)
    n_hold = max(1, int(round(len(areas) * holdout_frac)))
    held = set(rng.choice(areas, size=n_hold, replace=False).tolist())
    train = df[~df[area_col].isin(held)]
    test = df[df[area_col].isin(held)]
    return train, test, sorted(held)


def rolling_windows(df: pd.DataFrame, *, window: int = 13, step: int = 1,
                    week_col: str = "week"):
    """Yield (train, test) for a rolling-origin backtest.

    Closer to how the weekly job behaves than a single split: refit on a moving
    window, predict the next week, repeat. Gives a distribution of accuracy
    rather than one number that might be a lucky week.
    """
    weeks = np.sort(df[week_col].unique())
    for i in range(window, len(weeks), step):
        train_weeks = weeks[max(0, i - window):i]
        test_week = weeks[i]
        yield (
            df[df[week_col].isin(train_weeks)],
            df[df[week_col] == test_week],
            int(test_week),
        )

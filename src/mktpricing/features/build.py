"""Feature assembly.

Two decisions here carry most of the modelling weight.

**Target is log(premium).** UK household rating is multiplicative -- base rate
times relativity times relativity. Taking logs turns that into an additive
structure, which is exactly what a GAM/EBM represents natively and what a GLM
with a log link assumes. It also stabilises variance across the premium range.
Everything downstream predicts log-premium; convert back only at the edges, and
remember exp(mean of logs) is a geometric mean, not an arithmetic one.

**Geography enters as risk features, never as raw postcode.** A postcode
categorical cannot generalise to postcodes you never quoted, which defeats the
point. Flood band, crime, subsidence, deprivation and average property value
give the model a readable shape function per driver and let it price anywhere in
the UK.

This module expects `flood_band`, `crime_index`, `subsidence_band` and
`area_avg_value` to arrive already attached to the risk. The synthetic generator
supplies them directly; for real postcodes, `features/geo.py` resolves them from
published data and `geo.check_ready_for_modelling()` is the gate to call before
training. Do not fill a missing geo feature with a default to get past that gate
-- an invented flood band is a confident wrong prediction, and nothing
downstream can tell it apart from a real one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Categorical features. Order matters only for stable one-hot column names.
CATEGORICAL = [
    "policy_type",
    "building_type",
    "construction",
    "occupancy",
    "channel",
]

# Numeric features fed to every approach.
NUMERIC = [
    "log_sum_insured",
    "voluntary_excess",
    "log_excess",
    "property_age",
    "bedrooms",
    "claims_last_5y",
    "flood_band",
    "crime_index",
    "subsidence_band",
    "log_area_value",
    "flood_history",
    "subsidence_history",
    "week",
]

# Extra geo features that `features/geo.py` can supply but the synthetic
# generator does not. Included automatically when present, so enriching real
# postcodes strengthens the model without a code change -- and their absence
# never breaks the synthetic pipeline.
OPTIONAL_NUMERIC = [
    "flood_high_share",
    "imd_decile",
]

# Supplied by `features/geo.py` from the postcode. Absent from every raw source
# -- vendor extract, manual session -- so their absence is checked for
# explicitly rather than surfacing as a KeyError five columns into the build.
GEO_COLUMNS = ["flood_band", "crime_index", "subsidence_band", "area_avg_value"]

TARGET = "log_premium"


def combined_sum_insured(df: pd.DataFrame) -> pd.Series:
    """Buildings plus weighted contents.

    Contents is weighted up because contents cover is more claim-prone per pound
    insured; the 1.4 is a modelling convenience, not an actuarial constant. If
    you have real exposure data, replace it.
    """
    b = df["buildings_sum_insured"].fillna(0.0)
    c = df["contents_sum_insured"].fillna(0.0)
    return (b + 1.4 * c).clip(lower=10_000.0)


def build_matrix(
    quotes: pd.DataFrame,
    risks: pd.DataFrame,
    *,
    quoted_only: bool = True,
    reference_year: int = 2026,
) -> pd.DataFrame:
    """Join quotes to risks and derive the model matrix.

    `quoted_only=True` gives the premium model its training set. Pass False to
    build the quotability model's set, where declines are the positive signal
    rather than rows to drop.
    """
    df = quotes.merge(risks, on="risk_id", how="left", validate="many_to_one")

    missing_geo = [c for c in GEO_COLUMNS if c not in df.columns]
    if missing_geo:
        raise KeyError(
            f"risks are missing geo features {missing_geo}. Vendor extracts and "
            "hand-collected sessions carry a postcode but not the risk features "
            "derived from it -- run them through features.geo.GeoEnricher first, "
            "then features.geo.check_ready_for_modelling(). Do not fill these "
            "with defaults to get past this: an invented flood band is a "
            "confident wrong prediction nothing downstream can detect."
        )

    if quoted_only:
        df = df[df["quoted"]].copy()
        if df["premium"].isna().any():
            raise ValueError("quoted rows with null premium -- check ingestion")
        df[TARGET] = np.log(df["premium"].astype(float))
    else:
        df = df.copy()

    si = combined_sum_insured(df)
    df["log_sum_insured"] = np.log(si / 250_000.0)
    df["log_excess"] = np.log1p(df["voluntary_excess"].astype(float) / 250.0)
    df["property_age"] = (reference_year - df["year_built"].astype(int)).clip(lower=0)
    df["flood_history"] = df["flood_history"].astype(int)
    df["subsidence_history"] = df["subsidence_history"].astype(int)
    df["log_area_value"] = np.log(df["area_avg_value"].astype(float) / 300_000.0)

    if "week" not in df.columns:
        # Week is a feature, not an index. Its main effect absorbs level drift so
        # the risk-factor shapes stay stable across refits -- and that effect IS
        # the provider's price index over time.
        #
        # Within the training window. A tree has no split beyond the largest
        # week it saw, so every later week reuses the final leaf and forward
        # drift is predicted flat: on the sample run one Churchill risk priced
        # at GBP 136.50 for week 8 and GBP 136.50 for weeks 9, 10 and 11 alike,
        # while its holdout bias grew to -22.6%. See "Known limitations" in
        # docs/DESIGN.md before relying on a multi-week forecast horizon.
        #
        # Derive it from the collection date. Defaulting to 0 here used to look
        # harmless and was not: it collapsed every date into one week, so the
        # temporal split had nothing to hold out, the weekly index was a single
        # point, and drift was invisible to the model. Vendor extracts and
        # manual sessions carry `collected_on` but never `week`, so that was
        # every real data path.
        df["week"] = _weeks_from_dates(df)

    for c in CATEGORICAL:
        df[c] = df[c].astype("category")

    return df


def _weeks_from_dates(df: pd.DataFrame) -> pd.Series:
    """Whole weeks since the earliest collection date, 0-based."""
    if "collected_on" not in df.columns:
        raise KeyError(
            "cannot derive `week`: no `collected_on` column. Every quote needs a "
            "collection date, or temporal splits, drift and the weekly index are "
            "all meaningless."
        )
    d = pd.to_datetime(df["collected_on"], errors="coerce")
    if d.isna().all():
        raise ValueError(
            "cannot derive `week`: no `collected_on` value parsed as a date"
        )
    weeks = ((d - d.min()).dt.days // 7).astype("float")
    if weeks.isna().any():
        # Unparseable dates cannot be placed on the timeline, and guessing a
        # week for them would put a quote in the wrong period of the index.
        raise ValueError(
            f"{int(weeks.isna().sum())} row(s) have an unparseable `collected_on`; "
            "fix or drop them before building features"
        )
    return weeks.astype(int)

    for c in CATEGORICAL:
        df[c] = df[c].astype("category")

    return df


def feature_columns(include_brand: bool = False, df: pd.DataFrame | None = None) -> list:
    """Feature list. Pass `df` to pick up whichever optional geo columns it has."""
    cols = list(NUMERIC)
    if df is not None:
        cols += [c for c in OPTIONAL_NUMERIC if c in df.columns]
    cols += list(CATEGORICAL)
    if include_brand:
        cols = cols + ["brand"]
    return cols


def design_matrix(df: pd.DataFrame, *, include_brand: bool = False):
    """Return (X, y) with categoricals one-hot encoded.

    One-hot rather than ordinal because several approaches (GLM, linear
    baselines) would otherwise read a false ordering into building type.
    Tree-based approaches are indifferent, so one encoding serves all of them and
    keeps the comparison honest -- every approach sees identical inputs.
    """
    cols = feature_columns(include_brand=include_brand, df=df)
    X = df[cols].copy()
    cat_cols = [c for c in cols if c in CATEGORICAL or c == "brand"]
    X = pd.get_dummies(X, columns=cat_cols, drop_first=False, dtype=float)
    X = X.reindex(sorted(X.columns), axis=1)
    y = df[TARGET].to_numpy(dtype=float) if TARGET in df.columns else None
    return X, y


def align_columns(X: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Make X match `reference`'s columns.

    Needed whenever a holdout split contains a category the training split did
    not -- a spatial holdout on an unseen area, for instance. Missing columns
    become zero rather than raising, which is the correct behaviour for a
    one-hot absent level.
    """
    return X.reindex(columns=reference.columns, fill_value=0.0)

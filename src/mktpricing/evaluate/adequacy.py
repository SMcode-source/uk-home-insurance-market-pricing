"""What the data can support, decided before any approach is fitted.

The comparison harness will fit and rank every registered approach on whatever
it is handed. That is the right behaviour on a vendor extract with hundreds of
risks and the wrong behaviour on the data this project can actually collect
without a licence: one real person quoting one real property, weekly. On that
data every risk feature is a constant, so a rating model has nothing to learn
-- it fits the mean and ranks the leaderboard by noise -- and a spatial split
has one postcode area to hold out, which empties the training set.

Neither failure crashes. Both produce a plausible-looking leaderboard. So the
decision about which approaches the data can carry is made here, once, from
the data itself, and printed with its reasons. It is never silent: an approach
the data cannot support is *excluded with a reason*, exactly as one whose
library is missing is *skipped with a reason*.

Three tiers, by what varies:

``level_only``      No risk-level feature varies across the risks present. The
                    estimable quantity is a price level per brand (and channel)
                    over time. Baselines and the last-level carry-forward are
                    eligible; rating models are not.

``thin``            Risk features vary, but over too few distinct risks for a
                    per-brand rating fit to mean anything. Everything is
                    eligible, with a warning that shape functions will be noise
                    and every brand will fall back to the pooled model.

``cross_section``   Enough distinct risks to fit and compare rating models.
                    The full lineup runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..features.build import CATEGORICAL, NUMERIC, OPTIONAL_NUMERIC
from ..models import approaches as _approaches  # noqa: F401  (registers)
from ..models.base import all_approaches

#: Distinct risks below which a rating fit is reported as `thin`. Chosen so a
#: hand-collected panel of a handful of variants (excess ladder, cover type)
#: is still labelled honestly rather than promoted to a cross-section.
THIN_RISKS = 30

#: Approaches that learn a price *level* and nothing about the risk. These are
#: what remains estimable when every risk feature is a constant.
LEVEL_APPROACHES = ("global_geomean", "brand_geomean", "brand_last_level")

# Risk-level features: everything the models see except time and channel,
# which vary within a single risk and so say nothing about risk coverage.
_RISK_FEATURES = tuple(
    c for c in list(NUMERIC) + list(OPTIONAL_NUMERIC) + list(CATEGORICAL)
    if c not in ("week", "channel")
)


@dataclass
class Adequacy:
    """What the model matrix contains, and what that permits."""

    n_rows: int
    n_risks: int
    n_brands: int
    n_channels: int
    n_weeks: int
    n_areas: int
    holdout_weeks: int
    varying_features: list = field(default_factory=list)
    constant_features: list = field(default_factory=list)
    rows_per_brand: dict = field(default_factory=dict)
    tier: str = "cross_section"
    temporal_split_possible: bool = True
    spatial_split_possible: bool = True
    #: approach name -> why the data cannot support it
    excluded: dict = field(default_factory=dict)
    eligible: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def restrict(self, only):
        """Apply the exclusion to an ``only`` request, or to the full lineup.

        An explicit request wins: someone asking for a specific approach on
        thin data is running an experiment, not a leaderboard. The exclusions
        are still printed so the result is read with them in mind.
        """
        if only:
            return only
        return list(self.eligible)

    def format(self) -> str:
        lines = [
            f"  rows {self.n_rows:,}   risks {self.n_risks:,}   brands {self.n_brands}"
            f"   channels {self.n_channels}   weeks {self.n_weeks}"
            f"   postcode areas {self.n_areas}",
            f"  tier: {self.tier}",
        ]
        if self.constant_features:
            lines.append(
                f"  constant across every risk: {', '.join(self.constant_features)}"
            )
        for n in self.notes:
            lines.append(f"  {n}")
        if self.excluded:
            lines.append("  excluded -- the data cannot support these:")
            for name, why in self.excluded.items():
                lines.append(f"    {name:20} {why}")
        lines.append(f"  eligible: {', '.join(self.eligible)}")
        return "\n".join(lines)


def assess(df: pd.DataFrame, *, holdout_weeks: int = 2,
           min_rows_per_brand: int = 300) -> Adequacy:
    """Inspect a model matrix from ``features.build.build_matrix``.

    ``min_rows_per_brand`` should match ``PerBrand.min_rows``; it decides
    whether any brand would get its own model or all of them fall back to
    pooled.
    """
    risks = df.drop_duplicates("risk_id")
    features = [c for c in _RISK_FEATURES if c in df.columns]
    varying = [c for c in features if risks[c].nunique(dropna=False) > 1]
    constant = [c for c in features if c not in varying]

    n_weeks = int(df["week"].nunique()) if "week" in df.columns else 1
    n_areas = int(df["outcode"].nunique()) if "outcode" in df.columns else 0
    rows_per_brand = df.groupby("brand", observed=True).size().to_dict()

    a = Adequacy(
        n_rows=len(df),
        n_risks=int(risks.shape[0]),
        n_brands=int(df["brand"].nunique()),
        n_channels=int(df["channel"].nunique()) if "channel" in df.columns else 1,
        n_weeks=n_weeks,
        n_areas=n_areas,
        holdout_weeks=holdout_weeks,
        varying_features=varying,
        constant_features=constant,
        rows_per_brand={str(k): int(v) for k, v in rows_per_brand.items()},
    )

    a.temporal_split_possible = n_weeks > holdout_weeks
    if not a.temporal_split_possible:
        a.notes.append(
            f"only {n_weeks} week(s) of data; cannot hold out {holdout_weeks}. "
            "Nothing can be scored out of sample until more weeks are collected."
        )

    # Two areas is the floor: `spatial_split` holds out at least one, and with
    # one area that is the whole training set.
    a.spatial_split_possible = n_areas >= 2
    if not a.spatial_split_possible:
        a.notes.append(
            f"{n_areas} postcode area(s): no spatial split. The interpolation "
            "question cannot be asked of this data."
        )

    registry = all_approaches()
    if not varying:
        a.tier = "level_only"
        why = (
            "no risk feature varies across the risks present; a rating model "
            "would fit the mean and rank by noise"
        )
        for name in registry:
            if name not in LEVEL_APPROACHES:
                a.excluded[name] = why
        a.notes.append(
            "every risk feature is constant, so the estimable quantity is a price "
            "level per brand and channel over time -- not a rating structure"
        )
    elif a.n_risks < THIN_RISKS:
        a.tier = "thin"
        a.notes.append(
            f"{a.n_risks} distinct risk(s) is enough to fit a rating model and not "
            "enough to trust one: shape functions will be noise, and per-brand "
            "accuracy is a statement about these risks only"
        )

    thick = [b for b, n in rows_per_brand.items() if n >= min_rows_per_brand]
    if rows_per_brand and not thick:
        a.notes.append(
            f"no brand has {min_rows_per_brand} rows; every per-brand approach "
            "would fall back to its pooled model for every brand"
        )

    a.eligible = [n for n in registry if n not in a.excluded]
    return a

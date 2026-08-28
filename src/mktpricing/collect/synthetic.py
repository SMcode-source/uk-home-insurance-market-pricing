"""Synthetic market generator.

Exists so the whole pipeline -- features, every model, the accuracy harness,
top-5 simulation -- runs end to end before any real data arrives, and so model
accuracy can be measured against a KNOWN ground truth. On real data you never
learn whether an approach recovered the rating structure or merely fitted noise;
here you do.

The generator deliberately reproduces the awkward parts of real UK household
rating, because an approach that only works on smooth data will mislead you:

  multiplicative      base rate x relativity x relativity, so log(premium) is
                      additive -- the structure EBMs and GLMs represent natively
  sharp thresholds    sum-insured and excess bands step rather than glide
  minimum premium     a point mass; many cheap risks pile at exactly the floor
  capping             some brands cap their own worst relativities
  3-way interaction   flood x excess x building type, beyond EBM's pairwise reach
  declines            flood/subsidence/unoccupied/high-SI get refused, per brand
  tactical layer      a per-brand, per-week discount unrelated to risk
  rating errors       rare, large mispricings -- the signal we do not want cleaned
  channel effect      direct vs PCW differs by brand, in both directions
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

_BUILDING_TYPES = ["detached", "semi_detached", "terraced", "end_terrace", "flat", "bungalow"]
_POLICY_TYPES = ["buildings", "contents", "combined"]
_CONSTRUCTIONS = ["standard", "standard", "standard", "non_standard_walls", "non_standard_roof", "listed"]
_OCCUPANCIES = ["owner_occupied", "owner_occupied", "owner_occupied", "let", "second_home", "unoccupied"]

# Outcode -> (flood_band 0-3, crime_index 0-1, subsidence_band 0-3, avg_value)
_AREAS = {
    "BS1": (2, 0.72, 1, 320_000), "BS9": (0, 0.21, 1, 520_000),
    "M1": (1, 0.81, 0, 240_000), "M20": (0, 0.34, 0, 430_000),
    "SW1A": (1, 0.66, 3, 1_400_000), "SE15": (1, 0.74, 3, 560_000),
    "LS1": (2, 0.69, 0, 210_000), "LS17": (0, 0.24, 0, 480_000),
    "YO1": (3, 0.42, 0, 330_000), "TN34": (1, 0.55, 2, 290_000),
    "EX34": (3, 0.31, 1, 310_000), "CA11": (2, 0.19, 0, 260_000),
    "B15": (0, 0.58, 1, 350_000), "NE1": (1, 0.77, 0, 195_000),
    "CF10": (2, 0.63, 1, 265_000), "EH1": (0, 0.47, 0, 470_000),
    "PL1": (2, 0.61, 1, 225_000), "NR1": (2, 0.44, 0, 285_000),
    "GL50": (2, 0.38, 2, 395_000), "HU1": (3, 0.71, 0, 165_000),
}

_BUILDING_REL = {
    "detached": 0.13, "bungalow": 0.09, "semi_detached": 0.0,
    "end_terrace": 0.02, "terraced": -0.03, "flat": -0.18,
}
_CONSTRUCTION_REL = {
    "standard": 0.0, "non_standard_walls": 0.22,
    "non_standard_roof": 0.19, "listed": 0.35,
}
_OCCUPANCY_REL = {
    "owner_occupied": 0.0, "let": 0.16,
    "second_home": 0.21, "unoccupied": 0.48,
}
_POLICY_REL = {"buildings": 0.0, "contents": -0.34, "combined": 0.12}

_PCW_ONLY = {"Esure", "Ageas"}
_DIRECT_ONLY = {"NFU Mutual", "Homeprotect"}


@dataclass
class BrandRating:
    """One insurer rating engine. Shapes differ between brands, not just levels."""

    name: str
    base: float
    flood_slope: float
    si_exponent: float
    excess_slope: float
    crime_slope: float
    age_slope: float
    min_premium: float
    decline_flood_band: int
    decline_unoccupied: bool
    cap_relativity: float | None
    channel_effect: dict
    tactical_sd: float
    error_rate: float
    interaction_3way: float = 0.0
    quote_rate: float = 0.97


_SPECS = [
    # name, base, flood, si_exp, excess, crime, age, min_prem, decl_band, decl_unocc, cap
    ("Aviva", 195, 0.34, 0.62, -0.22, 0.20, 0.13, 120, 3, True, None),
    ("AXA", 188, 0.41, 0.58, -0.19, 0.26, 0.11, 115, 3, True, 1.9),
    ("Direct Line", 221, 0.22, 0.66, -0.26, 0.15, 0.16, 145, 4, False, None),
    ("Churchill", 206, 0.25, 0.64, -0.24, 0.17, 0.15, 135, 4, False, None),
    ("Admiral", 173, 0.49, 0.55, -0.17, 0.31, 0.09, 105, 2, True, 1.7),
    ("LV=", 199, 0.30, 0.61, -0.23, 0.19, 0.14, 128, 3, True, None),
    ("Policy Expert", 164, 0.55, 0.52, -0.15, 0.35, 0.08, 95, 2, True, 1.6),
    ("Ageas", 181, 0.44, 0.57, -0.20, 0.28, 0.12, 110, 3, True, None),
    ("Esure", 170, 0.51, 0.54, -0.16, 0.33, 0.10, 100, 2, True, 1.8),
    ("Saga", 213, 0.28, 0.63, -0.25, 0.16, 0.18, 140, 3, True, None),
    ("Homeprotect", 268, 0.12, 0.70, -0.30, 0.12, 0.20, 180, 9, False, None),
    ("NFU Mutual", 241, 0.19, 0.68, -0.28, 0.13, 0.17, 160, 4, False, None),
]


def default_brands(rng: np.random.Generator) -> list:
    """A roster spanning the behaviours the models must cope with."""
    brands = []
    for (nm, base, fl, si, ex, cr, ag, mp, db, du, cap) in _SPECS:
        brands.append(
            BrandRating(
                name=nm,
                base=base,
                flood_slope=fl,
                si_exponent=si,
                excess_slope=ex,
                crime_slope=cr,
                age_slope=ag,
                min_premium=mp,
                decline_flood_band=db,
                decline_unoccupied=du,
                cap_relativity=cap,
                channel_effect={
                    "direct": float(rng.normal(0.0, 0.06)),
                    "pcw_ctm": float(rng.normal(-0.03, 0.04)),
                    "pcw_msm": float(rng.normal(-0.03, 0.04)),
                    "pcw_confused": float(rng.normal(-0.02, 0.04)),
                    "pcw_gocompare": float(rng.normal(-0.02, 0.04)),
                },
                tactical_sd=float(rng.uniform(0.02, 0.09)),
                error_rate=float(rng.uniform(0.000, 0.004)),
                interaction_3way=float(rng.uniform(0.0, 0.18)),
                quote_rate=float(rng.uniform(0.93, 0.995)),
            )
        )
    return brands


# Letters a real UK inward code can use: A-Z without C, I, K, M, O and V.
_UNIT_LETTERS = "ABDEFGHJLNPQRSTUWXYZ"


def make_risks(n: int, rng: np.random.Generator, n_basket: int = 40) -> pd.DataFrame:
    """Risk population. The first `n_basket` form the fixed index basket."""
    outcodes = list(_AREAS)
    rows = []
    for i in range(n):
        oc = outcodes[int(rng.integers(len(outcodes)))]
        flood, crime, subs, avg_val = _AREAS[oc]
        ptype = _POLICY_TYPES[int(rng.integers(len(_POLICY_TYPES)))]
        btype = _BUILDING_TYPES[int(rng.integers(len(_BUILDING_TYPES)))]
        beds = int(np.clip(rng.poisson(3) + 1, 1, 8))
        value = float(avg_val * rng.lognormal(0.0, 0.28))
        # The inward code never uses C, I, K, M, O or V. Drawing from the full
        # alphabet produced postcodes that look right and fail validation, so
        # synthetic risks would not survive features.geo parsing.
        suffix = "{}{}{}".format(
            int(rng.integers(1, 9)),
            _UNIT_LETTERS[int(rng.integers(len(_UNIT_LETTERS)))],
            _UNIT_LETTERS[int(rng.integers(len(_UNIT_LETTERS)))],
        )
        rows.append(
            dict(
                risk_id="R{:05d}".format(i),
                postcode="{} {}".format(oc, suffix),
                outcode=oc,
                policy_type=ptype,
                building_type=btype,
                construction=_CONSTRUCTIONS[int(rng.integers(len(_CONSTRUCTIONS)))],
                occupancy=_OCCUPANCIES[int(rng.integers(len(_OCCUPANCIES)))],
                year_built=int(rng.integers(1850, 2024)),
                bedrooms=beds,
                buildings_sum_insured=(
                    float(round(value * rng.uniform(0.55, 0.85), -3))
                    if ptype in ("buildings", "combined")
                    else None
                ),
                contents_sum_insured=(
                    float(round(beds * rng.uniform(9_000, 18_000), -3))
                    if ptype in ("contents", "combined")
                    else None
                ),
                voluntary_excess=float(rng.choice([0, 100, 250, 500, 1000])),
                claims_last_5y=int(rng.binomial(2, 0.09)),
                flood_history=bool(rng.random() < 0.04),
                subsidence_history=bool(rng.random() < 0.03),
                flood_band=flood,
                crime_index=crime,
                subsidence_band=subs,
                area_avg_value=float(avg_val),
                in_basket=bool(i < n_basket),
            )
        )
    return pd.DataFrame(rows)


def _num(value) -> float:
    """None/NaN -> 0.0.

    `value or 0.0` is NOT enough: pandas stores a missing sum insured as NaN,
    and NaN is truthy, so it survives the `or` and poisons the whole log-premium
    calculation into NaN. Contents-only and buildings-only policies both hit
    this, which is most of the population.
    """
    if value is None:
        return 0.0
    v = float(value)
    return 0.0 if math.isnan(v) else v


def _log_premium(b, r, channel: str, week: int, rng, tactical: float) -> float:
    """The rating engine, in log space. Additive here == multiplicative in GBP."""
    si = _num(r.buildings_sum_insured) + _num(r.contents_sum_insured) * 1.4
    si = max(si, 10_000.0)

    lp = math.log(b.base)
    lp += b.si_exponent * math.log(si / 250_000.0)
    lp += b.flood_slope * (r.flood_band ** 1.35) / 2.0
    lp += b.crime_slope * r.crime_index
    lp += b.age_slope * max(0.0, (1960 - r.year_built) / 100.0)
    lp += b.excess_slope * math.log1p(r.voluntary_excess / 250.0)

    lp += 0.11 * r.subsidence_band
    lp += 0.24 * r.claims_last_5y
    lp += 0.31 if r.flood_history else 0.0
    lp += 0.42 if r.subsidence_history else 0.0

    lp += _BUILDING_REL[r.building_type]
    lp += _CONSTRUCTION_REL[r.construction]
    lp += _OCCUPANCY_REL[r.occupancy]
    lp += _POLICY_REL[r.policy_type]

    # Three-way term: flood x excess x detached. Beyond an additive+pairwise fit,
    # so the EBM-vs-GBM gap on these rows measures non-additive structure.
    if r.flood_band >= 2 and r.voluntary_excess >= 500 and r.building_type == "detached":
        lp -= b.interaction_3way

    lp += b.channel_effect.get(channel, 0.0)
    lp += tactical                        # per brand per week, unrelated to risk
    lp += 0.004 * week                    # slow market drift
    lp += float(rng.normal(0.0, 0.012))   # residual jitter

    if b.cap_relativity is not None:
        lp = min(lp, math.log(b.base) + math.log(b.cap_relativity))

    return lp


def _declines(b, r, rng) -> bool:
    """Whether this brand refuses the risk outright."""
    if r.flood_band >= b.decline_flood_band:
        return True
    if b.decline_unoccupied and r.occupancy == "unoccupied":
        return True
    if r.subsidence_history and rng.random() < 0.65:
        return True
    if r.flood_history and rng.random() < 0.55:
        return True
    if _num(r.buildings_sum_insured) > 900_000 and rng.random() < 0.7:
        return True
    return bool(rng.random() > b.quote_rate)


def generate(
    n_risks: int = 900,
    n_weeks: int = 26,
    channels: Iterable = ("pcw_ctm", "pcw_msm", "direct"),
    seed: int = 11,
    start: _dt.date | None = None,
    rotating_per_week: int = 160,
):
    """Return (risks, quotes, truth).

    `truth` holds the noiseless log-premium each brand would charge, so accuracy
    can be measured against the real rating structure rather than a proxy.
    """
    rng = np.random.default_rng(seed)
    if start is None:
        start = _dt.date.today() - _dt.timedelta(weeks=n_weeks)
    brands = default_brands(rng)
    risks = make_risks(n_risks, rng)
    channels = list(channels)

    # Tactical layer: a per-brand random walk, so discounting persists and drifts
    # rather than resetting each week. This is the layer we later try to recover
    # as a residual.
    tactical = {b.name: 0.0 for b in brands}

    quote_rows, truth_rows = [], []
    basket = risks[risks.in_basket]
    non_basket = risks[~risks.in_basket]

    for wk in range(n_weeks):
        day = start + _dt.timedelta(weeks=wk)
        for b in brands:
            tactical[b.name] = float(
                np.clip(tactical[b.name] + rng.normal(0, b.tactical_sd), -0.35, 0.35)
            )

        # Basket every week; the remainder rotates, mirroring vendor panels.
        rotating = non_basket.sample(
            n=min(rotating_per_week, len(non_basket)),
            random_state=int(rng.integers(1 << 30)),
        )
        live = pd.concat([basket, rotating])

        for r in live.itertuples(index=False):
            for ch in channels:
                for b in brands:
                    if ch == "direct" and b.name in _PCW_ONLY:
                        continue
                    if ch != "direct" and b.name in _DIRECT_ONLY:
                        continue

                    lp = _log_premium(b, r, ch, wk, rng, tactical[b.name])
                    truth_rows.append(
                        dict(
                            risk_id=r.risk_id, brand=b.name, channel=ch,
                            week=wk, true_log_premium=lp,
                        )
                    )

                    if _declines(b, r, rng):
                        quote_rows.append(
                            dict(
                                risk_id=r.risk_id, brand=b.name, channel=ch,
                                collected_on=day, week=wk, quoted=False,
                                premium=None, source="synthetic",
                            )
                        )
                        continue

                    prem = math.exp(lp)
                    if rng.random() < b.error_rate:
                        # Rating glitch. Deliberately NOT cleaned -- this is the
                        # mispricing signal the whole exercise wants to detect.
                        prem *= float(rng.choice([0.42, 0.55, 2.1, 3.4]))
                    prem = max(prem, b.min_premium)  # point mass at the floor

                    quote_rows.append(
                        dict(
                            risk_id=r.risk_id, brand=b.name, channel=ch,
                            collected_on=day, week=wk, quoted=True,
                            premium=round(prem, 2), source="synthetic",
                        )
                    )

    quotes = pd.DataFrame(quote_rows)
    bad = quotes[quotes.quoted & ~np.isfinite(quotes.premium.astype(float))]
    if len(bad):
        raise AssertionError(
            f"{len(bad)} quoted rows have non-finite premiums -- generator bug"
        )
    return risks, quotes, pd.DataFrame(truth_rows)

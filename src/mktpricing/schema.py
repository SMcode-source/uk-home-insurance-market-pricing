"""Canonical quote record.

One row per (risk, brand, channel, collection date). Everything downstream --
manual collection, vendor extracts, feature building, modelling -- speaks this
schema, so a licensed CI/Defaqto extract and a hand-collected POC quote land in
the same table and train the same models.

Two fields carry more weight than their size suggests:

`quoted`   False means the provider was asked and declined or referred. That is
           not the same as absent, and the distinction drives the quotability
           model. Never impute a premium for a declined row.

`premium`  Annual premium in GBP, inclusive of IPT, excluding add-ons priced
           separately. Cross-brand comparison is meaningless unless cover is
           held constant, so the cover fields are mandatory rather than optional.
"""

from __future__ import annotations

import datetime as _dt
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class PolicyType(str, Enum):
    buildings = "buildings"
    contents = "contents"
    combined = "combined"


class BuildingType(str, Enum):
    detached = "detached"
    semi_detached = "semi_detached"
    terraced = "terraced"
    end_terrace = "end_terrace"
    flat = "flat"
    bungalow = "bungalow"


class Construction(str, Enum):
    standard = "standard"
    non_standard_walls = "non_standard_walls"
    non_standard_roof = "non_standard_roof"
    listed = "listed"


class Occupancy(str, Enum):
    owner_occupied = "owner_occupied"
    let = "let"
    second_home = "second_home"
    unoccupied = "unoccupied"


class Channel(str, Enum):
    direct = "direct"
    pcw_ctm = "pcw_ctm"
    pcw_msm = "pcw_msm"
    pcw_confused = "pcw_confused"
    pcw_gocompare = "pcw_gocompare"


class Source(str, Enum):
    """Provenance. Never mix these silently -- accuracy differs by source."""

    manual = "manual"          # self-collected, real customer identity
    vendor_ci = "vendor_ci"    # Consumer Intelligence extract
    vendor_dfq = "vendor_dfq"  # Defaqto Market Pricing extract (ex Pearson Ham, from 2026)
    vendor_ph = "vendor_ph"    # historic Pearson Ham raw files (pre-2026)
    synthetic = "synthetic"    # generated for pipeline testing only


class Risk(BaseModel):
    """The insured risk. Stable across brands and collection dates."""

    risk_id: str = Field(description="Stable identifier; same risk over time.")
    postcode: str = Field(description="Full UK postcode, e.g. 'BS1 4DJ'.")
    policy_type: PolicyType
    building_type: BuildingType
    construction: Construction = Construction.standard
    occupancy: Occupancy = Occupancy.owner_occupied
    year_built: int = Field(ge=1000, le=2100)
    bedrooms: int = Field(ge=1, le=20)

    buildings_sum_insured: Optional[float] = Field(default=None, ge=0)
    contents_sum_insured: Optional[float] = Field(default=None, ge=0)
    voluntary_excess: float = Field(ge=0)

    claims_last_5y: int = Field(default=0, ge=0)
    flood_history: bool = False
    subsidence_history: bool = False

    in_basket: bool = Field(
        default=False,
        description="True if part of the fixed index basket. Basket risks must "
                    "be collected every cycle or the index breaks.",
    )

    @field_validator("postcode")
    @classmethod
    def _normalise_postcode(cls, v: str) -> str:
        v = " ".join(v.upper().split())
        if len(v.replace(" ", "")) < 5:
            raise ValueError(f"Implausible UK postcode: {v!r}")
        return v

    @model_validator(mode="after")
    def _check_sums_match_policy(self):
        if self.policy_type in (PolicyType.buildings, PolicyType.combined):
            if not self.buildings_sum_insured:
                raise ValueError("buildings_sum_insured required for this policy_type")
        if self.policy_type in (PolicyType.contents, PolicyType.combined):
            if not self.contents_sum_insured:
                raise ValueError("contents_sum_insured required for this policy_type")
        return self

    @property
    def outcode(self) -> str:
        return self.postcode.split()[0]

    @property
    def area(self) -> str:
        return "".join(c for c in self.outcode if c.isalpha())


class Quote(BaseModel):
    """One provider's response to one risk, on one channel, on one date."""

    risk_id: str
    brand: str
    underwriter: Optional[str] = None
    channel: Channel
    collected_on: _dt.date
    source: Source

    quoted: bool = Field(
        description="False = asked and declined/referred. Not the same as absent."
    )
    premium: Optional[float] = Field(default=None, ge=0)

    # Cover actually offered -- may differ from what was requested.
    compulsory_excess: Optional[float] = Field(default=None, ge=0)
    accidental_damage: Optional[bool] = None
    rank_on_page: Optional[int] = Field(default=None, ge=1)

    # Incentives sit OUTSIDE the premium. Folding them in corrupts the index.
    cashback: Optional[float] = Field(default=None, ge=0)
    incentive_note: Optional[str] = None

    collector_note: Optional[str] = None

    @model_validator(mode="after")
    def _premium_iff_quoted(self):
        if self.quoted and self.premium is None:
            raise ValueError("quoted=True requires a premium")
        if not self.quoted and self.premium is not None:
            raise ValueError("quoted=False must not carry a premium")
        return self

    @property
    def total_excess(self) -> Optional[float]:
        if self.compulsory_excess is None:
            return None
        return self.compulsory_excess


RISK_COLUMNS = list(Risk.model_fields.keys())
QUOTE_COLUMNS = list(Quote.model_fields.keys())

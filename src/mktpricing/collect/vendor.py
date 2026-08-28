"""Vendor extract adapter -- Consumer Intelligence, Defaqto, or anything else.

Maps a licensed extract onto the canonical schema in `schema.py`, so vendor rows
and hand-collected rows train the same models and nothing downstream cares which
they came from.

Read this before using it
-------------------------
**No sample extract has been seen.** The column names in `CI_SPEC` and
`DEFAQTO_SPEC` are provisional -- assembled from published vendor terminology,
not from a real file -- and they will be wrong in detail. That is why the module
is mapping-driven rather than hard-coded: when the first extract lands, run
`profile_extract()`, paste the suggested mapping into a `VendorSpec`, and the
rest of the pipeline works unchanged. Correcting a spec is a config edit. It
should never require touching the loader.

The audits are the point
------------------------
Mapping columns is the easy half. The half that silently ruins a market-pricing
project is that a vendor extract can be perfectly well-formed and still be the
wrong data:

- **Declines omitted.** Most extracts contain only quotes actually returned. If
  every row is a quote, the quotability model is unlearnable and the simulated
  market price is biased *down*, because the cheap provider that would have
  refused the risk still wins the cheapest-five.
- **Top-N truncation.** Some products supply only the cheapest N per risk. That
  is a truncated sample: fit on it and you learn each brand's price *conditional
  on it being competitive*, which is not its price. Aggregate accuracy will look
  excellent and per-brand accuracy on expensive risks will be terrible.
- **Premium basis.** Annual vs monthly, IPT in or out. Getting this wrong scales
  everything by ~12 or ~1.12, and every relative metric still looks fine.
- **Rotating panel.** If the risks change between weeks you cannot compute an
  index from them; week-on-week movement confounds price with mix.
- **Risk attributes absent.** An extract of premiums with no sum insured, excess
  or property attributes supports benchmarking and nothing else. You cannot
  train a per-provider model on it at any price.

`audit_extract()` checks all of these and returns findings ranked BLOCKER /
WARN / INFO. Run it before the first model fit, not after the first odd result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..schema import QUOTE_COLUMNS, RISK_COLUMNS, Quote, Risk, Source

# ---------------------------------------------------------------------------
# provider registry
# ---------------------------------------------------------------------------

_DEFAULT_PROVIDERS = Path(__file__).resolve().parents[3] / "config" / "providers.yml"


def load_providers(path=None) -> dict:
    """Read `config/providers.yml`."""
    p = Path(path) if path else _DEFAULT_PROVIDERS
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _brand_key(value) -> str:
    """Aggressive normalisation for brand matching.

    Vendors write "Direct Line Insurance", "Direct Line Home" and "DIRECT LINE"
    for one brand. Strip case, punctuation and the noise words that carry no
    identity, then compare. Kept deliberately blunt -- anything it cannot
    resolve is *reported*, never guessed at, because silently folding two brands
    together corrupts every per-brand number in the project.
    """
    s = str(value).lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    for noise in (
        "home insurance", "buildings and contents", "buildings", "contents",
        "insurance", "underwriting", "limited", "ltd", "plc", "uk", "group",
        "the", "com",
    ):
        s = re.sub(rf"\b{noise}\b", " ", s)
    return " ".join(s.split())


class BrandResolver:
    """Map vendor brand strings onto the names in `providers.yml`.

    Unresolved brands are collected rather than dropped. A brand the resolver
    does not recognise is usually either a genuine new entrant worth adding to
    the config, or a spelling variant -- and both need a human to look, because
    the alternative is a brand quietly vanishing from the top-five.
    """

    def __init__(self, providers=None, aliases=None):
        providers = providers or load_providers()
        self.canonical = [b["name"] for b in providers["brands"]]
        self.underwriter = {b["name"]: b.get("underwriter") for b in providers["brands"]}
        self._by_key = {_brand_key(n): n for n in self.canonical}
        for alias, target in (aliases or {}).items():
            if target not in self.canonical:
                raise ValueError(
                    f"alias {alias!r} points at {target!r}, which is not in "
                    "providers.yml"
                )
            self._by_key[_brand_key(alias)] = target
        self.unresolved: dict = {}

    def resolve(self, value):
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        hit = self._by_key.get(_brand_key(value))
        if hit is None:
            self.unresolved[str(value)] = self.unresolved.get(str(value), 0) + 1
        return hit

    def report(self) -> pd.DataFrame:
        return pd.DataFrame(
            sorted(
                ({"vendor_brand": k, "rows": v} for k, v in self.unresolved.items()),
                key=lambda r: -r["rows"],
            )
        )


# ---------------------------------------------------------------------------
# value normalisation
# ---------------------------------------------------------------------------

# Spellings vendors plausibly use, mapped onto the schema enums. A spec's own
# `values` entry overrides these; this is the starting point, not the law.
DEFAULT_VALUE_MAPS = {
    "policy_type": {
        "buildings only": "buildings", "buildings": "buildings",
        "contents only": "contents", "contents": "contents",
        "combined": "combined", "buildings and contents": "combined",
        "buildings & contents": "combined", "home": "combined",
    },
    "building_type": {
        "detached": "detached", "detached house": "detached",
        "semi detached": "semi_detached", "semi-detached": "semi_detached",
        "semi": "semi_detached", "semi detached house": "semi_detached",
        "terraced": "terraced", "mid terrace": "terraced",
        "mid-terrace": "terraced", "terrace": "terraced",
        "end terrace": "end_terrace", "end-terrace": "end_terrace",
        "end of terrace": "end_terrace",
        "flat": "flat", "apartment": "flat", "maisonette": "flat",
        "bungalow": "bungalow", "detached bungalow": "bungalow",
    },
    "construction": {
        "standard": "standard", "brick": "standard", "standard construction": "standard",
        "non standard walls": "non_standard_walls",
        "non-standard walls": "non_standard_walls",
        "timber frame": "non_standard_walls",
        "non standard roof": "non_standard_roof",
        "non-standard roof": "non_standard_roof",
        "thatch": "non_standard_roof", "thatched": "non_standard_roof",
        "flat roof": "non_standard_roof",
        "listed": "listed", "grade i": "listed", "grade ii": "listed",
    },
    "occupancy": {
        "owner occupied": "owner_occupied", "owner-occupied": "owner_occupied",
        "main residence": "owner_occupied", "owner": "owner_occupied",
        "let": "let", "let property": "let", "landlord": "let", "tenanted": "let",
        "second home": "second_home", "holiday home": "second_home",
        "unoccupied": "unoccupied", "vacant": "unoccupied",
    },
    "channel": {
        "direct": "direct", "insurer direct": "direct", "own site": "direct",
        "compare the market": "pcw_ctm", "comparethemarket": "pcw_ctm",
        "ctm": "pcw_ctm",
        "moneysupermarket": "pcw_msm", "money supermarket": "pcw_msm",
        "msm": "pcw_msm",
        "confused": "pcw_confused", "confused.com": "pcw_confused",
        "gocompare": "pcw_gocompare", "go compare": "pcw_gocompare",
    },
}

_TRUE = {"y", "yes", "true", "1", "t", "included", "quoted"}
_FALSE = {"n", "no", "false", "0", "f", "excluded", "declined", "refused", "referred"}


def _norm_token(value) -> str:
    return " ".join(str(value).strip().lower().split())


def _to_bool(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    t = _norm_token(value)
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    return None


def _to_float(value):
    """Parse a money-ish value. Returns None rather than raising."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float, np.number)):
        return float(value)
    s = re.sub(r"[£$,\s]", "", str(value))
    if s in ("", "-", "n/a", "na"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# spec
# ---------------------------------------------------------------------------


@dataclass
class VendorSpec:
    """How one vendor's file maps onto the canonical schema.

    `columns` maps canonical field -> the column name in their file. Anything
    not listed is simply absent, which the audit will tell you about.

    The four declared facts below cannot be inferred safely and must come from
    the vendor's documentation or a support email. Guessing any of them produces
    a dataset that looks right and is wrong by a constant factor.
    """

    name: str
    source: str = Source.vendor_ci.value
    columns: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    brand_aliases: dict = field(default_factory=dict)

    # -- declared, never inferred ------------------------------------------
    premium_basis: str = "annual"          # "annual" or "monthly"
    premium_includes_ipt: bool = True
    declines_included: bool | None = None   # None = not yet confirmed by the vendor
    truncated_to_top_n: int | None = None   # set if only the cheapest N are supplied

    # -- conveniences -------------------------------------------------------
    channel_default: str | None = None      # if the file covers one channel only
    date_format: str | None = None          # None = let pandas infer
    dayfirst: bool = True                  # UK files are almost always dd/mm/yyyy

    def value_map(self, field_name: str) -> dict:
        base = dict(DEFAULT_VALUE_MAPS.get(field_name, {}))
        base.update({_norm_token(k): v for k, v in self.values.get(field_name, {}).items()})
        return base


# Provisional. Verify every column name against a real extract before trusting
# these; they exist so the first mapping is an edit rather than a blank page.
CI_SPEC = VendorSpec(
    name="Consumer Intelligence",
    source=Source.vendor_ci.value,
    columns={
        "risk_id": "QuoteReference",
        "brand": "Brand",
        "channel": "Channel",
        "collected_on": "QuoteDate",
        "premium": "AnnualPremium",
        "quoted": "Status",
        "rank_on_page": "Rank",
        "postcode": "Postcode",
        "policy_type": "CoverType",
        "building_type": "PropertyType",
        "construction": "ConstructionType",
        "occupancy": "OccupancyType",
        "year_built": "YearBuilt",
        "bedrooms": "Bedrooms",
        "buildings_sum_insured": "BuildingsSumInsured",
        "contents_sum_insured": "ContentsSumInsured",
        "voluntary_excess": "VoluntaryExcess",
        "compulsory_excess": "CompulsoryExcess",
        "claims_last_5y": "ClaimsCount",
        "accidental_damage": "AccidentalDamage",
    },
)

DEFAQTO_SPEC = VendorSpec(
    name="Defaqto Market Pricing",
    source=Source.vendor_dfq.value,
    columns={
        "risk_id": "RiskId",
        "brand": "ProviderName",
        "channel": "Source",
        "collected_on": "CollectionDate",
        "premium": "Premium",
        "rank_on_page": "Position",
        "postcode": "Postcode",
        "policy_type": "PolicyType",
        "building_type": "PropertyType",
        "construction": "ConstructionType",
        "occupancy": "OccupancyType",
        "year_built": "YearOfConstruction",
        "bedrooms": "NumberOfBedrooms",
        "buildings_sum_insured": "BuildingsCover",
        "contents_sum_insured": "ContentsCover",
        "voluntary_excess": "VoluntaryExcess",
        "compulsory_excess": "CompulsoryExcess",
        "claims_last_5y": "PreviousClaims",
        "accidental_damage": "AccidentalDamage",
    },
)

SPECS = {"ci": CI_SPEC, "defaqto": DEFAQTO_SPEC}


# ---------------------------------------------------------------------------
# reading and profiling
# ---------------------------------------------------------------------------


def read_extract(path) -> pd.DataFrame:
    """Read csv / tsv / parquet / xlsx. Everything stays as text where possible.

    Text-first is deliberate: pandas will happily read a postcode column as a
    float if it looks numeric enough, and a sum insured with a thousands comma
    as a string. Coercion happens once, in `apply_spec`, where it is visible.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".parquet", ".pq"):
        return pd.read_parquet(p)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(p, dtype=str)
    sep = "\t" if suffix in (".tsv", ".tab") else ","
    return pd.read_csv(p, dtype=str, sep=sep, low_memory=False)


# Keywords that suggest a canonical field, checked against the column name.
_FIELD_HINTS = {
    "risk_id": ("riskid", "risk", "quoteref", "reference", "scenario", "caseid"),
    "brand": ("brand", "provider", "insurer", "productname", "scheme"),
    "underwriter": ("underwriter", "carrier", "insurerentity"),
    "channel": ("channel", "source", "aggregator", "site", "distribution"),
    "collected_on": ("date", "collected", "quotedate", "week", "period"),
    "premium": ("premium", "price", "annualprice", "totalcost", "cost"),
    "quoted": ("quoted", "status", "outcome", "declined", "result"),
    "rank_on_page": ("rank", "position", "placing"),
    "postcode": ("postcode", "postalcode", "pcd", "zip"),
    "policy_type": ("covertype", "policytype", "cover", "producttype"),
    "building_type": ("propertytype", "buildingtype", "housetype", "dwelling"),
    "construction": ("construction", "walls", "roof", "listed"),
    "occupancy": ("occupancy", "occupied", "residencetype", "use"),
    "year_built": ("yearbuilt", "yearofconstruction", "buildyear", "propertyage"),
    "bedrooms": ("bedroom", "beds", "numberofrooms"),
    "buildings_sum_insured": ("buildingssum", "buildingscover", "rebuild"),
    "contents_sum_insured": ("contentssum", "contentscover", "contentsvalue"),
    "voluntary_excess": ("voluntaryexcess", "volexcess"),
    "compulsory_excess": ("compulsoryexcess", "compexcess", "mandatoryexcess"),
    "claims_last_5y": ("claim",),
    "accidental_damage": ("accidentaldamage", "adcover"),
    "cashback": ("cashback", "incentive", "voucher"),
}


def _guess_field(column: str):
    c = re.sub(r"[^a-z0-9]", "", str(column).lower())
    best = None
    for canon, hints in _FIELD_HINTS.items():
        for h in hints:
            if h in c:
                # Prefer the longest hint matched -- "compulsoryexcess" must beat
                # the bare "excess"-ish prefixes of other fields.
                if best is None or len(h) > best[1]:
                    best = (canon, len(h))
    return best[0] if best else None


def profile_extract(source, *, max_samples: int = 5) -> pd.DataFrame:
    """Inspect an unknown extract: what is in each column, and what it might be.

    Run this first on any new vendor file. It does not modify anything and does
    not assume a spec; it exists so mapping a new file takes minutes and so you
    see the cardinalities before deciding what is trustworthy.
    """
    df = source if isinstance(source, pd.DataFrame) else read_extract(source)
    rows = []
    for col in df.columns:
        s = df[col]
        non_null = s.dropna()
        samples = [str(v) for v in non_null.unique()[:max_samples]]
        rows.append(
            {
                "column": col,
                "guessed_field": _guess_field(col),
                "n_unique": int(non_null.nunique()),
                "pct_null": round(float(s.isna().mean() * 100), 1),
                "samples": " | ".join(samples),
            }
        )
    return pd.DataFrame(rows)


def suggest_spec(source, *, name: str = "NewVendor") -> str:
    """Emit a `VendorSpec(...)` you can paste and correct.

    Deliberately emits a *draft*, with the four undeclarable facts left at their
    defaults and commented, because those must come from the vendor rather than
    from the file.
    """
    prof = profile_extract(source)
    mapped = prof.dropna(subset=["guessed_field"]).drop_duplicates("guessed_field")
    lines = [
        f'VendorSpec(',
        f'    name="{name}",',
        f'    source=Source.vendor_ci.value,        # or vendor_dfq',
        f'    columns={{',
    ]
    for _, r in mapped.iterrows():
        lines.append(f'        "{r.guessed_field}": "{r.column}",')
    lines += [
        "    },",
        "    # CONFIRM THESE WITH THE VENDOR -- they cannot be read off the file:",
        '    premium_basis="annual",',
        "    premium_includes_ipt=True,",
        "    declines_included=None,",
        "    truncated_to_top_n=None,",
        ")",
    ]
    unmapped = prof[prof.guessed_field.isna()].column.tolist()
    if unmapped:
        lines.append(f"# unmapped columns: {unmapped}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------

_NUMERIC_FIELDS = (
    "premium", "buildings_sum_insured", "contents_sum_insured",
    "voluntary_excess", "compulsory_excess", "cashback",
)
_INT_FIELDS = ("year_built", "bedrooms", "claims_last_5y", "rank_on_page")
_ENUM_FIELDS = ("policy_type", "building_type", "construction", "occupancy", "channel")


def apply_spec(source, spec: VendorSpec, *, resolver: BrandResolver = None):
    """Rename and normalise a vendor frame into canonical columns.

    Returns `(canonical_df, problems)`. Unmappable *values* become NaN and are
    reported; they are never coerced to a default, for the same reason an
    invented flood band is worse than a missing one.
    """
    df = source if isinstance(source, pd.DataFrame) else read_extract(source)
    problems: list = []
    out = pd.DataFrame(index=df.index)

    missing = [c for c in spec.columns.values() if c not in df.columns]
    if missing:
        problems.append(
            f"spec names {len(missing)} column(s) the file does not have: "
            f"{missing}. File has: {list(df.columns)[:30]}"
        )

    for canon, vendor_col in spec.columns.items():
        if vendor_col not in df.columns:
            continue
        s = df[vendor_col]

        if canon in _NUMERIC_FIELDS:
            out[canon] = [_to_float(v) for v in s]
        elif canon in _INT_FIELDS:
            vals = [_to_float(v) for v in s]
            out[canon] = [None if v is None else int(round(v)) for v in vals]
        elif canon in ("quoted", "accidental_damage", "flood_history",
                       "subsidence_history"):
            # A spec may declare the vendor's own vocabulary, e.g.
            # values={"quoted": {"NTU": False, "Refer": False}}. Without that,
            # `_to_bool` handles the common words and returns None otherwise.
            vmap = {
                _norm_token(k): v for k, v in spec.values.get(canon, {}).items()
            }
            out[canon] = [
                _to_bool(vmap.get(_norm_token(v), v)) if pd.notna(v) else None
                for v in s
            ]
        elif canon == "collected_on":
            out[canon] = pd.to_datetime(
                s, format=spec.date_format, dayfirst=spec.dayfirst, errors="coerce"
            ).dt.date
            n_bad = int(pd.isna(out[canon]).sum())
            if n_bad:
                problems.append(f"collected_on: {n_bad} row(s) unparseable as a date")
        elif canon in _ENUM_FIELDS:
            vmap = spec.value_map(canon)
            mapped = [vmap.get(_norm_token(v)) if pd.notna(v) else None for v in s]
            unknown = sorted(
                {
                    str(v) for v, m in zip(s, mapped)
                    if pd.notna(v) and m is None
                }
            )
            if unknown:
                problems.append(
                    f"{canon}: {len(unknown)} unmapped value(s) {unknown[:8]} -- "
                    f"add them to the spec's values['{canon}']"
                )
            out[canon] = mapped
        else:
            out[canon] = s.astype("string").str.strip()

    if spec.channel_default and "channel" not in out.columns:
        out["channel"] = spec.channel_default

    # Brand resolution against providers.yml.
    if "brand" in out.columns:
        resolver = resolver or BrandResolver(aliases=spec.brand_aliases)
        out["brand_raw"] = out["brand"]
        out["brand"] = [resolver.resolve(v) for v in out["brand"]]
        out["underwriter"] = [
            resolver.underwriter.get(b) if b else None for b in out["brand"]
        ]
        if resolver.unresolved:
            problems.append(
                f"{len(resolver.unresolved)} unrecognised brand(s): "
                f"{sorted(resolver.unresolved)[:8]} -- add to providers.yml or to "
                "the spec's brand_aliases"
            )

    # A column the file has, that looks like a model feature, that the spec
    # does not map. This is the quiet one: `construction` and `occupancy` have
    # schema defaults, so an unmapped column does not error -- every risk just
    # silently becomes standard construction, owner occupied, and the real
    # variation is gone with nothing to show it ever existed.
    mapped = set(spec.columns.values())
    overlooked = []
    for col in df.columns:
        if col in mapped:
            continue
        guess = _guess_field(col)
        if guess and guess not in spec.columns:
            overlooked.append(f"{col} -> {guess}")
    if overlooked:
        problems.append(
            f"file has {len(overlooked)} column(s) the spec ignores that look "
            f"like model features: {overlooked}. Fields with a schema default "
            "(construction, occupancy) will silently take that default."
        )

    out = _normalise_premium(out, spec, problems)

    # Absent `quoted` means the file carries only successful quotes. Mark them
    # True, and let the audit raise the consequence -- which is that the
    # quotability half of the model has no training data.
    has_premium = (
        out["premium"].notna() if "premium" in out.columns
        else pd.Series(True, index=out.index)
    )
    if "quoted" not in out.columns:
        out["quoted"] = has_premium
    else:
        # An unrecognised status word maps to None. Falling back to "did a
        # premium come back" is the right inference, but it is an inference --
        # say so, because a status vocabulary we do not know may distinguish
        # a decline from a referral, and those are different events.
        unknown = out["quoted"].isna()
        if unknown.any():
            out.loc[unknown, "quoted"] = has_premium[unknown]
            problems.append(
                f"quoted: {int(unknown.sum())} row(s) had an unrecognised status; "
                "inferred from whether a premium was returned. Add the vendor's "
                "status words to the spec's values['quoted'] to be sure."
            )
    out["quoted"] = out["quoted"].astype(bool)
    out["source"] = spec.source
    return out, problems


def _normalise_premium(out: pd.DataFrame, spec: VendorSpec, problems: list):
    """Put premium on the schema's basis: annual, IPT inclusive.

    Both conversions are declared on the spec rather than detected, because a
    detector that is wrong once silently rescales the entire dataset. The audit
    separately sanity-checks the result against plausible UK premiums, so a
    mis-declared basis still gets caught -- just as a finding, not a guess.
    """
    if "premium" not in out.columns:
        return out
    if spec.premium_basis == "monthly":
        out["premium"] = out["premium"] * 12.0
        problems.append("premium: converted monthly -> annual (x12) per spec")
    elif spec.premium_basis != "annual":
        raise ValueError(f"premium_basis must be 'annual' or 'monthly', got "
                         f"{spec.premium_basis!r}")
    if not spec.premium_includes_ipt:
        out["premium"] = out["premium"] * 1.12
        problems.append("premium: added 12% IPT per spec")
    return out


# ---------------------------------------------------------------------------
# audits
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    severity: str   # BLOCKER | WARN | INFO
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}: {self.message}"


# Plausible UK annual home premiums, IPT inclusive. Wide on purpose -- this is a
# basis check, not an outlier filter, and outliers are signal here.
_PLAUSIBLE_MEDIAN = (90.0, 1200.0)

# Risk attributes without which no per-provider model can be trained.
_MODELLING_ESSENTIALS = (
    "postcode", "policy_type", "building_type",
    "buildings_sum_insured", "contents_sum_insured", "voluntary_excess",
)


def audit_extract(canonical: pd.DataFrame, spec: VendorSpec) -> list:
    """Everything that can be wrong with a well-formed extract.

    Run before the first fit. A BLOCKER means the data cannot answer the
    question this repo asks, however clean it looks.
    """
    f: list = []
    n = len(canonical)
    if n == 0:
        return [Finding("BLOCKER", "empty", "extract has no rows")]

    # -- declines ----------------------------------------------------------
    quoted = canonical.get("quoted")
    n_declined = int((~quoted.astype(bool)).sum()) if quoted is not None else 0
    if n_declined == 0:
        sev = "BLOCKER" if spec.declines_included else "WARN"
        f.append(
            Finding(
                sev, "no_declines",
                "every row is a quote, so no provider ever declined. Either the "
                "extract omits declines -- in which case the quotability model "
                "cannot be trained and the simulated market price is biased "
                "DOWN, because a provider that would have refused still wins the "
                "cheapest-five -- or the panel is entirely mainstream risks. Ask "
                "the vendor which, and set spec.declines_included.",
            )
        )
    elif spec.declines_included is False:
        f.append(
            Finding("WARN", "declines_unexpected",
                    f"spec says declines are not supplied but {n_declined} rows "
                    "are non-quotes. The spec is stale.")
        )
    else:
        f.append(
            Finding("INFO", "declines",
                    f"{n_declined:,} declines ({n_declined / n * 100:.1f}%) -- "
                    "these train the quotability model")
        )

    # -- premium basis -----------------------------------------------------
    if "premium" in canonical:
        prem = pd.to_numeric(canonical["premium"], errors="coerce").dropna()
        if len(prem):
            med = float(prem.median())
            if med < _PLAUSIBLE_MEDIAN[0]:
                f.append(
                    Finding("BLOCKER", "premium_basis",
                            f"median premium GBP {med:,.0f} is too low for an "
                            "annual UK home policy. Likely monthly (set "
                            "premium_basis='monthly') or a per-cover component "
                            "rather than the total.")
                )
            elif med > _PLAUSIBLE_MEDIAN[1]:
                f.append(
                    Finding("WARN", "premium_basis",
                            f"median premium GBP {med:,.0f} is high for standard "
                            "UK home cover. Check for pence units, a high-net-"
                            "worth panel, or add-ons folded into the premium.")
                )
            else:
                f.append(
                    Finding("INFO", "premium_basis",
                            f"median premium GBP {med:,.0f}, annual IPT-inclusive "
                            "-- plausible")
                )

    # -- truncation --------------------------------------------------------
    keys = [c for c in ("risk_id", "collected_on", "channel") if c in canonical]
    if "risk_id" in canonical:
        sizes = canonical.groupby(keys, dropna=False).size()
        consequence = (
            "Fitting on a truncated sample learns each brand's price CONDITIONAL "
            "on being competitive, which is not its price -- aggregate accuracy "
            "looks excellent and expensive-risk accuracy is terrible."
        )
        if len(sizes) > 3 and sizes.nunique() == 1 and int(sizes.iloc[0]) <= 10:
            k = int(sizes.iloc[0])
            # A constant small panel is ambiguous on its own: a genuine panel of
            # exactly k brands looks identical to the cheapest k.
            #
            # Declines settle it. A cheapest-N list contains only quotes by
            # definition, so a declined row is proof the extract is a panel.
            # Rank cannot settle it -- a vendor ranking within the rows they
            # supplied makes "no rank exceeds k" true either way.
            if n_declined > 0:
                f.append(
                    Finding("INFO", "panel_size",
                            f"every risk-week has {k} rows, but {n_declined:,} are "
                            "declines -- so this is a full panel of the same "
                            f"{k} brands, not a top-{k} cut")
                )
            else:
                f.append(
                    Finding("WARN", "possible_truncation",
                            f"every risk has exactly {k} rows and none is a "
                            f"decline. Either the panel is genuinely {k} brands, "
                            f"or you were sent a top-{k}. Confirm with the vendor "
                            f"and set spec.truncated_to_top_n. {consequence}")
                )
        elif spec.truncated_to_top_n:
            f.append(
                Finding("BLOCKER", "truncated",
                        f"spec declares the extract is truncated to the cheapest "
                        f"{spec.truncated_to_top_n} per risk. {consequence}")
            )
        else:
            f.append(
                Finding("INFO", "panel_size",
                        f"median {sizes.median():.0f} brands per risk-week "
                        f"(min {sizes.min()}, max {sizes.max()})")
            )

    # -- rotating panel ----------------------------------------------------
    if {"risk_id", "collected_on"} <= set(canonical.columns):
        by_date = canonical.dropna(subset=["collected_on"]).groupby("collected_on")
        dates = sorted(by_date.groups)
        if len(dates) >= 2:
            first = set(canonical[canonical.collected_on == dates[0]].risk_id)
            last = set(canonical[canonical.collected_on == dates[-1]].risk_id)
            overlap = len(first & last) / max(len(first | last), 1)
            if overlap < 0.5:
                f.append(
                    Finding("WARN", "rotating_panel",
                            f"only {overlap * 100:.0f}% of risks are common to the "
                            "first and last collection date. This is a rotating "
                            "panel: good for training across risk space, unusable "
                            "for a week-on-week index, because movement confounds "
                            "price with mix. Index off a fixed basket only.")
                )
            else:
                f.append(
                    Finding("INFO", "fixed_basket",
                            f"{overlap * 100:.0f}% risk overlap across the period "
                            "-- suitable for indexing")
                )

    # -- risk attributes ---------------------------------------------------
    absent = [c for c in _MODELLING_ESSENTIALS if c not in canonical.columns]
    thin = [
        c for c in _MODELLING_ESSENTIALS
        if c in canonical.columns and canonical[c].notna().mean() < 0.5
    ]
    if absent:
        f.append(
            Finding("BLOCKER", "no_risk_attributes",
                    f"missing {absent}. Premiums without the risk they price "
                    "support benchmarking and nothing else -- no per-provider "
                    "model can be trained at any price. This is gate question 2 "
                    "in the vendor evaluation.")
        )
    if thin:
        f.append(
            Finding("WARN", "sparse_risk_attributes",
                    f"{thin} are present but under half populated")
        )

    # -- duplicates --------------------------------------------------------
    dup_keys = [c for c in ("risk_id", "brand", "channel", "collected_on")
                if c in canonical]
    if len(dup_keys) >= 3:
        n_dup = int(canonical.duplicated(dup_keys).sum())
        if n_dup:
            f.append(
                Finding("WARN", "duplicates",
                        f"{n_dup:,} duplicate rows on {dup_keys}. One risk-brand-"
                        "channel-date should appear once; duplicates reweight the "
                        "training set toward whatever was double-counted.")
            )

    # -- brand coverage ----------------------------------------------------
    if "brand" in canonical:
        n_unmapped = int(canonical["brand"].isna().sum())
        if n_unmapped:
            f.append(
                Finding("WARN", "unmapped_brands",
                        f"{n_unmapped:,} rows have a brand that does not resolve "
                        "to providers.yml and will be dropped")
            )

    order = {"BLOCKER": 0, "WARN": 1, "INFO": 2}
    return sorted(f, key=lambda x: order[x.severity])


def format_audit(findings) -> str:
    if not findings:
        return "  no findings"
    return "\n".join(f"  {x}" for x in findings)


# ---------------------------------------------------------------------------
# split into canonical records
# ---------------------------------------------------------------------------


def to_records(canonical: pd.DataFrame, *, validate: bool = True):
    """Split a canonical frame into `(risks, quotes, problems)`.

    Risk attributes are collapsed to one row per `risk_id`; the quote columns
    stay per row. Validation runs each record through the pydantic models, so
    anything that reaches the feature builder has already satisfied the same
    invariants a hand-collected row does -- including that a declined row must
    not carry a premium.
    """
    problems: list = []
    df = canonical.copy()

    if "risk_id" not in df.columns:
        return pd.DataFrame(), pd.DataFrame(), ["no risk_id column -- cannot split"]

    df = df[df["risk_id"].notna()]
    if "brand" in df.columns:
        n_before = len(df)
        df = df[df["brand"].notna()]
        if len(df) < n_before:
            problems.append(f"dropped {n_before - len(df):,} rows with unresolved brand")

    # A declined row must not carry a premium; vendors sometimes emit 0.
    if {"quoted", "premium"} <= set(df.columns):
        bad = (~df["quoted"].astype(bool)) & df["premium"].notna()
        if bad.any():
            problems.append(
                f"{int(bad.sum()):,} declined rows carried a premium -- cleared. "
                "A zero or placeholder premium on a decline would be read as a "
                "free policy and win every cheapest-five."
            )
            df.loc[bad, "premium"] = np.nan

    risk_cols = [c for c in RISK_COLUMNS if c in df.columns]
    risk_frame = df[["risk_id"] + [c for c in risk_cols if c != "risk_id"]]

    # A risk_id must describe one risk. If an attribute varies across rows
    # sharing an id, `drop_duplicates` would silently keep whichever row came
    # first -- so every model would then be trained against the wrong property.
    # Usually it means the id is a quote reference rather than a risk key.
    for col in risk_cols:
        if col == "risk_id":
            continue
        n_conflicting = int(
            (risk_frame.groupby("risk_id")[col].nunique(dropna=True) > 1).sum()
        )
        if n_conflicting:
            problems.append(
                f"{col}: {n_conflicting} risk_id(s) carry more than one value. "
                "The first was kept. Either risk_id is a quote reference rather "
                "than a stable risk key, or the attribute is quote-specific -- "
                "check before training, because the models will price a "
                "property that was never quoted."
            )

    risks = risk_frame.drop_duplicates("risk_id").reset_index(drop=True)
    quote_cols = [c for c in QUOTE_COLUMNS if c in df.columns]
    quotes = df[quote_cols].reset_index(drop=True)

    if not validate:
        return risks, quotes, problems

    good_risks, good_ids = [], set()
    for rec in risks.to_dict("records"):
        try:
            good_risks.append(Risk(**_drop_nulls(rec)).model_dump())
            good_ids.add(rec["risk_id"])
        except Exception as exc:
            problems.append(f"risk {rec.get('risk_id')!r}: {exc}")

    good_quotes = []
    for rec in quotes.to_dict("records"):
        if rec.get("risk_id") not in good_ids:
            continue  # its risk failed validation; keeping it would orphan the row
        try:
            good_quotes.append(Quote(**_drop_nulls(rec)).model_dump())
        except Exception as exc:
            problems.append(
                f"quote {rec.get('risk_id')!r}/{rec.get('brand')!r}: {exc}"
            )

    return (
        pd.DataFrame(good_risks),
        pd.DataFrame(good_quotes),
        problems,
    )


def _drop_nulls(rec: dict) -> dict:
    """Strip NaN/None so pydantic applies its own defaults.

    Passing NaN through would fail `ge=0` validators with a confusing message
    instead of falling back to the field default.
    """
    out = {}
    for k, v in rec.items():
        if v is None:
            continue
        if isinstance(v, float) and pd.isna(v):
            continue
        if v is pd.NaT:
            continue
        out[k] = v
    return out


def load_vendor_extract(path, spec, *, validate: bool = True):
    """Read, map, audit and validate in one call.

    Returns `(risks, quotes, findings, problems)`. Nothing is written and
    nothing is dropped silently -- if the audit returns a BLOCKER, the records
    still come back so you can look at them, but you should not train on them.
    """
    if isinstance(spec, str):
        spec = SPECS[spec]
    canonical, problems = apply_spec(path, spec)
    findings = audit_extract(canonical, spec)
    risks, quotes, more = to_records(canonical, validate=validate)
    return risks, quotes, findings, problems + more

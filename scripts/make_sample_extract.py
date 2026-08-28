"""Write a sample vendor extract, so the spec and the audits can be exercised.

**The output is synthetic. It is not Consumer Intelligence data.** No real CI
extract has been seen; this file is invented to have the *shape* one plausibly
has, so `collect/vendor.py` can be tested before a licensed file arrives. The
column names are as provisional as `CI_SPEC` itself -- when a real extract lands,
the real one wins and this script is only useful for the failure flavours below.

What is real about it is the *pricing*: rows come from the synthetic market
generator, so premiums carry genuine multiplicative structure, minimum-premium
point masses, per-brand declines and tactical drift. Only the presentation is
re-dressed into vendor form -- dd/mm/yyyy dates, title-case labels, brand names
written the way a vendor writes them.

    python scripts/make_sample_extract.py
    python scripts/inspect_vendor.py data/raw/sample_ci_extract.csv --spec ci

Each `--flavour` breaks exactly one thing, so you can watch a specific audit
finding fire:

    clean           well-formed; every column maps, declines present
    no-status       no Status column -- quoted must be inferred from the premium
    no-declines     quotes only            -> no_declines
    monthly         premiums divided by 12 -> premium_basis
    truncated       cheapest 5 per risk    -> truncated
    rotating        different risks weekly -> rotating_panel
    premiums-only   risk attributes removed-> no_risk_attributes
    messy           unknown brand, unmapped property type, duplicates, bad date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mktpricing.collect.synthetic import generate  # noqa: E402
from mktpricing.collect.vendor import CI_SPEC  # noqa: E402

FLAVOURS = (
    "clean", "no-status", "no-declines", "monthly", "truncated", "rotating",
    "premiums-only", "messy",
)

# Canonical value -> the label a vendor would print. Every one of these must
# round-trip through DEFAULT_VALUE_MAPS; `test_vendor_sample.py` asserts it.
_LABELS = {
    "policy_type": {
        "combined": "Buildings & Contents",
        "buildings": "Buildings Only",
        "contents": "Contents Only",
    },
    "building_type": {
        "detached": "Detached",
        "semi_detached": "Semi-Detached",
        "terraced": "Mid Terrace",
        "end_terrace": "End Terrace",
        "flat": "Flat",
        "bungalow": "Bungalow",
    },
    "construction": {
        "standard": "Standard",
        "non_standard_walls": "Timber Frame",
        "non_standard_roof": "Flat Roof",
        "listed": "Listed",
    },
    "occupancy": {
        "owner_occupied": "Owner Occupied",
        "let": "Let Property",
        "second_home": "Second Home",
        "unoccupied": "Unoccupied",
    },
    "channel": {
        "direct": "Direct",
        "pcw_ctm": "Compare the Market",
        "pcw_msm": "MoneySuperMarket",
        "pcw_confused": "Confused.com",
        "pcw_gocompare": "GoCompare",
    },
}

# Brands written the way a vendor writes them -- legal entity noise included, so
# the extract exercises BrandResolver rather than matching providers.yml exactly.
_BRAND_LABELS = {
    "Aviva": "Aviva UK",
    "AXA": "AXA Insurance",
    "Direct Line": "Direct Line Insurance",
    "Churchill": "Churchill Home Insurance",
    "Admiral": "Admiral Group plc",
    "LV=": "LV=",
    "Policy Expert": "Policy Expert",
    "Ageas": "Ageas Insurance Limited",
    "Esure": "Esure",
    "Saga": "Saga",
    "More Than": "More Than",
    "Homeprotect": "Homeprotect",
    "NFU Mutual": "NFU Mutual",
}


def build_frame(*, n_risks=60, n_weeks=6, seed=17, flavour="clean",
                rotating_per_week=0) -> pd.DataFrame:
    """Generate a synthetic market and re-dress it as a vendor extract.

    `rotating_per_week` adds risks beyond the fixed basket, which is what a real
    vendor panel looks like -- a stable core plus rotation. Left at 0 the sample
    is basket-only, which keeps the flavours' audit findings clean and
    reproducible, but caps the sample at 40 risks. Raise it for a sample big
    enough to actually train per-brand models on.
    """
    # The generator's first 40 risks are the fixed basket. A rotating flavour
    # therefore needs a population well above that, or there is no non-basket
    # pool to rotate through and the flavour silently produces nothing.
    rotating = flavour == "rotating"
    pop = max(n_risks, 220) if rotating else n_risks
    per_week = 30 if rotating else rotating_per_week
    if per_week and pop <= 40:
        raise ValueError(
            f"rotating_per_week={per_week} needs a population above the "
            f"generator's 40-risk basket; got n_risks={pop}"
        )

    risks, quotes, _ = generate(
        n_risks=pop, n_weeks=n_weeks, seed=seed,
        channels=("pcw_ctm", "pcw_msm", "direct"),
        rotating_per_week=per_week,
    )
    df = quotes.merge(risks, on="risk_id", how="left", validate="many_to_one")

    if rotating:
        # Drop the fixed basket, leaving only risks that change week to week.
        # Keeping it would hold the overlap above the audit's threshold and the
        # flavour would demonstrate nothing.
        df = df[~df.in_basket].copy()
        if df.empty:
            raise RuntimeError(
                "rotating flavour produced no rows -- the generator's basket "
                "swallowed the whole population"
            )

    if flavour == "no-declines":
        df = df[df.quoted].copy()

    # Rank within (risk, week, channel) by price -- what a results page shows.
    df["rank_on_page"] = (
        df.groupby(["risk_id", "week", "channel"])["premium"]
        .rank(method="first", ascending=True)
        .astype("Int64")
    )

    if flavour == "truncated":
        # Keep the cheapest five, and only where five actually quoted -- an
        # uneven row count would not read as a top-N cut to the audit, which is
        # the whole point of this flavour.
        df = df[df.quoted & (df.rank_on_page <= 5)].copy()
        sizes = df.groupby(["risk_id", "week", "channel"]).transform("size")
        df = df[sizes == 5].copy()

    out = pd.DataFrame(
        {
            "QuoteReference": df["risk_id"],
            "Brand": [_BRAND_LABELS.get(b, b) for b in df["brand"]],
            "Channel": [_LABELS["channel"][c] for c in df["channel"]],
            "QuoteDate": [d.strftime("%d/%m/%Y") for d in df["collected_on"]],
            "Status": ["Quoted" if q else "Declined" for q in df["quoted"]],
            "AnnualPremium": [
                "" if pd.isna(p) else f"{p:,.2f}" for p in df["premium"]
            ],
            "Rank": df["rank_on_page"].astype("string").fillna(""),
            "Postcode": df["postcode"],
            "CoverType": [_LABELS["policy_type"][v] for v in df["policy_type"]],
            "PropertyType": [_LABELS["building_type"][v] for v in df["building_type"]],
            "ConstructionType": [_LABELS["construction"][v] for v in df["construction"]],
            "OccupancyType": [_LABELS["occupancy"][v] for v in df["occupancy"]],
            "YearBuilt": df["year_built"],
            "Bedrooms": df["bedrooms"],
            "BuildingsSumInsured": [
                "" if pd.isna(v) else f"{v:,.0f}" for v in df["buildings_sum_insured"]
            ],
            "ContentsSumInsured": [
                "" if pd.isna(v) else f"{v:,.0f}" for v in df["contents_sum_insured"]
            ],
            "VoluntaryExcess": df["voluntary_excess"].astype(int),
            "CompulsoryExcess": 100,
            "ClaimsCount": df["claims_last_5y"],
            "AccidentalDamage": "No",
        }
    ).reset_index(drop=True)

    return _apply_flavour(out, flavour)


def _apply_flavour(out: pd.DataFrame, flavour: str) -> pd.DataFrame:
    if flavour == "no-status":
        return out.drop(columns=["Status"])

    if flavour == "monthly":
        # The vendor quotes monthly; the spec still says annual. The audit has
        # to catch this from the premium distribution alone.
        out["AnnualPremium"] = [
            "" if p == "" else f"{float(p.replace(',', '')) / 12:,.2f}"
            for p in out["AnnualPremium"]
        ]
        return out

    if flavour == "premiums-only":
        keep = ["QuoteReference", "Brand", "Channel", "QuoteDate", "Status",
                "AnnualPremium", "Rank"]
        return out[keep]

    if flavour == "messy":
        out = out.copy()
        # A brand not in providers.yml.
        out.loc[out.index[:20], "Brand"] = "Wibble Mutual"
        # A property type no value map knows.
        out.loc[out.index[20:40], "PropertyType"] = "Houseboat"
        # Currency formatting, which the parser must strip.
        out.loc[out.index[40:80], "AnnualPremium"] = [
            "" if p == "" else f"£{p}"
            for p in out.loc[out.index[40:80], "AnnualPremium"]
        ]
        # An unparseable date.
        out.loc[out.index[80:85], "QuoteDate"] = "not a date"
        # Duplicated rows.
        out = pd.concat([out, out.head(15)], ignore_index=True)
        return out

    return out


def write_geo_fixture(postcodes, out_dir) -> Path:
    """Write geo files describing the synthetic world's actual geography.

    Without this you can only test the chain with *random* geo values, and that
    quietly misreports the POC: the generator prices off each outcode's true
    flood band, crime, subsidence and property value, so random stand-ins strip
    real signal out and feed noise in. Accuracy then looks far worse than the
    pipeline deserves, for reasons nothing in the output explains.

    These files encode `synthetic._AREAS` in the published formats, so
    `features/geo.py` reconstructs the true drivers from files exactly as it
    would from Environment Agency and Land Registry data. Still synthetic --
    a stand-in for the real downloads, not a substitute for them.
    """
    from mktpricing.collect.synthetic import _AREAS
    from mktpricing.features.geo import parse_postcode

    out_dir = Path(out_dir)
    (out_dir / "police").mkdir(parents=True, exist_ok=True)

    pcs = sorted({p for p in postcodes if parse_postcode(p).valid})
    parts = {p: parse_postcode(p) for p in pcs}
    area = {p: _AREAS.get(parts[p].outcode) for p in pcs}
    known = [p for p in pcs if area[p] is not None]

    # Flood: property counts per likelihood band. geo.py takes the highest
    # occupied band, so populate every band up to the outcode's.
    flood_rows = []
    for p in known:
        band = area[p][0]
        counts = [20 if i == 0 else (6 - i if i <= band else 0) for i in range(4)]
        flood_rows.append(
            {"Postcode": p, "Very Low": counts[0], "Low": counts[1],
             "Medium": counts[2], "High": counts[3]}
        )
    pd.DataFrame(flood_rows).to_csv(out_dir / "ea_flood.csv", index=False)

    pd.DataFrame(
        [{"postcode": p, "subsidence_band": area[p][2]} for p in known]
    ).to_csv(out_dir / "subsidence.csv", index=False)

    # Price Paid: geo.py takes a per-sector median, so emit an odd number of
    # sales centred on the outcode's average value.
    sales = []
    for p in known:
        avg = area[p][3]
        for delta in (-0.18, -0.09, 0.0, 0.09, 0.18):
            sales.append(
                {"postcode": p, "price": int(avg * (1 + delta)),
                 "date_of_transfer": "2025-06-01"}
            )
    pd.DataFrame(sales).to_csv(out_dir / "price_paid.csv", index=False)

    # One LSOA per outcode, so crime resolves through the ONSPD bridge.
    outcodes = sorted({parts[p].outcode for p in known})
    lsoa_of = {oc: f"E{1000000 + i:07d}" for i, oc in enumerate(outcodes)}
    pd.DataFrame(
        [{"pcds": p, "lsoa11": lsoa_of[parts[p].outcode]} for p in known]
    ).to_csv(out_dir / "onspd.csv", index=False)

    # Crime counts ordered by the outcode's crime index. geo.py rank-normalises,
    # so only the ordering survives -- which is also true of a real crime index
    # against whatever latent thing actually drives claims.
    crime = []
    for oc in outcodes:
        n = 1 + int(round(_AREAS[oc][1] * 200))
        crime += [{"Crime ID": f"c{oc}", "LSOA code": lsoa_of[oc]}] * n
    pd.DataFrame(crime).to_csv(out_dir / "police" / "2025-06-street.csv", index=False)

    (out_dir / "README.txt").write_text(
        "SYNTHETIC geo fixture, written by scripts/make_sample_extract.py.\n"
        "Encodes the synthetic market generator's own geography so the sample\n"
        "extract can be enriched end to end. NOT Environment Agency, Land\n"
        "Registry, police.uk, ONS or BGS data. Do not mix with real downloads.\n",
        encoding="utf-8",
    )
    unknown = len(pcs) - len(known)
    return out_dir, len(known), unknown


_NOTE = """This file is SYNTHETIC. It is not Consumer Intelligence data.

No real CI extract has been seen. This was generated by
scripts/make_sample_extract.py to have the plausible *shape* of one, so that
src/mktpricing/collect/vendor.py can be tested before a licensed file arrives.
The column names are as provisional as CI_SPEC itself.

The premiums come from the repo's synthetic market generator, so they carry
genuine multiplicative structure, declines and drift -- but they are not any
real insurer's prices and must not be presented, published or benchmarked as
though they were.

flavour: {flavour}
rows:    {rows}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flavour", choices=FLAVOURS, default="clean")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--risks", type=int, default=60)
    ap.add_argument("--weeks", type=int, default=6)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--rotating", type=int, default=0, metavar="N",
                    help="risks per week beyond the 40-risk fixed basket; raise "
                         "for a sample big enough to train per-brand models")
    ap.add_argument("--geo-out", type=Path, default=None, metavar="DIR",
                    help="also write synthetic geo files matching this sample, "
                         "so it can be enriched end to end")
    args = ap.parse_args()

    df = build_frame(
        n_risks=args.risks, n_weeks=args.weeks, seed=args.seed,
        flavour=args.flavour, rotating_per_week=args.rotating,
    )

    out = args.out or Path("data/raw") / (
        "sample_ci_extract.csv" if args.flavour == "clean"
        else f"sample_ci_extract_{args.flavour}.csv"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    out.with_suffix(".NOTE.txt").write_text(
        _NOTE.format(flavour=args.flavour, rows=len(df)), encoding="utf-8"
    )

    print(f"\n  SYNTHETIC sample -- not real vendor data (see {out.stem}.NOTE.txt)")
    print(f"  wrote {len(df):,} rows x {len(df.columns)} columns to {out}")
    print(f"  flavour: {args.flavour}")
    if "QuoteReference" in df.columns:
        print(f"  {df.QuoteReference.nunique():,} risks, "
              f"{df.QuoteDate.nunique()} collection dates")
    unmapped = [c for c in df.columns if c not in CI_SPEC.columns.values()]
    if unmapped:
        print(f"  columns CI_SPEC does not map: {unmapped}")

    geo_arg = ""
    if args.geo_out is not None:
        if "Postcode" not in df.columns:
            print(f"  no Postcode column in the {args.flavour} flavour -- "
                  "no geo fixture written")
        else:
            d, n, unknown = write_geo_fixture(df.Postcode, args.geo_out)
            print(f"\n  SYNTHETIC geo fixture for {n} postcodes in {d}")
            print("  encodes the generator's own geography -- NOT EA / Land "
                  "Registry / police.uk data")
            if unknown:
                print(f"  {unknown} postcode(s) had no area entry and were skipped")
            geo_arg = f" --geo {args.geo_out}"

    print(f"\n  python scripts/inspect_vendor.py {out} --spec ci{geo_arg}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

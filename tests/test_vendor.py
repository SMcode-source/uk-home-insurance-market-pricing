"""Tests for the vendor extract adapter.

No real CI or Defaqto extract exists yet, so these are built against small
frames in the *shape* a vendor file plausibly has. That is enough to pin the
behaviour that matters, because the risky part of this module is not reading a
CSV -- it is the set of ways a perfectly well-formed extract can still be the
wrong data. Each audit finding has a test that constructs the exact failure.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from mktpricing.collect.vendor import (
    DEFAULT_VALUE_MAPS,
    BrandResolver,
    VendorSpec,
    _brand_key,
    _to_float,
    apply_spec,
    audit_extract,
    load_providers,
    profile_extract,
    suggest_spec,
    to_records,
)
from mktpricing.schema import (
    BuildingType,
    Channel,
    Construction,
    Occupancy,
    PolicyType,
)


def _extract(n_risks=4, n_dates=2, brands=("Aviva", "AXA", "Admiral"), premium=300):
    """A minimal well-formed vendor frame in canonical column names."""
    rows = []
    for r in range(n_risks):
        for d in range(n_dates):
            for b in brands:
                rows.append(
                    {
                        "risk_id": f"R{r}",
                        "brand": b,
                        "channel": "pcw_ctm",
                        "collected_on": _dt.date(2026, 7, 1 + d * 7),
                        "quoted": True,
                        "premium": float(premium),
                        "source": "vendor_ci",
                        "postcode": "BS1 4DJ",
                        "policy_type": "combined",
                        "building_type": "detached",
                        "buildings_sum_insured": 250000.0,
                        "contents_sum_insured": 45000.0,
                        "voluntary_excess": 250.0,
                        "year_built": 1990,
                        "bedrooms": 3,
                    }
                )
    return pd.DataFrame(rows)


# -- brand resolution ------------------------------------------------------


@pytest.mark.parametrize(
    "vendor_name,expected",
    [
        ("Direct Line Insurance", "Direct Line"),
        ("DIRECT LINE", "Direct Line"),
        ("direct line home insurance", "Direct Line"),
        ("Aviva UK", "Aviva"),
        ("Policy Expert Home Insurance", "Policy Expert"),
        ("LV=", "LV="),
        ("NFU Mutual Ltd", "NFU Mutual"),
    ],
)
def test_brand_variants_resolve_to_the_canonical_name(vendor_name, expected):
    assert BrandResolver().resolve(vendor_name) == expected


def test_unrecognised_brands_are_reported_not_guessed():
    """Silently folding an unknown brand into a known one would corrupt every
    per-brand number in the project."""
    r = BrandResolver()
    assert r.resolve("Wibble Mutual") is None
    assert r.unresolved == {"Wibble Mutual": 1}
    assert list(r.report().vendor_brand) == ["Wibble Mutual"]


def test_two_distinct_brands_do_not_collide():
    """Direct Line and Churchill share an underwriter but are separate brands,
    and the normaliser must not merge any pair like that."""
    keys = {_brand_key(b["name"]) for b in load_providers()["brands"]}
    assert len(keys) == len(load_providers()["brands"])


def test_alias_pointing_at_an_unknown_brand_is_rejected():
    with pytest.raises(ValueError, match="not in providers.yml"):
        BrandResolver(aliases={"Some Brand": "Not A Real Brand"})


def test_alias_overrides_resolve():
    r = BrandResolver(aliases={"DLG Home": "Direct Line"})
    assert r.resolve("DLG Home") == "Direct Line"


def test_underwriter_is_attached_from_the_config():
    r = BrandResolver()
    # Direct Line Group has been Aviva's since 1 July 2025 (docs/DATA-SOURCES.md).
    assert r.underwriter["Churchill"] == "Aviva"


# -- value maps ------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name,enum",
    [
        ("policy_type", PolicyType),
        ("building_type", BuildingType),
        ("construction", Construction),
        ("occupancy", Occupancy),
        ("channel", Channel),
    ],
)
def test_every_default_value_map_target_is_a_real_enum_member(field_name, enum):
    """A typo here would only surface as a pydantic error at load time, on a
    row somewhere in the middle of a large file."""
    valid = {e.value for e in enum}
    targets = set(DEFAULT_VALUE_MAPS[field_name].values())
    assert targets <= valid, targets - valid


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("£1,234", 1234.0),   # currency symbol and thousands separator
        ("1,234.56", 1234.56),
        (" 250 ", 250.0),
        (450, 450.0),
        ("", None),
        ("n/a", None),
        ("-", None),
        ("not a number", None),
        (None, None),
        (np.nan, None),
    ],
)
def test_money_parsing(raw, expected):
    """Returns None rather than raising: one malformed cell in a large extract
    should be a reported null, not a failed load."""
    assert _to_float(raw) == expected


# -- profiling -------------------------------------------------------------


def test_profile_guesses_the_canonical_field_for_each_column():
    df = pd.DataFrame(
        {
            "QuoteReference": ["R1"],
            "ProviderName": ["Aviva"],
            "AnnualPremium": ["300"],
            "Postcode": ["BS1 4DJ"],
            "NumberOfBedrooms": ["3"],
        }
    )
    got = dict(zip(profile_extract(df).column, profile_extract(df).guessed_field))
    assert got["QuoteReference"] == "risk_id"
    assert got["ProviderName"] == "brand"
    assert got["AnnualPremium"] == "premium"
    assert got["Postcode"] == "postcode"
    assert got["NumberOfBedrooms"] == "bedrooms"


def test_profile_distinguishes_the_two_excess_columns():
    """Both contain "excess"; mapping them to one field would silently discard
    the customer's chosen excess, which is a rating factor."""
    df = pd.DataFrame({"VoluntaryExcess": ["250"], "CompulsoryExcess": ["100"]})
    got = dict(zip(profile_extract(df).column, profile_extract(df).guessed_field))
    assert got["VoluntaryExcess"] == "voluntary_excess"
    assert got["CompulsoryExcess"] == "compulsory_excess"


def test_profile_flags_a_column_it_cannot_place():
    df = pd.DataFrame({"Weather": ["n/a"], "Postcode": ["BS1 4DJ"]})
    prof = profile_extract(df)
    assert prof[prof.column == "Weather"].guessed_field.isna().all()


def test_suggested_spec_leaves_the_undeclarable_facts_to_the_vendor():
    """Basis, IPT, declines and truncation cannot be read off a file. The draft
    must say so rather than emit a confident default."""
    df = pd.DataFrame({"QuoteReference": ["R1"], "AnnualPremium": ["300"]})
    out = suggest_spec(df, name="X")
    assert "CONFIRM THESE WITH THE VENDOR" in out
    assert 'premium_basis="annual"' in out
    assert '"risk_id": "QuoteReference"' in out


# -- mapping ---------------------------------------------------------------


def test_missing_spec_columns_are_reported_with_what_the_file_does_have():
    df = pd.DataFrame({"ref": ["R1"], "prem": ["300"]})
    spec = VendorSpec(name="x", columns={"risk_id": "ref", "premium": "NotThere"})
    _, problems = apply_spec(df, spec)
    assert any("NotThere" in p and "ref" in p for p in problems)


def test_unmapped_enum_values_become_null_and_are_reported():
    """Never coerce an unknown property type to a default -- that invents a
    rating factor, and no metric downstream can detect it."""
    df = pd.DataFrame({"ref": ["R1", "R2"], "pt": ["Detached", "Houseboat"]})
    spec = VendorSpec(name="x", columns={"risk_id": "ref", "building_type": "pt"})
    out, problems = apply_spec(df, spec)
    assert out.building_type.iloc[0] == "detached"
    assert pd.isna(out.building_type.iloc[1])     # never coerced to a default
    assert any("Houseboat" in p for p in problems)


def test_spec_values_override_the_defaults():
    df = pd.DataFrame({"ref": ["R1"], "pt": ["HOUSE-DET"]})
    spec = VendorSpec(
        name="x",
        columns={"risk_id": "ref", "building_type": "pt"},
        values={"building_type": {"HOUSE-DET": "detached"}},
    )
    out, problems = apply_spec(df, spec)
    assert out.building_type.iloc[0] == "detached"
    assert problems == []


def test_monthly_premiums_are_converted_to_annual():
    """A mis-declared basis rescales the whole dataset while every relative
    metric still looks fine."""
    df = pd.DataFrame({"ref": ["R1"], "p": ["25.00"]})
    spec = VendorSpec(
        name="x", columns={"risk_id": "ref", "premium": "p"}, premium_basis="monthly"
    )
    out, problems = apply_spec(df, spec)
    assert out.premium.iloc[0] == pytest.approx(300.0)
    assert any("monthly" in p for p in problems)


def test_ipt_is_added_when_the_vendor_quotes_net():
    df = pd.DataFrame({"ref": ["R1"], "p": ["100"]})
    spec = VendorSpec(
        name="x", columns={"risk_id": "ref", "premium": "p"},
        premium_includes_ipt=False,
    )
    out, problems = apply_spec(df, spec)
    assert out.premium.iloc[0] == pytest.approx(112.0)
    assert any("IPT" in p for p in problems)


def test_an_invalid_premium_basis_is_rejected_outright():
    df = pd.DataFrame({"ref": ["R1"], "p": ["100"]})
    spec = VendorSpec(
        name="x", columns={"risk_id": "ref", "premium": "p"}, premium_basis="weekly"
    )
    with pytest.raises(ValueError, match="premium_basis"):
        apply_spec(df, spec)


def test_unrecognised_status_words_are_inferred_but_flagged():
    df = pd.DataFrame({"ref": ["R1", "R2"], "st": ["Quoted", "NTU"], "p": ["200", ""]})
    spec = VendorSpec(
        name="x", columns={"risk_id": "ref", "quoted": "st", "premium": "p"}
    )
    out, problems = apply_spec(df, spec)
    assert out.quoted.tolist() == [True, False]
    assert any("unrecognised status" in p for p in problems)


def test_a_spec_can_declare_the_vendors_own_status_vocabulary():
    df = pd.DataFrame({"ref": ["R1", "R2"], "st": ["Quoted", "NTU"], "p": ["200", ""]})
    spec = VendorSpec(
        name="x",
        columns={"risk_id": "ref", "quoted": "st", "premium": "p"},
        values={"quoted": {"NTU": False}},
    )
    out, problems = apply_spec(df, spec)
    assert out.quoted.tolist() == [True, False]
    assert problems == []


def test_dates_parse_day_first():
    """UK extracts are dd/mm/yyyy. Month-first would silently reorder the
    weeks and turn the index into noise."""
    df = pd.DataFrame({"ref": ["R1"], "d": ["03/07/2026"]})
    spec = VendorSpec(name="x", columns={"risk_id": "ref", "collected_on": "d"})
    out, _ = apply_spec(df, spec)
    assert out.collected_on.iloc[0] == _dt.date(2026, 7, 3)


# -- audits ----------------------------------------------------------------


def _codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity == severity}


def test_an_extract_with_no_declines_is_flagged():
    """Ignoring declines biases the market price DOWN: the cheap provider that
    would have refused still wins the cheapest-five."""
    df = _extract()
    spec = VendorSpec(name="x", declines_included=True)
    f = audit_extract(df, spec)
    assert "no_declines" in _codes(f, "BLOCKER")


def test_declines_present_is_reported_as_information_not_a_problem():
    df = _extract()
    df.loc[df.index[:5], "quoted"] = False
    df.loc[df.index[:5], "premium"] = np.nan
    f = audit_extract(df, VendorSpec(name="x", declines_included=True))
    assert "no_declines" not in _codes(f)
    assert "declines" in _codes(f, "INFO")


def test_a_stale_spec_that_denies_declines_is_flagged():
    df = _extract()
    df.loc[df.index[:5], "quoted"] = False
    df.loc[df.index[:5], "premium"] = np.nan
    f = audit_extract(df, VendorSpec(name="x", declines_included=False))
    assert "declines_unexpected" in _codes(f, "WARN")


def test_monthly_looking_premiums_are_caught_even_though_the_spec_said_annual():
    """The declared basis is trusted for conversion, but the result is still
    sanity-checked -- a wrong declaration must not pass silently."""
    df = _extract(premium=28)
    f = audit_extract(df, VendorSpec(name="x"))
    assert "premium_basis" in _codes(f, "BLOCKER")


def test_implausibly_high_premiums_are_flagged():
    f = audit_extract(_extract(premium=9000), VendorSpec(name="x"))
    assert "premium_basis" in _codes(f, "WARN")


def test_plausible_premiums_pass():
    f = audit_extract(_extract(premium=340), VendorSpec(name="x"))
    assert "premium_basis" not in _codes(f, "BLOCKER")
    assert "premium_basis" in _codes(f, "INFO")


def test_a_constant_all_quoting_panel_reads_as_possibly_truncated():
    """A genuine panel of exactly five brands looks identical to a top-five when
    every row is a quote, so the audit warns rather than claiming to know."""
    df = _extract(n_risks=6, brands=("Aviva", "AXA", "Admiral", "LV=", "Ageas"))
    f = audit_extract(df, VendorSpec(name="x"))
    assert "possible_truncation" in _codes(f, "WARN")
    assert "truncated" not in _codes(f, "BLOCKER")


def test_a_single_decline_proves_the_extract_is_a_panel():
    """Regression: rank cannot settle this. A vendor ranking within the rows
    they supplied makes "no rank exceeds k" true for a panel AND for a top-k
    cut, which flagged every complete panel as truncated. A decline settles it
    -- a cheapest-N list contains only quotes by definition."""
    df = _extract(n_risks=6, brands=("Aviva", "AXA", "Admiral", "LV=", "Ageas"))
    df["rank_on_page"] = [(i % 5) + 1 for i in range(len(df))]   # ranks <= k
    df.loc[df.index[0], "quoted"] = False
    df.loc[df.index[0], "premium"] = np.nan
    f = audit_extract(df, VendorSpec(name="x"))
    assert "possible_truncation" not in _codes(f)
    assert "truncated" not in _codes(f)
    assert "panel_size" in _codes(f, "INFO")


def test_a_spec_declaring_truncation_is_a_blocker_regardless():
    df = _extract(n_risks=6)
    df = df.drop(df.index[:4])  # uneven sizes, so the heuristic stays quiet
    f = audit_extract(df, VendorSpec(name="x", truncated_to_top_n=5))
    assert "truncated" in _codes(f, "BLOCKER")


def test_a_varying_panel_size_is_not_mistaken_for_truncation():
    df = _extract(n_risks=6)
    df = df.drop(df.index[:4])  # make panel sizes uneven
    f = audit_extract(df, VendorSpec(name="x"))
    assert "truncated" not in _codes(f)
    assert "panel_size" in _codes(f, "INFO")


def test_a_rotating_panel_is_flagged_as_unusable_for_indexing():
    early = _extract(n_risks=3, n_dates=1)
    late = _extract(n_risks=3, n_dates=1)
    late["risk_id"] = late["risk_id"] + "_new"
    late["collected_on"] = _dt.date(2026, 8, 1)
    f = audit_extract(pd.concat([early, late], ignore_index=True), VendorSpec(name="x"))
    assert "rotating_panel" in _codes(f, "WARN")


def test_a_stable_basket_is_reported_as_indexable():
    f = audit_extract(_extract(n_dates=3), VendorSpec(name="x"))
    assert "fixed_basket" in _codes(f, "INFO")


def test_premiums_without_risk_attributes_are_a_blocker():
    """Gate question 2 of the vendor evaluation. Premiums with no risk attached
    support benchmarking and nothing else."""
    df = _extract()[["risk_id", "brand", "channel", "collected_on", "quoted", "premium"]]
    f = audit_extract(df, VendorSpec(name="x"))
    assert "no_risk_attributes" in _codes(f, "BLOCKER")


def test_sparsely_populated_risk_attributes_are_flagged():
    df = _extract()
    df.loc[df.index[: int(len(df) * 0.8)], "voluntary_excess"] = np.nan
    f = audit_extract(df, VendorSpec(name="x"))
    assert "sparse_risk_attributes" in _codes(f, "WARN")


def test_duplicate_rows_are_flagged():
    df = _extract()
    f = audit_extract(pd.concat([df, df.head(3)]), VendorSpec(name="x"))
    assert "duplicates" in _codes(f, "WARN")


def test_findings_are_ordered_blockers_first():
    df = _extract(premium=20)
    f = audit_extract(df, VendorSpec(name="x", declines_included=True))
    severities = [x.severity for x in f]
    assert severities == sorted(severities, key={"BLOCKER": 0, "WARN": 1, "INFO": 2}.get)


def test_an_empty_extract_is_a_blocker_not_a_crash():
    f = audit_extract(pd.DataFrame(), VendorSpec(name="x"))
    assert _codes(f) == {"empty"}


# -- record construction ---------------------------------------------------


def test_to_records_splits_risks_from_quotes():
    risks, quotes, problems = to_records(_extract(n_risks=4, n_dates=2))
    assert len(risks) == 4
    assert len(quotes) == 4 * 2 * 3
    assert problems == []


def test_a_placeholder_premium_on_a_decline_is_cleared():
    """A zero premium on a declined row would be read as a free policy and win
    every cheapest-five."""
    df = _extract()
    df.loc[df.index[0], "quoted"] = False
    df.loc[df.index[0], "premium"] = 0.0
    risks, quotes, problems = to_records(df)
    assert quotes[~quotes.quoted].premium.isna().all()
    assert any("declined rows carried a premium" in p for p in problems)


def test_conflicting_risk_attributes_are_reported():
    """If an attribute varies across rows sharing a risk_id, drop_duplicates
    keeps whichever came first -- so the model prices a property that was never
    quoted. Usually it means risk_id is a quote reference."""
    df = _extract(n_risks=2)
    df.loc[df.index[0], "bedrooms"] = 9
    _, _, problems = to_records(df)
    assert any("bedrooms" in p and "more than one value" in p for p in problems)


def test_rows_with_an_unresolved_brand_are_dropped_and_counted():
    df = _extract()
    df.loc[df.index[:3], "brand"] = None
    _, quotes, problems = to_records(df)
    assert len(quotes) == len(df) - 3
    assert any("unresolved brand" in p for p in problems)


def test_an_invalid_risk_takes_its_quotes_with_it():
    """Keeping quotes whose risk failed validation would orphan them -- they
    would join to nothing in build_matrix and vanish without a trace."""
    df = _extract(n_risks=2)
    df.loc[df.risk_id == "R0", "year_built"] = 12345   # fails Risk's ge/le
    risks, quotes, problems = to_records(df)
    assert set(risks.risk_id) == {"R1"}
    assert set(quotes.risk_id) == {"R1"}
    assert any("R0" in p for p in problems)


def test_validation_enforces_the_premium_iff_quoted_rule():
    df = _extract(n_risks=1, n_dates=1, brands=("Aviva",))
    df.loc[df.index[0], "quoted"] = True
    df.loc[df.index[0], "premium"] = np.nan
    _, quotes, problems = to_records(df)
    assert quotes.empty
    assert any("requires a premium" in p for p in problems)


def test_vendor_output_feeds_the_feature_builder():
    """The contract that matters: whatever a vendor sends must reach the models
    through the same door a hand-collected quote does."""
    from mktpricing.features.build import build_matrix

    risks, quotes, problems = to_records(_extract(n_risks=4, n_dates=2))
    assert problems == []

    # geo.py supplies these from the postcode; stubbed here so the test stays
    # about the vendor contract rather than about geodata files.
    risks = risks.assign(
        flood_band=0.0, crime_index=0.3, subsidence_band=0.0, area_avg_value=300000.0
    )
    quotes = quotes.assign(week=0)

    m = build_matrix(quotes, risks)
    assert len(m) == len(quotes)
    np.testing.assert_allclose(np.exp(m.log_premium), m.premium, rtol=1e-9)


def test_a_recognisable_column_the_spec_ignores_is_reported():
    """The quiet failure: construction and occupancy have schema defaults, so an
    unmapped column does not error -- every risk silently becomes standard
    construction, owner occupied, and the real variation is gone."""
    df = pd.DataFrame(
        {"ref": ["R1"], "ConstructionType": ["Timber Frame"], "Weather": ["n/a"]}
    )
    spec = VendorSpec(name="x", columns={"risk_id": "ref"})
    _, problems = apply_spec(df, spec)
    assert any("ConstructionType -> construction" in p for p in problems)
    # a column that maps to nothing is not worth reporting
    assert not any("Weather" in p for p in problems)


def test_the_shipped_specs_map_construction_and_occupancy():
    """Both are model features with schema defaults, so omitting them from a
    spec loses the variation without any error."""
    from mktpricing.collect.vendor import CI_SPEC, DEFAQTO_SPEC

    for spec in (CI_SPEC, DEFAQTO_SPEC):
        assert "construction" in spec.columns, spec.name
        assert "occupancy" in spec.columns, spec.name

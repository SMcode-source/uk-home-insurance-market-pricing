"""Tests for the sample vendor extract.

These do double duty. They check the sample generator, but their real job is to
guard `CI_SPEC` and `DEFAULT_VALUE_MAPS` against drift: if someone renames a
column or drops a value mapping, the clean sample stops loading without
problems and these fail. That is a cheaper way to notice than a silent column
of NaNs in training data.

Each flavour asserts the audit finding it exists to demonstrate, so the audits
have an end-to-end test as well as a unit test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from mktpricing.collect.vendor import (
    CI_SPEC,
    BrandResolver,
    DEFAULT_VALUE_MAPS,
    apply_spec,
    audit_extract,
    to_records,
)

# scripts/ is not a package; load the generator by path.
_SPEC_PATH = Path(__file__).resolve().parents[1] / "scripts" / "make_sample_extract.py"
_spec = importlib.util.spec_from_file_location("make_sample_extract", _SPEC_PATH)
sample = importlib.util.module_from_spec(_spec)
sys.modules["make_sample_extract"] = sample
_spec.loader.exec_module(sample)


@pytest.fixture(scope="module")
def frames():
    """One frame per flavour, built once -- the generator is the slow part."""
    return {
        f: sample.build_frame(n_risks=45, n_weeks=3, seed=5, flavour=f)
        for f in sample.FLAVOURS
    }


def _load(df):
    canonical, problems = apply_spec(df, CI_SPEC)
    findings = audit_extract(canonical, CI_SPEC)
    return canonical, findings, problems


def _codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity == severity}


# -- the round trip --------------------------------------------------------


def test_the_clean_sample_loads_with_no_problems(frames):
    """The guard that matters: every label the sample prints must map back
    through CI_SPEC and DEFAULT_VALUE_MAPS."""
    _, _, problems = _load(frames["clean"])
    assert problems == []


def test_the_clean_sample_raises_no_blockers_or_warnings(frames):
    _, findings, _ = _load(frames["clean"])
    assert _codes(findings, "BLOCKER") == set()
    assert _codes(findings, "WARN") == set()


def test_every_vendor_label_round_trips():
    """Explicit version of the above, so a failure names the offending label
    rather than pointing at a problems list."""
    for field_name, labels in sample._LABELS.items():
        vmap = CI_SPEC.value_map(field_name)
        for canonical_value, printed in labels.items():
            assert vmap.get(printed.strip().lower()) == canonical_value, printed


def test_every_vendor_brand_label_resolves():
    r = BrandResolver()
    for canonical, printed in sample._BRAND_LABELS.items():
        assert r.resolve(printed) == canonical, printed


def test_the_labels_cover_every_value_the_generator_emits(frames):
    """A new building type in the synthetic generator must not silently fall
    through to its raw enum name."""
    df = frames["clean"]
    assert set(df.CoverType) <= set(sample._LABELS["policy_type"].values())
    assert set(df.PropertyType) <= set(sample._LABELS["building_type"].values())
    assert set(df.Channel) <= set(sample._LABELS["channel"].values())


def test_labels_are_not_just_the_canonical_values():
    """If they were, the sample would test nothing -- the point is that vendors
    write "Semi-Detached", not "semi_detached"."""
    assert sample._LABELS["building_type"]["semi_detached"] == "Semi-Detached"
    assert sample._BRAND_LABELS["Direct Line"] != "Direct Line"


def test_default_value_maps_are_keyed_lower_case():
    """`_norm_token` lowercases before lookup, so an upper-case key would be
    unreachable and the value silently unmapped."""
    for field_name, m in DEFAULT_VALUE_MAPS.items():
        for k in m:
            assert k == k.lower(), (field_name, k)


# -- flavours --------------------------------------------------------------


def test_clean_has_declines_and_a_plausible_premium(frames):
    _, findings, _ = _load(frames["clean"])
    assert "declines" in _codes(findings, "INFO")
    assert "premium_basis" in _codes(findings, "INFO")


def test_no_status_forces_inference_and_says_so(frames):
    """Without a status column, quoted has to be inferred from whether a
    premium came back. That is the right inference, but it is an inference."""
    df = frames["no-status"]
    assert "Status" not in df.columns
    canonical, _, problems = _load(df)
    assert any("does not have" in p and "Status" in p for p in problems)
    assert canonical.quoted.any() and not canonical.quoted.all()


def test_no_declines_flavour_fires_the_declines_finding(frames):
    _, findings, _ = _load(frames["no-declines"])
    assert "no_declines" in _codes(findings)


def test_monthly_flavour_is_caught_by_the_premium_sanity_check(frames):
    """The spec still declares annual. The audit must catch the contradiction
    from the distribution alone."""
    _, findings, _ = _load(frames["monthly"])
    assert "premium_basis" in _codes(findings, "BLOCKER")


def test_truncated_flavour_is_flagged(frames):
    df = frames["truncated"]
    _, findings, _ = _load(df)
    assert "possible_truncation" in _codes(findings, "WARN")


def test_rotating_flavour_is_flagged_as_unindexable(frames):
    _, findings, _ = _load(frames["rotating"])
    assert "rotating_panel" in _codes(findings, "WARN")


def test_rotating_flavour_actually_rotates(frames):
    """Regression: the generator's first 40 risks are a fixed basket, so a
    small population left no rotating pool and the flavour produced nothing."""
    df = frames["rotating"]
    assert len(df) > 0
    by_date = df.groupby("QuoteDate").QuoteReference.apply(set)
    first, last = by_date.iloc[0], by_date.iloc[-1]
    assert len(first & last) / len(first | last) < 0.5


def test_premiums_only_flavour_blocks_on_missing_risk_attributes(frames):
    _, findings, _ = _load(frames["premiums-only"])
    assert "no_risk_attributes" in _codes(findings, "BLOCKER")


def test_messy_flavour_exercises_every_reporting_path(frames):
    canonical, findings, problems = _load(frames["messy"])
    assert any("Wibble Mutual" in p for p in problems)
    assert any("Houseboat" in p for p in problems)
    assert any("unparseable as a date" in p for p in problems)
    assert "duplicates" in _codes(findings, "WARN")
    assert "unmapped_brands" in _codes(findings, "WARN")


def test_messy_currency_formatting_still_parses(frames):
    """Some premiums are written "£1,234.00". They must arrive as numbers, not
    as nulls that quietly become declines."""
    df = frames["messy"]
    assert df.AnnualPremium.str.startswith("£").any()
    canonical, _, _ = _load(df)
    priced = canonical[canonical.quoted]
    assert priced.premium.notna().all()
    assert priced.premium.median() > 90


# -- the contract with the rest of the pipeline ----------------------------


def test_the_clean_sample_reaches_the_feature_builder(frames):
    """End to end: a vendor-shaped file must arrive at the models through the
    same door a hand-collected quote does."""
    from mktpricing.features.build import build_matrix

    canonical, _, _ = _load(frames["clean"])
    risks, quotes, problems = to_records(canonical)
    assert problems == []
    assert len(risks) > 10 and len(quotes) > 100

    # geo.py supplies these from the postcode; stubbed so this test stays about
    # the vendor contract rather than about geodata files.
    risks = risks.assign(
        flood_band=0.0, crime_index=0.3, subsidence_band=0.0, area_avg_value=300000.0
    )
    quotes = quotes.assign(week=0)

    m = build_matrix(quotes, risks)
    assert len(m) == int(quotes.quoted.sum())
    np.testing.assert_allclose(np.exp(m.log_premium), m.premium, rtol=1e-9)


def test_declines_survive_the_round_trip_without_a_premium(frames):
    canonical, _, _ = _load(frames["clean"])
    _, quotes, _ = to_records(canonical)
    declined = quotes[~quotes.quoted]
    assert len(declined) > 0
    assert declined.premium.isna().all()


def test_writing_and_rereading_the_file_changes_nothing(tmp_path, frames):
    """CSV is lossy about types. The audit verdict must not depend on whether
    the frame came from memory or from disk."""
    from mktpricing.collect.vendor import read_extract

    path = tmp_path / "sample.csv"
    frames["clean"].to_csv(path, index=False, encoding="utf-8")
    _, from_disk, problems = _load(read_extract(path))
    _, from_memory, _ = _load(frames["clean"])
    assert problems == []
    assert _codes(from_disk) == _codes(from_memory)

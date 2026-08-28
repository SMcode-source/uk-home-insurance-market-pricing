"""Tests for postcode parsing and geo enrichment.

Parsing is pure and fully covered. The loaders are tested against small CSVs in
the *published* shape of each source, so a change to a government file layout
shows up as a failing test rather than a column of NaNs in training data.

The theme throughout: an unresolved postcode must produce NaN and a False flag,
never a plausible default. Every test that could pass by silently defaulting is
written to fail if it does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mktpricing.features.geo import (
    BgsSubsidence,
    EnvironmentAgencyFlood,
    GeoEnricher,
    ImdDeprivation,
    LandRegistryValue,
    OnspdLookup,
    PoliceCrime,
    REQUIRED_GEO_COLUMNS,
    _pick_column,
    add_postcode_parts,
    check_ready_for_modelling,
    default_sources,
    missing_files,
    normalise_postcode,
    parse_postcode,
)


def _write(path, lines):
    """Write a CSV from a list of rows. Keeps test fixtures readable as tables."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- normalisation ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["BS1 4DJ", "bs1 4dj", "BS14DJ", "  bs1  4DJ  ", "BS1-4DJ", "bs1.4dj"],
)
def test_normalise_accepts_every_spelling_of_one_postcode(raw):
    assert normalise_postcode(raw) == "BS1 4DJ"


@pytest.mark.parametrize("bad", [None, "", "   ", "NOT A POSTCODE", "12", np.nan])
def test_normalise_returns_none_rather_than_a_mangling(bad):
    """None is a clear signal. A half-parsed string would join to nothing and
    look like a data problem in the wrong place."""
    assert normalise_postcode(bad) is None


# -- parsing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "pc,area,district,outcode,sector,unit",
    [
        ("BS1 4DJ", "BS", "1", "BS1", "BS1 4", "DJ"),
        ("M1 1AE", "M", "1", "M1", "M1 1", "AE"),
        ("SW1A 1AA", "SW", "1A", "SW1A", "SW1A 1", "AA"),
        ("EC1A 1BB", "EC", "1A", "EC1A", "EC1A 1", "BB"),
        ("W1A 0AX", "W", "1A", "W1A", "W1A 0", "AX"),
        ("DN55 1PT", "DN", "55", "DN55", "DN55 1", "PT"),
        ("CR2 6XH", "CR", "2", "CR2", "CR2 6", "XH"),
    ],
)
def test_parse_splits_real_postcodes_correctly(pc, area, district, outcode, sector, unit):
    p = parse_postcode(pc)
    assert p.valid
    assert (p.area, p.district, p.outcode, p.sector, p.unit) == (
        area, district, outcode, sector, unit
    )


def test_sector_is_outcode_plus_first_incode_digit():
    """Sector is the rating granularity most UK insurers use, so this is the
    join key that matters most."""
    assert parse_postcode("BS1 4DJ").sector == "BS1 4"
    assert parse_postcode("SW1A 1AA").sector == "SW1A 1"


@pytest.mark.parametrize("bad", ["ZZ1 1ZZ", "QQ1 1AA", "BS1 4CJ", "BS1 4DI", "AAAA AAA"])
def test_invalid_letters_are_rejected(bad):
    """The inward code excludes C, I, K, M, O and V; the first outward letter
    excludes Q, V and X. Rejecting these catches transcription errors that a
    loose pattern would let through into an unjoinable postcode."""
    assert not parse_postcode(bad).valid


def test_gir_0aa_is_valid():
    """Historic Girobank postcode. Real, matches no pattern, still shows up in
    address data."""
    p = parse_postcode("gir0aa")
    assert p.valid and p.normalised == "GIR 0AA"


def test_parse_never_raises_on_junk():
    for junk in [None, "", 42, "!!!", np.nan, "SW1A"]:
        assert parse_postcode(junk).valid in (True, False)


def test_scotland_and_ni_are_flagged():
    """Several English sources do not cover these, and finding that out from a
    coverage report beats finding it out from a model."""
    assert parse_postcode("EH1 1YZ").is_scotland_or_ni
    assert parse_postcode("BT1 5GS").is_scotland_or_ni
    assert not parse_postcode("BS1 4DJ").is_scotland_or_ni


def test_add_postcode_parts_keeps_the_original_text():
    df = pd.DataFrame({"postcode": ["bs14dj", "rubbish"]})
    out = add_postcode_parts(df)
    assert out.postcode.iloc[0] == "BS1 4DJ"
    assert out.postcode.isna().iloc[1]      # never "RUBB ISH"
    assert list(out.postcode_raw) == ["bs14dj", "rubbish"]
    assert list(out.postcode_valid) == [True, False]
    assert out.sector.iloc[0] == "BS1 4"
    assert out.sector.isna().iloc[1]


# -- column matching -------------------------------------------------------


def test_pick_column_error_names_the_columns_actually_present():
    """The error has to be actionable without opening the file."""
    df = pd.DataFrame({"Weird Name": [1]})
    with pytest.raises(KeyError, match="Weird Name"):
        _pick_column(df, ["postcode"], "postcode")


# -- Environment Agency flood ---------------------------------------------


@pytest.fixture()
def flood_csv(tmp_path):
    p = tmp_path / "flood.csv"
    p.write_text(
        "Postcode,Very Low,Low,Medium,High\n"
        "BS1 4DJ,10,0,0,0\n"      # clean: band 0
        "M1 1AE,5,3,0,0\n"        # highest occupied is Low -> band 1
        "SW1A 1AA,20,0,0,2\n"     # 2 High properties -> band 3, not band 0
        "CR2 6XH,0,0,4,0\n",      # band 2
        encoding="utf-8",
    )
    return p


def test_flood_band_uses_the_highest_occupied_category(flood_csv):
    """Modal category would call SW1A 1AA low risk. An underwriter would not:
    a postcode with any High-likelihood properties is not a band 0 postcode."""
    t = EnvironmentAgencyFlood(flood_csv).table().set_index("postcode")
    assert t.loc["BS1 4DJ", "flood_band"] == 0
    assert t.loc["M1 1AE", "flood_band"] == 1
    assert t.loc["CR2 6XH", "flood_band"] == 2
    assert t.loc["SW1A 1AA", "flood_band"] == 3


def test_flood_low_column_is_not_captured_by_very_low(flood_csv):
    """Regression: "low" is a substring of "verylow", so naive substring
    matching hands band 1 the Very Low column and shifts every band down."""
    cols = EnvironmentAgencyFlood._match_category_columns(
        ["Postcode", "Very Low", "Low", "Medium", "High"]
    )
    assert cols[0] == "Very Low"
    assert cols[1] == "Low"
    assert cols[2] == "Medium"
    assert cols[3] == "High"


def test_flood_matches_underscored_column_names():
    """Published headers get renamed between releases; snake_case is the other
    form these files ship in."""
    cols = EnvironmentAgencyFlood._match_category_columns(
        ["postcode", "very_low_count", "low_count", "medium_count", "high_count"]
    )
    assert cols[0] == "very_low_count"
    assert cols[1] == "low_count"


def test_flood_high_share_is_a_proportion(flood_csv):
    t = EnvironmentAgencyFlood(flood_csv).table().set_index("postcode")
    assert t.loc["SW1A 1AA", "flood_high_share"] == pytest.approx(2 / 22)
    assert t.loc["BS1 4DJ", "flood_high_share"] == 0.0


def test_flood_loader_fails_loudly_on_unrecognised_columns(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("Postcode,Something,Else\nBS1 4DJ,1,2\n", encoding="utf-8")
    with pytest.raises(KeyError, match="flood likelihood"):
        EnvironmentAgencyFlood(p).table()


# -- Land Registry ---------------------------------------------------------


def _ppd_rows(sector_postcodes, price):
    """Raw Price Paid rows in the published 16-column order, no header."""
    rows = []
    for i, pc in enumerate(sector_postcodes):
        rows.append(
            f'"{{GUID-{i}}}","{price}","2025-01-01 00:00","{pc}","D","N","F",'
            f'"1","","A STREET","","BRISTOL","BRISTOL","BRISTOL","A","A"'
        )
    return "\n".join(rows) + "\n"


def test_land_registry_reads_the_raw_headerless_file(tmp_path):
    p = tmp_path / "pp.csv"
    p.write_text(
        _ppd_rows(["BS1 4DJ"] * 3, 300000) + _ppd_rows(["BS1 4AA"] * 3, 400000),
        encoding="utf-8",
    )
    t = LandRegistryValue(p, min_sales=5).table()
    # Both postcodes are in sector BS1 4, so six sales land in one sector.
    assert list(t.sector) == ["BS1 4"]
    assert t.area_avg_value.iloc[0] == pytest.approx(350000.0)


def test_land_registry_drops_thin_sectors(tmp_path):
    """A sector median from two sales is noise wearing a feature's name."""
    p = tmp_path / "pp.csv"
    p.write_text(_ppd_rows(["BS1 4DJ"] * 2, 300000), encoding="utf-8")
    assert LandRegistryValue(p, min_sales=5).table().empty


def test_land_registry_uses_median_not_mean(tmp_path):
    """PPD carries occasional very large transactions; a mean would follow
    them and overstate the area."""
    p = tmp_path / "pp.csv"
    p.write_text(
        _ppd_rows(["BS1 4DJ"] * 5, 300000) + _ppd_rows(["BS1 4AA"], 9_000_000),
        encoding="utf-8",
    )
    t = LandRegistryValue(p, min_sales=5).table()
    assert t.area_avg_value.iloc[0] == pytest.approx(300000.0)


def test_land_registry_reads_a_headered_export(tmp_path):
    p = tmp_path / "std.csv"
    p.write_text(
        "postcode,price,date_of_transfer\n"
        + "".join(f"BS1 4DJ,{300000 + i},2025-01-01\n" for i in range(6)),
        encoding="utf-8",
    )
    t = LandRegistryValue(p, min_sales=5).table()
    assert list(t.sector) == ["BS1 4"]


# -- IMD, crime, ONSPD, subsidence ----------------------------------------


def test_imd_reads_the_postcode_export(tmp_path):
    p = tmp_path / "imd.csv"
    p.write_text(
        "Postcode,Index of Multiple Deprivation Decile\nBS1 4DJ,7\nm1 1ae,2\n",
        encoding="utf-8",
    )
    t = ImdDeprivation(p).table().set_index("postcode")
    assert t.loc["BS1 4DJ", "imd_decile"] == 7
    assert "M1 1AE" in t.index  # normalised on the way in


def test_crime_index_is_rank_normalised_not_a_raw_count(tmp_path):
    """Raw counts track LSOA population and how many months you downloaded.
    A percentile is stable against both."""
    d = tmp_path / "police"
    d.mkdir()
    (d / "2025-01-avon-street.csv").write_text(
        "Crime ID,LSOA code\n" + "".join("x,E01000001\n" for _ in range(50))
        + "y,E01000002\n",
        encoding="utf-8",
    )
    t = PoliceCrime(d).table().set_index("lsoa")
    assert t.loc["E01000001", "crime_index"] == 1.0
    assert 0.0 < t.loc["E01000002", "crime_index"] < 1.0


def test_onspd_bridges_postcode_to_lsoa(tmp_path):
    p = tmp_path / "onspd.csv"
    p.write_text("pcds,lsoa11\nBS1 4DJ,E01000001\n", encoding="utf-8")
    t = OnspdLookup(p).table()
    assert t.set_index("postcode").loc["BS1 4DJ", "lsoa"] == "E01000001"


def test_subsidence_source_is_interface_only_but_joins_a_supplied_file(tmp_path):
    """BGS GeoSure is licensed, so no loader ships. Supplying the documented
    two-column shape must work."""
    p = tmp_path / "sub.csv"
    p.write_text("postcode,subsidence_band\nBS1 4DJ,2\n", encoding="utf-8")
    t = BgsSubsidence(p).table()
    assert t.subsidence_band.iloc[0] == 2


# -- enrichment ------------------------------------------------------------


@pytest.fixture()
def risks():
    return pd.DataFrame(
        {
            "risk_id": ["R1", "R2", "R3"],
            "postcode": ["BS1 4DJ", "M1 1AE", "rubbish"],
        }
    )


def test_unresolved_postcodes_get_nan_not_a_default(risks, flood_csv):
    """The cardinal rule. A default flood band on an unresolved postcode is a
    confident wrong prediction that nothing downstream can detect."""
    e = GeoEnricher([EnvironmentAgencyFlood(flood_csv)])
    out = e.enrich(risks)
    bad = out[out.risk_id == "R3"]
    assert bad.flood_band.isna().all()
    assert not bad.flood_band_resolved.any()
    assert out[out.risk_id == "R1"].flood_band_resolved.all()


def test_enrichment_never_changes_the_row_count(risks, flood_csv, tmp_path):
    """A duplicated key in a reference file would silently fan out the training
    set and reweight it."""
    dup = tmp_path / "dup.csv"
    dup.write_text(
        "Postcode,Very Low,Low,Medium,High\nBS1 4DJ,1,0,0,0\nBS1 4DJ,0,0,0,9\n",
        encoding="utf-8",
    )
    out = GeoEnricher([EnvironmentAgencyFlood(dup)]).enrich(risks)
    assert len(out) == len(risks)


def test_missing_source_file_is_a_note_not_a_crash(risks, tmp_path):
    e = GeoEnricher([EnvironmentAgencyFlood(tmp_path / "absent.csv")])
    out = e.enrich(risks)
    assert len(out) == len(risks)
    assert any("skipped" in n for n in e.notes)


def test_onspd_is_applied_before_lsoa_keyed_sources_whatever_the_order(risks, tmp_path):
    """PoliceCrime is LSOA-keyed. Listing it before ONSPD must still work, or
    source ordering becomes an invisible correctness trap."""
    onspd = tmp_path / "onspd.csv"
    onspd.write_text(
        "pcds,lsoa11\nBS1 4DJ,E01000001\nM1 1AE,E01000002\n", encoding="utf-8"
    )
    police = tmp_path / "police"
    police.mkdir()
    (police / "2025-01-street.csv").write_text(
        "Crime ID,LSOA code\n" + "".join("x,E01000001\n" for _ in range(9))
        + "y,E01000002\n",
        encoding="utf-8",
    )
    out = GeoEnricher([PoliceCrime(police), OnspdLookup(onspd)]).enrich(risks)
    assert out.set_index("risk_id").loc["R1", "crime_index"] == 1.0
    assert out.set_index("risk_id").loc["R3", "crime_index"] != out.set_index(
        "risk_id"
    ).loc["R3", "crime_index"]  # NaN


def test_lsoa_source_without_a_bridge_warns_rather_than_silently_skipping(
    risks, tmp_path
):
    police = tmp_path / "police"
    police.mkdir()
    (police / "2025-01-street.csv").write_text(
        "Crime ID,LSOA code\nx,E01000001\n", encoding="utf-8"
    )
    e = GeoEnricher([PoliceCrime(police)])
    e.enrich(risks)
    assert any("onspd" in n for n in e.notes)


def test_coverage_reports_the_resolution_rate(risks, flood_csv):
    e = GeoEnricher([EnvironmentAgencyFlood(flood_csv)])
    cov = e.coverage(e.enrich(risks))
    row = cov[cov.column == "flood_band"].iloc[0]
    assert row.resolved_pct == pytest.approx(66.7, abs=0.1)
    assert row.missing == 1


# -- the gate before training ---------------------------------------------


def test_check_ready_rejects_partly_resolved_features(risks, flood_csv):
    """The failure this prevents is the quiet one: a model trained with a third
    of its flood bands missing still fits, still scores, and is still wrong."""
    out = GeoEnricher([EnvironmentAgencyFlood(flood_csv)]).enrich(risks)
    with pytest.raises(ValueError, match="only 66.7% resolved"):
        check_ready_for_modelling(out)


def test_check_ready_names_absent_columns(risks):
    out = GeoEnricher([]).enrich(risks)
    with pytest.raises(ValueError, match="column absent"):
        check_ready_for_modelling(out)


def test_check_ready_passes_when_everything_resolves():
    df = pd.DataFrame(
        {
            "flood_band": [0.0, 1.0],
            "crime_index": [0.2, 0.8],
            "subsidence_band": [0.0, 2.0],
            "area_avg_value": [300000.0, 450000.0],
        }
    )
    assert check_ready_for_modelling(df) is True


# -- standard layout -------------------------------------------------------


def test_default_sources_are_all_optional(risks, tmp_path):
    """You must be able to start with one file and add the rest later."""
    e = GeoEnricher(default_sources(tmp_path))
    out = e.enrich(risks)
    assert len(out) == len(risks)
    # No file present, so no geo feature appears -- and crucially none is
    # invented. Every absent source says so rather than failing silently.
    assert not set(REQUIRED_GEO_COLUMNS) & set(out.columns)
    for src in default_sources(tmp_path):
        assert any(src.name in n for n in e.notes), src.name


def test_missing_files_lists_urls_for_what_is_absent(tmp_path):
    m = missing_files(tmp_path)
    assert len(m) == 6
    assert m.url.str.startswith("https://").all()
    assert m[m.file == "subsidence.csv"].licence.iloc[0].startswith("LICENSED")


def test_missing_files_shrinks_as_files_arrive(tmp_path, flood_csv):
    import shutil

    shutil.copy(flood_csv, tmp_path / "ea_flood.csv")
    assert "ea_flood.csv" not in set(missing_files(tmp_path).file)


def test_end_to_end_from_the_standard_layout(risks, tmp_path):
    """The whole point: real postcodes in, model-ready risk features out."""
    _write(tmp_path / "ea_flood.csv", [
        "Postcode,Very Low,Low,Medium,High",
        "BS1 4DJ,10,0,0,0",
        "M1 1AE,1,0,2,0",
    ])
    _write(tmp_path / "price_paid.csv", [
        "postcode,price,date_of_transfer",
        *[f"BS1 4DJ,{300000 + i},2025-01-01" for i in range(6)],
        *[f"M1 1AE,{200000 + i},2025-01-01" for i in range(6)],
    ])
    _write(tmp_path / "subsidence.csv", [
        "postcode,subsidence_band", "BS1 4DJ,1", "M1 1AE,0",
    ])
    _write(tmp_path / "onspd.csv", [
        "pcds,lsoa11", "BS1 4DJ,E01000001", "M1 1AE,E01000002",
    ])
    (tmp_path / "police").mkdir()
    _write(tmp_path / "police" / "2025-01-street.csv", [
        "Crime ID,LSOA code",
        *["x,E01000001"] * 9,
        "y,E01000002",
    ])

    out = GeoEnricher(default_sources(tmp_path)).enrich(risks)
    resolved = out[out.postcode_valid]
    assert len(resolved) == 2
    for col in ("flood_band", "crime_index", "subsidence_band", "area_avg_value"):
        assert resolved[col].notna().all(), col
    assert check_ready_for_modelling(resolved) is True
    # The junk postcode stays visibly unresolved rather than being defaulted.
    assert out[~out.postcode_valid].flood_band.isna().all()


def test_enriched_frame_feeds_the_model_matrix(risks, tmp_path):
    """geo.py's output has to be what build.py expects, or the two halves of
    the pipeline only look joined."""
    from mktpricing.features.build import OPTIONAL_NUMERIC, feature_columns

    _write(tmp_path / "ea_flood.csv", [
        "Postcode,Very Low,Low,Medium,High",
        "BS1 4DJ,10,0,0,0",
        "M1 1AE,1,0,2,0",
    ])
    out = GeoEnricher([EnvironmentAgencyFlood(tmp_path / "ea_flood.csv")]).enrich(risks)
    assert "flood_band" in feature_columns()
    # flood_high_share is optional: picked up only because enrichment supplied it
    assert "flood_high_share" in OPTIONAL_NUMERIC
    assert "flood_high_share" in feature_columns(df=out)
    assert "flood_high_share" not in feature_columns(df=risks)



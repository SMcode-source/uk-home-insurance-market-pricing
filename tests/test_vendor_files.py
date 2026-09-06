"""Tests for the ways a vendor file can arrive, and for specs as config.

The adapter's mapping logic is covered in test_vendor.py. These pin the layer
around it: the file formats a vendor actually sends (Excel with title rows,
semicolon CSV, gzipped daily files, a folder of them), the YAML form of a
spec, and the wide brands-across layout -- each of which would otherwise be
the reason the first real delivery does not load.
"""

from __future__ import annotations

import datetime as _dt
import zipfile

import pandas as pd
import pytest

from mktpricing.collect.vendor import (
    CI_SPEC,
    PEARSON_HAM_SPEC,
    SPECS,
    SPEC_DIR,
    VendorSpec,
    apply_spec,
    draft_spec,
    expand_paths,
    load_spec,
    load_vendor_extract,
    melt_wide,
    read_extract,
    read_extracts,
    suggest_spec,
)
from mktpricing.schema import Source

# A small extract in CI_SPEC's vendor column names.
_COLS = {
    "QuoteReference": ["R1", "R1", "R1", "R2", "R2", "R2"],
    "Brand": ["Aviva", "AXA", "Admiral"] * 2,
    "Channel": ["Compare the Market"] * 6,
    "QuoteDate": ["01/07/2026"] * 6,
    "Status": ["Quoted", "Quoted", "Declined", "Quoted", "Quoted", "Quoted"],
    "AnnualPremium": ["£310.00", "£295.50", "", "£410.00", "£380.00", "£500.00"],
    "Rank": ["2", "1", "", "2", "1", "3"],
    "Postcode": ["BS1 4DJ"] * 3 + ["LS1 6RP"] * 3,
    "CoverType": ["Buildings & Contents"] * 6,
    "PropertyType": ["Semi-Detached"] * 6,
    "ConstructionType": ["Standard"] * 6,
    "OccupancyType": ["Owner Occupied"] * 6,
    "YearBuilt": ["1930"] * 6,
    "Bedrooms": ["3"] * 6,
    "BuildingsSumInsured": ["250,000"] * 6,
    "ContentsSumInsured": ["45,000"] * 6,
    "VoluntaryExcess": ["250"] * 6,
    "CompulsoryExcess": ["100"] * 6,
    "ClaimsCount": ["0"] * 6,
    "AccidentalDamage": ["No"] * 6,
}


def _frame():
    return pd.DataFrame(_COLS)


def _canonical_ok(canonical):
    assert len(canonical) == 6
    assert canonical.brand.tolist() == ["Aviva", "AXA", "Admiral"] * 2
    assert canonical.premium.tolist()[:2] == [310.0, 295.5]
    assert canonical.quoted.tolist() == [True, True, False, True, True, True]
    assert canonical.collected_on.iloc[0] == _dt.date(2026, 7, 1)


# -- formats -----------------------------------------------------------------


def test_semicolon_csv_is_sniffed(tmp_path):
    p = tmp_path / "x.csv"
    _frame().to_csv(p, sep=";", index=False)
    df = read_extract(p)
    assert list(df.columns) == list(_COLS)
    canonical, problems = apply_spec(df, CI_SPEC)
    _canonical_ok(canonical)


def test_pipe_and_tab_delimiters(tmp_path):
    for sep, name in (("|", "x.txt"), ("\t", "x.tsv")):
        p = tmp_path / name
        _frame().to_csv(p, sep=sep, index=False)
        assert list(read_extract(p).columns) == list(_COLS), name


def test_gzipped_csv_with_a_non_default_delimiter(tmp_path):
    p = tmp_path / "x.csv.gz"
    _frame().to_csv(p, sep=";", index=False, compression="gzip")
    assert list(read_extract(p).columns) == list(_COLS)


def test_zipped_csv(tmp_path):
    inner = tmp_path / "daily.csv"
    _frame().to_csv(inner, index=False)
    p = tmp_path / "daily.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.write(inner, arcname="daily.csv")
    assert list(read_extract(p).columns) == list(_COLS)


def test_excel_named_sheet_with_title_rows(tmp_path):
    """The shape an Excel 'raw data' tab usually has: a title above the header
    and other tabs beside it."""
    p = tmp_path / "market_view.xlsx"
    with pd.ExcelWriter(p) as xw:
        pd.DataFrame({"a": ["Cover sheet"]}).to_excel(xw, sheet_name="Cover", index=False)
        pd.DataFrame({"a": ["Home Insurance -- raw data", None]}).to_excel(
            xw, sheet_name="Raw Data", index=False, header=False
        )
        _frame().to_excel(xw, sheet_name="Raw Data", index=False, startrow=2)

    df = read_extract(p, sheet="Raw Data", header_row=2)
    assert list(df.columns) == list(_COLS)
    assert df["BuildingsSumInsured"].iloc[0] == "250,000"   # text, not 250000.0

    # the spec carries the layout, so a caller need not remember it
    spec = VendorSpec.from_dict({**CI_SPEC.to_dict(), "sheet": "Raw Data", "header_row": 2})
    canonical, problems = apply_spec(p, spec)
    _canonical_ok(canonical)


def test_json_records(tmp_path):
    p = tmp_path / "x.json"
    _frame().to_json(p, orient="records")
    assert set(read_extract(p).columns) == set(_COLS)


def test_cp1252_falls_back_when_utf8_fails(tmp_path):
    p = tmp_path / "x.csv"
    df = _frame()
    df.loc[0, "Brand"] = "Aviva – Home"     # en dash, not representable in ascii
    p.write_bytes(df.to_csv(index=False).encode("cp1252"))
    out = read_extract(p)
    assert "Aviva" in out.loc[0, "Brand"]


def test_missing_file_is_an_error_not_an_empty_frame(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_extract(tmp_path / "nope.csv")


# -- many files --------------------------------------------------------------


def _weekly_folder(tmp_path):
    d = tmp_path / "weekly"
    d.mkdir()
    for i, day in enumerate(("01/07/2026", "08/07/2026", "15/07/2026")):
        f = _frame()
        f["QuoteDate"] = day
        f.to_csv(d / f"ph_2026-07-{1 + 7 * i:02d}.csv", index=False)
    (d / "ph_2026-07-01.NOTE.txt").write_text("sidecar", encoding="utf-8")
    (d / ".hidden.csv").write_text("x", encoding="utf-8")
    return d


def test_a_folder_a_glob_and_a_list_all_expand_to_the_same_files(tmp_path):
    d = _weekly_folder(tmp_path)
    by_dir = expand_paths(d)
    by_glob = expand_paths(str(d / "ph_*.csv"))
    by_list = expand_paths([d / "ph_2026-07-01.csv", d / "ph_2026-07-08.csv", d / "ph_2026-07-15.csv"])
    assert [p.name for p in by_dir] == [p.name for p in by_glob] == [p.name for p in by_list]
    assert len(by_dir) == 3        # sidecar and hidden file skipped


def test_stacked_files_carry_their_source_file_through_to_canonical(tmp_path):
    d = _weekly_folder(tmp_path)
    raw = read_extracts(d)
    assert len(raw) == 18
    assert raw["source_file"].nunique() == 3
    canonical, problems = apply_spec(d, CI_SPEC)
    assert canonical["source_file"].nunique() == 3
    assert canonical.collected_on.nunique() == 3
    # source_file must not be mistaken for an overlooked feature column
    assert not any("source_file" in p for p in problems)


def test_load_vendor_extract_takes_a_folder_and_a_spec_name(tmp_path):
    d = _weekly_folder(tmp_path)
    risks, quotes, findings, problems = load_vendor_extract(d, "ci")
    assert len(risks) == 2 and len(quotes) == 18
    assert {f.code for f in findings} >= {"declines", "fixed_basket"}


def test_an_empty_folder_is_an_error(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        read_extracts(tmp_path / "empty")


# -- specs as config -----------------------------------------------------------


def test_spec_round_trips_through_yaml(tmp_path):
    p = tmp_path / "ci.yml"
    CI_SPEC.to_yaml(p)
    back = VendorSpec.from_yaml(p)
    assert back == CI_SPEC


@pytest.mark.parametrize("name", sorted(SPECS))
def test_the_shipped_yaml_specs_match_the_python_specs(name):
    """config/vendor_specs/<name>.yml and SPECS[name] are the same object in two
    forms. If one is corrected, the other must follow, or `--spec ci` and
    `SPECS['ci']` silently load different mappings."""
    path = SPEC_DIR / f"{name}.yml"
    assert path.exists(), path
    assert VendorSpec.from_yaml(path) == SPECS[name]


def test_load_spec_accepts_a_name_a_stem_and_a_path(tmp_path):
    assert load_spec("pearson_ham") == PEARSON_HAM_SPEC
    assert load_spec(PEARSON_HAM_SPEC) is PEARSON_HAM_SPEC
    p = tmp_path / "mine.yml"
    PEARSON_HAM_SPEC.to_yaml(p)
    assert load_spec(p) == PEARSON_HAM_SPEC
    assert load_spec(str(p)) == PEARSON_HAM_SPEC


def test_load_spec_reports_unknown_names_and_missing_files(tmp_path):
    with pytest.raises(KeyError):
        load_spec("nobody")
    with pytest.raises(FileNotFoundError):
        load_spec(tmp_path / "missing.yml")


def test_a_spec_file_with_a_typo_key_is_rejected():
    with pytest.raises(ValueError, match="unknown key"):
        VendorSpec.from_dict({"name": "x", "colums": {}})
    with pytest.raises(ValueError, match="layout"):
        VendorSpec.from_dict({"name": "x", "layout": "sideways"})
    with pytest.raises(ValueError):
        VendorSpec.from_dict({"name": "x", "source": "vendor_nobody"})


def test_each_shipped_spec_has_its_own_provenance():
    assert {s.source for s in SPECS.values()} == {
        Source.vendor_ci.value, Source.vendor_ph.value, Source.vendor_dfq.value,
    }


def test_the_drafted_yaml_spec_loads_back(tmp_path):
    text = suggest_spec(_frame(), name="CI draft", fmt="yaml")
    p = tmp_path / "draft.yml"
    p.write_text(text, encoding="utf-8")
    spec = VendorSpec.from_yaml(p)
    assert spec.name == "CI draft"
    assert spec.columns["premium"] == "AnnualPremium"
    assert spec.declines_included is None          # left for the vendor to confirm
    assert "CONFIRM" in spec.notes
    canonical, _ = apply_spec(_frame(), spec)
    _canonical_ok(canonical)


def test_draft_spec_python_and_yaml_carry_the_same_mapping():
    d = draft_spec(_frame())
    py = suggest_spec(_frame(), fmt="python")
    for canon, col in d.columns.items():
        assert f'"{canon}": "{col}"' in py


# -- the vendor's own underwriter column ---------------------------------------


def test_a_vendor_underwriter_column_is_kept_but_the_config_wins():
    df = pd.DataFrame({
        "RiskRef": ["R1", "R1"], "Brand": ["Churchill", "AXA"],
        "Underwriter": ["U K Insurance Limited", "AXA Insurance UK plc"],
        "PCW": ["Compare the Market"] * 2, "PriceDate": ["01/07/2026"] * 2,
        "AnnualPremium": ["300", "310"], "QuoteStatus": ["Quoted"] * 2,
        "Position": ["1", "2"], "Postcode": ["BS1 4DJ"] * 2,
        "CoverType": ["Buildings & Contents"] * 2, "PropertyType": ["Detached"] * 2,
        "Construction": ["Standard"] * 2, "Occupancy": ["Owner Occupied"] * 2,
        "YearBuilt": ["1990"] * 2, "Bedrooms": ["4"] * 2,
        "BuildingsSumInsured": ["300000"] * 2, "ContentsSumInsured": ["50000"] * 2,
        "VoluntaryExcess": ["250"] * 2, "CompulsoryExcess": ["100"] * 2,
        "Claims5Years": ["0"] * 2, "AccidentalDamage": ["No"] * 2,
    })
    canonical, problems = apply_spec(df, PEARSON_HAM_SPEC)
    assert canonical.underwriter.tolist() == ["Aviva", "AXA"]       # pricing group
    assert canonical.underwriter_raw.tolist()[0] == "U K Insurance Limited"
    assert any("underwriter" in p and "1 row" in p for p in problems)
    assert canonical.source.iloc[0] == "vendor_ph"


# -- wide layout -----------------------------------------------------------------


def _wide():
    return pd.DataFrame({
        "RiskId": ["R1", "R2"],
        "Date": ["01/07/2026", "01/07/2026"],
        "Postcode": ["BS1 4DJ", "LS1 6RP"],
        "PolicyType": ["Buildings & Contents"] * 2,
        "PropertyType": ["Detached"] * 2,
        "BuildingsCover": ["300000"] * 2, "ContentsCover": ["50000"] * 2,
        "VoluntaryExcess": ["250"] * 2, "YearOfConstruction": ["1990"] * 2,
        "NumberOfBedrooms": ["4"] * 2,
        "Aviva": ["£300", "£420"], "AXA": ["310", ""], "Admiral": ["", "450"],
    })


def _wide_spec(**over):
    base = dict(
        name="Wide", source="vendor_dfq", layout="wide", channel_default="pcw_ctm",
        columns={
            "risk_id": "RiskId", "collected_on": "Date", "postcode": "Postcode",
            "policy_type": "PolicyType", "building_type": "PropertyType",
            "buildings_sum_insured": "BuildingsCover", "contents_sum_insured": "ContentsCover",
            "voluntary_excess": "VoluntaryExcess", "year_built": "YearOfConstruction",
            "bedrooms": "NumberOfBedrooms",
        },
    )
    base.update(over)
    return VendorSpec.from_dict(base)


def test_wide_brand_columns_are_inferred_and_melted():
    long, problems = melt_wide(_wide(), _wide_spec())
    assert set(long["brand"]) == {"Aviva", "AXA", "Admiral"}
    assert len(long) == 4                      # two blanks dropped as absent
    canonical, problems = apply_spec(_wide(), _wide_spec())
    assert len(canonical) == 4
    assert canonical.quoted.all()
    assert canonical.channel.tolist() == ["pcw_ctm"] * 4
    assert sorted(canonical.premium) == [300.0, 310.0, 420.0, 450.0]


def test_wide_blank_can_be_declared_a_decline():
    spec = _wide_spec(wide_blank_means="declined",
                      columns={**_wide_spec().columns, "quoted": "Status"})
    canonical, problems = apply_spec(_wide(), spec)
    assert len(canonical) == 6
    assert int((~canonical.quoted).sum()) == 2
    assert canonical.loc[~canonical.quoted, "premium"].isna().all()


def test_wide_declined_needs_a_status_column_to_create():
    with pytest.raises(ValueError, match="quoted"):
        melt_wide(_wide(), _wide_spec(wide_blank_means="declined"))


def test_wide_explicit_brand_list_and_ignore():
    spec = _wide_spec(wide_brand_columns=["Aviva", "AXA"], wide_ignore=["Admiral"])
    long, problems = melt_wide(_wide(), spec)
    assert set(long["brand"]) == {"Aviva", "AXA"}
    spec2 = _wide_spec(wide_brand_columns=["Aviva", "Nobody"])
    long2, problems2 = melt_wide(_wide(), spec2)
    assert any("Nobody" in p for p in problems2)

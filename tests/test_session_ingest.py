"""Tests for the path from a filled-in collection grid to the model's tables.

Until this existed, `read_session` returned dicts and nothing turned them into
the parquet pair `run_poc.py` reads -- the only data source the project can
use without a licence had no way into the pipeline. These pin that path, and
the two things about it that would otherwise fail quietly: a risk defined by
defaults nobody entered, and a brand string folded into the wrong brand.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from mktpricing.collect.session import (
    CollectionSession, append_quotes, read_risk_definitions, read_session,
    session_to_canonical, write_risk_template,
)
from mktpricing.evaluate.adequacy import assess
from mktpricing.features.build import build_matrix

# scripts/ is not a package; load the ingester by path.
_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest_session.py"
_spec = importlib.util.spec_from_file_location("ingest_session", _PATH)
ingest = importlib.util.module_from_spec(_spec)
sys.modules["ingest_session"] = ingest
_spec.loader.exec_module(ingest)


GOOD_RISK = """\
risks:
  - risk_id: MY-HOUSE
    postcode: "BS1 4DJ"
    policy_type: combined
    building_type: semi_detached
    year_built: 1930
    bedrooms: 3
    buildings_sum_insured: 350000
    contents_sum_insured: 50000
    voluntary_excess: 250
    in_basket: true
"""


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- risk definitions ---------------------------------------------------------


def test_the_risk_template_does_not_validate_until_filled_in(tmp_path):
    """Blank required fields fail on purpose: a skeleton must never describe a
    property nobody quoted."""
    p = write_risk_template(tmp_path / "risks.yml", ["MY-HOUSE"])
    risks, problems = read_risk_definitions(p)
    assert risks.empty
    assert problems and "MY-HOUSE" in problems[0]


def test_risk_definitions_pass_through_the_schema(tmp_path):
    p = tmp_path / "risks.yml"
    p.write_text(GOOD_RISK, encoding="utf-8")
    risks, problems = read_risk_definitions(p)
    assert problems == []
    assert len(risks) == 1
    row = risks.iloc[0]
    assert row.policy_type == "combined"          # a plain string, not an Enum
    assert row.construction == "standard"         # schema default applied
    assert bool(row.in_basket) is True


def test_a_bad_postcode_is_a_problem_not_a_row(tmp_path):
    p = tmp_path / "risks.yml"
    p.write_text(GOOD_RISK.replace('"BS1 4DJ"', '"BS1"'), encoding="utf-8")
    risks, problems = read_risk_definitions(p)
    assert risks.empty
    assert any("postcode" in s.lower() for s in problems)


def test_a_duplicate_risk_id_is_reported(tmp_path):
    p = tmp_path / "risks.yml"
    p.write_text(GOOD_RISK + GOOD_RISK.split("risks:\n", 1)[1], encoding="utf-8")
    risks, problems = read_risk_definitions(p)
    assert len(risks) == 1
    assert any("twice" in s for s in problems)


# -- session rows -> canonical quotes ------------------------------------------


def _rows(**over):
    base = dict(
        risk_id="MY-HOUSE", brand="Direct Line Insurance", channel="pcw_ctm",
        collected_on=_dt.date(2026, 9, 4), quoted=True, premium=310.0,
        compulsory_excess=None, accidental_damage=None, rank_on_page=3,
        cashback=None, incentive_note=None, collector_note=None, source="manual",
    )
    base.update(over)
    return [base]


def _risks(tmp_path):
    p = tmp_path / "risks.yml"
    p.write_text(GOOD_RISK, encoding="utf-8")
    return read_risk_definitions(p)[0]


def test_brands_resolve_like_a_vendor_extract(tmp_path):
    quotes, problems = session_to_canonical(_rows(), _risks(tmp_path))
    assert problems == []
    assert quotes.brand.tolist() == ["Direct Line"]
    assert quotes.underwriter.tolist() == ["Aviva"]   # DLG has been Aviva's since 1 July 2025
    assert quotes.channel.tolist() == ["pcw_ctm"]
    assert quotes.source.tolist() == ["manual"]
    assert quotes.collected_on.tolist() == [_dt.date(2026, 9, 4)]


def test_an_unknown_brand_is_reported_never_guessed(tmp_path):
    quotes, problems = session_to_canonical(
        _rows(brand="Nobody Mutual"), _risks(tmp_path)
    )
    assert quotes.empty
    assert problems and "providers.yml" in problems[0]


def test_an_undefined_risk_id_is_reported_and_dropped(tmp_path):
    quotes, problems = session_to_canonical(
        _rows(risk_id="MY-BOAT"), _risks(tmp_path)
    )
    assert quotes.empty
    assert problems and "MY-BOAT" in problems[0]


def test_declines_survive_with_no_premium(tmp_path):
    quotes, problems = session_to_canonical(
        _rows(quoted=False, premium=None, rank_on_page=None), _risks(tmp_path)
    )
    assert problems == []
    assert quotes.quoted.tolist() == [False]
    assert quotes.premium.isna().all()


def test_reingesting_a_corrected_grid_replaces_rather_than_duplicates(tmp_path):
    old, _ = session_to_canonical(_rows(premium=300.0), _risks(tmp_path))
    new, _ = session_to_canonical(_rows(premium=310.0), _risks(tmp_path))
    merged, replaced = append_quotes(old, new)
    assert replaced == 1
    assert len(merged) == 1
    assert merged.premium.tolist() == [310.0]

    later, _ = session_to_canonical(
        _rows(collected_on=_dt.date(2026, 9, 11)), _risks(tmp_path)
    )
    merged2, replaced2 = append_quotes(merged, later)
    assert replaced2 == 0 and len(merged2) == 2


# -- the script, end to end ----------------------------------------------------


def _geo_dir(tmp_path):
    d = tmp_path / "geo"
    _write(d / "ea_flood.csv", ["Postcode,Very Low,Low,Medium,High", "BS1 4DJ,10,0,0,0"])
    _write(d / "price_paid.csv", [
        "postcode,price,date_of_transfer",
        *[f"BS1 4DJ,{300000 + i},2025-01-01" for i in range(6)],
    ])
    _write(d / "subsidence.csv", ["postcode,subsidence_band", "BS1 4DJ,1"])
    _write(d / "onspd.csv", ["pcds,lsoa11", "BS1 4DJ,E01000001"])
    _write(d / "police" / "2025-01-street.csv", ["Crime ID,LSOA code", *["x,E01000001"] * 3])
    return d


def _filled_grid(path, on: _dt.date, premiums: dict):
    """Write a template the way start_collection.py does, then fill it in."""
    s = CollectionSession(
        session_id=path.stem, collected_on=on, identity_ref="me",
        risk_ids=["MY-HOUSE"], channels=["pcw_ctm", "direct"],
        brands=list(premiums),
    )
    s.write_template(path)
    grid = pd.read_csv(path, dtype=str, keep_default_na=False)
    for i, row in grid.iterrows():
        p = premiums[row.brand]
        if p is None:                       # asked, declined
            grid.loc[i, "quoted"] = "n"
        else:
            grid.loc[i, "quoted"] = "y"
            grid.loc[i, "premium"] = f"{p * (1.05 if row.channel == 'direct' else 1.0):.2f}"
    # leave one brand entirely blank on one channel: a collection GAP
    grid.loc[(grid.brand == "AXA") & (grid.channel == "direct"), "quoted"] = ""
    grid.to_csv(path, index=False)
    return path


def test_ingest_script_end_to_end(tmp_path, capsys):
    raw, out = tmp_path / "raw", tmp_path / "processed" / "manual"
    (raw / "risks.yml").parent.mkdir(parents=True)
    (raw / "risks.yml").write_text(GOOD_RISK, encoding="utf-8")
    geo = _geo_dir(tmp_path)

    files = []
    for w in range(3):
        on = _dt.date(2026, 9, 4) + _dt.timedelta(weeks=w)
        files.append(_filled_grid(
            raw / f"2026-W{36 + w}.csv", on,
            {"Aviva": 300.0 + 5 * w, "AXA": 320.0 + 5 * w, "Admiral": None},
        ))

    rc = ingest.main([str(f) for f in files] + [
        "--risks", str(raw / "risks.yml"), "--geo", str(geo), "--out", str(out),
    ])
    text = capsys.readouterr().out
    assert rc == 0, text

    quotes = pd.read_parquet(out / "quotes.parquet")
    risks = pd.read_parquet(out / "risks.parquet")
    # 3 brands x 2 channels x 3 weeks, minus the one blank cell per week
    assert len(quotes) == 3 * 2 * 3 - 3
    assert (~quotes.quoted).sum() == 6          # Admiral declined on both channels
    assert "AXA" in text and "not asked on: direct" in text
    assert quotes.collected_on.nunique() == 3
    for col in ("flood_band", "crime_index", "subsidence_band", "area_avg_value"):
        assert risks[col].notna().all(), col

    # the output is what run_poc.py reads, and adequacy reads it honestly
    df = build_matrix(quotes, risks, quoted_only=True)
    assert len(df) == 3 * 2 * 3 - 3 - 6
    a = assess(df, holdout_weeks=1)
    assert a.tier == "level_only"
    assert "level_only" in text and "run_poc.py" in text
    assert (out / "ingest.json").exists()


def test_reingesting_replaces_and_never_duplicates(tmp_path, capsys):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    (raw / "risks.yml").write_text(GOOD_RISK, encoding="utf-8")
    grid = _filled_grid(raw / "w1.csv", _dt.date(2026, 9, 4), {"Aviva": 300.0})
    args = [str(grid), "--risks", str(raw / "risks.yml"), "--out", str(out)]

    assert ingest.main(args) == 0
    # a typo corrected, the grid re-ingested
    g = pd.read_csv(grid, dtype=str, keep_default_na=False)
    g.loc[g.channel == "pcw_ctm", "premium"] = "290.00"
    g.to_csv(grid, index=False)
    assert ingest.main(args) == 0
    text = capsys.readouterr().out

    quotes = pd.read_parquet(out / "quotes.parquet")
    assert len(quotes) == 2
    assert quotes[quotes.channel == "pcw_ctm"].premium.tolist() == [290.0]
    assert "replaced 2" in text
    # no --geo: written, but said plainly to be not model-ready
    assert "NOT model-ready" in text


def test_ingest_reports_bad_rows_and_still_writes_the_good_ones(tmp_path, capsys):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    (raw / "risks.yml").write_text(GOOD_RISK, encoding="utf-8")
    grid = _filled_grid(raw / "w1.csv", _dt.date(2026, 9, 4),
                        {"Aviva": 300.0, "Nobody Mutual": 250.0})
    rc = ingest.main([str(grid), "--risks", str(raw / "risks.yml"), "--out", str(out)])
    text = capsys.readouterr().out
    assert rc == 1
    assert "Nobody Mutual" in text and "providers.yml" in text
    assert pd.read_parquet(out / "quotes.parquet").brand.tolist() == ["Aviva", "Aviva"]


def test_missing_risk_file_is_exit_2(tmp_path, capsys):
    rc = ingest.main([str(tmp_path / "none.csv"), "--risks", str(tmp_path / "no.yml"),
                      "--out", str(tmp_path / "out")])
    assert rc == 2

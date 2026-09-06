"""Turn filled-in collection grids into the canonical tables the models read.

    python scripts/ingest_session.py data/raw/2026-W36.csv --risks data/raw/risks.yml --geo data/geo
    python scripts/ingest_session.py data/raw/2026-W3*.csv --risks data/raw/risks.yml --geo data/geo

Reads one or more session CSVs (`start_collection.py` writes the grid), the
risk definitions describing what was actually quoted, and:

  1. validates every row through the same pydantic schema a vendor extract
     passes through, resolving brands against config/providers.yml
  2. reports coverage per session -- quoted, declined and MISSING kept apart
  3. appends to whatever is already in --out, replacing rows with the same
     (risk, brand, channel, date) so a corrected grid can be re-ingested
  4. geo-enriches the risks from --geo and runs the model-readiness gate
  5. says what the resulting data can support, and prints the run command

Nothing here touches a website. The grids are filled in by hand, by a real
customer, for a real property; docs/COLLECTION.md states the boundary.

Output goes to its own directory (default data/processed/manual/), never to
data/processed/ itself, where a synthetic run's parquet pair already lives.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mktpricing.collect.session import (  # noqa: E402
    append_quotes, coverage_report, read_risk_definitions, read_session,
    session_to_canonical,
)
from mktpricing.collect.vendor import BrandResolver, load_providers  # noqa: E402
from mktpricing.evaluate.adequacy import assess  # noqa: E402
from mktpricing.features.build import build_matrix  # noqa: E402
from mktpricing.features.geo import (  # noqa: E402
    GeoEnricher, check_ready_for_modelling, default_sources, missing_files,
)


def _rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def _expand(paths) -> list:
    """Windows shells do not expand globs; do it here so `2026-W3*.csv` works."""
    out = []
    for p in paths:
        hits = sorted(glob.glob(str(p)))
        out.extend(Path(h) for h in hits) if hits else out.append(Path(p))
    return out


def _grid_expectations(path: Path):
    """What the template asked for: every brand and channel in the grid,
    filled in or not. That is the denominator the coverage report needs."""
    grid = pd.read_csv(path, dtype=str, keep_default_na=False)
    brands = [b for b in grid["brand"].unique() if b]
    channels = [c for c in grid["channel"].unique() if c]
    return brands, channels


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="+", help="filled-in session CSV(s); globs allowed")
    ap.add_argument("--risks", type=Path, required=True,
                    help="risk definitions YAML (start_collection.py writes the skeleton)")
    ap.add_argument("--geo", type=Path, default=None, metavar="DIR",
                    help="geo reference files, e.g. data/geo; without it the output "
                         "is not model-ready and run_poc.py will refuse it")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "processed" / "manual")
    ap.add_argument("--providers", type=Path, default=ROOT / "config" / "providers.yml")
    ap.add_argument("--weeks-holdout", type=int, default=2,
                    help="what run_poc.py will hold out; used only to say whether "
                         "the data has enough weeks yet")
    args = ap.parse_args(argv)

    problems: list = []

    # -- risks ------------------------------------------------------------
    _rule(f"RISK DEFINITIONS  ({args.risks})")
    if not args.risks.exists():
        print(f"  not found. `start_collection.py` writes a skeleton to fill in.")
        return 2
    risks, risk_problems = read_risk_definitions(args.risks)
    problems += risk_problems
    for p in risk_problems:
        print(f"  ! {p}")
    if risks.empty:
        print("  no valid risk definitions. Fill in the file before ingesting.")
        return 2
    print(f"  {len(risks)} risk(s): {', '.join(risks.risk_id)}")

    # -- sessions ---------------------------------------------------------
    resolver = BrandResolver(load_providers(args.providers))
    rows_all: list = []
    files = _expand(args.sessions)
    for path in files:
        _rule(f"SESSION  ({path})")
        if not path.exists():
            print("  not found")
            problems.append(f"{path}: not found")
            continue
        rows, row_problems = read_session(path)
        problems += [f"{path.name}: {p}" for p in row_problems]
        for p in row_problems:
            print(f"  ! {p}")
        brands, channels = _grid_expectations(path)
        rep = coverage_report(rows, brands, channels)
        n_missing = sum(r["status"] == "MISSING" for r in rep)
        print(f"  {len(rows)} row(s) filled in of {len(brands) * len(channels)} in the grid"
              f"   quoted {sum(r['quoted'] for r in rep)}"
              f"   declined {sum(r['declined'] for r in rep)}"
              f"   brands missing {n_missing}")
        for r in rep:
            if r["status"] != "complete":
                gap = ", ".join(r["missing_channels"])
                print(f"    {r['brand']:18} {r['status']:8} not asked on: {gap}")
        rows_all += rows

    quotes, canon_problems = session_to_canonical(rows_all, risks, resolver=resolver)
    problems += canon_problems
    if canon_problems:
        _rule(f"ROWS NOT INGESTED  ({len(canon_problems)})")
        for p in canon_problems:
            print(f"  ! {p}")

    # -- append -----------------------------------------------------------
    _rule(f"OUTPUT  ({args.out})")
    args.out.mkdir(parents=True, exist_ok=True)
    existing_path = args.out / "quotes.parquet"
    existing = pd.read_parquet(existing_path) if existing_path.exists() else None
    merged, n_replaced = append_quotes(existing, quotes)
    print(f"  new rows {len(quotes)}   replaced {n_replaced}   "
          f"total {len(merged)}   dates {merged.collected_on.nunique() if len(merged) else 0}")

    orphans = sorted(set(merged.risk_id) - set(risks.risk_id)) if len(merged) else []
    if orphans:
        problems.append(f"quotes reference risk_id(s) with no definition: {orphans}")
        print(f"  ! previously ingested quotes reference undefined risk(s): {orphans}")
        print("    add them to the risk file; they are kept but cannot be modelled")

    if merged.empty:
        print("  nothing to write.")
        return 2

    # -- geo --------------------------------------------------------------
    geo_ready = False
    if args.geo is not None:
        _rule(f"GEO ENRICHMENT  ({args.geo})")
        enricher = GeoEnricher(default_sources(args.geo))
        risks = enricher.enrich(risks)
        for note in enricher.notes:
            print(f"  {note}")
        try:
            check_ready_for_modelling(risks)
            geo_ready = True
            print("\n  geo features complete -- ready to model")
        except ValueError as exc:
            print(f"\n  {exc}")
            todo = missing_files(args.geo)
            if len(todo):
                print("\n  still to download:")
                print(todo[["file", "url"]].to_string(index=False))

    risks.to_parquet(args.out / "risks.parquet", index=False)
    merged.to_parquet(args.out / "quotes.parquet", index=False)
    (args.out / "ingest.json").write_text(
        json.dumps(
            {"argv": argv if argv is not None else sys.argv[1:],
             "sessions": [str(p) for p in files], "risks": str(args.risks),
             "n_quotes": int(len(merged)), "n_risks": int(len(risks)),
             "geo_ready": geo_ready, "problems": len(problems)},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  written: {args.out / 'quotes.parquet'}, {args.out / 'risks.parquet'}")

    # -- what it can support ---------------------------------------------
    if geo_ready:
        _rule("WHAT THIS DATA CAN SUPPORT")
        df = build_matrix(merged, risks, quoted_only=True)
        print(assess(df, holdout_weeks=args.weeks_holdout).format())
        print(f"\n  python scripts/run_poc.py --data {args.out / 'quotes.parquet'} "
              f"--risks {args.out / 'risks.parquet'} --out {args.out / 'poc'}")
    else:
        print("\n  NOT model-ready: the risks carry a postcode but no geo features.")
        print("  Re-run with --geo data/geo; run_poc.py refuses risks without them.")

    if problems:
        print(f"\n  {len(problems)} problem(s) above. Valid rows were written; fix the")
        print("  rest in the grid and re-run -- corrected rows replace the old ones.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

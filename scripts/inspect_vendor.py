"""Inspect a vendor extract before trusting it.

Two modes, matching the two things you do with a new file.

    # 1. First sight of an unknown extract -- what is in it, and what maps where
    python scripts/inspect_vendor.py data/raw/ci_sample.csv

    # 2. Once you have a spec -- map it, audit it, and write canonical parquet
    python scripts/inspect_vendor.py data/raw/ci_sample.csv --spec ci --write

Mode 1 prints a column profile and a draft `VendorSpec` to paste into
`collect/vendor.py`. Mode 2 runs the audits. Read the BLOCKERs before the
leaderboard, not after the first odd result: an extract can be clean, complete
and still unable to answer the question this repo asks.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mktpricing.collect.vendor import (  # noqa: E402
    SPECS,
    audit_extract,
    apply_spec,
    format_audit,
    profile_extract,
    suggest_spec,
    to_records,
)
from mktpricing.features.geo import (  # noqa: E402
    GeoEnricher,
    check_ready_for_modelling,
    default_sources,
    missing_files,
)


def _tidy(problem) -> str:
    """One line, without pydantic's per-field documentation URLs."""
    text = re.sub(
        r"\s*For further information visit https://\S+", "", str(problem)
    )
    return " ".join(text.split())


def _summarise(problems, max_kinds: int = 15) -> list:
    """Collapse per-row problems into one line per kind.

    A file with 10,000 bad risks produces 10,000 near-identical messages, which
    buries the two that are actually different. Group by the message with its
    identifiers stripped, then show a count and one example of each kind.
    """
    groups: dict = {}
    for p in problems:
        text = _tidy(p)
        # Key on a prefix: a pydantic error echoes the whole offending record,
        # so two reports of the same fault differ far down the string and would
        # otherwise land in separate groups.
        key = re.sub(r"\d[\d,]*", "N", re.sub(r"'[^']*'", "'_'", text))[:110]
        groups.setdefault(key, []).append(text)

    out = []
    for _, examples in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:max_kinds]:
        first = examples[0]
        if len(first) > 190:
            first = first[:187] + "..."
        prefix = f"[x{len(examples)}] " if len(examples) > 1 else ""
        out.append(f"  - {prefix}{first}")
    if len(groups) > max_kinds:
        out.append(f"  ... and {len(groups) - max_kinds} further kinds")
    return out


def _rule(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, help="vendor extract (csv/tsv/xlsx/parquet)")
    ap.add_argument("--spec", choices=sorted(SPECS), help="apply a known vendor spec")
    ap.add_argument("--name", default="NewVendor", help="name for the draft spec")
    ap.add_argument("--write", action="store_true",
                    help="write canonical parquet to data/processed/")
    ap.add_argument("--geo", type=Path, default=None, metavar="DIR",
                    help="enrich risks with geo features from DIR (e.g. data/geo)")
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    args = ap.parse_args()

    pd.set_option("display.width", 160)

    if not args.spec:
        _rule("COLUMN PROFILE")
        print(profile_extract(args.path).to_string(index=False, max_colwidth=44))
        _rule(f"DRAFT SPEC  (paste into collect/vendor.py and correct)")
        print(suggest_spec(args.path, name=args.name))
        print(
            "\n  The four facts under the CONFIRM comment cannot be read off the\n"
            "  file. Get them from the vendor's documentation before loading.\n"
        )
        return 0

    spec = SPECS[args.spec]
    canonical, problems = apply_spec(args.path, spec)

    _rule(f"AUDIT  ({spec.name}, {len(canonical):,} rows)")
    findings = audit_extract(canonical, spec)
    print(format_audit(findings))

    risks, quotes, more = to_records(canonical)
    problems += more

    if problems:
        _rule(f"MAPPING PROBLEMS  ({len(problems):,} total)")
        for line in _summarise(problems):
            print(line)

    _rule("RESULT")
    print(f"  {len(risks):,} risks, {len(quotes):,} quotes")
    if len(quotes):
        print(f"  {int((~quotes.quoted).sum()):,} declines")
        print(f"  brands: {quotes.brand.nunique()}   "
              f"dates: {quotes.collected_on.nunique()}")

    blockers = [f for f in findings if f.severity == "BLOCKER"]
    if blockers:
        print(f"\n  {len(blockers)} BLOCKER(s). Do not train on this extract until\n"
              "  they are resolved -- the models will fit and score regardless.")

    geo_ready = False
    if args.geo is not None and len(risks):
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

    if args.write:
        args.out.mkdir(parents=True, exist_ok=True)
        risks.to_parquet(args.out / "risks.parquet", index=False)
        quotes.to_parquet(args.out / "quotes.parquet", index=False)
        print(f"\n  written to {args.out}")
        if geo_ready:
            print("  python scripts/run_poc.py "
                  "--data data/processed/quotes.parquet "
                  "--risks data/processed/risks.parquet")
        else:
            # run_poc would fail on these: a vendor extract carries a postcode
            # but not the risk features derived from it.
            print("  NOT model-ready yet -- risks have a postcode but no geo\n"
                  "  features. Re-run with --geo data/geo before run_poc.py,\n"
                  "  which refuses them otherwise.")

    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())

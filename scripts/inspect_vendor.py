"""Inspect a vendor extract before trusting it, then load it.

Three modes, matching the three things you do with a new file.

    # 1. First sight of an unknown extract -- what is in it, and what maps where
    python scripts/inspect_vendor.py data/raw/ci/market_view.xlsx --sheet "Raw Data"

    # 2. Save the draft mapping as a spec file, then correct it by hand
    python scripts/inspect_vendor.py data/raw/ci/market_view.xlsx --draft-spec config/vendor_specs/ci.yml

    # 3. With a spec -- map, audit, geo-enrich, and write canonical parquet
    python scripts/inspect_vendor.py data/raw/ci/ --spec ci --geo data/geo --write

`--spec` takes a built-in name (ci, pearson_ham, defaqto), the name of a file
under config/vendor_specs/, or a path to any .yml. The file wins over the
built-in of the same name, because the file is the one a real extract has
been checked against.

The path may be one file, several, a folder or a glob: a vendor that delivers
one file per day or week is loaded by pointing at the folder. CSV in any
delimiter, gzip/zip CSV, TSV, Excel (`--sheet`, `--header-row` for title
rows), Parquet and JSON all read. `--append` adds to what --out already
holds, replacing rows with the same (risk, brand, channel, date), so a weekly
delivery is one command a week.

Mode 3 runs the audits. Read the BLOCKERs before the leaderboard, not after
the first odd result: an extract can be clean, complete and still unable to
answer the question this repo asks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mktpricing.collect.session import append_quotes  # noqa: E402
from mktpricing.collect.vendor import (  # noqa: E402
    audit_extract,
    apply_spec,
    draft_spec,
    expand_paths,
    format_audit,
    known_specs,
    load_spec,
    profile_extract,
    read_extracts,
    suggest_spec,
    to_records,
)
from mktpricing.features.geo import (  # noqa: E402
    GeoEnricher,
    check_ready_for_modelling,
    default_sources,
    missing_files,
)
from mktpricing.market.observed import observed_market, spread_summary  # noqa: E402


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


def _read_kwargs(args) -> dict:
    kw = {}
    if args.sheet is not None:
        kw["sheet"] = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
    if args.header_row:
        kw["header_row"] = args.header_row
    if args.delimiter:
        kw["delimiter"] = {"tab": "\t", "\\t": "\t"}.get(args.delimiter, args.delimiter)
    return kw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+",
                    help="vendor extract(s): file, folder or glob (csv/tsv/xlsx/parquet/json)")
    ap.add_argument("--spec", help=f"vendor spec: {' | '.join(known_specs())} | path/to.yml")
    ap.add_argument("--name", default="NewVendor", help="name for the draft spec")
    ap.add_argument("--draft-spec", type=Path, metavar="FILE.yml",
                    help="write the guessed mapping as a YAML spec to correct")
    ap.add_argument("--sheet", default=None, help="Excel sheet name or index (mode 1/2)")
    ap.add_argument("--header-row", type=int, default=0,
                    help="rows above the header to skip (mode 1/2)")
    ap.add_argument("--delimiter", default=None, help="CSV delimiter if sniffing fails")
    ap.add_argument("--write", action="store_true",
                    help="write canonical parquet to --out")
    ap.add_argument("--append", action="store_true",
                    help="add to the parquet already in --out (same-key rows replaced)")
    ap.add_argument("--geo", type=Path, default=None, metavar="DIR",
                    help="enrich risks with geo features from DIR (e.g. data/geo)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output directory (default data/processed/<spec name>)")
    args = ap.parse_args(argv)

    pd.set_option("display.width", 160)

    files = expand_paths(args.paths)
    if not files:
        print(f"no data files found at {args.paths}")
        return 2
    print(f"{len(files)} file(s): {', '.join(f.name for f in files[:6])}"
          f"{' ...' if len(files) > 6 else ''}")

    # -- mode 1 / 2: no spec yet ----------------------------------------------
    if not args.spec:
        raw = read_extracts(files, **_read_kwargs(args))
        _rule(f"COLUMN PROFILE  ({len(raw):,} rows)")
        print(profile_extract(raw).to_string(index=False, max_colwidth=44))
        if args.draft_spec:
            spec = draft_spec(raw, name=args.name)
            spec.sheet = _read_kwargs(args).get("sheet")
            spec.header_row = args.header_row
            spec.delimiter = _read_kwargs(args).get("delimiter")
            args.draft_spec.parent.mkdir(parents=True, exist_ok=True)
            head = suggest_spec(raw, name=args.name, fmt="yaml").split("name:")[0]
            args.draft_spec.write_text(head + spec.to_yaml(), encoding="utf-8")
            _rule(f"DRAFT SPEC written to {args.draft_spec}")
            print("  Correct the column names against the vendor's data dictionary,")
            print("  fill in the four declared facts, then:")
            print(f"    python scripts/inspect_vendor.py {args.paths[0]} "
                  f"--spec {args.draft_spec} --write")
        else:
            _rule("DRAFT SPEC  (--draft-spec FILE.yml saves it; or paste into collect/vendor.py)")
            print(suggest_spec(raw, name=args.name, fmt="yaml"))
        print(
            "\n  The four facts under CONFIRM cannot be read off the file. Get them\n"
            "  from the vendor's documentation before loading. docs/VENDOR-EXTRACTS.md\n"
            "  lists the questions to ask.\n"
        )
        return 0

    # -- mode 3: map, audit, write --------------------------------------------
    spec = load_spec(args.spec)
    spec_stem = Path(args.spec).stem if Path(args.spec).suffix else args.spec
    if args.out is None:
        args.out = ROOT / "data" / "processed" / spec_stem
    # A CLI override of the layout facts, for a one-off file that differs.
    for k_, v_ in _read_kwargs(args).items():
        setattr(spec, k_, v_)

    canonical, problems = apply_spec(files, spec)

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
        print(f"  brands: {quotes.brand.nunique()}   channels: {quotes.channel.nunique()}   "
              f"dates: {quotes.collected_on.nunique()} "
              f"({quotes.collected_on.min()} to {quotes.collected_on.max()})")

    blockers = [f for f in findings if f.severity == "BLOCKER"]
    if blockers:
        print(f"\n  {len(blockers)} BLOCKER(s). Do not train on this extract until\n"
              "  they are resolved -- the models will fit and score regardless.")

    if len(quotes):
        m = observed_market(quotes, k=5)
        s = spread_summary(m, k=5)
        if s:
            _rule("OBSERVED MARKET  (all dates, k=5; scripts/market_price.py for the full report)")
            print(f"  best price mean GBP {s['cheapest_mean']:.2f}   top-5 mean GBP {s['top5_mean']:.2f}   "
                  f"spread median {s['spread_pct_median']}% of best   "
                  f"({s['n_quoting_mean']} brands quoting per risk)")

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
        qp, rp = args.out / "quotes.parquet", args.out / "risks.parquet"
        n_replaced = 0
        if args.append and qp.exists():
            old_q = pd.read_parquet(qp)
            quotes, n_replaced = append_quotes(old_q, quotes)
            if rp.exists():
                old_r = pd.read_parquet(rp)
                risks = pd.concat([old_r[~old_r.risk_id.isin(set(risks.risk_id))], risks],
                                  ignore_index=True)
            print(f"\n  appended: {len(quotes):,} quotes now on file, replaced {n_replaced:,}")
        elif args.append:
            print(f"\n  --append: nothing in {args.out} yet, writing fresh")
        risks.to_parquet(rp, index=False)
        quotes.to_parquet(qp, index=False)
        (args.out / "load.json").write_text(json.dumps({
            "spec": spec.name, "spec_arg": args.spec, "files": [str(f) for f in files],
            "n_risks": int(len(risks)), "n_quotes": int(len(quotes)),
            "replaced": n_replaced, "geo_ready": geo_ready,
            "audit": [str(f) for f in findings],
        }, indent=2), encoding="utf-8")
        print(f"\n  written to {args.out}")
        print(f"  python scripts/market_price.py --data {qp} --risks {rp}")
        if geo_ready:
            print(f"  python scripts/run_poc.py --data {qp} --risks {rp} --out {args.out / 'poc'}")
        else:
            # run_poc would fail on these: a vendor extract carries a postcode
            # but not the risk features derived from it.
            print("  NOT model-ready yet -- risks have a postcode but no geo\n"
                  "  features. Re-run with --geo data/geo before run_poc.py,\n"
                  "  which refuses them otherwise. The market price above needs\n"
                  "  no geo features and no model.")

    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())

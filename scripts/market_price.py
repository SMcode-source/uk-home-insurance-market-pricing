"""Best price, top-5 market price and spread from observed quotes.

    # from canonical parquet (what inspect_vendor.py --write or ingest_session.py wrote)
    python scripts/market_price.py --data data/processed/ci/quotes.parquet \
        --risks data/processed/ci/risks.parquet --out data/processed/ci/market

    # straight from the vendor's files, mapped through a spec
    python scripts/market_price.py data/raw/ci/*.xlsx --spec ci --out data/processed/ci/market

    # per PCW rather than the consumer market; weekly buckets; cheapest 3
    python scripts/market_price.py --data ... --by-channel --period week --k 3

No model is fitted. This is arithmetic on the quotes that were actually
returned: for every risk and date, the cheapest brand, the mean of the k
cheapest brands, and the gap between the cheapest and the k-th (the spread).
`market/observed.py` defines each number; the docstring there is the spec.

Writes to --out:
    market_by_risk.csv        one row per risk and period (and channel)
    market_by_period.csv      per period: best, top-k, spread, index_100, wow_pct
    brand_competitiveness.csv per brand: quote rate, cheapest share, top-k share, gap
    channel_gap.csv           per brand: direct vs cheapest PCW, where both were quoted
    market.json               the headline numbers and how they were produced

The index is only a price index on a fixed basket. The script prefers the
declared basket (`Risk.in_basket`), falls back to the risks present in every
period, says which it used, and reports no index at all on a fully rotating
panel -- because week-on-week movement there is composition, not price.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mktpricing.collect.vendor import (  # noqa: E402
    apply_spec, audit_extract, format_audit, load_spec, to_records,
)
from mktpricing.market.observed import (  # noqa: E402
    brand_competitiveness, channel_gap, market_by_period, observed_market,
    spread_summary,
)


def _rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def _load(args):
    """Quotes and (optionally) risks, from parquet or from vendor files."""
    if args.data is not None:
        quotes = pd.read_parquet(args.data)
        risks = pd.read_parquet(args.risks) if args.risks else None
        return quotes, risks, None, []
    if not args.files:
        raise SystemExit("give --data <quotes.parquet> or vendor file(s) with --spec")
    if not args.spec:
        raise SystemExit("vendor files need --spec <name or path to .yml>")
    spec = load_spec(args.spec)
    canonical, problems = apply_spec(args.files, spec)
    findings = audit_extract(canonical, spec)
    risks, quotes, more = to_records(canonical)
    return quotes, risks, findings, problems + more


def _basket(market, risks):
    """Declared basket if any of it is present; else the risks in every period;
    else nothing. Returns (ids, kind)."""
    periods = market["period"].nunique()
    if risks is not None and "in_basket" in risks.columns:
        declared = set(risks[risks["in_basket"].astype(bool)]["risk_id"])
        if declared & set(market["risk_id"]):
            return sorted(declared & set(market["risk_id"])), "declared (Risk.in_basket)"
    per_risk = market.groupby("risk_id", observed=True)["period"].nunique()
    common = sorted(per_risk[per_risk == periods].index.tolist())
    if common and periods > 1:
        return common, "derived (risks present in every period)"
    return [], "none"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="vendor file(s), folder or glob (needs --spec)")
    ap.add_argument("--spec", help="vendor spec: ci | pearson_ham | defaqto | path/to.yml")
    ap.add_argument("--data", type=Path, help="canonical quotes.parquet")
    ap.add_argument("--risks", type=Path, help="canonical risks.parquet (for the declared basket)")
    ap.add_argument("--k", type=int, default=5, help="size of the cheapest-k (default 5)")
    ap.add_argument("--period", choices=("day", "week", "month"), default="day",
                    help="bucket collection dates (default day)")
    ap.add_argument("--by-channel", action="store_true",
                    help="rank within each channel (PCW) instead of the consumer market")
    ap.add_argument("--out", type=Path, default=None,
                    help="output directory (default: next to --data, in market/)")
    args = ap.parse_args(argv)

    pd.set_option("display.width", 170)
    pd.set_option("display.max_columns", 30)

    quotes, risks, findings, problems = _load(args)
    if args.out is None:
        base = args.data.parent if args.data is not None else ROOT / "data" / "processed" / (args.spec or "vendor")
        args.out = Path(base) / "market"
    args.out.mkdir(parents=True, exist_ok=True)
    k = args.k

    if findings is not None:
        _rule("AUDIT  (vendor files mapped on the way in)")
        print(format_audit(findings))
        if problems:
            print(f"\n  {len(problems)} mapping problem(s); first few:")
            for p in problems[:6]:
                print(f"  - {str(p)[:160]}")
        blockers = [f for f in findings if f.severity == "BLOCKER"]
        if any(f.code in ("truncated",) for f in blockers):
            print("\n  NOTE: a truncated extract is fine for the cheapest-k market price --")
            print("  that IS the metric -- and useless for per-brand modelling.")

    if quotes.empty:
        print("no quotes to price")
        return 2

    _rule(f"OBSERVED MARKET  ({len(quotes):,} quotes, k={k}, period={args.period}, "
          f"{'per channel' if args.by_channel else 'consumer market: each brand once'})")
    market = observed_market(quotes, k=k, period=args.period, by_channel=args.by_channel)
    if market.empty or "cheapest_price" not in market.columns:
        print("  no priced risk-periods -- every row is a decline or has no premium")
        return 2
    headline = spread_summary(market, k=k)
    latest = market[market["period"] == market["period"].max()]
    latest_h = spread_summary(latest, k=k)
    print(f"  risk-periods: {headline['n_risk_periods']:,}   with a full top-{k}: "
          f"{headline['n_complete']:,}   brands quoting per risk: {headline['n_quoting_mean']}")
    print(f"\n  latest period {market['period'].max()}  ({latest['risk_id'].nunique()} risks)")
    print(f"    best price        mean GBP {latest_h['cheapest_mean']:>8.2f}   median GBP {latest_h['cheapest_median']:.2f}")
    print(f"    top-{k} market      mean GBP {latest_h[f'top{k}_mean']:>8.2f}")
    print(f"    spread (best -> {k}th)  median GBP {latest_h['spread_abs_median']:.2f}  = "
          f"{latest_h['spread_pct_median']}% of best   (p10 {latest_h['spread_pct_p10']}%, "
          f"p90 {latest_h['spread_pct_p90']}%)")
    print(f"    panel spread (best -> dearest)  median {latest_h['panel_spread_pct_median']}%")
    winners = latest["cheapest_brand"].value_counts(normalize=True).head(3)
    print("    cheapest most often: " + ", ".join(f"{b} {s * 100:.0f}%" for b, s in winners.items()))

    # -- per period ---------------------------------------------------------
    basket_ids, basket_kind = _basket(market, risks)
    _rule(f"BY PERIOD  (basket: {len(basket_ids)} risks, {basket_kind})")
    if basket_ids:
        by_period = market_by_period(market, k=k, basket_risk_ids=basket_ids,
                                     by_channel=args.by_channel)
        print(by_period.round(2).to_string(index=False))
        if basket_kind.startswith("derived"):
            print("\n  derived basket: whatever the panel happened to re-quote every period,")
            print("  not a sample anyone designed. Declare `in_basket` on the risks to fix it.")
    else:
        by_period = market_by_period(market, k=k, by_channel=args.by_channel)
        by_period = by_period.drop(columns=["index_100", "wow_pct"], errors="ignore")
        print(by_period.round(2).to_string(index=False))
        print("\n  no index: the panel rotates completely, so no risk appears in every")
        print("  period. Movement between these rows is composition, not price.")
    by_period.to_csv(args.out / "market_by_period.csv", index=False)

    # -- brands -------------------------------------------------------------
    _rule(f"BRAND COMPETITIVENESS  (share of risk-periods cheapest / in the top {k})")
    bc = brand_competitiveness(quotes, k=k, period=args.period, by_channel=args.by_channel)
    print(bc.to_string(index=False))
    bc.to_csv(args.out / "brand_competitiveness.csv", index=False)

    # -- channels -----------------------------------------------------------
    cg = channel_gap(quotes, period=args.period)
    if len(cg):
        _rule("CHANNEL GAP  (direct vs cheapest PCW, same brand, risk and period)")
        print(cg.to_string(index=False))
        print("\n  positive = direct is dearer. Read with docs/COLLECTION.md trap 8: a PCW")
        print("  tier is not always the direct product.")
    cg.to_csv(args.out / "channel_gap.csv", index=False)

    # -- write --------------------------------------------------------------
    market.to_csv(args.out / "market_by_risk.csv", index=False)
    summary = {
        "argv": sys.argv[1:] if argv is None else list(argv),
        "k": k, "period": args.period, "by_channel": args.by_channel,
        "n_quotes": int(len(quotes)), "n_risks": int(quotes["risk_id"].nunique()),
        "n_brands": int(quotes["brand"].nunique()),
        "dates": [str(quotes["collected_on"].min()), str(quotes["collected_on"].max())],
        "basket": {"kind": basket_kind, "n": len(basket_ids)},
        "overall": headline, "latest_period": {"period": str(market["period"].max()), **latest_h},
        "definitions": {
            "best_price": "cheapest quote across brands, each brand at its cheapest channel",
            f"top{k}_mean": f"mean of the {k} cheapest brands",
            "spread_abs": f"{k}th cheapest minus cheapest, GBP",
            "spread_pct": "spread_abs as a percentage of the cheapest",
            "panel_spread_pct": "dearest quote over cheapest, percent",
        },
    }
    if findings is not None:
        summary["audit"] = [str(f) for f in findings]
    (args.out / "market.json").write_text(json.dumps(summary, indent=2, default=str),
                                          encoding="utf-8")
    print(f"\n  written to {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""End-to-end POC run.

    python scripts/run_poc.py                 # synthetic data, full comparison
    python scripts/run_poc.py --quick         # smaller, faster
    python scripts/run_poc.py --data data/processed/quotes.parquet

Does five things in order:

  1. loads or generates quote data
  2. compares every available modelling approach on temporal + spatial splits
  3. reports the EBM-vs-GBM additivity gap, then blind vs weekly refresh
  4. fits the two-part model and simulates the cheapest-5 market price
  5. builds the weekly index from the fixed basket

Every number it prints is on held-out data. Nothing here is scored in-sample.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mktpricing.collect.synthetic import generate  # noqa: E402
from mktpricing.evaluate.compare import (  # noqa: E402
    additivity_gap, first_holdout_week_is_identical, format_leaderboard,
    rolling_comparison, run_comparison,
)
from mktpricing.evaluate.metrics import per_brand_metrics  # noqa: E402
from mktpricing.features.build import align_columns, build_matrix, design_matrix  # noqa: E402
from mktpricing.market.simulate import (  # noqa: E402
    common_risks, market_index, simulate_market, top_k_table,
)
from mktpricing.models.approaches import QuotabilityModel  # noqa: E402
from mktpricing.models.base import (  # noqa: E402
    get, set_n_jobs, unavailable_approaches,
)


def _rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, help="parquet of quotes; omit for synthetic")
    ap.add_argument("--risks", type=Path, help="parquet of risks (with --data)")
    ap.add_argument("--quick", action="store_true", help="smaller synthetic run")
    ap.add_argument("--weeks-holdout", type=int, default=2)
    ap.add_argument("--k", type=int, default=5, help="top-k for the market price")
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "processed")
    ap.add_argument("--only", nargs="*", help="restrict to named approaches")
    ap.add_argument(
        "--jobs", type=int, default=None,
        help="workers per fit (default 1). Each EBM bag worker is a whole "
             "extra interpreter, so raise this only with memory headroom.",
    )
    args = ap.parse_args()

    if args.jobs is not None:
        set_n_jobs(args.jobs)

    args.out.mkdir(parents=True, exist_ok=True)

    # -- 1. data ----------------------------------------------------------
    _rule("1. DATA")
    if args.data:
        quotes = pd.read_parquet(args.data)
        risks = pd.read_parquet(args.risks) if args.risks else None
        if risks is None:
            print("  --risks is required alongside --data")
            return 2
        print(f"  loaded {len(quotes):,} quotes over {len(risks):,} risks")
    else:
        n_risks, n_weeks = (140, 8) if args.quick else (900, 26)
        risks, quotes, truth = generate(
            n_risks=n_risks, n_weeks=n_weeks,
            rotating_per_week=40 if args.quick else 160,
        )
        print(f"  synthetic: {len(quotes):,} quotes, {len(risks):,} risks, "
              f"{n_weeks} weeks, {quotes.brand.nunique()} brands")
        print(f"  declined:  {(~quotes.quoted).mean() * 100:.1f}% of rows "
              "(these train the quotability model, not the premium model)")
        risks.to_parquet(args.out / "risks.parquet", index=False)
        quotes.to_parquet(args.out / "quotes.parquet", index=False)

    df = build_matrix(quotes, risks, quoted_only=True)
    print(f"  model matrix: {len(df):,} quoted rows, "
          f"premium GBP {np.exp(df.log_premium).min():.0f}"
          f"-{np.exp(df.log_premium).max():.0f}")

    # -- 2. approach comparison -------------------------------------------
    _rule("2. APPROACH COMPARISON  (held-out; never random-split)")
    skipped = unavailable_approaches()
    if skipped:
        print("  skipped (missing libraries):")
        for name, why in skipped.items():
            print(f"    {name:18} {why}")

    leaderboard, preds, _ = run_comparison(
        df, holdout_weeks=args.weeks_holdout, k=args.k,
        only=args.only, verbose=True,
    )
    table = format_leaderboard(leaderboard, k=args.k)
    print("\n  LEADERBOARD (sorted by MdAPE within split)\n")
    print(table.to_string(index=False))
    table.to_csv(args.out / "leaderboard.csv", index=False)

    # -- 3. additivity gap -------------------------------------------------
    _rule("3. ADDITIVITY GAP  (EBM vs GBM -- a measurement, not a race)")
    gap = additivity_gap(leaderboard)
    if gap.empty:
        print("  needs both ebm_per_brand and gbm_per_brand to have run.")
    else:
        print(gap.to_string(index=False))
        print("\n  Positive gap = the boosted model finds structure the additive")
        print("  model cannot represent: caps, collars, 3-way terms, an")
        print("  optimisation layer. Near zero = a clean multiplicative table,")
        print("  and the interpretable model costs you nothing.")

    # -- 3b. blind vs weekly refresh ---------------------------------------
    _rule("3b. BLIND VS WEEKLY REFRESH  (the operating mode, not just the test)")
    roll, roll_brand, roll_week, _ = rolling_comparison(
        df, holdout_weeks=args.weeks_holdout, only=args.only, verbose=True,
    )
    if roll.empty:
        print("  no approach in this run supports recalibration.")
    else:
        print()
        print(roll.round(2).to_string(index=False))
        roll.to_csv(args.out / "rolling.csv", index=False)
        roll_brand.to_csv(args.out / "rolling_per_brand.csv", index=False)
        roll_week.to_csv(args.out / "rolling_per_week.csv", index=False)

        # The first holdout week has nothing observed behind it, so the two
        # regimes must agree exactly. If they ever stop agreeing, the rolling
        # pass is scoring on data it already absorbed -- which would make every
        # figure above flattering and wrong. Assert it; do not trust it.
        if not first_holdout_week_is_identical(roll_week):
            print("\n  *** week one differs between regimes -- the rolling pass")
            print("      is leaking the holdout. Do not report these numbers. ***")
            return 3
        first = int(roll_week.week.min())
        print(f"\n  week {first} identical under both regimes, as it must be:")
        print("  nothing is observed yet, so nothing is corrected. Every gain")
        print("  below appears later, where new information legitimately exists.")

        print("\n  per week (MAPE %):")
        print(roll_week.pivot_table(index="week", columns="regime",
                                    values="mape").round(2).to_string())
        worst = (roll_brand[roll_brand.regime == "blind"]
                 .sort_values("mape", ascending=False).head(3).brand.tolist())
        print(f"\n  worst three brands blind ({', '.join(worst)}):")
        print(roll_brand[roll_brand.brand.isin(worst)]
              .pivot_table(index="brand", columns="regime", values=["mape", "bias"])
              .round(2).to_string())

    # -- 4. two-part model + market simulation -----------------------------
    _rule(f"4. TWO-PART MODEL AND TOP-{args.k} MARKET PRICE")

    full = build_matrix(quotes, risks, quoted_only=False)
    Xq, _ = design_matrix(full, include_brand=True)
    quot = QuotabilityModel().fit(Xq, full["quoted"].to_numpy(), groups=full["brand"])
    print(f"  quotability backend: {quot.backend}")

    best_name = (
        table[table.split == "temporal"].iloc[0].approach if len(table) else "ridge_log"
    )
    print(f"  premium model: {best_name} (best on the temporal split)")

    train = df[df.week < df.week.max() - args.weeks_holdout + 1]
    test = df[df.week >= df.week.max() - args.weeks_holdout + 1]
    Xtr, ytr = design_matrix(train, include_brand=True)
    model = get(best_name)().fit(Xtr, ytr, groups=train["brand"].to_numpy())

    # Score the FULL panel on the holdout, declines included -- a provider that
    # would refuse must be able to lose its place in the top five.
    panel = full[full.week >= full.week.max() - args.weeks_holdout + 1].copy()
    Xp, _ = design_matrix(panel, include_brand=True)
    Xp = align_columns(Xp, Xtr)
    panel["pred_premium"] = np.exp(model.predict(Xp, groups=panel["brand"].to_numpy()))
    panel["p_quote"] = quot.predict_proba(
        align_columns(Xp, Xq), groups=panel["brand"].to_numpy()
    )

    market = simulate_market(panel, k=args.k, n_sims=args.sims)
    market.to_parquet(args.out / "market.parquet", index=False)
    print(f"\n  simulated {len(market):,} risk-weeks x {args.sims} draws")
    print(f"  mean top-{args.k} price GBP {market[f'top{args.k}_mean'].mean():.2f}   "
          f"mean panel size {market.n_on_panel.mean():.1f}   "
          f"mean quoting {market.n_quoting_mean.mean():.1f}")

    sample = panel.risk_id.iloc[0]
    wk = int(panel.week.max())
    print(f"\n  Example cheapest-{args.k} for {sample}, week {wk}:\n")
    print(top_k_table(panel, sample, week=wk, k=args.k).to_string(index=False))

    # -- 5. weekly index ---------------------------------------------------
    _rule("5. WEEKLY INDEX  (fixed basket only)")
    # Prefer the DECLARED basket: risks someone committed to re-quoting every
    # week. Vendor extracts never carry it -- which risks form your index is not
    # a fact about their file -- so fall back to the risks the panel happens to
    # hold constant, and say which of the two produced the number. Silently
    # swapping one for the other would present an after-the-fact selection as a
    # designed sample.
    declared = risks[risks.in_basket].risk_id.tolist()
    in_window = set(market.risk_id)
    basket_ids, basket_kind = declared, "declared (Risk.in_basket)"
    if not set(declared) & in_window:
        basket_ids = common_risks(market)
        basket_kind = "derived (risks present in every week)"
        if declared:
            print("  declared basket risks are all outside the holdout window.")
        else:
            print("  no declared basket -- `in_basket` is empty, as it is on any")
            print("  vendor extract: which risks form your index is your decision,")
            print("  not something the vendor's file can tell you.")

    if not basket_ids:
        print("\n  no index: the panel rotates completely, so no risk appears in")
        print("  all of the simulated weeks. Week-on-week movement here would be")
        print("  composition change, not price change.")
    else:
        print(f"\n  basket: {len(basket_ids)} risks, {basket_kind}")
        idx = market_index(market, basket_risk_ids=basket_ids, k=args.k)
        print(idx.to_string(index=False))
        idx.to_csv(args.out / "index.csv", index=False)

    # -- per-brand accuracy -------------------------------------------------
    _rule("PER-BRAND ACCURACY  (best approach, temporal split)")
    best_preds = preds[(preds.approach == best_name) & (preds.split == "temporal")]
    if not best_preds.empty:
        pb = per_brand_metrics(best_preds)
        print(pb.to_string(index=False))
        pb.to_csv(args.out / "per_brand.csv", index=False)
        print("\n  Read the tail, not the headline. Thin brands are always worse,")
        print("  and they decide whether 'model every provider' is achievable.")

    print(f"\n  outputs written to {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

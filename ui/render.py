"""Regenerate the numbers in `ui/index.html` from a POC run's outputs.

The page's prose, layout and argument are written by hand. Every figure in it
is generated, because a hand-transcribed number is correct exactly once -- the
next run moves it and nothing complains. That is the same failure as keeping
two copies of the page, one level up.

    python scripts/run_poc.py --data ... --out data/processed/poc_sample
    python ui/render.py --results data/processed/poc_sample

Each generated region sits between `<!-- gen:name -->` and `<!-- /gen:name -->`
markers. A missing marker is an error rather than a silent no-op: the whole
point is that the page cannot quietly go stale.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PAGE = HERE / "index.html"

# Display names for the leaderboard. The registry names are for the CLI; a
# first-time reader should not have to decode `ebm_per_brand`.
NAMES = {
    "gbm_per_brand_trend": "Boosted trees per brand, drift-corrected",
    "gbm_per_brand": "Boosted trees per brand",
    "gbm_pooled": "Boosted trees, pooled",
    "ebm_per_brand": "Explainable boosting machine, per brand",
    "ebm_per_brand_trend": "Explainable boosting machine, drift-corrected",
    "ebm_pooled": "Explainable boosting machine, pooled",
    "catboost_pooled": "CatBoost, pooled",
    "random_forest": "Random forest",
    "ridge_log": "Ridge on log premium",
    "brand_geomean": 'Per-brand geometric mean <span class="dim">(baseline)</span>',
    "global_geomean": 'Market geometric mean <span class="dim">(baseline)</span>',
}


def _pct(v, dp=1, sign=False):
    s = f"{v:+.{dp}f}" if sign else f"{v:.{dp}f}"
    return s.replace("-", "&minus;")


def _gbp(v):
    return f"&pound;{v:,.0f}"


def _cls(v, good_below=None, bad_above=None):
    if bad_above is not None and abs(v) >= bad_above:
        return ' class="neg"'
    if good_below is not None and abs(v) <= good_below:
        return ' class="dim"'
    return ""


# -- block builders ---------------------------------------------------------


def headline(roll):
    b = roll[roll.regime == "blind"].iloc[0]
    r = roll[roll.regime == "rolling"].iloc[0]
    tiles = [
        (_pct(r.mdape, 1) + '<span class="dim">%</span>',
         "Median absolute error &mdash; the typical quote"),
        (_pct(r.mape, 1) + '<span class="dim">%</span>',
         "Mean absolute error &mdash; pulled up by the tail"),
        (f"{r.within_10pct:.0f}" + '<span class="dim">%</span>',
         "Of quotes land within 10% of the real price"),
        (_pct(abs(r.bias), 1) + '<span class="dim">%</span>',
         "Overall bias &mdash; no systematic over- or under-pricing"),
    ]
    out = ['<div class="stats">']
    for k, l in tiles:
        out.append(f'      <div class="stat"><span class="k">{k}</span>'
                   f'<span class="l">{l}</span></div>')
    out.append("    </div>")
    out.append("")
    out.append(
        "    <p>Those are the figures for the system as it would actually run, "
        "re-reading the panel each week before pricing the next one. Held fully "
        f"blind for all three weeks instead &mdash; no refresh at all &mdash; it "
        f"degrades to {b.mdape:.1f}% median, {b.mape:.1f}% mean and "
        f"{b.within_10pct:.0f}% within 10%. Both numbers appear throughout this "
        'page, and the difference between them is the subject of '
        '<a href="#churchill">the section on Churchill</a>.</p>'
    )
    return "\n".join(out)


def tracks(per_brand):
    blind = per_brand[per_brand.regime == "blind"].set_index("brand")
    roll = per_brand[per_brand.regime == "rolling"].set_index("brand")
    order = blind.sort_values("mape").index
    scale = float(np.ceil(blind.mape.max() / 5.0) * 5.0)

    out = [f'<div class="tracks" style="--scale:{scale:g}">']
    for b in order:
        was, now = blind.loc[b].mape, roll.loc[b].mape
        out.append(
            f'        <div class="row"><span class="name">{b}</span>'
            f'<span class="track">'
            f'<i class="bar-was" style="--was:{was:.2f}"></i>'
            f'<i class="bar-now" style="--now:{now:.2f}"></i></span>'
            f'<span class="fig"><b>{now:.1f}%</b>'
            f'<span class="arrow">&larr;</span>{was:.1f}%</span></div>'
        )
    out.append("      </div>")
    out.append("")
    out.append('      <div class="axis">' + "".join(
        f"<span>{int(v)}%</span>" for v in np.linspace(0, scale, 4)) + "</div>")
    return "\n".join(out)


def _hit_class(within_10pct):
    """Colour the hit rate by what it means, not by rank within the table."""
    if within_10pct < 60:
        return ' class="neg"'
    if within_10pct >= 85:
        return ' class="pos"'
    return ""


def provider_table(per_brand):
    blind = per_brand[per_brand.regime == "blind"].sort_values("mape")
    rows = []
    for _, r in blind.iterrows():
        rows.append(
            f"          <tr><td>{r.brand}</td><td>{int(r.n):,}</td>"
            f"<td>{_gbp(r.mean_actual)}</td>"
            f"<td{_cls(r.bias, good_below=1.5, bad_above=10)}>{_pct(r.bias, 1, True)}%</td>"
            f"<td>{r.sd_pe:.1f}</td><td>{r.mape:.2f}%</td>"
            f"<td{_hit_class(r.within_10pct)}>{r.within_10pct:.0f}%</td>"
            f"<td>{_gbp(r.mae_gbp)}</td></tr>"
        )
    return "\n".join(rows)


def totals_row(roll):
    b = roll[roll.regime == "blind"].iloc[0]
    return (f'          <tr class="tot"><td>All</td><td>{int(b.n):,}</td>'
            f"<td>{_gbp(b.mean_actual)}</td>"
            f"<td>{_pct(b.bias, 1, True)}%</td><td>{b.sd_pe:.1f}</td>"
            f"<td>{b.mape:.2f}%</td><td>{b.within_10pct:.0f}%</td>"
            f"<td>{_gbp(b.mae_gbp)}</td></tr>")


def weeks_chart(prof, brand):
    row = prof[prof.brand == brand].sort_values("week")
    scale = float(np.ceil(row.resid_pct.abs().max()))
    out = [f'<div class="weeks" style="--scale:{scale:g}">']
    for _, r in row.iterrows():
        after = " after" if r.window == "holdout" else ""
        out.append(
            f'        <div class="wk{after}">'
            f'<span class="col" style="--v:{abs(r.resid_pct):.2f}"></span>'
            f'<span class="lab">{int(r.week)}</span></div>'
        )
    out.append("      </div>")
    return "\n".join(out)


def churchill_weeks(per_brand_week, brand):
    g = per_brand_week[per_brand_week.brand == brand]
    blind = g[g.regime == "blind"].set_index("week").sort_index()
    roll = g[g.regime == "rolling"].set_index("week").sort_index()
    rows = []
    for w in blind.index:
        bb, rr = blind.loc[w], roll.loc[w]
        rows.append(
            f"          <tr><td>Week {int(w)}</td>"
            f'<td class="neg">{_pct(bb.bias, 1, True)}%</td>'
            f"<td{_cls(rr.bias, good_below=7, bad_above=15)}>{_pct(rr.bias, 1, True)}%</td>"
            f"<td>{bb.mape:.2f}%</td><td>{rr.mape:.2f}%</td></tr>"
        )
    return "\n".join(rows)


def before_after(roll, per_brand, brand):
    b = roll[roll.regime == "blind"].iloc[0]
    r = roll[roll.regime == "rolling"].iloc[0]
    pb = per_brand[per_brand.brand == brand].set_index("regime")
    pairs = [
        (f"{b.mape:.2f}", f"{r.mape:.2f}", "Mean absolute error, all providers (%)"),
        (f"{pb.loc['blind'].mape:.1f}", f"{pb.loc['rolling'].mape:.1f}",
         f"{brand} mean absolute error (%)"),
        (f"{b.within_10pct:.0f}", f"{r.within_10pct:.0f}",
         "Quotes within 10% of actual (%)"),
        (f"{b.var_pe:.0f}", f"{r.var_pe:.0f}", "Variance of percentage error"),
    ]
    out = ['<div class="stats">']
    for was, now, label in pairs:
        out.append(f'      <div class="stat"><span class="k">{was} '
                   f'<span class="dim">&rarr;</span> <span class="pos">{now}</span>'
                   f'</span><span class="l">{label}</span></div>')
    out.append("    </div>")
    return "\n".join(out)


def leaderboard(lb):
    t = lb[lb.split == "temporal"].set_index("approach")
    s = lb[lb.split == "spatial"].set_index("approach")
    best = t.mdape.idxmin()
    rows = []
    for name in t.sort_values("mdape").index:
        spatial = f"{s.loc[name].mdape:.2f}" if name in s.index else "&mdash;"
        cls = ' class="best"' if name == best else ""
        fit = t.loc[name].fit_s
        fit_s = "&lt;1s" if fit < 1 else f"{fit:.0f}s"
        rows.append(
            f"          <tr{cls}><td>{NAMES.get(name, name)}</td>"
            f"<td>{t.loc[name].mdape:.2f}</td><td>{spatial}</td>"
            f"<td>{t.loc[name].within_10pct:.0f}%</td><td>{fit_s}</td></tr>"
        )
    return "\n".join(rows)


# -- splice -----------------------------------------------------------------


def splice(page: str, name: str, body: str) -> str:
    open_, close = f"<!-- gen:{name} -->", f"<!-- /gen:{name} -->"
    pat = re.compile(re.escape(open_) + r".*?" + re.escape(close), re.S)
    if not pat.search(page):
        raise SystemExit(
            f"marker gen:{name} not found in {PAGE.name}. The page cannot be "
            "regenerated, which means it is silently stale -- add the marker."
        )
    return pat.sub(f"{open_}\n    {body}\n    {close}", page, count=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path,
                    default=ROOT / "data" / "processed" / "poc_sample")
    ap.add_argument("--page", type=Path, default=PAGE)
    ap.add_argument("--check", action="store_true",
                    help="fail if the page would change, instead of writing it")
    args = ap.parse_args()

    need = ["rolling.csv", "rolling_per_brand.csv", "rolling_per_brand_week.csv",
            "residual_by_week.csv", "leaderboard.csv"]
    missing = [f for f in need if not (args.results / f).exists()]
    if missing:
        print(f"missing {', '.join(missing)} in {args.results}")
        print("run scripts/run_poc.py first -- the page is generated from a run,")
        print("not the other way round.")
        return 2

    roll = pd.read_csv(args.results / "rolling.csv")
    per_brand = pd.read_csv(args.results / "rolling_per_brand.csv")
    per_brand_week = pd.read_csv(args.results / "rolling_per_brand_week.csv")
    prof = pd.read_csv(args.results / "residual_by_week.csv")
    lb = pd.read_csv(args.results / "leaderboard.csv")

    # The narrative is about whichever brand is worst, not about Churchill by
    # name. If a future run has a different worst brand, the page should follow
    # the data rather than keep telling the old story.
    worst = (per_brand[per_brand.regime == "blind"]
             .sort_values("mape", ascending=False).iloc[0].brand)

    page = args.page.read_text(encoding="utf-8")
    before = page
    page = splice(page, "headline", headline(roll))
    page = splice(page, "tracks", tracks(per_brand))
    page = splice(page, "provider-table", provider_table(per_brand))
    page = splice(page, "provider-total", totals_row(roll))
    page = splice(page, "weeks", weeks_chart(prof, worst))
    page = splice(page, "worst-weeks", churchill_weeks(per_brand_week, worst))
    page = splice(page, "before-after", before_after(roll, per_brand, worst))
    page = splice(page, "leaderboard", leaderboard(lb))

    if args.check:
        if page != before:
            print(f"{args.page} is stale -- rerun ui/render.py")
            return 1
        print(f"{args.page} is up to date with {args.results}")
        return 0

    args.page.write_text(page, encoding="utf-8")
    print(f"regenerated {args.page} from {args.results}")
    print(f"  worst provider: {worst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

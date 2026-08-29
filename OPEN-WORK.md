# Open work — UK home insurance market pricing

Last updated 2026-08-29. What is still to do. When something ships it leaves
this file. For *why* things are the way they are, read `docs/handoffs/`; where
that and this disagree, **this file wins**.

| | |
|---|---|
| `main` head | `8217cfe` "Generate the page from a run that reproduces the published figures" |
| Pushed | yes, both repos |
| Remote | `SMcode-source/uk-home-insurance-market-pricing` (private) |
| Public page | `SMcode-source/home-insurance-price-accuracy` at `1121147` → smcode-source.github.io/home-insurance-price-accuracy/. No local clone survives; `gh repo clone` it when needed |
| Tests | Full suite green on CI for `29075a4`, Python 3.11 and 3.13 (run `33269505529`). 209 collected. CI runs on every push and fails on skips, so it — not this machine — is the authority; locally use `.venv/Scripts/python -m pytest`, never a bare `python` |
| Uncommitted | none |

## Blocked on owner

Nothing. The McAfee Framework Host restart cleared the memory crisis: commit in
use fell from 64,975 MB to 17,900 MB, free commit from 246 MB to 34,228 MB, and
the full run that had died twice completed on the first attempt afterwards. If
the fork failures (`bash` exit 45/66/127, LightGBM "Model format error") ever
return, check `mc-fw-host` first — it was holding 26.0 of 39.6 GB.

## Where the code stands

**The page is generated, and the mechanism has been run end to end.**
`data/processed/poc_h3/` is a `--weeks-holdout 3` run over the ten approaches
the page shows, and it reproduces every published MdAPE exactly (47.33 / 42.31 /
13.47 / 9.91 / 6.72 / 5.63 / 4.60 / 6.29 / 5.30 / 4.48, both splits).
`ui/render.py --check` returns 0 against it, and `--results` now defaults there.

`residual_profile()` has run. Churchill's maximum training-week residual is
0.142% against the page's stated 0.15%, then +8.89 / +18.53 / +22.84 across the
three held-out weeks — the structural break, measured rather than asserted.

`recalibrate()`, the rolling harness, stage 3b and the first-holdout-week leak
guard are all exercised by that run. `AGG_COLUMNS` pins the twelve metric names
the page reads; `tests/test_page.py` guards the column contract, the marker set,
marker balance and the data-driven chart scales, all without fitting a model.

## Actionable next

Items 1-6 closed 2026-08-29, then both hardening items. The page is generated
from `poc_h3`, which reproduces every published MdAPE exactly;
`render.py --check` returns 0 with no arguments.

1. **Collect the first real quotes** — `docs/COLLECTION.md` is the plan. Phase 1
   is ~44 rows across 8 journeys, roughly 2 hours. Manual, and the only item
   here that cannot be delegated to the repo: it needs a genuine address and
   claims history, which is exactly why it cannot be automated.

2. **Optional: keep `ebm_per_brand_trend` out of routine runs.** Measured now,
   so the question is closed: 3,341s — 4.25x its base — to score 4.59 against
   `ebm_per_brand`'s 4.51 at a two-week horizon. Registered for completeness;
   never put it in front of a deliverable again.

## Parked — do not re-suggest

**Do not try to fix Churchill's bias with a better estimator.** The residual is
flat through every training week and jumps the week the data ends. That is a
reprice, not an under-fit, and weeks 0–8 contain no information about a week-9
break. This was settled with the per-week residual profile; the answer was
`recalibrate()`, which changes the operating assumption rather than the fit.
`docs/DESIGN.md` §15 has the reasoning.

**Do not automate quote collection.** Scripted PCW journeys breach site terms,
engage the UK database right, and can reach the Computer Misuse Act 1990.
`docs/COLLECTION.md` states the boundary. There is no version of this repo that
scrapes a comparison site.

**Do not diagnose LightGBM's "Model format error, expect a tree here" as a
model bug.** It is `lightgbm/engine.py:349` round-tripping the booster through
`model_to_string()`; under memory pressure the allocation fails mid-buffer and
the parser is handed a truncated model. It is an OOM wearing a disguise.

## Things that will bite you

- **`--only` runs overwrite the full run's CSVs.** That is how the ten-approach
  leaderboard came to exist only in a log file. Give every `--only` run its own
  `--out`. `data/processed/poc_h3/` is the one the page is built from — do not point
  an `--only` run at it.
- **A bare `python` is not this project's interpreter.** It resolves to the
  Store shim, which has pandas and numpy but no LightGBM, EBM, CatBoost,
  sklearn or pyarrow. Eighteen tests `importorskip("lightgbm")` and vanish
  silently, so `pytest` there reports success having skipped every
  `recalibrate()` and leak-guard test. Always `.venv/Scripts/python -m pytest`.
- **Running without `--data` overwrites `risks.parquet` and `quotes.parquet`
  in `--out`.** The published figures come from the existing pair at
  `data/processed/`; reproduce them with
  `--data data/processed/quotes.parquet --risks data/processed/risks.parquet`,
  not from a fresh `generate()`, whose defaults are 900 risks over 26 weeks and
  a different dataset entirely.
- **The published page is public and the data is synthetic.** Brand names are
  real, premiums are invented. The SYNTHETIC banner is load-bearing; do not
  reword it into something softer.
- **`--weeks-holdout` defaults to 2; the published page is 3.** The leaderboard
  looks entirely plausible either way — every model simply scores better on a
  shorter horizon (`gbm_per_brand` 4.60 at 3 weeks, 2.69 at 2). Every output
  directory now carries `run.json` with the argv that made it, so read that
  first; before it existed this cost a two-hour run.
- **Never commit `data/`.** `.gitignore` covers `raw`, `interim`, `processed`
  and `geo`; verified with `git check-ignore` this session.
- **A brand vanishing from a collection grid is not a missing row.** Declined is
  signal, blank is a gap, and `start_collection.py` pre-fills the grid so the
  two stay distinguishable.

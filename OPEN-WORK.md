# Open work — UK home insurance market pricing

Last updated 2026-08-29. What is still to do. When something ships it leaves
this file. For *why* things are the way they are, read `docs/handoffs/`; where
that and this disagree, **this file wins**.

| | |
|---|---|
| `main` head | `dba13ee` "Generate the page's figures from the run that produced them" |
| Pushed | yes — no commits ahead of `origin/main` |
| Remote | `SMcode-source/uk-home-insurance-market-pricing` (private) |
| Public page | `SMcode-source/home-insurance-price-accuracy` → smcode-source.github.io/home-insurance-price-accuracy/ — a separate clone, not a remote here |
| Tests | 209 collected; `tests/test_page.py` 4/4 green. **Full suite not run since the memory problem started** — treat 209 as a collection count, not a pass count |
| Uncommitted | `CONTRIBUTING.md`, `README.md`, `docs/DESIGN.md`, `evaluate/compare.py`, `ui/render.py` modified; `docs/COLLECTION.md`, `tests/test_page.py` new |

## Blocked on owner

**Restart the McAfee Framework Host.** `mc-fw-host` (pid 5088 at time of
writing) held **26.0 GB of the 39.6 GB** total process commit, with the system
at 64,975 MB of 65,221 MB and 246 MB free. `sc.exe stop mc-fw-host` returns
*Access is denied* — this session is not elevated. In an elevated PowerShell:

    Restart-Service mc-fw-host -Force

Everything under "actionable next" needs a Python run, and Python runs are
currently dying: the EBM job exited 127 at 23:33, and `bash` itself returned
exit 45/66 on three separate calls this session. Those are fork failures, not
code failures. Do not debug them as code failures.

## Where the code stands

The page's figures are *mechanically* generated but the mechanism has **never
been run end to end**. `ui/render.py` splices eight `<!-- gen: -->` regions;
all eight markers are present in `ui/index.html` (verified in both HEAD and
worktree) and the two chart scales read `var(--scale)` from the data. What is
missing is a results directory it can actually run against — see below.

`recalibrate()`, the rolling harness, stage 3b of `run_poc.py` and the
first-holdout-week leak guard are all committed and were verified end to end
before the memory problem. `residual_profile()` has still never executed.

New this session and uncommitted: `AGG_COLUMNS` in `evaluate/compare.py` pins
the metric column names the page reads; `ui/render.py` now fails at load with
the missing column named rather than an `AttributeError` three frames deep;
`tests/test_page.py` guards the column contract, the marker set, marker
balance, and that the chart divisors stay data-driven. Those four tests need no
model fit, so they run even with no memory.

## Actionable next

1. **Regenerate a full results directory.** This is the real blocker, and it is
   worse than "poc_sample is missing two files". `poc_sample/leaderboard.csv`
   holds **two** approaches (`gbm_per_brand`, `gbm_per_brand_trend`) because it
   was an `--only` run; `data/processed/leaderboard.csv` holds two others
   (`ridge_log`, `brand_geomean`) for the same reason. The ten-approach
   leaderboard on the published page survives **only** in
   `data/processed/poc_full2.log` — a log, not a CSV. Later `--only` runs
   overwrote the CSVs that produced it. So `render.py` cannot currently
   reproduce the published page from anything in the repo, and pointing it at
   `poc_sample` would silently shrink the leaderboard from ten rows to two.
   Fix by running the full POC once, to its own `--out`, and not reusing that
   directory for `--only` runs.

2. **Run `ui/render.py` and diff.** Once (1) exists, run it and confirm the
   output matches the current hand-written content. Any difference is either a
   builder bug or a number that was wrong on the page. Then rebuild the public
   page with `ui/build_public.py` and push the public repo.

3. **Exercise `residual_profile()`.** It is committed, wired into stage 3b, and
   has never run. Its output feeds the `weeks` chart.

4. **Settle `ebm_per_brand_trend`.** Never scored — two attempts died. It is
   listed in the README approach table (correctly, as a lineup entry) and is
   correctly absent from the page's leaderboard, which shows the ten approaches
   that actually have numbers. **Verdict criterion:** if a full run including
   it completes, add its row; if it dies a third time on memory, drop it from
   the table and say why, rather than leaving a described-but-unmeasured
   approach in the lineup indefinitely.

5. **Commit the uncommitted work** listed in the header table.

6. **Confirm CI is green on GitHub.** `.github/workflows/tests.yml` has never
   been observed running. `tests/test_page.py` joins the default `pytest -q`
   automatically, so it is covered without a workflow edit.

7. **Collect the first real quotes** — `docs/COLLECTION.md` is the plan.
   Phase 1 is ~44 rows across 8 journeys, roughly 2 hours. This is a manual
   task and cannot be delegated to the repo.

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
  `--out`.
- **The published page is public and the data is synthetic.** Brand names are
  real, premiums are invented. The SYNTHETIC banner is load-bearing; do not
  reword it into something softer.
- **`render.py --results` defaults to `data/processed/poc_sample`,** which is
  currently a two-approach directory. The default is a trap until (1) is done.
- **Never commit `data/`.** `.gitignore` covers `raw`, `interim`, `processed`
  and `geo`; verified with `git check-ignore` this session.
- **A brand vanishing from a collection grid is not a missing row.** Declined is
  signal, blank is a gap, and `start_collection.py` pre-fills the grid so the
  two stay distinguishable.

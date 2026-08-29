# a — The page cannot be regenerated

First handoff for this project. Supersedes nothing. This is a record of *what
was found and why it matters*; it is not edited later to stay true.

**For what is still to do, read `OPEN-WORK.md`, not this file.**

State at close: `main` at `dba13ee`, pushed, clean of unpushed commits. Seven
files uncommitted (three docs, `evaluate/compare.py`, `ui/render.py`, plus new
`docs/COLLECTION.md` and `tests/test_page.py`). Python runs are blocked on a
memory problem the session could not clear.

---

## 1. The published leaderboard exists only in a log file

This is the session's real finding, and it inverts the story the previous
session told itself. The reproducibility work — `ui/render.py`, the eight
`<!-- gen: -->` markers, the data-driven chart scales — was built and committed
(`dba13ee`) on the premise that the page's numbers would then come from a run.
They still do not, for a reason nobody had checked.

Measured:

    cut -d, -f1-3 data/processed/poc_sample/leaderboard.csv   -> 2 approaches
    cut -d, -f1-3 data/processed/leaderboard.csv              -> 2 approaches
    grep -c MdAPE data/processed/poc_full2.log                -> 21 lines

`poc_sample/leaderboard.csv` holds `gbm_per_brand` and `gbm_per_brand_trend`.
The root `leaderboard.csv` holds `ridge_log` and `brand_geomean`. Both are the
residue of `--only` runs that overwrote whatever was there before. The
ten-approach table on the public page — global_geomean 47.33, brand_geomean
42.31, ridge_log 13.47, ebm_pooled 9.91, ebm_per_brand 6.72, gbm_pooled 5.63,
gbm_per_brand 4.60, catboost_pooled 6.29, random_forest 5.30,
gbm_per_brand_trend 4.48 — survives nowhere except `poc_full2.log`.

So the mechanism that exists to stop the page going stale cannot yet be run
against anything that would reproduce the page. Worse, `render.py --results`
defaults to `poc_sample`, so the obvious first command would silently shrink
the leaderboard from ten rows to two and look like it worked.

The generalisable lesson: **an `--only` run and a full run must never share an
`--out`.** Selective reruns are cheap and frequent; they quietly destroy the
expensive artefact. Nothing warned, because overwriting a CSV is a normal thing
for a pipeline to do.

## 2. Every number in this project is synthetic, and the chain is short

Asked directly where the data came from. Traced it rather than answering from
memory, because the page is public and names real insurers:

`collect/synthetic.py` invents the market → `scripts/make_sample_extract.py`
writes it in the shape of a Consumer Intelligence extract →
`data/raw/sample_ci_extract.csv` (46,800 quotes, 393 risks, 12 weeks) →
`collect/vendor.py` → features → models → the page.

Real: brand names from `config/providers.yml`, UK outcodes, the *form* of UK
household rating. Invented: every premium, relativity, decline and price move.
`data/geo/` is empty — the Environment Agency and other sources named in
`features/geo.py` have never been downloaded, so the flood, crime and
subsidence bands are the generator's own `_AREAS` table at `synthetic.py:40`.

Consequence worth stating in one line, because it is easy to lose: *"Churchill
is under-predicted by 14.8%"* means the simulator moved a brand labelled
Churchill and the model was slow to notice. It says nothing about Churchill.
`docs/DESIGN.md` "Known limitations" now opens with this rather than implying
it.

## 3. Fifty real quotes buys less than it sounds, and the unit is wrong

Drafting `docs/COLLECTION.md` turned on one observation that changes the whole
design: **a PCW journey returns 20–40 quotes at once.** So "50 quotes" is about
two journeys if spent carelessly. The unit of cost is the journey (10–20
minutes); the unit of data is the quote. Design around journeys.

The binding constraint on what can be varied is sharper than expected. Facts —
name, DOB, address, claims history, property attributes — cannot be varied:
Fraud Act 2006 s.2, and separately an unresolvable identity returns the
insurer's price for a person who does not exist, so the row is not a market
price for the risk. Only *choices* can be varied (excess, cover type, extras),
and in this schema each variant is a new `risk_id`, because `Risk` in
`schema.py:88` carries `voluntary_excess` on the risk, not on the quote.

That rules out the obvious one-factor-at-a-time design and pushes the budget
onto the two axes that are free of the constraint: **channel** (same brand,
same day, PCW vs direct) and **time** (same journey, weekly). Those are also
the two things `simulate.py` and `models/drift.py` currently assert on faith.

Rejected, so nobody re-litigates: an excess ladder in Phase 1. It spends
journeys on a factor the schema already models, to learn a relativity that is
specific to one house.

Also noted, and cheaper than any of it: an FCA-mandated renewal notice shows
last year's premium beside this year's. That is a real, cover-matched,
year-on-year delta for zero journeys.

## 4. The memory problem is one process, and it disguises itself

`mc-fw-host` (McAfee Framework Host) held **26.0 GB of the 39.6 GB** total
process commit — measured with `wmic process get PageFileUsage`, not from
`tasklist`, whose working-set column showed it at 1.96 GB and hid the problem
entirely. System commit was 64,975 MB of 65,221 MB with 246 MB free.

The failure modes it produces do not look like memory:

- LightGBM `Model format error, expect a tree here` — `engine.py:349`
  round-trips the booster through `model_to_string()`; a failed allocation
  hands the parser a truncated model. Already known, restated because it
  misled three earlier runs.
- `bash` returning exit **45**, **66** and **127** on ordinary `git`/`grep`
  calls. These are fork failures. The EBM job's `poc exit=127` at 23:33 is the
  same thing, not a Python error — `ebm_per_brand_trend` has still never been
  scored.
- PowerShell itself raising `OutOfMemoryException` while reading its own config.

`sc.exe stop mc-fw-host` returns *Access is denied*; the session is not
elevated and could not clear it. Requires the owner.

## 5. Two things this session got wrong

**The markers were already committed.** The session opened by inserting eight
`<!-- gen: -->` marker pairs into `ui/index.html`, on the summarised belief that
they were missing. `git show HEAD:ui/index.html | grep -c "<!-- gen:"` returns
8, and `git status` reports the file unmodified — so `dba13ee` already carried
them and the edit produced no net change. The script reported success, which
means its output could not be trusted as evidence that it had done anything.
Verify against `git`, not against a script's own print statement.

**The new guard's first version was broken.** `test_chart_scales_stay_data_driven`
failed on its first run with "no chart rule found for --was". The regex used
`[^)]+?` for the divisor, which cannot match `var(--scale, 15)` because of the
inner closing paren. Fixed to `.+?` anchored on `* 100%`. Then confirmed the
guard actually fires, rather than assuming: applied to a hardcoded `/ 15` it
reports `guard passes=False`, and to `var(--scale, 15)` it reports `True`. A
guard nobody has watched fail is a guard nobody has tested.

## 6. What was added, and why it is cheap

`tests/test_page.py` — four tests that need no model fit, chosen deliberately
so they still run on a machine with no memory to spare:

- `AGG_COLUMNS` (new, `evaluate/compare.py`) pins the twelve metric column
  names. `render.py` reads them by name out of CSVs, so a rename upstream
  breaks the page and nothing else. The test asserts `render.NEEDS_SUMMARY` is
  a subset.
- The marker set written by `splice()` must equal the marker set present in the
  page — the exact failure this session started by mis-diagnosing.
- Markers must be balanced, or `splice()` would consume the rest of the page.
- The chart divisors must stay `var(--scale)`.

`render.py` also now validates the columns of all five CSVs at load and exits
naming the missing one, instead of throwing an `AttributeError` three frames
deep inside a builder.

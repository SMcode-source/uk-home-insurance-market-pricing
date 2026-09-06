# Open work — UK home insurance market pricing

Last updated 2026-09-06. What is still to do. When something ships it leaves
this file. For *why* things are the way they are, read `docs/handoffs/`; where
that and this disagree, **this file wins**.

| | |
|---|---|
| `main` head | `d233cf0` "Point the OPEN-WORK header at the commit it describes" |
| Pushed | yes, both repos, as of `d233cf0` |
| Remote | `SMcode-source/uk-home-insurance-market-pricing` (private) |
| Public page | `SMcode-source/home-insurance-price-accuracy` at `1121147` → smcode-source.github.io/home-insurance-price-accuracy/. No local clone survives; `gh repo clone` it when needed |
| Tests | Full suite green locally on 2026-09-06 with all the uncommitted work below: 281 passed under `.venv/Scripts/python -m pytest` (1h25m wall clock, but that run shared the machine with three vendor-load smoke runs; the previous clean run of 236 took 6m20s). CI has not seen it yet. CI runs on every push and fails on skips, so it — not this machine — is the authority; never a bare `python`. `openpyxl` is now a core dependency; CI installs from `pyproject.toml`, so it will pick it up |
| Uncommitted | **Yes — both 2026-09-06 sessions' work, listed under "Where the code stands". Review and commit it.** |

## Blocked on owner

**Commit the 2026-09-06 work.** Two sessions' worth, listed below. Neither was
asked to commit, so neither did.

**Put the vendor questions to Consumer Intelligence and Defaqto Market
Pricing.** `docs/VENDOR-EXTRACTS.md` §4 lists them. Four answers gate the first
load and cannot be read off a file: premium basis, IPT treatment, whether
declines are rows, whether the extract is a top-N cut. Ask for a redacted
sample day before signing; the loader is built for the shape a sample will
confirm or correct. Note that there are two vendors, not three: Pearson Ham's
pricing business was sold to Defaqto in January 2026.

**Decide what to do about `subsidence_band` on the manual tier.**
`features.geo.REQUIRED_GEO_COLUMNS` includes it and BGS GeoSure is licensed, so
`check_ready_for_modelling()` will refuse a real hand-collected risk until a
`data/geo/subsidence.csv` exists — even though on a single property every geo
feature is a constant the level models never read. Options: move it to
`OPTIONAL_NUMERIC` (the synthetic run is unchanged because the generator
supplies it), or accept a one-row supplied file. Design call; `docs/DESIGN.md`
§7 currently says "licensed — interface only".

## Where the code stands

**The manual collection path now reaches the models, and the data decides the
lineup.** Before 2026-09-06, `read_session()` returned dicts and nothing turned
them into the parquet pair `run_poc.py` reads; the only data source the repo can
use without a licence had no way in. Now:

- `scripts/start_collection.py` also writes `data/raw/risks.yml`, a risk
  skeleton whose required fields are blank on purpose and fail validation until
  filled. `collect/session.py` gained `write_risk_template`,
  `read_risk_definitions`, `session_to_canonical` (brands resolved through
  `BrandResolver`, rows validated as `Quote`) and `append_quotes` (re-ingesting
  a corrected grid replaces rows on `(risk, brand, channel, date)`).
- `scripts/ingest_session.py` runs grids + risk file → coverage report →
  append → geo-enrich → readiness gate → adequacy report → prints the
  `run_poc.py` command. Default output `data/processed/manual/`, its own
  directory, never `data/processed/`.
- `evaluate/adequacy.py` classifies the model matrix before any fit:
  `level_only` / `thin` / `cross_section`, whether the spatial split can be
  asked, whether there are more weeks than the holdout, and which approaches
  the data can support, each exclusion with its reason. `run_poc.py` prints it,
  writes `adequacy.json`, restricts the lineup (an explicit `--only` wins and
  says so), and passes `spatial=` to `run_comparison`, which now accepts it.
- `brand_last_level` is registered: median log-premium of the last observed
  week per brand × channel, carried forward; `recalibrate()` replaces it. It is
  the model the `level_only` tier is for. Scored: 2.41% MdAPE blind vs
  `brand_geomean` 5.24% on an eight-week single-property test panel (1.44%
  under weekly refresh); 43.64 vs 42.31 on the rotating sample cross-section,
  where it should lose (`data/processed/poc_last_level/`). `docs/DESIGN.md`
  §16 has the reasoning.
- Verified end to end on a synthetic single-property panel through the real
  ingest script and `run_poc.py`: tier `level_only`, spatial skipped, nine
  rating approaches excluded with reasons, `brand_last_level` chosen as the
  premium model, weekly refresh run, index built from the declared basket.
- `docs/DATA-SOURCES.md` (new, 290 lines, every claim cited) records how quote
  and price data for the first ten brands can actually be obtained. Short
  version: no legitimate programmatic quote source exists for a consumer; per-
  brand per-quote data at scale is Consumer Intelligence, Pearson Ham or
  Defaqto under licence; the only free files are the FCA value-measures xlsx
  (per-underwriter claims bands, no prices) and the ONS contents-insurance CPI
  series (CSV endpoint, tested).
- `config/providers.yml` corrected against primary sources: Direct Line Group
  brands → Aviva (owned since 1 July 2025); LV= → Allianz; Esure → Ageas
  (completed 29 Sep 2025); Darwin removed (car only); More Than is PCW-only;
  Privilege and Ageas also sell direct; Direct Line home went on PCWs on
  3 Sep 2026 with PCW-specific tiers. Two tests updated to match.
- CI's smoke run (`--quick --only global_geomean,ridge_log,gbm_per_brand,
  gbm_per_brand_trend`) re-run locally with the adequacy hook: exit 0,
  `cross_section`, all outputs present.

Files: `src/mktpricing/evaluate/adequacy.py` (new), `scripts/ingest_session.py`
(new), `tests/test_adequacy.py` (new, 13 tests), `tests/test_session_ingest.py`
(new, 14 tests), `docs/DATA-SOURCES.md` (new); modified `collect/session.py`,
`models/approaches.py`, `evaluate/compare.py`, `scripts/run_poc.py`,
`scripts/start_collection.py`, `config/providers.yml`, `README.md`,
`docs/DESIGN.md`, `docs/COLLECTION.md`, `tests/test_vendor.py`.

**The vendor path now takes files in the forms vendors send them, specs are
config, and the observed market price exists.** Second session of 2026-09-06,
for the owner's coming per-brand, per-quote licence:

- `docs/VENDOR-EXTRACTS.md` (new, 362 lines, every claim cited and graded
  VERIFIED / INFERRED / UNKNOWN) records what Consumer Intelligence and Defaqto
  Market Pricing deliver: products, panel design, delivery formats, the
  metric-level field inventory, a draft mapping to the canonical schema, and
  the questions to ask. Headline: Pearson Ham's pricing business was sold to
  Defaqto on 19 January 2026 and rebranded Defaqto Market Pricing on 1 June
  2026, so there are two vendors. **No vendor publishes column names**; every
  spec remains a guess until a file is profiled.
- `collect/vendor.py`: `VendorSpec` gained layout fields (`sheet`,
  `header_row`, `delimiter`, `encoding`, `layout: long|wide`, `wide_*`,
  `notes`) and `to_yaml` / `from_yaml`; `load_spec()` resolves a built-in name,
  a file under `config/vendor_specs/`, or a path (file wins over built-in);
  `read_extract()` reads CSV in any delimiter (sniffed, also inside gzip/zip),
  TSV, Excel by sheet with title rows skipped, Parquet and JSON, with a cp1252
  fallback; `expand_paths()` / `read_extracts()` stack a folder, glob or list
  and record `source_file`; `melt_wide()` turns a brands-across table into
  rows with the blank-cell meaning declared; a vendor's own underwriter column
  is kept as `underwriter_raw` with disagreements against `providers.yml`
  reported; `draft_spec()` and `suggest_spec(fmt="yaml")` emit the YAML form.
  `PEARSON_HAM_SPEC` / `Source.vendor_ph` added for historic files only.
- `config/vendor_specs/{ci,defaqto,pearson_ham}.yml` (new): the specs as
  config, with the acquisition and the unconfirmed facts in the header
  comments. A test asserts each YAML equals its Python twin.
- `scripts/inspect_vendor.py`: takes files, folders and globs; `--spec` by
  name or path; `--draft-spec FILE.yml`; `--sheet`, `--header-row`,
  `--delimiter`; `--append` (rows replaced on risk, brand, channel, date, via
  `session.append_quotes`); default `--out` is now `data/processed/<spec>/`,
  never `data/processed/` itself; prints an observed-market headline and the
  `market_price.py` command; writes `load.json`.
- `market/observed.py` (new): `observed_market` (best price, top-k mean /
  median / k-th, spread in GBP and %, panel spread, counts, each brand once at
  its cheapest channel, declines counted never priced, `period` day/week/month,
  `by_channel`), `market_by_period` (index on a basket), `brand_competitiveness`
  (quote rate, cheapest share, top-k share, gap to leader and to top-k),
  `channel_gap` (direct over cheapest PCW per brand), `spread_summary`.
  `docs/DESIGN.md` §17 has the definitions and why each is a design choice.
- `scripts/market_price.py` (new): the report, from canonical parquet or
  straight from vendor files with `--spec`; declared basket, then derived,
  then no index; writes four CSVs and `market.json`. Verified on the synthetic
  sample (`--period week`: 40-risk derived basket, spread median 22-28% of
  best) and on the sample CI extract loaded from Excel, from a gzipped
  semicolon-delimited weekly folder, and appended a second time (7,200 rows,
  no duplicates).
- `openpyxl` added to core dependencies (Excel was declared and untested; it
  was not installed in the venv).
- Tests: `tests/test_vendor_files.py` (new, 25), `tests/test_observed_market.py`
  (new, 18). Full suite: 281 passed.

Files: `docs/VENDOR-EXTRACTS.md`, `config/vendor_specs/*.yml`,
`src/mktpricing/market/observed.py`, `scripts/market_price.py`,
`tests/test_vendor_files.py`, `tests/test_observed_market.py` (all new);
modified `collect/vendor.py`, `schema.py`, `scripts/inspect_vendor.py`,
`pyproject.toml`, `README.md`, `docs/DESIGN.md`, `docs/DATA-SOURCES.md`,
`docs/COLLECTION.md`, this file.

The page is unchanged and still generated from `data/processed/poc_h3/`, which
reproduces every published MdAPE exactly; `render.py --check` is unaffected by
this work (no CSV columns or markers changed).

## Actionable next

0. **When the first vendor file lands.** `python scripts/inspect_vendor.py
   <file-or-folder>` (with `--sheet`/`--header-row` for Excel) to profile it;
   `--draft-spec config/vendor_specs/<vendor>.yml` to save the guessed mapping;
   correct the column names and the four declared facts against the vendor's
   answers; `--spec <vendor> --geo data/geo --write`; read the BLOCKERs; then
   `scripts/market_price.py` for the top-5 / best / spread the same day, and
   `run_poc.py` once geo is in place. A top-N cut is fine for the market price
   and a BLOCKER for per-brand modelling; the audit says which.

1. **Download the free geo files into `data/geo/`.** `data/geo/` is still
   empty, so a real postcode cannot be enriched and `ingest_session.py` will
   write output that is not model-ready. `features.geo.missing_files()` lists
   the five free downloads with URLs (EA flood, Land Registry, IMD, police.uk,
   ONSPD). Subsidence is the licensed one; see "Blocked on owner".

2. **Collect the first real quotes** — `docs/COLLECTION.md` is the plan. Phase 1
   is ~44 rows across 8 journeys, roughly 2 hours. Manual, and the only item
   here that cannot be delegated to the repo. The ingest path now exists, so
   the sitting ends with `ingest_session.py` rather than a CSV on disk. Expect
   the adequacy report to say `level_only`; that is correct for one property.

3. **Optional: ingest the two free aggregate series as a plausibility check.**
   ONS D7F2 (contents CPI, CSV endpoint) and the ABI quarterly tracker (three
   hand-keyed numbers) would let the synthetic index's level and drift be
   checked against something real. Not a model input; a sanity check.
   `docs/DATA-SOURCES.md` §3.6 and §3.9 have the details.

4. **Optional: keep `ebm_per_brand_trend` out of routine runs.** Measured and
   closed: 3,341s — 4.25x its base — to score 4.59 against `ebm_per_brand`'s
   4.51 at a two-week horizon. Registered for completeness; never put it in
   front of a deliverable again.

## Parked — do not re-suggest

**Do not try to fix Churchill's bias with a better estimator.** The residual is
flat through every training week and jumps the week the data ends. That is a
reprice, not an under-fit, and weeks 0–8 contain no information about a week-9
break. This was settled with the per-week residual profile; the answer was
`recalibrate()`, which changes the operating assumption rather than the fit.
`docs/DESIGN.md` §15 has the reasoning.

**Do not automate quote collection.** Scripted PCW journeys breach site terms,
engage the UK database right, and can reach the Computer Misuse Act 1990.
`docs/COLLECTION.md` states the boundary, and `docs/DATA-SOURCES.md` §5 now
quotes where each PCW's terms say so. There is no version of this repo that
scrapes a comparison site, and no insurer in the ten offers a consumer quote
API to use instead.

**Do not look for a free per-brand price feed.** Searched 2026-09-06 against
primary sources; there is none. The ABI, Consumer Intelligence and Pearson Ham
publish aggregate top-5 movements in prose. The FCA publishes claims metrics,
not premiums. Per-brand, per-quote data is licensed or hand-collected.

**Do not diagnose LightGBM's "Model format error, expect a tree here" as a
model bug.** It is `lightgbm/engine.py:349` round-tripping the booster through
`model_to_string()`; under memory pressure the allocation fails mid-buffer and
the parser is handed a truncated model. It is an OOM wearing a disguise.

## Things that will bite you

- **`--only` runs overwrite the full run's CSVs.** That is how the ten-approach
  leaderboard came to exist only in a log file. Give every `--only` run its own
  `--out`. `data/processed/poc_h3/` is the one the page is built from — do not
  point an `--only` run at it. `poc_last_level/` is the `brand_last_level`
  scoring run and nothing else.
- **`brand_last_level` is a fixed-panel baseline, not a rating model.** It
  loses on any rotating cross-section by construction (mix confounding), and
  the harness will still rank it. Read `adequacy.json` before reading the
  leaderboard.
- **An explicit `--only` bypasses the adequacy exclusions.** Deliberately —
  but the leaderboard it produces on a `level_only` panel is noise ranked by
  noise, and the run says so once, above the table.
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
  directory carries `run.json` with the argv that made it, so read that first.
- **Never commit `data/`.** `.gitignore` covers `raw`, `interim`, `processed`
  and `geo`. `data/raw/risks.yml` describes a real address and is covered.
- **A brand vanishing from a collection grid is not a missing row.** Declined is
  signal, blank is a gap, and `start_collection.py` pre-fills the grid so the
  two stay distinguishable. `ingest_session.py` prints which brands were never
  asked, per channel.
- **Ownership changed under the config.** Aviva owns Direct Line Group; Ageas
  owns esure; Allianz owns LV= GI. The correlated-brand trap in
  `docs/COLLECTION.md` now groups them accordingly. Panel arrangements keep
  moving; `docs/DATA-SOURCES.md` is dated and says what was verified.
- **"Pearson Ham data" is Defaqto data.** The business changed hands in
  January 2026. `--spec pearson_ham` is for historic raw files only; a current
  delivery is `--spec defaqto`. `Source.vendor_ph` rows and `vendor_dfq` rows
  may be the same panel in two layouts; do not read the split as two vendors.
- **A spec file beats the built-in of the same name.** `load_spec("ci")`
  returns `config/vendor_specs/ci.yml` if it exists, not `CI_SPEC`. That is the
  point (the file is the corrected one), but a test asserts they are equal
  today, so correcting the YAML without the Python twin fails that test. Either
  update both or drop the guard deliberately.
- **`inspect_vendor.py --write` now defaults to `data/processed/<spec>/`.** It
  used to write into `data/processed/` and would have overwritten the synthetic
  parquet pair the published page depends on. `--append` replaces rows on
  (risk, brand, channel, date); without it a re-run overwrites the directory.
- **A blank cell in a wide file has no default meaning.** `wide_blank_means`
  is `absent` (brand not on that panel, row dropped) or `declined` (a
  non-quote). The two give different market prices and the file cannot tell
  you which; the spec must.
- **`market_price.py` indexes on a basket or not at all.** Without a declared
  or derived basket it prints per-period means and drops `index_100`, on
  purpose. Defaqto's panel rotates by design, so expect that on their daily
  files until a matched sub-panel is agreed.

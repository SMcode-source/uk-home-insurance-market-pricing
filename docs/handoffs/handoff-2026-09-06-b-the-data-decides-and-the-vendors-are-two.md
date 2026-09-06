# b — The data decides the lineup, and the vendors are two

Second handoff. Supersedes nothing; `a` still stands. This is a record of *what
was found and why it matters*; it is not edited later to stay true.

**For what is still to do, read `OPEN-WORK.md`, not this file.**

State at close: `main` at `d233cf0` when the two sessions of 2026-09-06 began,
pushed and clean. Everything below was uncommitted at the end of the second
session and committed on 2026-09-07 in the merge that carries this file. Full
suite 281 passed under `.venv/Scripts/python -m pytest`.

---

## 1. There is no free per-brand price feed, and no legitimate quote API

The first session's question was how quote or price data for the first ten
brands in `config/providers.yml` can actually be obtained. Answer, checked
against primary sources and recorded with citations in `docs/DATA-SOURCES.md`:

- No insurer in the ten offers a consumer quote API. The PCWs' terms forbid
  automated access, and the repo's boundary (`docs/COLLECTION.md`) already said
  so; §5 of DATA-SOURCES now quotes where each PCW's terms say it.
- Per-brand, per-quote data at scale is licensed. The only free files are the
  FCA General Insurance value-measures spreadsheet (per-underwriter claims
  metrics, no prices) and the ONS contents-insurance CPI series D7F2, which has
  a CSV endpoint that was fetched and works. The ABI, Consumer Intelligence and
  the former Pearson Ham publish aggregate top-5 movements in prose only.
- `config/providers.yml` was wrong about ownership. Aviva has owned Direct Line
  Group since 1 July 2025 (Direct Line, Churchill, Privilege); Admiral has owned
  More Than since 2 April 2024; Ageas completed esure on 29 September 2025; LV=
  GI is Allianz. Darwin is a car-only brand and was removed. More Than is PCW
  only; Privilege and Ageas also sell direct. Direct Line home went on PCWs for
  the first time on 3 September 2026 with PCW-specific tiers, which is why
  `docs/COLLECTION.md` gained trap 8: a PCW product is not always the direct
  product.

Consequence the config now carries: `underwriter` means the pricing group, not
the legal carrier. Four Aviva-group brands are not four observations.

## 2. The manual path never reached the models

`read_session()` returned dicts and nothing turned them into the parquet pair
`run_poc.py` reads. The only data source the project can use without a licence
had no way into the pipeline. The session built it: `start_collection.py`
writes a risk skeleton whose required fields are blank and fail validation
until filled; `collect/session.py` gained `read_risk_definitions`,
`session_to_canonical` and `append_quotes`; `scripts/ingest_session.py` runs
grid plus risk file to coverage report, append, geo-enrich, readiness gate,
adequacy report, and prints the run command.

## 3. The harness lies politely on a single property

Two failures that do not announce themselves, found by running the new ingest
path end to end on a synthetic eight-week single-property panel:

- Every risk feature is a constant, so a rating model fits the mean and the
  leaderboard ranks twelve approaches by noise.
- One postcode area, and `spatial_split` holds out at least one, so the training
  set is empty and every approach reports FAILED, which reads as broken models.

`evaluate/adequacy.py` now inspects the model matrix before any fit and
classifies it `level_only` / `thin` / `cross_section`, decides whether the
spatial split can be asked and whether there are more weeks than the holdout,
and excludes approaches with a printed reason. `run_poc.py` writes
`adequacy.json` and passes the eligible lineup; an explicit `--only` overrides
it and says so. `brand_last_level` was added as the model the `level_only` tier
is for: last observed level per brand and channel, carried forward, replaced by
`recalibrate()`.

Measured:

    single-property panel, 8 weeks, holdout 1:
      brand_last_level  2.41% MdAPE blind, 1.44% under weekly refresh
      brand_geomean     5.24%
    rotating synthetic cross-section (data/processed/poc_last_level/):
      brand_last_level  43.64      brand_geomean  42.31

The second result is the one to remember. `brand_last_level` loses on a
rotating cross-section by construction, because last week's brand median is
confounded with last week's mix, and the harness will still rank it. Read
`adequacy.json` before the leaderboard.

## 4. The vendors are two, and none publishes a column name

The second session's question was what Consumer Intelligence, Pearson Ham and
Defaqto deliver, so the owner's coming per-brand, per-quote licence can be
loaded and priced the day it arrives. `docs/VENDOR-EXTRACTS.md` records it with
every claim graded VERIFIED / INFERRED / UNKNOWN.

- **Pearson Ham Group sold its insurance pricing business to Defaqto (Fintel
  plc) on 19 January 2026 for GBP 11.0m; it was rebranded Defaqto Market Pricing
  on 1 June 2026.** Pearson Ham Group is now CIL Pearson Ham, a consultancy.
  Defaqto's Market Pricing Intelligence page is that business. Two vendors, not
  three. `Source.vendor_ph` and the `pearson_ham` spec were kept for historic
  raw files only.
- **No vendor publishes column names.** No data dictionary, sample file, API
  document or table screenshot exists in public. ONS refused field-level detail
  on the CI feed twice under s43 FOIA. What exists is each vendor's metric
  vocabulary, which is enough to say which canonical fields are almost
  certainly present and which four facts must be asked in writing: premium
  basis, IPT treatment, whether declines are rows, whether the extract is a
  top-N cut.
- Consumer Intelligence Market View: annual price, compulsory and voluntary
  excess for each insurer on the market, rank; raw data as Excel spreadsheets,
  weekly or monthly; four PCWs plus 32 to 34 direct sites. Voluntary excess is
  set per profile, so it lives on the risk. Underwriter View adds the
  underwriter from MoneySuperMarket only.
- Defaqto Market Pricing: four PCWs only, no direct channel mentioned anywhere,
  real-consumer profiles run a few consecutive days and drop out. Their public
  index is a top-5 average, so a top-5 cut of the raw file is a real
  possibility, and the audit's `rotating_panel` finding will fire on any daily
  file from either vendor.

## 5. What was built for the first file

- `collect/vendor.py`: `VendorSpec` gained layout fields and a YAML form;
  `load_spec()` resolves a built-in name, a file under `config/vendor_specs/`
  or a path, and the file wins; `read_extract()` reads CSV in any delimiter
  (sniffed, also inside gzip and zip), TSV, Excel by sheet with title rows
  skipped, Parquet and JSON, with a cp1252 fallback; `read_extracts()` stacks a
  folder, glob or list and records `source_file`; `melt_wide()` turns a
  brands-across table into rows with the blank-cell meaning declared; a
  vendor's own underwriter column is kept as `underwriter_raw` and
  disagreements with `providers.yml` are reported.
- `config/vendor_specs/{ci,defaqto,pearson_ham}.yml`, with a test that each
  equals its Python twin.
- `scripts/inspect_vendor.py`: folders and globs, `--spec` by name or path,
  `--draft-spec`, `--sheet`, `--header-row`, `--append`, default output
  `data/processed/<spec>/`.
- `market/observed.py` and `scripts/market_price.py`: best price, top-5 mean /
  median / 5th, spread as 5th minus best in GBP and as a share of best, panel
  spread, per-period index on a basket, per-brand competitiveness, direct over
  cheapest PCW per brand. Each brand once at its cheapest channel; declines
  counted, never priced; fewer than five quoting reported, not padded.
  `docs/DESIGN.md` §17 records why each definition is a design choice.

Measured on the synthetic sample (`--period week`, 40-risk derived basket):
best price mean GBP 250 to 314 by week, top-5 mean GBP 346 to 393, spread
median 22 to 28% of best, panel spread median 44 to 69%. The numbers are
synthetic; the point is that the report runs off a folder of vendor-shaped
files with no model and no geo features.

## 6. Rejected alternatives

- **Detecting premium basis, IPT, declines and truncation from the file.**
  Kept as declarations on the spec, as before. A detector that is wrong once
  rescales the whole dataset and every relative metric still looks fine. The
  audit sanity-checks the result and reports, which is the right division.
- **A single Source for Defaqto and Pearson Ham.** The research doc argued for
  it. Kept two, because a historic Pearson Ham raw file and a current Defaqto
  extract may be the same panel in two layouts, and accuracy is reported by
  source. OPEN-WORK tells the reader not to read the split as two vendors.
- **Spread as top-5 mean minus best, or as panel range.** Chose 5th minus best.
  The mean-based gap hides the shape of the five; the panel range is dominated
  by one specialist quoting a mainstream risk high. Both alternatives are still
  reported as columns; only the headline was chosen.
- **Adding the observed market to `run_poc.py`.** Not done. The harness already
  compares predicted and observed top-5 through `topN_price_err`, and a
  separate script is what the owner asked for: a number the day a file lands.

## 7. Mistakes the sessions made

- Excel reading was declared in `read_extract()` and had never been run:
  `openpyxl` was not installed in the venv and not a dependency. Added to core
  dependencies. CI installs from `pyproject.toml`, so it will pick it up.
- The delimiter sniffer read the raw bytes of a gzipped file and found no
  delimiter, so a semicolon-delimited `.csv.gz` fell to a comma and the parser
  died on row 32. Fixed by sniffing through the compression layer; a test now
  covers the gzipped non-default-delimiter case.
- A first `melt_wide()` created `brand` and `premium` columns the spec did not
  name, so `apply_spec()` never mapped them. Fixed by adding the two to the
  effective mapping after the melt.
- A test asserted the median of 20, 20 and 10 was 15. It is 20.
- The full suite took 1h25m instead of the usual six minutes because it shared
  the machine with three vendor-load smoke runs. Not a regression; recorded so
  the next reader does not chase it.
- The `providers.yml` corrections broke two tests that asserted Churchill's and
  Direct Line's underwriter was Direct Line Group. Updated to Aviva. The tests
  were right to fail; the config had been stale for over a year.

## 8. Still open at close

See `OPEN-WORK.md`. The two items that only the owner can move: put the
vendor questions to CI and Defaqto and get a redacted sample day; decide the
`subsidence_band` gate for the manual tier, since BGS GeoSure is licensed and
`data/geo/` is still empty.

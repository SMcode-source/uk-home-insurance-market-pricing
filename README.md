# UK Home Insurance Market Pricing

Estimate what **each provider** would charge for a given risk, generate a
**cheapest-5 market price**, and track both **weekly**. Built to compare several
modelling approaches head-to-head on held-out data rather than committing to one
up front.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[models,dev]"   # Windows
python scripts/run_poc.py --quick
```

The POC runs on a synthetic market, so the whole pipeline works before any real
data arrives — and because the synthetic engine's true parameters are known, you
can measure whether an approach **recovered the rating structure** or merely
fitted noise. You never learn that from real data.

Fits are single-worker by default. EBM bags through joblib's loky backend, so
each worker is a whole extra interpreter and a per-brand sweep pays that once
per brand — enough to kill the run on a loaded machine, inside a thread whose
failure no approach can catch and report. Raise it with `--jobs N` where there
is memory headroom. Do not buy speed by cutting `outer_bags` or `max_rounds`
instead: that under-fits the EBM and inflates the additivity gap below.

---

## What it does

```
collect/  →  features/  →  models/  →  evaluate/  →  market/
 quotes      risk feats    N models   held-out acc   cheapest-5 + index
```

1. **Collect** — self-collected quotes, vendor extracts, or synthetic. One
   canonical schema, so a Consumer Intelligence / Defaqto file and a
   hand-collected POC quote train the same models (`vendor.py` maps and audits
   the former).
2. **Features** — log-premium target, geography as risk features not raw
   postcode (`geo.py` resolves real UK postcodes).
3. **Models** — eleven approaches from a geometric mean to per-brand boosting.
4. **Evaluate** — temporal and spatial holdouts, premium *and* ranking accuracy.
5. **Market** — Monte Carlo over quote/decline, then cheapest-N and a weekly index.

## The approaches under test

| Approach | What it is | Why it's in the lineup |
|---|---|---|
| `global_geomean` | one number | the floor any model must clear |
| `brand_geomean` | per-brand mean | deceptively strong — beat this or stop |
| `ridge_log` | log-linear ridge | right shape for a purely multiplicative engine |
| `ebm_pooled` | EBM, brand as feature | readable curves, cheap |
| `ebm_per_brand` | one EBM per brand | **the design recommendation** |
| `gbm_pooled` | LightGBM | unrestricted interaction order |
| `gbm_per_brand` | LightGBM per brand | usually the best raw error |
| `catboost_pooled` | CatBoost | strong on high-cardinality categoricals |
| `random_forest` | bagged trees | sanity check against boosting |
| `gbm_per_brand_trend` | + forward drift correction | forecasts past the training weeks |
| `ebm_per_brand_trend` | + forward drift correction | same, on the readable model |

Adding a twelfth is one class plus a `@register` decorator — the evaluation code
never changes. Approaches whose library is missing are reported as **skipped**,
never silently dropped.

### Forecasting past the last week you trained on

A tree has no split beyond its largest trained `week`, so it prices every future
week at the final leaf. A brand that repriced after the cutoff is then wrong by a
growing level offset — on the sample data, Churchill drifted to −22.6% bias by
week three while the aggregate MdAPE looked fine.

The `*_trend` approaches correct it, and the shape of the fix matters: they leave
the underlying model untouched and add only the level *change* beyond the last
trained week, so in-window predictions are bit-identical. Re-expressing the model
as shape-plus-level instead — the obvious version — costs ~2 MdAPE points at a
one-week horizon, because a quote sitting on its brand's minimum premium does not
move when the brand's level moves.

Whether to project a trend at all is validated on held-out weeks rather than
assumed, since price levels wander more than they march. Expect modest gains
(4.60% → 4.48% at three weeks here, nothing at one) and read `drift_report()`
before believing a per-brand slope.

### Structural breaks need new data, not a better extrapolation

Extrapolation has a hard ceiling and it is worth knowing where it sits. On the
sample data Churchill is fitted to within 0.15% in *every* training week, week 8
included, then reprices upward ~8–9%/wk from week 9 — while its fitted training
slope points down at −1.5%/wk. Weeks 0–8 contain no signal about that break, so
any change that improves Churchill's holdout number from weeks 0–8 alone is
fitting the answer. Two attempts to extrapolate harder both made it worse.

What is fixable is the operating assumption. The batch evaluation withholds all
three weeks at once; the real capability re-collects the panel weekly, so week 9
is in hand before week 10 is priced. `recalibrate()` is how that enters:

```python
model.fit(X_train, y_train, groups=brands)        # weeks 0-8
pred_9 = model.predict(X_9, groups=brands_9)      # nothing observed yet
model.recalibrate(X_9, y_9, groups=brands_9)      # week 9 outturn arrives
pred_10 = model.predict(X_10, groups=brands_10)   # now corrected
```

It re-reads each brand's level from the newly observed week and carries it
forward. It does not refit the point model, so shape and interactions are
untouched — only the level moves, which is the only thing a repricing changes.
It uses the median rather than the mean because a minimum premium pins 14–29% of
a brand's quotes and those rows do not move when the level does. Thin updates are
shrunk toward the market on the same `n/(n+k)` reasoning as the slope.

Measured over weeks 9–11: pooled MAPE 6.97% → 5.97%, within-10% 76.5% → 81.7%,
Churchill 14.24% → 10.72% and its bias −14.8% → −8.7%. Week 9 is bit-identical
under both regimes, which is the evidence the mechanism is not leaking the
answer. Never call it on rows you then score.

### The EBM-vs-GBM gap is a measurement, not a race

`additivity_gap()` reports the MdAPE difference between the additive and
unrestricted per-brand models. Near zero means that brand runs a clean
multiplicative rating table and the interpretable model costs you nothing. A
large gap means caps, collars, three-way terms or an optimisation layer the EBM
cannot represent — so the readable curves are a simplification, and you should
say so.

## Metrics that matter

Premium accuracy and **ranking** accuracy are different, and a model can be good
at one and poor at the other:

- `mdape` — median absolute % error. Median, because rating glitches are real
  and deliberately not cleaned.
- `cheapest_hit` — did we name the actual cheapest provider?
- `topN_overlap` — how much of the true cheapest-N did we find?
- `topN_price_err` — how wrong is the *price* of our top-N?

For a cheapest-5 product the last three are the ones anyone notices.

## Collecting real quotes

```python
from mktpricing.collect.session import CollectionSession, ChannelAlias

s = CollectionSession(
    session_id="2026-W35", collected_on=date.today(), identity_ref="me",
    risk_ids=["MY-HOUSE"], channels=["pcw_ctm", "direct"],
    brands=["Aviva", "AXA", "Admiral", "LV="],
    aliases=[ChannelAlias("pcw_ctm", "you+ctm@example.com", "CtM")],
)
s.write_template("data/raw/2026-W35.csv")   # fill in by hand, then:
rows, problems = read_session("data/raw/2026-W35.csv")
```

The template pre-fills the full (risk × channel × brand) grid on purpose: a
provider you could not get a quote from leaves a **visible empty row** instead of
vanishing. `coverage_report()` then separates *declined* (market signal) from
*missing* (collection gap). Treating those alike is the fastest way to bias a
top-5 list.

**Identity policy** — vary the contact details, keep the rating details real.
Per-channel email aliases are sensible data hygiene and are supported directly.
But name, DOB, address, claims history and property attributes must be genuine:
UK household pricing commonly involves identity and credit checks at quote, so a
fabricated identity returns the insurer's price for an *unresolvable applicant*,
not their price for the risk. That is the failure mode Defaqto cite for not using
fake profiles, and it would invalidate the accuracy measurement this repo exists
to produce.

**Scope limit, stated plainly.** One real person quoting one real property yields
**one risk profile**. That is enough to validate the pipeline and benchmark
cross-provider spread for that risk. It is *not* enough to train per-provider
models across risk space — that needs licensed vendor data or consented
panellists. See `docs/DESIGN.md`.

## Real postcodes

`features/geo.py` turns a UK postcode into the risk features the models use, so
predictions generalise to postcodes you have never quoted.

```python
from mktpricing.features.geo import GeoEnricher, default_sources, missing_files

print(missing_files("data/geo"))          # what to download, with URLs
e = GeoEnricher(default_sources("data/geo"))
enriched = e.enrich(risks)                # risks needs a `postcode` column
print(e.notes)                            # resolution rate per source
print(e.coverage(enriched))
```

Parsing needs no downloads and covers normalisation, validation and the
split into area / district / outcode / **sector**. Sector (`BS1 4`) is the
granularity most UK insurance rating areas use and the right join key for
property value.

| Feature | Source | Key | Free |
|---|---|---|---|
| `flood_band`, `flood_high_share` | Environment Agency postcode flood data | postcode | yes |
| `area_avg_value` | Land Registry Price Paid, median per sector | sector | yes |
| `imd_decile` | Indices of Deprivation 2019 | postcode | yes |
| `crime_index` | police.uk street-level, rank-normalised | LSOA | yes |
| *(bridge)* | ONS Postcode Directory, postcode → LSOA | postcode | yes |
| `subsidence_band` | BGS GeoSure | postcode | **no — licensed** |

The EA publishes flood likelihood **keyed by postcode**, so flood needs no GIS
or spatial join. That is what makes this practical without geopandas.

### Missing means missing

A geo feature that will not resolve is `NaN` with a `<col>_resolved` flag —
never a default. Substituting "flood band 0" for an unresolved postcode is a
confident wrong prediction that nothing downstream can distinguish from a real
one. Call the gate before training:

```python
from mktpricing.features.geo import check_ready_for_modelling
check_ready_for_modelling(enriched)   # raises, naming each thin column
```

Coverage is England and Wales for several sources. Scotland and Northern Ireland
need SIMD, NIMDM and SEPA equivalents; those postcodes are reported unresolved
rather than guessed at.

## Vendor extracts

`collect/vendor.py` maps a licensed CI or Defaqto extract onto the canonical
schema. It is **mapping-driven**: no real extract has been seen, so the built-in
`CI_SPEC` and `DEFAQTO_SPEC` column names are provisional and will be wrong in
detail. Correcting them is a config edit, never a change to the loader.

```bash
python scripts/inspect_vendor.py data/raw/sample.csv
```

profiles every column, guesses which canonical field it is, and prints a draft
`VendorSpec` to paste and correct. Then:

```bash
python scripts/inspect_vendor.py data/raw/sample.csv --spec ci --geo data/geo --write
```

maps, audits, geo-enriches, validates and writes canonical parquet for the POC.
`--geo` matters: an extract carries a postcode but not the risk features derived
from it, and `build_matrix` refuses risks without them rather than guessing.

```bash
python scripts/run_poc.py --data data/processed/quotes.parquet --risks data/processed/risks.parquet
```

Whether the rows came from CI, Defaqto or a notebook is invisible downstream —
except that `source` is retained, because accuracy differs by provenance and
mixing sources silently would hide that.

One thing a vendor extract can never supply is the **index basket**. `in_basket`
marks the properties you committed to re-quoting weekly; which risks those are is
your decision, not a fact about their file. So the runner falls back to the risks
present in every week — the same property a fixed basket has — and prints which
of the two it used. A derived basket is the weaker one: it is whatever the panel
happened to keep re-quoting, not a sample anyone designed. On a fully rotating
panel it reports **no index**, which is the honest answer.

### The audits are the point

Mapping columns is the easy half. A vendor extract can be clean, complete and
still be the wrong data, so `audit_extract()` checks for the failures that
otherwise surface as a good-looking model:

| Finding | Why it matters |
|---|---|
| `no_declines` | Extract omits declines → quotability is unlearnable and the simulated market price is biased **down**, because the cheap provider that would have refused still wins the cheapest-five |
| `truncated` | Only the cheapest N supplied → you learn each brand's price *conditional on being competitive*, which is not its price |
| `premium_basis` | Monthly, or IPT-exclusive → everything scales by ~12 or ~1.12 and every *relative* metric still looks fine |
| `rotating_panel` | Risks change between weeks → week-on-week movement confounds price with mix; index off a fixed basket only |
| `no_risk_attributes` | Premiums with no risk attached support benchmarking and nothing else — no per-provider model can be trained at any price |
| `duplicates`, `unmapped_brands` | Silent reweighting, and brands vanishing from the top-five |

Findings are ranked BLOCKER / WARN / INFO. Run it before the first fit, not
after the first odd result — the models will fit and score regardless.

Four facts **cannot be read off the file** and must come from the vendor:
premium basis, IPT treatment, whether declines are included, and whether the
extract is truncated. They are declared on the `VendorSpec` rather than
inferred, because a detector that is wrong once silently rescales everything.
The audit still sanity-checks the result, so a mis-declaration gets caught — as
a finding, not a guess.

Brand strings are resolved against `config/providers.yml` (`"Direct Line
Insurance"` → `Direct Line`, with the underwriter attached). Anything that does
not resolve is **reported, never guessed** — folding two brands together would
corrupt every per-brand number in the project.

### Testing the spec before a real extract arrives

```bash
python scripts/make_sample_extract.py
python scripts/inspect_vendor.py data/raw/sample_ci_extract.csv --spec ci
```

writes a **synthetic** extract in the shape a CI file plausibly has — dd/mm/yyyy
dates, `"Semi-Detached"` labels, `"Direct Line Insurance"` brand strings. It is
not vendor data and says so in a sidecar `.NOTE.txt`; what is real about it is
the *pricing*, since rows come from the synthetic market generator and carry
genuine multiplicative structure, declines and drift.

Each `--flavour` breaks exactly one thing, so you can watch a specific audit
finding fire:

| Flavour | Demonstrates |
|---|---|
| `clean` | loads with zero problems and no findings above INFO |
| `no-status` | `quoted` inferred from the premium, and said so |
| `no-declines` | `no_declines` |
| `monthly` | `premium_basis` — spec says annual, distribution says otherwise |
| `truncated` | `possible_truncation` |
| `rotating` | `rotating_panel` |
| `premiums-only` | `no_risk_attributes` |
| `messy` | unknown brand, unmapped property type, bad dates, duplicates |

`tests/test_vendor_sample.py` asserts the clean flavour loads without problems,
so the sample doubles as a guard against `CI_SPEC` and `DEFAULT_VALUE_MAPS`
drifting.

## Layout

```
config/providers.yml     brand -> underwriter -> channel; tiering for cadence
src/mktpricing/
  schema.py              canonical Quote and Risk records
  collect/session.py     manual collection templates and validation
  collect/synthetic.py   synthetic market with known ground truth
  collect/vendor.py      CI/Defaqto extract mapping + audits
  features/build.py      log-premium target, feature assembly
  features/geo.py        postcode -> flood, crime, deprivation, area value
  models/                registry + the eleven approaches + quotability
  models/drift.py        forward drift correction and weekly recalibration
  evaluate/              splits, metrics, the comparison harness
  market/simulate.py     Monte Carlo -> cheapest-N, weekly index
scripts/run_poc.py       end-to-end run
scripts/inspect_vendor.py  profile / map / audit / enrich a vendor extract
scripts/make_sample_extract.py  synthetic vendor-shaped extract, 8 flavours
docs/DESIGN.md           why it is built this way -- read before changing models
ui/index.html            self-contained results summary; open it in a browser
tests/                   invariants that are easy to break silently
```

## Reading the results

Look at **per-brand accuracy before the headline**. An aggregate MdAPE hides that
thin-tail brands are far worse than the majors — and it is the tail that decides
whether "model every provider" is achievable at all. `fallback_brands` on a
per-brand model tells you which brands were too thin to model individually and
got pooled instead.

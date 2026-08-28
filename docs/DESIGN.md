# Design notes

Why the code is shaped the way it is. Read this before changing the modelling
layer — several choices that look arbitrary are load-bearing.

---

## 1. The target is `log(premium)`

UK household rating is **multiplicative**: base rate × geo relativity × sum-insured
relativity × excess factor × … Taking logs turns that into an **additive**
structure, which is:

- exactly what a GAM/EBM represents natively, so each shape function reads
  directly as a rating relativity curve;
- what a GLM with a log link already assumes;
- variance-stabilising across a premium range spanning roughly £95 to £3,000.

Convert back only at the edges. `exp(mean of logs)` is a **geometric** mean, not
arithmetic — fine for an index, arguably preferable for robustness, but say so
rather than implying otherwise.

## 2. One model per brand, not one model with `brand` as a feature

A pooled model makes brand a main effect: a flat level shift. Real brands differ
in the **shape** of their flood, sum-insured and excess curves, not just their
level. Representing that in a pooled additive model would need an interaction
between brand and every other feature — which is precisely what an additive
model cannot do.

Per-brand models are cheap here and let you diff shape functions across brands
directly.

**Graceful degradation is mandatory.** `PerBrand.min_rows` (default 300) routes
thin brands to a pooled fallback and records which ones in `fallback_brands`.
With a realistic panel, the majors get individual models and the tail gets
pooled. Reporting the fallback list matters — a silently pooled brand looks like
a modelled one on the leaderboard.

## 3. Two parts, because providers decline

Nobody quotes every risk. Flood zone 3, non-standard construction, prior
subsidence, unoccupancy and very high sums insured all get declined or referred.

- `QuotabilityModel` → P(quote offered | risk)
- premium approach → E[log premium | quoted]

Skipping part one silently imputes quotes from providers who would have walked
away, biasing the market price **downward exactly where it is most
interesting**. `simulate_market` samples the quote decision first and prices only
the survivors.

This is also why `quoted=False` rows are kept with a null premium rather than
dropped. **A decline and an absence are different things**, and only one of them
is market signal. `session.coverage_report` exists to keep collection gaps from
masquerading as declines.

## 4. EBM *and* GBM — the gap is the measurement

Not a horse race. `additivity_gap()` reports the MdAPE difference between
`ebm_per_brand` and `gbm_per_brand`:

- **Near zero** → that brand runs a clean multiplicative rating table, and the
  interpretable model costs you nothing. Use the EBM and enjoy the curves.
- **Large** → real structure the EBM cannot represent: caps, collars, three-way
  terms, an ML optimisation layer. The readable curves are then a
  simplification, and you should describe them as one.

The synthetic generator deliberately plants a three-way term (flood × excess ×
detached) so this gap is non-zero and measurable on day one.

## 5. Never random-split

The same risk is quoted repeatedly across weeks. A random split puts
near-identical rows on both sides and reports an accuracy you will never see.

- **Temporal** — train weeks 1..k, test k+1. The operational question.
- **Spatial** — hold out entire postcode areas. The interpolation question, and
  always the weaker number. **If the two are close, the model is memorising
  location rather than learning risk.**

`rolling_windows()` gives a distribution of accuracy rather than one possibly
lucky week.

## 6. Rank accuracy is usually the real metric

A model can sit at 6% MdAPE and still order the cheapest five wrongly. For a
top-5 product that is the only thing anyone notices. `top_k_metrics` separates
three things people routinely conflate:

| Metric | Question |
|---|---|
| `cheapest_hit` | did we name the actual cheapest provider? |
| `topN_overlap` | how much of the true top-N did we find? |
| `topN_price_err` | how wrong is the *price* of our top-N? |

The last can be accurate while membership is wrong, because near-ties barely
move the mean. That is a feature of the market, not a bug in the metric.

## 7. Geography as risk features, never raw postcode

A postcode categorical cannot generalise to postcodes you never quoted, which
defeats the purpose. Join instead on flood band, crime, subsidence, deprivation
and average property value. You get a readable shape function per driver and the
ability to price anywhere in the UK.

Free UK sources: Environment Agency flood risk, police.uk crime, HM Land
Registry Price Paid, ONS Postcode Directory, IMD. BGS GeoSure (subsidence) is
licensed.

`features/geo.py` implements these joins. Three choices in it are worth stating.

**Postcode sector, not outcode, for property value.** An outcode spans a 4x
price range in a city, and property value drives sum insured and therefore
premium. Sector is also the granularity most UK rating areas already use.

**Highest occupied flood category, not the modal one.** The EA file counts
properties per likelihood band per postcode. A postcode that is 90% Very Low and
10% High is not a low-risk postcode to an underwriter — they price the tail.

**Missing is NaN with a flag, never a default.** This is the one that matters.
Filling an unresolved postcode with flood band 0 produces a confident wrong
prediction that no metric can distinguish from a correct one; the model fits, it
scores, and it is wrong. `check_ready_for_modelling()` is the gate, and the
right response to it failing is to obtain the data or drop the rows, never to
fill.

The EA publishes flood likelihood keyed by postcode, so no spatial join is
needed for the highest-value geo feature. Only crime is LSOA-keyed, which is the
sole reason ONSPD is a dependency at all.

## 8. Do not clean outliers

Rating glitches and tactical mispricing are **the signal**, not noise. The
synthetic generator plants rare large errors on purpose. Metrics use **median**
APE rather than mean so a handful of genuine outliers cannot dominate the
headline, which removes the usual excuse for winsorising.

This is also the open question for Defaqto — their published methodology removes
outliers and cleanses data. Ask whether pre-cleansing data is available.

## 9. Decompose, don't just predict

Price is not risk cost. On top sit conversion-elasticity pricing, aggregator
position targeting, channel effects, promotional incentives and outright errors.

```
log(price) = risk_structure + channel_effect + provider_level(t) + residual
```

Fit the risk structure, then read the **residual as the commercial layer**. A
brand whose residual drops 8% with no change in risk structure is buying market
share this week. That alert is worth more than the price level, and you cannot
see it without stripping the risk component first.

`week` is a feature for the same reason: its main effect absorbs level drift so
risk-factor shapes stay stable across refits — and that effect *is* the brand's
price index over time.

## 10. Incentives sit outside the premium

Cashback and voucher offers are recorded in their own fields. Folding them into
the premium corrupts the index, because the incentive is frequently
aggregator-funded and not part of the insurer's price at all.

## 11. Vendor extracts are audited, not just mapped

`collect/vendor.py` is mapping-driven because no real extract has been seen: the
built-in CI and Defaqto specs are provisional, and correcting them must be a
config edit rather than a code change.

The mapping is the easy half. Four facts about an extract **cannot be read off
the file** — premium basis (annual/monthly), IPT treatment, whether declines are
included, and whether it is truncated to the cheapest N. They are declared on
the `VendorSpec`, never inferred, because a detector that is wrong once silently
rescales the whole dataset while every *relative* metric still looks correct.
The audit then sanity-checks the outcome, so a mis-declaration is caught as a
finding rather than passing as a guess.

The audit exists because an extract can be clean, complete and still be unable
to answer the question this repo asks. Two findings are BLOCKERs for reasons
worth restating:

- **No declines.** Ignoring quotability biases the market price *down*, since
  the cheap provider that would have refused the risk still wins the
  cheapest-five. See decision 3.
- **No risk attributes.** Premiums with no sum insured, excess or property
  detail support benchmarking and nothing else. This is gate question 2 in the
  vendor evaluation, and no price makes an extract without them trainable.

`scripts/make_sample_extract.py` writes a synthetic extract in vendor shape so
the spec and every audit can be exercised before a licensed file exists. Its
clean flavour is asserted to load with zero problems, which makes it a guard
against the spec and the value maps drifting apart — the failure it prevents is
a renamed column silently becoming a column of nulls.

Brands resolve against `providers.yml` with unresolved names *reported* rather
than guessed — silently merging two brands corrupts every per-brand number, and
per-brand accuracy is the number that decides whether "model every provider" is
achievable.

---

## 12. The index basket is declared, or derived and labelled as such

`Risk.in_basket` marks the properties someone committed to re-quoting every
week. That is a collection decision, and a vendor extract cannot carry it —
which risks form *your* index is not a fact about their file. So on vendor data
the declared basket is always empty, and stage five of the POC would silently
produce nothing.

The comparable sub-panel is still recoverable: "quoted in every week" is exactly
the property a fixed basket has, and `market.simulate.common_risks()` returns
it. But a derived basket is weaker than a declared one — it is selected after
the fact, so it is whatever the vendor happened to keep re-quoting rather than a
sample anyone designed, and it will over-represent risks the panel finds easy to
quote. The runner therefore prints **which of the two it used** and how many
risks it holds. Substituting one for the other quietly would present an
after-the-fact selection as a designed sample.

If the panel rotates completely, no risk survives and the honest output is *no
index* — not an index computed over a changing set of risks, which measures
composition change and calls it price movement.

---

## 13. Parallelism is a memory decision, not a speed one

EBM bags via joblib's loky backend, which is *process* parallelism: every worker
is a fresh interpreter that re-imports numpy, pandas and interpret before doing
any work. Four bags is four interpreters' worth of committed memory, and the
per-brand approaches pay that once per brand. On a loaded machine the run dies
inside loky's manager thread — `OSError [WinError 1455] the paging file is too
small` — which is not a Python-level error any approach can catch and report, so
the whole run disappears and takes its buffered stdout with it.

`models.base.n_jobs()` is therefore a single run-wide budget, defaulting to
**1**, settable with `--jobs` or `MKTPRICING_JOBS`. Fits here are small — a few
thousand rows per brand — so bag-level parallelism was buying a modest speedup
for an interpreter per worker.

What is *not* acceptable is buying speed by cutting `outer_bags`, `max_rounds`
or `interactions` for a leaderboard sweep. Those change how well the EBM fits or
how noisy its curves are, and the EBM-vs-GBM gap is a headline measurement —
under-fitting the additive model would inflate the gap and read as "this brand
has structure the EBM cannot represent" when the truth was "we gave it less
compute". Run it slower instead.

---

## 14. Forward drift is a correction on top, never a re-parameterisation

A tree has no split beyond the largest `week` it was trained on, so every later
week reuses the final leaf and forward drift is predicted flat. Measured: one
Churchill risk, model trained on weeks 0–8, priced at £136.50 for week 8 and
£136.50 for weeks 9, 10 and 11 alike, while its holdout bias grew −9.3% →
−18.8% → −22.6% with `bias ≈ −mdape` — a pure level error that scales with
horizon and is invisible in an aggregate MdAPE because it only bites the brands
that were repricing.

The obvious fix is to re-express the model as `risk_shape(no week) +
level(brand, week)`, fitting the shape without `week` and reading the level off
residuals. **That is wrong, and measurably so.** It makes a strictly additive
claim about the level, and a minimum premium breaks it: a quote on its brand's
floor does not move when the brand's level moves, and 14–29% of each brand's
quotes sit on that floor. It cost ~2 points of MdAPE at a *one-week* horizon,
where there is almost no drift to correct — so the whole difference was damage.

`models/drift.py` therefore leaves the underlying model alone and adds only the
level *change* beyond the last trained week. In-window predictions are
bit-identical to the unwrapped approach, which a test asserts. Three further
things it gets right, each because the naive version got it wrong first:

- **The level comes from residuals, not weekly means.** A mean premium per
  brand-week confounds price with mix, and vendor panels rotate.
- **Residuals are out-of-fold.** In-sample residuals are biased small — the
  model has already fitted part of the level as risk. On a synthetic market with
  a known 2.00%/week drift, in-sample recovered 1.61%; out-of-fold recovered
  1.98%.
- **Whether to project a trend at all is validated, not assumed.** Insurance
  price levels wander more than they march, and for a walk the optimal forecast
  at every horizon is the last value. Projecting fitted slopes wholesale took
  MdAPE from 4.60% to 7.11%. The last few training weeks are now held out and
  the blend weight is chosen on them; on the sample data it selects 0 at a
  one-week horizon and 0.25 at three.

The general rule this encodes: a correction that can only act where the base
model was structurally incapable is safe. A re-parameterisation that changes
predictions everywhere has to be right everywhere, and this one was not.

---

## Known limitations

**Single-identity manual collection.** One real person quoting one real property
yields **one risk profile**. That validates the pipeline and benchmarks
cross-provider spread and top-5 accuracy for that risk. It cannot train
per-provider models across risk space — that needs licensed vendor data or
consented panellists. Do not let a clean POC run imply otherwise.

**Panel is not market.** Each comparison site carries a different panel, and
direct-only players (NFU Mutual, Hiscox) sit outside all of them. Full market
coverage is not achievable from PCW collection alone; `config/providers.yml`
records which brands are reachable on which channels so the gap is explicit.

**Underwriter attribution is unverified.** `config/providers.yml` records
brand → underwriter mappings that change and are not always publicly disclosed.
Verify before relying on them commercially.

**Forward drift is corrected, but a walk stays a walk.** `*_trend` approaches
(§14) remove the structural flat-line, and cannot regress the in-window fit. They
do not make the level predictable: on the sample data the gain is 4.60% → 4.48%
MdAPE at a three-week horizon and nothing at all at one week, because that
market's level is a random walk. Do not present a `*_trend` model as a solved
forecasting problem — read `drift_report()` and see how much of each brand's
slope survived the credibility and validation damping first.

**The synthetic generator is a caricature.** It reproduces the *classes* of
behaviour real engines show — multiplicative structure, thresholds, minimum
premiums, caps, declines, tactical drift — not any real insurer's actual rating.
Good accuracy on synthetic data proves the pipeline works, not that the
approach will hit those numbers on real quotes.

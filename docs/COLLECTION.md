# Collecting a first real sample

Everything in this repo currently runs on synthetic data. This is the plan for
the first real quotes: roughly 50 rows, collected by hand, good enough to check
the simulator against reality and to prove the collection path end to end.

Read `src/mktpricing/collect/session.py` first. Its identity policy is not
box-ticking, and this plan assumes it.

## Count journeys, not quotes

The unit of *cost* is the journey (10-20 minutes of form-filling). The unit of
*data* is the quote (one brand on one journey). One PCW journey returns 20-40
quotes at once, so "50 quotes" is about two journeys if you spend it carelessly,
and about eight if you spend it well.

Design around journeys. Once you are on a results page the extra rows are free,
so never stop at 50 out of tidiness -- capture what the page gives you.

## What 50 real quotes can and cannot buy

**Cannot:** train or validate a per-brand rating model. One real person quoting
one real property is ONE risk. Risk-space coverage needs licensed vendor data or
consented panellists, and no amount of manual collection substitutes.

**Can, and these are worth having:**

1. **Cross-channel spread per brand.** The same brand on four PCWs and direct.
   Published material does not answer this, and `market/simulate.py` models it
   in both directions, currently on faith.
2. **Panel composition.** Who actually appears, who declines, who is absent.
   Feeds the coverage gap that `scripts/start_collection.py` already reports.
3. **Level and dispersion.** Is the synthetic spread between cheapest and median
   roughly the real spread, or did the generator invent a market that is
   implausibly tight?
4. **Minimum-premium floors.** The generator asserts a point mass at the floor.
   Real data either shows one or does not.
5. **Drift**, if you do Phase 2 -- the one thing `models/drift.py` and
   `recalibrate()` exist for, and currently demonstrated only on invented moves.
6. **The pipeline itself.** Schema, reader, validation, coverage report, all
   exercised on data that did not come from us.

## Phase 1 -- breadth, one sitting, ~44 rows, ~2 hours

One risk (`MY-HOUSE`), one day, everything held constant.

| Journeys | Channel | Capture | Rows |
|---|---|---|---|
| 4 | Compare the Market, MoneySuperMarket, GoCompare, Confused | top 10 by rank | 40 |
| 4 | Direct, for four brands that appeared on the PCWs | own quote | 4 |

The four direct journeys are the highest-value rows in the set: a brand quoted
both on a PCW and direct, on the same day for the same risk, is a direct
measurement of the channel effect. Pick brands you actually saw ranked, so the
pair is comparable.

## Phase 2 -- time, three more weeks, ~14 rows/week

Repeat the widest-panel PCW plus the same four direct brands, weekly, same
weekday and similar time of day. Three repeats gives four points per brand,
which is the minimum a trend estimate can stand on -- `BrandTrend` shrinks
slopes by week count (`credibility_weeks=4.0`) precisely because fewer than that
is not evidence.

Do Phase 1 first and see how the transcription feels before committing to four
weeks of it.

## What you may vary, and what you may not

This is the constraint that shapes the whole design.

**Facts -- never vary.** Name, date of birth, address, claims and conviction
history, construction, occupancy, year built, bedrooms. Fabricating these is a
Fraud Act 2006 s.2 problem *and* it invalidates the measurement: an identity
that does not resolve returns the insurer's price for an unresolvable applicant,
not their price for your risk. The dishonest version is also the useless one.

**Choices -- may vary, but each variant is a NEW `risk_id`.** Voluntary excess,
cover type, sums insured, optional extras. `Risk` in `schema.py` carries
`voluntary_excess`, `policy_type` and both sums insured, so a different excess
is a different risk record (`MY-HOUSE-EXC500`), not a column on the quote.

**Contact details -- vary freely.** One email alias per channel. These never
reach the rating engine; they exist so four PCWs and a dozen insurers do not all
land in one inbox, and so you can see who sells your address on.

Do not spend Phase 1 on excess ladders. Channel and time are cheaper and answer
questions the simulator is actually guessing at.

## Traps that would quietly ruin the sample

1. **Top-N censoring.** Capturing the top 10 of a 35-quote page is fine for the
   cheapest-5 market price -- that IS the metric -- and fatal for per-brand
   accuracy, because you never observe the expensive brands. Record the total
   number of quotes returned and the last visible price, and do not use a
   censored page for per-brand work.
2. **The saved-quote cache.** Re-running the same risk on the same PCW often
   returns the stored quote rather than a fresh one. That reads as "nothing
   moved" and destroys Phase 2. Record the quote reference every time; if two
   weeks share a reference, you re-read a cache and the row is not an
   observation.
3. **Cover terms moving underneath you.** A premium is comparable only if
   excess, cover type and extras match. PCWs sometimes default accidental damage
   on. `compulsory_excess` and `accidental_damage` are columns for this reason;
   fill them on every row.
4. **Cashback and vouchers.** Never fold into the premium. There is a `cashback`
   column. A 50-pound voucher is an acquisition incentive, not a rating decision.
5. **Monthly vs annual.** Always record the annual price. Monthly carries APR,
   often 20-40%, and would show up as an enormous brand-level loading.
6. **Declined is not missing.** `quoted=n` is market signal; a blank row is a
   collection gap. The template is pre-filled so the difference stays visible.
7. **Brands are not independent.** Churchill, Privilege, Darwin and Direct Line
   are one group; Admiral, Diamond and Elephant likewise. Four correlated brands
   are not four observations, and a group-wide reprice will look like four
   confirmations of the same move.

## Mechanics

    python scripts/start_collection.py --risk MY-HOUSE --identity me \
        --channels pcw_ctm pcw_msm pcw_gocompare direct \
        --tier 1 --alias-domain you@example.com

Writes a pre-filled grid to `data/raw/<session>.csv`. Fill in `quoted` and
`premium` for every row; use `collector_note` for anything the columns do not
hold. Then:

    from mktpricing.collect.session import read_session
    rows, problems = read_session("data/raw/2026-W36.csv")

`data/raw/` is gitignored and stays that way. The quotes describe a real person
at a real address, and PCW output may attract database right. Publish derived
statistics only -- never the rows.

## Cheaper real data that is not a PCW

- **Your own renewal notice.** FCA rules require last year's premium to be shown
  alongside this year's. That is a free, real, year-on-year delta with known
  cover terms, for zero journeys.
- **Published price indices** (ABI, Consumer Intelligence). Real, free,
  aggregate only. Useless for per-brand work, genuinely useful for checking that
  the synthetic index sits at a plausible level and moves at a plausible rate.
- **A licensed vendor extract** (Consumer Intelligence, Pearson Ham, Insurance
  DataLab). The only route to per-brand, per-risk data at scale, which is why
  `collect/vendor.py` targets that shape. Licensed, priced accordingly, and
  governed by terms that override anything in this document.

## The boundary

Manual collection, in your own browser, at human pace, for your own risk, with
genuine rating details, is ordinary consumer use of a public service. That is
the whole of what this plan asks for.

Automating it is not. Scripted quote journeys breach PCW terms of use, engage
the UK database right in the results, and depending on how access is obtained
can reach the Computer Misuse Act 1990. There is no version of this repo that
scrapes a comparison site.

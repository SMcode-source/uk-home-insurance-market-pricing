# Handoffs

Session records for this project. Each is *what happened and why* — findings,
measurements, rejected alternatives, mistakes. They are historical and are never
edited to stay true.

**`../../OPEN-WORK.md` is what is still to do.** Where it and a handoff
disagree, OPEN-WORK wins.

This series is separate from the CapEmber estate's handoffs
(`~/Documents/capember cashflows/handoffs/`, currently at letter V). Different
project, different letters; nothing here belongs there.

## Current: `b`

| | |
|---|---|
| [b — The data decides the lineup, and the vendors are two](handoff-2026-09-06-b-the-data-decides-and-the-vendors-are-two.md) | 2026-09-06 |
| [a — The page cannot be regenerated](handoff-2026-08-29-a-the-page-cannot-be-regenerated.md) | 2026-08-29 |

`b` records the two sessions of 2026-09-06: that no free per-brand price feed
or legitimate quote API exists and `config/providers.yml` was a year out of
date on ownership; that the manual collection path never reached the models
and now does; that the harness ranks noise on a single property unless the
data is classified before fitting (`evaluate/adequacy.py`, `brand_last_level`);
that Pearson Ham's pricing business became Defaqto Market Pricing in 2026, so
there are two vendors and neither publishes a column name; and what was built
so a vendor file can be loaded and priced (best, top-5, spread) the day it
arrives. Section 7 lists what the sessions got wrong.

`a` records that the reproducibility machinery built in `dba13ee` cannot actually
reproduce the published page: the ten-approach leaderboard on the public site
survives only in `data/processed/poc_full2.log`, because later `--only` runs
overwrote every CSV that produced it. Also traces the full synthetic-data
provenance chain (nothing in this project has ever touched a real quote),
records the design reasoning behind `docs/COLLECTION.md`, identifies
`mc-fw-host` as the single process behind the machine's memory failures and the
fork errors they disguise themselves as, and states two things the session
itself got wrong.

## Required reading before changing models

1. `docs/DESIGN.md` §14–15 — forward drift, and why a structural break is a data
   problem rather than a modelling one.
2. Handoff `a` §1 — why an `--only` run must never share an `--out` with a full
   run.
3. `docs/DESIGN.md` §16–17 — why the data classifies itself before any fit, and
   why the observed market price's definitions are the design.
4. `docs/VENDOR-EXTRACTS.md` §4 — the questions a vendor must answer in writing
   before the first file is loaded.

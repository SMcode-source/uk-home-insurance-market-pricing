# Handoffs

Session records for this project. Each is *what happened and why* — findings,
measurements, rejected alternatives, mistakes. They are historical and are never
edited to stay true.

**`../../OPEN-WORK.md` is what is still to do.** Where it and a handoff
disagree, OPEN-WORK wins.

This series is separate from the CapEmber estate's handoffs
(`~/Documents/capember cashflows/handoffs/`, currently at letter V). Different
project, different letters; nothing here belongs there.

## Current: `a`

| | |
|---|---|
| [a — The page cannot be regenerated](handoff-2026-08-29-a-the-page-cannot-be-regenerated.md) | 2026-08-29 |

Records that the reproducibility machinery built in `dba13ee` cannot actually
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

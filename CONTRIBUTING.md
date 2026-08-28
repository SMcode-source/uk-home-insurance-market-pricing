# Working on this repository

Written for whoever picks this up next, including you in six months.

## Read `docs/DESIGN.md` before changing anything in `models/`

It is not background reading. It records the decisions that are non-obvious and
the approaches that were tried and **measured to be worse** — three separate
attempts at forward drift, in §14, each of which looked correct and lost. If you
are about to re-parameterise the drift correction or extrapolate a per-brand
slope harder, that section already contains the experiment and the number.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[models,dev]"   # Windows
pytest -q                                                # ~6 minutes, 201 tests
```

The model libraries are optional by design: an approach whose library is missing
is reported as **skipped**, never silently dropped. That is deliberate for local
work and dangerous in CI, so `.github/workflows/tests.yml` fails the build if
anything is skipped — a green run over a shrunken lineup is worse than a red one.

## Memory before speed

Fits are single-worker by default. EBM bags through joblib's `loky` backend, so
every worker is a whole extra interpreter, and a per-brand sweep pays that once
per brand. On a loaded machine this kills the run from inside a manager thread
that no approach can catch — the visible symptom is a truncated log, or LightGBM
emitting `Model format error, expect a tree here` because an allocation failed
part-way through its internal model round-trip. Neither looks like an OOM.

Raise it with `--jobs N` only where there is headroom. Do **not** buy speed by
cutting `outer_bags` or `max_rounds` instead: that under-fits the EBM and
inflates the additivity gap into a finding that is not there.

## Adding an approach

One class plus `@register`. The evaluation code never changes.

```python
@register
class MyApproach(Approach):
    name = "my_approach"
    blurb = "One line, shown in the lineup."
    requires = ("some_library",)

    def fit(self, X, y, groups=None): ...
    def predict(self, X, groups=None): ...
```

Update the approach table in `README.md` in the same commit, and make sure it is
actually scored in a POC run before it appears there as if it were part of the
lineup.

## Rules that exist because breaking them is silent

**Never commit quote or risk data.** `.gitignore` covers `data/raw`,
`data/interim`, `data/processed` and `data/geo`. The data derives from real
identities and, where vendor-sourced, is licensed. See `LICENSE`.

**Never score in-sample and never random-split.** Both holdouts answer different
questions and they disagree — on this project the winner flips between them. If
you add a metric, add it to both.

**Do not call `recalibrate()` on rows you then score.** It folds observed weeks
into the per-brand level, so scoring on them is scoring on the training set with
extra steps. `run_poc.py` asserts that the first holdout week is identical under
both regimes and aborts if it is not; if you change the rolling evaluation, keep
that assertion working rather than removing it.

**Generated files have exactly one source.** `ui/index.html` is authored as an
Artifact fragment; the public page is produced from it by `ui/build_public.py`.
Do not hand-edit the generated copy — CI rebuilds it and fails on drift.

**Label synthetic data as synthetic, durably.** Generated extracts get a sidecar
`.NOTE.txt`, and anything published carries the label on its face. The brand
names are real; the data is not, and a reader who misses that will draw
conclusions about real insurers from invented numbers.

## Commit style

Explain the decision, not the diff — git already has the diff. If a change is
the third attempt at something, say what the first two measured. The commit log
is the only place that record survives once the failed branches are gone.

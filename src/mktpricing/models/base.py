"""Model registry.

Every approach implements the same three-method interface, so the accuracy
harness can treat them interchangeably and adding a fourth approach is one file
plus one decorator -- never a change to the evaluation code.

Approaches declare their dependencies. An approach whose library is not
installed reports `available() -> False` with a reason and is skipped with a
visible note rather than crashing the run or, worse, being silently omitted from
the leaderboard. Silent omission reads as "we compared everything" when you
did not.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

import numpy as np

_REGISTRY: dict = {}

# ---------------------------------------------------------------------------
# parallelism budget
# ---------------------------------------------------------------------------

# Workers per fit. One by default, and that default is deliberate.
#
# EBM bags via joblib's loky backend, which is *process* parallelism: on Windows
# every worker is a fresh interpreter that re-imports numpy, pandas and
# interpret before it does any work. Four bags is therefore four interpreters'
# worth of committed memory, and the per-brand approaches pay it once per brand.
# On a box with other things running that is what kills the run -- here it was
# `OSError [WinError 1455] the paging file is too small`, raised inside loky's
# manager thread, which takes the whole process down without a Python-level
# error anyone can catch and report.
#
# The fits are small -- a few thousand rows per brand -- so bag-level
# parallelism was buying a modest speedup for an interpreter per worker. Raise
# it with `--jobs` (or MKTPRICING_JOBS) on a machine with headroom; leave it at
# one anywhere the run has to finish more than it has to finish fast.
_N_JOBS = max(1, int(os.environ.get("MKTPRICING_JOBS", "1")))


def n_jobs() -> int:
    """Workers each approach may use for one fit."""
    return _N_JOBS


def set_n_jobs(n: int) -> None:
    global _N_JOBS
    _N_JOBS = max(1, int(n))


class Approach:
    """Base class. Predicts log-premium; the harness converts back to GBP."""

    name: str = "unnamed"
    kind: str = "regressor"
    #: Short note on what this approach is for -- printed in the leaderboard.
    blurb: str = ""
    #: Import names this approach needs.
    requires: tuple = ()

    def __init__(self, **params):
        self.params = params
        self.model = None
        self._columns = None

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def available(cls):
        """(bool, reason). Checked before every run."""
        import importlib.util

        for mod in cls.requires:
            if importlib.util.find_spec(mod) is None:
                return False, f"needs `{mod}` (pip install {mod})"
        return True, ""

    def fit(self, X, y, groups=None):
        """Fit on log-premium.

        `groups` carries brand labels. Pooled approaches ignore it; per-brand
        approaches split on it. Passing it uniformly keeps the harness from
        needing to know which kind it is holding.
        """
        raise NotImplementedError

    def predict(self, X, groups=None):
        raise NotImplementedError

    # -- optional --------------------------------------------------------

    def shape_functions(self):
        """Per-feature contribution curves, where the approach exposes them.

        Only genuinely-additive approaches can answer this. Returning None is a
        truthful answer, not a gap -- it is why the EBM stays in the lineup even
        when a boosted tree beats it on error.
        """
        return None

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name}>"


def register(cls):
    """Decorator. Registers an approach under its `name`."""
    if cls.name in _REGISTRY:
        raise ValueError(f"duplicate approach name: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def all_approaches():
    return dict(_REGISTRY)


def available_approaches():
    out = {}
    for name, cls in _REGISTRY.items():
        ok, _ = cls.available()
        if ok:
            out[name] = cls
    return out


def unavailable_approaches():
    out = {}
    for name, cls in _REGISTRY.items():
        ok, why = cls.available()
        if not ok:
            out[name] = why
    return out


def get(name: str):
    if name not in _REGISTRY:
        raise KeyError(f"unknown approach {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]

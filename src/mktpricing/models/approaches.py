"""The approaches under test.

Ordered roughly by ambition. The point of keeping the weak ones in is that a
sophisticated model which cannot beat `brand_geomean` on your data has told you
something important -- usually that the signal you think you have is thinner
than you think.

Why several of these exist at all:

`ebm_per_brand`   The design recommendation. Log-premium is additive under a
                  multiplicative rating engine, so each shape function reads
                  directly as that brand's relativity curve. Interpretable
                  output a pricing analyst can act on.

`gbm_per_brand`   Unrestricted boosting. Should beat the EBM wherever the engine
                  has three-way structure, caps or an optimisation layer.
                  **The gap between these two is a measurement, not a horse
                  race**: it quantifies how much non-additive structure each
                  brand's pricing contains.

`*_pooled`        One model, brand as a feature. Cheap, and the only option for
                  brands too thin to model individually. Expect it to lose on
                  the majors and win on the tail.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Approach, n_jobs, register
from .drift import TrendAdjusted


# --------------------------------------------------------------------------
# baselines -- always available, no third-party dependencies
# --------------------------------------------------------------------------


@register
class GlobalGeoMean(Approach):
    name = "global_geomean"
    blurb = "Single geometric mean premium. The floor any model must clear."
    requires = ()

    def fit(self, X, y, groups=None):
        self._mu = float(np.mean(y))
        return self

    def predict(self, X, groups=None):
        return np.full(len(X), self._mu, dtype=float)


@register
class BrandGeoMean(Approach):
    name = "brand_geomean"
    blurb = "Per-brand geometric mean. Deceptively strong; beat this or stop."
    requires = ()

    def fit(self, X, y, groups=None):
        if groups is None:
            raise ValueError("brand_geomean needs `groups` (brand labels)")
        s = pd.Series(y, index=np.asarray(groups))
        self._by_brand = s.groupby(level=0).mean().to_dict()
        self._fallback = float(np.mean(y))
        return self

    def predict(self, X, groups=None):
        if groups is None:
            return np.full(len(X), self._fallback, dtype=float)
        return np.array(
            [self._by_brand.get(g, self._fallback) for g in np.asarray(groups)],
            dtype=float,
        )


@register
class RidgeLog(Approach):
    """Closed-form ridge on log-premium, implemented in numpy.

    Deliberately dependency-free so the harness always has one real model. It is
    also the honest linear benchmark: if a multiplicative engine is purely
    additive-in-log with no interactions, a linear fit on log-premium is close to
    the right model, and the tree approaches should barely beat it.
    """

    name = "ridge_log"
    blurb = "Log-linear ridge. The right shape for a purely multiplicative engine."
    requires = ()

    def __init__(self, alpha: float = 1.0, **kw):
        super().__init__(alpha=alpha, **kw)
        self.alpha = alpha

    def fit(self, X, y, groups=None):
        A = np.asarray(X, dtype=float)
        self._mean = A.mean(axis=0)
        self._scale = A.std(axis=0)
        self._scale[self._scale < 1e-12] = 1.0
        Z = (A - self._mean) / self._scale
        Z = np.hstack([np.ones((len(Z), 1)), Z])

        p = Z.shape[1]
        pen = self.alpha * np.eye(p)
        pen[0, 0] = 0.0  # never penalise the intercept
        self._beta = np.linalg.solve(Z.T @ Z + pen, Z.T @ np.asarray(y, dtype=float))
        return self

    def predict(self, X, groups=None):
        A = np.asarray(X, dtype=float)
        Z = (A - self._mean) / self._scale
        Z = np.hstack([np.ones((len(Z), 1)), Z])
        return Z @ self._beta


# --------------------------------------------------------------------------
# per-brand wrapper
# --------------------------------------------------------------------------


class PerBrand(Approach):
    """Fit one independent sub-model per brand.

    Brands differ in the *shape* of their curves, not only their level, so a
    pooled model would need an interaction between brand and every other feature
    to represent them -- which is exactly what an additive model cannot do.

    Brands with fewer than `min_rows` observations fall back to a pooled model
    fitted on everything. That threshold is the graceful-degradation rule the
    thin-tail problem demands: individual models for the majors, pooled for the
    rest, and the fallback is reported rather than hidden.
    """

    inner_cls = None
    min_rows = 300

    def __init__(self, min_rows: int | None = None, **kw):
        super().__init__(**kw)
        if min_rows is not None:
            self.min_rows = min_rows
        self._models = {}
        self._pooled = None
        self.fallback_brands = []

    @classmethod
    def available(cls):
        return cls.inner_cls.available()

    def fit(self, X, y, groups=None):
        if groups is None:
            raise ValueError(f"{self.name} needs `groups` (brand labels)")
        X = pd.DataFrame(X)
        g = np.asarray(groups)
        y = np.asarray(y, dtype=float)

        self._pooled = self.inner_cls(**self.params).fit(X, y, groups=g)
        self._models, self.fallback_brands = {}, []

        for brand in pd.unique(g):
            mask = g == brand
            if mask.sum() < self.min_rows:
                self.fallback_brands.append(str(brand))
                continue
            self._models[brand] = self.inner_cls(**self.params).fit(
                X.loc[mask], y[mask], groups=g[mask]
            )
        return self

    def predict(self, X, groups=None):
        X = pd.DataFrame(X)
        if groups is None:
            return self._pooled.predict(X)
        g = np.asarray(groups)
        out = np.empty(len(X), dtype=float)
        for brand in pd.unique(g):
            mask = g == brand
            model = self._models.get(brand, self._pooled)
            out[mask] = model.predict(X.loc[mask])
        return out

    def shape_functions(self):
        return {b: m.shape_functions() for b, m in self._models.items()}


# --------------------------------------------------------------------------
# EBM -- interpretable, additive + pairwise
# --------------------------------------------------------------------------


@register
class EBMPooled(Approach):
    name = "ebm_pooled"
    blurb = "Explainable Boosting Machine, brand as a feature. Readable curves."
    requires = ("interpret",)

    def fit(self, X, y, groups=None):
        from interpret.glassbox import ExplainableBoostingRegressor

        self._columns = list(pd.DataFrame(X).columns)
        # Bounded on purpose, in two directions. EBM's pairwise interaction
        # SEARCH is the expensive part -- unbounded it dominates the whole
        # comparison -- so `interactions` stays small when sweeping the
        # leaderboard and gets raised only when fitting one brand deliberately.
        # `n_jobs` is the memory bound: it defaults to the run-wide budget in
        # `base.n_jobs()` because each bag worker is a whole extra interpreter.
        self.model = ExplainableBoostingRegressor(
            interactions=self.params.get("interactions", 5),
            outer_bags=self.params.get("outer_bags", 4),
            max_rounds=self.params.get("max_rounds", 2000),
            n_jobs=self.params.get("n_jobs", n_jobs()),
            random_state=self.params.get("random_state", 0),
        )
        self.model.fit(pd.DataFrame(X), np.asarray(y, dtype=float))
        return self

    def predict(self, X, groups=None):
        return np.asarray(self.model.predict(pd.DataFrame(X)), dtype=float)

    def shape_functions(self):
        """Term contributions -- each one is a relativity curve for that factor."""
        if self.model is None:
            return None
        try:
            return {
                "term_names": list(self.model.term_names_),
                "term_scores": [np.asarray(s).tolist() for s in self.model.term_scores_],
            }
        except AttributeError:
            return None


@register
class EBMPerBrand(PerBrand):
    name = "ebm_per_brand"
    blurb = "One EBM per brand. The design recommendation: shapes differ by brand."
    requires = ("interpret",)
    inner_cls = EBMPooled


# --------------------------------------------------------------------------
# gradient boosting -- unrestricted, higher-order interactions
# --------------------------------------------------------------------------


@register
class LGBMPooled(Approach):
    name = "gbm_pooled"
    blurb = "LightGBM, brand as a feature. Unrestricted interaction order."
    requires = ("lightgbm",)

    def fit(self, X, y, groups=None):
        import lightgbm as lgb

        self.model = lgb.LGBMRegressor(
            n_estimators=self.params.get("n_estimators", 400),
            learning_rate=self.params.get("learning_rate", 0.05),
            num_leaves=self.params.get("num_leaves", 31),
            min_child_samples=self.params.get("min_child_samples", 20),
            verbose=-1,
            random_state=self.params.get("random_state", 0),
        )
        self.model.fit(pd.DataFrame(X), np.asarray(y, dtype=float))
        return self

    def predict(self, X, groups=None):
        return np.asarray(self.model.predict(pd.DataFrame(X)), dtype=float)


@register
class LGBMPerBrand(PerBrand):
    name = "gbm_per_brand"
    blurb = "One LightGBM per brand. Expect the best raw error of the lineup."
    requires = ("lightgbm",)
    inner_cls = LGBMPooled


@register
class CatBoostPooled(Approach):
    name = "catboost_pooled"
    blurb = "CatBoost, brand as a feature. Strong on high-cardinality categoricals."
    requires = ("catboost",)

    def fit(self, X, y, groups=None):
        from catboost import CatBoostRegressor

        self.model = CatBoostRegressor(
            iterations=self.params.get("iterations", 500),
            learning_rate=self.params.get("learning_rate", 0.05),
            depth=self.params.get("depth", 6),
            verbose=False,
            random_seed=self.params.get("random_state", 0),
        )
        self.model.fit(pd.DataFrame(X), np.asarray(y, dtype=float))
        return self

    def predict(self, X, groups=None):
        return np.asarray(self.model.predict(pd.DataFrame(X)), dtype=float)


@register
class RandomForest(Approach):
    name = "random_forest"
    blurb = "Random forest. Bagged rather than boosted; a useful sanity check."
    requires = ("sklearn",)

    def fit(self, X, y, groups=None):
        from sklearn.ensemble import RandomForestRegressor

        self.model = RandomForestRegressor(
            n_estimators=self.params.get("n_estimators", 150),
            min_samples_leaf=self.params.get("min_samples_leaf", 3),
            n_jobs=self.params.get("n_jobs", n_jobs()),
            random_state=self.params.get("random_state", 0),
        )
        self.model.fit(pd.DataFrame(X), np.asarray(y, dtype=float))
        return self

    def predict(self, X, groups=None):
        return np.asarray(self.model.predict(pd.DataFrame(X)), dtype=float)


# --------------------------------------------------------------------------
# drift-adjusted -- the same models, with forward price movement modelled
# --------------------------------------------------------------------------
#
# These exist as separate entries rather than as a change to the models above so
# the leaderboard can *measure* whether the correction helps, on both splits,
# instead of the fix being asserted. On the spatial split expect them to match
# their unwrapped twin almost exactly: that split holds out geography, not time,
# so there is no forward horizon and the correction is near zero by
# construction. On the temporal split expect a small gain that grows with the
# holdout length -- 4.60% -> 4.48% at three weeks on the sample data, and no
# difference at all at one week.
#
# They cost roughly `n_folds + 2` inner fits rather than one, because the level
# series needs its own week-agnostic model fitted out-of-fold. That is cheap for
# LightGBM and expensive for the EBM; see `drift.py`.


@register
class LGBMPerBrandTrend(TrendAdjusted):
    name = "gbm_per_brand_trend"
    blurb = "LightGBM per brand, plus an extrapolating per-brand price level."
    requires = ("lightgbm",)
    inner_cls = LGBMPerBrand


@register
class EBMPerBrandTrend(TrendAdjusted):
    name = "ebm_per_brand_trend"
    blurb = "EBM per brand, plus an extrapolating per-brand price level."
    requires = ("interpret",)
    inner_cls = EBMPerBrand


# --------------------------------------------------------------------------
# quotability -- part one of the two-part model
# --------------------------------------------------------------------------


class QuotabilityModel:
    """P(brand quotes | risk).

    Separate from the premium model on purpose. Providers decline flood zone 3,
    non-standard construction, prior subsidence, unoccupancy and very high sums
    insured. Predicting a premium for a brand that would have walked away biases
    the market price downward exactly where it is most interesting, so the top-5
    simulation samples this first and only prices the survivors.

    Falls back to per-brand empirical quote rates when sklearn is absent, which
    is crude but unbiased on average and keeps the pipeline runnable.
    """

    def __init__(self, **params):
        self.params = params
        self.model = None
        self._rates = {}
        self._global = 1.0
        self.backend = "empirical"

    def fit(self, X, quoted, groups=None):
        quoted = np.asarray(quoted).astype(int)
        self._global = float(quoted.mean())
        if groups is not None:
            s = pd.Series(quoted, index=np.asarray(groups))
            self._rates = s.groupby(level=0).mean().to_dict()

        import importlib.util

        if importlib.util.find_spec("sklearn") is not None:
            from sklearn.ensemble import HistGradientBoostingClassifier

            self.model = HistGradientBoostingClassifier(
                max_iter=self.params.get("max_iter", 200),
                random_state=self.params.get("random_state", 0),
            )
            self.model.fit(pd.DataFrame(X), quoted)
            self.backend = "sklearn"
        return self

    def predict_proba(self, X, groups=None):
        if self.model is not None:
            return np.asarray(self.model.predict_proba(pd.DataFrame(X))[:, 1], dtype=float)
        if groups is None:
            return np.full(len(X), self._global, dtype=float)
        return np.array(
            [self._rates.get(g, self._global) for g in np.asarray(groups)], dtype=float
        )
